"""Approve one exact saved proposal through the existing HTTP action service."""

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time

from .models import LeagueSnapshot


class DashboardActionError(Exception):
    """Expose only a fixed, safe message to the dashboard."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


class DashboardActions:
    """Keep consent short-lived and preserve the existing action policy."""

    def __init__(self, portfolio, *, credential_file=None, service_factory=None, clock=time.monotonic):
        self.portfolio = portfolio
        configured_credentials = credential_file or os.environ.get("FFM_ESPN_CREDENTIAL_FILE")
        self.credential_file = Path(configured_credentials).expanduser().resolve() if configured_credentials else None
        self.service_factory = service_factory
        self.clock = clock
        self.csrf_token = secrets.token_urlsafe(32)
        self._nonces = {}
        self._mutex = threading.Lock()
        self._team_locks = {entry.key: threading.Lock() for entry in portfolio.entries}

    def _material(self, team_key, proposal_id):
        try:
            if self.portfolio.demo:
                frame = self.portfolio._load(self.portfolio._select(team_key)[0])
                proposal = next((item for item in frame.proposals if item["id"] == proposal_id), None)
                if (proposal is None or proposal["status"] not in {"pending", "prepared"}
                        or proposal["mode"] != "review" or not proposal["is_current"]
                        or not frame.snapshot.source.synthetic or proposal["action"] != "set_lineup"
                        or (proposal["revision"], proposal["config_revision"]) != (frame.revision, frame.config_revision)):
                    raise ValueError
                from .policy import check_action
                decision = check_action(frame.snapshot, frame.config, proposal["action"], proposal["payload"])
                if decision["payload"] != proposal["payload"]:
                    raise ValueError
                fingerprint = hashlib.sha256(json.dumps(proposal, sort_keys=True, allow_nan=False).encode()).hexdigest()
                return {"proposal": deepcopy(proposal), "frame": frame, "snapshot": frame.snapshot,
                        "config": frame.config, "fingerprint": fingerprint}
            return self.portfolio._http_review_material(team_key, proposal_id)
        except (ValueError, KeyError, TypeError, StopIteration):
            raise DashboardActionError("This proposal is not available for review. Refresh the saved proposals.") from None

    def review(self, team_key, proposal_id):
        material = self._material(team_key, proposal_id)
        now = self.clock()
        nonce = secrets.token_urlsafe(32)
        with self._mutex:
            self._nonces = {key: value for key, value in self._nonces.items() if value["expires"] > now}
            if len(self._nonces) >= 256:
                raise DashboardActionError("Too many reviews are open. Wait two minutes before another review.")
            self._nonces[nonce] = {"team_key": team_key, "proposal_id": proposal_id,
                                   "fingerprint": material["fingerprint"], "expires": now + 120}
        proposal, snapshot, config = material["proposal"], material["snapshot"], material["config"]
        payload = proposal["payload"]
        player_ids = {payload.get(key) for key in ("player_id", "drop_id", "repair_player_id")}
        player_ids.update(payload.get("lineup", {}).values())
        player_ids.update(snapshot.own_team().lineup.values())
        return {"status": "review_required", "review_nonce": nonce, "expires_in_seconds": 120,
                "proposal": material["proposal"], "demo": self.portfolio.demo,
                "live_actions": not self.portfolio.demo,
                "players": [{"id": player.id, "name": player.name, "position": player.position}
                            for player in snapshot.players if player.id in player_ids],
                "current_lineup": dict(snapshot.own_team().lineup),
                "policy": {"mode": config.automation.mode_for(proposal["action"]),
                           "paused": config.automation.paused, "limits": config.limits.model_dump(mode="json")}}

    def submit(self, team_key, proposal_id, review_nonce, confirmation):
        if confirmation is not True:
            raise DashboardActionError("Confirm the exact reviewed proposal before submission.")
        with self._mutex:
            consent = self._nonces.pop(review_nonce, None)
        if (consent is None or consent["expires"] <= self.clock()
                or consent["team_key"] != team_key or consent["proposal_id"] != proposal_id):
            raise DashboardActionError("The review expired or was already used. Review the proposal again.")
        lock = self._team_locks.get(team_key)
        if lock is None or not lock.acquire(blocking=False):
            raise DashboardActionError("Another action is in progress for this team. Check its result first.")
        try:
            material = self._material(team_key, proposal_id)
            if not secrets.compare_digest(consent["fingerprint"], material["fingerprint"]):
                raise DashboardActionError("The proposal or team state changed. Review the current proposal.")
            if self.portfolio.demo:
                frame, proposal = material["frame"], material["proposal"]
                snapshot = frame.snapshot.model_copy(deep=True)
                snapshot.own_team().lineup = dict(proposal["payload"]["lineup"])
                frame.snapshot = LeagueSnapshot.model_validate(snapshot.model_dump())
                frame.revision += 1
                for saved in frame.proposals:
                    saved["is_current"] = False
                    if saved["id"] == proposal_id:
                        saved["status"] = "confirmed"
                frame.pending_count = sum(item["status"] in {"prepared", "pending"} for item in frame.proposals)
                return self._receipt(team_key, proposal_id, "confirmed", demo=True)
            return asyncio.run(self._submit_http(team_key, proposal_id, material))
        finally:
            lock.release()

    async def _submit_http(self, team_key, proposal_id, material):
        service = None
        submission_started = False
        try:
            factory = self.service_factory
            if factory is None:
                from .espn_service import ESPNService
                factory = ESPNService
            service = factory(material["data_dir"], transport="http", credential_file=self.credential_file, auto_rollover=False)
            if service.transport != "http" or getattr(service.browser, "transport", None) != "http":
                raise DashboardActionError("This proposal requires the ESPN HTTP transport.")
            snapshot = material["snapshot"]
            service.phase = "season"
            service.browser.week = snapshot.week
            # The adapter owns the same per-team lease as the season coordinator.
            # Direct adapter connection preserves the coordinator's saved connection.
            await service.browser.connect(league_id=snapshot.league_id, team_id=snapshot.team_id,
                                          season=snapshot.season, cdp_url=None, headless=True)
            current = self._material(team_key, proposal_id)
            if not secrets.compare_digest(material["fingerprint"], current["fingerprint"]):
                raise DashboardActionError("The proposal or team state changed. Review the current proposal.")
            submission_started = True
            result = await service.submit_season_action(proposal_id, confirmation=True)
            status = result.get("status")
            normalized = status if status in {"confirmed", "pending_waiver", "not_submitted", "rejected", "cancelled", "conflict"} else "unknown"
            return self._receipt(team_key, proposal_id, normalized)
        except DashboardActionError:
            raise
        except Exception as exc:
            # An unknown result never authorizes a repeated platform request.
            status = "unknown" if submission_started else "not_submitted"
            if isinstance(exc, ValueError) and str(exc) == "Another HTTP service owns this ESPN league and team session.":
                status = "busy"
            elif submission_started and service is not None:
                try:
                    if service.http_actions.get(proposal_id).get("status") == "pending":
                        status = "not_submitted"
                except Exception:
                    pass
            return self._receipt(team_key, proposal_id, status)
        finally:
            if service is not None:
                try:
                    # service.close() also updates shared worker status. Only release this adapter.
                    await service.browser.close()
                except Exception:
                    pass

    @staticmethod
    def _receipt(team_key, proposal_id, status, *, demo=False):
        messages = {
            "confirmed": "The exact change is confirmed by a fresh ESPN observation.",
            "pending_waiver": "ESPN accepted the waiver claim. Player ownership has not changed yet.",
            "unknown": "The result needs reconciliation. Do not submit this proposal again.",
            "not_submitted": "No submission was confirmed. Check the saved proposal and connection before another review.",
            "busy": "Another HTTP service owns this team session. Wait for its visit to finish before a new review.",
            "rejected": "ESPN rejected the transaction. The observed roster did not change.",
            "cancelled": "ESPN cancelled the transaction. The observed roster did not change.",
            "conflict": "The transaction and observed roster conflict. Check the saved evidence before another action.",
        }
        return {"status": status, "team_key": team_key, "proposal_id": proposal_id, "demo": demo,
                "live_actions": not demo, "retry_allowed": False,
                "message": "The fictional lineup changed in memory. No live team was changed." if demo else messages[status]}
