"""Authorize one host browser click and reconcile the observed ESPN draft state.

This module does not control a browser. A click authorization is not proof of a pick.
Only a complete platform observation can settle an authorized proposal.
"""

from datetime import datetime, timezone
import json
import uuid

from .models import LeagueSnapshot
from .policy import check_action, require


class BrowserDraft:
    def __init__(self, manager):
        self.manager = manager
        with manager.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS browser_proposals (
                id TEXT PRIMARY KEY, league_id TEXT NOT NULL, team_id TEXT NOT NULL,
                season INTEGER NOT NULL, revision INTEGER NOT NULL, config_revision INTEGER NOT NULL,
                baseline TEXT NOT NULL, decision TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, authorized_at TEXT, result TEXT
            )""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS browser_draft_unresolved_scope
                ON browser_proposals(league_id,team_id,season) WHERE status='awaiting_verification'""")

    @staticmethod
    def _scope(snapshot):
        return snapshot.league_id, snapshot.team_id, snapshot.season

    @staticmethod
    def _live_draft(snapshot):
        require(snapshot.phase == "draft", "Browser reconciliation requires a draft snapshot.")
        require(snapshot.source.complete, "The platform snapshot is incomplete.")
        require(snapshot.source.provider == "espn_browser" and not snapshot.source.synthetic,
                "Browser reconciliation requires a non-synthetic ESPN browser observation.")
        browser = snapshot.source.browser
        require(browser is not None, "The platform browser observation is missing.")
        if browser.draft_complete:
            require(len(snapshot.picks) == snapshot.rules.teams * snapshot.rules.rounds,
                    "The completed platform draft does not include every pick.")
        else:
            require(browser.current_pick == len(snapshot.picks) + 1,
                    "The platform draft clock does not match the complete pick history.")

    @staticmethod
    def _row(db, proposal_id):
        row = db.execute("SELECT * FROM browser_proposals WHERE id=?", (proposal_id,)).fetchone()
        require(row is not None, "Unknown browser proposal identifier.")
        return row

    @staticmethod
    def _no_unresolved(db, scope, exclude=None):
        rows = db.execute("""SELECT id FROM browser_proposals
            WHERE league_id=? AND team_id=? AND season=? AND status='awaiting_verification'""", scope)
        require(not any(row["id"] != exclude for row in rows),
                "A browser pick awaits verification. Reconcile that proposal before another click.")

    @staticmethod
    def _view(row, should_click=False):
        baseline = LeagueSnapshot.model_validate_json(row["baseline"])
        decision = json.loads(row["decision"])
        pid = decision["payload"]["player_id"]
        player = next(player for player in baseline.players if player.id == pid)
        return {"proposal_id": row["id"], "action": "draft_pick", "scope": "host_browser",
                "executor": "connected_host_browser", "status": row["status"],
                "league_id": baseline.league_id, "team_id": baseline.team_id, "season": baseline.season,
                "pick_no": len(baseline.picks) + 1, "player_id": pid, "player_name": player.name,
                "payload": decision["payload"], "revision": row["revision"],
                "config_revision": row["config_revision"], "mode": decision["mode"],
                "requires_confirmation": decision["requires_confirmation"],
                "should_click": should_click, "authorized_at": row["authorized_at"]}

    def prepare(self, player_id):
        """Prepare an exact pick from the current state. This does not authorize a click."""
        with self.manager.transaction() as db:
            snapshot, config, revision, config_revision = self.manager._state(db)
            require(snapshot is not None, "Load a snapshot first.")
            self._no_unresolved(db, self._scope(snapshot))
            decision = check_action(snapshot, config, "draft_pick", {"player_id": player_id},
                                    execution_scope="host_browser")
            self._live_draft(snapshot)
            proposal_id = str(uuid.uuid4())
            db.execute("""INSERT INTO browser_proposals
                (id,league_id,team_id,season,revision,config_revision,baseline,decision,status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (proposal_id, *self._scope(snapshot), revision, config_revision,
                        snapshot.model_dump_json(), json.dumps(decision), "pending",
                        datetime.now(timezone.utc).isoformat()))
            self.manager._audit(db, "browser_draft_prepared", {"proposal_id": proposal_id,
                                "player_id": player_id, "revision": revision, "config_revision": config_revision})
            return self._view(self._row(db, proposal_id))

    def get(self, proposal_id):
        """Read a proposal without granting click authorization."""
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            return json.loads(row["result"]) if row["result"] else self._view(row)

    def pending(self):
        """Read unresolved click claims for the active league, team, and season."""
        with self.manager.transaction() as db:
            snapshot, _, _, _ = self.manager._state(db)
            if snapshot is None:
                return []
            rows = db.execute("""SELECT * FROM browser_proposals
                WHERE league_id=? AND team_id=? AND season=? AND status='awaiting_verification'
                ORDER BY authorized_at,id""", self._scope(snapshot)).fetchall()
            return [self._view(row) for row in rows]

    def authorize(self, proposal_id, confirmation=False):
        """Claim one click. Repeated calls never authorize another click."""
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            if row["result"]:
                return json.loads(row["result"])
            if row["status"] == "awaiting_verification":
                return self._view(row)
            require(row["status"] == "pending", "This browser proposal cannot be authorized.")
            snapshot, config, revision, config_revision = self.manager._state(db)
            require(snapshot is not None and (revision, config_revision) == (row["revision"], row["config_revision"]),
                    "State or config changed. Prepare a new browser proposal.")
            self._no_unresolved(db, self._scope(snapshot), exclude=proposal_id)
            decision = check_action(snapshot, config, "draft_pick", json.loads(row["decision"])["payload"],
                                    execution_scope="host_browser")
            self._live_draft(snapshot)
            require(not decision["requires_confirmation"] or confirmation is True,
                    "Review mode requires confirmation of this exact browser proposal.")
            authorized_at = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE browser_proposals SET status='awaiting_verification',authorized_at=?,decision=? WHERE id=?",
                       (authorized_at, json.dumps(decision), proposal_id))
            self.manager._audit(db, "browser_draft_authorized", {"proposal_id": proposal_id,
                                "authorized_at": authorized_at, "revision": revision, "config_revision": config_revision})
            return self._view(self._row(db, proposal_id), should_click=True)

    def reconcile(self, proposal_id, snapshot):
        """Settle the claim from an observed pick. Commit the complete platform state atomically."""
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            if row["result"]:
                return json.loads(row["result"])
            require(row["status"] == "awaiting_verification" and row["authorized_at"] is not None,
                    "Authorize this browser proposal before verification.")
            observed = LeagueSnapshot.model_validate(snapshot)
            self._live_draft(observed)
            baseline = LeagueSnapshot.model_validate_json(row["baseline"])
            require(self._scope(observed) == self._scope(baseline),
                    "The platform observation belongs to another league, team, or season.")
            require(observed.rules == baseline.rules, "The platform rules differ from the authorized proposal.")
            require({team.id: team.slot for team in observed.teams} == {team.id: team.slot for team in baseline.teams},
                    "The platform team identifiers differ from the authorized proposal.")
            require(observed.source.observed_at >= datetime.fromisoformat(row["authorized_at"]),
                    "The platform observation predates click authorization.")
            require(observed.picks[:len(baseline.picks)] == baseline.picks,
                    "The platform observation changes the authorized draft history.")
            current, _, revision, config_revision = self.manager._state(db)
            require(current is not None and self._scope(current) == self._scope(baseline),
                    "The active league context changed. The observation cannot replace current state.")
            require(current.phase == "draft" and current.source.provider == "espn_browser" and not current.source.synthetic,
                    "The active source is no longer an ESPN browser draft.")
            require(current.rules == baseline.rules, "The active league rules changed.")
            require(observed.source.observed_at >= current.source.observed_at and observed.week >= current.week,
                    "An older platform observation cannot replace current state.")
            require(observed.picks[:len(current.picks)] == current.picks,
                    "The platform observation cannot roll back or replace stored picks.")
            expected = len(baseline.picks) + 1
            if len(observed.picks) < expected:
                return self._view(row)
            actual = observed.picks[expected - 1]
            target = json.loads(row["decision"])["payload"]["player_id"]
            status = "confirmed" if actual.player_id == target else "not_selected"
            result = {**self._view(row), "status": status, "revision": revision + 1,
                      "config_revision": config_revision, "actual_pick": actual.model_dump(),
                      "observed_at": observed.source.observed_at.isoformat()}
            db.execute("UPDATE state SET snapshot=?,revision=? WHERE id=1",
                       (observed.model_dump_json(), revision + 1))
            db.execute("UPDATE browser_proposals SET status=?,result=? WHERE id=?",
                       (status, json.dumps(result), proposal_id))
            self.manager._audit(db, "browser_draft_reconciled", result)
            return result
