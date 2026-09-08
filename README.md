# Fantasy Football Manager

Local MCP tools for draft decisions, weekly team analysis, and ESPN draft and lineup automation.

<!-- mcp-name: io.github.krmisystems/fantasy-football-manager -->

Version **0.2.0** is a preview with two MCP servers: 17 manager tools and 13 ESPN companion tools.
The manager calculates recommendations and controls policy.
The ESPN companion observes league state and can submit real draft picks or weekly lineup swaps.

The packaged paths have offline tests and 13 passing isolated Chrome tests.
Those browser tests use local fixtures. **Live account acceptance of packaged draft picks and lineup swaps remains untested.**
Earlier direct browser picks were verified during a live draft. That separate evidence does not validate this package.

Season mode reads weekly rosters and can submit verified lineup swaps automatically.
Live waiver, free-agent, drop, and trade adapters remain planned. Complete season management is not yet implemented.

## Preview installation

The planned preview tag is `v0.2.0`. Publication of these assets is pending.
This version is not published on PyPI. After the GitHub preview is published, use its wheel:

```sh
uv tool install --force "https://github.com/krmisystems/fantasy-football-manager/releases/download/v0.2.0/fantasy_football_manager-0.2.0-py3-none-any.whl"
```

Planned assets: [preview release](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.2.0),
[plugin ZIP](https://github.com/krmisystems/fantasy-football-manager/releases/download/v0.2.0/fantasy-football-manager-0.2.0-plugin.zip),
and [SHA-256 manifest](https://github.com/krmisystems/fantasy-football-manager/releases/download/v0.2.0/fantasy-football-manager-0.2.0-plugin-manifest.json).
The plugin ZIP registers both commands. It does not install the Python package.

## Install from source

Use Python 3.11 or later, [uv](https://docs.astral.sh/uv/), and installed Google Chrome.
From this checkout, run:

```sh
uv sync --locked --dev
uv tool install --force .
fantasy-football-manager --help
fantasy-football-espn --help
```

The package includes Playwright and uses installed Chrome through a dedicated profile.
It does not copy cookies from an existing browser profile.

Register both commands with an MCP host, or use the [Codex plugin](docs/PLUGIN_INSTALL.md):

```sh
codex mcp add fantasy-football-manager -- fantasy-football-manager
codex mcp add fantasy-football-espn -- fantasy-football-espn
```

Both commands must be on the host's `PATH`. Restart the MCP connection after installation.
Use the same `FFM_DATA_DIR` or `--data-dir` for both servers when changing the default location.
The plugin already configures both servers. Avoid duplicate direct registrations when using it.

## Connect ESPN and run the draft

1. Call `get_capabilities` and `get_manager_config` on the manager.
2. Call `espn_connect` with the league ID, team ID, and season.
3. Sign in to ESPN in the browser window when required.
4. Call `espn_sync` to verify the complete draft history and visible clock.
5. Read `espn_get_status` and check the league, source age, and Autopick state.
6. Set the requested draft mode and limits with `update_manager_config`.
7. Call `espn_start_automation` for continued observation and simulation batches.

The default connection opens a dedicated local Chrome profile.
A supplied `cdp_url` connects through an explicit loopback debugging endpoint.
The package does not supply an ESPN account or bypass sign-in.
ESPN Autopick must be verified disabled before direct submission.

| Mode | ESPN draft behavior |
|---|---|
| Disabled or advisory | No submission. Advisory calculations remain available. |
| Review | Prepare a pick with `espn_prepare_draft_pick`. Confirm that exact proposal through `espn_submit_draft_pick`. |
| Automatic | The loop can submit its highest-ranked legal candidate within saved limits. It does not request per-pick confirmation. |

Use the custom preset with `draft_pick="automatic"` when only draft execution should be automatic.
A strategy preference does not grant permission. Read the full configuration before replacing it.
Each submission receives one durable click claim. A complete platform observation must confirm the actual pick.
If the result is uncertain, call `espn_reconcile_draft_pick`. The service does not retry the click automatically.
See the [ESPN workflow and tool list](docs/ESPN_AUTOMATION.md).

## Automate a weekly lineup

Connect with `espn_connect`, `phase="season"`, and an explicit scoring `week`.
Call `espn_sync` to check the team, weekly projections, and player locks.
Set the authorized `set_lineup` mode and improvement limit through `update_manager_config`.
Call `espn_start_automation` to observe and calculate continuously.

Automatic mode submits one qualifying swap at a time. Review mode requires confirmation of each exact proposal.
Each intermediate swap must meet the configured improvement limit. Some optimized targets cannot be reached under that limit.
An uncertain result blocks further moves until reconciliation. A confirmed swap does not mean the full target lineup was applied.
Reconnect for the next scoring week. Automatic week rollover remains planned.

## Continue after Codex closes

`espn_start_automation` runs inside the ESPN MCP process. Its lifetime depends on the MCP host.
Use `espn_start_standalone_worker` for an independent local worker after connecting and setting policy.
The worker uses the saved browser connection and can continue while the computer and browser remain available.
Draft mode stops when your roster is complete. Season mode monitors the explicit connected week until stopped.
The worker has no automatic reboot recovery or week rollover.

Call `espn_stop_automation` to set the shared pause flag and stop this process's loop.
The flag blocks new actions in other workers that use the same data directory.
It does not undo a submitted pick or lineup swap. Reconcile unresolved results before another action.

## Capabilities and limits

| Area | Implemented | Limit |
|---|---|---|
| Draft analysis | Snake order, roster completion, five strategies, continuous Monte Carlo batches, conditional availability | Two-pick horizon. No auctions or championship odds. |
| ESPN draft execution | Browser observation, proposals, one-click claims, platform reconciliation, automatic worker | Requires sign-in and compatible ESPN selectors. Packaged live end-to-end validation remains outstanding. |
| Season analysis | Weekly lineups, available-player comparisons, projected power rankings | Requires weekly projections, eligibility, ownership, and lock data. |
| Season execution | Weekly observations and one verified lineup swap at a time through ESPN MCP | Each swap must meet the improvement limit. Live waivers, acquisitions, drops, trades, and week rollover remain planned. |
| Policy and storage | Action modes, caps, protected players, spending limits, revisions, local SQLite records | One active league context per data directory. |

Scores and sampling errors are estimates. More trials do not repair stale data or incorrect projections.
See [policy](docs/POLICY.md), [architecture](docs/ARCHITECTURE.md), and [validation status](docs/VALIDATION.md).

## Synthetic demonstration

```sh
uv run fantasy-football-manager --demo
```

The CLI demo calculates an in-memory report. It does not replace saved league state.
The MCP `load_demo` tool stores synthetic state and refuses to overwrite an imported real league.
Use a separate data directory for demonstrations.
The manager's `prepare_action` and `execute_demo_action` tools change synthetic state only.
Use the ESPN companion for real ESPN draft submissions and lineup swaps.

## Privacy and packaging

ESPN requests use the connected browser session. The package does not bundle credentials.
Keep the dedicated profile, databases, logs, and real league exports out of Git.
See [privacy notes](docs/PRIVACY.md).

```sh
uv sync --locked --dev
uv run pytest -q
uv run python scripts/validate_release.py
uv build
uv run python -m twine check "dist/*.whl" "dist/*.tar.gz"
uv run python scripts/build_plugin_zip.py
```

The plugin contains three workflow skills and two portable MCP command registrations.
Publisher setup and registry submission are separate from local validation.
See [release instructions](docs/RELEASING.md).

License: [MIT](LICENSE). Copyright 2026 krmisystems.
