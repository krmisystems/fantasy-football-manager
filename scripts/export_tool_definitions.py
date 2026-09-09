"""Export public MCP metadata with isolated temporary state and no browser calls."""

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fantasy_football_manager.espn_mcp import create_espn_server
from fantasy_football_manager.mcp_server import create_server


async def export_tools(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="ffm-tool-definitions-") as temporary:
        root = Path(temporary)
        for name, factory in (("manager", create_server), ("espn", create_espn_server)):
            server = factory(root / name)
            definitions = await server.list_tools()
            result = {"tools": [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in definitions]}
            destination = output_dir / f"{name}-tools.json"
            destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"Exported {len(definitions)} {name} tool definitions to {destination.name}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for manager-tools.json and espn-tools.json.")
    arguments = parser.parse_args()
    asyncio.run(export_tools(arguments.output_dir))


if __name__ == "__main__":
    main()
