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
    players = {"players": []}
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

    def or_(self, other):
        return Locator(list(dict.fromkeys([*self.nodes, *other.nodes])))

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

    async def input_value(self):
        return self.nodes[0].attrs.get("value", "")

    def locator(self, selector):
        def selected(node):
            if selector == "option":
                return node.role == "option"
            if selector == 'input[type="checkbox"]':
                return node.attrs.get("type") == "checkbox"
            return node.attrs.get("selector") == selector
        return Locator([node for root in self.nodes for node in root.walk() if selected(node)])

    def get_by_role(self, role, name=None, exact=False):
        return Locator([node for root in self.nodes for node in root.walk()
                        if node.role == role and (name is None or matches(node.name, name, exact))])

    def get_by_text(self, text, exact=False):
        return Locator([node for root in self.nodes for node in root.walk() if matches(node.text, text, exact)], (text, exact))

    def filter(self, has=None, visible=None):
        if visible is not None:
            return Locator([node for node in self.nodes if node.visible is visible])
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
        if selector != "body":
            return Locator([self.root]).locator(selector)
        text = f"ON THE CLOCK: PICK {self.clock}\n{self.autopick.name}"
        return Locator([Node(text=text)])

    def get_by_placeholder(self, text, exact=False):
        return Locator([node for node in self.root.walk() if matches(node.attrs.get("placeholder", ""), text, exact)])

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
    assert browser._player_response_url == espn_browser.espn_data.player_read_url(123, 2026)
    assert set(context.players) == {"players"}
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
async def test_connection_waits_for_delayed_my_team_navigation(tmp_path, monkeypatch):
    page = Page()
    page.team_link.visible = False
    context = Context([page])
    driver = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=AsyncMock(return_value=context)), stop=AsyncMock())
    monkeypatch.setattr(espn_browser, "_start_playwright", AsyncMock(return_value=driver))
    waits = []
    async def delayed_navigation(locator, **kwargs):
        waits.append(kwargs)
        assert locator.nodes == [page.team_link]
        page.team_link.visible = True
    monkeypatch.setattr(Locator, "wait_for", delayed_navigation)
    browser = espn_browser.ESPNBrowser(tmp_path)
    result = await browser.connect("123", "11", 2026)
    assert waits == [{"state": "visible", "timeout": 5000}]
    assert result["ready"] is True and not context.closed
    assert context.calls == [] and page.button.clicks == 0
    await browser.close()


@pytest.mark.asyncio
async def test_missing_navigation_keeps_waiting_room_open_without_claiming_ready(tmp_path, monkeypatch):
    page = Page()
    page.team_link.visible = False
    context = Context([page])
    driver = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=AsyncMock(return_value=context)), stop=AsyncMock())
    monkeypatch.setattr(espn_browser, "_start_playwright", AsyncMock(return_value=driver))
    browser = espn_browser.ESPNBrowser(tmp_path)
    result = await browser.connect("123", "11", 2026)
    assert result["connected"] is True and result["ready"] is False
    assert result["status"] == "awaiting_draft_entry" and "Observation will retry" in result["error"]
    assert not context.closed
    assert context.calls == [] and page.button.clicks == 0
    await browser.close()


@pytest.mark.asyncio
async def test_observation_retries_waiting_room_when_entry_appears_without_reloading(tmp_path, monkeypatch):
    page = Page()
    page.team_link.visible = False
    target = URL + "&memberId=fictional-member"
    entry = Node("link", "Enter The Draft", visible=False, attrs={"href": target})
    roster = Node("combobox", attrs={"value": "11"}, children=[
        Node("option", "Fictional North", attrs={"value": "11"}),
        Node("option", "Fictional South", attrs={"value": "22"})])
    context = Context([page])
    driver = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=AsyncMock(return_value=context)), stop=AsyncMock())
    monkeypatch.setattr(espn_browser, "_start_playwright", AsyncMock(return_value=driver))

    async def navigate(url, **kwargs):
        page.gotos.append(url)
        page.url = url
        page.root.children = [entry] if "/waitingroom?" in url else [roster, page.autopick, page.row]

    monkeypatch.setattr(page, "goto", navigate)
    browser = espn_browser.ESPNBrowser(tmp_path)
    connected = await browser.connect("123", "11", 2026)
    assert connected["connected"] and not connected["ready"]
    assert connected["status"] == "awaiting_draft_entry"
    waiting_url = "https://fantasy.espn.com/football/waitingroom?leagueId=123"
    assert page.gotos == [waiting_url] and context.calls == []
    with pytest.raises(ValueError, match="Observation will retry"):
        await browser.observe()
    assert browser.status()["status"] == "awaiting_draft_entry"
    assert page.gotos == [waiting_url] and context.calls == []
    entry.visible = True
    snapshot = await browser.observe()
    assert browser._page is page and browser._draft_entry_url == target
    assert page.gotos == [waiting_url, target]
    assert snapshot.source.browser.current_pick == 1 and snapshot.picks == []
    assert snapshot.source.browser.team_id == "11"
    assert browser.status()["status"] == "observed" and browser.status()["error"] is None
    assert page.button.clicks == 0
    await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://fantasy.espn.com/football/waitingroom?leagueId=456",
    "https://fantasy.espn.com/football/waitingroom?leagueId=123&teamId=22",
    "https://fantasy.espn.com/football/waitingroom?leagueId=123&seasonId=2025",
    "https://fantasy.espn.com/football/waitingroom?leagueId=123&leagueId=456",
    "https://fantasy.espn.com/login?leagueId=123",
    "https://example.com/football/waitingroom?leagueId=123",
])
async def test_observation_never_enters_or_navigates_unverified_waiting_pages(connected, monkeypatch, url):
    browser, page, context = connected
    browser._managed = True
    page.url = url
    enter = AsyncMock(side_effect=AssertionError("Unverified page retried draft entry."))
    monkeypatch.setattr(browser, "_enter_from_waiting_room", enter)
    with pytest.raises(ValueError):
        await browser.observe()
    enter.assert_not_awaited()
    assert page.gotos == [] and context.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("restriction", ["cdp", "season", "existing_entry"])
async def test_waiting_room_retry_requires_managed_draft_without_prior_entry(connected, monkeypatch, restriction):
    browser, page, context = connected
    browser._managed = restriction != "cdp"
    page.url = "https://fantasy.espn.com/football/waitingroom?leagueId=123"
    if restriction == "season":
        browser.page_path = "team"
    elif restriction == "existing_entry":
        browser._draft_entry_url = URL + "&memberId=fictional-member"
    enter = AsyncMock(side_effect=AssertionError("Ineligible session retried draft entry."))
    monkeypatch.setattr(browser, "_enter_from_waiting_room", enter)
    with pytest.raises(ValueError):
        await browser.observe()
    enter.assert_not_awaited()
    assert page.gotos == [] and context.calls == []


@pytest.mark.asyncio
async def test_waiting_room_change_during_identity_read_blocks_draft_navigation(connected, monkeypatch):
    browser, page, context = connected
    browser._managed = True
    page.url = "https://fantasy.espn.com/football/waitingroom?leagueId=123"
    page.root.children = [Node("link", "Enter The Draft", attrs={"href": URL + "&memberId=fictional-member"})]

    async def read_after_navigation(url, headers=None):
        page.url = "https://fantasy.espn.com/football/waitingroom?leagueId=456"
        return deepcopy(context.league)

    monkeypatch.setattr(browser, "_read_json", read_after_navigation)
    with pytest.raises(ValueError, match="waiting room changed"):
        await browser.observe()
    assert page.gotos == [] and browser._draft_entry_url is None
    assert browser.status()["status"] == "observation_blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize("name_suffix", ["", " "])
async def test_waiting_room_entry_verifies_member_and_selected_roster(connected, monkeypatch, name_suffix):
    browser, page, context = connected
    # Whitespace on another team's API name must not invalidate this roster.
    context.league["teams"][1]["name"] += name_suffix
    browser._managed = True
    target = URL + "&memberId=fictional-member"
    entry = Node("link", "Enter The Draft", attrs={"href": target})
    roster = Node("combobox", attrs={"value": "11"}, children=[
        Node("option", "Fictional North", attrs={"value": "11"}),
        Node("option", "Fictional South", attrs={"value": "22"})])
    async def navigate(url, **kwargs):
        page.url = url
        page.root.children = [entry] if "/waitingroom?" in url else [roster, page.row]
    monkeypatch.setattr(page, "goto", navigate)
    assert await browser._enter_from_waiting_room() is True
    assert await browser._verify_scope() == "11"
    assert browser._draft_team_names == {"11": "Fictional North", "22": "Fictional South"}
    assert browser._draft_entry_url == target and len(context.calls) == 1
    assert page.button.clicks == 0
    roster.attrs["value"] = "22"
    with pytest.raises(ValueError, match="roster selection"):
        await browser._verify_scope()
    roster.attrs["value"] = "11"
    page.url = target.replace("fictional-member", "different-member")
    with pytest.raises(ValueError, match="draft member"):
        await browser._verify_scope()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["teamId=22", "leagueId=456"])
async def test_waiting_room_entry_rejects_other_team_or_league(connected, monkeypatch, change):
    browser, page, context = connected
    browser._managed = True
    original = "teamId=11" if change.startswith("teamId") else "leagueId=123"
    entry = Node("link", "Enter The Draft", attrs={"href": URL.replace(original, change) + "&memberId=fictional-member"})
    async def navigate(url, **kwargs):
        page.url = url
        page.root.children = [entry]
    monkeypatch.setattr(page, "goto", navigate)
    with pytest.raises(ValueError, match="requested draft team"):
        await browser._enter_from_waiting_room()
    assert browser._draft_entry_url is None and context.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("checked", [False, True])
async def test_custom_autopick_reads_hidden_input_in_exact_visible_container(connected, checked):
    browser, page, _ = connected
    control = Node(attrs={"type": "checkbox"}, checked=checked, visible=False)
    container = Node(attrs={"selector": "div.autoPick-container"}, children=[
        Node(text="Autopick", attrs={"selector": "label.autoPick-label"}), control])
    unrelated = Node(attrs={"type": "checkbox"}, checked=not checked)
    page.root.children = [page.team_link, container, unrelated]
    assert await browser._autopick() is checked
    assert control.clicks == 0 and unrelated.clicks == 0


@pytest.mark.asyncio
async def test_custom_autopick_duplicate_input_is_unknown(connected):
    browser, page, _ = connected
    page.root.children = [Node(attrs={"selector": "div.autoPick-container"}, children=[
        Node(text="Autopick", attrs={"selector": "label.autoPick-label"}),
        Node(attrs={"type": "checkbox"}), Node(attrs={"type": "checkbox"})])]
    assert await browser._autopick() is None


@pytest.mark.asyncio
async def test_player_name_placeholder_requires_verified_waiting_room_entry(connected):
    browser, page, _ = connected
    search = Node("textbox", attrs={"placeholder": "Player Name"})
    page.root.children.append(search)
    with pytest.raises(ValueError, match="no unique player-search"):
        await browser._search_player(SimpleNamespace(name="Runner Alpha", position="RB", team="ABC"))
    browser._draft_entry_url = URL + "&memberId=fictional-member"
    await browser._search_player(SimpleNamespace(name="Runner Alpha", position="RB", team="ABC"))
    assert search.text == "Runner Alpha"


@pytest.mark.asyncio
async def test_player_search_counts_one_element_matching_placeholder_and_accessible_name_once(connected):
    browser, page, _ = connected
    search = Node("textbox", "Search Players", attrs={"placeholder": "Player Name"})
    page.root.children.append(search)
    browser._draft_entry_url = URL + "&memberId=fictional-member"
    await browser._search_player(SimpleNamespace(name="Runner Alpha", position="RB", team="ABC"))
    assert search.text == "Runner Alpha" and page.button.clicks == 0


@pytest.mark.asyncio
async def test_player_search_still_rejects_two_distinct_matching_elements(connected):
    browser, page, _ = connected
    first = Node("textbox", "Search Players", attrs={"placeholder": "Player Name"})
    second = Node("searchbox", "Search Players", attrs={"placeholder": "Player Name"})
    page.root.children.extend([first, second])
    browser._draft_entry_url = URL + "&memberId=fictional-member"
    with pytest.raises(ValueError, match="no unique player-search"):
        await browser._search_player(SimpleNamespace(name="Runner Alpha", position="RB", team="ABC"))
    assert first.text == second.text == "Search Players" and page.button.clicks == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("capture_failure", [False, True])
async def test_incomplete_history_uses_outer_tab_and_restores_players(connected, monkeypatch, capture_failure):
    browser, page, _ = connected
    page.clock = 4
    players = Node("tab", "Players", attrs={"aria-selected": "true"}, children=[Node("tab", "Players")])
    history = Node("tab", "Pick History", attrs={"aria-selected": "false"}, children=[Node("tab", "Pick History")])
    def select_history():
        players.attrs["aria-selected"], history.attrs["aria-selected"] = "false", "true"
    def select_players():
        players.attrs["aria-selected"], history.attrs["aria-selected"] = "true", "false"
    history.on_click, players.on_click = select_history, select_players
    page.root.children.extend([players, history])
    original = page.locator
    async def history_text(**kwargs):
        return "ON THE CLOCK: PICK 4\nENABLE AUTOPICK\nPick History"
    async def accessible(**kwargs):
        assert history.attrs["aria-selected"] == "true"
        if capture_failure:
            raise RuntimeError("Fictional history capture failure")
        return ('- text: "ON THE CLOCK: PICK 3"\n'
                '- row "1 Runner Alpha ABC RB Fictional North":\n'
                '- row "2 Runner Beta ABC RB Fictional South":\n'
                '- row "3 Runner Gamma ABC RB Fictional South":')
    def locate(selector):
        if selector == "body" and history.attrs["aria-selected"] == "true":
            return SimpleNamespace(inner_text=history_text, aria_snapshot=accessible)
        return original(selector)
    monkeypatch.setattr(page, "locator", locate)
    if capture_failure:
        with pytest.raises(RuntimeError, match="history capture failure"):
            await browser.observe()
    else:
        snapshot = await browser.observe()
        assert [pick.player_id for pick in snapshot.picks] == ["101", "102", "103"]
        assert snapshot.source.browser.current_pick == 4
    assert players.attrs["aria-selected"] == "true"
    assert history.clicks == players.clicks == 1
    assert players.children[0].clicks == history.children[0].clicks == page.button.clicks == 0


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


@pytest.mark.asyncio
@pytest.mark.parametrize("position,team,label", [("RB", "ABC", "Runner Alpha ABC RB"),
                                               ("DST", "33", "Runner Alpha BAL D/ST")])
async def test_autocomplete_requires_exact_suggestion_before_row_appears(connected, position, team, label):
    browser, page, context = connected
    player = SimpleNamespace(name="Runner Alpha", position=position, team=team)
    page.root.children.remove(page.row)
    search = Node("textbox", "Search Players", attrs={"placeholder": "Player Name"})
    suggestion = Node("button", label, visible=False)
    misleading = Node("button", "Runner Alpha Jr. ABC RB")
    search.on_fill = lambda value: setattr(suggestion, "visible", True)
    suggestion.on_click = lambda: page.root.children.append(page.row)
    page.root.children.extend([search, suggestion, misleading])
    await browser._search_player(player)
    assert search.text == player.name and suggestion.clicks == 1
    assert misleading.clicks == page.button.clicks == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["duplicate", "disabled", "wrong_team", "wrong_position", "wrong_name", "unknown_team"])
async def test_autocomplete_ambiguous_or_wrong_identity_never_selects(connected, case):
    browser, page, _ = connected
    page.root.children.remove(page.row)
    player = SimpleNamespace(name="Runner Alpha", position="RB", team="ABC" if case != "unknown_team" else "999")
    search = Node("textbox", "Search Players")
    labels = {"wrong_team": "Runner Alpha XYZ RB", "wrong_position": "Runner Alpha ABC WR",
              "wrong_name": "Runner Alpha Jr. ABC RB"}
    suggestion = Node("button", labels.get(case, "Runner Alpha ABC RB"), enabled=case != "disabled")
    page.root.children.extend([search, suggestion])
    duplicate = Node("button", "Runner Alpha ABC RB")
    if case == "duplicate":
        page.root.children.append(duplicate)
    with pytest.raises((ValueError, TimeoutError)):
        await browser._search_player(player)
    assert suggestion.clicks == duplicate.clicks == page.button.clicks == 0


@pytest.mark.asyncio
async def test_autocomplete_rechecks_scope_after_input_changes_page(connected):
    browser, page, _ = connected
    page.root.children.remove(page.row)
    search = Node("textbox", "Search Players")
    suggestion = Node("button", "Runner Alpha ABC RB")
    search.on_fill = lambda value: setattr(page, "url", URL.replace("leagueId=123", "leagueId=456"))
    page.root.children.extend([search, suggestion])
    with pytest.raises(ValueError, match="exact connected"):
        await browser._search_player(SimpleNamespace(name="Runner Alpha", position="RB", team="ABC"))
    assert suggestion.clicks == page.button.clicks == 0
