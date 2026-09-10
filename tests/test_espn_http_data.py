"""Exercise HTTP normalization with fictional observations and no network."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from fantasy_football_manager.espn_data import ESPNDataError
from fantasy_football_manager.espn_http_client import league_url
from fantasy_football_manager.espn_http_data import normalize_espn_http, season_pro_teams_read_url
from fantasy_football_manager.espn_season_data import season_player_read_url
from test_espn_season_data import fixture as season_fixture


MEMBER = "{00000000-0000-0000-0000-000000000001}"
OTHER = "{00000000-0000-0000-0000-000000000002}"
ROSTER_URL = league_url(123, 2026) + "?forTeamId=1&scoringPeriodId=1&view=mRoster"
LEAGUE_URL = league_url(123, 2026) + "?scoringPeriodId=1&" + "&".join(
    "view=" + view for view in ("mRoster", "mSettings", "mTeam", "mStatus", "mDraftDetail", "mPendingTransactions"))
PRO_TEAMS_URL = season_pro_teams_read_url(2026)


def pro_teams_fixture():
    return {"settings": {"proTeams": [
        {"id": 0, "byeWeek": 0}, {"id": 1, "byeWeek": 9}, {"id": 2, "byeWeek": 10}]}}


def fixture():
    league, pool = season_fixture()
    league["status"] = {"latestScoringPeriod": 1, "transactionScoringPeriod": 1, "finalScoringPeriod": 18}
    league["settings"]["rosterSettings"]["isUsingUndroppableList"] = True
    league["settings"]["acquisitionSettings"] = {
        "isUsingAcquisitionBudget": True, "acquisitionType": "WAIVERS_TRADITIONAL",
        "acquisitionBudget": 100, "minimumBid": 0, "acquisitionLimit": -1, "matchupAcquisitionLimit": -1}
    for team in league["teams"]:
        team.update(owners=[MEMBER if team["id"] == 1 else OTHER], isTransactionLocked=False,
                    transactionCounter={"acquisitionBudgetSpent": 0, "acquisitions": 0})
        for entry in team["roster"]["entries"]:
            wrapper = entry["playerPoolEntry"]
            wrapper.update(tradeLocked=False, status="ONTEAM")
            wrapper["player"].update(droppable=True, injured=entry["lineupSlotId"] == 21, proTeamId=1)
    for wrapper in pool["players"]:
        wrapper.update(tradeLocked=False, status="ONTEAM" if wrapper["onTeamId"] else "FREEAGENT")
        wrapper["player"].update(droppable=True, injured=wrapper["id"] == 104,
                                 proTeamId=2 if wrapper["id"] == -16001 else 1)
    roster = {key: league[key] for key in ("id", "seasonId", "scoringPeriodId")}
    roster["teams"] = [deepcopy(league["teams"][0])]
    return league, pool, roster


def parse(league=None, pool=None, roster=None, **kwargs):
    defaults = fixture()
    options = dict(team_id=1, week=1, member_id=MEMBER, observed_at=datetime.now(timezone.utc),
                   player_response_url=season_player_read_url(123, 2026, 1),
                   roster_response_url=ROSTER_URL, league_response_url=LEAGUE_URL,
                   pro_teams_payload=pro_teams_fixture(), pro_teams_response_url=PRO_TEAMS_URL)
    options.update(kwargs)
    return normalize_espn_http(league if league is not None else defaults[0],
                               pool if pool is not None else defaults[1],
                               roster if roster is not None else defaults[2], **options)


def _players(snapshot):
    return {player.id: player for player in snapshot.players}


def test_bye_week_joins_professional_team_including_negative_dst_player_id():
    players = _players(parse())
    assert players["101"].bye == 9 and players["101"].espn.bye_verified is True
    assert players["-16001"].bye == 10 and players["-16001"].espn.bye_verified is True


@pytest.mark.parametrize("bye", [0, 1, 18])
def test_bye_week_boundaries_are_explicit_and_zero_means_no_bye(bye):
    pro_teams = pro_teams_fixture()
    pro_teams["settings"]["proTeams"][1]["byeWeek"] = bye
    player = _players(parse(pro_teams_payload=pro_teams))["101"]
    assert player.bye == (bye or None) and player.espn.bye_verified is True


@pytest.mark.parametrize("missing", ["payload", "url", "both", "player_team"])
def test_missing_professional_schedule_evidence_cannot_prove_no_bye(missing):
    options = {}
    if missing in {"payload", "both"}:
        options["pro_teams_payload"] = None
    if missing in {"url", "both"}:
        options["pro_teams_response_url"] = None
    if missing == "player_team":
        league, pool, roster = fixture()
        del next(row["player"] for row in pool["players"] if row["id"] == 109)["proTeamId"]
        options.update(league=league, pool=pool, roster=roster)
    player = _players(parse(**options))["109"]
    assert player.bye is None and player.espn.bye_verified is None


def test_explicit_free_agent_professional_team_row_verifies_null_bye():
    league, pool, roster = fixture()
    next(row["player"] for row in pool["players"] if row["id"] == 109)["proTeamId"] = 0
    player = _players(parse(league, pool, roster))["109"]
    assert player.bye is None and player.espn.bye_verified is True
    pro_teams = pro_teams_fixture()
    pro_teams["settings"]["proTeams"] = pro_teams["settings"]["proTeams"][1:]
    with pytest.raises(ESPNDataError, match="matching bye-week evidence"):
        parse(league, pool, roster, pro_teams_payload=pro_teams)


@pytest.mark.parametrize("url", [PRO_TEAMS_URL.replace("2026", "2025"),
                                 PRO_TEAMS_URL.replace("ffl", "flb"),
                                 PRO_TEAMS_URL.replace("https:", "http:"),
                                 PRO_TEAMS_URL + "&scoringPeriodId=1", PRO_TEAMS_URL + "#fragment"])
def test_professional_schedule_requires_exact_season_url(url):
    with pytest.raises(ESPNDataError, match="exact football season URL"):
        parse(pro_teams_response_url=url)


@pytest.mark.parametrize("field,value", [("seasonId", 2025), ("seasonId", "2026"),
                                        ("gameId", 2), ("gameId", True), ("segmentId", 1)])
def test_professional_schedule_rejects_conflicting_embedded_context(field, value):
    pro_teams = pro_teams_fixture()
    pro_teams[field] = value
    with pytest.raises(ESPNDataError, match="different scoring context"):
        parse(pro_teams_payload=pro_teams)


@pytest.mark.parametrize("bye", [-1, 19, 1.0, True, "1", None])
def test_professional_schedule_rejects_invalid_bye_week(bye):
    pro_teams = pro_teams_fixture()
    pro_teams["settings"]["proTeams"][1]["byeWeek"] = bye
    with pytest.raises(ESPNDataError, match="bye week is invalid"):
        parse(pro_teams_payload=pro_teams)


@pytest.mark.parametrize("change", ["duplicate", "missing", "missing_bye", "invalid_id", "invalid_fa_bye"])
def test_professional_schedule_rejects_malformed_or_missing_team_rows(change):
    pro_teams = pro_teams_fixture()
    rows = pro_teams["settings"]["proTeams"]
    if change == "duplicate":
        rows.append(deepcopy(rows[1]))
    elif change == "missing":
        rows.pop(1)
    elif change == "missing_bye":
        del rows[1]["byeWeek"]
    elif change == "invalid_id":
        rows[1]["id"] = True
    else:
        rows[0]["byeWeek"] = 1
    with pytest.raises(ESPNDataError):
        parse(pro_teams_payload=pro_teams)


def test_professional_team_change_between_pool_and_targeted_roster_rejects_observation():
    league, pool, roster = fixture()
    next(row["player"] for row in pool["players"] if row["id"] == 101)["proTeamId"] = 2
    with pytest.raises(ESPNDataError, match="professional team changed"):
        parse(league, pool, roster)


def test_http_source_keeps_scope_and_uses_targeted_locks_only():
    league, pool, roster = fixture()
    wrapper = roster["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]
    wrapper.update(lineupLocked=True, rosterLocked=True)
    snapshot = parse(league, pool, roster)
    assert snapshot.source.provider == "espn_http" and snapshot.source.browser is None
    assert snapshot.source.http.roster_url == ROSTER_URL
    assert snapshot.source.http.ownership_verified and snapshot.source.locks_verified
    assert snapshot.source.locks_scope == "selected_team"
    assert _players(snapshot)["101"].locked
    assert _players(snapshot)["101"].espn.roster_locked
    assert not _players(snapshot)["103"].locked
    assert _players(snapshot)["105"].locked  # Another team's generic flags are insufficient.
    assert not _players(snapshot)["109"].locked
    assert snapshot.own_team().reserve_ids == ["104"]
    assert snapshot.own_team().lineup == {"RB1": "101", "FLEX1": "102"}


@pytest.mark.parametrize("change", ["missing", "null"])
def test_partial_targeted_locks_keep_uncovered_players_locked(change):
    league, pool, roster = fixture()
    wrapper = roster["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]
    if change == "missing":
        del wrapper["lineupLocked"]
    else:
        wrapper["lineupLocked"] = None
    snapshot = parse(league, pool, roster)
    assert not snapshot.source.locks_verified
    assert _players(snapshot)["101"].locked
    assert _players(snapshot)["109"].locked
    assert not _players(snapshot)["103"].locked


@pytest.mark.parametrize("change", ["owner", "owners_missing", "invalid_member", "primary_owner",
                                     "league_week", "pool_week", "roster_week", "roster_league",
                                     "roster_team", "extra_team", "draft", "game", "segment"])
def test_context_authentication_and_phase_fail_closed(change):
    league, pool, roster = fixture()
    kwargs = {}
    if change == "owner":
        kwargs["member_id"] = OTHER
    elif change == "owners_missing":
        del league["teams"][0]["owners"]
    elif change == "invalid_member":
        kwargs["member_id"] = "not-a-member"
    elif change == "primary_owner":
        league["teams"][0]["primaryOwner"] = OTHER
    elif change == "league_week":
        league["scoringPeriodId"] = 2
    elif change == "pool_week":
        pool["scoringPeriodId"] = 2
    elif change == "roster_week":
        roster["scoringPeriodId"] = 2
    elif change == "roster_league":
        roster["id"] = 456
    elif change == "roster_team":
        roster["teams"][0]["id"] = 2
    elif change == "extra_team":
        roster["teams"].append(deepcopy(league["teams"][1]))
    elif change == "draft":
        league["draftDetail"]["drafted"] = False
    elif change == "game":
        roster["gameId"] = True
    else:
        roster["segmentId"] = 1
    with pytest.raises(ESPNDataError):
        parse(league, pool, roster, **kwargs)


@pytest.mark.parametrize("url", [None, ROSTER_URL.replace("https:", "http:"),
                                 ROSTER_URL.replace("forTeamId=1", "forTeamId=2"),
                                 ROSTER_URL.replace("scoringPeriodId=1", "scoringPeriodId=2"),
                                 ROSTER_URL + "&extra=value", ROSTER_URL + "#fragment"])
def test_lock_evidence_requires_exact_roster_url(url):
    with pytest.raises(ESPNDataError):
        parse(roster_response_url=url)


@pytest.mark.parametrize("change", ["missing_player", "changed_slot", "embedded_owner", "embedded_id", "pool_owner_zero"])
def test_roster_races_and_ownership_conflicts_are_rejected(change):
    league, pool, roster = fixture()
    entries = roster["teams"][0]["roster"]["entries"]
    if change == "missing_player":
        entries.pop()
    elif change == "changed_slot":
        entries[0]["lineupSlotId"] = 20
    elif change == "embedded_owner":
        entries[0]["playerPoolEntry"]["onTeamId"] = 2
    elif change == "embedded_id":
        entries[0]["playerPoolEntry"]["player"]["id"] = 999
    else:
        pool["players"][0]["onTeamId"] = 0
    with pytest.raises(ESPNDataError):
        parse(league, pool, roster)


def test_pending_omission_requires_requested_view_provenance():
    snapshot = parse()
    assert snapshot.source.http.pending_transactions_known
    assert snapshot.source.http.pending_transactions == []
    assert snapshot.budget.pending_amount == snapshot.budget.pending_moves == 0
    unknown = parse(league_response_url=None)
    assert not unknown.source.http.pending_transactions_known
    assert unknown.budget.pending_amount is None and unknown.budget.pending_moves is None
    with pytest.raises(ESPNDataError):
        parse(league_response_url=LEAGUE_URL.replace("&view=mPendingTransactions", ""))


def test_pending_scope_bid_reservations_and_player_references():
    league, pool, roster = fixture()
    league["pendingTransactions"] = [
        {"id": "own-claim", "teamId": 1, "type": "WAIVER", "status": "PENDING", "bidAmount": 7,
         "memberId": MEMBER, "comment": "private note",
         "items": [{"type": "ADD", "playerId": 109, "toTeamId": 1}]},
        {"id": "other-claim", "teamId": 2, "type": "WAIVER", "bidAmount": 50,
         "items": [{"type": "ADD", "playerId": 109, "toTeamId": 2}]},
        {"id": "incoming-trade", "teamId": 2, "type": "TRADE_PROPOSAL",
         "items": [{"type": "TRADE", "playerId": 102, "fromTeamId": 1, "toTeamId": 2}]}]
    snapshot = parse(league, pool, roster)
    transactions = snapshot.source.http.pending_transactions
    assert [row["id"] for row in transactions] == ["own-claim", "incoming-trade"]
    assert "memberId" not in transactions[0] and "comment" not in transactions[0]
    assert snapshot.budget.pending_amount == 7 and snapshot.budget.pending_moves == 1
    assert _players(snapshot)["102"].espn.pending_transaction_ids == ["incoming-trade"]
    assert _players(snapshot)["109"].espn.pending_transaction_ids == ["own-claim"]


def test_traditional_waivers_do_not_invent_faab_and_nonzero_history_remains_unknown():
    league, pool, roster = fixture()
    league["settings"]["acquisitionSettings"]["isUsingAcquisitionBudget"] = False
    league["pendingTransactions"] = [{"id": "claim", "teamId": 1, "type": "WAIVER",
                                      "items": [{"type": "ADD", "playerId": 109, "toTeamId": 1}]}]
    snapshot = parse(league, pool, roster)
    assert snapshot.budget.balance == snapshot.budget.pending_amount == 0
    assert snapshot.budget.pending_moves == 1
    league["teams"][0]["transactionCounter"]["acquisitions"] = 1
    assert parse(league, pool, roster).budget is None


def test_unknown_flags_and_ir_metadata_remain_explicit():
    league, pool, roster = fixture()
    raw = roster["teams"][0]["roster"]["entries"][0]["playerPoolEntry"]["player"]
    raw.update(injuryStatus="DOUBTFUL", injured=False, droppable=False)
    del league["teams"][0]["isTransactionLocked"]
    del league["settings"]["rosterSettings"]["isUsingUndroppableList"]
    snapshot = parse(league, pool, roster)
    player = _players(snapshot)["101"]
    assert 21 in player.espn.eligible_slots
    assert player.espn.injured is False and player.espn.droppable is False
    assert player.availability == "DOUBTFUL"
    assert snapshot.source.http.team_transaction_locked is None
    assert snapshot.source.http.uses_undroppable_list is None
    assert _players(snapshot)["109"].locked


def test_missing_projection_is_null_and_cached_download_time_is_preserved():
    league, pool, roster = fixture()
    pool["players"][0]["player"]["stats"][1]["stats"] = {}
    now = datetime.now(timezone.utc)
    downloaded = now - timedelta(minutes=3)
    snapshot = parse(league, pool, roster, observed_at=now, projections_observed_at=downloaded)
    assert _players(snapshot)["101"].weekly_projection is None
    assert snapshot.source.projections_observed_at == downloaded
    with pytest.raises(ESPNDataError, match="later"):
        parse(observed_at=now, projections_observed_at=now + timedelta(seconds=1))


@pytest.mark.parametrize("field", ["lineupLocked", "rosterLocked", "tradeLocked"])
def test_string_flags_cannot_establish_editability(field):
    league, pool, roster = fixture()
    roster["teams"][0]["roster"]["entries"][0]["playerPoolEntry"][field] = "false"
    with pytest.raises(ESPNDataError, match="boolean"):
        parse(league, pool, roster)


def test_normalization_does_not_change_input_observations():
    inputs = fixture()
    before = deepcopy(inputs)
    parse(*inputs)
    assert inputs == before


def test_requested_period_cannot_replace_the_actual_transaction_period():
    league, pool, roster = fixture()
    league["status"].update(latestScoringPeriod=2, transactionScoringPeriod=2)
    snapshot = parse(league, pool, roster)
    assert snapshot.week == snapshot.source.http.week == 1
    assert snapshot.source.http.transaction_period == snapshot.source.http.latest_period == 2


@pytest.mark.parametrize("field,value", [("transactionScoringPeriod", None), ("transactionScoringPeriod", True),
                                       ("transactionScoringPeriod", 19), ("latestScoringPeriod", None),
                                       ("latestScoringPeriod", 19), ("finalScoringPeriod", None)])
def test_missing_or_invalid_actual_periods_cannot_establish_write_context(field, value):
    league, pool, roster = fixture()
    league["status"][field] = value
    with pytest.raises(ESPNDataError):
        parse(league, pool, roster)


@pytest.mark.parametrize("field", ["transactionScoringPeriod", "latestScoringPeriod"])
def test_actual_period_cannot_exceed_final_period(field):
    league, pool, roster = fixture()
    league["status"].update(finalScoringPeriod=1)
    league["status"][field] = 2
    with pytest.raises(ESPNDataError, match="outside the active season"):
        parse(league, pool, roster)


def test_acquisition_limits_and_verified_matchup_counts_are_distinct():
    league, pool, roster = fixture()
    league["settings"]["acquisitionSettings"].update(acquisitionLimit=-1.0, matchupAcquisitionLimit=3.0)
    league["settings"]["scheduleSettings"] = {"matchupPeriods": {"1": [1, 2], "2": [3]}}
    league["status"]["currentMatchupPeriod"] = 1
    league["teams"][0]["transactionCounter"].update(acquisitions=5, matchupAcquisitionTotals={"1": 2, "2": 3})
    http = parse(league, pool, roster).source.http
    assert http.acquisition_limit == -1 and http.matchup_acquisition_limit == 3
    assert http.acquisitions_season == 5 and http.acquisitions_period == 2
    league["status"]["currentMatchupPeriod"] = 2
    assert parse(league, pool, roster).source.http.acquisitions_period is None
    del league["settings"]["scheduleSettings"]
    assert parse(league, pool, roster).source.http.acquisitions_period is None


@pytest.mark.parametrize("value", [True, -2, 1.5, float("nan"), "-1.0"])
def test_acquisition_limit_requires_an_exact_integral_value(value):
    league, pool, roster = fixture()
    league["settings"]["acquisitionSettings"]["acquisitionLimit"] = value
    with pytest.raises(ESPNDataError):
        parse(league, pool, roster)
