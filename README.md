# Fantasy Football Manager

Local MCP tools for fantasy football draft and weekly team decisions.

<!-- mcp-name: io.github.krmisystems/fantasy-football-manager -->

Version **0.1.0** supports validated JSON imports and synthetic demonstrations.
It separates strategy preferences, user limits, and action permissions.
The execution adapter changes synthetic state only. It cannot submit live ESPN or Sleeper roster actions.

The local release passed 105 tests and installed-command checks. See [validation status](docs/VALIDATION.md) for checked behavior and remaining checks.
PyPI publication, MCP Registry registration, and public plugin listing are not active merely because their configuration files exist.

## Run the synthetic demo

Use Python 3.11 or later and [uv](https://docs.astral.sh/uv/).
From this source checkout, run:

```sh
uv sync --locked --dev
uv run fantasy-football-manager --demo --data-dir .demo-state
```

The demo uses synthetic players, teams, projections, and league rules.
The CLI demo calculates a report in memory. It does not create or change saved state, even when `--data-dir` is supplied.

To run the MCP server from the checkout:

```sh
uv run fantasy-football-manager --transport stdio
```

This command waits for an MCP client. It is not an interactive terminal application.

## Install the local MCP command

Install from this checkout:

```sh
uv tool install .
fantasy-football-manager --help
```

The installed command must be on the MCP host's `PATH`.
Register it with Codex:

```sh
codex mcp add fantasy-football-manager -- fantasy-football-manager
```

This uses Codex's documented local STDIO connection. See [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp).
Restart the MCP connection after installation. Start a new conversation to test the tools.
Other MCP clients can use the command `fantasy-football-manager` with no arguments.

For the two workflow skills, use the [local plugin instructions](docs/PLUGIN_INSTALL.md).
The plugin and direct MCP connection are alternatives. Avoid enabling duplicate copies of the same server.

## Try the tools

Ask your MCP client to perform this sequence:

1. Call `get_capabilities`.
2. Call `load_demo` with `mode="draft"`.
3. Call `recommend_draft` with `trials=40` and `seed=1`.
4. Call `load_demo` with `mode="season"`.
5. Call `recommend_lineup`.
6. Call `rank_waiver_candidates`.
7. Call `get_manager_config` before preparing an action.

The MCP `load_demo` tool stores synthetic state. It refuses to replace an imported real snapshot.
It also refuses to erase confirmed picks when reloading the same draft.
Use a separate data directory to start a new demonstration.
Tool results identify their source, revision, missing inputs, and estimates.

## Version 0.1 scope

| Area | Available source behavior | Limit |
|---|---|---|
| Draft | Legal roster completion, configurable strategy, repeated Monte Carlo batches, availability estimates | Snake redraft workflow. No auction or live pick submission. |
| Season | Legal weekly lineup recommendations, available-player comparisons, projected power rankings | Requires weekly projections and authoritative eligibility and lock state. |
| Policy | Per-action modes, protected players, drop rules, spending limits, proposal checks | A strategy cannot grant permission or override a hard limit. |
| Execution | Local synthetic draft, lineup, acquisition, waiver, and drop actions | No live provider writes. Trades remain unsupported. |
| Storage | Local snapshots, profiles, revisions, and action records | One active league snapshot per data directory. |
| Distribution | Local STDIO server and Codex plugin source | Hosted HTTP service and marketplace listing remain separate work. |

Call `get_capabilities` for the effective supported behavior of the running version.
Selecting automatic mode does not add an unsupported adapter.

## Automation and strategy

Automation presets are **advisory**, **review**, **bounded automation**, and **custom**.
Custom profiles select a different mode for each action.
Action modes are **disabled**, **advisory**, **review**, and **automatic**.

Draft strategies include balanced value, RB priority, WR priority, hero RB, and zero RB.
Season strategies include projected points, floor, and upside.
Waiver strategies include immediate starters, bench upside, and conserving FAAB.
Floor and upside comparisons require corresponding projection inputs.

Protected players, authoritative league rules, source freshness, complete history, and current authorization remain execution checks.
An empty allowed-drop list permits no drops when `drop_mode="listed_only"`.
An acquisition with a required drop must satisfy both action policies.
Pending commitments count against spending and move limits.
The minimum lineup improvement also applies to acquisitions.
Execution requires a known, fresh projection timestamp for draft, lineup, and acquisition actions.

See [policy behavior](docs/POLICY.md) and [architecture](docs/ARCHITECTURE.md).
Scores and sampling error are estimates. They are not championship probabilities.

## Data and privacy

The default data directory is outside the source checkout.
Set `FFM_DATA_DIR`, or pass `--data-dir`, to choose a different location.
Keep imported league records, databases, credentials, and logs out of Git.
The source examples contain synthetic data only.

The server returns selected data to the connected MCP client.
That client's data handling also applies. See [privacy notes](docs/PRIVACY.md).
The package does not include provider credentials, a hosted service, or a live browser collector.

## Develop and package

```sh
uv sync --locked --dev
uv run pytest -q
uv run python scripts/validate_release.py
uv build
uv run python -m twine check "dist/*.whl" "dist/*.tar.gz"
uv run python scripts/build_plugin_zip.py
```

CI repeats source checks, tests, the synthetic CLI demo, and package validation.
Release jobs require separate publisher configuration and an approved GitHub environment.
See [release instructions](docs/RELEASING.md).

License: [MIT](LICENSE). Copyright 2026 krmisystems.
