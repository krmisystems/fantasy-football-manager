"""Exercise public MCP behavior through in-memory and STDIO clients."""

import asyncio
import json
import subprocess
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from fantasy_football_manager.demo import make_demo
from fantasy_football_manager.mcp_server import create_server
from fantasy_football_manager.store import Manager


EXPECTED_TOOLS = {
    "get_capabilities", "load_demo", "import_league_snapshot", "get_team",
    "get_source_status", "get_manager_config", "update_manager_config",
    "recommend_draft", "start_draft_monitor", "get_draft_recommendations",
    "stop_draft_monitor", "recommend_lineup", "rank_waiver_candidates",
    "get_power_rankings", "prepare_action", "execute_demo_action", "get_action_history",
}


async def call(client, name, arguments=None):
    result = await client.call_tool(name, arguments or {})
    assert not result.is_error, result.content
    data = result.structured_content
    assert isinstance(data, dict)
    return data


@pytest.mark.asyncio
async def test_in_memory_tools_and_schemas(tmp_path):
    async with Client(create_server(tmp_path), read_timeout_seconds=20) as client:
        listing = await client.list_tools()
        assert {tool.name for tool in listing.tools} == EXPECTED_TOOLS
        capabilities = await call(client, "get_capabilities")
        assert capabilities["execution_scope"] == "synthetic_demo_only"
        assert capabilities["live_provider_writes"] is False
        assert capabilities["snapshot_loaded"] is False
        for name, model in (("snapshot", "LeagueSnapshot"), ("config", "ManagerConfig")):
            resource = await client.read_resource(f"fantasy://schema/{name}")
            schema = json.loads(resource.contents[0].text)
            assert schema["title"] == model
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_season_proposal_confirmation_and_idempotence(tmp_path):
    async with Client(create_server(tmp_path), read_timeout_seconds=20) as client:
        await call(client, "load_demo", {"mode": "season"})
        lineup = await call(client, "recommend_lineup")
        assert lineup["status"] == "ok"
        assert len(lineup["lineup"]) == 9
        rankings = await call(client, "get_power_rankings")
        assert len(rankings["rankings"]) == 14
        config = await call(client, "get_manager_config")
        config["config"]["automation"]["preset"] = "review"
        config["config"]["limits"]["min_lineup_improvement"] = 0
        await call(client, "update_manager_config", {
            "config": config["config"], "expected_revision": config["config_revision"],
        })
        proposal = await call(client, "prepare_action", {
            "action": "set_lineup", "payload": {"lineup": lineup["lineup"]},
        })
        assert proposal["requires_confirmation"] is True
        unconfirmed = await client.call_tool("execute_demo_action", {"proposal_id": proposal["proposal_id"]})
        assert unconfirmed.is_error
        assert "confirmation" in " ".join(item.text for item in unconfirmed.content if item.type == "text")
        result = await call(client, "execute_demo_action", {
            "proposal_id": proposal["proposal_id"], "confirmation": True,
        })
        replay = await call(client, "execute_demo_action", {
            "proposal_id": proposal["proposal_id"], "confirmation": True,
        })
        assert result["status"] == "executed"
        assert replay["idempotent_replay"] is True
        assert replay["revision"] == result["revision"]
        team = await call(client, "get_team")
        assert team["team"]["lineup"] == lineup["lineup"]
        history = await call(client, "get_action_history")
        assert sum(item["event"] == "demo_action_executed" for item in history["history"]) == 1


@pytest.mark.asyncio
async def test_imported_snapshot_cannot_execute_or_be_replaced_by_demo(tmp_path):
    imported = make_demo().model_dump(mode="json")
    imported["source"].update(provider="fixture-import", synthetic=False)
    async with Client(create_server(tmp_path), read_timeout_seconds=20) as client:
        await call(client, "import_league_snapshot", {"snapshot": imported})
        config = await call(client, "get_manager_config")
        config["config"]["automation"]["preset"] = "bounded_automation"
        await call(client, "update_manager_config", {
            "config": config["config"], "expected_revision": config["config_revision"],
        })
        lineup = await call(client, "recommend_lineup")
        forbidden = await client.call_tool("prepare_action", {
            "action": "set_lineup", "payload": {"lineup": lineup["lineup"]},
        })
        assert forbidden.is_error
        assert "ESPN MCP service" in " ".join(item.text for item in forbidden.content if item.type == "text")
        before = await call(client, "get_team")
        overwrite = await client.call_tool("load_demo", {"mode": "draft"})
        assert overwrite.is_error
        assert "separate data directory" in " ".join(item.text for item in overwrite.content if item.type == "text")
        after = await call(client, "get_team")
        assert after == before


@pytest.mark.asyncio
async def test_invalid_tool_input_returns_error_and_server_remains_usable(tmp_path):
    async with Client(create_server(tmp_path), read_timeout_seconds=20) as client:
        invalid = await client.call_tool("import_league_snapshot", {"snapshot": {"schema_version": 999}})
        assert invalid.is_error
        invalid_mode = await client.call_tool("load_demo", {"mode": "unsupported"})
        assert invalid_mode.is_error
        capabilities = await call(client, "get_capabilities")
        assert capabilities["snapshot_loaded"] is False


@pytest.mark.asyncio
async def test_confirmed_draft_history_cannot_be_reset_by_demo_reload(tmp_path):
    async with Client(create_server(tmp_path), read_timeout_seconds=20) as client:
        await call(client, "load_demo", {"mode": "draft"})
        config = await call(client, "get_manager_config")
        config["config"]["automation"]["preset"] = "review"
        await call(client, "update_manager_config", {
            "config": config["config"], "expected_revision": config["config_revision"],
        })
        proposal = await call(client, "prepare_action", {
            "action": "draft_pick", "payload": {"player_id": "demo-rb-001"},
        })
        await call(client, "execute_demo_action", {"proposal_id": proposal["proposal_id"], "confirmation": True})
        before = await call(client, "get_team")
        reload = await client.call_tool("load_demo", {"mode": "draft"})
        assert reload.is_error
        assert await call(client, "get_team") == before


@pytest.mark.asyncio
async def test_subprocess_stdio_handshake_and_real_tool_calls(tmp_path):
    parameters = StdioServerParameters(command=sys.executable, args=[
        "-m", "fantasy_football_manager.mcp_server", "--transport", "stdio", "--data-dir", str(tmp_path),
    ])
    async with Client(parameters, mode="legacy", read_timeout_seconds=20) as client:
        listing = await client.list_tools()
        assert {tool.name for tool in listing.tools} == EXPECTED_TOOLS
        await call(client, "load_demo", {"mode": "season"})
        lineup = await call(client, "recommend_lineup")
        assert lineup["status"] == "ok"
        assert len(lineup["lineup"]) == 9
        source = await call(client, "get_source_status")
        assert source["provider"] == "synthetic"
        assert source["stale"] is False


@pytest.mark.asyncio
async def test_draft_tools_compute_and_stop_bounded_monitor(tmp_path):
    async with Client(create_server(tmp_path), read_timeout_seconds=20) as client:
        await call(client, "load_demo", {"mode": "draft"})
        result = await call(client, "recommend_draft", {"trials": 1, "seed": 7})
        assert result["current"] is True
        assert result["trials"] == 1
        assert result["recommendations"]
        assert result["my_next_pick"] == 1
        await call(client, "start_draft_monitor", {"interval_seconds": 1, "trials": 1})
        try:
            async with asyncio.timeout(10):
                while True:
                    board = await call(client, "get_draft_recommendations")
                    assert board["error"] is None
                    if board["current"]:
                        break
                    await asyncio.sleep(.05)
            assert board["completed_trials"] >= 1
            assert board["live_browser_monitoring"] is False
            assert board["latest"]["result"]["recommendations"]
        finally:
            await call(client, "stop_draft_monitor")
            async with asyncio.timeout(10):
                while (await call(client, "get_draft_recommendations"))["running"]:
                    await asyncio.sleep(.05)


def test_cli_demo_does_not_change_persisted_state(tmp_path):
    manager = Manager(tmp_path)
    imported = make_demo().model_dump(mode="json")
    imported["source"].update(provider="fixture-import", synthetic=False)
    manager.import_snapshot(imported)
    before = manager.path.read_bytes()
    result = subprocess.run([sys.executable, "-m", "fantasy_football_manager.mcp_server",
                             "--demo", "--data-dir", str(tmp_path)],
                            check=True, capture_output=True, text=True, timeout=20)
    report = json.loads(result.stdout)
    assert report["data"] == "fictional_demo"
    assert report["live_actions"] is False
    assert manager.path.read_bytes() == before
