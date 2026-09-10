"""Generate the repository-root catalog manifest from the packaged plugin."""

import argparse
import json

from validate_release import CATALOG_FILES, NAME, ROOT, catalog_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = ROOT / "plugins" / NAME / ".codex-plugin/plugin.json"
    expected = catalog_manifest(json.loads(source.read_text(encoding="utf-8")))
    target = ROOT / ".codex-plugin/plugin.json"
    for relative in CATALOG_FILES:
        content = (ROOT / "plugins" / NAME / relative).read_bytes()
        copy = ROOT / relative
        if args.check:
            if not copy.is_file() or copy.read_bytes() != content:
                raise SystemExit(f"Catalog file differs: {relative}. Run scripts/sync_catalog_manifest.py.")
        else:
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(content)
    if args.check:
        if not target.is_file() or json.loads(target.read_text(encoding="utf-8")) != expected:
            raise SystemExit("Catalog manifest differs. Run scripts/sync_catalog_manifest.py.")
        print("Catalog manifest matches the packaged plugin.")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print("Generated .codex-plugin/plugin.json.")


if __name__ == "__main__":
    main()
