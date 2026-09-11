# Install the local Codex plugin

The source plugin adds four workflow skills and three local MCP servers.
It uses `fantasy-football-manager`, `fantasy-football-espn`, and `fantasy-football-portfolio`.
The portfolio adds five read-only tools across explicitly configured team stores.
Configure `FFM_PORTFOLIO_MANIFEST` for that command. See the [portfolio guide](PORTFOLIO.md).
The v0.4.0 preview exposes 16 ESPN tools, including HTTP season transactions without a browser runtime.
Draft operation retains the browser adapter. Trade execution remains unavailable.
The published v0.3.3 package has the original 13 ESPN tools and browser lineup workflow.
Do not assume that installing the published package supplies the new HTTP tools.

## Install the commands

Version 0.3.0 adds server season scheduling and an evidence archive to the draft and lineup tools.
Version 0.3.1 fixes draft team-name whitespace and D/ST selectors.
Version 0.3.2 retains verified opponent picks when ESPN has no season projection.
Those players count toward roster limits. They receive no estimated points and cannot become draft recommendations.
Read the [installation instructions](../README.md#install-from-pypi) for the published package and plugin assets.
Check [validation status](VALIDATION.md) for installed-command and live acceptance evidence.
Check [distribution acceptance](DISCOVERY_ACCEPTANCE.md) for verified package, registry, and plugin availability.
The plugin archive contains registrations and skills. Install the Python wheel separately.

Install the published commands:

```sh
uv tool install fantasy-football-manager==0.4.0
fantasy-football-manager --help
fantasy-football-espn --help
```

For a development build, use the [source installation](../README.md#install-from-source).
Run these commands from the repository root to install both optional workflows:

```sh
uv sync --extra browser --extra session-import
uv run fantasy-football-espn --help
```

The base HTTP runtime requires neither Chrome nor Playwright.
The `browser` extra supplies Playwright for draft and legacy season operation. Those workflows also require installed Google Chrome.
The `session-import` extra supplies cryptography for the optional Linux session importer.
An already provisioned HTTP session file does not require that extra.
Use the v0.4.0 commands or configure a source checkout environment.

Check that the Codex process can find the configured commands on `PATH`.
Restart Codex if you changed its environment.
The manager and ESPN servers must share a per-team data directory.
The portfolio reads all directories listed in its private manifest.

## Configure an HTTP season session (v0.4.0)

Use an existing authorized ESPN session. The HTTP adapter does not provide password sign-in or renew expired sessions.
Store only `SWID` and `espn_s2` in a protected local JSON file.
Do not put their values in a prompt, tool argument, command line, log, or repository file.
Set `FFM_ESPN_CREDENTIAL_FILE` to that file, or pass its path through `--credential-file`.
On Linux, the file must belong to the service account and exclude group and other access.
The importer writes mode `0600`. Restrict file access separately on other operating systems.

The optional importer reads only ESPN session cookies from a Linux Chromium cookie database.
It opens the database read-only and does not start a browser.
It supports the inspected Linux `v10` cookie format and rejects unsupported encryption or expired cookies.
It does not import passwords, other sites, or a complete browser profile.
Use it only for a profile whose account session you are authorized to access.

Set the following shell variables to private local paths before this command.
Keep their values outside public examples.

```sh
uv run --extra session-import fantasy-football-espn \
  --import-linux-session "$PRIVATE_ESPN_COOKIE_DATABASE" \
  --credential-file "$PRIVATE_ESPN_SESSION_FILE"
```

This command replaces the destination only after a successful import and validation.
It reports credential names and status without printing their values.
An import does not verify that ESPN still accepts the session. Connection performs authenticated ownership checks.
See [authentication tests](../tests/test_espn_http_auth.py) and the [HTTP source contract](ESPN_HTTP_COMPATIBILITY.md).

The following MCP configuration uses placeholders. Replace them in a private local configuration.
The `command` paths select the installed or source-environment executables.

```json
{
  "mcpServers": {
    "fantasy-manager-season": {
      "command": "<manager-command>",
      "args": ["--data-dir", "<league-state-directory>"]
    },
    "fantasy-espn-season": {
      "command": "<espn-command>",
      "args": ["--data-dir", "<league-state-directory>", "--transport", "http"],
      "env": {
        "FFM_ESPN_CREDENTIAL_FILE": "<protected-session-file>"
      }
    }
  }
}
```

1. Restart the configured MCP processes.
2. Read `get_capabilities`, `get_manager_config`, and `espn_get_status`.
3. Connect the selected context with `phase="season"`, `transport="http"`, and the requested `week`.
4. Call `espn_sync`.
5. Verify the current period, source freshness, ownership, locks, and pending claims.
6. Preserve the user's action modes and limits before starting automation.

Use a separate state directory for each managed league and team context.
Use one protected credential directory for controllers that share an account.
A team lease blocks simultaneous HTTP controllers for the same league and team, even across separate state directories.
Different teams have separate leases. Copies of credentials in unrelated directories do not share this protection.
Set `auto_rollover=true` only when authorized operation should follow ESPN's verified current period.
Unresolved submissions and pending waivers retain their original week.

## Select league state and a shared browser profile

This section applies to browser drafts and the legacy browser season adapter.
Install the source `browser` extra and Google Chrome for these workflows.

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
      "args": ["--data-dir", "<league-two-state-directory>", "--transport", "browser"],
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

Clone the repository to use its plugin installer.
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
Use the HTTP session setup above for season operation with v0.4.0.
For a browser draft, use `espn_connect` in draft phase and complete sign-in in the dedicated profile.
See the [ESPN workflow](ESPN_AUTOMATION.md) before enabling automatic submissions.

The default personal marketplace is discovered implicitly.
No public marketplace entry is created by this process.
Use either this plugin or direct MCP registrations to avoid duplicate tool sets.

## Inspect the source

- [Plugin manifest](../plugins/fantasy-football-manager/.codex-plugin/plugin.json)
- [Three MCP commands](../plugins/fantasy-football-manager/.mcp.json)
- [Draft skill](../plugins/fantasy-football-manager/skills/draft-assistant/SKILL.md)
- [ESPN automation skill](../plugins/fantasy-football-manager/skills/espn-automation/SKILL.md)
- [Season skill](../plugins/fantasy-football-manager/skills/season-manager/SKILL.md)

The MCP file uses portable command names. It contains no user path, token, or account identifier.
It uses the `mcpServers` wrapper required by the locally installed plugin-creator validator.
Online documentation also shows other formats. Installed-client verification is a separate check.
See the [official plugin format](https://developers.openai.com/plugins/build/plugins) and [Codex MCP instructions](https://learn.chatgpt.com/docs/extend/mcp).
