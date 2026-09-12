"""Restore a verified backup into an explicitly selected empty rehearsal database."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile

import psycopg

from fantasy_football_manager.archive import compact_receipts
from fantasy_football_manager.backup_check import verify_backup
from fantasy_football_manager.readiness import atomic_json


def rehearse(backup, database, output):
    # No arbitrary DSN, production database name, or restore-in-place option exists.
    if not re.fullmatch(r"ffm_rehearsal_[a-z0-9_]{8,48}", database):
        raise ValueError("Use a dedicated ffm_rehearsal_ database name.")
    backup = Path(backup).resolve()
    verified = verify_backup(backup)
    with psycopg.connect(dbname=database) as connection:
        if connection.execute("SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')").fetchone()[0]:
            raise ValueError("The rehearsal database is not empty.")
        if connection.execute("SELECT current_database()").fetchone()[0] != database:
            raise ValueError("The rehearsal database differs from the requested target.")
    result = {"schema_version": 1, "kind": "isolated_restore", "status": "failed", "full_restore": False,
              "checked_at": datetime.now(timezone.utc).isoformat(), "marker_sha256": verified["marker_sha256"],
              "isolated_database_removed": False}
    try:
        subprocess.run(["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "--dbname", database,
                        str(backup / "archive.dump")], check=True, capture_output=True, timeout=600)
        counts = {}
        tables = ("archive_runs", "archive_records", "archive_labels", "archive_imports", "archive_source_checkpoints", "archive_source_objects")
        with psycopg.connect(dbname=database) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            for table in tables:
                counts[table] = connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
        with psycopg.connect(dbname=database) as connection:
            membership = compact_receipts(connection, apply=False)
        copied = 0
        with tempfile.TemporaryDirectory(prefix="ffm-restore-") as temporary:
            for source in sorted(backup.glob("manager-*.sqlite3")):
                with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader:
                    with closing(sqlite3.connect(Path(temporary) / source.name)) as writer:
                        reader.backup(writer)
                        if writer.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                            raise ValueError("The restored team database failed integrity verification.")
                        before = reader.execute("SELECT snapshot,config,revision,config_revision FROM state WHERE id=1").fetchone()
                        after = writer.execute("SELECT snapshot,config,revision,config_revision FROM state WHERE id=1").fetchone()
                        if before is None or before != after:
                            raise ValueError("The restored team state differs from the backup.")
                copied += 1
        if copied != verified["counts"]["sqlite"]:
            raise ValueError("The restored team count differs from the backup.")
        result.update(status="passed", full_restore=True, sqlite_verified=copied,
                      postgres_tables_verified=len(counts), postgres_counts=counts,
                      archive_membership_verified=membership.get("applied") is False)
    finally:
        # The name and empty-database check above restrict this cleanup to the selected rehearsal database.
        cleanup = subprocess.run(["dropdb", database], capture_output=True, timeout=60)
        result["isolated_database_removed"] = cleanup.returncode == 0
        if cleanup.returncode:
            result["status"] = "failed"
        atomic_json(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--database", required=True, help="Existing empty database with an ffm_rehearsal_ name. The current role must own it.")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    r = rehearse(args.backup, args.database, args.output)
    print(r["status"])
    raise SystemExit(0 if r["status"] == "passed" else 1)
