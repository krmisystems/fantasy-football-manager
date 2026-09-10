"""Durable HTTP proposal tests use temporary databases and fictional observations."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from fantasy_football_manager.espn_http_actions import ESPNHTTPActions, transaction_body, transaction_items
from fantasy_football_manager.espn_http_client import league_url
from fantasy_football_manager.policy import PolicyError
from fantasy_football_manager.store import Manager
from test_espn_http_policy import ADD, BASE, SWAP, automatic_config, http_snapshot


@pytest.fixture
def setup(tmp_path):
    manager = Manager(tmp_path)
    manager.import_snapshot(http_snapshot().model_dump(mode="json"))
    config = automatic_config()
    config.automation.preset = "review"
    manager.update_config(config.model_dump(mode="json"), 0)
    return manager, ESPNHTTPActions(manager)


def claim(actions, action="set_lineup", payload=None):
    proposal = actions.prepare(action, {"lineup": SWAP} if payload is None else payload)
    return actions.authorize(proposal["proposal_id"], confirmation=True)


def fresh(manager, *, lineup=None):
    snapshot = manager.state()[0].model_copy(deep=True)
    snapshot.source.observed_at = datetime.now(timezone.utc)
    snapshot.source.projections_observed_at = snapshot.source.observed_at
    if lineup is not None:
        snapshot.own_team().lineup = dict(lineup)
    return snapshot


def response_for(snapshot, action, payload, **changes):
    response = {"id": "fictional-transaction", "teamId": int(snapshot.team_id), "scoringPeriodId": snapshot.week,
                "type": {"free_agent_add": "FREEAGENT", "waiver_claim": "WAIVER"}.get(action, "ROSTER"),
                "status": "PENDING" if action == "waiver_claim" else "EXECUTED", "isPending": action == "waiver_claim",
                "items": transaction_items(snapshot, action, payload)}
    if action == "waiver_claim" and snapshot.source.http.uses_faab:
        response["bidAmount"] = payload.get("bid", 0)
    response.update(changes)
    return response


def waiver_claim(manager, actions):
    snapshot = fresh(manager)
    next(p for p in snapshot.players if p.id == "109").espn.acquisition_status = "WAIVERS"
    manager.import_snapshot(snapshot.model_dump(mode="json"), manager.state()[2])
    permit = claim(actions, "waiver_claim", ADD)
    response = response_for(snapshot, "waiver_claim", ADD)
    actions.record_response(permit["proposal_id"], response)
    return permit, response


def test_prepare_has_durable_evidence_and_does_not_change_team(setup):
    manager, actions = setup
    before = manager.state()
    proposal = actions.prepare("set_lineup", {"lineup": SWAP})
    assert proposal["status"] == "pending" and not proposal["should_submit"] and not proposal["retry_allowed"]
    assert proposal["scope"] == "espn_http" and proposal["payload"] == {"lineup": SWAP}
    assert manager.state() == before
    with manager.transaction() as db:
        row = db.execute("SELECT baseline,decision FROM espn_http_proposals").fetchone()
        assert json.loads(row["baseline"]) == before[0].model_dump(mode="json")
        assert json.loads(row["decision"])["requires_confirmation"]


def test_review_confirmation_and_concurrent_replay_authorize_one_request(setup):
    manager, actions = setup
    proposal = actions.prepare("set_lineup", {"lineup": SWAP})
    with pytest.raises(PolicyError, match="confirmation"):
        actions.authorize(proposal["proposal_id"])
    restarted = ESPNHTTPActions(Manager(manager.data_dir))
    with ThreadPoolExecutor(max_workers=2) as pool:
        permits = list(pool.map(lambda service: service.authorize(proposal["proposal_id"], True), [actions, restarted]))
    assert sum(permit["should_submit"] for permit in permits) == 1
    assert len(actions.pending()) == 1 and manager.state()[0].own_team().lineup == BASE
    with pytest.raises(PolicyError, match="awaits verification"):
        actions.prepare("free_agent_add", ADD)


@pytest.mark.parametrize("change", ["state", "config"])
def test_prepare_cannot_survive_state_or_config_revision_change(setup, change):
    manager, actions = setup
    proposal = actions.prepare("set_lineup", {"lineup": SWAP})
    if change == "state":
        manager.import_snapshot(fresh(manager).model_dump(mode="json"), manager.state()[2])
    else:
        manager.update_config(manager.state()[1].model_dump(mode="json"), manager.state()[3])
    with pytest.raises(PolicyError, match="changed"):
        actions.authorize(proposal["proposal_id"], True)
    assert actions.get(proposal["proposal_id"])["status"] == "pending"


def test_authorized_replay_after_restart_and_config_change_never_reissues(setup):
    manager, actions = setup
    permit = claim(actions)
    manager.update_config(manager.state()[1].model_dump(mode="json"), manager.state()[3])
    restarted = ESPNHTTPActions(Manager(manager.data_dir))
    assert not restarted.authorize(permit["proposal_id"], True)["should_submit"]
    with pytest.raises(PolicyError, match="changed"):
        restarted.validate_permit(permit, fresh(manager).model_dump(mode="json"))


@pytest.mark.parametrize("change", ["payload", "week", "claim_flag", "roster", "period", "old", "started"])
def test_preflight_rejects_changed_permit_and_live_context(setup, change):
    manager, actions = setup
    permit = claim(actions)
    snapshot = fresh(manager)
    assert actions.validate_permit(permit, snapshot.model_dump(mode="json"))
    if change == "payload":
        permit["payload"] = {"lineup": BASE}
    elif change == "week":
        permit["week"] = 2
    elif change == "claim_flag":
        permit["should_submit"] = False
    elif change == "roster":
        snapshot.own_team().lineup = SWAP
    elif change == "period":
        snapshot.source.http.transaction_period = 2
    elif change == "old":
        snapshot.source.observed_at = datetime.fromisoformat(permit["authorized_at"]) - timedelta(seconds=1)
    else:
        snapshot.players[2].locked = True
    with pytest.raises(PolicyError):
        actions.validate_permit(permit, snapshot.model_dump(mode="json"))
    assert len(actions.pending()) == 1 and manager.state()[0].own_team().lineup == BASE


@pytest.mark.parametrize("actual,status", [(SWAP, "confirmed"), ({"RB1": "101", "FLEX1": "103"}, "conflict")])
def test_observation_confirms_or_conflicts_and_replay_is_durable(setup, actual, status):
    manager, actions = setup
    permit = claim(actions)
    revision = manager.state()[2]
    result = actions.reconcile(permit["proposal_id"], fresh(manager, lineup=actual).model_dump(mode="json"))
    assert result["status"] == status and result["revision"] == revision + 1
    assert not result["should_submit"] and not result["retry_allowed"]
    assert manager.state()[0].own_team().lineup == actual and actions.pending() == []
    before, history = manager.state(), manager.history()
    restarted = ESPNHTTPActions(Manager(manager.data_dir))
    assert restarted.authorize(permit["proposal_id"], True) == result
    assert restarted.reconcile(permit["proposal_id"], fresh(manager).model_dump(mode="json")) == result
    assert manager.state() == before and manager.history() == history


def test_success_shaped_http_response_without_roster_change_is_not_confirmation(setup):
    manager, actions = setup
    permit = claim(actions)
    snapshot = fresh(manager)
    response = response_for(snapshot, "set_lineup", {"lineup": SWAP})
    response["irrelevant_private_field"] = "fictional-secret-must-not-persist"
    saved = actions.record_response(permit["proposal_id"], response)
    assert "irrelevant_private_field" not in saved
    before = manager.state()
    result = actions.reconcile(permit["proposal_id"], snapshot.model_dump(mode="json"))
    assert result["status"] == "awaiting_verification" and not result["retry_allowed"]
    assert manager.state() == before and len(actions.pending()) == 1


@pytest.mark.parametrize("change", ["unknown", "team", "period", "type", "items", "bid"])
def test_unknown_or_mismatched_response_keeps_claim_unresolved(setup, change):
    manager, actions = setup
    snapshot = fresh(manager)
    next(p for p in snapshot.players if p.id == "109").espn.acquisition_status = "WAIVERS"
    manager.import_snapshot(snapshot.model_dump(mode="json"), manager.state()[2])
    permit = claim(actions, "waiver_claim", ADD)
    response = response_for(snapshot, "waiver_claim", ADD)
    if change == "unknown":
        response = {"success": True}
    elif change == "team":
        response["teamId"] = 2
    elif change == "period":
        response["scoringPeriodId"] = 2
    elif change == "type":
        response["type"] = "FREEAGENT"
    elif change == "items":
        response["items"][0]["playerId"] = 105
    else:
        response["bidAmount"] = 7
    with pytest.raises(PolicyError):
        actions.record_response(permit["proposal_id"], response)
    assert len(actions.pending()) == 1 and "transaction" not in actions.get(permit["proposal_id"])


def test_pending_waiver_is_not_owned_or_confirmed_then_settles_from_roster(setup):
    manager, actions = setup
    permit, response = waiver_claim(manager, actions)
    snapshot = fresh(manager)
    snapshot.source.http.pending_transactions = [response]
    snapshot.budget.pending_moves = 1
    result = actions.reconcile(permit["proposal_id"], snapshot.model_dump(mode="json"))
    assert result["status"] == "pending_waiver" and "109" not in manager.state()[0].own_team().roster_ids
    assert actions.pending() == [] and len(actions.pending(include_waivers=True)) == 1
    assert not actions.authorize(permit["proposal_id"], True)["should_submit"]
    settled = fresh(manager)
    settled.own_team().roster_ids.remove("103")
    settled.own_team().roster_ids.append("109")
    settled.source.http.pending_transactions = []
    settled.budget.pending_moves = 0
    result = actions.reconcile(permit["proposal_id"], settled.model_dump(mode="json"))
    assert result["status"] == "confirmed" and "109" in manager.state()[0].own_team().roster_ids
    assert actions.pending(include_waivers=True) == []


@pytest.mark.parametrize("change", ["week", "bid", "status", "transaction_id"])
def test_other_pending_transaction_cannot_establish_this_waiver(setup, change):
    manager, actions = setup
    permit, response = waiver_claim(manager, actions)
    other = deepcopy(response)
    if change == "week":
        other["scoringPeriodId"] = 2
    elif change == "bid":
        other["bidAmount"] = 8
    elif change == "status":
        other.update(status="UNKNOWN", isPending=False)
    else:
        other["id"] = "another-transaction"
    snapshot = fresh(manager)
    snapshot.source.http.pending_transactions = [other]
    result = actions.reconcile(permit["proposal_id"], snapshot.model_dump(mode="json"))
    assert result["status"] == "awaiting_verification"
    assert len(actions.pending()) == 1 and "109" not in manager.state()[0].own_team().roster_ids


@pytest.mark.parametrize("context", ["league", "team", "week"])
def test_cross_context_reconciliation_never_changes_the_database(setup, context):
    manager, actions = setup
    permit = claim(actions)
    snapshot = fresh(manager, lineup=SWAP)
    if context == "league":
        snapshot.league_id = snapshot.source.http.league_id = "456"
    elif context == "team":
        snapshot.team_id = snapshot.source.http.team_id = "2"
        snapshot.rules.slot = 2
    else:
        snapshot.week = snapshot.source.http.week = snapshot.source.http.transaction_period = 2
    snapshot.source.http.roster_url = league_url(snapshot.league_id, snapshot.season) + f"?view=mRoster&forTeamId={snapshot.team_id}&scoringPeriodId={snapshot.week}"
    before = manager.state()
    with pytest.raises(PolicyError, match="context"):
        actions.reconcile(permit["proposal_id"], snapshot.model_dump(mode="json"))
    assert manager.state() == before and len(actions.pending()) == 1


def test_http_request_bodies_preserve_slot_ids_and_distinguish_waiver_bids():
    snapshot = http_snapshot()
    body = transaction_body(snapshot, "set_lineup", {"lineup": SWAP}, "fictional-member")
    assert body["items"] == [{"playerId": 101, "type": "LINEUP", "fromLineupSlotId": 2, "toLineupSlotId": 20},
                              {"playerId": 103, "type": "LINEUP", "fromLineupSlotId": 20, "toLineupSlotId": 2}]
    assert body["scoringPeriodId"] == 1 and body["type"] == "ROSTER"
    assert transaction_body(snapshot, "waiver_claim", {**ADD, "bid": 3}, "fictional-member")["bidAmount"] == 3
    snapshot.source.http.uses_faab = False
    assert "bidAmount" not in transaction_body(snapshot, "waiver_claim", ADD, "fictional-member")


def test_unresolved_browser_claim_blocks_http_route(setup):
    from fantasy_football_manager.browser_lineup import BrowserLineup
    from fantasy_football_manager.models import LeagueSnapshot

    manager, actions = setup
    snapshot = fresh(manager).model_dump(mode="json")
    snapshot["source"].update(provider="espn_browser", http=None, browser={
        "league_id": "123", "team_id": "1",
        "page_url": "https://fantasy.espn.com/football/team?leagueId=123&teamId=1&scoringPeriodId=1"})
    manager.import_snapshot(LeagueSnapshot.model_validate(snapshot).model_dump(mode="json"), manager.state()[2])
    browser = BrowserLineup(manager)
    proposal = browser.prepare(SWAP)
    browser.authorize(proposal["proposal_id"], True)
    with pytest.raises(ValueError, match="pending.*action"):
        manager.import_snapshot(http_snapshot().model_dump(mode="json"), manager.state()[2])
    with pytest.raises(PolicyError, match="HTTP observation"):
        actions.prepare("free_agent_add", ADD)
    assert len(browser.pending()) == 1


def test_unresolved_http_claim_blocks_switch_to_browser_source(setup):
    manager, actions = setup
    permit = claim(actions)
    snapshot = fresh(manager).model_dump(mode="json")
    snapshot["source"].update(provider="espn_browser", http=None, browser={
        "league_id": "123", "team_id": "1",
        "page_url": "https://fantasy.espn.com/football/team?leagueId=123&teamId=1&scoringPeriodId=1"})
    before = manager.state()
    with pytest.raises(ValueError, match="pending.*action"):
        manager.import_snapshot(snapshot, manager.state()[2])
    assert manager.state() == before and actions.pending()[0]["proposal_id"] == permit["proposal_id"]


@pytest.mark.parametrize("response_status,expected", [("FAILED", "rejected"), ("DENIED", "rejected"),
                                                     ("CANCELED", "cancelled"), ("CANCELLED", "cancelled")])
def test_matching_terminal_response_needs_unchanged_fresh_roster_before_release(setup, response_status, expected):
    manager, actions = setup
    permit = claim(actions)
    response = response_for(fresh(manager), "set_lineup", {"lineup": SWAP}, status=response_status, isPending=False)
    actions.record_response(permit["proposal_id"], response)
    assert len(actions.pending()) == 1
    old = fresh(manager)
    old.source.observed_at = datetime.fromisoformat(permit["authorized_at"]) - timedelta(seconds=1)
    with pytest.raises(PolicyError, match="predates"):
        actions.reconcile(permit["proposal_id"], old.model_dump(mode="json"))
    result = actions.reconcile(permit["proposal_id"], fresh(manager).model_dump(mode="json"))
    assert result["status"] == expected and not result["retry_allowed"] and not result["should_submit"]
    assert manager.state()[0].own_team().lineup == BASE and actions.pending() == []
    assert actions.authorize(permit["proposal_id"], True) == result


@pytest.mark.parametrize("terminal,expected", [("CANCELED", "cancelled"), ("FAILED", "rejected")])
def test_terminal_history_replaces_pending_receipt_in_durable_result(setup, terminal, expected):
    manager, actions = setup
    permit, response = waiver_claim(manager, actions)
    observed = fresh(manager)
    observed.source.http.pending_transactions = [response]
    assert actions.reconcile(permit["proposal_id"], observed.model_dump(mode="json"))["status"] == "pending_waiver"
    observed = fresh(manager)
    observed.source.http.pending_transactions = []
    receipt = {**response, "status": terminal, "isPending": False}
    observed.source.http.recent_transactions = [receipt]
    result = actions.reconcile(permit["proposal_id"], observed.model_dump(mode="json"))
    assert result["status"] == expected and result["transaction"] == receipt
    assert not result["retry_allowed"] and not result["should_submit"]
    with manager.transaction() as db:
        row = db.execute("SELECT status,response,result FROM espn_http_proposals WHERE id=?", (permit["proposal_id"],)).fetchone()
        assert row["status"] == expected and json.loads(row["response"]) == receipt
        assert json.loads(row["result"]) == result
    restarted = ESPNHTTPActions(Manager(manager.data_dir))
    assert restarted.get(permit["proposal_id"]) == result
    assert restarted.authorize(permit["proposal_id"], True) == result


@pytest.mark.parametrize("bid", [40, None, False])
@pytest.mark.parametrize("history_status,acquired", [("EXECUTED", True), ("CANCELED", False), ("PENDING", False)])
def test_changed_or_unknown_history_bid_conflicts_with_exact_waiver_authorization(setup, bid, history_status, acquired):
    manager, actions = setup
    permit, response = waiver_claim(manager, actions)
    queued = fresh(manager)
    queued.source.http.pending_transactions = [response]
    assert actions.reconcile(permit["proposal_id"], queued.model_dump(mode="json"))["status"] == "pending_waiver"
    observed = fresh(manager)
    receipt = {**response, "status": history_status, "isPending": history_status == "PENDING", "bidAmount": bid}
    if bid is None:
        receipt.pop("bidAmount")
    observed.source.http.recent_transactions = [receipt]
    if acquired:
        observed.own_team().roster_ids.remove("103")
        observed.own_team().roster_ids.append("109")
        observed.source.http.pending_transactions = []
    elif history_status == "CANCELED":
        observed.source.http.pending_transactions = []
    # A stale matching pending row must not override conflicting history.
    revision = manager.state()[2]
    result = actions.reconcile(permit["proposal_id"], observed.model_dump(mode="json"))
    assert result["status"] == "conflict" and result["payload"]["bid"] == 0
    assert result["transaction"] == receipt and result["revision"] == revision + 1
    assert not result["should_submit"] and not result["retry_allowed"]
    assert actions.pending(include_waivers=True) == []
    with manager.transaction() as db:
        row = db.execute("SELECT response,result FROM espn_http_proposals WHERE id=?", (permit["proposal_id"],)).fetchone()
        assert json.loads(row["response"]) == receipt and json.loads(row["result"]) == result
    before, events = manager.state(), manager.history()
    restarted = ESPNHTTPActions(Manager(manager.data_dir))
    assert restarted.authorize(permit["proposal_id"], True) == result
    assert restarted.reconcile(permit["proposal_id"], observed.model_dump(mode="json")) == result
    assert manager.state() == before and manager.history() == events


def test_matching_executed_history_bid_preserves_waiver_confirmation(setup):
    manager, actions = setup
    permit, response = waiver_claim(manager, actions)
    observed = fresh(manager)
    observed.own_team().roster_ids.remove("103")
    observed.own_team().roster_ids.append("109")
    observed.source.http.recent_transactions = [{**response, "status": "EXECUTED", "isPending": False}]
    result = actions.reconcile(permit["proposal_id"], observed.model_dump(mode="json"))
    assert result["status"] == "confirmed"
    assert result["payload"]["bid"] == result["transaction"]["bidAmount"] == 0


@pytest.mark.parametrize("change", ["week", "league", "source", "rules"])
def test_queued_waiver_preserves_context_until_terminal_reconciliation(setup, change):
    manager, actions = setup
    permit, response = waiver_claim(manager, actions)
    observed = fresh(manager)
    observed.source.http.pending_transactions = [response]
    actions.reconcile(permit["proposal_id"], observed.model_dump(mode="json"))
    changed = fresh(manager)
    if change == "week":
        changed.week = changed.source.http.week = changed.source.http.transaction_period = 2
    elif change == "league":
        changed.league_id = changed.source.http.league_id = "456"
    elif change == "source":
        changed.source.provider = "espn_browser"
        from fantasy_football_manager.models import BrowserObservation
        changed.source.browser = BrowserObservation(league_id="123", team_id="1",
            page_url="https://fantasy.espn.com/football/team?leagueId=123&teamId=1&scoringPeriodId=1")
        changed.source.http = None
    else:
        changed.rules.caps["RB"] += 1
    if changed.source.http is not None:
        changed.source.http.roster_url = league_url(changed.league_id, changed.season) + f"?view=mRoster&forTeamId={changed.team_id}&scoringPeriodId={changed.week}"
    before = manager.state()
    with pytest.raises(ValueError, match="pending.*action"):
        manager.import_snapshot(changed.model_dump(mode="json"), before[2])
    assert manager.state() == before
    assert actions.pending() == []
    assert actions.pending(include_waivers=True)[0]["proposal_id"] == permit["proposal_id"]
    settled = fresh(manager)
    settled.source.http.pending_transactions = []
    settled.source.http.recent_transactions = [{**response, "status": "CANCELED", "isPending": False}]
    assert actions.reconcile(permit["proposal_id"], settled.model_dump(mode="json"))["status"] == "cancelled"
    changed.source.observed_at = datetime.now(timezone.utc)
    assert manager.import_snapshot(changed.model_dump(mode="json"), manager.state()[2])["status"] == "imported"


@pytest.mark.parametrize("lineup", [SWAP, {"RB1": "101", "FLEX1": "103"}])
def test_terminal_response_with_any_roster_change_is_a_conflict(setup, lineup):
    manager, actions = setup
    permit = claim(actions)
    actions.record_response(permit["proposal_id"], response_for(fresh(manager), "set_lineup", {"lineup": SWAP},
                                                              status="FAILED", isPending=False))
    observed = fresh(manager, lineup=lineup)
    result = actions.reconcile(permit["proposal_id"], observed.model_dump(mode="json"))
    assert result["status"] == "conflict" and not result["retry_allowed"]
    assert manager.state()[0].own_team().lineup == observed.own_team().lineup


def test_free_agent_confirmation_accepts_only_the_exact_acquisition_roster(setup):
    manager, actions = setup
    permit = claim(actions, "free_agent_add", ADD)
    observed = fresh(manager)
    observed.own_team().roster_ids.remove("103")
    observed.own_team().roster_ids.append("109")
    result = actions.reconcile(permit["proposal_id"], observed.model_dump(mode="json"))
    assert result["status"] == "confirmed" and set(result["actual_roster_ids"]) == {"101", "102", "109"}


@pytest.mark.parametrize("action,pid", [("move_to_ir", "103"), ("activate_from_ir", "104")])
def test_ir_claims_confirm_only_after_exact_roster_observation(setup, action, pid):
    manager, actions = setup
    snapshot = fresh(manager)
    if action == "move_to_ir":
        snapshot.rules.ir = 2
        snapshot.players[2].espn.injured = True
    else:
        snapshot.own_team().roster_ids.remove("103")
    manager.import_snapshot(snapshot.model_dump(mode="json"), manager.state()[2])
    permit = claim(actions, action, {"player_id": pid})
    unchanged = actions.reconcile(permit["proposal_id"], fresh(manager).model_dump(mode="json"))
    assert unchanged["status"] == "awaiting_verification"
    observed = fresh(manager)
    source, target = (observed.own_team().roster_ids, observed.own_team().reserve_ids) if action == "move_to_ir" else (observed.own_team().reserve_ids, observed.own_team().roster_ids)
    source.remove(pid)
    target.append(pid)
    assert actions.reconcile(permit["proposal_id"], observed.model_dump(mode="json"))["status"] == "confirmed"
