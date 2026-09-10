"""Build an allowlisted Codex plugin ZIP and its SHA-256 file manifest."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from validate_release import NAME, ROOT, SKILLS, validate

FILES = (
    "LICENSE",
    "README.md",
    "SECURITY.md",
    ".codexignore",
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "assets/icon.svg",
    *(f"skills/{name}/SKILL.md" for name in SKILLS),
)


def main() -> int:
    errors, _ = validate(ROOT)
    if errors:
        raise SystemExit("Release checks failed:\n" + "\n".join(errors))
    source = ROOT / "plugins" / NAME
    version = json.loads((source / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / f"{NAME}-{version}-plugin.zip"
    entries = []
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for relative in FILES:
            path = source / relative
            if path.is_symlink():
                raise SystemExit(f"Plugin source must not be a symlink: {relative}")
            data = path.read_bytes()
            bundle.writestr(f"{NAME}/{relative}", data)
            entries.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = output / f"{NAME}-{version}-plugin-manifest.json"
    manifest.write_text(json.dumps({
        "name": NAME, "version": version, "files": entries,
        "archive": archive.name, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }, indent=2) + "\n", encoding="utf-8")
    print(archive)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
