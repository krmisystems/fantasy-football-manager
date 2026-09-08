# ESPN automation

The ESPN companion implements live snake-draft observation and submission.
It shares policy and SQLite state with the manager MCP server.
Season mode reads weekly rosters and can submit one verified lineup swap at a time.
Live waivers, acquisitions, drops, and trades remain planned.

## Connection

Use `espn_connect` with the numeric league ID, numeric team ID, and season.
The default connection opens installed Google Chrome with a dedicated profile in the data directory.
Complete sign-in in that browser when required. Do not send passwords or cookies through tool arguments.
The adapter does not copy credentials from another profile.

An optional `cdp_url` must identify an explicit loopback HTTP or WebSocket endpoint with a debugging port.
The adapter validates local discovery and the selected ESPN page.
Use the draft phase for a draft room. Use `phase="season"` and an explicit `week` for a weekly lineup.
A profile lease prevents another manager process from controlling the same profile simultaneously.

Call `espn_sync` after sign-in. The source must identify the selected league and team.
In draft mode, complete pick history must agree with the visible clock and saved history.
In season mode, the visible team and week must match the requested context.
Missing or contradictory observations do not authorize a submission.

## Separate league state from the browser profile

Set `FFM_BROWSER_DATA_DIR` to select the browser directory for the ESPN process.
That directory contains `espn-browser-profile` and `espn-browser.lock`.
Select the parent directory when you reuse an existing managed profile.
The setting does not copy cookies or move league records.

Use `--data-dir` or `FFM_DATA_DIR` to select each league's separate state directory.
Both MCP servers for that league must select the same state directory.
`FFM_BROWSER_DATA_DIR` affects the ESPN browser only. It does not change the selected league database.
If this setting is absent or empty, the browser uses the league state directory.

The ESPN service selects the browser directory when its process starts.
Draft and season adapters keep that selection when the connection changes phase.
A worker launched by `espn_start_standalone_worker` receives the same selected browser directory.
Set the variable again when you start an MCP process or worker manually. The saved connection does not store this setting.

Only one controller can hold a shared browser profile lease.
Reconcile pending actions before changing controllers.
Call `espn_disconnect` on the current controller to release its browser connection.
Then connect the other league through its separate MCP server pair.
Pausing one league does not pause another league's separate state directory.

For a completed draft, connect with `phase="season"` and the current scoring week.
Call `espn_sync` to verify the selected roster, projections, and locks.
A phase change keeps the league's saved policy. Check `set_lineup` mode before you start season automation.
See the [local server configuration example](PLUGIN_INSTALL.md#select-league-state-and-a-shared-browser-profile).

`FFM_BROWSER_DATA_DIR` is available from version 0.2.2.

## Companion tools

| Tool | Purpose |
|---|---|
| `espn_get_status` | Read browser health, worker heartbeat, policy, pending claims, and current recommendations. |
| `espn_connect` | Open the managed profile or connect through local CDP. |
| `espn_sync` | Import verified observations and reconcile pending claims. |
| `espn_start_automation` | Run observations and analysis in the MCP process. Automatic mode can submit picks or lineup swaps. |
| `espn_stop_automation` | Pause new actions across processes sharing the data directory. Stop this process's loop. |
| `espn_start_standalone_worker` | Transfer the saved connection to an independent local worker. |
| `espn_prepare_draft_pick` | Refresh the board and prepare one player under current limits. |
| `espn_submit_draft_pick` | Submit one pick. Review mode requires confirmation of the exact proposal. |
| `espn_reconcile_draft_pick` | Read the platform result without authorizing another click. |
| `espn_prepare_lineup` | Prepare a full resulting lineup that contains one legal swap. |
| `espn_submit_lineup` | Submit one lineup swap under its exact proposal and configured review mode. |
| `espn_reconcile_lineup` | Verify the resulting roster without repeating the confirmation click. |
| `espn_disconnect` | Stop this process's loop and release its browser connection. |

The manager provides `get_manager_config` and `update_manager_config`.
Use them to select action modes, strategy, and limits.
Use `espn_stop_automation` for a shared pause. Disconnecting one process is not a global pause.

## Automatic mode

For draft operation, set the draft action mode to `automatic` within the user's authorization.
Clear `automation.paused` when resuming an authorized task.
Call `espn_start_automation` to observe and calculate continuously.
The loop submits only on the selected team's turn when a current candidate passes policy.
ESPN Autopick must be verified disabled.

The default draft observation limit is 15 seconds.
Projection age has a separate limit of 3600 seconds by default.
An observation timestamp records a download or capture, not ESPN's projection publication time.
Read configured values because the user can change these limits.

The model combines batches only when calculation inputs match.
New picks, projections, or strategy changes reset the aggregate.
Scores compare estimated roster value across the next two selections.
They are not probabilities of winning the league.

## Review and uncertain results

Prepare a player with `espn_prepare_draft_pick`.
Show the exact player, pick number, league, and policy decision.
Submit with `confirmation=true` after required review confirmation.
Changed decision inputs or configuration invalidate an unclaimed proposal.
A timestamp-only refresh preserves the proposal revision. The final submission still requires a fresh observation.

Authorization creates one durable claim with status `awaiting_verification` before a click occurs.
Repeated submission does not authorize another click.
A timeout, missing result, or empty response cannot confirm success.
Use `espn_reconcile_draft_pick` to obtain a complete observation after authorization.

The result is `confirmed` if the expected pick contains the selected player.
It is `not_selected` if that pick contains another player.
It remains `awaiting_verification` if that pick is absent.
An unresolved claim blocks another claim in the same league, team, and season.
Reconciliation commits actual platform state and its action record in one transaction.

## Worker lifetime

The ordinary loop runs inside the MCP process.
`espn_start_standalone_worker` starts a separate local process from the saved connection.
It can continue after Codex closes while the computer and authenticated browser remain available.
Draft mode stops after the selected roster is complete. Season mode continues for the connected scoring week.

Read status before starting another worker.
Use `espn_stop_automation` to set the shared pause flag.
An already submitted pick or lineup swap still requires reconciliation.
The worker is not an operating-system service and does not resume automatically after a reboot.

## Validation boundary

Automated tests use browser stubs, offline observations, and fictional players.
Isolated Chrome tests exercise the adapters against local page fixtures.
The [fourth draft](FOURTH_DRAFT_ACCEPTANCE.md) verified all 16 own selections with unchanged installed v0.3.1 execution methods.
A private orchestration launcher collected the remaining league history. One preauthorization error recovered without operator intervention.
Live lineup submission remains **Not Tested** in the recorded server acceptance checks.
See the exact test checkpoint in [validation status](VALIDATION.md).
Earlier direct browser picks were verified separately. They do not prove this package's selector compatibility.
ESPN's fantasy read endpoints and page structure are unofficial integration surfaces.
Authentication and compatible ESPN draft and team pages remain external requirements.
Live waivers, acquisitions, drops, and trades remain planned.

## Weekly lineup automation

Connect with `phase="season"` and an explicit `week` from 1 through 18.
The browser verifies the selected team and the visible lineup week.
The adapter reads complete rosters and period-specific projections. Missing projections remain null.
The adapter verifies own-team locks from explicit move controls. Unknown lock states block execution.
This evidence has `locks_scope="selected_team"`. League-wide power rankings remain incomplete without league-wide lock coverage.
Player responses without embedded league identifiers are bound to the verified request URL.
A roster ownership change on any team invalidates the cached player response.
Live ESPN does not supply verified floor or ceiling estimates in this adapter. Those strategies require additional data.

Set `set_lineup` to `automatic` within the user's authorization.
The loop calculates the best legal weekly lineup. It selects one legal swap toward that lineup.
Each swap must independently meet the configured improvement limit.
The browser selects the incoming player and confirms the exact destination occupant.
The worker verifies the observed roster before another swap.
An uncertain result blocks further automatic moves. A confirmed conflict records the actual roster.

Equivalent numbered slots share an eligibility group. Reordering two RB slots alone does not establish a different lineup.
The worker does not claim the entire optimized lineup was applied after one swap.
Some targets require intermediate moves below the improvement limit. The worker reports that it cannot apply a qualifying swap.
The scoring week is explicit. Reconnect for the next week. Automatic week rollover remains planned.
