# Discovery and distribution acceptance

**Scope: v0.3.0 discovery changes and v0.3.1 distribution checks. Updated: 2026-09-08.**

This record separates implemented changes from publication and measured adoption.
Deployment identities, credentials, traffic snapshots, and private league records remain outside the repository.

Version 0.3.1 adds the tested fixes from the [third draft](THIRD_DRAFT_ACCEPTANCE.md).
GitHub, PyPI, and MCP Registry publication checks passed. The local plugin update is verified.
Remote v0.3.1 SSH command checks passed with the state-isolation limit recorded below.
The historical v0.3.0 records retain their original evidence scope.

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

## Version 0.3.1 distribution checks

The release source commit is `5fd4727d0f21751508c9caac3fba62ba03c8c756`.
All seven [main CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262013806) passed.
The local suite passed **611 tests with two skips**, including **17 isolated Chrome cases**.

| Channel | Verified state |
|---|---|
| GitHub releases | [v0.3.1](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.1) is published as a prerelease. All five public downloads matched the reviewed hashes and sizes. |
| PyPI | [v0.3.1](https://pypi.org/project/fantasy-football-manager/0.3.1/) is published. The [approved workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262132640) passed. A fresh public installation passed checks for both MCP commands. |
| MCP Registry | The [v0.3.1 record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.1) was active and latest at 18:28:25 UTC on 2026-09-08. Exact-version and latest responses matched the reviewed metadata. The [GitHub OIDC workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262942173) passed from the release commit. |
| Local Codex plugin | Version 0.3.1 is installed and enabled with a Codex cachebuster. All six installed files match the cache. The private SSH configuration, including `PROGRAMDATA`, remains byte-identical. |

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

The server verified three-team Week 1 observation and analysis without a qualifying single lineup swap.
The five-team season evaluation remains planned. Read the [multi-team plan](MULTI_TEAM_ACCEPTANCE.md) for draft trial status.

See [draft acceptance](LIVE_DRAFT_ACCEPTANCE.md), [server acceptance](SERVER_ACCEPTANCE.md), and [validation status](VALIDATION.md).
