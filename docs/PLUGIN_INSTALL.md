# Install the local Codex plugin

The source plugin adds three workflow skills and two local MCP servers.
It uses the installed `fantasy-football-manager` and `fantasy-football-espn` commands.
The ESPN companion implements live draft observation and submission.
It requires an authenticated browser connection. Season mode supports lineup swaps. Live waivers, acquisitions, drops, and trades remain planned.

## Install the commands

Use version 0.2.2 for public-draft compatibility and separate league state with a shared browser profile.
Read the [preview installation instructions](../README.md#preview-installation) for the wheel and plugin assets.
Check [validation status](VALIDATION.md) for installed-command and live acceptance evidence.
The preview is not published on PyPI or the MCP Registry.
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

## Select league state and a shared browser profile

Use a separate state directory for each league that you want to preserve.
Set the same `--data-dir` argument on both MCP commands for that league.
Set `FFM_BROWSER_DATA_DIR` on the ESPN command to reuse an existing managed browser profile.
The browser directory must be the parent of `espn-browser-profile`.

The following local MCP configuration uses placeholders. Replace each placeholder with an absolute path.
Keep these personal settings outside the public repository.

```json
{
  "mcpServers": {
    "fantasy-manager-league-two": {
      "command": "fantasy-football-manager",
      "args": ["--data-dir", "<league-two-state-directory>"]
    },
    "fantasy-espn-league-two": {
      "command": "fantasy-football-espn",
      "args": ["--data-dir", "<league-two-state-directory>"],
      "env": {
        "FFM_BROWSER_DATA_DIR": "<shared-browser-directory>"
      }
    }
  }
}
```

Use this pair once for the selected league. Keep the original pair pointed at its original state directory.
Do not register another pair that controls the same league state.
Restart the configured MCP processes after you change their arguments or environment.
The servers select these directories at process startup.

The new state directory retains its own roster, policy, action history, and pending claims.
The shared profile retains the existing browser sign-in. No cookie copy is required.
ESPN can still require a new sign-in when a session expires.
The profile lease permits one controller at a time, including controllers for different leagues.
Disconnect the current browser controller before connecting the other league.

Workers started through the ESPN tool receive the same browser setting.
For a manual worker restart, set `FFM_BROWSER_DATA_DIR` in that process's environment again.
`FFM_BROWSER_DATA_DIR` is available from version 0.2.2. Install that version or later before using this configuration.
See the [connection and handoff steps](ESPN_AUTOMATION.md#separate-league-state-from-the-browser-profile).

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
