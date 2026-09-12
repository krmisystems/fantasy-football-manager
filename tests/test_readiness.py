"""Acceptance evidence must fail closed on missing, stale, or conflicting records."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import sqlite3

import pytest

from fantasy_football_manager.readiness import DAY, atomic_json, collect, evaluate, public_report, receipt_verified, record_sample
from test_espn_http_actions import setup, claim, fresh, response_for
from test_espn_http_policy import SWAP


def sample(at, week=1, healthy=True, scope="fictional-scope"):
    return {"at": at, "scope": scope, "healthy": healthy,
            "teams": [{"team_key": "fictional-team", "valid": healthy, "week": week, "pending": [], "receipts": []}]}


def test_week_change_alone_does_not_prove_a_weekly_cycle():
    rows = [sample(0), sample(300, 2)]
    gates = evaluate(rows, rows[-1])["gates"]
    assert gates["live_rollover"]["status"] == "passed"
    assert gates["weekly_cycle"]["status"] == "pending"


@pytest.mark.parametrize("defect", [None, "gap", "unhealthy", "scope", "no_rollover"])
def test_cycle_requires_seven_days_continuity_and_rollover(defect):
    rows = [sample(t, 1 if t < DAY else 2) for t in range(0, 7 * DAY + 1, 300)]
    if defect == "gap":
        del rows[10:15]
    elif defect == "unhealthy":
        rows[10]["healthy"] = False
    elif defect == "scope":
        rows[10]["scope"] = "different"
    elif defect == "no_rollover":
        for row in rows:
            row["teams"][0]["week"] = 1
    assert (evaluate(rows, rows[-1])["gates"]["weekly_cycle"]["status"] == "passed") == (defect is None)


def test_pending_old_week_prevents_rollover_acceptance():
    rows = [sample(0), sample(300, 2)]
    rows[-1]["teams"][0]["pending"] = [{"id": "a", "status": "pending_waiver", "week": 1}]
    assert evaluate(rows, rows[-1])["gates"]["live_rollover"]["status"] == "pending"


def test_waiver_requires_observed_pending_before_confirmation():
    rows = [sample(0), sample(300)]
    proof = {"id": "receipt", "action": "waiver_claim"}
    rows[-1]["teams"][0]["receipts"] = [proof]
    assert evaluate(rows, rows[-1])["gates"]["live_waiver_claim"]["status"] == "pending"
    rows[0]["teams"][0]["pending"] = [{"id": "receipt", "status": "pending_waiver", "week": 1}]
    assert evaluate(rows, rows[-1])["gates"]["live_waiver_claim"]["status"] == "passed"


@pytest.mark.parametrize("defect", [None, "response", "roster", "context", "future", "synthetic"])
def test_exact_receipt_verification(setup, defect):
    manager, actions = setup
    permit = claim(actions)
    baseline = manager.state()[0]
    actions.record_response(permit["proposal_id"], response_for(baseline, "set_lineup", {"lineup": SWAP}))
    actions.reconcile(permit["proposal_id"], fresh(manager, lineup=SWAP).model_dump(mode="json"))
    with manager.transaction() as db:
        row = dict(db.execute("SELECT * FROM espn_http_proposals").fetchone())
    if defect == "response":
        r = json.loads(row["response"]); r["status"] = "PENDING"; row["response"] = json.dumps(r)
    elif defect == "roster":
        r = json.loads(row["result"]); r["actual_roster_ids"].append("unexpected"); row["result"] = json.dumps(r)
    elif defect == "context":
        row["week"] += 1
    elif defect == "future":
        r = json.loads(row["result"]); r["observed_at"] = "2099-01-01T00:00:00+00:00"; row["result"] = json.dumps(r)
    elif defect == "synthetic":
        r = json.loads(row["baseline"]); r["source"]["synthetic"] = True; row["baseline"] = json.dumps(r)
    assert receipt_verified(row, datetime.now(timezone.utc).timestamp()) == (defect is None)


def test_collector_does_not_modify_team_store_and_missing_health_stays_pending(setup, tmp_path):
    manager, _ = setup
    snap = manager.state()[0]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"browser_data_dir": "unused", "leagues": [{"league_id": snap.league_id,
        "team_id": snap.team_id, "season": snap.season, "week": snap.week, "phase": "season", "data_dir": str(manager.data_dir)}]}))
    before = manager.state()
    r = collect(manifest, tmp_path / "evidence")
    assert not r["healthy"] and not r["release_ready"] and r["live_action_calls"] == 0
    assert manager.state() == before
    assert (tmp_path / "evidence/report.json").is_file()
    assert public_report(tmp_path / "evidence/report.json")["status"] == "pending"
    with pytest.raises(ValueError, match="separate"):
        collect(manifest, manager.data_dir)


def test_retention_and_idempotent_collection():
    with sqlite3.connect(":memory:") as db:
        record_sample(db, sample(0))
        record_sample(db, sample(36 * DAY))
        record_sample(db, sample(36 * DAY))
        assert db.execute("SELECT count(*) FROM samples").fetchone()[0] == 1


def test_repeated_receipts_are_stored_once_instead_of_in_every_sample():
    with sqlite3.connect(":memory:") as db:
        for at in range(0, 3600, 300):
            s = sample(at)
            s["teams"][0]["receipts"] = [{"id": "same-receipt", "action": "set_lineup", "proof_hash": "a" * 64}]
            record_sample(db, s)
        assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1
        assert all(not json.loads(r[0])["teams"][0]["receipts"] for r in db.execute("SELECT value FROM samples"))


def test_missing_or_untrusted_public_report_is_not_passed(tmp_path):
    p = tmp_path / "report.json"
    assert public_report(p)["status"] == "unavailable"
    atomic_json(p, {"secret": "private-path", "release_ready": True})
    assert public_report(p) == {"status": "unavailable", "release_ready": False, "gates": {}}


def test_coordinator_transition_retries_are_bounded(monkeypatch):
    from types import SimpleNamespace
    from fantasy_football_manager import readiness
    calls = []
    monkeypatch.setattr(readiness, "read_json", lambda _: {"status": "visiting", "leagues": []})
    result = readiness.observe_coordinator(SimpleNamespace(status_file="fixture", leagues=[]), sleeper=calls.append)
    assert calls == [3] * 7 and result[-1] == 7
    assert not result[1]["healthy"]


@pytest.mark.parametrize("age,count,expected", [(60, 5, True), (1000, 5, False), (-60, 5, False), (60, 4, False)])
def test_archive_checks_freshness_and_complete_checkpoint_coverage(monkeypatch, age, count, expected):
    from types import SimpleNamespace
    import sys
    from fantasy_football_manager.readiness import archive_check
    calls = []
    now = datetime.now(timezone.utc).timestamp()
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql):
            calls.append(sql)
            value = datetime.fromtimestamp(now - age, timezone.utc).isoformat() if "max(imported_at)" in sql else count
            return SimpleNamespace(fetchone=lambda: (value,))
    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=lambda *a, **k: Connection()))
    assert archive_check("dbname=fictional", 5, now)["verified"] is expected
    assert calls[0] == "SET TRANSACTION READ ONLY"


def test_supplemental_candidate_mismatch_cannot_pass(tmp_path):
    from fantasy_football_manager.readiness import supplementary_gates
    now = datetime.now(timezone.utc)
    report = {"gates": {}, "teams": [{"team_key": "fictional"}], "team_count": 1}
    atomic_json(tmp_path / "candidate-report.json", {"schema_version": 1, "checked_at": now.isoformat(),
        "commit": "a" * 40, "checks": {k: True for k in ("ci", "clean_install", "upgrade", "draft_regression", "dashboard_regression", "docs_current")}})
    atomic_json(tmp_path / "installation-report.json", {"schema_version": 1, "checked_at": now.isoformat(),
        "commit": "b" * 40, "checks": {k: True for k in ("services_match", "plugins_match", "mcp_definitions_match")}})
    supplementary_gates(tmp_path, report, now.timestamp())
    assert report["gates"]["candidate_checks"]["status"] == "passed"
    assert report["gates"]["installation_provenance"]["status"] == "pending"
    assert report["gates"]["backup_restore"]["status"] == "pending"
