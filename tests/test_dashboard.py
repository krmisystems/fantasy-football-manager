"""Exercise the local dashboard over real loopback HTTP connections."""

from contextlib import contextmanager
import http.client
import json
import threading

import pytest

from fantasy_football_manager.dashboard import create_http_server


class SavedPortfolio:
    def __init__(self):
        self.calls = []

    def _result(self, method, **params):
        self.calls.append((method, params))
        if params.get("team_key") == "broken":
            raise RuntimeError("Private credential path: /srv/private/token.json")
        if params.get("team_key") == "missing":
            raise ValueError("Unknown team key.")
        return {"method": method, "params": params, "read_only": True}

    def overview(self, **params):
        return self._result("overview", **params)

    def team(self, team_key):
        return self._result("team", team_key=team_key)

    def analysis(self, team_key):
        return self._result("analysis", team_key=team_key)

    def players(self, **params):
        return self._result("players", **params)

    def proposals(self, **params):
        return self._result("proposals", **params)


@contextmanager
def running_server(tmp_path, portfolio=None):
    assets = tmp_path / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "index.html").write_text('<!doctype html><script src="app.js"></script>', encoding="utf-8")
    (assets / "app.js").write_text("document.title = 'Portfolio';", encoding="utf-8")
    selected = portfolio or SavedPortfolio()
    server = create_http_server(port=0, asset_root=assets, portfolio=selected)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield server, selected, assets
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def request(server, path="/", *, method="GET", headers=None, body=None):
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        client.request(method, path, body=body, headers=headers or {})
        response = client.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        client.close()


def test_static_delivery_security_headers_and_head(tmp_path):
    with running_server(tmp_path) as (server, portfolio, assets):
        status, headers, body = request(server)
        assert status == 200 and body == (assets / "index.html").read_bytes()
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors 'self'" in headers["Content-Security-Policy"]
        assert headers["X-Frame-Options"] == "SAMEORIGIN"
        assert "Access-Control-Allow-Origin" not in headers
        assert "Python" not in headers["Server"]
        assert request(server, "/app.js")[1]["Content-Type"] == "text/javascript"
        assert request(server, method="HEAD")[2] == b""
        assert portfolio.calls == []


@pytest.mark.parametrize(("path", "method", "params"), [
    ("/api/overview?sport=football&provider=espn", "overview", {"sport": "football", "provider": "espn"}),
    ("/api/teams/team-a", "team", {"team_key": "team-a"}),
    ("/api/teams/team-a/analysis", "analysis", {"team_key": "team-a"}),
    ("/api/players?team_key=team-a&query=Pat&position=TE&rostered_only=false&limit=2&offset=1", "players",
     {"team_key": "team-a", "query": "Pat", "position": "TE", "rostered_only": False, "limit": 2, "offset": 1}),
    ("/api/proposals?team_key=team-a&status=prepared&limit=10&offset=3", "proposals",
     {"team_key": "team-a", "status": "prepared", "limit": 10, "offset": 3}),
])
def test_read_routes_and_filter_arguments(tmp_path, path, method, params):
    with running_server(tmp_path) as (server, portfolio, _):
        status, _, body = request(server, path)
        assert status == 200 and json.loads(body)["params"] == params
        assert portfolio.calls == [(method, params)]


def test_health_has_no_private_manifest_or_asset_paths(tmp_path):
    with running_server(tmp_path) as (server, portfolio, _):
        status, _, body = request(server, "/api/health")
        assert status == 200
        value = json.loads(body)
        assert value["read_only"] is True
        assert value["source_mode"] == "configuration_required"
        assert str(tmp_path).encode() not in body
        assert portfolio.calls == []


@pytest.mark.parametrize("path", [
    "/../private", "/%2e%2e/private", "/%5c..%5cprivate", "/assets/../private",
    "/%00private", "/api/players?limit=0", "/api/players?limit=201", "/api/players?offset=-1",
    "/api/players?offset=100001", "/api/players?rostered_only=1", "/api/players?limit=1&limit=2",
    "/api/overview?manifest=/private/file", "/api/teams/team-a?manifest=secret",
    "/api/players?query=" + "x" * 201, "/api/overview?broken", "/api/players?limit=1.0",
])
def test_invalid_requests_cannot_read_or_change_state(tmp_path, path):
    with running_server(tmp_path) as (server, portfolio, _):
        assert request(server, path)[0] in {400, 404}
        assert portfolio.calls == []


@pytest.mark.parametrize("headers", [
    {"Host": "attacker.example:8765"}, {"Host": "127.0.0.1:1"}, {"Host": "localhost"},
    {"Host": "user@127.0.0.1:8765"}, {"Origin": "https://attacker.example"}, {"Origin": "null"},
])
def test_rebinding_and_cross_origin_requests_are_blocked(tmp_path, headers):
    with running_server(tmp_path) as (server, portfolio, _):
        assert request(server, "/api/overview", headers=headers)[0] == 403
        assert portfolio.calls == []


def test_same_origin_is_accepted_but_loopback_alias_origin_is_not(tmp_path):
    with running_server(tmp_path) as (server, _, _):
        origin = f"http://127.0.0.1:{server.server_port}"
        assert request(server, "/api/overview", headers={"Origin": origin})[0] == 200
        assert request(server, "/api/overview", headers={"Origin": f"http://localhost:{server.server_port}"})[0] == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"])
def test_write_methods_are_unavailable(tmp_path, method):
    with running_server(tmp_path) as (server, portfolio, _):
        assert request(server, "/api/proposals/approve", method=method, body=b"private")[0] == 405
        assert portfolio.calls == []


def test_get_body_is_rejected_and_errors_do_not_leak_private_paths(tmp_path):
    with running_server(tmp_path) as (server, portfolio, _):
        assert request(server, "/api/overview", body=b"private")[0] == 400
        assert portfolio.calls == []
        for name, expected in (("missing", 400), ("broken", 503)):
            status, _, body = request(server, "/api/teams/" + name)
            assert status == expected
            assert b"/srv/private" not in body and b"credential" not in body
        assert request(server, "/api/proposals/approve")[0] == 404


def test_symlink_cannot_leave_packaged_assets(tmp_path):
    with running_server(tmp_path) as (server, _, assets):
        outside = tmp_path / "secret.json"
        outside.write_text('{"secret": true}', encoding="utf-8")
        try:
            (assets / "escape.json").symlink_to(outside)
        except OSError:
            pytest.skip("This account cannot create symlinks.")
        status, _, body = request(server, "/escape.json")
        assert status == 404 and b"secret" not in body


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.2", "example.com", "127.1"])
def test_only_loopback_bind_names_are_accepted(host):
    with pytest.raises(ValueError, match="Bind the dashboard"):
        create_http_server(host=host, demo=True)


def test_missing_assets_have_a_clear_safe_error(tmp_path):
    with pytest.raises(ValueError, match="Dashboard assets are missing") as exc:
        create_http_server(demo=True, asset_root=tmp_path)
    assert str(tmp_path) not in str(exc.value)


def test_demo_uses_packaged_assets_and_real_portfolio():
    server = create_http_server(demo=True, port=0)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        assert request(server)[0] == 200
        status, _, body = request(server, "/api/overview")
        assert status == 200 and json.loads(body)["demo"] is True
        assert json.loads(request(server, "/api/health")[2])["source_mode"] == "demo"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
