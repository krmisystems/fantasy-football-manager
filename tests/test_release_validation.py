"""Test release version consistency and privacy checks with temporary fixtures."""

import ast
import importlib.util
import io
import json
from pathlib import Path
import re
import textwrap
import tomllib
import urllib.error
import urllib.request

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
fantasy-football-portfolio = "fantasy_football_manager.portfolio_mcp:main"
fantasy-football-dashboard = "fantasy_football_manager.dashboard:main"
''')
    write(tmp_path, "src/fantasy_football_manager/__init__.py", f'__version__ = "{VERSION}"\n')
    write(tmp_path, "uv.lock", lock_text())
    write(tmp_path, "README.md", f"mcp-name: io.github.krmisystems/{validator.NAME}\n")
    plugin = f"plugins/{validator.NAME}"
    write_json(tmp_path, f"{plugin}/.codex-plugin/plugin.json", {
        "name": validator.NAME, "version": VERSION, "mcpServers": "./.mcp.json"})
    write_json(tmp_path, f"{plugin}/.mcp.json", {"mcpServers": {
        name: {"command": name, "args": []} for name in (validator.NAME, validator.COMPANION, validator.PORTFOLIO)}})
    for skill in validator.SKILLS:
        write(tmp_path, f"{plugin}/skills/{skill}/SKILL.md", f"---\nname: {skill}\n---\nFictional release fixture.\n")
    write_json(tmp_path, "docs/registry/server.json", {
        "name": f"io.github.krmisystems/{validator.NAME}", "version": VERSION,
        "description": "Fictional release validation server.",
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


@pytest.mark.parametrize("suffix", ["service", "timer", "sh", "jsonl", "js", "jsx", "ts", "tsx", "css"])
@pytest.mark.parametrize("kind", ["path", "token"])
def test_deployment_and_event_files_receive_privacy_scanning(release_source, suffix, kind):
    private = "C:" + "/Users/" + "FictionalPerson/Documents/state" if kind == "path" else "ghp_" + "x" * 36
    relative = f"deployment/unsafe.{suffix}"
    write(release_source, relative, private)
    errors, _ = validator.validate(release_source)
    assert f"Possible private path or secret in: {relative}" in errors


@pytest.mark.parametrize("mutation, expected", [
    (lambda value: value.update(name="io.github.other/example"), "Registry namespace"),
    (lambda value: value["packages"][0].update(version="0.0.6"), "Registry package"),
    (lambda value: value["packages"][0].update(transport={"type": "streamable-http"}), "Registry package"),
    (lambda value: value.update(description="x" * 101), "Registry description"),
    (lambda value: value.update(description=" "), "Registry description"),
])
def test_registry_namespace_version_and_transport_checks_remain_active(release_source, mutation, expected):
    path = release_source / "docs/registry/server.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    mutation(value)
    write_json(release_source, "docs/registry/server.json", value)
    errors, _ = validator.validate(release_source)
    assert any(expected in error for error in errors)


def test_registry_dispatch_version_matches_current_package():
    workflow = (REPO / ".github/workflows/registry.yml").read_text(encoding="utf-8")
    version = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    inputs = workflow.split("permissions:", 1)[0]
    defaults = re.findall(r"^        default: (.+)$", inputs, re.MULTILINE)
    choices = re.findall(r"^        options: (.+)$", inputs, re.MULTILINE)
    assert len(defaults) == len(choices) == 1
    assert ast.literal_eval(defaults[0]) == version
    assert ast.literal_eval(choices[0]) == [version]


@pytest.fixture
def registry_preflight(tmp_path, monkeypatch):
    """Run the actual workflow preflight with fictional public metadata only."""
    workflow = (REPO / ".github/workflows/registry.yml").read_text(encoding="utf-8")
    marker = "          uv run --no-project --python 3.12 python - <<'PY'\n"
    assert workflow.count(marker) == 1
    source, terminator, _ = workflow.split(marker, 1)[1].partition("\n          PY\n")
    assert terminator
    code = compile(textwrap.dedent(source), "registry-workflow-preflight", "exec")
    for name in ("pyproject.toml", "docs/registry/server.json"):
        write(tmp_path, name, (REPO / name).read_text(encoding="utf-8"))
    version = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RELEASE_VERSION", version)
    pypi_url = f"https://pypi.org/pypi/fantasy-football-manager/{version}/json"
    registry_url = ("https://registry.modelcontextprotocol.io/v0.1/servers/"
                    "io.github.krmisystems%2Ffantasy-football-manager/versions/" + version)
    state = {
        "pypi_status": 200,
        "registry_status": 404,
        "requested": [],
        "published": {
            "info": {"name": validator.NAME, "version": version,
                     "description": f"mcp-name: io.github.krmisystems/{validator.NAME}"},
            "urls": [
                {"filename": f"fantasy_football_manager-{version}-py3-none-any.whl",
                 "packagetype": "bdist_wheel", "yanked": False, "digests": {"sha256": "0" * 64}},
                {"filename": f"fantasy_football_manager-{version}.tar.gz",
                 "packagetype": "sdist", "yanked": False, "digests": {"sha256": "1" * 64}},
            ],
        },
    }

    class FakeResponse(io.BytesIO):
        def geturl(self):
            return pypi_url

    class FakeOpener:
        def open(self, request, timeout):
            url = request.full_url
            assert url in (pypi_url, registry_url), "Unexpected preflight endpoint"
            state["requested"].append(url)
            status = state["pypi_status" if url == pypi_url else "registry_status"]
            if status != 200:
                raise urllib.error.HTTPError(url, status, "Fictional response", {}, None)
            return FakeResponse(json.dumps(state["published"]).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: FakeOpener())
    state["run"] = lambda: exec(code, {"__name__": "__main__"})
    state["metadata_path"] = tmp_path / "docs/registry/server.json"
    state["expected_requests"] = [pypi_url, registry_url]
    return state


def test_current_registry_preflight_accepts_reviewed_metadata(registry_preflight):
    registry_preflight["run"]()
    assert registry_preflight["requested"] == registry_preflight["expected_requests"]


def test_registry_preflight_rejects_unreviewed_metadata_before_network(registry_preflight):
    path = registry_preflight["metadata_path"]
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata["description"] = "Unreviewed description."
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(SystemExit, match="Registry metadata differs"):
        registry_preflight["run"]()
    assert registry_preflight["requested"] == []


@pytest.mark.parametrize("scenario, expected", [
    ("wrong_version", "exact package version"),
    ("missing_marker", "ownership marker"),
    ("yanked_wheel", "missing, yanked"),
    ("existing_registry_version", "Registry version already exists"),
])
def test_registry_preflight_preserves_publication_gates(registry_preflight, scenario, expected):
    published = registry_preflight["published"]
    if scenario == "wrong_version":
        published["info"]["version"] = "0.0.0"
    elif scenario == "missing_marker":
        published["info"]["description"] = "Fictional package without an ownership marker."
    elif scenario == "yanked_wheel":
        published["urls"][0]["yanked"] = True
    elif scenario == "existing_registry_version":
        registry_preflight["registry_status"] = 200
    with pytest.raises(SystemExit, match=expected):
        registry_preflight["run"]()
    expected_requests = registry_preflight["expected_requests"]
    assert registry_preflight["requested"] == (
        expected_requests if scenario == "existing_registry_version" else expected_requests[:1])


def test_registry_preflight_stops_when_public_package_is_absent(registry_preflight):
    registry_preflight["pypi_status"] = 404
    with pytest.raises(urllib.error.HTTPError) as error:
        registry_preflight["run"]()
    assert error.value.code == 404
    assert registry_preflight["requested"] == registry_preflight["expected_requests"][:1]
