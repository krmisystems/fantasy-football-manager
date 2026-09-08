# Discovery and distribution acceptance

**Scope: discovery changes for v0.3.0. Updated: 2026-09-08.**

This record separates implemented changes from publication and measured adoption.
Deployment identities, credentials, traffic snapshots, and private league records remain outside the repository.

## Findings and verification

| Finding | Change | Verification |
|---|---|---|
| Missing GitHub topics and About terms | About identifies ESPN, Codex, MCP clients, browser sign-in, approval modes, limits, and server monitoring. Twelve relevant topics classify the repository. | Verified with the GitHub repository API after the update. |
| Broad product positioning | The README and package metadata identify ESPN draft and lineup tools for Codex and other MCP clients. | Verified in source. The manager and ESPN companion remain separate commands. |
| Workflow appears after release details | The README starts with sign-in, sync, advisory lineup analysis, and status inspection. | The workflow matches the recorded authenticated read checks. It does not claim a live server lineup swap. |
| Specific search terms lack a clear explanation | The README explains ESPN MCP, browser sign-in without manual cookie copying, and lineup changes with approval. | Capability fit is verified. Search volume and conversion improvement are not measured. |
| Compatibility evidence is scattered | The [compatibility matrix](ESPN_COMPATIBILITY.md) links layouts, failures, fictional fixtures, repeatable commands, and live evidence. | The matrix preserves platform fallback and manual intervention records. |
| Weekly discovery measurements are absent | A [collector and measurement guide](DISCOVERY_MEASUREMENT.md) cover views, clones, referrers, and star counts. | Local tests verify deduplication, partial responses, repository scope, and atomic storage. Deployment verification appears below. |
| Distribution is incomplete | The project has a package workflow, Codex plugin, registry metadata, and configured PyPI trusted publisher. | Channel-specific publication status appears below. Prepared metadata is not proof of publication. |

The repository description is:

> ESPN draft and lineup tools for Codex and other MCP clients, with browser sign-in, approval modes, per-team limits, and server monitoring.

Topics are `browser-automation`, `codex`, `codex-plugin`, `espn`, `fantasy-draft`, `fantasy-football`, `lineup-optimization`, `mcp`, `mcp-server`, `monte-carlo`, `python`, and `self-hosted`.

## Distribution checks

| Channel | Verified state |
|---|---|
| GitHub releases | v0.2.2 remains published. The v0.3.0 release is prepared and awaits final commit checks and publication. |
| PyPI | Account verification and a pending trusted publisher are configured. Package upload is not yet verified. |
| MCP Registry | Official publisher authentication and metadata validation passed. Registry publication is not yet verified. |
| Local Codex plugin | The v0.3.0 plugin passed SSH STDIO checks for 17 manager tools and 13 ESPN tools. This is a personal installation. |

The registry record describes the manager entry point.
Live browser actions require the ESPN companion entry point or the two-server Codex plugin.
Package and registry publication do not establish official Codex marketplace inclusion.

## Measurement checks

The collector preserves each observation and deduplicates overlapping daily traffic records.
It keeps 14-day windows, referral snapshots, and star snapshots separate.
Missing API responses remain errors or missing values. They do not become zero counts.
The authenticated baseline returned HTTP 200 for all four endpoints with the dedicated repository read token.
The installed service then completed a second collection with exit code 0.
Its weekly timer is active and enabled for startup. The next scheduled run is 2026-09-14.
Both reports remain private. Successful manual service execution does not establish a future scheduled result.

The final Windows run passed **608 tests with two skips in 33.48 seconds**, including all 15 Chrome cases.
The skips required PostgreSQL configuration and Windows symlink privileges.
Separate Linux runs passed **23 PostgreSQL archive tests** and **28 discovery collector tests**.
Release metadata, known private-pattern checks, MCP examples, and local documentation links passed validation.

A baseline captured after these changes cannot establish their causal effect.
Clones do not establish successful installations. Stars do not establish active users.
Review reporting delays and the repository's age before drawing conclusions from small counts.

## Product evidence boundaries

The recorded live draft ended with 13 manager-confirmed picks and three ESPN Autopicks after compatibility failures and manual recovery.
It used changing development patches, not one unchanged released wheel.
The server verified two-team observation and analysis without a qualifying live lineup swap.
The five-team season evaluation and three additional drafts remain planned.

See [draft acceptance](LIVE_DRAFT_ACCEPTANCE.md), [server acceptance](SERVER_ACCEPTANCE.md), and [validation status](VALIDATION.md).
