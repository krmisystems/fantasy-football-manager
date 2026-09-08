"""Test ESPN parsing with fictional, isolated payloads. No network calls."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from fantasy_football_manager.espn_data import (
    ESPNDataError, league_read_url, normalize_espn_draft,
    player_read_headers, player_read_url,
)


URL = "https://fantasy.espn.com/football/draft?leagueId=123&seasonId=2026&teamId=22"


def fixture():
    """Use two fictional teams with four active slots each."""
    league = {
        "id": 123, "seasonId": 2026, "gameId": 1, "segmentId": 0,
        "settings": {
            "size": 2, "draftSettings": {"type": "SNAKE", "pickOrder": [11, 22], "keeperCount": 0},
            "rosterSettings": {
                "lineupSlotCounts": {"2": 1, "23": 1, "20": 2, "21": 1},
                "positionLimits": {"1": 1, "2": 3, "3": 3, "4": 1, "5": 1, "16": 1}},
            "scoringSettings": {"scoringType": "H2H_POINTS", "scoringItems": [
                {"statId": 53, "points": 1, "pointsOverrides": {"4": 1.5}},
                {"statId": 24, "points": .1, "pointsOverrides": {}},
                {"statId": 89, "points": 0, "pointsOverrides": {"16": 5}}]}},
        "teams": [{"id": 11, "name": "Fictional North"}, {"id": 22, "name": "Fictional South"}],
        "draftDetail": {"drafted": False, "picks": []}, "status": {"isActive": True},
    }
    players = {"players": []}
    for pid, name, position, slot in [
        (101, "Runner Alpha", 2, 2), (102, "Receiver Beta", 3, 4),
        (103, "Runner Gamma", 2, 2), (104, "Receiver Delta", 3, 4),
        (105, "Runner Epsilon", 2, 2), (106, "Receiver Zeta", 3, 4),
        (107, "Tight Eta", 4, 6), (-16001, "Fictional Defense", 16, 16),
        (109, "Runner Theta", 2, 2), (110, "Receiver Iota", 3, 4),
    ]:
        players["players"].append({"id": pid, "onTeamId": 0, "player": {
            "id": pid, "fullName": name, "defaultPositionId": position,
            "eligibleSlots": [slot, 20, 21, 23], "active": True,
            "ownership": {"averageDraftPosition": len(players["players"]) + 1},
            "stats": [{"seasonId": 2026, "statSourceId": 1, "statSplitTypeId": 0,
                       "scoringPeriodId": 0, "appliedTotal": 9999,
                       "stats": {"53": 20, "24": 100, "89": 2}}]}})
    return league, players


def api_pick(number, player_id):
    rnd, offset = divmod(number - 1, 2)
    owner = [11, 22][1 - offset if rnd % 2 else offset]
    return {"overallPickNumber": number, "roundId": rnd + 1,
            "roundPickNumber": offset + 1, "teamId": owner, "playerId": player_id}


def parse(league=None, players=None, **kwargs):
    default_league, default_players = fixture()
    options = dict(team_id=22, visible_text="ON THE CLOCK: PICK 1\nENABLE AUTOPICK",
                   page_url=URL, observed_at=datetime.now(timezone.utc),
                   player_response_url=player_read_url(123, 2026))
    options.update(kwargs)
    return normalize_espn_draft(league or default_league, players or default_players, **options)


def test_numeric_endpoint_scope_and_read_filters():
    assert league_read_url(123, 2026).endswith("leagues/123?view=mSettings&view=mTeam&view=mDraftDetail&view=mStatus")
    assert player_read_url("123", 2026).endswith("leagues/123?view=kona_player_info")
    assert json.loads(player_read_headers(2026)["x-fantasy-filter"])["players"]["limit"] == 10000
    for value in ("123/../other", "1?view=write", True, "0"):
        with pytest.raises(ValueError):
            league_read_url(value, 2026)


def test_pregame_rules_real_scoring_and_explicit_data_scope():
    snap = parse()
    assert snap.rules.slot == 2
    assert snap.rules.rounds == 4 and snap.rules.ir == 1
    assert snap.rules.starters == {"RB": 1, "FLEX": 1}
    assert snap.source.provider == "espn_browser" and not snap.source.synthetic
    assert snap.source.complete and not snap.source.locks_verified
    assert snap.source.browser.team_id == "22"
    assert snap.source.browser.autopick_enabled is False
    assert snap.source.browser.draft_complete is False
    assert any("download time" in note for note in snap.source.notes)
    assert snap.players[0].projection == 30
    assert next(p for p in snap.players if p.id == "107").projection == 40
    assert next(p for p in snap.players if p.id == "-16001").projection == 40
    assert all(p.weekly_projection is None and not p.locked for p in snap.players)


def test_negative_defense_ids_and_placeholder_picks():
    league, players = fixture()
    league["draftDetail"]["picks"] = [api_pick(1, 101), api_pick(2, -16001), api_pick(3, -1)]
    snap = parse(league, players, visible_text="ON THE CLOCK: PICK 3\nDISABLE AUTOPICK")
    assert [p.player_id for p in snap.picks] == ["101", "-16001"]
    assert snap.own_team().roster_ids == ["-16001"]
    assert snap.source.browser.autopick_enabled is True


def test_api_previous_and_activity_merge_without_gaps():
    league, players = fixture()
    league["draftDetail"]["picks"] = [api_pick(1, 101)]
    previous = parse(league, players, visible_text="ON THE CLOCK: PICK 2")
    league["draftDetail"]["picks"] = []
    snap = parse(league, players, previous=previous, visible_text=(
        "ON THE CLOCK: PICK 3\n142 text Receiver Beta / ABC WR R1, P2 - Fictional South"))
    assert [p.player_id for p in snap.picks] == ["101", "102"]
    assert snap.source.browser.autopick_enabled is None


def test_visible_full_history_repairs_empty_api():
    snap = parse(visible_text=("ON THE CLOCK: PICK 3\nDRAFT HISTORY\n"
                              "11 row 1 Runner Alpha ABC RB Fictional North\n"
                              "12 row 2 Receiver Beta ABC WR Fictional South\n"
                              "13 row 3 Runner Gamma ABC RB QUEUE DRAFT"))
    assert len(snap.picks) == 2


@pytest.mark.parametrize("text", [
    "ON THE CLOCK: PICK 3\nReceiver Beta / ABC WR R1, P2 - Fictional South",
    "ON THE CLOCK: PICK 2", "Draft lobby", "ON THE CLOCK: PICK 1\nON THE CLOCK: PICK 2",
])
def test_missing_history_or_clock_is_rejected(text):
    with pytest.raises(ESPNDataError):
        parse(visible_text=text)


def test_conflicting_confirmed_pick_is_rejected():
    league, players = fixture()
    league["draftDetail"]["picks"] = [api_pick(1, 101)]
    with pytest.raises(ESPNDataError, match="conflict"):
        parse(league, players, visible_text="ON THE CLOCK: PICK 2\nReceiver Beta / ABC WR R1, P1 - Fictional North")


def test_duplicate_player_is_rejected_across_sources():
    league, players = fixture()
    league["draftDetail"]["picks"] = [api_pick(1, 101)]
    with pytest.raises(ESPNDataError, match="more than one"):
        parse(league, players, visible_text="ON THE CLOCK: PICK 3\nRunner Alpha / ABC RB R1, P2 - Fictional South")


def test_persisted_history_cannot_mask_a_rewind_or_new_scope():
    league, players = fixture()
    league["draftDetail"]["picks"] = [api_pick(1, 101)]
    previous = parse(league, players, visible_text="ON THE CLOCK: PICK 2")
    league["draftDetail"]["picks"] = []
    with pytest.raises(ESPNDataError, match="stale"):
        parse(league, players, previous=previous)
    previous = previous.model_copy(update={"team_id": "11"})
    with pytest.raises(ESPNDataError, match="scope"):
        parse(league, players, previous=previous)


@pytest.mark.parametrize("field,value", [("seasonId", 2025), ("id", 456), ("gameId", 2)])
def test_player_payload_scope_must_match_page(field, value):
    league, players = fixture()
    players[field] = value
    with pytest.raises(ESPNDataError):
        parse(league, players)


@pytest.mark.parametrize("identity", [{}, {"id": 123}, {"seasonId": 2026}])
def test_player_only_response_requires_exact_request_metadata(identity):
    league, players = fixture()
    players.update(identity)
    with pytest.raises(ESPNDataError, match="exact verified request URL"):
        parse(league, players, player_response_url=None)
    snapshot = parse(league, players)
    assert snapshot.league_id == "123" and snapshot.season == 2026
    assert set(players) == {"players", *identity}


@pytest.mark.parametrize("url", [
    player_read_url(456, 2026), player_read_url(123, 2025), league_read_url(123, 2026),
    player_read_url(123, 2026) + "&scoringPeriodId=2",
    player_read_url(123, 2026).replace("https:", "http:"),
    player_read_url(123, 2026).replace("lm-api-reads.fantasy.espn.com", "example.com"),
])
def test_player_request_metadata_cannot_identify_another_scope_or_endpoint(url):
    with pytest.raises(ESPNDataError, match="response URL"):
        parse(player_response_url=url)


@pytest.mark.parametrize("identity", [
    {"id": 456}, {"seasonId": 2025}, {"id": None}, {"seasonId": None},
    {"id": True}, {"gameId": True}, {"segmentId": 1},
])
def test_request_metadata_does_not_override_invalid_explicit_player_identity(identity):
    league, players = fixture()
    players.update(identity)
    with pytest.raises(ESPNDataError):
        parse(league, players)


def test_explicit_player_identity_remains_supported_without_url_metadata():
    league, players = fixture()
    players.update(id=123, seasonId=2026)
    assert parse(league, players, player_response_url=None).league_id == "123"
    with pytest.raises(ESPNDataError, match="response URL"):
        parse(league, players, player_response_url=player_read_url(456, 2026))


@pytest.mark.parametrize("missing", ["id", "seasonId"])
def test_player_url_does_not_replace_missing_league_payload_identity(missing):
    league, players = fixture()
    league.pop(missing)
    with pytest.raises(ESPNDataError):
        parse(league, players)


def test_missing_team_url_requires_verified_my_team_identity():
    url = URL.replace("&teamId=22", "")
    with pytest.raises(ESPNDataError, match="Verify the active team"):
        parse(page_url=url)
    assert parse(page_url=url, observed_team_id="22").source.browser.team_id == "22"
    with pytest.raises(ESPNDataError, match="does not match"):
        parse(page_url=url, observed_team_id="11")
    with pytest.raises(ESPNDataError, match="conflict"):
        parse(observed_team_id="11")


@pytest.mark.parametrize("url", [
    URL.replace("fantasy.espn.com", "fantasy.espn.com.example.com"),
    URL.replace("https:", "http:"), URL + "&teamId=11", URL + "&leagueId=456",
    URL.replace("fantasy.espn.com", "name@fantasy.espn.com"),
])
def test_page_identity_rejects_ambiguous_or_untrusted_urls(url):
    with pytest.raises(ValueError):
        parse(page_url=url)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(seasonId=2025),
    lambda p: p.update(statSourceId=0),
    lambda p: p.update(statSplitTypeId=1),
    lambda p: p.update(scoringPeriodId=1),
])
def test_only_exact_current_full_season_projection_is_accepted(mutation):
    league, players = fixture()
    league["draftDetail"]["picks"] = [api_pick(1, 101)]
    mutation(players["players"][0]["player"]["stats"][0])
    with pytest.raises(ESPNDataError, match="full-season"):
        parse(league, players, visible_text="ON THE CLOCK: PICK 2")


def test_unprojected_irrelevant_player_is_excluded_but_drafted_one_blocks():
    league, players = fixture()
    extra = deepcopy(players["players"][0])
    extra["player"].update(id=999, fullName="Unprojected Example", stats=[], ownership={"averageDraftPosition": 170})
    players["players"].append(extra)
    snap = parse(league, players)
    assert len(snap.players) == 10
    assert any("Excluded 1 player" in note for note in snap.source.notes)
    league["draftDetail"]["picks"] = [api_pick(1, 999)]
    with pytest.raises(ESPNDataError, match="required player"):
        parse(league, players, visible_text="ON THE CLOCK: PICK 2")


def test_ambiguous_visible_names_fail_instead_of_guessing():
    league, players = fixture()
    players["players"][2]["player"]["fullName"] = "Runner Alpha"
    with pytest.raises(ESPNDataError, match="one projected player"):
        parse(league, players, visible_text="ON THE CLOCK: PICK 2\nRunner Alpha / ABC RB R1, P1 - Fictional North")


@pytest.mark.parametrize("kind", ["auction", "keeper", "trade", "slot", "scoring"])
def test_unsupported_league_rules_fail(kind):
    league, players = fixture()
    if kind == "auction":
        league["settings"]["draftSettings"]["type"] = "AUCTION"
    elif kind == "keeper":
        league["settings"]["draftSettings"]["keeperCount"] = 1
    elif kind == "trade":
        league["settings"]["draftSettings"]["isTradingEnabled"] = True
    elif kind == "slot":
        league["settings"]["rosterSettings"]["lineupSlotCounts"]["7"] = 1
    else:
        league["settings"]["scoringSettings"]["scoringItems"] = []
    with pytest.raises(ESPNDataError):
        parse(league, players)


def test_first_round_schedule_can_prove_missing_pick_order():
    league, players = fixture()
    del league["settings"]["draftSettings"]["pickOrder"]
    league["draftDetail"]["picks"] = [api_pick(1, -1), api_pick(2, -1)]
    assert parse(league, players).rules.slot == 2
    league["draftDetail"]["picks"] = [api_pick(1, -1)]
    with pytest.raises(ESPNDataError, match="draft order"):
        parse(league, players)


def test_wrong_api_owner_or_round_is_rejected_even_for_placeholder():
    league, players = fixture()
    league["draftDetail"]["picks"] = [api_pick(1, -1)]
    league["draftDetail"]["picks"][0]["teamId"] = 22
    with pytest.raises(ESPNDataError, match="snake"):
        parse(league, players)
    league["draftDetail"]["picks"][0] = api_pick(1, -1)
    league["draftDetail"]["picks"][0]["roundId"] = 2
    with pytest.raises(ESPNDataError, match="round"):
        parse(league, players)


def test_completed_status_requires_every_pick_and_rosters_derive_from_history():
    league, players = fixture()
    league["draftDetail"]["drafted"] = True
    with pytest.raises(ESPNDataError, match="incomplete"):
        parse(league, players, visible_text="DRAFT COMPLETE")
    league["draftDetail"]["picks"] = [api_pick(i, pid) for i, pid in enumerate(
        [101, 102, 103, 104, 105, 106, 107, -16001], 1)]
    snap = parse(league, players, visible_text="DRAFT COMPLETE")
    assert snap.source.browser.draft_complete
    assert snap.source.browser.current_pick == 9
    assert len(snap.picks) == 8
    assert all(len(team.roster_ids) == 4 for team in snap.teams)
    with pytest.raises(ESPNDataError, match="conflicts"):
        parse(league, players, visible_text="ON THE CLOCK: PICK 8")


def test_cached_projection_time_is_not_refreshed_by_new_browser_observation():
    observed = datetime.now(timezone.utc)
    fetched = observed - timedelta(minutes=3)
    snap = parse(observed_at=observed, projections_observed_at=fetched)
    assert snap.source.projections_observed_at == fetched
    with pytest.raises(ESPNDataError, match="later"):
        parse(observed_at=observed, projections_observed_at=observed + timedelta(seconds=1))
    with pytest.raises(ValueError, match="UTC offset"):
        parse(observed_at=observed.replace(tzinfo=None))


def test_invalid_projection_and_conflicting_autopick_controls_fail():
    league, players = fixture()
    players["players"][0]["player"]["stats"][0]["stats"]["53"] = float("nan")
    with pytest.raises(ESPNDataError, match="finite"):
        parse(league, players)
    with pytest.raises(ESPNDataError, match="Autopick"):
        parse(visible_text="ON THE CLOCK: PICK 1\nENABLE AUTOPICK\nDISABLE AUTOPICK")


def test_unprojected_empty_record_is_excluded_and_unknown_history_rows_do_not_prove_picks():
    league, players = fixture()
    players["players"][-1]["player"]["stats"][0]["stats"] = {}
    assert len(parse(league, players).players) == 9
    with pytest.raises(ESPNDataError, match="incomplete"):
        parse(visible_text="ON THE CLOCK: PICK 2\n11 row 1 Runner Alpha ABC RB")
