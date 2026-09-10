"""Verify public distribution checks with fictional responses and no network calls."""

import base64
from copy import deepcopy
from http.client import BadStatusLine, IncompleteRead
import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("distribution_status", ROOT / "scripts/check_distribution_status.py")
distribution = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(distribution)
HEAD = "a" * 40
OLD_HEAD = "b" * 40
VERSION = "0.0.7"
FICTIONAL_AUTH_VALUE = "fictional-private-token"
AT = "2026-08-20T08:00:00Z"


@pytest.fixture(autouse=True)
def no_external_processes_or_network(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("This test must not use the network or an external process.")
    monkeypatch.setattr(distribution, "build_opener", forbidden)
    monkeypatch.setattr(distribution.subprocess, "run", forbidden)


def hydration_nodes(nodes):
    return "<script>window.__reactRouterContext.streamController.enqueue(" + json.dumps(json.dumps(nodes)) + ")</script>"


def hydration(value):
    nodes = []
    def encode(item):
        index = len(nodes)
        nodes.append(None)
        if isinstance(item, dict):
            encoded = {"_" + str(encode(key)): encode(value) for key, value in item.items()}
        elif isinstance(item, list):
            encoded = [encode(value) for value in item]
        else:
            encoded = item
        nodes[index] = encoded
        return index
    assert encode(value) == 0
    return hydration_nodes(nodes)


def route_page(suffix, value):
    return hydration({"loaderData": {distribution.ROUTE + suffix: value}})


def encoded_content(text):
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


def manager_source():
    return "\n".join(f'@server.tool()\ndef manager_tool_{i}():\n    """Read fictional manager data {i}."""\n    return {{}}\n'
                     for i in range(17))


def ci_run(*, head=HEAD, run_id=10, status="completed", conclusion="success", branch="main", event="push"):
    return {"id": run_id, "head_sha": head, "head_branch": branch, "event": event,
            "status": status, "conclusion": conclusion, "html_url": "https://github.com/fictional/project/actions/runs/10"}


class PublicReader:
    def __init__(self):
        self.calls = []
        self.failures = {}
        self.responses = {
            "main": {"sha": HEAD},
            "source": encoded_content('[project]\nname="fantasy-football-manager"\nversion="' + VERSION + '"\n'),
            "tools": encoded_content(manager_source()),
            "ci": {"workflow_runs": [ci_run()]},
            "releases": [{"draft": False, "prerelease": False, "tag_name": "v" + VERSION, "published_at": AT,
                          "html_url": "https://github.com/fictional/project/releases/tag/v" + VERSION}],
            "pypi": {"info": {"name": "fantasy-football-manager", "version": VERSION}},
            "tree": route_page("_explorer/tree/_index/_route", {"member": {"commit": {"sha": HEAD}}}),
            "schema": route_page("schema/_route", {"schema": {"tools": [
                {"name": f"manager_tool_{i}", "description": f"Read fictional manager data {i}."} for i in range(17)]}}),
            "overview": route_page("_index/_route", {"mcpServer": {"updatedAt": AT,
                "repository": {"latestRelease": {"version": "0.1.2"}}, "latestRelease": {"version": "0.1.2"}}}),
        }

    def __call__(self, url, *, token=None):
        self.calls.append(url)
        path = urlsplit(url).path
        if path.endswith("/commits/main"):
            key = "main"
        elif path.endswith("/contents/pyproject.toml"):
            key = "source"
        elif path.endswith("/contents/src/fantasy_football_manager/mcp_server.py"):
            key = "tools"
        elif path.endswith("/actions/workflows/ci.yml/runs"):
            key = "ci"
        elif path.endswith("/releases"):
            key = "releases"
        elif url.startswith("https://pypi.org/"):
            key = "pypi"
        elif url == distribution.GLAMA + "/tree":
            key = "tree"
        elif url == distribution.GLAMA + "/schema":
            key = "schema"
        elif url == distribution.GLAMA:
            key = "overview"
        else:
            raise AssertionError("Unexpected public endpoint.")
        if key in self.failures:
            raise self.failures[key]
        value = self.responses[key]
        return value if isinstance(value, str) else json.dumps(value)


@pytest.fixture
def public_reader(monkeypatch):
    def git_value(*args):
        if args == ("rev-parse", "HEAD"):
            return HEAD
        if args == ("status", "--porcelain"):
            return ""
        raise AssertionError("Unexpected git query.")
    monkeypatch.setattr(distribution, "git_value", git_value)
    return PublicReader()


def test_hydration_decodes_data_without_executing_page_scripts():
    value = {"loaderData": {"fictional": {"text": "<script>raise Exception('never run')</script>",
             "tools": ["one", "two"], "count": 2, "enabled": True, "missing": None}}}
    html = hydration(value)
    assert distribution.decode_hydration(html) == value
    assert distribution.decode_hydration(hydration_nodes([{ "_1": -5 }, "missing"])) == {"missing": None}


@pytest.mark.parametrize("nodes", [[], {}, [{"bad-key": 1}, "value"], [[0]], [[True]], [[999]],
                                   [{"_1": 2, "_3": 2}, "same", "value", "same"],
                                   [{"_1": 2}, 7, "value"], [[-1]]])
def test_invalid_hydration_references_and_cycles_are_rejected(nodes):
    with pytest.raises(distribution.CheckError):
        distribution.decode_hydration(hydration_nodes(nodes))


def test_hydration_depth_and_chunk_count_are_bounded():
    nodes = [[i + 1] for i in range(102)] + ["leaf"]
    with pytest.raises(distribution.CheckError):
        distribution.decode_hydration(hydration_nodes(nodes))
    page = hydration({"ok": True})
    with pytest.raises(distribution.CheckError):
        distribution.decode_hydration(page + page)
    with pytest.raises(distribution.CheckError):
        distribution.decode_hydration("<html>No compatible hydration.</html>")


def test_matching_public_sources_do_not_attest_a_hosted_build(public_reader):
    report = distribution.collect(reader=public_reader)
    checks = report["checks"]
    assert checks["github_main"]["commit"] == HEAD
    assert checks["github_ci"]["status"] == "current"
    assert checks["glama_index"]["status"] == "current"
    assert checks["glama_tools"]["expected_count"] == 17
    assert checks["glama_tools"]["public_count"] == 17
    assert checks["glama_build"]["status"] == "unknown"
    assert report["status"] == "attention"
    assert report["attention"] == ["glama_build"]
    assert checks["glama_listing"]["status"] == "observed"
    assert checks["glama_listing"]["image_release"] == "0.1.2"
    assert report["read_only"] is True and report["remote_writes"] == 0 and report["model_calls"] == 0
    for url in public_reader.calls:
        if "/contents/" in url:
            assert parse_qs(urlsplit(url).query)["ref"] == [HEAD]
    ci_url = next(url for url in public_reader.calls if "/actions/workflows/" in url)
    assert parse_qs(urlsplit(ci_url).query)["head_sha"] == [HEAD]


@pytest.mark.parametrize("endpoint,check", [("ci", "github_ci"), ("releases", "github_release"),
    ("pypi", "pypi_release"), ("tree", "glama_index"), ("schema", "glama_tools"),
    ("overview", "glama_listing"), ("tools", "glama_tools"), ("source", "source_package")])
def test_upstream_failures_stay_unknown_and_preserve_independent_checks(public_reader, endpoint, check):
    public_reader.failures[endpoint] = distribution.CheckError(FICTIONAL_AUTH_VALUE)
    report = distribution.collect(reader=public_reader, token=FICTIONAL_AUTH_VALUE)
    assert report["checks"][check]["status"] == "unknown"
    assert report["checks"]["github_main"]["status"] == "current"
    if endpoint != "tree":
        assert report["checks"]["glama_index"]["status"] == "current"
    if endpoint == "source":
        assert report["checks"]["github_release"]["status"] == "unknown"
        assert report["checks"]["pypi_release"]["status"] == "unknown"
    assert FICTIONAL_AUTH_VALUE not in json.dumps(report) + distribution.markdown(report)
    assert report["status"] == "attention"


def test_glama_index_compares_exact_remote_main_not_local_head(public_reader, monkeypatch):
    monkeypatch.setattr(distribution, "git_value", lambda *args: OLD_HEAD if args[0] == "rev-parse" else "")
    public_reader.responses["tree"] = route_page("_explorer/tree/_index/_route", {"member": {"commit": {"sha": OLD_HEAD}}})
    report = distribution.collect(reader=public_reader)
    assert report["checks"]["local_checkout"]["status"] == "pending"
    assert report["checks"]["glama_index"]["status"] == "stale"
    assert report["checks"]["glama_index"]["expected_commit"] == HEAD
    assert report["checks"]["glama_index"]["indexed_commit"] == OLD_HEAD


def test_changed_or_duplicate_public_metadata_does_not_report_current(public_reader):
    tools = [{"name": f"manager_tool_{i}", "description": f"Read fictional manager data {i}."} for i in range(17)]
    tools[0]["description"] = "Old documentation."
    tools.append({"name": "list_managed_teams", "description": "Portfolio data belongs to a separate server."})
    public_reader.responses["schema"] = route_page("schema/_route", {"schema": {"tools": tools}})
    report = distribution.collect(reader=public_reader)
    result = report["checks"]["glama_tools"]
    assert result["status"] == "stale" and result["expected_count"] == 17
    assert result["changed_descriptions"] == ["manager_tool_0"]
    assert result["unexpected"] == ["list_managed_teams"]
    assert "portfolio tools are not compared" in result["scope"]
    tools.append(deepcopy(tools[0]))
    public_reader.responses["schema"] = route_page("schema/_route", {"schema": {"tools": tools}})
    assert distribution.collect(reader=public_reader)["checks"]["glama_tools"]["status"] == "unknown"


@pytest.mark.parametrize("runs,expected", [
    ([], "pending"),
    ([ci_run(head=OLD_HEAD)], "pending"),
    ([ci_run(branch="feature")], "pending"),
    ([ci_run(event="pull_request")], "pending"),
    ([ci_run(status="in_progress", conclusion=None)], "pending"),
    ([ci_run(conclusion="failure")], "failed"),
    ([ci_run(conclusion="cancelled")], "failed"),
    ([ci_run(event="workflow_dispatch")], "current"),
    ([ci_run(), ci_run(run_id=11, status="queued", conclusion=None)], "pending"),
    ([ci_run(run_id=12, conclusion="failure"), ci_run(run_id=11)], "failed"),
    ([ci_run(), ci_run(head=OLD_HEAD, run_id=99, conclusion="failure")], "current"),
])
def test_ci_uses_latest_matching_main_run_and_preserves_failure_states(runs, expected):
    assert distribution.ci_status({"workflow_runs": runs}, HEAD)["status"] == expected


@pytest.mark.parametrize("response", [None, [], {"unexpected": []}, {"workflow_runs": None}, {"workflow_runs": ["invalid"]}])
def test_malformed_ci_data_is_unknown_in_public_report(public_reader, response):
    public_reader.responses["ci"] = response
    assert distribution.collect(reader=public_reader)["checks"]["github_ci"]["status"] == "unknown"


@pytest.mark.parametrize("version", ["123", "true", '""'])
def test_invalid_source_version_is_unknown(public_reader, version):
    public_reader.responses["source"] = encoded_content("[project]\nversion=" + version + "\n")
    checks = distribution.collect(reader=public_reader)["checks"]
    assert checks["source_package"]["status"] == "unknown"
    assert checks["github_release"]["status"] == "unknown"
    assert checks["pypi_release"]["status"] == "unknown"


def test_wrong_public_shapes_cannot_turn_green(public_reader):
    public_reader.responses["tree"] = hydration(["not a route mapping"])
    public_reader.responses["schema"] = route_page("schema/_route", {"schema": {"tools": {"unexpected": "mapping"}}})
    public_reader.responses["overview"] = hydration(None)
    public_reader.responses["pypi"] = {"info": {"name": "some-other-package", "version": VERSION}}
    public_reader.responses["releases"] = {"unexpected": "mapping"}
    checks = distribution.collect(reader=public_reader)["checks"]
    for check in ("glama_index", "glama_tools", "glama_listing", "pypi_release", "github_release"):
        assert checks[check]["status"] == "unknown"


def test_source_tool_inspection_never_imports_or_executes_source():
    source = 'raise RuntimeError("Do not execute source")\n' + manager_source()
    tools = distribution.source_tools(source)
    assert len(tools) == 17
    assert tools["manager_tool_0"] == "Read fictional manager data 0."


class Response:
    def __init__(self, body=b"{}", error=None):
        self.body, self.error = body, error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        if self.error is not None:
            raise self.error
        return self.body[:size]


def fake_opener(monkeypatch, response=None, error=None):
    captured = []
    class Opener:
        def open(self, request, *, timeout):
            captured.append(request)
            if error is not None:
                raise error
            return response or Response()
    def factory(handler):
        assert isinstance(handler, distribution.NoRedirect)
        return Opener()
    monkeypatch.setattr(distribution, "build_opener", factory)
    return captured


def test_token_is_sent_only_to_the_fixed_github_host(monkeypatch):
    requests = fake_opener(monkeypatch)
    for url in (distribution.GITHUB + "/commits/main", distribution.GLAMA, "https://pypi.org/pypi/fantasy-football-manager/json"):
        assert distribution.fetch(url, token=FICTIONAL_AUTH_VALUE) == "{}"
    assert requests[0].get_header("Authorization") == "Bearer " + FICTIONAL_AUTH_VALUE
    assert all(request.get_header("Authorization") is None for request in requests[1:])


@pytest.mark.parametrize("url", ["http://api.github.com/repos/x", "https://evil.example/", "https://api.github.com.evil.example/",
                                 "https://api.github.com@evil.example/", "https://user:password@api.github.com/",
                                 "https://api.github.com:444/", "file:///private/secret", "https://glama.ai@evil.example/"])
def test_untrusted_endpoints_are_rejected_before_a_request(url):
    with pytest.raises(distribution.CheckError, match="unexpected_endpoint"):
        distribution.fetch(url, token=FICTIONAL_AUTH_VALUE)


def test_redirect_cannot_forward_a_github_token():
    request = Request(distribution.GITHUB, headers={"Authorization": "Bearer " + FICTIONAL_AUTH_VALUE})
    with pytest.raises(distribution.CheckError, match="redirect_refused"):
        distribution.NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://evil.example/")


@pytest.mark.parametrize("failure", [URLError(FICTIONAL_AUTH_VALUE), TimeoutError(FICTIONAL_AUTH_VALUE), OSError(FICTIONAL_AUTH_VALUE),
                                     HTTPError("https://api.github.com/", 403, FICTIONAL_AUTH_VALUE, {}, None)])
def test_transport_errors_do_not_expose_tokens(monkeypatch, failure):
    fake_opener(monkeypatch, error=failure)
    with pytest.raises(distribution.CheckError) as error:
        distribution.fetch(distribution.GITHUB, token=FICTIONAL_AUTH_VALUE)
    assert FICTIONAL_AUTH_VALUE not in str(error.value)


@pytest.mark.parametrize("failure", [IncompleteRead(b"private-response", 30), BadStatusLine(FICTIONAL_AUTH_VALUE)])
def test_broken_http_stream_is_a_safe_unknown_failure(monkeypatch, failure):
    fake_opener(monkeypatch, response=Response(error=failure))
    with pytest.raises(distribution.CheckError) as error:
        distribution.fetch(distribution.GITHUB, token=FICTIONAL_AUTH_VALUE)
    assert FICTIONAL_AUTH_VALUE not in str(error.value) and "private-response" not in str(error.value)


def test_oversized_and_invalid_utf8_responses_are_rejected(monkeypatch):
    fake_opener(monkeypatch, response=Response(b"x" * (distribution.MAX_BYTES + 1)))
    with pytest.raises(distribution.CheckError, match="response_too_large"):
        distribution.fetch(distribution.GLAMA)
    fake_opener(monkeypatch, response=Response(b"\xff"))
    with pytest.raises(distribution.CheckError, match="request_failed"):
        distribution.fetch(distribution.GLAMA)


@pytest.mark.parametrize("strict,overall,exit_code", [(False, "attention", 0), (True, "attention", 1), (True, "current", 0)])
def test_cli_exit_status_does_not_confuse_collection_with_readiness(tmp_path, monkeypatch, capsys, strict, overall, exit_code):
    report = {"checked_at": AT, "status": overall, "checks": {"github_ci": {"status": "pending" if overall == "attention" else "current"}},
              "read_only": True, "remote_writes": 0, "model_calls": 0}
    monkeypatch.setattr(distribution, "collect", lambda **kwargs: report)
    output, summary = tmp_path / "report.json", tmp_path / "summary.md"
    arguments = ["check_distribution_status", "--output", str(output), "--summary", str(summary)]
    if strict:
        arguments.append("--strict")
    monkeypatch.setattr("sys.argv", arguments)
    assert distribution.main() == exit_code
    assert json.loads(output.read_text())["status"] == overall
    assert "does not mean every service is current" in summary.read_text()
    assert json.loads(capsys.readouterr().out)["status"] == overall


def test_failed_main_lookup_produces_unknown_report_and_exit_two(tmp_path, monkeypatch, capsys):
    def fail(**kwargs):
        raise distribution.CheckError(FICTIONAL_AUTH_VALUE)
    monkeypatch.setattr(distribution, "collect", fail)
    monkeypatch.setenv("GH_TOKEN", FICTIONAL_AUTH_VALUE)
    output, summary = tmp_path / "report.json", tmp_path / "summary.md"
    monkeypatch.setattr("sys.argv", ["check_distribution_status", "--output", str(output), "--summary", str(summary)])
    assert distribution.main() == 2
    text = output.read_text() + summary.read_text() + capsys.readouterr().out
    assert FICTIONAL_AUTH_VALUE not in text
    assert json.loads(output.read_text())["status"] == "unknown"


def test_github_actions_flags_incomplete_evidence(tmp_path, monkeypatch, capsys):
    report = {"checked_at": AT, "status": "attention", "checks": {"glama_index": {"status": "stale"}}}
    monkeypatch.setattr(distribution, "collect", lambda **kwargs: report)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr("sys.argv", ["check_distribution_status", "--output", str(tmp_path / "report.json"),
                                    "--summary", str(tmp_path / "summary.md")])
    assert distribution.main() == 0
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[0])["checks"]["glama_index"] == "stale"
    assert lines[1].startswith("::warning title=FF distribution needs review::")


@pytest.mark.parametrize("malformed", [[], None, "not a commit object"])
def test_malformed_main_replaces_prior_green_report_with_fresh_unknown(tmp_path, monkeypatch, public_reader, malformed):
    public_reader.responses["main"] = malformed
    collect = distribution.collect
    monkeypatch.setattr(distribution, "collect", lambda **kwargs: collect(reader=public_reader, **kwargs))
    output, summary = tmp_path / "report.json", tmp_path / "summary.md"
    output.write_text(json.dumps({"status": "current", "checks": {"github_main": {"status": "current"}}}), encoding="utf-8")
    summary.write_text("Overall: current", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["check_distribution_status", "--output", str(output), "--summary", str(summary)])
    assert distribution.main() == 2
    report = json.loads(output.read_text())
    assert report["status"] == "unknown"
    assert report["checks"]["github_main"]["status"] == "unknown"
    assert "Overall: **unknown**" in summary.read_text()
    assert report["read_only"] is True and report["remote_writes"] == 0
    assert len(public_reader.calls) == 1


def test_markdown_escapes_remote_table_and_html_content():
    report = {"checked_at": AT, "status": "attention", "checks": {"fictional": {
        "status": "unknown", "detail": "<img src=x onerror=bad()> | `code`\nnext"}}}
    result = distribution.markdown(report)
    assert "<img" not in result and "`code`" not in result
    assert "&lt;img" in result and "&#124;" in result and "&#96;code&#96;" in result
