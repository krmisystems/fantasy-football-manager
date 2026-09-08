"""Discovery metrics tests use fictional API responses and no network requests."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from http.client import BadStatusLine, IncompleteRead
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('github_metrics', ROOT / 'scripts/collect_github_metrics.py')
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)
REPO = 'fictional-owner/fictional-project'
AT = '2026-08-20T08:00:00+00:00'


def traffic(at=AT, value=2):
    end = metrics.timestamp(at).date()
    rows = [{'timestamp': (end - timedelta(days=n)).isoformat() + 'T00:00:00Z',
             'count': value, 'uniques': min(1, value)} for n in reversed(range(14))]
    return {'count': value * 14, 'uniques': min(value * 14, 3), 'views': rows, 'clones': deepcopy(rows)}


class FakeClient:
    def __init__(self, at=AT, failures=None, stars=12, value=2):
        self.at, self.failures, self.stars, self.value = at, failures or {}, stars, value
        self.calls = []

    def fetch(self, endpoint):
        self.calls.append(endpoint)
        if endpoint in self.failures:
            raise self.failures[endpoint]
        if endpoint == 'stars':
            return {'full_name': REPO, 'stargazers_count': self.stars, 'private_field': 'never export'}
        if endpoint == 'referrers':
            return [{'referrer': 'search.example', 'count': 4, 'uniques': 3}]
        return traffic(self.at, self.value)


def report(at=AT, **kwargs):
    return metrics.collect(REPO, None, client=FakeClient(at, **kwargs), observed_at=at)


def test_four_metrics_collected_without_raw_repository_or_secret_fields():
    client = FakeClient()
    value = metrics.collect(REPO, None, client=client, observed_at=AT, baseline=True)
    assert set(client.calls) == set(metrics.ENDPOINTS)
    assert value['status'] == 'complete' and value['baseline']
    assert value['results']['stars']['data'] == {'count': 12}
    assert 'private_field' not in metrics.canonical(value)


def test_partial_failure_is_missing_and_never_zero():
    secret = 'fictional-private-token'
    fail = {'views': HTTPError('https://api.github.com/', 403, secret, {}, None),
            'referrers': OSError(secret)}
    value = report(failures=fail)
    assert value['status'] == 'partial'
    assert value['results']['views'] == {'status': 'error', 'data': None, 'error_code': 'http_error', 'http_status': 403}
    summary = metrics.summarize(metrics.merge_report(metrics.empty_state(REPO), value))
    assert summary['views']['previous_7_days']['count'] is None
    assert summary['views']['previous_7_days']['observed_count'] is None
    assert summary['referrers']['latest_successful_14_day_snapshot'] is None
    assert summary['stars']['latest_successful_snapshot']['count'] == 12
    assert secret not in metrics.canonical(value) + metrics.canonical(summary)


@pytest.mark.parametrize('failure', [IncompleteRead(b'fictional-private-response', 30),
                                    BadStatusLine('fictional-private-response')])
def test_truncated_or_invalid_http_response_preserves_other_metrics(failure):
    value = report(failures={'views': failure})
    assert value['status'] == 'partial'
    assert value['results']['views'] == {'status': 'error', 'data': None, 'error_code': 'transport_error', 'http_status': None}
    assert all(value['results'][endpoint]['status'] == 'ok' for endpoint in ('clones', 'referrers', 'stars'))
    assert 'fictional-private-response' not in metrics.canonical(value)


def test_repeated_report_is_idempotent_and_does_not_mutate_state():
    value = report()
    state = metrics.merge_report(metrics.empty_state(REPO), value)
    original = deepcopy(state)
    assert metrics.merge_report(state, value) == state
    assert state == original
    assert len(state['stars']) == len(state['windows']['referrers']) == 1


def test_overlapping_days_replace_latest_values_without_summing_uniques_or_referrers():
    first = report(value=2)
    second_at = '2026-08-27T08:00:00+00:00'
    second = report(second_at, value=5, stars=15)
    state = metrics.merge_report(metrics.merge_report(metrics.empty_state(REPO), first), second)
    assert len(state['daily']['views']) == 21
    assert state['daily']['views']['2026-08-19']['count'] == 5
    assert state['daily']['views']['2026-08-19']['uniques'] == 1
    assert len(state['windows']['referrers']) == 2
    summary = metrics.summarize(state)
    assert summary['views']['previous_7_days']['count'] == 35
    assert summary['views']['previous_7_days']['uniques'] is None
    assert summary['views']['latest_successful_14_day_window']['uniques'] == 3
    assert summary['referrers']['latest_successful_14_day_snapshot']['rows'][0]['count'] == 4
    assert summary['stars']['net_change'] == 3
    # An older report replay cannot replace the newer value.
    reverse = metrics.merge_report(metrics.merge_report(metrics.empty_state(REPO), second), first)
    assert reverse['daily'] == state['daily']


def test_missed_collection_exposes_date_gaps_and_keeps_stale_window_explicit():
    first = report()
    later = report('2026-09-20T08:00:00+00:00', failures={'views': TimeoutError()})
    state = metrics.merge_report(metrics.merge_report(metrics.empty_state(REPO), first), later)
    summary = metrics.summarize(state)
    assert summary['views']['latest_fetch']['status'] == 'error'
    assert summary['views']['previous_7_days']['count'] is None
    assert len(summary['views']['previous_7_days']['missing_days']) == 7
    assert summary['views']['latest_successful_14_day_window']['observed_at'] == AT


def test_reported_zero_is_preserved_and_star_delta_can_be_negative():
    state = metrics.merge_report(metrics.empty_state(REPO), report(stars=12))
    state = metrics.merge_report(state, report('2026-08-21T08:00:00+00:00', value=0, stars=10))
    summary = metrics.summarize(state)
    assert summary['views']['previous_7_days']['count'] == 0
    assert summary['stars']['net_change'] == -2


def test_explicit_missing_star_baseline_is_not_replaced_by_a_later_value():
    first = metrics.collect(REPO, None, baseline=True, observed_at=AT,
                            client=FakeClient(failures={'stars': TimeoutError()}))
    state = metrics.merge_report(metrics.empty_state(REPO), first)
    state = metrics.merge_report(state, report('2026-08-21T08:00:00+00:00'))
    assert metrics.summarize(state)['stars']['net_change'] is None
    assert metrics.summarize(state)['stars']['baseline'] is None


@pytest.mark.parametrize('bad', ['other.example/path/repo', 'owner/../repo', 'owner/repo?token=x',
                                  'owner/repo#fragment', 'https://api.github.com/repos/owner/repo',
                                  '../repo', 'owner/..', 'owner/repo%2fsecret'])
def test_repository_argument_cannot_change_the_request_host_or_path(bad):
    with pytest.raises(metrics.MetricsError):
        metrics.GitHubClient(bad, 'fixture-token')


class Response:
    status = 200

    def __init__(self, url, payload):
        self.url, self.payload = url, payload

    def geturl(self):
        return self.url

    def read(self, limit):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_transport_uses_only_fixed_get_endpoints_and_does_not_follow_redirects():
    requests = []
    def open_request(request, timeout):
        requests.append(request)
        return Response(request.full_url, {'full_name': REPO, 'stargazers_count': 12})
    client = metrics.GitHubClient(REPO, 'fixture-token', opener=SimpleNamespace(open=open_request))
    assert client.fetch('stars')['stargazers_count'] == 12
    assert requests[0].method == 'GET'
    assert requests[0].full_url == 'https://api.github.com/repos/' + REPO
    with pytest.raises(metrics.MetricsError, match='unsupported_endpoint'):
        client.fetch('https://other.example/')
    handler = metrics.NoRedirect()
    with pytest.raises(metrics.MetricsError, match='redirect_blocked'):
        handler.redirect_request(Request(requests[0].full_url), None, 302, 'redirect', {}, 'https://other.example/')


def test_unexpected_response_origin_is_rejected_before_payload_read():
    client = metrics.GitHubClient(REPO, 'fixture-token', opener=SimpleNamespace(
        open=lambda request, timeout: Response('https://other.example/', {'secret': 'never-read'})))
    with pytest.raises(metrics.MetricsError, match='redirect_blocked'):
        client.fetch('stars')


@pytest.mark.parametrize('mutation', [lambda value: value.update(count=None),
                                    lambda value: value.update(uniques=-1),
                                    lambda value: value['views'].append(deepcopy(value['views'][0])),
                                    lambda value: value['views'][0].update(timestamp='2026-08-07T03:00:00Z')])
def test_missing_invalid_or_duplicate_daily_values_are_rejected(mutation):
    value = traffic(); mutation(value)
    with pytest.raises(metrics.MetricsError):
        metrics.normalize('views', value, REPO, AT)


def test_atomic_reports_can_rebuild_after_derived_state_is_lost(tmp_path):
    value = report()
    first = metrics.save_report(tmp_path, value)
    (tmp_path / 'state.json').unlink()
    (tmp_path / 'summary.json').write_text('interrupted derived output')
    assert metrics.save_report(tmp_path, value) == first
    assert len(list((tmp_path / 'reports').glob('*.json'))) == 1
    assert json.loads((tmp_path / 'summary.json').read_text()) == first
    assert not list(tmp_path.rglob('*.tmp'))


def test_cross_repository_or_changed_saved_report_is_rejected(tmp_path):
    value = report(); metrics.save_report(tmp_path, value)
    with pytest.raises(metrics.MetricsError, match='different repository'):
        metrics.load_reports(tmp_path, 'other-owner/other-project')
    path = next((tmp_path / 'reports').glob('*.json'))
    changed = json.loads(path.read_text()); changed['results']['stars']['data']['count'] = 500
    path.write_text(json.dumps(changed))
    with pytest.raises(metrics.MetricsError, match='checksum'):
        metrics.load_reports(tmp_path, REPO)


def test_cli_reads_token_from_stdin_without_printing_it(tmp_path, monkeypatch, capsys):
    import io
    received = []
    saved = report()
    def fake_collect(repo, token, baseline=False):
        received.append(token)
        return saved
    monkeypatch.setattr(metrics, 'collect', fake_collect)
    monkeypatch.setattr(metrics.sys, 'stdin', io.StringIO('fixture-private-token\n'))
    assert metrics.main(['collect', '--repo', REPO, '--data-dir', str(tmp_path), '--token-stdin']) == 0
    output = capsys.readouterr()
    assert received == ['fixture-private-token']
    assert 'fixture-private-token' not in output.out + output.err
    assert metrics.main(['summary', '--repo', REPO, '--data-dir', str(tmp_path)]) == 0


def test_interrupted_state_replace_preserves_evidence_for_next_run(tmp_path, monkeypatch):
    first = report(); metrics.save_report(tmp_path, first)
    second = report('2026-08-21T08:00:00+00:00', stars=14)
    original = metrics.os.replace
    def interrupt(source, destination):
        if Path(destination).name == 'state.json':
            raise OSError('Fictional interruption')
        return original(source, destination)
    monkeypatch.setattr(metrics.os, 'replace', interrupt)
    with pytest.raises(OSError):
        metrics.save_report(tmp_path, second)
    assert len(json.loads((tmp_path / 'state.json').read_text())['reports']) == 1
    assert len(list((tmp_path / 'reports').glob('*.json'))) == 2
    monkeypatch.setattr(metrics.os, 'replace', original)
    summary = metrics.save_report(tmp_path, second)
    assert summary['report_count'] == 2 and summary['stars']['net_change'] == 2
    assert not list(tmp_path.rglob('*.tmp'))


def test_symlinked_report_directory_is_not_read_or_written(tmp_path):
    elsewhere = tmp_path / 'outside'; elsewhere.mkdir()
    target = tmp_path / 'metrics'; target.mkdir()
    try:
        (target / 'reports').symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip('This platform does not permit creating the isolated test symlink.')
    with pytest.raises(metrics.MetricsError, match='symlink'):
        metrics.load_reports(target, REPO)
    with pytest.raises(metrics.MetricsError, match='symlink'):
        metrics.save_report(target, report())
    assert not list(elsewhere.iterdir())
