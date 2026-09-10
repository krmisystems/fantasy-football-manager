"""Serial season visits through the configured ESPN transport.

The private manifest selects explicit league contexts. Saved manager configs
control actions. HTTP mode can follow verified scoring periods. Draft automation
uses the separate ESPN companion workflow.
"""

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import signal
import uuid

from filelock import FileLock, Timeout
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

from .espn_service import ESPNService
from .browser_lineup import lineup_equivalent, next_lineup_swap


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class LeagueEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    league_id: str
    team_id: str
    season: int = Field(ge=2020, le=2100)
    week: int = Field(ge=1, le=18)
    data_dir: str
    enabled: bool = True
    phase: Literal["season"] = "season"
    mode: Literal["existing", "advisory", "review", "automatic"] = "existing"

    @field_validator("league_id", "team_id")
    @classmethod
    def numeric_id(cls, value):
        if not value.isascii() or not value.isdigit():
            raise ValueError("Use numeric ESPN identifiers.")
        return value

    @field_validator("data_dir")
    @classmethod
    def nonempty_path(cls, value):
        if not value.strip():
            raise ValueError("Supply a manager data directory.")
        return value

    def context(self):
        return self.league_id, self.team_id, self.season, self.phase, self.week


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    browser_data_dir: str = Field(min_length=1)
    status_file: str | None = None
    headless: bool = True
    transport: Literal["http", "browser"] = "http"
    credential_file: str | None = None
    auto_rollover: bool = True
    leagues: list[LeagueEntry] = Field(min_length=1)


def load_manifest(path):
    path = Path(path).expanduser().resolve()
    manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    resolve = lambda value: str((path.parent / Path(value).expanduser()).resolve())
    manifest.browser_data_dir = resolve(manifest.browser_data_dir)
    manifest.status_file = resolve(manifest.status_file or "season-status.json")
    if manifest.credential_file is not None:
        manifest.credential_file = resolve(manifest.credential_file)
    directories, contexts = set(), set()
    for entry in manifest.leagues:
        entry.data_dir = resolve(entry.data_dir)
        if entry.data_dir in directories or entry.context()[:3] in contexts:
            raise ValueError("Each league needs a unique context and manager data directory.")
        directories.add(entry.data_dir)
        contexts.add(entry.context()[:3])
    if Path(manifest.status_file) == path:
        raise ValueError("The status file must differ from the manifest.")
    if Path(manifest.status_file).suffix.lower() != ".json":
        raise ValueError("Use a separate JSON file for coordinator health.")
    return manifest


@contextmanager
def stop_signals(callback):
    """Request a stop without cancelling an authorized platform operation."""
    loop = asyncio.get_running_loop()
    previous = {}
    for name in (signal.SIGINT, signal.SIGTERM):
        old = signal.getsignal(name)
        try:
            loop.add_signal_handler(name, callback)
        except (NotImplementedError, RuntimeError):
            try:
                signal.signal(name, lambda signum, frame: loop.call_soon_threadsafe(callback))
            except ValueError:
                continue  # Embedded callers can run outside the main thread.
        previous[name] = old
    try:
        yield
    finally:
        for name, old in previous.items():
            try:
                loop.remove_signal_handler(name)
            except NotImplementedError:
                pass
            signal.signal(name, old)


def write_status(path, value):
    """Replace private health data atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _not_ready(reason):
    return {"analysis": {"ready": False, "status": "not_run", "reasons": [reason]},
            "action": {"ready": False, "status": "blocked", "reasons": [reason], "scope": "set_lineup"}}


def lineup_readiness(snapshot, config, revision, config_revision, latest, *, pending_count=0, stopped=False):
    """Describe the last calculation and next automatic exchange. This does not authorize an action."""
    now = datetime.now(timezone.utc)
    reasons = []
    source = snapshot.source
    expires = source.observed_at + timedelta(seconds=config.limits.max_season_age_seconds)
    if not source.complete:
        reasons.append("source_incomplete")
    if not source.locks_verified:
        reasons.append("player_locks_unverified")
    if source.observed_at > now or expires < now:
        reasons.append("snapshot_not_fresh")
    if source.projections_observed_at is None:
        reasons.append("projection_timestamp_unknown")
    else:
        projection_expiry = source.projections_observed_at + timedelta(seconds=config.limits.max_projection_age_seconds)
        expires = min(expires, projection_expiry)
        if source.projections_observed_at > now or projection_expiry < now:
            reasons.append("projections_not_fresh")
    result = latest.get("result", {}) if isinstance(latest, dict) else {}
    if not latest or latest.get("phase") != "season":
        reasons.append("analysis_not_run")
    else:
        if (latest.get("revision"), latest.get("config_revision")) != (revision, config_revision):
            reasons.append("analysis_input_changed")
        if result.get("status") != "ok":
            reasons.append("analysis_incomplete")
        if result.get("blocking_missing_projections", result.get("missing_projections")):
            reasons.append("weekly_projections_missing")
    mode, paused = config.automation.mode_for("set_lineup"), config.automation.paused
    hold = "coordinator_stopped" if stopped else "intentional_paused" if paused else "pending_claim" if pending_count else None
    if hold and not latest:
        reasons.append(hold)
    analysis = {"ready": not reasons, "status": "ready" if not reasons else "not_run" if not latest else "incomplete",
                "reasons": reasons, "evaluated_at": now.isoformat(), "expires_at": expires.isoformat(),
                "revision": latest.get("revision") if latest else None,
                "config_revision": latest.get("config_revision") if latest else None,
                "result_status": result.get("status"), "errors": result.get("errors", []),
                "missing_projections": result.get("missing_projections", [])}
    action = {"ready": False, "status": "blocked", "reasons": [], "scope": "set_lineup",
              "revision": revision, "config_revision": config_revision}
    if hold:
        action["reasons"] = [hold]
    elif reasons:
        action["reasons"] = ["analysis_not_ready"]
    elif mode != "automatic":
        action.update(status="approval_required" if mode == "review" else "disabled", reasons=[f"mode_{mode}"])
    elif lineup_equivalent(snapshot, snapshot.own_team().lineup, result["lineup"]):
        action.update(status="not_needed", reasons=["lineup_current"])
    else:
        legal = False
        if snapshot.source.provider == "espn_http":
            from .policy import check_action
            try:
                decision = check_action(snapshot, config, "set_lineup", {"lineup": result["lineup"]}, execution_scope="espn_http")
                legal = not decision["requires_confirmation"]
            except ValueError:
                pass
        else:
            legal = next_lineup_swap(snapshot, config, result["lineup"]) is not None
        if legal:
            action.update(ready=True, status="ready")
        else:
            action.update(status="not_needed", reasons=["no_admissible_lineup_exchange"])
    return {"analysis": analysis, "action": action}


def _invalid_health():
    return {"healthy": False, "process_active": False, "heartbeat_fresh": False, "observations_fresh": False,
            "analysis_ready": False, "action_ready": False, "action_ready_count": 0, "team_count": 0,
            "degraded": True, "reasons": ["invalid_health"], "leagues": [], "status": "invalid_health"}


def health(value):
    """Separate reported process activity, fresh observations, and current lineup readiness.

    Old status files remain readable, but missing readiness cannot imply success.
    Analysis readiness requires every enabled team. Action readiness requires at least one team.
    A saved status file does not prove that its process still exists.
    """
    try:
        now = datetime.now(timezone.utc)
        def age(text):
            timestamp = datetime.fromisoformat(text)
            if timestamp.tzinfo is None:
                raise ValueError("Health timestamps must include a UTC offset.")
            seconds = (now - timestamp).total_seconds()
            if seconds < 0:
                raise ValueError("Health timestamps cannot be in the future.")
            return seconds
        interval = value["interval_seconds"]
        if type(interval) not in {int, float} or not math.isfinite(interval) or interval < 60:
            raise ValueError("The health interval is invalid.")
        active = value.get("status") in {"visiting", "waiting", "running"}
        heartbeat_ok = age(value["updated_at"]) <= max(180, interval * 2)
        if not isinstance(value["leagues"], list) or any(
            not isinstance(item, dict) or type(item.get("enabled")) is not bool
            or not isinstance(item.get("status"), str) for item in value["leagues"]
        ):
            raise ValueError("The health league entries are invalid.")
        enabled = [item for item in value["leagues"] if item["enabled"]]
        summaries = []
        for index, item in enumerate(value["leagues"]):
            if not item["enabled"]:
                continue
            limit = item.get("max_age_seconds", 300)
            observed = bool(item.get("last_success_at") and age(item["last_success_at"]) >= 0
                            and item.get("snapshot_observed_at") and type(limit) in {int, float}
                            and math.isfinite(limit) and 0 < limit <= 86400
                            and age(item["snapshot_observed_at"]) <= limit
                            and item["status"] not in {"error", "profile_busy", "authentication_required"})
            analysis, action = item.get("analysis", {}), item.get("action", {})
            if not isinstance(analysis, dict) or not isinstance(action, dict):
                raise ValueError("The saved readiness entries are invalid.")
            reasons = list(analysis.get("reasons", ["readiness_unknown"]))
            current = bool(observed and analysis.get("ready") is True and analysis.get("status") == "ready"
                           and analysis.get("reasons") == [] and analysis.get("result_status") == "ok"
                           and type(item.get("revision")) is int and type(item.get("config_revision")) is int
                           and (analysis.get("revision"), analysis.get("config_revision"))
                           == (item["revision"], item["config_revision"])
                           and analysis.get("evaluated_at") and age(analysis["evaluated_at"]) <= limit
                           and analysis.get("expires_at")
                           and datetime.fromisoformat(analysis["expires_at"]) >= now)
            if not observed:
                reasons.append("observation_not_fresh")
            if not current and not reasons:
                reasons.append("analysis_not_current")
            if item.get("paused") is True:
                reasons.append("intentional_paused")
            pending = item.get("pending_count")
            if type(pending) is not int or pending < 0:
                reasons.append("pending_claims_unknown")
            elif pending:
                reasons.append("pending_claim")
            actionable = bool(active and heartbeat_ok and current and item.get("paused") is False
                              and type(pending) is int and pending == 0 and item.get("mode") == "automatic"
                              and action.get("ready") is True and action.get("status") == "ready"
                              and action.get("reasons") == [] and action.get("scope") == "set_lineup"
                              and (action.get("revision"), action.get("config_revision"))
                              == (item["revision"], item["config_revision"]))
            summaries.append({"league_index": index, "observations_fresh": observed, "analysis_ready": current,
                              "action_ready": actionable, "reasons": list(dict.fromkeys(reasons))})
        observations_ok = bool(enabled) and all(item["observations_fresh"] for item in summaries)
        analysis_ok = bool(enabled) and all(item["analysis_ready"] for item in summaries)
        reasons = []
        if not active:
            reasons.append("process_inactive")
        if not heartbeat_ok:
            reasons.append("heartbeat_stale")
        if not enabled:
            reasons.append("no_enabled_teams")
        for item in summaries:
            reasons.extend(item["reasons"])
        healthy = bool(active and heartbeat_ok and observations_ok and analysis_ok and not reasons)
        ready_count = sum(item["action_ready"] for item in summaries)
        return {"healthy": healthy, "process_active": active, "heartbeat_fresh": heartbeat_ok,
                "observations_fresh": observations_ok, "analysis_ready": analysis_ok,
                "action_ready": bool(ready_count), "action_ready_count": ready_count, "team_count": len(enabled),
                "degraded": not healthy, "reasons": list(dict.fromkeys(reasons)), "leagues": summaries,
                "status": value.get("status")}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return _invalid_health()


def read_health(path):
    try:
        return health(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeError):
        return _invalid_health()


class SeasonCoordinator:
    def __init__(self, manifest, interval=60, *, service_factory=None):
        if isinstance(interval, bool) or not math.isfinite(interval) or interval < 60:
            raise ValueError("Use a season interval of at least 60 seconds.")
        self.manifest = manifest
        self.interval = interval
        self.service_factory = service_factory
        self.stop_event = asyncio.Event()
        self.active_service = None
        self.cleanup_error = None
        self.value = {"schema_version": 1, "pid": os.getpid(), "status": "starting", "started_at": utc_now(),
                      "updated_at": utc_now(), "interval_seconds": interval, "cycles": 0,
                      "leagues": [{"league_id": item.league_id, "team_id": item.team_id, "season": item.season,
                                   "week": item.week, "enabled": item.enabled,
                                   "status": "pending" if item.enabled else "disabled",
                                   **_not_ready("visit_pending" if item.enabled else "team_disabled")}
                                  for item in manifest.leagues]}

    def save(self, status=None):
        if status:
            self.value["status"] = status
        self.value["updated_at"] = utc_now()
        self.value["health"] = health(self.value)
        write_status(self.manifest.status_file, self.value)

    def request_stop(self):
        self.stop_event.set()
        if self.active_service is not None:
            self.active_service.stop_event.set()

    def _service(self, entry):
        if self.service_factory:
            return self.service_factory(entry, Path(self.manifest.browser_data_dir))
        # The process owns one browser root. Set it before constructing adapters.
        return ESPNService(entry.data_dir, transport=self.manifest.transport,
                           credential_file=self.manifest.credential_file, auto_rollover=self.manifest.auto_rollover)

    @staticmethod
    def _global_error(error):
        message = str(error).lower()
        if isinstance(error, Timeout) or "owns this espn browser profile" in message:
            return "profile_busy"
        if any(term in message for term in ("sign in", "sign-in", "log in", "login", "authentication", "unauthorized", "http 401")):
            return "authentication_required"
        return None

    async def visit(self, index, entry):
        item = self.value["leagues"][index]
        item.update(status="visiting", last_attempt_at=utc_now(), **_not_ready("visit_in_progress"))
        self.value["active_league_index"] = index
        self.save("visiting")
        service = None
        global_error = None
        try:
            service = self._service(entry)
            self.active_service = service
            old, config, _, _ = service.manager.state()
            if old is not None and (old.league_id, old.team_id, old.season) != entry.context()[:3]:
                raise ValueError("The manager database belongs to another league context.")
            mode = config.automation.mode_for("set_lineup")
            if entry.mode != "existing" and mode != entry.mode:
                raise ValueError("The saved lineup mode differs from the manifest mode. No config was changed.")
            item.update(mode=mode, paused=config.automation.paused)
            if self.stop_event.is_set():
                item.update(status="stopped", **_not_ready("coordinator_stopped"))
                return False
            requested_week = max(entry.week, old.week) if self.manifest.auto_rollover and old is not None else entry.week
            connected = await service.connect(entry.league_id, entry.team_id, entry.season,
                                              phase="season", week=requested_week, headless=self.manifest.headless)
            if not connected.get("ready"):
                raise ValueError(connected.get("error") or "The ESPN browser is not ready for this league.")
            async with service.operation:
                await service._sync()
                snapshot, config, revision, config_revision = service.manager.require_state()
                actual_context = (snapshot.league_id, snapshot.team_id, snapshot.season, snapshot.phase, snapshot.week)
                expected_context = entry.context()
                if self.manifest.transport == "http" and self.manifest.auto_rollover and snapshot.source.http is not None:
                    expected_context = (*entry.context()[:4], snapshot.source.http.transaction_period)
                    if service._controller(snapshot).pending(include_waivers=True):
                        expected_context = (*entry.context()[:4], requested_week)
                if actual_context != expected_context:
                    raise ValueError("The observed league context differs from the manifest.")
                if entry.mode != "existing" and config.automation.mode_for("set_lineup") != entry.mode:
                    raise ValueError("The saved lineup mode changed during observation.")
                if self.stop_event.is_set():
                    service.stop_event.set()
                    item["status"] = "stopped"
                elif config.automation.paused:
                    service._save_status("paused")
                elif service._controller(snapshot).pending():
                    service._save_status("awaiting_verification")
                else:
                    await service._season_step(snapshot, config, revision, config_revision)
                current, config, revision, config_revision = service.manager.require_state()
                item.update(status="stopped" if self.stop_event.is_set() else service.local_status,
                            last_success_at=utc_now(), snapshot_observed_at=current.source.observed_at.isoformat(),
                            max_age_seconds=config.limits.max_season_age_seconds, revision=revision,
                            config_revision=config_revision, pending_count=len(service._controller(current).pending()),
                            mode=config.automation.mode_for("set_lineup"), paused=config.automation.paused)
                item.update(lineup_readiness(current, config, revision, config_revision, service.latest,
                                             pending_count=item["pending_count"], stopped=self.stop_event.is_set()))
                item.pop("error", None)
        except Exception as exc:
            global_error = self._global_error(exc)
            item.update(status=global_error or "error", error=str(exc), **_not_ready(global_error or "visit_failed"))
        finally:
            if service is not None:
                try:
                    result = await service.close()
                    if result.get("status") != "disconnected":
                        raise RuntimeError("The browser has not released its profile.")
                except Exception as exc:
                    # Never start a second adapter after uncertain browser cleanup.
                    item.update(status="error", error=f"Browser cleanup failed: {exc}", **_not_ready("browser_cleanup_failed"))
                    self.cleanup_error = str(exc)
                    self.request_stop()
                    global_error = "profile_busy"
                finally:
                    self.active_service = None
            self.value.pop("active_league_index", None)
            self.save()
        print(json.dumps({"event": "season_visit", "league_index": index, "status": item["status"]}), flush=True)
        return global_error is None

    async def _heartbeat(self):
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), 15)
            except asyncio.TimeoutError:
                self.save()

    async def run(self, *, once=False):
        root = Path(self.manifest.browser_data_dir)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lease = FileLock(root / "espn-season-coordinator.lock")
        try:
            lease.acquire(timeout=0)
        except Timeout as exc:
            # Do not overwrite the active coordinator's health file.
            raise ValueError("Another season coordinator owns this browser root.") from exc
        previous_root = os.environ.get("FFM_BROWSER_DATA_DIR")
        os.environ["FFM_BROWSER_DATA_DIR"] = str(root)
        heartbeat = asyncio.create_task(self._heartbeat())
        failed = False
        try:
            self.save("running")
            while not self.stop_event.is_set():
                for index, entry in enumerate(self.manifest.leagues):
                    if self.stop_event.is_set():
                        break
                    if entry.enabled and not await self.visit(index, entry):
                        break
                if self.cleanup_error is not None:
                    raise RuntimeError("Browser cleanup failed. The coordinator stopped before another visit.")
                self.value["cycles"] += 1
                if once:
                    break
                self.save("waiting")
                try:
                    await asyncio.wait_for(self.stop_event.wait(), self.interval)
                except asyncio.TimeoutError:
                    pass
        except BaseException:
            failed = True
            raise
        finally:
            self.request_stop()
            try:
                await heartbeat
                self.save("failed" if failed else "stopped")
            finally:
                lease.release()
                if previous_root is None:
                    os.environ.pop("FFM_BROWSER_DATA_DIR", None)
                else:
                    os.environ["FFM_BROWSER_DATA_DIR"] = previous_root
        return self.value


async def _run_cli(args):
    coordinator = SeasonCoordinator(load_manifest(args.manifest), args.interval)
    with stop_signals(coordinator.request_stop):
        result = await coordinator.run(once=args.once)
    return result


def main():
    parser = argparse.ArgumentParser(description="Visit ESPN season contexts through HTTP or the optional browser transport.")
    parser.add_argument("--manifest", required=True, help="Read a private JSON manifest. Restart after manifest changes.")
    parser.add_argument("--interval", type=float, default=60, help="Wait at least 60 seconds after each complete league sweep.")
    parser.add_argument("--once", action="store_true", help="Run one sweep, close the transport, and exit.")
    parser.add_argument("--health", action="store_true", help="Read saved health without connecting to ESPN.")
    args = parser.parse_args()
    if args.health:
        manifest = load_manifest(args.manifest)
        result = read_health(manifest.status_file)
        print(json.dumps(result))
        raise SystemExit(0 if result["healthy"] else 1)
    result = asyncio.run(_run_cli(args))
    if args.once and not health(result)["observations_fresh"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
