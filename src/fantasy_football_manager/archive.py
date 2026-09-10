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

from . import __version__, evidence
from .models import LeagueSnapshot, ManagerConfig


SCHEMA_VERSION = 1
INCREMENTAL_SCHEMA_VERSION = 2
DEFAULT_BATCH_SIZE = 500
COMPACT_RECEIPT_FORMAT = 'ffm-compact-receipt-v1'
SHA256 = re.compile(r'^[0-9a-f]{64}$')
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
http ownership_verified transaction_period latest_period final_period team_transaction_locked pending_transactions_known
uses_faab acquisition_type minimum_bid acquisition_limit matchup_acquisition_limit acquisitions_season acquisitions_period
uses_undroppable_list pending_transactions recent_transactions transaction type teamId scoringPeriodId isPending bidAmount
executionType items playerId fromTeamId toTeamId fromLineupSlotId toLineupSlotId espn roster_locked trade_locked droppable
injured bye_verified eligible_slots acquisition_status waiver_process_date pending_transaction_ids coverage_repair_ids coverage_repair_add_ids
comparison_complete projection_complete comparison_scope objective_field objective_points fixed_slots blocking_missing_projections
excluded_players unfilled_slots baseline_unfilled_slots coverage gaps source_ready platform_eligibility_verified authorized
repair_player_id drop_id reasons blocking_reasons fields reason backup_player_ids should_submit actual_roster_ids actual_reserve_ids
remaining_weekly_moves bid submission_phase
""".split())
DYNAMIC_MAPS = {"lineup", "actual_lineup", "starters", "caps", "actions", "fixed_slots"}


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
        if key == 'http' and isinstance(item, dict):
            item = evidence.http_record(item)
        elif key == 'transaction' and isinstance(item, dict):
            item = evidence.transaction_record(item)
        elif key in {'pending_transactions', 'recent_transactions'} and isinstance(item, list):
            item = [evidence.transaction_record(row) for row in item if isinstance(row, dict)]
        elif key in {'reasons', 'blocking_reasons', 'fields', 'reason', 'submission_phase'}:
            selected = evidence.action_or_result({key: item})
            if key not in selected:
                continue
            item = selected[key]
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


def _snapshot(value, expected, *, redacted=False, archived=False):
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
    http = value.get('source', {}).get('http')
    if (redacted or archived) and http is not None and 'roster_url' not in http:
        from .espn_http_client import league_url
        value = deepcopy(value)
        value['source']['http']['roster_url'] = league_url(http['league_id'], http['season']) + '?' + urlencode({
            'view': 'mRoster', 'forTeamId': http['team_id'], 'scoringPeriodId': http['week']})
    snapshot = LeagueSnapshot.model_validate(value)
    raw = snapshot.model_dump(mode='json')
    # Missing optional evidence stays missing in historical bundles. New model
    # defaults must not change an old observation's hash during validation.
    if 'http' not in value.get('source', {}):
        raw['source'].pop('http', None)
    for original, player in zip(value.get('players', []), raw['players']):
        if 'espn' not in original:
            player.pop('espn', None)
        elif isinstance(original['espn'], dict) and isinstance(player.get('espn'), dict):
            player['espn'] = {key: item for key, item in player['espn'].items() if key in original['espn']}
    context = _context(raw, expected)
    clean = sanitize(raw)
    # Retain a scoped, canonical source URL. Never preserve a member query value.
    if clean.get('source', {}).get('browser') is not None:
        query = {'leagueId': context['league_id'], 'teamId': context['team_id'], 'seasonId': context['season']}
        if context['phase'] == 'season':
            query['scoringPeriodId'] = context['week']
        clean['source']['browser']['page_url'] = 'https://fantasy.espn.com/football/' + ('draft' if context['phase'] == 'draft' else 'team') + '?' + urlencode(query)
    return clean, context


def _config(raw):
    """Validate stored configuration without inventing newly added fields."""
    value = json.loads(raw) if isinstance(raw, str) else raw
    result = ManagerConfig.model_validate(value).model_dump(mode='json')
    for key in ('coverage_repair_ids', 'coverage_repair_add_ids'):
        if key not in value.get('limits', {}):
            result['limits'].pop(key, None)
    actions = value.get('automation', {}).get('actions')
    if isinstance(actions, dict):
        result['automation']['actions'] = {key: item for key, item in result['automation']['actions'].items() if key in actions}
    return result


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
                config = _config(row['config'])
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


def _execute(connection, sql, values=()):
    return connection.execute(sql.replace('?', '?' if isinstance(connection, sqlite3.Connection) else '%s'), values)


def _has_table(connection, name):
    if isinstance(connection, sqlite3.Connection):
        return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
    return connection.execute('SELECT to_regclass(%s)', (name,)).fetchone()[0] is not None


def _source_reset(reason):
    raise ArchiveError(f"Source continuity check failed ({reason}). Restore the original source, or use a new source_id and run_id after a reviewed reset.")


def _stream_batch(db, table, previous, limit):
    """Check committed boundaries and read only the next append-only batch."""
    cursor = previous['last_id'] if previous else None
    if cursor is not None:
        count = db.execute(f'SELECT count(*) FROM {table} WHERE id<=?', (cursor,)).fetchone()[0]
        first = db.execute(f'SELECT * FROM {table} WHERE id=?', (previous['first_id'],)).fetchone()
        last = db.execute(f'SELECT * FROM {table} WHERE id=?', (cursor,)).fetchone()
        if (count != previous['count'] or first is None or last is None
                or _hash(dict(first)) != previous['first_sha256'] or _hash(dict(last)) != previous['last_sha256']):
            _source_reset(f'{table} committed rows changed or disappeared')
    rows = [dict(row) for row in db.execute(f'SELECT * FROM {table} WHERE id>? ORDER BY id LIMIT ?',
                                           (cursor if cursor is not None else 0, limit))]
    if db.execute(f'SELECT 1 FROM {table} WHERE id<=0 LIMIT 1').fetchone():
        raise ArchiveError('Incremental event rows require positive integer identifiers.')
    state = deepcopy(previous) if previous else {'count': 0, 'first_id': None, 'last_id': None,
                                                'first_sha256': None, 'last_sha256': None}
    if rows:
        if not state['count']:
            state.update(first_id=rows[0]['id'], first_sha256=_hash(rows[0]))
        state.update(count=state['count'] + len(rows), last_id=rows[-1]['id'], last_sha256=_hash(rows[-1]))
    more = db.execute(f'SELECT 1 FROM {table} WHERE id>? LIMIT 1', (state['last_id'] or 0,)).fetchone() is not None
    return rows, state, more


def _dataset_batch(path, fmt, previous, limit):
    """Verify an event-file prefix. Keep JSONL memory bounded by the batch."""
    def rows():
        with path.open(encoding='utf-8-sig') as stream:
            if fmt == 'runtime_jsonl':
                for line in stream:
                    if line.strip():
                        yield json.loads(line)
            else:
                value = json.load(stream)
                if not isinstance(value, list):
                    raise ArchiveError('An event dataset must contain a list of records.')
                yield from value
    old_count = previous['count'] if previous else 0
    digest, count, batch, more = _hash([]), 0, [], False
    iterator = rows()
    try:
        for index, row in enumerate(iterator):
            if not isinstance(row, dict):
                raise ArchiveError('An event dataset contains a non-object record.')
            if index >= old_count + limit:
                more = True
                break
            digest = _hash([digest, row])
            count += 1
            if count == old_count and digest != previous['prefix_sha256']:
                _source_reset('dataset committed prefix changed')
            if index >= old_count:
                batch.append((index, row))
    finally:
        iterator.close()
    if count < old_count:
        _source_reset('dataset became shorter')
    return batch, {'format': fmt, 'count': count, 'prefix_sha256': digest}, more


def _archived_picks(connection, source):
    if not _has_table(connection, 'archive_records'):
        return {}
    columns = ('record_id', 'run_id', 'source_id', 'kind', 'source_key', 'league_id', 'team_id', 'season',
               'phase', 'week', 'observed_at', 'recorded_at', 'payload_sha256', 'payload')
    result = {}
    for values in _execute(connection, 'SELECT ' + ','.join(columns) +
                           " FROM archive_records WHERE run_id=? AND source_id=? AND kind='draft_pick'",
                           (source['run_id'], source['source_id'])):
        row = dict(zip(columns, values))
        row['context'] = {key: row.pop(key) for key in ('league_id', 'team_id', 'season', 'phase', 'week')}
        row['payload'] = json.loads(row['payload'])
        result[row['record_id']] = row
    return result


def export_incremental_bundle(connection, manifest, *, base_dir=None, batch_size=DEFAULT_BATCH_SIZE):
    """Read committed destination checkpoints without advancing them.

    Each event stream and proposal table contributes at most batch_size rows.
    A failed export or import cannot acknowledge source data. Source files stay read-only.
    """
    if type(batch_size) is not int or not 1 <= batch_size <= 10000:
        raise ArchiveError('The archive batch size must be from 1 through 10000.')
    if not isinstance(manifest, dict) or manifest.get('schema_version') != SCHEMA_VERSION:
        raise ArchiveError('Use a version 1 archive input manifest.')
    entries = manifest.get('sources')
    if not isinstance(entries, list) or not entries:
        raise ArchiveError('At least one explicit source is required.')
    # The legacy validator remains the single run-metadata contract.
    metadata = export_bundle({'schema_version': SCHEMA_VERSION,
                              'sources': [{key: entry[key] for key in ('source_id', 'run', 'context')} for entry in entries]})
    builder, transitions, has_more = _Builder(), [], False
    builder.runs = {run['run_id']: run for run in metadata['runs']}
    runs = {run['source_id']: run for run in metadata['runs']}
    base = Path(base_dir or '.')
    for entry in entries:
        run = runs[entry['source_id']]
        source = {'source_id': run['source_id'], 'run_id': run['run_id'], 'context': run['context']}
        previous = None
        if _has_table(connection, 'archive_source_checkpoints'):
            old = _execute(connection, 'SELECT source_id,payload FROM archive_source_checkpoints WHERE run_id=?', (run['run_id'],)).fetchone()
            if old:
                if old[0] != source['source_id']:
                    _source_reset('checkpoint source identity differs')
                previous = json.loads(old[1])
        epoch = _identifier(entry.get('source_epoch', run['external_id']))
        datasets = entry.get('datasets', [])
        dataset_ids = [_identifier(item['dataset_id']) for item in datasets]
        if len(set(dataset_ids)) != len(dataset_ids):
            raise ArchiveError('Dataset identifiers must be unique within a source.')
        selection = _hash({'run': run, 'source_epoch': epoch, 'database': bool(entry.get('database')),
                           'datasets': sorted([{'dataset_id': item['dataset_id'], 'format': item.get('format')} for item in datasets],
                                              key=lambda item: item['dataset_id'])})
        if previous and (previous['selection_sha256'] != selection or previous['source_epoch'] != epoch):
            _source_reset('source selection, epoch, context, or run metadata differs')
        state = deepcopy(previous) if previous else {'sequence': 0, 'source_epoch': epoch, 'selection_sha256': selection,
                                                      'database': None, 'streams': {}, 'datasets': {},
                                                      'operator_labels_sha256': _hash([])}
        objects = []
        if entry.get('database'):
            path = _read_file(entry['database'], base)
            db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
            db.row_factory = sqlite3.Row
            try:
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'state' not in tables:
                    raise ArchiveError('The source is not a manager database.')
                row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
                if row is None:
                    raise ArchiveError('The manager state is missing.')
                raw_snapshot = json.loads(row['snapshot']) if row['snapshot'] else None
                config = _config(row['config'])
                current = {'revision': row['revision'], 'config_revision': row['config_revision'],
                           'snapshot_sha256': _hash(raw_snapshot), 'config_sha256': _hash(json.loads(row['config']))}
                if any(type(current[key]) is not int or current[key] < 0 for key in ('revision', 'config_revision')):
                    raise ArchiveError('Source revisions must be nonnegative integers.')
                prior = state['database']
                if prior:
                    for revision, digest in (('revision', 'snapshot_sha256'), ('config_revision', 'config_sha256')):
                        if current[revision] < prior[revision] or (current[revision] == prior[revision] and current[digest] != prior[digest]):
                            _source_reset(f'{revision} rolled back or changed without a revision')
                if raw_snapshot is not None:
                    _context(raw_snapshot, source['context'])
                    if prior is None or current['revision'] != prior['revision']:
                        builder.snapshot(source, f"state:{row['revision']}", raw_snapshot)
                if prior is None or current['config_revision'] != prior['config_revision']:
                    builder.add(source, 'config', f"config:{row['config_revision']}", {'config': config, 'config_revision': row['config_revision']})
                state['database'] = current
                known = {}
                if _has_table(connection, 'archive_source_objects'):
                    known = dict(_execute(connection, 'SELECT source_key,payload_sha256 FROM archive_source_objects WHERE run_id=?', (run['run_id'],)))
                for table in ('browser_proposals', 'browser_lineup_proposals'):
                    seen, selected = set(), 0
                    if table in tables:
                        for proposal in db.execute(f'SELECT * FROM {table} ORDER BY id'):
                            value = dict(proposal)
                            key = table + ':' + _identifier(value['id'])
                            seen.add(key)
                            digest = _hash(value)
                            if known.get(key) == digest:
                                continue
                            if selected == batch_size:
                                has_more = True
                                continue
                            builder.proposal(source, table, value)
                            objects.append({'source_key': key, 'payload_sha256': digest})
                            selected += 1
                    if any(key.startswith(table + ':') and key not in seen for key in known):
                        _source_reset('a committed proposal disappeared')
                if any(table not in tables for table in state['streams']):
                    _source_reset('an event table disappeared')
                for table, prefix in (('audit', 'audit'), ('ffm_archive_outbox', 'outbox')):
                    if table not in tables:
                        continue
                    rows, cursor, more = _stream_batch(db, table, state['streams'].get(table), batch_size)
                    state['streams'][table] = cursor
                    has_more |= more
                    for event in rows:
                        builder.event(source, f"{prefix}:{event['id']}", event['event'], json.loads(event['detail']), event['at'])
            finally:
                db.rollback()
                db.close()
        for dataset in datasets:
            dataset_id, fmt = dataset['dataset_id'], dataset.get('format')
            if fmt not in {'snapshot', 'audit_json', 'runtime_jsonl'}:
                raise ArchiveError('Only structured snapshot, audit JSON, or runtime JSONL datasets are supported.')
            path = _read_file(dataset['path'], base)
            old = state['datasets'].get(dataset_id)
            if fmt == 'snapshot':
                raw = json.loads(path.read_text(encoding='utf-8-sig'))
                cursor = {'format': fmt, 'sha256': _hash(raw)}
                if old != cursor:
                    builder.snapshot(source, 'dataset:' + dataset_id, raw)
            else:
                rows, cursor, more = _dataset_batch(path, fmt, old, batch_size)
                has_more |= more
                for index, event in rows:
                    builder.event(source, f'dataset:{dataset_id}:{index}', event.get('event', 'runtime_observation'),
                                  event.get('detail', event), event.get('at'))
            state['datasets'][dataset_id] = cursor
        labels = [label for label in manifest.get('operator_labels', []) if label.get('source_id') == source['source_id']]
        if _hash(labels) != state['operator_labels_sha256']:
            candidates = _archived_picks(connection, source)
            candidates.update({key: value for key, value in builder.records.items() if value['run_id'] == run['run_id'] and value['kind'] == 'draft_pick'})
            assertions = {}
            for label in labels:
                if (label.get('evidence_type') != 'operator_observation' or label.get('kind') != 'draft_pick'
                        or label.get('key') != 'executor' or label.get('value') not in {'espn_autopick', 'manual', 'manager_browser', 'host_browser', 'unknown'}):
                    raise ArchiveError('Unsupported operator label.')
                matched = [record for record in candidates.values() if record['payload']['pick_no'] == label.get('pick_no')]
                if len(matched) != 1:
                    raise ArchiveError('An operator label must identify exactly one observed draft pick. Complete the initial backfill before adding historical labels.')
                record = matched[0]
                if record['record_id'] in assertions and assertions[record['record_id']] != label['value']:
                    raise ArchiveError('Operator observations conflict for the same record and label.')
                assertions[record['record_id']] = label['value']
                builder.records[record['record_id']] = record
                builder.label(record['record_id'], 'executor', label['value'], evidence_type='operator_observation', rule='operator-annotation-v1')
            state['operator_labels_sha256'] = _hash(labels)
        if previous != state or objects:
            state['sequence'] += 1
            transitions.append({'run_id': run['run_id'], 'source_id': source['source_id'],
                                'previous_sha256': _hash(previous) if previous else None,
                                'state': state, 'objects': sorted(objects, key=lambda item: item['source_key'])})
    if any(label.get('source_id') not in runs for label in manifest.get('operator_labels', [])):
        raise ArchiveError('Operator labels require an explicit known source and observation evidence.')
    bundle = {'schema_version': INCREMENTAL_SCHEMA_VERSION, 'exporter_version': __version__, 'exported_at': _now(),
              'runs': sorted(builder.runs.values(), key=lambda row: row['run_id']),
              'records': sorted(builder.records.values(), key=lambda row: row['record_id']),
              'labels': sorted(builder.labels.values(), key=lambda row: row['label_id']),
              'checkpoints': sorted(transitions, key=lambda row: row['run_id']), 'has_more': has_more}
    bundle['manifest'] = _bundle_manifest(bundle)
    bundle['bundle_id'] = _hash(bundle['manifest'])
    validate_bundle(bundle)
    return bundle


def _validate_checkpoints(bundle, runs):
    if type(bundle.get('has_more')) is not bool or not isinstance(bundle['checkpoints'], list):
        raise ArchiveError('An incremental bundle has invalid batch metadata.')
    seen = set()
    digest = lambda value: isinstance(value, str) and SHA256.fullmatch(value) is not None
    integer = lambda value: type(value) is int and value >= 0
    for checkpoint in bundle['checkpoints']:
        if set(checkpoint) != {'run_id', 'source_id', 'previous_sha256', 'state', 'objects'}:
            raise ArchiveError('An incremental checkpoint contains unsupported metadata.')
        run_id = checkpoint['run_id']
        if (run_id not in runs or run_id in seen or checkpoint['source_id'] != runs[run_id]['source_id']
                or (checkpoint['previous_sha256'] is not None and not digest(checkpoint['previous_sha256']))):
            raise ArchiveError('An incremental checkpoint has invalid provenance.')
        seen.add(run_id)
        state = checkpoint['state']
        if (set(state) != {'sequence', 'source_epoch', 'selection_sha256', 'database', 'streams', 'datasets', 'operator_labels_sha256'}
                or not integer(state['sequence']) or not state['sequence']
                or not digest(state['selection_sha256']) or not digest(state['operator_labels_sha256'])):
            raise ArchiveError('An incremental checkpoint has invalid state.')
        _identifier(state['source_epoch'])
        value = state['database']
        if value is not None and (set(value) != {'revision', 'config_revision', 'snapshot_sha256', 'config_sha256'}
                                  or not all(integer(value[key]) for key in ('revision', 'config_revision'))
                                  or not all(digest(value[key]) for key in ('snapshot_sha256', 'config_sha256'))):
            raise ArchiveError('An incremental checkpoint has invalid database state.')
        if not isinstance(state['streams'], dict) or set(state['streams']) - {'audit', 'ffm_archive_outbox'}:
            raise ArchiveError('An incremental checkpoint has an invalid event stream.')
        for cursor in state['streams'].values():
            if set(cursor) != {'count', 'first_id', 'last_id', 'first_sha256', 'last_sha256'} or not integer(cursor['count']):
                raise ArchiveError('An incremental checkpoint has an invalid cursor.')
            if cursor['count']:
                if (not all(integer(cursor[key]) and cursor[key] > 0 for key in ('first_id', 'last_id'))
                        or cursor['first_id'] > cursor['last_id'] or cursor['count'] > cursor['last_id'] - cursor['first_id'] + 1
                        or not all(digest(cursor[key]) for key in ('first_sha256', 'last_sha256'))):
                    raise ArchiveError('An incremental checkpoint has invalid boundaries.')
            elif any(cursor[key] is not None for key in ('first_id', 'last_id', 'first_sha256', 'last_sha256')):
                raise ArchiveError('An empty stream cannot contain boundaries.')
        if not isinstance(state['datasets'], dict):
            raise ArchiveError('An incremental checkpoint has invalid datasets.')
        for key, cursor in state['datasets'].items():
            _identifier(key)
            if cursor.get('format') == 'snapshot':
                valid = set(cursor) == {'format', 'sha256'} and digest(cursor['sha256'])
            else:
                valid = (set(cursor) == {'format', 'count', 'prefix_sha256'} and cursor['format'] in {'audit_json', 'runtime_jsonl'}
                         and integer(cursor['count']) and digest(cursor['prefix_sha256']))
            if not valid:
                raise ArchiveError('An incremental checkpoint has invalid dataset state.')
        keys = set()
        for item in checkpoint['objects']:
            if set(item) != {'source_key', 'payload_sha256'} or not digest(item['payload_sha256']):
                raise ArchiveError('An incremental object has invalid metadata.')
            table, separator, key = item['source_key'].partition(':')
            if not separator or table not in {'browser_proposals', 'browser_lineup_proposals'} or item['source_key'] in keys:
                raise ArchiveError('An incremental object has an invalid source key.')
            _identifier(key)
            keys.add(item['source_key'])
    if any(row['run_id'] not in seen for row in bundle['records']):
        raise ArchiveError('Incremental evidence requires a checkpoint transition.')


def _bundle_manifest(bundle):
    if bundle['schema_version'] == INCREMENTAL_SCHEMA_VERSION:
        # A receipt commits to all content without repeating a growing ID list.
        return {'schema_version': INCREMENTAL_SCHEMA_VERSION, 'exporter_version': bundle['exporter_version'],
                'has_more': bundle['has_more'],
                **{kind: {'count': len(bundle[kind]), 'sha256': _hash(bundle[kind])}
                   for kind in ('runs', 'records', 'labels', 'checkpoints')}}
    return {'schema_version': SCHEMA_VERSION, 'exporter_version': bundle['exporter_version'],
            **{kind: [{'id': row[key], 'sha256': _hash(row)} for row in bundle[kind]]
               for kind, key in (('runs', 'run_id'), ('records', 'record_id'), ('labels', 'label_id'))}}


def validate_bundle(bundle):
    """Reject changed payloads, broken references, and invalid evidence before writes."""
    if bundle.get('schema_version') not in {SCHEMA_VERSION, INCREMENTAL_SCHEMA_VERSION} or bundle.get('manifest') != _bundle_manifest(bundle) or bundle.get('bundle_id') != _hash(bundle['manifest']):
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
        clean = _snapshot(row['payload'], row['context'], archived=True)[0] if row['kind'] == 'snapshot' else sanitize(row['payload'])
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
    if bundle['schema_version'] == INCREMENTAL_SCHEMA_VERSION:
        _validate_checkpoints(bundle, runs)


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
    '''CREATE TABLE IF NOT EXISTS archive_source_checkpoints (run_id TEXT PRIMARY KEY REFERENCES archive_runs(run_id),
        source_id TEXT NOT NULL, payload TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS archive_source_objects (run_id TEXT NOT NULL REFERENCES archive_runs(run_id),
        source_key TEXT NOT NULL, payload_sha256 TEXT NOT NULL, PRIMARY KEY(run_id, source_key))''',
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
        if connection.info.transaction_status != 0:
            raise ArchiveError('Archive import requires its own database transaction.')
        with connection.transaction():
            yield


def _check_advance(previous, state):
    if previous is None:
        if state['sequence'] != 1:
            raise ArchiveError('An initial checkpoint must start at sequence one.')
        return
    if (state['sequence'] != previous['sequence'] + 1 or state['source_epoch'] != previous['source_epoch']
            or state['selection_sha256'] != previous['selection_sha256']):
        raise ArchiveError('An incremental checkpoint cannot reset source identity or sequence.')
    old, new = previous['database'], state['database']
    if old is not None and (new is None or any(new[key] < old[key] for key in ('revision', 'config_revision'))):
        raise ArchiveError('An incremental checkpoint cannot reduce source revisions.')
    if old is not None:
        for revision, digest in (('revision', 'snapshot_sha256'), ('config_revision', 'config_sha256')):
            if new[revision] == old[revision] and new[digest] != old[digest]:
                raise ArchiveError('An incremental checkpoint cannot change data without a source revision.')
    for collection in ('streams', 'datasets'):
        if set(previous[collection]) - set(state[collection]):
            raise ArchiveError('An incremental checkpoint cannot remove a source stream.')
        for key, old in previous[collection].items():
            new = state[collection][key]
            if collection == 'datasets' and new['format'] != old['format']:
                raise ArchiveError('An incremental checkpoint cannot change a dataset format.')
            if 'count' in old:
                if new.get('count', -1) < old['count'] or (new['count'] == old['count'] and new != old):
                    raise ArchiveError('An incremental checkpoint cannot replace a committed prefix.')
                if collection == 'streams' and old['count'] and (
                        new['first_id'] != old['first_id'] or new['first_sha256'] != old['first_sha256']
                        or (new['count'] > old['count'] and new['last_id'] <= old['last_id'])):
                    raise ArchiveError('An incremental checkpoint cannot replace committed stream boundaries.')


def _compact_manifest(manifest, runs):
    """Retain the original manifest commitment and bounded run provenance."""
    return {'receipt_format': COMPACT_RECEIPT_FORMAT, 'original_schema_version': SCHEMA_VERSION,
            'original_manifest_sha256': _hash(manifest), 'exporter_version': manifest['exporter_version'],
            'counts': {kind: len(manifest[kind]) for kind in ('runs', 'records', 'labels')},
            'membership_sha256': {kind: _hash(manifest[kind]) for kind in ('runs', 'records', 'labels')},
            'runs': [{'run_id': item['id'], 'source_id': runs[item['id']]['source_id'],
                      'external_id': runs[item['id']]['external_id'], 'context': runs[item['id']]['context'],
                      'run_payload_sha256': item['sha256']} for item in manifest['runs']]}


def _receipt_matches(saved, bundle):
    if saved == bundle['manifest']:
        return True
    return (bundle['schema_version'] == SCHEMA_VERSION and saved.get('receipt_format') == COMPACT_RECEIPT_FORMAT
            and saved == _compact_manifest(bundle['manifest'], {run['run_id']: run for run in bundle['runs']}))


@contextmanager
def _stream_rows(connection, query, *, batch_size=500):
    if isinstance(connection, sqlite3.Connection):
        cursor = connection.execute(query)
    else:
        # A server cursor avoids buffering the full evidence table in libpq.
        cursor = connection.cursor(name='ffm_archive_maintenance')
        cursor.itersize = batch_size
        cursor.execute(query)
    try:
        yield cursor
    finally:
        cursor.close()


def _coverage_index(connection):
    """Hash exact stored rows and index original evidence hashes once."""
    tables = {
        'archive_runs': ('run_id', 'source_id', 'payload'),
        'archive_records': ('record_id', 'run_id', 'source_id', 'kind', 'source_key', 'league_id', 'team_id', 'season',
                            'phase', 'week', 'observed_at', 'recorded_at', 'ingested_at', 'payload_sha256', 'payload'),
        'archive_labels': ('label_id', 'record_id', 'label_key', 'label_value', 'evidence_type', 'payload'),
        'archive_source_checkpoints': ('run_id', 'source_id', 'payload'),
        'archive_source_objects': ('run_id', 'source_key', 'payload_sha256'),
    }
    hashes, runs, references, coverage = {'runs': {}, 'records': {}, 'labels': {}}, {}, {}, {}
    for table, columns in tables.items():
        if not _has_table(connection, table):
            if table in {'archive_runs', 'archive_records', 'archive_labels'}:
                raise ArchiveError('The archive evidence tables are missing.')
            continue
        digest, count = hashlib.sha256(), 0
        digest.update((_json(list(columns)) + '\n').encode('utf-8'))
        order = 'run_id,source_key' if table == 'archive_source_objects' else columns[0]
        with _stream_rows(connection, 'SELECT ' + ','.join(columns) + f' FROM {table} ORDER BY {order}') as rows:
            for values in rows:
                row = dict(zip(columns, values))
                digest.update((_json(list(values)) + '\n').encode('utf-8'))
                count += 1
                if table == 'archive_runs':
                    payload = json.loads(row['payload'])
                    if (payload.get('run_id') != row['run_id'] or payload.get('source_id') != row['source_id']
                            or row['run_id'] != _hash({'source_id': row['source_id'], 'external_id': payload['external_id']})):
                        raise ArchiveError('Stored archive run identity is invalid.')
                    runs[row['run_id']] = payload
                    hashes['runs'][row['run_id']] = _hash(payload)
                elif table == 'archive_records':
                    row.pop('ingested_at')
                    row['context'] = {key: row.pop(key) for key in ('league_id', 'team_id', 'season', 'phase', 'week')}
                    row['payload'] = json.loads(row['payload'])
                    if (row['run_id'] not in runs or row['source_id'] != runs[row['run_id']]['source_id']
                            or row['payload_sha256'] != _hash(row['payload'])
                            or row['record_id'] != _hash({key: value for key, value in row.items() if key != 'record_id'})):
                        raise ArchiveError('Stored archive record identity or content is invalid.')
                    hashes['records'][row['record_id']] = _hash(row)
                    references[row['record_id']] = row['run_id']
                elif table == 'archive_labels':
                    payload = json.loads(row['payload'])
                    if (payload.get('label_id') != row['label_id'] or payload.get('record_id') != row['record_id']
                            or payload.get('key') != row['label_key'] or _json(payload.get('value')) != row['label_value']
                            or payload.get('evidence_type') != row['evidence_type']
                            or row['label_id'] != _hash({key: value for key, value in payload.items() if key != 'label_id'})):
                        raise ArchiveError('Stored archive label identity or content is invalid.')
                    refs = (payload['record_id'], *payload['evidence_ids'])
                    if any(key not in hashes['records'] for key in refs):
                        raise ArchiveError('Stored archive label evidence is missing.')
                    hashes['labels'][row['label_id']] = _hash(payload)
                    references[row['label_id']] = refs
        coverage[table] = {'rows': count, 'sha256': digest.hexdigest()}
    return hashes, runs, references, coverage


def compact_receipts(connection, *, apply=False):
    """Verify legacy membership and compact receipts in one maintenance transaction.

    The default is read-only verification. Pause archive writers before applying.
    Evidence rows, labels, run metadata, import identities, and import times remain unchanged.
    """
    report = {'applied': apply, 'verified_receipts': 0, 'compacted_receipts': 0, 'already_compact_receipts': 0,
              'original_text_bytes': 0, 'compact_text_bytes': 0}
    with _transaction(connection):
        if not isinstance(connection, sqlite3.Connection):
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ' + (' READ ONLY' if not apply else ''))
        if not _has_table(connection, 'archive_imports'):
            raise ArchiveError('The archive import table is missing.')
        hashes, runs, references, before = _coverage_index(connection)
        receipt_identity = hashlib.sha256()
        # Use a different named cursor because UPDATE runs while this cursor is open.
        with _stream_rows(connection, 'SELECT bundle_id,imported_at,manifest FROM archive_imports ORDER BY bundle_id', batch_size=1) as rows:
            for bundle_id, imported_at, text in rows:
                receipt_identity.update((_json([bundle_id, imported_at]) + '\n').encode('utf-8'))
                manifest = json.loads(text)
                if manifest.get('receipt_format') == COMPACT_RECEIPT_FORMAT:
                    if (manifest.get('original_manifest_sha256') != bundle_id
                            or manifest.get('original_schema_version') != SCHEMA_VERSION
                            or set(manifest) != {'receipt_format', 'original_schema_version', 'original_manifest_sha256',
                                                 'exporter_version', 'counts', 'membership_sha256', 'runs'}
                            or set(manifest['counts']) != {'runs', 'records', 'labels'}
                            or set(manifest['membership_sha256']) != {'runs', 'records', 'labels'}
                            or any(type(value) is not int or value < 0 for value in manifest['counts'].values())
                            or any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in manifest['membership_sha256'].values())
                            or len(manifest['runs']) != manifest['counts']['runs']):
                        raise ArchiveError('A compact receipt has invalid identity or metadata.')
                    for run in manifest['runs']:
                        stored = runs.get(run['run_id'])
                        if not stored or run != {'run_id': stored['run_id'], 'source_id': stored['source_id'],
                                                  'external_id': stored['external_id'], 'context': stored['context'],
                                                  'run_payload_sha256': _hash(stored)}:
                            raise ArchiveError('A compact receipt has changed run provenance.')
                    report['already_compact_receipts'] += 1
                    continue
                if manifest.get('schema_version') == INCREMENTAL_SCHEMA_VERSION:
                    if _hash(manifest) != bundle_id:
                        raise ArchiveError('An incremental receipt has an invalid manifest hash.')
                    report['already_compact_receipts'] += 1
                    continue
                if (set(manifest) != {'schema_version', 'exporter_version', 'runs', 'records', 'labels'}
                        or manifest['schema_version'] != SCHEMA_VERSION or _hash(manifest) != bundle_id):
                    raise ArchiveError('A legacy receipt has an invalid manifest hash or schema.')
                members = {}
                for kind in ('runs', 'records', 'labels'):
                    members[kind] = set()
                    for item in manifest[kind]:
                        if (set(item) != {'id', 'sha256'} or item['id'] in members[kind]
                                or hashes[kind].get(item['id']) != item['sha256']):
                            raise ArchiveError('A legacy receipt has missing, duplicate, or changed evidence.')
                        members[kind].add(item['id'])
                if (any(references[key] not in members['runs'] for key in members['records'])
                        or any(any(ref not in members['records'] for ref in references[key]) for key in members['labels'])):
                    raise ArchiveError('A legacy receipt has incomplete evidence references.')
                compact = _json(_compact_manifest(manifest, runs))
                report['verified_receipts'] += 1
                report['original_text_bytes'] += len(text.encode('utf-8'))
                report['compact_text_bytes'] += len(compact.encode('utf-8'))
                if apply:
                    changed = _execute(connection, 'UPDATE archive_imports SET manifest=? WHERE bundle_id=? AND manifest=?',
                                       (compact, bundle_id, text)).rowcount
                    if changed != 1:
                        raise ArchiveError('A receipt changed during compaction. No compaction was committed.')
                    report['compacted_receipts'] += 1
        del hashes, runs, references
        # Rehash stored rows after writes. This also detects unexpected database triggers.
        if apply:
            _, _, _, after = _coverage_index(connection)
        else:
            after = before
        if before != after:
            raise ArchiveError('Compaction changed archived evidence. No compaction was committed.')
        identity_after = hashlib.sha256()
        with _stream_rows(connection, 'SELECT bundle_id,imported_at FROM archive_imports ORDER BY bundle_id') as rows:
            for values in rows:
                identity_after.update((_json(list(values)) + '\n').encode('utf-8'))
        if identity_after.digest() != receipt_identity.digest():
            raise ArchiveError('Compaction changed import identities or times. No compaction was committed.')
        report['evidence_coverage'] = after
        report['import_identity_sha256'] = identity_after.hexdigest()
        report['evidence_unchanged'] = True
    return report


def import_bundle(connection, bundle):
    """Atomically insert a verified bundle. Existing evidence is never overwritten."""
    validate_bundle(bundle)
    placeholder = '?' if isinstance(connection, sqlite3.Connection) else '%s'
    def execute(sql, values=()):
        return connection.execute(sql.replace('?', placeholder), values)
    added = {'runs': 0, 'records': 0, 'labels': 0, 'imports': 0}
    incremental = bundle['schema_version'] == INCREMENTAL_SCHEMA_VERSION
    if incremental and not bundle['checkpoints']:
        return added
    with _transaction(connection):
        for statement in DDL:
            execute(statement)
        receipt = execute('SELECT manifest FROM archive_imports WHERE bundle_id=?', (bundle['bundle_id'],)).fetchone()
        if receipt:
            if not _receipt_matches(json.loads(receipt[0]), bundle):
                raise ArchiveError('An existing import receipt has different content.')
            if incremental:
                return added
        if incremental:
            for checkpoint in bundle['checkpoints']:
                old = execute('SELECT source_id,payload FROM archive_source_checkpoints WHERE run_id=?', (checkpoint['run_id'],)).fetchone()
                previous = json.loads(old[1]) if old else None
                if ((old and old[0] != checkpoint['source_id'])
                        or (_hash(previous) if previous else None) != checkpoint['previous_sha256']):
                    raise ArchiveError('The incremental checkpoint is stale. Export again from the committed archive.')
                _check_advance(previous, checkpoint['state'])
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
        for checkpoint in bundle.get('checkpoints', []) if incremental else []:
            payload = _json(checkpoint['state'])
            if checkpoint['previous_sha256'] is None:
                changed = execute('INSERT INTO archive_source_checkpoints VALUES(?,?,?) ON CONFLICT DO NOTHING',
                                  (checkpoint['run_id'], checkpoint['source_id'], payload)).rowcount
            else:
                old = execute('SELECT payload FROM archive_source_checkpoints WHERE run_id=?', (checkpoint['run_id'],)).fetchone()
                if old is None or _hash(json.loads(old[0])) != checkpoint['previous_sha256']:
                    raise ArchiveError('The incremental checkpoint changed during import. Export again.')
                changed = execute('UPDATE archive_source_checkpoints SET payload=? WHERE run_id=? AND payload=?',
                                  (payload, checkpoint['run_id'], old[0])).rowcount
            if changed != 1:
                raise ArchiveError('The incremental checkpoint changed during import. Export again.')
            for item in checkpoint['objects']:
                execute('INSERT INTO archive_source_objects VALUES(?,?,?) ON CONFLICT(run_id,source_key) DO UPDATE SET payload_sha256=excluded.payload_sha256',
                        (checkpoint['run_id'], item['source_key'], item['payload_sha256']))
    return added


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    export.add_argument('--manifest', required=True); export.add_argument('--output', required=True)
    export.add_argument('--incremental', action='store_true', help='Read committed destination checkpoints; do not advance them.')
    export.add_argument('--dsn', default='dbname=fantasy_football')
    export.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE)
    ingest = sub.add_parser('import')
    ingest.add_argument('--bundle', required=True); ingest.add_argument('--dsn', default='dbname=fantasy_football')
    sync = sub.add_parser('sync')
    sync.add_argument('--manifest', required=True); sync.add_argument('--dsn', default='dbname=fantasy_football')
    sync.add_argument('--interval', type=float, default=0)
    sync.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE)
    sync.add_argument('--legacy-full', action='store_true', help='Use the legacy full-history export explicitly.')
    sync.add_argument('--drain', action='store_true', help='Commit further batches until the observed backlog is empty.')
    compact = sub.add_parser('compact-receipts')
    compact.add_argument('--dsn', default='dbname=fantasy_football')
    compact.add_argument('--apply', action='store_true', help='Replace verified legacy manifests; the default only verifies.')
    args = parser.parse_args(argv)
    if args.command == 'sync' and args.interval != 0 and not 1 <= args.interval <= 86400:
        parser.error('The interval must be zero or from 1 through 86400 seconds.')
    while True:
        incremental = (args.command == 'sync' and not args.legacy_full) or (args.command == 'export' and args.incremental)
        if args.command == 'export' and not incremental:
            path = Path(args.manifest)
            bundle = export_bundle(json.loads(path.read_text(encoding='utf-8-sig')), base_dir=path.parent)
            Path(args.output).write_text(_json(bundle) + '\n', encoding='utf-8')
            print(_json({'bundle_id': bundle['bundle_id'], 'records': len(bundle['records']), 'labels': len(bundle['labels'])}))
            return 0
        try:
            import psycopg
        except ImportError as exc:
            raise ArchiveError('Install the server extra before using PostgreSQL archive checkpoints or imports.') from exc
        if args.command == 'import':
            bundle = json.loads(Path(args.bundle).read_text(encoding='utf-8'))
        elif args.command == 'sync' and not incremental:
            path = Path(args.manifest)
            bundle = export_bundle(json.loads(path.read_text(encoding='utf-8-sig')), base_dir=path.parent)
        with psycopg.connect(args.dsn, autocommit=True) as connection:
            if args.command == 'compact-receipts':
                print(_json(compact_receipts(connection, apply=args.apply)), flush=True)
                return 0
            if incremental:
                path = Path(args.manifest)
                bundle = export_incremental_bundle(connection, json.loads(path.read_text(encoding='utf-8-sig')),
                                                   base_dir=path.parent, batch_size=args.batch_size)
            if args.command == 'export':
                Path(args.output).write_text(_json(bundle) + '\n', encoding='utf-8')
                print(_json({'bundle_id': bundle['bundle_id'], 'records': len(bundle['records']),
                             'labels': len(bundle['labels']), 'has_more': bundle['has_more']}))
                return 0
            result = import_bundle(connection, bundle)
        print(_json({'bundle_id': bundle['bundle_id'], 'inserted': result, 'has_more': bundle.get('has_more', False)}), flush=True)
        if args.command == 'sync' and args.drain and bundle.get('has_more'):
            continue
        if args.command != 'sync' or args.interval == 0:
            return 0
        time.sleep(args.interval)


if __name__ == '__main__':
    raise SystemExit(main())
