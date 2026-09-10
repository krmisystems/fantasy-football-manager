# Policy behavior

Strategy, execution permission, and hard limits are separate controls.
The manager's execution tools remain restricted to synthetic demonstrations.
Published v0.3.3 supports browser draft picks and one verified lineup swap per proposal.
The unreleased v0.4.0 candidate adds HTTP lineups, acquisitions, waiver claims, drops, and IR moves through the ESPN companion.
Trade execution remains unavailable.
A live trial on 2026-09-10 UTC verified one automatic HTTP free-agent add/drop and a subsequent lineup exchange.
The trial used exact user-authorized limits and restored the previous policy after verification.
Read [HTTP season acceptance](HTTP_SEASON_ACCEPTANCE.md) for the transaction receipts and roster verification.
Live waiver processing, IR moves, and scoring-week rollover remain **Not Tested**.

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

## HTTP season checks (unreleased)

The complete ESPN observation must match the selected league, team, season, and scoring week.
The source must be non-synthetic `espn_http` evidence with authenticated team ownership.
The requested week must match ESPN's verified transaction period before a write.
Own-team locks require the targeted team roster response. Generic player-pool flags do not establish those locks.
Pending transaction evidence must be known. Affected players cannot participate in another move.
Missing fields remain unknown and block actions that require them.
Incoming starters and acquisitions require verified bye-week evidence from the scoped professional team schedule.
A missing schedule or team join cannot establish that a player has no bye.

An HTTP lineup proposal contains every starter slot, including unchanged starters.
One transaction can contain several legal positional changes.
Locked assignments must remain unchanged. Changed players require clear locks and valid slot eligibility.
Ordinary lineup changes require a known projected improvement that meets `min_lineup_improvement`.
Missing weekly projections remain null. They are not zero-point estimates.

An acquisition must match the player's current ESPN free-agent or waiver status.
The result must satisfy roster size and position caps.
A required drop must satisfy its separate action mode, protection list, drop permission, and ESPN droppable state.
An empty allowed-drop list permits no drops in `listed_only` mode.
League acquisition limits, applicable counters, weekly move limits, and pending commitments must be known.
Incomplete transaction history cannot establish a zero balance or zero completed moves.

FAAB claims must satisfy league minimums, per-claim limits, weekly limits, season limits, and the configured reserve.
Pending claims reserve their bid amount and move count.
Traditional waivers and free-agent additions require a zero bid.
Ordinary acquisitions require a complete projected comparison that meets the improvement limit.

### Named coverage repair

A coverage repair replaces one explicitly authorized starter with a verified coverage gap.
The starter must appear in `limits.coverage_repair_ids` and remain unlocked on the current active lineup.
The gap must be a missing weekly projection or a supported unavailable status.
A nonempty `limits.coverage_repair_add_ids` restricts replacement players to that list.
An empty replacement list permits policy-valid candidates for the named starter. It does not authorize arbitrary starter repairs.

Manual proposals identify the starter through `repair_player_id`.
This exception replaces the ordinary improvement comparison. It does not invent a projection or lower the saved improvement limit.
The replacement still requires a verified weekly projection, eligibility, availability, and clear locks.
An acquisition for this repair cannot drop a current starter.
Drop authorization, protected players, budgets, and action modes remain mandatory.
The acquisition and starter replacement require separate confirmed transactions.

### IR operation

An IR move requires ESPN's explicit `injured=true` and IR slot eligibility.
A `DOUBTFUL` label or membership in `eligibleSlots` alone does not establish IR eligibility.
The player must be owned, unlocked, and free of conflicting pending transactions.
The roster must have an available IR slot.

Activation moves an IR player to the bench.
It requires a vacant active roster slot, bench eligibility, and capacity under the position cap.
The automatic loop considers injured bench players for IR and healthy reserves for activation.
It does not create an unauthorized drop to force activation.

### Claims, reconciliation, and rollover

Authorization saves a durable claim before the HTTP transaction request.
The service rechecks fresh evidence and policy immediately before that request.
A proved preflight failure records `not_submitted`. The same proposal cannot submit later.
Failures after the request boundary remain uncertain until reconciliation establishes the result.
Never create a replacement proposal to retry an uncertain request.

`confirmed` requires the expected fresh roster result. An addition requires observed ownership.
`pending_waiver` identifies a queued claim and does not establish ownership.
A matching failure or cancellation receipt requires an unchanged fresh baseline before the service records that terminal result.
Conflicting changes produce `conflict`. An unchanged roster alone does not prove rejection.
Reconciliation can inspect results without granting another write.

Optional `auto_rollover=true` follows ESPN's verified current transaction period.
The default remains false. Unresolved submissions and pending waivers retain their original week.
Backward periods and missing period evidence stop rollover.

The [HTTP policy tests](../tests/test_espn_http_policy.py), [action tests](../tests/test_espn_http_actions.py), and [service tests](../tests/test_espn_http_service.py) use fictional data.
The [compatibility report](ESPN_HTTP_COMPATIBILITY.md) records the supporting ESPN source contract.
These checks do not establish live write acceptance.

## Legacy browser lineup checks

The complete browser observation must match the selected league, team, season, and scoring week.
Each proposal contains exactly one legal swap and its full resulting lineup.
Each swap must meet the improvement limit, including intermediate swaps toward a larger target.
The browser checks the incoming player and destination occupant before its confirmation click.
An unresolved result blocks further moves until reconciliation.
Equivalent numbered slots are compared as occupant groups. The connected browser week does not roll over automatically.

## Synthetic season limits and strategies

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
