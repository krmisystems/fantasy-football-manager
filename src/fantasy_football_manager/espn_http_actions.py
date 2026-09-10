"""Durable authorization and reconciliation for ESPN HTTP season transactions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid

from .browser_lineup import lineup_equivalent
from .models import LeagueSnapshot
from .policy import check_action, require


SLOT_IDS = {"QB": 0, "RB": 2, "WR": 4, "TE": 6, "DST": 16, "K": 17, "BN": 20, "IR": 21, "FLEX": 23}


def roster_slots(snapshot):
    team = snapshot.own_team()
    result = {pid: 20 for pid in team.roster_ids}
    result.update({pid: 21 for pid in team.reserve_ids})
    for slot, pid in team.lineup.items():
        if pid:
            result[pid] = SLOT_IDS[slot.rstrip("0123456789")]
    return result


def transaction_items(snapshot, action, payload):
    current = roster_slots(snapshot)
    if action == "set_lineup":
        target = {pid: 20 for pid in snapshot.own_team().roster_ids}
        target.update({pid: 21 for pid in snapshot.own_team().reserve_ids})
        for slot, pid in payload["lineup"].items():
            target[pid] = SLOT_IDS[slot.rstrip("0123456789")]
        items = [{"playerId": int(pid), "type": "LINEUP", "fromLineupSlotId": current[pid],
                  "toLineupSlotId": target[pid]} for pid in sorted(current) if current[pid] != target[pid]]
        require(items, "The lineup has no positional change to submit.")
        return items
    pid = payload["player_id"]
    if action in {"move_to_ir", "activate_from_ir"}:
        return [{"playerId": int(pid), "type": "LINEUP", "fromLineupSlotId": current[pid],
                 "toLineupSlotId": 21 if action == "move_to_ir" else 20}]
    if action == "drop_player":
        return [{"playerId": int(pid), "type": "DROP", "fromTeamId": int(snapshot.team_id)}]
    items = [{"playerId": int(pid), "type": "ADD", "toTeamId": int(snapshot.team_id)}]
    if payload.get("drop_id"):
        items.append({"playerId": int(payload["drop_id"]), "type": "DROP", "fromTeamId": int(snapshot.team_id)})
    return items


def transaction_body(snapshot, action, payload, member_id):
    kind = {"free_agent_add": "FREEAGENT", "waiver_claim": "WAIVER"}.get(action, "ROSTER")
    result = {"isLeagueManager": False, "teamId": int(snapshot.team_id), "type": kind,
              "memberId": member_id, "scoringPeriodId": snapshot.week, "executionType": "EXECUTE",
              "items": transaction_items(snapshot, action, payload)}
    if action == "waiver_claim" and snapshot.source.http.uses_faab is True:
        result["bidAmount"] = payload["bid"]
    return result


def _same_items(actual, expected):
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    return all(sum(isinstance(item, dict) and all(item.get(k) == v for k, v in target.items())
                   for item in actual) == 1 for target in expected)


class ESPNHTTPActions:
    def __init__(self, manager):
        self.manager = manager
        with manager.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS espn_http_proposals(
                id TEXT PRIMARY KEY, action TEXT NOT NULL, league_id TEXT NOT NULL, team_id TEXT NOT NULL,
                season INTEGER NOT NULL, week INTEGER NOT NULL, revision INTEGER NOT NULL,
                config_revision INTEGER NOT NULL, baseline TEXT NOT NULL, decision TEXT NOT NULL,
                status TEXT NOT NULL, authorized_at TEXT, response TEXT, result TEXT)""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS espn_http_unresolved_scope
                ON espn_http_proposals(league_id,team_id,season) WHERE status='awaiting_verification'""")

    @staticmethod
    def _scope(snapshot):
        return snapshot.league_id, snapshot.team_id, snapshot.season, snapshot.week

    @staticmethod
    def _live(snapshot):
        require(snapshot.phase == "season" and snapshot.source.provider == "espn_http"
                and not snapshot.source.synthetic and snapshot.source.http is not None
                and snapshot.source.http.ownership_verified and snapshot.source.complete,
                "This action requires a complete authenticated ESPN HTTP observation.")

    @staticmethod
    def _row(db, proposal_id):
        row = db.execute("SELECT * FROM espn_http_proposals WHERE id=?", (proposal_id,)).fetchone()
        require(row is not None, "Unknown ESPN HTTP proposal identifier.")
        return row

    @staticmethod
    def _view(row, should_submit=False):
        decision = json.loads(row["decision"])
        result = {key: row[key] for key in ("action", "league_id", "team_id", "season", "week", "revision",
                                          "config_revision", "status", "authorized_at")}
        result.update(proposal_id=row["id"], executor="espn_http",
                      should_submit=should_submit, retry_allowed=False, **decision)
        if row["response"]:
            result["transaction"] = json.loads(row["response"])
        return result

    @staticmethod
    def _no_unresolved(db, snapshot):
        for table in ("espn_http_proposals", "browser_lineup_proposals", "browser_proposals"):
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                unresolved = db.execute(f"SELECT id FROM {table} WHERE league_id=? AND team_id=? AND season=? AND status='awaiting_verification'",
                                        (snapshot.league_id, snapshot.team_id, snapshot.season)).fetchone()
                require(unresolved is None, "An ESPN submission awaits verification. Reconcile it before another submission.")

    def prepare(self, action, payload):
        with self.manager.transaction() as db:
            snapshot, config, revision, config_revision = self.manager._state(db)
            require(snapshot is not None, "Load an ESPN HTTP snapshot first.")
            self._live(snapshot)
            self._no_unresolved(db, snapshot)
            decision = check_action(snapshot, config, action, payload, execution_scope="espn_http")
            transaction_items(snapshot, action, decision["payload"])
            pid = str(uuid.uuid4())
            db.execute("""INSERT INTO espn_http_proposals
                (id,action,league_id,team_id,season,week,revision,config_revision,baseline,decision,status)
                VALUES(?,?,?,?,?,?,?,?,?,?,'pending')""", (pid, action, *self._scope(snapshot), revision, config_revision,
                                                         snapshot.model_dump_json(), json.dumps(decision)))
            result = self._view(self._row(db, pid))
            self.manager._audit(db, "espn_http_prepared", result)
            return result

    def get(self, proposal_id):
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            return json.loads(row["result"]) if row["result"] else self._view(row)

    def pending(self, *, include_waivers=False):
        with self.manager.transaction() as db:
            snapshot, _, _, _ = self.manager._state(db)
            if snapshot is None:
                return []
            statuses = ("awaiting_verification", "pending_waiver") if include_waivers else ("awaiting_verification",)
            rows = db.execute("""SELECT * FROM espn_http_proposals WHERE league_id=? AND team_id=? AND season=?
                ORDER BY authorized_at,id""", self._scope(snapshot)[:3]).fetchall()
            return [self._view(row) for row in rows if row["status"] in statuses]

    def authorize(self, proposal_id, confirmation=False):
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            if row["result"]:
                return {**json.loads(row["result"]), "should_submit": False}
            if row["status"] != "pending":
                return self._view(row)
            snapshot, config, revision, config_revision = self.manager._state(db)
            require(snapshot is not None and (revision, config_revision) == (row["revision"], row["config_revision"]),
                    "State or config changed. Prepare a new HTTP proposal.")
            self._live(snapshot)
            self._no_unresolved(db, snapshot)
            decision = check_action(snapshot, config, row["action"], json.loads(row["decision"])["payload"], execution_scope="espn_http")
            require(not decision["requires_confirmation"] or confirmation is True,
                    "Review mode requires confirmation of this exact proposal.")
            db.execute("UPDATE espn_http_proposals SET status='awaiting_verification',authorized_at=? WHERE id=?",
                       (datetime.now(timezone.utc).isoformat(), proposal_id))
            result = self._view(self._row(db, proposal_id), should_submit=True)
            self.manager._audit(db, "espn_http_authorized", result)
            return result

    def validate_permit(self, permit, fresh_snapshot):
        with self.manager.transaction() as db:
            row = self._row(db, permit["proposal_id"])
            require(row["status"] == "awaiting_verification" and permit.get("should_submit") is True,
                    "This HTTP permit does not authorize a request.")
            expected = self._view(row)
            require(all(permit.get(key) == expected.get(key) for key in
                        ("action", "league_id", "team_id", "season", "week", "revision", "config_revision", "authorized_at", "payload")),
                    "The HTTP permit has changed.")
            current, config, revision, config_revision = self.manager._state(db)
            require((revision, config_revision) == (row["revision"], row["config_revision"]),
                    "State or config changed before the HTTP request.")
            observed = LeagueSnapshot.model_validate(fresh_snapshot)
            baseline = LeagueSnapshot.model_validate_json(row["baseline"])
            self._live(observed)
            require(self._scope(observed) == self._scope(baseline) and observed.rules == baseline.rules,
                    "The observed context or rules changed before submission.")
            require(roster_slots(observed) == roster_slots(baseline), "The selected roster changed before submission.")
            require(observed.source.observed_at >= datetime.fromisoformat(row["authorized_at"]),
                    "The HTTP preflight observation predates authorization.")
            check_action(observed, config, row["action"], expected["payload"], execution_scope="espn_http")
            return True

    def record_response(self, proposal_id, response):
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            require(row["status"] == "awaiting_verification", "This proposal does not await an HTTP response.")
            baseline = LeagueSnapshot.model_validate_json(row["baseline"])
            decision = json.loads(row["decision"])
            expected = transaction_items(baseline, row["action"], decision["payload"])
            require(isinstance(response, dict) and response.get("teamId") == int(row["team_id"])
                    and response.get("scoringPeriodId") == row["week"]
                    and response.get("type") == {"free_agent_add": "FREEAGENT", "waiver_claim": "WAIVER"}.get(row["action"], "ROSTER")
                    and (row["action"] != "waiver_claim" or baseline.source.http.uses_faab is not True
                         or response.get("bidAmount") == decision["payload"]["bid"])
                    and _same_items(response.get("items"), expected),
                    "The transaction response does not match the submitted proposal.")
            allowed = {"id", "type", "teamId", "scoringPeriodId", "status", "isPending", "bidAmount", "items"}
            safe = {key: response[key] for key in allowed if key in response}
            db.execute("UPDATE espn_http_proposals SET response=? WHERE id=?", (json.dumps(safe), proposal_id))
            self.manager._audit(db, "espn_http_response", {"proposal_id": proposal_id, "transaction": safe})
            return safe

    def record_not_submitted(self, proposal_id, error):
        """Settle a failed preflight only when the adapter proves no POST began."""
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            require(row["status"] == "awaiting_verification" and row["response"] is None,
                    "Only an unsubmitted HTTP claim can end as not_submitted.")
            result = {**self._view(row), "status": "not_submitted", "submission_phase": "preflight",
                      "error": str(error), "should_submit": False}
            db.execute("UPDATE espn_http_proposals SET status='not_submitted',result=? WHERE id=?", (json.dumps(result), proposal_id))
            self.manager._audit(db, "espn_http_not_submitted", result)
            return result

    def reconcile(self, proposal_id, snapshot):
        observed = LeagueSnapshot.model_validate(snapshot)
        self._live(observed)
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            if row["result"]:
                return json.loads(row["result"])
            require(row["status"] in {"awaiting_verification", "pending_waiver"} and row["authorized_at"],
                    "Authorize this HTTP proposal before verification.")
            baseline = LeagueSnapshot.model_validate_json(row["baseline"])
            require(self._scope(observed) == self._scope(baseline) and observed.rules == baseline.rules,
                    "The reconciliation context or rules differ from the proposal.")
            require(observed.source.observed_at >= datetime.fromisoformat(row["authorized_at"]),
                    "The observation predates HTTP authorization.")
            current, _, revision, config_revision = self.manager._state(db)
            require(current is not None and self._scope(current) == self._scope(baseline)
                    and observed.source.observed_at >= current.source.observed_at,
                    "The observation cannot replace the current context or newer state.")
            payload = json.loads(row["decision"])["payload"]
            action = row["action"]
            target = roster_slots(baseline)
            for item in transaction_items(baseline, action, payload):
                pid = str(item["playerId"])
                if item["type"] == "LINEUP":
                    target[pid] = item["toLineupSlotId"]
                elif item["type"] == "DROP":
                    target.pop(pid)
                else:
                    target[pid] = 20
            actual = roster_slots(observed)
            if action in {"free_agent_add", "waiver_claim"}:
                # ESPN may place an addition directly in a vacant starter slot.
                confirmed = (set(actual) == set(target) and
                             all(actual[pid] == slot for pid, slot in target.items() if pid != payload["player_id"]))
            else:
                confirmed = actual == target
            status = "confirmed" if confirmed else "awaiting_verification"
            response = json.loads(row["response"]) if row["response"] else {}
            expected_items = transaction_items(baseline, action, payload)
            history_bid_conflict = False
            if response.get("id"):
                history = [tx for tx in observed.source.http.recent_transactions if tx.get("id") == response["id"]
                           and tx.get("teamId") == int(row["team_id"]) and tx.get("scoringPeriodId") == row["week"]
                           and tx.get("type") == response.get("type") and _same_items(tx.get("items"), expected_items)]
                if len(history) == 1:
                    response = history[0]
                    history_bid_conflict = (action == "waiver_claim" and baseline.source.http.uses_faab is True
                                            and (type(response.get("bidAmount")) is not int
                                                 or response["bidAmount"] != payload["bid"]))
                    db.execute("UPDATE espn_http_proposals SET response=? WHERE id=?", (json.dumps(response), proposal_id))
                    row = self._row(db, proposal_id)
            terminal = {"FAILED": "rejected", "DENIED": "rejected", "CANCELED": "cancelled", "CANCELLED": "cancelled"}.get(response.get("status"))
            if isinstance(response.get("status"), str) and response["status"].startswith("FAILED_"):
                terminal = "rejected"
            if terminal:
                status = terminal if actual == roster_slots(baseline) else "conflict"
            if not confirmed and not terminal and action == "waiver_claim" and observed.source.http.pending_transactions_known:
                expected = transaction_items(baseline, action, payload)
                matches = [tx for tx in observed.source.http.pending_transactions if tx.get("type") == "WAIVER"
                           and tx.get("teamId") == int(row["team_id"]) and tx.get("scoringPeriodId") == row["week"]
                           and tx.get("status") == "PENDING" and tx.get("isPending") is True
                           and (baseline.source.http.uses_faab is not True or tx.get("bidAmount") == payload["bid"])
                           and _same_items(tx.get("items"), expected)
                           and (not response.get("id") or tx.get("id") == response["id"])]
                if len(matches) == 1:
                    status = "pending_waiver"
                    if not row["response"]:
                        db.execute("UPDATE espn_http_proposals SET response=? WHERE id=?", (json.dumps(matches[0]), proposal_id))
            if history_bid_conflict:
                status = "conflict"
            if status == "awaiting_verification" and actual != roster_slots(baseline):
                status = "conflict"
            if status == "awaiting_verification":
                return self._view(row)
            if status == "pending_waiver" and row["status"] == "pending_waiver":
                return self._view(self._row(db, proposal_id))
            result = {**self._view(row), "status": status, "revision": revision + 1,
                      "config_revision": config_revision, "actual_lineup": observed.own_team().lineup,
                      "actual_roster_ids": observed.own_team().roster_ids,
                      "actual_reserve_ids": observed.own_team().reserve_ids,
                      "observed_at": observed.source.observed_at.isoformat()}
            db.execute("UPDATE state SET snapshot=?,revision=? WHERE id=1", (observed.model_dump_json(), revision + 1))
            db.execute("UPDATE espn_http_proposals SET status=?,result=? WHERE id=?",
                       (status, None if status == "pending_waiver" else json.dumps(result), proposal_id))
            self.manager._audit(db, "espn_http_reconciled", result)
            return result
