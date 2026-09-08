"""Create private PostgreSQL and SQLite backup sets.

Use --manifest for the archive input manifest. Each sources[].database selects
one SQLite database. Repeat --config for additional private configuration files.
The archive manifest is included automatically. Browser profiles are excluded.
Retention removes only complete application backup sets within --output-dir.
"""

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time
import uuid


SET_NAME = re.compile(r"ffm-backup-\d{8}T\d{12}Z")
FILE_NAME = re.compile(r"(?:archive\.dump|backup\.json|manager-\d{3}\.sqlite3|config-\d{3}\.json)")


def regular_file(path):
    path = Path(path).expanduser().absolute()
    if any(part.lower() in {"espn-browser-profile", "browser-profile"} for part in path.parts):
        raise ValueError("Browser authentication profiles cannot enter this backup.")
    if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file():
        raise ValueError("Supply an explicit regular source file without symlinks.")
    return path.resolve()


def selected_sources(manifest_path, configs):
    manifest_path = regular_file(manifest_path)
    value = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if value.get("schema_version") != 1 or not isinstance(value.get("sources"), list):
        raise ValueError("Use a version 1 archive input manifest.")
    databases = []
    for entry in value["sources"]:
        if entry.get("database"):
            path = regular_file(manifest_path.parent / Path(entry["database"]).expanduser())
            if path not in databases:
                databases.append(path)
    if not databases:
        raise ValueError("The archive manifest must select at least one manager database.")
    config_files = list(dict.fromkeys([manifest_path, *(regular_file(item) for item in configs)]))
    if len(databases) > 999 or len(config_files) > 999:
        raise ValueError("A backup set can contain at most 999 databases and 999 configuration files.")
    return databases, config_files


def sqlite_backup(source, destination, *, timeout=120):
    deadline = time.monotonic() + timeout
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError("The SQLite backup exceeded its time limit.")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=15)) as reader:
        if reader.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='state'").fetchone() is None:
            raise ValueError("The source is not a manager database.")
        with closing(sqlite3.connect(destination)) as writer:
            reader.backup(writer, pages=256, progress=progress, sleep=.05)
            if writer.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("The SQLite backup failed its integrity check.")
    os.chmod(destination, 0o600)


def remove_set(directory, root):
    """Remove only known regular files in one checked application directory."""
    root = Path(root).resolve()
    directory = Path(directory)
    if directory.is_symlink() or directory.resolve().parent != root or not directory.is_dir():
        return False
    files = list(directory.iterdir())
    if any(item.is_symlink() or not item.is_file() or not FILE_NAME.fullmatch(item.name)
           or item.resolve().parent != directory.resolve() for item in files):
        return False
    for item in files:
        item.unlink()
    directory.rmdir()
    return True


def prune(root, retention_days, *, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    removed = 0
    for directory in Path(root).iterdir():
        if not SET_NAME.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir():
            continue
        marker = directory / "backup.json"
        try:
            if marker.is_symlink():
                continue
            value = json.loads(marker.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(value["created_at"])
            if (value.get("application") != "fantasy-football-manager" or value.get("complete") is not True
                    or created.tzinfo is None or created >= cutoff):
                continue
        except (OSError, ValueError, KeyError, TypeError):
            continue
        removed += int(remove_set(directory, root))
    return removed


def run_backup(manifest, output_dir, *, dsn="dbname=fantasy_football", configs=(), retention_days=14,
               pg_dump="pg_dump", runner=subprocess.run, now=None):
    if type(retention_days) is not int or not 1 <= retention_days <= 3650:
        raise ValueError("Retention must be from 1 through 3650 days.")
    databases, config_files = selected_sources(manifest, configs)
    root = Path(output_dir).expanduser().absolute()
    if any(item.is_symlink() for item in (root, *root.parents)):
        raise ValueError("The backup output directory cannot use symlinks.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = root.resolve()
    os.chmod(root, 0o700)
    now = now or datetime.now(timezone.utc)
    name = "ffm-backup-" + now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = root / name
    if destination.exists():
        raise ValueError("A backup set already exists for this timestamp.")
    staging = root / (".ffm-backup-staging-" + uuid.uuid4().hex)
    staging.mkdir(mode=0o700)
    records = []
    try:
        runner([pg_dump, "--dbname", dsn, "--format=custom", "--file", str(staging / "archive.dump")],
               check=True, timeout=600, stdin=subprocess.DEVNULL, capture_output=True)
        dump = staging / "archive.dump"
        if not dump.is_file() or dump.is_symlink() or dump.stat().st_size == 0:
            raise ValueError("PostgreSQL did not produce a complete dump file.")
        with dump.open("rb") as stream:
            if stream.read(5) != b"PGDMP":
                raise ValueError("The PostgreSQL dump is not in custom format.")
        os.chmod(dump, 0o600)
        records.append({"file": dump.name, "kind": "postgres"})
        for index, source in enumerate(databases, 1):
            target = staging / f"manager-{index:03}.sqlite3"
            sqlite_backup(source, target)
            records.append({"file": target.name, "source": str(source), "kind": "sqlite"})
        for index, source in enumerate(config_files, 1):
            target = staging / f"config-{index:03}.json"
            shutil.copyfile(source, target)
            os.chmod(target, 0o600)
            records.append({"file": target.name, "source": str(source), "kind": "config"})
        for record in records:
            digest, size = hashlib.sha256(), 0
            with (staging / record["file"]).open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            record.update(sha256=digest.hexdigest(), bytes=size)
        marker = {"schema_version": 1, "application": "fantasy-football-manager", "complete": True,
                  "created_at": now.isoformat(), "files": records,
                  "consistency": "Each database is internally consistent. This is not one cross-database transaction."}
        with (staging / "backup.json").open("x", encoding="utf-8") as stream:
            json.dump(marker, stream, sort_keys=True)
            stream.write("\n")
        os.chmod(staging / "backup.json", 0o600)
        staging.rename(destination)
    except BaseException:
        remove_set(staging, root)
        raise
    removed = prune(root, retention_days, now=now)
    return {"status": "complete", "backup_set": name, "sqlite_databases": len(databases),
            "configuration_files": len(config_files), "removed_sets": removed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Read the private archive input manifest.")
    parser.add_argument("--output-dir", required=True, help="Store private backup sets in this directory.")
    parser.add_argument("--dsn", default="dbname=fantasy_football", help="Use PostgreSQL peer authentication or a protected service definition.")
    parser.add_argument("--config", action="append", default=[], help="Include this explicit private configuration file. Repeat as needed.")
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--pg-dump", default="pg_dump")
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(run_backup(args.manifest, args.output_dir, dsn=args.dsn, configs=args.config,
                               retention_days=args.retention_days, pg_dump=args.pg_dump)), flush=True)


if __name__ == "__main__":
    main()
