"""Browser action tests use fictional platform observations and no browser calls."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

import pytest

from fantasy_football_manager.browser_draft import BrowserDraft
from fantasy_football_manager.models import LeagueSnapshot, ManagerConfig
from fantasy_football_manager.policy import PolicyError
from fantasy_football_manager.store import Manager


def platform_snapshot(selected=(), **updates):
    now = datetime.now(timezone.utc)
    picks = [{"pick_no": index, "player_id": pid,
              "slot": [1, 2, 2, 1][index - 1]} for index, pid in enumerate(selected, 1)]
    data = {"league_id": "fictional-league", "team_id": "team-1", "season": 2026,
            "phase": "draft", "source": {"provider": "espn_browser", "synthetic": False,
                "complete": True, "locks_verified": True, "observed_at": now,
                "projections_observed_at": now},
            "rules": {"teams": 2, "slot": 1, "rounds": 2, "starters": {"RB": 1}, "bench": 1},
            "players": [{"id": f"p{index}", "name": f"Fictional player {index}", "position": "RB",
                         "projection": 150-index, "adp": index, "availability": "ACTIVE"}
                        for index in range(1, 7)],
            "teams": [{"id": f"team-{slot}", "name": f"Fictional team {slot}", "slot": slot,
                       "roster_ids": [pick["player_id"] for pick in picks if pick["slot"] == slot]}
                      for slot in [1, 2]], "picks": picks}
    data.update(updates)
    data["source"]["browser"] = {
        "page_url": f"https://fantasy.espn.com/football/draft?leagueId={data['league_id']}&teamId={data['team_id']}",
        "league_id": data["league_id"], "team_id": data["team_id"],
        "current_pick": len(picks) + 1, "autopick_enabled": False, "draft_complete": len(picks) == 4}
    return LeagueSnapshot.model_validate(data).model_dump(mode="json")


@pytest.fixture
def setup(tmp_path):
    manager = Manager(tmp_path)
    manager.import_snapshot(platform_snapshot())
    manager.update_config(ManagerConfig(automation={"preset": "review"}).model_dump(mode="json"), 0)
    return manager, BrowserDraft(manager)


def proposal_state(manager, proposal_id):
    with manager.transaction() as db:
        return dict(db.execute("SELECT * FROM browser_proposals WHERE id=?", (proposal_id,)).fetchone())


def authorize(browser, player_id="p1"):
    proposed = browser.prepare(player_id)
    return browser.authorize(proposed["proposal_id"], confirmation=True)


def test_prepare_stores_exact_baseline_and_does_not_draft(setup):
    manager, browser = setup
    before = manager.state()
    proposal = browser.prepare("p1")
    saved = proposal_state(manager, proposal["proposal_id"])
    assert proposal["scope"] == "host_browser" and proposal["executor"] == "connected_host_browser"
    assert proposal["player_name"] == "Fictional player 1" and proposal["pick_no"] == 1
    assert proposal["requires_confirmation"] and not proposal["should_click"]
    assert json.loads(saved["baseline"]) == before[0].model_dump(mode="json")
    assert json.loads(saved["decision"])["payload"] == {"player_id": "p1"}
    assert manager.state() == before


def test_review_requires_exact_confirmation_and_failure_is_atomic(setup):
    manager, browser = setup
    proposed = browser.prepare("p1")
    before = manager.state()
    history = manager.history()
    with pytest.raises(PolicyError, match="confirmation"):
        browser.authorize(proposed["proposal_id"])
    assert manager.state() == before and manager.history() == history
    assert proposal_state(manager, proposed["proposal_id"])["status"] == "pending"
    claimed = browser.authorize(proposed["proposal_id"], confirmation=True)
    assert claimed["status"] == "awaiting_verification" and claimed["should_click"]
    assert manager.state() == before


def test_automatic_mode_still_requires_platform_verification(setup):
    manager, browser = setup
    config = manager.state()[1].model_copy(deep=True)
    config.automation.preset = "bounded_automation"
    manager.update_config(config.model_dump(mode="json"), manager.state()[3])
    proposal = browser.prepare("p1")
    result = browser.authorize(proposal["proposal_id"])
    assert result["mode"] == "automatic" and not result["requires_confirmation"]
    assert result["should_click"] and result["status"] == "awaiting_verification"
    assert manager.state()[0].picks == []


def test_repeat_authorization_never_reclicks_even_after_state_changes(setup):
    manager, browser = setup
    claimed = authorize(browser)
    manager.import_snapshot(platform_snapshot(["p1"]), manager.state()[2])
    config = manager.state()[1].model_copy(deep=True)
    config.automation.paused = True
    manager.update_config(config.model_dump(mode="json"), manager.state()[3])
    replay = browser.authorize(claimed["proposal_id"], confirmation=True)
    assert replay["status"] == "awaiting_verification" and not replay["should_click"]
    assert replay["authorized_at"] == claimed["authorized_at"]


@pytest.mark.parametrize("changed", ["snapshot", "config"])
def test_stale_prepared_proposal_is_rejected(setup, changed):
    manager, browser = setup
    proposed = browser.prepare("p1")
    if changed == "snapshot":
        manager.import_snapshot(platform_snapshot(), manager.state()[2])
    else:
        manager.update_config(manager.state()[1].model_dump(mode="json"), manager.state()[3])
    with pytest.raises(PolicyError, match="changed"):
        browser.authorize(proposed["proposal_id"], confirmation=True)
    assert proposal_state(manager, proposed["proposal_id"])["status"] == "pending"
    assert manager.state()[0].picks == []


def test_unresolved_claim_blocks_another_prepare_or_claim(setup):
    _, browser = setup
    first, second = browser.prepare("p1"), browser.prepare("p2")
    browser.authorize(first["proposal_id"], confirmation=True)
    with pytest.raises(PolicyError, match="awaits verification"):
        browser.prepare("p3")
    with pytest.raises(PolicyError, match="awaits verification"):
        browser.authorize(second["proposal_id"], confirmation=True)


def test_concurrent_authorization_returns_one_click_claim(setup):
    manager, browser = setup
    proposed = browser.prepare("p1")
    # Separate manager instances also serialize through SQLite, without a shared Python lock.
    second = BrowserDraft(Manager(manager.data_dir))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda service: service.authorize(proposed["proposal_id"], confirmation=True), [browser, second]))
    assert sum(result["should_click"] for result in results) == 1
    assert {result["status"] for result in results} == {"awaiting_verification"}
    assert manager.state()[0].picks == []


def test_missing_expected_pick_remains_pending_without_phantom_state(setup):
    manager, browser = setup
    claimed = authorize(browser)
    before, history = manager.state(), manager.history()
    result = browser.reconcile(claimed["proposal_id"], platform_snapshot())
    assert result["status"] == "awaiting_verification" and not result["should_click"]
    assert manager.state() == before and manager.history() == history
    assert proposal_state(manager, claimed["proposal_id"])["result"] is None
    with pytest.raises(PolicyError, match="awaits verification"):
        browser.prepare("p2")


@pytest.mark.parametrize("selected, status", [(["p1", "p2"], "confirmed"), (["p2", "p1"], "not_selected")])
def test_reconciliation_imports_actual_platform_state_and_is_idempotent(setup, selected, status):
    manager, browser = setup
    claimed = authorize(browser)
    before_revision = manager.state()[2]
    observed = platform_snapshot(selected)
    result = browser.reconcile(claimed["proposal_id"], observed)
    assert result["status"] == status and not result["should_click"]
    assert result["actual_pick"]["player_id"] == selected[0]
    assert result["revision"] == before_revision + 1
    assert manager.state()[0].model_dump(mode="json") == observed
    after, history = manager.state(), manager.history()
    assert browser.reconcile(claimed["proposal_id"], {}) == result
    assert browser.authorize(claimed["proposal_id"], confirmation=True) == result
    assert manager.state() == after and manager.history() == history


def test_reconcile_requires_authorization(setup):
    manager, browser = setup
    proposed = browser.prepare("p1")
    before = manager.state()
    with pytest.raises(PolicyError, match="Authorize"):
        browser.reconcile(proposed["proposal_id"], platform_snapshot(["p1"]))
    assert manager.state() == before


@pytest.mark.parametrize("case", ["empty", "incomplete", "synthetic", "provider", "league", "team", "season", "rules", "preauthorization", "season_phase", "missing_browser", "wrong_clock", "false_end"])
def test_invalid_observation_fails_atomically_without_confirmation(setup, case):
    manager, browser = setup
    claimed = authorize(browser)
    observed = platform_snapshot(["p1"])
    if case == "empty":
        observed = {}
    elif case == "incomplete":
        observed["source"]["complete"] = False
    elif case == "synthetic":
        observed["source"]["synthetic"] = True
    elif case == "provider":
        observed["source"]["provider"] = "unverified-text"
    elif case == "league":
        observed["league_id"] = "other-fictional-league"
    elif case == "team":
        observed["team_id"] = "team-2"
        observed["rules"]["slot"] = 2
    elif case == "season":
        observed["season"] = 2027
    elif case == "rules":
        observed["rules"]["ir"] = 1
    elif case == "preauthorization":
        observed["source"]["observed_at"] = (datetime.fromisoformat(claimed["authorized_at"]) - timedelta(seconds=1)).isoformat()
    elif case == "season_phase":
        observed["phase"] = "season"
    elif case == "missing_browser":
        observed["source"]["browser"] = None
    elif case == "wrong_clock":
        observed["source"]["browser"]["current_pick"] += 1
    else:
        observed["source"]["browser"]["draft_complete"] = True
    before, history = manager.state(), manager.history()
    with pytest.raises(ValueError):
        browser.reconcile(claimed["proposal_id"], observed)
    assert manager.state() == before and manager.history() == history
    assert proposal_state(manager, claimed["proposal_id"])["status"] == "awaiting_verification"


def test_baseline_pick_history_cannot_change(setup):
    manager, browser = setup
    manager.import_snapshot(platform_snapshot(["p1", "p2", "p3"]), manager.state()[2])
    claimed = authorize(browser, "p4")
    before = manager.state()
    with pytest.raises(PolicyError, match="authorized draft history"):
        browser.reconcile(claimed["proposal_id"], platform_snapshot(["p2", "p1", "p3", "p4"]))
    assert manager.state() == before


def test_newer_stored_history_cannot_roll_back(setup):
    manager, browser = setup
    claimed = authorize(browser)
    manager.import_snapshot(platform_snapshot(["p1", "p2", "p3"]), manager.state()[2])
    before = manager.state()
    with pytest.raises(PolicyError, match="roll back"):
        browser.reconcile(claimed["proposal_id"], platform_snapshot(["p1"]))
    assert manager.state() == before


def test_older_observation_cannot_replace_stored_observation(setup):
    manager, browser = setup
    claimed = authorize(browser)
    older = platform_snapshot(["p1"])
    newer = platform_snapshot(["p1"])
    newer["source"]["observed_at"] = (datetime.fromisoformat(older["source"]["observed_at"]) + timedelta(seconds=1)).isoformat()
    manager.import_snapshot(newer, manager.state()[2])
    before = manager.state()
    with pytest.raises(PolicyError, match="older"):
        browser.reconcile(claimed["proposal_id"], older)
    assert manager.state() == before


def test_pending_pick_prevents_context_abandonment(setup):
    manager, browser = setup
    claimed = authorize(browser)
    before = manager.state()
    with pytest.raises(ValueError, match="pending browser action"):
        manager.import_snapshot(platform_snapshot(league_id="other-fictional-league"), manager.state()[2])
    assert manager.state() == before
    assert browser.reconcile(claimed["proposal_id"], platform_snapshot(["p1"]))["status"] == "confirmed"


def test_failure_during_audit_rolls_back_snapshot_and_proposal(setup, monkeypatch):
    manager, browser = setup
    claimed = authorize(browser)
    before, proposal = manager.state(), proposal_state(manager, claimed["proposal_id"])

    def failed_audit(*args):
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr(manager, "_audit", failed_audit)
    with pytest.raises(RuntimeError, match="audit failure"):
        browser.reconcile(claimed["proposal_id"], platform_snapshot(["p1"]))
    assert manager.state() == before
    assert proposal_state(manager, claimed["proposal_id"]) == proposal


@pytest.mark.parametrize("case", ["paused", "advisory", "stale", "out", "reach", "not_own_turn", "synthetic", "season", "autopick", "wrong_clock", "missing_browser"])
def test_host_path_keeps_hard_policy_checks(setup, case):
    manager, browser = setup
    snapshot, config, revision, config_revision = manager.state()
    snapshot = snapshot.model_dump(mode="json")
    config = config.model_copy(deep=True)
    if case == "paused":
        config.automation.paused = True
    elif case == "advisory":
        config.automation.preset = "advisory"
    elif case == "stale":
        # Store directly to test stale policy without violating the import monotonicity check.
        snapshot["source"]["observed_at"] = (datetime.now(timezone.utc)-timedelta(seconds=60)).isoformat()
    elif case == "out":
        snapshot["players"][0]["availability"] = "OUT"
    elif case == "reach":
        config.limits.max_adp_reach = 0
        snapshot["players"][0]["adp"] = 40
    elif case == "not_own_turn":
        snapshot = platform_snapshot(["p2"])
    elif case == "synthetic":
        snapshot["source"].update(provider="synthetic", synthetic=True)
    elif case == "season":
        snapshot["phase"] = "season"
    elif case == "autopick":
        snapshot["source"]["browser"]["autopick_enabled"] = True
    elif case == "wrong_clock":
        snapshot["source"]["browser"]["current_pick"] = 2
    else:
        snapshot["source"]["browser"] = None
    with manager.transaction() as db:
        db.execute("UPDATE state SET snapshot=?,config=? WHERE id=1", (json.dumps(snapshot), config.model_dump_json()))
    before = manager.state()
    with pytest.raises(PolicyError):
        browser.prepare("p1")
    assert manager.state() == before
    with manager.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM browser_proposals").fetchone()[0] == 0


def test_demo_path_cannot_execute_browser_proposal_or_browser_state(setup):
    manager, browser = setup
    proposal = browser.prepare("p1")
    with pytest.raises(ValueError, match="Unknown proposal"):
        manager.execute(proposal["proposal_id"], confirmation=True)
    with pytest.raises(PolicyError):
        manager.prepare("draft_pick", {"player_id": "p1"})
    assert manager.state()[0].picks == []


def test_read_methods_never_grant_a_click(setup):
    manager, browser = setup
    proposed = browser.prepare("p1")
    assert browser.pending() == []
    assert not browser.get(proposed["proposal_id"])["should_click"]
    browser.authorize(proposed["proposal_id"], confirmation=True)
    pending = browser.pending()
    assert len(pending) == 1 and not pending[0]["should_click"]
    assert not browser.get(proposed["proposal_id"])["should_click"]
    result = browser.reconcile(proposed["proposal_id"], platform_snapshot(["p1"]))
    assert browser.pending() == [] and browser.get(proposed["proposal_id"]) == result


def test_completed_draft_observation_can_settle_final_pick(setup):
    manager, browser = setup
    manager.import_snapshot(platform_snapshot(["p1", "p2", "p3"]), manager.state()[2])
    claimed = authorize(browser, "p4")
    result = browser.reconcile(claimed["proposal_id"], platform_snapshot(["p1", "p2", "p3", "p4"]))
    assert result["status"] == "confirmed"
    assert manager.state()[0].source.browser.draft_complete
