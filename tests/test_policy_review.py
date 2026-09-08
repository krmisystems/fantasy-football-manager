"""Synthetic regression checks from the independent action-policy review."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from fantasy_football_manager.models import (
    Budget, LeagueSnapshot, ManagerConfig, Player, Rules, Source, Team,
)
from fantasy_football_manager.policy import PolicyError, check_action
from fantasy_football_manager.store import Manager


def fixture(*, vacancy=False):
    now = datetime.now(timezone.utc)
    players = [Player(id="starter", name="Synthetic starter", position="WR", weekly_projection=10, availability="ACTIVE"),
               Player(id="bench", name="Synthetic bench", position="RB" if vacancy else "WR",
                      weekly_projection=None if vacancy else 2, availability="OUT" if vacancy else "ACTIVE"),
               Player(id="available", name="Synthetic available", position="RB" if vacancy else "WR",
                      weekly_projection=8 if vacancy else 20, availability="ACTIVE"),
               Player(id="opponent", name="Synthetic opponent", position="WR", weekly_projection=15, availability="ACTIVE")]
    rules = Rules(teams=2, slot=1, rounds=2, starters={"WR": 1, "RB": 1} if vacancy else {"WR": 1}, bench=0 if vacancy else 1)
    state = LeagueSnapshot(league_id="policy-review", team_id="team-a", season=2026, week=1,
                           source=Source(provider="synthetic", synthetic=True, complete=True, locks_verified=True,
                                         observed_at=now, projections_observed_at=now), rules=rules, players=players,
                           teams=[Team(id="team-a", name="Synthetic A", slot=1, roster_ids=["starter", "bench"],
                                       lineup={"WR1": "starter", **({"RB1": "bench"} if vacancy else {})}),
                                  Team(id="team-b", name="Synthetic B", slot=2, roster_ids=["opponent"], lineup={"WR1": "opponent"})],
                           budget=Budget(balance=100, pending_amount=0, pending_moves=0))
    config = ManagerConfig()
    config.automation.preset = "review"
    config.limits.drop_mode = "any_unprotected"
    config.limits.min_lineup_improvement = 5
    return state, config


@pytest.mark.parametrize("action", ["free_agent_add", "waiver_claim"])
def test_acquisition_cannot_bypass_minimum_lineup_improvement(action):
    state, config = fixture()
    state.players[2].weekly_projection = 1
    with pytest.raises(PolicyError):
        check_action(state, config, action, {"player_id": "available", "drop_id": "starter"})


def test_bench_upside_does_not_override_a_positive_improvement_limit():
    state, config = fixture()
    config.strategy.waiver = "bench_upside"
    state.players[2].weekly_projection = 3
    for p in state.players:
        p.weekly_ceiling = 50 if p.id == "available" else 15
    with pytest.raises(PolicyError):
        check_action(state, config, "free_agent_add", {"player_id": "available", "drop_id": "bench"})


def test_acquisition_can_repair_a_vacancy_with_known_player_projections():
    state, config = fixture(vacancy=True)
    decision = check_action(state, config, "free_agent_add", {"player_id": "available", "drop_id": "bench"})
    assert decision["mode"] == "review"


def test_acquisition_must_leave_a_complete_legal_weekly_lineup():
    state, config = fixture(vacancy=True)
    state.players[0].availability = "OUT"
    with pytest.raises(PolicyError):
        check_action(state, config, "free_agent_add", {"player_id": "available", "drop_id": "bench"})


@pytest.mark.parametrize("projection_stamp", ["stale", "unknown"])
def test_execution_policy_requires_a_known_fresh_projection_timestamp(projection_stamp):
    state, config = fixture()
    config.limits.min_lineup_improvement = 0
    state.source.projections_observed_at = None if projection_stamp == "unknown" else datetime.now(timezone.utc) - timedelta(days=7)
    with pytest.raises(PolicyError):
        check_action(state, config, "set_lineup", {"lineup": {"WR1": "starter"}})


@pytest.mark.parametrize("status", ["PUP", "EXEMPT", "INJURED RESERVE", "UNRECOGNIZED"])
def test_execution_does_not_accept_definitive_or_unrecognized_unavailable_status(status):
    state, config = fixture()
    state.players[1].availability = status
    state.players[1].weekly_projection = 30
    with pytest.raises(PolicyError):
        check_action(state, config, "set_lineup", {"lineup": {"WR1": "bench"}})


def test_draft_feasibility_accounts_for_remaining_position_capacity():
    now = datetime.now(timezone.utc)
    rules = Rules(teams=2, slot=1, rounds=2, starters={"RB": 1, "FLEX": 1}, bench=0,
                  flex_eligible=["RB"], caps={"RB": 1, "QB": 4})
    players = [Player(id="rb-a", name="Synthetic RB A", position="RB", availability="ACTIVE", projection=100),
               Player(id="rb-b", name="Synthetic RB B", position="RB", availability="ACTIVE", projection=90),
               Player(id="qb", name="Synthetic QB", position="QB", availability="ACTIVE", projection=80)]
    state = LeagueSnapshot(league_id="impossible-draft", team_id="team-a", season=2026, phase="draft",
                           source=Source(provider="synthetic", synthetic=True, observed_at=now, projections_observed_at=now),
                           rules=rules, players=players,
                           teams=[Team(id="team-a", name="Synthetic A", slot=1), Team(id="team-b", name="Synthetic B", slot=2)])
    _, config = fixture()
    with pytest.raises(PolicyError):
        check_action(state, config, "draft_pick", {"player_id": "rb-a"})


def manager_fixture(tmp_path):
    state, config = fixture()
    manager = Manager(tmp_path)
    manager.import_snapshot(state.model_dump(mode="json"))
    manager.update_config(config.model_dump(mode="json"), expected_revision=0)
    return manager


def test_failed_commit_rolls_back_snapshot_proposal_result_and_audit(tmp_path, monkeypatch):
    manager = manager_fixture(tmp_path)
    prepared = manager.prepare("free_agent_add", {"player_id": "available", "drop_id": "bench"})
    before, _, revision, _ = manager.require_state()
    audit_before = manager.history()
    original_audit = manager._audit

    def fail_audit(*args):
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr(manager, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="Synthetic audit failure"):
        manager.execute(prepared["proposal_id"], confirmation=True)
    after, _, new_revision, _ = manager.require_state()
    assert new_revision == revision
    assert after.model_dump() == before.model_dump()
    assert manager.history() == audit_before
    monkeypatch.setattr(manager, "_audit", original_audit)
    assert manager.execute(prepared["proposal_id"], confirmation=True)["idempotent_replay"] is False


def test_config_revision_invalidates_a_prepared_action(tmp_path):
    manager = manager_fixture(tmp_path)
    prepared = manager.prepare("free_agent_add", {"player_id": "available", "drop_id": "bench"})
    _, config, _, revision = manager.require_state()
    config.limits.protected_ids = ["bench"]
    manager.update_config(config.model_dump(mode="json"), revision)
    with pytest.raises(PolicyError):
        manager.execute(prepared["proposal_id"], confirmation=True)


def test_two_connections_execute_one_proposal_exactly_once(tmp_path):
    manager = manager_fixture(tmp_path)
    prepared = manager.prepare("free_agent_add", {"player_id": "available", "drop_id": "bench"})
    second = Manager(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(instance.execute, prepared["proposal_id"], True) for instance in (manager, second)]
        results = [job.result() for job in jobs]
    assert sorted(r["idempotent_replay"] for r in results) == [False, True]
    state, _, revision, _ = manager.require_state()
    assert revision == prepared["revision"] + 1
    assert state.budget.roster_moves_week == 1
    assert state.own_team().roster_ids.count("available") == 1


@pytest.mark.parametrize("provider,synthetic", [("espn", True), ("synthetic", False)])
def test_execution_requires_both_synthetic_scope_markers(provider, synthetic):
    state, config = fixture()
    state.source.provider, state.source.synthetic = provider, synthetic
    with pytest.raises(PolicyError):
        check_action(state, config, "free_agent_add", {"player_id": "available", "drop_id": "bench"})
