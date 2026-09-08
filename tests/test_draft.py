"""Draft regression tests use synthetic players and league settings."""

from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from fantasy_football_manager import legacy_engine
from fantasy_football_manager.draft import recommend_draft
from fantasy_football_manager.models import LeagueSnapshot, ManagerConfig, Rules


def player(pid, position, projection=100, adp=1, **extra):
    return {"id": pid, "name": f"Synthetic {pid}", "position": position,
            "projection": projection, "adp": adp, "availability": "ACTIVE", **extra}


def snapshot(players=None, selected=(), rules=None, source=None):
    rules = rules or Rules(teams=2, slot=1, rounds=1, starters={}, bench=1)
    players = players or [player("rb", "RB", 100), player("wr", "WR", 110)]
    picks = [{"pick_no": number, "player_id": pid,
              "slot": legacy_engine.draft_slot(number, rules.teams, rules.snake)}
             for number, pid in enumerate(selected, 1)]
    now = datetime.now(timezone.utc)
    return LeagueSnapshot(
        league_id="synthetic-league", team_id=f"team-{rules.slot}", season=2026,
        phase="draft", source={"provider": "synthetic", "synthetic": True,
                               "observed_at": now, "projections_observed_at": now,
                               **(source or {})}, rules=rules, players=players, picks=picks,
        teams=[{"id": f"team-{slot}", "name": f"Synthetic team {slot}", "slot": slot,
                "roster_ids": [p["player_id"] for p in picks if p["slot"] == slot]}
               for slot in range(1, rules.teams + 1)])


def strategy(name="balanced_value", **limits):
    return ManagerConfig(strategy={"draft": name}, limits=limits)


def test_strategy_changes_actual_recommendation_without_changing_projection():
    state = snapshot()
    results = {name: recommend_draft(state, strategy(name), trials=12, seed=7)
               for name in sorted(legacy_engine.DRAFT_STRATEGIES)}
    assert {name: value["recommendations"][0]["position"] for name, value in results.items()} == {
        "balanced_value": "RB", "rb_priority": "RB", "wr_priority": "WR",
        "hero_rb": "RB", "zero_rb": "WR"}
    assert results["rb_priority"]["recommendations"][0]["score"] > results["balanced_value"]["recommendations"][0]["score"]
    for result in results.values():
        assert {row["id"]: row["projection"] for row in result["recommendations"]} == {"rb": 100, "wr": 110}
        assert result["trials"] == 12
        assert result["read_only"]


def test_hero_rb_favors_other_positions_after_first_rb():
    rules = Rules(teams=2, slot=1, rounds=2, starters={}, bench=2)
    state = snapshot([player("owned", "RB", 300), player("other-a", "QB", 100),
                      player("other-b", "TE", 100), player("rb", "RB", 280),
                      player("wr", "WR", 200)], ["owned", "other-a", "other-b"], rules)
    balanced = recommend_draft(state, strategy(), trials=20, seed=8)
    hero = recommend_draft(state, strategy("hero_rb"), trials=20, seed=8)
    assert balanced["recommendations"][0]["id"] == "rb"
    assert hero["recommendations"][0]["id"] == "wr"
    assert hero["strategy_weights"]["RB"] == {"first_player": 1.25, "additional_players": 0.7}


def test_seed_reproduces_results_and_does_not_mutate_inputs():
    rules = Rules(teams=2, slot=2, rounds=3, starters={"RB": 1, "WR": 1}, bench=1)
    pool = [player(f"{pos}-{number}", pos, 240-number*9, number*2 + offset)
            for offset, pos in enumerate(["RB", "WR"], 1) for number in range(1, 10)]
    state = snapshot(pool, rules=rules)
    config = strategy("wr_priority")
    before = state.model_dump(mode="json"), config.model_dump(mode="json")
    first = recommend_draft(state, config, trials=10, seed=22)
    second = recommend_draft(state, config, trials=10, seed=22)
    assert first["recommendations"] == second["recommendations"]
    assert first["analysis_fingerprint"] == second["analysis_fingerprint"]
    assert before == (state.model_dump(mode="json"), config.model_dump(mode="json"))
    assert first["my_next_pick"] == 2 and first["following_pick"] == 3
    for row in first["recommendations"]:
        assert row["availability_at_pick"] == row["availability_count"] / 10
        assert row["score"] == row["score_sum"] / row["simulation_count"]
        assert row["survival_next_pick"] == row["survival_count"] / row["availability_count"]


@pytest.mark.parametrize("source, expected", [
    ({"observed_at": datetime.now(timezone.utc)-timedelta(seconds=60)}, "stale_snapshot"),
    ({"complete": False}, "incomplete_snapshot"),
])
def test_invalid_freshness_skips_simulation(monkeypatch, source, expected):
    monkeypatch.setattr(legacy_engine, "run_batch", lambda *a, **kw: pytest.fail("Skipped analysis ran a simulation."))
    result = recommend_draft(snapshot(source=source), strategy(), trials=25)
    assert result["status"] == expected
    assert result["trials"] == 0 and result["requested_trials"] == 25
    assert result["recommendations"] == []
    assert result["warnings"]


@pytest.mark.parametrize("selected, draft_complete", [(["rb"], False), (["rb", "wr"], True)])
def test_complete_roster_reports_zero_work(monkeypatch, selected, draft_complete):
    monkeypatch.setattr(legacy_engine, "run_batch", lambda *a, **kw: pytest.fail("A complete roster ran a simulation."))
    result = recommend_draft(snapshot(selected=selected), strategy(), trials=50)
    assert result["status"] == "roster_complete" and result["completed"]
    assert result["draft_complete"] is draft_complete
    assert result["trials"] == 0 and result["recommendations"] == []


def test_no_projections_reports_zero_work():
    result = recommend_draft(snapshot([player("rb", "RB", 0)]), strategy())
    assert result["status"] == "missing_projections" and result["trials"] == 0


@pytest.mark.parametrize("name", sorted(legacy_engine.DRAFT_STRATEGIES))
def test_all_strategies_respect_caps_and_custom_flex_completion(name):
    rules = Rules(teams=2, slot=1, rounds=4, starters={"QB": 1, "RB": 1, "WR": 1, "FLEX": 1},
                  caps={"QB": 2, "RB": 1, "WR": 1}, flex_eligible=["QB"], bench=0)
    pool = [player("own-qb", "QB", 250), player("other-qb", "QB", 240),
            player("other-rb", "RB", 230), player("own-rb", "RB", 220),
            player("own-wr", "WR", 210), player("other-wr", "WR", 200),
            player("other-flex", "QB", 190), player("needed-qb", "QB", 80),
            player("over-cap-rb", "RB", 500), player("over-cap-wr", "WR", 500)]
    state = snapshot(pool, [row["id"] for row in pool[:7]], rules)
    result = recommend_draft(state, strategy(name), trials=4, seed=2)
    assert [row["id"] for row in result["recommendations"]] == ["needed-qb"]
    assert result["recommendations"][0]["survival_next_pick"] is None
    assert result["recommendations"][0]["availability_at_pick"] == 1
    own_counts = Counter(p.position for p in state.players if p.id in state.own_team().roster_ids)
    assert legacy_engine.minimum_missing(own_counts, rules.starters, rules.flex_eligible) == 1
    own_counts["QB"] += 1
    assert legacy_engine.minimum_missing(own_counts, rules.starters, rules.flex_eligible) == 0


def test_reach_limit_filters_suggestions_and_reports_blocked_candidates():
    state = snapshot([player("in-limit", "RB", 80, 1), player("reach", "WR", 500, 30)])
    result = recommend_draft(state, strategy(max_adp_reach=5), trials=4)
    assert [row["id"] for row in result["recommendations"]] == ["in-limit"]
    assert [row["id"] for row in result["blocked_candidates"]] == ["reach"]
    blocked = recommend_draft(state, strategy(max_adp_reach=0), trials=4)
    assert blocked["recommendations"][0]["adp_reach"] == 0


def test_reach_limit_blocks_all_without_claiming_trials():
    state = snapshot([player("reach", "WR", 500, 30)])
    result = recommend_draft(state, strategy(max_adp_reach=0), trials=7)
    assert result["status"] == "blocked_by_limits"
    assert result["trials"] == 0 and result["recommendations"] == []


def test_following_selection_also_respects_reach_limit(monkeypatch):
    calls = []
    original = legacy_engine._Market.best_addition

    def checked(market, available, roster, counts, replacement, pick_no):
        addition = original(market, available, roster, counts, replacement, pick_no)
        calls.append(addition)
        if addition:
            assert addition.adp - pick_no <= market.max_adp_reach
        return addition

    monkeypatch.setattr(legacy_engine._Market, "best_addition", checked)
    rules = Rules(teams=2, slot=1, rounds=2, starters={}, bench=2)
    pool = [player(f"rb-{n}", "RB", 100, n) for n in range(1, 6)] + [player("large-reach", "WR", 1000, 100)]
    result = recommend_draft(snapshot(pool, rules=rules), strategy(max_adp_reach=3), trials=4)
    assert calls and result["trials"] == 4
    assert all(addition is None or addition.id != "large-reach" for addition in calls)


def test_dst_and_k_wait_until_final_three_own_selections():
    rules = Rules(teams=2, slot=1, rounds=5, starters={"RB": 1, "DST": 1, "K": 1}, bench=2)
    pool = [player(f"rb-{n}", "RB", 100, n+10) for n in range(10)]
    pool += [player("dst", "DST", 1000, 1), player("k", "K", 1000, 2)]
    result = recommend_draft(snapshot(pool, rules=rules), strategy(), trials=4)
    assert {row["position"] for row in result["recommendations"]} == {"RB"}


def test_three_projected_options_per_position_survive_candidate_shortlist():
    pool = [player(f"wr-{n}", "WR", 200-n, n+1) for n in range(40)]
    pool += [player(f"rb-{n}", "RB", 20-n, 100+n) for n in range(4)]
    result = recommend_draft(snapshot(pool), strategy("wr_priority"), trials=2)
    ids = {row["id"] for row in result["recommendations"]}
    assert {"rb-0", "rb-1", "rb-2"} <= ids


def test_backup_qb_cannot_use_hindsight_to_become_starter():
    roster = [player("starter", "QB", 300), player("backup", "QB", 200)]
    outcomes = {"starter": 100, "backup": 400}
    utility = legacy_engine.roster_utility(roster, {"QB": 1}, {"QB": 150}, outcomes)
    assert utility == pytest.approx((400 - 150 * .7) * .07)


def test_fingerprint_changes_with_strategy_or_projection():
    state = snapshot()
    first = recommend_draft(state, strategy(), trials=2)
    other_strategy = recommend_draft(state, strategy("wr_priority"), trials=2)
    changed = state.model_copy(deep=True)
    changed.players[0].projection += 1
    other_projection = recommend_draft(changed, strategy(), trials=2)
    assert len({item["analysis_fingerprint"] for item in [first, other_strategy, other_projection]}) == 3


def test_unavailable_projection_timestamp_and_extra_eligibility_are_explicit():
    state = snapshot([player("hybrid", "RB", eligible_positions=["RB", "WR"])],
                     source={"projections_observed_at": None})
    result = recommend_draft(state, strategy(), trials=2)
    assert result["projection_age_seconds"] is None
    assert any("observation time" in warning for warning in result["warnings"])
    assert any("primary positions" in warning for warning in result["warnings"])


@pytest.mark.parametrize("trials", [0, 501, 1.5, True])
def test_invalid_trial_request_is_rejected(trials):
    with pytest.raises(ValueError, match="trial count"):
        recommend_draft(snapshot(), strategy(), trials=trials)


def test_rules_reject_caps_that_cannot_fill_the_full_roster():
    with pytest.raises(ValueError, match="cap|Cap"):
        Rules(teams=2, rounds=3, starters={"RB": 1}, bench=2, caps={"RB": 2})


def test_merge_rejects_new_projection_fingerprint():
    first = recommend_draft(snapshot(), strategy(), trials=2)
    changed = dict(first, analysis_fingerprint="different-projection-inputs")
    with pytest.raises(ValueError, match="inputs change"):
        legacy_engine.merge_batches(first, changed)
