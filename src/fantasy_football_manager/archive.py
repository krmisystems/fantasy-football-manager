"""Export sanitized evidence and import it into an immutable archive.

Input manifests can contain private database paths. Exported bundles cannot.
The archive records observed results separately from executor attribution.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlencode

from . import __version__
from .models import LeagueSnapshot, ManagerConfig


SCHEMA_VERSION = 1
KINDS = {"snapshot", "draft_pick", "proposal", "audit_event", "runtime_observation", "failure", "recommendation", "outbox_event", "config"}
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
PRIVATE_TEXT = re.compile(
    r"[A-Za-z]:[\\/]|(?:^|\s)/(?:home|Users|root|data|archive|var|tmp|etc)/|"
    r"https?://|\b(?:gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{24,}|sk-[A-Za-z0-9]{24,})\b|"
    r"-----BEGIN .*PRIVATE KEY-----", re.I)
BLOCKED_KEYS = {"members", "owners", "memberid", "member_id", "swid", "espn_s2", "cookies", "cookie",
                "headers", "authorization", "password", "access_token", "refresh_token", "token", "secret",
                "page_url", "url", "href", "cdp_url", "browser_data_dir", "data_dir", "path", "profile",
                "command", "traceback", "stack", "error", "last_error", "notes", "team_name", "display_name"}
# Unknown fields are omitted. Dynamic player-ID and lineup maps use separate rules.
SAFE_KEYS = set("""schema_version context source provider synthetic complete observed_at projections_observed_at
locks_verified locks_scope browser current_pick autopick_enabled draft_complete league_id team_id season phase week
revision config_revision snapshot config calculation action payload decision result status scope executor mode
requires_confirmation should_click authorized_at created_at proposal_id player_id player_name outgoing_player_id
outgoing_player_name source_slot destination_slot actual_pick actual_lineup pick_no slot id position
eligible_positions team projection weekly_projection weekly_floor weekly_ceiling adp availability locked bye
rules teams players picks roster_ids reserve_ids lineup budget balance spent_week spent_season pending_amount
pending_moves roster_moves_week rounds snake starters caps flex_eligible bench ir automation preset paused actions
limits strategy protected_ids drop_mode allowed_drop_ids max_weekly_moves faab_per_claim faab_per_week faab_per_season
faab_reserve min_lineup_improvement max_draft_age_seconds max_season_age_seconds max_projection_age_seconds
max_adp_reach batch_trials draft waiver seed trials requested_trials analysis_fingerprint config_fingerprint
recommendations rejected_candidates score objective projected_points expected_improvement improvement value
rank probability mean median min max stdev floor ceiling replacement_value survives_to_next_pick
next_pick my_next_pick simulations elapsed_seconds duration_seconds clicked uncertain retry_allowed
event at recorded_at attempt_id click_returned outcome failure_code exception_type stage terminal
confirmed pending count samples aggregate fingerprint algorithm version package_version code_revision
synthetic_demo_only evidence_type reason_code failure_class estimated selected_player_id selected_lineup
policy_decision proposed actual target player_ids recommendation worker_launch_id launch_id
application_version input_fingerprint kind completed_trials accepted disposition work_scope selection_causality
submission returned error_category confirmation_scope worker previous_status classification_basis
acceptance_scope
add_player_id drop_player_id idempotent_replay model_version completed following_pick available_count
snapshot_age_seconds source_observed_at snapshot_complete stale projection_age_seconds automation_paused action_mode
score_se score_sum score_sq_sum simulation_count availability_count survival_count trial_count availability_at_pick
survival_next_pick adp_reach estimate_quality current_points current_projected_points objective_value
weekly_upside_gain maximum_faab_bid baseline_projected_points bid_win_probability platform_claim_status_verified
championship_odds basis effective_limits candidates rankings blocked_candidates missing_projections runtime top roster
""".split())
DYNAMIC_MAPS = {"lineup", "actual_lineup", "starters", "caps", "actions"}


class ArchiveError(ValueError):
    """The evidence cannot be safely or consistently archived."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        if (parsed - datetime.now(timezone.utc)).total_seconds() > 30:
            raise ValueError
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError) as exc:
        raise ArchiveError("Evidence timestamps require a valid UTC offset and cannot be in the future.") from exc


def _identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or PRIVATE_TEXT.search(value):
        raise ArchiveError("Logical evidence identifiers must use letters, digits, periods, underscores, colons, or hyphens.")
    return value


def _safe_text(value):
    return "[redacted]" if PRIVATE_TEXT.search(value) else value


def failure_code(value):
    """Classify a failure without retaining its browser log or private message."""
    text = str(value).casefold()
    for words, code in ((('history',), 'history_validation'), (('search', 'suggestion'), 'player_search'),
                        (('autopick',), 'autopick_state'), (('scope', 'another league', 'team link'), 'context_validation'),
                        (('timeout', 'timed out'), 'timeout'), (('http 401', 'http 403', 'sign in'), 'authentication'),
                        (('revision', 'changed'), 'state_changed'), (('lock',), 'lock_validation')):
        if any(word in text for word in words):
            return code
    return 'unclassified'


def sanitize(value, parent=""):
    """Keep typed evidence fields. Do not export arbitrary provider objects."""
    if value is None or isinstance(value, (bool, int, float)):
        _json(value)
        return value
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [sanitize(item, parent) for item in value]
    if not isinstance(value, dict):
        raise ArchiveError("Evidence must contain JSON values.")
    result = {}
    is_team = 'roster_ids' in value and 'slot' in value and 'id' in value
    is_player = 'position' in value and 'id' in value
    for key, item in value.items():
        if not isinstance(key, str):
            raise ArchiveError("Evidence object keys must be strings.")
        if key.casefold() in BLOCKED_KEYS:
            if key in {'error', 'last_error'} and item:
                result['failure_code'] = failure_code(item)
            continue
        if key == 'name':
            if is_team:
                result[key] = f"Team {value['slot']}"
            elif is_player:
                result[key] = sanitize(item)
            continue
        if parent in DYNAMIC_MAPS:
            if not IDENTIFIER.fullmatch(key):
                raise ArchiveError("A dynamic evidence map contains an invalid key.")
        elif key not in SAFE_KEYS:
            continue
        result[key] = sanitize(item, key)
    return result


def _context(value, expected=None):
    if not isinstance(value, dict):
        raise ArchiveError("An explicit league context is required.")
    result = {key: value.get(key) for key in ('league_id', 'team_id', 'season')}
    if not all(isinstance(result[key], str) and result[key] and _safe_text(result[key]) == result[key]
               for key in ('league_id', 'team_id')):
        raise ArchiveError("League and team identifiers are required.")
    if type(result['season']) is not int or not 2020 <= result['season'] <= 2100:
        raise ArchiveError("The season is invalid.")
    if expected and any(result[k] != expected[k] for k in result):
        raise ArchiveError("Evidence belongs to a different league, team, or season.")
    phase, week = value.get('phase'), value.get('week')
    if phase is not None and phase not in {'draft', 'season'}:
        raise ArchiveError("The evidence phase is invalid.")
    if week is not None and (type(week) is not int or not 1 <= week <= 18):
        raise ArchiveError("The evidence week is invalid.")
    return {**result, 'phase': phase, 'week': week}


def _snapshot(value, expected, *, redacted=False):
    # Validate before sanitization, so a malformed raw object cannot become valid
    # merely because a required field was omitted by the exporter.
    if redacted:
        value = deepcopy(value)
        # The outbox intentionally omits display names and navigation URLs.
        # These labels are identifiers, not reconstructed personal information.
        for player in value.get('players', []):
            player['name'] = f"Player {player['id']}"
        for team in value.get('teams', []):
            team['name'] = f"Team {team['slot']}"
        browser = value.get('source', {}).get('browser')
        if browser is not None:
            browser['page_url'] = 'https://fantasy.espn.com/football/' + ('draft' if value.get('phase') == 'draft' else 'team') + '?' + urlencode({
                'leagueId': value['league_id'], 'teamId': value['team_id'], 'seasonId': value['season']})
    snapshot = LeagueSnapshot.model_validate(value)
    raw = snapshot.model_dump(mode='json')
    context = _context(raw, expected)
    clean = sanitize(raw)
    # Retain a scoped, canonical source URL. Never preserve a member query value.
    if clean.get('source', {}).get('browser') is not None:
        query = {'leagueId': context['league_id'], 'teamId': context['team_id'], 'seasonId': context['season']}
        if context['phase'] == 'season':
            query['scoringPeriodId'] = context['week']
        clean['source']['browser']['page_url'] = 'https://fantasy.espn.com/football/' + ('draft' if context['phase'] == 'draft' else 'team') + '?' + urlencode(query)
    return clean, context


def _read_file(path, base):
    path = Path(path)
    path = path if path.is_absolute() else base / path
    if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file():
        raise ArchiveError("An explicit regular evidence file is required.")
    if any(part.casefold() in {'espn-browser-profile', 'browser-profile', 'private-captures'} for part in path.parts):
        raise ArchiveError("Browser profiles and unstructured capture directories cannot be exported.")
    return path


class _Builder:
    def __init__(self):
        self.runs, self.records, self.labels = {}, {}, {}

    def add(self, source, kind, key, payload, *, context=None, observed_at=None, recorded_at=None):
        if kind not in KINDS:
            raise ArchiveError("Unsupported archive record kind.")
        context = _context(context or source['context'], source['context'])
        clean = sanitize(payload) if kind != 'snapshot' else payload
        item = {'source_id': source['source_id'], 'run_id': source['run_id'], 'kind': kind,
                'source_key': key, 'context': context, 'observed_at': _timestamp(observed_at),
                'recorded_at': _timestamp(recorded_at), 'payload': clean, 'payload_sha256': _hash(clean)}
        item['record_id'] = _hash(item)
        self.records[item['record_id']] = item
        return item['record_id']

    def label(self, record_id, key, value, *, evidence_type='derived', evidence_ids=None, rule='archive-v1'):
        item = {'record_id': record_id, 'key': key, 'value': value, 'evidence_type': evidence_type,
                'evidence_ids': evidence_ids or [record_id], 'rule_version': rule}
        item['label_id'] = _hash(item)
        self.labels[item['label_id']] = item

    def snapshot(self, source, key, raw, recorded_at=None, *, redacted=False):
        clean, context = _snapshot(raw, source['context'], redacted=redacted)
        rid = self.add(source, 'snapshot', key, clean, context=context,
                       observed_at=clean['source']['observed_at'], recorded_at=recorded_at)
        for pick in clean['picks']:
            pid = self.add(source, 'draft_pick', f"pick:{pick['pick_no']}", pick, context=context,
                           observed_at=None, recorded_at=None)
            self.label(pid, 'executor', 'unknown', evidence_ids=[rid], rule='no-causal-inference-v1')
            self.label(pid, 'pick_observed', True, evidence_ids=[rid])
        return rid

    def proposal(self, source, table, row):
        _context(row, source['context'])
        baseline = json.loads(row['baseline'])
        if table == 'browser_lineup_proposals' and row['week'] != baseline.get('week'):
            raise ArchiveError("A lineup proposal and its baseline identify different weeks.")
        sid = self.snapshot(source, f"{table}:{row['id']}:baseline", baseline)
        result = json.loads(row['result']) if row['result'] else None
        data = {'proposal_id': row['id'], 'action': 'set_lineup' if table == 'browser_lineup_proposals' else 'draft_pick',
                'revision': row['revision'], 'config_revision': row['config_revision'],
                'status': row['status'], 'authorized_at': row['authorized_at'],
                'decision': json.loads(row['decision']), 'result': result}
        context = _context(baseline, source['context'])
        rid = self.add(source, 'proposal', f"{table}:{row['id']}", data, context=context,
                       observed_at=(result or {}).get('observed_at'),
                       recorded_at=row.get('created_at') or row['authorized_at'])
        self.label(rid, 'authorization', 'persisted' if row['authorized_at'] else 'absent', evidence_ids=[rid, sid])
        self.label(rid, 'reconciliation', row['status'] if row['status'] in {'confirmed', 'not_selected', 'conflict'} else 'unresolved')
        self.label(rid, 'executor', 'unknown', rule='no-causal-inference-v1')
        return rid

    def event(self, source, key, event, detail, at):
        if not isinstance(detail, dict):
            raise ArchiveError("An event detail must be an object.")
        declared_context = detail.get('context') or source['context']
        if 'league_id' not in declared_context:
            # Startup/config events can precede the first snapshot. Their phase
            # and week remain unknown, and the manifest supplies source scope.
            declared_context = source['context']
        context = _context(declared_context, source['context'])
        if isinstance(detail.get('snapshot'), dict):
            self.snapshot(source, key + ':snapshot', detail['snapshot'], at, redacted=key.startswith('outbox:'))
        if detail.get('config') is not None:
            ManagerConfig.model_validate(detail['config'])
        failed = (detail.get('error') or detail.get('failure_code') or (detail.get('worker') or {}).get('error_category')
                  or (detail.get('submission') or {}).get('error_category'))
        kind = ('failure' if failed else 'recommendation' if event == 'calculation_completed' else
                'runtime_observation' if event == 'worker_transition' else 'outbox_event' if key.startswith('outbox:') else 'audit_event')
        data = {**detail, 'event': _identifier(event)}
        rid = self.add(source, kind, key, data, context=context, observed_at=detail.get('observed_at'), recorded_at=at)
        # A click return is evidence only when the collector explicitly recorded it.
        if type(detail.get('clicked')) is bool:
            self.label(rid, 'click_returned', detail['clicked'], rule='explicit-browser-return-v1')
        submission = detail.get('submission') or {}
        if type(submission.get('returned')) is bool:
            self.label(rid, 'submission_returned', submission['returned'], rule='explicit-browser-return-v1')
        click = (submission.get('result') or {}).get('clicked')
        if type(click) is bool:
            self.label(rid, 'click_returned', click, rule='explicit-browser-return-v1')
        return rid


def export_bundle(manifest, *, base_dir=None):
    """Read explicit sources in consistent SQLite transactions. Never modify them."""
    if not isinstance(manifest, dict) or manifest.get('schema_version') != SCHEMA_VERSION:
        raise ArchiveError("Unsupported input manifest version.")
    sources = manifest.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ArchiveError("At least one explicit source is required.")
    base = Path(base_dir or '.')
    builder, source_ids = _Builder(), set()
    for entry in sources:
        source_id = _identifier(entry['source_id'])
        if source_id in source_ids:
            raise ArchiveError("Source identifiers must be unique.")
        source_ids.add(source_id)
        context = _context(entry['context'])
        declared = entry['run']
        kind = declared.get('kind', 'backfill')
        if kind not in {'backfill', 'live_collection', 'test'}:
            raise ArchiveError("Unsupported archive run kind.")
        run = {'source_id': source_id, 'external_id': _identifier(declared['run_id']), 'kind': kind,
               'label': _safe_text(str(declared.get('label', declared['run_id']))),
               'runtime_version': declared.get('runtime_version'), 'code_revision': declared.get('code_revision'),
               'context': context}
        for key in ('runtime_version', 'code_revision'):
            if run[key] is not None:
                _identifier(run[key])
        run['run_id'] = _hash({'source_id': source_id, 'external_id': run['external_id']})
        builder.runs[run['run_id']] = run
        source = {'source_id': source_id, 'run_id': run['run_id'], 'context': context}
        if entry.get('database'):
            path = _read_file(entry['database'], base)
            db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            db.row_factory = sqlite3.Row
            try:
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'state' not in tables:
                    raise ArchiveError("The source is not a manager database.")
                row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
                if row is None:
                    raise ArchiveError("The manager state is missing.")
                if row['snapshot']:
                    builder.snapshot(source, f"state:{row['revision']}", json.loads(row['snapshot']))
                config = ManagerConfig.model_validate_json(row['config']).model_dump(mode='json')
                builder.add(source, 'config', f"config:{row['config_revision']}", {'config': config, 'config_revision': row['config_revision']})
                for table in ('browser_proposals', 'browser_lineup_proposals'):
                    if table in tables:
                        for proposal in db.execute(f'SELECT * FROM {table} ORDER BY id'):
                            builder.proposal(source, table, dict(proposal))
                for table, prefix in (('audit', 'audit'), ('ffm_archive_outbox', 'outbox')):
                    if table in tables:
                        for row in db.execute(f'SELECT * FROM {table} ORDER BY id'):
                            builder.event(source, f"{prefix}:{row['id']}", row['event'], json.loads(row['detail']), row['at'])
            finally:
                db.rollback()
                db.close()
        dataset_ids = set()
        for dataset in entry.get('datasets', []):
            dataset_id = _identifier(dataset['dataset_id'])
            if dataset_id in dataset_ids:
                raise ArchiveError("Dataset identifiers must be unique within a source.")
            dataset_ids.add(dataset_id)
            fmt = dataset.get('format')
            if fmt not in {'snapshot', 'audit_json', 'runtime_jsonl'}:
                raise ArchiveError("Only structured snapshot, audit JSON, or runtime JSONL datasets are supported.")
            path = _read_file(dataset['path'], base)
            text = path.read_text(encoding='utf-8-sig')
            if fmt == 'snapshot':
                builder.snapshot(source, 'dataset:' + dataset_id, json.loads(text))
                continue
            rows = [json.loads(line) for line in text.splitlines() if line.strip()] if fmt == 'runtime_jsonl' else json.loads(text)
            if not isinstance(rows, list):
                raise ArchiveError("An event dataset must contain a list of records.")
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ArchiveError("An event dataset contains a non-object record.")
                builder.event(source, f"dataset:{dataset_id}:{index}", row.get('event', 'runtime_observation'),
                              row.get('detail', row), row.get('at'))
    assertions = {}
    for label in manifest.get('operator_labels', []):
        if label.get('source_id') not in source_ids or label.get('evidence_type') != 'operator_observation':
            raise ArchiveError("Operator labels require an explicit known source and observation evidence.")
        if label.get('kind') != 'draft_pick' or label.get('key') != 'executor' or label.get('value') not in {'espn_autopick', 'manual', 'manager_browser', 'host_browser', 'unknown'}:
            raise ArchiveError("Unsupported operator label.")
        matched = [r for r in builder.records.values() if r['source_id'] == label['source_id'] and r['kind'] == 'draft_pick'
                   and r['payload']['pick_no'] == label.get('pick_no')]
        if len(matched) != 1:
            raise ArchiveError("An operator label must identify exactly one observed draft pick.")
        identity = (matched[0]['record_id'], label['key'])
        if identity in assertions and assertions[identity] != label['value']:
            raise ArchiveError("Operator observations conflict for the same record and label.")
        assertions[identity] = label['value']
        builder.label(matched[0]['record_id'], 'executor', label['value'], evidence_type='operator_observation', rule='operator-annotation-v1')
    bundle = {'schema_version': SCHEMA_VERSION, 'exporter_version': __version__, 'exported_at': _now(),
              'runs': sorted(builder.runs.values(), key=lambda r: r['run_id']),
              'records': sorted(builder.records.values(), key=lambda r: r['record_id']),
              'labels': sorted(builder.labels.values(), key=lambda r: r['label_id'])}
    bundle['manifest'] = _bundle_manifest(bundle)
    bundle['bundle_id'] = _hash(bundle['manifest'])
    validate_bundle(bundle)
    return bundle


def _bundle_manifest(bundle):
    return {'schema_version': SCHEMA_VERSION, 'exporter_version': bundle['exporter_version'],
            **{kind: [{'id': row[key], 'sha256': _hash(row)} for row in bundle[kind]]
               for kind, key in (('runs', 'run_id'), ('records', 'record_id'), ('labels', 'label_id'))}}


def validate_bundle(bundle):
    """Reject changed payloads, broken references, and invalid evidence before writes."""
    if bundle.get('schema_version') != SCHEMA_VERSION or bundle.get('manifest') != _bundle_manifest(bundle) or bundle.get('bundle_id') != _hash(bundle['manifest']):
        raise ArchiveError("The archive bundle manifest does not match its contents.")
    runs = {r['run_id']: r for r in bundle['runs']}
    records = {r['record_id']: r for r in bundle['records']}
    if len(runs) != len(bundle['runs']) or len(records) != len(bundle['records']) or len({r['label_id'] for r in bundle['labels']}) != len(bundle['labels']):
        raise ArchiveError("Archive identifiers must be unique.")
    for run in runs.values():
        if set(run) != {'source_id', 'external_id', 'kind', 'label', 'runtime_version', 'code_revision', 'context', 'run_id'}:
            raise ArchiveError("An archive run contains unsupported metadata.")
        _identifier(run['source_id']); _identifier(run['external_id'])
        if (run['run_id'] != _hash({'source_id': run['source_id'], 'external_id': run['external_id']})
                or run['kind'] not in {'backfill', 'live_collection', 'test'} or _safe_text(run['label']) != run['label']):
            raise ArchiveError("An archive run has invalid identity or metadata.")
        _context(run['context'])
        for key in ('runtime_version', 'code_revision'):
            if run[key] is not None:
                _identifier(run[key])
    for row in bundle['records']:
        if not isinstance(row['source_key'], str) or _safe_text(row['source_key']) != row['source_key']:
            raise ArchiveError("An evidence source key contains private text.")
        core = {k: v for k, v in row.items() if k != 'record_id'}
        if row['record_id'] != _hash(core) or row['payload_sha256'] != _hash(row['payload']):
            raise ArchiveError("An evidence record hash is invalid.")
        if row['run_id'] not in runs or row['source_id'] != runs[row['run_id']]['source_id'] or row['kind'] not in KINDS:
            raise ArchiveError("An evidence record has invalid provenance.")
        _context(row['context'], runs[row['run_id']]['context'])
        _timestamp(row['observed_at']); _timestamp(row['recorded_at'])
        clean = _snapshot(row['payload'], row['context'])[0] if row['kind'] == 'snapshot' else sanitize(row['payload'])
        if clean != row['payload']:
            raise ArchiveError("An evidence record contains fields outside the sanitized archive contract.")
    for label in bundle['labels']:
        if set(label) != {'record_id', 'key', 'value', 'evidence_type', 'evidence_ids', 'rule_version', 'label_id'}:
            raise ArchiveError("An evidence label contains unsupported metadata.")
        if label['label_id'] != _hash({k: v for k, v in label.items() if k != 'label_id'}) or label['record_id'] not in records or any(r not in records for r in label['evidence_ids']):
            raise ArchiveError("An evidence label has an invalid hash or reference.")
        if label['key'] not in {'executor', 'authorization', 'reconciliation', 'pick_observed', 'click_returned', 'submission_returned'} or label['evidence_type'] not in {'derived', 'operator_observation'}:
            raise ArchiveError("An evidence label has an unsupported type.")
        if isinstance(label['value'], str) and _safe_text(label['value']) != label['value']:
            raise ArchiveError("An evidence label contains private text.")


DDL = (
    'CREATE TABLE IF NOT EXISTS archive_imports (bundle_id TEXT PRIMARY KEY, imported_at TEXT NOT NULL, manifest TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS archive_runs (run_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, payload TEXT NOT NULL)',
    '''CREATE TABLE IF NOT EXISTS archive_records (record_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES archive_runs(run_id),
        source_id TEXT NOT NULL, kind TEXT NOT NULL, source_key TEXT NOT NULL, league_id TEXT NOT NULL, team_id TEXT NOT NULL,
        season INTEGER NOT NULL, phase TEXT, week INTEGER, observed_at TEXT, recorded_at TEXT, ingested_at TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL, payload TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS archive_labels (label_id TEXT PRIMARY KEY, record_id TEXT NOT NULL REFERENCES archive_records(record_id),
        label_key TEXT NOT NULL, label_value TEXT NOT NULL, evidence_type TEXT NOT NULL, payload TEXT NOT NULL)''',
    'CREATE INDEX IF NOT EXISTS archive_records_scope ON archive_records(league_id, team_id, season, phase, week, kind)',
    'CREATE INDEX IF NOT EXISTS archive_records_source ON archive_records(source_id, source_key)',
)


@contextmanager
def _transaction(connection):
    if isinstance(connection, sqlite3.Connection):
        if connection.in_transaction:
            raise ArchiveError("Archive import requires its own database transaction.")
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('BEGIN IMMEDIATE')
        try:
            yield
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    else:
        with connection.transaction():
            yield


def import_bundle(connection, bundle):
    """Atomically insert a verified bundle. Existing evidence is never overwritten."""
    validate_bundle(bundle)
    placeholder = '?' if isinstance(connection, sqlite3.Connection) else '%s'
    def execute(sql, values=()):
        return connection.execute(sql.replace('?', placeholder), values)
    added = {'runs': 0, 'records': 0, 'labels': 0, 'imports': 0}
    with _transaction(connection):
        for statement in DDL:
            execute(statement)
        for run in bundle['runs']:
            old = execute('SELECT payload FROM archive_runs WHERE run_id=?', (run['run_id'],)).fetchone()
            payload = _json(run)
            if old and old[0] != payload:
                raise ArchiveError("An existing run has different immutable metadata.")
            added['runs'] += max(0, execute('INSERT INTO archive_runs VALUES(?,?,?) ON CONFLICT DO NOTHING', (run['run_id'], run['source_id'], payload)).rowcount)
        at = _now()
        for row in bundle['records']:
            ctx = row['context']
            values = (row['record_id'], row['run_id'], row['source_id'], row['kind'], row['source_key'],
                      ctx['league_id'], ctx['team_id'], ctx['season'], ctx['phase'], ctx['week'], row['observed_at'],
                      row['recorded_at'], at, row['payload_sha256'], _json(row['payload']))
            added['records'] += max(0, execute('INSERT INTO archive_records VALUES(' + ','.join('?' for _ in values) + ') ON CONFLICT DO NOTHING', values).rowcount)
        for row in bundle['labels']:
            values = (row['label_id'], row['record_id'], row['key'], _json(row['value']), row['evidence_type'], _json(row))
            added['labels'] += max(0, execute('INSERT INTO archive_labels VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING', values).rowcount)
        added['imports'] += max(0, execute('INSERT INTO archive_imports VALUES(?,?,?) ON CONFLICT DO NOTHING',
                                         (bundle['bundle_id'], at, _json(bundle['manifest']))).rowcount)
    return added


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    export.add_argument('--manifest', required=True); export.add_argument('--output', required=True)
    ingest = sub.add_parser('import')
    ingest.add_argument('--bundle', required=True); ingest.add_argument('--dsn', default='dbname=fantasy_football')
    sync = sub.add_parser('sync')
    sync.add_argument('--manifest', required=True); sync.add_argument('--dsn', default='dbname=fantasy_football')
    sync.add_argument('--interval', type=float, default=0)
    args = parser.parse_args(argv)
    if args.command == 'sync' and args.interval != 0 and not 1 <= args.interval <= 86400:
        parser.error('The interval must be zero or from 1 through 86400 seconds.')
    while True:
        if args.command == 'import':
            bundle = json.loads(Path(args.bundle).read_text(encoding='utf-8'))
        else:
            path = Path(args.manifest)
            bundle = export_bundle(json.loads(path.read_text(encoding='utf-8-sig')), base_dir=path.parent)
        if args.command == 'export':
            Path(args.output).write_text(_json(bundle) + '\n', encoding='utf-8')
            print(_json({'bundle_id': bundle['bundle_id'], 'records': len(bundle['records']), 'labels': len(bundle['labels'])}))
            return 0
        try:
            import psycopg
        except ImportError as exc:
            raise ArchiveError('Install the server extra before importing into PostgreSQL.') from exc
        with psycopg.connect(args.dsn, autocommit=True) as connection:
            result = import_bundle(connection, bundle)
        print(_json({'bundle_id': bundle['bundle_id'], 'inserted': result}), flush=True)
        if args.command != 'sync' or args.interval == 0:
            return 0
        time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
