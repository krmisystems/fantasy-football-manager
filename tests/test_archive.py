"""Archive tests use fictional identifiers, temporary databases, and no network."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

import pytest

from fantasy_football_manager import archive
from fantasy_football_manager.models import ManagerConfig


def snapshot(phase='draft'):
    now = datetime.now(timezone.utc).isoformat()
    players = [{'id': pid, 'name': f'Fictional Player {pid}', 'position': pos, 'projection': 100,
                'weekly_projection': None, 'availability': 'ACTIVE'}
               for pid, pos in [('101', 'RB'), ('102', 'RB'), ('-33', 'DST'), ('103', 'RB')]]
    return {'league_id': '123', 'team_id': '11', 'season': 2026, 'phase': phase, 'week': 1,
            'source': {'provider': 'espn_browser', 'synthetic': False, 'observed_at': now,
                       'projections_observed_at': now, 'locks_verified': False,
                       'notes': ['Private operator note'],
                       'browser': {'page_url': 'https://fantasy.espn.com/football/draft?leagueId=123&teamId=11&seasonId=2026&memberId=fictional-account',
                                   'league_id': '123', 'team_id': '11', 'current_pick': 5,
                                   'draft_complete': True, 'autopick_enabled': None}},
            'rules': {'teams': 2, 'slot': 1, 'rounds': 2, 'starters': {'RB': 1}, 'bench': 1, 'ir': 1,
                      'caps': {'QB': 1, 'RB': 2, 'WR': 2, 'TE': 1, 'DST': 1, 'K': 1}},
            'players': players,
            'teams': [{'id': '11', 'name': 'Private Fictional Club A', 'slot': 1, 'roster_ids': ['101', '103']},
                      {'id': '22', 'name': 'Private Fictional Club B', 'slot': 2, 'roster_ids': ['102', '-33']}],
            'picks': [{'pick_no': n, 'player_id': pid, 'slot': slot}
                      for n, pid, slot in [(1, '101', 1), (2, '102', 2), (3, '-33', 2), (4, '103', 1)]]}


def write_db(path, raw=None):
    raw = raw or snapshot()
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE state(id INTEGER PRIMARY KEY,snapshot TEXT,revision INTEGER,config TEXT,config_revision INTEGER);
            CREATE TABLE audit(id INTEGER PRIMARY KEY,at TEXT,event TEXT,detail TEXT);
            CREATE TABLE browser_proposals(id TEXT PRIMARY KEY,league_id TEXT,team_id TEXT,season INTEGER,
            revision INTEGER,config_revision INTEGER,baseline TEXT,decision TEXT,status TEXT,created_at TEXT,authorized_at TEXT,result TEXT);
            CREATE TABLE ffm_archive_outbox(id INTEGER PRIMARY KEY,at TEXT,event TEXT,detail TEXT);''')
        db.execute('INSERT INTO state VALUES(1,?,1,?,0)', (json.dumps(raw), ManagerConfig().model_dump_json()))
        db.execute('INSERT INTO audit VALUES(1,?,?,?)', (raw['source']['observed_at'], 'snapshot_imported', json.dumps({'revision': 1, 'synthetic': False})))
    return path


@pytest.fixture
def manifest(tmp_path):
    path = write_db(tmp_path / 'source.sqlite3')
    return {'schema_version': 1, 'sources': [{'source_id': 'fictional-source',
                'run': {'run_id': 'fictional-backfill', 'label': 'Fictional backfill', 'kind': 'backfill',
                        'runtime_version': None, 'code_revision': None},
                'context': {'league_id': '123', 'team_id': '11', 'season': 2026}, 'database': str(path)}]}


def rehash(bundle):
    for row in bundle['records']:
        row['payload_sha256'] = archive._hash(row['payload'])
        row['record_id'] = archive._hash({k: v for k, v in row.items() if k != 'record_id'})
    bundle['manifest'] = archive._bundle_manifest(bundle)
    bundle['bundle_id'] = archive._hash(bundle['manifest'])


def test_export_preserves_evidence_without_private_navigation_or_names(manifest):
    bundle = archive.export_bundle(manifest)
    text = json.dumps(bundle)
    assert 'fictional-account' not in text and 'memberId' not in text
    assert 'Private Fictional Club' not in text and 'Private operator note' not in text
    assert manifest['sources'][0]['database'] not in text
    records = [r for r in bundle['records'] if r['kind'] == 'draft_pick']
    assert len(records) == 4 and any(r['payload']['player_id'] == '-33' for r in records)
    archived = next(r['payload'] for r in bundle['records'] if r['kind'] == 'snapshot')
    assert archived['players'][0]['weekly_projection'] is None
    assert archived['source']['browser']['autopick_enabled'] is None
    assert archived['source']['locks_scope'] == 'selected_team'
    assert archived['teams'][0]['name'] == 'Team 1'
    assert {r['value'] for r in bundle['labels'] if r['key'] == 'executor'} == {'unknown'}


def test_export_leaves_database_bytes_and_rows_unchanged(manifest):
    path = Path(manifest['sources'][0]['database'])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    first = archive.export_bundle(manifest)
    second = archive.export_bundle(manifest)
    assert first['bundle_id'] == second['bundle_id']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert first['records'] == second['records']


def test_import_is_idempotent_and_preserves_schema(manifest):
    bundle = archive.export_bundle(manifest)
    with sqlite3.connect(':memory:') as db:
        first = archive.import_bundle(db, bundle)
        assert first['records'] == len(bundle['records']) and first['imports'] == 1
        assert archive.import_bundle(db, bundle) == {'runs': 0, 'records': 0, 'labels': 0, 'imports': 0}
        assert db.execute('SELECT count(*) FROM archive_records').fetchone()[0] == len(bundle['records'])


def test_conflicting_run_metadata_rolls_back_complete_import(manifest):
    bundle = archive.export_bundle(manifest)
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, bundle)
        changed = deepcopy(manifest)
        changed['sources'][0]['run']['label'] = 'Changed historical claim'
        bad = archive.export_bundle(changed)
        before = db.execute('SELECT count(*) FROM archive_records').fetchone()[0]
        with pytest.raises(archive.ArchiveError, match='immutable'):
            archive.import_bundle(db, bad)
        assert db.execute('SELECT count(*) FROM archive_records').fetchone()[0] == before
        assert db.execute('SELECT count(*) FROM archive_imports').fetchone()[0] == 1


def test_database_failure_rolls_back_inserted_run_records_and_import(manifest):
    bundle = archive.export_bundle(manifest)
    with sqlite3.connect(':memory:') as db:
        for ddl in archive.DDL:
            db.execute(ddl)
        db.execute("CREATE TRIGGER reject_record BEFORE INSERT ON archive_records BEGIN SELECT RAISE(ABORT,'fictional failure'); END")
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            archive.import_bundle(db, bundle)
        assert db.execute('SELECT count(*) FROM archive_runs').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM archive_imports').fetchone()[0] == 0


@pytest.mark.parametrize('change', ['payload', 'reference', 'duplicate', 'scope'])
def test_bundle_tampering_rejected_before_writes(manifest, change):
    bundle = archive.export_bundle(manifest)
    if change == 'payload':
        bundle['records'][0]['payload']['status'] = 'changed'
    elif change == 'reference':
        bundle['labels'][0]['record_id'] = 'missing'
    elif change == 'duplicate':
        bundle['records'].append(deepcopy(bundle['records'][0]))
    else:
        bundle['records'][0]['context']['league_id'] = '456'
    with sqlite3.connect(':memory:') as db:
        with pytest.raises(archive.ArchiveError):
            archive.import_bundle(db, bundle)
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 0


def test_rehashed_private_payload_still_rejected(manifest):
    bundle = archive.export_bundle(manifest)
    bundle['labels'] = []
    next(r for r in bundle['records'] if r['kind'] == 'config')['payload']['cookies'] = {'account': 'fictional'}
    rehash(bundle)
    with pytest.raises(archive.ArchiveError, match='sanitized'):
        archive.validate_bundle(bundle)


@pytest.mark.parametrize('status,authorized', [('confirmed', True), ('not_selected', True), ('pending', False)])
def test_proposal_result_never_infers_causal_executor(manifest, status, authorized):
    raw = snapshot()
    at = raw['source']['observed_at']
    result = {'status': status, 'observed_at': at, 'actual_pick': raw['picks'][-1]} if status != 'pending' else None
    with sqlite3.connect(manifest['sources'][0]['database']) as db:
        db.execute('INSERT INTO browser_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('fictional-proposal', '123', '11', 2026, 1, 0, json.dumps(raw),
                    json.dumps({'payload': {'player_id': '103'}}), status, at, at if authorized else None, json.dumps(result) if result else None))
    bundle = archive.export_bundle(manifest)
    proposal = next(r for r in bundle['records'] if r['kind'] == 'proposal')
    labels = {r['key']: r['value'] for r in bundle['labels'] if r['record_id'] == proposal['record_id']}
    assert labels['executor'] == 'unknown'
    assert labels['authorization'] == ('persisted' if authorized else 'absent')
    assert labels['reconciliation'] == (status if status != 'pending' else 'unresolved')


def test_operator_autopick_label_requires_exact_observed_pick(manifest):
    manifest['operator_labels'] = [{'source_id': 'fictional-source', 'kind': 'draft_pick', 'pick_no': 1,
                                    'key': 'executor', 'value': 'espn_autopick', 'evidence_type': 'operator_observation'}]
    bundle = archive.export_bundle(manifest)
    explicit = [r for r in bundle['labels'] if r['evidence_type'] == 'operator_observation']
    assert len(explicit) == 1 and explicit[0]['value'] == 'espn_autopick'
    manifest['operator_labels'][0]['pick_no'] = 5
    with pytest.raises(archive.ArchiveError, match='exactly one'):
        archive.export_bundle(manifest)


def test_scope_mismatch_in_separate_dataset_rejected(manifest, tmp_path):
    path = tmp_path / 'other.json'
    value = snapshot(); value['league_id'] = '456'
    path.write_text(json.dumps(value))
    manifest['sources'][0]['datasets'] = [{'dataset_id': 'other', 'format': 'snapshot', 'path': str(path)}]
    with pytest.raises(ValueError):
        archive.export_bundle(manifest)


def test_raw_capture_or_profile_dataset_is_not_supported(manifest, tmp_path):
    path = tmp_path / 'room.html'; path.write_text('<p>Fictional private page</p>')
    manifest['sources'][0]['datasets'] = [{'dataset_id': 'raw', 'format': 'html', 'path': str(path)}]
    with pytest.raises(archive.ArchiveError, match='structured'):
        archive.export_bundle(manifest)


def test_outbox_snapshot_and_submission_fields_survive_without_false_confirmation(manifest):
    from fantasy_football_manager import evidence
    from fantasy_football_manager.models import LeagueSnapshot
    raw = LeagueSnapshot.model_validate(snapshot())
    detail = evidence.envelope(raw, ManagerConfig(), 4, 2, include_snapshot=True)
    detail['submission'] = {'returned': True, 'result': {'clicked': True, 'uncertain': True},
                            'confirmation_scope': 'requires_platform_reconciliation'}
    detail['action'] = {'proposal_id': 'fictional-proposal', 'action': 'draft_pick'}
    with sqlite3.connect(manifest['sources'][0]['database']) as db:
        db.execute('INSERT INTO ffm_archive_outbox VALUES(1,?,?,?)', (raw.source.observed_at.isoformat(), 'browser_submission_returned', json.dumps(detail)))
    bundle = archive.export_bundle(manifest)
    row = next(r for r in bundle['records'] if r['source_key'] == 'outbox:1')
    assert row['payload']['application_version'] and row['payload']['input_fingerprint']
    assert row['payload']['submission']['result'] == {'clicked': True, 'uncertain': True}
    labels = {r['key']: r['value'] for r in bundle['labels'] if r['record_id'] == row['record_id']}
    assert labels == {'submission_returned': True, 'click_returned': True}


def test_runtime_error_is_classified_and_secret_fields_are_removed(manifest, tmp_path):
    token = 'ghp_' + 'x' * 36
    local = 'C:' + '/Users/' + 'FictionalName/private'
    row = {'event': 'status', 'at': datetime.now(timezone.utc).isoformat(),
           'error': 'Search failed at ' + local + ' ' + token,
           'runtime': {'headers': {'Authorization': token}, 'memberId': 'fictional-account',
                       'status': 'needs_attention', 'data_dir': local}}
    path = tmp_path / 'runtime.jsonl'; path.write_text(json.dumps(row) + '\n')
    manifest['sources'][0]['datasets'] = [{'dataset_id': 'runtime', 'format': 'runtime_jsonl', 'path': str(path)}]
    bundle = archive.export_bundle(manifest)
    text = json.dumps(bundle)
    assert token not in text and local not in text and 'fictional-account' not in text
    assert any(r['payload'].get('failure_code') == 'player_search' for r in bundle['records'])


def test_missing_time_remains_unknown_and_future_time_is_rejected(manifest, tmp_path):
    path = tmp_path / 'events.json'; path.write_text(json.dumps([{'event': 'status', 'detail': {'status': 'observed'}}]))
    manifest['sources'][0]['datasets'] = [{'dataset_id': 'events', 'format': 'audit_json', 'path': str(path)}]
    bundle = archive.export_bundle(manifest)
    row = next(r for r in bundle['records'] if r['source_key'].startswith('dataset:events'))
    assert row['observed_at'] is None and row['recorded_at'] is None
    path.write_text(json.dumps([{'event': 'status', 'at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), 'detail': {}}]))
    with pytest.raises(archive.ArchiveError, match='future'):
        archive.export_bundle(manifest)


def test_updated_proposal_adds_new_evidence_without_overwriting_pending(manifest):
    raw = snapshot(); at = raw['source']['observed_at']
    path = manifest['sources'][0]['database']
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO browser_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                   ('fictional-proposal', '123', '11', 2026, 1, 0, json.dumps(raw),
                    json.dumps({'payload': {'player_id': '103'}}), 'pending', at, None, None))
    before = archive.export_bundle(manifest)
    with sqlite3.connect(path) as db:
        db.execute('UPDATE browser_proposals SET status=?,authorized_at=?,result=?',
                   ('confirmed', at, json.dumps({'status': 'confirmed', 'observed_at': at})))
    after = archive.export_bundle(manifest)
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, before); archive.import_bundle(db, after)
        statuses = [json.loads(row[0])['status'] for row in db.execute("SELECT payload FROM archive_records WHERE kind='proposal'")]
        assert sorted(statuses) == ['confirmed', 'pending']


def test_conflicting_operator_labels_are_rejected(manifest):
    first = {'source_id': 'fictional-source', 'kind': 'draft_pick', 'pick_no': 1,
             'key': 'executor', 'value': 'espn_autopick', 'evidence_type': 'operator_observation'}
    manifest['operator_labels'] = [first, {**first, 'value': 'manual'}]
    with pytest.raises(archive.ArchiveError, match='conflict'):
        archive.export_bundle(manifest)


def test_outbox_calculation_keeps_trial_provenance_and_acceptance_scope(manifest):
    detail = {'schema_version': 1, 'context': manifest['sources'][0]['context'],
              'calculation': {'kind': 'draft', 'seed': 7, 'requested_trials': 40, 'completed_trials': 32,
                              'accepted': True, 'disposition': 'current', 'work_scope': 'single_completed_call',
                              'acceptance_scope': 'current_calculation_not_action_permission',
                              'selection_causality': 'not_inferred', 'result': {'trials': 32}}}
    with sqlite3.connect(manifest['sources'][0]['database']) as db:
        db.execute('INSERT INTO ffm_archive_outbox VALUES(1,?,?,?)',
                   (datetime.now(timezone.utc).isoformat(), 'calculation_completed', json.dumps(detail)))
    bundle = archive.export_bundle(manifest)
    row = next(r for r in bundle['records'] if r['kind'] == 'recommendation')
    assert row['payload']['calculation'] == detail['calculation']


@pytest.mark.skipif(not os.environ.get('FFM_ARCHIVE_TEST_DSN'), reason='Set an explicit PostgreSQL test DSN to run this isolated integration.')
def test_postgresql_atomic_import_and_idempotence(manifest):
    psycopg = pytest.importorskip('psycopg')
    from psycopg import sql
    schema = 'ffm_archive_test_' + uuid.uuid4().hex
    bundle = archive.export_bundle(manifest)
    with psycopg.connect(os.environ['FFM_ARCHIVE_TEST_DSN'], autocommit=True) as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            db.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            assert archive.import_bundle(db, bundle)['records'] == len(bundle['records'])
            assert archive.import_bundle(db, bundle) == {'runs': 0, 'records': 0, 'labels': 0, 'imports': 0}
            changed = deepcopy(manifest)
            changed['sources'][0]['run']['label'] = 'Conflicting test claim'
            with pytest.raises(archive.ArchiveError, match='immutable'):
                archive.import_bundle(db, archive.export_bundle(changed))
            assert db.execute('SELECT count(*) FROM archive_imports').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM archive_records').fetchone()[0] == len(bundle['records'])
        finally:
            db.execute('SET search_path TO public')
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
