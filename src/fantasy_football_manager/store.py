"""Local SQLite state with atomic action execution and revision checks."""

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

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
