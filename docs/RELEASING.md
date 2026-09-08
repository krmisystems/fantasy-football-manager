# Release the package

These files prepare version 0.2.0 for review.
The planned GitHub tag is `v0.2.0`, with the release marked as a prerelease.
GitHub preview publication is pending. Version 0.2.0 is not published on PyPI.
They do not prove that a repository, package, registry entry, or trusted publisher exists.
Check [validation status](VALIDATION.md) before each release.

## Build the artifacts

From a clean source checkout, run:

```sh
uv sync --locked --dev
uv run pytest -q
uv run fantasy-football-manager --demo --data-dir .ci-demo
uv run fantasy-football-espn --help
uv run python scripts/validate_release.py
uv build
uv run python -m twine check "dist/*.whl" "dist/*.tar.gz"
uv run python scripts/build_plugin_zip.py
```

Twine checks the selected Python distributions only.
The ZIP builder writes a plugin archive and a SHA-256 manifest to `dist/`.
The archive includes three skills and registrations for both installed MCP commands.
It copies an explicit list of plugin files. It does not include league records or local state.

Inspect the wheel, source distribution, and plugin manifest before publication.
Do not add imports, credentials, browser profiles, databases, logs, or private captures to the release.
The local validation script checks known file types and secret patterns. It does not replace artifact review.

## Configure GitHub and PyPI

The intended repository is `krmisystems/fantasy-football-manager`.
The intended PyPI project is `fantasy-football-manager`.
Package-name availability and publisher ownership must be confirmed by the publisher account.

1. Create the PyPI project or a pending trusted publisher.
2. Set its GitHub repository to `krmisystems/fantasy-football-manager`.
3. Set its workflow filename to `release.yml`.
4. Set its environment name to `pypi`.
5. Create the `pypi` environment in GitHub.
6. Require a reviewer for that environment.
7. Confirm that the current GitHub plan enforces the environment review.
8. Set the repository variable `PYPI_PUBLISH_ENABLED` to `true` when publishing is authorized.

The release workflow runs only on manual dispatch.
It builds and tests the exact checkout before the publish job requests environment approval.
The publish job uses an OIDC identity token. It does not require a stored PyPI API token.
The workflow file cannot configure environment reviewers or create the PyPI trust relationship.
Follow the [PyPI trusted-publisher setup](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

Dispatch `.github/workflows/release.yml` from the reviewed release commit.
Enter the same version as `pyproject.toml`.
Review the built artifacts before you approve the `pypi` environment.
The workflow does not create a GitHub release or publish a Codex marketplace entry.

## Register MCP metadata

The [registry template](registry/server.json) names:

- Server: `io.github.krmisystems/fantasy-football-manager`
- PyPI package: `fantasy-football-manager`
- Transport: `stdio`

The registry package describes the main `fantasy-football-manager` entry point.
The same Python distribution includes the `fantasy-football-espn` companion command.
The plugin registers both commands. A direct MCP installation must register each required server.

Publish the Python package before submitting registry metadata.
Authenticate as the namespace owner through the registry's documented process.
Copy the template to the publisher's working directory as `server.json`.
Validate it with the current registry publisher before submission.
The README contains the matching `mcp-name` marker needed for PyPI package ownership checks.

Namespace ownership is not established by this file.
The registry contains discovery metadata; it does not host this server or its user data.
See [MCP Registry package types](https://modelcontextprotocol.io/registry/package-types) and [registry publication instructions](https://modelcontextprotocol.io/registry/quickstart).

## Evidence for live operation

Run the complete offline suite before release. Record its actual count and platform in the release notes.
Keep packaged live acceptance marked untested until authenticated draft and lineup actions confirm their respective full paths.
Isolated Chrome fixture tests verify browser mechanics without changing a real league.
Earlier direct browser picks do not establish packaged selector compatibility.
Distinguish implemented lineup automation from live acceptance testing.
Live waivers, acquisitions, drops, trades, and automatic week rollover remain planned.
