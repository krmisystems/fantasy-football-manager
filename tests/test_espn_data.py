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


def test_explicit_predraft_countdown_preserves_no_active_pick():
    snap = parse(visible_text="DRAFTING IN\n01:42\nPICK 1\nFictional North\nPICK 2\nFictional South\nPicks")
    assert snap.picks == [] and snap.source.complete
    assert snap.source.browser.current_pick is None
    assert snap.source.browser.draft_complete is False
    assert any("No active pick" in note for note in snap.source.notes)


def test_predraft_countdown_never_authorizes_the_first_team_to_pick():
    from fantasy_football_manager.models import ManagerConfig
    from fantasy_football_manager.policy import PolicyError, check_action

    snap = parse(team_id=11, page_url=URL.replace("teamId=22", "teamId=11"),
                 visible_text="DRAFTING IN\n00:00\nPICK 1\nFictional North\nENABLE AUTOPICK")
    settings = ManagerConfig(automation={"preset": "bounded_automation"})
    with pytest.raises(PolicyError, match="visible draft clock"):
        check_action(snap, settings, "draft_pick", {"player_id": "101"}, execution_scope="host_browser")


def test_live_clock_can_follow_a_verified_predraft_countdown():
    previous = parse(visible_text="DRAFTING IN\n00:01\nPICK 1\nFictional North")
    live = parse(previous=previous)
    assert live.source.browser.current_pick == 1
    assert live.picks == [] and live.source.complete


def test_standard_draft_lobby_subtype_retains_exact_snake_rules():
    league, players = fixture()
    league["settings"]["draftSettings"]["leagueSubType"] = "DRAFT_LOBBY"
    snap = parse(league, players)
    assert snap.rules.snake and snap.rules.slot == 2 and snap.rules.rounds == 4
    league["settings"]["draftSettings"]["keeperCount"] = 1
    with pytest.raises(ESPNDataError, match="Keeper"):
        parse(league, players)


def test_unknown_draft_subtype_is_still_rejected():
    league, players = fixture()
    league["settings"]["draftSettings"]["leagueSubType"] = "FICTIONAL_UNSUPPORTED_TYPE"
    with pytest.raises(ESPNDataError, match="subtype"):
        parse(league, players)


def test_multiline_body_activity_parses_picks_but_never_fills_missing_history():
    league, players = fixture()
    text = "ON THE CLOCK: PICK 3\nPicks\nReceiver Beta / ABC WR\nR1, P2 - Fictional South"
    with pytest.raises(ESPNDataError, match="incomplete"):
        parse(league, players, visible_text=text)
    text += "\nRunner Alpha / ABC RB\nR1, P1 - Fictional North"
    snap = parse(league, players, visible_text=text)
    assert [(p.pick_no, p.player_id) for p in snap.picks] == [(1, "101"), (2, "102")]


@pytest.mark.parametrize("prefix", ["    - listitem: ", "  - text: "])
def test_playwright_activity_node_prefix_is_not_part_of_player_identity(prefix):
    text = ("ON THE CLOCK: PICK 3\nPicks\nRunner Alpha / ABC RB\nR1, P1 - Fictional North\n"
            + prefix + "Receiver Beta / ABC WR R1, P2 - Fictional South")
    snap = parse(visible_text=text)
    assert [p.player_id for p in snap.picks] == ["101", "102"]
    with pytest.raises(ESPNDataError, match="Unknown Example.*WR"):
        parse(visible_text=text.replace("Receiver Beta", "Unknown Example"))


@pytest.mark.parametrize("progress", ["api_pick", "previous_pick", "clock", "completed"])
def test_predraft_countdown_cannot_hide_confirmed_draft_progress(progress):
    league, players = fixture()
    text = "DRAFTING IN\n01:42\nPICK 1\nFictional North"
    previous = None
    if progress in {"api_pick", "previous_pick"}:
        league["draftDetail"]["picks"] = [api_pick(1, 101)]
        if progress == "previous_pick":
            previous = parse(league, players, visible_text="ON THE CLOCK: PICK 2")
            league["draftDetail"]["picks"] = []
    elif progress == "clock":
        text += "\nON THE CLOCK: PICK 1"
    else:
        league["draftDetail"]["drafted"] = True
    with pytest.raises(ESPNDataError, match="countdown conflicts"):
        parse(league, players, visible_text=text, previous=previous)


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


def test_playwright_history_rows_require_history_scope_and_skip_player_controls():
    rows = ('  - row "1 Runner Alpha ABC RB Fictional North":\n'
            '  - row "2 Receiver Beta ABC WR Fictional South":\n'
            '  - row "3 Runner Gamma ABC RB Queue Draft":\n')
    snap = parse(visible_text="ON THE CLOCK: PICK 3\nPICK HISTORY\n" + rows)
    assert [p.player_id for p in snap.picks] == ["101", "102"]
    with pytest.raises(ESPNDataError, match="incomplete"):
        parse(visible_text="ON THE CLOCK: PICK 3\n" + rows)


@pytest.mark.parametrize("format", ["cua", "aria", "body", "activity"])
def test_every_visible_pick_format_verifies_position_and_snake_team_owner(format):
    if format == "cua":
        evidence = "PICK HISTORY\n11 row 1 Runner Alpha ABC RB Fictional North"
    elif format == "aria":
        evidence = 'PICK HISTORY\n- row "1 Runner Alpha Q ABC RB Fictional North 15.5 30 7":'
    elif format == "body":
        evidence = "PICK HISTORY\nPICK\nPLAYER\nTEAM\n2025 PTS\nPROJ PTS\nRK\n1\nRunner Alpha\nABC\nRB\nFictional North\n15.5\n30\n7"
    else:
        evidence = "Picks\n- listitem: Runner Alpha / ABC RB R1, P1 - Fictional North"
    text = "ON THE CLOCK: PICK 2\n" + evidence
    snap = parse(visible_text=text)
    assert [(pick.player_id, pick.slot) for pick in snap.picks] == [("101", 1)]
    with pytest.raises(ESPNDataError, match="visible pick team"):
        parse(visible_text=text.replace("Fictional North", "Fictional South"))
    with pytest.raises(ESPNDataError, match="verified player"):
        parse(visible_text=text.replace("RB", "WR"))


def test_visible_history_owner_validation_accounts_for_reversed_snake_round():
    text = ("ON THE CLOCK: PICK 4\nPICK HISTORY\n"
            '- row "1 Runner Alpha ABC RB Fictional North 10 30 1":\n'
            '- row "2 Receiver Beta ABC WR Fictional South 10 30 2":\n'
            '- row "3 Runner Gamma ABC RB Fictional South 10 30 3":')
    assert parse(visible_text=text).picks[-1].slot == 2
    with pytest.raises(ESPNDataError, match="visible pick team"):
        parse(visible_text=text.replace("Runner Gamma ABC RB Fictional South", "Runner Gamma ABC RB Fictional North"))


def test_multiline_pick_history_grid_preserves_rounds_injury_markers_and_defense_ids():
    header = "PICK\nPLAYER\nTEAM\n2025 PTS\nPROJ PTS\nRK\n"
    text = ("ON THE CLOCK: PICK 4\nPick History\nRound 1\n" + header
            + "1\nRunner Alpha\nABC\nRB\nFictional North\n100.5\n120.5\n1\n"
            + "2\nReceiver Beta\nQ\nABC\nWR\nFictional South\n-\n100\n2\n"
            + "Round 2\n" + header
            + "3\nFictional Defense\nABC\nD/ST\nFictional South\n-2\n40\n-\nPicks")
    snap = parse(visible_text=text)
    assert [(p.pick_no, p.player_id, p.slot) for p in snap.picks] == [
        (1, "101", 1), (2, "102", 2), (3, "-16001", 2)]
    # Body and accessibility text can independently describe the same pick.
    duplicate = '\n- row "1 Runner Alpha ABC RB Fictional North 100.5 120.5 1":'
    assert parse(visible_text=text + duplicate).picks == snap.picks


@pytest.mark.parametrize("change", ["no_header", "no_history", "wrong_position", "unknown_player", "missing_pick"])
def test_multiline_history_requires_verified_structure_and_complete_identity(change):
    header = "PICK\nPLAYER\nTEAM\n2025 PTS\nPROJ PTS\nRK\n"
    row = "1\nRunner Alpha\nABC\nRB\nFictional North\n100\n120\n1\n"
    text = "ON THE CLOCK: PICK 2\nPick History\n" + header + row
    if change == "no_header":
        text = text.replace(header, "")
    elif change == "no_history":
        text = text.replace("Pick History\n", "")
    elif change == "wrong_position":
        text = text.replace("\nRB\n", "\nWR\n")
    elif change == "unknown_player":
        text = text.replace("Runner Alpha", "Unknown Example")
    else:
        text = text.replace("PICK 2", "PICK 3")
    with pytest.raises(ESPNDataError):
        parse(visible_text=text)


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
        parse(league, players, visible_text="ON THE CLOCK: PICK 2",
              team_id=11, page_url=URL.replace("teamId=22", "teamId=11"))


def test_unprojected_irrelevant_player_is_excluded_but_own_drafted_one_blocks():
    league, players = fixture()
    extra = deepcopy(players["players"][0])
    extra["player"].update(id=999, fullName="Unprojected Example", stats=[], ownership={"averageDraftPosition": 170})
    players["players"].append(extra)
    snap = parse(league, players)
    assert len(snap.players) == 10
    assert any("Excluded 1 player" in note for note in snap.source.notes)
    league["draftDetail"]["picks"] = [api_pick(1, 999)]
    with pytest.raises(ESPNDataError, match="required player"):
        parse(league, players, visible_text="ON THE CLOCK: PICK 2",
              team_id=11, page_url=URL.replace("teamId=22", "teamId=11"))


def test_ambiguous_visible_names_fail_instead_of_guessing():
    league, players = fixture()
    players["players"][2]["player"]["fullName"] = "Runner Alpha"
    with pytest.raises(ESPNDataError, match="one verified player"):
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


def _full_draft_fixture():
    """Create a fictional 10-team draft. No recorded league data is used."""
    league, small_pool = fixture()
    order = list(range(11, 21))
    league["settings"]["size"] = 10
    league["settings"]["draftSettings"].update(pickOrder=order, leagueSubType="DRAFT_LOBBY")
    league["settings"]["rosterSettings"] = {
        "lineupSlotCounts": {"0": 1, "2": 2, "4": 2, "6": 1, "16": 1, "17": 1, "23": 1, "20": 7, "21": 1},
        "positionLimits": {"1": 4, "2": 8, "3": 8, "4": 3, "5": 3, "16": 3},
    }
    league["teams"] = [{"id": tid, "name": f"Fictional Team {slot}"} for slot, tid in enumerate(order, 1)]
    positions = ["RB", "WR", "RB", "WR", "TE", "QB", "WR", "RB", "WR", "RB", "TE", "QB", "WR", "RB", "DST", "K"]
    position_ids = {"QB": (1, 0), "RB": (2, 2), "WR": (3, 4), "TE": (4, 6), "K": (5, 17), "DST": (16, 16)}
    pool, events, placeholders = {"players": []}, [], []
    for number in range(1, 161):
        rnd, offset = divmod(number - 1, 10)
        slot = offset + 1 if rnd % 2 == 0 else 10 - offset
        position = positions[rnd]
        position_id, lineup_slot = position_ids[position]
        pid = -16000 - offset if position == "DST" else 10000 + number
        name = f"Fictional Player {number:03d}"
        raw = deepcopy(small_pool["players"][0]["player"])
        raw.update(id=pid, fullName=name, defaultPositionId=position_id,
                   eligibleSlots=[lineup_slot, 20, 21] + ([23] if position in {"RB", "WR", "TE"} else []),
                   ownership={"averageDraftPosition": number})
        pool["players"].append({"id": pid, "onTeamId": 0, "player": raw})
        placeholders.append({"overallPickNumber": number, "roundId": rnd + 1,
                             "roundPickNumber": offset + 1, "teamId": order[slot - 1], "playerId": -1})
        events.append({"number": number, "round": rnd + 1, "offset": offset + 1, "slot": slot,
                       "id": str(pid), "name": name, "position": "D/ST" if position == "DST" else position,
                       "team": f"Fictional Team {slot}"})
    league["draftDetail"]["picks"] = placeholders
    return league, pool, events


def _replay_activity(events, through):
    return "Picks\n" + "\n".join(
        f"{row['name']} / ABC {row['position']}\nR{row['round']}, P{row['offset']} - {row['team']}"
        for row in events[max(0, through - 3):through])


def _replay_history(events, through):
    text = ["PICK HISTORY"]
    for row in events[:through]:
        if row["offset"] == 1:
            text.append(f"Round {row['round']}\nPICK\nPLAYER\nTEAM\n2025 PTS\nPROJ PTS\nRK")
        text.append(f"{row['number']}\n{row['name']}\nABC\n{row['position']}\n{row['team']}\n-\n30\n{row['number']}")
    return "\n".join(text)


def _replay_parse(league, pool, text, previous=None):
    return normalize_espn_draft(
        league, pool, team_id=20, visible_text=text, page_url=URL.replace("teamId=22", "teamId=20"),
        observed_at=datetime.now(timezone.utc), previous=previous, player_response_url=player_read_url(123, 2026))


def test_complete_ten_team_draft_replay_bootstraps_history_then_preserves_every_increment():
    league, pool, events = _full_draft_fixture()
    before_league, before_pool = deepcopy(league), deepcopy(pool)
    text = "ON THE CLOCK: PICK 46\n" + _replay_activity(events, 45)
    with pytest.raises(ESPNDataError, match="incomplete"):
        _replay_parse(league, pool, text)
    state = _replay_parse(league, pool, text + "\n" + _replay_history(events, 45))
    assert len(state.picks) == 45 and state.rules.teams == 10 and state.rules.rounds == 16
    for through in range(46, 160):
        previous = state
        frozen_previous = previous.model_dump(mode="json")
        state = _replay_parse(league, pool, f"ON THE CLOCK: PICK {through + 1}\n" + _replay_activity(events, through), previous)
        assert len(state.picks) == through
        assert state.source.browser.current_pick == through + 1
        assert previous.model_dump(mode="json") == frozen_previous
    # ESPN may still expose only placeholders when the visible draft ends.
    state = _replay_parse(league, pool, "DRAFT COMPLETE\n" + _replay_activity(events, 160), state)
    assert state.source.browser.draft_complete and state.source.browser.current_pick == 161
    assert len(state.picks) == len({p.player_id for p in state.picks}) == 160
    assert [p.player_id for p in state.picks] == [row["id"] for row in events]
    assert [p.slot for p in state.picks] == [row["slot"] for row in events]
    assert all(len(team.roster_ids) == 16 for team in state.teams)
    assert all(team.roster_ids == [row["id"] for row in events if row["slot"] == team.slot] for team in state.teams)
    assert league == before_league and pool == before_pool
    assert all(pick["playerId"] == -1 for pick in league["draftDetail"]["picks"])


@pytest.mark.parametrize("failure", ["missing_history", "conflicting_pick", "duplicate_player", "unknown_player", "false_completion"])
def test_full_draft_replay_rejects_unproven_progress_without_changing_previous(failure):
    league, pool, events = _full_draft_fixture()
    previous = _replay_parse(league, pool, "ON THE CLOCK: PICK 46\n" + _replay_history(events, 45))
    frozen_previous = previous.model_dump(mode="json")
    text = "ON THE CLOCK: PICK 47\n" + _replay_activity(events, 46)
    if failure == "missing_history":
        text = "ON THE CLOCK: PICK 51\n" + _replay_activity(events, 50)
    elif failure == "conflicting_pick":
        text = text.replace(events[44]["name"], events[45]["name"])
    elif failure == "duplicate_player":
        text = text.replace(events[45]["name"], events[44]["name"])
    elif failure == "unknown_player":
        text = text.replace(events[45]["name"], "Fictional Unknown Player")
    else:
        text = "DRAFT COMPLETE\n" + _replay_activity(events, 46)
    with pytest.raises(ESPNDataError):
        _replay_parse(league, pool, text, previous)
    assert previous.model_dump(mode="json") == frozen_previous


@pytest.mark.parametrize("label", ["WR CB", "WRCB", "WR\nCB"])
def test_history_two_way_player_retains_primary_position_and_exact_owner(label):
    from fantasy_football_manager.espn_data import _visible_picks
    from fantasy_football_manager.models import Player
    player = Player(id="901", name="Fictional Two Way", position="WR", projection=100)
    header = "PICK HISTORY\nPICK\nPLAYER\nTEAM\n2025 PTS\nPROJ PTS\nRK\n"
    text = header + f"1\nFictional Two Way\nDTD\nABC\n{label}\nFictional North\n10\n100\n1"
    assert _visible_picks(text, [player], 2, {1: "Fictional North", 2: "Fictional South"}) == [(1, "901")]
    with pytest.raises(ESPNDataError, match="owner"):
        _visible_picks(text.replace("Fictional North", "Fictional South"), [player], 2,
                       {1: "Fictional North", 2: "Fictional South"})


def test_accessible_history_accepts_dtd_and_wr_cb_but_rejects_wrong_owner_or_primary():
    from fantasy_football_manager.espn_data import _visible_picks
    from fantasy_football_manager.models import Player
    player = Player(id="901", name="Fictional Two Way", position="WR", projection=100)
    text = 'PICK HISTORY\n- row "1 Fictional Two Way DTD ABC WR CB Fictional North 10 100 1":'
    teams = {1: "Fictional North", 2: "Fictional South"}
    assert _visible_picks(text, [player], 2, teams) == [(1, "901")]
    with pytest.raises(ESPNDataError, match="owner"):
        _visible_picks(text.replace("Fictional North", "Fictional South"), [player], 2, teams)
    with pytest.raises(ESPNDataError):
        _visible_picks(text.replace("WR CB", "RB CB"), [player], 2, teams)


@pytest.mark.parametrize("missing", ["absent_record", "empty_stats"])
@pytest.mark.parametrize("evidence", ["activity", "api", "body_history", "aria_history"])
def test_unprojected_opponent_pick_retains_identity_without_inventing_points(missing, evidence):
    league, pool = fixture()
    raw = pool["players"][0]["player"]
    if missing == "absent_record":
        raw["stats"] = []
    else:
        raw["stats"][0]["stats"] = {}
    text = "ON THE CLOCK: PICK 2\nENABLE AUTOPICK\n"
    if evidence == "api":
        league["draftDetail"]["picks"] = [api_pick(1, 101)]
    elif evidence == "activity":
        text += "Runner Alpha / ABC RB R1, P1 - Fictional North"
    elif evidence == "aria_history":
        text += 'PICK HISTORY\n- row "1 Runner Alpha ABC RB Fictional North - - 1"'
    else:
        text += "PICK HISTORY\nPICK\nPLAYER\nTEAM\n2025 PTS\nPROJ PTS\nRK\n1\nRunner Alpha\nABC\nRB\nFictional North\n-\n-\n1"
    fetched = datetime.now(timezone.utc) - timedelta(minutes=2)
    state = parse(league, pool, visible_text=text, projections_observed_at=fetched)
    unknown = next(p for p in state.players if p.id == "101")
    assert unknown.projection is None and unknown.position == "RB"
    assert state.teams[0].roster_ids == ["101"] and state.own_team().roster_ids == []
    assert state.source.complete and state.source.projections_observed_at == fetched
    assert any("Retained 1 opponent draft identities" in note for note in state.source.notes)
    # The next observation may have neither a complete API log nor that Activity row.
    league["draftDetail"]["picks"] = []
    fresh = parse(league, pool, previous=state, visible_text="ON THE CLOCK: PICK 2", projections_observed_at=fetched)
    assert fresh.picks == state.picks
    assert next(p for p in fresh.players if p.id == "101").projection is None
    if evidence == "api":
        league["draftDetail"]["picks"] = [api_pick(1, 101)]
    with pytest.raises(ESPNDataError, match="required player"):
        parse(league, pool, visible_text=text, team_id=11,
              page_url=URL.replace("teamId=22", "teamId=11"))


def test_unprojected_identity_cannot_hide_ambiguous_name_or_wrong_owner():
    league, pool = fixture()
    pool["players"][0]["player"]["stats"][0]["stats"] = {}
    text = "ON THE CLOCK: PICK 2\nRunner Alpha / ABC RB R1, P1 - Fictional North"
    with pytest.raises(ESPNDataError, match="owner"):
        parse(league, pool, visible_text=text.replace("Fictional North", "Fictional South"))
    pool["players"][2]["player"]["fullName"] = "Runner Alpha"
    with pytest.raises(ESPNDataError, match="one verified player"):
        parse(league, pool, visible_text=text)


def test_rostered_unprojected_identity_requires_verified_opponent_history():
    league, pool = fixture()
    pool["players"][0]["player"]["stats"] = []
    pool["players"][0]["onTeamId"] = 11
    with pytest.raises(ESPNDataError, match="required player"):
        parse(league, pool)
    league["draftDetail"]["picks"] = [api_pick(1, 101)]
    state = parse(league, pool, visible_text="ON THE CLOCK: PICK 2")
    assert state.players[0].projection is None


def test_full_draft_replay_can_complete_with_unprojected_opponent_identity():
    league, pool, events = _full_draft_fixture()
    pool["players"][132]["player"]["stats"][0]["stats"] = {}
    extra = deepcopy(pool["players"][0])
    extra["id"] = 99999
    extra["player"].update(id=99999, fullName="Fictional Reserve Example")
    pool["players"].append(extra)
    state = _replay_parse(league, pool, "ON THE CLOCK: PICK 133\n" + _replay_history(events, 132))
    assert events[132]["id"] not in {p.id for p in state.players}
    state = _replay_parse(league, pool, "ON THE CLOCK: PICK 134\n" + _replay_activity(events, 133), state)
    state = _replay_parse(league, pool, "DRAFT COMPLETE\n" + _replay_history(events, 160), state)
    assert len(state.picks) == 160 and state.source.browser.current_pick == 161
    assert state.source.browser.draft_complete
    assert all(len(team.roster_ids) == 16 for team in state.teams)
    assert next(p for p in state.players if p.id == events[132]["id"]).projection is None
