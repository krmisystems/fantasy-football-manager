"""Test HTTP boundaries with a fake opener and fictional credentials."""

import json
from urllib.error import HTTPError, URLError

import pytest

from fantasy_football_manager import espn_http_client as transport


READ = transport.league_url(123, 2026) + "?view=mRoster"
WRITE = transport.league_url(123, 2026, write=True) + "/transactions/"
COOKIES = {"SWID": "fictional-member", "espn_s2": "fictional-session-canary"}


class Response:
    def __init__(self, url, body=b'{"status":"EXECUTED"}'):
        self.url, self.body = url, body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit):
        return self.body[:limit]


class Opener:
    def __init__(self, response):
        self.response, self.calls = response, []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def client(monkeypatch, response):
    monkeypatch.setattr(transport, "read_credentials", lambda _: dict(COOKIES))
    opener = Opener(response)
    return transport.ESPNHTTPClient("fictional.json", opener=opener, timeout=7), opener


def test_read_and_write_use_exact_urls_methods_and_restricted_credentials(monkeypatch):
    api, opener = client(monkeypatch, Response(READ, b'{"teams":[]}'))
    assert api._request(READ, headers={"x-fantasy-filter": '{"players":{"limit":1}}'}) == {"teams": []}
    request, timeout = opener.calls[0]
    assert request.full_url == READ and request.method == "GET" and request.data is None and timeout == 7
    assert request.get_header("Cookie") == "SWID=fictional-member; espn_s2=fictional-session-canary"
    assert request.get_header("X-fantasy-filter") == '{"players":{"limit":1}}'
    opener.response = Response(WRITE)
    payload = {"isLeagueManager": False, "teamId": 1, "type": "ROSTER", "items": []}
    assert api._request(WRITE, payload=payload)["status"] == "EXECUTED"
    request, _ = opener.calls[1]
    assert request.method == "POST" and json.loads(request.data) == payload
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("X-fantasy-source") == "kona"
    assert request.get_header("X-fantasy-platform") == "espn-fantasy-web"


@pytest.mark.parametrize("url", ["http://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026",
                                 READ.replace("fantasy.espn.com", "fantasy.espn.com.invalid"),
                                 READ.replace("https://", "https://user:password@"),
                                 READ.replace(".com/", ".com:443/"), READ + "#fragment",
                                 READ.replace("/ffl/", "/fba/"),
                                 READ.replace("/leagues/123", "/leagues/123/teams/1"),
                                 READ.replace("/leagues/123", "/leagues/0")])
def test_disallowed_destinations_fail_before_credential_loading(monkeypatch, url):
    def forbidden(_):
        pytest.fail("A disallowed request loaded credentials.")
    monkeypatch.setattr(transport, "read_credentials", forbidden)
    opener = Opener(Response(url))
    api = transport.ESPNHTTPClient("fictional.json", opener=opener)
    with pytest.raises(ValueError):
        api._request(url)
    assert opener.calls == []


@pytest.mark.parametrize("url", [READ, WRITE + "?extra=1", WRITE.removesuffix("transactions/")])
def test_writes_require_the_exact_transaction_endpoint(monkeypatch, url):
    api, opener = client(monkeypatch, Response(url))
    with pytest.raises(ValueError):
        api._request(url, payload={})
    assert opener.calls == []


@pytest.mark.parametrize("headers", [{"Cookie": "other"}, {"Authorization": "other"}, {"Host": "elsewhere.invalid"}])
def test_callers_cannot_replace_security_headers(monkeypatch, headers):
    api, opener = client(monkeypatch, Response(READ))
    with pytest.raises(ValueError):
        api._request(READ, headers=headers)
    assert opener.calls == []


@pytest.mark.parametrize("problem", ["redirect", "invalid_json", "scalar_json", "oversized", "timeout", "network", "http401", "http503"])
@pytest.mark.parametrize("write", [False, True])
def test_ambiguous_responses_never_retry_and_do_not_expose_secrets(monkeypatch, problem, write):
    url = WRITE if write else READ
    response = Response(url)
    if problem == "redirect":
        response.url = "https://elsewhere.invalid/fictional-session-canary"
    elif problem == "invalid_json":
        response.body = b"fictional-session-canary"
    elif problem == "scalar_json":
        response.body = b'"fictional-session-canary"'
    elif problem == "oversized":
        monkeypatch.setattr(transport, "MAX_RESPONSE_BYTES", 4)
        response.body = b'{"oversized":true}'
    elif problem == "timeout":
        response = TimeoutError("fictional-session-canary")
    elif problem == "network":
        response = URLError("fictional-session-canary")
    else:
        response = HTTPError(url, int(problem[4:]), "fictional-session-canary", {}, None)
    api, opener = client(monkeypatch, response)
    with pytest.raises(transport.ESPNHTTPError) as error:
        api._request(url, payload={} if write else None)
    assert len(opener.calls) == 1
    assert error.value.submission_uncertain is write
    assert "fictional-session-canary" not in str(error.value)
    if problem.startswith("http"):
        assert error.value.status == int(problem[4:])


def test_default_opener_disables_environment_proxies_and_redirects(monkeypatch):
    captured = []
    monkeypatch.setattr(transport, "build_opener", lambda *handlers: captured.extend(handlers) or object())
    transport.ESPNHTTPClient("fictional.json")
    assert next(handler for handler in captured if isinstance(handler, transport.ProxyHandler)).proxies == {}
    redirect = next(handler for handler in captured if isinstance(handler, transport._NoRedirect))
    assert redirect.redirect_request(None, None, 302, "redirect", {}, "https://elsewhere.invalid") is None


@pytest.mark.asyncio
async def test_async_wrapper_uses_the_same_single_request_contract(monkeypatch):
    api, opener = client(monkeypatch, Response(READ, b'{"teams":[]}'))
    assert await api.request(READ) == {"teams": []}
    assert len(opener.calls) == 1
