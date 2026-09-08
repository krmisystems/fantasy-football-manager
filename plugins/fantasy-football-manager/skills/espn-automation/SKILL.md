---
name: espn-automation
description: Connect the ESPN companion MCP, watch live drafts or weekly rosters, run continuous analysis, and submit real picks or lineup swaps within user limits.
---

# ESPN automation

Use the `fantasy-football-espn` companion supplied by this plugin for live ESPN drafts.
Use `season-manager` for weekly observation and lineup automation through the same companion.
Use the manager MCP for saved configuration and strategy.
Live draft submission and weekly lineup swaps are implemented.
Check the current release evidence before claiming live account acceptance.
Distinguish installed-package checks from working-tree live submissions and local browser fixtures.
Season mode supports one verified lineup swap at a time.
Live waivers, acquisitions, drops, and trades are not implemented.

## Connect and verify

1. Read `get_capabilities`, `get_manager_config`, and `espn_get_status`.
2. Identify the requested league ID, team ID, and season.
3. Call `espn_connect` with that context.
4. Have the user complete ESPN sign-in in the browser when required.
5. Call `espn_sync` to obtain a complete current board.
6. Read `espn_get_status` before starting submissions.

The default connection uses a dedicated local Chrome profile.
The old draft Chrome extension is not required.
It does not copy cookies from an existing profile.
The optional `cdp_url` must identify a loopback debugging endpoint.
Do not request passwords or cookies through tool arguments.
ESPN Autopick must be verified disabled before direct submission.

## Continuous operation

Use the user's authorized mode and limits. Preserve unrelated configuration fields.
Use `update_manager_config` with the current revision for an authorized policy change.
A strategy change does not grant submission authority.

Call `espn_start_automation` for continued observations and simulation batches.
Only draft mode `automatic` permits the loop to select and submit picks itself.
Do not request per-pick confirmation when the user has already authorized automatic mode.
Review mode requires exact proposal confirmation as described below.

The ordinary loop runs inside the MCP process.
Use `espn_start_standalone_worker` when the user requests operation after Codex closes.
The standalone worker uses saved policy. Draft mode stops when the selected roster is complete.
Season mode monitors the explicit connected week until stopped. Automatic week rollover remains planned.
Read status before starting another worker.

Call `espn_stop_automation` to pause new actions across processes sharing the data directory.
Clear `automation.paused` through an authorized configuration update when resuming.
Use `espn_disconnect` to release this process's connection after its work ends.
Disconnect is not a shared pause for another worker.

## Exact picks and verification

Use `espn_prepare_draft_pick(player_id)` to refresh the board and prepare a specific pick.
Show its player, pick number, league, mode, and required confirmation.
Use `espn_submit_draft_pick(proposal_id, confirmation=true)` after required review confirmation.
Automatic mode can submit without per-pick confirmation within the user's authorization.

A proposal can grant only one click claim.
If a response reports `awaiting_verification`, call `espn_reconcile_draft_pick`.
Never retry an uncertain submission as a new click or proposal.
Missing, empty, or failed browser results do not prove success.
Report `confirmed` only after the platform identifies the expected player at the expected pick.
Report `not_selected` when that pick identifies another player.

Read `espn_get_status` for worker health, pending claims, and current recommendations.
Report actual trials and source age. Treat model scores and availability as estimates.
Do not claim championship odds or fully automatic season management.
