# Policy behavior

Strategy, action permission, and hard limits are separate controls.
Changing a strategy does not authorize an action.
Version 0.1 can exercise execution policy against synthetic snapshots only.

| Control | Meaning |
|---|---|
| Advisory | Return recommendations without submitting an action. |
| Review | Prepare an exact proposal that requires confirmation before supported execution. |
| Bounded automation | Permit supported actions within saved limits and current authorization. |
| Custom | Select a different mode for each action. |
| Disabled action | Block execution for that action. |

Read `get_capabilities` and `get_manager_config` before preparing an action.
Report the effective mode when a requested mode cannot execute.
Live writes and trades remain unsupported in this version.

## Limits

- Preserve platform roster limits, eligibility, deadlines, and player locks.
- Preserve protected players during ownership changes.
- Treat an empty allowed-drop list as no permitted drops in `listed_only` mode.
- Apply add and drop permissions to the complete acquisition transaction.
- Include pending commitments in FAAB and move checks.
- Apply per-claim, weekly, season, and remaining-reserve limits together.
- Require the configured lineup improvement before lineup changes and acquisitions in review or automatic mode.
- Require known, fresh projection timestamps for draft, lineup, and acquisition execution.
- Reject execution when required observations or budget inputs are unknown.

Ordinary proposal confirmation does not remove a hard limit.
Change a user limit explicitly before preparing a new proposal that requires it.
League rules and system invariants remain mandatory.

## Strategy presets

Draft presets are `balanced_value`, `rb_priority`, `wr_priority`, `hero_rb`, and `zero_rb`.
Season presets are `projected_points`, `floor`, and `upside`.
Waiver presets are `immediate_starter`, `bench_upside`, and `conserve_faab`.

A zero-RB preference must still leave enough selections to fill required RB slots.
`max_adp_reach` is a hard execution limit when it has a numeric value.
It limits `player.adp - overall_pick`; `null` disables that optional limit.
Floor and upside strategies require suitable uncertainty inputs.
All strategy results are estimates, not guarantees.

Use `get_manager_config` to inspect the actual configuration schema and current values.
The generated JSON schemas in this repository describe the accepted source models when available.
