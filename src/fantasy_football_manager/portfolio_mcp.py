"""Read managed teams through a separate portfolio MCP server."""

import argparse
from functools import wraps
import os
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__
from .portfolio import Portfolio


def _errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        except Exception:
            raise ToolError("The saved portfolio data is unavailable.") from None
    return wrapped


def create_server(manifest=None, *, demo=False):
    """Create a read-only server without a live provider connection."""
    portfolio = Portfolio(manifest, demo=demo)
    server = MCPServer(
        "Fantasy Football Portfolio", version=__version__,
        instructions=(
            "Read saved data for explicitly configured teams. Start with list_managed_teams to obtain team keys and source freshness. "
            "This server does not refresh ESPN, run automation, approve proposals, or change saved state. "
            "Saved proposals are not proof of execution. The optional demo contains fictional football teams. "
            "Other sports require a supported data adapter. No other sport is implemented by this server."
        ),
    )
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @server.tool(annotations=read)
    @_errors
    def list_managed_teams(
        sport: Annotated[str | None, Field(description="Optional sport identifier used by the configured portfolio, such as football. Omit for every sport.", max_length=80)] = None,
        provider: Annotated[str | None, Field(description="Optional provider identifier used by the configured portfolio. Omit for every provider.", max_length=80)] = None,
    ) -> dict[str, Any]:
        """List configured teams across leagues before requesting a team, players, or proposals.

        Returns team keys, source freshness, saved automation modes, and portfolio totals.
        Filters apply to the configured sport and provider identifiers. Empty matches return an empty team list.
        Reads only explicit manifest entries and saved observations. Missing or invalid team data has a separate status.
        Requires a portfolio manifest or explicit demo mode. Does not fetch new observations or change league state.
        """
        return portfolio.overview(sport=sport, provider=provider)

    @server.tool(annotations=read)
    @_errors
    def get_managed_team(
        team_key: Annotated[str, Field(description="Exact opaque team key returned by list_managed_teams. This is not a league ID or filesystem path.", min_length=1, max_length=200)],
    ) -> dict[str, Any]:
        """Read one configured team's saved roster, starters, reserve players, rules, and policy summary.

        Use a team key from list_managed_teams. Returns source freshness and data status with the team details.
        Missing saved data remains missing. It is not replaced with demo records or a live ESPN request.
        An unknown team key returns an error. This tool does not move players or change automation settings.
        """
        return portfolio.team(team_key)

    @server.tool(annotations=read)
    @_errors
    def get_managed_analysis(
        team_key: Annotated[str, Field(description="Exact team key from list_managed_teams. Analysis uses only this team's saved observation.", min_length=1, max_length=200)],
    ) -> dict[str, Any]:
        """Read one team's available analysis and its observation context.

        Calculates lineup analysis from a saved season snapshot and returns source age, projected points, and missing-data states.
        Draft snapshots return an unavailable state. Use the existing draft tools for draft analysis.
        Review observation age and missing projections before using recommendations. Estimates do not guarantee points or ownership.
        An unknown team key returns an error. This tool does not save a proposal, approve an action, or contact ESPN.
        """
        return portfolio.analysis(team_key)

    @server.tool(annotations=read)
    @_errors
    def search_managed_players(
        team_key: Annotated[str | None, Field(description="Optional exact team key from list_managed_teams. Omit to search all configured teams.", max_length=200)] = None,
        query: Annotated[str, Field(description="Optional case-insensitive player name or NFL team search text. An empty string returns every player that matches the other filters.", max_length=160)] = "",
        position: Annotated[str | None, Field(description="Optional position filter, such as RB, WR, or TE. Omit for every position.", max_length=80)] = None,
        rostered_only: Annotated[bool, Field(description="True returns players on the selected managed rosters, including reserve players. False also includes observed available players.")] = True,
        limit: Annotated[int, Field(description="Maximum player records to return, from 1 through 200. Default is 100.", ge=1, le=200)] = 100,
        offset: Annotated[int, Field(description="Number of matching records to skip for pagination. Use zero for the first page.", ge=0, le=100000)] = 0,
    ) -> dict[str, Any]:
        """Search saved players across managed teams or within one team context.

        Returns player records, their team context, and pagination counts. A player can occur in several league contexts.
        Source observations define roster ownership and availability. They do not establish current platform availability.
        This tool does not refresh player data or acquire, drop, or move players. Invalid filters return an error.
        """
        return portfolio.players(team_key=team_key, query=query, position=position, rostered_only=rostered_only, limit=limit, offset=offset)

    @server.tool(annotations=read)
    @_errors
    def list_managed_proposals(
        team_key: Annotated[str | None, Field(description="Optional exact team key from list_managed_teams. Omit to read proposals across configured teams.", max_length=200)] = None,
        status: Annotated[str | None, Field(description="Optional saved proposal status filter. Omit for every saved status. A proposal status alone does not verify platform execution.", max_length=80)] = None,
        limit: Annotated[int, Field(description="Maximum saved proposal records to return, from 1 through 200. Default is 50.", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Number of matching records to skip for pagination. Use zero for the first page.", ge=0, le=100000)] = 0,
    ) -> dict[str, Any]:
        """Read saved proposed changes across teams for review.

        Returns proposal context, action, safe payload fields, saved status, revisions, and whether the proposal matches the current state.
        Reads at most 500 recent records per team. A truncated result reports total_scope='loaded_records', not a complete history count.
        Prepared or approved proposals do not prove execution. Pending waivers do not establish player ownership.
        This tool cannot approve, submit, reject, or modify proposals. Use existing action tools within the saved user limits.
        Invalid filters or unknown team keys return an error. Missing proposal history returns an empty list.
        """
        return portfolio.proposals(team_key=team_key, status=status, limit=limit, offset=offset)

    return server


def main():
    parser = argparse.ArgumentParser(description="Read managed teams through the portfolio MCP server.")
    parser.add_argument("--manifest", default=os.environ.get("FFM_PORTFOLIO_MANIFEST"), help="Explicit portfolio manifest. Defaults to FFM_PORTFOLIO_MANIFEST.")
    parser.add_argument("--demo", action="store_true", help="Read fictional portfolio data without local team state.")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    try:
        server = create_server(args.manifest, demo=args.demo)
    except ValueError as exc:
        parser.error(str(exc))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
