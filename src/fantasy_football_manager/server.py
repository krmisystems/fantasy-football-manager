"""Serial season visits for an authenticated server browser.

The private manifest selects explicit league contexts. Saved manager configs
control actions. This module does not advance weeks or run draft automation.
"""

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
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
    leagues: list[LeagueEntry] = Field(min_length=1)


def load_manifest(path):
    path = Path(path).expanduser().resolve()
    manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    resolve = lambda value: str((path.parent / Path(value).expanduser()).resolve())
    manifest.browser_data_dir = resolve(manifest.browser_data_dir)
    manifest.status_file = resolve(manifest.status_file or "season-status.json")
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
    """Request a stop without cancelling an authorized browser operation."""
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


def health(value):
    """Require recent successful observations, not only a live process."""
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
        observations_ok = bool(enabled) and all(
            item.get("last_success_at") and age(item["last_success_at"]) >= 0
            and item.get("snapshot_observed_at")
            and 0 < item.get("max_age_seconds", 300) <= 86400
            and age(item["snapshot_observed_at"]) <= item.get("max_age_seconds", 300)
            and item.get("status") not in {"error", "profile_busy", "authentication_required", "awaiting_verification"}
            for item in enabled
        )
        return {"healthy": bool(active and heartbeat_ok and observations_ok), "heartbeat_fresh": heartbeat_ok,
                "observations_fresh": bool(observations_ok), "status": value.get("status")}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return {"healthy": False, "heartbeat_fresh": False, "observations_fresh": False, "status": "invalid_health"}


def read_health(path):
    try:
        return health(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeError):
        return {"healthy": False, "heartbeat_fresh": False, "observations_fresh": False, "status": "invalid_health"}


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
                                   "status": "pending" if item.enabled else "disabled"}
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
        return ESPNService(entry.data_dir)

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
        item.update(status="visiting", last_attempt_at=utc_now())
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
                item["status"] = "stopped"
                return False
            connected = await service.connect(entry.league_id, entry.team_id, entry.season,
                                              phase="season", week=entry.week, headless=self.manifest.headless)
            if not connected.get("ready"):
                raise ValueError(connected.get("error") or "The ESPN browser is not ready for this league.")
            async with service.operation:
                await service._sync()
                snapshot, config, revision, config_revision = service.manager.require_state()
                if (snapshot.league_id, snapshot.team_id, snapshot.season, snapshot.phase, snapshot.week) != entry.context():
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
                current, _, revision, config_revision = service.manager.require_state()
                item.update(status="stopped" if self.stop_event.is_set() else service.local_status,
                            last_success_at=utc_now(), snapshot_observed_at=current.source.observed_at.isoformat(),
                            max_age_seconds=config.limits.max_season_age_seconds, revision=revision,
                            config_revision=config_revision, pending_count=len(service._controller(current).pending()))
                item.pop("error", None)
        except Exception as exc:
            global_error = self._global_error(exc)
            item.update(status=global_error or "error", error=str(exc))
        finally:
            if service is not None:
                try:
                    result = await service.close()
                    if result.get("status") != "disconnected":
                        raise RuntimeError("The browser has not released its profile.")
                except Exception as exc:
                    # Never start a second adapter after uncertain browser cleanup.
                    item.update(status="error", error=f"Browser cleanup failed: {exc}")
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
    parser = argparse.ArgumentParser(description="Visit explicit ESPN season contexts with one server browser.")
    parser.add_argument("--manifest", required=True, help="Read a private JSON manifest. Restart after manifest changes.")
    parser.add_argument("--interval", type=float, default=60, help="Wait at least 60 seconds after each complete league sweep.")
    parser.add_argument("--once", action="store_true", help="Run one sweep, close Chrome, and exit.")
    parser.add_argument("--health", action="store_true", help="Read saved health without starting a browser.")
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
