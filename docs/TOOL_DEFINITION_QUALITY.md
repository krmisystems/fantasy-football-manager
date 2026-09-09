# MCP tool definition quality

## Objective and baseline

Improve tool selection and invocation while preserving existing tool names, defaults, accepted calls, and execution policy.
This work covers the 17 manager tools and 13 ESPN companion tools.

The public Glama baseline showed an overall TDQS of **3.6/5, tier A**, scored at 10:01:10 UTC on 2026-09-08.
The weakest manager definitions were `execute_demo_action` (2.7), `start_draft_monitor` (2.7), and `recommend_draft` (2.9).
Naming consistency already scored 5/5.
The baseline describes indexed definitions. It does not verify fantasy results or application reliability.

The [TDQS specification](https://tdqs.dev/spec) weights tool definition quality at 70% and server coherence at 30%.
The definition aggregate gives additional weight to the lowest tool score.
The [public listing](https://glama.ai/mcp/servers/krmisystems/fantasy-football-manager) and its tool pages provide the external baseline.

## Verified metadata and lint results

The 0.3.3 metadata export completed on 2026-09-09 with isolated temporary state.
It contained all 17 manager tools and all 13 ESPN companion tools.
The export did not connect a browser or submit a live action.
Each tool had 100% description coverage for its top-level input parameters.
This measure also assigns 100% coverage to tools with no parameters.

Offline lint used the pinned `tdqs==0.1.0` package and specification 1.2.
It made no model calls.
The public manager baseline produced nine `undocumented-parameters` warnings.
The updated manager definitions resolved all nine warnings.

| Definition set | Deterministic lint findings | Result with `--fail-on warning` |
|---|---|---|
| Public manager baseline | Nine undocumented-parameter warnings | Exit 1 |
| Updated manager, 17 tools | Three structural shadow candidates | Exit 1 |
| Updated ESPN companion, 13 tools | No findings | Exit 0 |

The updated manager also passed the `--fail-on error` threshold.
The three remaining warnings come from a schema-cost comparison.
They identify pairs for further review without deciding whether their purposes overlap.
Passing lint does not establish a TDQS score. Read the [official CLI documentation](https://tdqs.dev/cli) for this distinction.

| Candidate | Lower-cost tool | Distinct operations to review |
|---|---|---|
| `import_league_snapshot` | `prepare_action` | Import replaces the stored league snapshot. Preparation saves a synthetic action proposal against existing state. |
| `update_manager_config` | `get_action_history` | Configuration update replaces strategy, automation, and limits. History reads audit records. |
| `prepare_action` | `update_manager_config` | Preparation saves a synthetic action proposal. Configuration update changes policy and invalidates existing proposals. |

**Verified:** Manual review found distinct inputs, effects, and results for all three pairs.
None of the lower-cost tools can perform its paired operation.
The warnings remain visible because the deterministic lint does not evaluate those semantics.
The expanded schemas remain available for valid snapshot, configuration, and action inputs.
Removing useful schema details would hide required input structure without establishing that the tools have different purposes.

Version metadata now matches 0.3.3 across the package, runtime, lockfile, plugin, and Registry document.
The dependency definitions and all 72 locked package records remain unchanged, except for the local package version.
Offline lock validation and release metadata validation passed.
Registry workflow permissions and the pinned publisher remain unchanged.

## Release and Glama verification

The [v0.3.3 release](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.3) uses commit `f04710724a52ef0a2da35795ca27b00eda37b0f3`.
All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34314653579) passed.
The separate [PyPI release workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34314686784) passed its seven verification jobs and publication job.
Five GitHub release downloads matched their reviewed hashes. The PyPI wheel and source archive matched the same reviewed files.
The [MCP Registry record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.3) was active and latest at 05:35:29 UTC on 2026-09-09.
Both exact-version and latest responses matched the reviewed Registry metadata.

A fresh public PyPI installation passed on 2026-09-09 at 05:33 UTC.
All 23 installed package files matched the reviewed wheel.
Actual STDIO metadata matched the final export for all 17 manager and 13 ESPN tools.
Both empty-state read-only checks passed. The installed CLI demo returned the verified fictional 5.50-point improvement.
An earlier install attempt could not resolve the new version from the package index.
Index propagation is the likely cause, but the earlier index response was not captured.
Both attempts remain separate in the private evidence record.

Glama built and released the reviewed commit on 2026-09-09 at 05:26 UTC.
Its image release is **0.1.1**; the initialized Python package is **0.3.3**.
At 05:32:57 UTC, the public catalog contained all 17 updated manager definitions.
Input schemas, output schemas, and annotations matched exactly.
Descriptions matched after normalization of docstring indentation and surrounding blank lines.
The public schema changelog recorded the new Glama release at 05:26:19 UTC.

At 05:55:51 UTC, **all 17 updated tools had fresh A scores**, ranging from 4.1 to 4.9.
The three priority definitions all improved:

| Tool | Baseline score | New score |
|---|---:|---:|
| [`execute_demo_action`](https://glama.ai/mcp/servers/krmisystems/fantasy-football-manager/tools/execute_demo_action) | 2.7 | 4.8 |
| [`start_draft_monitor`](https://glama.ai/mcp/servers/krmisystems/fantasy-football-manager/tools/start_draft_monitor) | 2.7 | 4.4 |
| [`recommend_draft`](https://glama.ai/mcp/servers/krmisystems/fantasy-football-manager/tools/recommend_draft) | 2.9 | 4.6 |

The [public score page](https://glama.ai/mcp/servers/krmisystems/fantasy-football-manager/score) showed a complete aggregate of **4.4/5, tier A**, scored at 05:51:47 UTC.
Its record counted all 17 tools, with a mean tool score of 4.6 and a minimum of 4.1.
The public overview and score page agreed. All 17 public definitions still matched the reviewed export.

| Measure | Baseline | Complete new evaluation |
|---|---:|---:|
| Overall TDQS | 3.6 | 4.4 |
| Tool definition quality | 3.3 | 4.4 |
| Server coherence | 4.3 | 4.3 |
| Disambiguation | 4 | 4 |
| Naming consistency | 5 | 5 |
| Tool count appropriateness | 4 | 3 |
| Completeness | 4 | 5 |

An earlier partial evaluation displayed 4.6 overall with only 14 tools counted.
The complete 17-tool evaluation replaces that provisional result.
Tool count remained 17 to preserve existing tool names and workflows. Its lower external rating remains visible in this report.
The hosted sandbox's tool-call workflow remains **Not Tested**.
Glama's [score page](https://glama.ai/mcp/servers/krmisystems/fantasy-football-manager/score) recommends Try in Browser for its recent-usage check.
Usage is separate from the documented TDQS formula and does not prove independent adoption.

## Reproduce the metadata checks

Install the development environment:

```sh
uv sync --locked --dev
```

Export both public tool catalogs with isolated temporary state:

```sh
uv run --no-sync python scripts/export_tool_definitions.py --output-dir build/tool-definitions
```

Cache the pinned lint package:

```sh
uvx --from tdqs==0.1.0 tdqs --help
```

Run the offline lint checks:

```sh
uvx --offline --from tdqs==0.1.0 tdqs lint --file build/tool-definitions/manager-tools.json --format json --fail-on warning
uvx --offline --from tdqs==0.1.0 tdqs lint --file build/tool-definitions/espn-tools.json --format json --fail-on warning
```

The manager command returns exit 1 for the three documented candidates.
The ESPN command returns exit 0.

Check the manager error threshold:

```sh
uvx --offline --from tdqs==0.1.0 tdqs lint --file build/tool-definitions/manager-tools.json --format json --fail-on error
```

This command returns exit 0 while retaining the candidate warnings in its report.
These commands do not calculate a model-based score.

## Execution plan

| Priority | Work | Expected value | Effort |
|---|---|---|---|
| 1 | Repair the weakest definitions and describe all parameters | High: resolves observed gaps in tool selection and calls | Low to medium |
| 2 | Expose structured inputs and correct behavior annotations | High: helps clients form valid requests and identify effects | Medium |
| 3 | Publish tested definitions and verify Glama inspection | Required for external scoring of this change | Medium |
| 4 | Compare the new external score | Measures the result after inspection | Low local effort; external timing |

Expected value is an estimate. The lint and test results above are measured evidence.

1. Capture both existing `tools/list` responses using isolated local state.
2. Explain each tool's purpose, prerequisites, alternatives, effects, and result states.
3. Describe each parameter, including revision sources, timing units, simulation limits, and exact proposal confirmation.
4. Expose snapshot, configuration, and action payload structure without replacing existing runtime validation.
5. Align annotations with state replacement, evidence writes, browser access, and per-proposal replay protection.
6. Verify unchanged tool names, defaults, representative accepted calls, and policy failures through MCP.
7. Run the full base suite, isolated Chrome cases, release checks, and the existing seven CI jobs.
8. Publish a new version through the reviewed distribution process.
9. Verify that Glama captures the changed executable definitions before comparing scores.

## Implementation limits

Metadata must distinguish a single calculation, repeated local batches, cached results, and live ESPN automation.
Local simulation tools do not supply a browser observation feed or submit ESPN picks.
Browser lifecycle controls must distinguish process shutdown, shared pause, and an independent worker.

Schema descriptions must preserve valid existing JSON payloads and defaults.
The existing store and policy remain authoritative for runtime validation.
No new live action adapter, scoring strategy, or automatic season rollover is part of this change.
The running season deployment requires a separate verified upgrade before it uses a newly published package.

## Completion checks

| Check | Required evidence | Status |
|---|---|---|
| Tool interface | Same 17 manager names and 13 companion names, with compatible arguments and defaults | Verified in focused and base tests |
| Parameter semantics | Descriptions for every emitted top-level input parameter | Verified in export and offline lint |
| Structured inputs | Valid schemas and representative existing payloads accepted through MCP | Verified in focused and base tests |
| Effects and workflow | Tests cover revision conflicts, replay, evidence writes, and mocked browser delegation | Verified in focused and base tests |
| Shadow candidates | Manual review of the three schema-cost candidate pairs | Verified distinct operations; lint warnings retained |
| Version metadata | Matching 0.3.3 metadata and unchanged dependencies | Verified locally |
| Regression checks | Base, isolated Chrome, package, and all seven CI jobs pass | Verified |
| Distribution | New public artifacts and fresh installation match the reviewed source | GitHub, PyPI, and MCP Registry verified |
| Glama inspection | Public tool definitions match the changed descriptions and schemas | Verified for all 17 indexed manager tools |
| TDQS improvement | A new score applies to the changed definitions | Verified: all 17 tools scored A; complete aggregate increased from 3.6 to 4.4 |

The complete server score increase is verified for the definitions indexed on 2026-09-09.
A successful README sync does not establish a new executable inspection or score.
