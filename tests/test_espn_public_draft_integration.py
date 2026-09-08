"""Exercise the public draft layout in isolated Chrome with fictional data.

All page requests are intercepted. JSON reads are stubbed because Playwright's
request context does not use page routes. No real account or league is used.
"""

import asyncio
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from fantasy_football_manager import espn_browser
from fantasy_football_manager.espn_data import league_read_url, player_read_url
from fantasy_football_manager.espn_service import ESPNService
from fantasy_football_manager.models import ManagerConfig


pytestmark = [pytest.mark.asyncio,
              pytest.mark.skipif(os.environ.get("FFM_BROWSER_TESTS") != "1",
                                 reason="Set FFM_BROWSER_TESTS=1 to run isolated Chrome tests.")]

WAITING = "https://fantasy.espn.com/football/waitingroom?leagueId=123"
ENTRY = ("https://fantasy.espn.com/football/draft?leagueId=123&teamId=11"
         "&seasonId=2026&memberId=fictional-member")
ROOM = Path(__file__).parent / "fixtures" / "public_draft_room.html"


def public_payloads():
    """Leave every API pick unresolved so only observed UI history can confirm it."""
    league = {
        "id": 123, "seasonId": 2026, "gameId": 1, "segmentId": 0,
        "settings": {
            "size": 2,
            "draftSettings": {"type": "SNAKE", "pickOrder": [11, 22],
                              "keeperCount": 0, "leagueSubType": "DRAFT_LOBBY"},
            "rosterSettings": {
                "lineupSlotCounts": {"2": 1, "20": 1, "21": 0},
                "positionLimits": {"1": 1, "2": 2, "3": 2, "4": 1, "5": 1, "16": 1}},
            "scoringSettings": {"scoringType": "H2H_POINTS", "scoringItems": [
                {"statId": 53, "points": 1}, {"statId": 24, "points": .1}]}},
        "teams": [{"id": 11, "name": "Fictional North"},
                  {"id": 22, "name": "Fictional South "}],
        "draftDetail": {"drafted": False, "picks": [
            {"overallPickNumber": number, "roundId": (number - 1) // 2 + 1,
             "roundPickNumber": (number - 1) % 2 + 1, "teamId": owner, "playerId": -1}
            for number, owner in enumerate([11, 22, 22, 11], 1)]},
        "status": {"isActive": True},
    }
    # Public player responses can omit league identifiers. The adapter must
    # bind this response to its verified player-read URL.
    players = {"players": []}
    for pid, name, rushing in [(101, "Alpha", 900), (102, "Beta", 800),
                               (103, "Gamma", 700), (104, "Delta", 1700),
                               (105, "Delta Jr.", 100)]:
        players["players"].append({"id": pid, "onTeamId": 0, "player": {
            "id": pid, "fullName": f"Fictional Runner {name}", "defaultPositionId": 2,
            "eligibleSlots": [2, 20, 21, 23], "active": True, "injuryStatus": "ACTIVE",
            "proTeamAbbreviation": "ABC", "ownership": {"averageDraftPosition": pid - 100},
            "stats": [{"seasonId": 2026, "statSourceId": 1, "statSplitTypeId": 0,
                       "scoringPeriodId": 0, "stats": {"53": 30, "24": rushing}}]}})
    return league, players


async def test_public_room_history_recovery_and_automatic_pick_are_verified(tmp_path, monkeypatch):
    from playwright.async_api import async_playwright

    monkeypatch.delenv("FFM_BROWSER_DATA_DIR", raising=False)
    playwright = await async_playwright().start()
    chrome = await playwright.chromium.launch(channel="chrome", headless=True)
    context = await chrome.new_context(service_workers="block", accept_downloads=False)
    page_requests, unexpected_requests, json_reads = [], [], []
    league, players = public_payloads()
    room_html = ROOM.read_text(encoding="utf-8")

    async def local_page(route):
        url = route.request.url
        page_requests.append(url)
        parsed, query = urlsplit(url), parse_qs(urlsplit(url).query)
        if url == WAITING:
            await route.fulfill(content_type="text/html", body=(
                '<!doctype html><html lang="en"><body><h1>Fictional authenticated waiting room</h1>'
                f'<a href="{ENTRY.replace("&", "&amp;")}">Enter The Draft</a></body></html>'))
        elif url == ENTRY:
            await route.fulfill(content_type="text/html", body=room_html)
        elif (parsed.hostname == "fantasy.espn.com" and parsed.path == "/football/draft"
              and query == {"leagueId": ["123"], "teamId": ["11"], "seasonId": ["2026"]}):
            # Serve a local entry screen. HTTP redirects can bypass a route
            # handler, so connect must navigate to the intercepted waiting room.
            await route.fulfill(content_type="text/html", body=(
                "<!doctype html><html><body>Fictional draft entry required.</body></html>"))
        elif parsed.hostname == "fantasy.espn.com" and parsed.path == "/favicon.ico":
            await route.fulfill(status=204, body="")
        else:
            unexpected_requests.append(url)
            await route.abort()

    await context.route("**/*", local_page)
    # Use the real isolated context while exercising connect's managed-profile
    # entry and lease logic. Never open the installed user's persistent profile.
    launcher = AsyncMock(return_value=context)
    driver = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launcher), stop=AsyncMock())
    monkeypatch.setattr(espn_browser, "_start_playwright", AsyncMock(return_value=driver))
    adapter = espn_browser.ESPNBrowser(tmp_path)

    async def local_json(url, headers=None):
        json_reads.append(url)
        if url == league_read_url(123, 2026):
            return deepcopy(league)
        if url == player_read_url(123, 2026):
            return deepcopy(players)
        pytest.fail("The adapter requested an unexpected JSON endpoint.")

    monkeypatch.setattr(adapter, "_read_json", local_json)
    service = ESPNService(tmp_path, browser=adapter)
    try:
        connected = await service.connect("123", "11", 2026, headless=True)
        assert connected["ready"] and adapter._draft_entry_url == ENTRY, connected
        page = adapter._page
        assert await page.get_by_role("link", name="My Team", exact=True).count() == 0
        assert await page.locator("#roster").input_value() == "11"
        assert not await page.locator("#autopick").is_visible()

        await service.sync()
        before = service.manager.require_state()[0]
        assert [(pick.pick_no, pick.player_id, pick.slot) for pick in before.picks] == [
            (1, "101", 1), (2, "102", 2), (3, "103", 2)]
        assert before.source.browser.current_pick == 4
        assert before.source.browser.autopick_enabled is False
        assert await page.locator("#round").input_value() == "all"
        assert await page.locator("#history-visits").inner_text() == "1"
        assert await page.locator("#restorations").inner_text() == "1"
        assert await page.locator("#players-tab").get_attribute("aria-selected") == "true"
        assert not await page.locator("#target-row").is_visible()
        assert not await page.locator("#suggestions").is_visible()
        assert await page.locator("#clicks").inner_text() == "0"

        config = ManagerConfig()
        config.automation.preset = "custom"
        config.automation.actions["draft_pick"] = "automatic"
        service.manager.update_config(config.model_dump(mode="json"), 0)
        await service.start(interval_seconds=1, trials=4)
        try:
            await asyncio.wait_for(asyncio.shield(service.task), timeout=12)
        except TimeoutError:
            pytest.fail(f"The fictional automatic draft did not finish: {service.status()['worker']}")

        saved = service.manager.require_state()[0]
        assert [(pick.pick_no, pick.player_id, pick.slot) for pick in saved.picks] == [
            (1, "101", 1), (2, "102", 2), (3, "103", 2), (4, "104", 1)]
        assert saved.own_team().roster_ids == ["101", "104"]
        assert saved.source.browser.draft_complete
        assert saved.source.browser.current_pick == 5
        assert await page.locator("#clicks").inner_text() == "1"
        assert await page.locator("#wrong").inner_text() == "0"
        assert await page.locator("#searches").inner_text() == "1"
        assert await page.locator("#suggestion-clicks").inner_text() == "1"
        assert await page.locator("#players-tab").get_attribute("aria-selected") == "true"
        assert service.status()["worker"]["status"] == "draft_complete"
        assert service.draft.pending() == []
        receipts = [event["detail"] for event in service.manager.history()
                    if event["event"] == "browser_draft_reconciled"]
        assert len(receipts) == 1 and receipts[0]["status"] == "confirmed"
        assert receipts[0]["actual_pick"] == {"pick_no": 4, "player_id": "104", "slot": 1}
        replay = await service.submit_pick(receipts[0]["proposal_id"])
        assert replay["status"] == "confirmed"
        assert await page.locator("#clicks").inner_text() == "1"
        assert all(pick["playerId"] == -1 for pick in league["draftDetail"]["picks"])
        assert WAITING in page_requests and ENTRY in page_requests and not unexpected_requests
        assert set(json_reads) == {league_read_url(123, 2026), player_read_url(123, 2026)}
        assert launcher.await_args.args == (tmp_path / "espn-browser-profile",)
    finally:
        await service.close()
        await context.close()
        await chrome.close()
        await playwright.stop()
