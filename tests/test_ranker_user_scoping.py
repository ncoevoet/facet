"""User-scoped comparison fetching + per-user personal ranker (roadmap 2.5).

Pins the scoping foundation for adapted-PIAA cold-start:

* ``_fetch_comparison_data(user_id=...)`` returns a user's own rows plus legacy
  ``NULL`` rows and excludes other users; ``user_id=None`` stays the global
  pooled default (every row).
* ``train_ranker(user_id=...)`` threads the scope down to per-user
  ``learned_scores`` and a per-user ``stats_cache`` snapshot key, while leaving
  the global ``photos.learned_score`` mirror untouched (per-user gallery sort is
  future work).
* the CLI resolves ``--user`` to a validated id (unknown user -> None -> error).
"""

import sqlite3

import pytest

from db import get_connection
from db.schema import init_database
from facet import _resolve_cli_user
from optimization import personal_ranker as pr
from optimization.personal_ranker import ranker_metrics_key
from optimization.weight_optimizer import WeightOptimizer
from tests.test_personal_ranker import _seed_photos


@pytest.fixture()
def scoped_db(tmp_path):
    db_path = str(tmp_path / "scoped.db")
    init_database(db_path)
    return db_path


def _insert_pair(conn, pa, pb, winner, user_id):
    conn.execute(
        "INSERT INTO comparisons (photo_a_path, photo_b_path, winner, source, user_id) "
        "VALUES (?, ?, ?, 'vote', ?)",
        (pa, pb, winner, user_id),
    )


def _add_user_comparisons(db_path, signals, paths, count, user_id, seed):
    """Distinct pairs sampled from ``paths``, winner decided by the embedding signal."""
    import numpy as np

    rng = np.random.default_rng(seed)
    conn = sqlite3.connect(db_path)
    added = 0
    while added < count:
        ia, ib = rng.choice(len(paths), size=2, replace=False)
        pa, pb = paths[ia], paths[ib]
        winner = 'a' if signals[pa] > signals[pb] else 'b'
        cur = conn.execute(
            "INSERT OR IGNORE INTO comparisons "
            "(photo_a_path, photo_b_path, winner, source, user_id) VALUES (?, ?, ?, 'vote', ?)",
            (pa, pb, winner, user_id),
        )
        added += cur.rowcount
    conn.commit()
    conn.close()


# --- fetch-layer scoping (Deliverable 1 core) ---

class TestFetchScoping:
    def _seed_disjoint(self, db_path):
        signals = _seed_photos(db_path, n=12)
        p = sorted(signals)
        conn = sqlite3.connect(db_path)
        _insert_pair(conn, p[0], p[1], 'a', 'alice')
        _insert_pair(conn, p[2], p[3], 'b', 'alice')
        _insert_pair(conn, p[4], p[5], 'a', 'bob')
        _insert_pair(conn, p[6], p[7], 'b', 'bob')
        _insert_pair(conn, p[8], p[9], 'a', 'bob')
        _insert_pair(conn, p[10], p[11], 'a', None)
        conn.commit()
        conn.close()
        return p

    def test_none_returns_every_row(self, scoped_db):
        self._seed_disjoint(scoped_db)
        opt = WeightOptimizer(scoped_db)
        with get_connection(scoped_db) as conn:
            comps, *_ = opt._fetch_comparison_data(conn)
        assert len(comps) == 6

    def test_user_returns_own_plus_legacy_null(self, scoped_db):
        p = self._seed_disjoint(scoped_db)
        opt = WeightOptimizer(scoped_db)
        with get_connection(scoped_db) as conn:
            comps, *_ = opt._fetch_comparison_data(conn, user_id='alice')
        pairs = {(c['photo_a'], c['photo_b']) for c in comps}
        assert pairs == {(p[0], p[1]), (p[2], p[3]), (p[10], p[11])}

    def test_other_users_rows_excluded(self, scoped_db):
        p = self._seed_disjoint(scoped_db)
        opt = WeightOptimizer(scoped_db)
        with get_connection(scoped_db) as conn:
            comps, *_ = opt._fetch_comparison_data(conn, user_id='alice')
        pairs = {(c['photo_a'], c['photo_b']) for c in comps}
        for bob_pair in ((p[4], p[5]), (p[6], p[7]), (p[8], p[9])):
            assert bob_pair not in pairs

    def test_unknown_user_sees_only_legacy_null(self, scoped_db):
        p = self._seed_disjoint(scoped_db)
        opt = WeightOptimizer(scoped_db)
        with get_connection(scoped_db) as conn:
            comps, *_ = opt._fetch_comparison_data(conn, user_id='carol')
        pairs = {(c['photo_a'], c['photo_b']) for c in comps}
        assert pairs == {(p[10], p[11])}


# --- train_ranker pass-through (Deliverable 1 wiring) ---

def test_train_ranker_scopes_pairs_to_user_plus_legacy(scoped_db):
    signals = _seed_photos(scoped_db, n=60, aggregate="noise")
    paths = sorted(signals)
    _add_user_comparisons(scoped_db, signals, paths[0:20], count=40, user_id='alice', seed=1)
    _add_user_comparisons(scoped_db, signals, paths[20:40], count=40, user_id='bob', seed=2)
    _add_user_comparisons(scoped_db, signals, paths[40:60], count=10, user_id=None, seed=3)

    r_alice = pr.train_ranker(scoped_db, user_id='alice', force=True)
    r_global = pr.train_ranker(scoped_db, user_id=None, force=True)

    assert r_alice['user_id'] == 'alice'
    assert r_alice['n_pairs'] == 50   # alice's 40 + 10 legacy NULL, bob excluded
    assert r_global['n_pairs'] == 90  # every row pooled


def test_train_ranker_writes_user_scope_and_leaves_global_untouched(scoped_db):
    signals = _seed_photos(scoped_db, n=40, aggregate="noise")
    paths = sorted(signals)
    _add_user_comparisons(scoped_db, signals, paths, count=80, user_id='alice', seed=7)

    result = pr.train_ranker(scoped_db, user_id='alice', force=True)
    assert result['written'] > 0

    conn = sqlite3.connect(scoped_db)
    try:
        user_rows = conn.execute(
            "SELECT COUNT(*) FROM learned_scores WHERE user_id = 'alice' AND category IS NULL"
        ).fetchone()[0]
        global_rows = conn.execute(
            "SELECT COUNT(*) FROM learned_scores WHERE user_id IS NULL"
        ).fetchone()[0]
        mirrored = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE learned_score IS NOT NULL"
        ).fetchone()[0]
        snapshot = conn.execute(
            "SELECT value FROM stats_cache WHERE key = ?",
            (ranker_metrics_key('alice', None),),
        ).fetchone()
    finally:
        conn.close()

    assert user_rows == result['written']
    assert global_rows == 0
    assert mirrored == 0            # per-user overlay of photos.learned_score is future work
    assert snapshot is not None     # per-user stats_cache snapshot key written


# --- CLI user resolution (Deliverable 1 wiring) ---

class TestCliUserResolution:
    _CONFIG = {'users': {'alice': {'role': 'user'}, 'shared_directories': []}}

    def test_known_user_resolves_to_username(self):
        assert _resolve_cli_user(self._CONFIG, 'alice') == 'alice'

    def test_unknown_user_resolves_to_none(self):
        assert _resolve_cli_user(self._CONFIG, 'bob') is None

    def test_single_user_mode_has_no_users(self):
        assert _resolve_cli_user({}, 'alice') is None
