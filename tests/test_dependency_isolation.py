"""Verify HTTP MCP discovery with optional browser imports disabled in a fresh process."""

import json
from pathlib import Path
import subprocess
import sys
import textwrap
import tomllib


def test_http_mcp_needs_no_playwright_and_explicit_browser_errors_are_actionable(tmp_path):
    source = Path(__file__).resolve().parents[1] / "src"
    code = textwrap.dedent("""
        import asyncio
        import importlib.abc
        import json
        import os
        from pathlib import Path
        import sys
        import urllib.request

        sys.path.insert(0, sys.argv[1])
        root = Path(sys.argv[2])
        os.environ['FFM_DATA_DIR'] = str(root / 'unused-state')
        os.environ['FFM_BROWSER_DATA_DIR'] = str(root / 'adapter-state')
        os.environ['FFM_ESPN_TRANSPORT'] = 'http'
        os.environ['FFM_ESPN_CREDENTIAL_FILE'] = str(root / 'missing-session.json')
        blocked = []

        class NoPlaywright(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == 'playwright' or fullname.startswith('playwright.'):
                    blocked.append(fullname)
                    raise ModuleNotFoundError('Optional browser dependency disabled for this test.')
                return None

        sys.meta_path.insert(0, NoPlaywright())

        def no_network(*args, **kwargs):
            raise AssertionError('Discovery and missing-dependency checks must not make HTTP requests.')

        urllib.request.OpenerDirector.open = no_network
        from mcp import Client
        from fantasy_football_manager.espn_mcp import create_espn_server
        from fantasy_football_manager.espn_service import ESPNService

        async def main():
            service = ESPNService(root / 'service', transport='http')
            assert service.browser.transport == 'http'
            assert not service.browser.status()['connected']
            assert not service.browser.status()['browser_started']
            assert 'fantasy_football_manager.espn_browser' not in sys.modules
            assert blocked == []
            await service.close()

            async with Client(create_espn_server(root / 'mcp', transport='http')) as client:
                listing = await client.list_tools()
                assert len(listing.tools) == 16
                status = await client.call_tool('espn_get_status', {})
                assert not status.is_error
                assert not status.structured_content['browser']['connected']
                assert not status.structured_content['browser']['browser_started']
                assert status.structured_content['transport'] == 'http'
                assert blocked == []
                for phase in ('draft', 'season'):
                    result = await client.call_tool('espn_connect', {
                        'league_id': '123', 'team_id': '1', 'season': 2026,
                        'phase': phase, 'transport': 'browser', 'headless': True,
                    })
                    assert result.is_error
                    message = ' '.join(item.text for item in result.content if hasattr(item, 'text')).lower()
                    assert 'install' in message and 'browser' in message, message
                    assert 'dependencies' in message or 'extra' in message, message
            assert blocked
            print(json.dumps({'http_discovery': True, 'explicit_browser_errors': True, 'blocked_imports': len(blocked)}))

        asyncio.run(main())
    """)
    result = subprocess.run([sys.executable, "-I", "-c", code, str(source), str(tmp_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout)
    assert observed["http_discovery"] and observed["explicit_browser_errors"] and observed["blocked_imports"] >= 2


def test_browser_library_is_an_optional_install_dependency():
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any(item.lower().startswith("playwright") for item in project["project"]["dependencies"])
    assert any(item.lower().startswith("playwright") for item in project["project"]["optional-dependencies"]["browser"])
