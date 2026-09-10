"""Observe and submit ESPN season transactions through authenticated HTTP."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
from filelock import FileLock, Timeout

from .espn_http_actions import transaction_body
from .espn_http_client import ESPNHTTPClient, league_url
from .espn_http_data import normalize_espn_http, season_pro_teams_read_url
from .espn_season_data import season_player_read_headers, season_player_read_url
from .models import Budget
from .policy import require


class ESPNPreflightError(ValueError):
    """The operation failed before the HTTP transaction request began."""


def _safe_transactions(payload, snapshot):
    require(isinstance(payload, dict) and payload.get("id") == int(snapshot.league_id)
            and payload.get("seasonId") == snapshot.season and payload.get("scoringPeriodId") == snapshot.week,
            "The transaction history belongs to another context.")
    rows = payload.get("transactions", [])
    require(isinstance(rows, list), "The ESPN transaction history is invalid.")
    result = []
    for row in rows:
        require(isinstance(row, dict), "The ESPN transaction history is invalid.")
        if row.get("teamId") != int(snapshot.team_id):
            continue
        safe = {key: row[key] for key in ("id", "type", "status", "isPending", "scoringPeriodId", "bidAmount",
                                         "teamId", "proposedDate", "processDate") if key in row}
        require(isinstance(row.get("items"), list), "A transaction has no verified item list.")
        safe["items"] = [{key: item[key] for key in ("playerId", "type", "fromTeamId", "toTeamId",
                                                    "fromLineupSlotId", "toLineupSlotId") if key in item}
                         for item in row["items"]]
        result.append(safe)
    return result


def _history_budget(snapshot, league, transactions):
    """Use history only when it reconciles with ESPN's completed season counters."""
    team = next(team for team in league["teams"] if str(team["id"]) == snapshot.team_id)
    counters = team.get("transactionCounter", {})
    http = snapshot.source.http
    if not http.pending_transactions_known or http.uses_faab is None:
        return None
    completed = [row for row in transactions if row.get("status") == "EXECUTED"]
    acquisitions = [row for row in completed if any(item.get("type") == "ADD" for item in row["items"])]
    drops = [row for row in completed if any(item.get("type") == "DROP" for item in row["items"])]
    if (type(counters.get("acquisitions")) is not int or len(acquisitions) != counters["acquisitions"]
            or type(counters.get("drops")) is not int or len(drops) != counters["drops"]):
        return None
    if any(type(row.get("scoringPeriodId")) is not int or not 1 <= row["scoringPeriodId"] <= 18
           for row in acquisitions + drops):
        return None
    claims = [row for row in http.pending_transactions if row.get("type") == "WAIVER"]
    if any(row.get("isPending") is not True or row.get("status") != "PENDING" for row in claims):
        return None
    moves = {row["id"] for row in acquisitions + drops if row["scoringPeriodId"] == snapshot.week}
    if http.uses_faab:
        if any(type(row.get("bidAmount")) is not int or row["bidAmount"] < 0 for row in acquisitions + claims):
            return None
        spent = sum(row["bidAmount"] for row in acquisitions)
        total = league.get("settings", {}).get("acquisitionSettings", {}).get("acquisitionBudget")
        if (spent != counters.get("acquisitionBudgetSpent") or type(total) is not int or total < spent):
            return None
        spent_week = sum(row["bidAmount"] for row in acquisitions if row["scoringPeriodId"] == snapshot.week)
        pending = sum(row["bidAmount"] for row in claims)
        balance = total - spent
    else:
        balance = spent = spent_week = pending = 0
    return Budget(balance=balance, spent_week=spent_week, spent_season=spent,
                  roster_moves_week=len(moves), pending_moves=len(claims), pending_amount=pending)


class ESPNHTTPSeason:
    transport = "http"

    def __init__(self, data_dir, *, week=1, credential_file=None, client=None):
        self.week = week
        self.data_dir = Path(data_dir)
        self.client = client or ESPNHTTPClient(credential_file or os.environ.get("FFM_ESPN_CREDENTIAL_FILE")
                                              or self.data_dir / "espn-http-credentials.json")
        self.context = None
        self.permit_validator = None
        credential_path = credential_file or os.environ.get("FFM_ESPN_CREDENTIAL_FILE") or getattr(self.client, "credential_file", None)
        self.lease_root = Path(credential_path).expanduser().resolve().parent if credential_path else self.data_dir.resolve()
        self._lease = None

    def status(self):
        return {"connected": self.context is not None, "transport": "http", "browser_started": False,
                "week": self.week, "authenticated": self.context is not None}

    async def connect(self, league_id, team_id, season, cdp_url=None, headless=False):
        require(cdp_url is None, "HTTP mode does not accept a browser debugging URL.")
        from .espn_data import _numeric_id, _scope
        league_id, season = _scope(league_id, season)
        team_id = _numeric_id(team_id, "Team ID")
        if self._lease is not None:
            await self.close()
        self.lease_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lease = FileLock(self.lease_root / f"espn-http-{league_id}-{team_id}.lock")
        try:
            lease.acquire(timeout=0)
        except Timeout:
            raise ValueError("Another HTTP service owns this ESPN league and team session.") from None
        self._lease = lease
        self.context = (str(league_id), str(team_id), season)
        try:
            snapshot = await self.observe()
        except BaseException:
            await self.close()
            raise
        return {"ready": True, "transport": "http", "browser_started": False,
                "week": snapshot.week, "transaction_period": snapshot.source.http.transaction_period}

    async def current_period(self):
        require(self.context is not None, "Connect the ESPN HTTP session first.")
        league, _, season = self.context
        payload = await self.client.request(league_url(league, season) + "?view=mStatus")
        require(isinstance(payload, dict) and payload.get("id") == int(league) and payload.get("seasonId") == season,
                "The period response belongs to another league or season.")
        status = payload.get("status", {})
        period, final = status.get("transactionScoringPeriod"), status.get("finalScoringPeriod")
        require(type(period) is int and type(final) is int and 1 <= period <= final <= 18,
                "ESPN has no supported current transaction period.")
        return period

    async def observe(self, previous=None):
        require(self.context is not None, "Connect the ESPN HTTP session first.")
        league, team, season = self.context
        base = league_url(league, season)
        league_request = (base + "?view=mSettings&view=mTeam&view=mRoster&view=mStatus&view=mDraftDetail"
                          f"&view=mPendingTransactions&scoringPeriodId={self.week}")
        player_request = season_player_read_url(league, season, self.week)
        roster_request = base + f"?forTeamId={team}&scoringPeriodId={self.week}&view=mRoster"
        pro_teams_request = season_pro_teams_read_url(season)
        # Read the complete roster before its targeted lock observation. A mismatch rejects a race.
        league_payload = await self.client.request(league_request)
        players = await self.client.request(player_request, headers=season_player_read_headers(season))
        projection_time = datetime.now(timezone.utc)
        pro_teams = await self.client.request(pro_teams_request)
        roster = await self.client.request(roster_request)
        observed = datetime.now(timezone.utc)
        result = normalize_espn_http(league_payload, players, roster, team_id=team, week=self.week,
                                    member_id=self.client.credentials()["SWID"], observed_at=observed,
                                    projections_observed_at=projection_time, player_response_url=player_request,
                                    roster_response_url=roster_request, league_response_url=league_request,
                                    pro_teams_payload=pro_teams, pro_teams_response_url=pro_teams_request)
        history = await self.client.request(base + f"?view=mTransactions2&scoringPeriodId={self.week}")
        transactions = _safe_transactions(history, result)
        result.source.http.recent_transactions = transactions
        result.budget = _history_budget(result, league_payload, transactions)
        return result

    async def preflight(self, permit):
        observed = await self.observe()
        if self.permit_validator:
            require(self.permit_validator(permit, observed.model_dump(mode="json")) is True,
                    "The HTTP service did not authorize this request.")
        else:
            raise ValueError("The HTTP service has no permit validator.")
        return observed

    async def submit_action(self, permit):
        try:
            observed = await self.preflight(permit)
            body = transaction_body(observed, permit["action"], permit["payload"], self.client.credentials()["SWID"])
            url = league_url(observed.league_id, observed.season, write=True) + "/transactions/"
        except Exception as exc:
            raise ESPNPreflightError(str(exc)) from None
        response = await self.client.request(url, payload=body)
        return {"transport": "http", "response": response}

    async def close(self):
        self.context = None
        if self._lease is not None:
            self._lease.release()
            self._lease = None
        return {"status": "disconnected", "transport": "http", "browser_started": False}
