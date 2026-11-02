"""Durable receipts restore sparse logical authority, never original file labels."""
import sqlite3

import pytest

from db import logical_assets as assets, logical_review as review, logical_history as history
from db.organization_history import init_schema

LABELS = {'/a.jpg': dict(star_rating=5, is_favorite=0, is_rejected=0, is_kept=1),
          '/a.CR2': dict(star_rating=2, is_favorite=0, is_rejected=1, is_kept=0)}


@pytest.fixture
def catalog(tmp_path):
    filename = tmp_path / 'history.db'
    conn = sqlite3.connect(filename)
    conn.execute('CREATE TABLE photos(path TEXT PRIMARY KEY,star_rating INTEGER,is_favorite INTEGER,is_rejected INTEGER,is_kept INTEGER,gps_latitude REAL,gps_longitude REAL,gps_manually_set INTEGER,date_taken TEXT,date_manually_set INTEGER)')
    conn.execute('CREATE TABLE user_preferences(user_id TEXT,photo_path TEXT,star_rating INTEGER,is_favorite INTEGER,is_rejected INTEGER,is_kept INTEGER,PRIMARY KEY(user_id,photo_path))')
    assets.init_schema(conn)
    review.init_schema(conn)
    init_schema(conn)
    conn.executemany('INSERT INTO photos(path,star_rating,is_favorite,is_rejected,is_kept) VALUES (?,?,?,?,?)',
                     [(path, *labels.values()) for path, labels in LABELS.items()])
    conn.commit()
    conn.execute('BEGIN')
    key = assets.create(conn, list(LABELS), '/a.jpg', visibility_sql='1=1')
    review.seed(conn, key, '/a.jpg', 1, visibility_sql='1=1')
    conn.commit()
    yield conn, filename, key
    conn.close()


def edit(conn, key, value):
    before = history.capture(conn, key, 'alice', LABELS)
    review.set_fields(conn, key, 'alice', before['group_revision'], before['revision'], {'star_rating': value},
                      origin='user', visibility_sql='1=1', file_labels=LABELS, input_token=before['input_token'])
    after = history.capture(conn, key, 'alice', LABELS)
    return history.record(conn, 'alice', 'alice', {key: before}, {key: after})[0]


def test_receipt_survives_reopen_and_restores_inheritance_without_original_writes(catalog):
    conn, filename, key = catalog
    originals = conn.execute('SELECT * FROM photos ORDER BY path').fetchall()
    conn.execute('BEGIN IMMEDIATE')
    entry = edit(conn, key, 4)
    conn.commit()
    conn.close()
    with sqlite3.connect(filename) as reopened:
        reopened.execute('BEGIN IMMEDIATE')
        assert history.restore(reopened, 'alice', 'alice', entry, LABELS, visibility_sql='1=1') == 1
        state = review.read(reopened, key, 'alice', LABELS)
        assert state['values']['star_rating'] == 5 and state['origins']['star_rating'] == 'file'
        assert reopened.execute('SELECT COUNT(*) FROM logical_review_fields').fetchone()[0] == 0
        assert reopened.execute('SELECT * FROM photos ORDER BY path').fetchall() == originals
        assert reopened.execute('SELECT reverted FROM organization_history WHERE id=?', (entry,)).fetchone()[0] == 1
        assert reopened.execute('SELECT COUNT(*) FROM organization_history').fetchone()[0] == 2


@pytest.mark.parametrize('change', ['account', 'edit_aba', 'primary', 'visibility'])
def test_changed_scope_or_revision_refuses_whole_undo(catalog, change):
    conn, _, key = catalog
    conn.execute('BEGIN IMMEDIATE')
    entry = edit(conn, key, 4)
    if change == 'edit_aba':
        edit(conn, key, 3)
        edit(conn, key, 4)
    elif change == 'primary':
        assets.set_primary(conn, key, '/a.CR2', 1, visibility_sql='1=1')
    before = conn.execute('SELECT * FROM logical_review_fields').fetchall()
    with pytest.raises(assets.AssetConflict):
        history.restore(conn, 'mallory' if change == 'account' else 'alice', 'alice', entry, LABELS,
                        visibility_sql='photos.path != ?' if change == 'visibility' else '1=1',
                        visibility_params=('/a.CR2',) if change == 'visibility' else ())
    assert conn.execute('SELECT * FROM logical_review_fields').fetchall() == before
    assert conn.execute('SELECT reverted FROM organization_history WHERE id=?', (entry,)).fetchone()[0] == 0


def test_undo_preserves_explicit_null_and_agent_origin(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN IMMEDIATE')
    state = review.read(conn, key, 'alice', LABELS)
    review.set_fields(conn, key, 'alice', 1, state['revision'], {'star_rating': None}, origin='agent',
                      visibility_sql='1=1', file_labels=LABELS, input_token=state['input_token'])
    entry = edit(conn, key, 4)
    history.restore(conn, 'alice', 'alice', entry, LABELS, visibility_sql='1=1')
    assert conn.execute('SELECT value,origin FROM logical_review_fields WHERE asset_id=? AND field=?',
                        (key, 'star_rating')).fetchone() == (None, 'agent')
    state = review.read(conn, key, 'alice', LABELS)
    assert state['values']['star_rating'] is None and state['origins']['star_rating'] == 'agent'


def test_failed_inverse_receipt_rolls_back_values_clocks_and_reverted_marker(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN IMMEDIATE')
    entry = edit(conn, key, 4)
    before = history.capture(conn, key, 'alice', LABELS)
    clocks = conn.execute('SELECT * FROM logical_review_field_versions').fetchall()
    conn.execute("CREATE TRIGGER fail_inverse BEFORE INSERT ON organization_history BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        history.restore(conn, 'alice', 'alice', entry, LABELS, visibility_sql='1=1')
    assert history.capture(conn, key, 'alice', LABELS) == before
    assert conn.execute('SELECT * FROM logical_review_field_versions').fetchall() == clocks
    assert conn.execute('SELECT reverted FROM organization_history WHERE id=?', (entry,)).fetchone()[0] == 0


def test_bounded_private_history_keeps_latest_receipts(catalog, monkeypatch):
    conn, _, key = catalog
    monkeypatch.setattr(history, 'MAX_ENTRIES', 2)
    conn.execute('BEGIN IMMEDIATE')
    entries = [edit(conn, key, value) for value in (4, 3, 2)]
    assert [row[0] for row in conn.execute('SELECT id FROM organization_history ORDER BY id')] == entries[-2:]


def two_asset_edit(conn, first):
    labels = {**LABELS, '/b.jpg': dict(star_rating=5, is_favorite=0, is_rejected=0, is_kept=0),
              '/b.CR2': dict(star_rating=2, is_favorite=0, is_rejected=0, is_kept=0)}
    conn.executemany('INSERT INTO photos(path,star_rating,is_favorite,is_rejected,is_kept) VALUES (?,?,?,?,?)',
                     [(path, *values.values()) for path, values in labels.items() if path.startswith('/b.')])
    second = assets.create(conn, ['/b.jpg', '/b.CR2'], '/b.jpg', visibility_sql='1=1')
    review.seed(conn, second, '/b.jpg', 1, visibility_sql='1=1')
    before = {key: history.capture(conn, key, 'alice', labels) for key in (first, second)}
    for key, state in before.items():
        review.set_fields(conn, key, 'alice', 1, state['revision'], {'star_rating': 4}, origin='user',
                          visibility_sql='1=1', file_labels=labels, input_token=state['input_token'])
    after = {key: history.capture(conn, key, 'alice', labels) for key in before}
    return labels, before, after


def test_one_stale_asset_prevents_every_change_in_receipt(catalog):
    conn, _, first = catalog
    conn.execute('BEGIN IMMEDIATE')
    labels, before, after = two_asset_edit(conn, first)
    entry = history.record(conn, 'alice', 'alice', before, after)[0]
    second = next(key for key in after if key != first)
    review.set_fields(conn, second, 'alice', 1, after[second]['revision'], {'star_rating': 3}, origin='user',
                      visibility_sql='1=1', file_labels=labels, input_token=after[second]['input_token'])
    fields = conn.execute('SELECT * FROM logical_review_fields ORDER BY asset_id,field').fetchall()
    clocks = conn.execute('SELECT * FROM logical_review_versions ORDER BY asset_id').fetchall()
    with pytest.raises(assets.AssetConflict):
        history.restore(conn, 'alice', 'alice', entry, labels, visibility_sql='1=1')
    assert conn.execute('SELECT * FROM logical_review_fields ORDER BY asset_id,field').fetchall() == fields
    assert conn.execute('SELECT * FROM logical_review_versions ORDER BY asset_id').fetchall() == clocks
    assert conn.execute('SELECT reverted FROM organization_history WHERE id=?', (entry,)).fetchone()[0] == 0


def test_multipart_receipts_are_complete_and_each_reverts_atomically(catalog, monkeypatch):
    import json
    conn, _, first = catalog
    conn.execute('BEGIN IMMEDIATE')
    labels, before, after = two_asset_edit(conn, first)
    monkeypatch.setattr(history, 'MAX_PHOTOS', 1)
    entries = history.record(conn, 'alice', 'alice', before, after)
    assert len(entries) == 2
    rows = conn.execute('SELECT payload,part,parts FROM organization_history ORDER BY id').fetchall()
    assert [(row[1], row[2]) for row in rows] == [(1, 2), (2, 2)]
    assert {change['asset_id'] for row in rows for change in json.loads(row[0])} == set(before)
    assert all(len(row[0].encode('utf-8')) <= history.MAX_BYTES for row in rows)
    for entry in entries:
        assert history.restore(conn, 'alice', 'alice', entry, labels, visibility_sql='1=1') == 1
    assert all(review.read(conn, key, 'alice', labels)['values']['star_rating'] == 5 for key in before)


def test_oversize_receipt_is_refused_without_partial_history(catalog, monkeypatch):
    conn, _, first = catalog
    conn.execute('BEGIN IMMEDIATE')
    _, before, after = two_asset_edit(conn, first)
    monkeypatch.setattr(history, 'MAX_BYTES', 64)
    with pytest.raises(assets.AssetConflict, match='too large'):
        history.record(conn, 'alice', 'alice', before, after)
    assert conn.execute('SELECT COUNT(*) FROM organization_history').fetchone()[0] == 0


def test_changed_inherited_file_labels_refuse_undo_without_rewinding_scanner(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN IMMEDIATE')
    entry = edit(conn, key, 4)
    conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', ('/a.jpg',))
    labels = {path: dict(values) for path, values in LABELS.items()}
    labels['/a.jpg']['star_rating'] = 3
    with pytest.raises(assets.AssetConflict):
        history.restore(conn, 'alice', 'alice', entry, labels, visibility_sql='1=1')
    assert conn.execute('SELECT star_rating FROM photos WHERE path=?', ('/a.jpg',)).fetchone()[0] == 3
    assert review.read(conn, key, 'alice', labels)['values']['star_rating'] == 4


@pytest.mark.parametrize('ending', ['restore', 'physical_conflict', 'logical_conflict', 'inverse_failure'])
def test_mixed_receipt_survives_reopen_and_has_one_atomic_boundary(catalog, ending):
    from db.organization_history import snapshot

    conn, filename, key = catalog
    conn.execute('BEGIN IMMEDIATE')
    conn.execute("INSERT INTO photos(path,star_rating,is_favorite,is_rejected,is_kept) VALUES ('/ordinary.jpg',2,0,0,0)")
    physical_before = snapshot(conn, 'review', '', ['/ordinary.jpg'])
    before = history.capture(conn, key, '', LABELS)
    review.set_fields(conn, key, '', 1, before['revision'], {'star_rating': 4}, origin='user',
                      visibility_sql='1=1', file_labels=LABELS, input_token=before['input_token'])
    conn.execute("UPDATE photos SET star_rating=4 WHERE path='/ordinary.jpg'")
    entry = history.record(conn, '', '', {key: before}, {key: history.capture(conn, key, '', LABELS)},
                           physical_before=physical_before)[0]
    conn.commit()
    conn.close()
    with sqlite3.connect(filename) as reopened:
        reopened.execute('BEGIN IMMEDIATE')
        if ending == 'physical_conflict':
            reopened.execute("UPDATE photos SET star_rating=3 WHERE path='/ordinary.jpg'")
        elif ending == 'logical_conflict':
            now = history.capture(reopened, key, '', LABELS)
            review.set_fields(reopened, key, '', 1, now['revision'], {'star_rating': 3}, origin='user',
                              visibility_sql='1=1', file_labels=LABELS, input_token=now['input_token'])
        elif ending == 'inverse_failure':
            reopened.execute("CREATE TRIGGER fail_mixed_inverse BEFORE INSERT ON organization_history BEGIN SELECT RAISE(ABORT,'injected'); END")
        previous = history.capture(reopened, key, '', LABELS)
        physical = snapshot(reopened, 'review', '', ['/ordinary.jpg'])
        if ending == 'restore':
            assert history.restore(reopened, '', '', entry, LABELS, visibility_sql='1=1') == 2
            assert review.read(reopened, key, '', LABELS)['values']['star_rating'] == 5
            assert reopened.execute("SELECT star_rating FROM photos WHERE path='/ordinary.jpg'").fetchone()[0] == 2
        else:
            error = sqlite3.IntegrityError if ending == 'inverse_failure' else assets.AssetConflict
            with pytest.raises(error):
                history.restore(reopened, '', '', entry, LABELS, visibility_sql='1=1')
            assert history.capture(reopened, key, '', LABELS) == previous
            assert snapshot(reopened, 'review', '', ['/ordinary.jpg']) == physical
            assert reopened.execute('SELECT reverted FROM organization_history WHERE id=?', (entry,)).fetchone()[0] == 0


def test_mixed_receipt_can_contain_only_physical_changes_after_logical_noop(catalog):
    from db.organization_history import snapshot
    conn, _, key = catalog
    conn.execute('BEGIN IMMEDIATE')
    conn.execute("INSERT INTO photos(path,star_rating,is_favorite,is_rejected,is_kept) VALUES ('/ordinary.jpg',2,0,0,0)")
    physical = snapshot(conn, 'review', '', ['/ordinary.jpg'])
    same = history.capture(conn, key, '', LABELS)
    conn.execute("UPDATE photos SET star_rating=4 WHERE path='/ordinary.jpg'")
    entry = history.record(conn, '', '', {key: same}, {key: same}, physical_before=physical)[0]
    assert history.restore(conn, '', '', entry, LABELS, visibility_sql='1=1') == 1
    assert conn.execute("SELECT star_rating FROM photos WHERE path='/ordinary.jpg'").fetchone()[0] == 2
    assert history.capture(conn, key, '', LABELS) == same


def test_hidden_physical_target_refuses_all_logical_restore(catalog):
    from db.organization_history import snapshot
    conn, _, key = catalog
    conn.execute('BEGIN IMMEDIATE')
    conn.execute("INSERT INTO photos(path,star_rating,is_favorite,is_rejected,is_kept) VALUES ('/ordinary.jpg',2,0,0,0)")
    physical = snapshot(conn, 'review', '', ['/ordinary.jpg'])
    before = history.capture(conn, key, '', LABELS)
    review.set_fields(conn, key, '', 1, before['revision'], {'star_rating': 4}, origin='user',
                      visibility_sql='1=1', file_labels=LABELS, input_token=before['input_token'])
    after = history.capture(conn, key, '', LABELS)
    conn.execute("UPDATE photos SET star_rating=4 WHERE path='/ordinary.jpg'")
    entry = history.record(conn, '', '', {key: before}, {key: after}, physical_before=physical)[0]
    with pytest.raises(assets.AssetConflict):
        history.restore(conn, '', '', entry, LABELS, visibility_sql='photos.path != ?',
                        visibility_params=['/ordinary.jpg'])
    assert history.capture(conn, key, '', LABELS) == after
    assert conn.execute("SELECT star_rating FROM photos WHERE path='/ordinary.jpg'").fetchone()[0] == 4
