"""One browser lineup exchange with durable authorization and observed verification."""

from datetime import datetime, timezone
import json
import uuid

from .models import LeagueSnapshot, ManagerConfig
from .policy import PolicyError, check_action, require


def _groups(snapshot):
    return {position: [f"{position}{number}" for number in range(1, count+1)]
            for position, count in snapshot.rules.starters.items() if count}


def lineup_equivalent(snapshot: LeagueSnapshot, first: dict, second: dict) -> bool:
    """Compare occupants within interchangeable slots. FLEX remains a separate group."""
    slots = snapshot.rules.lineup_slots()
    return (set(first) == set(second) == set(slots) and
            all({first[slot] for slot in group} == {second[slot] for slot in group}
                for group in _groups(snapshot).values()))


def _canonical_target(snapshot, target):
    """Keep existing occupants in equivalent slots before deriving an actual exchange."""
    current = snapshot.own_team().lineup
    require(set(target) == set(current) == set(snapshot.rules.lineup_slots()), "The lineup must identify every starter slot.")
    require(all(isinstance(pid, str) and pid for pid in target.values()) and len(set(target.values())) == len(target),
            "The target lineup must assign one player to each starter slot.")
    result = {}
    for slots in _groups(snapshot).values():
        desired = {target[slot] for slot in slots}
        for slot in slots:
            if current[slot] in desired:
                result[slot] = current[slot]
                desired.remove(current[slot])
        for slot, pid in zip((slot for slot in slots if slot not in result), sorted(desired)):
            result[slot] = pid
    return result


def _swap_details(snapshot: LeagueSnapshot, target: dict[str, str]) -> dict:
    current = snapshot.own_team().lineup
    slots = snapshot.rules.lineup_slots()
    require(set(current) == set(slots) and set(target) == set(slots),
            "A browser exchange requires complete current and target slot maps.")
    require(all(isinstance(pid, str) and pid for pid in target.values()) and len(set(target.values())) == len(target),
            "The target lineup must assign one player to each starter slot.")
    require(not lineup_equivalent(snapshot, current, target), "The lineup has the same occupants in each positional group.")
    changed = sorted(slot for slot in slots if current[slot] != target[slot])
    require(len(changed) in {1, 2}, "A browser proposal must contain exactly one lineup exchange.")
    if len(changed) == 1:
        destination = changed[0]
        source = "BN"
        require(target[destination] not in current.values(), "The incoming player must be on the bench.")
    else:
        source, destination = changed
        require(current[source] == target[destination] and current[destination] == target[source],
                "Two changed starter slots must exchange their current players.")
    incoming, outgoing = target[destination], current[destination]
    players = {player.id: player for player in snapshot.players}
    require(incoming in snapshot.own_team().roster_ids, "The incoming player is not on the active roster.")
    require(not players[incoming].locked and (outgoing is None or not players[outgoing].locked),
            "A locked player cannot participate in a browser exchange.")
    return {"source_slot": source, "destination_slot": destination,
            "player_id": incoming, "player_name": players[incoming].name,
            "outgoing_player_id": outgoing, "outgoing_player_name": players[outgoing].name if outgoing else None}


def next_lineup_swap(snapshot: LeagueSnapshot, config: ManagerConfig,
                     target: dict[str, str]) -> dict[str, str] | None:
    """Return the best permitted single exchange toward a complete target lineup.

    Each exchange must meet the configured mean improvement limit on its own.
    This helper does not claim that the complete target has been applied.
    """
    current = snapshot.own_team().lineup
    if (set(target) != set(snapshot.rules.lineup_slots()) or set(current) != set(target)
            or len(set(target.values())) != len(target) or any(not isinstance(pid, str) for pid in target.values())):
        return None
    players = {player.id: player for player in snapshot.players}
    if not set(target.values()).issubset(snapshot.own_team().roster_ids):
        return None
    try:
        target = _canonical_target(snapshot, target)
    except ValueError:
        return None
    field = {"projected_points": "weekly_projection", "floor": "weekly_floor", "upside": "weekly_ceiling"}[config.strategy.season]
    inverse = {pid: slot for slot, pid in current.items() if pid is not None}
    candidates = []
    for destination in sorted(target):
        incoming = target[destination]
        if current[destination] == incoming:
            continue
        candidate = dict(current)
        source = inverse.get(incoming)
        candidate[destination] = incoming
        if source is not None:
            candidate[source] = current[destination]
        try:
            _swap_details(snapshot, candidate)
            check_action(snapshot, config, "set_lineup", {"lineup": candidate}, execution_scope="host_browser")
        except (PolicyError, ValueError):
            continue
        from .season import lineup_delta
        objective = lineup_delta(current, candidate, players, field)
        mean = lineup_delta(current, candidate, players, "weekly_projection")
        if objective is None or mean is None:
            continue
        progress = sum(candidate[slot] == target[slot] for slot in target)
        candidates.append((objective, mean, progress, tuple(sorted(candidate.items())), candidate))
    return max(candidates, key=lambda item: item[:4])[-1] if candidates else None


class BrowserLineup:
    def __init__(self, manager):
        self.manager = manager
        with manager.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS browser_lineup_proposals (
                id TEXT PRIMARY KEY, league_id TEXT NOT NULL, team_id TEXT NOT NULL,
                season INTEGER NOT NULL, week INTEGER NOT NULL, revision INTEGER NOT NULL,
                config_revision INTEGER NOT NULL, baseline TEXT NOT NULL, decision TEXT NOT NULL,
                status TEXT NOT NULL, authorized_at TEXT, result TEXT
            )""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS browser_lineup_unresolved_scope
                ON browser_lineup_proposals(league_id,team_id,season,week) WHERE status='awaiting_verification'""")

    @staticmethod
    def _scope(snapshot):
        return snapshot.league_id, snapshot.team_id, snapshot.season, snapshot.week

    @staticmethod
    def _rosters(snapshot):
        return {team.id: (team.slot, frozenset(team.roster_ids), frozenset(team.reserve_ids)) for team in snapshot.teams}

    @staticmethod
    def _live(snapshot):
        require(snapshot.phase == "season", "Lineup verification requires a season snapshot.")
        require(snapshot.source.provider == "espn_browser" and not snapshot.source.synthetic,
                "Lineup verification requires a non-synthetic ESPN browser observation.")
        require(snapshot.source.complete and snapshot.source.locks_verified and snapshot.source.browser is not None,
                "The browser observation and player locks must be complete and verified.")
        require(set(snapshot.own_team().lineup) == set(snapshot.rules.lineup_slots()),
                "The observed lineup must identify every starter slot.")

    @staticmethod
    def _row(db, proposal_id):
        row = db.execute("SELECT * FROM browser_lineup_proposals WHERE id=?", (proposal_id,)).fetchone()
        require(row is not None, "Unknown browser lineup proposal identifier.")
        return row

    @staticmethod
    def _no_unresolved(db, scope):
        row = db.execute("""SELECT id FROM browser_lineup_proposals
            WHERE league_id=? AND team_id=? AND season=? AND week=? AND status='awaiting_verification'""", scope).fetchone()
        require(row is None, "A lineup exchange awaits verification. Reconcile it before another exchange.")

    @staticmethod
    def _view(row, should_click=False):
        baseline = LeagueSnapshot.model_validate_json(row["baseline"])
        decision = json.loads(row["decision"])
        return {"proposal_id": row["id"], "action": "set_lineup", "scope": "host_browser",
                "executor": "connected_host_browser", "league_id": baseline.league_id,
                "team_id": baseline.team_id, "season": baseline.season, "week": baseline.week,
                "revision": row["revision"], "config_revision": row["config_revision"],
                "status": row["status"], "should_click": should_click, "authorized_at": row["authorized_at"],
                "mode": decision["mode"], "requires_confirmation": decision["requires_confirmation"],
                "payload": decision["payload"], "lineup": decision["payload"]["lineup"],
                **_swap_details(baseline, decision["payload"]["lineup"])}

    def prepare(self, lineup: dict[str, str]):
        with self.manager.transaction() as db:
            snapshot, config, revision, config_revision = self.manager._state(db)
            require(snapshot is not None, "Load a snapshot first.")
            self._live(snapshot)
            self._no_unresolved(db, self._scope(snapshot))
            lineup = _canonical_target(snapshot, lineup)
            decision = check_action(snapshot, config, "set_lineup", {"lineup": lineup}, execution_scope="host_browser")
            _swap_details(snapshot, decision["payload"]["lineup"])
            proposal_id = str(uuid.uuid4())
            db.execute("""INSERT INTO browser_lineup_proposals
                (id,league_id,team_id,season,week,revision,config_revision,baseline,decision,status)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (proposal_id, *self._scope(snapshot), revision, config_revision,
                    snapshot.model_dump_json(), json.dumps(decision), "pending"))
            self.manager._audit(db, "browser_lineup_prepared", {"proposal_id": proposal_id,
                                "lineup": decision["payload"]["lineup"], "revision": revision, "config_revision": config_revision})
            return self._view(self._row(db, proposal_id))

    def get(self, proposal_id):
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            return json.loads(row["result"]) if row["result"] else self._view(row)

    def pending(self):
        with self.manager.transaction() as db:
            snapshot, _, _, _ = self.manager._state(db)
            if snapshot is None:
                return []
            rows = db.execute("""SELECT * FROM browser_lineup_proposals
                WHERE league_id=? AND team_id=? AND season=? AND status='awaiting_verification'
                ORDER BY authorized_at,id""", self._scope(snapshot)[:3]).fetchall()
            return [self._view(row) for row in rows]

    def authorize(self, proposal_id, confirmation=False):
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            if row["result"]:
                return json.loads(row["result"])
            if row["status"] == "awaiting_verification":
                return self._view(row)
            require(row["status"] == "pending", "This lineup proposal cannot be authorized.")
            snapshot, config, revision, config_revision = self.manager._state(db)
            require(snapshot is not None and (revision, config_revision) == (row["revision"], row["config_revision"]),
                    "State or config changed. Prepare a new lineup proposal.")
            self._no_unresolved(db, self._scope(snapshot))
            self._live(snapshot)
            decision = check_action(snapshot, config, "set_lineup", json.loads(row["decision"])["payload"], execution_scope="host_browser")
            _swap_details(snapshot, decision["payload"]["lineup"])
            require(not decision["requires_confirmation"] or confirmation is True,
                    "Review mode requires confirmation of this exact lineup proposal.")
            db.execute("UPDATE browser_lineup_proposals SET status='awaiting_verification',authorized_at=? WHERE id=?",
                       (datetime.now(timezone.utc).isoformat(), proposal_id))
            result = self._view(self._row(db, proposal_id), should_click=True)
            self.manager._audit(db, "browser_lineup_authorized", {"proposal_id": proposal_id, "authorized_at": result["authorized_at"]})
            return result

    def validate_permit(self, permit: dict, snapshot=None) -> bool:
        """Recheck the claim and optional fresh browser state immediately before confirmation."""
        with self.manager.transaction() as db:
            row = self._row(db, permit["proposal_id"])
            require(row["status"] == "awaiting_verification", "This lineup claim is no longer awaiting verification.")
            expected = self._view(row)
            keys = ("action", "scope", "league_id", "team_id", "season", "week", "revision", "config_revision",
                    "payload", "lineup", "source_slot", "destination_slot", "player_id", "player_name",
                    "outgoing_player_id", "outgoing_player_name", "authorized_at")
            require(permit.get("should_click") is True and all(permit.get(key) == expected[key] for key in keys),
                    "The lineup click permit changed or does not grant a click.")
            current, config, revision, config_revision = self.manager._state(db)
            require((revision, config_revision) == (row["revision"], row["config_revision"]), "State or config changed before confirmation.")
            baseline = LeagueSnapshot.model_validate_json(row["baseline"])
            observed = current if snapshot is None else LeagueSnapshot.model_validate(snapshot)
            self._live(observed)
            require(self._scope(observed) == self._scope(baseline) and observed.rules == baseline.rules
                    and {team.id: team.slot for team in observed.teams} == {team.id: team.slot for team in baseline.teams}
                    and self._rosters(observed)[observed.team_id] == self._rosters(baseline)[baseline.team_id]
                    and lineup_equivalent(baseline, observed.own_team().lineup, baseline.own_team().lineup),
                    "The observed context, rosters, rules, or lineup changed before confirmation.")
            require(observed.source.observed_at >= baseline.source.observed_at, "The browser observation is older than the proposal.")
            target = _canonical_target(observed, expected["lineup"])
            details = _swap_details(observed, target)
            require(details["player_id"] == expected["player_id"] and details["outgoing_player_id"] == expected["outgoing_player_id"],
                    "The incoming or outgoing player changed before confirmation.")
            check_action(observed, config, "set_lineup", {"lineup": target}, execution_scope="host_browser")
            return True

    def reconcile(self, proposal_id, snapshot):
        with self.manager.transaction() as db:
            row = self._row(db, proposal_id)
            if row["result"]:
                return json.loads(row["result"])
            require(row["status"] == "awaiting_verification" and row["authorized_at"], "Authorize this lineup proposal before verification.")
            observed = LeagueSnapshot.model_validate(snapshot)
            self._live(observed)
            baseline = LeagueSnapshot.model_validate_json(row["baseline"])
            require(self._scope(observed) == self._scope(baseline), "The observed league, team, season, or week differs from the proposal.")
            require(observed.rules == baseline.rules and
                    {team.id: team.slot for team in observed.teams} == {team.id: team.slot for team in baseline.teams},
                    "The observed rules or team identities changed during the exchange.")
            require(observed.picks == baseline.picks, "The observed draft history changed during the lineup exchange.")
            require(observed.source.observed_at >= datetime.fromisoformat(row["authorized_at"]), "The observation predates lineup authorization.")
            current, _, revision, config_revision = self.manager._state(db)
            require(current is not None and current.phase == "season" and self._scope(current) == self._scope(baseline)
                    and current.source.provider == "espn_browser" and not current.source.synthetic,
                    "The active league context changed. Verification cannot replace current state.")
            require(current.rules == baseline.rules, "Stored rules changed during the exchange.")
            require(observed.source.observed_at >= current.source.observed_at, "An older observation cannot replace stored state.")
            target = json.loads(row["decision"])["payload"]["lineup"]
            actual = observed.own_team().lineup
            own_roster_same = self._rosters(observed)[observed.team_id] == self._rosters(baseline)[baseline.team_id]
            if own_roster_same and lineup_equivalent(baseline, actual, baseline.own_team().lineup):
                return self._view(row)
            status = "confirmed" if own_roster_same and lineup_equivalent(baseline, actual, target) else "conflict"
            result = {**self._view(row), "status": status, "actual_lineup": actual,
                      "revision": revision+1, "config_revision": config_revision,
                      "observed_at": observed.source.observed_at.isoformat()}
            db.execute("UPDATE state SET snapshot=?,revision=? WHERE id=1", (observed.model_dump_json(), revision+1))
            db.execute("UPDATE browser_lineup_proposals SET status=?,result=? WHERE id=?", (status, json.dumps(result), proposal_id))
            self.manager._audit(db, "browser_lineup_reconciled", result)
            return result
