from datetime import datetime, timezone
import hashlib
import json
import sqlite3

import pytest

from fantasy_football_manager.backup_check import check_latest, verify_backup


@pytest.fixture
def backup(tmp_path):
    root = tmp_path / "ffm-backup-20260912T073000000000Z"
    root.mkdir()
    with sqlite3.connect(root / "manager-001.sqlite3") as db:
        db.execute("CREATE TABLE state(id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO state VALUES(1)")
    (root / "archive.dump").write_bytes(b"PGDMP fictional fixture")
    rows = [{"file": p.name, "kind": "postgres" if p.suffix == ".dump" else "sqlite",
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size} for p in root.iterdir()]
    (root / "backup.json").write_text(json.dumps({"schema_version": 1, "application": "fantasy-football-manager", "complete": True,
        "created_at": "2026-09-12T07:30:00+00:00", "files": rows}))
    return root


NOW = datetime(2026, 9, 12, 8, tzinfo=timezone.utc)


def test_backup_verification_is_not_full_restore(backup):
    calls = []
    r = verify_backup(backup, now=NOW, runner=lambda *a, **k: calls.append(a))
    assert r["status"] == "passed" and r["counts"]["sqlite"] == 1 and r["full_restore"] is False
    assert calls[0][0][:2] == ["pg_restore", "--list"]


@pytest.mark.parametrize("defect", ["hash", "path", "duplicate", "age", "missing_state"])
def test_invalid_backup_does_not_pass(backup, defect):
    marker = backup / "backup.json"
    m = json.loads(marker.read_text())
    if defect == "hash":
        m["files"][0]["sha256"] = "0" * 64
    elif defect == "path":
        m["files"][0]["file"] = "../private.json"
    elif defect == "duplicate":
        m["files"].append(m["files"][0])
    elif defect == "age":
        m["created_at"] = "2026-09-01T00:00:00+00:00"
    else:
        with sqlite3.connect(backup / "manager-001.sqlite3") as db:
            db.execute("DELETE FROM state")
        for row in m["files"]:
            row["sha256"] = hashlib.sha256((backup / row["file"]).read_bytes()).hexdigest()
    marker.write_text(json.dumps(m))
    with pytest.raises(ValueError):
        verify_backup(backup, now=NOW, runner=lambda *a, **k: None)
    r = check_latest(backup.parent, backup.parent / "result.json", now=NOW, runner=lambda *a, **k: None)
    assert r["status"] == "failed"
