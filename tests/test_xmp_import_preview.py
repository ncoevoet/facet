"""Read-only import plans and exact review-edit conflict clocks on real SQLite."""
import json
import pytest
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from xml.etree import ElementTree as ET

from db.metadata_edits import review_edit_state
from db.schema import init_database
from processing.xmp_export import NS_XMP, NS_RDF, XmpRating, build_xmp
from processing.xmp_import import import_sidecars


def _seed_library(tmp_path, rating=1):
    path = tmp_path / 'photo.jpg'
    db = tmp_path / 'test.db'
    init_database(str(db))
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute('INSERT INTO photos(path,star_rating,scanned_at) VALUES (?,?,?)',
                 (str(path), rating, '2020-01-01 00:00:00'))
    conn.commit()
    return conn, path, db


@contextmanager
def _library(tmp_path, rating=1):
    """Seeded library connection that is always closed."""
    conn, path, db = _seed_library(tmp_path, rating)
    try:
        yield conn, path, db
    finally:
        conn.close()


def _run_facet(*args, **kwargs):
    """Run ``facet.py`` from the repository root and capture its text output."""
    return subprocess.run([sys.executable, 'facet.py', *args], cwd=Path(__file__).resolve().parents[1],
                          capture_output=True, text=True, timeout=30, **kwargs)


def _write_sidecar(path, *, rating=5, tags=(), gps=False, decision=False):
    packet = ET.fromstring(build_xmp(XmpRating(star_rating=rating, tags=list(tags), is_kept=decision,
                                              gps_manually_set=gps, gps_latitude=1, gps_longitude=2)))
    packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_XMP}}}MetadataDate', '2021-01-01T00:00:00Z')
    filename = Path(str(path) + '.xmp')
    filename.write_bytes(ET.tostring(packet))
    return filename


def test_preview_changes_diagnostics_and_source_without_any_database_write(tmp_path):
    with _library(tmp_path) as (conn, path, db):
        _write_sidecar(path, tags=['new', 'a|hierarchy', 'bad,word'], gps=True)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        before = db.read_bytes()
        writes = conn.total_changes
        result = import_sidecars(conn, str(path), dry_run=True)
        assert result['updated'] == 1
        assert result['dry_run'] is True
        plan = result['entries'][0]
        assert plan['changes']['star_rating'] == {'before': 1, 'after': 5}
        assert plan['changes']['keywords'] == {'added': ['new', 'a|hierarchy']}
        assert plan['changes']['gps']['after'] == [1, 2, 1]
        assert {d['reason'] for d in plan['diagnostics']} >= {'invalid_keyword', 'untracked_legacy_edit'}
        assert plan['source']['metadata_date'] == '2021-01-01T00:00:00+00:00'
        assert conn.total_changes == writes
        assert db.read_bytes() == before
        assert not conn.in_transaction
        assert conn.execute('SELECT COUNT(*) FROM photo_manual_tags').fetchone()[0] == 0
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 1
        json.dumps(result)  # Preview is a CLI/API-ready JSON value.


def test_newer_manual_review_clock_blocks_old_packet_but_not_keyword_additions(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        _write_sidecar(path, rating=5, tags=['external'])
        conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
        conn.commit()
        preview = import_sidecars(conn, dry_run=True)
        assert preview['conflicts'] == 1
        assert preview['entries'][0]['changes'] == {'keywords': {'added': ['external']}}
        reason = next(d for d in preview['entries'][0]['diagnostics'] if d['reason'] == 'newer_local_edit')
        assert reason['fields'] == ['star_rating']
        assert reason['incoming']['star_rating'] == {'before': 3, 'after': 5}
        result = import_sidecars(conn)
        assert result['conflicts'] == 1
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 3
        assert review_edit_state(conn, str(path), '')['star_rating']['source'] == 'local'
        assert conn.execute('SELECT tag,source FROM photo_manual_tags').fetchone()[:] == ('external', 'xmp')


def test_explicit_review_override_records_exact_field_receipt_and_repeat_is_noop(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        filename = _write_sidecar(path)
        conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
        conn.commit()
        assert import_sidecars(conn, overwrite_review=True)['updated'] == 1
        receipt = review_edit_state(conn, str(path), '')['star_rating']
        assert receipt['source'] == 'xmp'
        assert receipt['source_path'] == str(filename)
        assert receipt['source_at'].startswith('2021-01-01')
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 5
        assert import_sidecars(conn)['unchanged'] == 1
        assert review_edit_state(conn, str(path), '')['star_rating'] == receipt


@pytest.mark.parametrize('fields', [{'gps'}, {'keywords'}])
def test_overwrite_review_with_unselected_review_field_changes_nothing_and_records_no_receipt(tmp_path, fields):
    with _library(tmp_path) as (conn, path, _):
        conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
        conn.commit()
        clocks = review_edit_state(conn, str(path), '')
        assert clocks['star_rating']['source'] == 'local'
        _write_sidecar(path, rating=5, tags=['external'], gps=True)
        for dry_run in (True, False):
            result = import_sidecars(conn, str(path), dry_run=dry_run, fields=fields, overwrite_review=True)
            assert result['updated'] == 1
            assert not {'star_rating', 'is_favorite', 'is_rejected', 'is_kept'} & set(result['entries'][0]['changes'])
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 3
        assert review_edit_state(conn, str(path), '') == clocks


def test_apply_replans_after_an_intervening_manual_edit(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        _write_sidecar(path)
        assert import_sidecars(conn, dry_run=True)['entries'][0]['changes']['star_rating']['after'] == 5
        conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (str(path),))
        conn.commit()
        result = import_sidecars(conn)
        assert result['conflicts'] == 1
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 2


def test_selected_fields_do_not_import_review_or_gps_and_preview_does_not_commit_caller(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        _write_sidecar(path, tags=['one'], gps=True)
        conn.execute('UPDATE photos SET caption=? WHERE path=?', ('pending', str(path)))
        result = import_sidecars(conn, fields=['keywords'], dry_run=True)
        assert conn.in_transaction
        assert result['entries'][0]['changes'] == {'keywords': {'added': ['one']}}
        conn.rollback()
        assert conn.execute('SELECT caption FROM photos').fetchone()[0] is None
        import_sidecars(conn, fields=['keywords'])
        row = conn.execute('SELECT star_rating,gps_manually_set FROM photos').fetchone()
        assert tuple(row) == (1, 0)


def test_per_user_clocks_and_visibility_are_isolated(tmp_path, monkeypatch):
    with _library(tmp_path, rating=0) as (conn, path, _):
        hidden = tmp_path / 'hidden.jpg'
        conn.execute('INSERT INTO photos(path) VALUES (?)', (str(hidden),))
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,?)',
                     ('alice', str(path), 3))
        conn.commit()
        _write_sidecar(path)
        _write_sidecar(hidden)
        monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: True)
        monkeypatch.setattr('api.db_helpers.get_visibility_clause', lambda user: ('photos.path=?', [str(path)]))
        alice = import_sidecars(conn, user_id='alice', dry_run=True)
        assert alice['conflicts'] == 1
        assert [e['path'] for e in alice['entries']] == [str(path)]
        assert import_sidecars(conn, user_id='bob')['updated'] == 1
        assert conn.execute('SELECT star_rating FROM user_preferences WHERE user_id=?', ('alice',)).fetchone()[0] == 3
        assert conn.execute('SELECT star_rating FROM user_preferences WHERE user_id=?', ('bob',)).fetchone()[0] == 5
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (str(path),)).fetchone()[0] == 0
        assert review_edit_state(conn, str(path), 'alice')['star_rating']['source'] == 'local'
        assert review_edit_state(conn, str(path), 'bob')['star_rating']['source'] == 'xmp'
        assert review_edit_state(conn, str(hidden), '') == {}


def test_edit_clocks_rollback_noop_delete_and_path_move(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (str(path),))
        assert review_edit_state(conn, str(path), '')
        conn.rollback()
        assert review_edit_state(conn, str(path), '') == {}
        conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (str(path),))
        conn.commit()
        clock = review_edit_state(conn, str(path), '')
        conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (str(path),))
        assert review_edit_state(conn, str(path), '') == clock
        moved = str(path) + '.moved'
        conn.execute('UPDATE photos SET path=? WHERE path=?', (moved, str(path)))
        assert review_edit_state(conn, moved, '')['star_rating'] == {**clock['star_rating'], 'photo_path': moved}
        conn.execute('DELETE FROM photos WHERE path=?', (moved,))
        assert review_edit_state(conn, moved, '') == {}


def test_missing_malformed_and_manual_gps_are_explained(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        assert import_sidecars(conn, dry_run=True)['entries'][0]['diagnostics'] == [{'reason': 'missing_sidecar'}]
        filename = Path(str(path) + '.xmp')
        filename.write_text('broken xml')
        assert import_sidecars(conn, dry_run=True)['entries'][0]['diagnostics'] == [{'reason': 'unparseable_sidecar'}]
        _write_sidecar(path, gps=True)
        conn.execute('UPDATE photos SET gps_latitude=7,gps_longitude=8,gps_manually_set=1 WHERE path=?', (str(path),))
        conn.commit()
        result = import_sidecars(conn, fields=['gps'], dry_run=True)
        assert result['entries'][0]['changes'] == {}
        assert result['entries'][0]['diagnostics'] == [{'field': 'gps', 'reason': 'manual_gps_protected'}]



def test_epoch_zero_metadata_date_never_falls_back_to_recent_file_mtime(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        filename = _write_sidecar(path)
        packet = ET.parse(filename)
        packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_XMP}}}MetadataDate', '1970-01-01T00:00:00Z')
        packet.write(filename, encoding='utf-8')
        preview = import_sidecars(conn, dry_run=True)
        assert preview['entries'][0]['changes'] == {}
        assert preview['entries'][0]['source']['effective_at'].startswith('1970-01-01')
        assert preview['entries'][0]['source']['clock'] == 'metadata_date'


@pytest.mark.parametrize('database_state', ['missing', 'corrupt', 'unreadable', 'empty'])
def test_cli_preview_refuses_unusable_database_without_traceback_or_writes(tmp_path, database_state):
    import os
    db = tmp_path / 'library.db'
    if database_state == 'corrupt':
        db.write_bytes(b'not a SQLite database')
    elif database_state == 'empty':
        with sqlite3.connect(db):
            pass
    elif database_state == 'unreadable':
        db.write_bytes(b'private database')
        db.chmod(0)
        if os.access(db, os.R_OK):
            db.chmod(0o600)
            pytest.skip('This account can read files with all permission bits removed')
    before = db.read_bytes() if db.exists() and database_state != 'unreadable' else None
    try:
        result = _run_facet('--db', str(db), '--import-sidecars', '--dry-run', encoding='utf-8')
        assert result.returncode == 1
        assert result.stdout == ''
        assert 'Sidecar import preview failed' in result.stderr
        assert 'readable Facet database' in result.stderr
        assert 'Traceback' not in result.stderr
        assert 'sqlite3.' not in result.stderr
        if database_state == 'missing':
            assert not db.exists()
        elif before is not None:
            assert db.read_bytes() == before
        assert not Path(str(db) + '-wal').exists()
        assert not Path(str(db) + '-shm').exists()
        assert not Path(str(db) + '-journal').exists()
    finally:
        if database_state == 'unreadable':
            db.chmod(0o600)
            assert db.read_bytes() == b'private database'


def test_cli_preview_opens_existing_database_readonly_without_schema_migration(tmp_path):
    conn, path, db = _seed_library(tmp_path, rating=0)
    _write_sidecar(path, tags=['external'])
    conn.execute('DROP TABLE photo_metadata_edits')
    conn.commit()
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.close()
    before = db.read_bytes()
    result = _run_facet('--db', str(db), '--import-sidecars', str(path), '--dry-run', '--sidecar-fields', 'keywords')
    assert result.returncode == 0, result.stderr
    preview = json.loads(result.stdout)
    assert preview['dry_run'] is True
    assert preview['entries'][0]['changes'] == {'keywords': {'added': ['external']}}
    assert db.read_bytes() == before
    with sqlite3.connect(db) as check:
        assert not check.execute("SELECT 1 FROM sqlite_master WHERE name='photo_metadata_edits'").fetchone()
        assert check.execute('SELECT COUNT(*) FROM photo_manual_tags').fetchone()[0] == 0



def _tracked(conn, path, changed_at, scanned_at):
    conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
    conn.execute('UPDATE photo_metadata_edits SET changed_at=? WHERE photo_path=?', (changed_at, str(path)))
    conn.execute('UPDATE photos SET scanned_at=? WHERE path=?', (scanned_at, str(path)))
    conn.commit()


def test_tracked_receipt_older_than_sidecar_applies_despite_a_later_rescan(tmp_path):
    # Receipt 2020-06, sidecar 2021-01, rescan 2022-01: the receipt clock, not the scan, decides.
    with _library(tmp_path) as (conn, path, _):
        _write_sidecar(path, rating=5)
        _tracked(conn, path, '2020-06-01T00:00:00.000Z', '2022-01-01 00:00:00')
        preview = import_sidecars(conn, dry_run=True)
        assert preview['updated'] == 1
        assert preview['entries'][0]['changes']['star_rating'] == {'before': 3, 'after': 5}
        assert not {d['reason'] for d in preview['entries'][0]['diagnostics']} & {'older_than_scan', 'newer_local_edit'}
        assert import_sidecars(conn)['updated'] == 1
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 5


def test_tracked_receipt_newer_than_sidecar_is_refused_even_before_the_scan(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        _write_sidecar(path, rating=5)
        _tracked(conn, path, '2021-06-01T00:00:00.000Z', '2020-01-01 00:00:00')
        result = import_sidecars(conn)
        assert result['conflicts'] == 1
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 3


def test_untracked_row_keeps_the_legacy_scan_gate(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        _write_sidecar(path, rating=5)
        conn.execute('UPDATE photos SET scanned_at=? WHERE path=?', ('2022-01-01 00:00:00', str(path)))
        conn.commit()
        assert review_edit_state(conn, str(path), '') == {}
        result = import_sidecars(conn)
        assert result['updated'] == 0
        reasons = {d['reason'] for d in result['entries'][0]['diagnostics']}
        assert 'older_than_scan' in reasons
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 1


def test_explicit_override_also_bypasses_scan_gate_and_review_group_stays_atomic(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        _write_sidecar(path, rating=5, decision=True)
        conn.execute('UPDATE photos SET star_rating=3,scanned_at=? WHERE path=?',
                     ('2099-01-01 00:00:00', str(path)))
        conn.commit()
        # Rejection/Keep and stars are one review group; never apply only the unconflicted half.
        result = import_sidecars(conn, dry_run=True)
        assert result['entries'][0]['changes'] == {}
        assert import_sidecars(conn, overwrite_review=True)['updated'] == 1
        assert tuple(conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos').fetchone()) == (5, 1, 0)


@pytest.mark.parametrize('per_user', [False, True])
def test_explicit_reset_clock_prevents_a_stale_sidecar_resurrecting_review(tmp_path, monkeypatch, per_user):
    with _library(tmp_path, rating=0) as (conn, path, _):
        _write_sidecar(path)
        monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: per_user)
        if per_user:
            conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
            conn.execute('DELETE FROM user_preferences WHERE user_id=?', ('alice',))
        else:
            conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
            conn.execute('UPDATE photos SET star_rating=0 WHERE path=?', (str(path),))
        conn.commit()
        result = import_sidecars(conn, user_id='alice' if per_user else None)
        assert result['conflicts'] == 1
        assert result['updated'] == 0
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM user_preferences').fetchone()[0] == 0


def test_photo_deletion_cascades_preferences_without_recreating_edit_receipts(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        conn.commit()
        conn.execute('DELETE FROM photos WHERE path=?', (str(path),))
        conn.commit()
        assert conn.execute('SELECT COUNT(*) FROM photo_metadata_edits').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM user_preferences').fetchone()[0] == 0


def test_failed_apply_rolls_back_tags_and_releases_its_writer_transaction(tmp_path, monkeypatch):
    with _library(tmp_path, rating=0) as (conn, path, db):
        _write_sidecar(path, tags=['external'])
        def fail(*args, **kwargs):
            raise RuntimeError('simulated write failure')
        monkeypatch.setattr('processing.xmp_import.upsert_rating_state', fail)
        with pytest.raises(RuntimeError, match='simulated write failure'):
            import_sidecars(conn)
        assert not conn.in_transaction
        assert conn.execute('SELECT COUNT(*) FROM photo_manual_tags').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM photo_metadata_edits').fetchone()[0] == 0
        with sqlite3.connect(db, timeout=0.1) as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.rollback()



def test_viewer_incremental_export_preserves_local_edit_clock_and_conflict(tmp_path):
    from db.maintenance import export_viewer_db
    with _library(tmp_path, rating=0) as (conn, path, db):
        viewer = tmp_path / 'viewer.db'
        _write_sidecar(path)
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            output.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
            output.commit()
            clock = review_edit_state(output, str(path), '')
            assert clock['star_rating']['source'] == 'local'
        conn.execute('UPDATE photos SET aggregate=8 WHERE path=?', (str(path),))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert review_edit_state(output, str(path), '') == clock
            result = import_sidecars(output)
            assert result['conflicts'] == 1
            assert output.execute('SELECT star_rating FROM photos').fetchone()[0] == 3


@pytest.mark.parametrize('rating', ['NaN', 'inf', 'not-a-rating'])
def test_invalid_review_value_is_reported_and_never_clears_existing_review(tmp_path, rating):
    with _library(tmp_path) as (conn, path, _):
        filename = _write_sidecar(path, tags=['external'])
        packet = ET.parse(filename)
        packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_XMP}}}Rating', rating)
        packet.write(filename, encoding='utf-8')
        preview = import_sidecars(conn, dry_run=True)
        assert preview['entries'][0]['changes'] == {'keywords': {'added': ['external']}}
        assert {'field': 'review', 'reason': 'invalid_rating'} in preview['entries'][0]['diagnostics']
        import_sidecars(conn)
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 1


@pytest.mark.parametrize('per_user', [False, True])
@pytest.mark.parametrize('field', ['star_rating', 'is_favorite', 'is_rejected', 'is_kept'])
def test_viewer_incremental_preserves_explicit_zero_and_exact_clock(tmp_path, per_user, field):
    from db.maintenance import export_viewer_db
    with _library(tmp_path, rating=0) as (conn, path, db):
        viewer = tmp_path / 'viewer.db'
        value = 3 if field == 'star_rating' else 1
        if per_user:
            conn.execute(f'INSERT INTO user_preferences(user_id,photo_path,{field}) VALUES (?,?,?)', ('alice', str(path), value))
        else:
            conn.execute(f'UPDATE photos SET {field}=? WHERE path=?', (value, str(path)))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        table = 'user_preferences' if per_user else 'photos'
        key = "photo_path=? AND user_id='alice'" if per_user else 'path=?'
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            output.execute(f'UPDATE {table} SET {field}=0 WHERE {key}', (str(path),))
            output.commit()
            clock = review_edit_state(output, str(path), 'alice' if per_user else '')
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert output.execute(f'SELECT {field} FROM {table} WHERE {key}', (str(path),)).fetchone()[0] == 0
            assert review_edit_state(output, str(path), 'alice' if per_user else '') == clock


def test_viewer_incremental_preserves_deleted_preference_reset(tmp_path):
    from db.maintenance import export_viewer_db
    with _library(tmp_path, rating=0) as (conn, path, db):
        viewer = tmp_path / 'viewer.db'
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            output.execute("DELETE FROM user_preferences WHERE user_id='alice'")
            output.commit()
            clock = review_edit_state(output, str(path), 'alice')
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert output.execute("SELECT star_rating FROM user_preferences WHERE user_id='alice'").fetchone()[0] == 0
            assert review_edit_state(output, str(path), 'alice') == clock


@pytest.mark.parametrize('per_user', [False, True])
@pytest.mark.parametrize('new_photo', [False, True])
def test_incremental_does_not_copy_source_receipts_with_baseline_values(tmp_path, monkeypatch, per_user, new_photo):
    from db.maintenance import export_viewer_db
    from db.metadata_edits import record_sidecar_receipt
    with _library(tmp_path, rating=0) as (conn, original, db):
        viewer = tmp_path / 'viewer.db'
        export_viewer_db(str(db), str(viewer), verbose=False)
        path = tmp_path / 'later.jpg' if new_photo else original
        if new_photo:
            conn.execute('INSERT INTO photos(path,scanned_at) VALUES (?,?)', (str(path), '2020-01-01'))
        if per_user:
            conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        else:
            conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
        scope = 'alice' if per_user else ''
        filename = _write_sidecar(path)
        record_sidecar_receipt(conn, str(path), scope, ['star_rating'], str(filename), '2021-01-01T00:00:00+00:00')
        conn.commit()
        source_clock = review_edit_state(conn, str(path), scope)
        export_viewer_db(str(db), str(viewer), verbose=False)
        monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: per_user)
        monkeypatch.setattr('api.db_helpers.get_visibility_clause', lambda user: ('photos.path=?', [str(path)]))
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert source_clock
            assert review_edit_state(output, str(path), scope) == {}
            result = import_sidecars(output, str(path), user_id='alice' if per_user else None)
            assert result['conflicts'] == 0
            table = 'user_preferences' if per_user else 'photos'
            key = "photo_path=? AND user_id='alice'" if per_user else 'path=?'
            assert output.execute(f'SELECT star_rating FROM {table} WHERE {key}', (str(path),)).fetchone()[0] == 5


def test_incremental_source_deleted_preference_is_baseline_not_viewer_authority(tmp_path, monkeypatch):
    from db.maintenance import export_viewer_db
    with _library(tmp_path, rating=0) as (conn, path, db):
        viewer = tmp_path / 'viewer.db'
        export_viewer_db(str(db), str(viewer), verbose=False)
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        conn.execute("DELETE FROM user_preferences WHERE user_id='alice'")
        conn.commit()
        clock = review_edit_state(conn, str(path), 'alice')
        _write_sidecar(path)
        export_viewer_db(str(db), str(viewer), verbose=False)
        monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: True)
        monkeypatch.setattr('api.db_helpers.get_visibility_clause', lambda user: ('photos.path=?', [str(path)]))
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert clock
            assert review_edit_state(output, str(path), 'alice') == {}
            assert import_sidecars(output, str(path), user_id='alice')['conflicts'] == 0
            assert output.execute("SELECT star_rating FROM user_preferences WHERE user_id='alice'").fetchone()[0] == 5


def test_incremental_legacy_source_does_not_manufacture_clocks(tmp_path):
    from db.maintenance import export_viewer_db
    with _library(tmp_path, rating=0) as (conn, _, db):
        viewer = tmp_path / 'viewer.db'
        path = str(tmp_path / 'legacy.jpg')
        export_viewer_db(str(db), str(viewer), verbose=False)
        for (trigger,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'metadata_review_*'").fetchall():
            conn.execute('DROP TRIGGER "' + trigger.replace('"', '""') + '"')
        conn.execute('DROP TABLE photo_metadata_edits')
        conn.execute('INSERT INTO photos(path,star_rating) VALUES (?,3)', (path,))
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', path))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert output.execute('SELECT star_rating FROM photos WHERE path=?', (path,)).fetchone()[0] == 3
            assert review_edit_state(output, path, '') == {}
            assert review_edit_state(output, path, 'alice') == {}


def test_viewer_review_sync_failure_rolls_back_values_and_clocks(tmp_path):
    from db.metadata_edits import viewer_review_sync
    with _library(tmp_path, rating=1) as (conn, path, db):
        source = tmp_path / 'source.db'
        init_database(str(source))
        with sqlite3.connect(source) as origin:
            origin.execute('INSERT INTO photos(path,star_rating) VALUES (?,3)', (str(path),))
        conn.execute('ATTACH DATABASE ? AS src', (str(source),))
        with pytest.raises(RuntimeError, match='late replication failure'):
            with viewer_review_sync(conn, 'photos'):
                conn.execute('UPDATE photos SET star_rating=2 WHERE path=?', (str(path),))
                raise RuntimeError('late replication failure')
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (str(path),)).fetchone()[0] == 1
        assert review_edit_state(conn, str(path), '') == {}
        assert not conn.in_transaction
        assert not conn.execute("SELECT 1 FROM sqlite_temp_master WHERE name LIKE 'viewer_%edits'").fetchone()
        with sqlite3.connect(db, timeout=0.1) as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.rollback()


@pytest.mark.parametrize('dry_run', [False, True])
@pytest.mark.parametrize('fields', [[], ['unsupported']])
def test_invalid_field_policy_is_rejected_before_database_access(dry_run, fields):
    with pytest.raises(ValueError, match='fields must select'):
        import_sidecars(None, fields=fields, dry_run=dry_run)


@pytest.mark.parametrize('dry_run', [False, True])
def test_invalid_naming_policy_is_rejected_before_database_access(dry_run):
    with pytest.raises(ValueError, match='sidecar_naming'):
        import_sidecars(None, sidecar_naming='unsupported', dry_run=dry_run)


@pytest.mark.parametrize('naming', ['basename', 'auto'])
def test_basename_preview_and_apply_share_source_and_review_receipt(tmp_path, naming):
    with _library(tmp_path) as (conn, path, db):
        packet = _write_sidecar(path, tags=['external'])
        basename = path.with_suffix('.xmp')
        packet.rename(basename)
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        before = db.read_bytes()
        preview = import_sidecars(conn, dry_run=True, sidecar_naming=naming)
        assert preview['updated'] == 1
        assert preview['entries'][0]['sidecar'] == str(basename)
        assert preview['entries'][0]['changes']['star_rating']['after'] == 5
        assert db.read_bytes() == before
        applied = import_sidecars(conn, sidecar_naming=naming)
        assert applied['updated'] == 1
        assert applied['entries'] == preview['entries']
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 5
        assert review_edit_state(conn, str(path), '')['star_rating']['source'] == 'xmp'


def test_ambiguous_naming_preview_reports_refusal_without_receipts(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        _write_sidecar(path)
        path.with_suffix('.xmp').write_text(build_xmp(XmpRating(star_rating=2)), encoding='utf-8')
        preview = import_sidecars(conn, dry_run=True, sidecar_naming='auto')
        assert preview['ambiguous'] == preview['skipped'] == 1
        assert preview['entries'][0]['diagnostics'] == [{'reason': 'ambiguous'}]
        assert not preview['entries'][0]['changes']
        applied = import_sidecars(conn, sidecar_naming='auto')
        assert applied['updated'] == 0
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 1
        assert not review_edit_state(conn, str(path), '')


@pytest.mark.parametrize('per_user', [False, True])
@pytest.mark.parametrize('field', ['star_rating', 'is_favorite', 'is_rejected'])
def test_exported_source_reset_does_not_claim_viewer_authority(tmp_path, per_user, field):
    from db.maintenance import export_viewer_db
    with _library(tmp_path, rating=0) as (conn, path, db):
        viewer = tmp_path / 'viewer.db'
        table = 'user_preferences' if per_user else 'photos'
        key = "photo_path=? AND user_id='alice'" if per_user else 'path=?'
        if per_user:
            conn.execute('INSERT INTO user_preferences(user_id,photo_path) VALUES (?,?)', ('alice', str(path)))
        conn.execute(f'UPDATE {table} SET {field}=? WHERE {key}', (3 if field == 'star_rating' else 1, str(path)))
        conn.execute(f'UPDATE {table} SET {field}=0 WHERE {key}', (str(path),))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            output.row_factory = sqlite3.Row
            assert review_edit_state(output, str(path), 'alice' if per_user else '') == {}
        conn.execute(f'UPDATE {table} SET {field}=? WHERE {key}', (4 if field == 'star_rating' else 1, str(path)))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            assert output.execute(f'SELECT {field} FROM {table} WHERE {key}', (str(path),)).fetchone()[0] == (4 if field == 'star_rating' else 1)


@pytest.mark.parametrize('per_user', [False, True])
def test_readonly_preview_of_release_schema_without_keep_columns(tmp_path, monkeypatch, per_user):
    with _library(tmp_path, rating=0) as (conn, path, db):
        _write_sidecar(path, tags=['old-ai', 'manual'])
        from processing.xmp_export import NS_FACET
        from processing.xmp_keywords import serialize_keyword_state
        packet_path = Path(str(path) + '.xmp')
        packet = ET.parse(packet_path)
        packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_FACET}}}KeywordState', serialize_keyword_state({
            'version': 1, 'owned': [], 'deleted': ['manual'], 'ai': ['old-ai'], 'manual': []}))
        packet.write(packet_path, encoding='utf-8')
        if per_user:
            conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,0)', ('alice', str(path)))
        for (trigger,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND (name GLOB 'metadata_review_*' OR name GLOB 'organization_*' OR name GLOB 'logical_*')").fetchall():
            conn.execute('DROP TRIGGER "' + trigger.replace('"', '""') + '"')
        conn.execute('DROP TABLE photo_metadata_edits')
        for table in ('photos', 'user_preferences'):
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info({table})') if row[1] != 'is_kept']
            projection = ','.join('"' + column + '"' for column in columns)
            conn.execute(f'CREATE TABLE {table}_released AS SELECT {projection} FROM {table}')
            conn.execute(f'DROP TABLE {table}')
            conn.execute(f'ALTER TABLE {table}_released RENAME TO {table}')
        conn.commit()
        before = db.read_bytes()
        monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: per_user)
        monkeypatch.setattr('api.db_helpers.get_visibility_clause', lambda _user: ('1=1', []))
        with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as reader:
            reader.row_factory = sqlite3.Row
            result = import_sidecars(reader, dry_run=True, user_id='alice' if per_user else None)
            assert result['entries'][0]['changes']['star_rating']['after'] == 5
            assert result['entries'][0]['changes']['keywords'] == {'added': ['manual']}
            assert reader.total_changes == 0
        assert db.read_bytes() == before
        if not per_user:
            result = _run_facet('--db', str(db), '--import-sidecars', str(path), '--dry-run')
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout)['entries'][0]['changes']['star_rating']['after'] == 5
            assert db.read_bytes() == before


def test_preview_detail_and_diagnostic_limits_report_omissions(tmp_path):
    with _library(tmp_path, rating=0) as (conn, path, _):
        conn.executemany('INSERT INTO photos(path,scanned_at) VALUES (?,?)',
                         [(str(tmp_path / f'extra-{index}.jpg'), '2020-01-01') for index in range(1000)])
        conn.commit()
        _write_sidecar(path, rating=0, tags=[f'bad,keyword-{index}' for index in range(105)])
        result = import_sidecars(conn, dry_run=True)
        assert len(result['entries']) == 1000
        assert result['details_truncated'] == 1
        photo = next(entry for entry in result['entries'] if entry['path'] == str(path))
        assert len(photo['diagnostics']) == 100
        assert photo['diagnostics_omitted'] == 5
        assert conn.execute('SELECT COUNT(*) FROM photo_manual_tags').fetchone()[0] == 0


def test_preview_explains_scan_age_keyword_cap_people_and_ai_duplicates(tmp_path):
    with _library(tmp_path) as (conn, path, _):
        conn.execute("UPDATE photos SET tags='generated',scanned_at='2099-01-01' WHERE path=?", (str(path),))
        conn.execute("INSERT INTO persons(id,name) VALUES (1,'Alice')")
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id) VALUES (?,0,X'',1)", (str(path),))
        conn.executemany("INSERT INTO photo_manual_tags(photo_path,tag,source) VALUES (?,?,'user')",
                         [(str(path), f'present-{index}') for index in range(50)])
        conn.commit()
        _write_sidecar(path, tags=['generated', 'Alice', 'foreign'])
        entry = import_sidecars(conn, dry_run=True)['entries'][0]
        assert {row['reason'] for row in entry['diagnostics']} >= {'older_than_scan', 'tag_cap', 'person_name', 'ai_or_duplicate'}
        assert entry['changes'] == {}


def test_preview_reports_sidecar_inspection_failure_without_writes(tmp_path, monkeypatch):
    with _library(tmp_path) as (conn, _, _):
        def inaccessible(*_args):
            raise PermissionError('denied')
        monkeypatch.setattr('processing.xmp_import._discover_sidecar', inaccessible)
        result = import_sidecars(conn, dry_run=True)
        assert result['skipped'] == 1
        assert result['entries'][0]['diagnostics'] == [{'reason': 'sidecar_inspection_failed'}]
        assert conn.execute('SELECT COUNT(*) FROM photo_metadata_edits').fetchone()[0] == 0


@pytest.mark.parametrize('arguments,reason', [
    (['--sidecar-fields', 'review'], 'require --import-sidecars'),
    (['--overwrite-sidecar-review'], 'require --import-sidecars'),
    (['--import-sidecars', '--sidecar-fields', 'review,bogus'], 'must select review,gps,keywords'),
    (['--import-sidecars', '--sidecar-fields', ''], 'must select review,gps,keywords'),
])
def test_cli_rejects_invalid_import_policy_before_opening_database(tmp_path, arguments, reason):
    db = tmp_path / 'must-not-exist.db'
    result = _run_facet('--db', str(db), *arguments)
    assert result.returncode == 2
    assert reason in result.stderr
    assert not db.exists()


def test_cli_explicit_review_override_previews_and_applies_newer_local_conflict(tmp_path):
    conn, path, db = _seed_library(tmp_path)
    _write_sidecar(path)
    conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
    conn.commit()
    conn.close()
    base = ['--db', str(db), '--import-sidecars', str(path)]
    protected = _run_facet(*base, '--dry-run')
    assert protected.returncode == 0, protected.stderr
    assert json.loads(protected.stdout)['conflicts'] == 1
    override = _run_facet(*base, '--dry-run', '--overwrite-sidecar-review')
    assert override.returncode == 0, override.stderr
    assert json.loads(override.stdout)['updated'] == 1
    applied = _run_facet(*base, '--overwrite-sidecar-review')
    assert applied.returncode == 0, applied.stderr
    with sqlite3.connect(db) as output:
        assert output.execute('SELECT star_rating FROM photos').fetchone()[0] == 5


@pytest.mark.parametrize('per_user', [False, True])
def test_unknown_existing_viewer_receipt_origin_is_conservatively_preserved(tmp_path, per_user):
    from db.maintenance import export_viewer_db
    with _library(tmp_path, rating=0) as (conn, path, db):
        viewer = tmp_path / 'viewer.db'
        table = 'user_preferences' if per_user else 'photos'
        key = "photo_path=? AND user_id='alice'" if per_user else 'path=?'
        if per_user:
            conn.execute('INSERT INTO user_preferences(user_id,photo_path) VALUES (?,?)', ('alice', str(path)))
        conn.execute(f'UPDATE {table} SET star_rating=3 WHERE {key}', (str(path),))
        conn.execute(f'UPDATE {table} SET star_rating=0 WHERE {key}', (str(path),))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        # Model a previous preview build's copied receipts. Their format is
        # identical to actual local edits; automatic origin guessing is unsafe.
        rows = [tuple(row) for row in conn.execute('SELECT * FROM photo_metadata_edits')]
        with sqlite3.connect(viewer) as output:
            output.executemany('INSERT INTO photo_metadata_edits VALUES (?,?,?,?,?,?,?)', rows)
        conn.execute(f'UPDATE {table} SET star_rating=4 WHERE {key}', (str(path),))
        conn.commit()
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            assert output.execute(f'SELECT star_rating FROM {table} WHERE {key}', (str(path),)).fetchone()[0] == 0
            assert output.execute('SELECT * FROM photo_metadata_edits').fetchall() == rows


@pytest.mark.parametrize('per_user', [False, True])
def test_fresh_viewer_has_no_private_source_receipt_path_in_rows_or_file_bytes(tmp_path, per_user):
    from db.maintenance import export_viewer_db
    from db.metadata_edits import record_sidecar_receipt
    with _library(tmp_path, rating=0) as (conn, path, db):
        viewer = tmp_path / 'viewer.db'
        marker = '/private/scanner/DO-NOT-EXPORT-receipt-location.xmp'
        if per_user:
            conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        else:
            conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
        record_sidecar_receipt(conn, str(path), 'alice' if per_user else '', ['star_rating'], marker, '2025-01-02T03:04:05+00:00')
        conn.commit()
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        assert marker.encode() in db.read_bytes()
        export_viewer_db(str(db), str(viewer), verbose=False)
        with sqlite3.connect(viewer) as output:
            assert output.execute('SELECT COUNT(*) FROM photo_metadata_edits').fetchone()[0] == 0
        assert marker.encode() not in viewer.read_bytes()
        assert marker.encode() in db.read_bytes()


@pytest.mark.parametrize('per_user', [False, True])
def test_failed_viewer_sync_restores_existing_local_reset_and_receipt_snapshot(tmp_path, per_user):
    from db.metadata_edits import viewer_review_sync
    with _library(tmp_path, rating=1) as (conn, path, _):
        source = tmp_path / 'source.db'
        init_database(str(source))
        table = 'user_preferences' if per_user else 'photos'
        key = "photo_path=? AND user_id='alice'" if per_user else 'path=?'
        if per_user:
            conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,1)', ('alice', str(path)))
        conn.execute(f'UPDATE {table} SET star_rating=0 WHERE {key}', (str(path),))
        conn.commit()
        clock = review_edit_state(conn, str(path), 'alice' if per_user else '')
        assert clock
        with sqlite3.connect(source) as origin:
            origin.execute('INSERT INTO photos(path,star_rating) VALUES (?,3)', (str(path),))
            if per_user:
                origin.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        conn.execute('ATTACH DATABASE ? AS src', (str(source),))
        with pytest.raises(RuntimeError, match='replication failed'):
            with viewer_review_sync(conn, table):
                conn.execute(f'UPDATE {table} SET star_rating=2 WHERE {key}', (str(path),))
                raise RuntimeError('replication failed')
        assert conn.execute(f'SELECT star_rating FROM {table} WHERE {key}', (str(path),)).fetchone()[0] == 0
        assert review_edit_state(conn, str(path), 'alice' if per_user else '') == clock
        assert not conn.in_transaction


@pytest.mark.parametrize('per_user', [False, True])
@pytest.mark.parametrize('fields', [frozenset({'keywords'}), frozenset({'review', 'gps', 'keywords'})])
def test_preview_and_apply_share_keyword_provenance_without_overriding_review_clocks(tmp_path, monkeypatch, per_user, fields):
    from db.manual_tags import load_manual_tags
    from processing.xmp_export import NS_FACET
    from processing.xmp_keywords import serialize_keyword_state

    with _library(tmp_path, rating=0) as (conn, path, db):
        monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: per_user)
        monkeypatch.setattr('api.db_helpers.get_visibility_clause', lambda _user: ('1=1', []))
        if per_user:
            conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,3)', ('alice', str(path)))
        else:
            conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
        conn.execute("UPDATE photos SET tags='new-ai',gps_latitude=10,gps_longitude=20,gps_manually_set=1 WHERE path=?", (str(path),))
        conn.commit()
        filename = _write_sidecar(path, tags=['old-ai', 'restored', 'shared', 'a|hierarchy'], gps=True)
        packet = ET.parse(filename)
        packet.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_FACET}}}KeywordState', serialize_keyword_state({
            'version': 1, 'owned': ['shared'], 'deleted': ['restored', 'old-ai'],
            'ai': ['old-ai', 'shared'], 'manual': ['shared']}))
        packet.write(filename, encoding='utf-8')
        user = 'alice' if per_user else None
        clock = review_edit_state(conn, str(path), user or '')
        before = db.read_bytes()
        writes = conn.total_changes
        preview = import_sidecars(conn, str(path), user_id=user, fields=fields, dry_run=True)
        entry = preview['entries'][0]
        assert entry['changes'] == {'keywords': {'added': ['restored', 'shared', 'a|hierarchy']}}
        reasons = {d['reason'] for d in entry['diagnostics']}
        assert 'hierarchy_unsupported' not in reasons
        assert ('newer_local_edit' in reasons) == ('review' in fields)
        assert ('manual_gps_protected' in reasons) == ('gps' in fields)
        assert conn.total_changes == writes and db.read_bytes() == before
        applied = import_sidecars(conn, str(path), user_id=user, fields=fields)
        assert applied['entries'] == preview['entries']
        assert applied['tags_added'] == 3
        assert load_manual_tags(conn, str(path)) == ['a|hierarchy', 'restored', 'shared']
        assert review_edit_state(conn, str(path), user or '') == clock
        assert conn.execute('SELECT gps_latitude,gps_longitude FROM photos').fetchone()[:] == (10, 20)
        assert import_sidecars(conn, str(path), user_id=user, fields=fields)['tags_added'] == 0


@pytest.mark.parametrize('policy', ['full', 'basename', 'auto'])
def test_bounded_naming_notices_retain_per_photo_preview_diagnostics(tmp_path, caplog, policy):
    with _library(tmp_path, rating=0) as (conn, first, db):
        paths = [first, tmp_path / 'second.jpg', tmp_path / 'third.jpg']
        for path in paths[1:]:
            conn.execute('INSERT INTO photos(path,scanned_at) VALUES (?,?)', (str(path), '2020-01-01'))
        conn.commit()
        for path in paths:
            packet = _write_sidecar(path, tags=[f'bad,keyword-{index}' for index in range(105)])
            path.with_suffix('.xmp').write_bytes(packet.read_bytes())
        before, writes = db.read_bytes(), conn.total_changes
        result = import_sidecars(conn, dry_run=True, sidecar_naming=policy)
        assert result['full_ignored'] == (3 if policy == 'basename' else 0)
        assert result['basename_ignored'] == (3 if policy == 'full' else 0)
        assert len(result['entries']) == 3
        assert result['ambiguous'] == result['skipped'] == (3 if policy == 'auto' else 0)
        notices = [record for record in caplog.records if record.name == 'processing.xmp_import'
                   and 'further notices of this kind are suppressed' in record.getMessage()]
        assert len(notices) == 1
        for entry in result['entries']:
            if policy == 'auto':
                assert entry['changes'] == {}
                assert entry['diagnostics'] == [{'reason': 'ambiguous'}]
            else:
                assert len(entry['diagnostics']) == 100
                assert entry['diagnostics_omitted'] == 6
                assert entry['changes']['star_rating']['after'] == 5
                ignored = 'full_ignored' if policy == 'basename' else 'basename_ignored'
                assert entry['diagnostics'][0] == {'reason': ignored}
        assert conn.total_changes == writes and db.read_bytes() == before
        if policy != 'auto':
            completed = _run_facet('--db', str(db), '--import-sidecars', 'all', '--sidecar-naming', policy, '--dry-run')
            assert completed.returncode == 0, completed.stderr
            assert json.loads(completed.stdout)[ignored] == 3
            label = 'full-name' if policy == 'basename' else 'basename'
            assert f'3 {label} sidecars ignored' in completed.stderr
            assert f'preview ({policy})' in completed.stderr
            assert db.read_bytes() == before


def test_full_naming_does_not_count_another_images_full_name_sidecar_as_ignored(tmp_path, caplog):
    with _library(tmp_path, rating=0) as (conn, path, db):
        derivative = tmp_path / 'IMG.CR2.jpg'
        derivative.write_bytes(b'jpg')
        conn.execute('INSERT INTO photos(path,scanned_at) VALUES (?,?)', (str(derivative), '2020-01-01'))
        conn.commit()
        (tmp_path / 'IMG.CR2').write_bytes(b'raw')
        _write_sidecar(derivative)
        _write_sidecar(tmp_path / 'IMG.CR2')
        result = import_sidecars(conn, str(derivative), dry_run=True, sidecar_naming='full')
        assert result['basename_ignored'] == 0
        assert result['entries'][0]['diagnostics'] == []
        assert not [record for record in caplog.records if record.name == 'processing.xmp_import']


def test_malformed_basename_preview_retains_selection_and_parse_diagnostics(tmp_path):
    with _library(tmp_path, rating=0) as (conn, path, db):
        full = _write_sidecar(path, rating=5)
        basename = path.with_suffix('.xmp')
        basename.write_bytes(b'not an XMP packet')
        db_before, full_before, basename_before = db.read_bytes(), full.read_bytes(), basename.read_bytes()
        result = import_sidecars(conn, sidecar_naming='basename', dry_run=True)
        assert result['full_ignored'] == result['skipped'] == 1
        assert result['updated'] == 0
        assert result['entries'] == [{'path': str(path), 'sidecar': str(basename), 'changes': {},
                                      'diagnostics': [{'reason': 'full_ignored'}, {'reason': 'unparseable_sidecar'}]}]
        assert db.read_bytes() == db_before
        assert full.read_bytes() == full_before
        assert basename.read_bytes() == basename_before
        assert conn.execute('SELECT star_rating FROM photos').fetchone()[0] == 0


@pytest.mark.parametrize('dry_run', [True, False])
@pytest.mark.parametrize('secret_store', ['missing', 'directory'])
def test_global_import_cli_does_not_initialize_viewer_secret(tmp_path, dry_run, secret_store):
    import os
    conn, image, db = _seed_library(tmp_path)
    packet = _write_sidecar(image).read_bytes()
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.close()
    before = db.read_bytes()
    install = tmp_path / 'config'
    install.mkdir()
    config = install / 'scoring_config.json'
    config.write_text('{}', encoding='utf-8')
    secret = install / '.facet_secret'
    if secret_store == 'directory':
        secret.mkdir()
    environment = os.environ.copy()
    environment.pop('FACET_JWT_SECRET', None)
    environment['FACET_CONFIG'] = str(config)
    command = ['--db', str(db), '--import-sidecars', str(image)]
    if dry_run:
        command.append('--dry-run')
    result = _run_facet(*command, env=environment, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    assert 'Traceback' not in result.stderr
    if dry_run:
        assert json.loads(result.stdout)['updated'] == 1
        assert db.read_bytes() == before
    with sqlite3.connect(db) as output:
        assert output.execute('SELECT star_rating FROM photos').fetchone()[0] == (1 if dry_run else 5)
    assert Path(str(image) + '.xmp').read_bytes() == packet
    assert config.read_bytes() == b'{}'
    if secret_store == 'directory':
        assert secret.is_dir() and list(secret.iterdir()) == []
    else:
        assert not secret.exists()
    assert {entry.name for entry in install.iterdir()} == (
        {'scoring_config.json', '.facet_secret'} if secret_store == 'directory' else {'scoring_config.json'})


@pytest.mark.parametrize('database_state', ['corrupt', 'empty'])
def test_global_import_preview_database_refusal_needs_no_viewer_secret(tmp_path, database_state):
    import os
    db = tmp_path / 'library.db'
    if database_state == 'corrupt':
        db.write_bytes(b'not a SQLite database')
    else:
        with sqlite3.connect(db):
            pass
    before = db.read_bytes()
    config = tmp_path / 'scoring_config.json'
    config.write_text('{}', encoding='utf-8')
    secret = tmp_path / '.facet_secret'
    secret.mkdir()
    environment = os.environ.copy()
    environment.pop('FACET_JWT_SECRET', None)
    environment['FACET_CONFIG'] = str(config)
    result = _run_facet('--db', str(db), '--import-sidecars', '--dry-run', env=environment, encoding='utf-8')
    assert result.returncode == 1
    assert result.stdout == ''
    assert 'Sidecar import preview failed' in result.stderr
    assert 'readable Facet database' in result.stderr
    assert 'Traceback' not in result.stderr
    assert db.read_bytes() == before
    assert secret.is_dir() and list(secret.iterdir()) == []
    assert config.read_bytes() == b'{}'
