"""Service tests use a browser stub. They do not launch a browser or contact ESPN."""

import copy
import json
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from fantasy_football_manager import espn_service
from fantasy_football_manager.models import LeagueSnapshot, ManagerConfig
from fantasy_football_manager.policy import PolicyError


def observed(selected=()):
    now = datetime.now(timezone.utc)
    picks = [{"pick_no": n, "player_id": pid, "slot": [1, 2, 2, 1][n-1]} for n, pid in enumerate(selected, 1)]
    return LeagueSnapshot.model_validate({
        "league_id": "fictional-league", "team_id": "team-1", "season": 2026, "phase": "draft",
        "source": {"provider": "espn_browser", "synthetic": False, "complete": True,
                   "observed_at": now, "projections_observed_at": now,
                   "browser": {"page_url": "https://fantasy.espn.com/football/draft?leagueId=fictional-league&teamId=team-1",
                               "league_id": "fictional-league", "team_id": "team-1", "current_pick": len(picks)+1,
                               "autopick_enabled": False, "draft_complete": len(picks) == 4}},
        "rules": {"teams": 2, "slot": 1, "rounds": 2, "starters": {"RB": 1}, "bench": 1},
        "players": [{"id": f"p{n}", "name": f"Fictional player {n}", "position": "RB", "projection": 200-n,
                     "adp": n, "availability": "ACTIVE"} for n in range(1, 7)],
        "teams": [{"id": f"team-{slot}", "name": f"Fictional team {slot}", "slot": slot,
                   "roster_ids": [p["player_id"] for p in picks if p["slot"] == slot]} for slot in [1, 2]], "picks": picks})


def season_observed():
    data = observed().model_dump(mode="json")
    data["phase"] = "season"
    data["rules"].update(rounds=4, starters={"RB": 2}, bench=2)
    data["source"]["locks_verified"] = True
    data["source"]["browser"]["current_pick"] = None
    data["source"]["browser"]["page_url"] = data["source"]["browser"]["page_url"].replace("/draft?", "/team?") + "&scoringPeriodId=1"
    for player, projection in zip(data["players"], [5, 8, 20, 18, 10, 11]):
        player["weekly_projection"] = projection
    data["teams"][0].update(roster_ids=["p1", "p2", "p3", "p4"], lineup={"RB1": "p1", "RB2": "p2"})
    data["teams"][1].update(roster_ids=["p5", "p6"], lineup={"RB1": "p5", "RB2": "p6"})
    return LeagueSnapshot.model_validate(data)


class BrowserStub:
    def __init__(self):
        self.current = observed()
        self.queue = []
        self.observations = 0
        self.preflights = []
        self.clicks = []
        self.preflight_error = None
        self.submit_error = None
        self.submit_response = None
        self.before_click = None
        self.connected = True
        self.closed = False

    def status(self):
        return {"connected": self.connected}

    async def connect(self, **kwargs):
        self.connected = True
        return {"ready": True}

    async def observe(self, previous=None):
        self.observations += 1
        if self.queue:
            self.current = self.queue.pop(0)
        snapshot = self.current.model_copy(deep=True)
        snapshot.source.observed_at = datetime.now(timezone.utc)
        return snapshot

    async def preflight_pick(self, proposal):
        self.preflights.append(copy.deepcopy(proposal))
        if self.preflight_error:
            raise self.preflight_error

    async def submit_pick(self, permit):
        if self.before_click:
            self.before_click()
        fresh = self.current.model_copy(deep=True)
        fresh.source.observed_at = datetime.now(timezone.utc)
        self.permit_validator(permit, fresh)
        self.clicks.append(copy.deepcopy(permit))
        if self.submit_error:
            raise self.submit_error
        if self.submit_response is not None:
            return copy.deepcopy(self.submit_response)
        selected = [pick.player_id for pick in self.current.picks] + [permit["player_id"]]
        self.current = observed(selected)
        return {"status": "clicked", "snapshot": self.current.model_dump(mode="json")}

    async def close(self):
        self.closed = True
        self.connected = False


class SeasonBrowserStub(BrowserStub):
    def __init__(self):
        super().__init__()
        self.current = season_observed()

    async def preflight_lineup(self, proposal):
        return await self.preflight_pick(proposal)

    async def submit_lineup(self, permit):
        if self.before_click:
            self.before_click()
        fresh = self.current.model_copy(deep=True)
        fresh.source.observed_at = datetime.now(timezone.utc)
        self.permit_validator(permit, fresh)
        self.clicks.append(copy.deepcopy(permit))
        if self.submit_error:
            raise self.submit_error
        if self.submit_response is not None:
            return copy.deepcopy(self.submit_response)
        self.current.own_team().lineup = dict(permit["lineup"])
        self.current.source.observed_at = datetime.now(timezone.utc)
        return {"status": "clicked", "snapshot": self.current.model_dump(mode="json")}


class StepEvent:
    def __init__(self, steps=1):
        self.steps = steps
        self.waits = 0
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def clear(self):
        self.stopped = False

    async def wait(self):
        self.waits += 1
        if self.waits >= self.steps:
            self.set()
        return self.stopped


@pytest.fixture
def service(tmp_path):
    browser = BrowserStub()
    service = espn_service.ESPNService(tmp_path, browser=browser)
    service.manager.import_snapshot(browser.current.model_dump(mode="json"))
    service.manager.update_config(ManagerConfig(automation={"preset": "review"}).model_dump(mode="json"), 0)
    return service


@pytest.fixture
def season_service(tmp_path):
    browser = SeasonBrowserStub()
    service = espn_service.ESPNService(tmp_path, browser=browser)
    service.phase = "season"
    service.manager.import_snapshot(browser.current.model_dump(mode="json"))
    service.manager.update_config(ManagerConfig(automation={"preset": "review"}).model_dump(mode="json"), 0)
    return service


def batch(snapshot, config, trials, seed):
    count = len(snapshot.picks)
    return {"status": "ready", "completed": False, "analysis_fingerprint": f"state-{count}", "trials": trials,
            "current_pick": count+1, "my_next_pick": 1 if count == 0 else 4, "following_pick": 4 if count == 0 else None,
            "available_count": 6-count,
            "recommendations": [{"id": "p1" if count == 0 else "p4", "adp": 1, "score": 10,
                                 "score_sum": 10*trials, "score_sq_sum": 100*trials, "simulation_count": trials,
                                 "availability_count": trials, "survival_count": trials, "trial_count": trials,
                                 "availability_at_pick": 1, "survival_next_pick": 1, "reason": "Fills a starter slot."}]}


@pytest.mark.asyncio
async def test_prepare_refreshes_before_creating_exact_proposal(service):
    revision = service.manager.state()[2]
    proposal = await service.prepare_pick("p1")
    assert service.browser.observations == 1 and proposal["revision"] == revision
    assert not proposal["should_click"] and service.browser.clicks == []


@pytest.mark.asyncio
async def test_preflight_failure_does_not_claim_or_click(service):
    proposal = await service.prepare_pick("p1")
    service.browser.preflight_error = ValueError("Fictional clock changed")
    with pytest.raises(ValueError, match="clock changed"):
        await service.submit_pick(proposal["proposal_id"], confirmation=True)
    assert service.draft.get(proposal["proposal_id"])["status"] == "pending"
    assert service.browser.clicks == [] and service.draft.pending() == []


@pytest.mark.asyncio
async def test_review_without_confirmation_never_clicks(service):
    proposal = await service.prepare_pick("p1")
    with pytest.raises(PolicyError, match="confirmation"):
        await service.submit_pick(proposal["proposal_id"])
    assert not service.browser.clicks
    assert service.draft.get(proposal["proposal_id"])["status"] == "pending"


@pytest.mark.asyncio
async def test_successful_submit_reconciles_and_repeat_never_clicks(service):
    proposal = await service.prepare_pick("p1")
    result = await service.submit_pick(proposal["proposal_id"], confirmation=True)
    assert result["status"] == "confirmed" and len(service.browser.clicks) == 1
    repeat = await service.submit_pick(proposal["proposal_id"], confirmation=True)
    assert repeat["status"] == "confirmed" and not repeat["should_click"]
    assert len(service.browser.clicks) == 1 and len(service.browser.preflights) == 1
    assert [pick.player_id for pick in service.manager.state()[0].picks] == ["p1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "no_snapshot"])
async def test_uncertain_browser_result_keeps_claim_without_retry(service, failure):
    proposal = await service.prepare_pick("p1")
    if failure == "exception":
        service.browser.submit_error = RuntimeError("Fictional browser disconnected after click")
    else:
        service.browser.submit_response = {"status": "success", "clicked": True}
    result = await service.submit_pick(proposal["proposal_id"], confirmation=True)
    assert result["status"] == "awaiting_verification" and not result["retry_allowed"]
    assert service.manager.state()[0].picks == []
    await service.submit_pick(proposal["proposal_id"], confirmation=True)
    assert len(service.browser.clicks) == 1
    service.browser.current = observed(["p1"])
    verified = await service.reconcile_pick(proposal["proposal_id"])
    assert verified["status"] == "confirmed" and len(service.browser.clicks) == 1


@pytest.mark.asyncio
async def test_config_change_before_adapter_click_invalidates_permit(service):
    proposal = await service.prepare_pick("p1")

    def pause():
        _, config, _, revision = service.manager.state()
        config.automation.paused = True
        service.manager.update_config(config.model_dump(mode="json"), revision)

    service.browser.before_click = pause
    result = await service.submit_pick(proposal["proposal_id"], confirmation=True)
    assert result["status"] == "awaiting_verification" and not result["retry_allowed"]
    assert not service.browser.clicks and service.manager.state()[0].picks == []


@pytest.mark.asyncio
async def test_new_pick_resets_simulation_aggregate(service, monkeypatch):
    service.browser.queue = [observed(), observed(["p1"])]
    service.stop_event = StepEvent(2)
    monkeypatch.setattr(espn_service, "recommend_draft", batch)
    await service._run(1, 4)
    latest = service.status()["latest_recommendations"]
    assert latest["result"]["current_pick"] == 2
    assert latest["result"]["trials"] == 4
    assert latest["revision"] == service.manager.state()[2]


@pytest.mark.asyncio
async def test_matching_batches_accumulate_without_new_clock_work(service, monkeypatch):
    service.stop_event = StepEvent(2)
    monkeypatch.setattr(espn_service, "recommend_draft", batch)
    await service._run(1, 4)
    latest = service.status()["latest_recommendations"]
    assert latest["result"]["trials"] == 8
    assert not service.browser.clicks


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "config", "stale"])
async def test_status_hides_recommendations_when_input_is_no_longer_current(service, monkeypatch, change):
    service.stop_event = StepEvent()
    monkeypatch.setattr(espn_service, "recommend_draft", batch)
    await service._run(1, 4)
    assert service.status()["latest_recommendations"] is not None
    snapshot, config, revision, config_revision = service.manager.state()
    if change == "revision":
        service.manager.import_snapshot(observed(["p1"]).model_dump(mode="json"), revision)
    elif change == "config":
        service.manager.update_config(config.model_dump(mode="json"), config_revision)
    else:
        snapshot.source.observed_at -= timedelta(seconds=60)
        with service.manager.transaction() as db:
            db.execute("UPDATE state SET snapshot=? WHERE id=1", (snapshot.model_dump_json(),))
    assert service.status()["latest_recommendations"] is None


@pytest.mark.asyncio
async def test_failed_browser_refresh_suppresses_previous_recommendations(service, monkeypatch):
    service.stop_event = StepEvent(2)
    original = service.browser.observe

    async def failed_refresh(previous=None):
        if service.browser.observations:
            raise RuntimeError("Fictional draft observation unavailable")
        return await original(previous=previous)

    monkeypatch.setattr(service.browser, "observe", failed_refresh)
    monkeypatch.setattr(espn_service, "recommend_draft", batch)
    await service._run(1, 4)
    assert service.status()["latest_recommendations"] is None
    assert not service.browser.clicks


@pytest.mark.asyncio
async def test_pause_skips_browser_polling_and_simulation(service, monkeypatch):
    _, config, _, revision = service.manager.state()
    config.automation.paused = True
    service.manager.update_config(config.model_dump(mode="json"), revision)
    service.stop_event = StepEvent()
    monkeypatch.setattr(espn_service, "recommend_draft", lambda *a: pytest.fail("Paused service ran simulations."))
    await service._run(1, 4)
    assert service.browser.observations == 0 and not service.browser.clicks


@pytest.mark.asyncio
async def test_complete_roster_stops_without_simulation(service, monkeypatch):
    service.browser.current = observed(["p1", "p2", "p3", "p4"])
    service.stop_event = StepEvent()
    monkeypatch.setattr(espn_service, "recommend_draft", lambda *a: pytest.fail("Complete roster ran simulations."))
    await service._run(1, 4)
    assert service.local_status == "draft_complete" and service.stop_event.waits == 0
    assert service.browser.observations == 1 and not service.browser.clicks


@pytest.mark.asyncio
async def test_automatic_mode_submits_only_one_verified_pick(service, monkeypatch):
    _, config, _, revision = service.manager.state()
    config.automation.preset = "bounded_automation"
    service.manager.update_config(config.model_dump(mode="json"), revision)
    service.stop_event = StepEvent()
    monkeypatch.setattr(espn_service, "recommend_draft", batch)
    await service._run(1, 4)
    assert len(service.browser.clicks) == 1
    assert service.manager.state()[0].picks[0].player_id == "p1"
    assert service.draft.pending() == []


@pytest.mark.asyncio
async def test_stop_during_calculation_prevents_new_action(service, monkeypatch):
    _, config, _, revision = service.manager.state()
    config.automation.preset = "bounded_automation"
    service.manager.update_config(config.model_dump(mode="json"), revision)
    service.stop_event = StepEvent()

    def stopped_batch(*args):
        service.stop_event.set()
        return batch(*args)

    monkeypatch.setattr(espn_service, "recommend_draft", stopped_batch)
    await service._run(1, 4)
    assert not service.browser.clicks and service.manager.state()[0].picks == []


@pytest.mark.asyncio
async def test_close_disconnects_the_adapter(service):
    result = await service.close()
    assert result["status"] == "disconnected" and service.browser.closed


@pytest.mark.asyncio
async def test_polling_preserves_exact_review_proposal_when_only_time_changes(service, monkeypatch):
    proposal = await service.prepare_pick("p1")
    service.stop_event = StepEvent(2)
    monkeypatch.setattr(espn_service, "recommend_draft", batch)
    await service._run(1, 4)
    assert service.manager.state()[2] == proposal["revision"]
    status = service.status()
    assert status["awaiting_review"] is True
    assert status["review_proposals"][0]["proposal_id"] == proposal["proposal_id"]
    assert (await service.submit_pick(proposal["proposal_id"], True))["status"] == "confirmed"


@pytest.mark.asyncio
async def test_review_can_be_confirmed_after_old_observation_ages(service):
    proposal = await service.prepare_pick("p1")
    snapshot = service.manager.state()[0]
    snapshot.source.observed_at -= timedelta(seconds=60)
    with service.manager.transaction() as db:
        db.execute("UPDATE state SET snapshot=? WHERE id=1", (snapshot.model_dump_json(),))
    assert (await service.submit_pick(proposal["proposal_id"], True))["status"] == "confirmed"


@pytest.mark.asyncio
async def test_real_player_input_change_invalidates_review_proposal(service):
    proposal = await service.prepare_pick("p1")
    service.browser.current.players[0].projection += 1
    await service.sync()
    assert service.manager.state()[2] > proposal["revision"]
    assert service.status()["review_proposals"][0]["current"] is False
    with pytest.raises(ValueError, match="State or config changed"):
        await service.submit_pick(proposal["proposal_id"], True)
    assert service.browser.clicks == []


@pytest.mark.asyncio
async def test_fresh_permit_check_uses_fresh_evidence_but_preserves_identity(service):
    proposal = await service.prepare_pick("p1")
    permit = service.draft.authorize(proposal["proposal_id"], True)
    stored = service.manager.state()[0]
    stored.source.observed_at -= timedelta(seconds=60)
    with service.manager.transaction() as db:
        db.execute("UPDATE state SET snapshot=? WHERE id=1", (stored.model_dump_json(),))
    assert service._validate_permit(permit, observed()) is True
    with pytest.raises(ValueError, match="permit changed"):
        service._validate_permit({**permit, "payload": {"player_id": "p2"}}, observed())
    changed = observed()
    changed.teams[1].id = "other-team"
    with pytest.raises(ValueError, match="team identities"):
        service._validate_permit(permit, changed)
    unavailable = observed()
    unavailable.players[0].availability = "OUT"
    with pytest.raises(ValueError, match="not confirmed available"):
        service._validate_permit(permit, unavailable)


@pytest.mark.asyncio
async def test_automatic_mode_skips_policy_rejected_top_candidate(service, monkeypatch):
    _, config, _, revision = service.manager.state()
    config.automation.preset = "bounded_automation"
    service.manager.update_config(config.model_dump(mode="json"), revision)
    service.browser.current.players[0].availability = "OUT"
    service.stop_event = StepEvent()
    def ranked(*args):
        value = batch(*args)
        value["recommendations"].append({**value["recommendations"][0], "id": "p2"})
        return value
    monkeypatch.setattr(espn_service, "recommend_draft", ranked)
    await service._run(1, 4)
    assert len(service.browser.clicks) == 1 and service.browser.clicks[0]["player_id"] == "p2"


@pytest.mark.asyncio
async def test_standalone_busy_profile_does_not_spawn(service, monkeypatch):
    from filelock import FileLock
    monkeypatch.setattr(service, "saved_connection", lambda: {})
    monkeypatch.setattr(espn_service.subprocess, "Popen", lambda *a, **k: pytest.fail("Busy profile spawned a worker."))
    with FileLock(service.manager.data_dir / "espn-browser.lock"):
        with pytest.raises(ValueError, match="second worker was not started"):
            await service.start_standalone()


@pytest.mark.asyncio
async def test_worker_early_exit_is_reported_as_failure(service):
    service._save_status("connection_failed", pid=123456, launch_id="fictional-launch", error="Fictional browser lease is busy")
    with pytest.raises(ValueError, match="lease is busy"):
        await service._await_worker_start(SimpleNamespace(pid=123456, poll=lambda: 1), timeout=0, launch_id="fictional-launch")
    assert service.local_status == "startup_failed"


@pytest.mark.asyncio
async def test_worker_start_requires_matching_process_acknowledgement(service):
    process = SimpleNamespace(pid=123456, poll=lambda: None)
    assert (await service._await_worker_start(process, timeout=0, launch_id="fictional-launch"))["status"] == "startup_pending"
    service._save_status("monitoring", pid=process.pid, launch_id="fictional-launch")
    result = await service._await_worker_start(process, timeout=0, launch_id="fictional-launch")
    assert result["startup_acknowledged"] is True and result["status"] == "monitoring"


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_status", ["monitoring", "monitoring_lineup", "lineup_current", "no_admissible_lineup_exchange", "confirmed"])
async def test_local_disconnect_does_not_erase_other_worker_heartbeat(service, worker_status):
    service._save_status(worker_status, pid=123456)
    service._save_status("connection_failed", error="Fictional profile lease is busy")
    await service.close()
    with service.manager.transaction() as db:
        shared = json.loads(db.execute("SELECT status FROM espn_runtime WHERE id=1").fetchone()["status"])
    assert shared["pid"] == 123456 and shared["status"] == worker_status
    assert service.local_status == "disconnected"


@pytest.mark.asyncio
async def test_lineup_review_proposal_survives_poll_and_requires_confirmation(season_service):
    service = season_service
    target = {"RB1": "p3", "RB2": "p2"}
    proposal = await service.prepare_lineup(target)
    await service.sync()
    assert service.status()["awaiting_review"] is True
    assert service.manager.state()[2] == proposal["revision"]
    with pytest.raises(ValueError, match="confirmation"):
        await service.submit_lineup(proposal["proposal_id"])
    result = await service.submit_lineup(proposal["proposal_id"], True)
    assert result["status"] == "confirmed"
    assert service.manager.state()[0].own_team().lineup == target
    assert len(service.browser.clicks) == 1
    assert not (await service.submit_lineup(proposal["proposal_id"], True))["should_click"]
    assert len(service.browser.clicks) == 1


@pytest.mark.asyncio
async def test_season_loop_reconciles_one_exchange_before_next_and_keeps_monitoring(season_service):
    service = season_service
    _, config, _, revision = service.manager.state()
    config.automation.preset = "bounded_automation"
    service.manager.update_config(config.model_dump(mode="json"), revision)
    service.stop_event = StepEvent(3)
    await service._run(1, 4)
    assert len(service.browser.clicks) == 2
    assert set(service.manager.state()[0].own_team().lineup.values()) == {"p3", "p4"}
    assert service.lineup.pending() == []
    assert service.stop_event.waits == 3
    assert all(permit["action"] == "set_lineup" for permit in service.browser.clicks)


@pytest.mark.asyncio
async def test_uncertain_lineup_submission_blocks_new_exchanges(season_service):
    service = season_service
    _, config, _, revision = service.manager.state()
    config.automation.preset = "bounded_automation"
    service.manager.update_config(config.model_dump(mode="json"), revision)
    service.browser.submit_response = {"status": "awaiting_verification", "uncertain": True}
    service.stop_event = StepEvent(3)
    await service._run(1, 4)
    assert len(service.browser.clicks) == 1
    assert len(service.lineup.pending()) == 1
    assert service.manager.state()[0].own_team().lineup == {"RB1": "p1", "RB2": "p2"}


@pytest.mark.asyncio
async def test_automatic_draft_mode_does_not_authorize_lineup_moves(season_service):
    service = season_service
    _, config, _, revision = service.manager.state()
    config.automation.preset = "custom"
    config.automation.actions["draft_pick"] = "automatic"
    config.automation.actions["set_lineup"] = "advisory"
    service.manager.update_config(config.model_dump(mode="json"), revision)
    service.stop_event = StepEvent()
    await service._run(1, 4)
    assert service.browser.clicks == []
    assert service.status()["latest_recommendations"]["phase"] == "season"


@pytest.mark.asyncio
async def test_lineup_locks_changed_before_confirmation_block_action(season_service):
    service = season_service
    proposal = await service.prepare_lineup({"RB1": "p3", "RB2": "p2"})
    def lock_player():
        service.browser.current.players[2].locked = True
    service.browser.before_click = lock_player
    result = await service.submit_lineup(proposal["proposal_id"], True)
    assert result["status"] == "awaiting_verification" and not result["retry_allowed"]
    assert service.browser.clicks == []


@pytest.mark.asyncio
async def test_connect_persists_season_and_week_for_worker(season_service):
    service = season_service
    result = await service.connect("123", "11", 2026, phase="season", week=3)
    assert result["phase"] == "season" and result["week"] == 3
    assert service.saved_connection()["phase"] == "season"
    assert service.saved_connection()["week"] == 3
    with pytest.raises(ValueError, match="Phase"):
        await service.connect("123", "11", 2026, phase="auction")


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["draft", "season"])
async def test_restarted_service_reconnects_exact_pending_scope_and_verifies_without_click(request, phase):
    service = request.getfixturevalue("season_service" if phase == "season" else "service")
    target = {"RB1": "p3", "RB2": "p2"}
    proposal = await (service.prepare_lineup(target) if phase == "season" else service.prepare_pick("p1"))
    service.browser.submit_response = {"status": "awaiting_verification", "uncertain": True}
    submitted = await (service.submit_lineup(proposal["proposal_id"], True) if phase == "season"
                       else service.submit_pick(proposal["proposal_id"], True))
    assert submitted["status"] == "awaiting_verification" and len(service.browser.clicks) == 1
    await service.close()
    browser = SeasonBrowserStub() if phase == "season" else BrowserStub()
    browser.connected = False
    restarted = espn_service.ESPNService(service.manager.data_dir, browser=browser)
    assert restarted.status()["phase"] == phase
    connection = {"league_id": "fictional-league", "team_id": "team-1", "season": 2026, "phase": phase, "week": 1}
    changes = {"league_id": "other-league", "team_id": "other-team", "season": 2027,
               "phase": "draft" if phase == "season" else "season", "week": 2}
    for field, value in changes.items():
        with pytest.raises(ValueError, match="Reconnect its exact"):
            await restarted.connect(**{**connection, field: value})
        assert browser.connected is False
    assert (await restarted.connect(**connection))["ready"] is True
    assert len(restarted.status()["pending"]) == 1
    if phase == "season":
        browser.current.own_team().lineup = target
    else:
        browser.current = observed(["p1"])
    result = await restarted.sync()
    assert result["reconciliation"]["status"] == "confirmed"
    repeat = await (restarted.submit_lineup(proposal["proposal_id"], True) if phase == "season"
                    else restarted.submit_pick(proposal["proposal_id"], True))
    assert not repeat["should_click"] and browser.clicks == []
    assert restarted.status()["pending"] == []


@pytest.mark.asyncio
async def test_equivalent_lineup_order_reports_current_without_click(season_service, monkeypatch):
    service = season_service
    _, config, _, config_revision = service.manager.state()
    config.automation.preset = "bounded_automation"
    service.manager.update_config(config.model_dump(mode="json"), config_revision)
    monkeypatch.setattr(espn_service, "recommend_lineup", lambda *args: {
        "status": "ok", "lineup": {"RB1": "p2", "RB2": "p1"}})
    await service._season_step(*service.manager.require_state())
    assert service.local_status == "lineup_current" and service.browser.clicks == []
