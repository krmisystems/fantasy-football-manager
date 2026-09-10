# Fantasy Football Manager for Codex

This plugin registers four skills and three local MCP servers for ESPN fantasy football.
It supports draft analysis, season proposals, and a portfolio of configured teams.
Saved automation modes and per-team limits control submissions.

This source package is the **unreleased v0.4.0 candidate**.
The published v0.3.3 Python package does not contain all of these tools.
Install the candidate commands from the source checkout:

```sh
uv tool install .
fantasy-football-manager --help
fantasy-football-espn --help
fantasy-football-portfolio --help
```

Run the installation command from the cloned repository root, not this plugin directory.
Make the three commands available on the Codex process's `PATH`.
Configure private team stores, the portfolio manifest, and authorized ESPN sessions separately.
The plugin contains registrations and instructions. It does not contain the Python runtime or credentials.

See the [installation guide](https://github.com/krmisystems/fantasy-football-manager/blob/main/docs/PLUGIN_INSTALL.md)
for source environments, optional browser dependencies, and HTTP session configuration.
Season HTTP operation needs no browser runtime. Live drafts retain a browser adapter.
Football is the only implemented sport. Trade execution is unavailable.

See [validation status](https://github.com/krmisystems/fantasy-football-manager/blob/main/docs/VALIDATION.md)
before relying on live operation. A scanner pass does not validate ESPN transactions.
See [security reporting](SECURITY.md) and the
[privacy guide](https://github.com/krmisystems/fantasy-football-manager/blob/main/docs/PRIVACY.md).
