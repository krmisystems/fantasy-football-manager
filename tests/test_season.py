"""Synthetic checks for weekly assignments and roster proposals."""

from datetime import datetime, timedelta, timezone
from itertools import permutations
import random

import pytest

from fantasy_football_manager.models import (
    Budget, LeagueSnapshot, ManagerConfig, Player, Rules, Source, Team,
)
from fantasy_football_manager.season import power_rankings, rank_waivers, recommend_lineup


def player(pid, position, points, **kwargs):
    return Player(id=pid, name=f"Synthetic {pid}", position=position,
                  weekly_projection=points, availability="ACTIVE", **kwargs)


def snapshot(players, own_ids, lineup=None, *, starters=None, bench=2, reserve=None,
             other_ids=None, other_lineup=None, caps=None):
    starters = starters or {"RB": 1, "WR": 1, "FLEX": 1}
    options = {"teams": 2, "slot": 1, "rounds": sum(starters.values()) + bench,
               "starters": starters, "bench": bench}
    if caps is not None:
        options["caps"] = caps
    now = datetime.now(timezone.utc)
    return LeagueSnapshot(
        league_id="synthetic-league", team_id="synthetic-a", season=2026, week=1,
        source=Source(provider="synthetic", observed_at=now, projections_observed_at=now,
                      complete=True, locks_verified=True, synthetic=True),
        rules=Rules(**options), players=players,
        teams=[Team(id="synthetic-a", name="Synthetic A", slot=1, roster_ids=own_ids,
                    reserve_ids=reserve or [], lineup=lineup or {}),
               Team(id="synthetic-b", name="Synthetic B", slot=2, roster_ids=other_ids or [],
                    lineup=other_lineup or {})],
        budget=Budget(balance=100, pending_amount=0, pending_moves=0),
    )


def config(**limits):
    result = ManagerConfig()
    result.limits = result.limits.model_copy(update={"drop_mode": "any_unprotected", **limits})
    return result


def test_exact_assignment_reserves_dual_eligible_player_for_required_slot():
    state = snapshot([player("dual", "RB", 20, eligible_positions=["RB", "WR"]),
                      player("rb-a", "RB", 19), player("rb-b", "RB", 18)],
                     ["dual", "rb-a", "rb-b"])
    result = recommend_lineup(state, config())
    assert result["status"] == "ok"
    assert result["lineup"]["WR1"] == "dual"
    assert len(set(result["lineup"].values())) == 3
    assert result["projected_points"] == 57


def test_locked_unavailable_starter_keeps_slot_and_locked_bench_cannot_enter():
    state = snapshot([player("locked-out", "RB", 0, locked=True),
                      player("locked-bench", "WR", 40, locked=True),
                      player("wr", "WR", 12), player("rb", "RB", 15)],
                     ["locked-out", "locked-bench", "wr", "rb"],
                     {"RB1": "locked-out", "WR1": "wr", "FLEX1": "rb"})
    state.players[0].availability = "OUT"
    result = recommend_lineup(state, config())
    assert result["lineup"] == {"RB1": "locked-out", "WR1": "wr", "FLEX1": "rb"}
    assert "locked-bench" not in result["lineup"].values()
    assert result["projected_points"] == 27
    assert result["warnings"]


def test_flex_eligibility_excludes_high_scoring_quarterback():
    state = snapshot([player("rb", "RB", 10), player("wr", "WR", 11),
                      player("te", "TE", 12), player("qb", "QB", 40)],
                     ["rb", "wr", "te", "qb"])
    result = recommend_lineup(state, config())
    assert result["lineup"]["FLEX1"] == "te"
    assert result["projected_points"] == 33


def test_out_reserve_and_bye_players_do_not_enter_unlocked_lineup():
    roster = [player("rb", "RB", 10), player("wr", "WR", 11), player("te", "TE", 12),
              player("out", "WR", 100), player("bye", "WR", 100, bye=1),
              player("reserve", "WR", 100)]
    roster[3].availability = "OUT"
    state = snapshot(roster, ["rb", "wr", "te", "out", "bye"], reserve=["reserve"])
    result = recommend_lineup(state, config())
    assert set(result["lineup"].values()) == {"rb", "wr", "te"}


def test_inactive_player_is_excluded_and_doubtful_player_is_flagged():
    state = snapshot([player("inactive", "WR", 30), player("doubtful", "WR", 20), player("active", "WR", 10)],
                     ["inactive", "doubtful", "active"], starters={"WR": 1}, bench=2)
    state.players[0].availability = "INACTIVE"
    state.players[1].availability = "DOUBTFUL"
    result = recommend_lineup(state, config())
    assert result["lineup"] == {"WR1": "doubtful"}
    assert result["availability_flags"] == [{"player_id": "doubtful", "availability": "DOUBTFUL"}]


def test_missing_weekly_value_never_uses_season_projection():
    state = snapshot([player("rb", "RB", 10), player("wr", "WR", 11),
                      player("unknown", "TE", None, projection=1000)], ["rb", "wr", "unknown"])
    result = recommend_lineup(state, config())
    assert result["status"] == "incomplete"
    assert result["projected_points"] is None
    assert result["missing_projections"] == [{"player_id": "unknown", "fields": ["weekly_projection"]}]


@pytest.mark.parametrize("strategy,expected,score", [("floor", "safe", 12), ("upside", "risky", 15)])
def test_floor_and_upside_use_explicit_weekly_bounds(strategy, expected, score):
    state = snapshot([player("safe", "WR", 12, weekly_floor=10, weekly_ceiling=15),
                      player("risky", "WR", 15, weekly_floor=2, weekly_ceiling=30)],
                     ["safe", "risky"], starters={"WR": 1}, bench=1)
    settings = config()
    settings.strategy.season = strategy
    result = recommend_lineup(state, settings)
    assert result["lineup"] == {"WR1": expected}
    assert result["projected_points"] == score
    assert result["objective_points"] == (10 if strategy == "floor" else 30)
    state.players[0].weekly_floor = None
    settings.strategy.season = "floor"
    assert recommend_lineup(state, settings)["status"] == "incomplete"


def test_solver_matches_exhaustive_assignments_with_negative_scores():
    rng = random.Random(913)
    slots = {"RB1": {"RB"}, "WR1": {"WR"}, "FLEX1": {"RB", "WR", "TE"}}
    for _ in range(12):
        players = [player(f"p{i}", "RB" if i % 2 == 0 else "WR", rng.randint(-10, 25),
                          eligible_positions=rng.choice([["RB"], ["WR"], ["RB", "WR"], ["TE"]]))
                   for i in range(5)]
        state = snapshot(players, [p.id for p in players])
        choices = [sum(p.weekly_projection for p in assignment)
                   for assignment in permutations(players, 3)
                   if all(set(p.eligible_positions) & eligible
                          for p, eligible in zip(assignment, slots.values()))]
        result = recommend_lineup(state, config())
        if choices:
            assert result["projected_points"] == max(choices)
        else:
            assert result["status"] == "incomplete"


def waiver_fixture():
    return snapshot([player("starter", "WR", 10), player("bench", "WR", 2),
                     player("available", "WR", 20), player("owned-elsewhere", "WR", 99),
                     player("reserve-elsewhere", "WR", 100)],
                    ["starter", "bench"], {"WR1": "starter"}, starters={"WR": 1}, bench=1,
                    other_ids=["owned-elsewhere"], other_lineup={"WR1": "owned-elsewhere"},
                    reserve=[]).model_copy()


def test_waiver_respects_protection_allowlist_ownership_and_unique_adds():
    state = waiver_fixture()
    state.teams[1].reserve_ids = ["reserve-elsewhere"]
    settings = config(protected_ids=["starter"], drop_mode="listed_only", allowed_drop_ids=["starter", "bench"])
    result = rank_waivers(state, settings)
    assert result["status"] == "ok"
    assert len(result["recommendations"]) == 1
    proposal = result["recommendations"][0]
    assert proposal["add_player_id"] == "available"
    assert proposal["drop_player_id"] == "bench"
    assert proposal["improvement"] == 10
    assert proposal["suggested_bid"] is None
    settings.limits.allowed_drop_ids = ["starter"]
    assert not rank_waivers(state, settings)["recommendations"]


def test_waiver_uses_optimal_baseline_not_a_poor_current_lineup():
    state = waiver_fixture()
    state.teams[0].lineup = {"WR1": "bench"}
    result = rank_waivers(state, config())
    candidate = next(x for x in result["recommendations"] if x["add_player_id"] == "available")
    assert result["baseline_projected_points"] == 10
    assert candidate["improvement"] == 10


def test_waiver_caps_require_a_compatible_drop_even_with_open_roster_space():
    state = snapshot([player("wr", "WR", 10), player("rb", "RB", 4), player("new", "WR", 20)],
                     ["wr", "rb"], {"WR1": "wr"}, starters={"WR": 1}, bench=2,
                     caps={"WR": 1, "RB": 8})
    result = rank_waivers(state, config(protected_ids=["wr"]))
    assert not result["recommendations"]
    result = rank_waivers(state, config())
    assert result["recommendations"][0]["drop_player_id"] == "wr"


def test_waiver_move_and_faab_limits_include_pending_commitments():
    state = waiver_fixture()
    state.budget.pending_amount = 8
    state.budget.spent_week = 7
    result = rank_waivers(state, config())
    assert result["effective_limits"]["maximum_faab_bid"] == 5
    state.budget.pending_moves = 3
    assert rank_waivers(state, config())["status"] == "blocked"
    state.budget.pending_moves = None
    assert rank_waivers(state, config())["status"] == "incomplete"


def test_missing_free_agent_data_is_visible_and_does_not_become_zero():
    state = waiver_fixture()
    state.players[2].weekly_projection = None
    result = rank_waivers(state, config())
    assert result["status"] == "incomplete"
    assert any(x["player_id"] == "available" for x in result["missing_projections"])
    assert all(x["add_player_id"] != "available" for x in result["recommendations"])


def test_waiver_repairs_a_vacant_position_without_zeroing_missing_projections():
    state = snapshot([player("wr", "WR", 10), player("out", "RB", None), player("new", "RB", 8)],
                     ["wr", "out"], {"WR1": "wr", "RB1": "out"},
                     starters={"RB": 1, "WR": 1}, bench=0)
    state.players[1].availability = "OUT"
    result = rank_waivers(state, config(protected_ids=["wr"]))
    assert result["status"] == "ok"
    assert result["baseline_projected_points"] == 10
    assert result["baseline_unfilled_slots"] == ["RB1"]
    proposal = result["recommendations"][0]
    assert proposal["add_player_id"] == "new"
    assert proposal["drop_player_id"] == "out"
    assert proposal["improvement"] == 8
    assert proposal["lineup"] == {"RB1": "new", "WR1": "wr"}


def test_bench_upside_changes_ranking_with_explicit_ceiling_data():
    state = snapshot([player("starter", "WR", 20, weekly_ceiling=30),
                      player("bench", "WR", 5, weekly_ceiling=10),
                      player("floor", "WR", 21, weekly_ceiling=25),
                      player("ceiling", "WR", 20, weekly_ceiling=50)],
                     ["starter", "bench"], {"WR1": "starter"}, starters={"WR": 1}, bench=1)
    settings = config(protected_ids=["starter"], min_lineup_improvement=0)
    assert rank_waivers(state, settings)["recommendations"][0]["add_player_id"] == "floor"
    settings.strategy.waiver = "bench_upside"
    assert rank_waivers(state, settings)["recommendations"][0]["add_player_id"] == "ceiling"


def test_locked_bench_player_cannot_be_dropped_even_when_allowlisted():
    state = waiver_fixture()
    state.players[1].locked = True
    settings = config(protected_ids=["starter"], drop_mode="listed_only", allowed_drop_ids=["bench"])
    assert rank_waivers(state, settings)["recommendations"] == []


def test_power_rankings_require_all_teams_and_preserve_inputs():
    state = waiver_fixture()
    before = state.model_dump()
    result = power_rankings(state, config())
    assert [(x["team_id"], x["rank"]) for x in result["rankings"]] == [("synthetic-b", 1), ("synthetic-a", 2)]
    assert result["championship_odds"] is None
    assert state.model_dump() == before
    state.players[3].weekly_projection = None
    result = power_rankings(state, config())
    assert result["status"] == "incomplete"
    assert all(x["rank"] is None for x in result["rankings"])


def test_unverified_locks_and_stale_data_block_complete_recommendations():
    state = waiver_fixture()
    state.source.locks_verified = False
    assert recommend_lineup(state, config())["status"] == "incomplete"
    state.source.locks_verified = True
    state.source.observed_at -= timedelta(minutes=10)
    result = recommend_lineup(state, config())
    assert result["status"] == "incomplete"
    assert result["source"]["stale"]
