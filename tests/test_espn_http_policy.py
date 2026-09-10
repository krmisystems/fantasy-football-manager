"""HTTP action policy tests use fictional normalized observations and no network."""

from datetime import datetime, timedelta, timezone

import pytest

from fantasy_football_manager.espn_http_client import league_url
from fantasy_football_manager.models import Budget, ESPNPlayerState, LeagueSnapshot, ManagerConfig
from fantasy_football_manager.policy import PolicyError, check_action
from fantasy_football_manager.season import lineup_delta
from test_espn_season_data import own_locks, parse


BASE = {"RB1": "101", "FLEX1": "102"}
SWAP = {"RB1": "103", "FLEX1": "102"}
ADD = {"player_id": "109", "drop_id": "103", "bid": 0}


def http_snapshot():
    value = parse(player_locks=own_locks()).model_dump(mode="json")
    value["source"].update(provider="espn_http", browser=None, http={
        "league_id": "123", "team_id": "1", "season": 2026, "week": 1,
        "roster_url": league_url("123", 2026) + "?view=mRoster&forTeamId=1&scoringPeriodId=1",
        "ownership_verified": True, "transaction_period": 1, "latest_period": 1, "final_period": 18,
        "team_transaction_locked": False, "pending_transactions_known": True,
        "uses_faab": True, "minimum_bid": 0, "uses_undroppable_list": True,
        "acquisition_limit": -1, "matchup_acquisition_limit": -1,
        "acquisitions_season": 0, "acquisitions_period": 0,
    })
    value["budget"] = Budget(balance=100, pending_amount=0, pending_moves=0).model_dump()
    snapshot = LeagueSnapshot.model_validate(value)
    for player in snapshot.players:
        player.locked = False
        player.espn = ESPNPlayerState(roster_locked=False, trade_locked=False, droppable=True,
                                     injured=player.id == "104", bye_verified=True, eligible_slots=[2, 20, 21, 23],
                                     acquisition_status="FREEAGENT" if player.id == "109" else "ONTEAM")
        if player.id in {"103", "109"}:
            player.weekly_projection = 20 if player.id == "103" else 30
    return snapshot


def automatic_config():
    return ManagerConfig(automation={"preset": "bounded_automation"}, limits={"drop_mode": "any_unprotected"})


def decide(snapshot, action="set_lineup", payload=None, config=None):
    return check_action(snapshot, config or automatic_config(), action,
                        {"lineup": SWAP} if payload is None else payload, execution_scope="espn_http")


def test_http_scope_requires_explicit_owner_period_and_complete_platform_state():
    snapshot = http_snapshot()
    assert decide(snapshot)["mode"] == "automatic"
    for attribute, value in [("ownership_verified", False), ("team_transaction_locked", None),
                             ("team_transaction_locked", True), ("pending_transactions_known", False),
                             ("transaction_period", 2)]:
        bad = snapshot.model_copy(deep=True)
        setattr(bad.source.http, attribute, value)
        with pytest.raises(PolicyError):
            decide(bad)


@pytest.mark.parametrize("change", [
    lambda snap: setattr(snap.source, "locks_verified", False),
    lambda snap: setattr(snap.source, "complete", False),
    lambda snap: setattr(snap.source, "observed_at", datetime.now(timezone.utc) - timedelta(minutes=6)),
    lambda snap: setattr(snap.source, "projections_observed_at", None),
])
def test_unknown_or_stale_evidence_cannot_authorize(change):
    snapshot = http_snapshot()
    change(snapshot)
    with pytest.raises(PolicyError):
        decide(snapshot)


@pytest.mark.parametrize("attribute,value", [("roster_locked", None), ("roster_locked", True),
                                             ("trade_locked", None), ("trade_locked", True),
                                             ("pending_transaction_ids", ["fictional-trade"])])
def test_changed_players_require_clear_roster_trade_and_pending_locks(attribute, value):
    snapshot = http_snapshot()
    setattr(snapshot.players[2].espn, attribute, value)
    with pytest.raises(PolicyError):
        decide(snapshot)


def test_pending_trade_items_block_a_player_even_without_player_level_ids():
    snapshot = http_snapshot()
    snapshot.source.http.pending_transactions = [{"type": "TRADE", "items": [{"playerId": 103}]}]
    with pytest.raises(PolicyError, match="pending ESPN transaction"):
        decide(snapshot)


@pytest.mark.parametrize("player_id", ["101", "103"])
def test_started_incoming_or_outgoing_players_cannot_move(player_id):
    snapshot = http_snapshot()
    next(p for p in snapshot.players if p.id == player_id).locked = True
    with pytest.raises(PolicyError, match="locked player"):
        decide(snapshot)


def test_locked_unchanged_unknown_projection_cancels_from_known_swap():
    snapshot = http_snapshot()
    snapshot.players[1].locked = True
    snapshot.players[1].weekly_projection = None
    decision = decide(snapshot)
    assert decision["payload"]["lineup"] == SWAP
    assert lineup_delta(BASE, SWAP, {p.id: p for p in snapshot.players}) == 8
    assert snapshot.players[1].weekly_projection is None


def test_unknown_starter_needs_exact_configured_repair_and_never_becomes_zero():
    snapshot, config = http_snapshot(), automatic_config()
    snapshot.players[0].weekly_projection = None
    snapshot.players[0].availability = "DOUBTFUL"
    with pytest.raises(PolicyError, match="Weekly projections"):
        decide(snapshot)
    payload = {"lineup": SWAP, "repair_player_id": "101"}
    with pytest.raises(PolicyError, match="authorization"):
        decide(snapshot, payload=payload, config=config)
    config.limits.coverage_repair_ids = ["102"]
    with pytest.raises(PolicyError, match="authorization"):
        decide(snapshot, payload=payload, config=config)
    config.limits.coverage_repair_ids = ["101"]
    decision = decide(snapshot, payload=payload, config=config)
    assert decision["payload"] == payload and "improvement" not in decision
    assert lineup_delta(BASE, SWAP, {p.id: p for p in snapshot.players}) is None
    assert snapshot.players[0].weekly_projection is None


def test_repair_cannot_move_other_starters_or_use_an_unknown_replacement():
    snapshot, config = http_snapshot(), automatic_config()
    snapshot.players[0].weekly_projection = None
    config.limits.coverage_repair_ids = ["101"]
    with pytest.raises(PolicyError, match="exactly"):
        decide(snapshot, payload={"lineup": {"RB1": "103", "FLEX1": "101"}, "repair_player_id": "101"}, config=config)
    snapshot.players[2].weekly_projection = None
    with pytest.raises(PolicyError, match="replacement starter"):
        decide(snapshot, payload={"lineup": SWAP, "repair_player_id": "101"}, config=config)


def test_repair_is_not_authority_for_a_healthy_or_started_starter():
    snapshot, config = http_snapshot(), automatic_config()
    config.limits.coverage_repair_ids = ["101"]
    payload = {"lineup": SWAP, "repair_player_id": "101"}
    with pytest.raises(PolicyError, match="coverage gap"):
        decide(snapshot, payload=payload, config=config)
    snapshot.players[0].weekly_projection = None
    snapshot.players[0].locked = True
    with pytest.raises(PolicyError, match="locked player"):
        decide(snapshot, payload=payload, config=config)


def test_exact_acquisition_repair_preserves_starters_and_requires_incoming_projection():
    snapshot, config = http_snapshot(), automatic_config()
    snapshot.players[0].weekly_projection = None
    config.limits.coverage_repair_ids = ["101"]
    with pytest.raises(PolicyError, match="Complete comparisons"):
        decide(snapshot, "free_agent_add", ADD, config)
    payload = {**ADD, "repair_player_id": "101"}
    assert decide(snapshot, "free_agent_add", payload, config)["payload"] == payload
    with pytest.raises(PolicyError, match="cannot drop a current starter"):
        decide(snapshot, "free_agent_add", {**payload, "drop_id": "102"}, config)
    incoming = next(p for p in snapshot.players if p.id == "109")
    incoming.eligible_positions = ["WR"]
    with pytest.raises(PolicyError, match="authorized slot"):
        decide(snapshot, "free_agent_add", payload, config)
    incoming.eligible_positions = ["RB"]
    incoming.weekly_projection = None
    with pytest.raises(PolicyError, match="verified weekly projection"):
        decide(snapshot, "free_agent_add", payload, config)


@pytest.mark.parametrize("action", ["free_agent_add", "waiver_claim"])
def test_coverage_acquisition_cannot_spend_or_drop_for_a_bye_week_player(action):
    snapshot, config = http_snapshot(), automatic_config()
    snapshot.players[0].weekly_projection = None
    config.limits.coverage_repair_ids = ["101"]
    incoming = next(p for p in snapshot.players if p.id == "109")
    incoming.espn.acquisition_status = "FREEAGENT" if action == "free_agent_add" else "WAIVERS"
    payload = {**ADD, "repair_player_id": "101"}
    assert decide(snapshot, action, payload, config)["mode"] == "automatic"
    incoming.bye = snapshot.week
    with pytest.raises(PolicyError, match="bye"):
        decide(snapshot, action, payload, config)
    assert snapshot.own_team().roster_ids == ["101", "102", "103"]
    assert snapshot.budget.spent_season == 0


def test_named_coverage_repair_can_resolve_one_of_two_unavailable_starters():
    snapshot, config = http_snapshot(), automatic_config()
    for player in snapshot.players[:2]:
        player.weekly_projection = None
        player.availability = "DOUBTFUL"
    config.limits.coverage_repair_ids = ["101", "102"]
    payload = {"lineup": SWAP, "repair_player_id": "101"}
    assert decide(snapshot, payload=payload, config=config)["payload"] == payload
    assert lineup_delta(BASE, SWAP, {p.id: p for p in snapshot.players}) is None
    assert snapshot.players[1].weekly_projection is None
    with pytest.raises(PolicyError, match="available"):
        decide(snapshot, payload={"lineup": SWAP}, config=config)
    incoming = next(p for p in snapshot.players if p.id == "103")
    incoming.bye = snapshot.week
    with pytest.raises(PolicyError, match="available"):
        decide(snapshot, payload=payload, config=config)


@pytest.mark.parametrize("verified", [None, False])
@pytest.mark.parametrize("action", ["set_lineup", "free_agent_add", "waiver_claim"])
def test_unknown_bye_evidence_cannot_authorize_a_new_starter_or_acquisition(action, verified):
    snapshot, config = http_snapshot(), automatic_config()
    snapshot.players[0].weekly_projection = None
    config.limits.coverage_repair_ids = ["101"]
    incoming = next(p for p in snapshot.players if p.id == ("103" if action == "set_lineup" else "109"))
    incoming.espn.bye_verified = verified
    incoming.bye = None
    if action == "waiver_claim":
        incoming.espn.acquisition_status = "WAIVERS"
    payload = {"lineup": SWAP} if action == "set_lineup" else dict(ADD)
    payload["repair_player_id"] = "101"
    with pytest.raises(PolicyError, match="[Bb]ye"):
        decide(snapshot, action, payload, config)


@pytest.mark.parametrize("uses,droppable", [(True, False), (True, None), (None, True)])
def test_drop_requires_verified_undroppable_setting(uses, droppable):
    snapshot = http_snapshot()
    snapshot.source.http.uses_undroppable_list = uses
    snapshot.players[2].espn.droppable = droppable
    with pytest.raises(PolicyError, match="can be dropped"):
        decide(snapshot, "free_agent_add", ADD)


def test_ir_requires_live_injury_and_slot_eligibility_not_doubtful_label():
    snapshot = http_snapshot()
    snapshot.rules.ir = 2
    snapshot.players[2].availability = "DOUBTFUL"
    with pytest.raises(PolicyError, match="injury status"):
        decide(snapshot, "move_to_ir", {"player_id": "103"})
    snapshot.players[2].espn.injured = True
    snapshot.players[2].espn.eligible_slots = [2, 20]
    with pytest.raises(PolicyError, match="IR slot eligibility"):
        decide(snapshot, "move_to_ir", {"player_id": "103"})
    snapshot.players[2].espn.eligible_slots.append(21)
    assert decide(snapshot, "move_to_ir", {"player_id": "103"})["payload"] == {"player_id": "103"}
    snapshot.rules.ir = 1
    with pytest.raises(PolicyError, match="available IR slot"):
        decide(snapshot, "move_to_ir", {"player_id": "103"})


def test_ir_activation_requires_open_space_and_verified_bench_eligibility():
    snapshot = http_snapshot()
    with pytest.raises(PolicyError, match="available active roster slot"):
        decide(snapshot, "activate_from_ir", {"player_id": "104"})
    snapshot.own_team().roster_ids.remove("103")
    assert decide(snapshot, "activate_from_ir", {"player_id": "104"})["payload"] == {"player_id": "104"}
    snapshot.players[3].espn.eligible_slots = [21]
    with pytest.raises(PolicyError, match="bench eligibility"):
        decide(snapshot, "activate_from_ir", {"player_id": "104"})


def test_faab_and_traditional_waivers_use_distinct_bid_rules():
    snapshot = http_snapshot()
    next(p for p in snapshot.players if p.id == "109").espn.acquisition_status = "WAIVERS"
    snapshot.source.http.minimum_bid = 2
    with pytest.raises(PolicyError, match="league minimum"):
        decide(snapshot, "waiver_claim", ADD)
    assert decide(snapshot, "waiver_claim", {**ADD, "bid": 2})["payload"]["bid"] == 2
    snapshot.budget.pending_amount = 20
    with pytest.raises(PolicyError, match="weekly FAAB"):
        decide(snapshot, "waiver_claim", {**ADD, "bid": 2})
    snapshot.source.http.uses_faab = False
    snapshot.budget.balance = 0
    assert decide(snapshot, "waiver_claim", ADD)["payload"]["bid"] == 0
    with pytest.raises(PolicyError, match="Traditional waivers"):
        decide(snapshot, "waiver_claim", {**ADD, "bid": 2})


def test_acquisition_status_and_each_action_mode_are_enforced():
    snapshot, config = http_snapshot(), automatic_config()
    with pytest.raises(PolicyError, match="acquisition status"):
        decide(snapshot, "waiver_claim", ADD)
    config.automation.preset = "custom"
    config.automation.actions.update(free_agent_add="automatic", drop_player="advisory")
    with pytest.raises(PolicyError, match="Every part"):
        decide(snapshot, "free_agent_add", ADD, config)


@pytest.mark.parametrize("limit,count", [("acquisition_limit", "acquisitions_season"),
                                        ("matchup_acquisition_limit", "acquisitions_period")])
def test_platform_acquisition_limits_include_pending_moves_and_unknown_counts(limit, count):
    snapshot = http_snapshot()
    setattr(snapshot.source.http, limit, None)
    with pytest.raises(PolicyError):
        decide(snapshot, "free_agent_add", ADD)
    setattr(snapshot.source.http, limit, 2)
    setattr(snapshot.source.http, count, None)
    with pytest.raises(PolicyError):
        decide(snapshot, "free_agent_add", ADD)
    setattr(snapshot.source.http, count, 1)
    assert decide(snapshot, "free_agent_add", ADD)["scope"] == "espn_http"
    snapshot.budget.pending_moves = 1
    with pytest.raises(PolicyError):
        decide(snapshot, "free_agent_add", ADD)
