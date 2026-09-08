"""Test season normalization with fictional payloads and no network requests."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from fantasy_football_manager.espn_data import ESPNDataError
from fantasy_football_manager.espn_season_data import (
    normalize_espn_season, season_player_read_headers, season_player_read_url, season_read_url,
)
from fantasy_football_manager.models import ManagerConfig
from fantasy_football_manager.season import recommend_lineup


URL = "https://fantasy.espn.com/football/team?leagueId=123&teamId=1&seasonId=2026"


def projection(week, stats, *, season=2026, source=1):
    return {"seasonId": season, "statSourceId": source, "statSplitTypeId": 1 if week else 0,
            "scoringPeriodId": week, "stats": stats, "appliedTotal": 9999}


def fixture():
    league = {"id": 123, "seasonId": 2026, "scoringPeriodId": 1,
              "settings": {"size": 2,
                           "draftSettings": {"type": "SNAKE", "pickOrder": [1, 2], "keeperCount": 0},
                           "rosterSettings": {"lineupSlotCounts": {"2": 1, "23": 1, "20": 1, "21": 1},
                                              "positionLimits": {"1": 1, "2": 3, "3": 3, "4": 1, "5": 1, "16": 1}},
                           "scoringSettings": {"scoringType": "H2H_POINTS", "scoringItems": [
                               {"statId": 53, "points": 1, "pointsOverrides": {"4": 1.5}},
                               {"statId": 24, "points": .1, "pointsOverrides": {}}]}},
              "draftDetail": {"drafted": True, "picks": []},
              "teams": [{"id": 1, "name": "Fictional North", "roster": {"entries": []}},
                        {"id": 2, "name": "Fictional South", "roster": {"entries": []}}]}
    pool = {"id": 123, "seasonId": 2026, "scoringPeriodId": 1, "players": []}
    specifications = [(101, "Runner Alpha", 2, 2, 1, 2),
                      (102, "Receiver Beta", 3, 4, 1, 23),
                      (103, "Runner Gamma", 2, 2, 1, 20),
                      (104, "Reserve Delta", 2, 2, 1, 21),
                      (105, "Runner Epsilon", 2, 2, 2, 2),
                      (106, "Tight Zeta", 4, 6, 2, 23),
                      (107, "Receiver Eta", 3, 4, 2, 20),
                      (-16001, "Fictional Defense", 16, 16, 0, None),
                      (109, "Available Theta", 2, 2, 0, None)]
    for pid, name, position, primary_slot, owner, lineup_slot in specifications:
        raw = {"id": pid, "fullName": name, "defaultPositionId": position,
               "eligibleSlots": [primary_slot, 20, 21, 23], "active": True,
               "injuryStatus": "IR" if lineup_slot == 21 else "ACTIVE",
               "ownership": {"averageDraftPosition": 10},
               "stats": [projection(0, {"53": 40, "24": 1000}),
                         projection(1, {"53": 5, "24": 70}),
                         projection(2, {"53": 99, "24": 900}),
                         projection(1, {"53": 100, "24": 100}, season=2025),
                         projection(1, {"53": 200, "24": 100}, source=0)]}
        entry = {"id": pid, "onTeamId": owner, "lineupLocked": False, "rosterLocked": False, "player": raw}
        pool["players"].append(entry)
        if owner:
            league["teams"][owner - 1]["roster"]["entries"].append({
                "playerId": pid, "lineupSlotId": lineup_slot, "playerPoolEntry": deepcopy(entry)})
    return league, pool


def parse(league=None, pool=None, **kwargs):
    default_league, default_pool = fixture()
    options = dict(team_id=1, week=1, visible_text="My Team\nWeek 1", page_url=URL,
                   observed_at=datetime.now(timezone.utc))
    options.update(kwargs)
    return normalize_espn_season(league or default_league, pool or default_pool, **options)


def own_locks():
    return {str(pid): False for pid in (101, 102, 103, 104)}


def test_read_urls_include_week_and_full_roster_views():
    assert "view=mRoster" in season_read_url(123, 2026, 1)
    assert season_read_url(123, 2026, 1).endswith("scoringPeriodId=1")
    assert season_player_read_url(123, 2026, 1).endswith("view=kona_player_info&scoringPeriodId=1")
    assert "FREEAGENT" not in season_player_read_headers(2026)["x-fantasy-filter"]
    for bad in (0, 19, True, "1?view=write"):
        with pytest.raises(ESPNDataError):
            season_read_url(123, 2026, bad)


def test_all_rosters_ir_flex_and_weekly_custom_scoring_are_preserved():
    snap = parse()
    assert snap.phase == "season" and snap.week == 1 and snap.picks == []
    assert snap.rules.rounds == 3 and snap.rules.ir == 1 and snap.rules.slot == 1
    assert snap.own_team().roster_ids == ["101", "102", "103"]
    assert snap.own_team().reserve_ids == ["104"]
    assert snap.own_team().lineup == {"RB1": "101", "FLEX1": "102"}
    assert snap.teams[1].lineup == {"RB1": "105", "FLEX1": "106"}
    assert next(p for p in snap.players if p.id == "101").weekly_projection == 12
    assert next(p for p in snap.players if p.id == "106").weekly_projection == 14.5
    assert next(p for p in snap.players if p.id == "101").projection == 140
    assert any(p.id == "-16001" for p in snap.players)
    assert all(p.weekly_floor is None and p.weekly_ceiling is None for p in snap.players)
    assert snap.source.browser.current_pick is None and snap.source.browser.draft_complete


def test_default_api_lock_flags_do_not_establish_editability():
    snap = parse()
    assert not snap.source.locks_verified
    assert all(p.locked for p in snap.players)


def test_complete_own_ui_locks_verify_own_team_without_unlocking_free_agents():
    snap = parse(player_locks=own_locks())
    assert snap.source.locks_verified
    assert all(not p.locked for p in snap.players if p.id in own_locks())
    assert all(p.locked for p in snap.players if p.id not in own_locks())


def test_locked_starter_and_bench_controls_constrain_lineup_recommendation():
    league, pool = fixture()
    pool["players"][2]["player"]["stats"][1]["stats"] = {"53": 99}
    locks = own_locks()
    locks.update({"101": True, "103": True})
    snap = parse(league, pool, player_locks=locks)
    result = recommend_lineup(snap, ManagerConfig())
    assert result["lineup"]["RB1"] == "101"
    assert "103" not in result["lineup"].values()


def test_incomplete_ui_coverage_is_explicit_and_unknown_locks_are_conservative():
    snap = parse(player_locks={"101": False})
    assert not snap.source.locks_verified
    assert next(p for p in snap.players if p.id == "101").locked is False
    assert next(p for p in snap.players if p.id == "103").locked is True


@pytest.mark.parametrize("locks", [{"101": 0}, {"101": "false"}, {"unknown": False}])
def test_ui_lock_values_require_known_ids_and_booleans(locks):
    with pytest.raises(ESPNDataError, match="booleans"):
        parse(player_locks=locks)


def test_lock_evidence_must_match_the_visible_week():
    with pytest.raises(ESPNDataError, match="visible scoring week"):
        parse(visible_text="My Team", player_locks=own_locks())
    assert parse(visible_text="My Team", observed_week=1, player_locks=own_locks()).source.locks_verified
    with pytest.raises(ESPNDataError, match="visible week"):
        parse(observed_week=2, player_locks=own_locks())
    with pytest.raises(ESPNDataError, match="different scoring week"):
        parse(page_url=URL + "&scoringPeriodId=2")


def test_missing_weekly_projection_is_null_and_never_season_divided_by_seventeen():
    league, pool = fixture()
    pool["players"][0]["player"]["stats"] = [projection(0, {"53": 340})]
    snap = parse(league, pool, player_locks=own_locks())
    assert snap.players[0].projection == 340
    assert snap.players[0].weekly_projection is None
    assert recommend_lineup(snap, ManagerConfig())["status"] == "incomplete"
    assert any("Weekly projections are missing for 1" in note for note in snap.source.notes)


def test_reserve_player_without_any_projection_remains_owned():
    league, pool = fixture()
    pool["players"][3]["player"]["stats"] = []
    snap = parse(league, pool)
    reserve = next(p for p in snap.players if p.id == "104")
    assert reserve.projection is None and reserve.weekly_projection is None
    assert snap.own_team().reserve_ids == ["104"]


def test_embedded_roster_metadata_can_supply_player_missing_from_pool():
    league, pool = fixture()
    pool["players"] = pool["players"][1:]
    snap = parse(league, pool)
    assert next(p for p in snap.players if p.id == "101").weekly_projection == 12


def test_missing_embedded_and_pool_metadata_blocks_whole_roster_import():
    league, pool = fixture()
    pool["players"] = pool["players"][1:]
    del league["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]
    with pytest.raises(ESPNDataError, match="no player metadata"):
        parse(league, pool)


@pytest.mark.parametrize("case", ["missing_team_roster", "duplicate_owner", "pool_owner", "embedded_id", "unsupported_slot", "overflow_slot"])
def test_incomplete_or_conflicting_rosters_fail(case):
    league, pool = fixture()
    if case == "missing_team_roster":
        del league["teams"][1]["roster"]
    elif case == "duplicate_owner":
        league["teams"][1]["roster"]["entries"].append(deepcopy(league["teams"][0]["roster"]["entries"][0]))
    elif case == "pool_owner":
        pool["players"][0]["onTeamId"] = 2
    elif case == "embedded_id":
        league["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]["player"]["id"] = 999
    elif case == "unsupported_slot":
        league["teams"][0]["roster"]["entries"][0]["lineupSlotId"] = 7
    else:
        league["teams"][0]["roster"]["entries"][2]["lineupSlotId"] = 2
    with pytest.raises(ESPNDataError):
        parse(league, pool)


def test_vacant_starter_is_explicit_and_not_filled_from_projection_rank():
    league, pool = fixture()
    league["teams"][0]["roster"]["entries"][1]["lineupSlotId"] = 20
    assert parse(league, pool).own_team().lineup == {"RB1": "101", "FLEX1": None}


@pytest.mark.parametrize("case", ["league_week", "pool_week", "pool_season", "league_id", "unfinished_draft"])
def test_wrong_period_or_scope_cannot_be_imported(case):
    league, pool = fixture()
    if case == "league_week":
        league["scoringPeriodId"] = 2
    elif case == "pool_week":
        pool["scoringPeriodId"] = 2
    elif case == "pool_season":
        pool["seasonId"] = 2025
    elif case == "league_id":
        league["id"] = 456
    else:
        league["draftDetail"]["drafted"] = False
    with pytest.raises(ESPNDataError):
        parse(league, pool)


def test_empty_or_duplicate_weekly_records_do_not_create_points():
    league, pool = fixture()
    pool["players"][0]["player"]["stats"][1]["stats"] = {}
    assert parse(league, pool).players[0].weekly_projection is None
    pool["players"][0]["player"]["stats"].append(projection(1, {"53": 1}))
    with pytest.raises(ESPNDataError, match="duplicate projection"):
        parse(league, pool)


def test_cached_projection_timestamp_is_preserved():
    now = datetime.now(timezone.utc)
    downloaded = now - timedelta(minutes=2)
    snap = parse(observed_at=now, projections_observed_at=downloaded)
    assert snap.source.projections_observed_at == downloaded
    with pytest.raises(ESPNDataError, match="later"):
        parse(observed_at=now, projections_observed_at=now + timedelta(seconds=1))


def test_unknown_budget_stays_unknown_and_zero_history_does_not_invent_pending_claims():
    assert parse().budget is None
    league, pool = fixture()
    league["settings"]["acquisitionSettings"] = {"acquisitionBudget": 100}
    league["teams"][0]["transactionCounter"] = {"acquisitionBudgetSpent": 0, "acquisitions": 0}
    budget = parse(league, pool).budget
    assert budget.balance == 100 and budget.spent_week == 0 and budget.spent_season == 0
    assert budget.roster_moves_week == 0
    assert budget.pending_amount is None and budget.pending_moves is None
    league["teams"][0]["transactionCounter"]["acquisitions"] = 1
    assert parse(league, pool).budget is None


def test_nonzero_season_spend_cannot_be_assigned_to_the_current_week():
    league, pool = fixture()
    league["settings"]["acquisitionSettings"] = {"acquisitionBudget": 100}
    league["teams"][0]["transactionCounter"] = {"acquisitionBudgetSpent": 25, "acquisitions": 3}
    snap = parse(league, pool)
    assert snap.budget is None
    assert any("weekly spending and moves are unknown" in note for note in snap.source.notes)


def test_invalid_faab_counter_is_rejected():
    league, pool = fixture()
    league["settings"]["acquisitionSettings"] = {"acquisitionBudget": 100}
    league["teams"][0]["transactionCounter"] = {"acquisitionBudgetSpent": 101, "acquisitions": 3}
    with pytest.raises(ESPNDataError, match="exceeds"):
        parse(league, pool)
