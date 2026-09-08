# Install the local Codex plugin

The source plugin adds three workflow skills and two local MCP servers.
It uses the installed `fantasy-football-manager` and `fantasy-football-espn` commands.
The ESPN companion implements live draft observation and submission.
It requires an authenticated browser connection. Season mode supports lineup swaps. Live waivers, acquisitions, drops, and trades remain planned.

## Install the commands

For the planned `v0.2.0` GitHub preview assets, use the [preview installation instructions](../README.md#preview-installation).
Publication is pending. The preview is not published on PyPI.
The plugin archive contains registrations and skills. Install the Python wheel separately.

From the repository root, run:

```sh
uv tool install --force .
fantasy-football-manager --help
fantasy-football-espn --help
```

Check that the Codex process can find both commands on `PATH`.
Restart Codex if you changed its environment.
Install Google Chrome before using the managed ESPN profile.
The package includes Playwright but does not copy an existing browser's cookies.
Both servers must use the same data directory to share policy, observations, and pause state.

## Prepare a personal plugin

The installer uses the helper files from Codex's `plugin-creator` skill.
Set `PLUGIN_CREATOR_SKILL_ROOT` to the directory that contains that skill's `SKILL.md`.
This is an external Codex tool. It is not bundled with this project.

Preview the local paths and helper commands:

```sh
uv run --with pyyaml python scripts/install_local_plugin.py --skill-root "$PLUGIN_CREATOR_SKILL_ROOT"
```

In PowerShell, use `$env:PLUGIN_CREATOR_SKILL_ROOT` instead of `$PLUGIN_CREATOR_SKILL_ROOT`.
The preview does not write files.

To create the personal plugin and marketplace entry, run:

```sh
uv run --with pyyaml python scripts/install_local_plugin.py --skill-root "$PLUGIN_CREATOR_SKILL_ROOT" --apply
```

This command copies the plugin to `~/plugins/fantasy-football-manager`.
It uses the official helper to update `~/.agents/plugins/marketplace.json`.
It validates the copied plugin and prints the next Codex command.
It does not run that command or install the Python package.
The installer checks PyYAML and validates the source before it writes personal files.
For an existing plugin, add `--replace` when you intend to update its files.
An update verifies the existing local marketplace source, then updates the copied files and cachebuster.
It does not rewrite the marketplace entry.

Run the printed `codex plugin add` command.
Start a new Codex conversation.
Ask Codex to call `get_capabilities` and `espn_get_status`.
Use the synthetic workflow to check the manager without a real league.
Use `espn_connect` and sign in through its dedicated Chrome profile for ESPN.
See the [ESPN workflow](ESPN_AUTOMATION.md) before enabling automatic submissions.

The default personal marketplace is discovered implicitly.
No public marketplace entry is created by this process.
Use either this plugin or direct MCP registrations to avoid duplicate tool sets.

## Inspect the source

- [Plugin manifest](../plugins/fantasy-football-manager/.codex-plugin/plugin.json)
- [Both MCP commands](../plugins/fantasy-football-manager/.mcp.json)
- [Draft skill](../plugins/fantasy-football-manager/skills/draft-assistant/SKILL.md)
- [ESPN automation skill](../plugins/fantasy-football-manager/skills/espn-automation/SKILL.md)
- [Season skill](../plugins/fantasy-football-manager/skills/season-manager/SKILL.md)

The MCP file uses portable command names. It contains no user path, token, or account identifier.
It uses the `mcpServers` wrapper required by the locally installed plugin-creator validator.
Online documentation also shows other formats. Installed-client verification is a separate check.
See the [official plugin format](https://developers.openai.com/plugins/build/plugins) and [Codex MCP instructions](https://learn.chatgpt.com/docs/extend/mcp).
