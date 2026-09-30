"""Tests for the headless ``facet.py --auto-cull`` and the core it shares with
``POST /api/culling/auto``.

Unit tests build their databases with ``db.schema.init_database`` (never a
hand-rolled ``CREATE TABLE photos``); the CLI cases shell out the way
``tests/test_cli.py`` does and assert message text as well as exit codes.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import api.config
from api.db_helpers import build_path_scope, scope_sql
from api.routers.burst_culling import (
    list_keeper_paths, list_rejected_paths, reject_standalone_below, run_auto_cull,
)
from api.routers.export import _copy_files_into
from api.similarity_groups import compute_similarity_groups
from db.schema import init_database

REPO_ROOT = Path(__file__).resolve().parents[1]
FACET = str(REPO_ROOT / 'facet.py')
_SIX_TABLES = ('photos', 'user_preferences', 'comparisons', 'albums', 'album_photos', 'stats_cache')


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _new_db(tmp_path, name='lib.db'):
    db = str(tmp_path / name)
    init_database(db)
    return db


def _connect(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def _add(conn, path, **cols):
    """Insert one photo; every default is overridable, ``None`` writes a real NULL."""
    row = {
        'path': str(path), 'filename': os.path.basename(str(path)),
        'date_taken': '2024:06:15 10:00:00', 'aggregate': 5.0, 'aesthetic': 5.0,
        'tech_sharpness': 5.0, 'is_blink': 0, 'is_burst_lead': 0,
    }
    row.update(cols)
    names = ', '.join(row)
    conn.execute(f"INSERT INTO photos ({names}) VALUES ({', '.join('?' * len(row))})",
                 list(row.values()))
    conn.commit()


def _emb(vec):
    return np.asarray(vec, dtype=np.float32).tobytes()


def _onehot(i, dim=16, noise=0.0):
    v = np.zeros(dim, dtype=np.float32)
    v[i] = 1.0
    v[(i + 1) % dim] = noise
    return _emb(v)


def _cull_kwargs(**over):
    kw = dict(group_by='all', strictness=100, min_keep=1)
    kw.update(over)
    return kw


def _state(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT path, is_rejected, burst_reviewed, is_burst_lead, similarity_reviewed "
        "FROM photos ORDER BY path")]


def _checksum(db):
    conn = sqlite3.connect(db)
    digest = hashlib.md5()
    for table in _SIX_TABLES:
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"):
            digest.update(repr((table, row)).encode())
    conn.close()
    return digest.hexdigest()


@pytest.fixture()
def fixed_scene_gap(monkeypatch):
    """A 20-minute scene gap that does not widen with the median delta."""
    from api.routers import scenes
    original = scenes._scene_config
    monkeypatch.setattr(scenes, '_scene_config', lambda: {**original(), 'adaptive': False})


@pytest.fixture(autouse=True)
def _no_retrain(monkeypatch):
    monkeypatch.setattr('api.routers.burst_culling.trigger_auto_retrain', lambda *a, **k: None)


def _seed_burst(conn, folder, gid=1, names=('a', 'b', 'c'), scores=(9.0, 8.0, 3.0)):
    for i, (name, score) in enumerate(zip(names, scores)):
        _add(conn, folder / f'{name}.jpg', aggregate=score, aesthetic=score, tech_sharpness=score,
             burst_group_id=gid, date_taken=f'2024:06:15 10:00:0{i}')


# ---------------------------------------------------------------------------
# Step 2: PathScope
# ---------------------------------------------------------------------------

class TestPathScope:
    @pytest.fixture()
    def dirs(self, tmp_path):
        for name in ('shoot', 'shoot2', 'sh_ot', 'shxot', '100%', '1000', 'Shoot'):
            (tmp_path / name).mkdir()
        return tmp_path

    def test_a_directory_prefix_stops_at_the_separator(self, dirs):
        scope = build_path_scope([str(dirs / 'shoot')])
        assert scope.matches(str(dirs / 'shoot' / 'a.jpg'))
        assert not scope.matches(str(dirs / 'shoot2' / 'a.jpg'))

    def test_wildcards_and_case_are_literal(self, dirs):
        for scoped, other in (('sh_ot', 'shxot'), ('100%', '1000'), ('shoot', 'Shoot')):
            scope = build_path_scope([str(dirs / scoped)])
            assert scope.matches(str(dirs / scoped / 'a.jpg'))
            assert not scope.matches(str(dirs / other / 'a.jpg'))

    def test_sql_agrees_with_matches(self, dirs):
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE TABLE t (path TEXT)")
        candidates = [str(dirs / d / 'a.jpg')
                      for d in ('shoot', 'shoot2', 'sh_ot', 'shxot', '100%', '1000', 'Shoot')]
        conn.executemany("INSERT INTO t VALUES (?)", [(c,) for c in candidates])
        for scoped in ('shoot', 'sh_ot', '100%', 'Shoot'):
            scope = build_path_scope([str(dirs / scoped)])
            fragment, params = scope.sql('path')
            got = {r[0] for r in conn.execute(f"SELECT path FROM t WHERE {fragment}", params)}
            assert got == {c for c in candidates if scope.matches(c)}
            assert len(got) == 1

    def test_a_file_is_an_exact_entry(self, dirs):
        target = dirs / 'shoot' / 'a.jpg'
        target.write_bytes(b'x')
        scope = build_path_scope([str(target)])
        assert scope.matches(str(target))
        assert not scope.matches(str(target) + '.xmp')

    def test_a_denormalised_path_equals_the_clean_one(self, dirs):
        messy = f"{dirs}/shoot//./"
        assert build_path_scope([messy]).prefixes == build_path_scope([str(dirs / 'shoot')]).prefixes

    def test_a_missing_entry_raises(self, dirs):
        with pytest.raises(ValueError):
            build_path_scope([str(dirs / 'nope')])

    def test_none_scope_is_a_no_op(self):
        assert build_path_scope([]) is None
        assert build_path_scope(None) is None
        assert scope_sql(None) == ('1=1', [])


# ---------------------------------------------------------------------------
# Step 1: the dry run writes nothing
# ---------------------------------------------------------------------------

class TestDryRunIsReadOnly:
    def _seed(self, conn, folder):
        _add(conn, folder / 'p1.jpg', clip_embedding=_onehot(3), aggregate=8.0)
        _add(conn, folder / 'p2.jpg', clip_embedding=_onehot(3, noise=0.01), aggregate=6.0)

    @pytest.mark.parametrize('group_by', ['all', 'scene'])
    def test_cache_free_dry_run_leaves_the_database_untouched(self, tmp_path, group_by):
        db = _new_db(tmp_path)
        conn = _connect(db)
        self._seed(conn, tmp_path)
        cache = "SELECT count(*), coalesce(sum(length(value)), 0) FROM stats_cache"
        before = (tuple(conn.execute(cache).fetchone()), conn.total_changes, _checksum(db))
        result = run_auto_cull(conn, db, '_anonymous', **_cull_kwargs(group_by=group_by),
                               dry_run=True, use_cache=False)
        assert result.processed == 1 and result.rejected == 1
        after = (tuple(conn.execute(cache).fetchone()), conn.total_changes, _checksum(db))
        assert after == before

    def test_the_cached_path_does_write_so_the_check_is_not_vacuous(self, tmp_path):
        db = _new_db(tmp_path)
        conn = _connect(db)
        self._seed(conn, tmp_path)
        run_auto_cull(conn, db, '_anonymous', **_cull_kwargs(group_by='all'),
                      dry_run=True, use_cache=True)
        run_auto_cull(conn, db, '_anonymous', **_cull_kwargs(group_by='scene'),
                      dry_run=True, use_cache=True)
        assert conn.execute("SELECT count(*) FROM stats_cache").fetchone()[0] >= 2

    def test_a_scoped_call_is_cache_free_even_when_asked_to_cache(self, tmp_path):
        db = _new_db(tmp_path)
        conn = _connect(db)
        self._seed(conn, tmp_path)
        run_auto_cull(conn, db, '_anonymous', **_cull_kwargs(group_by='all'), dry_run=True,
                      use_cache=True, path_scope=build_path_scope([str(tmp_path)]))
        assert conn.execute("SELECT count(*) FROM stats_cache").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Step 2: scoping keeps writes inside the scope
# ---------------------------------------------------------------------------

class TestScopedCull:
    def test_a_burst_crossing_the_scope_edge_is_skipped_whole(self, tmp_path):
        inside, outside = tmp_path / 'in', tmp_path / 'out'
        inside.mkdir()
        outside.mkdir()
        db = _new_db(tmp_path)
        conn = _connect(db)
        _add(conn, inside / 'a.jpg', aggregate=9, aesthetic=9, tech_sharpness=9, burst_group_id=1)
        _add(conn, inside / 'b.jpg', aggregate=3, aesthetic=3, tech_sharpness=3, burst_group_id=1)
        _add(conn, outside / 'c.jpg', aggregate=6, aesthetic=6, tech_sharpness=6, burst_group_id=1)
        before = _state(conn)
        result = run_auto_cull(conn, db, '_anonymous', **_cull_kwargs(), dry_run=False,
                               path_scope=build_path_scope([str(inside)]))
        assert result.spanning_skipped == 1 and result.processed == 0
        assert _state(conn) == before

    def test_a_burst_wholly_inside_is_culled_and_one_outside_is_not(self, tmp_path):
        inside, outside = tmp_path / 'in', tmp_path / 'out'
        inside.mkdir()
        outside.mkdir()
        db = _new_db(tmp_path)
        conn = _connect(db)
        _seed_burst(conn, inside, gid=1)
        _seed_burst(conn, outside, gid=2)
        result = run_auto_cull(conn, db, '_anonymous', **_cull_kwargs(), dry_run=False,
                               path_scope=build_path_scope([str(inside)]))
        assert result.processed == 1 and result.spanning_skipped == 0
        assert sorted(os.path.basename(p) for p in result.reject_paths) == ['b.jpg', 'c.jpg']
        rejected = {r['path'] for r in conn.execute("SELECT path FROM photos WHERE is_rejected = 1")}
        assert rejected == set(result.reject_paths)
        untouched = conn.execute(
            "SELECT count(*) FROM photos WHERE path LIKE ? AND (is_rejected = 1 OR burst_reviewed = 1)",
            (str(outside) + '%',)).fetchone()[0]
        assert untouched == 0

    def test_scoped_similar_pair_is_found_behind_a_larger_newer_out_of_scope_set(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr('api.similarity_groups._get_similarity_config', lambda: {
            'default_threshold': 0.85, 'min_group_size': 2, 'max_photos': 3, 'max_group_size': 50})
        inside, outside = tmp_path / 'in', tmp_path / 'out'
        inside.mkdir()
        outside.mkdir()
        db = _new_db(tmp_path)
        conn = _connect(db)
        for i in range(6):
            _add(conn, outside / f'o{i}.jpg', clip_embedding=_onehot(i), date_taken='2025:01:01 10:00:00')
        _add(conn, inside / 'p1.jpg', clip_embedding=_onehot(10), date_taken='2020:01:01 10:00:00')
        _add(conn, inside / 'p2.jpg', clip_embedding=_onehot(10, noise=0.01),
             date_taken='2020:01:01 10:00:01')
        scope = build_path_scope([str(inside)])
        # The cap bites without a scope: the newest three are all out-of-scope.
        assert compute_similarity_groups(conn, use_cache=False) == []
        found = compute_similarity_groups(conn, use_cache=False, path_scope=scope)
        assert [sorted(os.path.basename(p) for p in g['paths']) for g in found] == [['p1.jpg', 'p2.jpg']]

    def test_scoped_scene_is_found_behind_a_larger_older_out_of_scope_set(
            self, tmp_path, monkeypatch, fixed_scene_gap):
        from api.routers import scenes
        original = scenes._scene_config
        monkeypatch.setattr(scenes, '_scene_config', lambda: {**original(), 'max_photos': 3})
        inside, outside = tmp_path / 'in', tmp_path / 'out'
        inside.mkdir()
        outside.mkdir()
        db = _new_db(tmp_path)
        conn = _connect(db)
        for i in range(6):
            _add(conn, outside / f'o{i}.jpg', date_taken=f'2019:01:01 {i * 3:02d}:00:00')
        _add(conn, inside / 's1.jpg', date_taken='2024:06:15 10:00:00')
        _add(conn, inside / 's2.jpg', date_taken='2024:06:15 10:02:00')
        assert scenes.compute_scenes(conn, use_cache=False) == []
        found = scenes.compute_scenes(conn, use_cache=False, path_scope=build_path_scope([str(inside)]))
        assert len(found) == 1 and found[0]['count'] == 2


# ---------------------------------------------------------------------------
# Step 3: the standalone threshold pass
# ---------------------------------------------------------------------------

class TestRejectStandaloneBelow:
    def _seed(self, conn, folder):
        low = dict(aggregate=3.0)
        _add(conn, folder / 'low_single.jpg', **low)
        _add(conn, folder / 'low_solo_group.jpg', burst_group_id=7, **low)
        _add(conn, folder / 'pair_a.jpg', burst_group_id=8, **low)
        _add(conn, folder / 'pair_b.jpg', burst_group_id=8, is_rejected=1, **low)
        _add(conn, folder / 'bracket.jpg', sequence_kind='bracket', sequence_group_id=1, **low)
        _add(conn, folder / 'pano.jpg', sequence_kind='panorama', sequence_group_id=1, **low)
        _add(conn, folder / 'unknown.jpg', aggregate=None)
        _add(conn, folder / 'exact.jpg', aggregate=5.0)
        _add(conn, folder / 'already.jpg', is_rejected=1, **low)
        _add(conn, folder / 'fav.jpg', is_favorite=1, **low)
        _add(conn, folder / 'starred.jpg', star_rating=3, **low)
        _add(conn, folder / 'excluded.jpg', **low)
        _add(conn, folder / 'reviewed.jpg', similarity_reviewed=1, **low)
        _add(conn, folder / 'null_prefs.jpg', is_favorite=None, star_rating=None, is_rejected=None, **low)

    def test_only_true_standalone_photos_below_the_threshold_are_rejected(self, tmp_path):
        db = _new_db(tmp_path)
        conn = _connect(db)
        self._seed(conn, tmp_path)
        rejected = reject_standalone_below(
            conn, '_anonymous', None, 5.0, {str(tmp_path / 'excluded.jpg')}, dry_run=False)
        assert sorted(os.path.basename(p) for p in rejected) == [
            'low_single.jpg', 'low_solo_group.jpg', 'null_prefs.jpg']
        flagged = {os.path.basename(r['path']) for r in conn.execute(
            "SELECT path FROM photos WHERE is_rejected = 1")}
        assert flagged == {'low_single.jpg', 'low_solo_group.jpg', 'null_prefs.jpg',
                           'pair_b.jpg', 'already.jpg'}

    def test_a_dry_run_selects_without_writing(self, tmp_path):
        db = _new_db(tmp_path)
        conn = _connect(db)
        self._seed(conn, tmp_path)
        before_changes = conn.total_changes
        before = _checksum(db)
        rejected = reject_standalone_below(conn, '_anonymous', None, 5.0, set(), dry_run=True)
        assert len(rejected) == 4
        assert conn.total_changes == before_changes and _checksum(db) == before

    def test_out_of_scope_photos_are_untouched_and_scope_digits_do_not_confuse_binds(self, tmp_path):
        inside, outside = tmp_path / '5', tmp_path / 'out'
        inside.mkdir()
        outside.mkdir()
        db = _new_db(tmp_path)
        conn = _connect(db)
        _add(conn, inside / 'a.jpg', aggregate=3.0)
        _add(conn, inside / 'good.jpg', aggregate=9.0)
        _add(conn, outside / 'b.jpg', aggregate=3.0)
        rejected = reject_standalone_below(
            conn, '_anonymous', build_path_scope([str(inside)]), 5, set(), dry_run=False)
        assert rejected == [str(inside / 'a.jpg')]
        assert conn.execute("SELECT is_rejected FROM photos WHERE path = ?",
                            (str(outside / 'b.jpg'),)).fetchone()[0] == 0

    def test_multi_user_writes_user_preferences_not_the_global_column(self, tmp_path, monkeypatch):
        monkeypatch.setitem(api.config._FULL_CONFIG, 'users', {
            'alice': {'role': 'user', 'directories': [str(tmp_path)]}})
        db = _new_db(tmp_path)
        conn = _connect(db)
        _add(conn, tmp_path / 'low.jpg', aggregate=3.0)
        _add(conn, tmp_path / 'loved.jpg', aggregate=3.0)
        conn.execute("INSERT INTO user_preferences (user_id, photo_path, is_favorite) VALUES (?, ?, 1)",
                     ('alice', str(tmp_path / 'loved.jpg')))
        conn.commit()
        rejected = reject_standalone_below(conn, 'alice', None, 5.0, set(), dry_run=False)
        assert rejected == [str(tmp_path / 'low.jpg')]
        assert conn.execute("SELECT is_rejected FROM user_preferences WHERE user_id = 'alice' "
                            "AND photo_path = ?", (rejected[0],)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM photos WHERE is_rejected = 1").fetchone()[0] == 0

    def test_sharing_a_scene_window_does_not_shield_a_low_score_photo(self, tmp_path):
        db = _new_db(tmp_path)
        conn = _connect(db)
        _add(conn, tmp_path / 'low.jpg', aggregate=1.0, date_taken='2024:06:15 10:00:00')
        _add(conn, tmp_path / 'good.jpg', aggregate=9.0, date_taken='2024:06:15 10:02:00')
        result = run_auto_cull(conn, db, '_anonymous', **_cull_kwargs(group_by='all'),
                               dry_run=True, membership_groups=True)
        standalone = reject_standalone_below(
            conn, '_anonymous', None, 5.0, result.collected | result.decided, dry_run=True)
        assert standalone == [str(tmp_path / 'low.jpg')]

    def test_scene_members_are_shielded_when_scenes_are_being_culled(self, tmp_path):
        db = _new_db(tmp_path)
        conn = _connect(db)
        _add(conn, tmp_path / 'low.jpg', aggregate=1.0, date_taken='2024:06:15 10:00:00')
        _add(conn, tmp_path / 'good.jpg', aggregate=9.0, date_taken='2024:06:15 10:02:00')
        result = run_auto_cull(conn, db, '_anonymous', **_cull_kwargs(group_by='scene'),
                               dry_run=True, membership_groups=True)
        standalone = reject_standalone_below(
            conn, '_anonymous', None, 5.0, result.collected | result.decided, dry_run=True)
        assert standalone == []

    def test_a_low_scene_keeper_is_not_score_rejected_on_the_second_run(self, tmp_path, fixed_scene_gap):
        db = _new_db(tmp_path)
        conn = _connect(db)
        _add(conn, tmp_path / 'low1.jpg', aggregate=3.0, aesthetic=3.0, tech_sharpness=3.0,
             date_taken='2024:06:15 10:00:00')
        _add(conn, tmp_path / 'low2.jpg', aggregate=2.0, aesthetic=2.0, tech_sharpness=2.0,
             date_taken='2024:06:15 10:01:00')
        for run in (1, 2):
            result = run_auto_cull(conn, db, '_anonymous', **_cull_kwargs(group_by='scene'),
                                   dry_run=False, membership_groups=True)
            standalone = reject_standalone_below(
                conn, '_anonymous', None, 5.0, result.collected | result.decided, dry_run=False)
            assert standalone == [], f'run {run}'
        assert conn.execute("SELECT count(*) FROM photos WHERE is_rejected = 1").fetchone()[0] == 1

    def test_a_second_full_run_rejects_nothing_new(self, tmp_path, fixed_scene_gap):
        db = _new_db(tmp_path)
        conn = _connect(db)
        # Both keepers score under the threshold, so only their protection keeps run 2 quiet.
        _seed_burst(conn, tmp_path, gid=1, scores=(4.0, 3.0, 2.0))
        _add(conn, tmp_path / 'p1.jpg', clip_embedding=_onehot(3), aggregate=4.0)
        _add(conn, tmp_path / 'p2.jpg', clip_embedding=_onehot(3, noise=0.01), aggregate=2.0,
             date_taken='2024:06:15 15:00:00')
        _add(conn, tmp_path / 'lonely.jpg', aggregate=1.0, date_taken='2023:01:01 08:00:00')

        def run():
            result = run_auto_cull(conn, db, '_anonymous', **_cull_kwargs(), dry_run=False,
                                   membership_groups=True)
            standalone = reject_standalone_below(
                conn, '_anonymous', None, 5.0, result.collected | result.decided, dry_run=False)
            return result, standalone

        first, first_standalone = run()
        assert first.rejected == 3 and first_standalone == [str(tmp_path / 'lonely.jpg')]
        second, second_standalone = run()
        assert second.reject_paths == [] and second_standalone == []


class TestListings:
    def test_keepers_and_rejects_partition_the_scope(self, tmp_path):
        inside = tmp_path / 'in'
        inside.mkdir()
        db = _new_db(tmp_path)
        conn = _connect(db)
        _add(conn, inside / 'keep.jpg')
        _add(conn, inside / 'gone.jpg', is_rejected=1)
        _add(conn, inside / 'pending.jpg')
        _add(conn, tmp_path / 'elsewhere.jpg')
        scope = build_path_scope([str(inside)])
        assert list_keeper_paths(conn, '_anonymous', scope, exclude_paths={str(inside / 'pending.jpg')}) \
            == [str(inside / 'keep.jpg')]
        assert list_rejected_paths(conn, '_anonymous', scope) == {str(inside / 'gone.jpg')}


# ---------------------------------------------------------------------------
# Step 4: the copy helper
# ---------------------------------------------------------------------------

class TestCopyFilesInto:
    def test_same_named_files_both_arrive_and_a_rerun_copies_nothing(self, tmp_path):
        one, two, target = tmp_path / 'one', tmp_path / 'two', tmp_path / 'out'
        one.mkdir()
        two.mkdir()
        (one / 'x.jpg').write_bytes(b'aaaa')
        (two / 'x.jpg').write_bytes(b'bbbbbb')
        files = [str(one / 'x.jpg'), str(two / 'x.jpg')]
        assert _copy_files_into(files, str(target), skip_identical=True) == (2, 0, 0)
        assert sorted(os.listdir(target)) == ['x.jpg', 'x_1.jpg']
        assert _copy_files_into(files, str(target), skip_identical=True) == (0, 0, 2)
        assert sorted(os.listdir(target)) == ['x.jpg', 'x_1.jpg']

    def test_without_skip_identical_a_rerun_adds_suffixed_copies(self, tmp_path):
        (tmp_path / 'x.jpg').write_bytes(b'aaaa')
        files = [str(tmp_path / 'x.jpg')]
        target = str(tmp_path / 'out')
        _copy_files_into(files, target)
        assert _copy_files_into(files, target) == (1, 0, 0)
        assert sorted(os.listdir(target)) == ['x.jpg', 'x_1.jpg']


# ---------------------------------------------------------------------------
# Step 5: visibility on a single-user install
# ---------------------------------------------------------------------------

class TestSingleUserVisibility:
    def test_a_viewer_password_hides_everything_from_none_but_not_from_the_sentinel(
            self, tmp_path, monkeypatch):
        monkeypatch.setitem(api.config.VIEWER_CONFIG, 'password', 'secret')
        monkeypatch.setattr(api.config, 'config_load_failed', lambda: False, raising=False)
        db = _new_db(tmp_path)
        conn = _connect(db)
        _seed_burst(conn, tmp_path)
        blind = run_auto_cull(conn, db, None, **_cull_kwargs(), dry_run=True)
        assert blind.processed == 0
        seen = run_auto_cull(conn, db, '_legacy', **_cull_kwargs(), dry_run=True)
        assert seen.processed == 1

    def test_the_sentinel_follows_the_viewer_password(self, monkeypatch):
        from api.auth import VIEWER_PASSWORD_KEY, _is_open_install
        monkeypatch.setitem(api.config.VIEWER_CONFIG, 'password', '')
        assert _is_open_install(VIEWER_PASSWORD_KEY) is True
        monkeypatch.setitem(api.config.VIEWER_CONFIG, 'password', 'secret')
        assert _is_open_install(VIEWER_PASSWORD_KEY) is False


# ---------------------------------------------------------------------------
# Step 5: the scan-then-cull hook
# ---------------------------------------------------------------------------

class TestScanThenCull:
    def _run_main(self, monkeypatch, tmp_path, scan):
        import facet
        calls = []

        class _Lock:
            def release(self):
                calls.append('release')

        monkeypatch.setattr(facet, '_run_scan', scan)
        monkeypatch.setattr(facet, '_acquire_library_lock', lambda args, kind: _Lock())
        monkeypatch.setattr(facet, '_run_auto_cull_cli',
                            lambda args, scope, lock_held: calls.append(('cull', scope, lock_held)))
        monkeypatch.setattr(sys, 'argv', ['facet.py', str(tmp_path), '--auto-cull',
                                          '--db', str(tmp_path / 'x.db')])
        return facet, calls

    def test_the_cull_runs_after_a_completed_scan_under_the_scan_lock(self, monkeypatch, tmp_path):
        facet, calls = self._run_main(monkeypatch, tmp_path, lambda args, resumed: True)
        facet.main()
        assert calls == [('cull', [str(tmp_path)], True), 'release']

    def test_an_interrupted_scan_does_not_cull_and_says_so(self, monkeypatch, tmp_path, caplog):
        facet, calls = self._run_main(monkeypatch, tmp_path, lambda args, resumed: False)
        with caplog.at_level('INFO', logger='facet'):
            facet.main()
        assert calls == ['release']
        assert sum('cull skipped' in r.getMessage() for r in caplog.records) == 1

    def test_a_failed_scan_does_not_cull_and_still_releases_the_lock(self, monkeypatch, tmp_path):
        def boom(args, resumed):
            raise RuntimeError('scan blew up')
        facet, calls = self._run_main(monkeypatch, tmp_path, boom)
        with pytest.raises(RuntimeError):
            facet.main()
        assert calls == ['release']


# ---------------------------------------------------------------------------
# Step 5: the CLI end to end (subprocess)
# ---------------------------------------------------------------------------

def _env(config_path):
    env = {k: v for k, v in os.environ.items()
           if not any(k.startswith(p) or p in k for p in (
               'SLACK_', 'GITHUB_', 'GH_', 'AWS_', 'OPENAI_', 'ANTHROPIC_', 'GOOGLE_', 'AZURE_',
               'HF_', 'HUGGINGFACE_', 'SENTRY_', 'API_KEY', 'TOKEN', 'PASSWORD', 'SECRET',
               'CREDENTIAL', 'FACET_'))}
    env.pop('DB_PATH', None)
    env['FACET_CONFIG'] = str(config_path)
    return env


def _facet(config_path, *argv):
    return subprocess.run(
        [sys.executable, FACET, *argv], capture_output=True, text=True, timeout=180,
        env=_env(config_path), cwd=str(REPO_ROOT))


def _write_config(tmp_path, body=None, name='cfg.json'):
    path = tmp_path / name
    path.write_text(json.dumps(body or {}))
    return path


class _Library:
    """A tiny on-disk library: a burst, a kept single with companions, a rejected RAW row."""

    def __init__(self, tmp_path):
        self.root = tmp_path / 'library'
        self.root.mkdir()
        self.db = _new_db(tmp_path)
        self.config = _write_config(tmp_path)
        for name, size in (('b1.jpg', 11), ('b2.jpg', 12), ('b3.jpg', 13), ('a.jpg', 14),
                           ('b1.cr2', 15), ('b2.cr2', 16), ('a.cr2', 17), ('a.xmp', 18)):
            (self.root / name).write_bytes(b'x' * size)
        # Real files are resolved through realpath; store the resolved form, like the scanner.
        self.real = self.root.resolve()
        conn = _connect(self.db)
        _seed_burst(conn, self.real, gid=1, names=('b1', 'b2', 'b3'))
        _add(conn, self.real / 'a.jpg', aggregate=7.0, date_taken='2023:01:01 08:00:00')
        _add(conn, self.real / 'a.cr2', aggregate=7.0, is_rejected=1, date_taken='2023:01:01 08:00:00')
        conn.close()

    def run(self, *argv, config=None):
        return _facet(config or self.config, '--db', self.db, '--config', str(config or self.config), *argv)

    def rejected(self):
        conn = sqlite3.connect(self.db)
        try:
            return sorted(os.path.basename(r[0]) for r in conn.execute(
                "SELECT path FROM photos WHERE is_rejected = 1"))
        finally:
            conn.close()


class TestCliValidation:
    @pytest.fixture()
    def cfg(self, tmp_path):
        return _write_config(tmp_path)

    @pytest.mark.parametrize('argv, message', [
        (['--apply'], '--apply requires --auto-cull'),
        (['--copy-keepers', '/tmp/x'], '--copy-keepers requires --auto-cull'),
        (['--cull-min-score', '3'], '--cull-min-score requires --auto-cull'),
        (['--auto-cull', '--dry-run'], 'cannot be combined with --auto-cull'),
        (['--auto-cull', '/x', '/y'], '--auto-cull PATH cannot be combined'),
        (['--auto-cull', '--resume'], 'cannot be combined with --resume'),
        (['--auto-cull', '--retry-failed'], 'cannot be combined with --retry-failed'),
        (['--auto-cull', '--watch', '/x'], 'cannot be combined with --watch'),
        (['--auto-cull', '--cull-strictness', '101'], '--cull-strictness must be between 0 and 100'),
        (['--auto-cull', '--cull-min-keep', '0'], '--cull-min-keep must be at least 1'),
    ])
    def test_usage_errors_exit_2_naming_the_conflict(self, cfg, argv, message):
        proc = _facet(cfg, *argv)
        assert proc.returncode == 2, proc.stderr
        assert message in proc.stderr

    def test_a_missing_database_exits_1_and_is_not_created(self, tmp_path, cfg):
        missing = tmp_path / 'nope.db'
        proc = _facet(cfg, '--db', str(missing), '--auto-cull')
        assert proc.returncode == 1
        assert 'Database not found' in proc.stderr
        assert not missing.exists()

    def test_multi_user_requires_a_known_user(self, tmp_path):
        folder = tmp_path / 'lib'
        folder.mkdir()
        cfg = _write_config(tmp_path, {'users': {'alice': {'role': 'user', 'directories': [str(folder)]}}})
        db = _new_db(tmp_path)
        proc = _facet(cfg, '--db', db, '--config', str(cfg), '--auto-cull')
        assert proc.returncode == 1 and 'requires --user' in proc.stderr
        proc = _facet(cfg, '--db', db, '--config', str(cfg), '--auto-cull', '--user', 'bob')
        assert proc.returncode == 1 and 'Unknown --user' in proc.stderr


class TestCliRuns:
    def test_a_dry_run_changes_nothing_and_creates_no_target(self, tmp_path):
        lib = _Library(tmp_path)
        target = tmp_path / 'keepers'
        before = _checksum(lib.db)
        proc = lib.run('--auto-cull', '--cull-strictness', '100', '--cull-min-score', '5',
                       '--copy-keepers', str(target))
        assert proc.returncode == 0, proc.stderr
        assert 'DRY RUN - nothing written' in proc.stdout
        assert 'would_reject_by_groups=2' in proc.stdout
        assert 'would_copy=' in proc.stdout
        assert _checksum(lib.db) == before
        assert not target.exists()

    def test_apply_rejects_the_expected_paths_and_copies_the_keepers(self, tmp_path):
        lib = _Library(tmp_path)
        target = tmp_path / 'keepers'
        proc = lib.run('--auto-cull', '--apply', '--cull-strictness', '100',
                       '--copy-keepers', str(target))
        assert proc.returncode == 0, proc.stderr
        assert 'DRY RUN' not in proc.stdout
        assert 'rejected_by_groups=2' in proc.stdout
        assert lib.rejected() == ['a.cr2', 'b2.jpg', 'b3.jpg']
        # A keeper's companion RAW that is a rejected row of its own is not copied.
        assert sorted(os.listdir(target)) == ['a.jpg', 'a.xmp', 'b1.cr2', 'b1.jpg']
        again = lib.run('--auto-cull', '--apply', '--copy-keepers', str(target))
        assert again.returncode == 0, again.stderr
        assert 'copied=0' in again.stdout and 'already_present=4' in again.stdout
        assert sorted(os.listdir(target)) == ['a.jpg', 'a.xmp', 'b1.cr2', 'b1.jpg']

    def test_a_target_inside_the_scope_is_refused_before_anything_is_written(self, tmp_path):
        lib = _Library(tmp_path)
        inside = lib.root / 'keepers'
        for extra in ([], ['--apply']):
            proc = lib.run('--auto-cull', str(lib.root), '--cull-strictness', '100',
                           '--copy-keepers', str(inside), *extra)
            assert proc.returncode == 1, proc.stderr
            assert 'overlaps the library path' in proc.stderr
        assert lib.rejected() == ['a.cr2']
        assert not inside.exists()

    def test_a_target_containing_the_library_is_refused_for_the_whole_library_scope(self, tmp_path):
        lib = _Library(tmp_path)
        proc = lib.run('--auto-cull', '--copy-keepers', str(tmp_path))
        assert proc.returncode == 1 and 'overlaps the library path' in proc.stderr

    def test_a_copy_that_resolves_no_file_exits_3_naming_the_allow_list(self, tmp_path):
        lib = _Library(tmp_path)
        other = tmp_path / 'not_the_library'
        other.mkdir()
        cfg = _write_config(tmp_path, {'viewer': {'scan_directories': [str(other)]}}, name='allow.json')
        target = tmp_path / 'keepers'
        proc = lib.run('--auto-cull', '--apply', '--cull-strictness', '100',
                       '--copy-keepers', str(target), config=cfg)
        assert proc.returncode == 3, proc.stderr
        assert 'viewer.scan_directories' in proc.stderr
        assert lib.rejected() == ['a.cr2', 'b2.jpg', 'b3.jpg']

    def test_a_single_user_install_behind_a_viewer_password_still_culls(self, tmp_path):
        lib = _Library(tmp_path)
        cfg = _write_config(tmp_path, {'viewer': {'password': 'pbkdf2:not-a-real-hash'}}, name='pw.json')
        proc = lib.run('--auto-cull', '--apply', '--cull-strictness', '100', config=cfg)
        assert proc.returncode == 0, proc.stderr
        assert 'rejected_by_groups=2' in proc.stdout
        assert lib.rejected() == ['a.cr2', 'b2.jpg', 'b3.jpg']


class TestCliRegressions:
    def test_a_stale_cache_entry_changes_neither_the_dry_run_nor_apply(self, tmp_path):
        lib = _Library(tmp_path)
        conn = _connect(lib.db)
        conn.execute("DELETE FROM photos")
        _add(conn, lib.real / 'p1.jpg', clip_embedding=_onehot(3), aggregate=8.0)
        _add(conn, lib.real / 'p3.jpg', clip_embedding=_onehot(9), aggregate=8.0)
        # A viewer visit populated the similar-group cache before p2 was scanned.
        run_auto_cull(conn, lib.db, '_anonymous', **_cull_kwargs(group_by='similar'),
                      dry_run=True, use_cache=True)
        assert conn.execute("SELECT count(*) FROM stats_cache").fetchone()[0] >= 1
        _add(conn, lib.real / 'p2.jpg', clip_embedding=_onehot(3, noise=0.01), aggregate=2.0)
        conn.close()
        dry = lib.run('--auto-cull', '--cull-group-by', 'similar', '--cull-strictness', '100')
        assert 'would_reject_by_groups=1' in dry.stdout, dry.stdout + dry.stderr
        applied = lib.run('--auto-cull', '--apply', '--cull-group-by', 'similar',
                          '--cull-strictness', '100')
        assert 'rejected_by_groups=1' in applied.stdout, applied.stdout + applied.stderr
        assert lib.rejected() == ['p2.jpg']

    @pytest.mark.parametrize('scope', [[], ['2024']])
    def test_a_target_inside_a_recorded_scan_root_is_refused(self, tmp_path, scope):
        root = tmp_path / 'lib'
        (root / '2024').mkdir(parents=True)
        db = _new_db(tmp_path)
        conn = _connect(db)
        for name, score in (('a.jpg', 7.0), ('b.jpg', 2.0)):
            (root / '2024' / name).write_bytes(b'x' * 10)
            _add(conn, (root / '2024' / name).resolve(), aggregate=score)
        conn.execute("INSERT INTO scan_runs (mode, args_json, total_files) VALUES ('scan', ?, 2)",
                     (json.dumps({'directories': [str(root)], 'force': False}),))
        conn.commit()
        conn.close()
        cfg = _write_config(tmp_path)
        argv = ['--auto-cull', *[str(root / s) for s in scope]]
        proc = _facet(cfg, '--db', db, '--config', str(cfg), *argv, '--apply',
                      '--copy-keepers', str(root / 'keepers'))
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert 'overlaps the library path' in proc.stderr
        assert not (root / 'keepers').exists()

    def test_a_file_scope_never_copies_a_rejected_companion(self, tmp_path):
        lib = _Library(tmp_path)
        target = tmp_path / 'keepers'
        proc = lib.run('--auto-cull', str(lib.real / 'a.jpg'), '--apply', '--copy-keepers', str(target))
        assert proc.returncode == 0, proc.stderr
        assert sorted(os.listdir(target)) == ['a.jpg', 'a.xmp']

    def test_a_dry_run_whose_keepers_are_all_disallowed_exits_3_with_the_hint(self, tmp_path):
        lib = _Library(tmp_path)
        other = tmp_path / 'not_the_library'
        other.mkdir()
        cfg = _write_config(tmp_path, {'viewer': {'scan_directories': [str(other)]}}, name='allow.json')
        before = _checksum(lib.db)
        proc = lib.run('--auto-cull', '--copy-keepers', str(tmp_path / 'keepers'), config=cfg)
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert 'viewer.scan_directories' in proc.stderr
        assert _checksum(lib.db) == before
