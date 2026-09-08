"""Test the season adapter in isolated Chrome with fictional local HTML and data."""

from copy import deepcopy
import os

import pytest

from fantasy_football_manager.browser_lineup import BrowserLineup
from fantasy_football_manager.espn_season_browser import ESPNSeasonBrowser
from fantasy_football_manager.espn_season_data import season_read_url, season_player_read_url
from fantasy_football_manager.models import ManagerConfig
from fantasy_football_manager.store import Manager
from test_espn_season_data import fixture


pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.environ.get("FFM_BROWSER_TESTS") != "1",
                    reason="Set FFM_BROWSER_TESTS=1 for isolated Chrome tests.")]
URL = "https://fantasy.espn.com/football/team?leagueId=123&teamId=1&seasonId=2026&scoringPeriodId=1"


@pytest.fixture
async def case(tmp_path, monkeypatch):
    from playwright.async_api import async_playwright
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(channel="chrome", headless=True)
    context = await browser.new_context(service_workers="block")
    page = await context.new_page()
    league, pool = fixture()
    for entry in pool["players"]:
        if entry["id"] == 103:
            entry["player"]["stats"][1]["stats"] = {"53": 10, "24": 120}
    html = '''<!doctype html><html lang="en"><title>Fictional weekly team</title>
    <a href="/football/team?leagueId=123&amp;teamId=1&amp;seasonId=2026">My Team</a>
    <table><tr><td id="week">NFL Week 1</td></tr></table>
    <div id="controls"></div><output id="swaps">0</output><script>
    const players=['Runner Alpha','Receiver Beta','Runner Gamma','Reserve Delta'];
    function normal(){document.getElementById('controls').replaceChildren(...players.map(name=>{
      const b=document.createElement('button');b.textContent='Select '+name+' to move';
      b.onclick=()=>select(name);return b;}));}
    function select(name){const box=document.getElementById('controls');box.replaceChildren();
      const cancel=document.createElement('button');cancel.textContent='Cancel Move of '+name;cancel.onclick=normal;box.append(cancel);
      const confirm=document.createElement('button');confirm.textContent='Confirm move of Runner Alpha to Running Back';
      confirm.onclick=()=>{document.getElementById('swaps').textContent=String(Number(document.getElementById('swaps').textContent)+1);normal();};
      box.append(confirm);}
    normal();</script></html>'''
    requests = []

    async def local_page(route):
        requests.append(route.request.url)
        await route.fulfill(status=200, content_type="text/html", body=html)

    await context.route("**/*", local_page)
    await page.goto(URL)
    adapter = ESPNSeasonBrowser(tmp_path, week=1)
    adapter._context, adapter._page, adapter._scope = context, page, ("123", "1", 2026)

    async def local_json(url, headers=None):
        if url == season_player_read_url(123, 2026, 1):
            return deepcopy(pool)
        assert url == season_read_url(123, 2026, 1)
        result = deepcopy(league)
        if await page.locator("#swaps").inner_text() != "0":
            for entry in result["teams"][0]["roster"]["entries"]:
                if entry["playerId"] in {101, 103}:
                    entry["lineupSlotId"] = 20 if entry["playerId"] == 101 else 2
        return result

    monkeypatch.setattr(adapter, "_read_json", local_json)
    manager = Manager(tmp_path)
    manager.import_snapshot((await adapter.observe()).model_dump(mode="json"))
    manager.update_config(ManagerConfig(automation={"preset": "review"}).model_dump(mode="json"), 0)
    lineup = BrowserLineup(manager)
    try:
        yield adapter, page, manager, lineup, requests
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()


async def test_exact_confirm_click_and_api_roster_verification(case):
    adapter, page, manager, lineup, requests = case
    proposal = lineup.prepare({"RB1": "103", "FLEX1": "102"})
    permit = lineup.authorize(proposal["proposal_id"], confirmation=True)
    validations = []
    def validate(value, fresh):
        validations.append((value["proposal_id"], fresh.week))
        return lineup.validate_permit(value, fresh)

    adapter.permit_validator = validate
    result = await adapter.submit_lineup(permit)
    assert result["clicked"] and not result["retry_allowed"]
    assert await page.locator("#swaps").inner_text() == "1"
    assert validations == [(proposal["proposal_id"], 1)]
    assert lineup.reconcile(proposal["proposal_id"], result["snapshot"])["status"] == "confirmed"
    assert manager.state()[0].own_team().lineup == {"RB1": "103", "FLEX1": "102"}
    assert requests == [URL]
    with pytest.raises(ValueError, match="already attempted"):
        await adapter.submit_lineup(permit)
    assert await page.locator("#swaps").inner_text() == "1"


async def test_rejected_final_permit_cancels_selection_without_confirm(case):
    adapter, page, manager, lineup, _ = case
    proposal = lineup.prepare({"RB1": "103", "FLEX1": "102"})
    permit = lineup.authorize(proposal["proposal_id"], confirmation=True)

    def reject(*args):
        raise ValueError("Config was paused")

    adapter.permit_validator = reject
    result = await adapter.submit_lineup(permit)
    assert not result["clicked"] and result["status"] == "awaiting_verification"
    assert await page.locator("#swaps").inner_text() == "0"
    assert await page.get_by_role("button", name="Select Runner Gamma to move", exact=True).count() == 1
    assert lineup.pending()


async def test_different_visible_week_prevents_a_lineup_claim(case):
    adapter, page, _, _, _ = case
    await page.locator("#week").evaluate("element => element.textContent = 'NFL Week 2'")
    with pytest.raises(ValueError, match="visible lineup week"):
        await adapter.observe()
    assert await page.locator("#swaps").inner_text() == "0"


@pytest.mark.parametrize("decision", [False, None, {"should_click": False}])
async def test_non_authorizing_validator_result_never_confirms(case, decision):
    adapter, page, _, lineup, _ = case
    proposal = lineup.prepare({"RB1": "103", "FLEX1": "102"})
    permit = lineup.authorize(proposal["proposal_id"], confirmation=True)
    adapter.permit_validator = lambda value, fresh: decision

    result = await adapter.submit_lineup(permit)

    assert not result["clicked"] and not result["retry_allowed"]
    assert "did not authorize" in result["error"]
    assert await page.locator("#swaps").inner_text() == "0"
    assert await page.get_by_role("button", name="Select Runner Gamma to move", exact=True).count() == 1
    assert lineup.pending()


async def test_extra_visible_roster_player_blocks_stale_api_ownership(case):
    adapter, page, _, _, _ = case
    await page.locator("#controls").evaluate("""element => {
        const button = document.createElement('button');
        button.textContent = 'Select Unexpected Fictional Player to move';
        element.append(button);
    }""")
    with pytest.raises(ValueError, match="outside the complete selected-team roster"):
        await adapter.observe()
    assert await page.locator("#swaps").inner_text() == "0"


async def test_missing_move_control_does_not_report_verified_locks(case):
    adapter, page, _, _, _ = case
    await page.get_by_role("button", name="Select Runner Gamma to move", exact=True).evaluate("element => element.remove()")
    snapshot = await adapter.observe()
    assert not snapshot.source.locks_verified
    assert next(player for player in snapshot.players if player.id == "103").locked
    assert await page.locator("#swaps").inner_text() == "0"


async def test_reordered_running_back_slots_keep_the_exact_exchange(case, monkeypatch):
    adapter, page, manager, lineup, _ = case
    league, pool = fixture()
    league["settings"]["rosterSettings"]["lineupSlotCounts"]["2"] = 2
    extra = next(entry for entry in pool["players"] if entry["id"] == 109)
    extra["onTeamId"] = 1
    league["teams"][0]["roster"]["entries"].append(
        {"playerId": 109, "lineupSlotId": 2, "playerPoolEntry": deepcopy(extra)})
    next(entry for entry in pool["players"] if entry["id"] == 103)["player"]["stats"][1]["stats"] = {"53": 10, "24": 120}
    await page.evaluate("players.push('Available Theta'); normal()")
    state = {"reorder": False}

    async def local_json(url, headers=None):
        if url == season_player_read_url(123, 2026, 1):
            return deepcopy(pool)
        assert url == season_read_url(123, 2026, 1)
        result = deepcopy(league)
        entries = result["teams"][0]["roster"]["entries"]
        if await page.locator("#swaps").inner_text() != "0":
            for entry in entries:
                if entry["playerId"] in {101, 103}:
                    entry["lineupSlotId"] = 20 if entry["playerId"] == 101 else 2
        if state["reorder"]:
            indices = [index for index, entry in enumerate(entries) if entry["lineupSlotId"] == 2]
            ordered = sorted((entries[index] for index in indices), key=lambda entry: entry["playerId"], reverse=True)
            for index, entry in zip(indices, ordered):
                entries[index] = entry
        return result

    monkeypatch.setattr(adapter, "_read_json", local_json)
    adapter._players_payload = None
    manager.import_snapshot((await adapter.observe()).model_dump(mode="json"), manager.state()[2])
    target = {"RB1": "103", "RB2": "109", "FLEX1": "102"}
    proposal = lineup.prepare(target)
    permit = lineup.authorize(proposal["proposal_id"], confirmation=True)
    assert permit["destination_slot"] == "RB1" and permit["outgoing_player_id"] == "101"
    state["reorder"] = True
    assert (await adapter.observe()).own_team().lineup["RB2"] == "101"
    adapter.permit_validator = lineup.validate_permit

    result = await adapter.submit_lineup(permit)

    assert result["clicked"] and await page.locator("#swaps").inner_text() == "1"
    assert lineup.reconcile(proposal["proposal_id"], result["snapshot"])["status"] == "confirmed"
    current = manager.state()[0].own_team().lineup
    assert {current["RB1"], current["RB2"]} == {"103", "109"}
    assert current["FLEX1"] == "102"
