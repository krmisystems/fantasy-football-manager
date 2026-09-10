"""Receipt compaction preserves exact evidence and supports legacy replay."""

from contextlib import closing
from copy import deepcopy
import json
import os
import sqlite3
import uuid

import pytest

from fantasy_football_manager import archive
from test_archive import manifest
from test_archive_incremental import append_events, ZERO


def populate(db, manifest):
    bundles = []
    for _ in range(3):
        append_events(manifest, 2)
        bundle = archive.export_bundle(manifest)
        archive.import_bundle(db, bundle)
        bundles.append(bundle)
    return bundles


def receipts(db):
    return list(db.execute('SELECT bundle_id,imported_at,manifest FROM archive_imports ORDER BY bundle_id'))


def test_compaction_default_only_verifies_and_apply_preserves_exact_evidence(manifest):
    with sqlite3.connect(':memory:') as db:
        bundles = populate(db, manifest)
        original = receipts(db)
        preview = archive.compact_receipts(db)
        assert preview['verified_receipts'] == 3 and preview['compacted_receipts'] == 0
        assert preview['original_text_bytes'] > preview['compact_text_bytes']
        assert receipts(db) == original
        result = archive.compact_receipts(db, apply=True)
        assert result['compacted_receipts'] == 3 and result['evidence_unchanged']
        assert result['evidence_coverage'] == preview['evidence_coverage']
        assert result['import_identity_sha256'] == preview['import_identity_sha256']
        compacted = receipts(db)
        assert [row[:2] for row in compacted] == [row[:2] for row in original]
        originals = {bundle['bundle_id']: bundle for bundle in bundles}
        for bundle_id, _, text in compacted:
            value = json.loads(text)
            bundle = originals[bundle_id]
            assert value['receipt_format'] == archive.COMPACT_RECEIPT_FORMAT
            assert value['original_manifest_sha256'] == bundle_id
            assert value['counts'] == {kind: len(bundle[kind]) for kind in ('runs', 'records', 'labels')}
            assert value['membership_sha256'] == {kind: archive._hash(bundle['manifest'][kind]) for kind in ('runs', 'records', 'labels')}
            assert value['runs'][0]['source_id'] == manifest['sources'][0]['source_id']
            assert value['runs'][0]['context'] == bundle['runs'][0]['context']
        for bundle in bundles:
            assert archive.import_bundle(db, bundle) == ZERO
        assert receipts(db) == compacted
        again = archive.compact_receipts(db, apply=True)
        assert again['compacted_receipts'] == 0 and again['already_compact_receipts'] == 3
        assert again['evidence_coverage'] == result['evidence_coverage']


def test_compaction_coexists_with_incremental_checkpoints(manifest):
    with sqlite3.connect(':memory:') as db:
        populate(db, manifest)
        bundle = archive.export_incremental_bundle(db, manifest)
        archive.import_bundle(db, bundle)
        original_checkpoint = db.execute('SELECT payload FROM archive_source_checkpoints').fetchone()[0]
        before = archive.compact_receipts(db)
        result = archive.compact_receipts(db, apply=True)
        assert result['compacted_receipts'] == 3 and result['already_compact_receipts'] == 1
        assert result['evidence_coverage'] == before['evidence_coverage']
        assert db.execute('SELECT payload FROM archive_source_checkpoints').fetchone()[0] == original_checkpoint
        assert archive.import_bundle(db, bundle) == ZERO
        append_events(manifest, 1)
        new = archive.export_incremental_bundle(db, manifest)
        assert len(new['records']) == 1
        assert archive.import_bundle(db, new)['records'] == 1


@pytest.mark.parametrize('change', ['invalid_hash', 'missing_record', 'duplicate_record', 'missing_label_reference'])
def test_invalid_manifest_rolls_back_all_compaction(manifest, change):
    with sqlite3.connect(':memory:') as db:
        bundles = populate(db, manifest)
        bad = deepcopy(bundles[0]['manifest'])
        if change == 'missing_record':
            bad['records'][0]['id'] = 'f' * 64
        elif change == 'duplicate_record':
            bad['records'].append(bad['records'][0])
        elif change == 'missing_label_reference':
            pick_id = next(row['record_id'] for row in bundles[0]['records'] if row['kind'] == 'draft_pick')
            bad['records'] = [row for row in bad['records'] if row['id'] != pick_id]
        bad_id = 'f' * 64 if change == 'invalid_hash' else archive._hash(bad)
        db.execute('INSERT INTO archive_imports VALUES(?,?,?)', (bad_id, '2026-01-01T00:00:00+00:00', archive._json(bad)))
        db.commit()
        before = receipts(db)
        with pytest.raises(archive.ArchiveError):
            archive.compact_receipts(db, apply=True)
        assert receipts(db) == before


def test_compaction_detects_evidence_changes_from_an_unexpected_trigger(manifest):
    with sqlite3.connect(':memory:') as db:
        populate(db, manifest)
        db.execute("CREATE TRIGGER alter_evidence AFTER UPDATE ON archive_imports BEGIN UPDATE archive_labels SET label_value='true'; END")
        db.commit()
        before = receipts(db)
        labels = list(db.execute('SELECT * FROM archive_labels ORDER BY label_id'))
        with pytest.raises(archive.ArchiveError, match='label identity or content'):
            archive.compact_receipts(db, apply=True)
        assert receipts(db) == before
        assert list(db.execute('SELECT * FROM archive_labels ORDER BY label_id')) == labels


def test_compaction_commit_failure_restores_full_receipts(manifest):
    class FailingCommit(sqlite3.Connection):
        fail_commit = False
        def commit(self):
            if self.fail_commit:
                raise sqlite3.OperationalError('injected commit failure')
            super().commit()
    with closing(sqlite3.connect(':memory:', factory=FailingCommit)) as db:
        populate(db, manifest)
        original = receipts(db)
        db.fail_commit = True
        with pytest.raises(sqlite3.OperationalError, match='commit failure'):
            archive.compact_receipts(db, apply=True)
        assert receipts(db) == original
        db.fail_commit = False
        assert archive.compact_receipts(db, apply=True)['compacted_receipts'] == 3


def test_legacy_replay_rejects_changed_compact_receipt(manifest):
    with sqlite3.connect(':memory:') as db:
        bundle = populate(db, manifest)[0]
        archive.compact_receipts(db, apply=True)
        value = json.loads(db.execute('SELECT manifest FROM archive_imports WHERE bundle_id=?', (bundle['bundle_id'],)).fetchone()[0])
        value['counts']['records'] += 1
        db.execute('UPDATE archive_imports SET manifest=? WHERE bundle_id=?', (archive._json(value), bundle['bundle_id']))
        db.commit()
        with pytest.raises(archive.ArchiveError, match='different content'):
            archive.import_bundle(db, bundle)


@pytest.mark.skipif(not os.environ.get('FFM_ARCHIVE_TEST_DSN'), reason='An explicit isolated PostgreSQL test DSN is required.')
def test_postgres_compaction_and_legacy_replay(manifest):
    import psycopg
    from psycopg import sql
    schema = 'test_archive_compaction_' + uuid.uuid4().hex
    with psycopg.connect(os.environ['FFM_ARCHIVE_TEST_DSN'], autocommit=True) as db:
        db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            db.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            bundles = populate(db, manifest)
            preview = archive.compact_receipts(db)
            result = archive.compact_receipts(db, apply=True)
            assert result['compacted_receipts'] == 3
            assert result['evidence_coverage'] == preview['evidence_coverage']
            assert result['import_identity_sha256'] == preview['import_identity_sha256']
            for bundle in bundles:
                assert archive.import_bundle(db, bundle) == ZERO
            assert archive.compact_receipts(db, apply=True)['already_compact_receipts'] == 3
        finally:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
