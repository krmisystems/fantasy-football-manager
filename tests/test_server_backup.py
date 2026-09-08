"""Backup tests use temporary databases and a fake PostgreSQL dump command."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest


spec = importlib.util.spec_from_file_location("ffm_backup", Path(__file__).parents[1] / "deployment" / "backup.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def sources(tmp_path):
    database = tmp_path / "manager.sqlite3"
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TABLE state(id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO state VALUES(1, 'initial')")
        db.commit()
    manifest = tmp_path / "archive.json"
    manifest.write_text(json.dumps({"schema_version": 1, "sources": [{"database": "manager.sqlite3"}]}), encoding="utf-8")
    return database, manifest


def dump_command(command, **kwargs):
    assert command[:3] == ["pg_dump", "--dbname", "dbname=fantasy_football"]
    assert "--format=custom" in command
    assert kwargs["check"] and kwargs["timeout"] == 600
    Path(command[-1]).write_bytes(b"PGDMPfictional dump")


def test_backup_captures_committed_wal_rows_and_explicit_configs(tmp_path):
    database, manifest = sources(tmp_path)
    config = tmp_path / "leagues.json"
    config.write_text('{"private_configuration": true}', encoding="utf-8")
    root = tmp_path / "backups"
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("UPDATE state SET value='committed WAL update' WHERE id=1")
        writer.commit()
        assert Path(str(database) + "-wal").stat().st_size > 0
        result = backup.run_backup(manifest, root, configs=[config], runner=dump_command)
        copied = root / result["backup_set"] / "manager-001.sqlite3"
        with closing(sqlite3.connect(copied)) as reader:
            assert reader.execute("SELECT value FROM state").fetchone()[0] == "committed WAL update"
            assert reader.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert result["sqlite_databases"] == 1 and result["configuration_files"] == 2
    directory = root / result["backup_set"]
    assert (directory / "config-002.json").read_bytes() == config.read_bytes()
    marker = json.loads((directory / "backup.json").read_text())
    assert marker["complete"] is True
    assert [item["kind"] for item in marker["files"]] == ["postgres", "sqlite", "config", "config"]
    for item in marker["files"]:
        payload = (directory / item["file"]).read_bytes()
        assert item["bytes"] == len(payload)
        assert item["sha256"] == hashlib.sha256(payload).hexdigest()
    assert not list(root.glob(".ffm-backup-staging-*"))


def test_failed_pg_dump_never_publishes_or_prunes(tmp_path):
    _, manifest = sources(tmp_path)
    root = tmp_path / "backups"
    old = backup.run_backup(manifest, root, runner=dump_command,
                            now=datetime.now(timezone.utc) - timedelta(days=20))
    def failure(command, **kwargs):
        Path(command[-1]).write_bytes(b"partial")
        raise subprocess.CalledProcessError(1, command)
    with pytest.raises(subprocess.CalledProcessError):
        backup.run_backup(manifest, root, runner=failure)
    assert [item.name for item in root.iterdir()] == [old["backup_set"]]


def test_retention_preserves_unrelated_or_unrecognized_files(tmp_path):
    _, manifest = sources(tmp_path)
    root = tmp_path / "backups"
    now = datetime.now(timezone.utc)
    old = backup.run_backup(manifest, root, runner=dump_command, now=now - timedelta(days=20))
    suspicious = root / "ffm-backup-20000101T000000000000Z"
    suspicious.mkdir()
    (suspicious / "backup.json").write_text(json.dumps({"application": "fantasy-football-manager", "complete": True,
                                                       "created_at": "2000-01-01T00:00:00+00:00"}), encoding="utf-8")
    (suspicious / "unrelated.txt").write_text("Keep this file.", encoding="utf-8")
    unrelated = root / "unrelated.txt"
    unrelated.write_text("Keep this file.", encoding="utf-8")
    new = backup.run_backup(manifest, root, runner=dump_command, now=now)
    assert new["removed_sets"] == 1
    assert not (root / old["backup_set"]).exists()
    assert unrelated.exists() and (suspicious / "unrelated.txt").exists()


def test_browser_profile_files_are_rejected(tmp_path):
    _, manifest = sources(tmp_path)
    profile = tmp_path / "espn-browser-profile"
    profile.mkdir()
    cookie_file = profile / "Cookies"
    cookie_file.write_bytes(b"fictional private browser file")
    with pytest.raises(ValueError, match="profiles"):
        backup.run_backup(manifest, tmp_path / "backups", configs=[cookie_file], runner=dump_command)


def test_sqlite_failure_never_publishes_partial_set(tmp_path):
    database, manifest = sources(tmp_path)
    database.write_bytes(b"not a database")
    root = tmp_path / "backups"
    with pytest.raises(sqlite3.DatabaseError):
        backup.run_backup(manifest, root, runner=dump_command)
    assert not list(root.iterdir())
