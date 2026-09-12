"""Verify completed private backup sets. This does not restore production databases."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
import subprocess

from .readiness import atomic_json, read_json, stamp


SET = re.compile(r"ffm-backup-\d{8}T\d{12}Z\Z")
FILE = re.compile(r"(?:archive\.dump|manager-\d{3}\.sqlite3|config-\d{3}\.json)\Z")


def verify_backup(directory, *, now=None, runner=subprocess.run):
    now = now or datetime.now(timezone.utc)
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir() or not SET.fullmatch(directory.name):
        raise ValueError("Select a completed backup set.")
    marker = directory / "backup.json"
    if marker.is_symlink():
        raise ValueError("Backup markers cannot be symbolic links.")
    value = read_json(marker)
    if (value.get("application") != "fantasy-football-manager" or value.get("complete") is not True
            or value.get("schema_version") != 1 or not 0 <= now.timestamp() - stamp(value["created_at"]) <= 36 * 3600):
        raise ValueError("A complete backup less than 36 hours old is required.")
    records = value["files"]
    if not isinstance(records, list) or not 2 <= len(records) <= 1999:
        raise ValueError("The backup inventory is invalid.")
    names, counts = set(), {"sqlite": 0, "postgres": 0, "config": 0}
    for row in records:
        name, kind = row["file"], row["kind"]
        if not isinstance(name, str) or not FILE.fullmatch(name) or name in names or kind not in counts:
            raise ValueError("The backup inventory is invalid.")
        expected = "postgres" if name == "archive.dump" else "sqlite" if name.startswith("manager-") else "config"
        if kind != expected:
            raise ValueError("The backup file type is invalid.")
        names.add(name)
        file = directory / name
        if file.is_symlink() or not file.is_file() or type(row["bytes"]) is not int or row["bytes"] <= 0 or file.stat().st_size != row["bytes"]:
            raise ValueError("A backup file is missing or has changed.")
        sha = hashlib.sha256()
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                sha.update(chunk)
        if sha.hexdigest() != row["sha256"]:
            raise ValueError("A backup checksum differs from its manifest.")
        if kind == "sqlite":
            with closing(sqlite3.connect(file.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                db.execute("PRAGMA query_only=ON")
                if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("A SQLite backup failed its integrity check.")
                if db.execute("SELECT count(*) FROM state WHERE id=1").fetchone()[0] != 1:
                    raise ValueError("A SQLite backup has no manager state.")
        elif kind == "postgres":
            runner(["pg_restore", "--list", str(file)], check=True, capture_output=True, timeout=120)
        else:
            read_json(file)
        counts[kind] += 1
    if counts["postgres"] != 1 or counts["sqlite"] < 1:
        raise ValueError("PostgreSQL and manager backups are required.")
    return {"schema_version": 1, "kind": "backup_integrity", "status": "passed", "checked_at": now.isoformat(),
            "backup_created_at": value["created_at"], "marker_sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
            "counts": counts, "full_restore": False}


def check_latest(root, output, *, now=None, runner=subprocess.run):
    now = now or datetime.now(timezone.utc)
    try:
        sets = sorted(p for p in Path(root).iterdir() if SET.fullmatch(p.name) and p.is_dir() and not p.is_symlink())
        if not sets:
            raise ValueError("No completed backup exists.")
        # Always verify bytes. A previous successful check cannot mask a changed file.
        result = verify_backup(sets[-1], now=now, runner=runner)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError):
        result = {"schema_version": 1, "kind": "backup_integrity", "status": "failed", "checked_at": now.isoformat(),
                  "reason": "The latest backup is missing, stale, invalid, or unreadable.", "full_restore": False}
    atomic_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    r = check_latest(args.backup_root, args.output)
    print(r["status"])
    return 0 if r["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
