"""Culling learns from logical identities and their explicit representations."""
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import config, db_helpers
from db import logical_assets, logical_review
from db.schema import init_database


@pytest.fixture()
def library(tmp_path, monkeypatch):
    database = tmp_path / 'pairs.db'
    init_database(str(database))
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    nudges = []
    monkeypatch.setattr(db_helpers, 'trigger_auto_retrain', lambda *args, **kwargs: nudges.append(args[2]))
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    paths = [str(tmp_path / ('hidden' if name == 'reject.cr2' else 'visible') / name)
             for name in ('keep.jpg', 'keep.cr2', 'reject.jpg', 'reject.cr2', 'other.jpg')]
    conn.executemany('INSERT INTO photos(path,category,is_kept,is_rejected,star_rating,is_favorite) VALUES (?, ?,0,0,0,0)',
                     [(path, f'category-{index}') for index, path in enumerate(paths)])
    keys = []
    for members, primary in ((paths[:2], paths[1]), (paths[2:4], paths[2])):
        key = logical_assets.create(conn, members, primary, visibility_sql='1=1')
        logical_review.seed(conn, key, members[0], 1, visibility_sql='1=1')
        keys.append(key)
    conn.commit()
    yield conn, paths, keys, nudges
    conn.close()


def test_aliases_record_one_pair_using_the_chosen_primaries(library):
    conn, paths, _, nudges = library
    count = db_helpers.record_culling_decision(conn, paths[:2], paths[2:4], set())
    assert count == 1
    row = conn.execute('SELECT photo_a_path,photo_b_path,winner,category,source FROM comparisons').fetchone()
    a, b = sorted((paths[1], paths[2]))
    assert tuple(row) == (a, b, 'a' if a == paths[1] else 'b', 'category-1', 'culling')
    assert nudges == [1]


@pytest.mark.parametrize('conflict', ['opposite_alias', 'sequence_alias'])
def test_ambiguous_or_sequence_identity_does_not_teach_preferences(library, conflict):
    conn, paths, _, _ = library
    rejects = [paths[2]] + ([paths[1]] if conflict == 'opposite_alias' else [])
    sequence = {paths[1]} if conflict == 'sequence_alias' else set()
    count = db_helpers.record_culling_decision(conn, [paths[0], paths[4]], rejects, sequence)
    assert count == 1
    row = conn.execute('SELECT photo_a_path,photo_b_path,winner FROM comparisons').fetchone()
    assert set(row[:2]) == {paths[2], paths[4]}
    assert row[0 if row[2] == 'a' else 1] == paths[4]


@pytest.mark.parametrize('kind', ['bracket', 'panorama', 'hdr_panorama'])
@pytest.mark.parametrize('protected_primary', [False, True])
def test_sequence_metadata_on_an_unselected_representation_prevents_training(library, kind, protected_primary):
    conn, paths, _, _ = library
    protected = paths[1] if protected_primary else paths[0]
    selected = paths[0] if protected_primary else paths[1]
    conn.execute('UPDATE photos SET sequence_kind=? WHERE path=?', (kind, protected))
    conn.commit()
    assert db_helpers.record_culling_decision(conn, [selected, paths[4]], [paths[2]], set()) == 1
    row = conn.execute('SELECT photo_a_path,photo_b_path FROM comparisons').fetchone()
    assert set(row) == {paths[2], paths[4]}


def test_missing_primary_keeps_the_decision_without_guessing_training_features(library):
    conn, paths, keys, _ = library
    conn.execute('UPDATE logical_assets SET primary_path=NULL,revision=revision+1 WHERE id=?', (keys[0],))
    conn.commit()
    assert db_helpers.record_culling_decision(conn, [paths[0]], [paths[2]], set()) == 0
    assert conn.execute('SELECT COUNT(*) FROM comparisons').fetchone()[0] == 0
    assert conn.execute("SELECT value FROM logical_review_fields WHERE asset_id=? AND field='decision'", (keys[0],)).fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM photos WHERE is_kept=1').fetchone()[0] == 0


@pytest.mark.parametrize('prior_source', ['vote', 'culling'])
def test_existing_alias_comparison_is_preserved_and_not_duplicated(library, prior_source):
    conn, paths, _, _ = library
    a, b = sorted((paths[0], paths[3]))
    conn.execute('INSERT INTO comparisons(photo_a_path,photo_b_path,winner,source) VALUES (?,?,?,?)',
                 (a, b, 'b' if a == paths[0] else 'a', prior_source))
    conn.commit()
    before = [tuple(row) for row in conn.execute('SELECT * FROM comparisons')]
    assert db_helpers.record_culling_decision(conn, [paths[1]], [paths[2]], set()) == 0
    assert [tuple(row) for row in conn.execute('SELECT * FROM comparisons')] == before


def test_a_primary_change_does_not_duplicate_existing_logical_pair(library):
    conn, paths, keys, _ = library
    assert db_helpers.record_culling_decision(conn, [paths[0]], [paths[3]], set()) == 1
    before = [tuple(row) for row in conn.execute('SELECT * FROM comparisons')]
    conn.execute('UPDATE logical_assets SET primary_path=?,revision=revision+1 WHERE id=?', (paths[0], keys[0]))
    conn.commit()
    assert db_helpers.record_culling_decision(conn, [paths[1]], [paths[3]], set()) == 0
    assert [tuple(row) for row in conn.execute('SELECT * FROM comparisons')] == before


def test_other_users_alias_vote_does_not_suppress_current_users_pair(library, monkeypatch):
    conn, paths, _, _ = library
    root = str(Path(paths[0]).parent.parent)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'alice': {'role': 'user', 'directories': [root]}, 'bob': {'role': 'user', 'directories': [root]},
    })
    a, b = sorted((paths[0], paths[3]))
    conn.execute("INSERT INTO comparisons(photo_a_path,photo_b_path,winner,source,user_id) VALUES (?,?,'tie','vote','bob')", (a, b))
    conn.commit()
    before = tuple(conn.execute("SELECT * FROM comparisons WHERE user_id='bob'").fetchone())
    assert db_helpers.record_culling_decision(conn, [paths[0]], [paths[3]], set(), user_id='alice') == 1
    assert tuple(conn.execute("SELECT * FROM comparisons WHERE user_id='bob'").fetchone()) == before
    assert conn.execute("SELECT COUNT(*) FROM comparisons WHERE user_id='alice' AND source='culling'").fetchone()[0] == 1


def test_hidden_training_member_refuses_before_keeper_labels_change(library, monkeypatch):
    conn, paths, _, _ = library
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'alice': {'role': 'user', 'directories': [str(Path(paths[0]).parent)]},
        'bob': {'role': 'admin', 'directories': [str(Path(paths[0]).parent.parent)]},
    })
    predicate, params = db_helpers.get_visibility_clause('alice')
    assert {row[0] for row in conn.execute(f'SELECT path FROM photos WHERE {predicate}', params)} == set(paths) - {paths[3]}
    with pytest.raises(HTTPException) as error:
        db_helpers.record_culling_decision(conn, [paths[4]], [paths[2]], set(), user_id='alice')
    assert error.value.status_code == 404
    assert paths[3] not in str(error.value.detail)
    assert conn.execute('SELECT COUNT(*) FROM user_preferences').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM comparisons').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM organization_history').fetchone()[0] == 0


def test_invisible_independent_reject_cannot_create_a_training_pair(library, monkeypatch):
    conn, paths, _, _ = library
    hidden = str(Path(paths[3]).parent / 'independent.jpg')
    conn.execute('INSERT INTO photos(path,is_kept,is_rejected) VALUES (?,0,0)', (hidden,))
    conn.commit()
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'alice': {'role': 'user', 'directories': [str(Path(paths[0]).parent)]},
        'bob': {'role': 'admin', 'directories': [str(Path(paths[0]).parent.parent)]},
    })
    assert db_helpers.record_culling_decision(conn, [paths[4]], [hidden], set(), user_id='alice') == 0
    assert conn.execute('SELECT is_kept FROM user_preferences WHERE user_id=? AND photo_path=?', ('alice', paths[4])).fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM user_preferences WHERE photo_path=?', (hidden,)).fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM comparisons').fetchone()[0] == 0
