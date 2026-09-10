"""Check this project's public distribution state. Never publish or trigger builds."""

from __future__ import annotations

import argparse
import ast
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.client import HTTPException
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = "krmisystems/fantasy-football-manager"
GITHUB = "https://api.github.com/repos/" + REPO
GLAMA = "https://glama.ai/mcp/servers/" + REPO
ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 6_000_000
SHA = re.compile(r"[0-9a-f]{40}")
ROUTE = "routes/_public/mcp/servers/~namespace/~slug/_pages/"


class CheckError(ValueError):
    """A bounded public check could not establish its result."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CheckError("redirect_refused")


def fetch(url, *, token=None):
    """Read fixed public hosts. Send an optional token only to GitHub."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc not in {"api.github.com", "glama.ai", "pypi.org"}:
        raise CheckError("unexpected_endpoint")
    headers = {"User-Agent": "fantasy-football-manager-distribution-check", "Cache-Control": "no-cache"}
    if parsed.netloc == "api.github.com":
        headers.update(Accept="application/vnd.github+json")
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token:
            headers["Authorization"] = "Bearer " + token
    try:
        with build_opener(NoRedirect()).open(Request(url, headers=headers), timeout=15) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise CheckError("response_too_large")
            return body.decode("utf-8")
    except HTTPError as exc:
        raise CheckError("http_" + str(exc.code)) from None
    except (URLError, TimeoutError, OSError, UnicodeError, HTTPException):
        raise CheckError("request_failed") from None


def decode_hydration(html):
    """Decode Glama's observed public JSON format without executing JavaScript."""
    chunks = re.findall(r'window\.__reactRouterContext\.streamController\.enqueue\(("(?:\\.|[^"\\])*")\)', html)
    if len(chunks) != 1:
        raise CheckError("public_page_format_changed")
    try:
        nodes = json.loads(json.loads(chunks[0]))
        if not isinstance(nodes, list) or not 0 < len(nodes) <= 100_000:
            raise CheckError("invalid_public_nodes")
        memo, active = {}, set()

        def resolve(index, depth=0):
            if type(index) is not int or depth > 100:
                raise CheckError("invalid_public_reference")
            if index == -5:
                return None
            if not 0 <= index < len(nodes) or index in active:
                raise CheckError("invalid_public_reference")
            if index in memo:
                return memo[index]
            active.add(index)
            value = nodes[index]
            if isinstance(value, dict):
                result = {}
                for key, item in value.items():
                    if not re.fullmatch(r"_\d+", key):
                        raise CheckError("invalid_public_key")
                    name = resolve(int(key[1:]), depth + 1)
                    if not isinstance(name, str) or name in result:
                        raise CheckError("invalid_public_key")
                    result[name] = resolve(item, depth + 1)
            elif isinstance(value, list):
                result = [resolve(item, depth + 1) for item in value]
            else:
                result = value
            active.remove(index)
            memo[index] = result
            return result

        return resolve(0)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise CheckError("public_page_format_changed") from None


def route(data, suffix):
    value = data.get("loaderData", {}).get(ROUTE + suffix)
    if not isinstance(value, dict):
        raise CheckError("public_page_format_changed")
    return value


def source_tools(source):
    """Read tool names and docstrings from source without importing the manager."""
    result = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "server"
                    and decorator.func.attr == "tool"):
                name = node.name
                for keyword in decorator.keywords:
                    if keyword.arg == "name":
                        name = ast.literal_eval(keyword.value)
                if not isinstance(name, str) or name in result:
                    raise CheckError("invalid_source_tool_names")
                result[name] = inspect.cleandoc(ast.get_docstring(node, clean=False) or "")
    if not result:
        raise CheckError("no_source_tools")
    return result


def compare_tools(expected, tools):
    if not isinstance(tools, list) or not tools:
        raise CheckError("invalid_public_tools")
    actual = {}
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not isinstance(tool.get("description"), str):
            raise CheckError("invalid_public_tools")
        if tool["name"] in actual:
            raise CheckError("duplicate_public_tools")
        actual[tool["name"]] = inspect.cleandoc(tool["description"])
    changed = sorted(name for name in expected.keys() & actual.keys() if expected[name] != actual[name])
    return {"status": "current" if expected == actual else "stale", "expected_count": len(expected),
            "public_count": len(actual), "missing": sorted(expected.keys() - actual.keys()),
            "unexpected": sorted(actual.keys() - expected.keys()), "changed_descriptions": changed,
            "scope": "Manager tool names and descriptions only. Schemas, ESPN tools, and portfolio tools are not compared."}


def ci_status(data, head):
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        raise CheckError("invalid_ci_response")
    if any(not isinstance(run, dict) or type(run.get("id")) is not int for run in data["workflow_runs"]):
        raise CheckError("invalid_ci_response")
    runs = [run for run in data["workflow_runs"] if run.get("head_sha") == head
            and run.get("head_branch") == "main" and run.get("event") in {"push", "workflow_dispatch"}]
    if not runs:
        return {"status": "pending", "reason": "No main CI run is available for this commit."}
    run = max(runs, key=lambda item: item["id"])
    conclusion = run.get("conclusion")
    state = "pending" if run.get("status") != "completed" else ("current" if conclusion == "success" else "failed")
    return {"status": state, "run_id": run["id"], "conclusion": conclusion, "url": run.get("html_url")}


def git_value(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise CheckError("local_git_unavailable")
    return result.stdout.strip()


def content(value):
    if value.get("encoding") != "base64" or not isinstance(value.get("content"), str):
        raise CheckError("invalid_source_content")
    return base64.b64decode(value["content"]).decode("utf-8")


def outcome(function):
    try:
        return function()
    except (CheckError, ValueError, TypeError, KeyError, AttributeError, RecursionError, SyntaxError, subprocess.SubprocessError):
        return {"status": "unknown", "reason": "The response could not establish this check. Retry or inspect the linked service."}


def collect(*, reader=fetch, token=None):
    def get(url):
        return reader(url, token=token)

    def get_json(url):
        return json.loads(get(url))

    main = get_json(GITHUB + "/commits/main")
    if not isinstance(main, dict):
        raise CheckError("invalid_github_commit")
    head = main.get("sha")
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise CheckError("invalid_github_commit")
    urls = {
        "source": GITHUB + "/contents/pyproject.toml?" + urlencode({"ref": head}),
        "tools": GITHUB + "/contents/src/fantasy_football_manager/mcp_server.py?" + urlencode({"ref": head}),
        "ci": GITHUB + "/actions/workflows/ci.yml/runs?" + urlencode({"head_sha": head, "branch": "main", "per_page": 20}),
        "releases": GITHUB + "/releases?per_page=30",
        "pypi": "https://pypi.org/pypi/fantasy-football-manager/json",
        "tree": GLAMA + "/tree", "schema": GLAMA + "/schema", "overview": GLAMA,
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {name: pool.submit(get, url) for name, url in urls.items()}
        responses = {}
        for name, future in futures.items():
            try:
                responses[name] = future.result()
            except (CheckError, ValueError, TypeError, OSError):
                responses[name] = None

    def data(name):
        return json.loads(responses[name])

    def source_version():
        project = tomllib.loads(content(data("source")))["project"]
        value = project["version"]
        if (project.get("name") != "fantasy-football-manager" or not isinstance(value, str)
                or not re.fullmatch(r"[0-9][A-Za-z0-9.!+_-]{0,99}", value)):
            raise CheckError("invalid_source_version")
        return {"status": "current", "version": value}

    source = outcome(source_version)
    version = source.get("version")

    def local():
        local_head = git_value("rev-parse", "HEAD")
        dirty = bool(git_value("status", "--porcelain"))
        return {"status": "current" if local_head == head and not dirty else "pending", "head": local_head,
                "uncommitted_changes": dirty, "matches_main": local_head == head}

    def releases():
        published = [item for item in data("releases") if not item.get("draft")]
        if not published:
            return {"status": "pending", "reason": "No GitHub release is published."}
        latest = max(published, key=lambda item: item.get("published_at") or "")
        return {"status": "unknown" if version is None else ("current" if latest["tag_name"].removeprefix("v") == version else "pending"),
                "tag": latest["tag_name"], "prerelease": latest.get("prerelease"), "url": latest.get("html_url"),
                "scope": "Version comparison only. A tag is not a build attestation for current main."}

    def pypi():
        info = data("pypi")["info"]
        if info.get("name") != "fantasy-football-manager":
            raise CheckError("wrong_package")
        return {"status": "unknown" if version is None else ("current" if info["version"] == version else "pending"),
                "version": info["version"], "url": "https://pypi.org/project/fantasy-football-manager/",
                "scope": "Version comparison only. Unreleased source can intentionally be newer."}

    def index():
        tree = route(decode_hydration(responses["tree"]), "_explorer/tree/_index/_route")
        indexed = tree["member"]["commit"]["sha"]
        if not isinstance(indexed, str) or not SHA.fullmatch(indexed):
            raise CheckError("invalid_glama_commit")
        return {"status": "current" if indexed == head else "stale", "indexed_commit": indexed,
                "expected_commit": head, "url": GLAMA + "/tree", "scope": "Indexed repository source, not the hosted build."}

    def schema():
        public = route(decode_hydration(responses["schema"]), "schema/_route")["schema"]
        return compare_tools(source_tools(content(data("tools"))), public["tools"])

    def listing():
        public = decode_hydration(responses["overview"])
        server = route(public, "_index/_route")["mcpServer"]
        latest = server["repository"].get("latestRelease") or {}
        return {"status": "observed", "url": GLAMA, "updated_at": server.get("updatedAt"),
                "image_release": latest.get("version"), "scope": "Glama image versions differ from Python package versions."}

    checks = {"local_checkout": outcome(local), "github_main": {"status": "current", "commit": head,
              "url": "https://github.com/" + REPO + "/commit/" + head}, "source_package": source,
              "github_ci": outcome(lambda: ci_status(data("ci"), head)), "github_release": outcome(releases),
              "pypi_release": outcome(pypi), "glama_index": outcome(index), "glama_tools": outcome(schema),
              "glama_listing": outcome(listing), "glama_build": {"status": "unknown",
              "reason": "The checked public pages do not attest the deployed build commit. Verify it in Glama Admin."}}
    issues = [name for name, value in checks.items() if value["status"] not in {"current", "observed"}]
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "repository": REPO,
            "status": "attention" if issues else "current", "attention": issues, "checks": checks,
            "read_only": True, "model_calls": 0, "remote_writes": 0,
            "method": "GitHub and PyPI public APIs; observed Glama public JSON hydration without script execution.",
            "limits": "Glama hydration is undocumented. Format changes report unknown. No sync, build, publication, or score change is requested."}


def markdown(report):
    lines = ["# FF distribution status", "", "Checked: " + report["checked_at"], "",
             "Overall: **" + report["status"] + "**. A successful check run does not mean every service is current.", "",
             "| Check | State | Evidence |", "|---|---|---|"]
    for name, value in report.get("checks", {}).items():
        details = {key: item for key, item in value.items() if key not in {"status", "url"}}
        # Remote values are text only. Escape table and HTML syntax in the summary.
        text = json.dumps(details, ensure_ascii=True).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace("|", "&#124;").replace("`", "&#96;").replace("\n", " ")
        lines.append(f"| {name} | {value['status']} | {text} |")
    lines += ["", "No remote changes or model calls occurred.", "", report.get("limits", "Check collection failed."), ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local-state/distribution-status/report.json")
    parser.add_argument("--summary", type=Path, default=ROOT / ".local-state/distribution-status/summary.md")
    parser.add_argument("--strict", action="store_true", help="Exit 1 for pending, stale, failed, or unknown checks.")
    args = parser.parse_args()
    failed = False
    try:
        report = collect(token=os.environ.get("GH_TOKEN"))
    except (CheckError, ValueError, TypeError, KeyError, OSError):
        failed = True
        report = {"checked_at": datetime.now(timezone.utc).isoformat(), "repository": REPO,
                  "status": "unknown", "checks": {"github_main": {"status": "unknown", "reason": "Could not read GitHub main."}},
                  "read_only": True, "model_calls": 0, "remote_writes": 0}
    for path, text in [(args.output, json.dumps(report, indent=2) + "\n"), (args.summary, markdown(report))]:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    print(json.dumps({"status": report["status"], "checks": {name: value["status"] for name, value in report["checks"].items()}}))
    if os.environ.get("GITHUB_ACTIONS") == "true" and report["status"] != "current":
        print("::warning title=FF distribution needs review::One or more checks are pending, stale, failed, or unknown. Read the job summary and report artifact.")
    return 2 if failed else (1 if args.strict and report["status"] != "current" else 0)


if __name__ == "__main__":
    raise SystemExit(main())
