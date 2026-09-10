"""Incremental archive behavior with fictional data and temporary databases."""

from copy import deepcopy
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import types
import uuid

import pytest

from fantasy_football_manager import archive
from test_archive import manifest, snapshot, write_db


ZERO = {'runs': 0, 'records': 0, 'labels': 0, 'imports': 0}


def append_events(manifest, count, table='ffm_archive_outbox', at=None):
    with sqlite3.connect(manifest['sources'][0]['database']) as source:
        start = source.execute(f'SELECT COALESCE(MAX(id),0) FROM {table}').fetchone()[0]
        for index in range(start + 1, start + count + 1):
            source.execute(f'INSERT INTO {table} VALUES(?,?,?,?)',
                           (index, at, 'calculation_completed', json.dumps({'calculation': {'seed': index,
                            'requested_trials': 40, 'completed_trials': 32, 'accepted': True,
                            'selection_causality': 'not_inferred'}})))


def export(db, manifest, size=2):
    return archive.export_incremental_bundle(db, manifest, batch_size=size)


def checkpoint(db):
    return json.loads(db.execute('SELECT payload FROM archive_source_checkpoints').fetchone()[0])


def rehash(bundle):
    bundle['manifest'] = archive._bundle_manifest(bundle)
    bundle['bundle_id'] = archive._hash(bundle['manifest'])


def refresh_timestamps(manifest, seconds=1, edit=None):
    with sqlite3.connect(manifest['sources'][0]['database']) as source:
        raw = json.loads(source.execute('SELECT snapshot FROM state WHERE id=1').fetchone()[0])
        for key in ('observed_at', 'projections_observed_at'):
            raw['source'][key] = (datetime.fromisoformat(raw['source'][key].replace('Z', '+00:00'))
                                  + timedelta(seconds=seconds)).isoformat()
        if edit:
            edit(raw)
        source.execute('UPDATE state SET snapshot=? WHERE id=1', (json.dumps(raw),))
    return raw


def legacy_checkpoint_bundle(db, manifest, size=2):
    bundle = export(db, manifest, size)
    with sqlite3.connect(manifest['sources'][0]['database']) as source:
        raw = json.loads(source.execute('SELECT snapshot FROM state WHERE id=1').fetchone()[0])
    state = bundle['checkpoints'][0]['state']['database']
    for key in ('snapshot_hash_format', 'snapshot_observed_at', 'snapshot_projections_observed_at'):
        state.pop(key)
    state['snapshot_sha256'] = archive._hash(raw)
    rehash(bundle)
    return bundle


def test_live_refresh_path_during_multibatch_export_preserves_decision_revision(manifest, tmp_path):
    from fantasy_football_manager.espn_service import ESPNService
    service = ESPNService(tmp_path / 'runtime', browser=types.SimpleNamespace(transport='http'))
    service.manager.import_snapshot(snapshot(), 0)
    manifest['sources'][0]['database'] = str(service.manager.path)
    append_events(manifest, 6, at=service.manager.state()[0].source.observed_at.isoformat())
    with sqlite3.connect(':memory:') as db:
        first_hash = None
        while True:
            bundle = export(db, manifest, 2)
            observed, _, revision, _ = service.manager.state()
            refreshed = observed.model_dump(mode='json')
            for key in ('observed_at', 'projections_observed_at'):
                refreshed['source'][key] = (datetime.fromisoformat(refreshed['source'][key].replace('Z', '+00:00'))
                                            + timedelta(seconds=1)).isoformat()
            result = service._accept_observation(refreshed, revision)
            assert result['status'] == 'refreshed' and result['revision'] == revision == 1
            archive.import_bundle(db, bundle)
            saved = checkpoint(db)['database']
            assert saved['snapshot_hash_format'] == archive.SNAPSHOT_HASH_FORMAT
            first_hash = first_hash or saved['snapshot_sha256']
            assert saved['snapshot_sha256'] == first_hash
            if not bundle['has_more']:
                break
        archive.import_bundle(db, export(db, manifest, 20))
        assert checkpoint(db)['database']['revision'] == 1
        assert checkpoint(db)['streams']['ffm_archive_outbox']['count'] >= 6
        assert db.execute("SELECT count(*) FROM archive_records WHERE source_key='state:1' AND kind='snapshot'").fetchone()[0] == 1
        assert archive.import_bundle(db, export(db, manifest, 20)) == ZERO


@pytest.mark.parametrize('change', ['projection', 'rules', 'roster', 'lock'])
def test_refresh_hash_keeps_every_non_timestamp_decision_input(manifest, change):
    edits = {'projection': lambda raw: raw['players'][0].update(projection=999),
             'rules': lambda raw: raw['rules']['starters'].update(RB=2),
             'roster': lambda raw: raw['teams'][0]['roster_ids'].reverse(),
             'lock': lambda raw: raw['source'].update(locks_verified=True)}
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest))
        before = checkpoint(db)
        refresh_timestamps(manifest, edit=edits[change])
        with pytest.raises(archive.ArchiveError, match='continuity'):
            export(db, manifest)
        assert checkpoint(db) == before


def test_refresh_timestamps_cannot_move_backward_at_same_revision(manifest):
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest))
        refresh_timestamps(manifest)
        archive.import_bundle(db, export(db, manifest))
        before = checkpoint(db)
        refresh_timestamps(manifest, seconds=-1)
        with pytest.raises(archive.ArchiveError, match='timestamp moved backward'):
            export(db, manifest)
        assert checkpoint(db) == before


def test_legacy_hash_upgrade_requires_source_proof_and_preserves_replay(manifest):
    append_events(manifest, 4)
    with sqlite3.connect(':memory:') as db:
        old_bundle = legacy_checkpoint_bundle(db, manifest)
        archive.import_bundle(db, old_bundle)
        before = checkpoint(db)
        refresh_timestamps(manifest)
        upgrade = export(db, manifest)
        assert checkpoint(db) == before
        assert str(manifest['sources'][0]['database']) not in json.dumps(upgrade)
        with pytest.raises(archive.ArchiveError, match='private source manifest'):
            archive.import_bundle(db, upgrade)
        assert checkpoint(db) == before
        archive.import_bundle(db, upgrade, source_manifest=manifest)
        assert checkpoint(db)['database']['snapshot_hash_format'] == archive.SNAPSHOT_HASH_FORMAT
        assert checkpoint(db)['streams']['ffm_archive_outbox']['count'] == 4
        assert archive.import_bundle(db, old_bundle) == ZERO
        assert archive.import_bundle(db, upgrade) == ZERO


def test_legacy_hash_upgrade_resolves_relative_manifest_and_database_paths(manifest, tmp_path, monkeypatch):
    append_events(manifest, 4)
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, legacy_checkpoint_bundle(db, manifest))
        before = checkpoint(db)
        refresh_timestamps(manifest)
        relative_sources = deepcopy(manifest)
        relative_sources['sources'][0]['database'] = 'source.sqlite3'
        (tmp_path / 'manifest.json').write_text(json.dumps(relative_sources), encoding='utf-8')
        monkeypatch.chdir(tmp_path.parent)
        manifest_path = Path(tmp_path.name) / 'manifest.json'
        loaded = json.loads(manifest_path.read_text(encoding='utf-8'))
        upgrade = archive.export_incremental_bundle(db, loaded, base_dir=manifest_path.parent, batch_size=2)
        archive.import_bundle(db, upgrade, source_manifest=loaded, base_dir=manifest_path.parent)
        after = checkpoint(db)
        assert after['database']['snapshot_hash_format'] == archive.SNAPSHOT_HASH_FORMAT
        assert after['database']['revision'] == before['database']['revision']
        assert after['source_epoch'] == before['source_epoch']
        assert after['selection_sha256'] == before['selection_sha256']
        assert after['sequence'] == before['sequence'] + 1
        assert after['streams']['ffm_archive_outbox']['count'] == 4
        assert archive.import_bundle(db, upgrade) == ZERO


@pytest.mark.parametrize('failure', ['missing_evidence', 'changed_decision', 'timestamp_rollback'])
def test_legacy_hash_upgrade_refuses_unproven_reconstruction(manifest, failure):
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, legacy_checkpoint_bundle(db, manifest))
        before = checkpoint(db)
        if failure == 'missing_evidence':
            db.execute("DELETE FROM archive_records WHERE kind='snapshot'")
            db.commit()
            refresh_timestamps(manifest)
        elif failure == 'changed_decision':
            refresh_timestamps(manifest, edit=lambda raw: raw['players'][0].update(projection=999))
        else:
            refresh_timestamps(manifest, seconds=-1)
        with pytest.raises(archive.ArchiveError, match='continuity'):
            export(db, manifest)
        assert checkpoint(db) == before


def test_legacy_upgrade_rechecks_source_after_export_and_before_commit(manifest):
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, legacy_checkpoint_bundle(db, manifest))
        before = checkpoint(db)
        refresh_timestamps(manifest)
        upgrade = export(db, manifest)
        refresh_timestamps(manifest, edit=lambda raw: raw['players'][0].update(projection=999))
        with pytest.raises(archive.ArchiveError, match='source changed before'):
            archive.import_bundle(db, upgrade, source_manifest=manifest)
        assert checkpoint(db) == before
        assert db.execute('SELECT count(*) FROM archive_imports').fetchone()[0] == 1


def test_legacy_upgrade_rechecks_forged_hash_even_with_a_manifest(manifest):
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, legacy_checkpoint_bundle(db, manifest))
        before = checkpoint(db)
        refresh_timestamps(manifest)
        upgrade = export(db, manifest)
        upgrade['checkpoints'][0]['state']['database']['snapshot_sha256'] = '0' * 64
        rehash(upgrade)
        with pytest.raises(archive.ArchiveError, match='source changed before'):
            archive.import_bundle(db, upgrade, source_manifest=manifest)
        assert checkpoint(db) == before


def test_new_snapshot_hash_format_cannot_downgrade_or_accept_unknown_format(manifest):
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest))
        before = checkpoint(db)
        refresh_timestamps(manifest)
        bundle = export(db, manifest)
        state = bundle['checkpoints'][0]['state']['database']
        state['snapshot_hash_format'] = 'unverified-v2'
        rehash(bundle)
        with pytest.raises(archive.ArchiveError, match='unsupported snapshot hash format'):
            archive.import_bundle(db, bundle)
        for key in ('snapshot_hash_format', 'snapshot_observed_at', 'snapshot_projections_observed_at'):
            state.pop(key)
        rehash(bundle)
        with pytest.raises(archive.ArchiveError, match='downgrade'):
            archive.import_bundle(db, bundle)
        assert checkpoint(db) == before


@pytest.mark.skipif(not os.environ.get('FFM_ARCHIVE_TEST_DSN'), reason='An explicit isolated PostgreSQL test DSN is required.')
def test_postgres_legacy_refresh_upgrade_rolls_back_and_replays(manifest):
    import psycopg
    from psycopg import sql
    schema = 'test_archive_refresh_' + uuid.uuid4().hex
    append_events(manifest, 4)
    with psycopg.connect(os.environ['FFM_ARCHIVE_TEST_DSN'], autocommit=True) as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            db.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            legacy = legacy_checkpoint_bundle(db, manifest)
            archive.import_bundle(db, legacy)
            previous = checkpoint(db)
            refresh_timestamps(manifest)
            upgraded = export(db, manifest)
            with pytest.raises(archive.ArchiveError, match='private source manifest'):
                archive.import_bundle(db, upgraded)
            db.execute("ALTER TABLE archive_source_checkpoints ADD CONSTRAINT reject_upgrade CHECK ((payload::json->'database'->>'snapshot_hash_format') IS NULL)")
            count = db.execute('SELECT count(*) FROM archive_records').fetchone()[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                archive.import_bundle(db, upgraded, source_manifest=manifest)
            assert checkpoint(db) == previous
            assert db.execute('SELECT count(*) FROM archive_records').fetchone()[0] == count
            db.execute('ALTER TABLE archive_source_checkpoints DROP CONSTRAINT reject_upgrade')
            archive.import_bundle(db, upgraded, source_manifest=manifest)
            assert checkpoint(db)['database']['snapshot_hash_format'] == archive.SNAPSHOT_HASH_FORMAT
            assert checkpoint(db)['streams']['ffm_archive_outbox']['count'] == 4
            assert archive.import_bundle(db, legacy) == ZERO
            assert archive.import_bundle(db, upgraded) == ZERO
        finally:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def test_bounded_batches_cover_legacy_records_and_labels_exactly(manifest):
    append_events(manifest, 7)
    legacy = archive.export_bundle(manifest)
    before = hashlib.sha256(Path(manifest['sources'][0]['database']).read_bytes()).hexdigest()
    with sqlite3.connect(':memory:') as db:
        bundle_ids = []
        for expected_cursor in (2, 4, 6, 7):
            bundle = export(db, manifest)
            event_records = [row for row in bundle['records'] if row['source_key'].startswith('outbox:')]
            assert 1 <= len(event_records) <= 2
            assert all(row['payload']['calculation']['completed_trials'] == 32 for row in event_records)
            assert all(row['payload']['calculation']['selection_causality'] == 'not_inferred' for row in event_records)
            archive.import_bundle(db, bundle)
            assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == expected_cursor
            bundle_ids.append(bundle['bundle_id'])
        assert len(set(bundle_ids)) == 4
        assert {row[0] for row in db.execute('SELECT record_id FROM archive_records')} == {row['record_id'] for row in legacy['records']}
        assert {row[0] for row in db.execute('SELECT label_id FROM archive_labels')} == {row['label_id'] for row in legacy['labels']}
        manifests = [json.loads(row[0]) for row in db.execute('SELECT manifest FROM archive_imports')]
        assert all(item['schema_version'] == 2 and isinstance(item['records'], dict) for item in manifests)
        assert max(len(archive._json(item)) for item in manifests) < 650
        idle = export(db, manifest)
        assert idle['records'] == idle['labels'] == idle['checkpoints'] == []
        assert not idle['has_more']
        assert archive.import_bundle(db, idle) == ZERO
        assert db.execute('SELECT count(*) FROM archive_imports').fetchone()[0] == 4
        assert archive.import_bundle(db, bundle) == ZERO
    assert hashlib.sha256(Path(manifest['sources'][0]['database']).read_bytes()).hexdigest() == before


def test_legacy_archive_bootstrap_does_not_duplicate_evidence(manifest):
    append_events(manifest, 4)
    legacy = archive.export_bundle(manifest)
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, legacy)
        old_receipt = db.execute('SELECT manifest FROM archive_imports WHERE bundle_id=?', (legacy['bundle_id'],)).fetchone()[0]
        while True:
            bundle = export(db, manifest)
            added = archive.import_bundle(db, bundle)
            assert added['records'] == added['labels'] == added['runs'] == 0
            if not bundle['has_more']:
                break
        assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == 4
        assert db.execute('SELECT manifest FROM archive_imports WHERE bundle_id=?', (legacy['bundle_id'],)).fetchone()[0] == old_receipt
        assert archive.import_bundle(db, legacy) == ZERO


@pytest.mark.parametrize('failing_table', ['archive_records', 'archive_imports', 'archive_source_checkpoints', 'archive_source_objects'])
def test_failed_import_never_acknowledges_a_batch(manifest, failing_table):
    with sqlite3.connect(manifest['sources'][0]['database']) as source:
        raw = snapshot()
        source.execute('INSERT INTO browser_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('proposal-1', '123', '11', 2026, 1, 0, json.dumps(raw), '{}', 'pending', None, None, None))
    with sqlite3.connect(':memory:') as db:
        for statement in archive.DDL:
            db.execute(statement)
        db.execute(f"CREATE TRIGGER reject_write BEFORE INSERT ON {failing_table} BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        db.commit()
        before = export(db, manifest)
        assert db.execute('SELECT count(*) FROM archive_source_checkpoints').fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError, match='injected failure'):
            archive.import_bundle(db, before)
        for table in ('archive_runs', 'archive_records', 'archive_labels', 'archive_imports', 'archive_source_checkpoints', 'archive_source_objects'):
            assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
        retry = export(db, manifest)
        assert retry['bundle_id'] == before['bundle_id']
        db.execute('DROP TRIGGER reject_write')
        db.commit()
        archive.import_bundle(db, retry)
        assert checkpoint(db)['sequence'] == 1


def test_new_events_after_export_wait_for_next_committed_batch(manifest):
    append_events(manifest, 1)
    with sqlite3.connect(':memory:') as db:
        first = export(db, manifest)
        append_events(manifest, 1)
        assert not archive._has_table(db, 'archive_source_checkpoints')
        archive.import_bundle(db, first)
        assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == 1
        second = export(db, manifest)
        assert [row['source_key'] for row in second['records']] == ['outbox:2']
        archive.import_bundle(db, second)
        assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == 2
        # A replay after newer commits must not move the checkpoint backward.
        assert archive.import_bundle(db, first) == ZERO
        assert checkpoint(db)['sequence'] == 2


def test_stale_concurrent_export_is_rejected_without_partial_writes(manifest):
    append_events(manifest, 3)
    with sqlite3.connect(':memory:') as db:
        short = export(db, manifest, 1)
        stale = export(db, manifest, 3)
        archive.import_bundle(db, short)
        before = db.execute('SELECT count(*) FROM archive_records').fetchone()[0]
        with pytest.raises(archive.ArchiveError, match='stale'):
            archive.import_bundle(db, stale)
        assert db.execute('SELECT count(*) FROM archive_records').fetchone()[0] == before
        assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == 1
        archive.import_bundle(db, export(db, manifest, 3))
        assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == 3


@pytest.mark.parametrize('change', ['revision', 'snapshot_same_revision', 'config_revision', 'deleted_tail', 'changed_first', 'deleted_interior', 'dropped_table', 'replaced_database'])
def test_source_rollback_and_replacement_stop_before_checkpoint_advance(manifest, change):
    append_events(manifest, 3)
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest, 10))
        previous = checkpoint(db)
        path = Path(manifest['sources'][0]['database'])
        if change == 'replaced_database':
            replacement = write_db(path.parent / 'replacement.sqlite3')
            manifest['sources'][0]['database'] = str(replacement)
        else:
            with sqlite3.connect(path) as source:
                operations = {
                    'revision': 'UPDATE state SET revision=0',
                    'snapshot_same_revision': "UPDATE state SET snapshot=NULL",
                    'config_revision': 'UPDATE state SET config_revision=-1',
                    'deleted_tail': 'DELETE FROM ffm_archive_outbox WHERE id=3',
                    'changed_first': "UPDATE ffm_archive_outbox SET detail='{}' WHERE id=1",
                    'deleted_interior': 'DELETE FROM ffm_archive_outbox WHERE id=2',
                    'dropped_table': 'DROP TABLE ffm_archive_outbox',
                }
                source.execute(operations[change])
        with pytest.raises(archive.ArchiveError):
            export(db, manifest, 10)
        assert checkpoint(db) == previous


@pytest.mark.parametrize('field', ['source_epoch', 'context', 'run', 'datasets'])
def test_checkpoint_source_selection_is_immutable(manifest, field):
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest))
        changed = deepcopy(manifest)
        source = changed['sources'][0]
        if field == 'source_epoch':
            source[field] = 'replacement-002'
        elif field == 'context':
            source[field]['team_id'] = '22'
        elif field == 'run':
            source[field]['label'] = 'Changed claim'
        else:
            source[field] = [{'dataset_id': 'extra', 'format': 'snapshot', 'path': 'absent.json'}]
        with pytest.raises(archive.ArchiveError, match='continuity'):
            export(db, changed)


def test_same_external_run_and_row_ids_keep_two_sources_separate(manifest):
    second = deepcopy(manifest['sources'][0])
    second['source_id'] = 'fictional-source-two'
    manifest['sources'].append(second)
    with sqlite3.connect(':memory:') as db:
        bundle = export(db, manifest)
        assert len(bundle['checkpoints']) == 2
        archive.import_bundle(db, bundle)
        assert db.execute('SELECT count(*) FROM archive_source_checkpoints').fetchone()[0] == 2
        counts = dict(db.execute('SELECT source_id,count(*) FROM archive_records GROUP BY source_id'))
        assert counts['fictional-source'] == counts['fictional-source-two'] > 0
        assert all(label['value'] == 'unknown' for label in bundle['labels'] if label['key'] == 'executor')


def test_proposal_status_updates_keep_both_versions_and_original_labels(manifest):
    raw = snapshot()
    with sqlite3.connect(manifest['sources'][0]['database']) as source:
        source.execute('INSERT INTO browser_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('proposal-1', '123', '11', 2026, 1, 0, json.dumps(raw), '{}', 'pending', None, None, None))
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest))
        with sqlite3.connect(manifest['sources'][0]['database']) as source:
            source.execute("UPDATE browser_proposals SET status='confirmed',result=? WHERE id='proposal-1'", (json.dumps({'clicked': True}),))
        changed = export(db, manifest)
        proposals = [row for row in changed['records'] if row['kind'] == 'proposal']
        assert len(proposals) == 1 and proposals[0]['payload']['status'] == 'confirmed'
        assert any(label['key'] == 'executor' and label['value'] == 'unknown' for label in changed['labels'])
        archive.import_bundle(db, changed)
        assert {json.loads(row[0])['status'] for row in db.execute("SELECT payload FROM archive_records WHERE kind='proposal'")} == {'pending', 'confirmed'}
        assert db.execute('SELECT count(*) FROM archive_source_objects').fetchone()[0] == 1
        assert export(db, manifest)['records'] == []
        with sqlite3.connect(manifest['sources'][0]['database']) as source:
            source.execute('DELETE FROM browser_proposals')
        with pytest.raises(archive.ArchiveError, match='proposal disappeared'):
            export(db, manifest)


def test_operator_annotation_can_reference_a_committed_pick(manifest):
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest))
        manifest['operator_labels'] = [{'source_id': 'fictional-source', 'kind': 'draft_pick', 'pick_no': 1,
                                        'key': 'executor', 'value': 'manual', 'evidence_type': 'operator_observation'}]
        labeled = export(db, manifest)
        assert len(labeled['records']) == len(labeled['labels']) == 1
        assert labeled['labels'][0]['value'] == 'manual'
        added = archive.import_bundle(db, labeled)
        assert added['records'] == 0 and added['labels'] == 1
        assert export(db, manifest)['labels'] == []


@pytest.mark.parametrize('fmt', ['audit_json', 'runtime_jsonl'])
def test_dataset_prefix_is_batched_and_cannot_be_rewritten(manifest, tmp_path, fmt):
    path = tmp_path / 'events.json'
    rows = [{'event': 'runtime_observation', 'detail': {'revision': number}} for number in range(5)]
    def write():
        path.write_text('\n'.join(json.dumps(row) for row in rows) if fmt == 'runtime_jsonl' else json.dumps(rows), encoding='utf-8')
    write()
    manifest['sources'][0]['datasets'] = [{'dataset_id': 'history', 'format': fmt, 'path': str(path)}]
    with sqlite3.connect(':memory:') as db:
        for count in (2, 4, 5):
            bundle = export(db, manifest)
            archive.import_bundle(db, bundle)
            assert checkpoint(db)['datasets']['history']['count'] == count
        assert export(db, manifest)['records'] == []
        rows[1]['detail']['revision'] = 99
        write()
        with pytest.raises(archive.ArchiveError, match='prefix changed'):
            export(db, manifest)


def test_compact_manifests_do_not_grow_with_committed_history(manifest):
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest))
        lengths = []
        for _ in range(15):
            append_events(manifest, 2)
            bundle = export(db, manifest)
            assert len(bundle['records']) == 2
            archive.import_bundle(db, bundle)
            lengths.append(len(archive._json(bundle['manifest'])))
        assert max(lengths) == min(lengths)
        assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == 30
        assert len(archive._json(checkpoint(db))) < 1300


def test_tampered_checkpoint_is_rejected_before_database_writes(manifest):
    with sqlite3.connect(':memory:') as db:
        bundle = export(db, manifest)
        bundle['checkpoints'][0]['state']['password'] = 'private'
        rehash(bundle)
        with pytest.raises(archive.ArchiveError, match='invalid state'):
            archive.import_bundle(db, bundle)
        assert not archive._has_table(db, 'archive_runs')


def test_import_cannot_commit_inside_an_outer_transaction(manifest):
    with sqlite3.connect(':memory:') as db:
        bundle = export(db, manifest)
        db.execute('BEGIN')
        with pytest.raises(archive.ArchiveError, match='own database transaction'):
            archive.import_bundle(db, bundle)


def test_checkpoint_survives_connection_restart(manifest, tmp_path):
    append_events(manifest, 3)
    destination = tmp_path / 'archive.sqlite3'
    with closing(sqlite3.connect(destination)) as db:
        first = export(db, manifest)
        archive.import_bundle(db, first)
    with closing(sqlite3.connect(destination)) as restarted:
        assert checkpoint(restarted)['streams']['ffm_archive_outbox']['last_id'] == 2
        retry = export(restarted, manifest)
        assert [record['source_key'] for record in retry['records']] == ['outbox:3']
        archive.import_bundle(restarted, retry)
        assert archive.import_bundle(restarted, first) == ZERO
        assert checkpoint(restarted)['streams']['ffm_archive_outbox']['last_id'] == 3


def test_commit_failure_preserves_previous_checkpoint_and_retry(manifest):
    class FailingCommit(sqlite3.Connection):
        fail_commit = False
        def commit(self):
            if self.fail_commit:
                raise sqlite3.OperationalError('injected commit failure')
            super().commit()
    with closing(sqlite3.connect(':memory:', factory=FailingCommit)) as db:
        archive.import_bundle(db, export(db, manifest))
        previous = checkpoint(db)
        append_events(manifest, 1)
        pending = export(db, manifest)
        old_count = db.execute('SELECT count(*) FROM archive_records').fetchone()[0]
        db.fail_commit = True
        with pytest.raises(sqlite3.OperationalError, match='commit failure'):
            archive.import_bundle(db, pending)
        assert not db.in_transaction
        assert checkpoint(db) == previous
        assert db.execute('SELECT count(*) FROM archive_records').fetchone()[0] == old_count
        assert export(db, manifest)['bundle_id'] == pending['bundle_id']
        db.fail_commit = False
        archive.import_bundle(db, pending)
        assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == 1


def test_new_snapshot_and_config_revisions_are_captured(manifest):
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest))
        with sqlite3.connect(manifest['sources'][0]['database']) as source:
            raw = json.loads(source.execute('SELECT snapshot FROM state').fetchone()[0])
            raw['players'][0]['projection'] = 120
            source.execute('UPDATE state SET snapshot=?,revision=2,config_revision=1', (json.dumps(raw),))
        bundle = export(db, manifest)
        assert any(row['source_key'] == 'state:2' for row in bundle['records'])
        assert any(row['source_key'] == 'config:1' for row in bundle['records'])
        archive.import_bundle(db, bundle)
        assert checkpoint(db)['database']['revision'] == 2
        assert checkpoint(db)['database']['config_revision'] == 1


def test_config_checkpoint_hash_uses_stored_json_not_new_model_defaults(manifest):
    with sqlite3.connect(manifest['sources'][0]['database']) as source:
        config = json.loads(source.execute('SELECT config FROM state').fetchone()[0])
        config['limits'].pop('coverage_repair_ids', None)
        config['limits'].pop('coverage_repair_add_ids', None)
        config['automation']['actions'].pop('move_to_ir', None)
        config['automation']['actions'].pop('activate_from_ir', None)
        source.execute('UPDATE state SET config=?', (json.dumps(config),))
    with sqlite3.connect(':memory:') as db:
        bundle = export(db, manifest)
        saved = next(row['payload']['config'] for row in bundle['records'] if row['kind'] == 'config')
        assert 'coverage_repair_ids' not in saved['limits']
        assert 'coverage_repair_add_ids' not in saved['limits']
        assert 'move_to_ir' not in saved['automation']['actions']
        assert 'activate_from_ir' not in saved['automation']['actions']
        archive.import_bundle(db, bundle)
        assert checkpoint(db)['database']['config_sha256'] == archive._hash(config)
        assert export(db, manifest)['checkpoints'] == []


def test_legacy_snapshot_does_not_gain_optional_http_or_player_fields(manifest):
    bundle = archive.export_bundle(manifest)
    saved = next(row['payload'] for row in bundle['records'] if row['kind'] == 'snapshot')
    assert 'http' not in saved['source']
    assert all('espn' not in player for player in saved['players'])
    archive.validate_bundle(bundle)
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, bundle)
        archive.compact_receipts(db, apply=True)
        assert archive.import_bundle(db, bundle) == ZERO


@pytest.mark.parametrize('incremental', [False, True])
def test_http_snapshot_and_coverage_provenance_survive_without_private_fields(manifest, incremental):
    from fantasy_football_manager import evidence
    from fantasy_football_manager.espn_http_client import league_url
    from fantasy_football_manager.models import LeagueSnapshot, ManagerConfig
    raw = snapshot('season')
    raw['source'].update(provider='espn_http', browser=None, http={
        'league_id': '123', 'team_id': '11', 'season': 2026, 'week': 1,
        'roster_url': league_url('123', 2026) + '?view=mRoster&forTeamId=11&scoringPeriodId=1&memberId=PRIVATE-MEMBER',
        'ownership_verified': True, 'transaction_period': 1, 'latest_period': 1, 'final_period': 18,
        'team_transaction_locked': False, 'pending_transactions_known': True,
        'uses_faab': True, 'minimum_bid': 0, 'acquisition_limit': -1,
        'pending_transactions': [{'id': 'tx-1', 'type': 'ADD', 'teamId': 11, 'isPending': True,
                                  'memberId': 'PRIVATE-MEMBER', 'headers': {'authorization': 'PRIVATE-HEADER'},
                                  'items': [{'playerId': 101, 'type': 'ADD', 'toTeamId': 11, 'notes': 'PRIVATE-NOTE'}]}],
        'recent_transactions': [{'id': 'tx-2', 'type': 'ROSTER', 'status': 'FAILED', 'message': 'PRIVATE-MESSAGE'}],
    })
    raw['players'][0]['bye'] = 9
    raw['players'][0]['espn'] = {'roster_locked': False, 'trade_locked': None, 'droppable': True, 'bye_verified': True,
                                'injured': False, 'eligible_slots': [2, 20], 'pending_transaction_ids': ['tx-1']}
    parsed = LeagueSnapshot.model_validate(raw)
    config = ManagerConfig(limits={'coverage_repair_ids': ['101'], 'coverage_repair_add_ids': ['103']})
    detail = evidence.envelope(parsed, config, 1, 0, include_snapshot=True)
    detail['calculation'] = {'fixed_slots': {'RB1': '101'}, 'comparison_complete': True,
                             'blocking_missing_projections': [{'player_id': '103', 'fields': ['weekly_projection']}],
                             'coverage': {'source_ready': True, 'gaps': [{'slot': 'RB1', 'player_id': '101',
                                  'backup_player_ids': ['103'], 'reasons': ['starter_unavailable', 'PRIVATE-REASON']}],
                                  'candidates': [{'repair_player_id': '103', 'drop_id': '101', 'authorized': False,
                                                  'blocking_reasons': ['coverage_repair_not_enabled']}]}}
    detail['action'] = {'payload': {'bid': 0}, 'submission_phase': 'preflight', 'error_category': 'policy_blocked',
                        'transaction': raw['source']['http']['pending_transactions'][0]}
    with sqlite3.connect(manifest['sources'][0]['database']) as source:
        source.execute('UPDATE state SET snapshot=?,config=?', (json.dumps(raw), config.model_dump_json()))
        source.execute('INSERT INTO ffm_archive_outbox VALUES(1,NULL,?,?)', ('calculation_completed', json.dumps(detail)))
    with sqlite3.connect(':memory:') as db:
        bundle = export(db, manifest) if incremental else archive.export_bundle(manifest)
        archive.import_bundle(db, bundle)
        assert 'PRIVATE-' not in json.dumps(bundle)
        assert 'roster_url' not in json.dumps(bundle)
        snapshots = [row['payload'] for row in bundle['records'] if row['kind'] == 'snapshot']
        assert len(snapshots) == 2
        for saved in snapshots:
            http = saved['source']['http']
            assert http['ownership_verified'] and http['pending_transactions_known']
            assert http['team_transaction_locked'] is False and http['acquisition_limit'] == -1
            assert http['pending_transactions'][0]['items'] == [{'playerId': 101, 'type': 'ADD', 'toTeamId': 11}]
            assert http['recent_transactions'] == [{'id': 'tx-2', 'type': 'ROSTER', 'status': 'FAILED'}]
            assert saved['players'][0]['espn']['trade_locked'] is None
            assert saved['players'][0]['bye'] == 9 and saved['players'][0]['espn']['bye_verified'] is True
            assert saved['players'][0]['espn']['pending_transaction_ids'] == ['tx-1']
        event = next(row['payload'] for row in bundle['records'] if row['source_key'] == 'outbox:1')
        assert event['calculation']['fixed_slots'] == {'RB1': '101'}
        assert event['calculation']['coverage']['gaps'][0]['reasons'] == ['starter_unavailable']
        assert event['action']['payload']['bid'] == 0
        assert event['action']['submission_phase'] == 'preflight'
        saved_config = next(row['payload']['config'] for row in bundle['records'] if row['kind'] == 'config')
        assert saved_config['limits']['coverage_repair_ids'] == ['101']
        assert saved_config['limits']['coverage_repair_add_ids'] == ['103']


def test_dataset_truncation_and_later_append(manifest, tmp_path):
    path = tmp_path / 'events.jsonl'
    line = json.dumps({'event': 'runtime_observation', 'detail': {'revision': 1}}) + '\n'
    path.write_text(line * 3, encoding='utf-8')
    manifest['sources'][0]['datasets'] = [{'dataset_id': 'events', 'format': 'runtime_jsonl', 'path': str(path)}]
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest, 10))
        path.write_text(line * 4, encoding='utf-8')
        additional = export(db, manifest)
        assert [record['source_key'] for record in additional['records']] == ['dataset:events:3']
        archive.import_bundle(db, additional)
        path.write_text(line * 2, encoding='utf-8')
        with pytest.raises(archive.ArchiveError, match='shorter'):
            export(db, manifest)
        assert checkpoint(db)['datasets']['events']['count'] == 4


@pytest.mark.parametrize('drain,expected_last_id', [(False, 2), (True, 5)])
def test_sync_cli_defaults_to_incremental_and_can_drain_backlog(manifest, tmp_path, monkeypatch, drain, expected_last_id):
    append_events(manifest, 5)
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    destination = tmp_path / 'archive.sqlite3'
    def connect(dsn, *, autocommit):
        assert dsn == 'fictional-test-destination' and autocommit
        return sqlite3.connect(destination)
    monkeypatch.setitem(sys.modules, 'psycopg', types.SimpleNamespace(connect=connect))
    args = ['sync', '--manifest', str(path), '--dsn', 'fictional-test-destination', '--batch-size', '2']
    assert archive.main(args + (['--drain'] if drain else [])) == 0
    with sqlite3.connect(destination) as db:
        assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == expected_last_id
        assert all(json.loads(row[0])['schema_version'] == 2 for row in db.execute('SELECT manifest FROM archive_imports'))


def test_incremental_export_cli_does_not_advance_checkpoint(manifest, tmp_path, monkeypatch):
    path, output = tmp_path / 'manifest.json', tmp_path / 'bundle.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    destination = tmp_path / 'archive.sqlite3'
    monkeypatch.setitem(sys.modules, 'psycopg', types.SimpleNamespace(connect=lambda *args, **kwargs: sqlite3.connect(destination)))
    assert archive.main(['export', '--incremental', '--manifest', str(path), '--output', str(output)]) == 0
    bundle = json.loads(output.read_text(encoding='utf-8'))
    assert bundle['schema_version'] == 2
    with sqlite3.connect(destination) as db:
        assert not archive._has_table(db, 'archive_source_checkpoints')
        archive.import_bundle(db, bundle)
        assert checkpoint(db)['sequence'] == 1


def test_checkpoint_content_cannot_rewind_committed_cursor(manifest):
    append_events(manifest, 2)
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest))
        append_events(manifest, 1)
        bundle = export(db, manifest)
        bundle['checkpoints'][0]['state']['streams']['ffm_archive_outbox']['count'] = 1
        rehash(bundle)
        with pytest.raises(archive.ArchiveError, match='committed prefix'):
            archive.import_bundle(db, bundle)
        assert checkpoint(db)['streams']['ffm_archive_outbox']['count'] == 2


@pytest.mark.parametrize('change', ['boundary', 'snapshot_digest', 'sequence'])
def test_rehashed_checkpoint_cannot_rewrite_source_continuity(manifest, change):
    append_events(manifest, 2)
    with sqlite3.connect(':memory:') as db:
        archive.import_bundle(db, export(db, manifest))
        append_events(manifest, 1)
        bundle = export(db, manifest)
        state = bundle['checkpoints'][0]['state']
        if change == 'boundary':
            state['streams']['ffm_archive_outbox']['first_sha256'] = '0' * 64
        elif change == 'snapshot_digest':
            state['database']['snapshot_sha256'] = '0' * 64
        else:
            state['sequence'] += 1
        rehash(bundle)
        with pytest.raises(archive.ArchiveError, match='checkpoint cannot'):
            archive.import_bundle(db, bundle)
        assert checkpoint(db)['sequence'] == 1


@pytest.mark.skipif(not os.environ.get('FFM_ARCHIVE_TEST_DSN'), reason='An explicit isolated PostgreSQL test DSN is required.')
def test_postgres_incremental_atomicity_replay_and_stale_export(manifest):
    import psycopg
    from psycopg import sql
    schema = 'test_archive_incremental_' + uuid.uuid4().hex
    append_events(manifest, 3)
    with psycopg.connect(os.environ['FFM_ARCHIVE_TEST_DSN'], autocommit=True) as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            db.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            first, stale = export(db, manifest, 1), export(db, manifest, 3)
            archive.import_bundle(db, first)
            assert archive.import_bundle(db, first) == ZERO
            with pytest.raises(archive.ArchiveError, match='stale'):
                archive.import_bundle(db, stale)
            assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == 1
            db.execute("ALTER TABLE archive_source_checkpoints ADD CONSTRAINT injected_failure CHECK ((payload::json->>'sequence')::int=1)")
            pending = export(db, manifest, 3)
            count = db.execute('SELECT count(*) FROM archive_records').fetchone()[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                archive.import_bundle(db, pending)
            assert db.execute('SELECT count(*) FROM archive_records').fetchone()[0] == count
            assert checkpoint(db)['sequence'] == 1
            db.execute('ALTER TABLE archive_source_checkpoints DROP CONSTRAINT injected_failure')
            archive.import_bundle(db, pending)
            assert checkpoint(db)['streams']['ffm_archive_outbox']['last_id'] == 3
            with db.transaction():
                with pytest.raises(archive.ArchiveError, match='own database transaction'):
                    archive.import_bundle(db, pending)
        finally:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
