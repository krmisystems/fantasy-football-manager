"""Read configured team stores without changing state or contacting a provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from .models import ACTIONS, POSITIONS, LeagueSnapshot, ManagerConfig
from .season import recommend_lineup


MAX_TEAMS = 100
MAX_PROPOSALS_PER_TEAM = 500
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z")
_TABLES = {"proposals": (None, "synthetic"), "browser_proposals": ("draft_pick", "browser"),
           "browser_lineup_proposals": ("set_lineup", "browser"), "espn_http_proposals": (None, "http")}


def _now():
    return datetime.now(timezone.utc)


def _text(value, maximum=160):
    return value if isinstance(value, str) and 0 < len(value) <= maximum and not any(ord(c) < 32 for c in value) else None


def _key(value):
    return isinstance(value, str) and _KEY.fullmatch(value) is not None


def _json(value, maximum=MAX_JSON_BYTES):
    if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
        raise ValueError("Stored team data is invalid.")
    return json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid JSON number.")))


def _stamp(value):
    if not isinstance(value, str) or len(value) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.isoformat() if parsed.tzinfo is not None else None
    except ValueError:
        return None


@dataclass(frozen=True)
class _Entry:
    key: str
    path: Path | None
    label: str | None = None
    league_name: str | None = None
    sport: str = "football"
    provider: str = "espn"
    context: tuple[str, str, int] | None = None


@dataclass
class _Frame:
    entry: _Entry
    snapshot: LeagueSnapshot | None = None
    config: ManagerConfig | None = None
    revision: int = 0
    config_revision: int = 0
    status: str = "missing"
    proposals: list = field(default_factory=list)
    proposal_count: int = 0
    pending_count: int = 0
    truncated: bool = False
    exact_proposal: dict | None = None


class Portfolio:
    """Expose validated team summaries, players, proposals, and pure calculations."""

    def __init__(self, manifest_path=None, *, demo=False):
        if type(demo) is not bool or (demo and manifest_path is not None):
            raise ValueError("Select a manifest or the fictional demo.")
        self.demo = demo
        self._demo_frames = None
        if demo:
            from .portfolio_demo import make_portfolio_demo
            self._demo_frames = make_portfolio_demo()
            self.entries = [frame.entry for frame in self._demo_frames]
            return
        if manifest_path is None:
            self.entries = []
            return
        try:
            path = Path(manifest_path).expanduser().resolve()
            with path.open("rb") as stream:
                content = stream.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise ValueError()
            document = _json(content.decode("utf-8-sig"), 1024 * 1024)
            if not isinstance(document, dict):
                raise ValueError()
            legacy = "leagues" in document and "teams" not in document
            if not legacy and document.get("schema_version") != 1:
                raise ValueError()
            items = document.get("leagues" if legacy else "teams")
            if not isinstance(items, list) or not 1 <= len(items) <= MAX_TEAMS:
                raise ValueError()
            entries, keys, contexts, directories = [], set(), set(), set()
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError()
                sport, provider = item.get("sport", "football"), item.get("provider", "espn")
                if not _key(sport) or not _key(provider):
                    raise ValueError()
                context = None
                if legacy or any(key in item for key in ("league_id", "team_id", "season")):
                    league, team, season = item.get("league_id"), item.get("team_id"), item.get("season")
                    if not _key(league) or not _key(team) or type(season) is not int or not 2020 <= season <= 2100:
                        raise ValueError()
                    context = (league, team, season)
                key = item.get("key")
                if legacy and key is None:
                    digest = hashlib.sha256(json.dumps([sport, provider, *context]).encode()).hexdigest()[:20]
                    key = "team-" + digest
                if not _key(key) or key in keys:
                    raise ValueError()
                label, league_name = item.get("label"), item.get("league_name")
                if (label is not None and _text(label) is None) or (league_name is not None and _text(league_name) is None):
                    raise ValueError()
                directory = item.get("data_dir")
                if not isinstance(directory, str) or not directory or len(directory) > 4096:
                    raise ValueError()
                directory = Path(directory).expanduser()
                directory = (path.parent / directory).resolve() if not directory.is_absolute() else directory.resolve()
                scope = None if context is None else (sport, provider, *context)
                if directory in directories or (scope is not None and scope in contexts):
                    raise ValueError()
                keys.add(key)
                directories.add(directory)
                contexts.add(scope)
                entries.append(_Entry(key, directory / "manager.sqlite3", label, league_name, sport, provider, context))
            self.entries = entries
        except (OSError, ValueError, TypeError, RuntimeError, RecursionError):
            raise ValueError("The portfolio manifest is invalid or unavailable.") from None

    def _select(self, team_key=None):
        if team_key is None:
            return self.entries
        if not _key(team_key):
            raise ValueError("Unknown managed team.")
        selected = [entry for entry in self.entries if entry.key == team_key]
        if not selected:
            raise ValueError("Unknown managed team.")
        return selected

    def _load(self, entry, exact_proposal_id=None):
        if self._demo_frames is not None:
            return next(frame for frame in self._demo_frames if frame.entry.key == entry.key)
        frame = _Frame(entry)
        if entry.sport != "football" or entry.provider not in {"espn", "local", "synthetic"}:
            frame.status = "unsupported"
            return frame
        if not entry.path.is_file():
            return frame
        try:
            with sqlite3.connect(entry.path.as_uri() + "?mode=ro", uri=True, timeout=1) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                db.execute("PRAGMA trusted_schema=OFF")
                deadline, work = time.monotonic() + 2, [0]
                def stop_query():
                    work[0] += 1
                    return int(work[0] > 1000 or time.monotonic() > deadline)
                db.set_progress_handler(stop_query, 5000)
                db.execute("BEGIN")
                row = db.execute("""SELECT revision, config_revision,
                    CASE WHEN length(CAST(snapshot AS BLOB)) <= ? THEN snapshot END AS snapshot,
                    CASE WHEN length(CAST(config AS BLOB)) <= ? THEN config END AS config,
                    snapshot IS NOT NULL AS has_snapshot FROM state WHERE id=1""",
                    (MAX_SNAPSHOT_BYTES, MAX_JSON_BYTES)).fetchone()
                if row is None or not row["has_snapshot"]:
                    return frame
                snapshot = LeagueSnapshot.model_validate(_json(row["snapshot"], MAX_SNAPSHOT_BYTES))
                config = ManagerConfig.model_validate(_json(row["config"]))
                context = (snapshot.league_id, snapshot.team_id, snapshot.season)
                if entry.context is not None and entry.context != context:
                    raise ValueError()
                if any(type(row[key]) is not int or row[key] < 0 for key in ("revision", "config_revision")):
                    raise ValueError()
                frame.snapshot, frame.config = snapshot, config
                frame.revision, frame.config_revision = row["revision"], row["config_revision"]
                frame.status = "ready"
                self._read_proposals(db, frame)
                if exact_proposal_id is not None:
                    exact = db.execute("""SELECT id, action, league_id, team_id, season, week,
                        revision, config_revision, status, authorized_at,
                        CASE WHEN length(CAST(decision AS BLOB)) <= ? THEN decision END AS decision
                        FROM espn_http_proposals WHERE id=? AND league_id=? AND team_id=? AND season=?""",
                        (MAX_JSON_BYTES, exact_proposal_id, *context)).fetchone()
                    frame.exact_proposal = dict(exact) if exact is not None else None
                db.rollback()
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, IndexError, RecursionError):
            return _Frame(entry, status="invalid")
        finally:
            if "db" in locals():
                db.close()
        return frame

    def _frames(self, team_key=None):
        selected = {entry.key for entry in self._select(team_key)}
        frames = [self._load(entry) for entry in self.entries]
        scopes, duplicates = {}, set()
        for frame in frames:
            if frame.snapshot is None:
                continue
            snapshot = frame.snapshot
            scope = (frame.entry.sport, frame.entry.provider, snapshot.league_id, snapshot.team_id, snapshot.season)
            if scope in scopes:
                duplicates.update((scopes[scope], frame.entry.key))
            scopes[scope] = frame.entry.key
        return [_Frame(frame.entry, status="invalid") if frame.entry.key in duplicates else frame
                for frame in frames if frame.entry.key in selected]

    def _team_frame(self, team_key):
        if not _key(team_key):
            raise ValueError("Unknown managed team.")
        return self._frames(team_key)[0]

    def _http_review_material(self, team_key, proposal_id):
        """Return private action inputs. The caller must not serialize this object."""
        from .policy import check_action
        try:
            if self.demo or not _key(proposal_id):
                raise ValueError()
            current = self._team_frame(team_key)
            if current.status != "ready" or current.entry.provider != "espn":
                raise ValueError()
            frame = self._load(current.entry, proposal_id)
            row, snapshot, config = frame.exact_proposal, frame.snapshot, frame.config
            if (row is None or snapshot is None or config is None or snapshot.source.synthetic
                    or snapshot.source.provider != "espn_http" or snapshot.phase != "season"
                    or snapshot.source.http is None or not snapshot.source.locks_verified
                    or row["status"] != "pending" or row["week"] != snapshot.week
                    or (row["revision"], row["config_revision"]) != (frame.revision, frame.config_revision)
                    or row["action"] not in ACTIONS or config.automation.mode_for(row["action"]) != "review"):
                raise ValueError()
            decision = _json(row["decision"])
            if not isinstance(decision, dict) or decision.get("mode") != "review":
                raise ValueError()
            checked = check_action(snapshot, config, row["action"], decision["payload"], execution_scope="espn_http")
            if checked["payload"] != decision["payload"] or checked["mode"] != "review":
                raise ValueError()
            proposal = self._proposal(frame, row, row["action"], "http")
            if proposal is None:
                raise ValueError()
            proposal.update(payload=checked["payload"], league_id=snapshot.league_id, team_id=snapshot.team_id,
                            season=snapshot.season, week=snapshot.week)
            snapshot_input = snapshot.model_dump(mode="json")
            # A timestamp-only refresh preserves the service's proposal revision.
            # check_action still checks both timestamps on every review and submission.
            snapshot_input["source"].pop("observed_at", None)
            snapshot_input["source"].pop("projections_observed_at", None)
            fingerprint = hashlib.sha256(json.dumps({"team_key": team_key, "proposal": proposal,
                "decision": decision, "snapshot": snapshot_input, "config": config.model_dump(mode="json")},
                sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            return {"proposal": proposal, "snapshot": snapshot, "config": config,
                    "data_dir": frame.entry.path.parent, "fingerprint": fingerprint}
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            raise ValueError("This proposal is not available for review.") from None

    def _read_proposals(self, db, frame):
        snapshot = frame.snapshot
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 100")}
        collected = []
        for table, (action, source) in _TABLES.items():
            if table not in tables:
                continue
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            if table == "proposals":
                # This legacy table has no context column. Only current revisions have a proven scope.
                where, args = "revision=? AND config_revision=?", [frame.revision, frame.config_revision]
                if not snapshot.source.synthetic:
                    source = "local"
                pending = "result IS NULL"
            else:
                where, args = "league_id=? AND team_id=? AND season=?", list((snapshot.league_id, snapshot.team_id, snapshot.season))
                pending = "status IN ('pending','awaiting_verification','pending_waiver')"
            count = db.execute(f"SELECT COUNT(*), SUM(CASE WHEN {pending} THEN 1 ELSE 0 END) FROM {table} WHERE {where}", args).fetchone()
            frame.proposal_count += count[0]
            frame.pending_count += count[1] or 0
            names = [name for name in ("id", "action", "revision", "config_revision", "status", "created_at", "authorized_at", "week") if name in columns]
            fields = ", ".join(names)
            for name in ("payload", "decision", "result"):
                if name in columns:
                    fields += f", CASE WHEN length(CAST({name} AS BLOB)) <= {MAX_JSON_BYTES} THEN {name} END AS {name}"
            rows = db.execute(f"SELECT {fields} FROM {table} WHERE {where} ORDER BY rowid DESC LIMIT ?", [*args, MAX_PROPOSALS_PER_TEAM]).fetchall()
            for row in rows:
                try:
                    proposal = self._proposal(frame, dict(row), action, source)
                    if proposal is not None:
                        collected.append(proposal)
                except (ValueError, TypeError, KeyError, RecursionError):
                    frame.truncated = True
        collected.sort(key=lambda item: (item["created_at"] or "", item["revision"], item["id"]), reverse=True)
        frame.proposals = collected[:MAX_PROPOSALS_PER_TEAM]
        frame.truncated = frame.truncated or frame.proposal_count > len(frame.proposals)

    @staticmethod
    def _proposal(frame, row, action, source):
        if not _key(row.get("id")):
            return None
        action = action or row.get("action")
        if action not in ACTIONS:
            return None
        decision = _json(row["decision"]) if "decision" in row else {}
        if not isinstance(decision, dict):
            return None
        payload = decision.get("payload", {}) if "decision" in row else _json(row["payload"])
        if not isinstance(payload, dict):
            return None
        result = _json(row["result"]) if row.get("result") else {}
        if not isinstance(result, dict):
            return None
        status = row.get("status") or result.get("status") or "prepared"
        if not _key(status):
            return None
        current = (row["revision"], row["config_revision"]) == (frame.revision, frame.config_revision)
        current = current and ("week" not in row or row["week"] == frame.snapshot.week)
        mode = decision.get("mode")
        if mode not in {"disabled", "advisory", "review", "automatic"}:
            mode = frame.config.automation.mode_for(action) if current else None
        players = {player.id: player.name for player in frame.snapshot.players}
        safe = {}
        for key in ("player_id", "drop_id", "repair_player_id"):
            if payload.get(key) in players:
                safe[key] = payload[key]
        if type(payload.get("bid")) is int and 0 <= payload["bid"] <= 1000000000:
            safe["bid"] = payload["bid"]
        lineup = payload.get("lineup")
        if isinstance(lineup, dict):
            safe["lineup"] = {slot: pid for slot, pid in lineup.items()
                              if slot in frame.snapshot.rules.lineup_slots() and (pid is None or pid in players)}
        if payload.get("repair_slot") in frame.snapshot.rules.lineup_slots():
            safe["repair_slot"] = payload["repair_slot"]
        summary = {"draft_pick": "Draft player", "set_lineup": "Change lineup", "waiver_claim": "Submit waiver claim",
                   "free_agent_add": "Add free agent", "drop_player": "Drop player", "move_to_ir": "Move player to IR",
                   "activate_from_ir": "Activate player from IR", "trade_offer": "Offer trade", "trade_accept": "Accept trade"}[action]
        if safe.get("player_id"):
            summary += ": " + players[safe["player_id"]]
        named_ids = {value for key, value in safe.items() if key in {"player_id", "drop_id", "repair_player_id"}}
        named_ids.update(pid for pid in safe.get("lineup", {}).values() if pid is not None)
        return {"id": row["id"], "team_key": frame.entry.key,
                "team_name": frame.entry.label or frame.snapshot.own_team().name,
                "action": action, "status": status, "mode": mode, "created_at": _stamp(row.get("created_at")),
                "authorized_at": _stamp(row.get("authorized_at")), "summary": summary, "payload": safe,
                "player_names": {pid: players[pid] for pid in sorted(named_ids)},
                "revision": row["revision"], "config_revision": row["config_revision"], "is_current": current,
                "source": source, "scope": {"synthetic": "synthetic_demo_only", "local": "local_preparation",
                                              "http": "espn_http", "browser": "host_browser"}[source],
                "synthetic": source == "synthetic"}

    def _summary(self, frame):
        entry, snapshot, config = frame.entry, frame.snapshot, frame.config
        league_id = snapshot.league_id if snapshot is not None else entry.context[0] if entry.context else None
        season = snapshot.season if snapshot is not None else entry.context[2] if entry.context else None
        league_key = None
        if league_id is not None and season is not None and frame.status != "unsupported":
            identity = json.dumps([entry.sport, entry.provider, league_id, season], separators=(",", ":"))
            league_key = "league-" + hashlib.sha256(identity.encode()).hexdigest()[:20]
        league_name = entry.league_name or (f"League {league_id}" if league_id is not None else "Managed league")
        summary = {"team_key": entry.key, "name": entry.label or entry.key, "league_name": league_name, "league_key": league_key,
                   "sport": entry.sport, "provider": entry.provider,
                   "season": entry.context[2] if entry.context else None, "week": None, "phase": None,
                   "data_status": frame.status, "observed_at": None, "age_seconds": None,
                   "source_complete": False, "locks_verified": False, "roster_count": 0,
                   "pending_count": frame.pending_count, "proposal_count": frame.proposal_count,
                   "automation_mode": None, "paused": None, "demo": self.demo, "synthetic": False,
                   "source_provider": None, "missing_projection_count": 0}
        if snapshot is None:
            return summary
        age = snapshot.age_seconds()
        limit = config.limits.max_draft_age_seconds if snapshot.phase == "draft" else config.limits.max_season_age_seconds
        data_status = "stale" if age > limit else "ready" if snapshot.source.complete else "invalid"
        own = snapshot.own_team()
        owned = set(own.roster_ids + own.reserve_ids)
        summary.update(name=entry.label or own.name, season=snapshot.season, week=snapshot.week, phase=snapshot.phase,
                       data_status=data_status, observed_at=snapshot.source.observed_at.isoformat(), age_seconds=round(age, 3),
                       source_complete=snapshot.source.complete, locks_verified=snapshot.source.locks_verified,
                       roster_count=len(owned), automation_mode=config.automation.preset, paused=config.automation.paused,
                       synthetic=snapshot.source.synthetic, source_provider=snapshot.source.provider,
                       missing_projection_count=sum(player.weekly_projection is None for player in snapshot.players if player.id in owned))
        return summary

    def overview(self, sport=None, provider=None):
        for value in (sport, provider):
            if value is not None and not _key(value):
                raise ValueError("Invalid portfolio filter.")
        teams = [self._summary(frame) for frame in self._frames()
                 if (sport is None or frame.entry.sport == sport) and (provider is None or frame.entry.provider == provider)]
        return {"schema_version": 1, "read_only": True, "generated_at": _now().isoformat(),
                "source_mode": "demo" if self.demo else "local", "demo": self.demo,
                "configuration_required": not bool(self.entries),
                "supported_sports": ["football"], "teams": teams,
                "summary": {"total_teams": len(teams), "ready_teams": sum(t["data_status"] == "ready" for t in teams),
                            "attention_teams": sum(t["data_status"] != "ready" or not t["locks_verified"] or t["pending_count"] > 0
                                                   or t["missing_projection_count"] > 0 or t["paused"] is True for t in teams),
                            "pending_proposals": sum(t["pending_count"] for t in teams)}}

    @staticmethod
    def _players(frame, owned_only):
        if frame.snapshot is None:
            return []
        own = frame.snapshot.own_team()
        owned, reserve = set(own.roster_ids + own.reserve_ids), set(own.reserve_ids)
        league_owned = {pid for team in frame.snapshot.teams for pid in team.roster_ids + team.reserve_ids}
        slots = {pid: slot for slot, pid in own.lineup.items() if pid is not None}
        protected = set(frame.config.limits.protected_ids)
        return [{"id": player.id, "name": player.name, "position": player.position, "nfl_team": player.team,
                 "slot": slots.get(player.id, "IR" if player.id in reserve else "BENCH" if player.id in owned else None),
                 "weekly_projection": player.weekly_projection, "availability": player.availability, "locked": player.locked,
                 "owned": player.id in owned, "protected": player.id in protected,
                 "roster_status": "managed_team" if player.id in owned else "opponent" if player.id in league_owned else "free_agent",
                 "team_key": frame.entry.key, "team_name": frame.entry.label or own.name,
                 "synthetic": frame.snapshot.source.synthetic}
                for player in frame.snapshot.players if not owned_only or player.id in owned]

    def team(self, team_key):
        frame = self._team_frame(team_key)
        config, snapshot = frame.config, frame.snapshot
        return {"team": self._summary(frame), "roster": self._players(frame, True), "read_only": True, "demo": self.demo,
                "rules": snapshot.rules.model_dump(mode="json") if snapshot else None,
                "budget": snapshot.budget.model_dump(mode="json") if snapshot and snapshot.budget else None,
                "policy": None if config is None else {"actions": dict(config.automation.actions),
                    "effective_modes": {action: config.automation.mode_for(action) for action in ACTIONS},
                    "strategy": config.strategy.model_dump(mode="json"), "paused": config.automation.paused,
                    "limits": config.limits.model_dump(mode="json")}}

    def analysis(self, team_key):
        frame = self._team_frame(team_key)
        summary = self._summary(frame)
        result = {"status": "unavailable", "errors": ["A valid season snapshot is required."], "warnings": [],
                  "lineup": {}, "projected_points": None, "current_points": None, "improvement": None}
        if frame.snapshot is not None and frame.snapshot.phase == "season":
            result = recommend_lineup(frame.snapshot, frame.config)
        elif frame.snapshot is not None:
            result["errors"] = ["Draft analysis remains available through the draft MCP tools."]
        invalid_numbers = []
        def finite(value):
            if isinstance(value, float) and not math.isfinite(value):
                invalid_numbers.append(True)
                return None
            if isinstance(value, dict):
                return {key: finite(item) for key, item in value.items()}
            if isinstance(value, list):
                return [finite(item) for item in value]
            return value
        result = finite(result)
        if invalid_numbers:
            result.update(status="incomplete", comparison_complete=False, projection_complete=False)
            result.setdefault("warnings", []).append("Some calculations exceeded numeric limits.")
        return {**result, "team_key": frame.entry.key, "generated_at": _now().isoformat(),
                "data_status": summary["data_status"], "source_age_seconds": summary["age_seconds"],
                "read_only": True, "demo": self.demo}

    @staticmethod
    def _page(limit, offset):
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or not 0 <= offset <= 100000:
            raise ValueError("Use a limit from 1 to 200 and an offset from 0 to 100000.")

    def players(self, team_key=None, query="", position=None, rostered_only=True, limit=100, offset=0):
        self._page(limit, offset)
        if not isinstance(query, str) or len(query) > 160 or type(rostered_only) is not bool or (position is not None and position not in POSITIONS):
            raise ValueError("Invalid player filter.")
        found, total = [], 0
        query = query.casefold().strip()
        for frame in self._frames(team_key):
            for player in self._players(frame, rostered_only):
                if (position is None or player["position"] == position) and (not query or query in player["name"].casefold() or query in player["nfl_team"].casefold()):
                    if offset <= total < offset + limit:
                        found.append(player)
                    total += 1
        return {"players": found, "total": total, "limit": limit, "offset": offset,
                "read_only": True, "demo": self.demo}

    def proposals(self, team_key=None, status=None, limit=50, offset=0):
        self._page(limit, offset)
        if status is not None and not _key(status):
            raise ValueError("Invalid proposal filter.")
        frames = self._frames(team_key)
        found = [proposal for frame in frames for proposal in frame.proposals if status is None or proposal["status"] == status]
        found.sort(key=lambda item: (item["created_at"] or "", item["revision"], item["team_key"], item["id"]), reverse=True)
        return {"proposals": found[offset:offset + limit], "total": len(found), "limit": limit, "offset": offset,
                "truncated": any(frame.truncated for frame in frames), "total_scope": "loaded_records",
                "read_only": True, "demo": self.demo}
