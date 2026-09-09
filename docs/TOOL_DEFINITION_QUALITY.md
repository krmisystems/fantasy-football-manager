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
| Regression checks | Base, isolated Chrome, package, and all seven CI jobs pass | 647 base and 17 Chrome tests passed; package build, Twine, and privacy checks passed; CI pending |
| Distribution | New public artifacts and fresh installation match the reviewed source | Planned |
| Glama inspection | Public tool definitions match the changed descriptions and schemas | Planned |
| TDQS improvement | A new score applies to the changed definitions | Not Tested |

The exact score increase remains unverified until a new evaluation completes.
A successful README sync does not establish a new executable inspection or score.
