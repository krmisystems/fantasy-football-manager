"""Check portable release metadata and reject common private runtime files."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "fantasy-football-manager"
COMPANION = "fantasy-football-espn"
SKILLS = ("draft-assistant", "espn-automation", "season-manager")
SKIP_DIRS = {".git", ".venv", ".pytest_cache", "__pycache__", "dist", "build",
             ".demo-state", ".ci-demo", ".test-state", ".local-state", ".ruff_cache"}
PRIVATE_NAMES = {".watcher-token", "draft-state.json", "observed-ledger.json",
                 "verified-history.txt", "manual-observed-picks.json", "cookies.json",
                 "credentials.json", "corrected-recommendations.json"}
PRIVATE_NAMES.update({"Cookies", "Login Data", "Local State", "Web Data", "History",
                      "Preferences", "Secure Preferences", "espn-browser.lock"})
PRIVATE_DIRS = {"private-captures", "espn-browser-profile", "browser-profile"}
PRIVATE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".log", ".pem", ".key"}
TEXT_SUFFIXES = {".py", ".json", ".md", ".toml", ".yml", ".yaml", ".txt", ".mmd", ".lock", ".html",
                 ".service", ".timer", ".sh", ".jsonl"}
SECRET_PATTERNS = (
    re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s\"']+", re.IGNORECASE),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{32,}|github_pat_[A-Za-z0-9_]{32,}|sk-[A-Za-z0-9]{32,})\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def validate(root: Path, expected_version: str | None = None) -> tuple[list[str], int]:
    errors: list[str] = []
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    runtime_versions = []
    try:
        runtime = ast.parse((root / "src" / "fantasy_football_manager" / "__init__.py").read_text(encoding="utf-8"))
        for node in runtime.body:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            if any(isinstance(target, ast.Name) and target.id == "__version__" for target in targets):
                runtime_versions.append(node.value.value if isinstance(node.value, ast.Constant) else None)
    except (OSError, SyntaxError):
        pass
    if runtime_versions != [version]:
        errors.append("Runtime __version__ must be one literal matching pyproject.toml")
    try:
        lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
        local_packages = [package for package in lock.get("package", []) if package.get("name") == NAME]
        valid_lock = (len(local_packages) == 1 and local_packages[0].get("version") == version
                      and local_packages[0].get("source") in ({"editable": "."}, {"virtual": "."}))
    except (OSError, tomllib.TOMLDecodeError):
        valid_lock = False
    if not valid_lock:
        errors.append("uv.lock must contain one matching local project package version")
    plugin_dir = root / "plugins" / NAME
    plugin = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    registry = json.loads((root / "docs" / "registry" / "server.json").read_text(encoding="utf-8"))
    command = json.loads((plugin_dir / ".mcp.json").read_text(encoding="utf-8"))
    if expected_version and expected_version != version:
        errors.append("Requested release version does not match pyproject.toml")
    if project["name"] != NAME or plugin.get("name") != NAME:
        errors.append("Package and plugin names must match")
    if plugin.get("version") != version or registry.get("version") != version:
        errors.append("Package, plugin, and registry versions must match")
    namespace = f"io.github.krmisystems/{NAME}"
    if registry.get("name") != namespace:
        errors.append("Registry namespace does not match the intended package owner")
    marker = f"mcp-name: {namespace}"
    if marker not in (root / "README.md").read_text(encoding="utf-8"):
        errors.append("README is missing the MCP Registry package marker")
    packages = registry.get("packages", [])
    if len(packages) != 1 or packages[0] != {
        "registryType": "pypi", "identifier": NAME, "version": version, "transport": {"type": "stdio"}
    }:
        errors.append("Registry package must match the local PyPI STDIO release")
    expected_commands = {"mcpServers": {name: {"command": name, "args": []} for name in (NAME, COMPANION)}}
    if command != expected_commands:
        errors.append("Plugin MCP configuration must include both portable installed commands")
    expected_scripts = {NAME: "fantasy_football_manager.mcp_server:main",
                        COMPANION: "fantasy_football_manager.espn_mcp:main"}
    if any(project.get("scripts", {}).get(name) != target for name, target in expected_scripts.items()):
        errors.append("Manager and ESPN installed CLI entry points must match the package")
    if plugin.get("mcpServers") != "./.mcp.json":
        errors.append("Plugin manifest must reference its two-server companion configuration")
    for skill_name in SKILLS:
        path = plugin_dir / "skills" / skill_name / "SKILL.md"
        if not path.is_file():
            errors.append(f"Plugin is missing required skill: {skill_name}")
            continue
        contents = path.read_text(encoding="utf-8")
        if not contents.startswith("---\n") or f"name: {skill_name}\n" not in contents:
            errors.append(f"Skill front matter does not identify {skill_name}")
    checked = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in relative.parts):
            continue
        if path.is_symlink():
            errors.append(f"Review symlink before release: {relative.as_posix()}")
            continue
        if not path.is_file():
            continue
        checked += 1
        if (path.name in PRIVATE_NAMES or path.suffix.lower() in PRIVATE_SUFFIXES
                or path.name.startswith(".env") or any(part in PRIVATE_DIRS for part in relative.parts)
                or path.name.endswith((".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm"))):
            errors.append(f"Private runtime file is in release source: {relative.as_posix()}")
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", ".gitignore"}:
            contents = path.read_text(encoding="utf-8")
            if any(pattern.search(contents) for pattern in SECRET_PATTERNS):
                errors.append(f"Possible private path or secret in: {relative.as_posix()}")
    return errors, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Require this exact package version")
    args = parser.parse_args()
    errors, checked = validate(ROOT, args.version)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Release metadata and privacy-pattern checks passed ({checked} source files).")
    print("This check does not verify publisher ownership or live provider integration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
