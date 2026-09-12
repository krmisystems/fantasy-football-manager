"""Restore a verified backup into an explicitly selected empty rehearsal database."""

import argparse
import os
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile

import psycopg

from .archive import compact_receipts
from .backup_check import SET, verify_backup
from .readiness import atomic_json, read_json


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


def isolated_cluster(root, output, *, runner=subprocess.run):
    """Use a temporary PostgreSQL cluster. Never connect to the production cluster."""
    result = {"schema_version": 1, "kind": "isolated_restore", "status": "failed", "full_restore": False,
              "checked_at": datetime.now(timezone.utc).isoformat(), "isolated_database_removed": False,
              "isolated_cluster_removed": False}
    try:
        sets = sorted(p for p in Path(root).iterdir() if SET.fullmatch(p.name) and p.is_dir() and not p.is_symlink())
        if not sets:
            raise ValueError("No completed backup exists.")
        verify_backup(sets[-1])
        bindir = Path(runner(["pg_config", "--bindir"], check=True, capture_output=True, text=True, timeout=10).stdout.strip())
        if not bindir.is_absolute() or not all((bindir / name).is_file() for name in ("initdb", "pg_ctl", "createdb")):
            raise ValueError("PostgreSQL server utilities are unavailable.")
        # Remove inherited connection settings, including service files and credentials.
        env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
        with tempfile.TemporaryDirectory(prefix="ffm-pg-") as temporary:
            base = Path(temporary)
            data, socket = base / "data", base / "socket"
            socket.mkdir(mode=0o700)
            database = "ffm_rehearsal_" + uuid.uuid4().hex
            env.update(PGHOST=str(socket), PGPORT="5432", PGDATABASE=database)
            runner([str(bindir / "initdb"), "-D", str(data), "--auth-local=trust", "--auth-host=reject", "--no-locale", "--encoding=UTF8"],
                   env=env, check=True, capture_output=True, timeout=120)
            # No TCP listener exists. The private socket directory is accessible only to this account.
            with (data / "postgresql.conf").open("a") as config:
                config.write("\nlisten_addresses = ''\nunix_socket_directories = '" + str(socket) + "'\n")
            try:
                runner([str(bindir / "pg_ctl"), "-D", str(data), "-l", str(base / "postgres.log"), "-w", "start"],
                       env=env, check=True, capture_output=True, timeout=90)
                runner([str(bindir / "createdb"), "--template=template0", database], env=env, check=True, capture_output=True, timeout=30)
                runner([sys.executable, "-m", "fantasy_football_manager.backup_restore", "--backup", str(sets[-1].resolve()),
                        "--database", database, "--output", str(base / "restore.json")],
                       env=env, check=True, capture_output=True, timeout=900)
                result = read_json(base / "restore.json")
            finally:
                runner([str(bindir / "pg_ctl"), "-D", str(data), "-m", "immediate", "-w", "stop"],
                       env=env, check=True, capture_output=True, timeout=90)
        result["isolated_cluster_removed"] = True
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        result.update(status="failed", full_restore=False, reason="The isolated restore or cluster cleanup failed.")
    atomic_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--backup", help="Completed backup for an existing empty rehearsal database.")
    group.add_argument("--backup-root", help="Verify the latest backup in a new temporary PostgreSQL cluster.")
    parser.add_argument("--database", help="Existing empty ffm_rehearsal_ database, used only with --backup.")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.backup_root:
        if args.database:
            parser.error("--database cannot be combined with --backup-root")
        result = isolated_cluster(args.backup_root, args.output)
    else:
        if not args.database:
            parser.error("--backup requires --database")
        result = rehearse(args.backup, args.database, args.output)
    print(result["status"])
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())


