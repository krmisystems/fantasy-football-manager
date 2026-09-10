"""Verify ESPN discovery metadata and argument forwarding without a browser."""

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from mcp import Client
import pytest

from fantasy_football_manager import espn_mcp


EXPECTED_INPUTS = {
    "espn_get_status": ({}, []),
    "espn_connect": ({
        "league_id": {"type": "string"},
        "team_id": {"type": "string"},
        "season": {"type": "integer"},
        "cdp_url": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "headless": {"type": "boolean", "default": False},
        "phase": {"type": "string", "default": "draft"},
        "week": {"type": "integer", "default": 1},
        "transport": {"anyOf": [{"enum": ["http", "browser"], "type": "string"}, {"type": "null"}], "default": None},
        "auto_rollover": {"type": "boolean", "default": False},
    }, ["league_id", "team_id", "season"]),
    "espn_sync": ({}, []),
    "espn_start_automation": ({
        "interval_seconds": {"type": "number", "default": 2},
        "trials": {"type": "integer", "default": 40},
    }, []),
    "espn_stop_automation": ({}, []),
    "espn_start_standalone_worker": ({}, []),
    "espn_prepare_draft_pick": ({"player_id": {"type": "string"}}, ["player_id"]),
    "espn_submit_draft_pick": ({
        "proposal_id": {"type": "string"}, "confirmation": {"type": "boolean", "default": False},
    }, ["proposal_id"]),
    "espn_reconcile_draft_pick": ({"proposal_id": {"type": "string"}}, ["proposal_id"]),
    "espn_prepare_lineup": ({
        "lineup": {"type": "object", "additionalProperties": {"type": "string"}},
    }, ["lineup"]),
    "espn_submit_lineup": ({
        "proposal_id": {"type": "string"}, "confirmation": {"type": "boolean", "default": False},
    }, ["proposal_id"]),
    "espn_reconcile_lineup": ({"proposal_id": {"type": "string"}}, ["proposal_id"]),
    "espn_prepare_season_action": ({
        "action": {"enum": ["set_lineup", "free_agent_add", "waiver_claim", "drop_player", "move_to_ir", "activate_from_ir"], "type": "string"},
        "player_id": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "drop_id": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "bid": {"type": "integer", "minimum": 0, "default": 0},
        "lineup": {"anyOf": [{"type": "object", "additionalProperties": {"type": "string"}}, {"type": "null"}], "default": None},
        "repair_player_id": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
    }, ["action"]),
    "espn_submit_season_action": ({
        "proposal_id": {"type": "string"}, "confirmation": {"type": "boolean", "default": False},
    }, ["proposal_id"]),
    "espn_reconcile_season_action": ({"proposal_id": {"type": "string"}}, ["proposal_id"]),
    "espn_disconnect": ({}, []),
}


async def test_espn_discovery_preserves_input_contract(tmp_path):
    """Verify the 16-tool contract and preserve defaults for existing tool arguments."""
    async with Client(espn_mcp.create_espn_server(tmp_path)) as client:
        listing = await client.list_tools()
    assert {tool.name for tool in listing.tools} == set(EXPECTED_INPUTS)
    for tool in listing.tools:
        expected, required = EXPECTED_INPUTS[tool.name]
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert schema.get("required", []) == required
        assert set(schema["properties"]) == set(expected)
        for name, definition in schema["properties"].items():
            assert definition.get("description", "").strip(), (tool.name, name)
            assert {key: value for key, value in definition.items()
                    if key not in {"title", "description"}} == expected[name]
        assert tool.description and "returns" in tool.description.lower()
        referenced = set(re.findall(r"\bespn_[a-z_]+\b", tool.description))
        assert referenced <= set(EXPECTED_INPUTS)

    tools = {tool.name: tool for tool in listing.tools}
    for name in ("espn_submit_draft_pick", "espn_submit_lineup", "espn_submit_season_action"):
        assert tools[name].annotations.idempotent_hint is True
        assert tools[name].annotations.destructive_hint is True
        assert tools[name].annotations.open_world_hint is True
    for name in ("espn_start_automation", "espn_start_standalone_worker"):
        assert tools[name].annotations.idempotent_hint is False
        assert tools[name].annotations.destructive_hint is True
        assert tools[name].annotations.open_world_hint is True
    assert tools["espn_get_status"].annotations.read_only_hint is True
    # Local configuration and snapshot replacements count as environment changes,
    # even when a tool does not submit a fantasy action to ESPN.
    for name, tool in tools.items():
        if name == "espn_get_status":
            continue
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is True
        assert tool.annotations.open_world_hint is (name != "espn_stop_automation")


@pytest.fixture
def recorded_service(monkeypatch):
    service = SimpleNamespace(status=Mock(return_value={"status": "recorded"}))
    for method in ("connect", "sync", "start", "pause", "start_standalone", "prepare_pick",
                   "submit_pick", "reconcile_pick", "prepare_lineup", "submit_lineup",
                   "reconcile_lineup", "prepare_season_action", "submit_season_action", "close"):
        setattr(service, method, AsyncMock(return_value={"status": "recorded"}))
    service.operation = asyncio.Lock()
    service.http_actions = SimpleNamespace(get=Mock(return_value={"status": "recorded"}),
                                           reconcile=Mock(return_value={"status": "confirmed"}))
    service.browser = SimpleNamespace(observe=AsyncMock())
    monkeypatch.setattr(espn_mcp, "ESPNService", lambda data_dir: service)
    return service


@pytest.mark.parametrize("tool, arguments, method, positional, keywords", [
    ("espn_get_status", {}, "status", (), {}),
    ("espn_connect", {"league_id": "101", "team_id": "2", "season": 2026},
     "connect", ("101", "2", 2026, None, False), {"phase": "draft", "week": 1, "transport": None, "auto_rollover": False}),
    ("espn_connect", {"league_id": "101", "team_id": "2", "season": 2026,
                      "cdp_url": "http://127.0.0.1:9222", "headless": True, "phase": "season", "week": 4},
     "connect", ("101", "2", 2026, "http://127.0.0.1:9222", True), {"phase": "season", "week": 4, "transport": None, "auto_rollover": False}),
    ("espn_connect", {"league_id": "101", "team_id": "2", "season": 2026, "phase": "season",
                      "transport": "http", "auto_rollover": True},
     "connect", ("101", "2", 2026, None, False), {"phase": "season", "week": 1, "transport": "http", "auto_rollover": True}),
    ("espn_sync", {}, "sync", (), {}),
    ("espn_start_automation", {}, "start", (2, 40), {}),
    ("espn_start_automation", {"interval_seconds": 1.5, "trials": 12}, "start", (1.5, 12), {}),
    ("espn_stop_automation", {}, "pause", (), {}),
    ("espn_start_standalone_worker", {}, "start_standalone", (), {}),
    ("espn_prepare_draft_pick", {"player_id": "player-1"}, "prepare_pick", ("player-1",), {}),
    ("espn_submit_draft_pick", {"proposal_id": "proposal-1"}, "submit_pick", ("proposal-1", False), {}),
    ("espn_submit_draft_pick", {"proposal_id": "proposal-1", "confirmation": True},
     "submit_pick", ("proposal-1", True), {}),
    ("espn_reconcile_draft_pick", {"proposal_id": "proposal-1"}, "reconcile_pick", ("proposal-1",), {}),
    ("espn_prepare_lineup", {"lineup": {"QB1": "player-1", "FLEX1": "player-2"}},
     "prepare_lineup", ({"QB1": "player-1", "FLEX1": "player-2"},), {}),
    ("espn_submit_lineup", {"proposal_id": "proposal-2"}, "submit_lineup", ("proposal-2", False), {}),
    ("espn_submit_lineup", {"proposal_id": "proposal-2", "confirmation": True},
     "submit_lineup", ("proposal-2", True), {}),
    ("espn_reconcile_lineup", {"proposal_id": "proposal-2"}, "reconcile_lineup", ("proposal-2",), {}),
    ("espn_prepare_season_action", {"action": "set_lineup", "lineup": {"RB1": "103"}},
     "prepare_season_action", ("set_lineup", {"lineup": {"RB1": "103"}}), {}),
    ("espn_prepare_season_action", {"action": "set_lineup", "lineup": {"RB1": "103"}, "repair_player_id": "101"},
     "prepare_season_action", ("set_lineup", {"lineup": {"RB1": "103"}, "repair_player_id": "101"}), {}),
    ("espn_prepare_season_action", {"action": "free_agent_add", "player_id": "109"},
     "prepare_season_action", ("free_agent_add", {"player_id": "109", "drop_id": None, "bid": 0}), {}),
    ("espn_prepare_season_action", {"action": "waiver_claim", "player_id": "109", "drop_id": "103", "bid": 3, "repair_player_id": "101"},
     "prepare_season_action", ("waiver_claim", {"player_id": "109", "drop_id": "103", "bid": 3, "repair_player_id": "101"}), {}),
    ("espn_prepare_season_action", {"action": "drop_player", "player_id": "103"},
     "prepare_season_action", ("drop_player", {"player_id": "103"}), {}),
    ("espn_prepare_season_action", {"action": "move_to_ir", "player_id": "103"},
     "prepare_season_action", ("move_to_ir", {"player_id": "103"}), {}),
    ("espn_prepare_season_action", {"action": "activate_from_ir", "player_id": "104"},
     "prepare_season_action", ("activate_from_ir", {"player_id": "104"}), {}),
    ("espn_submit_season_action", {"proposal_id": "proposal-http"}, "submit_season_action", ("proposal-http", False), {}),
    ("espn_submit_season_action", {"proposal_id": "proposal-http", "confirmation": True},
     "submit_season_action", ("proposal-http", True), {}),
    ("espn_disconnect", {}, "close", (), {}),
])
async def test_espn_metadata_keeps_service_arguments(recorded_service, tmp_path, tool, arguments, method, positional, keywords):
    """Call through MCP validation, then check the unchanged service boundary."""
    async with Client(espn_mcp.create_espn_server(tmp_path)) as client:
        result = await client.call_tool(tool, arguments)
        assert not result.is_error
        assert result.structured_content == {"status": "recorded"}
        getattr(recorded_service, method).assert_called_once_with(*positional, **keywords)


@pytest.mark.parametrize("arguments", [
    {"action": "set_lineup"},
    {"action": "set_lineup", "lineup": {"RB1": "103"}, "player_id": "103"},
    {"action": "set_lineup", "lineup": {"RB1": "103"}, "drop_id": "101"},
    {"action": "set_lineup", "lineup": {"RB1": "103"}, "bid": 1},
    {"action": "free_agent_add"},
    {"action": "free_agent_add", "player_id": "109", "lineup": {"RB1": "103"}},
    {"action": "drop_player", "player_id": "103", "drop_id": "101"},
    {"action": "drop_player", "player_id": "103", "repair_player_id": "101"},
    {"action": "move_to_ir", "player_id": "103", "bid": 1},
    {"action": "activate_from_ir", "player_id": "104", "lineup": {}},
    {"action": "trade_offer", "player_id": "103"},
    {"action": "waiver_claim", "player_id": "109", "bid": -1},
    {"action": "waiver_claim", "player_id": "109", "bid": 1.5},
    {"action": "waiver_claim", "player_id": "109", "bid": True},
])
async def test_invalid_season_argument_combinations_fail_before_service(recorded_service, tmp_path, arguments):
    async with Client(espn_mcp.create_espn_server(tmp_path)) as client:
        result = await client.call_tool("espn_prepare_season_action", arguments)
    assert result.is_error
    recorded_service.prepare_season_action.assert_not_awaited()
    recorded_service.submit_season_action.assert_not_awaited()
    recorded_service.browser.observe.assert_not_awaited()


async def test_prepare_dispatch_never_submits_and_docs_explain_local_proposal_only(recorded_service, tmp_path):
    async with Client(espn_mcp.create_espn_server(tmp_path)) as client:
        listing = await client.list_tools()
        description = next(tool.description for tool in listing.tools if tool.name == "espn_prepare_season_action")
        result = await client.call_tool("espn_prepare_season_action", {"action": "free_agent_add", "player_id": "109"})
    assert not result.is_error
    recorded_service.prepare_season_action.assert_awaited_once()
    recorded_service.submit_season_action.assert_not_awaited()
    assert "without submitting" in description and "does not send a transaction request" in description
    assert "local snapshots" in description and "proposal evidence" in description


@pytest.mark.parametrize("status", ["confirmed", "rejected", "cancelled", "not_submitted"])
async def test_settled_http_reconciliation_returns_cached_result_without_observation(recorded_service, tmp_path, status):
    recorded_service.http_actions.get.return_value = {"status": status}
    async with Client(espn_mcp.create_espn_server(tmp_path)) as client:
        result = await client.call_tool("espn_reconcile_season_action", {"proposal_id": "proposal-http"})
    assert not result.is_error and result.structured_content == {"status": status}
    recorded_service.http_actions.get.assert_called_once_with("proposal-http")
    recorded_service.browser.observe.assert_not_awaited()
    recorded_service.http_actions.reconcile.assert_not_called()
    recorded_service.submit_season_action.assert_not_awaited()


@pytest.mark.parametrize("status", ["awaiting_verification", "pending_waiver"])
async def test_pending_http_reconciliation_observes_without_submission(recorded_service, tmp_path, status):
    recorded_service.http_actions.get.return_value = {"status": status}
    snapshot = SimpleNamespace(model_dump=Mock(return_value={"fictional": "observation"}))
    recorded_service.browser.observe.return_value = snapshot
    async with Client(espn_mcp.create_espn_server(tmp_path)) as client:
        result = await client.call_tool("espn_reconcile_season_action", {"proposal_id": "proposal-http"})
    assert not result.is_error and result.structured_content == {"status": "confirmed"}
    recorded_service.browser.observe.assert_awaited_once()
    recorded_service.http_actions.reconcile.assert_called_once_with("proposal-http", {"fictional": "observation"})
    recorded_service.submit_season_action.assert_not_awaited()


@pytest.mark.parametrize("exception", [ValueError, RuntimeError])
async def test_espn_metadata_preserves_service_error_details(recorded_service, tmp_path, exception):
    """Described limits remain service checks, with their existing MCP errors."""
    recorded_service.start.side_effect = exception("Use an observation interval from 1 to 60 seconds.")
    async with Client(espn_mcp.create_espn_server(tmp_path)) as client:
        result = await client.call_tool("espn_start_automation", {"interval_seconds": 0, "trials": 40})
    recorded_service.start.assert_awaited_once_with(0, 40)
    assert result.is_error
    assert any("Use an observation interval from 1 to 60 seconds." in item.text for item in result.content)
