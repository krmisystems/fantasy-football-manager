"""Profile configuration tests use temporary state and no browser connections."""

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from fantasy_football_manager import espn_browser, espn_season_browser, espn_service


class BrowserStub:
    def __init__(self, data_dir, week=None):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.week = week
        self.connected = False
        self.closed = False

    def status(self):
        return {"connected": self.connected}

    async def connect(self, **kwargs):
        self.connected = True
        return {"connected": True, "ready": True}

    async def close(self):
        self.connected = False
        self.closed = True


@pytest.mark.parametrize("value", [None, ""])
def test_unset_or_empty_profile_root_preserves_the_manager_directory(tmp_path, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("FFM_BROWSER_DATA_DIR", raising=False)
    else:
        monkeypatch.setenv("FFM_BROWSER_DATA_DIR", value)
    service = espn_service.ESPNService(tmp_path / "league-state")
    assert service.browser.data_dir == service.manager.data_dir.resolve()
    assert service.browser_data_dir == service.manager.data_dir.resolve()
    assert service.browser.status()["connected"] is False


def test_explicit_profile_root_shares_browser_location_but_not_league_state(tmp_path, monkeypatch):
    shared = tmp_path / "shared-browser"
    monkeypatch.setenv("FFM_BROWSER_DATA_DIR", str(shared))
    first = espn_service.ESPNService(tmp_path / "first-league")
    second = espn_service.ESPNService(tmp_path / "second-league")
    assert first.browser.data_dir == second.browser.data_dir == shared.resolve()
    assert first.manager.path != second.manager.path
    config = first.manager.state()[1]
    config.automation.paused = True
    first.manager.update_config(config.model_dump(mode="json"), 0)
    assert first.manager.state()[1].automation.paused is True
    assert second.manager.state()[1].automation.paused is False
    assert not (shared / "manager.sqlite3").exists()
    assert not (shared / "espn-browser-profile").exists()


def test_state_environment_and_browser_environment_select_separate_locations(tmp_path, monkeypatch):
    monkeypatch.setenv("FFM_DATA_DIR", str(tmp_path / "league-state"))
    monkeypatch.setenv("FFM_BROWSER_DATA_DIR", str(tmp_path / "browser-root"))
    service = espn_service.ESPNService()
    assert service.manager.data_dir == tmp_path / "league-state"
    assert service.browser.data_dir == (tmp_path / "browser-root").resolve()


@pytest.mark.asyncio
async def test_phase_changes_keep_the_profile_root_selected_at_service_start(tmp_path, monkeypatch):
    selected_root = tmp_path / "selected-browser"
    monkeypatch.setenv("FFM_BROWSER_DATA_DIR", str(selected_root))
    monkeypatch.setattr(espn_browser, "ESPNBrowser", BrowserStub)
    monkeypatch.setattr(espn_season_browser, "ESPNSeasonBrowser", BrowserStub)
    service = espn_service.ESPNService(tmp_path / "league-state")
    initial = service.browser
    monkeypatch.setenv("FFM_BROWSER_DATA_DIR", str(tmp_path / "later-environment-value"))
    await service.connect("123", "1", 2026, phase="draft")
    draft = service.browser
    assert initial.closed and draft is not initial
    await service.connect("123", "1", 2026, phase="season", week=3)
    assert draft.closed and service.browser is not draft
    assert service.browser.data_dir == selected_root.resolve()
    assert service.browser.week == 3
    assert service.saved_connection()["phase"] == "season"
    assert service.saved_connection()["week"] == 3


@pytest.mark.asyncio
async def test_explicit_profile_environment_does_not_replace_an_injected_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("FFM_BROWSER_DATA_DIR", str(tmp_path / "configured-root"))
    browser = BrowserStub(tmp_path / "injected-root")
    service = espn_service.ESPNService(tmp_path / "league-state", browser=browser)
    await service.connect("123", "1", 2026, phase="season", week=2)
    assert service.browser is browser
    assert browser.data_dir == (tmp_path / "injected-root").resolve()
    assert browser.week == 2


@pytest.mark.asyncio
async def test_standalone_checks_the_shared_profile_lease_before_spawning(tmp_path, monkeypatch):
    from filelock import FileLock

    shared = tmp_path / "shared-browser"
    shared.mkdir()
    monkeypatch.setenv("FFM_BROWSER_DATA_DIR", str(shared))
    service = espn_service.ESPNService(tmp_path / "league-state", browser=BrowserStub(shared))
    await service.connect("123", "1", 2026)
    monkeypatch.setattr(espn_service.subprocess, "Popen", lambda *a, **k: pytest.fail("A busy shared profile spawned a worker."))
    with FileLock(shared / "espn-browser.lock"):
        with pytest.raises(ValueError, match="second worker was not started"):
            await service.start_standalone()


@pytest.mark.asyncio
async def test_standalone_passes_the_selected_profile_root_and_keeps_state_directory(tmp_path, monkeypatch):
    shared, state_dir = tmp_path / "shared-browser", tmp_path / "league-state"
    monkeypatch.setenv("FFM_BROWSER_DATA_DIR", str(shared))
    service = espn_service.ESPNService(state_dir, browser=BrowserStub(shared))
    await service.connect("123", "1", 2026)
    calls = []

    def launch(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=123456)

    async def acknowledge(process, *args, **kwargs):
        return {"status": "starting"}

    monkeypatch.setattr(espn_service.subprocess, "Popen", launch)
    monkeypatch.setattr(service, "_await_worker_start", acknowledge)
    monkeypatch.setenv("FFM_BROWSER_DATA_DIR", str(tmp_path / "changed-after-construction"))
    await service.start_standalone()
    command, options = calls[0]
    assert command[command.index("--data-dir") + 1] == str(state_dir)
    assert options["env"]["FFM_BROWSER_DATA_DIR"] == str(shared.resolve())
    assert len(calls) == 1


def test_child_service_inherits_explicit_profile_configuration_without_copying_state(tmp_path, monkeypatch):
    shared, state_dir = tmp_path / "shared-browser", tmp_path / "worker-state"
    monkeypatch.setenv("FFM_BROWSER_DATA_DIR", str(shared))
    code = (
        "import json,sys; from fantasy_football_manager.espn_service import ESPNService; "
        "s=ESPNService(sys.argv[1]); "
        "print(json.dumps({'state':str(s.manager.data_dir),'browser':str(s.browser.data_dir),'connected':s.browser.status()['connected']}))"
    )
    result = subprocess.run([sys.executable, "-c", code, str(state_dir)], check=True,
                            capture_output=True, text=True, timeout=15)
    assert json.loads(result.stdout) == {"state": str(state_dir), "browser": str(shared.resolve()), "connected": False}
    assert not shared.exists()
