"""ESPN observation, draft execution, and continuous automation service."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from .browser_draft import BrowserDraft
from .browser_lineup import BrowserLineup, lineup_equivalent, next_lineup_swap
from .draft import recommend_draft
from .legacy_engine import merge_batches
from .models import LeagueSnapshot
from .policy import check_action, require
from .season import recommend_lineup
from .store import Manager


class ESPNService:
    def __init__(self, data_dir=None, browser=None):
        self.manager = Manager(data_dir)
        self.draft = BrowserDraft(self.manager)
        self.lineup = BrowserLineup(self.manager)
        self._injected_browser = browser is not None
        self.phase = "draft"
        if browser is None:
            from .espn_browser import ESPNBrowser
            browser = ESPNBrowser(self.manager.data_dir)
        self.browser = browser
        self.browser.permit_validator = self._validate_permit
        self.task = None
        self.stop_event = asyncio.Event()
        self.operation = asyncio.Lock()
        self.latest = None
        self.seed = 1
        self.local_status = "disconnected"
        self._last_status = None
        with self.manager.transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS espn_runtime(id INTEGER PRIMARY KEY CHECK(id=1),connection TEXT,status TEXT)")
            db.execute("INSERT OR IGNORE INTO espn_runtime VALUES(1,NULL,NULL)")
            connection = db.execute("SELECT connection FROM espn_runtime WHERE id=1").fetchone()["connection"]
        snapshot = self.manager.state()[0]
        self.phase = json.loads(connection).get("phase", "draft") if connection else (snapshot.phase if snapshot else "draft")

    def _save_status(self, status, **details):
        self.local_status = status
        value = {"status": status, "pid": os.getpid(), "observed_at": datetime.now(timezone.utc).isoformat(), **details}
        self._last_status = value
        with self.manager.transaction() as db:
            previous = db.execute("SELECT status FROM espn_runtime WHERE id=1").fetchone()["status"]
            previous = json.loads(previous) if previous else {}
            if status in {"connection_failed", "disconnected"} and previous.get("pid") not in {None, os.getpid()}:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous["observed_at"])).total_seconds()
                if age <= 90 and previous.get("status") not in {"disconnected", "startup_failed", "draft_complete"}:
                    return value
            db.execute("UPDATE espn_runtime SET status=? WHERE id=1", (json.dumps(value),))
        return value

    def saved_connection(self):
        with self.manager.transaction() as db:
            row = db.execute("SELECT connection FROM espn_runtime WHERE id=1").fetchone()
        require(row["connection"] is not None, "Connect the ESPN browser before starting a standalone worker.")
        return json.loads(row["connection"])

    def status(self):
        with self.manager.transaction() as db:
            row = db.execute("SELECT status FROM espn_runtime WHERE id=1").fetchone()
        shared = json.loads(row["status"]) if row["status"] else None
        if shared:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(shared["observed_at"])).total_seconds()
            shared = {**shared, "heartbeat_age_seconds": round(max(0, age), 2), "heartbeat_stale": age > 90}
        snapshot, config, revision, config_revision = self.manager.state()
        current = (self.latest is not None and snapshot is not None and
                   (self.latest["revision"], self.latest["config_revision"]) == (revision, config_revision) and
                   snapshot.age_seconds() <= (config.limits.max_season_age_seconds if snapshot.phase == "season" else config.limits.max_draft_age_seconds)
                   and not config.automation.paused)
        review = self._review_proposals()
        return {"browser": self.browser.status(), "local_status": self.local_status,
                "automation_running": self.task is not None and not self.task.done(),
                "worker": shared, "paused": config.automation.paused,
                "draft_mode": config.automation.mode_for("draft_pick"), "revision": revision,
                "config_revision": config_revision, "pending": self._controller(snapshot).pending(),
                "review_proposals": review, "awaiting_review": any(item["current"] for item in review),
                "latest_recommendations": self.latest if current else None,
                "live_actions": ["draft_pick", "set_lineup"], "season_actions": ["set_lineup"],
                "unsupported_live_actions": ["waiver_claim", "free_agent_add", "drop_player", "trade_offer", "trade_accept"],
                "phase": self.phase, "lineup_mode": config.automation.mode_for("set_lineup"),
                "snapshot_age_seconds": snapshot.age_seconds() if snapshot else None}

    async def connect(self, league_id, team_id, season, cdp_url=None, headless=False, phase="draft", week=1):
        require(phase in {"draft", "season"}, "Phase must be draft or season.")
        require(type(week) is int and 1 <= week <= 18, "Week must be an integer from 1 through 18.")
        require(self.task is None or self.task.done(), "Stop automation before changing its browser connection.")
        async with self.operation:
            with self.manager.transaction() as db:
                claims = []
                for table in ("browser_proposals", "browser_lineup_proposals"):
                    claims.extend(db.execute(f"SELECT baseline FROM {table} WHERE status='awaiting_verification'").fetchall())
            for claim in claims:
                baseline = LeagueSnapshot.model_validate_json(claim["baseline"])
                require((str(league_id), str(team_id), season, phase, week) ==
                        (baseline.league_id, baseline.team_id, baseline.season, baseline.phase, baseline.week),
                        "An action awaits verification. Reconnect its exact league, team, season, phase, and week before changing the connection.")
            if not self._injected_browser:
                await self.browser.close()
                if phase == "season":
                    from .espn_season_browser import ESPNSeasonBrowser
                    self.browser = ESPNSeasonBrowser(self.manager.data_dir, week=week)
                else:
                    from .espn_browser import ESPNBrowser
                    self.browser = ESPNBrowser(self.manager.data_dir)
                self.browser.permit_validator = self._validate_permit
            elif phase == "season" and hasattr(self.browser, "week"):
                self.browser.week = week
            self.phase = phase
            self.latest = None
            try:
                result = await self.browser.connect(league_id=league_id, team_id=team_id, season=season,
                                                    cdp_url=cdp_url, headless=headless)
            except Exception as exc:
                self.latest = None
                self._save_status("connection_failed", error=str(exc))
                raise
            connection = {"league_id": str(league_id), "team_id": str(team_id), "season": season,
                          "cdp_url": cdp_url, "headless": headless, "phase": phase, "week": week}
            with self.manager.transaction() as db:
                db.execute("UPDATE espn_runtime SET connection=? WHERE id=1", (json.dumps(connection),))
            self._save_status("connected", ready=result.get("ready", False))
            return {**result, "phase": phase, "week": week}

    def _controller(self, snapshot=None):
        if snapshot is None:
            snapshot = self.manager.state()[0]
        return self.lineup if snapshot is not None and snapshot.phase == "season" else self.draft

    @staticmethod
    def _decision_state(snapshot):
        """Exclude observation times, but preserve every rule and decision input."""
        value = snapshot.model_dump(mode="json")
        value["source"].pop("observed_at", None)
        value["source"].pop("projections_observed_at", None)
        value["players"].sort(key=lambda player: player["id"])
        value["teams"].sort(key=lambda team: team["id"])
        return value

    def _accept_observation(self, observed, expected_revision):
        """Refresh evidence without invalidating consent when decision inputs match."""
        observed = LeagueSnapshot.model_validate(observed)
        with self.manager.transaction() as db:
            old, _, revision, config_revision = self.manager._state(db)
            require(revision == expected_revision, "State changed while the browser observation was in progress.")
            if old is not None and self._decision_state(old) == self._decision_state(observed):
                require(observed.source.observed_at >= old.source.observed_at, "An older observation cannot refresh current state.")
                old_projection, new_projection = old.source.projections_observed_at, observed.source.projections_observed_at
                require(old_projection is None or (new_projection is not None and new_projection >= old_projection),
                        "An older projection response cannot refresh current state.")
                db.execute("UPDATE state SET snapshot=? WHERE id=1", (observed.model_dump_json(),))
                self.manager._audit(db, "observation_refreshed", {"revision": revision,
                                    "observed_at": observed.source.observed_at.isoformat()})
                return {"status": "refreshed", "revision": revision, "config_revision": config_revision,
                        "decision_inputs_changed": False}
        result = self.manager.import_snapshot(observed.model_dump(mode="json"), expected_revision)
        return {**result, "decision_inputs_changed": True}

    def _review_proposals(self):
        with self.manager.transaction() as db:
            snapshot, _, revision, config_revision = self.manager._state(db)
            if snapshot is None:
                return []
            season = snapshot.phase == "season"
            table = "browser_lineup_proposals" if season else "browser_proposals"
            week_clause = " AND week=?" if season else ""
            values = (snapshot.league_id, snapshot.team_id, snapshot.season) + ((snapshot.week,) if season else ())
            rows = db.execute(f"""SELECT id,revision,config_revision,decision FROM {table}
                WHERE league_id=? AND team_id=? AND season=? AND status='pending'
                {week_clause} ORDER BY rowid DESC LIMIT 20""", values).fetchall()
        controller = self._controller(snapshot)
        return [{**controller.get(row["id"]), "current": (row["revision"], row["config_revision"]) == (revision, config_revision)}
                for row in rows if json.loads(row["decision"])["requires_confirmation"]]

    async def _sync(self):
        old, _, revision, _ = self.manager.state()
        observed = await self.browser.observe(previous=old)
        controller = self._controller(observed)
        pending = controller.pending()
        if pending:
            result = controller.reconcile(pending[0]["proposal_id"], observed.model_dump(mode="json"))
            if result["status"] != "awaiting_verification":
                return {"status": "synced", "reconciliation": result, "revision": result["revision"]}
        result = self._accept_observation(observed, revision)
        return {**result, "status": "synced", "pending_verification": bool(pending)}

    async def sync(self):
        async with self.operation:
            return await self._sync()

    def _validate_permit(self, permit, fresh_snapshot=None):
        if permit.get("action") == "set_lineup":
            return self.lineup.validate_permit(permit, fresh_snapshot)
        current = self.draft.get(permit["proposal_id"])
        require(current["status"] == "awaiting_verification", "This click claim is no longer pending verification.")
        snapshot, config, revision, config_revision = self.manager.require_state()
        require((revision, config_revision) == (permit["revision"], permit["config_revision"]),
                "State or config changed before the browser click.")
        require((snapshot.league_id, snapshot.team_id, snapshot.season) ==
                (permit["league_id"], permit["team_id"], permit["season"]), "The active league context changed.")
        require(all(current.get(key) == permit.get(key) for key in (
            "league_id", "team_id", "season", "player_id", "player_name", "pick_no", "payload",
            "revision", "config_revision", "authorized_at")), "The click permit changed.")
        evidence = snapshot
        if fresh_snapshot is not None:
            fresh_snapshot = LeagueSnapshot.model_validate(fresh_snapshot)
            require((fresh_snapshot.league_id, fresh_snapshot.team_id, fresh_snapshot.season) ==
                    (snapshot.league_id, snapshot.team_id, snapshot.season), "The fresh browser observation belongs to another league context.")
            require(fresh_snapshot.picks == snapshot.picks and fresh_snapshot.rules == snapshot.rules,
                    "The fresh browser history or league rules changed before submission.")
            require({team.id: team.slot for team in fresh_snapshot.teams} == {team.id: team.slot for team in snapshot.teams},
                    "The fresh browser team identities changed before submission.")
            selected = lambda state: next((player for player in state.players if player.id == permit["player_id"]), None)
            old_player, new_player = selected(snapshot), selected(fresh_snapshot)
            require(old_player is not None and new_player is not None and
                    (old_player.name, old_player.position, old_player.eligible_positions) ==
                    (new_player.name, new_player.position, new_player.eligible_positions),
                    "The selected player identity or eligibility changed before submission.")
            require(fresh_snapshot.source.observed_at >= snapshot.source.observed_at,
                    "The browser observation predates the stored state.")
            require(fresh_snapshot.source.observed_at >= datetime.fromisoformat(permit["authorized_at"]),
                    "The browser observation predates click authorization.")
            evidence = fresh_snapshot
        check_action(evidence, config, "draft_pick", permit["payload"], execution_scope="host_browser")
        return True

    async def prepare_pick(self, player_id):
        async with self.operation:
            await self._sync()
            return self.draft.prepare(player_id)

    async def _submit(self, proposal_id, confirmation=False, action="draft_pick"):
        controller = self.lineup if action == "set_lineup" else self.draft
        proposal = controller.get(proposal_id)
        if proposal["status"] != "pending":
            return {**proposal, "should_click": False}
        # Timestamp-only refreshes preserve the exact proposal revision.
        await self._sync()
        preflight = self.browser.preflight_lineup if action == "set_lineup" else self.browser.preflight_pick
        submit = self.browser.submit_lineup if action == "set_lineup" else self.browser.submit_pick
        await preflight(proposal)
        snapshot, config, _, _ = self.manager.require_state()
        age_limit = config.limits.max_season_age_seconds if action == "set_lineup" else config.limits.max_draft_age_seconds
        if snapshot.age_seconds() > age_limit:
            await self._sync()
        permit = controller.authorize(proposal_id, confirmation)
        if not permit["should_click"]:
            return permit
        try:
            result = await submit(permit)
            if result.get("snapshot") is not None:
                reconciliation = controller.reconcile(proposal_id, result["snapshot"])
                return {**reconciliation, "browser": {k: v for k, v in result.items() if k != "snapshot"}}
            return {**controller.get(proposal_id), "browser": result, "retry_allowed": False}
        except Exception as exc:
            # Once claimed, no exception permits an automatic second click.
            self._save_status("awaiting_verification", proposal_id=proposal_id, error=str(exc))
            return {**controller.get(proposal_id), "error": str(exc), "retry_allowed": False}

    async def submit_pick(self, proposal_id, confirmation=False):
        async with self.operation:
            return await self._submit(proposal_id, confirmation)

    async def reconcile_pick(self, proposal_id):
        async with self.operation:
            old, _, _, _ = self.manager.require_state()
            observed = await self.browser.observe(previous=old)
            return self.draft.reconcile(proposal_id, observed.model_dump(mode="json"))

    async def prepare_lineup(self, lineup):
        async with self.operation:
            await self._sync()
            return self.lineup.prepare(lineup)

    async def submit_lineup(self, proposal_id, confirmation=False):
        async with self.operation:
            return await self._submit(proposal_id, confirmation, action="set_lineup")

    async def reconcile_lineup(self, proposal_id):
        async with self.operation:
            old, _, _, _ = self.manager.require_state()
            observed = await self.browser.observe(previous=old)
            return self.lineup.reconcile(proposal_id, observed.model_dump(mode="json"))

    async def _season_step(self, snapshot, config, revision, config_revision):
        result = await asyncio.to_thread(recommend_lineup, snapshot, config)
        self.latest = {"revision": revision, "config_revision": config_revision, "phase": "season", "result": result}
        review = self._review_proposals()
        self._save_status("awaiting_review" if any(item["current"] for item in review) else "monitoring_lineup", week=snapshot.week)
        _, latest_config, latest_revision, latest_config_revision = self.manager.require_state()
        if (self.stop_event.is_set() or latest_config.automation.paused
                or (revision, config_revision) != (latest_revision, latest_config_revision)
                or config.automation.mode_for("set_lineup") != "automatic" or result.get("status") != "ok"):
            return
        candidate = next_lineup_swap(snapshot, latest_config, result["lineup"])
        if candidate is None:
            self._save_status("lineup_current" if lineup_equivalent(snapshot, snapshot.own_team().lineup, result["lineup"]) else "no_admissible_lineup_exchange", week=snapshot.week)
            return
        proposal = self.lineup.prepare(candidate)
        submitted = await self._submit(proposal["proposal_id"], action="set_lineup")
        self._save_status(submitted["status"], proposal_id=proposal["proposal_id"], week=snapshot.week)

    async def start(self, interval_seconds=2, trials=40):
        require(type(interval_seconds) in {int, float} and 1 <= interval_seconds <= 60,
                "Use an observation interval from 1 to 60 seconds.")
        _, config, _, _ = self.manager.state()
        require(type(trials) is int and 1 <= trials <= config.limits.batch_trials,
                "Trials must be positive and within the configured batch limit.")
        require(self.task is None or self.task.done(), "ESPN automation is already running.")
        require(self.browser.status().get("connected"), "Connect the ESPN browser first.")
        self.stop_event.clear()
        self.task = asyncio.create_task(self._run(interval_seconds, trials), name="espn-automation")
        self._save_status("starting")
        return self.status()

    async def _run(self, interval_seconds, trials):
        while not self.stop_event.is_set():
            try:
                async with self.operation:
                    _, config, _, _ = self.manager.state()
                    if config.automation.paused:
                        self._save_status("paused")
                    else:
                        await self._sync()
                        snapshot, config, revision, config_revision = self.manager.require_state()
                        if self._controller(snapshot).pending():
                            self._save_status("awaiting_verification")
                        elif snapshot.phase == "season":
                            await self._season_step(snapshot, config, revision, config_revision)
                        elif len(snapshot.own_team().roster_ids) >= snapshot.rules.rounds:
                            self._save_status("draft_complete")
                            return
                        else:
                            batch = await asyncio.to_thread(recommend_draft, snapshot, config,
                                                            min(trials, config.limits.batch_trials), self.seed)
                            self.seed += 1
                            if (self.latest is None or self.latest["config_revision"] != config_revision or
                                self.latest["result"].get("analysis_fingerprint") != batch.get("analysis_fingerprint")):
                                aggregate = batch
                            else:
                                aggregate = merge_batches(self.latest["result"], batch)
                            self.latest = {"revision": revision, "config_revision": config_revision, "result": aggregate}
                            review = self._review_proposals()
                            self._save_status("awaiting_review" if any(item["current"] for item in review) else "monitoring",
                                              trials=aggregate.get("trials", 0), current_pick=batch["current_pick"])
                            # No new action is selected after pause, stop, config, or state changes during calculation.
                            _, latest_config, latest_revision, latest_config_revision = self.manager.require_state()
                            if (not self.stop_event.is_set() and not latest_config.automation.paused and
                                (revision, config_revision) == (latest_revision, latest_config_revision) and
                                batch.get("my_next_pick") == batch.get("current_pick") and
                                aggregate.get("recommendations") and config.automation.mode_for("draft_pick") == "automatic"):
                                rejected = []
                                chosen = None
                                for candidate in aggregate["recommendations"]:
                                    try:
                                        check_action(snapshot, latest_config, "draft_pick", {"player_id": candidate["id"]}, execution_scope="host_browser")
                                    except ValueError as exc:
                                        rejected.append({"player_id": candidate["id"], "reason": str(exc)})
                                        continue
                                    chosen = candidate["id"]
                                    break
                                if chosen is None:
                                    self._save_status("no_admissible_candidate", rejected_candidates=rejected)
                                else:
                                    proposal = self.draft.prepare(chosen)
                                    result = await self._submit(proposal["proposal_id"])
                                    self._save_status(result["status"], proposal_id=proposal["proposal_id"], rejected_candidates=rejected)
            except Exception as exc:
                self.latest = None
                self._save_status("needs_attention", error=str(exc))
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass
        self._save_status("stopped")

    async def stop(self):
        self.stop_event.set()
        if self.task is not None and not self.task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self.task), timeout=5)
            except asyncio.TimeoutError:
                self._save_status("stopping")
        return self.status()

    async def close(self):
        await self.stop()
        if self.task is not None and not self.task.done():
            return {"status": "stopping", "message": "The current bounded browser operation must finish before disconnecting."}
        async with self.operation:
            await self.browser.close()
            previous = self._last_status or {}
            self._save_status("disconnected", previous_status=previous.get("status"), last_error=previous.get("error"))
        return {"status": "disconnected"}

    async def pause(self):
        """Pause new actions across every process that uses this data directory."""
        _, config, _, revision = self.manager.state()
        config.automation.paused = True
        self.manager.update_config(config.model_dump(mode="json"), revision)
        return await self.stop()

    async def start_standalone(self):
        self.saved_connection()
        closed = await self.close()
        require(closed["status"] == "disconnected", "Wait for the current operation before starting the standalone worker.")
        from filelock import FileLock, Timeout
        lease = FileLock(self.manager.data_dir / "espn-browser.lock")
        try:
            lease.acquire(timeout=0)
        except Timeout as exc:
            raise ValueError("Another manager process owns the ESPN browser. A second worker was not started.") from exc
        else:
            lease.release()
        log_path = self.manager.data_dir / "espn-worker.log"
        command = [sys.executable, "-m", "fantasy_football_manager.espn_mcp", "--worker", "--data-dir", str(self.manager.data_dir)]
        with log_path.open("ab") as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                       start_new_session=os.name != "nt")
        return await self._await_worker_start(process)

    async def _await_worker_start(self, process, timeout=10):
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            with self.manager.transaction() as db:
                raw = db.execute("SELECT status FROM espn_runtime WHERE id=1").fetchone()["status"]
            shared = json.loads(raw) if raw else {}
            exited = process.poll()
            if exited is not None:
                reason = (shared.get("error") or shared.get("last_error")) if shared.get("pid") == process.pid else None
                message = f"ESPN worker exited during startup with code {exited}." + (f" {reason}" if reason else " Check the local worker log.")
                self._save_status("startup_failed", worker_pid=process.pid, error=message)
                raise ValueError(message)
            if shared.get("pid") == process.pid and shared.get("status") in {
                "starting", "monitoring", "monitoring_lineup", "lineup_current", "no_admissible_lineup_exchange",
                "paused", "awaiting_review", "awaiting_verification", "draft_complete", "needs_attention"}:
                return {"status": shared["status"], "pid": process.pid, "startup_acknowledged": True,
                        "worker": shared, "lifetime": "independent_of_codex",
                        "control": "Set automation.paused=true in the manager config to stop new actions."}
            if asyncio.get_running_loop().time() >= deadline:
                return {"status": "startup_pending", "pid": process.pid, "startup_acknowledged": False,
                        "lifetime": "independent_of_codex", "message": "The process started, but browser startup is not yet verified."}
            await asyncio.sleep(.1)
