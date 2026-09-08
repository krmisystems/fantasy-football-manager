# Policy behavior

Strategy, execution permission, and hard limits are separate controls.
Version 0.2 supports real ESPN draft picks through the companion MCP server.
The manager's execution tools remain restricted to synthetic demonstrations.
The ESPN service can submit one verified lineup swap at a time.
Live waivers, acquisitions, drops, and trades are not implemented.

| Control | Meaning |
|---|---|
| Advisory | Return recommendations without submitting an action. |
| Review | Require confirmation of an exact proposal before supported execution. |
| Bounded automation | Permit supported actions within saved limits and current authorization. |
| Custom | Select a mode for each action. |
| Disabled action | Block execution for that action. |
| Shared pause | Block new actions across processes using the same data directory. |

Read `get_capabilities`, `get_manager_config`, and `espn_get_status` before live operation.
Use `espn_stop_automation` to set the shared pause flag.
Disconnecting one MCP process does not necessarily stop a separate worker.

## Live draft checks

The source must be a complete, non-synthetic `espn_browser` observation.
Its league and team must match the connected draft page.
The visible current pick must equal the complete history length plus one.
ESPN Autopick must be verified disabled. It must be the selected team's turn.

The player must be available and undrafted.
The pick must respect position caps, starter completion, and `max_adp_reach` when configured.
The draft observation age defaults to at most 15 seconds.
Projection age defaults to at most 3600 seconds through `max_projection_age_seconds`.
Unknown projection observation time blocks execution.

Review confirmation applies to one exact proposal.
Changed decision inputs or configuration require a new unclaimed proposal.
A timestamp-only refresh preserves the revision. Submission still requires a fresh observation.
Authorization creates a durable claim before the browser acts.
An unresolved claim blocks another click for the same league, team, and season.
Only a complete observation after authorization can confirm the actual platform pick.

## Live lineup checks

The complete ESPN observation must match the selected league, team, season, and scoring week.
Weekly projections and own-team lock states must be known. Locked assignments must remain unchanged.
Each proposal contains exactly one legal swap and its full resulting lineup.
Each swap must meet the configured improvement limit, including intermediate swaps toward a larger target.
The browser checks the incoming player and destination occupant before its final confirmation click.
An unresolved result blocks further moves until reconciliation. Equivalent numbered slots are compared as occupant groups.
The connected scoring week does not roll over automatically.

## Synthetic season limits

Protected players, eligibility, locks, allowed drops, and budgets remain checks for supported synthetic season actions.
An empty allowed-drop list permits no drops in `listed_only` mode.
An acquisition must satisfy both add and drop permissions.
Pending commitments count against FAAB and move limits.
The minimum lineup improvement applies to lineup changes and acquisitions.

Ordinary confirmation does not remove a hard limit.
Change a user limit explicitly before preparing a proposal that requires it.
A strategy change does not grant execution authority.

Draft strategies are `balanced_value`, `rb_priority`, `wr_priority`, `hero_rb`, and `zero_rb`.
Season strategies are `projected_points`, `floor`, and `upside`.
Waiver strategies are `immediate_starter`, `bench_upside`, and `conserve_faab`.
Floor and upside require supplied bounds.
Strategy scores and availability estimates are not guarantees or championship probabilities.
