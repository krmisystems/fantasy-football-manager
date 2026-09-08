---
name: season-manager
description: Read ESPN weekly rosters, optimize lineups, submit verified lineup swaps, rank waiver candidates, and inspect configured automation limits.
---

# Season manager

Read `get_capabilities` and `get_manager_config` before selecting a season workflow.
The manager provides weekly analysis and synthetic season execution.
The ESPN companion supports live weekly observations and verified lineup swaps.
Live waiver, acquisition, drop, and trade adapters are not implemented.
For live ESPN drafts, use the included `espn-automation` skill and companion tools.

## Review the week

1. Read `get_team` when a snapshot is loaded.
2. Identify the league, team, season, and week.
3. Use `load_demo(mode="season")` for a requested synthetic demonstration.
4. Use `import_league_snapshot` for supplied weekly observations.
5. Call `recommend_lineup` for a legal weekly comparison.
6. Call `rank_waiver_candidates` to compare additions and required drops.
7. Use `get_power_rankings` as a projection-based comparison.

Read `get_source_status` after an import.
Report missing projections, eligibility, locks, ownership, and pending claims.
Do not divide season totals into invented weekly projections.
Floor and upside comparisons require supplied bounds.
Projection rankings do not establish matchup or championship probabilities.
Use a separate data directory for demonstrations when real league state is loaded.

## Policy and proposals

Preserve the user's authorized action modes and hard limits.
Use `update_manager_config` with the current revision for an authorized configuration change.
Strategy changes do not grant action permission.

Use `prepare_action` for supported synthetic lineup, acquisition, waiver, or drop proposals.
Review the complete add/drop transaction and its budget effects.
An empty drop list permits no drops in `listed_only` mode.
Protected players and pending commitments remain hard checks.

Use `execute_demo_action` only within current authorization and required confirmation.
Read the resulting state and `get_action_history` after execution.
For a requested live acquisition, drop, or trade, report the missing adapter and provide the calculated recommendation.
Do not describe a synthetic result as a change to the real league.

## Live lineup operation

1. Call `espn_connect` with the selected context, `phase="season"`, and the requested `week`.
2. Complete browser sign-in when required.
3. Call `espn_sync` and verify source completeness, current week, and own-team locks.
4. Preserve the user's authorized `set_lineup` mode, strategy, and improvement limit.
5. Call `espn_start_automation` for continuous observations and analysis.

Automatic lineup mode can submit one qualifying swap at a time.
Review mode provides recommendations and requires confirmation of an exact proposal.
Use `espn_prepare_lineup` with the full resulting lineup for one legal swap.
Use `espn_submit_lineup` with required review confirmation.
Use `espn_reconcile_lineup` for an uncertain result. Never repeat an uncertain confirmation click.
Read `espn_get_status` and `get_action_history` after a submission.
Do not claim the full recommended lineup was applied after one swap.
Some targets require intermediate swaps below the user limit. Report that limitation without lowering the limit.
Reconnect for the next scoring week. Automatic week rollover is not implemented.
Use `espn_stop_automation` for a shared pause.
