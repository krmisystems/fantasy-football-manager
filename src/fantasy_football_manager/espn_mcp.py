"""Companion ESPN MCP server and standalone draft worker."""

import argparse
import asyncio
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

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
    local = ToolAnnotations(readOnlyHint=False, openWorldHint=False, destructiveHint=False)
    browser = ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=False)
    submit = ToolAnnotations(readOnlyHint=False, openWorldHint=True, destructiveHint=True, idempotentHint=True)

    @server.tool(annotations=read)
    @errors
    async def espn_get_status() -> dict[str, Any]:
        """Read browser connection, worker health, policy mode, and pending submissions."""
        return service.status()

    @server.tool(annotations=browser)
    @errors
    async def espn_connect(league_id: str, team_id: str, season: int, cdp_url: str | None = None, headless: bool = False,
                           phase: str = "draft", week: int = 1) -> dict[str, Any]:
        """Open a dedicated Chrome profile or connect to a local CDP browser. Sign in through the browser when needed."""
        return await service.connect(league_id, team_id, season, cdp_url, headless, phase=phase, week=week)

    @server.tool(annotations=browser)
    @errors
    async def espn_sync() -> dict[str, Any]:
        """Read the connected ESPN draft or weekly roster and reconcile pending submissions."""
        return await service.sync()

    @server.tool(annotations=submit)
    @errors
    async def espn_start_automation(interval_seconds: float = 2, trials: int = 40) -> dict[str, Any]:
        """Start continuous observation and analysis. Automatic mode can submit real picks or lineup swaps within saved limits."""
        return await service.start(interval_seconds, trials)

    @server.tool(annotations=local)
    @errors
    async def espn_stop_automation() -> dict[str, Any]:
        """Pause new ESPN actions across connected processes and stop this process's loop."""
        return await service.pause()

    @server.tool(annotations=submit)
    @errors
    async def espn_start_standalone_worker() -> dict[str, Any]:
        """Start a local worker that survives Codex closure. Saved automatic modes permit real picks or lineup swaps."""
        return await service.start_standalone()

    @server.tool(annotations=browser)
    @errors
    async def espn_prepare_draft_pick(player_id: str) -> dict[str, Any]:
        """Refresh ESPN state and prepare a specific pick under current automation limits."""
        return await service.prepare_pick(player_id)

    @server.tool(annotations=submit)
    @errors
    async def espn_submit_draft_pick(proposal_id: str, confirmation: bool = False) -> dict[str, Any]:
        """Submit one real ESPN draft pick. Review mode requires user confirmation of this exact proposal."""
        return await service.submit_pick(proposal_id, confirmation)

    @server.tool(annotations=browser)
    @errors
    async def espn_reconcile_draft_pick(proposal_id: str) -> dict[str, Any]:
        """Observe ESPN after a submission. An uncertain result never permits an automatic repeat click."""
        return await service.reconcile_pick(proposal_id)

    @server.tool(annotations=browser)
    @errors
    async def espn_prepare_lineup(lineup: dict[str, str]) -> dict[str, Any]:
        """Prepare one legal lineup swap. Supply the resulting full lineup. Check user limits and current player locks."""
        return await service.prepare_lineup(lineup)

    @server.tool(annotations=submit)
    @errors
    async def espn_submit_lineup(proposal_id: str, confirmation: bool = False) -> dict[str, Any]:
        """Submit one ESPN lineup swap. Review mode requires user confirmation of the exact proposal."""
        return await service.submit_lineup(proposal_id, confirmation)

    @server.tool(annotations=browser)
    @errors
    async def espn_reconcile_lineup(proposal_id: str) -> dict[str, Any]:
        """Read the roster to verify a lineup submission. Never repeat an uncertain confirmation click."""
        return await service.reconcile_lineup(proposal_id)

    @server.tool(annotations=browser)
    @errors
    async def espn_disconnect() -> dict[str, Any]:
        """Stop this loop and release this process's browser connection."""
        return await service.close()

    return server


async def _worker(args):
    service = ESPNService(args.data_dir)
    try:
        connection = service.saved_connection()
        await service.connect(**connection)
        await service.start(args.interval, args.trials)
        await service.task
    finally:
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
