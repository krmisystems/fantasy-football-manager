"""Collect private GitHub discovery measurements through four read-only requests."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

from filelock import FileLock


API_VERSION = '2026-03-10'
ENDPOINTS = {'views': '/traffic/views?per=day', 'clones': '/traffic/clones?per=day',
             'referrers': '/traffic/popular/referrers', 'stars': ''}
MAX_RESPONSE_BYTES = 2_000_000


class MetricsError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def repository(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}', value):
        raise MetricsError('Use one GitHub OWNER/REPO identifier.')
    if value.split('/')[1] in {'.', '..'}:
        raise MetricsError('The repository name is invalid.')
    return value.lower()


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as exc:
        raise MetricsError('A measurement timestamp must include a UTC offset.') from exc


def count(value):
    if type(value) is not int or value < 0:
        raise MetricsError('invalid_response')
    return value


def normalize(endpoint, value, repo, observed_at):
    if endpoint == 'stars':
        if not isinstance(value, dict) or value.get('full_name', '').lower() != repo:
            raise MetricsError('repository_mismatch')
        return {'count': count(value.get('stargazers_count'))}
    if endpoint == 'referrers':
        if not isinstance(value, list) or len(value) > 10:
            raise MetricsError('invalid_response')
        rows, names = [], set()
        for item in value:
            name = item.get('referrer') if isinstance(item, dict) else None
            if not isinstance(name, str) or not name or len(name) > 500 or any(ord(c) < 32 for c in name) or name in names:
                raise MetricsError('invalid_response')
            names.add(name)
            total, unique = count(item.get('count')), count(item.get('uniques'))
            if unique > total:
                raise MetricsError('invalid_response')
            rows.append({'referrer': name, 'count': total, 'uniques': unique})
        return {'window_days': 14, 'rows': sorted(rows, key=lambda r: (-r['count'], r['referrer']))}
    if endpoint not in {'views', 'clones'} or not isinstance(value, dict) or not isinstance(value.get(endpoint), list):
        raise MetricsError('invalid_response')
    total, unique = count(value.get('count')), count(value.get('uniques'))
    if unique > total:
        raise MetricsError('invalid_response')
    rows, days = [], set()
    today = timestamp(observed_at).date()
    for item in value[endpoint]:
        if not isinstance(item, dict):
            raise MetricsError('invalid_response')
        point = timestamp(item.get('timestamp'))
        day = point.date()
        if point.hour or point.minute or point.second or point.microsecond or day > today or day < today - timedelta(days=14) or day in days:
            raise MetricsError('invalid_response')
        days.add(day)
        row_count, row_unique = count(item.get('count')), count(item.get('uniques'))
        if row_unique > row_count:
            raise MetricsError('invalid_response')
        rows.append({'date': day.isoformat(), 'count': row_count, 'uniques': row_unique})
    return {'window_days': 14, 'count': total, 'uniques': unique, 'days': sorted(rows, key=lambda r: r['date']),
            'warnings': [] if sum(r['count'] for r in rows) == total else ['daily_count_sum_differs_from_window']}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MetricsError('redirect_blocked')


class GitHubClient:
    def __init__(self, repo, token, *, opener=None):
        self.repo = repository(repo)
        if not isinstance(token, str) or not token or len(token) > 4096 or any(c.isspace() for c in token):
            raise MetricsError('Supply a token through GH_TOKEN or --token-stdin.')
        self.token = token
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect())

    def fetch(self, endpoint):
        if endpoint not in ENDPOINTS:
            raise MetricsError('unsupported_endpoint')
        url = 'https://api.github.com/repos/' + self.repo + ENDPOINTS[endpoint]
        request = Request(url, method='GET', headers={
            'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + self.token,
            'X-GitHub-Api-Version': API_VERSION, 'User-Agent': 'fantasy-football-discovery-metrics'})
        with self.opener.open(request, timeout=15) as response:
            if response.geturl() != url:
                raise MetricsError('redirect_blocked')
            if response.status != 200:
                raise MetricsError('unexpected_http_status')
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise MetricsError('response_too_large')
            return json.loads(raw)


def collect(repo, token, *, baseline=False, client=None, observed_at=None):
    repo = repository(repo)
    client = client or GitHubClient(repo, token)
    at = timestamp(observed_at).isoformat() if observed_at else datetime.now(timezone.utc).isoformat()
    def one(endpoint):
        try:
            data = normalize(endpoint, client.fetch(endpoint), repo, at)
            return {'status': 'ok', 'data': data, 'error_code': None, 'http_status': 200}
        except HTTPError as exc:
            code = 'redirect_blocked' if 300 <= exc.code < 400 else 'http_error'
            return {'status': 'error', 'data': None, 'error_code': code, 'http_status': exc.code}
        except (URLError, TimeoutError, OSError, HTTPException):
            return {'status': 'error', 'data': None, 'error_code': 'transport_error', 'http_status': None}
        except (MetricsError, ValueError, TypeError, KeyError, AttributeError) as exc:
            allowed = {'redirect_blocked', 'invalid_response', 'repository_mismatch', 'response_too_large', 'unexpected_http_status'}
            code = str(exc) if str(exc) in allowed else 'invalid_response'
            return {'status': 'error', 'data': None, 'error_code': code, 'http_status': None}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(zip(ENDPOINTS, pool.map(one, ENDPOINTS)))
    report = {'schema_version': 1, 'repository': repo, 'observed_at': at, 'baseline': bool(baseline),
              'api_version': API_VERSION, 'results': results,
              'status': 'complete' if all(r['status'] == 'ok' for r in results.values()) else 'partial'}
    report['report_id'] = digest(report)
    return report


def empty_state(repo):
    return {'schema_version': 1, 'repository': repository(repo), 'reports': {}, 'daily': {'views': {}, 'clones': {}},
            'windows': {'views': [], 'clones': [], 'referrers': []}, 'stars': [], 'baseline_report_id': None}


def merge_report(state, report):
    if report.get('schema_version') != 1 or report.get('repository') != state['repository']:
        raise MetricsError('The report belongs to a different repository or schema.')
    if report.get('report_id') != digest({k: v for k, v in report.items() if k != 'report_id'}):
        raise MetricsError('The report checksum does not match its contents.')
    rid, at = report['report_id'], report['observed_at']
    timestamp(at)
    if rid in state['reports']:
        return deepcopy(state)
    if report.get('baseline') and state['baseline_report_id'] is not None:
        raise MetricsError('A baseline is already recorded.')
    if any(r['observed_at'] == at for r in state['reports'].values()):
        raise MetricsError('Different reports have the same observation timestamp.')
    merged = deepcopy(state)
    merged['reports'][rid] = deepcopy(report)
    if report.get('baseline'):
        merged['baseline_report_id'] = rid
    for endpoint in ENDPOINTS:
        result = report['results'][endpoint]
        if result['status'] != 'ok':
            if result.get('data') is not None:
                raise MetricsError('An unavailable metric cannot contain a numeric result.')
            continue
        data = result['data']
        if endpoint in {'views', 'clones'}:
            for day in data['days']:
                old = merged['daily'][endpoint].get(day['date'])
                if old is None or timestamp(old['observed_at']) < timestamp(at):
                    merged['daily'][endpoint][day['date']] = {**day, 'observed_at': at, 'report_id': rid}
            merged['windows'][endpoint].append({'observed_at': at, 'report_id': rid,
                                                **{key: data[key] for key in ('window_days', 'count', 'uniques', 'warnings')}})
        elif endpoint == 'referrers':
            merged['windows']['referrers'].append({'observed_at': at, 'report_id': rid, **data})
        else:
            merged['stars'].append({'observed_at': at, 'report_id': rid, 'count': data['count']})
    for rows in [*merged['windows'].values(), merged['stars']]:
        rows.sort(key=lambda row: timestamp(row['observed_at']))
    return merged


def summarize(state):
    if not state['reports']:
        return {'repository': state['repository'], 'status': 'missing', 'reason': 'no_reports'}
    latest = max(state['reports'].values(), key=lambda r: timestamp(r['observed_at']))
    end = timestamp(latest['observed_at']).date() - timedelta(days=1)
    days = [(end - timedelta(days=n)).isoformat() for n in reversed(range(7))]
    result = {'repository': state['repository'], 'as_of': latest['observed_at'], 'status': latest['status'],
              'report_count': len(state['reports']), 'previous_7_complete_utc_days': {'start': days[0], 'end': days[-1]},
              'interpretation': 'Repository discovery measurements do not establish installations or active users.'}
    for endpoint in ('views', 'clones'):
        records = state['daily'][endpoint]
        missing = [day for day in days if day not in records]
        observed = sum(records[day]['count'] for day in days if day in records)
        result[endpoint] = {'latest_fetch': {k: latest['results'][endpoint][k] for k in ('status', 'error_code', 'http_status')},
                            'latest_successful_14_day_window': state['windows'][endpoint][-1] if state['windows'][endpoint] else None,
                            'previous_7_days': {'count': observed if not missing else None, 'observed_count': observed if len(missing) < 7 else None,
                                                'observed_days': 7 - len(missing), 'missing_days': missing,
                                                'uniques': None, 'uniques_status': 'not_additive_across_days'}}
    result['referrers'] = {'latest_fetch': {k: latest['results']['referrers'][k] for k in ('status', 'error_code', 'http_status')},
                           'latest_successful_14_day_snapshot': state['windows']['referrers'][-1] if state['windows']['referrers'] else None,
                           'aggregation': 'Each snapshot is a separate overlapping window. Do not sum snapshots.'}
    stars = state['stars']
    baseline = next((r for r in stars if r['report_id'] == state['baseline_report_id']), None) if state['baseline_report_id'] else (stars[0] if stars else None)
    result['stars'] = {'latest_fetch': {k: latest['results']['stars'][k] for k in ('status', 'error_code', 'http_status')},
                       'latest_successful_snapshot': stars[-1] if stars else None, 'baseline': baseline,
                       'baseline_source': 'explicit_baseline_report' if state['baseline_report_id'] else 'first_successful_snapshot',
                       'net_change': stars[-1]['count'] - baseline['count'] if stars and baseline else None,
                       'interpretation': 'Net star-count change can be negative. It is not an active-user count.'}
    return result


def atomic_json(path, value):
    path = Path(path)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise MetricsError('Output paths cannot contain symlinks.')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as stream:
            stream.write(canonical(value) + '\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_reports(directory, repo):
    directory = Path(directory)
    reports_directory = directory / 'reports'
    if any(path.is_symlink() for path in (reports_directory, directory, *directory.parents)):
        raise MetricsError('Report paths cannot contain symlinks.')
    state = empty_state(repo)
    reports = []
    for path in reports_directory.glob('*.json'):
        if path.is_symlink():
            raise MetricsError('Report files cannot be symlinks.')
        report = json.loads(path.read_text(encoding='utf-8'))
        if path.stem != report.get('report_id'):
            raise MetricsError('The saved report name does not match its identifier.')
        reports.append(report)
    for report in sorted(reports, key=lambda r: timestamp(r['observed_at'])):
        state = merge_report(state, report)
    return state


def save_report(directory, report):
    directory = Path(directory)
    if any(path.is_symlink() for path in (directory, *directory.parents)):
        raise MetricsError('Output paths cannot contain symlinks.')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (directory / '.metrics.lock').is_symlink():
        raise MetricsError('The metrics lock cannot be a symlink.')
    with FileLock(directory / '.metrics.lock', timeout=15):
        state = merge_report(load_reports(directory, report['repository']), report)
        # Save evidence first. The next run rebuilds derived state after a crash.
        atomic_json(directory / 'reports' / (report['report_id'] + '.json'), report)
        atomic_json(directory / 'state.json', state)
        summary = summarize(state)
        atomic_json(directory / 'summary.json', summary)
        return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('collect', 'summary'):
        child = sub.add_parser(command)
        child.add_argument('--repo', required=True)
        child.add_argument('--data-dir', required=True)
        if command == 'collect':
            child.add_argument('--token-stdin', action='store_true')
            child.add_argument('--baseline', action='store_true')
    args = parser.parse_args(argv)
    try:
        repo = repository(args.repo)
        if args.command == 'summary':
            result = summarize(load_reports(args.data_dir, repo))
        else:
            token = sys.stdin.readline(4098).strip() if args.token_stdin else os.environ.get('GH_TOKEN', '').strip()
            result = save_report(args.data_dir, collect(repo, token, baseline=args.baseline))
        print(canonical(result))
        return 0 if result['status'] == 'complete' else 2
    except (MetricsError, OSError, ValueError, KeyError) as exc:
        # Raw transport errors can include request URLs or credential text.
        print(canonical({'status': 'error', 'error_code': 'collector_failed', 'error_type': type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
