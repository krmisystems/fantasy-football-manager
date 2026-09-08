"""Live policy checks use fictional observations and do not access ESPN."""

from datetime import datetime, timedelta, timezone

import pytest

from fantasy_football_manager.models import BrowserObservation, LeagueSnapshot, ManagerConfig
from fantasy_football_manager.policy import PolicyError, check_action


def live_snapshot():
    now = datetime.now(timezone.utc)
    return LeagueSnapshot.model_validate({
        "league_id": "fictional-league", "team_id": "fictional-team-a", "season": 2026, "phase": "draft",
        "source": {"provider": "espn_browser", "synthetic": False, "complete": True,
                   "observed_at": now, "projections_observed_at": now,
                   "browser": {"page_url": "https://fantasy.espn.com/football/draft?leagueId=fictional-league&teamId=fictional-team-a",
                               "league_id": "fictional-league", "team_id": "fictional-team-a",
                               "current_pick": 1, "autopick_enabled": False, "draft_complete": False}},
        "rules": {"teams": 2, "slot": 1, "rounds": 1, "starters": {"RB": 1}, "bench": 0},
        "players": [{"id": "fictional-rb-a", "name": "Fictional RB A", "position": "RB", "projection": 200,
                     "adp": 1, "availability": "ACTIVE"},
                    {"id": "fictional-rb-b", "name": "Fictional RB B", "position": "RB", "projection": 190,
                     "adp": 2, "availability": "ACTIVE"}],
        "teams": [{"id": "fictional-team-a", "name": "Fictional team A", "slot": 1},
                  {"id": "fictional-team-b", "name": "Fictional team B", "slot": 2}]})


def config(preset="review"):
    return ManagerConfig(automation={"preset": preset})


def host_check(snapshot=None, settings=None, action="draft_pick", payload=None):
    return check_action(snapshot or live_snapshot(), settings or config(), action,
                        payload if payload is not None else {"player_id": "fictional-rb-a"}, execution_scope="host_browser")


def test_default_execution_scope_cannot_execute_live_data():
    with pytest.raises(PolicyError, match="synthetic"):
        check_action(live_snapshot(), config(), "draft_pick", {"player_id": "fictional-rb-a"})


@pytest.mark.parametrize("preset, mode, confirmation", [("review", "review", True), ("bounded_automation", "automatic", False)])
def test_supported_modes_report_host_scope_without_mutating_snapshot(preset, mode, confirmation):
    snapshot = live_snapshot()
    before = snapshot.model_dump(mode="json")
    decision = host_check(snapshot, config(preset))
    assert decision == {"mode": mode, "payload": {"player_id": "fictional-rb-a"},
                        "requires_confirmation": confirmation, "scope": "host_browser"}
    assert snapshot.model_dump(mode="json") == before


@pytest.mark.parametrize("bad_state", ["missing_browser", "wrong_clock", "unknown_clock", "draft_complete", "autopick_on", "autopick_unknown",
                                       "wrong_provider", "synthetic", "incomplete", "paused", "advisory", "disabled"])
def test_live_execution_rejects_unverified_or_disallowed_state(bad_state):
    snapshot, settings = live_snapshot(), config()
    if bad_state == "missing_browser":
        snapshot.source.browser = None
    elif bad_state == "wrong_clock":
        snapshot.source.browser.current_pick = 2
    elif bad_state == "unknown_clock":
        snapshot.source.browser.current_pick = None
    elif bad_state == "draft_complete":
        snapshot.source.browser.draft_complete = True
    elif bad_state == "autopick_on":
        snapshot.source.browser.autopick_enabled = True
    elif bad_state == "autopick_unknown":
        snapshot.source.browser.autopick_enabled = None
    elif bad_state == "wrong_provider":
        snapshot.source.provider = "imported_json"
    elif bad_state == "synthetic":
        snapshot.source.synthetic = True
    elif bad_state == "incomplete":
        snapshot.source.complete = False
    elif bad_state == "paused":
        settings.automation.paused = True
    elif bad_state == "advisory":
        settings.automation.preset = "advisory"
    else:
        settings.automation.preset = "custom"
        settings.automation.actions["draft_pick"] = "disabled"
    with pytest.raises(PolicyError):
        host_check(snapshot, settings)


def test_snapshot_age_uses_15_second_default():
    snapshot, settings = live_snapshot(), config()
    assert settings.limits.max_draft_age_seconds == 15
    snapshot.source.observed_at -= timedelta(seconds=16)
    with pytest.raises(PolicyError, match="snapshot is stale"):
        host_check(snapshot, settings)


def test_projection_age_uses_separate_one_hour_default():
    snapshot, settings = live_snapshot(), config()
    assert settings.limits.max_projection_age_seconds == 3600
    snapshot.source.projections_observed_at -= timedelta(seconds=1800)
    assert host_check(snapshot, settings)["scope"] == "host_browser"
    snapshot.source.projections_observed_at -= timedelta(seconds=1801)
    with pytest.raises(PolicyError, match="projections are stale"):
        host_check(snapshot, settings)


def test_unknown_projection_time_cannot_authorize_live_pick():
    snapshot = live_snapshot()
    snapshot.source.projections_observed_at = None
    with pytest.raises(PolicyError, match="observation time"):
        host_check(snapshot)


@pytest.mark.parametrize("action, payload", [("set_lineup", {"lineup": {"RB1": "fictional-rb-a"}}),
                                             ("waiver_claim", {"player_id": "fictional-rb-a"}),
                                             ("trade_offer", {}), ("trade_accept", {})])
def test_host_browser_route_does_not_execute_season_or_trade_actions(action, payload):
    with pytest.raises(PolicyError):
        host_check(action=action, payload=payload)


def test_draft_pick_cannot_run_in_season_phase():
    snapshot = live_snapshot()
    snapshot.phase = "season"
    with pytest.raises(PolicyError, match="draft snapshot"):
        host_check(snapshot)


@pytest.mark.parametrize("field, value", [("league_id", "other-fictional-league"), ("team_id", "fictional-team-b")])
def test_browser_identity_must_match_selected_context(field, value):
    snapshot = live_snapshot().model_dump(mode="json")
    browser = snapshot["source"]["browser"]
    browser[field] = value
    browser["page_url"] = f"https://fantasy.espn.com/football/draft?leagueId={browser['league_id']}&teamId={browser['team_id']}"
    with pytest.raises(ValueError, match="match the selected"):
        LeagueSnapshot.model_validate(snapshot)


@pytest.mark.parametrize("url", ["http://fantasy.espn.com/football/draft?leagueId=fictional-league",
                                 "https://fantasy.espn.com.invalid/football/draft?leagueId=fictional-league",
                                 "https://name:secret@fantasy.espn.com/football/draft?leagueId=fictional-league",
                                 "https://fantasy.espn.com/football/draft?leagueId=other-fictional-league",
                                 "https://fantasy.espn.com/football/draft?leagueId=fictional-league&teamId=wrong-team",
                                 "https://fantasy.espn.com/football/draft?leagueId=fictional-league&leagueId=other-fictional-league"])
def test_browser_location_rejects_nonofficial_or_conflicting_context(url):
    with pytest.raises(ValueError):
        BrowserObservation(page_url=url, league_id="fictional-league", team_id="fictional-team-a")


def test_unknown_execution_scope_has_no_demo_fallback():
    with pytest.raises(PolicyError, match="Unknown execution scope"):
        check_action(live_snapshot(), config(), "draft_pick", {"player_id": "fictional-rb-a"}, execution_scope="unknown")
