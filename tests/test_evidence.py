"""Verify durable evidence without a browser, remote database, or live league."""

import json
import threading
from datetime import datetime, timezone

import pytest

from fantasy_football_manager import evidence, runtime
from fantasy_football_manager.demo import make_demo
from fantasy_football_manager.draft import recommend_draft
from fantasy_football_manager.espn_service import ESPNService
from fantasy_football_manager.store import Manager
from test_espn_service import BrowserStub


def outbox(manager, event=None):
    with manager.transaction() as db:
        rows = db.execute("SELECT * FROM ffm_archive_outbox ORDER BY id").fetchall()
    return [{**dict(row), "detail": json.loads(row["detail"])} for row in rows if event is None or row["event"] == event]


def imported(tmp_path):
    manager = Manager(tmp_path)
    manager.import_snapshot(make_demo("draft").model_dump(mode="json"))
    return manager


def test_snapshot_and_outbox_commit_or_rollback_together(tmp_path, monkeypatch):
    manager = Manager(tmp_path)
    monkeypatch.setattr(evidence, "append", lambda *args: (_ for _ in ()).throw(RuntimeError("fixture write failure")))
    with pytest.raises(RuntimeError, match="fixture write failure"):
        manager.import_snapshot(make_demo("draft").model_dump(mode="json"))
    assert manager.state()[0] is None
    assert manager.state()[2] == 0
    assert manager.history() == [] and outbox(manager) == []


def test_semantic_history_survives_reopen_without_timestamp_only_duplicates(tmp_path):
    manager = imported(tmp_path)
    original = outbox(manager, "snapshot_changed")[0]
    snapshot, _, revision, _ = manager.require_state()
    snapshot.source.observed_at = datetime.now(timezone.utc)
    manager.import_snapshot(snapshot.model_dump(mode="json"), revision)
    assert manager.state()[2] == revision + 1  # Existing import revision behavior remains intact.
    assert len(outbox(manager, "snapshot_changed")) == 1
    snapshot.players[0].projection += 1
    manager.import_snapshot(snapshot.model_dump(mode="json"), revision + 1)
    saved = outbox(Manager(tmp_path), "snapshot_changed")
    assert len(saved) == 2 and saved[0] == original
    assert saved[0]["detail"]["input_fingerprint"] != saved[1]["detail"]["input_fingerprint"]
    assert saved[0]["detail"]["snapshot"]["players"][0]["projection"] + 1 == saved[1]["detail"]["snapshot"]["players"][0]["projection"]


def test_config_provenance_and_actual_work_retain_original_revision(tmp_path):
    manager = imported(tmp_path)
    snapshot, config, revision, config_revision = manager.require_state()
    batch = recommend_draft(snapshot, config, trials=2, seed=17)
    changed = config.model_copy(deep=True)
    changed.strategy.draft = "wr_priority"
    manager.update_config(changed.model_dump(mode="json"), config_revision)
    manager.record_calculation("draft", snapshot, config, revision, config_revision, batch,
                               seed=17, requested_trials=40, accepted=False, reason="state_changed")
    manager.record_calculation("draft", snapshot, config, revision, config_revision,
                               {"status": "roster_complete", "trials": 0}, seed=18, requested_trials=40)
    records = outbox(Manager(tmp_path), "calculation_completed")
    assert sum(row["detail"]["calculation"]["completed_trials"] for row in records) == 2
    first = records[0]["detail"]
    assert first["context"]["config_revision"] == config_revision
    assert first["config"]["strategy"]["draft"] == config.strategy.draft
    assert first["calculation"]["seed"] == 17
    assert first["calculation"]["requested_trials"] == 40
    assert first["calculation"]["accepted"] is False
    assert first["calculation"]["selection_causality"] == "not_inferred"
    assert first["input_fingerprint"] == evidence.fingerprint(snapshot, config)
    assert outbox(manager, "config_updated")[-1]["detail"]["config"]["strategy"]["draft"] == "wr_priority"


def test_completed_calculation_does_not_move_into_a_new_league_context(tmp_path):
    manager = imported(tmp_path)
    snapshot, config, revision, config_revision = manager.require_state()
    manager.import_snapshot(make_demo("season").model_dump(mode="json"), revision)
    manager.record_calculation("draft", snapshot, config, revision, config_revision,
                               {"status": "ready", "trials": 2}, seed=4, requested_trials=2)
    record = outbox(manager, "calculation_completed")[0]["detail"]
    assert record["context"]["league_id"] == snapshot.league_id
    assert record["context"]["phase"] == "draft"
    assert record["calculation"]["accepted"] is False
    assert record["calculation"]["disposition"] == "state_changed"


def test_outbox_omits_names_navigation_notes_and_raw_errors(tmp_path):
    browser = BrowserStub()
    browser.current.source.notes = ["PRIVATE-NOTE-MARKER"]
    browser.current.source.browser.page_url += "&memberId=PRIVATE-MEMBER-MARKER"
    browser.current.players[0].name = "PRIVATE-PLAYER-MARKER"
    browser.current.teams[0].name = "PRIVATE-TEAM-MARKER"
    manager = Manager(tmp_path)
    manager.import_snapshot(browser.current.model_dump(mode="json"))
    manager.record_submission({"proposal_id": "fictional-proposal", "player_name": "PRIVATE-PROPOSAL-NAME"},
        {"status": "uncertain", "clicked": True, "uncertain": True, "dom": "PRIVATE-DOM-MARKER",
         "error": "timeout PRIVATE-ERROR-MARKER", "snapshot": {"raw": "PRIVATE-SNAPSHOT-MARKER"}})
    serialized = json.dumps(outbox(manager))
    assert "PRIVATE-" not in serialized
    returned = outbox(manager, "browser_submission_returned")[0]["detail"]["submission"]
    assert returned["result"]["clicked"] is True and returned["result"]["uncertain"] is True
    assert returned["error_category"] == "timeout"
    assert returned["confirmation_scope"] == "requires_platform_reconciliation"


@pytest.fixture
def service(tmp_path):
    browser = BrowserStub()
    service = ESPNService(tmp_path, browser=browser)
    service.manager.import_snapshot(browser.current.model_dump(mode="json"))
    _, config, _, revision = service.manager.state()
    config.automation.preset = "bounded_automation"
    service.manager.update_config(config.model_dump(mode="json"), revision)
    return service


@pytest.mark.asyncio
async def test_browser_return_and_confirmation_are_distinct_durable_events(service):
    proposal = await service.prepare_pick("p1")
    confirmed = await service.submit_pick(proposal["proposal_id"])
    assert confirmed["status"] == "confirmed"
    events = outbox(service.manager)
    authorized = next(row for row in events if row["event"] == "browser_draft_authorized")
    returned = next(row for row in events if row["event"] == "browser_submission_returned")
    reconciled = next(row for row in events if row["event"] == "browser_draft_reconciled")
    assert authorized["id"] < returned["id"] < reconciled["id"]
    assert returned["detail"]["submission"]["result"]["status"] == "clicked"
    assert reconciled["detail"]["action"]["status"] == "confirmed"
    assert reconciled["detail"]["action"]["actual_pick"]["player_id"] == "p1"
    before = outbox(Manager(service.manager.data_dir))
    assert (await service.submit_pick(proposal["proposal_id"]))["status"] == "confirmed"
    assert outbox(service.manager) == before and len(service.browser.clicks) == 1


@pytest.mark.asyncio
async def test_authorization_outbox_failure_rolls_back_claim_before_click(service, monkeypatch):
    proposal = await service.prepare_pick("p1")
    original = evidence.append

    def fail_authorization(db, event, detail):
        if event == "browser_draft_authorized":
            raise RuntimeError("fixture outbox unavailable")
        return original(db, event, detail)

    monkeypatch.setattr(evidence, "append", fail_authorization)
    with pytest.raises(RuntimeError, match="fixture outbox unavailable"):
        await service.submit_pick(proposal["proposal_id"])
    assert service.draft.get(proposal["proposal_id"])["status"] == "pending"
    assert not service.browser.clicks and not outbox(service.manager, "browser_draft_authorized")
    monkeypatch.setattr(evidence, "append", original)
    assert (await service.submit_pick(proposal["proposal_id"]))["status"] == "confirmed"
    assert len(service.browser.clicks) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_uncertain_browser_outcome_cannot_become_a_confirmation(service, raises):
    if raises:
        service.browser.submit_error = TimeoutError("PRIVATE-ERROR-MARKER timeout")
    else:
        service.browser.submit_response = {"status": "uncertain", "clicked": True, "error": "PRIVATE-ERROR-MARKER timeout"}
    proposal = await service.prepare_pick("p1")
    result = await service.submit_pick(proposal["proposal_id"])
    assert result["status"] == "awaiting_verification"
    assert not outbox(service.manager, "browser_draft_reconciled")
    event = "browser_submission_raised" if raises else "browser_submission_returned"
    record = outbox(Manager(service.manager.data_dir), event)[0]["detail"]
    assert record["submission"]["returned"] is (not raises)
    assert record["submission"]["error_category"] == "timeout"
    assert "PRIVATE-ERROR-MARKER" not in json.dumps(outbox(service.manager))
    await service.submit_pick(proposal["proposal_id"])
    assert len(service.browser.clicks) == 1


def test_failure_transitions_deduplicate_repeated_poll_errors_and_retain_recovery(service):
    service._save_status("needs_attention", error="HTTP 429 PRIVATE-ERROR-MARKER")
    service._save_status("needs_attention", error="HTTP 429 another raw message")
    service._save_status("monitoring")
    service._save_status("needs_attention", error="HTTP 401 PRIVATE-ERROR-MARKER")
    records = outbox(Manager(service.manager.data_dir), "worker_transition")
    assert [row["detail"]["worker"]["error_category"] for row in records] == ["rate_limited", None, "authentication"]
    assert "PRIVATE-ERROR-MARKER" not in json.dumps(records)


def test_monitor_records_executed_work_discarded_during_shutdown(tmp_path, monkeypatch):
    manager = imported(tmp_path)
    monitor = runtime.DraftMonitor(manager)
    entered, release = threading.Event(), threading.Event()

    def calculate(snapshot, config, trials, seed):
        entered.set()
        assert release.wait(3)
        return {"status": "ready", "trials": 3, "recommendations": []}

    monkeypatch.setattr(runtime, "recommend_draft", calculate)
    monitor.start(trials=4)
    assert entered.wait(2)
    monitor.stop_event.set()
    release.set()
    monitor.thread.join(3)
    assert not monitor.thread.is_alive()
    record = outbox(Manager(tmp_path), "calculation_completed")[0]["detail"]["calculation"]
    assert record["completed_trials"] == 3 and record["requested_trials"] == 4
    assert record["disposition"] == "stopped" and record["accepted"] is False
    assert monitor.completed_trials == monitor.discarded_trials == 3


def test_http_snapshot_retains_decision_flags_without_request_or_account_data(tmp_path):
    from test_espn_http_policy import http_snapshot

    snapshot = http_snapshot()
    snapshot.source.notes = ["PRIVATE-NOTE-MARKER"]
    snapshot.source.http.roster_url += "&memberId=PRIVATE-MEMBER-MARKER"
    snapshot.source.http.pending_transactions = [{
        "id": "fictional-pending", "type": "WAIVER", "teamId": 1, "scoringPeriodId": 1,
        "status": "PENDING", "isPending": True, "bidAmount": 2,
        "memberId": "PRIVATE-MEMBER-MARKER", "headers": {"Cookie": "PRIVATE-COOKIE-MARKER"},
        "items": [{"playerId": 109, "type": "ADD", "toTeamId": 1, "name": "PRIVATE-NAME-MARKER"}],
    }]
    snapshot.source.http.recent_transactions = [{"id": "fictional-recent", "type": "ROSTER", "status": "FAILED",
                                                  "error": "PRIVATE-ERROR-MARKER"}]
    snapshot.players[0].name = "PRIVATE-PLAYER-MARKER"
    snapshot.players[0].espn.pending_transaction_ids = ["fictional-pending"]
    manager = Manager(tmp_path)
    manager.import_snapshot(snapshot.model_dump(mode="json"))
    record = outbox(manager, "snapshot_changed")[0]["detail"]["snapshot"]
    assert "PRIVATE-" not in json.dumps(outbox(manager))
    assert "roster_url" not in record["source"]["http"]
    source = record["source"]["http"]
    assert source["ownership_verified"] and source["pending_transactions_known"]
    assert source["team_transaction_locked"] is False and source["acquisition_limit"] == -1
    assert source["pending_transactions"][0]["items"] == [{"playerId": 109, "type": "ADD", "toTeamId": 1}]
    assert source["recent_transactions"] == [{"id": "fictional-recent", "type": "ROSTER", "status": "FAILED"}]
    player = next(row for row in record["players"] if row["id"] == "101")
    assert player["espn"]["roster_locked"] is False and player["espn"]["droppable"] is True
    assert player["espn"]["pending_transaction_ids"] == ["fictional-pending"]


def test_comparison_and_coverage_evidence_preserves_unknowns_and_known_reason_codes(tmp_path):
    from fantasy_football_manager.season import recommend_lineup
    from test_espn_http_policy import automatic_config, http_snapshot

    snapshot, config = http_snapshot(), automatic_config()
    snapshot.players[0].weekly_projection = None
    snapshot.players[0].availability = "DOUBTFUL"
    result = recommend_lineup(snapshot, config)
    result["coverage"]["gaps"][0]["reasons"].append("PRIVATE-FREEFORM-REASON")
    result["coverage"]["candidates"][0]["player_name"] = "PRIVATE-PLAYER-MARKER"
    result["coverage"]["candidates"][0]["error"] = "PRIVATE-ERROR-MARKER"
    manager = Manager(tmp_path)
    manager.import_snapshot(snapshot.model_dump(mode="json"))
    manager.update_config(config.model_dump(mode="json"), 0)
    _, _, revision, config_revision = manager.require_state()
    manager.record_calculation("lineup", snapshot, config, revision, config_revision, result)
    saved = outbox(manager, "calculation_completed")[0]["detail"]["calculation"]["result"]
    assert "PRIVATE-" not in json.dumps(outbox(manager))
    assert saved["comparison_complete"] is False and saved["projection_complete"] is False
    assert saved["blocking_missing_projections"] == [{"player_id": "101", "fields": ["weekly_projection"]}]
    gap = saved["coverage"]["gaps"][0]
    assert gap["weekly_projection"] is None and "starter_projection_unknown" in gap["reasons"]
    candidate = saved["coverage"]["candidates"][0]
    assert candidate["repair_player_id"] == "101" and candidate["improvement"] is None
    assert candidate["authorized"] is False and "coverage_repair_not_enabled" in candidate["blocking_reasons"]
    assert candidate["lineup"] and candidate["weekly_projection"] == 30


def test_http_authorization_response_and_observation_have_distinct_sanitized_events(tmp_path):
    from fantasy_football_manager.espn_http_actions import ESPNHTTPActions, transaction_items
    from test_espn_http_policy import SWAP, automatic_config, http_snapshot

    manager = Manager(tmp_path)
    snapshot, config = http_snapshot(), automatic_config()
    manager.import_snapshot(snapshot.model_dump(mode="json"))
    manager.update_config(config.model_dump(mode="json"), 0)
    actions = ESPNHTTPActions(manager)
    proposal = actions.prepare("set_lineup", {"lineup": SWAP})
    permit = actions.authorize(proposal["proposal_id"])
    actions.record_response(permit["proposal_id"], {"id": "fictional-response", "type": "ROSTER", "teamId": 1,
        "scoringPeriodId": 1, "status": "EXECUTED", "isPending": False,
        "items": transaction_items(snapshot, "set_lineup", {"lineup": SWAP}), "memberId": "PRIVATE-MEMBER-MARKER"})
    assert outbox(manager, "espn_http_response") and not outbox(manager, "espn_http_reconciled")
    snapshot.source.observed_at = datetime.now(timezone.utc)
    snapshot.own_team().lineup = SWAP
    result = actions.reconcile(permit["proposal_id"], snapshot.model_dump(mode="json"))
    records = [row for row in outbox(manager) if row["event"].startswith("espn_http_")]
    assert [row["event"] for row in records] == ["espn_http_prepared", "espn_http_authorized", "espn_http_response", "espn_http_reconciled"]
    assert records[1]["detail"]["action"]["should_submit"] is True
    assert records[2]["detail"]["action"]["transaction"]["status"] == "EXECUTED"
    assert records[-1]["detail"]["action"]["status"] == "confirmed"
    assert set(records[-1]["detail"]["action"]["actual_roster_ids"]) == {"101", "102", "103"}
    snapshots = outbox(manager, "snapshot_changed")
    assert len(snapshots) == 2
    settled = snapshots[-1]["detail"]
    assert settled["context"]["revision"] == result["revision"]
    assert settled["snapshot"]["teams"][0]["lineup"] == SWAP
    assert settled["snapshot"]["budget"]["balance"] == 100
    assert all(player["espn"]["bye_verified"] is True for player in settled["snapshot"]["players"])
    assert "PRIVATE-" not in json.dumps(records)
    before = outbox(manager)
    assert actions.authorize(permit["proposal_id"]) == result
    assert outbox(manager) == before


def test_http_outbox_failure_rolls_back_authorization_before_request(tmp_path, monkeypatch):
    from fantasy_football_manager.espn_http_actions import ESPNHTTPActions
    from test_espn_http_policy import SWAP, automatic_config, http_snapshot

    manager = Manager(tmp_path)
    manager.import_snapshot(http_snapshot().model_dump(mode="json"))
    manager.update_config(automatic_config().model_dump(mode="json"), 0)
    actions = ESPNHTTPActions(manager)
    proposal = actions.prepare("set_lineup", {"lineup": SWAP})
    original = evidence.append

    def fail(db, event, detail):
        if event == "espn_http_authorized":
            raise RuntimeError("Fictional evidence write failure.")
        return original(db, event, detail)

    monkeypatch.setattr(evidence, "append", fail)
    with pytest.raises(RuntimeError, match="evidence write failure"):
        actions.authorize(proposal["proposal_id"])
    assert actions.get(proposal["proposal_id"])["status"] == "pending" and actions.pending() == []
    assert not outbox(manager, "espn_http_authorized")


def test_http_preflight_failure_records_only_classified_error_and_known_phase(tmp_path):
    from fantasy_football_manager.espn_http_actions import ESPNHTTPActions
    from test_espn_http_policy import SWAP, automatic_config, http_snapshot

    manager = Manager(tmp_path)
    manager.import_snapshot(http_snapshot().model_dump(mode="json"))
    manager.update_config(automatic_config().model_dump(mode="json"), 0)
    actions = ESPNHTTPActions(manager)
    proposal = actions.prepare("set_lineup", {"lineup": SWAP})
    permit = actions.authorize(proposal["proposal_id"])
    actions.record_not_submitted(permit["proposal_id"], "HTTP 401 PRIVATE-CREDENTIAL-MARKER")
    saved = outbox(manager, "espn_http_not_submitted")[0]["detail"]["action"]
    assert saved["status"] == "not_submitted" and saved["should_submit"] is False
    assert saved["error_category"] == "authentication" and "PRIVATE-" not in json.dumps(outbox(manager))
    assert not actions.pending() and not actions.authorize(permit["proposal_id"])["should_submit"]
    assert evidence.action_or_result({"submission_phase": "preflight", "error_category": "timeout", "payload": {"bid": 3}}) == {
        "submission_phase": "preflight", "error_category": "timeout", "payload": {"bid": 3}}
    assert evidence.action_or_result({"submission_phase": "PRIVATE-PHASE", "error_category": "PRIVATE-ERROR"}) == {}
