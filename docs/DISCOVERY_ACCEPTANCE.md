# Discovery and distribution acceptance

**Scope: v0.3.3 distribution checks and historical discovery evidence. Updated: 2026-09-09.**

This record separates implemented changes from publication and measured adoption.
Deployment identities, credentials, traffic snapshots, and private league records remain outside the repository.

Version 0.3.2 adds the tested player-identity fix from the [fifth draft](FIFTH_DRAFT_ACCEPTANCE.md).
GitHub, PyPI, and MCP Registry publication checks passed. Fresh public installation and the local plugin update are verified.
The v0.3.2 server upgrade and remote SSH command checks passed with the state-isolation limit recorded below.
Historical release records retain their original evidence scope.

## Version 0.3.3 distribution checks

Version 0.3.3 improves descriptions, parameter schemas, and behavior annotations across 17 manager tools and 13 ESPN companion tools.
The release source commit is `f04710724a52ef0a2da35795ca27b00eda37b0f3`.
Local checks passed **664 tests**, including all 17 isolated Chrome cases.
The two remaining skips require PostgreSQL configuration and Windows symlink privileges.
All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34314653579) passed.

| Channel | Verified state |
|---|---|
| GitHub releases | [v0.3.3](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.3) is published as a prerelease. All five public asset downloads matched the reviewed hashes. |
| PyPI | [v0.3.3](https://pypi.org/project/fantasy-football-manager/0.3.3/) is published. All eight [release workflow jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34314686784) passed: seven verification jobs and publication. |
| MCP Registry | The [v0.3.3 record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.3) was active and latest at 05:35:29 UTC on 2026-09-09. Exact-version and latest responses matched the reviewed metadata. The [publication workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34315361802) passed. |
| Glama inspection | Glama release 0.1.1 contains Python package 0.3.3. All 17 public manager definitions matched the reviewed export at 05:32:57 UTC on 2026-09-09. |

Both public PyPI distributions matched the reviewed files:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `fantasy_football_manager-0.3.3-py3-none-any.whl` | 114309 | `2c1593cc788cb317b0008ddd8df841ee685b7f56d192f67445705303329b035d` |
| `fantasy_football_manager-0.3.3.tar.gz` | 345471 | `ef442959c3a407a501475d4678847c144b3e72cfec9cd7c53aecb260a329edfd` |

A fresh public PyPI installation passed at 05:32:47 UTC on 2026-09-09 with Python 3.12.13.
All 23 installed package files matched the reviewed wheel.
Both STDIO commands reported version 0.3.3.
Their complete tool metadata matched the reviewed exports: 17 manager tools and 13 ESPN tools.
Capability and status calls passed without a provider browser, real league state, or live action.

The Glama comparison matched input schemas, output schemas, and annotations exactly.
Descriptions matched after removal of common docstring indentation and blank lines at the beginning and end.
The public changelog recorded Glama release 0.1.1 at 05:26:19 UTC.
This Glama image version differs from the Python package version.

At 05:55:51 UTC, all 17 updated tools had fresh **A** scores, ranging from 4.1 to 4.9.
All three priority definitions improved: `execute_demo_action` 2.7 to 4.8, `start_draft_monitor` 2.7 to 4.4, and `recommend_draft` 2.9 to 4.6.
The complete aggregate increased from **3.6/5 to 4.4/5**, with a new 05:51:47 UTC timestamp.
Its record counted all 17 tools, with a mean of 4.6 and a minimum of 4.1. Both public pages agreed, and all 17 definitions still matched the reviewed export.
The earlier 4.6 aggregate covered only 14 tools and is superseded by this complete result.
Tool definition quality increased from 3.3 to 4.4. Coherence remained 4.3.
Completeness reached 5/5, disambiguation remained 4/5, and naming remained 5/5. Tool count appropriateness decreased from 4/5 to 3/5.
At 21:04:38 UTC, the Glama hosted demonstration passed three calls: `get_capabilities`, `load_demo`, and `recommend_lineup`.
The sandbox reported v0.3.3 and returned the fictional 124.53-to-130.03 lineup projection, an estimated 5.50-point improvement.
All three calls returned `isError=false`. No real league data or live action was involved.
An earlier call through a restored Inspector tab returned HTTP 404. A fresh sandbox recovered the workflow.
At 21:05:27 UTC, the public score page showed **Active usage**, with six tool uses in the last 30 days.
This count does not establish unique users or independent adoption.
The 17:35:46 UTC TDQS evaluation retained 4.4 overall. Its coherence subscores were disambiguation 4, naming 5, tool count 4, and completeness 4.
Read the [tool definition review](TOOL_DEFINITION_QUALITY.md) for lint results and scoring limits.

These publication checks did not upgrade the running season service or establish new live ESPN acceptance.
Local plugin installation and any server upgrade require their own verification.
Package publication and the personal plugin do not establish official Codex marketplace inclusion.

## Findings and verification

| Finding | Change | Verification |
|---|---|---|
| Missing GitHub topics and About terms | About identifies ESPN, Codex, MCP clients, browser sign-in, approval modes, limits, and server monitoring. Twelve relevant topics classify the repository. | Verified with the GitHub repository API after the update. |
| Broad product positioning | The README and package metadata identify ESPN draft and lineup tools for Codex and other MCP clients. | Verified in source. The manager and ESPN companion remain separate commands. |
| Workflow appears after release details | The README starts with sign-in, sync, advisory lineup analysis, and status inspection. | The workflow matches the recorded authenticated read checks. It does not claim a live server lineup swap. |
| Specific search terms lack a clear explanation | The README explains ESPN MCP, browser sign-in without manual cookie copying, and lineup changes with approval. | Capability fit is verified. Search volume and conversion improvement are not measured. |
| Compatibility evidence is scattered | The [compatibility matrix](ESPN_COMPATIBILITY.md) links layouts, failures, fictional fixtures, repeatable commands, and live evidence. | The matrix preserves platform fallback and manual intervention records. |
| Weekly discovery measurements are absent | A [collector and measurement guide](DISCOVERY_MEASUREMENT.md) cover views, clones, referrers, and star counts. | Local tests verify deduplication, partial responses, repository scope, and atomic storage. Deployment verification appears below. |
| Distribution is incomplete | GitHub and PyPI packages are published. The manager is listed in the MCP Registry. The local Codex plugin includes both MCP commands. | Public downloads, fresh installation, Registry responses, and local plugin checks passed. Channel details appear below. |

The repository description is:

> ESPN draft and lineup tools for Codex and other MCP clients, with browser sign-in, approval modes, per-team limits, and server monitoring.

Topics are `browser-automation`, `codex`, `codex-plugin`, `espn`, `fantasy-draft`, `fantasy-football`, `lineup-optimization`, `mcp`, `mcp-server`, `monte-carlo`, `python`, and `self-hosted`.

## Version 0.3.2 distribution checks

The release source commit is `2810a7503073a52b4f80aacc4a35bf8d987530c5`.
All seven [main CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34278096118) passed.
Local checks passed **628 tests with two skips** across the base suite and separate Chrome run.
All **17 isolated Chrome cases** passed. PostgreSQL configuration and Windows symlink privileges account for the remaining skips.

| Channel | Verified state |
|---|---|
| GitHub releases | [v0.3.2](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.2) is published as a prerelease. All five public asset downloads matched the reviewed hashes. |
| PyPI | [v0.3.2](https://pypi.org/project/fantasy-football-manager/0.3.2/) is published. All seven checks and publication passed in the [approved workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34278117606). Public metadata and downloaded distributions matched the reviewed build. |
| MCP Registry | The [v0.3.2 record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.2) was active and latest at 21:09:50 UTC on 2026-09-08. Exact-version and latest responses matched the reviewed metadata. The [GitHub OIDC workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34278805847) passed. |
| Local Codex plugin | Version 0.3.2 is installed and enabled with a Codex cachebuster. All six installed files match the cache. The private SSH configuration, including `PROGRAMDATA`, remains byte-identical. |

Both public PyPI distributions matched these reviewed values:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `fantasy_football_manager-0.3.2-py3-none-any.whl` | 105304 | `da18734a6af2fbad0d1cdb07399212fdc912a4c067665205e9e7737b7958dbb3` |
| `fantasy_football_manager-0.3.2.tar.gz` | 322304 | `b54c3084abd69151a6e004c890852d5b01b0706f6837b1d33f3246b0d09120a5` |

A fresh Python 3.12.13 environment installed `fantasy-football-manager==0.3.2` from the public PyPI index with cache disabled.
At 21:10:03 UTC, both installed commands reported version 0.3.2 and listed 17 manager tools and 13 ESPN tools.
The manager capability check and ESPN status check passed.
This check did not open a browser, load real league state, or submit a live action.

The first fresh installation could not find version 0.3.2 in the public simple index, although metadata and distribution files were visible.
The second fresh installation passed after the simple index listed the version.
The failed attempt and successful retry remain separate private receipts.

The Registry record describes the manager entry point and links the paired installation guide.
Live browser actions require the ESPN companion entry point or the two-server Codex plugin.
These distribution checks do not establish official Codex marketplace inclusion.
A new Codex thread must load the updated local plugin.

The server upgrade completed separately at 21:11:49 UTC on 2026-09-08.
All 22 installed package files matched the reviewed v0.3.2 CI wheel. Dependency versions remained unchanged.
At 21:13:17 UTC, the preserved manager SSH target reported version 0.3.2 and 17 tools.
The ESPN command reported version 0.3.2 and 13 tools through the same SSH transport, environment, and installed executable.
Only its state directory changed to an isolated temporary directory, which was removed after the check.
The private MCP configuration remained unchanged.

The ESPN check did not launch the preserved league target or connect a provider browser.
No live action occurred. This isolation prevented lifecycle status writes to the coordinator's league database.
The five-team coordinator separately passed fresh Week 1 observation and current lineup analysis.
The final [server acceptance check](SERVER_ACCEPTANCE.md) verified ten coordinator cycles, all five archive cutoffs, and an eight-file backup.
The backup check verified file hashes, five SQLite integrity checks, and the PostgreSQL dump catalog. It did not perform a new PostgreSQL restore.
**Not Tested:** live draft submission through the corrected installed v0.3.2 wheel.
The [fifth draft record](FIFTH_DRAFT_ACCEPTANCE.md) separates its v0.3.1 live execution from the v0.3.2 fixture checks.

## Version 0.3.1 distribution checks

The release source commit is `5fd4727d0f21751508c9caac3fba62ba03c8c756`.
All seven [main CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262013806) passed.
The local suite passed **611 tests with two skips**, including **17 isolated Chrome cases**.

| Channel | Verified state |
|---|---|
| GitHub releases | [v0.3.1](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.1) is published as a prerelease. All five public downloads matched the reviewed hashes and sizes. |
| PyPI | [v0.3.1](https://pypi.org/project/fantasy-football-manager/0.3.1/) is published. The [approved workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262132640) passed. A fresh public installation passed checks for both MCP commands. |
| MCP Registry | The [v0.3.1 record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.1) was active and latest at 18:28:25 UTC on 2026-09-08. Exact-version and latest responses matched the reviewed metadata. The [GitHub OIDC workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262942173) passed from the release commit. |
| Local Codex plugin | Version 0.3.1 was installed and enabled with a Codex cachebuster at this check. All six installed files matched the cache. The private SSH configuration, including `PROGRAMDATA`, remained byte-identical. |

A fresh Python 3.12.13 environment installed `fantasy-football-manager==0.3.1` from the public PyPI index.
The check disabled cache and local configuration and removed environment overrides.
Both commands reported version 0.3.1 and listed 17 manager tools and 13 ESPN tools.
The manager capability check and ESPN status check passed.
Both downloaded distributions matched the reviewed PyPI hashes and sizes.
This check did not open a browser, use real league state, or submit a live action.

The first installation could not find version 0.3.1 in the public simple index, although package metadata and files were visible.
The same installation check passed after the simple index listed the version.
The failed attempt and successful retry remain separate private receipts.

The server package was upgraded separately after the local plugin installation.
All 22 installed package files matched the reviewed v0.3.1 wheel. Dependency versions remained unchanged.
The preserved manager SSH connection reported version 0.3.1 and 17 tools. Capability and source-status calls passed.
The ESPN SSH check reported version 0.3.1 and 13 tools through the same transport, environment, and installed executable.
Only its state directory changed to an isolated temporary directory, which was removed after the check.
This prevented lifecycle status writes to the running coordinator's league database.
The preserved ESPN league target was not launched during this check. No browser connection or live action occurred.
A new Codex thread must load the updated plugin.

## Historical v0.3.0 distribution checks

| Channel | Verified state |
|---|---|
| GitHub releases | [v0.3.0](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.0) is published from commit `d3acc32150ad71b0d85847f603fcd7649a2436b7`. All five asset downloads matched the reviewed hashes. Earlier assets remain unchanged. |
| PyPI | [v0.3.0](https://pypi.org/project/fantasy-football-manager/0.3.0/) is published. The [trusted-publisher workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34198024653) passed. Both public distribution hashes match the reviewed CI artifact. The ownership marker is present. |
| MCP Registry | The [v0.3.0 record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.0) was active and latest at publication. Exact-version and latest responses matched the reviewed metadata. The [GitHub OIDC workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34199217116) passed. |
| Local Codex plugin | The v0.3.0 plugin passed SSH STDIO checks for 17 manager tools and 13 ESPN tools. This is a personal installation. |

The registry record describes the manager entry point.
Live browser actions require the ESPN companion entry point or the two-server Codex plugin.
Package and registry publication do not establish official Codex marketplace inclusion.

A fresh Python 3.12.13 environment installed `fantasy-football-manager==0.3.0` from the public PyPI index with cache and local configuration disabled.
Both installed commands passed STDIO initialization and tool listing: 17 manager tools and 13 ESPN tools.
Both reported version 0.3.0. Read-only capability and status calls passed.
This installation check did not open a browser or submit a live action.

## Measurement checks

The collector preserves each observation and deduplicates overlapping daily traffic records.
It keeps 14-day windows, referral snapshots, and star snapshots separate.
Missing API responses remain errors or missing values. They do not become zero counts.
The authenticated baseline returned HTTP 200 for all four endpoints with the dedicated repository read token.
The installed service then completed a second collection with exit code 0.
Its weekly timer is active and enabled for startup. The next scheduled run is 2026-09-14.
Both reports remain private. Successful manual service execution does not establish a future scheduled result.

The v0.3.0 Windows run passed **608 tests with two skips in 33.48 seconds**, including all 15 Chrome cases.
The skips required PostgreSQL configuration and Windows symlink privileges.
Separate Linux runs passed **23 PostgreSQL archive tests** and **28 discovery collector tests**.
Release metadata, known private-pattern checks, MCP examples, and local documentation links passed validation.

A baseline captured after these changes cannot establish their causal effect.
Clones do not establish successful installations. Stars do not establish active users.
Review reporting delays and the repository's age before drawing conclusions from small counts.

## Product evidence boundaries

The second live draft ended with 13 manager-confirmed picks and three ESPN Autopicks after compatibility failures and manual recovery.
It used changing development patches, not one unchanged released wheel.

The [third draft](THIRD_DRAFT_ACCEPTANCE.md) also verified 13 manager-confirmed selections and three ESPN Autopicks.
Its visible history contains all 160 selections, and its selected roster contains 16 players.
That runtime used v0.3.0 with private recovery changes. The corrected v0.3.1 source has separate fixture evidence.
The final host capture matched the stored 133-pick prefix and completed the stored 160-pick history.
This import has a separate source provider. The completed server draft page could not be reopened for fresh observation.
The third roster then passed fresh Week 1 browser observation after the server upgrade to v0.3.1.

The [fourth draft](FOURTH_DRAFT_ACCEPTANCE.md) confirmed all 16 own picks and captured 160 league picks through the live server browser.
Installed v0.3.1 execution methods remained unchanged. A private orchestration launcher collected the final league history.
One preauthorization browser error recovered without operator intervention. No platform fallback or manual selection was required.
Live D/ST selection passed. The exact autocomplete branch remains separate fixture evidence.

The [fifth draft](FIFTH_DRAFT_ACCEPTANCE.md) verified 13 manager selections, two direct host selections, and one selection with an unidentified executor.
The final host capture contains all 160 picks and matches the stored 132-pick prefix.
An opponent's missing season projection blocked the unchanged v0.3.1 parser. Version 0.3.2 has separate fixture evidence for the correction.
Five-team Week 1 observation, current lineup calculations, archive cutoff coverage, and backup checks passed.

The earlier server checks verified four-team Week 1 observation and analysis without a qualifying single lineup swap.
The archive contained every event through four checked cutoffs. All four SQLite backups passed checksum, context, and quick checks.
The five-team season evaluation remains planned. Read the [multi-team plan](MULTI_TEAM_ACCEPTANCE.md) for draft trial status.

See [draft acceptance](LIVE_DRAFT_ACCEPTANCE.md), [server acceptance](SERVER_ACCEPTANCE.md), and [validation status](VALIDATION.md).
