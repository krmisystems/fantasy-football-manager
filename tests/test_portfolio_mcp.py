"""Verify portfolio tool metadata and read-only call routing."""

import pytest
from mcp import Client

from fantasy_football_manager import portfolio_mcp


TOOLS = {"list_managed_teams", "get_managed_team", "get_managed_analysis", "search_managed_players", "list_managed_proposals"}


@pytest.mark.asyncio
async def test_five_tools_have_complete_read_only_metadata():
    async with Client(portfolio_mcp.create_server(demo=True)) as client:
        listing = await client.list_tools()
    assert {tool.name for tool in listing.tools} == TOOLS
    for tool in listing.tools:
        wire = tool.model_dump(mode="json", by_alias=True)
        assert len(wire["description"].split()) >= 35
        assert wire["annotations"]["readOnlyHint"] is True
        assert wire["annotations"]["destructiveHint"] is False
        assert wire["annotations"]["openWorldHint"] is False
        assert wire["annotations"]["idempotentHint"] is True
        assert wire["outputSchema"]["type"] == "object"
        assert all(value.get("description") for value in wire["inputSchema"]["properties"].values())
    by_name = {tool.name: tool.input_schema for tool in listing.tools}
    assert by_name["search_managed_players"]["properties"]["limit"]["maximum"] == 200
    assert by_name["get_managed_team"]["required"] == ["team_key"]


@pytest.mark.asyncio
async def test_tools_route_only_to_read_only_portfolio(monkeypatch):
    calls = []

    class Portfolio:
        def __init__(self, manifest, *, demo):
            calls.append(("init", manifest, demo))

        def overview(self, **params):
            return {"method": "overview", "params": params}

        def team(self, team_key):
            return {"method": "team", "team_key": team_key}

        def analysis(self, team_key):
            return {"method": "analysis", "team_key": team_key}

        def players(self, **params):
            return {"method": "players", "params": params}

        def proposals(self, **params):
            return {"method": "proposals", "params": params}

    monkeypatch.setattr(portfolio_mcp, "Portfolio", Portfolio)
    async with Client(portfolio_mcp.create_server("selected-manifest.json")) as client:
        cases = [
            ("list_managed_teams", {"sport": "football"}, "overview"),
            ("get_managed_team", {"team_key": "team-a"}, "team"),
            ("get_managed_analysis", {"team_key": "team-a"}, "analysis"),
            ("search_managed_players", {"query": "Pat", "limit": 2}, "players"),
            ("list_managed_proposals", {"status": "prepared", "offset": 1}, "proposals"),
        ]
        for name, arguments, method in cases:
            result = await client.call_tool(name, arguments)
            assert not result.is_error, result.content
            assert result.structured_content["method"] == method
    assert calls == [("init", "selected-manifest.json", False)]


@pytest.mark.asyncio
async def test_expected_errors_and_unexpected_errors_are_safe(monkeypatch):
    class Portfolio:
        def __init__(self, *args, **kwargs):
            pass

        def team(self, team_key):
            if team_key == "missing":
                raise ValueError("Unknown team key.")
            raise RuntimeError("/private/server/credential.json")

    monkeypatch.setattr(portfolio_mcp, "Portfolio", Portfolio)
    async with Client(portfolio_mcp.create_server()) as client:
        for key in ("missing", "broken"):
            result = await client.call_tool("get_managed_team", {"team_key": key})
            assert result.is_error
            assert "/private/server" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"offset": 100001}])
async def test_player_pagination_schema_rejects_out_of_bounds(arguments):
    async with Client(portfolio_mcp.create_server(demo=True)) as client:
        result = await client.call_tool("search_managed_players", arguments)
        assert result.is_error


@pytest.mark.asyncio
async def test_real_demo_overview_is_explicitly_fictional():
    async with Client(portfolio_mcp.create_server(demo=True)) as client:
        result = await client.call_tool("list_managed_teams", {})
        assert not result.is_error, result.content
        assert result.structured_content["demo"] is True
        team_key = result.structured_content["teams"][0]["team_key"]
        for name, args in (
            ("get_managed_team", {"team_key": team_key}),
            ("get_managed_analysis", {"team_key": team_key}),
            ("search_managed_players", {"team_key": team_key}),
            ("list_managed_proposals", {"team_key": team_key}),
        ):
            response = await client.call_tool(name, args)
            assert not response.is_error, response.content
            assert response.structured_content["demo"] is True


@pytest.mark.asyncio
async def test_unconfigured_server_is_empty_without_directory_scan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async with Client(portfolio_mcp.create_server()) as client:
        result = await client.call_tool("list_managed_teams", {})
        assert not result.is_error
        assert result.structured_content["configuration_required"] is True
        assert result.structured_content["teams"] == []
        assert not list(tmp_path.iterdir())
