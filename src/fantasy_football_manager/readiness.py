"""Collect private release evidence without controlling teams or contacting ESPN."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time

from filelock import FileLock

from .espn_http_actions import SLOT_IDS, _same_items, roster_slots, transaction_items
from .models import LeagueSnapshot, ManagerConfig
from .server import load_manifest, health as assess_health


DAY = 86400
MAX_GAP = 900
ACTIONS = ("set_lineup", "free_agent_add", "waiver_claim", "move_to_ir", "activate_from_ir")


def stamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Evidence timestamps require a UTC offset.")
    return parsed.timestamp()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path, maximum=8 * 1024 * 1024):
    with Path(path).open("rb") as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Evidence exceeds its size limit.")
    return json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid number.")))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".readiness-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def receipt_verified(row, now):
    """Require the exact ESPN receipt and the reconciled complete roster result."""
    try:
        if row["status"] != "confirmed" or row["action"] not in ACTIONS:
            return False
        baseline = LeagueSnapshot.model_validate_json(row["baseline"])
        source = baseline.source
        context = (row["league_id"], row["team_id"], row["season"], row["week"])
        if context != (baseline.league_id, baseline.team_id, baseline.season, baseline.week):
            return False
        if source.provider != "espn_http" or source.synthetic or not source.complete or not source.http or not source.http.ownership_verified:
            return False
        response, result = json.loads(row["response"]), json.loads(row["result"])
        payload = json.loads(row["decision"])["payload"]
        expected = transaction_items(baseline, row["action"], payload)
        if not (response.get("id") and response.get("status") == "EXECUTED"
                and response.get("teamId") == int(row["team_id"])
                and response.get("scoringPeriodId") == row["week"]
                and response.get("type") == {"free_agent_add": "FREEAGENT", "waiver_claim": "WAIVER"}.get(row["action"], "ROSTER")
                and _same_items(response.get("items"), expected)
                and result.get("status") == "confirmed" and result.get("proposal_id") == row["id"]
                and all(result.get(k) == row[k] for k in ("league_id", "team_id", "season", "week", "action"))
                and stamp(row["authorized_at"]) <= stamp(result["observed_at"]) <= now):
            return False
        if row["action"] == "waiver_claim" and source.http.uses_faab is True and response.get("bidAmount") != payload["bid"]:
            return False
        target = roster_slots(baseline)
        for item in expected:
            pid = str(item["playerId"])
            if item["type"] == "DROP":
                target.pop(pid)
            else:
                target[pid] = item.get("toLineupSlotId", 20)
        roster, reserve = result["actual_roster_ids"], result["actual_reserve_ids"]
        if len(set(roster + reserve)) != len(roster + reserve):
            return False
        starters = [pid for pid in result["actual_lineup"].values() if pid]
        if len(set(starters)) != len(starters):
            return False
        actual = {pid: 20 for pid in roster}
        actual.update({pid: 21 for pid in reserve})
        for slot, pid in result["actual_lineup"].items():
            if pid:
                if pid not in roster:
                    return False
                actual[pid] = SLOT_IDS[slot.rstrip("0123456789")]
        if row["action"] in {"free_agent_add", "waiver_claim"}:
            return set(actual) == set(target) and all(actual[p] == s for p, s in target.items() if p != payload["player_id"])
        return actual == target
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def observe_team(entry, now):
    key = digest([entry.league_id, entry.team_id, entry.season])[:20]
    out = {"team_key": key, "valid": False, "receipts": [], "pending": [], "error": None}
    try:
        path = Path(entry.data_dir, "manager.sqlite3").resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            row = db.execute("SELECT snapshot,config,revision,config_revision FROM state WHERE id=1").fetchone()
            snapshot = LeagueSnapshot.model_validate_json(row["snapshot"])
            config = ManagerConfig.model_validate_json(row["config"])
            source, http = snapshot.source, snapshot.source.http
            age = now - source.observed_at.timestamp()
            valid = ((snapshot.league_id, snapshot.team_id, snapshot.season) == (entry.league_id, entry.team_id, entry.season)
                     and snapshot.phase == "season" and source.provider == "espn_http" and not source.synthetic
                     and source.complete and source.locks_verified and http is not None and http.ownership_verified
                     and http.transaction_period == snapshot.week and 0 <= age <= config.limits.max_season_age_seconds)
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            rows = db.execute("SELECT * FROM espn_http_proposals ORDER BY rowid DESC LIMIT 1001").fetchall() if "espn_http_proposals" in tables else []
            if len(rows) > 1000:
                raise ValueError("Proposal history requires a larger reviewed collection window.")
            for proposal in rows:
                if (proposal["league_id"], proposal["team_id"], proposal["season"]) != (entry.league_id, entry.team_id, entry.season):
                    continue
                identifier = digest([key, proposal["id"]])
                if proposal["status"] in {"pending_waiver", "awaiting_verification"}:
                    out["pending"].append({"id": identifier, "status": proposal["status"], "week": proposal["week"]})
                if receipt_verified(proposal, now):
                    out["receipts"].append({"id": identifier, "action": proposal["action"], "week": proposal["week"],
                                            "observed_at": json.loads(proposal["result"])["observed_at"],
                                            "proof_hash": digest(dict(proposal))})
            out.update(valid=bool(valid), week=snapshot.week, observed_at=source.observed_at.isoformat(),
                       policy_hash=digest(config.model_dump(mode="json")), revision=row["revision"], config_revision=row["config_revision"],
                       modes={action: config.automation.mode_for(action) for action in ACTIONS}, paused=config.automation.paused,
                       uses_faab=http.uses_faab if http else None)
            own = snapshot.own_team()
            out["opportunities"] = {
                "ir_candidates_for_review": sum(p.id in own.roster_ids and p.espn is not None
                    and p.espn.injured is True and 21 in p.espn.eligible_slots and p.espn.roster_locked is False for p in snapshot.players),
                "reserve_players_for_review": len(own.reserve_ids),
                "observed_waiver_players": sum(p.espn is not None and p.espn.acquisition_status == "WAIVERS" for p in snapshot.players),
                "pending_transactions_known": http.pending_transactions_known if http else False,
                "pending_transaction_count": len(http.pending_transactions) if http and http.pending_transactions_known else None,
                "requires_policy_and_roster_review": True,
            }
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, AttributeError):
        out["error"] = "team_evidence_unavailable_or_invalid"
    return out


def gate(passed, reason):
    return {"status": "passed" if passed else "pending", "reason": reason}


def record_sample(db, sample):
    db.execute("CREATE TABLE IF NOT EXISTS samples(at REAL PRIMARY KEY, scope TEXT NOT NULL, value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, scope TEXT NOT NULL, last_seen REAL NOT NULL, value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS pending_seen(id TEXT PRIMARY KEY, at REAL NOT NULL)")
    compact = {k: sample[k] for k in ("at", "scope", "healthy")}
    compact["teams"] = []
    for team in sample["teams"]:
        compact["teams"].append({k: team[k] for k in ("team_key", "valid", "week", "pending") if k in team} | {"receipts": []})
        for pending in team["pending"]:
            if pending["status"] == "pending_waiver":
                db.execute("INSERT OR IGNORE INTO pending_seen VALUES(?,?)", (pending["id"], sample["at"]))
        for proof in team["receipts"]:
            db.execute("INSERT OR REPLACE INTO receipts VALUES(?,?,?,?)", (proof["id"], sample["scope"], sample["at"], json.dumps(proof)))
    db.execute("INSERT OR REPLACE INTO samples VALUES(?,?,?)", (sample["at"], sample["scope"], json.dumps(compact)))
    # Keep 35 days of bounded observations. Never modify team stores or their archive.
    db.execute("DELETE FROM samples WHERE at < ?", (sample["at"] - 35 * DAY,))
    db.execute("DELETE FROM receipts WHERE last_seen < ?", (sample["at"] - 35 * DAY,))
    db.execute("DELETE FROM pending_seen WHERE at < ? AND id NOT IN (SELECT id FROM receipts)", (sample["at"] - 35 * DAY,))
    db.commit()


def evaluate(samples, current, known_receipts=()):
    """A scope change, evidence gap, or unhealthy sample prevents a continuous-cycle pass."""
    same = [s for s in samples if s["scope"] == current["scope"] and s["at"] <= current["at"]]
    gates = {"operational_health": gate(current["healthy"], "Fresh observations and analysis are required for every enabled team.")}
    proofs = {a: [] for a in ACTIONS}
    queued = set()
    for s in same:
        for t in s["teams"]:
            queued.update(p["id"] for p in t["pending"] if p["status"] == "pending_waiver")
            for proof in t["receipts"]:
                if proof["action"] != "waiver_claim" or proof["id"] in queued:
                    proofs[proof["action"]].append(proof["id"])
    for action in ACTIONS:
        for proof in known_receipts:
            if proof["action"] == action and (action != "waiver_claim" or proof.get("pending_seen") is True):
                proofs[action].append(proof["id"])
        gates["live_" + action] = gate(bool(proofs[action]), "Exact executed receipt and matching reconciled roster required. Waivers also require observed pending state.")
    rollover = set()
    previous = {}
    for s in same:
        for t in s["teams"]:
            if not t["valid"]:
                continue
            prior = previous.get(t["team_key"])
            if (prior and t["week"] == prior["week"] + 1 and s["healthy"]
                    and not any(p["week"] < t["week"] for p in t["pending"])):
                rollover.add(t["team_key"])
            previous[t["team_key"]] = t
    keys = {t["team_key"] for t in current["teams"]}
    gates["live_rollover"] = gate(bool(keys) and keys <= rollover, "Every enabled team needs a verified forward week change and fresh analysis.")
    window = [s for s in samples if s["at"] >= current["at"] - 7 * DAY - MAX_GAP and s["at"] <= current["at"]]
    span = window[-1]["at"] - window[0]["at"] if window else 0
    gaps = [b["at"] - a["at"] for a, b in zip(window, window[1:])]
    continuity = (span >= 7 * DAY and all(s["healthy"] and s["scope"] == current["scope"] for s in window)
                  and max(gaps, default=0) <= MAX_GAP and bool(keys) and keys <= rollover)
    gates["weekly_cycle"] = gate(continuity, "Seven observed days, no unexplained health failure or collection gap over 15 minutes, and all-team rollover required.")
    for name, reason in {
        "waiver_window": "Verify each league's processing window and terminal results. A calendar date alone is insufficient.",
        "backup_restore": "A current verified backup and an isolated full restore are required.",
        "installation_provenance": "Compare the candidate with installed services, plugin files, and MCP definitions.",
        "candidate_checks": "Candidate CI, clean installation, upgrade rehearsal, and documentation review are required.",
        "distribution_build": "Verify release artifacts and actual Glama build evidence for the selected commit.",
        "publication_approval": "Stable publication requires a separate release decision.",
    }.items():
        gates[name] = gate(False, reason)
    return {"gates": gates, "observation_span_hours": round(span / 3600, 2), "max_gap_seconds": max(gaps, default=0),
            "rollover_team_count": len(keys & rollover), "verified_receipt_counts": {a: len(set(ids)) for a, ids in proofs.items()}}


def supplementary_gates(root, report, now):
    """Consume explicit local rehearsal receipts. Missing receipts remain pending.

    These files are operator-controlled evidence, not an external attestation service.
    Candidate receipts must identify one exact reviewed commit. No date grants publication.
    """
    def receipt(name, max_age):
        try:
            value = read_json(root / name)
            if value.get("schema_version") != 1 or not 0 <= now - stamp(value["checked_at"]) <= max_age:
                return {}
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return {}
    backup = receipt("backup-report.json", 36 * 3600)
    backup_ok = (backup.get("kind") == "backup_integrity" and backup.get("status") == "passed"
                 and backup.get("counts", {}).get("sqlite") == report["team_count"]
                 and isinstance(backup.get("marker_sha256"), str) and len(backup["marker_sha256"]) == 64
                 and 0 <= now - stamp(backup["backup_created_at"]) <= 36 * 3600) if backup else False
    report["gates"]["backup_integrity"] = gate(backup_ok, "Require fresh checksums, all team databases, SQLite integrity, and a readable PostgreSQL dump.")
    restore = receipt("restore-report.json", 7 * DAY)
    restore_ok = (restore.get("kind") == "isolated_restore" and restore.get("status") == "passed"
                  and restore.get("full_restore") is True and restore.get("sqlite_verified") == report["team_count"]
                  and restore.get("postgres_tables_verified", 0) >= 6 and restore.get("isolated_database_removed") is True)
    report["gates"]["backup_restore"] = gate(bool(backup_ok and restore_ok), "Require current backup integrity and a full isolated restore within seven days.")
    candidate = receipt("candidate-report.json", 7 * DAY)
    commit = candidate.get("commit", "")
    pinned = isinstance(commit, str) and len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
    checks = candidate.get("checks", {})
    report["gates"]["candidate_checks"] = gate(pinned and all(checks.get(k) is True for k in
        ("ci", "clean_install", "upgrade", "draft_regression", "dashboard_regression", "docs_current")),
        "Require passing checks bound to one reviewed commit; a source test alone is insufficient.")
    installed = receipt("installation-report.json", DAY)
    report["gates"]["installation_provenance"] = gate(pinned and installed.get("commit") == commit and
        all(installed.get("checks", {}).get(k) is True for k in ("services_match", "plugins_match", "mcp_definitions_match")),
        "Require service, plugin, and MCP definition comparisons against the selected candidate.")
    windows = receipt("waiver-window-report.json", 7 * DAY)
    # Each league needs a source-backed processing interval and a checked terminal result.
    expected = {t["team_key"] for t in report["teams"]}
    rows = windows.get("teams", [])
    window_ok = isinstance(rows, list) and len(rows) == len(expected) and {t.get("team_key") for t in rows} == expected
    if window_ok:
        try:
            window_ok = all(t.get("provider") == "espn_http" and t.get("rules_verified") is True
                            and t.get("terminal_results_verified") is True
                            and stamp(t["opened_at"]) < stamp(t["closed_at"]) <= stamp(t["verified_at"]) <= now for t in rows)
        except (ValueError, TypeError, KeyError):
            window_ok = False
    report["gates"]["waiver_window"] = gate(bool(window_ok), "Require actual league processing evidence and reconciled terminal outcomes for all teams.")
    published = receipt("distribution-build-report.json", DAY)
    report["gates"]["distribution_build"] = gate(pinned and published.get("commit") == commit and
        all(published.get("checks", {}).get(k) is True for k in ("github_artifacts", "pypi_artifacts", "registry", "glama_build_commit")),
        "Require artifact hashes and actual hosted build evidence for the selected commit.")


def service_checks(runner=subprocess.run):
    results = {}
    for unit in ("fantasy-football-season.service", "fantasy-football-archive.timer", "fantasy-football-backup.timer"):
        try:
            r = runner(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
            results[unit] = r.returncode == 0 and r.stdout.strip() == "active"
        except (OSError, subprocess.SubprocessError):
            results[unit] = False
    return results


def observe_coordinator(manifest, *, now=None, sleeper=time.sleep):
    for attempt in range(8):
        observed_time = now or datetime.now(timezone.utc)
        try:
            saved = read_json(manifest.status_file)
            if not isinstance(saved, dict):
                saved = {}
        except (OSError, ValueError):
            saved = {}
        health = assess_health(saved)
        teams = [observe_team(e, observed_time.timestamp()) for e in manifest.leagues if e.enabled]
        recorded = [t for t in saved.get("leagues", []) if isinstance(t, dict) and t.get("enabled") is True]
        consistent = len(recorded) == len(teams) and all(
            t.get("revision") == r.get("revision") and t.get("config_revision") == r.get("config_revision")
            and t.get("team_key") == digest([r.get("league_id"), r.get("team_id"), r.get("season")])[:20]
            for t, r in zip(teams, recorded))
        transient = saved.get("status") == "visiting" or (bool(recorded) and not consistent)
        if not transient or attempt == 7:
            return observed_time, health, teams, consistent, attempt
        sleeper(3)


def archive_check(dsn, team_count, now):
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=5, options="-c statement_timeout=5000") as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            latest = connection.execute("SELECT max(imported_at) FROM archive_imports").fetchone()[0]
            checkpoints = connection.execute("SELECT count(*) FROM archive_source_checkpoints").fetchone()[0]
        age = now - stamp(latest)
        return {"verified": 0 <= age <= MAX_GAP and checkpoints == team_count,
                "latest_import_age_seconds": round(age, 2), "source_checkpoints": checkpoints}
    except Exception:
        # Never expose connection strings or driver errors in reports.
        return {"verified": False, "reason": "archive_evidence_unavailable"}


def collect(manifest_path, output_dir, *, now=None, systemd=False, archive_dsn=None):
    if now is not None and now.tzinfo is None:
        raise ValueError("Use an aware collection time.")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = load_manifest(manifest_path)
    # A separate destination is mandatory, including for an empty source directory.
    if any(root == Path(e.data_dir).resolve() or root in Path(e.data_dir).resolve().parents for e in manifest.leagues):
        raise ValueError("Use a separate readiness output directory.")
    with FileLock(str(root / "collector.lock"), timeout=0):
        now, health, teams, consistent, retries = observe_coordinator(manifest, now=now)
        sample = {"at": now.timestamp(), "scope": digest(sorted(t["team_key"] for t in teams)), "teams": teams,
                  "healthy": bool(teams) and health["healthy"] and consistent and all(t["valid"] for t in teams)}
        services = service_checks() if systemd else {}
        archive = archive_check(archive_dsn, len(teams), now.timestamp()) if archive_dsn else {"verified": None}
        if systemd:
            sample["healthy"] = sample["healthy"] and all(services.values())
        if archive_dsn:
            sample["healthy"] = sample["healthy"] and archive["verified"]
        with closing(sqlite3.connect(root / "observations.sqlite3")) as db:
            record_sample(db, sample)
            samples = [json.loads(r[0]) for r in db.execute("SELECT value FROM samples ORDER BY at")]
            known = []
            for value, pending_at in db.execute("SELECT r.value,p.at FROM receipts r LEFT JOIN pending_seen p ON r.id=p.id WHERE r.scope=?", (sample["scope"],)):
                proof = json.loads(value)
                proof["pending_seen"] = pending_at is not None and pending_at <= stamp(proof["observed_at"])
                known.append(proof)
        report = {"schema_version": 1, "checked_at": now.isoformat(), "expires_at": datetime.fromtimestamp(now.timestamp() + MAX_GAP, timezone.utc).isoformat(),
                  "status": "pending", "release_ready": False, "healthy": sample["healthy"], "team_count": len(teams),
                  "transport": manifest.transport, "auto_rollover": manifest.auto_rollover,
                  "services": services, "archive": archive, "transition_retries": retries,
                  "teams": teams, "health_reasons": health["reasons"], **evaluate(samples, sample, known),
                  "model_calls": 0, "provider_requests": 0, "live_action_calls": 0}
        supplementary_gates(root, report, now.timestamp())
        atomic_json(root / "report.json", report)
        # One daily summary is replaced atomically; observations remain in the bounded database.
        atomic_json(root / "daily-summary.json", {"date": now.date().isoformat(), **public_report(root / "report.json")})
        return report


def public_report(path):
    """Read only the report schema; never expose a raw evidence file through HTTP."""
    try:
        r = read_json(path)
        fresh = stamp(r["checked_at"]) <= datetime.now(timezone.utc).timestamp() <= stamp(r["expires_at"])
        allowed = ("operational_health", *("live_" + a for a in ACTIONS), "live_rollover", "weekly_cycle", "waiver_window",
                   "backup_integrity", "backup_restore", "installation_provenance", "candidate_checks", "distribution_build", "publication_approval")
        statuses = {k: r["gates"][k]["status"] for k in allowed}
        if r["schema_version"] != 1 or any(s not in {"passed", "pending", "failed"} for s in statuses.values()):
            raise ValueError()
        return {"status": "pending" if fresh else "stale", "checked_at": r["checked_at"], "release_ready": False,
                "healthy": fresh and r["healthy"] is True, "team_count": int(r["team_count"]), "gates": statuses}
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "unavailable", "release_ready": False, "gates": {}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--systemd", action="store_true", help="Also verify the existing coordinator and archive/backup timers.")
    parser.add_argument("--archive-dsn", help="Optional local PostgreSQL service definition or peer-authenticated database. Do not include credentials.")
    args = parser.parse_args()
    try:
        r = collect(args.manifest, args.output_dir, systemd=args.systemd, archive_dsn=args.archive_dsn)
        print(json.dumps({"status": r["status"], "healthy": r["healthy"], "team_count": r["team_count"],
                          "gates": {k: v["status"] for k, v in r["gates"].items()}}))
        return 0 if r["healthy"] else 1
    except (OSError, ValueError, sqlite3.Error):
        print(json.dumps({"status": "failed", "reason": "Readiness evidence is unavailable or invalid."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
