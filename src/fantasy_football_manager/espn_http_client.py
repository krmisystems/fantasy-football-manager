"""Restricted ESPN HTTP transport with no browser and no automatic POST retry."""

from __future__ import annotations

import asyncio
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .espn_http_auth import read_credentials


READ_ORIGIN = "https://lm-api-reads.fantasy.espn.com"
WRITE_ORIGIN = "https://lm-api-writes.fantasy.espn.com"
MAX_RESPONSE_BYTES = 24 * 1024 * 1024


class ESPNHTTPError(ValueError):
    def __init__(self, message, *, status=None, submission_uncertain=False):
        super().__init__(message)
        self.status = status
        self.submission_uncertain = submission_uncertain


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def league_url(league_id, season, *, write=False):
    from .espn_data import _scope
    league, year = _scope(league_id, season)
    origin = WRITE_ORIGIN if write else READ_ORIGIN
    return f"{origin}/apis/v3/games/ffl/seasons/{year}/segments/0/leagues/{league}"


class ESPNHTTPClient:
    def __init__(self, credential_file, *, opener=None, timeout=20):
        self.credential_file = credential_file
        self.opener = opener or build_opener(ProxyHandler({}), _NoRedirect())
        self.timeout = timeout

    def credentials(self):
        return read_credentials(self.credential_file)

    def _request(self, url, *, payload=None, headers=None):
        parsed = urlsplit(url)
        allowed = {urlsplit(READ_ORIGIN).hostname, urlsplit(WRITE_ORIGIN).hostname}
        if (parsed.scheme != "https" or parsed.hostname not in allowed or parsed.port is not None
                or parsed.username or parsed.password or parsed.fragment
                or not re.fullmatch(r"/apis/v3/games/ffl/seasons/20\d{2}(?:/segments/0/leagues/[1-9]\d*(?:/transactions/)?)?", parsed.path)):
            raise ValueError("The request must use an allowed ESPN football API endpoint.")
        if payload is not None and (parsed.hostname != urlsplit(WRITE_ORIGIN).hostname
                                    or not parsed.path.endswith("/transactions/") or parsed.query):
            raise ValueError("ESPN writes require the exact league transaction endpoint.")
        supplied = headers or {}
        if set(supplied) - {"x-fantasy-filter"}:
            raise ValueError("Only the ESPN player or transaction filter header can be supplied.")
        cookies = self.credentials()
        request_headers = {"Cookie": "; ".join(f"{key}={value}" for key, value in cookies.items()),
                           "Accept": "application/json", "User-Agent": "FantasyFootballManager",
                           "X-Fantasy-Source": "kona", "X-Fantasy-Platform": "espn-fantasy-web",
                           "Cache-Control": "no-cache", **supplied}
        body = None
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            body = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
        request = Request(url, data=body, headers=request_headers, method="GET" if body is None else "POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.url != url:
                    raise ESPNHTTPError("ESPN returned an unexpected response URL.", submission_uncertain=body is not None)
                data = response.read(MAX_RESPONSE_BYTES + 1)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ESPNHTTPError("The ESPN response exceeds the size limit.", submission_uncertain=body is not None)
                result = json.loads(data)
                if not isinstance(result, (dict, list)):
                    raise ValueError()
                return result
        except HTTPError as exc:
            reason = "ESPN authentication is required." if exc.code in {401, 403} else f"ESPN returned HTTP {exc.code}."
            raise ESPNHTTPError(reason, status=exc.code, submission_uncertain=body is not None) from None
        except ESPNHTTPError:
            raise
        except (URLError, OSError, ValueError, UnicodeError, TimeoutError):
            raise ESPNHTTPError("The ESPN request did not return a verified JSON response.",
                                submission_uncertain=body is not None) from None

    async def request(self, url, *, payload=None, headers=None):
        return await asyncio.to_thread(self._request, url, payload=payload, headers=headers)
