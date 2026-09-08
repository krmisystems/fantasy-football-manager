"""Server tests use isolated state and fictional browser observations."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import signal
from types import SimpleNamespace

from filelock import FileLock
import pytest

from fantasy_football_manager import espn_mcp, server
from fantasy_football_manager.espn_service import ESPNService
from test_espn_service import SeasonBrowserStub, season_observed


def make_manifest(tmp_path, *, mode="advisory", entries=2):
    value = {"browser_data_dir": "browser", "status_file": "health.json", "headless": True,
             "leagues": [{"league_id": str(101 + index), "team_id": "1", "season": 2026,
                          "week": index + 1, "data_dir": f"league-{index}", "mode": mode}
                         for index in range(entries)]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return server.load_manifest(path)


def snapshot_for(entry):
    value = season_observed().model_dump(mode="json")
    value.update(league_id=entry.league_id, team_id=entry.team_id, week=entry.week)
    value["teams"][0]["id"] = entry.team_id
    value["teams"][1]["id"] = "2"
    value["source"]["browser"].update(
        league_id=entry.league_id, team_id=entry.team_id,
        page_url=f"https://fantasy.espn.com/football/team?leagueId={entry.league_id}&teamId={entry.team_id}&scoringPeriodId={entry.week}")
    return season_observed().__class__.model_validate(value)


class ServerBrowser(SeasonBrowserStub):
    def __init__(self, entry, events, *, fail=None, coordinator=None):
        super().__init__()
        self.current = snapshot_for(entry)
        self.entry, self.events = entry, events
        self.week = entry.week
        self.fail, self.coordinator = fail, coordinator
        self.closed = False
        self.lease = None

    async def connect(self, **kwargs):
        self.events.append(("connect", self.entry.league_id, kwargs))
        if self.fail:
            raise ValueError(self.fail)
        if self.lease is not None:
            self.lease.acquire(timeout=0)
        return {"ready": True, "connected": True}

    async def observe(self, previous=None):
        if self.coordinator:
            self.coordinator.request_stop()
        return await super().observe(previous)

    async def close(self):
        self.events.append(("close", self.entry.league_id))
        if self.lease:
            self.lease.release()
        await super().close()


def factory_for(manifest, events, browsers, **kwargs):
    def factory(entry, root):
        assert root == Path(manifest.browser_data_dir)
        browser = ServerBrowser(entry, events, **kwargs)
        browser.lease = FileLock(root / "test-browser.lock")
        browsers.append(browser)
        return ESPNService(entry.data_dir, browser=browser)
    return factory


async def test_two_leagues_use_serial_browser_and_exact_context(tmp_path):
    manifest = make_manifest(tmp_path)
    events, browsers = [], []
    coordinator = server.SeasonCoordinator(manifest, service_factory=factory_for(manifest, events, browsers))
    result = await coordinator.run(once=True)
    assert [(item[0], item[1]) for item in events] == [("connect", "101"), ("close", "101"), ("connect", "102"), ("close", "102")]
    assert [browser.week for browser in browsers] == [1, 2]
    assert all(event[2]["headless"] is True for event in events if event[0] == "connect")
    assert result["cycles"] == 1 and result["status"] == "stopped"
    assert all(item["last_success_at"] and item["status"] == "monitoring_lineup" for item in result["leagues"])
    assert all(not browser.clicks and browser.closed for browser in browsers)
    for entry in manifest.leagues:
        snapshot = ESPNService(entry.data_dir, browser=SeasonBrowserStub()).manager.state()[0]
        assert (snapshot.league_id, snapshot.team_id, snapshot.week) == (entry.league_id, entry.team_id, entry.week)
    assert json.loads(Path(manifest.status_file).read_text())["cycles"] == 1


async def test_failed_league_does_not_block_other_league(tmp_path):
    manifest = make_manifest(tmp_path)
    events, browsers = [], []
    normal = factory_for(manifest, events, browsers)

    def factory(entry, root):
        service = normal(entry, root)
        if entry.league_id == "101":
            service.browser.fail = "League access denied."
        return service

    result = await server.SeasonCoordinator(manifest, service_factory=factory).run(once=True)
    assert result["leagues"][0]["status"] == "error"
    assert result["leagues"][1]["last_success_at"]
    assert all(browser.closed for browser in browsers)


@pytest.mark.parametrize("error, expected", [("Another manager process owns this ESPN browser profile.", "profile_busy"),
                                            ("Sign in to ESPN.", "authentication_required")])
async def test_shared_profile_or_auth_failure_stops_sweep(tmp_path, error, expected):
    manifest = make_manifest(tmp_path)
    events, browsers = [], []
    factory = factory_for(manifest, events, browsers, fail=error)
    result = await server.SeasonCoordinator(manifest, service_factory=factory).run(once=True)
    assert len(browsers) == 1 and browsers[0].closed
    assert result["leagues"][0]["status"] == expected
    assert result["leagues"][1]["status"] == "pending"


async def test_stop_during_observation_prevents_new_action_and_next_league(tmp_path):
    manifest = make_manifest(tmp_path, mode="existing")
    events, browsers = [], []
    coordinator = server.SeasonCoordinator(manifest)
    coordinator.service_factory = factory_for(manifest, events, browsers, coordinator=coordinator)
    result = await coordinator.run(once=True)
    assert len(browsers) == 1 and browsers[0].closed and not browsers[0].clicks
    assert result["status"] == "stopped"
    assert result["leagues"][1]["status"] == "pending"
    with FileLock(Path(manifest.browser_data_dir) / "espn-season-coordinator.lock", timeout=0):
        pass


async def test_saved_automatic_policy_can_apply_only_own_league_swap(tmp_path):
    manifest = make_manifest(tmp_path, mode="automatic")
    events, browsers = [], []
    normal = factory_for(manifest, events, browsers)

    def factory(entry, root):
        service = normal(entry, root)
        _, config, _, revision = service.manager.state()
        config.automation.preset = "bounded_automation"
        service.manager.update_config(config.model_dump(mode="json"), revision)
        return service

    result = await server.SeasonCoordinator(manifest, service_factory=factory).run(once=True)
    assert all(item["status"] == "confirmed" for item in result["leagues"])
    assert [len(browser.clicks) for browser in browsers] == [1, 1]
    for entry, browser in zip(manifest.leagues, browsers):
        permit = browser.clicks[0]
        assert (permit["league_id"], permit["team_id"], permit["week"]) == (entry.league_id, entry.team_id, entry.week)


async def test_pending_claim_survives_next_visit_without_repeat_click(tmp_path):
    manifest = make_manifest(tmp_path, mode="automatic", entries=1)
    events, browsers = [], []
    normal = factory_for(manifest, events, browsers)

    def factory(entry, root):
        service = normal(entry, root)
        _, config, _, revision = service.manager.state()
        if config.automation.preset != "bounded_automation":
            config.automation.preset = "bounded_automation"
            service.manager.update_config(config.model_dump(mode="json"), revision)
        service.browser.submit_error = RuntimeError("Fictional connection failed after authorization.")
        return service

    await server.SeasonCoordinator(manifest, service_factory=factory).run(once=True)
    result = await server.SeasonCoordinator(manifest, service_factory=factory).run(once=True)
    assert [len(browser.clicks) for browser in browsers] == [1, 0]
    assert result["leagues"][0]["status"] == "awaiting_verification"
    assert result["leagues"][0]["pending_count"] == 1


async def test_manifest_mode_cannot_elevate_saved_advisory_config(tmp_path):
    manifest = make_manifest(tmp_path, mode="automatic", entries=1)
    events, browsers = [], []
    result = await server.SeasonCoordinator(manifest, service_factory=factory_for(manifest, events, browsers)).run(once=True)
    assert result["leagues"][0]["status"] == "error"
    assert not any(event[0] == "connect" for event in events)


async def test_wrong_database_context_blocks_browser_and_preserves_state(tmp_path):
    manifest = make_manifest(tmp_path, entries=1)
    events, browsers = [], []
    normal = factory_for(manifest, events, browsers)

    def factory(entry, root):
        service = normal(entry, root)
        wrong = snapshot_for(entry.model_copy(update={"league_id": "999"})).model_dump(mode="json")
        service.manager.import_snapshot(wrong)
        return service

    result = await server.SeasonCoordinator(manifest, service_factory=factory).run(once=True)
    assert result["leagues"][0]["status"] == "error"
    assert not any(event[0] == "connect" for event in events)
    manager = ESPNService(manifest.leagues[0].data_dir, browser=SeasonBrowserStub()).manager
    assert manager.state()[0].league_id == "999"


async def test_cleanup_failure_stops_before_second_browser_and_releases_coordinator_lock(tmp_path):
    manifest = make_manifest(tmp_path)
    events, browsers = [], []
    normal = factory_for(manifest, events, browsers)

    def factory(entry, root):
        service = normal(entry, root)
        original = service.close
        async def close():
            await original()
            raise RuntimeError("Fictional browser cleanup failure.")
        service.close = close
        return service

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await server.SeasonCoordinator(manifest, service_factory=factory).run(once=True)
    assert len(browsers) == 1
    assert json.loads(Path(manifest.status_file).read_text())["status"] == "failed"
    with FileLock(Path(manifest.browser_data_dir) / "espn-season-coordinator.lock", timeout=0):
        pass


async def test_stop_interrupts_interval_wait_without_next_visit(tmp_path):
    manifest = make_manifest(tmp_path, entries=1)
    events, browsers = [], []
    coordinator = server.SeasonCoordinator(manifest, service_factory=factory_for(manifest, events, browsers))
    task = asyncio.create_task(coordinator.run())
    for _ in range(200):
        if coordinator.value["status"] == "waiting":
            break
        await asyncio.sleep(.01)
    assert coordinator.value["status"] == "waiting"
    coordinator.request_stop()
    await asyncio.wait_for(task, 1)
    assert coordinator.value["cycles"] == 1 and len(browsers) == 1


async def test_duplicate_coordinator_does_not_overwrite_live_health(tmp_path):
    manifest = make_manifest(tmp_path)
    Path(manifest.browser_data_dir).mkdir()
    Path(manifest.status_file).write_text("existing health", encoding="utf-8")
    with FileLock(Path(manifest.browser_data_dir) / "espn-season-coordinator.lock", timeout=0):
        with pytest.raises(ValueError, match="Another season coordinator"):
            await server.SeasonCoordinator(manifest).run(once=True)
    assert Path(manifest.status_file).read_text() == "existing health"


def test_manifest_rejects_drafts_duplicate_databases_and_missing_week(tmp_path):
    make_manifest(tmp_path)
    path = tmp_path / "manifest.json"
    original = json.loads(path.read_text())
    for change in (lambda data: data["leagues"][0].update(phase="draft"),
                   lambda data: data["leagues"][1].update(data_dir="league-0"),
                   lambda data: data["leagues"][0].pop("week")):
        value = json.loads(json.dumps(original))
        change(value)
        path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(ValueError):
            server.load_manifest(path)


def test_health_requires_successful_fresh_observation(tmp_path):
    coordinator = server.SeasonCoordinator(make_manifest(tmp_path, entries=1))
    value = coordinator.value
    value["status"] = "waiting"
    assert not server.health(value)["healthy"]
    value["leagues"][0].update(status="monitoring_lineup", last_success_at=server.utc_now(), snapshot_observed_at=server.utc_now())
    assert server.health(value)["healthy"]
    value["leagues"][0]["snapshot_observed_at"] = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    assert not server.health(value)["healthy"]
    value["leagues"][0].update(status="error", snapshot_observed_at=server.utc_now())
    assert not server.health(value)["healthy"]


def test_once_cli_returns_failure_when_observation_failed(tmp_path, monkeypatch):
    make_manifest(tmp_path, entries=1)
    async def run(args):
        coordinator = server.SeasonCoordinator(server.load_manifest(args.manifest))
        coordinator.value["status"] = "stopped"
        coordinator.value["leagues"][0]["status"] = "error"
        return coordinator.value
    monkeypatch.setattr(server, "_run_cli", run)
    monkeypatch.setattr("sys.argv", ["server", "--manifest", str(tmp_path / "manifest.json"), "--once"])
    with pytest.raises(SystemExit) as failure:
        server.main()
    assert failure.value.code == 1


@pytest.mark.parametrize("field", ["updated_at", "last_success_at", "snapshot_observed_at"])
def test_future_health_timestamps_are_unhealthy(tmp_path, field):
    value = server.SeasonCoordinator(make_manifest(tmp_path, entries=1)).value
    value["status"] = "waiting"
    value["leagues"][0].update(status="monitoring_lineup", last_success_at=server.utc_now(), snapshot_observed_at=server.utc_now())
    target = value if field == "updated_at" else value["leagues"][0]
    target[field] = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    assert not server.health(value)["healthy"]


@pytest.mark.parametrize("text", ["not JSON", "null", "{}", '{"updated_at":"no timestamp"}'])
def test_malformed_health_files_return_unhealthy(tmp_path, text):
    path = tmp_path / "health.json"
    path.write_text(text, encoding="utf-8")
    assert server.read_health(path) == {"healthy": False, "heartbeat_fresh": False, "observations_fresh": False, "status": "invalid_health"}


async def test_worker_stop_finishes_operation_then_closes(monkeypatch):
    events = []
    signal_callback = None

    @contextmanager
    def signals(callback):
        nonlocal signal_callback
        signal_callback = callback
        yield

    class Service:
        def __init__(self, data_dir):
            self.stop_event = asyncio.Event()
            self.task = None
        def saved_connection(self):
            return {}
        async def connect(self):
            events.append("connected")
        async def start(self, interval, trials):
            async def operation():
                events.append("authorized")
                signal_callback()
                await asyncio.sleep(0)
                events.append("reconciled")
                assert self.stop_event.is_set()
            self.task = asyncio.create_task(operation())
        async def close(self):
            assert self.task.done()
            events.append("closed")

    monkeypatch.setattr(server, "stop_signals", signals)
    monkeypatch.setattr(espn_mcp, "ESPNService", Service)
    await espn_mcp._worker(SimpleNamespace(data_dir="fictional", interval=2, trials=4))
    assert events == ["connected", "authorized", "reconciled", "closed"]


async def test_signal_handler_requests_stop_without_cancelling_task(monkeypatch):
    callbacks, restored, called = {}, [], []
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda name, callback: callbacks.__setitem__(name, callback))
    monkeypatch.setattr(loop, "remove_signal_handler", lambda name: restored.append(name))
    with server.stop_signals(lambda: called.append("stop")):
        callbacks[signal.SIGTERM]()
        await asyncio.sleep(0)
    assert called == ["stop"]
    assert set(restored) == {signal.SIGINT, signal.SIGTERM}
