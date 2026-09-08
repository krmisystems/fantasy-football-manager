"""Local stdio MCP tools for imported fantasy football league data."""

import argparse
import json
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .demo import make_demo
from .draft import recommend_draft as draft_recommendation
from .models import ACTIONS, LeagueSnapshot, ManagerConfig
from .runtime import DraftMonitor
from .season import power_rankings, rank_waivers, recommend_lineup as lineup_recommendation
from .store import Manager


def expected_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
    return wrapped


def create_server(data_dir=None):
    manager = Manager(data_dir)
    monitor = DraftMonitor(manager)

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield {}
        finally:
            monitor.stop()

    server = MCPServer("Fantasy Football Manager", version=__version__, lifespan=lifespan,
                       instructions="Use imported league snapshots or fictional demo data. Read capabilities before preparing actions. "
                       "Use the companion ESPN MCP service for live draft observations and browser submissions. "
                       "This server's execute_demo_action changes synthetic state only. Use exact proposal confirmation in review mode.")
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    @server.tool(annotations=read)
    @expected_errors
    def get_capabilities() -> dict[str, Any]:
        """Read supported operations and the effective execution scope."""
        snapshot, config, revision, config_revision = manager.state()
        return {"version": __version__, "transport": "stdio", "input": ["imported_json", "synthetic_demo", "espn_companion"],
                "analysis": ["draft_simulation", "continuous_draft_batches", "weekly_lineup", "waivers", "weekly_power_rankings"],
                "execution_scope": "synthetic_demo_only", "live_provider_writes": False, "live_browser_monitoring": False,
                "capability_scope": "this_server", "espn_companion": {
                    "command": "fantasy-football-espn", "browser_connection_required": True,
                    "live_draft_observation": True, "live_draft_submission": True,
                    "continuous_automation": True, "standalone_worker": True,
                    "live_season_actions": ["set_lineup"], "live_acquisitions_and_trades": False,
                    "live_acceptance_test": "versioned_evidence",
                    "acceptance_report_url": (
                        "https://github.com/krmisystems/fantasy-football-manager/"
                        f"blob/v{__version__}/docs/ESPN_COMPATIBILITY.md")},
                "supported_demo_actions": list(ACTIONS[:5]), "unsupported_actions": list(ACTIONS[5:]),
                "automation_modes": ["disabled", "advisory", "review", "automatic"],
                "configured_modes": {action: config.automation.mode_for(action) for action in ACTIONS},
                "paused": config.automation.paused, "snapshot_loaded": snapshot is not None,
                "revision": revision, "config_revision": config_revision}

    @server.tool(annotations=write)
    @expected_errors
    def load_demo(mode: str = "season") -> dict[str, Any]:
        """Load fictional data. This replaces local state and resets config when the league changes."""
        snapshot, _, revision, _ = manager.state()
        if snapshot is not None and not snapshot.source.synthetic:
            raise ValueError("Use a separate data directory for the demo. Imported league state is already loaded.")
        monitor.stop()
        return manager.import_snapshot(make_demo(mode).model_dump(mode="json"), revision)

    @server.tool(annotations=write)
    @expected_errors
    def import_league_snapshot(snapshot: dict, expected_revision: int | None = None) -> dict[str, Any]:
        """Import a complete JSON snapshot. Supply the current revision when replacing state."""
        return manager.import_snapshot(snapshot, expected_revision)

    @server.tool(annotations=read)
    @expected_errors
    def get_team() -> dict[str, Any]:
        """Read the selected team and its players from the current snapshot."""
        snapshot, _, revision, _ = manager.require_state()
        team = snapshot.own_team()
        return {"revision": revision, "league_id": snapshot.league_id, "season": snapshot.season, "week": snapshot.week,
                "phase": snapshot.phase, "team": team.model_dump(mode="json"), "rules": snapshot.rules.model_dump(mode="json"),
                "players": [p.model_dump(mode="json") for p in snapshot.players if p.id in team.roster_ids + team.reserve_ids],
                "budget": snapshot.budget.model_dump(mode="json") if snapshot.budget else None}

    @server.tool(annotations=read)
    @expected_errors
    def get_source_status() -> dict[str, Any]:
        """Read observation age, source completeness, and monitor status."""
        snapshot, config, revision, _ = manager.require_state()
        limit = config.limits.max_draft_age_seconds if snapshot.phase == "draft" else config.limits.max_season_age_seconds
        return {"revision": revision, **snapshot.source.model_dump(mode="json"), "age_seconds": snapshot.age_seconds(),
                "stale": snapshot.age_seconds() > limit, "maximum_age_seconds": limit, "monitor": monitor.get()}

    @server.tool(annotations=read)
    @expected_errors
    def get_manager_config() -> dict[str, Any]:
        """Read user strategy, automation modes, limits, and config revision."""
        _, config, _, revision = manager.state()
        return {"config_revision": revision, "config": config.model_dump(mode="json")}

    @server.tool(annotations=write)
    @expected_errors
    def update_manager_config(config: dict, expected_revision: int) -> dict[str, Any]:
        """Replace the full config using its current revision. This invalidates prepared actions."""
        return manager.update_config(config, expected_revision)

    @server.tool(annotations=read)
    @expected_errors
    def recommend_draft(trials: int = 40, seed: int = 1) -> dict[str, Any]:
        """Simulate draft choices from the current snapshot. Results are estimates."""
        snapshot, config, revision, config_revision = manager.require_state()
        if type(trials) is not int or not 1 <= trials <= config.limits.batch_trials:
            raise ValueError("Trials must be positive and cannot exceed the configured batch limit.")
        result = draft_recommendation(snapshot, config, trials, seed)
        latest, _, current_revision, current_config_revision = manager.require_state()
        current = (revision, config_revision) == (current_revision, current_config_revision) and latest.age_seconds() <= config.limits.max_draft_age_seconds
        manager.record_calculation("draft", snapshot, config, revision, config_revision, result,
                                   seed=seed, requested_trials=trials, accepted=current,
                                   reason="current" if current else "state_changed" if
                                   (revision, config_revision) != (current_revision, current_config_revision) else "stale")
        return {**result, "revision": revision, "config_revision": config_revision, "current": current}

    @server.tool(annotations=write)
    @expected_errors
    def start_draft_monitor(interval_seconds: float = 2, trials: int = 40) -> dict[str, Any]:
        """Start repeated local simulation batches. Import new observations to keep results current."""
        return monitor.start(interval_seconds, trials)

    @server.tool(annotations=read)
    @expected_errors
    def get_draft_recommendations() -> dict[str, Any]:
        """Read current monitor results. Changed or stale snapshots suppress cached results."""
        return monitor.get()

    @server.tool(annotations=write)
    @expected_errors
    def stop_draft_monitor() -> dict[str, Any]:
        """Stop the monitor after its current bounded batch."""
        return monitor.stop()

    @server.tool(annotations=read)
    @expected_errors
    def recommend_lineup() -> dict[str, Any]:
        """Find the best legal weekly lineup for the selected strategy."""
        snapshot, config, revision, config_revision = manager.require_state()
        result = lineup_recommendation(snapshot, config)
        manager.record_calculation("lineup", snapshot, config, revision, config_revision, result)
        return {**result, "revision": revision, "config_revision": config_revision}

    @server.tool(annotations=read)
    @expected_errors
    def rank_waiver_candidates(limit: int = 10) -> dict[str, Any]:
        """Rank alternative acquisitions using weekly projections and configured limits."""
        snapshot, config, revision, config_revision = manager.require_state()
        result = rank_waivers(snapshot, config, limit)
        manager.record_calculation("waivers", snapshot, config, revision, config_revision, result)
        return {**result, "revision": revision, "config_revision": config_revision}

    @server.tool(annotations=read)
    @expected_errors
    def get_power_rankings() -> dict[str, Any]:
        """Compare each team's best legal weekly lineup. These are not championship odds."""
        snapshot, config, revision, config_revision = manager.require_state()
        result = power_rankings(snapshot, config)
        manager.record_calculation("power_rankings", snapshot, config, revision, config_revision, result)
        return {**result, "revision": revision, "config_revision": config_revision}

    @server.tool(annotations=write)
    @expected_errors
    def prepare_action(action: str, payload: dict) -> dict[str, Any]:
        """Check an exact synthetic action and save a revision-bound proposal. This does not execute it."""
        return manager.prepare(action, payload)

    @server.tool(annotations=write)
    @expected_errors
    def execute_demo_action(proposal_id: str, confirmation: bool = False) -> dict[str, Any]:
        """Execute a saved synthetic proposal. Set confirmation only after the user approves that proposal in review mode."""
        return manager.execute(proposal_id, confirmation)

    @server.tool(annotations=read)
    @expected_errors
    def get_action_history(limit: int = 50) -> dict[str, Any]:
        """Read local state changes and completed demo actions from the audit history."""
        return {"history": manager.history(limit)}

    @server.resource("fantasy://schema/snapshot")
    def snapshot_schema() -> str:
        """JSON schema for a complete league snapshot."""
        return json.dumps(LeagueSnapshot.model_json_schema())

    @server.resource("fantasy://schema/config")
    def config_schema() -> str:
        """JSON schema for user limits, strategies, and automation modes."""
        return json.dumps(ManagerConfig.model_json_schema())

    return server


def main():
    parser = argparse.ArgumentParser(description="Fantasy Football Manager MCP server")
    parser.add_argument("--data-dir", help="Local state directory. Defaults to FFM_DATA_DIR or the user data folder.")
    parser.add_argument("--transport", choices=["stdio"], default="stdio")
    parser.add_argument("--demo", action="store_true", help="Print a fictional weekly lineup report and exit without changing saved state.")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    if args.demo:
        result = lineup_recommendation(make_demo(), ManagerConfig())
        print(json.dumps({"data": "fictional_demo", "live_actions": False, **result}, indent=2))
        return
    create_server(args.data_dir).run(transport=args.transport)


if __name__ == "__main__":
    main()
