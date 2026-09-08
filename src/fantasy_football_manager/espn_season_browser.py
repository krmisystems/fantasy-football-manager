"""Read weekly ESPN state and submit a verified lineup exchange through Chrome."""

from datetime import datetime, timezone
import re
from urllib.parse import urlsplit

from .espn_browser import ESPNBrowser, _visible
from . import espn_season_data
from .policy import require


LABELS = {"QB": "Quarterback", "RB": "Running Back", "WR": "Wide Receiver",
          "TE": "Tight End", "FLEX": "Flex", "DST": "Team Defense/Special Teams", "K": "Place Kicker"}


class ESPNSeasonBrowser(ESPNBrowser):
    page_path = "team"

    def __init__(self, data_dir, week=1):
        super().__init__(data_dir)
        require(type(week) is int and 1 <= week <= 18, "Week must be an integer from 1 through 18.")
        self.week = week
        self._player_ownership_key = None

    async def connect(self, *args, **kwargs):
        result = await super().connect(*args, **kwargs)
        if result["ready"]:
            league, team, season = self._scope
            await self._page.goto(f"https://fantasy.espn.com/football/team?leagueId={league}&teamId={team}"
                                  f"&seasonId={season}&scoringPeriodId={self.week}",
                                  wait_until="domcontentloaded", timeout=30000)
            try:
                await self._page.get_by_role("button", name="Quick Lineup", exact=True).wait_for(state="visible", timeout=15000)
                await self._verify_scope()
                await self._verify_week()
            except Exception as exc:
                self._status.update(ready=False, status="awaiting_team_page", error=str(exc))
                result = self.status()
        return {**result, "phase": "season", "week": self.week}

    async def _verify_week(self):
        cells = []
        for role in ("columnheader", "cell"):
            cells.extend(await _visible(self._page.get_by_role(role, name=re.compile(r"^NFL\s+WEEK\s+\d+$", re.I))))
        weeks = {int(re.search(r"\d+", await cell.inner_text()).group()) for cell in cells}
        require(weeks == {self.week}, "The visible lineup week does not match the connected week.")

    async def _read_json(self, url, headers=None):
        league, _, season = self._scope
        allowed = {espn_season_data.season_read_url(league, season, self.week),
                   espn_season_data.season_player_read_url(league, season, self.week)}
        require(url in allowed and urlsplit(url).hostname == "lm-api-reads.fantasy.espn.com",
                "The ESPN season read is outside the connected league scope.")
        response = await self._context.request.get(url, headers=headers or {}, timeout=15000, max_redirects=0)
        try:
            require(response.ok, f"ESPN season read failed with HTTP {response.status}. Sign in to the dedicated browser.")
            return await response.json()
        finally:
            await response.dispose()

    async def _observe(self, previous=None):
        selected = await self._verify_scope()
        await self._verify_week()
        league, team, season = self._scope
        payload = await self._read_json(espn_season_data.season_read_url(league, season, self.week))
        ownership_key = tuple(sorted((str(team["id"]), tuple(sorted(str(entry["playerId"])
            for entry in team["roster"]["entries"]))) for team in payload["teams"]))
        now = datetime.now(timezone.utc)
        if (self._players_payload is None or self._projections_at is None
                or ownership_key != self._player_ownership_key or (now - self._projections_at).total_seconds() >= 300):
            response_url = espn_season_data.season_player_read_url(league, season, self.week)
            self._players_payload = await self._read_json(
                response_url, espn_season_data.season_player_read_headers(season))
            self._projections_at = datetime.now(timezone.utc)
            self._player_response_url = response_url
            self._player_ownership_key = ownership_key
        options = dict(team_id=team, week=self.week, visible_text=await self._page.locator("body").inner_text(),
                       page_url=self._page.url, observed_at=datetime.now(timezone.utc),
                       observed_team_id=selected, observed_week=self.week, projections_observed_at=self._projections_at,
                       player_response_url=self._player_response_url)
        snapshot = espn_season_data.normalize_espn_season(payload, self._players_payload, **options)
        players = {p.id: p for p in snapshot.players}
        locks, matched_controls = {}, 0
        all_controls = await _visible(self._page.get_by_role("button", name=re.compile(r"^Select .+ to move$")))
        for pid in snapshot.own_team().roster_ids + snapshot.own_team().reserve_ids:
            player = players[pid]
            if sum(p.name == player.name for p in snapshot.players) != 1:
                continue
            buttons = await _visible(self._page.get_by_role("button", name=f"Select {player.name} to move", exact=True))
            matched_controls += len(buttons)
            if len(buttons) == 1:
                locks[pid] = not await buttons[0].is_enabled()
        require(matched_controls == len(all_controls),
                "The visible move controls contain a player outside the complete selected-team roster.")
        await self._verify_scope()
        await self._verify_week()
        options["observed_at"] = datetime.now(timezone.utc)
        snapshot = espn_season_data.normalize_espn_season(payload, self._players_payload, player_locks=locks, **options)
        self._snapshot = snapshot
        self._status.update(ready=True, status="observed", error=None, phase="season", week=self.week,
                            observed_at=snapshot.source.observed_at.isoformat(), locks_verified=snapshot.source.locks_verified)
        return snapshot

    async def _lineup_preflight(self, proposal):
        snapshot = await self._observe()
        require((proposal.get("league_id"), proposal.get("team_id"), proposal.get("season"), proposal.get("week")) ==
                (*self._scope, self.week), "The lineup proposal belongs to another league context or week.")
        players = {p.id: p for p in snapshot.players}
        for key, name_key in (("player_id", "player_name"), ("outgoing_player_id", "outgoing_player_name")):
            pid = proposal.get(key)
            require(pid in snapshot.own_team().roster_ids and players[pid].name == proposal.get(name_key),
                    "The lineup player identity changed.")
            require(sum(p.name == players[pid].name for p in snapshot.players) == 1, "The lineup player name is ambiguous.")
            require(not players[pid].locked, "A lineup player is locked.")
        source, destination = proposal["source_slot"], proposal["destination_slot"]
        current = snapshot.own_team().lineup
        def group_occupants(slot):
            require(slot in current, "The lineup proposal uses an unknown starter slot.")
            position = re.sub(r"\d+$", "", slot)
            return {pid for key, pid in current.items() if re.sub(r"\d+$", "", key) == position}
        # ESPN can change the order of equal-position roster entries. Bind the
        # move to its exact occupants. FLEX is a separate positional group.
        require(proposal["outgoing_player_id"] in group_occupants(destination), "The destination lineup group changed.")
        require((proposal["player_id"] not in current.values()) if source == "BN" else proposal["player_id"] in group_occupants(source),
                "The source lineup slot changed.")
        controls = await _visible(self._page.get_by_role("button", name=f"Select {proposal['player_name']} to move", exact=True))
        require(len(controls) == 1 and await controls[0].is_enabled(), "The exact lineup move control is unavailable.")
        return snapshot, controls[0]

    async def preflight_lineup(self, proposal):
        async with self._lock:
            snapshot, _ = await self._lineup_preflight(proposal)
            return {"ready": True, "observed_at": snapshot.source.observed_at.isoformat()}

    async def _cancel_selection(self, name):
        controls = await _visible(self._page.get_by_role("button", name=f"Cancel Move of {name}", exact=True))
        if controls:
            await controls[0].click(timeout=3000)

    async def submit_lineup(self, permit):
        async with self._lock:
            require(isinstance(permit, dict) and permit.get("should_click") is True and permit.get("proposal_id"),
                    "A one-click lineup permit is required.")
            require(self.permit_validator is not None, "The lineup permit validator is missing.")
            pid = permit["proposal_id"]
            require(pid not in self._attempted, "This browser already attempted the lineup submission. Reconcile the result.")
            clicked = selected = False
            try:
                snapshot, select = await self._lineup_preflight(permit)
                await select.click(timeout=3000)
                selected = True
                prefix = re.sub(r"\d+$", "", permit["destination_slot"])
                require(prefix in LABELS, "The lineup destination is unsupported.")
                label = f"Confirm move of {permit['outgoing_player_name']} to {LABELS[prefix]}"
                controls = await _visible(self._page.get_by_role("button", name=label, exact=True))
                require(len(controls) == 1 and await controls[0].is_enabled(), "The exact lineup confirmation control is unavailable.")
                await self._verify_scope()
                await self._verify_week()
                decision = self.permit_validator(permit, snapshot)
                require(decision is True or (isinstance(decision, dict) and decision.get("should_click") is True),
                        "The current permit validator did not authorize lineup confirmation.")
                self._attempted.add(pid)
                clicked = True
                await controls[0].click(timeout=3000)
                result = {"status": "awaiting_verification", "proposal_id": pid, "clicked": True, "retry_allowed": False}
                result["snapshot"] = (await self._observe()).model_dump(mode="json")
                return result
            except Exception as exc:
                if selected and not clicked:
                    try:
                        await self._cancel_selection(permit["player_name"])
                    except Exception:
                        pass
                return {"status": "awaiting_verification", "proposal_id": pid, "clicked": clicked,
                        "uncertain": True, "retry_allowed": False, "error": str(exc)}
