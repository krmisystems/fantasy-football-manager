"""Companion ESPN MCP server and standalone draft worker."""

import argparse
import asyncio
from contextlib import asynccontextmanager
from functools import wraps
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__
from .espn_service import ESPNService


def errors(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except (ValueError, RuntimeError) as exc:
            raise ToolError(str(exc)) from None
    return wrapped


def create_espn_server(data_dir=None):
    service = ESPNService(data_dir)

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield {}
        finally:
            await service.close()

    server = MCPServer("Fantasy Football ESPN", version=__version__, lifespan=lifespan,
                       instructions="Connect an authenticated ESPN browser before live operations. The manager config controls automation. "
                       "Read status and source freshness. Draft submissions require one exact proposal and platform reconciliation. "
                       "Never retry an uncertain submission. Season mode can apply one verified lineup swap at a time. "
                       "Live acquisitions, drops, and trades are not implemented in this adapter.")
    read = ToolAnnotations(readOnlyHint=True, openWorldHint=False, destructiveHint=False)
    # These calls replace persisted local state even when they submit no ESPN action.
    local = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=True)
    browser = ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True)
    submit = ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True, idempotentHint=True)
    automation = ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True, idempotentHint=False)

    @server.tool(annotations=read)
    @errors
    async def espn_get_status() -> dict[str, Any]:
        """Read cached ESPN connection, automation, and submission status without a new browser observation.

        Returns the browser state, local loop state, shared worker heartbeat, saved pause, action modes, and state/config revisions.
        It also returns snapshot age, unresolved submissions, review proposals, and current recommendations from this process when available.
        A connected browser or worker heartbeat does not prove that the source snapshot is fresh.
        Use espn_sync for a new observation and espn_reconcile_draft_pick or espn_reconcile_lineup to resolve a specific submission.
        The supported live actions are draft picks and lineup swaps. Live acquisitions, drops, and trades are unavailable.
        """
        return service.status()

    @server.tool(annotations=browser)
    @errors
    async def espn_connect(
        league_id: Annotated[str, Field(description="Positive numeric ESPN league ID from the league URL, supplied as a string.")],
        team_id: Annotated[str, Field(description="Positive numeric ESPN team ID within this league, supplied as a string.")],
        season: Annotated[int, Field(description="ESPN football season year, from 2020 through 2100.")],
        cdp_url: Annotated[str | None, Field(description=(
            "Optional loopback Chrome debugging HTTP or WebSocket URL with an explicit port and no credentials. "
            "The browser must contain exactly one matching ESPN tab. Null opens the dedicated Chrome profile."
        ))] = None,
        headless: Annotated[bool, Field(description=(
            "Hide the dedicated Chrome window when true. Use false for interactive sign-in. "
            "This option does not change an existing CDP browser."
        ))] = False,
        phase: Annotated[str, Field(description=(
            "Use draft for live draft operations or season for weekly roster and lineup operations."
        ))] = "draft",
        week: Annotated[int, Field(description=(
            "NFL scoring week from 1 through 18. Season mode reads this week. "
            "An unresolved action requires its original week when reconnecting."
        ))] = 1,
    ) -> dict[str, Any]:
        """Connect Chrome to one ESPN league, team, season, and phase, then save that connection locally.

        The default opens a dedicated persistent profile. Sign in through that browser when required.
        A loopback CDP URL uses an existing browser. Credentials or copied cookies are not tool arguments.
        Stop this process's automation before changing context. An unresolved submission requires its exact original context when reconnecting.

        Returns connection status, readiness, phase, and week. A connected browser can still require sign-in or draft entry.
        Use espn_sync to read current state before analysis. This tool does not start automation or submit a fantasy action.
        """
        return await service.connect(league_id, team_id, season, cdp_url, headless, phase=phase, week=week)

    @server.tool(annotations=browser)
    @errors
    async def espn_sync() -> dict[str, Any]:
        """Read the connected ESPN draft or weekly roster into the manager's local state.

        Connect the browser first. Complete sign-in before observation. The saved phase selects draft history or the weekly roster.
        The observation checks the active context and source completeness. Season observations also check player locks.

        Returns the state revision and either observation details or reconciliation details for an unresolved submission.
        Unchanged decision inputs refresh observation times without changing the revision. An uncertain submission remains blocked for new actions.
        This tool does not calculate recommendations or submit a pick or lineup swap. Use espn_get_status to inspect the resulting state.
        """
        return await service.sync()

    @server.tool(annotations=automation)
    @errors
    async def espn_start_automation(
        interval_seconds: Annotated[float, Field(description=(
            "Delay in seconds after each completed observation and analysis cycle, from 1 through 60. "
            "Browser and calculation time add to this delay."
        ))] = 2,
        trials: Annotated[int, Field(description=(
            "Draft simulation trials per cycle, from 1 through the saved limits.batch_trials value. "
            "Season mode uses lineup optimization instead of draft simulations."
        ))] = 40,
    ) -> dict[str, Any]:
        """Start continuous ESPN observation and analysis inside this MCP server process.

        Connect the browser first. This tool returns current status without waiting for the first complete cycle.
        Unpaused cycles refresh ESPN state. The loop calculates draft recommendations or a weekly lineup when no submission awaits verification.
        Compatible draft batches accumulate additional trials.

        Saved automatic modes can submit real picks or one legal lineup swap within user limits.
        Other modes do not submit automatically. Review mode requires a prepared proposal and exact user confirmation through the matching submit tool.

        This tool does not clear a saved pause. Stale sources, changed revisions, and unresolved submissions block new actions.
        Read espn_get_status for current local recommendations, worker errors, and source age. Use espn_stop_automation to pause new actions.
        The loop ends when this MCP process closes. Use espn_start_standalone_worker for an independent local process.
        """
        return await service.start(interval_seconds, trials)

    @server.tool(annotations=local)
    @errors
    async def espn_stop_automation() -> dict[str, Any]:
        """Save automation.paused=true in local configuration and request a stop for this process's ESPN loop.

        The saved pause blocks new actions in every manager process that uses the same data directory, including a standalone worker.
        A current bounded browser operation can finish. This tool does not cancel a submitted action or clear an unresolved submission.
        Returns current status, including the saved pause and whether this process's loop still runs.

        The browser stays connected. Use espn_disconnect to release this process's browser connection.
        To resume actions, read get_manager_config from the manager server for its current configuration and config_revision.
        Use update_manager_config with that revision and automation.paused=false. Restart this process's loop if it stopped.
        """
        return await service.pause()

    @server.tool(annotations=automation)
    @errors
    async def espn_start_standalone_worker() -> dict[str, Any]:
        """Start an independent local ESPN worker that continues after the MCP client or Codex closes.

        First save a connection with espn_connect. This tool stops the local loop and releases its browser before the worker connects.
        The worker uses the saved connection, a two-second cycle delay, and 40 draft trials per cycle.
        It uses saved action modes, limits, and pause. Automatic modes can submit real picks or one legal lineup swap at a time.

        A browser ownership conflict blocks another worker. The saved batch limit must permit the worker's 40-trial default.
        Returns the launch identifier, process identifiers, status, and startup_acknowledged. A startup_pending result does not verify browser readiness.

        Read espn_get_status for the shared worker heartbeat and errors. Recommendations in that tool belong to its own process.
        Use espn_stop_automation to save a shared pause. Disconnecting this MCP process does not stop the independent worker.
        """
        return await service.start_standalone()

    @server.tool(annotations=browser)
    @errors
    async def espn_prepare_draft_pick(
        player_id: Annotated[str, Field(description=(
            "Exact player ID from the current ESPN draft snapshot or its recommendations. Use the ID, not the player's name."
        ))],
    ) -> dict[str, Any]:
        """Refresh the connected draft and save one exact pick proposal without a submission click.

        Use draft phase with the correct league and team. The player must be legal for the current pick under saved user limits.
        Preparation requires review or automatic mode, fresh source data and projections, verified disabled ESPN Autopick, and no unresolved pick submission.

        Returns proposal_id, player identity, pick number, payload, state/config revisions, mode, and requires_confirmation.
        The local proposal and audit record do not prove that ESPN selected the player.
        Review the proposal before espn_submit_draft_pick. Prepare a new proposal if decision inputs or configuration change before authorization.
        """
        return await service.prepare_pick(player_id)

    @server.tool(annotations=submit)
    @errors
    async def espn_submit_draft_pick(
        proposal_id: Annotated[str, Field(description=(
            "Exact proposal_id returned by espn_prepare_draft_pick for this league, team, season, player, and pick."
        ))],
        confirmation: Annotated[bool, Field(description=(
            "Set true only after the user approves this exact proposal in review mode. "
            "Automatic mode does not require confirmation. This value does not bypass saved limits."
        ))] = False,
    ) -> dict[str, Any]:
        """Authorize and attempt one real ESPN draft pick from a prepared proposal.

        First call espn_prepare_draft_pick. Review mode requires user approval of this exact proposal and confirmation=true.
        The service refreshes state and rechecks context, revisions, source freshness, player identity, and saved limits before the click.
        It records authorization and the submission result locally. A browser return alone does not prove that ESPN selected the player.

        Returns the proposal status and available browser or reconciliation details. A repeated claimed proposal does not authorize another click.
        If status is awaiting_verification, use espn_reconcile_draft_pick. Never retry an uncertain submission with a new proposal.
        """
        return await service.submit_pick(proposal_id, confirmation)

    @server.tool(annotations=browser)
    @errors
    async def espn_reconcile_draft_pick(
        proposal_id: Annotated[str, Field(description=(
            "Exact proposal_id from an authorized ESPN draft submission that needs verification, or a previously settled proposal."
        ))],
    ) -> dict[str, Any]:
        """Observe ESPN draft history to verify one previously authorized pick without another submission click.

        Keep the browser connected to the proposal's league, team, and season in draft phase.
        Returns confirmed when the expected pick contains the requested player, or not_selected when it contains another player.
        If the expected pick is not visible yet, status remains awaiting_verification. Continue observation without a new pick attempt.

        A complete matching observation commits the platform state and audit result locally. Conflicting context or incomplete history produces an error.
        A settled proposal returns its stored result. Never treat an uncertain result as permission to repeat a click.
        """
        return await service.reconcile_pick(proposal_id)

    @server.tool(annotations=browser)
    @errors
    async def espn_prepare_lineup(
        lineup: Annotated[dict[str, str], Field(description=(
            "Resulting full starter mapping: every configured slot key maps to one distinct roster player ID. "
            "Use observed slot keys such as QB1, RB1, WR1, FLEX1, DST1, and K1. Do not include bench or reserve keys. "
            "The change must be exactly one bench-to-starter swap or one exchange between two starter slots. "
            "Include unchanged starters. A complete optimized lineup can require several separate proposals."
        ))],
    ) -> dict[str, Any]:
        """Refresh the weekly roster and save one legal lineup swap proposal without a submission click.

        Connect in season phase for the intended week. Supply the resulting full starter mapping, including unchanged starters.
        Exactly one bench-to-starter swap or one exchange between starter slots is supported. Equivalent slots within one position are interchangeable.
        Preparation checks current player locks, roster membership, eligibility, source and projection freshness, saved limits, and unresolved submissions.

        Review or automatic mode is required. Returns proposal_id, full lineup, swap details, state/config revisions, mode, and requires_confirmation.
        Use espn_submit_lineup for this exact proposal. A full lineup recommendation with several swaps requires separate verified proposals.
        """
        return await service.prepare_lineup(lineup)

    @server.tool(annotations=submit)
    @errors
    async def espn_submit_lineup(
        proposal_id: Annotated[str, Field(description=(
            "Exact proposal_id returned by espn_prepare_lineup for this league, team, season, week, and single swap."
        ))],
        confirmation: Annotated[bool, Field(description=(
            "Set true only after the user approves this exact proposal in review mode. "
            "Automatic mode does not require confirmation. This value does not bypass saved limits or player locks."
        ))] = False,
    ) -> dict[str, Any]:
        """Authorize and attempt one real ESPN lineup swap from a prepared proposal.

        First call espn_prepare_lineup. Review mode requires user approval of this exact proposal and confirmation=true.
        The service refreshes the roster and rechecks context, revisions, player locks, source freshness, and saved limits before confirmation.
        It records authorization and the submission result locally. Returns the proposal status and available browser or reconciliation details.

        A repeated claimed proposal does not authorize another click. An uncertain result remains awaiting_verification.
        Use espn_reconcile_lineup before another swap. Never retry an uncertain submission with a new proposal.
        """
        return await service.submit_lineup(proposal_id, confirmation)

    @server.tool(annotations=browser)
    @errors
    async def espn_reconcile_lineup(
        proposal_id: Annotated[str, Field(description=(
            "Exact proposal_id from an authorized ESPN lineup submission that needs verification, or a previously settled proposal."
        ))],
    ) -> dict[str, Any]:
        """Observe the weekly ESPN roster to verify one authorized lineup swap without another confirmation click.

        Keep the browser connected to the proposal's exact league, team, season, and week in season phase.
        Returns confirmed for the expected lineup, or conflict for a different changed lineup or own roster.
        An unchanged baseline lineup remains awaiting_verification. Continue observation without another swap attempt.

        A complete matching observation commits the platform state and audit result locally.
        Conflicting context, incomplete state, or unverified locks produces an error.
        A settled proposal returns its stored result. Never treat an uncertain result as permission to repeat a click.
        """
        return await service.reconcile_lineup(proposal_id)

    @server.tool(annotations=browser)
    @errors
    async def espn_disconnect() -> dict[str, Any]:
        """Stop this process's loop and release its ESPN browser connection.

        Returns disconnected when the connection closes, or stopping while a current bounded operation must finish.
        The dedicated browser closes. A CDP browser remains open after this process disconnects.
        Saved connection settings, local evidence, and unresolved submissions remain available. This tool does not change the saved pause.

        An independent standalone worker continues. Use espn_stop_automation to save a shared pause before disconnecting if new actions must stop.
        This tool updates local connection status. It does not submit a fantasy action.
        """
        return await service.close()

    return server


async def _worker(args):
    from .server import stop_signals
    service = ESPNService(args.data_dir)
    stopping = asyncio.Event()

    def request_stop():
        stopping.set()
        service.stop_event.set()

    with stop_signals(request_stop):
        try:
            connection = service.saved_connection()
            await service.connect(**connection)
            if not stopping.is_set():
                await service.start(args.interval, args.trials)
                if stopping.is_set():
                    service.stop_event.set()
                await service.task
        except Exception as exc:
            service._save_status("startup_failed", error=str(exc))
            raise
        finally:
            service.stop_event.set()
            if service.task is not None and not service.task.done():
                # Finish the authorized operation before closing its browser.
                await asyncio.shield(service.task)
            await service.close()


def main():
    parser = argparse.ArgumentParser(description="ESPN MCP server and local automation worker")
    parser.add_argument("--data-dir")
    parser.add_argument("--worker", action="store_true", help="Run the saved browser connection independently of an MCP client.")
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    if args.worker:
        asyncio.run(_worker(args))
    else:
        create_espn_server(args.data_dir).run(transport="stdio")


if __name__ == "__main__":
    main()
