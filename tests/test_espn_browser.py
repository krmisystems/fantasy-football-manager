"""Exercise ESPN browser safeguards with fictional DOM and request objects only."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fantasy_football_manager import espn_browser
from fantasy_football_manager.demo import make_demo


URL = "https://fantasy.espn.com/football/draft?leagueId=123&teamId=11&seasonId=2026"


def payloads():
    league = {
        "id": 123, "seasonId": 2026,
        "settings": {"size": 2,
            "draftSettings": {"type": "SNAKE", "pickOrder": [11, 22], "keeperCount": 0},
            "rosterSettings": {"lineupSlotCounts": {"2": 1, "20": 1},
                               "positionLimits": {"1": 1, "2": 2, "3": 2, "4": 1, "5": 1, "16": 1}},
            "scoringSettings": {"scoringType": "H2H_POINTS", "scoringItems": [{"statId": 24, "points": .1}]}},
        "teams": [{"id": 11, "name": "Fictional North"}, {"id": 22, "name": "Fictional South"}],
        "draftDetail": {"drafted": False, "picks": []}, "status": {"isActive": True},
    }
    players = {"id": 123, "seasonId": 2026, "players": []}
    for number, name in enumerate(("Runner Alpha", "Runner Beta", "Runner Gamma", "Runner Delta"), 101):
        players["players"].append({"id": number, "onTeamId": 0, "player": {
            "id": number, "fullName": name, "defaultPositionId": 2, "eligibleSlots": [2, 20, 23], "active": True,
            "ownership": {"averageDraftPosition": number - 100},
            "stats": [{"seasonId": 2026, "statSourceId": 1, "statSplitTypeId": 0, "scoringPeriodId": 0,
                       "stats": {"24": 1000}}]}})
    return league, players


def matches(actual, query, exact=False):
    if hasattr(query, "search"):
        return bool(query.search(actual))
    return actual == query if exact else query in actual


class Node:
    def __init__(self, role="generic", name="", text=None, children=None, visible=True, enabled=True, attrs=None, checked=False):
        self.role, self.name = role, name
        self.text = name if text is None else text
        self.children = children or []
        self.visible, self.enabled, self.attrs, self.checked = visible, enabled, attrs or {}, checked
        self.clicks = 0
        self.on_click = self.on_fill = None

    def walk(self):
        yield self
        for node in self.children:
            yield from node.walk()


class Locator:
    def __init__(self, nodes, text_query=None):
        self.nodes, self.text_query = nodes, text_query

    async def all(self):
        return [Locator([node]) for node in self.nodes]

    async def is_visible(self):
        return self.nodes[0].visible

    async def is_enabled(self):
        return self.nodes[0].enabled

    async def is_checked(self):
        return self.nodes[0].checked

    async def get_attribute(self, name):
        return self.nodes[0].attrs.get(name)

    async def inner_text(self, **kwargs):
        return self.nodes[0].text

    def get_by_role(self, role, name=None, exact=False):
        return Locator([node for root in self.nodes for node in root.walk()
                        if node.role == role and (name is None or matches(node.name, name, exact))])

    def get_by_text(self, text, exact=False):
        return Locator([node for root in self.nodes for node in root.walk() if matches(node.text, text, exact)], (text, exact))

    def filter(self, has):
        text, exact = has.text_query
        return Locator([node for node in self.nodes if any(matches(child.text, text, exact) for child in node.walk())])

    @property
    def first(self):
        return Locator(self.nodes[:1])

    async def wait_for(self, **kwargs):
        if not self.nodes or not self.nodes[0].visible:
            raise TimeoutError("Synthetic row did not appear")

    async def fill(self, value, **kwargs):
        self.nodes[0].text = value
        if self.nodes[0].on_fill:
            self.nodes[0].on_fill(value)

    async def click(self, **kwargs):
        node = self.nodes[0]
        node.clicks += 1
        if node.on_click:
            node.on_click()


class Page:
    def __init__(self, url=URL):
        self.url, self.closed, self.clock = url, False, 1
        self.team_link = Node("link", "My Team", attrs={"href": "/football/team?leagueId=123&teamId=11&seasonId=2026"})
        self.autopick = Node("button", "ENABLE AUTOPICK")
        self.button = Node("button", "DRAFT")
        self.row = self.player_row(self.button)
        self.root = Node(children=[self.team_link, self.autopick, self.row])
        self.gotos = []

    @staticmethod
    def player_row(button, name="Runner Alpha", position="RB"):
        return Node("row", children=[Node(text=name), Node(text=position), button])

    def is_closed(self):
        return self.closed

    def get_by_role(self, *args, **kwargs):
        return Locator([self.root]).get_by_role(*args, **kwargs)

    def get_by_text(self, *args, **kwargs):
        return Locator([self.root]).get_by_text(*args, **kwargs)

    def locator(self, selector):
        assert selector == "body"
        text = f"ON THE CLOCK: PICK {self.clock}\n{self.autopick.name}"
        return Locator([Node(text=text)])

    async def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.url = url


class Response:
    ok, status = True, 200

    def __init__(self, data):
        self.data, self.disposed = data, False

    async def json(self):
        return deepcopy(self.data)

    async def dispose(self):
        self.disposed = True


class Context:
    def __init__(self, pages=None):
        self.pages, self.closed, self.calls = pages or [], False, []
        self.league, self.players = payloads()
        self.request = SimpleNamespace(get=self.get)

    async def get(self, url, **kwargs):
        assert kwargs["max_redirects"] == 0
        self.calls.append(url)
        return Response(self.players if "kona_player_info" in url else self.league)

    async def new_page(self):
        page = Page("about:blank")
        self.pages.append(page)
        return page

    async def close(self):
        self.closed = True


def permit():
    return {"proposal_id": "fictional-proposal", "should_click": True, "league_id": "123", "team_id": "11",
            "season": 2026, "pick_no": 1, "player_id": "101", "player_name": "Runner Alpha"}


@pytest.fixture
def connected(tmp_path):
    browser = espn_browser.ESPNBrowser(tmp_path)
    browser._scope = ("123", "11", 2026)
    browser._page = page = Page()
    browser._context = context = Context([page])
    browser.permit_validator = lambda proposal, snapshot: True
    return browser, page, context


@pytest.mark.asyncio
async def test_observe_uses_read_endpoints_and_preserves_cached_projection_time(connected):
    browser, _, context = connected
    first = await browser.observe()
    second = await browser.observe(first)
    assert len(context.calls) == 3
    assert second.source.projections_observed_at == first.source.projections_observed_at
    assert second.source.observed_at >= first.source.observed_at
    assert second.source.browser.autopick_enabled is False
    browser._projections_at -= timedelta(seconds=301)
    third = await browser.observe(second)
    assert len(context.calls) == 5
    # Windows can return the same wall-clock tick for these immediate stub reads.
    # The five requests above prove that the expired payload was fetched again.
    assert third.source.projections_observed_at >= first.source.projections_observed_at


@pytest.mark.asyncio
async def test_demo_or_other_league_history_does_not_block_new_connection(connected):
    browser, _, _ = connected
    snapshot = await browser.observe(make_demo("draft"))
    assert snapshot.league_id == "123" and snapshot.source.provider == "espn_browser"
    other = snapshot.model_copy(update={"league_id": "456"})
    assert (await browser.observe(other)).league_id == "123"


@pytest.mark.asyncio
async def test_same_scope_history_is_preserved_and_stale_clock_is_rejected(connected):
    browser, page, context = connected
    context.league["draftDetail"]["picks"] = [{"overallPickNumber": 1, "roundId": 1, "roundPickNumber": 1, "teamId": 11, "playerId": 101}]
    page.clock = 2
    previous = await browser.observe()
    context.league["draftDetail"]["picks"] = []
    current = await browser.observe(previous)
    assert current.picks == previous.picks
    page.clock = 1
    with pytest.raises(ValueError):
        await browser.observe(current)


@pytest.mark.asyncio
async def test_fresh_unavailable_player_blocks_even_with_service_permit(connected):
    browser, page, context = connected
    context.players["players"][0]["player"]["injuryStatus"] = "OUT"
    with pytest.raises(ValueError, match="not confirmed available"):
        await browser.submit_pick(permit())
    assert page.button.clicks == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://example.com/football/draft?leagueId=123", URL.replace("123", "999"), URL.replace("teamId=11", "teamId=22")])
async def test_wrong_scope_prevents_reads_and_clicks(connected, url):
    browser, page, context = connected
    page.url = url
    with pytest.raises(ValueError):
        await browser.submit_pick(permit())
    assert page.button.clicks == 0 and context.calls == []


@pytest.mark.asyncio
async def test_visible_my_team_must_match_even_when_url_matches(connected):
    browser, page, context = connected
    page.team_link.attrs["href"] = "/football/team?leagueId=123&teamId=22"
    with pytest.raises(ValueError, match="My Team"):
        await browser.observe()
    assert not context.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["DISABLE AUTOPICK", ""])
async def test_enabled_or_unknown_autopick_blocks_submission(connected, state):
    browser, page, _ = connected
    page.autopick.name = state
    with pytest.raises(ValueError, match="Autopick"):
        await browser.submit_pick(permit())
    assert page.button.clicks == 0


@pytest.mark.asyncio
async def test_explicit_unchecked_autopick_switch_is_accepted(connected):
    browser, page, _ = connected
    page.autopick.role, page.autopick.name, page.autopick.checked = "switch", "Autopick", False
    result = await browser.preflight_pick(permit())
    assert result["autopick_enabled"] is False
    assert page.button.clicks == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", [
    lambda page: page.root.children.append(page.player_row(Node("button", "DRAFT"))),
    lambda page: setattr(page.row.children[1], "text", "WR"),
    lambda page: setattr(page.button, "enabled", False),
])
async def test_ambiguous_wrong_position_or_disabled_row_never_clicks(connected, mutate):
    browser, page, _ = connected
    mutate(page)
    with pytest.raises(ValueError):
        await browser.submit_pick(permit())
    assert page.button.clicks == 0


@pytest.mark.asyncio
async def test_unique_player_search_can_find_row_without_using_global_search(connected):
    browser, page, _ = connected
    page.root.children.remove(page.row)
    search = Node("textbox", "Search Players")
    search.on_fill = lambda value: page.root.children.append(page.row)
    page.root.children.append(search)
    global_search = Node("textbox", "Search")
    page.root.children.append(global_search)
    assert (await browser.preflight_pick(permit()))["ready"] is True
    assert search.text == "Runner Alpha" and global_search.text == "Search"
    assert page.button.clicks == 0


@pytest.mark.asyncio
async def test_global_search_alone_is_not_used(connected):
    browser, page, _ = connected
    page.root.children.remove(page.row)
    search = Node("textbox", "Search")
    page.root.children.append(search)
    with pytest.raises(ValueError, match="Global ESPN search"):
        await browser.preflight_pick(permit())
    assert search.text == "Search"


@pytest.mark.asyncio
async def test_service_permit_is_required_and_rechecked_after_ui_preflight(connected):
    browser, page, _ = connected
    browser.permit_validator = None
    with pytest.raises(ValueError, match="validator"):
        await browser.submit_pick(permit())
    browser.permit_validator = lambda proposal, snapshot: False
    with pytest.raises(ValueError, match="current browser service policy"):
        await browser.submit_pick(permit())
    assert page.button.clicks == 0
    with pytest.raises(ValueError, match="one-click permit"):
        await browser.submit_pick({**permit(), "should_click": False})


@pytest.mark.asyncio
async def test_exactly_one_click_then_observation_and_no_repeat(connected):
    browser, page, context = connected
    checked = []
    browser.permit_validator = lambda proposal, snapshot: checked.append((proposal["proposal_id"], len(context.calls), snapshot)) or True
    def draft():
        assert checked and checked[0][1] >= 2
        assert checked[0][2].source.browser.current_pick == 1
        assert checked[0][2].source.provider == "espn_browser"
        context.league["draftDetail"]["picks"] = [{"overallPickNumber": 1, "roundId": 1, "roundPickNumber": 1, "teamId": 11, "playerId": 101}]
        page.clock = 2
    page.button.on_click = draft
    result = await browser.submit_pick(permit())
    assert result["status"] == "awaiting_verification" and not result["uncertain"]
    assert result["snapshot"]["picks"][0]["player_id"] == "101"
    repeated = await browser.submit_pick(permit())
    assert repeated["retry_allowed"] is False and page.button.clicks == 1


@pytest.mark.asyncio
async def test_click_exception_is_uncertain_and_cannot_retry(connected):
    browser, page, _ = connected
    def disconnected():
        raise TimeoutError("Synthetic disconnect after dispatch")
    page.button.on_click = disconnected
    result = await browser.submit_pick(permit())
    assert result["uncertain"] is True and result["retry_allowed"] is False
    await browser.submit_pick(permit())
    assert page.button.clicks == 1


@pytest.mark.asyncio
async def test_clock_change_or_proposal_identity_mismatch_blocks_click(connected):
    browser, page, _ = connected
    for bad in ({**permit(), "pick_no": 2}, {**permit(), "player_name": "Runner Beta"}, {**permit(), "team_id": "22"}):
        with pytest.raises(ValueError):
            await browser.submit_pick(bad)
    assert page.button.clicks == 0


@pytest.mark.parametrize("url", ["http://example.com:9222", "http://127.0.0.1.example.com:9222", "http://user@localhost:9222", "http://localhost", "file:///tmp/browser", "http://0.0.0.0:9222"])
def test_non_loopback_or_credential_cdp_urls_rejected(url):
    with pytest.raises(ValueError):
        espn_browser._loopback_url(url)


@pytest.mark.asyncio
async def test_managed_connection_uses_own_profile_and_never_navigates_unrelated_tab(tmp_path, monkeypatch):
    unrelated = Page("https://example.com/")
    context = Context([unrelated])
    chromium = SimpleNamespace(launch_persistent_context=AsyncMock(return_value=context))
    driver = SimpleNamespace(chromium=chromium, stop=AsyncMock())
    monkeypatch.setattr(espn_browser, "_start_playwright", AsyncMock(return_value=driver))
    browser = espn_browser.ESPNBrowser(tmp_path)
    result = await browser.connect("123", "11", 2026)
    assert result["ready"] is True and not unrelated.gotos
    args, kwargs = chromium.launch_persistent_context.call_args
    assert args == (tmp_path / "espn-browser-profile",) and kwargs["channel"] == "chrome"
    second = espn_browser.ESPNBrowser(tmp_path)
    with pytest.raises(ValueError, match="Another manager"):
        await second.connect("123", "11", 2026)
    await browser.close()
    assert context.closed
    driver.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_cdp_selects_exact_tab_and_detaches_without_closing_user_context(tmp_path, monkeypatch):
    unrelated, exact = Page("https://example.com/"), Page()
    context = Context([unrelated, exact])
    chromium = SimpleNamespace(connect_over_cdp=AsyncMock(return_value=SimpleNamespace(contexts=[context])))
    driver = SimpleNamespace(chromium=chromium, stop=AsyncMock())
    monkeypatch.setattr(espn_browser, "_start_playwright", AsyncMock(return_value=driver))
    browser = espn_browser.ESPNBrowser(tmp_path)
    await browser.connect("123", "11", 2026, "ws://127.0.0.1:9222/devtools/browser/fictional")
    assert browser._page is exact
    await browser.close()
    assert context.closed is False
    driver.stop.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("league,team,season", [("123/../99", "11", 2026), ("123", True, 2026), ("123", "11", "2026")])
async def test_invalid_connection_scope_never_starts_browser(tmp_path, monkeypatch, league, team, season):
    start = AsyncMock()
    monkeypatch.setattr(espn_browser, "_start_playwright", start)
    browser = espn_browser.ESPNBrowser(tmp_path)
    with pytest.raises(ValueError):
        await browser.connect(league, team, season)
    start.assert_not_called()
