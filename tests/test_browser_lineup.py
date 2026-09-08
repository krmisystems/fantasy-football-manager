"""Browser lineup tests use fictional snapshots and no browser operations."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

import pytest

from fantasy_football_manager.browser_lineup import BrowserLineup, lineup_equivalent, next_lineup_swap
from fantasy_football_manager.models import LeagueSnapshot, ManagerConfig
from fantasy_football_manager.policy import PolicyError
from fantasy_football_manager.store import Manager


BASE = {"RB1": "rb", "WR1": "wr"}
RB_SWAP = {"RB1": "rb-new", "WR1": "wr"}
WR_SWAP = {"RB1": "rb", "WR1": "wr-new"}
FULL_TARGET = {"RB1": "rb-new", "WR1": "wr-new"}


def observation(lineup=None):
    now = datetime.now(timezone.utc)
    return LeagueSnapshot.model_validate({
        "league_id": "fictional-league", "team_id": "team-1", "season": 2026, "week": 2, "phase": "season",
        "source": {"provider": "espn_browser", "synthetic": False, "complete": True, "locks_verified": True,
                   "observed_at": now, "projections_observed_at": now,
                   "browser": {"page_url": "https://fantasy.espn.com/football/team?leagueId=fictional-league&teamId=team-1&scoringPeriodId=2",
                               "league_id": "fictional-league", "team_id": "team-1"}},
        "rules": {"teams": 2, "slot": 1, "rounds": 4, "starters": {"RB": 1, "WR": 1}, "bench": 2},
        "players": [{"id": pid, "name": f"Fictional {pid}", "position": pos, "weekly_projection": points,
                     "weekly_floor": points/2, "weekly_ceiling": points*2, "availability": "ACTIVE"}
                    for pid, pos, points in [("rb", "RB", 10), ("wr", "WR", 10), ("rb-new", "RB", 20),
                                              ("wr-new", "WR", 30), ("other-rb", "RB", 10), ("other-wr", "WR", 10)]],
        "teams": [{"id": "team-1", "name": "Fictional team 1", "slot": 1,
                   "roster_ids": ["rb", "wr", "rb-new", "wr-new"], "lineup": BASE if lineup is None else lineup},
                  {"id": "team-2", "name": "Fictional team 2", "slot": 2,
                   "roster_ids": ["other-rb", "other-wr"], "lineup": {"RB1": "other-rb", "WR1": "other-wr"}}]})


@pytest.fixture
def setup(tmp_path):
    manager = Manager(tmp_path)
    manager.import_snapshot(observation().model_dump(mode="json"))
    manager.update_config(ManagerConfig(automation={"preset": "review"}).model_dump(mode="json"), 0)
    return manager, BrowserLineup(manager)


def claim(browser, lineup=RB_SWAP):
    proposal = browser.prepare(lineup)
    return browser.authorize(proposal["proposal_id"], confirmation=True)


def test_prepare_describes_one_exchange_without_mutation(setup):
    manager, browser = setup
    before = manager.state()
    proposal = browser.prepare(RB_SWAP)
    assert proposal["source_slot"] == "BN" and proposal["destination_slot"] == "RB1"
    assert proposal["player_id"] == "rb-new" and proposal["outgoing_player_id"] == "rb"
    assert proposal["player_name"] == "Fictional rb-new" and proposal["outgoing_player_name"] == "Fictional rb"
    assert proposal["payload"] == {"lineup": RB_SWAP} and not proposal["should_click"]
    assert manager.state() == before
    with manager.transaction() as db:
        row = db.execute("SELECT * FROM browser_lineup_proposals").fetchone()
        assert json.loads(row["baseline"]) == before[0].model_dump(mode="json")


def test_multiple_bench_replacements_are_not_one_exchange(setup):
    _, browser = setup
    with pytest.raises(PolicyError, match="exchange their current players"):
        browser.prepare(FULL_TARGET)


def test_review_confirmation_and_concurrent_claim_are_exact(setup):
    manager, browser = setup
    proposal = browser.prepare(RB_SWAP)
    with pytest.raises(PolicyError, match="confirmation"):
        browser.authorize(proposal["proposal_id"])
    other = BrowserLineup(Manager(manager.data_dir))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda service: service.authorize(proposal["proposal_id"], True), [browser, other]))
    assert sum(result["should_click"] for result in results) == 1
    assert manager.state()[0].own_team().lineup == BASE
    assert len(browser.pending()) == 1
    with pytest.raises(PolicyError, match="awaits verification"):
        browser.prepare(WR_SWAP)


@pytest.mark.parametrize("change", ["state", "config"])
def test_unclaimed_proposal_rejects_changed_revisions(setup, change):
    manager, browser = setup
    proposal = browser.prepare(RB_SWAP)
    if change == "state":
        manager.import_snapshot(observation().model_dump(mode="json"), manager.state()[2])
    else:
        manager.update_config(manager.state()[1].model_dump(mode="json"), manager.state()[3])
    with pytest.raises(PolicyError, match="changed"):
        browser.authorize(proposal["proposal_id"], True)
    assert browser.get(proposal["proposal_id"])["status"] == "pending"


def test_claim_replay_does_not_click_after_config_changes(setup):
    manager, browser = setup
    permit = claim(browser)
    manager.update_config(manager.state()[1].model_dump(mode="json"), manager.state()[3])
    replay = browser.authorize(permit["proposal_id"], True)
    assert replay["status"] == "awaiting_verification" and not replay["should_click"]


@pytest.mark.parametrize("actual, status", [(RB_SWAP, "confirmed"), (WR_SWAP, "conflict")])
def test_reconcile_exact_lineup_or_conflict_atomically(setup, actual, status):
    manager, browser = setup
    permit = claim(browser)
    revision = manager.state()[2]
    observed = observation(actual).model_dump(mode="json")
    result = browser.reconcile(permit["proposal_id"], observed)
    assert result["status"] == status and not result["should_click"]
    assert result["actual_lineup"] == actual and result["revision"] == revision+1
    assert manager.state()[0].model_dump(mode="json") == observed
    assert browser.pending() == []
    after, history = manager.state(), manager.history()
    assert browser.reconcile(permit["proposal_id"], {}) == result
    assert browser.authorize(permit["proposal_id"], True) == result
    assert manager.state() == after and manager.history() == history


def test_unchanged_lineup_stays_unresolved_without_phantom_change(setup):
    manager, browser = setup
    permit = claim(browser)
    before = manager.state()
    result = browser.reconcile(permit["proposal_id"], observation().model_dump(mode="json"))
    assert result["status"] == "awaiting_verification" and not result["should_click"]
    assert manager.state() == before


@pytest.mark.parametrize("bad", ["empty", "week", "rules", "old", "incomplete", "locks"])
def test_invalid_verification_preserves_state_and_claim(setup, bad):
    manager, browser = setup
    permit = claim(browser)
    observed = observation(RB_SWAP).model_dump(mode="json")
    if bad == "empty":
        observed = {}
    elif bad == "week":
        observed["week"] = 3
    elif bad == "rules":
        observed["rules"]["ir"] = 1
    elif bad == "old":
        observed["source"]["observed_at"] = (datetime.fromisoformat(permit["authorized_at"])-timedelta(seconds=1)).isoformat()
    elif bad == "incomplete":
        observed["source"]["complete"] = False
    else:
        observed["source"]["locks_verified"] = False
    before, history = manager.state(), manager.history()
    with pytest.raises(ValueError):
        browser.reconcile(permit["proposal_id"], observed)
    assert manager.state() == before and manager.history() == history
    assert browser.get(permit["proposal_id"])["status"] == "awaiting_verification"


def test_audit_failure_rolls_back_observation_and_receipt(setup, monkeypatch):
    manager, browser = setup
    permit = claim(browser)
    before = manager.state()
    monkeypatch.setattr(manager, "_audit", lambda *args: (_ for _ in ()).throw(RuntimeError("Fictional audit error")))
    with pytest.raises(RuntimeError):
        browser.reconcile(permit["proposal_id"], observation(RB_SWAP).model_dump(mode="json"))
    assert manager.state() == before and browser.get(permit["proposal_id"])["status"] == "awaiting_verification"


@pytest.mark.parametrize("change", ["week", "source", "rules"])
def test_pending_lineup_prevents_context_abandonment(setup, change):
    manager, browser = setup
    permit = claim(browser)
    newer = observation().model_dump(mode="json")
    if change == "week":
        newer["week"] = 3
        newer["source"]["browser"]["page_url"] = newer["source"]["browser"]["page_url"].replace("scoringPeriodId=2", "scoringPeriodId=3")
    elif change == "source":
        newer["source"]["provider"] = "unverified_import"
    else:
        newer["rules"]["ir"] += 1
    before = manager.state()
    with pytest.raises(ValueError, match="pending browser action"):
        manager.import_snapshot(newer, before[2])
    assert manager.state() == before
    assert browser.pending()[0]["proposal_id"] == permit["proposal_id"]
    assert browser.reconcile(permit["proposal_id"], observation(RB_SWAP).model_dump(mode="json"))["status"] == "confirmed"


def test_other_team_roster_change_does_not_block_own_verification(setup):
    manager, browser = setup
    permit = claim(browser)
    fresh = observation()
    fresh.teams[1].roster_ids.remove("other-wr")
    fresh.teams[1].lineup["WR1"] = None
    assert browser.validate_permit(permit, fresh)
    fresh.own_team().lineup = RB_SWAP
    result = browser.reconcile(permit["proposal_id"], fresh.model_dump(mode="json"))
    assert result["status"] == "confirmed" and not browser.pending()
    assert manager.state()[0].teams[1].lineup["WR1"] is None


def test_own_roster_change_after_click_records_conflict_and_actual_state(setup):
    manager, browser = setup
    permit = claim(browser)
    fresh = observation(RB_SWAP)
    fresh.own_team().roster_ids.remove("wr-new")
    with pytest.raises(ValueError, match="rosters"):
        browser.validate_permit(permit, fresh)
    result = browser.reconcile(permit["proposal_id"], fresh.model_dump(mode="json"))
    assert result["status"] == "conflict" and not browser.pending()
    assert "wr-new" not in manager.state()[0].own_team().roster_ids


def test_validate_permit_checks_fresh_lineup_and_exact_names(setup):
    _, browser = setup
    permit = claim(browser)
    assert browser.validate_permit(permit)
    assert browser.validate_permit(permit, observation().model_dump(mode="json"))
    with pytest.raises(PolicyError, match="changed"):
        browser.validate_permit({**permit, "player_name": "Different fictional player"})
    with pytest.raises(PolicyError, match="changed before confirmation"):
        browser.validate_permit(permit, observation(WR_SWAP).model_dump(mode="json"))
    with pytest.raises(PolicyError, match="does not grant"):
        browser.validate_permit(browser.get(permit["proposal_id"]))


def test_helper_chooses_greatest_immediate_gain_then_next_step(setup):
    manager, _ = setup
    snapshot, config, _, _ = manager.state()
    before = snapshot.model_dump(mode="json")
    assert next_lineup_swap(snapshot, config, FULL_TARGET) == WR_SWAP
    changed = snapshot.model_copy(deep=True)
    changed.own_team().lineup = WR_SWAP
    assert next_lineup_swap(changed, config, FULL_TARGET) == FULL_TARGET
    assert snapshot.model_dump(mode="json") == before


def test_helper_respects_minimum_improvement_and_locked_players(setup):
    manager, browser = setup
    snapshot, config, _, _ = manager.state()
    config.limits.min_lineup_improvement = 21
    assert next_lineup_swap(snapshot, config, FULL_TARGET) is None
    config.limits.min_lineup_improvement = 1.5
    next(player for player in snapshot.players if player.id == "wr").locked = True
    assert next_lineup_swap(snapshot, config, FULL_TARGET) == RB_SWAP
    next(player for player in snapshot.players if player.id == "rb-new").locked = True
    assert next_lineup_swap(snapshot, config, FULL_TARGET) is None


def test_starter_exchange_is_supported_only_when_each_step_meets_policy(setup):
    manager, browser = setup
    snapshot, config, revision, config_revision = manager.state()
    for player in snapshot.players:
        player.eligible_positions = ["RB", "WR"]
    manager.import_snapshot(snapshot.model_dump(mode="json"), revision)
    target = {"RB1": "wr", "WR1": "rb"}
    assert next_lineup_swap(snapshot, config, target) is None
    config.limits.min_lineup_improvement = 0
    manager.update_config(config.model_dump(mode="json"), config_revision)
    proposal = browser.prepare(target)
    assert {proposal["source_slot"], proposal["destination_slot"]} == {"RB1", "WR1"}
    assert next_lineup_swap(snapshot, config, target) == target


def repeated_rb_snapshot():
    snapshot = observation()
    snapshot.rules.starters = {"RB": 2}
    for player in snapshot.players:
        player.position = "RB"
        player.eligible_positions = ["RB"]
    for team in snapshot.teams:
        team.lineup = {"RB1": team.lineup["RB1"], "RB2": team.lineup["WR1"]}
    return LeagueSnapshot.model_validate(snapshot.model_dump())


def test_equivalent_slot_order_does_not_create_or_conflict_with_exchange(setup):
    manager, browser = setup
    snapshot = repeated_rb_snapshot()
    manager.import_snapshot(snapshot.model_dump(mode="json"), manager.state()[2])
    target = {"RB1": "wr", "RB2": "rb-new"}
    proposal = browser.prepare(target)
    assert proposal["lineup"] == {"RB1": "rb-new", "RB2": "wr"}
    permit = browser.authorize(proposal["proposal_id"], True)
    fresh = snapshot.model_copy(deep=True)
    fresh.own_team().lineup = {"RB1": "wr", "RB2": "rb"}
    fresh.source.observed_at = datetime.now(timezone.utc)
    assert browser.validate_permit(permit, fresh.model_dump(mode="json"))
    fresh.own_team().lineup = target
    result = browser.reconcile(proposal["proposal_id"], fresh.model_dump(mode="json"))
    assert result["status"] == "confirmed"
    assert manager.state()[0].own_team().lineup == target


def test_helper_ignores_within_group_permutations(setup):
    manager, _ = setup
    snapshot = repeated_rb_snapshot()
    config = manager.state()[1]
    config.limits.min_lineup_improvement = 0
    assert next_lineup_swap(snapshot, config, {"RB1": "wr", "RB2": "rb"}) is None
    assert lineup_equivalent(snapshot, snapshot.own_team().lineup, {"RB1": "wr", "RB2": "rb"})


def test_flex_is_not_interchangeable_with_primary_position():
    snapshot = observation()
    snapshot.rules.starters = {"RB": 1, "FLEX": 1}
    assert not lineup_equivalent(snapshot, {"RB1": "rb", "FLEX1": "wr"}, {"RB1": "wr", "FLEX1": "rb"})
