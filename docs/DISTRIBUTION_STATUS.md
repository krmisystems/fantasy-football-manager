# Distribution status

The checker compares this checkout with public distribution evidence.
It writes a JSON report and a Markdown summary.
It does not publish packages, refresh Glama, or call a Codex model.

Run this command from the repository root with Python 3.11 or later:

```text
python scripts/check_distribution_status.py --output .local-state/distribution-status/report.json --summary .local-state/distribution-status/summary.md
```

The script uses the Python standard library.
An optional `GH_TOKEN` supplies read access to GitHub metadata.
No PyPI, Glama, or model API key is required.
Do not place tokens in command arguments or reports.

The default exit code permits a completed check with pending or unknown states.
Read the report before declaring distribution complete.
Add `--strict` to return exit code 1 for pending, stale, failed, or unknown checks, including local checkout state.
Collection failure returns exit code 2.

## Evidence checked

| Surface | Comparison | Limit |
| --- | --- | --- |
| Checkout | Local commit and worktree state against GitHub `main` | Unpushed or uncommitted work does not prove a remote update. |
| GitHub CI | Latest `Test and package` run for the target commit | This distribution workflow does not count its own run as release validation. |
| Releases | Source version, GitHub release tag, and public PyPI version | Source changes do not automatically create a release. |
| Glama indexed source | Public source-tree commit against GitHub `main` | An indexed commit identifies the listing's source. It does not attest to the hosted runtime build. |
| Glama tools | Manager tool names and normalized descriptions, extracted from source with Python's AST parser | The current manager defines 17 tools. The five portfolio tools and ESPN tools belong to separate servers and are excluded. |
| Glama build information | Publicly exposed version and build evidence | A hidden build commit remains unknown. Python and image versions are separate values. |

Unavailable or ambiguous evidence remains unknown.
A pending external update remains pending until a later check confirms it.
A matching indexed commit or version cannot establish an unpublished runtime build commit.
Tool metadata comparison does not include input schemas, output schemas, or annotations.

The checker cannot verify the runtime build commit from the public pages it reads.
Thus `glama_build` remains unknown, and `--strict` currently returns a nonzero result even when every other check is current.
An owner-side build verification feature is not implemented.
An owner can review Glama Admin separately, but this checker does not import that evidence.

The 0.4.0 source candidate is newer than the published 0.3.3 package at this implementation's review.
That version difference is an intentional pending publication state, not evidence of a failed release.
Use the latest report for current versions.

Public evidence comes from [GitHub commit metadata](https://api.github.com/repos/krmisystems/fantasy-football-manager/commits/main),
[PyPI package metadata](https://pypi.org/pypi/fantasy-football-manager/json),
and Glama's [indexed source](https://glama.ai/mcp/servers/krmisystems/fantasy-football-manager/tree),
[tool listing](https://glama.ai/mcp/servers/krmisystems/fantasy-football-manager/schema),
and [overview](https://glama.ai/mcp/servers/krmisystems/fantasy-football-manager).
The Glama reader decodes observed page data without executing JavaScript.
That page format is undocumented. A format change can make a check unknown.

## Automatic reports

The [Distribution status workflow](../.github/workflows/distribution-status.yml) checks the canonical repository:

- After a push to `main`.
- After a published GitHub release.
- After `Test and package` completes on the repository's `main` branch.
- On a manual run selected from `main`.
- Daily at 07:17 UTC.

The workflow always checks out trusted `main`.
It does not execute a pull request checkout or download artifacts from an untrusted run.
Its GitHub permissions are limited to read access for contents, actions, and checks.
Concurrent runs wait, and each job has a ten-minute timeout.

The workflow attaches its summary to the job and saves both reports as an artifact for 30 days.
If collection fails before a report exists, the artifact records that failure as unknown distribution evidence.
A green workflow means the checker completed successfully. It does not mean every external state is current.

GitHub can delay scheduled jobs. Scheduled and workflow-completion triggers require the workflow file on the default branch.
See [GitHub's event documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).

This workflow only observes Glama.
It does not configure a webhook or request a sync or build.
The daily report can detect a later external update, but it does not cause that update.
This is a repository GitHub Actions hook plus an `AGENTS.md` completion instruction.
It does not change global Codex settings, native Codex hooks, or plugin hooks.

## Completion gate

Follow the [repository instructions](../AGENTS.md) after each update.
Run relevant tests and the release privacy validator.
Inspect the distribution report after the authorized remote update.
Report remaining external work separately from completed implementation work.

Publication and listing changes require authorization from the current task or earlier instructions.
A failed status comparison does not supply that authorization.
