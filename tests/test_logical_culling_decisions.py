"""Culling decisions use logical authority without mutating member file labels."""
import sqlite3
from contextlib import nullcontext

import pytest

from api import config, logical_reviews, organization_capture
from api.db_helpers import set_photos_kept, set_photos_rejected, record_culling_decision
from db import logical_assets, logical_review, logical_history
from db.schema import init_database


@pytest.mark.parametrize('rejected', [False, True])
@pytest.mark.parametrize('personal', [False, True])
@pytest.mark.parametrize('agent', [False, True])
@pytest.mark.parametrize('grouped', [False, True])
def test_culling_helper_writes_one_logical_decision_and_one_independent_file(tmp_path, monkeypatch, rejected, personal, agent, grouped):
    database = tmp_path / 'culling.db'
    init_database(str(database))
    user = 'alice' if personal else None
    owner = user or ''
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'alice': {'role': 'admin', 'directories': [str(tmp_path)]},
        'bob': {'role': 'user', 'directories': [str(tmp_path)]},
    } if personal else {})
    jpg, raw, ordinary = [str(tmp_path / name) for name in ('pair.jpg', 'pair.cr2', 'ordinary.jpg')]
    labels = {path: dict(star_rating=0, is_favorite=0, is_rejected=0, is_kept=0) for path in (jpg, raw)}
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.executemany('INSERT INTO photos(path,star_rating,is_favorite,is_rejected,is_kept) VALUES (?,0,0,0,0)',
                         [(path,) for path in (jpg, raw, ordinary)])
        key = logical_assets.create(conn, [jpg, raw], raw, visibility_sql='1=1')
        logical_review.seed(conn, key, jpg, 1, visibility_sql='1=1')
        state = logical_review.read(conn, key, owner, labels)
        logical_review.set_fields(conn, key, owner, 1, state['revision'],
            {'is_rejected': int(not rejected), 'is_kept': int(rejected), 'star_rating': 4, 'is_favorite': 1},
            origin='user', visibility_sql='1=1', file_labels=labels, input_token=state['input_token'])
        conn.commit()
        write = set_photos_rejected if rejected else set_photos_kept
        with organization_capture.action(conn, user) if grouped else nullcontext():
            if grouped:
                earlier = set_photos_kept if rejected else set_photos_rejected
                assert earlier(conn, [jpg, raw, ordinary], user, agent=agent) == 2
            assert write(conn, iter([jpg, raw, ordinary]), user, agent=agent) == 2
        conn.commit()
        conn.execute('BEGIN')
        current = logical_reviews.read(conn, key, user)
        assert current['values'] == {'is_rejected': int(rejected), 'is_kept': int(not rejected), 'star_rating': 4, 'is_favorite': 1}
        assert current['origins']['is_rejected'] == ('agent' if agent else 'user')
        assert conn.execute('SELECT COUNT(*) FROM organization_history').fetchone()[0] == 1
        rows = conn.execute('SELECT path,is_rejected,is_kept,star_rating,is_favorite FROM photos WHERE path IN (?,?)', (jpg, raw)).fetchall()
        assert {row['path']: tuple(row)[1:] for row in rows} == {jpg: (0, 0, 0, 0), raw: (0, 0, 0, 0)}
        if personal:
            assert conn.execute('SELECT COUNT(*) FROM user_preferences WHERE photo_path IN (?,?)', (jpg, raw)).fetchone()[0] == 0
            decision = conn.execute('SELECT is_rejected,is_kept FROM user_preferences WHERE photo_path=? AND user_id=?', (ordinary, user)).fetchone()
        else:
            decision = conn.execute('SELECT is_rejected,is_kept FROM photos WHERE path=?', (ordinary,)).fetchone()
        assert tuple(decision) == (int(rejected), int(not rejected))
        entry = conn.execute('SELECT id FROM organization_history').fetchone()[0]
        assert logical_history.restore(conn, user or '', owner, entry, labels, visibility_sql='1=1') == 2
        restored = logical_reviews.read(conn, key, user)['values']
        assert restored == {'is_rejected': int(not rejected), 'is_kept': int(rejected), 'star_rating': 4, 'is_favorite': 1}
        if personal:
            original = conn.execute('SELECT is_rejected,is_kept FROM user_preferences WHERE photo_path=? AND user_id=?', (ordinary, user)).fetchone()
        else:
            original = conn.execute('SELECT is_rejected,is_kept FROM photos WHERE path=?', (ordinary,)).fetchone()
        assert tuple(original) == (0, 0)


def test_culling_helper_refuses_partial_group_before_independent_file_write(tmp_path, monkeypatch):
    from fastapi import HTTPException

    visible = tmp_path / 'visible'
    hidden = tmp_path / 'hidden'
    jpg, raw, ordinary = str(visible / 'pair.jpg'), str(hidden / 'pair.cr2'), str(visible / 'ordinary.jpg')
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'alice': {'role': 'user', 'directories': [str(visible)]},
        'bob': {'role': 'admin', 'directories': [str(tmp_path)]},
    })
    database = tmp_path / 'hidden.db'
    init_database(str(database))
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.executemany('INSERT INTO photos(path,is_rejected,is_kept) VALUES (?,0,0)', [(p,) for p in (jpg, raw, ordinary)])
        logical_assets.create(conn, [jpg, raw], jpg, visibility_sql='1=1')
        conn.commit()
        with pytest.raises(HTTPException) as error:
            set_photos_rejected(conn, [ordinary, jpg], 'alice')
        assert error.value.status_code == 404
        assert raw not in str(error.value.detail)
        assert conn.execute('SELECT COUNT(*) FROM user_preferences').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM logical_review_fields').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM organization_history').fetchone()[0] == 0
        assert [tuple(row) for row in conn.execute('SELECT is_rejected,is_kept FROM photos')] == [(0, 0)] * 3


def test_committing_cull_rolls_back_labels_when_mixed_history_refuses(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from db.logical_assets import AssetConflict

    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    database = tmp_path / 'rollback.db'
    init_database(str(database))
    jpg, raw, ordinary = [str(tmp_path / name) for name in ('a.jpg', 'a.cr2', 'ordinary.jpg')]
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.executemany('INSERT INTO photos(path,is_rejected,is_kept) VALUES (?,0,0)', [(p,) for p in (jpg, raw, ordinary)])
        key = logical_assets.create(conn, [jpg, raw], jpg, visibility_sql='1=1')
        logical_review.seed(conn, key, jpg, 1, visibility_sql='1=1')
        conn.commit()

        def refuse(*args, **kwargs):
            raise AssetConflict('History cannot represent this action')

        monkeypatch.setattr(logical_history, 'record', refuse)
        with pytest.raises(HTTPException) as error:
            record_culling_decision(conn, [jpg, ordinary], [], set(), record=False)
        assert error.value.status_code == 409
    with sqlite3.connect(database) as reopened:
        assert reopened.execute('SELECT COUNT(*) FROM photos WHERE is_kept=1 OR is_rejected=1').fetchone()[0] == 0
        assert reopened.execute('SELECT COUNT(*) FROM logical_review_fields').fetchone()[0] == 0
        assert reopened.execute('SELECT COUNT(*) FROM organization_history').fetchone()[0] == 0


@pytest.mark.parametrize('raw_primary', [False, True])
@pytest.mark.parametrize('burst_aliases', [False, True])
@pytest.mark.parametrize('protection', [None, 'exclude', 'comparison'])
def test_standalone_threshold_uses_only_the_chosen_representation(tmp_path, monkeypatch, raw_primary, burst_aliases, protection):
    from api.routers.burst_culling import reject_standalone_below
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    database = tmp_path / 'threshold.db'
    init_database(str(database))
    jpg, raw = str(tmp_path / 'pair.jpg'), str(tmp_path / 'pair.cr2')
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.executemany('INSERT INTO photos(path,aggregate,is_rejected,is_kept,star_rating,is_favorite) VALUES (?,?,0,0,0,0)', [(jpg, 9), (raw, 1)])
        if burst_aliases:
            conn.execute('UPDATE photos SET burst_group_id=7')
        key = logical_assets.create(conn, [jpg, raw], raw if raw_primary else jpg, visibility_sql='1=1')
        logical_review.seed(conn, key, jpg, 1, visibility_sql='1=1')
        if protection == 'comparison':
            other = str(tmp_path / 'other.jpg')
            conn.execute('INSERT INTO photos(path,is_rejected,is_kept,star_rating,is_favorite) VALUES (?,0,0,0,0)', (other,))
            conn.execute("INSERT INTO comparisons(photo_a_path,photo_b_path,winner,source) VALUES (?,?,'a','culling')", (raw, other))
        conn.commit()
        excluded = [jpg if raw_primary else raw] if protection == 'exclude' else []
        result = reject_standalone_below(conn, None, None, 10 if protection else 5, excluded, False)
        qualifies = raw_primary and protection is None
        assert result == ([raw] if qualifies else [])
        conn.execute('BEGIN')
        assert logical_reviews.read(conn, key, None)['values']['is_rejected'] == int(qualifies)
        assert [tuple(row) for row in conn.execute('SELECT is_rejected,is_kept FROM photos')] == [(0, 0)] * (3 if protection == 'comparison' else 2)
