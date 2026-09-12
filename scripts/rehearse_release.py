"""Check a wheel in fresh and upgraded isolated environments without live credentials."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile


PROBE = r'''
import asyncio, hashlib, importlib.util, json, os, sys
from pathlib import Path
from mcp import Client
from mcp.client.stdio import StdioServerParameters
import fantasy_football_manager as package
async def main():
    assert importlib.util.find_spec('playwright') is None
    definitions = {}
    for module, arguments, tool in [
        ('mcp_server', ['--data-dir', 'manager'], 'get_capabilities'),
        ('espn_mcp', ['--data-dir', 'espn', '--transport', 'http'], 'espn_get_status'),
        ('portfolio_mcp', [], 'list_managed_teams')]:
        parameters = StdioServerParameters(command=sys.executable, args=['-m', 'fantasy_football_manager.'+module, *arguments], env=dict(os.environ))
        async with Client(parameters, mode='legacy', read_timeout_seconds=30) as client:
            tools = await client.list_tools()
            result = await client.call_tool(tool, {})
            assert not result.is_error
            definitions[module] = [t.model_dump(mode='json') for t in tools.tools]
    root = Path(package.__file__).parent
    files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.py')}
    print(json.dumps({'version':package.__version__, 'python_files': files, 'definitions': definitions, 'playwright_absent':True}))
asyncio.run(main())
'''


def run(wheel, previous, output):
    wheel = Path(wheel).resolve()
    if not wheel.is_file() or wheel.suffix != ".whl" or not re.fullmatch(r"\d+\.\d+\.\d+(?:[a-z0-9.]+)?", previous):
        raise ValueError("Supply a wheel and an exact previous package version.")
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("Install uv before this rehearsal.")
    # Strip application configuration before every subprocess. Never inherit a real team or credential path.
    env = {k: v for k, v in os.environ.items() if not k.startswith("FFM_") and k not in {"PYTHONPATH", "PYTHONHOME"}}
    results = {}
    with tempfile.TemporaryDirectory(prefix="ffm-release-") as temporary:
        root = Path(temporary)
        def command(args, cwd=root):
            return subprocess.run(args, cwd=cwd, env=env, check=True, capture_output=True, text=True, timeout=300)
        for mode in ("clean", "upgrade"):
            directory = root / mode
            command([uv, "venv", str(directory)])
            python = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if mode == "upgrade":
                command([uv, "pip", "install", "--python", str(python), "fantasy-football-manager==" + previous])
                # Seed an isolated fictional store before upgrading; verify byte-for-byte logical state afterward.
                seed = "from fantasy_football_manager.store import Manager; from fantasy_football_manager.portfolio_demo import make_portfolio_demo; import json; m=Manager('retained'); f=make_portfolio_demo()[0]; m.import_snapshot(f.snapshot.model_dump(mode='json')); print(json.dumps([v.model_dump(mode='json') if hasattr(v,'model_dump') else v for v in m.state()],sort_keys=True))"
                before = command([str(python), "-c", seed], directory).stdout
            command([uv, "pip", "install", "--reinstall-package", "fantasy-football-manager", "--python", str(python), str(wheel)])
            if mode == "upgrade":
                after = command([str(python), "-c", "from fantasy_football_manager.store import Manager; import json; print(json.dumps([v.model_dump(mode='json') if hasattr(v,'model_dump') else v for v in Manager('retained').state()],sort_keys=True))"], directory).stdout
                if before != after:
                    raise ValueError("The upgrade changed retained team state.")
            results[mode] = json.loads(command([str(python), "-c", PROBE], directory).stdout)
        if results["clean"] != results["upgrade"]:
            raise ValueError("Fresh and upgraded installations differ.")
    with zipfile.ZipFile(wheel) as archive:
        expected = {name.removeprefix("fantasy_football_manager/").replace("/", os.sep): hashlib.sha256(archive.read(name)).hexdigest()
                    for name in archive.namelist() if name.startswith("fantasy_football_manager/") and name.endswith(".py")}
    if results["clean"]["python_files"] != expected:
        raise ValueError("Installed Python files differ from the selected wheel.")
    result = {"schema_version": 1, "kind": "release_rehearsal", "checked_at": datetime.now(timezone.utc).isoformat(),
              "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "previous_version": previous,
              "clean_install": True, "upgrade": True, "retained_snapshot_unchanged": True,
              "version": results["clean"]["version"], "playwright_absent": True,
              "tool_counts": {k: len(v) for k, v in results["clean"]["definitions"].items()},
              "python_files": results["clean"]["python_files"],
              "tool_definitions_sha256": hashlib.sha256(json.dumps(results["clean"]["definitions"],sort_keys=True).encode()).hexdigest()}
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--previous-version", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.wheel, args.previous_version, args.output)
    print(json.dumps({k: result[k] for k in ("clean_install", "upgrade", "version", "tool_counts", "wheel_sha256")}))
