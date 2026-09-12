"""The scheduled rehearsal must not inherit production PostgreSQL connections."""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

pytest.importorskip("psycopg")
from fantasy_football_manager import backup_restore


@pytest.mark.parametrize("failure", [None, "restore", "stop"])
def test_isolated_cluster_connection_and_cleanup(tmp_path, monkeypatch, failure):
    root = tmp_path / "backups"
    (root / "ffm-backup-20260912T090000000000Z").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("initdb", "pg_ctl", "createdb"):
        (bindir / name).touch()
    monkeypatch.setattr(backup_restore, "verify_backup", lambda _: {})
    monkeypatch.setenv("PGHOST", "production.invalid")
    monkeypatch.setenv("PGSERVICE", "production")
    monkeypatch.setenv("PGPASSWORD", "fixture-password")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        name = Path(args[0]).name
        if name == "pg_config":
            return SimpleNamespace(stdout=str(bindir))
        env = kwargs["env"]
        assert env["PGHOST"] != "production.invalid"
        assert env["PGDATABASE"].startswith("ffm_rehearsal_")
        assert "PGSERVICE" not in env and "PGPASSWORD" not in env
        if name == "initdb":
            assert "--encoding=UTF8" in args
            Path(args[args.index("-D") + 1]).mkdir()
        if "start" in args:
            config = Path(args[args.index("-D") + 1]) / "postgresql.conf"
            assert "listen_addresses = ''" in config.read_text()
        if "--output" in args:
            if failure == "restore":
                raise subprocess.CalledProcessError(1, args)
            Path(args[args.index("--output") + 1]).write_text(json.dumps({"status": "passed", "full_restore": True,
                "isolated_database_removed": True}))
        if "stop" in args and failure == "stop":
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(returncode=0)

    result = backup_restore.isolated_cluster(root, tmp_path / "report.json", runner=run)
    assert any("stop" in args for args, _ in calls)
    assert result["status"] == ("passed" if failure is None else "failed")
    assert json.loads((tmp_path / "report.json").read_text()) == result


def test_production_database_name_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="dedicated"):
        backup_restore.rehearse(tmp_path, "production", tmp_path / "report.json")


def test_missing_backup_overwrites_previous_success(tmp_path):
    output = tmp_path / "report.json"
    output.write_text('{"status":"passed"}')
    result = backup_restore.isolated_cluster(tmp_path / "missing", output)
    assert result["status"] == "failed" and result["full_restore"] is False
