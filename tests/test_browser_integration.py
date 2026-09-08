"""Exercise real Chrome against fictional HTML, not the live ESPN service.

Run with FFM_BROWSER_TESTS=1 and a local Chrome installation. The tests use an
isolated, temporary browser context. Every page request is fulfilled locally.
The adapter's JSON reader is replaced, because context.request bypasses routes.
These tests verify browser mechanics. They do not establish live ESPN acceptance.
"""

from copy import deepcopy
import os
from types import SimpleNamespace

import pytest

from fantasy_football_manager.espn_browser import ESPNBrowser
from fantasy_football_manager.espn_data import league_read_url, player_read_url
from fantasy_football_manager.espn_service import ESPNService
from fantasy_football_manager.models import ManagerConfig


pytestmark = [pytest.mark.asyncio,
              pytest.mark.skipif(os.environ.get("FFM_BROWSER_TESTS") != "1",
                                 reason="Set FFM_BROWSER_TESTS=1 to run isolated Chrome tests.")]

URL = "https://fantasy.espn.com/football/draft?leagueId=123&teamId=1&seasonId=2026"


def fictional_payloads():
    league = {
        "id": 123, "seasonId": 2026, "gameId": 1, "segmentId": 0,
        "settings": {
            "size": 2, "draftSettings": {"type": "SNAKE", "pickOrder": [1, 2], "keeperCount": 0},
            "rosterSettings": {"lineupSlotCounts": {"2": 1, "20": 1, "21": 0},
                               "positionLimits": {"1": 1, "2": 2, "3": 2, "4": 1, "5": 1, "16": 1}},
            "scoringSettings": {"scoringType": "H2H_POINTS", "scoringItems": [
                {"statId": 53, "points": 1, "pointsOverrides": {}},
                {"statId": 24, "points": .1, "pointsOverrides": {}}]}},
        "teams": [{"id": 1, "name": "Fictional North"}, {"id": 2, "name": "Fictional South"}],
        # Keep the API history empty after the click. Visible Activity must
        # supply the actual result to the normalizer and reconciliation code.
        "draftDetail": {"drafted": False, "picks": []}, "status": {"isActive": True},
    }
    players = {"id": 123, "seasonId": 2026, "players": []}
    for index, name in enumerate(["Fictional Runner One", "Fictional Runner One Jr.",
                                  "Fictional Runner Two", "Fictional Runner Three"], 101):
        players["players"].append({"id": index, "onTeamId": 0, "player": {
            "id": index, "fullName": name, "defaultPositionId": 2,
            "eligibleSlots": [2, 20, 21, 23], "active": True, "injuryStatus": "ACTIVE",
            "ownership": {"averageDraftPosition": index - 100},
            "stats": [{"seasonId": 2026, "statSourceId": 1, "statSplitTypeId": 0,
                       "scoringPeriodId": 0, "stats": {"53": 30, "24": 900}}]}})
    return league, players


def fictional_html(*, duplicate=False, autopick="button"):
    control = ('<button type="button">ENABLE AUTOPICK</button>' if autopick == "button" else
               '<input type="checkbox" role="switch" aria-label="Autopick">')
    row = ('<tr><td><span>Fictional Runner One</span></td><td>RB</td>'
           '<td><button type="button" onclick="selectPlayer(this)">DRAFT</button></td></tr>')
    return """<!doctype html><html lang="en"><head><title>Fictional draft test</title></head><body>
    <h1>Fictional draft test</h1>
    <a href="/football/team?leagueId=123&amp;teamId=1&amp;seasonId=2026">My Team</a>
    <p id="clock">ON THE CLOCK: PICK 1</p>
    <div>""" + control + """</div>
    <table aria-label="Available Players"><tbody>
    <tr><td><span>Fictional Runner One Jr.</span></td><td>RB</td>
        <td><button type="button" onclick="wrongPlayer()">DRAFT</button></td></tr>
    """ + row + (row if duplicate else "") + """
    </tbody></table>
    <h2>Activity</h2><div id="activity"></div>
    <p>Selection count: <output id="clicks">0</output></p>
    <p>Wrong selection count: <output id="wrong">0</output></p>
    <script>
    function selectPlayer(button) {
      const count = document.getElementById('clicks');
      count.textContent = String(Number(count.textContent) + 1);
      document.getElementById('clock').textContent = 'ON THE CLOCK: PICK 2';
      document.getElementById('activity').textContent =
        'Fictional Runner One / ABC RB R1, P1 - Fictional North';
      button.disabled = true;
    }
    function wrongPlayer() {
      const count = document.getElementById('wrong');
      count.textContent = String(Number(count.textContent) + 1);
    }
    </script></body></html>"""


@pytest.fixture
async def browser_case(tmp_path, monkeypatch):
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(channel="chrome", headless=True)
    context = await browser.new_context(service_workers="block", accept_downloads=False)
    page = await context.new_page()
    league, players = fictional_payloads()
    page_requests, json_reads = [], []
    state = {"html": fictional_html()}

    async def local_page(route):
        page_requests.append(route.request.url)
        await route.fulfill(status=200, content_type="text/html", body=state["html"])

    await context.route("**/*", local_page)
    adapter = ESPNBrowser(tmp_path)
    adapter._context, adapter._page, adapter._scope = context, page, ("123", "1", 2026)
    adapter._status.update(connected=True, ready=True, status="fictional_browser_test")

    async def local_json(url, headers=None):
        json_reads.append(url)
        if url == league_read_url(123, 2026):
            return deepcopy(league)
        if url == player_read_url(123, 2026):
            return deepcopy(players)
        pytest.fail("The adapter requested an unexpected read endpoint.")

    # This replacement is essential: Playwright APIRequestContext is separate
    # from browser route interception. No authenticated request is performed.
    monkeypatch.setattr(adapter, "_read_json", local_json)
    service = ESPNService(tmp_path, browser=adapter)

    async def load(*, duplicate=False, autopick="button"):
        state["html"] = fictional_html(duplicate=duplicate, autopick=autopick)
        await page.goto(URL, wait_until="domcontentloaded")
        observed = await adapter.observe()
        service.manager.import_snapshot(observed.model_dump(mode="json"))
        config = ManagerConfig(automation={"preset": "review"})
        service.manager.update_config(config.model_dump(mode="json"), 0)
        return service, adapter, page

    try:
        yield load, page_requests, json_reads
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()


@pytest.mark.parametrize("autopick", ["button", "switch"])
async def test_unique_exact_player_click_reconciles_real_dom_activity(browser_case, autopick):
    load, page_requests, json_reads = browser_case
    service, adapter, page = await load(autopick=autopick)
    proposal = await service.prepare_pick("101")
    preflight = await adapter.preflight_pick(proposal)
    assert preflight["ready"] and not preflight["autopick_enabled"]
    assert await page.locator("#clicks").inner_text() == "0"
    assert service.manager.state()[0].picks == []

    result = await service.submit_pick(proposal["proposal_id"], confirmation=True)

    assert result["status"] == "confirmed"
    assert await page.locator("#clicks").inner_text() == "1"
    assert await page.locator("#wrong").inner_text() == "0"
    saved = service.manager.state()[0]
    assert [(p.pick_no, p.player_id, p.slot) for p in saved.picks] == [(1, "101", 1)]
    assert saved.own_team().roster_ids == ["101"]
    assert saved.source.browser.current_pick == 2
    assert service.draft.pending() == []
    assert any(event["event"] == "browser_draft_reconciled" for event in service.manager.history())
    assert page_requests and all(url == URL for url in page_requests)
    assert set(json_reads) == {league_read_url(123, 2026), player_read_url(123, 2026)}


async def test_same_permit_cannot_click_the_real_dom_twice(browser_case):
    load, _, json_reads = browser_case
    service, adapter, page = await load()
    proposal = await service.prepare_pick("101")
    permit = service.draft.authorize(proposal["proposal_id"], confirmation=True)
    first = await adapter.submit_pick(permit)
    assert first["clicked"] and first["snapshot"]["picks"][0]["player_id"] == "101"
    reads_after_click = len(json_reads)

    repeat = await adapter.submit_pick(permit)

    assert not repeat["clicked"] and not repeat["retry_allowed"]
    assert len(json_reads) == reads_after_click
    assert await page.locator("#clicks").inner_text() == "1"
    assert await page.locator("#wrong").inner_text() == "0"
    result = service.draft.reconcile(proposal["proposal_id"], first["snapshot"])
    assert result["status"] == "confirmed"
    assert service.draft.authorize(proposal["proposal_id"], confirmation=True)["should_click"] is False


async def test_duplicate_visible_player_rows_block_before_authorization(browser_case):
    load, _, _ = browser_case
    service, _, page = await load(duplicate=True)
    proposal = await service.prepare_pick("101")

    with pytest.raises(ValueError, match="More than one.*DRAFT"):
        await service.submit_pick(proposal["proposal_id"], confirmation=True)

    assert await page.locator("#clicks").inner_text() == "0"
    assert await page.locator("#wrong").inner_text() == "0"
    assert service.draft.get(proposal["proposal_id"])["status"] == "pending"
    assert service.draft.pending() == []
    assert service.manager.state()[0].picks == []


@pytest.mark.parametrize("position_label", ["D/ST", "DST"])
async def test_defense_autocomplete_escapes_slashes_in_real_selector(browser_case, position_label):
    load, _, _ = browser_case
    service, adapter, page = await load()
    html = '''<!doctype html><html lang="en"><body>
      <a href="/football/team?leagueId=123&amp;teamId=1&amp;seasonId=2026">My Team</a>
      <input aria-label="Search Players" oninput="document.getElementById('suggestions').hidden=false">
      <div id="suggestions" hidden>
        <button onclick="count('wrong')">Fictional Example D/ST CHI D/ST</button>
        <button onclick="count('wrong')">Fictional Example D/ST DEN RB</button>
        <button onclick="choose()">Fictional Example D/ST DEN POSITION_LABEL</button>
      </div>
      <table><tbody><tr id="target" hidden>
        <td>Fictional Example D/ST</td><td>POSITION_LABEL</td>
        <td><button onclick="count('drafted')">DRAFT</button></td>
      </tr></tbody></table>
      <output id="selected">0</output><output id="drafted">0</output><output id="wrong">0</output>
      <script>
      function count(id){const item=document.getElementById(id);item.textContent=String(Number(item.textContent)+1);}
      function choose(){count('selected');document.getElementById('suggestions').hidden=true;
                        document.getElementById('target').hidden=false;}
      </script></body></html>'''.replace("POSITION_LABEL", position_label)
    await page.set_content(html)
    player = SimpleNamespace(name="Fictional Example D/ST", position="DST", team="DEN")
    assert await adapter._find_button(player) is None

    await adapter._search_player(player)
    button = await adapter._find_button(player)
    assert button is not None
    await button.click()

    assert await page.locator("#selected").inner_text() == "1"
    assert await page.locator("#drafted").inner_text() == "1"
    assert await page.locator("#wrong").inner_text() == "0"
    assert service.draft.pending() == []
