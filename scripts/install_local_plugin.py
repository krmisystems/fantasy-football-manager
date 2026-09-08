"""Preview or prepare a personal Codex plugin through the plugin-creator helpers."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

NAME = "fantasy-football-manager"
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, required=True,
                        help="Directory containing the installed plugin-creator SKILL.md")
    parser.add_argument("--apply", action="store_true", help="Write the personal plugin and marketplace")
    parser.add_argument("--replace", action="store_true", help="Replace an existing plugin and its entry")
    args = parser.parse_args()
    helper_dir = args.skill_root.expanduser().resolve() / "scripts"
    helpers = {name: helper_dir / name for name in (
        "create_basic_plugin.py", "read_marketplace_name.py",
        "validate_plugin.py", "update_plugin_cachebuster.py",
    )}
    for path in helpers.values():
        if not path.is_file():
            parser.error(f"Missing Codex helper: {path}")

    source = ROOT / "plugins" / NAME
    manifest = json.loads((source / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    if manifest.get("name") != NAME:
        parser.error("Source plugin name does not match the installer")
    target = (Path.home() / "plugins" / NAME).resolve()
    marketplace = Path.home() / ".agents" / "plugins" / "marketplace.json"
    if source.resolve() == target or source.resolve() in target.parents:
        parser.error("The personal target must be separate from the source checkout")
    command = [sys.executable, str(helpers["create_basic_plugin.py"]), NAME,
               "--with-skills", "--with-mcp", "--with-marketplace"]
    print(f"Source: {source}")
    print(f"Personal plugin: {target}")
    print(f"Personal marketplace: {marketplace}")
    if args.replace:
        print("Update: verify the existing personal source, copy files, update cachebuster, validate.")
    else:
        print(f"Scaffold command: {subprocess.list2cmdline(command)}")
    if not args.apply:
        print("Preview only. Add --apply to write these files. No files were changed.")
        return 0
    if target.exists() and not args.replace:
        parser.error("Personal plugin already exists. Use --replace for an intentional update")
    try:
        __import__("yaml")
    except ImportError:
        parser.error("Plugin helpers require PyYAML. Run this installer with uv run --with pyyaml python")
    # Check the complete source and helper dependencies before personal files change.
    subprocess.run([sys.executable, str(helpers["validate_plugin.py"]), str(source)], check=True)
    if marketplace.exists():
        subprocess.run([sys.executable, str(helpers["read_marketplace_name.py"])], check=True)
    if args.replace:
        if not target.is_dir() or target.is_symlink() or not marketplace.is_file():
            parser.error("An update requires an existing personal plugin and marketplace entry")
        existing_manifest = json.loads((target / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        if existing_manifest.get("name") != NAME:
            parser.error("The existing plugin identifier does not match the source")
        existing_marketplace = json.loads(marketplace.read_text(encoding="utf-8"))
        entries = [entry for entry in existing_marketplace.get("plugins", []) if entry.get("name") == NAME]
        expected_source = {"source": "local", "path": f"./plugins/{NAME}"}
        if len(entries) != 1 or entries[0].get("source") != expected_source:
            parser.error("The personal marketplace must already point to this local plugin source")
    else:
        subprocess.run(command, check=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    if args.replace:
        subprocess.run([sys.executable, str(helpers["update_plugin_cachebuster.py"]), str(target)], check=True)
    subprocess.run([sys.executable, str(helpers["validate_plugin.py"]), str(target)], check=True)
    result = subprocess.run([sys.executable, str(helpers["read_marketplace_name.py"])],
                            check=True, capture_output=True, text=True)
    marketplace_name = result.stdout.strip()
    # The helper validates the identifier before this command is displayed.
    print("Personal source is ready. Run this command yourself:")
    print(f"codex plugin add {NAME}@{marketplace_name}")
    print("Start a new Codex conversation after installation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
