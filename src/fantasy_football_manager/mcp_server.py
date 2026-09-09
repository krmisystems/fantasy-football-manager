"""Local stdio MCP tools for imported fantasy football league data."""

import argparse
import json
from contextlib import asynccontextmanager
from functools import wraps
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field, WithJsonSchema

from . import __version__
from .demo import make_demo
from .draft import recommend_draft as draft_recommendation
from .models import ACTIONS, LeagueSnapshot, ManagerConfig
from .policy import AddPayload, LineupPayload, PickPayload
from .runtime import DraftMonitor
from .season import power_rankings, rank_waivers, recommend_lineup as lineup_recommendation
from .store import Manager
from .tool_schema import model_input_schema


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
    snapshot_input = model_input_schema(LeagueSnapshot)
    for name, description in {
        "league_id": "Stable league identifier from the observation provider.",
        "team_id": "Selected team's ID. Its draft slot must match rules.slot.",
        "season": "Season year for this league context.",
        "week": "Scoring week used by weekly projections and season actions.",
        "phase": "Use draft for pick analysis or season for weekly roster analysis.",
        "source": "Observation provenance and freshness. Timestamps require a UTC offset and must describe the actual observation.",
        "rules": "League roster rules. Draft rounds equal starter slots plus bench slots. Injured reserve slots are separate.",
        "players": "Unique available and rostered player identities. Projections must already use the league's scoring system.",
        "teams": "Every league team, with unique IDs and draft slots. Roster IDs must reference known players with unique ownership.",
        "picks": "Complete ordered draft history, starting at pick 1 with no gaps. Draft rosters must match these picks.",
        "budget": "Selected team's current FAAB balance, spending, and pending commitments. Acquisitions require known budget and move counts.",
    }.items():
        snapshot_input["properties"][name]["description"] = description
    for name, description in {
        "observed_at": "Timestamp when the source was observed, with a UTC offset.",
        "projections_observed_at": "Timestamp when projections were observed, with a UTC offset. Draft, lineup, and acquisition checks require a known fresh timestamp.",
        "complete": "True only when the observation contains the complete required league context and draft history.",
        "locks_verified": "True only when current player lock states have been verified for locks_scope.",
        "locks_scope": "Extent of verified player locks. ESPN browser observations without this field default to selected_team.",
        "synthetic": "True only for fictional observations. Demo actions also require provider='synthetic'.",
    }.items():
        snapshot_input["properties"]["source"]["properties"][name]["description"] = description
    snapshot_input["properties"]["source"]["properties"]["locks_scope"].pop("default", None)
    snapshot_input["properties"]["players"]["items"]["properties"]["projection"]["description"] = (
        "Full-season fantasy projection. Draft data requires a value except for verified opponent picks retained as identities."
    )
    config_input = model_input_schema(ManagerConfig)
    for name, description in {
        "automation": "Preset, pause state, and action modes. Only custom uses the per-action map, which must include every supported action.",
        "limits": "User limits on freshness, simulation batches, roster moves, protected players, drops, and FAAB spending.",
        "strategy": "Draft, season, and waiver objectives. Strategy preferences never override user limits.",
    }.items():
        config_input["properties"][name]["description"] = description
    pick_input = model_input_schema(PickPayload)
    pick_input["description"] = "Payload for draft_pick or drop_player."
    pick_input["properties"]["player_id"]["description"] = "Exact player ID from the saved snapshot."
    lineup_input = model_input_schema(LineupPayload)
    lineup_input["description"] = "Payload for set_lineup."
    lineup_input["properties"]["lineup"]["description"] = (
        "Every starter slot mapped to a unique active-roster player ID, using slot keys such as QB1, RB1, and FLEX1."
    )
    add_input = model_input_schema(AddPayload)
    add_input["description"] = "Payload for waiver_claim or free_agent_add."
    for name, description in {
        "player_id": "Exact unrostered player ID to acquire from the saved snapshot.",
        "drop_id": "Optional active-roster player ID to drop. A full roster requires an allowed drop.",
        "bid": "Nonnegative integer FAAB bid, subject to user budget limits. free_agent_add requires zero.",
    }.items():
        add_input["properties"][name]["description"] = description
    payload_input = {"anyOf": [pick_input, lineup_input, add_input]}

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
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
    replace = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)
    execute = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
    stop = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @server.tool(annotations=read)
    @expected_errors
    def get_capabilities() -> dict[str, Any]:
        """Read this server's capabilities before selecting analysis or execution tools.

        Returns supported actions, effective automation modes, pause state, snapshot presence, and state and configuration revisions.
        This server analyzes imported data and executes synthetic demo actions only.
        The response separately describes the ESPN companion for live observations, draft picks, and lineup changes.
        Works before a snapshot is loaded and does not change saved state.
        """
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

    @server.tool(annotations=replace)
    @expected_errors
    def load_demo(
        mode: Annotated[str, Field(description="Fictional scenario to load: 'season' for weekly tools or 'draft' for draft simulations.", json_schema_extra={"enum": ["season", "draft"]})] = "season",
    ) -> dict[str, Any]:
        """Load a fictional scenario for local testing or demonstrations.

        Use import_league_snapshot for your own data.
        Requires an empty data directory or existing synthetic state and preserves confirmed draft history checks.
        Stops the local draft monitor, replaces the snapshot, and resets configuration when the league changes.
        Records the import and returns status='imported', revision, config_revision, and config_reset.
        This tool does not connect to ESPN.
        """
        snapshot, _, revision, _ = manager.state()
        if snapshot is not None and not snapshot.source.synthetic:
            raise ValueError("Use a separate data directory for the demo. Imported league state is already loaded.")
        monitor.stop()
        return manager.import_snapshot(make_demo(mode).model_dump(mode="json"), revision)

    @server.tool(annotations=replace)
    @expected_errors
    def import_league_snapshot(
        snapshot: Annotated[dict, WithJsonSchema(snapshot_input), Field(description="Complete league observation. Use fantasy://schema/snapshot for fields, defaults, and rules. This is replacement data, not a patch.")],
        expected_revision: Annotated[int | None, Field(description="Current snapshot revision from get_team or get_capabilities. Omit only for the first import into empty state.")] = None,
    ) -> dict[str, Any]:
        """Validate and save a complete league snapshot supplied by the caller.

        Use the ESPN companion to fetch live observations or load_demo for fictional data.
        Replacement requires the current snapshot revision and must preserve observation order, confirmed draft history, and pending browser action context.
        Changing the league, selected team, or season resets configuration to defaults.
        Records the import, increments the snapshot revision, and invalidates unexecuted proposals and monitor results.
        Returns status='imported', revision, config_revision, and config_reset, or an error without replacing state.
        """
        return manager.import_snapshot(snapshot, expected_revision)

    @server.tool(annotations=read)
    @expected_errors
    def get_team() -> dict[str, Any]:
        """Read the selected team's roster from the saved snapshot.

        Requires an imported snapshot or loaded demo.
        Returns the snapshot revision, league context, roster and reserve players, lineup, league rules, and budget when supplied.
        Use recommend_lineup to calculate a lineup or get_source_status to check observation freshness.
        This tool does not fetch new data or change saved state.
        """
        snapshot, _, revision, _ = manager.require_state()
        team = snapshot.own_team()
        return {"revision": revision, "league_id": snapshot.league_id, "season": snapshot.season, "week": snapshot.week,
                "phase": snapshot.phase, "team": team.model_dump(mode="json"), "rules": snapshot.rules.model_dump(mode="json"),
                "players": [p.model_dump(mode="json") for p in snapshot.players if p.id in team.roster_ids + team.reserve_ids],
                "budget": snapshot.budget.model_dump(mode="json") if snapshot.budget else None}

    @server.tool(annotations=read)
    @expected_errors
    def get_source_status() -> dict[str, Any]:
        """Check the freshness and completeness of the saved observation.

        Requires an imported snapshot or loaded demo.
        Returns source fields, age_seconds, the phase-specific maximum_age_seconds, stale, and local draft monitor status.
        This tool reads saved data and does not refresh the source or run a simulation.
        Use the ESPN companion for new browser observations or import_league_snapshot for replacement data.
        """
        snapshot, config, revision, _ = manager.require_state()
        limit = config.limits.max_draft_age_seconds if snapshot.phase == "draft" else config.limits.max_season_age_seconds
        return {"revision": revision, **snapshot.source.model_dump(mode="json"), "age_seconds": snapshot.age_seconds(),
                "stale": snapshot.age_seconds() > limit, "maximum_age_seconds": limit, "monitor": monitor.get()}

    @server.tool(annotations=read)
    @expected_errors
    def get_manager_config() -> dict[str, Any]:
        """Read the full current configuration and its config_revision.

        Returns strategies, automation presets and per-action modes, pause state, and user limits.
        Works before a snapshot is loaded and does not change saved state.
        Use this response as the starting configuration for update_manager_config to preserve existing settings.
        """
        _, config, _, revision = manager.state()
        return {"config_revision": revision, "config": config.model_dump(mode="json")}

    @server.tool(annotations=replace)
    @expected_errors
    def update_manager_config(
        config: Annotated[dict, WithJsonSchema(config_input), Field(description="Replacement configuration using fantasy://schema/config. Omitted fields reset to model defaults. Existing values are not merged.")],
        expected_revision: Annotated[int, Field(description="Current config_revision from get_manager_config. This is the configuration revision, not the snapshot revision.")],
    ) -> dict[str, Any]:
        """Replace the saved configuration using its current configuration revision.

        Read get_manager_config first to preserve settings that you do not intend to change.
        Omitted fields use model defaults rather than existing values, including when config is an empty object.
        Validates strategies and limits, records the change, and invalidates unexecuted proposals and monitor results.
        Returns status='updated' and the new config_revision, or a revision conflict without changing configuration.
        This tool does not execute actions or start a monitor.
        """
        return manager.update_config(config, expected_revision)

    @server.tool(annotations=write)
    @expected_errors
    def recommend_draft(
        trials: Annotated[int, Field(description="Simulation trials in this single batch. Use 1 through the configured limits.batch_trials, at most 500. More trials increase work and reduce sampling noise.")] = 40,
        seed: Annotated[int, Field(description="Random seed for this batch. Reuse an integer with identical inputs to reproduce the simulation. This does not remove forecast uncertainty.")] = 1,
    ) -> dict[str, Any]:
        """Run one bounded draft simulation against the current imported draft snapshot.

        Use start_draft_monitor for repeated batches or get_draft_recommendations to read that monitor's cached results.
        Requires draft data with consistent pick history and full-season projections for available and selected-team players.
        Returns estimated recommendations, trial counts, warnings, revisions, and status such as ready, stale_snapshot, incomplete_snapshot, or roster_complete.
        current checks revision and snapshot freshness after calculation, but does not grant action permission.
        Appends a calculation evidence record, including discarded work, without changing rosters or submitting picks.
        """
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
    def start_draft_monitor(
        interval_seconds: Annotated[float, Field(description="Pause in seconds after each batch or waiting check, from 1 through 60. Batch duration adds to the interval.")] = 2,
        trials: Annotated[int, Field(description="Trials per simulation batch, from 1 through 500 and no greater than limits.batch_trials. This is not a total trial budget.")] = 40,
    ) -> dict[str, Any]:
        """Start background draft simulations and return the initial monitor status.

        Requires a loaded draft snapshot and no active local draft monitor.
        Each batch uses the latest imported snapshot and appends calculation evidence, including discarded batches.
        The monitor waits while paused or while the snapshot is stale or incomplete, and clears obsolete cached results.
        Import new observations to maintain freshness. This tool neither reads a browser nor submits picks.
        Use get_draft_recommendations for results, stop_draft_monitor to stop, or recommend_draft for one synchronous calculation.
        """
        return monitor.start(interval_seconds, trials)

    @server.tool(annotations=read)
    @expected_errors
    def get_draft_recommendations() -> dict[str, Any]:
        """Read cached results and status from the local draft monitor without running a simulation.

        Returns running, status, error, current, trial counters, and latest when the cached inputs remain usable.
        latest is null when revisions change, the snapshot becomes stale or incomplete, automation pauses, or no result exists.
        Completed trials include work across the monitor session, while current_state_trials counts only the current inputs.
        Use start_draft_monitor to produce these results or recommend_draft for an independent single batch.
        This tool does not fetch observations or append calculation evidence.
        """
        return monitor.get()

    @server.tool(annotations=stop)
    @expected_errors
    def stop_draft_monitor() -> dict[str, Any]:
        """Request shutdown of the local draft monitor and wait up to five seconds.

        Returns monitor status and counters, with running=true and status='stopping' if the active batch still needs to finish.
        Use get_draft_recommendations to confirm running=false before starting another monitor.
        Repeated calls are safe when the monitor is already stopped.
        This tool does not stop the ESPN companion or change saved automation configuration.
        """
        return monitor.stop()

    @server.tool(annotations=write)
    @expected_errors
    def recommend_lineup() -> dict[str, Any]:
        """Calculate the selected team's best legal weekly lineup for the configured season strategy.

        Uses the saved season snapshot, weekly projections, verified player locks, and configured source age limits.
        Returns status='ok' with lineup, projected points, and improvement, or status='incomplete' with errors and missing-input details.
        Locked players remain in their current slots, including unavailable players whose games have locked.
        Appends calculation evidence without changing the lineup, and includes the input snapshot and configuration revisions.
        Use prepare_action for a synthetic proposal or the ESPN companion for live lineup changes.
        """
        snapshot, config, revision, config_revision = manager.require_state()
        result = lineup_recommendation(snapshot, config)
        manager.record_calculation("lineup", snapshot, config, revision, config_revision, result)
        return {**result, "revision": revision, "config_revision": config_revision}

    @server.tool(annotations=write)
    @expected_errors
    def rank_waiver_candidates(
        limit: Annotated[int, Field(description="Maximum number of alternative single-player acquisitions to return, from 1 through 100. Candidates are not a combined claim plan.")] = 10,
    ) -> dict[str, Any]:
        """Rank alternative single-player acquisitions using the saved weekly snapshot and user limits.

        Requires current season data, verified locks, weekly projections, and known budget and pending commitments.
        Returns recommendations with add and optional drop IDs, lineup improvement, and maximum FAAB bids, plus revisions and input warnings.
        Status is ok, incomplete for missing inputs, or blocked when the weekly move limit is reached.
        Unrostered players are not verified free agents, and this tool does not estimate winning bids or submit claims.
        Appends calculation evidence. Use prepare_action only for synthetic acquisitions that pass action checks.
        """
        snapshot, config, revision, config_revision = manager.require_state()
        result = rank_waivers(snapshot, config, limit)
        manager.record_calculation("waivers", snapshot, config, revision, config_revision, result)
        return {**result, "revision": revision, "config_revision": config_revision}

    @server.tool(annotations=write)
    @expected_errors
    def get_power_rankings() -> dict[str, Any]:
        """Compare every team's best legal weekly lineup by projected points.

        Requires current season data, weekly inputs for every team, and verified locks with league scope.
        Returns rankings, source details, warnings, and input revisions with status='ok' or status='incomplete'.
        Incomplete team lineups produce null ranks, while missing league lock coverage produces an empty rankings list.
        These estimates describe one week and are not championship probabilities.
        Appends calculation evidence without changing rosters. Use recommend_lineup to analyze only the selected team.
        """
        snapshot, config, revision, config_revision = manager.require_state()
        result = power_rankings(snapshot, config)
        manager.record_calculation("power_rankings", snapshot, config, revision, config_revision, result)
        return {**result, "revision": revision, "config_revision": config_revision}

    @server.tool(annotations=write)
    @expected_errors
    def prepare_action(
        action: Annotated[str, Field(description="Synthetic action: draft_pick, set_lineup, waiver_claim, free_agent_add, or drop_player. Trades are unsupported.", json_schema_extra={"enum": list(ACTIONS[:5])})],
        payload: Annotated[dict, WithJsonSchema(payload_input), Field(description="Exact action data. Picks and drops use player_id. Lineups use a complete lineup slot-to-player map. Adds use player_id, optional drop_id, and bid (default 0).", examples=[{"player_id": "demo-rb-001"}])],
    ) -> dict[str, Any]:
        """Validate a synthetic action and save a proposal without executing it.

        Requires fresh, complete synthetic data, unpaused automation, and review or automatic mode for every action component.
        Checks action-specific player eligibility, locks, projections, roster rules, and user limits before saving the proposal.
        Returns proposal_id, normalized payload, mode, requires_confirmation, scope, and the bound snapshot and configuration revisions.
        Each call creates a new proposal and audit record. Use execute_demo_action with that exact proposal_id for execution.
        Use the ESPN companion to prepare live draft picks or lineup changes.
        """
        return manager.prepare(action, payload)

    @server.tool(annotations=execute)
    @expected_errors
    def execute_demo_action(
        proposal_id: Annotated[str, Field(description="Exact proposal_id returned by prepare_action in this data directory. Reuse the same ID to retry an uncertain response.")],
        confirmation: Annotated[bool, Field(description="Set true only after the user approves this exact proposal in review mode. Automatic mode does not require confirmation.")] = False,
    ) -> dict[str, Any]:
        """Execute an existing proposal against synthetic demo state only.

        First call prepare_action, then obtain approval for that exact proposal when requires_confirmation is true.
        Execution rechecks snapshot and configuration revisions, freshness, automation modes, and action limits before changing state.
        Returns status='executed', scope, action, proposal_id, and the new revision, and records one audit event.
        Retrying a completed proposal returns its original result with idempotent_replay=true, without another state change or approval check.
        Unknown or changed proposals fail. Use the ESPN companion for live submissions.
        """
        return manager.execute(proposal_id, confirmation)

    @server.tool(annotations=read)
    @expected_errors
    def get_action_history(
        limit: Annotated[int, Field(description="Maximum audit records to return, from 1 through 500. Results are ordered from newest to oldest.")] = 50,
    ) -> dict[str, Any]:
        """Read recent audit records from this data directory without changing state.

        Returns history entries with id, at, event, and detail, ordered from newest to oldest.
        Records include snapshot imports, configuration changes, prepared proposals, and completed demo actions.
        An action_prepared event records preparation, not execution.
        Calculation evidence is separate from this audit history. Works before a snapshot is loaded.
        """
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
