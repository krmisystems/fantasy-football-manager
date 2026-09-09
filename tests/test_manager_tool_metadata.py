"""Verify the public tool contract and the state effects described by metadata."""

import asyncio
import json
import sqlite3

import pytest
from jsonschema import Draft202012Validator
from mcp import Client

from fantasy_football_manager.demo import make_demo
from fantasy_football_manager.mcp_server import create_server
from fantasy_football_manager.models import ManagerConfig, Source


TOOLS = {
    "get_capabilities", "load_demo", "import_league_snapshot", "get_team",
    "get_source_status", "get_manager_config", "update_manager_config",
    "recommend_draft", "start_draft_monitor", "get_draft_recommendations",
    "stop_draft_monitor", "recommend_lineup", "rank_waiver_candidates",
    "get_power_rankings", "prepare_action", "execute_demo_action", "get_action_history",
}
DEFAULTS = {
    "load_demo": {"mode": "season"},
    "import_league_snapshot": {"expected_revision": None},
    "recommend_draft": {"trials": 40, "seed": 1},
    "start_draft_monitor": {"interval_seconds": 2, "trials": 40},
    "rank_waiver_candidates": {"limit": 10},
    "execute_demo_action": {"confirmation": False},
    "get_action_history": {"limit": 50},
}
REQUIRED = {
    "import_league_snapshot": {"snapshot"},
    "update_manager_config": {"config", "expected_revision"},
    "prepare_action": {"action", "payload"},
    "execute_demo_action": {"proposal_id"},
}


async def call(client, name, arguments=None):
    response = await client.call_tool(name, arguments or {})
    assert not response.is_error, response.content
    assert isinstance(response.structured_content, dict)
    return response.structured_content


def database_records(data_dir):
    """Compare all persistent records, including evidence, without changing them."""
    with sqlite3.connect(data_dir / "manager.sqlite3") as db:
        return {
            table: db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in ("state", "proposals", "audit", "ffm_archive_outbox")
        }


@pytest.mark.asyncio
async def test_wire_metadata_preserves_tool_names_required_arguments_and_defaults(tmp_path):
    async with Client(create_server(tmp_path)) as client:
        listing = await client.list_tools()
    assert {tool.name for tool in listing.tools} == TOOLS
    for tool in listing.tools:
        wire = tool.model_dump(mode="json", by_alias=True)
        schema = wire["inputSchema"]
        assert schema["type"] == "object"
        assert set(schema.get("required", [])) == REQUIRED.get(tool.name, set())
        properties = schema["properties"]
        assert set(properties) == REQUIRED.get(tool.name, set()) | set(DEFAULTS.get(tool.name, {}))
        assert {name: prop["default"] for name, prop in properties.items() if "default" in prop} == DEFAULTS.get(tool.name, {})
        assert wire["description"].strip()
        for prop in properties.values():
            assert prop["description"].strip()
        # Limits remain runtime checks. Metadata adds no new scalar coercion or range policy.
        for name in ("trials", "seed", "interval_seconds", "limit", "expected_revision"):
            if name in properties:
                assert not {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"} & properties[name].keys()
        assert wire["annotations"]["openWorldHint"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "mode", "arguments", "kind"), [
    ("recommend_draft", "draft", {"trials": 1, "seed": 7}, "draft"),
    ("recommend_lineup", "season", {}, "lineup"),
    ("rank_waiver_candidates", "season", {"limit": 1}, "waivers"),
    ("get_power_rankings", "season", {}, "power_rankings"),
])
async def test_calculation_annotations_match_append_only_evidence(tmp_path, tool_name, mode, arguments, kind):
    async with Client(create_server(tmp_path)) as client:
        await call(client, "load_demo", {"mode": mode})
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        annotations = tools[tool_name].annotations
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is False
        assert annotations.idempotent_hint is False
        before = database_records(tmp_path)
        first = await call(client, tool_name, arguments)
        second = await call(client, tool_name, arguments)
        after = database_records(tmp_path)
        assert first["revision"] == second["revision"] == 1
        for table in ("state", "proposals", "audit"):
            assert before[table] == after[table]
        appended = after["ffm_archive_outbox"][len(before["ffm_archive_outbox"]):]
        assert len(appended) == 2
        assert all(row[2] == "calculation_completed" for row in appended)
        assert all(json.loads(row[3])["calculation"]["kind"] == kind for row in appended)


@pytest.mark.asyncio
async def test_read_only_getters_leave_all_records_unchanged(tmp_path):
    async with Client(create_server(tmp_path)) as client:
        await call(client, "load_demo")
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        before = database_records(tmp_path)
        for name in ("get_capabilities", "get_team", "get_source_status", "get_manager_config",
                     "get_draft_recommendations", "get_action_history"):
            assert tools[name].annotations.read_only_hint is True
            assert tools[name].annotations.idempotent_hint is True
            await call(client, name)
        assert database_records(tmp_path) == before


@pytest.mark.asyncio
async def test_replacement_config_accepts_partial_and_empty_objects_without_merging(tmp_path):
    async with Client(create_server(tmp_path)) as client:
        partial = {"automation": {"preset": "review"}, "limits": {"batch_trials": "7"}}
        result = await call(client, "update_manager_config", {"config": partial, "expected_revision": 0})
        assert result == {"status": "updated", "config_revision": 1}
        configured = await call(client, "get_manager_config")
        assert configured["config"] == ManagerConfig.model_validate(partial).model_dump(mode="json")
        second = await call(client, "update_manager_config", {"config": {"strategy": {"draft": "hero_rb"}}, "expected_revision": 1})
        assert second["config_revision"] == 2
        configured = await call(client, "get_manager_config")
        assert configured["config"]["automation"]["preset"] == "advisory"
        assert configured["config"]["limits"]["batch_trials"] == 40
        reset = await call(client, "update_manager_config", {"config": {}, "expected_revision": 2})
        assert reset["config_revision"] == 3
        before = database_records(tmp_path)
        stale = await client.call_tool("update_manager_config", {"config": partial, "expected_revision": 2})
        assert stale.is_error
        assert database_records(tmp_path) == before
        assert (await call(client, "get_manager_config"))["config"] == ManagerConfig().model_dump(mode="json")


@pytest.mark.asyncio
async def test_completed_proposal_replay_matches_idempotent_hint_after_config_change(tmp_path):
    async with Client(create_server(tmp_path)) as client:
        await call(client, "load_demo", {"mode": "draft"})
        await call(client, "update_manager_config", {
            "config": {"automation": {"preset": "review"}}, "expected_revision": 0,
        })
        proposal = await call(client, "prepare_action", {
            "action": "draft_pick", "payload": {"player_id": "demo-rb-001"},
        })
        before = database_records(tmp_path)
        refused = await client.call_tool("execute_demo_action", {"proposal_id": proposal["proposal_id"]})
        assert refused.is_error
        assert database_records(tmp_path) == before
        executed = await call(client, "execute_demo_action", {"proposal_id": proposal["proposal_id"], "confirmation": True})
        await call(client, "update_manager_config", {
            "config": {"automation": {"paused": True}}, "expected_revision": 1,
        })
        before_replay = database_records(tmp_path)
        replay = await call(client, "execute_demo_action", {"proposal_id": proposal["proposal_id"]})
        assert replay == {**executed, "idempotent_replay": True}
        assert database_records(tmp_path) == before_replay
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert tools["execute_demo_action"].annotations.idempotent_hint is True
        assert tools["execute_demo_action"].annotations.destructive_hint is True


@pytest.mark.asyncio
async def test_cached_monitor_results_are_separate_from_single_calculations(tmp_path):
    async with Client(create_server(tmp_path)) as client:
        await call(client, "load_demo", {"mode": "draft"})
        await call(client, "recommend_draft", {"trials": 1})
        cached = await call(client, "get_draft_recommendations")
        assert cached["latest"] is None
        assert cached["running"] is False
        await call(client, "start_draft_monitor", {"interval_seconds": 1, "trials": 1})
        try:
            async with asyncio.timeout(10):
                while not (await call(client, "get_draft_recommendations"))["current"]:
                    await asyncio.sleep(.02)
        finally:
            await call(client, "stop_draft_monitor")
        async with asyncio.timeout(10):
            while (await call(client, "get_draft_recommendations"))["running"]:
                await asyncio.sleep(.02)
        cached = await call(client, "get_draft_recommendations")
        assert cached["latest"]["revision"] == 1
        assert cached["current_state_trials"] >= 1
        await call(client, "update_manager_config", {"config": {}, "expected_revision": 0})
        before = database_records(tmp_path)
        changed = await call(client, "get_draft_recommendations")
        assert changed["current"] is False
        assert changed["latest"] is None
        assert changed["current_state_trials"] == 0
        assert changed["completed_trials"] == cached["completed_trials"]
        assert database_records(tmp_path) == before


@pytest.mark.asyncio
async def test_embedded_schemas_validate_fictional_snapshots_configs_and_action_payloads(tmp_path):
    async with Client(create_server(tmp_path)) as client:
        schemas = {
            tool.name: tool.model_dump(mode="json", by_alias=True)["inputSchema"]
            for tool in (await client.list_tools()).tools
        }
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    snapshot_validator = Draft202012Validator(schemas["import_league_snapshot"])
    for mode in ("draft", "season"):
        snapshot_validator.validate({"snapshot": make_demo(mode).model_dump(mode="json")})
    assert not snapshot_validator.is_valid({"snapshot": {"schema_version": 1}})
    config_validator = Draft202012Validator(schemas["update_manager_config"])
    for config in ({}, {"limits": {"batch_trials": 7}}, ManagerConfig().model_dump(mode="json")):
        config_validator.validate({"config": config, "expected_revision": 0})
    assert not config_validator.is_valid({"config": {"unknown_setting": True}, "expected_revision": 0})
    action_validator = Draft202012Validator(schemas["prepare_action"])
    for action, payload in (
        ("draft_pick", {"player_id": "demo-rb-001"}),
        ("drop_player", {"player_id": "demo-rb-001"}),
        ("set_lineup", {"lineup": {"RB1": "demo-rb-001"}}),
        ("waiver_claim", {"player_id": "demo-rb-099", "drop_id": None, "bid": 1}),
        ("free_agent_add", {"player_id": "demo-rb-099"}),
    ):
        # Structural schemas describe shapes. Runtime policy still checks roster legality and action-specific limits.
        action_validator.validate({"action": action, "payload": payload})
    assert not action_validator.is_valid({"action": "draft_pick", "payload": {"unknown": "demo-rb-001"}})
    assert not action_validator.is_valid({"action": "trade_offer", "payload": {"player_id": "demo-rb-001"}})


@pytest.mark.asyncio
async def test_schema_metadata_keeps_runtime_coercion_and_snapshot_revision_checks(tmp_path):
    snapshot = make_demo().model_dump(mode="json")
    season = snapshot["season"]
    snapshot["season"] = str(season)
    async with Client(create_server(tmp_path)) as client:
        imported = await call(client, "import_league_snapshot", {"snapshot": snapshot})
        assert imported["revision"] == 1
        assert (await call(client, "get_team"))["season"] == season
        before = database_records(tmp_path)
        conflict = await client.call_tool("import_league_snapshot", {"snapshot": snapshot})
        assert conflict.is_error
        assert database_records(tmp_path) == before
        updated = await call(client, "import_league_snapshot", {"snapshot": snapshot, "expected_revision": 1})
        assert updated["revision"] == 2
        assert updated["config_reset"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("provider", "expected_scope"), [
    ("espn_browser", "selected_team"),
    ("fixture-import", "league"),
])
async def test_lock_scope_schema_omits_a_default_that_depends_on_provider(tmp_path, provider, expected_scope):
    async with Client(create_server(tmp_path)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        snapshot_schema = tools["import_league_snapshot"].input_schema["properties"]["snapshot"]
        scope_schema = snapshot_schema["properties"]["source"]["properties"]["locks_scope"]
        assert "default" not in scope_schema
        assert set(scope_schema["enum"]) == {"league", "selected_team"}
        resource = await client.read_resource("fantasy://schema/snapshot")
        original_schema = json.loads(resource.contents[0].text)
        assert original_schema["$defs"]["Source"]["properties"]["locks_scope"]["default"] == "league"
    observed = make_demo().source.model_dump(mode="json")
    observed.pop("locks_scope")
    observed["provider"] = provider
    assert Source.model_validate(observed).locks_scope == expected_scope
    # An explicit observation still takes precedence over either provider default.
    observed["locks_scope"] = "league"
    assert Source.model_validate(observed).locks_scope == "league"
