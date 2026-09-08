"""Observe ESPN through a scoped browser and submit one authorized draft click.

Uses Playwright's documented persistent-context, CDP, locator, and request APIs:
https://playwright.dev/python/docs/api/class-browsertype
https://playwright.dev/python/docs/api/class-locator
https://playwright.dev/python/docs/api/class-apirequestcontext
Live ESPN selector compatibility requires a connected draft-room check.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from . import espn_data
from .models import LeagueSnapshot

ESPN_HOST = "fantasy.espn.com"
API_HOST = "lm-api-reads.fantasy.espn.com"
CLOCK = re.compile(r"ON\s+THE\s+CLOCK\s*:\s*PICK\s+(\d+)", re.I)


def _identifier(value, label):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)):
        raise ValueError(f"{label} must be a positive numeric identifier.")
    return str(value)


def _loopback_url(value):
    try:
        parsed = urlsplit(value)
        local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        local = False
    if not local or parsed.scheme not in {"http", "https", "ws", "wss"} or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("CDP must use an explicit loopback HTTP or WebSocket URL without credentials.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("CDP URL has an invalid port.") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("CDP URL must include a local debugging port.")
    return parsed


def _cdp_websocket(value):
    """Validate discovery too, so a local HTTP endpoint cannot redirect the connection."""
    parsed = _loopback_url(value)
    if parsed.scheme in {"ws", "wss"}:
        return value
    if parsed.path not in {"", "/"} or parsed.query:
        raise ValueError("HTTP CDP URLs must identify the debugging server root.")

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(value.rstrip("/") + "/json/version", timeout=10) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("CDP discovery response is too large.")
    endpoint = json.loads(raw).get("webSocketDebuggerUrl")
    if not isinstance(endpoint, str) or _loopback_url(endpoint).scheme not in {"ws", "wss"}:
        raise ValueError("CDP discovery did not return a loopback WebSocket URL.")
    return endpoint


async def _start_playwright():
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ValueError("Install the browser dependencies before connecting to ESPN.") from exc
    return await async_playwright().start()


async def _visible(locator):
    return [item for item in await locator.all() if await item.is_visible()]


class ESPNBrowser:
    """One browser connection. The service must supply a current permit validator."""

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.permit_validator = None
        self._lock = asyncio.Lock()
        self._playwright = self._browser = self._context = self._page = self._lease = None
        self._managed = False
        self._scope = None
        self._players_payload = self._projections_at = self._snapshot = None
        self._attempted = set()
        self._status = {"connected": False, "ready": False, "status": "disconnected", "error": None}

    page_path = "draft"

    def status(self):
        return dict(self._status)

    def _url_matches(self, url, *, draft=False, require_team=False):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != ESPN_HOST or parsed.port not in {None, 443} or parsed.username or parsed.password:
            return False
        if draft and parsed.path.rstrip("/") != "/football/" + self.page_path:
            return False
        query = parse_qs(parsed.query)
        league, team, season = self._scope
        return (query.get("leagueId") == [league]
                and (query.get("teamId") == [team] if require_team else query.get("teamId", [team]) == [team])
                and query.get("seasonId", [str(season)]) == [str(season)])

    async def _verify_scope(self):
        if self._page is None or self._page.is_closed() or not self._url_matches(self._page.url, draft=True):
            raise ValueError("Open the exact connected ESPN league draft page.")
        links = await _visible(self._page.get_by_role("link", name="My Team", exact=True))
        if len(links) != 1:
            raise ValueError("A unique visible My Team link is required to verify the selected team.")
        href = await links[0].get_attribute("href")
        if not href or not self._url_matches(urljoin(self._page.url, href), require_team=True):
            raise ValueError("The visible My Team link does not match the connected league and team.")
        return self._scope[1]

    async def connect(self, league_id, team_id, season, cdp_url=None, headless=False):
        league, team = _identifier(league_id, "League ID"), _identifier(team_id, "Team ID")
        if type(season) is not int or not 2020 <= season <= 2100:
            raise ValueError("Season must be an integer from 2020 to 2100.")
        if type(headless) is not bool:
            raise ValueError("Headless must be true or false.")
        if cdp_url is not None:
            _loopback_url(cdp_url)
        async with self._lock:
            if self._playwright is not None:
                raise ValueError("Disconnect the current ESPN browser before connecting another scope.")
            from filelock import FileLock, Timeout
            self.data_dir.mkdir(parents=True, exist_ok=True)
            lease = FileLock(self.data_dir / "espn-browser.lock")
            try:
                lease.acquire(timeout=0)
            except Timeout as exc:
                raise ValueError("Another manager process owns this ESPN browser profile.") from exc
            self._lease = lease
            self._scope = (league, team, season)
            self._players_payload = self._projections_at = self._snapshot = None
            try:
                self._playwright = await _start_playwright()
                self._managed = cdp_url is None
                if cdp_url:
                    endpoint = await asyncio.to_thread(_cdp_websocket, cdp_url)
                    self._browser = await self._playwright.chromium.connect_over_cdp(endpoint, timeout=15000)
                    candidates = [(context, page) for context in self._browser.contexts for page in context.pages
                                  if not page.is_closed() and self._url_matches(page.url, draft=True)]
                    if len(candidates) != 1:
                        raise ValueError("CDP must contain exactly one draft tab for the requested league and team.")
                    self._context, self._page = candidates[0]
                else:
                    self._context = await self._playwright.chromium.launch_persistent_context(
                        self.data_dir / "espn-browser-profile", channel="chrome", headless=headless,
                        accept_downloads=False, timeout=30000)
                    candidates = [page for page in self._context.pages if not page.is_closed() and self._url_matches(page.url, draft=True)]
                    if len(candidates) > 1:
                        raise ValueError("Close duplicate draft tabs in the dedicated ESPN browser profile.")
                    self._page = candidates[0] if candidates else await self._context.new_page()
                    if not candidates:
                        url = f"https://{ESPN_HOST}/football/{self.page_path}?leagueId={league}&teamId={team}&seasonId={season}"
                        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self._status = {"connected": True, "ready": False, "status": "awaiting_login_or_draft",
                                "mode": "managed_profile" if self._managed else "loopback_cdp",
                                "league_id": league, "team_id": team, "season": season, "error": None}
                try:
                    await self._verify_scope()
                    self._status.update(ready=True, status="connected")
                except ValueError as exc:
                    self._status["error"] = str(exc)
                return self.status()
            except BaseException:
                await self._close()
                raise

    async def _autopick(self):
        evidence = []
        for label, state in (("ENABLE AUTOPICK", False), ("DISABLE AUTOPICK", True)):
            controls = await _visible(self._page.get_by_role("button", name=re.compile(r"^" + label + r"$", re.I)))
            if len(controls) > 1:
                return None
            if controls:
                evidence.append(state)
        for role in ("switch", "checkbox"):
            controls = await _visible(self._page.get_by_role(role, name=re.compile(r"^AUTO\s*PICK$", re.I)))
            for control in controls:
                evidence.append(await control.is_checked())
        return evidence[0] if evidence and len(set(evidence)) == 1 else None

    async def _read_json(self, url, headers=None):
        parsed = urlsplit(url)
        league, _, season = self._scope
        expected = f"/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league}"
        allowed = {espn_data.league_read_url(league, season), espn_data.player_read_url(league, season)}
        if url not in allowed or parsed.scheme != "https" or parsed.hostname != API_HOST or parsed.path != expected:
            raise ValueError("The ESPN read endpoint is outside the connected league scope.")
        response = await self._context.request.get(url, headers=headers or {}, timeout=15000, max_redirects=0)
        try:
            if not response.ok:
                raise ValueError(f"ESPN read request failed with HTTP {response.status}. Sign in to the dedicated browser if required.")
            return await response.json()
        finally:
            await response.dispose()

    async def _observe(self, previous=None):
        await self._verify_scope()
        league, team, season = self._scope
        payload = await self._read_json(espn_data.league_read_url(league, season))
        now = datetime.now(timezone.utc)
        if self._players_payload is None or self._projections_at is None or (now - self._projections_at).total_seconds() >= 300:
            players = await self._read_json(espn_data.player_read_url(league, season), espn_data.player_read_headers(season))
            self._players_payload = players
            self._projections_at = datetime.now(timezone.utc)
        selected_team = await self._verify_scope()
        body = await self._page.locator("body").inner_text(timeout=5000)
        autopick = await self._autopick()
        observed_at = datetime.now(timezone.utc)
        def compatible(candidate):
            return (isinstance(candidate, LeagueSnapshot) and candidate.phase == "draft"
                    and candidate.source.provider == "espn_browser" and not candidate.source.synthetic
                    and (candidate.league_id, candidate.team_id, candidate.season) == self._scope)
        previous = previous if compatible(previous) else self._snapshot if compatible(self._snapshot) else None
        snapshot = espn_data.normalize_espn_draft(
            payload, self._players_payload, team_id=team, visible_text=body, page_url=self._page.url,
            observed_at=observed_at, previous=previous,
            observed_team_id=selected_team, projections_observed_at=self._projections_at)
        if snapshot.source.browser is None:
            raise ValueError("The ESPN observation has no verified browser metadata.")
        snapshot.source.browser = snapshot.source.browser.model_copy(update={"autopick_enabled": autopick})
        self._snapshot = snapshot
        self._status.update(ready=True, status="observed", error=None, observed_at=observed_at.isoformat(),
                            current_pick=snapshot.source.browser.current_pick, autopick_enabled=autopick)
        return snapshot

    async def observe(self, previous=None) -> LeagueSnapshot:
        async with self._lock:
            try:
                return await self._observe(previous)
            except Exception as exc:
                self._status.update(ready=False, status="observation_blocked", error=str(exc))
                raise

    def _check_proposal(self, proposal, snapshot):
        expected_scope = (str(proposal.get("league_id")), str(proposal.get("team_id")), proposal.get("season"))
        if expected_scope != self._scope:
            raise ValueError("The proposal belongs to another league, team, or season.")
        browser = snapshot.source.browser
        pick = proposal.get("pick_no")
        if type(pick) is not int or browser.draft_complete or pick != browser.current_pick or pick != len(snapshot.picks) + 1:
            raise ValueError("The current visible pick does not match the proposal.")
        rnd, offset = divmod(pick - 1, snapshot.rules.teams)
        owner = snapshot.rules.teams - offset if snapshot.rules.snake and rnd % 2 else offset + 1
        if owner != snapshot.own_team().slot:
            raise ValueError("It is not the selected team's turn.")
        matches = [player for player in snapshot.players if player.id == proposal.get("player_id")]
        if len(matches) != 1 or matches[0].name != proposal.get("player_name"):
            raise ValueError("The proposal player identity does not match the observed player data.")
        player = matches[0]
        if player.availability not in {"ACTIVE", "HEALTHY", "QUESTIONABLE"}:
            raise ValueError("The proposed player is not confirmed available in the observed player data.")
        if any(pick.player_id == player.id for pick in snapshot.picks):
            raise ValueError("The proposed player was already drafted.")
        if sum(other.name == player.name and other.position == player.position for other in snapshot.players) != 1:
            raise ValueError("The observed player name and position are ambiguous.")
        return player

    async def _find_button(self, player):
        # Keep the locator tied to the exact name when ESPN reorders its rows.
        rows = self._page.get_by_role("row").filter(has=self._page.get_by_text(player.name, exact=True))
        position = "(?:DST|D/ST)" if player.position == "DST" else re.escape(player.position)
        candidates = []
        for row in await _visible(rows):
            exact_names = await _visible(row.get_by_text(player.name, exact=True))
            positions = await _visible(row.get_by_text(re.compile(r"^" + position + r"$")))
            if len(exact_names) != 1 or not positions:
                continue
            buttons = await _visible(row.get_by_role("button", name=re.compile(r"^DRAFT$", re.I)))
            enabled = [button for button in buttons if await button.is_enabled()]
            candidates.extend(enabled)
        if len(candidates) > 1:
            raise ValueError("More than one visible enabled DRAFT button matches the exact player.")
        return candidates[0] if candidates else None

    async def _search_player(self, name):
        controls = []
        for role in ("textbox", "searchbox"):
            controls.extend(await _visible(self._page.get_by_role(role, name=re.compile(r"^(?:Search\s+Players?|Player\s+Search)$", re.I))))
            regions = await _visible(self._page.get_by_role("region", name=re.compile(r"^(?:Available Players|Players|Player Pool)$", re.I)))
            for region in regions:
                controls.extend(await _visible(region.get_by_role(role, name=re.compile(r"^Search$", re.I))))
        if len(controls) != 1:
            raise ValueError("The player row is not actionable and no unique player-search control is visible. Global ESPN search is not used.")
        await controls[0].fill(name, timeout=3000)
        rows = self._page.get_by_role("row").filter(has=self._page.get_by_text(name, exact=True))
        await rows.first.wait_for(state="visible", timeout=3000)

    async def _final_ui_check(self, proposal):
        await self._verify_scope()
        body = await self._page.locator("body").inner_text(timeout=5000)
        clocks = {int(value) for value in CLOCK.findall(body)}
        if clocks != {proposal["pick_no"]}:
            raise ValueError("The visible draft clock changed or is not unambiguous.")
        if await self._autopick() is not False:
            raise ValueError("ESPN Autopick must be visibly disabled before a managed pick.")

    async def _preflight(self, proposal):
        if not isinstance(proposal, dict):
            raise ValueError("A draft proposal object is required.")
        snapshot = await self._observe()
        player = self._check_proposal(proposal, snapshot)
        button = await self._find_button(player)
        if button is None:
            await self._search_player(player.name)
            snapshot = await self._observe()
            player = self._check_proposal(proposal, snapshot)
            button = await self._find_button(player)
        if button is None:
            raise ValueError("No visible enabled DRAFT button matches the exact player and position.")
        await self._final_ui_check(proposal)
        return {"ready": True, "player_id": player.id, "player_name": player.name,
                "pick_no": proposal["pick_no"], "autopick_enabled": False,
                "observed_at": datetime.now(timezone.utc).isoformat()}, button

    async def preflight_pick(self, proposal):
        async with self._lock:
            result, _ = await self._preflight(proposal)
            return result

    async def submit_pick(self, proposal):
        async with self._lock:
            if not isinstance(proposal, dict) or proposal.get("should_click") is not True or not proposal.get("proposal_id"):
                raise ValueError("A one-click permit from BrowserDraft.authorize is required.")
            if self.permit_validator is None:
                raise ValueError("The browser service must configure a current permit validator.")
            identifier = proposal["proposal_id"]
            if identifier in self._attempted:
                return {"status": "awaiting_verification", "proposal_id": identifier, "clicked": False,
                        "uncertain": True, "retry_allowed": False, "error": "This permit already had a click attempt. Reconcile the observed draft."}
            _, button = await self._preflight(proposal)
            decision = self.permit_validator(proposal, self._snapshot)
            if decision is not True and not (isinstance(decision, dict) and decision.get("should_click") is True):
                raise ValueError("The current browser service policy did not authorize this click.")
            self._attempted.add(identifier)
            result = {"status": "awaiting_verification", "proposal_id": identifier, "clicked": False,
                      "uncertain": True, "retry_allowed": False}
            try:
                await button.click(timeout=3000)
                result["clicked"] = True
                snapshot = await self._observe()
                result.update(snapshot=snapshot.model_dump(mode="json"), uncertain=False)
                return result
            except asyncio.CancelledError:
                result["error"] = "Click attempt was interrupted. Reconcile before another action."
                self._status.update(ready=False, status="awaiting_verification", error=result["error"])
                return result
            except Exception as exc:
                result["error"] = str(exc)
                self._status.update(ready=False, status="awaiting_verification", error=str(exc))
                return result

    async def _close(self):
        try:
            if self._managed and self._context is not None:
                await self._context.close()
        finally:
            try:
                if self._playwright is not None:
                    await self._playwright.stop()
            finally:
                if self._lease is not None:
                    self._lease.release()
                self._playwright = self._browser = self._context = self._page = self._lease = None
                self._status = {"connected": False, "ready": False, "status": "disconnected", "error": None}

    async def close(self):
        async with self._lock:
            await self._close()
