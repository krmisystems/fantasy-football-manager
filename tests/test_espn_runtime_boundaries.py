"""Test process and HTTP boundaries with fictional data and temporary files.

Child processes use Python and SQLite only. These tests never launch Chrome,
contact ESPN, read a saved browser profile, or submit a platform action.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from filelock import FileLock
import pytest

from fantasy_football_manager import espn_browser, espn_data
from fantasy_football_manager.browser_draft import BrowserDraft
from fantasy_football_manager.espn_service import ESPNService
from fantasy_football_manager.models import ManagerConfig
from fantasy_football_manager.store import Manager


URL = "https://fantasy.espn.com/football/draft?leagueId=123&teamId=11&seasonId=2026"


def fictional_payloads(selected=()):
    picks = [{"overallPickNumber": n, "roundId": (n - 1) // 2 + 1,
              "roundPickNumber": (n - 1) % 2 + 1, "teamId": [11, 22, 22, 11][n - 1],
              "playerId": pid} for n, pid in enumerate(selected, 1)]
    league = {
        "id": 123, "seasonId": 2026,
        "settings": {"size": 2,
            "draftSettings": {"type": "SNAKE", "pickOrder": [11, 22]},
            "rosterSettings": {"lineupSlotCounts": {"2": 1, "20": 1},
                               "positionLimits": {str(pid): 2 for pid in [1, 2, 3, 4, 5, 16]}},
            "scoringSettings": {"scoringType": "H2H_POINTS", "scoringItems": [{"statId": 24, "points": .1}]}},
        "teams": [{"id": 11, "name": "Fictional North"}, {"id": 22, "name": "Fictional South"}],
        "draftDetail": {"drafted": False, "picks": picks},
    }
    players = {"players": [{"id": pid, "onTeamId": 0, "player": {
        "id": pid, "fullName": f"Fictional Runner {pid}", "defaultPositionId": 2,
        "eligibleSlots": [2, 20, 23], "active": True,
        "ownership": {"averageDraftPosition": pid - 100},
        "stats": [{"seasonId": 2026, "statSourceId": 1, "statSplitTypeId": 0,
                   "scoringPeriodId": 0, "stats": {"24": 1000}}]}}
        for pid in range(101, 105)]}
    return league, players


def fictional_snapshot(selected=()):
    league, players = fictional_payloads(selected)
    return espn_data.normalize_espn_draft(
        league, players, team_id="11", page_url=URL,
        visible_text=f"ON THE CLOCK: PICK {len(selected) + 1}\nENABLE AUTOPICK",
        observed_at=datetime.now(timezone.utc), player_response_url=espn_data.player_read_url(123, 2026))


def child_process(script, *args, env=None):
    return subprocess.Popen(
        [sys.executable, "-u", "-c", textwrap.dedent(script), *map(str, args)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def await_marker(process, marker):
    deadline = time.monotonic() + 10
    while not marker.exists():
        if process.poll() is not None:
            output, error = process.communicate(timeout=2)
            pytest.fail(f"Fictional child exited before readiness: {output} {error}")
        if time.monotonic() >= deadline:
            pytest.fail("Fictional child did not become ready within ten seconds.")
        time.sleep(.02)


def finish_child(process):
    if process.poll() is None:
        process.terminate()
    try:
        return process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_mode", ["graceful", "abrupt"])
async def test_separate_process_profile_lease_blocks_browser_then_releases(tmp_path, monkeypatch, exit_mode):
    marker = tmp_path / "lock-ready"
    process = child_process("""
        from filelock import FileLock
        from pathlib import Path
        import os, sys
        root = Path(sys.argv[1])
        with FileLock(root / 'espn-browser.lock'):
            (root / 'lock-ready').write_text('ready', encoding='utf-8')
            command = sys.stdin.readline().strip()
            if command == 'crash':
                os._exit(23)
    """, tmp_path)
    browser = espn_browser.ESPNBrowser(tmp_path)
    start = AsyncMock(side_effect=RuntimeError("Fictional startup stops before Chrome"))
    monkeypatch.setattr(espn_browser, "_start_playwright", start)
    try:
        await_marker(process, marker)
        with pytest.raises(ValueError, match="Another manager process"):
            await browser.connect("123", "11", 2026)
        start.assert_not_awaited()
        if exit_mode == "graceful":
            output, error = process.communicate("release\n", timeout=5)
            assert process.returncode == 0, output + error
        else:
            output, error = process.communicate("crash\n", timeout=5)
            assert process.returncode == 23, output + error
        with pytest.raises(RuntimeError, match="stops before Chrome"):
            await browser.connect("123", "11", 2026)
        start.assert_awaited_once()
        assert browser.status()["connected"] is False
        with FileLock(tmp_path / "espn-browser.lock", timeout=0):
            pass
    finally:
        finish_child(process)
        await browser.close()


def configured_manager(path):
    manager = Manager(path)
    manager.import_snapshot(fictional_snapshot().model_dump(mode="json"))
    manager.update_config(ManagerConfig(automation={"preset": "review"}).model_dump(mode="json"), 0)
    return manager


@pytest.mark.parametrize("actual_player, expected", [(101, "confirmed"), (102, "not_selected")])
def test_claim_survives_claimant_exit_and_cannot_grant_another_click(tmp_path, actual_player, expected):
    configured_manager(tmp_path)
    report = tmp_path / "claim.json"
    process = child_process("""
        from pathlib import Path
        import json, os, sys
        from fantasy_football_manager.store import Manager
        from fantasy_football_manager.browser_draft import BrowserDraft
        draft = BrowserDraft(Manager(sys.argv[1]))
        proposal = draft.prepare('101')
        permit = draft.authorize(proposal['proposal_id'], confirmation=True)
        Path(sys.argv[2]).write_text(json.dumps(permit), encoding='utf-8')
        os._exit(0)
    """, tmp_path, report)
    try:
        output, error = process.communicate(timeout=10)
        assert process.returncode == 0, output + error
    finally:
        finish_child(process)
    permit = json.loads(report.read_text(encoding="utf-8"))
    assert permit["should_click"] is True
    reopened = Manager(tmp_path)
    draft = BrowserDraft(reopened)
    assert len(draft.pending()) == 1 and not draft.pending()[0]["should_click"]
    assert not draft.authorize(permit["proposal_id"], confirmation=True)["should_click"]
    with pytest.raises(ValueError, match="awaits verification"):
        draft.prepare("102")
    unchanged = draft.reconcile(permit["proposal_id"], fictional_snapshot().model_dump(mode="json"))
    assert unchanged["status"] == "awaiting_verification" and not unchanged["should_click"]
    result = draft.reconcile(permit["proposal_id"], fictional_snapshot([actual_player]).model_dump(mode="json"))
    assert result["status"] == expected and draft.pending() == []
    assert not draft.authorize(permit["proposal_id"], confirmation=True)["should_click"]
    assert reopened.state()[0].picks[0].player_id == str(actual_player)
    with reopened.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM audit WHERE event='browser_draft_authorized'").fetchone()[0] == 1


def test_two_processes_racing_authorization_grant_exactly_one_click(tmp_path):
    draft = BrowserDraft(configured_manager(tmp_path))
    proposal = draft.prepare("101")
    script = """
        import json, sys, time
        from pathlib import Path
        from fantasy_football_manager.store import Manager
        from fantasy_football_manager.browser_draft import BrowserDraft
        draft = BrowserDraft(Manager(sys.argv[1]))
        root = Path(sys.argv[1])
        (root / f'ready-{sys.argv[3]}').write_text('ready', encoding='utf-8')
        deadline = time.monotonic() + 10
        while not (root / 'release-claims').exists():
            if time.monotonic() >= deadline:
                raise RuntimeError('Fictional claim barrier timed out')
            time.sleep(.005)
        print(json.dumps(draft.authorize(sys.argv[2], confirmation=True)), flush=True)
    """
    processes = [child_process(script, tmp_path, proposal["proposal_id"], index) for index in range(2)]
    results = []
    try:
        for index, process in enumerate(processes):
            await_marker(process, tmp_path / f"ready-{index}")
        (tmp_path / "release-claims").write_text("ready", encoding="utf-8")
        for process in processes:
            output, error = process.communicate(timeout=10)
            assert process.returncode == 0, output + error
            results.append(json.loads(output))
    finally:
        for process in processes:
            finish_child(process)
    assert sum(result["should_click"] for result in results) == 1
    assert {result["status"] for result in results} == {"awaiting_verification"}
    assert len(draft.pending()) == 1


class FakeResponse:
    def __init__(self, payload=None, status=200, json_error=None):
        self.payload, self.status, self.json_error = payload, status, json_error
        self.ok = 200 <= status < 300
        self.disposed = False

    async def json(self):
        if self.json_error:
            raise self.json_error
        return self.payload

    async def dispose(self):
        self.disposed = True


class FakeRequest:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def request_browser(path, responses):
    browser = espn_browser.ESPNBrowser(path)
    browser._scope = ("123", "11", 2026)
    request = FakeRequest(responses)
    browser._context = SimpleNamespace(request=request)
    return browser, request


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 302, 307])
async def test_http_errors_and_redirects_release_response_then_allow_fresh_read(tmp_path, status):
    failed, recovered = FakeResponse(status=status), FakeResponse({"players": []})
    browser, request = request_browser(tmp_path, [failed, recovered])
    url = espn_data.player_read_url(123, 2026)
    with pytest.raises(ValueError, match=f"HTTP {status}"):
        await browser._read_json(url)
    assert failed.disposed
    assert await browser._read_json(url) == {"players": []}
    assert recovered.disposed
    assert len(request.calls) == 2 and all(call[1]["max_redirects"] == 0 for call in request.calls)
    assert all(call[0] == url for call in request.calls)


@pytest.mark.asyncio
async def test_non_json_response_is_released_and_does_not_prevent_recovery(tmp_path):
    failed = FakeResponse(json_error=json.JSONDecodeError("Fictional login page", "<html>", 0))
    browser, _ = request_browser(tmp_path, [failed, FakeResponse({"players": []})])
    url = espn_data.player_read_url(123, 2026)
    with pytest.raises(json.JSONDecodeError):
        await browser._read_json(url)
    assert failed.disposed
    assert await browser._read_json(url) == {"players": []}


@pytest.mark.asyncio
async def test_read_timeout_does_not_retry_implicitly_and_next_observation_can_read(tmp_path):
    browser, request = request_browser(tmp_path, [asyncio.TimeoutError("Fictional read timeout"), FakeResponse({"players": []})])
    url = espn_data.player_read_url(123, 2026)
    with pytest.raises(asyncio.TimeoutError, match="Fictional read timeout"):
        await browser._read_json(url)
    assert len(request.calls) == 1
    assert await browser._read_json(url) == {"players": []}
    assert len(request.calls) == 2


@pytest.mark.asyncio
async def test_failed_player_download_does_not_create_cache_or_claim_ready(tmp_path, monkeypatch):
    league, players = fictional_payloads()
    failed = FakeResponse(status=403)
    browser, request = request_browser(tmp_path, [FakeResponse(league), failed, FakeResponse(league), FakeResponse(players)])
    monkeypatch.setattr(browser, "_verify_scope", AsyncMock(return_value="11"))
    monkeypatch.setattr(browser, "_autopick", AsyncMock(return_value=False))
    body = SimpleNamespace(inner_text=AsyncMock(return_value="ON THE CLOCK: PICK 1\nENABLE AUTOPICK"))
    browser._page = SimpleNamespace(url=URL, locator=lambda selector: body)
    with pytest.raises(ValueError, match="HTTP 403"):
        await browser.observe()
    assert failed.disposed and browser.status()["ready"] is False
    assert browser._players_payload is browser._projections_at is browser._player_response_url is None
    snapshot = await browser.observe()
    assert browser.status()["ready"] is True and browser.status()["error"] is None
    assert snapshot.source.browser.current_pick == 1 and snapshot.picks == []
    assert len(request.calls) == 4


@pytest.mark.asyncio
async def test_worker_acknowledgement_uses_launch_id_and_reports_interpreter_pid(tmp_path):
    service = ESPNService(tmp_path)
    launch_id = uuid.uuid4().hex
    service._save_status("monitoring", pid=20202, launch_id=launch_id)
    result = await service._await_worker_start(SimpleNamespace(pid=10101, poll=lambda: None),
                                              timeout=0, launch_id=launch_id)
    assert result["startup_acknowledged"] is True
    assert result["pid"] == 20202 and result["launcher_pid"] == 10101
    assert result["launch_id"] == launch_id


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", ["other_launch", "stale", "future"])
async def test_other_or_stale_heartbeat_cannot_acknowledge_new_worker(tmp_path, evidence):
    service = ESPNService(tmp_path)
    launch_id = uuid.uuid4().hex
    timestamp = datetime.now(timezone.utc)
    if evidence == "stale":
        timestamp -= timedelta(seconds=120)
    elif evidence == "future":
        timestamp += timedelta(seconds=120)
    service._save_status("monitoring", pid=10101, launch_id="other-launch" if evidence == "other_launch" else launch_id,
                         observed_at=timestamp.isoformat())
    result = await service._await_worker_start(SimpleNamespace(pid=10101, poll=lambda: None),
                                              timeout=0, launch_id=launch_id)
    assert result["status"] == "startup_pending" and result["pid"] is None
    assert result["startup_acknowledged"] is False


@pytest.mark.asyncio
async def test_real_child_heartbeat_matches_launch_even_when_launcher_pid_differs(tmp_path):
    service = ESPNService(tmp_path)
    launch_id = uuid.uuid4().hex
    process = child_process("""
        from pathlib import Path
        import json, os, sys
        from fantasy_football_manager.espn_service import ESPNService
        service = ESPNService(sys.argv[1])
        status = service._save_status('monitoring')
        Path(sys.argv[1], 'worker-ready').write_text(json.dumps(status), encoding='utf-8')
        sys.stdin.readline()
    """, tmp_path, env={**os.environ, "FFM_WORKER_LAUNCH_ID": launch_id})
    try:
        marker = tmp_path / "worker-ready"
        await_marker(process, marker)
        actual = json.loads(marker.read_text(encoding="utf-8"))
        result = await service._await_worker_start(process, timeout=0, launch_id=launch_id)
        assert result["startup_acknowledged"] is True
        assert result["pid"] == actual["pid"] and result["launch_id"] == launch_id
        assert result["launcher_pid"] == process.pid
        output, error = process.communicate("stop\n", timeout=5)
        assert process.returncode == 0, output + error
    finally:
        finish_child(process)


@pytest.mark.asyncio
async def test_real_worker_early_failure_keeps_reason_without_erasing_other_worker(tmp_path):
    service = ESPNService(tmp_path)
    service._save_status("monitoring", pid=90909, launch_id="existing-worker")
    launch_id = uuid.uuid4().hex
    process = child_process("""
        import asyncio, sys
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from fantasy_football_manager import espn_browser
        from fantasy_football_manager.espn_mcp import _worker
        espn_browser._start_playwright = AsyncMock(side_effect=AssertionError('Chrome must not start'))
        # No saved connection: the real worker must fail before any browser call.
        asyncio.run(_worker(SimpleNamespace(data_dir=sys.argv[1], interval=2, trials=40)))
    """, tmp_path, env={**os.environ, "FFM_WORKER_LAUNCH_ID": launch_id})
    try:
        process.communicate(timeout=10)
        assert process.returncode != 0
        with pytest.raises(ValueError, match="Connect ESPN before starting a standalone worker"):
            await service._await_worker_start(process, timeout=0, launch_id=launch_id)
        assert service._last_status["worker_pid"] > 0
        assert service._last_status["launcher_pid"] == process.pid
        with service.manager.transaction() as db:
            shared = json.loads(db.execute("SELECT status FROM espn_runtime WHERE id=1").fetchone()["status"])
        assert shared["pid"] == 90909 and shared["launch_id"] == "existing-worker"
    finally:
        finish_child(process)
