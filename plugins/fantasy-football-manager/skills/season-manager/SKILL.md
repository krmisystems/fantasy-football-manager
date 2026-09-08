---
name: season-manager
description: Use local Fantasy Football Manager MCP tools to compare legal weekly lineups, rank waiver candidates, inspect automation policy, and exercise synthetic roster actions.
---

# Season manager

Call `get_capabilities` before you promise an action or live connection.
Version 0.1 executes changes against synthetic snapshots only.
Live provider writes and trades are unsupported.

## Review the week

1. Read `get_manager_config`.
2. If a snapshot is loaded, read `get_team` and identify the league, team, season, and week.
3. Use `load_demo(mode="season")` for an explicitly requested synthetic demonstration.
4. Import supplied JSON with `import_league_snapshot` when needed.
5. Call `recommend_lineup` for a legal weekly comparison.
6. Call `rank_waiver_candidates` to compare additions and required drops.
7. Use `get_power_rankings` only as a projection-based comparison.

Do not divide season projections into invented weekly forecasts.
Read `get_source_status` after a snapshot is loaded.
`load_demo` refuses to replace imported real state. Use a separate data directory for a new demonstration.
Report unknown projections, eligibility, locks, ownership, and pending claims.
Floor and upside comparisons require suitable inputs.
Projection rankings do not establish matchup, playoff, or championship probabilities.

## Policy and proposals

Show the current action modes and limits before changing policy.
Use `update_manager_config` only for an explicitly requested change.
Pass the current configuration revision.
A strategy change does not grant execution authority.

Use `prepare_action` for a supported synthetic lineup, waiver, acquisition, or drop proposal.
Review the complete add/drop transaction and its budget effects.
An empty drop list permits no drops in `listed_only` mode.
Protected players and pending commitments remain hard checks.

Use `execute_demo_action` only when current authorization and required confirmation permit the exact proposal.
Read the resulting state and `get_action_history` after execution.
Do not turn an unsupported action into a browser task or guessed API call.
Return a clear recommendation when execution is unavailable.
