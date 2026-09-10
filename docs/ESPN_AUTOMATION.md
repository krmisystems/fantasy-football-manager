# ESPN automation

The ESPN companion implements live snake-draft observation and submission.
It shares policy and SQLite state with the manager MCP server.
The unreleased v0.4.0 candidate adds HTTP season operation without a browser runtime.
It supports lineups, free-agent additions, waiver claims, drops, and IR moves under saved limits.
Trade execution remains unavailable.

The published v0.3.3 package retains the browser draft and single-swap lineup workflows.
The HTTP implementation has source and fictional-service tests.
Verified staged reads cover ownership and targeted locks for five teams.
Live HTTP write acceptance remains **Not Tested** at this documentation checkpoint.
See [validation status](VALIDATION.md) before using a release claim.

## Connection

Use `espn_connect` with the numeric league ID, numeric team ID, and season.
Set `phase="season"`, `transport="http"`, and the requested `week` for HTTP season operation.
HTTP is the default season transport unless configuration selects the browser adapter.
Configure a protected session file before connecting. See [HTTP session setup](PLUGIN_INSTALL.md#configure-an-http-season-session-unreleased).
Do not send passwords or cookie values through tool arguments.

The HTTP adapter verifies the session member against the selected team's owners.
It reads all rosters, player data, and the exact team's roster for the requested period.
Generic player-pool lock flags cannot replace targeted roster lock evidence.
Missing or conflicting context, ownership, or lock evidence blocks a write.
The season schedule supplies bye weeks through each player's `proTeamId`.
Unknown bye evidence blocks incoming starters and acquisitions.

Draft phase preserves the browser adapter. Explicit `transport="browser"` selects the legacy season adapter.
These connections require the `browser` extra and installed Google Chrome.
They use a dedicated profile or a local CDP connection.
Complete browser sign-in when that workflow requires it.
The browser adapter does not import another profile's credentials.

An optional `cdp_url` must identify an explicit loopback HTTP or WebSocket endpoint with a debugging port.
The adapter validates local discovery and the selected ESPN page.
HTTP mode rejects `cdp_url`. The `headless` option affects only the browser adapter.
A profile lease prevents another manager process from controlling the same profile simultaneously.

Call `espn_sync` after connection. The source must identify the selected league and team.
In draft mode, complete pick history must agree with the visible clock and saved history.
The legacy season adapter also verifies the visible team and week.
Missing or contradictory observations do not authorize a submission.

## HTTP session and team lease

The protected session file contains only `SWID` and `espn_s2`.
The HTTP client sends these values only to its allowed ESPN football API hosts.
It rejects redirects and does not retry transaction POSTs automatically.
The optional Linux importer reads two ESPN cookies from an existing authorized Chromium database without starting Chromium.
It supports the inspected Linux `v10` format. It does not supply password sign-in or renew expired sessions.

A team lease prevents two HTTP services from controlling the same league and team through a shared credential directory.
Separate manager databases do not bypass this lease. Different teams can hold separate leases.
Closing the connection releases its lease. A failed connection also releases it.
Separate copies of credentials in unrelated directories do not establish a shared lease.
Use one protected credential directory for controllers that share an account.

## Separate league state from the browser profile

Set `FFM_BROWSER_DATA_DIR` to select the browser directory for the ESPN process.
This section describes browser drafts and the legacy browser season adapter.
That directory contains `espn-browser-profile` and `espn-browser.lock`.
Select the parent directory when you reuse an existing managed profile.
The setting does not copy cookies or move league records.

Use `--data-dir` or `FFM_DATA_DIR` to select each league's separate state directory.
Both MCP servers for that league must select the same state directory.
`FFM_BROWSER_DATA_DIR` selects the profile location. It does not change the selected league database.
Configure the HTTP session file explicitly when using the HTTP adapter.
If this setting is absent or empty, the browser uses the league state directory.

The ESPN service selects the browser directory when its process starts.
The browser adapters keep that selection when the connection changes phase.
A worker launched by `espn_start_standalone_worker` receives the same selected browser directory.
Set the variable again when you start an MCP process or worker manually. The saved connection does not store this setting.

Only one controller can hold a shared browser profile lease.
Reconcile pending actions before changing controllers.
Call `espn_disconnect` on the current controller to release its browser connection.
Then connect the other league through its separate MCP server pair.
Pausing one league does not pause another league's separate state directory.

For the legacy season workflow, connect with `phase="season"`, `transport="browser"`, and the current scoring week.
Call `espn_sync` to verify the selected roster, projections, and locks.
A phase change keeps the league's saved policy. Check `set_lineup` mode before you start season automation.
See the [local server configuration example](PLUGIN_INSTALL.md#select-league-state-and-a-shared-browser-profile).

`FFM_BROWSER_DATA_DIR` is available from version 0.2.2.

## Companion tools

The unreleased v0.4.0 candidate exposes 16 ESPN tools. Version 0.3.3 exposes the original 13 tools.

| Tool | Purpose |
|---|---|
| `espn_get_status` | Read cached connection health, transport, worker heartbeat, policy, proposals, and current recommendations. |
| `espn_connect` | Connect the selected HTTP season session or browser context. |
| `espn_sync` | Import verified observations and reconcile pending claims. |
| `espn_start_automation` | Run observations and analysis. Saved automatic modes permit supported actions within limits. |
| `espn_stop_automation` | Pause new actions across processes sharing the data directory. Stop this process's loop. |
| `espn_start_standalone_worker` | Transfer the saved connection to an independent local worker. |
| `espn_prepare_draft_pick` | Refresh the board and prepare one player under current limits. |
| `espn_submit_draft_pick` | Submit one pick. Review mode requires confirmation of the exact proposal. |
| `espn_reconcile_draft_pick` | Read the platform result without authorizing another click. |
| `espn_prepare_lineup` | Prepare a complete HTTP lineup transaction, or one legal swap through the browser adapter. |
| `espn_submit_lineup` | Submit the exact lineup proposal under saved limits and required confirmation. |
| `espn_reconcile_lineup` | Verify the resulting roster without another submission. |
| `espn_prepare_season_action` | Prepare an HTTP lineup, addition, claim, drop, or IR transaction. |
| `espn_submit_season_action` | Authorize one prepared HTTP transaction and observe its result. |
| `espn_reconcile_season_action` | Read the result of an HTTP transaction without another POST. |
| `espn_disconnect` | Stop this process's loop and release its connection and lease. |

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
It can continue after Codex closes while its computer, network, and authenticated session remain available.
HTTP season operation does not require a browser process.
Draft mode stops after the selected roster is complete.
Season mode uses the selected week or optional verified rollover.

Read status before starting another worker.
Use `espn_stop_automation` to set the shared pause flag.
An already submitted action still requires reconciliation.
The worker is not an operating-system service and does not resume automatically after a reboot.

## Validation boundary

Automated tests use HTTP clients with fictional state, browser stubs, and offline observations.
Isolated Chrome tests exercise the adapters against local page fixtures.
The [fourth draft](FOURTH_DRAFT_ACCEPTANCE.md) verified all 16 own selections with unchanged installed v0.3.1 execution methods.
A private orchestration launcher collected the remaining league history. One preauthorization error recovered without operator intervention.
The historical server acceptance checks recorded live lineup submission as **Not Tested**.
See the exact test checkpoint in [validation status](VALIDATION.md).
Earlier direct browser picks were verified separately. They do not prove this package's selector compatibility.
ESPN's API endpoints and page structure are unofficial integration surfaces.
The [HTTP compatibility report](ESPN_HTTP_COMPATIBILITY.md) records public transaction, lock, and IR source evidence.
[Service tests](../tests/test_espn_http_service.py) cover durable claims, lost responses, pending waivers, rollover, authentication failure, and team leases.
[Policy tests](../tests/test_espn_http_policy.py) and [action tests](../tests/test_espn_http_actions.py) exercise HTTP permission and reconciliation rules.
These fictional tests do not establish live account acceptance.

## HTTP season automation

1. Connect with `phase="season"`, `transport="http"`, and a week from 1 through 18.
2. Call `espn_sync`.
3. Read the source age, current transaction period, ownership, lock coverage, and pending claims.
4. Preserve the user's action modes, strategy, and hard limits.
5. Call `espn_start_automation` for continuous operation within that authorization.

Unpaused cycles read current state. The loop submits at most one admitted transaction per cycle.
It observes the result before a dependent action.
An acquisition and a later starter assignment require separate confirmed transactions.
Automatic IR operation considers eligible bench players and healthy reserves with an active roster vacancy.
Automatic FAAB claims use the league minimum bid. A different bid requires an exact prepared proposal within policy.

Use `espn_prepare_season_action` for an exact action under review or automatic mode.
Supply `lineup` for `set_lineup`. The map must contain every starter slot, including unchanged starters.
Supply `player_id` for other actions. Acquisitions also accept an optional `drop_id` and `bid`.
Traditional waivers and free-agent additions require `bid=0`.
Preparation refreshes local state and saves proposal evidence. It does not submit the transaction.
Use `espn_submit_season_action` for the returned proposal identifier.
Set `confirmation=true` only when review mode requires approval and the user approved that exact proposal.

Missing weekly projections remain null. Ordinary actions require a known improvement that meets the saved limit.
A named coverage repair can replace that comparison for a verified starter coverage gap.
The starter must appear in `limits.coverage_repair_ids`.
A nonempty `limits.coverage_repair_add_ids` also restricts replacements to those named players.
Pass the authorized starter as `repair_player_id` for a manual repair proposal.
This exception preserves locks, eligibility, player protection, drop permission, and budgets.
It does not permit invented projections or an automatic expansion of user authorization.

IR slot membership alone does not prove injury eligibility.
An IR move requires ESPN's explicit `injured=true`, slot eligibility, available capacity, and clear player locks.
Activation moves a reserve player to the bench and requires an active roster vacancy.
Read the full [policy behavior](POLICY.md) before changing limits.

## HTTP transaction results

Authorization saves one durable claim before the transaction POST.
Repeated submission of that proposal cannot send another POST.
The HTTP adapter has no verified caller idempotency key from ESPN.

| Status | Evidence and next action |
| --- | --- |
| `confirmed` | A fresh roster shows the expected change. An addition requires observed ownership. |
| `pending_waiver` | A matching pending claim exists. The player is not yet acquired. Continue reconciliation. |
| `not_submitted` | Preflight failed before the transaction request began. Correct the cause before preparing a new authorized proposal. |
| `rejected` or `cancelled` | A matching terminal receipt and unchanged fresh roster establish the result. |
| `conflict` | The fresh roster conflicts with the expected result or receipt. Inspect actual state before another action. |
| `awaiting_verification` | The outcome remains uncertain. Reconcile without a new submission or replacement proposal. |

Use `espn_reconcile_season_action` for another observation.
A timeout or HTTP success alone cannot establish ownership or completion.
Pending waiver commitments count against configured limits and block affected player moves.

Set `auto_rollover=true` only for authorized HTTP season operation that should follow ESPN's current transaction period.
The default is false. Unresolved submissions and pending waivers retain their original week.
The service rejects backward or unverified periods. Old-week reads cannot authorize current-week writes.

## Legacy browser lineup operation

The browser adapter supports one bench-to-starter swap or one starter exchange per proposal.
Each swap must independently meet the improvement limit.
It verifies the incoming player, destination occupant, and final observed lineup.
Some full lineup targets require intermediate swaps that the limit blocks.
One confirmed swap does not establish that the full target was applied.
This adapter uses an explicit week and does not perform HTTP acquisitions, IR moves, or automatic rollover.
