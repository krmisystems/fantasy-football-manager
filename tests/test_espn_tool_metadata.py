"""Verify ESPN discovery metadata and argument forwarding without a browser."""

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
    "espn_disconnect": ({}, []),
}


async def test_espn_discovery_preserves_input_contract(tmp_path):
    """Descriptions must not add constraints or change defaults in tools/list."""
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
    for name in ("espn_submit_draft_pick", "espn_submit_lineup"):
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
                   "reconcile_lineup", "close"):
        setattr(service, method, AsyncMock(return_value={"status": "recorded"}))
    monkeypatch.setattr(espn_mcp, "ESPNService", lambda data_dir: service)
    return service


@pytest.mark.parametrize("tool, arguments, method, positional, keywords", [
    ("espn_get_status", {}, "status", (), {}),
    ("espn_connect", {"league_id": "101", "team_id": "2", "season": 2026},
     "connect", ("101", "2", 2026, None, False), {"phase": "draft", "week": 1}),
    ("espn_connect", {"league_id": "101", "team_id": "2", "season": 2026,
                      "cdp_url": "http://127.0.0.1:9222", "headless": True, "phase": "season", "week": 4},
     "connect", ("101", "2", 2026, "http://127.0.0.1:9222", True), {"phase": "season", "week": 4}),
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
    ("espn_disconnect", {}, "close", (), {}),
])
async def test_espn_metadata_keeps_service_arguments(recorded_service, tmp_path, tool, arguments, method, positional, keywords):
    """Call through MCP validation, then check the unchanged service boundary."""
    async with Client(espn_mcp.create_espn_server(tmp_path)) as client:
        result = await client.call_tool(tool, arguments)
        assert not result.is_error
        assert result.structured_content == {"status": "recorded"}
        getattr(recorded_service, method).assert_called_once_with(*positional, **keywords)


@pytest.mark.parametrize("exception", [ValueError, RuntimeError])
async def test_espn_metadata_preserves_service_error_details(recorded_service, tmp_path, exception):
    """Described limits remain service checks, with their existing MCP errors."""
    recorded_service.start.side_effect = exception("Use an observation interval from 1 to 60 seconds.")
    async with Client(espn_mcp.create_espn_server(tmp_path)) as client:
        result = await client.call_tool("espn_start_automation", {"interval_seconds": 0, "trials": 40})
    recorded_service.start.assert_awaited_once_with(0, 40)
    assert result.is_error
    assert any("Use an observation interval from 1 to 60 seconds." in item.text for item in result.content)
