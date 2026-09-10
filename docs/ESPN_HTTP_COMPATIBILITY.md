# ESPN HTTP compatibility evidence

Verified source review: 2026-09-10 UTC. This report records ESPN's public football application code, retrieved through HTTP requests.
It does not claim that every transaction has passed a live account test.
No browser, account request, or live transaction was used for this source review.

## Source artifacts

The public [football team page](https://fantasy.espn.com/football/team) referenced these assets at review time.
Offsets below count zero-based Unicode characters after UTF-8 decoding. SHA-256 values identify the original response bytes.

| Asset | Public source | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Main bundle | [ESPN main bundle](https://cdn1.espn.net/kona/5a90d30cd38d-1.490/_next/static/commons/main-82d208d52efd2b467c49.js) | 9680523 | `573c650d2b7360fd432ce64360cfac95855749d8abe8b97bad82cfcf1c9b7823` |
| Football team page | [ESPN team bundle](https://cdn1.espn.net/kona/5a90d30cd38d-1.490/_next/665d2b9b-1cde-46fb-ab1c-8c623982286e/page/football/team.js) | 766915 | `118dcf4396e438b440abbe9bbad25576b05a155d38fa8211e3f2e0748513029e` |

| Evidence | Asset and offset | Search anchor |
| --- | --- | --- |
| HTTP host selection | Main, 125909 | `const St=` |
| HTTP headers and credentials | Main, 126313 and 126772 | `const zt=`, `const Yt=` |
| HTTP POST transport | Main, 128184 | `function Zt(e)` |
| Combined league read | Main, 135157 | `function Ln(){Ln=nt(function*({config:e,guest:t` |
| Targeted period roster read | Main, 136574 | `function xn(){xn=nt(function*({config:e,filters:t` |
| Pending transaction default | Main, 158003 | `pendingTransactions:Object` |
| Player injury eligibility | Main, 182746 | `injured:Object` |
| Player lock fields | Main, 183293, 184496, 184702 | `lineupLocked:Object`, `rosterLocked:Object`, `tradeLocked:Object` |
| Team ownership | Main, 203726 | `owners:Object` |
| Transaction endpoint | Main, 216041 | `function lo(e,t,n,r)` |
| Professional team schedule request | Main, 224278 | `function Go()` |
| Football player bye week | Main, 188584 | `c.proTeamByeWeek=` |
| Player-to-professional-team join | Main, 188890 | `c.proTeamSchedule=` |
| Transaction dispatch | Main, 828802 | `class M{createTransaction` |
| Acquisition counter check | Main, 911319 | `y.transactionCounter.matchupAcquisitionTotals` |
| FAAB bounds | Main, 915161 | `minimumBid,a=e.acquisitionBudget` |
| Drop eligibility | Main, 929148 | `const i=r.droppable` |
| Lineup item builder | Main, 4867223 | `const u=e=>e.map(e=>i({fromSlotId:` |
| Transaction serialization | Main, 4868309 | `class b{constructor({bidAmount:` |
| Transaction failure states | Main, 7607829 | `transactionStatusTypes:[{failed:true,id:-1,name:"FAILED_UNKNOWN"}` |
| Requested football views | Team, 77001 | `view:["mDraftDetail","mLiveScoring"` |
| Football MOVE lock check | Team, 125572 | `if(a.abbreviation===C)if(u&&u.lineupLocked` |
| Slot eligibility | Team, 127343 | `154:function` |
| Pending transaction team filter | Team, 491923 | `408:function` |
| Manage IR candidate filter | Team, 720509 | `const F=D.filter(e=>e.injured` |

## Read contract

Verified: the production read host is `https://lm-api-reads.fantasy.espn.com`.
The football league path is `/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league}`.

The football team page requests these views:

```text
mDraftDetail, mLiveScoring, mMatchupScore, mPendingTransactions,
mPositionalRatings, mRoster, mSettings, mTeam
```

Its combined league request supplies `rosterForTeamId={team}`.
Its separate roster request supplies `forTeamId={team}`, `scoringPeriodId={period}`, and `view=mRoster`.
These are distinct request shapes. A general player-pool response does not prove that a selected roster's lock fields are current.

The league model reads root `pendingTransactions` and defaults an omitted value to an empty list.
The team filter includes transactions with a matching `teamId` or matching item `fromTeamId` or `toTeamId`.
The manager must establish authentication, requested views, and league context before it applies this default.
An incomplete request must not establish that no pending claim exists.

Player-pool wrappers supply `onTeamId`, `status`, `lineupLocked`, `rosterLocked`, `tradeLocked`, and `waiverProcessDate`.
Roster entries supply `playerId`, `lineupSlotId`, and an embedded `playerPoolEntry`.
The team model exposes `owners`, `primaryOwner`, and `isTransactionLocked`.
The manager must compare its session member with the selected team's owners before a write.

Verified client support: [espn-api authentication](https://github.com/cwendt94/espn-api/blob/master/espn_api/base_league.py) uses the `espn_s2` and `SWID` cookies.
Its [request client](https://github.com/cwendt94/espn-api/blob/master/espn_api/requests/espn_requests.py) supplies these cookies to HTTP reads.
The inspected client does not establish an unattended password sign-in contract.

## Professional team schedule and bye weeks

Verified: ESPN's application requests `view=proTeamSchedules_wl` at the football season endpoint.
It reads `settings.proTeams` from that response.
The player model selects the row whose `id` equals the player's positive `proTeamId`.
For football, `proTeamByeWeek` returns that row's `byeWeek`, or null when the value is absent or zero.
The application keeps this schedule cache separate for each sport, season, and professional team.

An unauthenticated GET verified this public endpoint on 2026-09-10 UTC:

```text
https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026?view=proTeamSchedules_wl
```

The response returned HTTP 200 at the exact requested URL.
Its 109163 response bytes had SHA-256 `280a1af4b7491ae6572dbca6590cf398404a0482bf612dd0c5b0cc7803d29826`.
Its root fields were `display` and `settings`. It contained no embedded `seasonId` or `gameId`.
`settings.proTeams` contained 32 NFL teams and one free-agent row.
The rows supplied `id`, `abbrev`, `byeWeek`, and `proGamesByScoringPeriod` among their fields.
The free-agent row used `byeWeek: 0`. All observed bye-week values were integers.

Manager contract: bind this response to the exact observed football season URL before joining it to player data.
Reject conflicting embedded context if a later response supplies those fields.
Match player `proTeamId` to one unique professional team row, including for D/ST players.
Do not use the fantasy team ID or the D/ST player ID for this join.
Missing team or bye-week evidence must remain unknown. It cannot establish that a player has no bye.
This public read establishes the data contract, not a live manager action or a completed implementation test.

Separate [normalizer tests](../tests/test_espn_http_data.py) verify scoped bye-week joins, D/ST identifiers, missing evidence, and invalid values.
[Service tests](../tests/test_espn_http_service.py) verify schedule refresh and rejection of incoming players with unknown bye evidence.
These tests use fictional responses and do not submit live transactions.

## Transaction contract

Verified: ESPN's application sends HTTP POST requests to:

```text
https://lm-api-writes.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league}/transactions/
```

The application sends `Content-Type: application/json`, `X-Fantasy-Source: kona`, and `X-Fantasy-Platform: espn-fantasy-web`.
It enables credentials. Its shared request configuration adds a `platformVersion` query value.

The ordinary owner body includes `isLeagueManager: false`, `teamId`, `type`, `scoringPeriodId`, and `executionType: "EXECUTE"`.
It includes `memberId` when the signed-in member identifier is available.
It includes `items` when at least one item exists.
The manager must not request commissioner powers or skip transaction counters.

| Operation | Outer `type` | Item fields |
| --- | --- | --- |
| Current lineup move | `ROSTER` | `playerId`, `type: "LINEUP"`, `fromLineupSlotId`, `toLineupSlotId` |
| Future lineup move | `FUTURE_ROSTER` | Same lineup item fields |
| Immediate acquisition | `FREEAGENT` | `playerId`, `type: "ADD"`, `toTeamId` |
| Waiver claim | `WAIVER` | Same add item fields |
| Drop | `ROSTER` | `playerId`, `type: "DROP"`, `fromTeamId` |
| Move into or out of IR | `ROSTER` for the current period | Same lineup item fields |

The official lineup builder omits `fromTeamId` and `toTeamId` for lineup items.
An acquisition can include its required drop in the same transaction.
The application also supports combined DROP and LINEUP items under `ROSTER`.
Football bench and IR slot identifiers are `20` and `21`; basketball slot identifiers differ.

After the draft, the move dispatcher uses `FUTURE_ROSTER` when the requested period exceeds `status.latestScoringPeriod`.
Otherwise, it uses `ROSTER` and the latest period.
A rollover implementation must read the new period before it prepares another action.

For FAAB claims, the body includes `bidAmount`.
Traditional claims do not require the FAAB field in the inspected builder path: an undefined value disappears during JSON serialization.
The claim modal uses `minimumBid` and `acquisitionBudget - transactionCounter.acquisitionBudgetSpent` as its bid bounds.
The acquisition button treats `acquisitionLimit: -1` as unlimited.
Otherwise, it compares that limit with the sum of `transactionCounter.matchupAcquisitionTotals` values.
These league counters do not independently establish the manager's weekly budget or pending reservations.

## Lock and IR checks

Verified: the football MOVE control uses the selected player's `lineupLocked` field.
The player model reads that value from `playerPoolEntry.lineupLocked`.
The inspected control does not calculate a replacement lock value from a schedule.
Conflicting or incomplete lock evidence must stop a manager write.

The ordinary drop predicate requires both `rosterLocked` and `tradeLocked` to be false.
It also honors `droppable` when `settings.rosterSettings.isUsingUndroppableList` is true.
The predicate excludes additional players reserved by a roster-fix operation.

The slot helper checks `player.eligibleSlots` for the destination slot identifier.
That check alone does not establish IR eligibility.
Manage IR first selects players with `player.injured` true who are outside the IR slot.
The model reads `injured` directly from `playerPoolEntry.player.injured`, separately from the injury status text.
The manager must also verify the IR slot count, current occupancy, ownership, and lock state.
It must not infer IR eligibility from a `DOUBTFUL` or `QUESTIONABLE` label.

Activation uses an empty non-IR slot when one exists.
Otherwise, the application opens its roster-fix flow.
The manager must plan the complete legal transaction before it removes a player from IR.

## Reconciliation and remaining validation

Verified: the inspected serializer supplies no caller-selected idempotency key.
It does not establish safe duplicate retries after a lost response.
ESPN's transaction status constants distinguish `PENDING`, `EXECUTED`, `CANCELED`, and multiple failure states.
The constants mark `FAILED_LINEUPLOCK`, `FAILED_ROSTERLOCK`, `FAILED_IRSLOT`, `FAILED_NOPERMISSION`, and other `FAILED_*` values with `failed: true`.
They also include `FAILED_UNKNOWN`, `FAILED_UNDROPPABLEPLAYER`, `FAILED_MATCHUPACQUISITIONLIMIT`, and `FAILED_MINIMUMBID`.
An HTTP success response alone does not establish the final roster change.

Manager reconciliation rule: accept a matching `FAILED_*` receipt as rejection only when a fresh roster still matches the authorized baseline.
The receipt must match the exact transaction context and items.
A changed roster with a failure receipt is conflicting evidence. An unchanged roster without a matching failure receipt remains uncertain.
These rules are implementation requirements derived from the source contract. This source review did not trigger a live failure response.

The [espn-api transaction reader](https://github.com/cwendt94/espn-api/blob/master/espn_api/football/league.py) uses `view=mTransactions2` with `scoringPeriodId`.
It supplies transaction type filters through `X-Fantasy-Filter`.
Its [transaction model](https://github.com/cwendt94/espn-api/blob/master/espn_api/football/transaction.py) reads status, period, dates, bid amount, and items.

Planned validation requirements:

1. Verify the selected league, season, period, and owner through authenticated reads.
2. Verify targeted roster locks and pool ownership before each submission.
3. Save an action intent before the HTTP request.
4. Reconcile the response with transaction history, pending claims, and a fresh targeted roster.
5. Keep uncertain submissions unresolved until read evidence establishes their outcome.
6. Verify pending claims separately from completed acquisitions.
7. Stop dependent actions when a rollover changes the scoring period.

Not Tested by this source review: live football add/drop, waiver processing, IR activation, future-period propagation, and transaction response loss.
Publication or release claims must cite separate test evidence for those behaviors.
