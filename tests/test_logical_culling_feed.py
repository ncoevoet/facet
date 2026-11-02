"""Culling burst membership/counts use logical primary representations."""
import sqlite3

import pytest

from api import config
from api.routers.burst_culling import _count_unreviewed_burst_groups, _query_burst_groups, attach_user_marks
from db import logical_assets, logical_review
from db.schema import init_database


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    database = tmp_path / 'feed.db'
    init_database(str(database))
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        jpg, raw, other = [str(tmp_path / name) for name in ('pair.jpg', 'pair.CR2', 'other.jpg')]
        conn.executemany('INSERT INTO photos(path,filename,aggregate,burst_group_id,is_burst_lead,date_taken,is_rejected,is_kept,star_rating,is_favorite) VALUES (?,?,?,1,1,?,0,0,0,0)',
                         [(jpg, 'pair.jpg', 9, '2026:10:01 10:00:00'), (raw, 'pair.CR2', 3, '2026:10:01 10:00:00'), (other, 'other.jpg', 7, '2026:10:01 10:00:01')])
        key = logical_assets.create(conn, [jpg, raw], raw, visibility_sql='1=1')
        logical_review.seed(conn, key, jpg, 1, visibility_sql='1=1')
        conn.commit()
        yield conn, key, jpg, raw, other


def test_burst_lists_primary_once_and_counts_logical_photos(catalog):
    conn, _, jpg, raw, other = catalog
    groups, total, pages = _query_burst_groups(conn, '1=1', [], page=1, per_page=1)
    assert total == pages == 1
    assert {p['path'] for p in groups[0]['photos']} == {raw, other}
    assert next(p for p in groups[0]['photos'] if p['path'] == raw)['aggregate'] == 3
    assert groups[0]['count'] == 2
    assert groups[0]['best_path'] == other
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 3


def test_duplicate_representations_alone_do_not_create_a_review_group(catalog):
    conn, _, _, _, other = catalog
    conn.execute('DELETE FROM photos WHERE path=?', (other,))
    conn.commit()
    groups, total, _ = _query_burst_groups(conn, '1=1', [], page=1, per_page=1)
    assert groups == []
    assert total == 0


def test_album_member_alias_selects_primary_without_requiring_both_files(catalog):
    conn, _, jpg, raw, other = catalog
    conn.execute("INSERT INTO albums(id,name) VALUES (7,'Chosen')")
    conn.executemany('INSERT INTO album_photos(album_id,photo_path) VALUES (7,?)', [(jpg,), (other,)])
    conn.commit()
    groups, total, _ = _query_burst_groups(conn, '1=1', [], album_id=7)
    assert total == 1
    assert {p['path'] for p in groups[0]['photos']} == {raw, other}


def test_window_qualifies_a_group_without_truncating_its_tail(catalog):
    conn, _, _, raw, other = catalog
    groups, total, _ = _query_burst_groups(conn, '1=1', [], date_from='2026:10:01 10:00:00', date_to='2026:10:01 10:00:00')
    assert total == 1
    assert {p['path'] for p in groups[0]['photos']} == {raw, other}


def test_partial_visibility_never_uses_hidden_primary_or_shared_marks(catalog):
    conn, key, jpg, raw, other = catalog
    conn.execute("INSERT INTO logical_review_fields VALUES (?, '', 'decision', 2, 'user')", (key,))
    conn.commit()
    groups, total, _ = _query_burst_groups(conn, 'photos.path<>?', [raw], exclude_rejected=True)
    assert total == 1
    assert {p['path'] for p in groups[0]['photos']} == {jpg, other}


def test_shared_rejection_filters_the_logical_photo_and_stamps_current_marks(catalog):
    conn, key, _, raw, other = catalog
    conn.execute("INSERT INTO logical_review_fields VALUES (?, '', 'decision', 2, 'user')", (key,))
    conn.commit()
    groups, total, _ = _query_burst_groups(conn, '1=1', [], exclude_rejected=True)
    assert groups == [] and total == 0
    groups, _, _ = _query_burst_groups(conn, '1=1', [])
    attach_user_marks(conn, groups, None)
    marks = {p['path']: p['is_rejected'] for p in groups[0]['photos']}
    assert marks == {raw: 1, other: 0}
    assert conn.execute('SELECT SUM(is_rejected) FROM photos').fetchone()[0] == 0


def test_unreviewed_count_matches_the_feed_total(catalog):
    conn, _, _, _, other = catalog
    assert _count_unreviewed_burst_groups(conn, '1=1', []) == 1
    conn.execute('DELETE FROM photos WHERE path=?', (other,))
    conn.commit()
    assert _count_unreviewed_burst_groups(conn, '1=1', []) == 0
