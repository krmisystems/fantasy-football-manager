# ESPN compatibility matrix

**Record version: 4. Candidate: v0.4.0. Updated: 2026-09-10 UTC.**

The v0.4.0 candidate implements HTTP season actions and retains browser draft execution.
Source tests verify the new HTTP workflows with fictional responses.
Authenticated HTTP reads have verified five team contexts.
The reviewed candidate wheel is deployed privately. Its first HTTP sweep returned fresh observations for all five teams.
Live HTTP writes and publication remain incomplete at this checkpoint.

Read [HTTP season acceptance](HTTP_SEASON_ACCEPTANCE.md) for the candidate results and remaining gates.
Read [HTTP compatibility evidence](ESPN_HTTP_COMPATIBILITY.md) for the verified ESPN request contract and source artifacts.
This matrix retains the earlier source checks and installed-version evidence below.
Read [distribution acceptance](DISCOVERY_ACCEPTANCE.md) for verified publication status on each channel.
It does not guarantee compatibility with every ESPN layout or future website change.
Use [the ESPN workflow](ESPN_AUTOMATION.md) for operating instructions.

## Evidence terms

**Verified, fictional** means a test used invented league data or an isolated local browser fixture.
**Verified, live** means a recorded observation or action used an authenticated ESPN session.
**Planned** means the capability or acceptance trial is incomplete.
**Not Tested** means no matching acceptance result is recorded.

Fictional browser tests intercept page requests and supply controlled ESPN JSON responses.
They do not sign in to a real account or submit changes to a real league.
The test source contains inline fixtures where no separate HTML file is linked.
Fictional HTTP tests use a simulated ESPN service without a browser or a network connection.
These source tests do not establish live transaction acceptance.

## Version and layout coverage

| Version introduced | Input or control | Regression fixture and checks | Evidence boundary |
|---|---|---|---|
| v0.2.0 | Draft page identity, visible clock, standard Autopick controls, exact player row | [Draft Chrome fixture](../tests/test_browser_integration.py), [browser unit tests](../tests/test_espn_browser.py), [live policy tests](../tests/test_live_policy.py) | Verified, fictional. Duplicate rows, wrong context, enabled Autopick, and repeated permits block submission. |
| v0.2.0 | Weekly roster move controls and one final confirmation | [Season Chrome fixture](../tests/test_season_browser_integration.py), [lineup claim tests](../tests/test_browser_lineup.py) | Verified, fictional. Exact roster reconciliation is required. Equivalent RB or WR slot order does not imply a conflict. |
| v0.2.1 | Weekly header with `columnheader` role; player response containing only `players` | [Season Chrome fixture](../tests/test_season_browser_integration.py), [season normalization](../tests/test_espn_season_data.py), [request provenance checks](../tests/test_espn_data.py) | Verified, fictional and live reads. A player-only response must bind to the verified request URL. |
| v0.2.1 | Selected-team move controls, incomplete league-wide locks, changed roster ownership, delayed navigation | [Season normalization](../tests/test_espn_season_data.py), [season Chrome tests](../tests/test_season_browser_integration.py), [browser navigation tests](../tests/test_espn_browser.py) | Verified, fictional; selected-team live lock reads are recorded. Own-team controls cannot establish lock coverage for other teams. |
| v0.2.2 | Authenticated waiting-room entry, numeric roster selector, hidden Autopick input in its visible control, `Player Name` search | [Public draft HTML](../tests/fixtures/public_draft_room.html), [public draft Chrome test](../tests/test_espn_public_draft_integration.py), [browser unit tests](../tests/test_espn_browser.py) | Verified, fictional. The entry and selected roster must prove the requested context before search or submission. |
| v0.2.2 | Stale API pick placeholders, truncated Activity, full Pick History recovery, Players-tab restoration | [Public draft Chrome test](../tests/test_espn_public_draft_integration.py), [draft normalization and replay](../tests/test_espn_data.py) | Verified, fictional and working-tree live recovery. History must remain contiguous and agree with player identity and snake-round ownership. |
| v0.2.2 | Exact autocomplete suggestion before the target draft row appears; status and secondary-position labels | [Public draft HTML](../tests/fixtures/public_draft_room.html), [autocomplete checks](../tests/test_espn_browser.py), [history parser checks](../tests/test_espn_data.py) | Verified, fictional; later live draft receipts followed the fixes. Ambiguous suggestions and mismatched owners still block. |
| v0.2.2 | Shared browser profile across separate league databases; standalone startup receipt | [Profile configuration tests](../tests/test_browser_profile_config.py), [service tests](../tests/test_espn_service.py) | Verified, fictional and installed observation checks. One controller holds the profile lease at a time. |
| v0.3.0 | Serial season visits, explicit league and week, graceful stop, health, pending claim recovery | [Coordinator tests](../tests/test_server.py), [server acceptance](SERVER_ACCEPTANCE.md) | Verified, fictional and initial two-team server reads. Later handoffs expanded observation to four exact Week 1 contexts. Live server lineup submission remains unverified. |
| v0.3.0 | Durable evidence, PostgreSQL import, consistent SQLite snapshots, private backup sets | [Archive tests](../tests/test_archive.py), [backup tests](../tests/test_server_backup.py), [server acceptance](SERVER_ACCEPTANCE.md) | Verified with local tests and recorded server import and recovery checks. The archive is not a public dataset. |
| v0.3.1 | Surrounding whitespace in an API team name | [Waiting-room tests](../tests/test_espn_browser.py), [public draft Chrome test](../tests/test_espn_public_draft_integration.py) | Verified, fictional. Name normalization retains exact team, member, and roster checks. The third draft required a private workaround. The fourth draft completed with unchanged installed v0.3.1 methods. |
| v0.3.1 | Slash delimiters in D/ST autocomplete and position selectors | [D/ST Chrome tests](../tests/test_browser_integration.py) | Both `D/ST` and `DST` display variants reproduced the failure before the fix and passed afterward. Wrong-team and wrong-position suggestions remain blocked. A live Ravens D/ST selection succeeded in the fourth draft. The exact autocomplete branch was not established. |
| v0.3.2 | Confirmed opponent selection with an absent or empty season projection | [Draft normalization and replay](../tests/test_espn_data.py), [draft engine checks](../tests/test_draft.py) | Verified, fictional. The parser retains the verified identity with `projection=None`. The engine counts roster occupancy without scoring or recommending that player. Missing selected-team projections, ambiguous identities, and wrong owners still block. Live draft execution of an installed v0.3.2 wheel is Not Tested. |
| v0.4.0 candidate | Authenticated HTTP ownership, selected-team locks, request scope, and session leases | [HTTP authentication](../tests/test_espn_http_auth.py), [HTTP client](../tests/test_espn_http_client.py), [HTTP normalization](../tests/test_espn_http_data.py), [HTTP service](../tests/test_espn_http_service.py) | Verified, fictional and five authenticated team reads. HTTP mode does not require a browser. Live HTTP writes remain Not Tested. |
| v0.4.0 candidate | Full lineup proposals, acquisitions with optional drops, and observed ownership confirmation | [HTTP policy](../tests/test_espn_http_policy.py), [HTTP claims and receipts](../tests/test_espn_http_actions.py), [HTTP service](../tests/test_espn_http_service.py) | Verified, fictional. Authorization precedes one POST. A response alone does not establish roster ownership. |
| v0.4.0 candidate | Queued waivers, terminal receipts, changed FAAB bids, and context protection | [HTTP claims and receipts](../tests/test_espn_http_actions.py), [reconnect checks](../tests/test_espn_service.py), [HTTP service](../tests/test_espn_http_service.py) | Verified, fictional. A queued waiver retains its original context. Conflicting bids produce `conflict`. Reconciliation and settled replay do not submit another request. |
| v0.4.0 candidate | Unknown projections, named coverage repair, independent unavailable starters, and verified bye weeks | [Season comparisons](../tests/test_season.py), [HTTP policy](../tests/test_espn_http_policy.py), [HTTP normalization](../tests/test_espn_http_data.py) | Verified, fictional. Unknown projections remain null. A named repair does not invent an improvement. Unknown bye evidence blocks incoming starters and acquisitions. |
| v0.4.0 candidate | IR eligibility, active-roster capacity, and current-period rollover | [HTTP policy](../tests/test_espn_http_policy.py), [HTTP service](../tests/test_espn_http_service.py), [coordinator](../tests/test_server.py) | Verified, fictional. ESPN injury and slot evidence govern IR moves. Pending claims prevent rollover. Live IR moves and rollover remain Not Tested. |
| v0.4.0 candidate | Browser dependency isolation, readiness, and resulting roster evidence | [Dependency isolation](../tests/test_dependency_isolation.py), [coordinator](../tests/test_server.py), [evidence archive](../tests/test_evidence.py) | Verified, fictional. HTTP status works without Playwright. Health separates process activity from analysis and action readiness. Reconciliation archives the resulting snapshot. |

The version column identifies the implementation series. It does not relabel historical live runs as released-wheel acceptance.
The second draft trial used installed v0.2.1 dependencies and changing working-tree patches.

## Recorded live evidence and failures

| Observation or failure | Recorded result | Current interpretation |
|---|---|---|
| Authenticated weekly connection and sync | Installed v0.2.1 and v0.2.2 commands completed season reads and advisory calculations. | Verified live read workflow. No lineup write was submitted in those checks. |
| Draft startup compatibility failures | ESPN Autopick made the first two selections for the controlled roster. | Failure recorded. Waiting-room identity and control handling required fixes. |
| Autocomplete did not filter the player grid after text entry | At pick 131, manual suggestion selection was too late. ESPN Autopick selected a player. The proposal reconciled as `not_selected`. | Failure recorded. Exact autocomplete selection now has a fictional Chrome regression. |
| History recovery after restart | Availability and secondary-position labels exposed parser gaps. Manual recovery and patches restored complete history. | Recovery recorded. No claim of uninterrupted operation. |
| Second draft completion | All 160 league selections were verified. The selected roster contained 16 players: 13 manager-confirmed picks and 3 ESPN Autopicks. | Completed with failures and interventions. No duplicate submissions were observed. |
| Server season checks | After the fifth draft, all five exact Week 1 contexts had fresh browser observations, verified selected-team locks, and current accepted lineup calculations. | The [verified handoff](SERVER_ACCEPTANCE.md) recorded zero new lineup authorizations and zero unresolved authorized claims. Live server lineup submission remains Not Tested. |
| Future evaluation | All three additional draft trials and five-team Week 1 observation are complete. Five-team season outcomes remain pending. | Planned. Each completed draft retains its own runtime, failure, and execution-source limits. |
| Third draft trial | Host-capture reconciliation verified all 160 picks against the stored 133-pick prefix. Thirteen manager picks and three platform fallbacks filled the roster. | Team-name whitespace, a D/ST selector failure, and a late browser handoff required recovery. The final import has a separate source provider. Read the [third-draft record](THIRD_DRAFT_ACCEPTANCE.md). |
| Fourth draft trial | All 160 league picks and 16 manager-confirmed selections were verified. Zero ESPN Autopicks and zero host-browser draft clicks occurred. | Installed v0.3.1 execution methods were unchanged. A private launcher handled collection and lifecycle. No package patches, restart, or manual recovery were required during the run. Read the [fourth-draft record](FOURTH_DRAFT_ACCEPTANCE.md). |
| Fourth draft preauthorization error | One `browser_control` error occurred at the first turn. Its exact text was unavailable. | A later check recovered before submission. The error remains recorded despite all 16 confirmed selections. |
| Fifth draft history failure | An opponent selected a verified player whose matching season projection statistics were empty. Version 0.3.1 had excluded that identity and stopped accepting history after 132 picks. | The operator stopped the worker with zero unresolved claims. Version 0.3.2 separates history identity from projected value. This was not an availability-label parsing failure. |
| Fifth draft completion | The final host capture contains 160 selections and matches the stored 132-pick prefix. The roster has 13 manager-confirmed picks, two direct host picks, and one unattributed selection. | Installed v0.3.1 package methods remained unchanged. The browser handoff completed picks 146 and 155 with Autopick off. Read the [fifth-draft record](FIFTH_DRAFT_ACCEPTANCE.md). |
| v0.4.0 candidate HTTP reads | Authenticated reads verified ownership and selected-team locks in five private contexts. Four teams had complete lineup analysis with no projected improvement. | The remaining team had an unavailable starter with an unknown projection. Saved drop limits blocked its proposed acquisition. No live HTTP write occurred. Read [HTTP season acceptance](HTTP_SEASON_ACCEPTANCE.md). |
| v0.4.0 candidate deployment | All 28 installed Python files matched the reviewed wheel. Dependencies and team policies remained unchanged. The first HTTP sweep returned five fresh observations. | Four teams had current analysis and no required lineup change. One team had incomplete tight-end coverage. No live HTTP POST occurred. |

Read the [live draft acceptance record](LIVE_DRAFT_ACCEPTANCE.md) for failures, interventions, and receipt timing.
Read [server acceptance](SERVER_ACCEPTANCE.md) for deployment, archive, backup, and restart evidence.
The [multi-team plan](MULTI_TEAM_ACCEPTANCE.md) defines future evaluation measures.

## Repeat the checks

Install development and server dependencies from the locked checkout:

```sh
uv sync --locked --dev --extra server
```

Run unit, policy, parser, service, and coordinator checks:

```sh
uv run python -m pytest -q
```

That command skips Chrome and PostgreSQL integration cases unless their settings are supplied.
The v0.4.0 local suite passed 1,034 tests with 21 skips. Separate PostgreSQL validation passed all 77 archive tests.
A fresh base installation passed actual STDIO checks for 17 manager tools and 16 ESPN tools without Playwright.
Public release gates and live HTTP write acceptance remain incomplete.
Run the focused HTTP checks without a browser:

```sh
uv run python -m pytest -q tests/test_espn_http_auth.py tests/test_espn_http_client.py tests/test_espn_http_data.py tests/test_espn_http_policy.py tests/test_espn_http_actions.py tests/test_espn_http_service.py tests/test_dependency_isolation.py
```

The following counts remain historical results. They do not describe the complete v0.4.0 candidate suite.
The recorded v0.3.1 Windows run passed **611 tests**, including **17 isolated Chrome cases**, with two skips for PostgreSQL configuration and Windows symlink privileges.
The separate Linux PostgreSQL run passed **23 archive tests**.
These counts describe the recorded runs. Re-run the gates for a changed candidate.
The v0.3.2 source passed 611 tests with 19 skips in the base run, then all 17 separate Chrome cases.
Together, these runs passed **628 tests**, with two remaining local skips.
All seven [v0.3.2 source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34278096118) passed, including PostgreSQL and Chrome integration.

Run all three Chrome fixture files with installed Google Chrome.
On Linux or macOS:

```sh
FFM_BROWSER_TESTS=1 uv run pytest -q tests/test_browser_integration.py tests/test_season_browser_integration.py tests/test_espn_public_draft_integration.py
```

On PowerShell:

```powershell
$env:FFM_BROWSER_TESTS = "1"
uv run pytest -q tests/test_browser_integration.py tests/test_season_browser_integration.py tests/test_espn_public_draft_integration.py
```

The 17 recorded Chrome cases comprise 7 draft cases and 10 season cases.
They validate browser mechanics against fictional fixtures, not the current ESPN service.

Set `FFM_ARCHIVE_TEST_DSN` to a private PostgreSQL test database before the archive integration run:

```sh
uv run pytest -q tests/test_archive.py
```

The PostgreSQL case creates and removes an isolated validation schema.
Do not put connection credentials in documentation, fixtures, or public logs.
The [CI workflow](../.github/workflows/ci.yml) supplies a disposable PostgreSQL service.
The [release workflow](../.github/workflows/release.yml) requires the same commit's matrix, Chrome, and PostgreSQL gates before packaging.

## Limits and maintenance

The browser adapter supports draft picks and one legal lineup swap per proposal.
Each ordinary browser swap must meet the configured improvement limit.
The HTTP candidate implements full lineup proposals, waiver claims, free-agent additions, drops, IR moves, and IR activation.
It also implements rollover from verified current-period evidence.
These HTTP workflows have source-test coverage. Their live execution remains Not Tested at this checkpoint.
An HTTP proposal does not authorize a trade. Trade execution remains outside this release scope.

Ordinary lineup and acquisition proposals must meet the configured improvement limit.
A named coverage repair requires explicit configuration and preserves an unknown improvement when its baseline projection is missing.
Pending submissions retain their original context until reconciliation resolves them.
Queued waivers do not establish ownership, and uncertain responses do not authorize another submission.
The draft model uses a two-pick horizon and conditional availability estimates.

When ESPN changes a supported layout or HTTP response, record the blocked observation or action before changing the adapter.
Create a fictional fixture that reproduces the failure without private account data.
Add both a successful case and a case that must block an unsafe action.
Run the relevant fixture command and the complete release gates.
Update this matrix with the candidate version, test source, result, and live evidence boundary.
Retain previous failure records. Do not replace them with the later successful test result.
