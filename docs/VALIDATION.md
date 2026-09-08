# Validation status

Local checks below ran on 2026-09-07 with the 0.1.0 source.
These results describe the local release checks.
Public package publication requires separate publisher setup.

| Check | Status |
|---|---|
| Full Python unit and integration suite | 105 passed in 3.05 seconds with Python 3.12 on Windows |
| GitHub test matrix | Passed on Windows and Ubuntu with Python 3.11 and 3.14 in [the initial source run](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34182051866) |
| MCP integration tests | 8 passed with Python 3.12 on Windows |
| Synthetic CLI demo | Passed; existing imported SQLite file remained byte-for-byte unchanged |
| STDIO MCP initialization and tool calls | Passed through an actual subprocess; 17 tools listed and season tools called |
| MCP schema resources | Snapshot and config schemas read and checked through an in-memory client |
| Draft monitor over MCP | A bounded batch produced current results; explicit stop completed |
| Wheel and source distribution build | Passed; Twine 7 accepted both distributions |
| Isolated wheel installation | Installed with uv; installed CLI version and synthetic demo passed |
| Installed command through STDIO | 17 tools; lineup proposal, confirmation requirement, execution, and idempotent replay passed from a temporary working directory |
| Plugin manifest and skill structure | Local plugin-creator validator and both skill validators passed |
| Local installer | Preview passed; isolated checks verified that missing PyYAML causes no writes and updates preserve the marketplace entry |
| Personal plugin install | Source created and validated; CLI reported the plugin installed and enabled |
| Release source checks | Portable metadata and private-path/secret-pattern checks passed |
| Script and workflow syntax | 3 Python scripts parsed; 2 workflow YAML files parsed |
| MCP Registry template schema | Validated against its declared published JSON schema |
| Plugin ZIP | 5 allowlisted files including MIT license text; archive and per-file SHA-256 hashes verified |
| Installed Codex plugin in a new conversation | Not tested |
| Live provider writes | Unsupported |
| PyPI trusted publisher | Not configured by these source files |
| MCP Registry namespace | Authentication and ownership verification required |

Run `uv run pytest -q`, the synthetic demo, and `uv run python scripts/validate_release.py` before each later release.
The linked GitHub run is separate evidence for the tested source commit.

The MCP tests also checked proposal confirmation, idempotent execution, useful policy errors,
rejection of live writes, protection of imported state, and prevention of confirmed draft-history rollback.
The plugin uses the companion-file wrapper accepted by the installed validator.
An actual installed Codex connection still needs a new-conversation test.

A fictional 14-team draft batch completed 40 trials in 0.734 seconds on this Windows computer.
This single measurement is not a latency guarantee.
The monitor combines matching batches and reports discarded work separately.
