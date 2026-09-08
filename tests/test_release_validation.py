"""Test release version consistency and privacy checks with temporary fixtures."""

import importlib.util
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_validator", REPO / "scripts" / "validate_release.py")
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)
VERSION = "0.0.7"


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def write_json(root, name, value):
    write(root, name, json.dumps(value, indent=2))


@pytest.fixture
def release_source(tmp_path):
    write(tmp_path, "pyproject.toml", f'''[project]
name = "{validator.NAME}"
version = "{VERSION}"
[project.scripts]
fantasy-football-manager = "fantasy_football_manager.mcp_server:main"
fantasy-football-espn = "fantasy_football_manager.espn_mcp:main"
''')
    write(tmp_path, "src/fantasy_football_manager/__init__.py", f'__version__ = "{VERSION}"\n')
    write(tmp_path, "uv.lock", lock_text())
    write(tmp_path, "README.md", f"mcp-name: io.github.krmisystems/{validator.NAME}\n")
    plugin = f"plugins/{validator.NAME}"
    write_json(tmp_path, f"{plugin}/.codex-plugin/plugin.json", {
        "name": validator.NAME, "version": VERSION, "mcpServers": "./.mcp.json"})
    write_json(tmp_path, f"{plugin}/.mcp.json", {"mcpServers": {
        name: {"command": name, "args": []} for name in (validator.NAME, validator.COMPANION)}})
    for skill in validator.SKILLS:
        write(tmp_path, f"{plugin}/skills/{skill}/SKILL.md", f"---\nname: {skill}\n---\nFictional release fixture.\n")
    write_json(tmp_path, "docs/registry/server.json", {
        "name": f"io.github.krmisystems/{validator.NAME}", "version": VERSION,
        "packages": [{"registryType": "pypi", "identifier": validator.NAME,
                      "version": VERSION, "transport": {"type": "stdio"}}]})
    return tmp_path


def lock_text(version=VERSION, source='editable = "."'):
    return f'version = 1\n[[package]]\nname = "{validator.NAME}"\nversion = "{version}"\nsource = {{ {source} }}\n'


def test_matching_release_metadata_and_safe_html_pass(release_source):
    write(release_source, "tests/fixtures/room.html", '<p>Fictional team 123. No account credentials.</p>')
    errors, checked = validator.validate(release_source, VERSION)
    assert errors == [] and checked >= 10


@pytest.mark.parametrize("runtime", [
    '__version__ = "0.0.6"\n',
    '__version__ = "0.0.7"\n__version__ = "0.0.8"\n',
    '__version__ = get_version()\n',
    '__version__ = [\n',
])
def test_runtime_version_mismatch_or_ambiguous_assignment_is_rejected(release_source, runtime):
    write(release_source, "src/fantasy_football_manager/__init__.py", runtime)
    errors, _ = validator.validate(release_source)
    assert any("Runtime __version__" in error for error in errors)


def test_missing_runtime_version_file_is_rejected(release_source):
    (release_source / "src/fantasy_football_manager/__init__.py").unlink()
    errors, _ = validator.validate(release_source)
    assert any("Runtime __version__" in error for error in errors)


@pytest.mark.parametrize("contents", [
    lock_text("0.0.6"),
    'version = 1\n',
    lock_text(source='registry = "https://example.invalid/simple"'),
    lock_text() + lock_text().replace('version = 1\n', '', 1),
])
def test_lock_must_identify_one_matching_local_package(release_source, contents):
    write(release_source, "uv.lock", contents)
    errors, _ = validator.validate(release_source)
    assert any("uv.lock" in error for error in errors)


@pytest.mark.parametrize("kind", ["path", "token"])
def test_html_private_path_or_token_is_rejected(release_source, kind):
    # Build test strings at runtime so the test source is safe to publish.
    private = "C:" + "/Users/" + "FictionalPerson/Documents/state" if kind == "path" else "ghp_" + "x" * 36
    write(release_source, "tests/fixtures/unsafe.HTML", f"<pre>{private}</pre>")
    errors, _ = validator.validate(release_source)
    assert "Possible private path or secret in: tests/fixtures/unsafe.HTML" in errors


@pytest.mark.parametrize("mutation, expected", [
    (lambda value: value.update(name="io.github.other/example"), "Registry namespace"),
    (lambda value: value["packages"][0].update(version="0.0.6"), "Registry package"),
    (lambda value: value["packages"][0].update(transport={"type": "streamable-http"}), "Registry package"),
])
def test_registry_namespace_version_and_transport_checks_remain_active(release_source, mutation, expected):
    path = release_source / "docs/registry/server.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    write_json(release_source, "docs/registry/server.json", value)
    errors, _ = validator.validate(release_source)
    assert any(expected in error for error in errors)
