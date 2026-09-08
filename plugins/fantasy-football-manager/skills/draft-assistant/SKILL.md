---
name: draft-assistant
description: Use local Fantasy Football Manager MCP tools to import a league snapshot, compare legal draft candidates, and monitor synthetic or imported snake drafts.
---

# Draft assistant

Use the Fantasy Football Manager MCP server supplied by this plugin.
Call `get_capabilities` before you promise an action or provider connection.
Version 0.1 has no verified live ESPN or Sleeper write adapter.
Its execution tools change synthetic state only.

## Start

1. Read `get_manager_config`.
2. Identify the league, team, season, and current board revision.
3. Use `load_demo(mode="draft")` when the user requests the synthetic demo.
4. Use `import_league_snapshot` for a supplied JSON snapshot.
5. Preserve the expected revision when replacing existing state.

Treat a demo load or import as a change to local state.
Read `get_source_status` when `get_capabilities` reports that a snapshot is loaded.
`load_demo` refuses to replace imported real state or reset confirmed picks in the same draft.
Use a separate data directory when the user must preserve another league snapshot.

## Recommend

1. Call `recommend_draft` for a bounded calculation.
2. Use `start_draft_monitor` when the user requests continued calculations.
3. Read `get_draft_recommendations` for the current job result.
4. Report the source age, board revision, trial count, and limitations.
5. Explain conditional player availability and the strongest legal alternatives.
6. Use `stop_draft_monitor` when the requested monitoring task ends.

More trials do not repair a stale or incomplete board.
Call a recommendation an estimate. Do not describe its score as a win probability.
Strategy presets cannot override roster rules, protected players, user limits, or execution permission.

## Synthetic actions

Use `prepare_action` to create an exact proposal when the user requests a supported demonstration action.
Inspect the returned effective mode and blocking reasons.
Use `execute_demo_action` only within current authorization and required confirmation.
Do not reuse confirmation after the proposal or relevant state changes.
Verify the result through `get_team`, `get_source_status`, or `get_action_history`.

Do not use browser controls, unrelated connectors, or guessed endpoints to bypass an unsupported plugin action.
Explain the capability limit and return a reviewable recommendation.
