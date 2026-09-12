"""Serve local portfolio views with optional exact proposal approval."""

import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import socket
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

from . import __version__
from .portfolio import Portfolio


_HOSTS = {"127.0.0.1", "localhost", "::1"}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
)


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _IPv6Server(DashboardServer):
    address_family = socket.AF_INET6


def _authority(value, port):
    """Accept an explicit loopback authority with the actual listening port."""
    try:
        parsed = urlsplit("//" + value)
        return (
            parsed.hostname in _HOSTS and parsed.port == port
            and not parsed.username and not parsed.password
            and not parsed.path and not parsed.query and not parsed.fragment
        )
    except ValueError:
        return False


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "FantasyPortfolio"
    sys_version = ""

    def __init__(self, *args, portfolio, asset_root, source_mode, actions=None, readiness_report=None, **kwargs):
        self.portfolio = portfolio
        self.asset_root = asset_root
        self.source_mode = source_mode
        self.actions = actions
        self.readiness_report = readiness_report
        self._request_body_consumed = False
        super().__init__(*args, **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # URLs can include private team names. Do not log request arguments.
        return

    def _respond(self, status, value, content_type="application/json; charset=utf-8"):
        headers = getattr(self, "headers", None)
        if status >= 400 and not self._request_body_consumed and headers is not None:
            lengths = headers.get_all("Content-Length", [])
            if (len(lengths) == 1 and lengths[0].isascii() and lengths[0].isdigit()
                    and 0 < int(lengths[0]) <= 8192 and not headers.get("Transfer-Encoding")):
                # Drain a bounded rejected body so Windows can deliver the error response.
                self._request_body_consumed = True
                try:
                    self.rfile.read(int(lengths[0]))
                except OSError:
                    pass
        if not isinstance(value, bytes):
            value = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(value)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", _CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(value)

    def send_error(self, code, message=None, explain=None):
        self._respond(code, {"error": "The request is invalid."})

    def _trusted_request(self, *, write=False):
        port = self.server.server_port
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or not _authority(hosts[0], port):
            self._respond(403, {"error": "Use the dashboard's loopback address."})
            return False
        origins = self.headers.get_all("Origin", [])
        if write and not origins:
            self._respond(403, {"error": "A same-origin request is required."})
            return False
        if origins:
            try:
                origin = urlsplit(origins[0])
                accepted = (
                    len(origins) == 1 and origin.scheme == "http" and not origin.path
                    and not origin.query and not origin.fragment and origin.netloc.lower() == hosts[0].lower()
                    and _authority(origin.netloc, port)
                )
            except ValueError:
                accepted = False
            if not accepted:
                self._respond(403, {"error": "Cross-origin requests are unavailable."})
                return False
        if self.headers.get("Transfer-Encoding") or (not write and self.headers.get("Content-Length", "0") != "0"):
            self._respond(400, {"error": "Request bodies are unavailable."})
            return False
        return True

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._trusted_request():
            return
        try:
            if len(self.path) > 4096 or not self.path.startswith("/") or self.path.startswith("//"):
                raise ValueError
            target = urlsplit(self.path)
            if target.scheme or target.netloc or target.fragment:
                raise ValueError
            path = unquote(target.path, errors="strict")
            if "\\" in path or "\x00" in path or any(part in {".", ".."} for part in path.split("/")):
                raise ValueError
            query = parse_qs(target.query, keep_blank_values=True, strict_parsing=True, max_num_fields=12)
            if any(len(values) != 1 or len(values[0]) > 200 for values in query.values()):
                raise ValueError
            params = {key: values[0] for key, values in query.items()}
            if path.startswith("/api/"):
                self._api(path, params)
            else:
                if params:
                    raise ValueError
                self._static(path)
        except (ValueError, UnicodeError):
            self._respond(400, {"error": "Invalid team, filter, or request. Check the portfolio configuration."})
        except Exception:
            self._respond(503, {"error": "The saved portfolio data is unavailable."})

    def _api(self, path, params):
        if path == "/api/readiness" and not params:
            from .readiness import public_report
            self._respond(200, public_report(self.readiness_report) if self.readiness_report else
                          {"status": "unavailable", "release_ready": False, "gates": {}})
            return
        if path == "/api/session" and not params:
            self._respond(200, {"actions_enabled": self.actions is not None,
                                "demo": self.source_mode == "demo", "read_only": self.actions is None,
                                "csrf_token": self.actions.csrf_token if self.actions else None})
            return
        if path == "/api/health" and not params:
            self._respond(200, {"service": "fantasy-football-dashboard", "version": __version__,
                                "read_only": self.actions is None, "source_mode": self.source_mode})
            return
        routes = {
            "/api/overview": (self.portfolio.overview, {"sport", "provider"}),
            "/api/players": (self.portfolio.players, {"team_key", "query", "position", "rostered_only", "limit", "offset"}),
            "/api/proposals": (self.portfolio.proposals, {"team_key", "status", "limit", "offset"}),
        }
        if path in routes:
            function, allowed = routes[path]
            if not set(params) <= allowed:
                raise ValueError
            for key in ("limit", "offset"):
                if key in params:
                    if not params[key].isascii() or not params[key].isdigit():
                        raise ValueError
                    params[key] = int(params[key])
                    if not (1 <= params[key] <= 200 if key == "limit" else 0 <= params[key] <= 100000):
                        raise ValueError
            if "rostered_only" in params:
                if params["rostered_only"] not in {"true", "false"}:
                    raise ValueError
                params["rostered_only"] = params["rostered_only"] == "true"
            self._respond(200, function(**params))
            return
        parts = path.split("/")
        if len(parts) in {4, 5} and parts[:3] == ["", "api", "teams"] and parts[3] and not params:
            if len(parts) == 4:
                self._respond(200, self.portfolio.team(parts[3]))
                return
            if parts[4] == "analysis":
                self._respond(200, self.portfolio.analysis(parts[3]))
                return
        self._respond(404, {"error": "This dashboard route does not exist."})

    def _static(self, path):
        relative = "index.html" if path == "/" else path.lstrip("/")
        file = (self.asset_root / relative).resolve()
        if not file.is_relative_to(self.asset_root) or not file.is_file():
            self._respond(404, {"error": "This dashboard asset does not exist."})
            return
        if file.stat().st_size > 5_000_000:
            self._respond(413, {"error": "The dashboard asset exceeds the size limit."})
            return
        media = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}.get(file.suffix)
        media = media or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self._respond(200, file.read_bytes(), media)

    def _reject_method(self):
        self._respond(405, {"error": "This dashboard accepts GET and HEAD requests only."})

    def do_POST(self):
        if self.actions is None:
            self._reject_method()
            return
        if not self._trusted_request(write=True):
            return
        if self.path not in {"/api/review", "/api/submit"}:
            self._respond(404, {"error": "This dashboard route does not exist."})
            return
        tokens = self.headers.get_all("X-FFM-CSRF", [])
        if len(tokens) != 1 or not secrets.compare_digest(tokens[0].encode("utf-8"), self.actions.csrf_token.encode("utf-8")):
            self._respond(403, {"error": "The dashboard session is invalid. Reload the page."})
            return
        content_types = self.headers.get_all("Content-Type", [])
        lengths = self.headers.get_all("Content-Length", [])
        if (len(content_types) != 1 or content_types[0].lower() not in {"application/json", "application/json; charset=utf-8"}
                or len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()
                or not 1 <= int(lengths[0]) <= 8192):
            self._respond(400, {"error": "Use one bounded JSON request body."})
            return
        try:
            def unique_object(pairs):
                result = dict(pairs)
                if len(result) != len(pairs):
                    raise ValueError
                return result
            self._request_body_consumed = True
            value = json.loads(self.rfile.read(int(lengths[0])).decode("utf-8"), object_pairs_hook=unique_object)
            keys = {"team_key", "proposal_id"} if self.path == "/api/review" else {"team_key", "proposal_id", "review_nonce", "confirmation"}
            if not isinstance(value, dict) or set(value) != keys:
                raise ValueError
            for key in keys - {"confirmation"}:
                if not isinstance(value[key], str) or not 1 <= len(value[key]) <= 200:
                    raise ValueError
            if self.path == "/api/review":
                result = self.actions.review(value["team_key"], value["proposal_id"])
            else:
                if value["confirmation"] is not True:
                    raise ValueError
                result = self.actions.submit(**value)
            self._respond(200, result)
        except ValueError:
            self._respond(400, {"error": "The approval request is invalid."})
        except Exception as exc:
            from .dashboard_actions import DashboardActionError
            if isinstance(exc, DashboardActionError):
                self._respond(409, {"error": exc.message})
            else:
                self._respond(503, {"error": "The request could not finish. Check the saved proposal before another action."})

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = _reject_method


def create_http_server(manifest=None, *, demo=False, host="127.0.0.1", port=8765, asset_root=None, portfolio=None,
                       enable_actions=False, credential_file=None, actions=None, readiness_report=None):
    """Bind a local dashboard. Call serve_forever to handle requests."""
    if host not in _HOSTS:
        raise ValueError("Bind the dashboard to localhost, 127.0.0.1, or ::1.")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Use a port from 0 through 65535.")
    assets = Path(asset_root) if asset_root is not None else Path(__file__).parent / "dashboard_static"
    assets = assets.resolve()
    if not (assets / "index.html").is_file() or not (assets / "index.html").resolve().is_relative_to(assets):
        raise ValueError("Dashboard assets are missing. Reinstall the package with its dashboard assets.")
    portfolio = portfolio if portfolio is not None else Portfolio(manifest, demo=demo)
    if type(enable_actions) is not bool:
        raise ValueError("Action permission must be a boolean.")
    if actions is not None and not enable_actions:
        raise ValueError("Enable actions before selecting an action service.")
    if enable_actions and actions is None:
        from .dashboard_actions import DashboardActions
        actions = DashboardActions(portfolio, credential_file=credential_file)
    source_mode = "demo" if demo else "manifest" if manifest else "configuration_required"
    handler = partial(DashboardHandler, portfolio=portfolio, asset_root=assets, source_mode=source_mode, actions=actions,
                      readiness_report=readiness_report)
    server_class = _IPv6Server if host == "::1" else DashboardServer
    return server_class((host, port), handler)


def main():
    parser = argparse.ArgumentParser(description="Display saved teams locally. Enable exact proposal approval with an explicit option.")
    parser.add_argument("--manifest", default=os.environ.get("FFM_PORTFOLIO_MANIFEST"), help="Explicit portfolio manifest. Defaults to FFM_PORTFOLIO_MANIFEST.")
    parser.add_argument("--demo", action="store_true", help="Display fictional portfolio data.")
    parser.add_argument("--host", choices=sorted(_HOSTS), default="127.0.0.1", help="Loopback interface only.")
    parser.add_argument("--port", type=int, default=8765, help="Local port. Default: 8765.")
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser.")
    parser.add_argument("--enable-actions", action="store_true", help="Permit exact reviewed HTTP season proposals. Default: read-only.")
    parser.add_argument("--credential-file", help="Protected ESPN session file for approved HTTP actions. Defaults to the existing environment setting.")
    parser.add_argument("--readiness-report", default=os.environ.get("FFM_READINESS_REPORT"), help="Optional private readiness report. Display only sanitized gate states.")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    try:
        server = create_http_server(args.manifest, demo=args.demo, host=args.host, port=args.port,
                                    enable_actions=args.enable_actions, credential_file=args.credential_file,
                                    readiness_report=args.readiness_report)
    except ValueError as exc:
        parser.error(str(exc))
    except OSError:
        parser.error("The loopback address or port is unavailable. Select another local port.")
    address = f"[{args.host}]" if args.host == "::1" else args.host
    url = f"http://{address}:{server.server_port}/"
    label = "Dashboard with exact proposal approval" if args.enable_actions else "Read-only dashboard"
    print(f"{label}: {url}", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
