"""Check the public ESPN MCP contract without opening ESPN or a browser."""

import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from fantasy_football_manager.espn_mcp import create_espn_server


TOOLS = {"espn_get_status", "espn_connect", "espn_sync", "espn_start_automation",
         "espn_stop_automation", "espn_start_standalone_worker", "espn_prepare_draft_pick",
         "espn_submit_draft_pick", "espn_reconcile_draft_pick", "espn_disconnect",
         "espn_prepare_lineup", "espn_submit_lineup", "espn_reconcile_lineup"}


async def check_contract(client):
    listing = await client.list_tools()
    assert {tool.name for tool in listing.tools} == TOOLS
    for tool in listing.tools:
        if tool.name in {"espn_submit_draft_pick", "espn_submit_lineup", "espn_start_automation", "espn_start_standalone_worker"}:
            assert tool.annotations.destructive_hint is True
            assert tool.annotations.open_world_hint is True
    response = await client.call_tool("espn_get_status", {})
    assert not response.is_error
    assert response.structured_content["browser"]["connected"] is False
    assert response.structured_content["automation_running"] is False
    assert set(response.structured_content["live_actions"]) == {"draft_pick", "set_lineup"}
    bad = await client.call_tool("espn_submit_draft_pick", {"proposal_id": "unknown"})
    assert bad.is_error
    paused = await client.call_tool("espn_stop_automation", {})
    assert not paused.is_error
    status = await client.call_tool("espn_get_status", {})
    assert status.structured_content["paused"] is True


@pytest.mark.asyncio
async def test_espn_in_memory_contract(tmp_path):
    async with Client(create_espn_server(tmp_path), read_timeout_seconds=20) as client:
        await check_contract(client)


@pytest.mark.asyncio
async def test_espn_stdio_contract(tmp_path):
    parameters = StdioServerParameters(command=sys.executable,
        args=["-m", "fantasy_football_manager.espn_mcp", "--data-dir", str(tmp_path)])
    async with Client(parameters, mode="legacy", read_timeout_seconds=20) as client:
        await check_contract(client)
