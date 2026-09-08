"""Local SQLite state with atomic action execution and revision checks."""

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import evidence
from .models import LeagueSnapshot, ManagerConfig
from .policy import PolicyError, apply_demo_action, check_action


def default_data_dir() -> Path:
    if os.environ.get("FFM_DATA_DIR"):
        return Path(os.environ["FFM_DATA_DIR"]).expanduser()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "fantasy-football-manager"


class Manager:
    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "manager.sqlite3"
        self.lock = threading.RLock()
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1),
                    snapshot TEXT, revision INTEGER NOT NULL, config TEXT NOT NULL, config_revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, action TEXT NOT NULL, payload TEXT NOT NULL,
                    revision INTEGER NOT NULL, config_revision INTEGER NOT NULL, result TEXT);
                CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO state VALUES(1,NULL,0,?,0)", (ManagerConfig().model_dump_json(),))
            evidence.initialize(db)

    @contextmanager
    def transaction(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=15)
            db.row_factory = sqlite3.Row
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    @staticmethod
    def _state(db):
        row = db.execute("SELECT * FROM state WHERE id=1").fetchone()
        return (LeagueSnapshot.model_validate_json(row["snapshot"]) if row["snapshot"] else None,
                ManagerConfig.model_validate_json(row["config"]), row["revision"], row["config_revision"])

    @staticmethod
    def _audit(db, event, detail):
        db.execute("INSERT INTO audit(at,event,detail) VALUES(?,?,?)",
                   (datetime.now(timezone.utc).isoformat(), event, json.dumps(detail)))
        if event in evidence.AUDIT_EVENTS:
            state = Manager._state(db)
            record = evidence.envelope(*state)
            action = dict(detail)
            if event.startswith("browser_"):
                table = "browser_lineup_proposals" if event.startswith("browser_lineup_") else "browser_proposals"
                row = db.execute(f"SELECT decision FROM {table} WHERE id=?", (detail["proposal_id"],)).fetchone()
                action = {**json.loads(row["decision"]), **action,
                          "action": "set_lineup" if table == "browser_lineup_proposals" else "draft_pick"}
            record["action"] = evidence.action_or_result(action)
            evidence.append(db, event, record)
            if event in {"demo_action_executed", "browser_draft_reconciled", "browser_lineup_reconciled"}:
                evidence.append(db, "snapshot_changed", evidence.envelope(*state, include_snapshot=True))

    def state(self):
        with self.transaction() as db:
            return self._state(db)

    def require_state(self):
        state = self.state()
        if state[0] is None:
            raise ValueError("Import a league snapshot or load a demo first.")
        return state

    def import_snapshot(self, snapshot: dict, expected_revision=None):
        parsed = LeagueSnapshot.model_validate(snapshot)
        with self.transaction() as db:
            old, _, revision, config_revision = self._state(db)
            if expected_revision != revision and (old is not None or expected_revision is not None):
                raise ValueError(f"Snapshot revision conflict. Current revision: {revision}.")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("browser_proposals", "browser_lineup_proposals"):
                if table not in tables or old is None:
                    continue
                rows = db.execute(f"SELECT baseline FROM {table} WHERE league_id=? AND team_id=? AND season=? AND status='awaiting_verification'",
                                  (old.league_id, old.team_id, old.season)).fetchall()
                for row in rows:
                    baseline = LeagueSnapshot.model_validate_json(row["baseline"])
                    context = lambda value: (value.league_id, value.team_id, value.season, value.phase,
                                             value.week if value.phase == "season" else None,
                                             value.source.provider, value.source.synthetic)
                    if context(parsed) != context(baseline) or parsed.rules != baseline.rules:
                        raise ValueError("Reconcile the pending browser action before changing league context, week, source, or rules.")
            same_scope = old is not None and (old.league_id, old.team_id, old.season) == (parsed.league_id, parsed.team_id, parsed.season)
            if same_scope:
                if parsed.source.observed_at < old.source.observed_at or parsed.week < old.week:
                    raise ValueError("An older observation cannot replace current state.")
                if old.phase == "season" and parsed.phase == "draft":
                    raise ValueError("A season snapshot cannot return to draft phase.")
                if old.phase == "draft" and parsed.phase == "draft" and parsed.picks[:len(old.picks)] != old.picks:
                    raise ValueError("Draft history cannot roll back or replace confirmed picks.")
            elif old is not None:
                config_revision += 1
                db.execute("UPDATE state SET config=?,config_revision=? WHERE id=1", (ManagerConfig().model_dump_json(), config_revision))
            db.execute("UPDATE state SET snapshot=?,revision=? WHERE id=1", (parsed.model_dump_json(), revision + 1))
            self._audit(db, "snapshot_imported", {"revision": revision + 1, "synthetic": parsed.source.synthetic})
            if old is None or evidence.fingerprint(old) != evidence.fingerprint(parsed):
                evidence.append(db, "snapshot_changed", evidence.envelope(*self._state(db), include_snapshot=True))
            return {"status": "imported", "revision": revision + 1, "config_revision": config_revision,
                    "config_reset": old is not None and not same_scope}

    def update_config(self, config: dict, expected_revision: int):
        parsed = ManagerConfig.model_validate(config)
        with self.transaction() as db:
            _, _, _, revision = self._state(db)
            if expected_revision != revision:
                raise ValueError(f"Config revision conflict. Current revision: {revision}.")
            db.execute("UPDATE state SET config=?,config_revision=? WHERE id=1", (parsed.model_dump_json(), revision + 1))
            self._audit(db, "config_updated", {"config_revision": revision + 1, "config": parsed.model_dump(mode="json")})
            return {"status": "updated", "config_revision": revision + 1}

    def prepare(self, action: str, payload: dict):
        with self.transaction() as db:
            snapshot, config, revision, config_revision = self._state(db)
            if snapshot is None:
                raise ValueError("Load a snapshot first.")
            decision = check_action(snapshot, config, action, payload)
            # Validate the complete resulting roster before presenting a proposal.
            apply_demo_action(snapshot, action, decision["payload"])
            proposal_id = str(uuid.uuid4())
            db.execute("INSERT INTO proposals VALUES(?,?,?,?,?,NULL)",
                       (proposal_id, action, json.dumps(decision["payload"]), revision, config_revision))
            self._audit(db, "action_prepared", {"proposal_id": proposal_id, "action": action, "payload": decision["payload"]})
            return {"proposal_id": proposal_id, "action": action, "revision": revision, "config_revision": config_revision, **decision}

    def execute(self, proposal_id: str, confirmation: bool = False):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown proposal identifier.")
            if row["result"]:
                return {**json.loads(row["result"]), "idempotent_replay": True}
            snapshot, config, revision, config_revision = self._state(db)
            if revision != row["revision"] or config_revision != row["config_revision"]:
                raise PolicyError("State or config changed. Prepare a new proposal.")
            decision = check_action(snapshot, config, row["action"], json.loads(row["payload"]))
            if decision["requires_confirmation"] and confirmation is not True:
                raise PolicyError("Review mode requires confirmation of this exact proposal.")
            updated = apply_demo_action(snapshot, row["action"], decision["payload"])
            result = {"status": "executed", "scope": "synthetic_demo_only", "proposal_id": proposal_id,
                      "action": row["action"], "revision": revision + 1, "idempotent_replay": False}
            db.execute("UPDATE state SET snapshot=?,revision=? WHERE id=1", (updated.model_dump_json(), revision + 1))
            db.execute("UPDATE proposals SET result=? WHERE id=?", (json.dumps(result), proposal_id))
            self._audit(db, "demo_action_executed", result)
            return result

    def history(self, limit=50):
        if not 1 <= limit <= 500:
            raise ValueError("History limit must be between 1 and 500.")
        with self.transaction() as db:
            return [{"id": r["id"], "at": r["at"], "event": r["event"], "detail": json.loads(r["detail"])}
                    for r in db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))]

    def record_calculation(self, kind, snapshot, config, revision, config_revision, result, *,
                           seed=None, requested_trials=None, accepted=True, reason=None):
        """Record completed work against its original inputs, including discarded work."""
        if kind not in {"draft", "lineup", "waivers", "power_rankings"}:
            raise ValueError("Unknown evidence calculation kind.")
        record = evidence.envelope(snapshot, config, revision, config_revision)
        actual = result.get("trials", 0) if kind == "draft" else 0
        record["calculation"] = {"kind": kind, "seed": seed, "requested_trials": requested_trials,
            "completed_trials": actual if type(actual) is int and actual >= 0 else 0,
            "accepted": bool(accepted), "disposition": reason if reason in {
                "state_changed", "stopped", "paused", "stale", "incomplete", "current"} else None,
            "work_scope": "single_completed_call", "acceptance_scope": "current_calculation_not_action_permission",
            "selection_causality": "not_inferred",
            "result": evidence.action_or_result(result)}
        with self.transaction() as db:
            if reason is None:
                _, latest_config, latest_revision, latest_config_revision = self._state(db)
                age_limit = config.limits.max_draft_age_seconds if snapshot.phase == "draft" else config.limits.max_season_age_seconds
                disposition = ("state_changed" if (revision, config_revision) != (latest_revision, latest_config_revision) else
                    "paused" if latest_config.automation.paused else "incomplete" if not snapshot.source.complete else
                    "stale" if snapshot.age_seconds() > age_limit else "current")
                record["calculation"].update(disposition=disposition, accepted=bool(accepted) and disposition == "current")
            evidence.append(db, "calculation_completed", record)

    def record_submission(self, permit, result=None, *, error=None):
        """Record a browser return separately from platform confirmation."""
        with self.transaction() as db:
            record = evidence.envelope(*self._state(db))
            record["action"] = evidence.action_or_result(permit)
            record["submission"] = {"returned": error is None,
                "result": evidence.action_or_result(result or {}),
                "error_category": evidence.failure_category(error if error is not None else (result or {}).get("error")),
                "confirmation_scope": "requires_platform_reconciliation"}
            evidence.append(db, "browser_submission_returned" if error is None else "browser_submission_raised", record)
