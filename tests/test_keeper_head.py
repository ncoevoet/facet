"""Tests for the learned keeper-ranking head (optimization/keeper_head.py).

Mirrors the personal-ranker tests: a clean embedding signal that the auto-cull
heuristic (aggregate/aesthetic/sharpness/blink) cannot see lets the keeper head
beat the heuristic baseline; when the heuristic already tracks the winner the
gate blocks. Also covers within-group softmax normalization, the snapshot
round-trip, and the flag-off no-op seam.
"""

import sqlite3
from contextlib import contextmanager
from unittest import mock

import numpy as np
import pytest

from db.schema import init_database
from optimization import keeper_head as kh
from optimization import personal_ranker as pr
from optimization.weight_optimizer import WeightOptimizer
from processing.burst_score import (
    DEFAULT_BURST_WEIGHTS, burst_weights_from_config, compute_burst_score,
)


_METRIC_COLS = (
    "aesthetic, quality_score, face_quality, face_sharpness, eye_sharpness, "
    "tech_sharpness, comp_score, power_point_score, leading_lines_score, "
    "exposure_score, color_score, contrast_score, dynamic_range_stops, "
    "mean_saturation, noise_sigma, isolation_bonus"
)
_METRIC_VALS = "5, 5, 5, 50, 5, 5, 5, 5, 5, 5, 5, 5, 7, 0.5, 1, 5"


def _emb_bytes(signal, dim=16, rng=None):
    """Embedding whose component 0 carries the preference signal."""
    v = np.full(dim, 0.1, dtype=np.float32)
    v[0] = signal
    if rng is not None:
        v[1:] += rng.normal(scale=0.01, size=dim - 1).astype(np.float32)
    return v.tobytes()


def _seed_photos(db_path, n=40, seed=3, aggregate="noise"):
    """Insert n photos; component-0 of the embedding is the preference signal.

    aggregate="signal" makes aggregate (hence the heuristic) track the signal;
    aggregate="noise" makes it uninformative.
    """
    rng = np.random.default_rng(seed)
    conn = sqlite3.connect(db_path)
    signals = {}
    for i in range(n):
        s = float(rng.uniform(0.2, 2.0))
        path = f'/r/p{i:03d}.jpg'
        signals[path] = s
        agg = s * 5.0 if aggregate == "signal" else float(rng.uniform(1, 9))
        conn.execute(
            f"INSERT INTO photos (path, filename, clip_embedding, aggregate, {_METRIC_COLS}) "
            f"VALUES (?, ?, ?, ?, {_METRIC_VALS})",
            (path, f'p{i:03d}.jpg', _emb_bytes(s, rng=rng), agg),
        )
    conn.commit()
    conn.close()
    return signals


def _add_culling(db_path, signals, count=80, seed=11):
    """source='culling' pairs whose winner is decided by the embedding signal."""
    rng = np.random.default_rng(seed)
    paths = list(signals)
    conn = sqlite3.connect(db_path)
    added = 0
    while added < count:
        ia, ib = rng.choice(len(paths), size=2, replace=False)
        pa, pb = paths[ia], paths[ib]
        winner_path = pa if signals[pa] > signals[pb] else pb
        winner = 'a' if winner_path == pa else 'b'
        cur = conn.execute(
            "INSERT OR IGNORE INTO comparisons (photo_a_path, photo_b_path, winner, source) "
            "VALUES (?, ?, ?, 'culling')",
            (pa, pb, winner),
        )
        added += cur.rowcount
    conn.commit()
    conn.close()


@pytest.fixture()
def keeper_db(tmp_path):
    db_path = str(tmp_path / "keeper.db")
    init_database(db_path)
    return db_path


def _rows(db_path, paths):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ph = ','.join('?' * len(paths))
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM photos WHERE path IN ({ph})", list(paths))]
    conn.close()
    return rows


def _load_head(db_path, user_id=None, category=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    head = kh.load_keeper_head(conn, user_id, category)
    conn.close()
    return head


def _get_db_patch(db_path):
    """Patch burst_culling.get_db to open a fresh Row connection per call.

    The keeper_hints endpoint is a sync ``def`` FastAPI runs in a worker thread,
    so the connection must be created inside that thread, not the test thread.
    """
    @contextmanager
    def _open():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    return mock.patch("api.routers.burst_culling.get_db", _open)


def _set_burst_group(db_path, paths, gid=1):
    conn = sqlite3.connect(db_path)
    ph = ','.join('?' * len(paths))
    conn.execute(
        f"UPDATE photos SET burst_group_id = {gid} WHERE path IN ({ph})", list(paths))
    conn.commit()
    conn.close()


def _reject_photo(db_path, path):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE photos SET is_rejected = 1 WHERE path = ?", (path,))
    conn.commit()
    conn.close()


@pytest.fixture()
def trained_keeper_db(keeper_db):
    """A seeded DB with a forced (persisted) keeper head and its signal ordering."""
    signals = _seed_photos(keeper_db, n=40, aggregate="noise")
    _add_culling(keeper_db, signals, count=80)
    kh.train_keeper_head(keeper_db, min_improvement_pp=2.0, force=True)
    ordered = sorted(signals, key=lambda p: signals[p])
    return keeper_db, signals, ordered


# --- pure-function tests ---

def test_burst_score_extraction_values():
    photo = {'aggregate': 8, 'aesthetic': 6, 'tech_sharpness': 7, 'is_blink': 0}
    assert compute_burst_score(photo) == pytest.approx(7.6)
    blink = {'aggregate': 8, 'aesthetic': 6, 'tech_sharpness': 7, 'is_blink': 1}
    assert compute_burst_score(blink) == pytest.approx(6.1)


def test_keeper_baseline_accuracy():
    heur_a = np.array([8.0, 3.0, 5.0])
    heur_b = np.array([4.0, 6.0, 5.0])
    y = np.array([1, 1, 0])
    assert kh._keeper_baseline_accuracy(heur_a, heur_b, y) == pytest.approx(2 / 3)


# --- dataset extension ---

def test_with_heuristic_dataset_shapes(keeper_db):
    signals = _seed_photos(keeper_db, n=40)
    _add_culling(keeper_db, signals, count=80)
    opt = WeightOptimizer(keeper_db, 'scoring_config.json')
    conn = sqlite3.connect(keeper_db)
    conn.row_factory = sqlite3.Row
    data = pr.build_ranker_dataset(conn, opt, sources=['culling'], with_heuristic=True)
    conn.close()
    assert data['heur_a'] is not None and data['heur_b'] is not None
    assert len(data['heur_a']) == data['n_pairs'] == len(data['heur_b'])


def test_default_dataset_unchanged(keeper_db):
    signals = _seed_photos(keeper_db, n=40)
    _add_culling(keeper_db, signals, count=80)
    opt = WeightOptimizer(keeper_db, 'scoring_config.json')
    conn = sqlite3.connect(keeper_db)
    conn.row_factory = sqlite3.Row
    data = pr.build_ranker_dataset(conn, opt, sources=['culling'])
    conn.close()
    assert data['heur_a'] is None and data['heur_b'] is None


# --- trainer gate ---

def test_too_few_culling_pairs_errors(keeper_db):
    signals = _seed_photos(keeper_db, n=20)
    _add_culling(keeper_db, signals, count=10)
    result = kh.train_keeper_head(keeper_db)
    assert 'error' in result and result['n_pairs'] < kh.MIN_COMPARISONS
    assert _load_head(keeper_db) is None


def test_head_beats_heuristic_and_persists(keeper_db):
    signals = _seed_photos(keeper_db, n=40, aggregate="noise")
    _add_culling(keeper_db, signals, count=80)
    result = kh.train_keeper_head(keeper_db, min_improvement_pp=2.0)
    assert 'error' not in result
    assert result['cv_accuracy'] > 80.0
    assert result['improvement_pp'] >= 2.0
    assert result['gated'] is False and result['written'] is True
    head = _load_head(keeper_db)
    assert head is not None
    assert head.emb_dim == 16
    assert head.w.shape[0] == head.col_std.shape[0]


def test_gate_blocks_when_heuristic_already_optimal(keeper_db):
    signals = _seed_photos(keeper_db, n=40, aggregate="signal")
    _add_culling(keeper_db, signals, count=80)
    result = kh.train_keeper_head(keeper_db, min_improvement_pp=2.0)
    assert result.get('gated') is True and result['written'] is False
    assert _load_head(keeper_db) is None


def test_force_persists_despite_gate(keeper_db):
    signals = _seed_photos(keeper_db, n=40, aggregate="signal")
    _add_culling(keeper_db, signals, count=80)
    result = kh.train_keeper_head(keeper_db, min_improvement_pp=2.0, force=True)
    assert result['gated'] is False and result['written'] is True
    assert _load_head(keeper_db) is not None


# --- within-group scorer ---

def test_group_probs_sum_to_one_and_order_by_signal(keeper_db):
    signals = _seed_photos(keeper_db, n=40, aggregate="noise")
    _add_culling(keeper_db, signals, count=80)
    kh.train_keeper_head(keeper_db, min_improvement_pp=2.0, force=True)
    head = _load_head(keeper_db)
    opt = WeightOptimizer(keeper_db, 'scoring_config.json')
    ordered = sorted(signals, key=lambda p: signals[p])
    pick = [ordered[0], ordered[len(ordered) // 2], ordered[-1]]
    probs = kh.keeper_probs_for_group(head, opt, _rows(keeper_db, pick))
    assert probs is not None
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-6)
    assert max(probs, key=probs.get) == pick[-1]


def test_group_probs_none_when_fewer_than_two(keeper_db):
    signals = _seed_photos(keeper_db, n=40)
    _add_culling(keeper_db, signals, count=80)
    kh.train_keeper_head(keeper_db, force=True)
    head = _load_head(keeper_db)
    opt = WeightOptimizer(keeper_db, 'scoring_config.json')
    one = _rows(keeper_db, [next(iter(signals))])
    assert kh.keeper_probs_for_group(head, opt, one) is None
    assert kh.keeper_probs_for_group(None, opt, one) is None


# --- snapshot round-trip ---

def test_save_load_roundtrip(keeper_db):
    conn = sqlite3.connect(keeper_db)
    conn.row_factory = sqlite3.Row
    head = kh.KeeperHead(w=[0.1, 0.2, 0.3], col_std=[1.0, 2.0, 4.0],
                         emb_dim=1, n_metrics=1,
                         meta={'n_pairs': 42, 'cv_accuracy': 88.0})
    kh.save_keeper_head(conn, head, user_id=None, category=None)
    conn.close()
    loaded = _load_head(keeper_db)
    assert loaded is not None
    np.testing.assert_allclose(loaded.w, [0.1, 0.2, 0.3])
    np.testing.assert_allclose(loaded.col_std, [1.0, 2.0, 4.0])
    assert loaded.emb_dim == 1 and loaded.n_metrics == 1
    assert loaded.meta.get('n_pairs') == 42


# --- flag-off parity seam ---

def test_apply_keeper_scores_noop_without_head(keeper_db):
    from api.routers import burst_culling as bc
    signals = _seed_photos(keeper_db, n=6)
    conn = sqlite3.connect(keeper_db)
    conn.row_factory = sqlite3.Row
    paths = list(signals)[:3]
    groups = [{'type': 'burst',
               'photos': [{'path': p, 'burst_score': 3.0} for p in paths]}]
    bc._apply_keeper_scores(conn, groups, None)
    bc.attach_keeper_probs(conn, groups, None)
    conn.close()
    assert all(p['burst_score'] == 3.0 for p in groups[0]['photos'])
    assert all('keeper_prob' not in p for p in groups[0]['photos'])
    assert 'keeper_best_path' not in groups[0]


def test_apply_keeper_scores_best_relative_and_size_independent(keeper_db):
    """The keeper burst_score is best-relative (best == 10.0) and group-size
    independent: a shared non-best frame scores the same in a small and a large
    group, so _auto_keep_split's absolute strictness margin stays calibrated
    (raw 10*softmax would shrink the shared frame's score as the group grows).
    """
    from api.routers import burst_culling as bc
    signals = _seed_photos(keeper_db, n=40, aggregate="noise")
    _add_culling(keeper_db, signals, count=80)
    kh.train_keeper_head(keeper_db, min_improvement_pp=2.0, force=True)
    conn = sqlite3.connect(keeper_db)
    conn.row_factory = sqlite3.Row

    ordered = sorted(signals, key=lambda p: signals[p])  # ascending signal
    best, shared = ordered[-1], ordered[0]  # head prefers the highest signal
    small = [best, shared, ordered[1]]
    large = small + ordered[2:8]

    def score(paths):
        grp = [{'type': 'burst',
                'photos': [{'path': p, 'burst_score': 0.0} for p in paths]}]
        bc._apply_keeper_scores(conn, grp, None)
        return {p['path']: p['burst_score'] for p in grp[0]['photos']}

    s_small, s_large = score(small), score(large)
    conn.close()
    assert s_small[best] == pytest.approx(10.0)
    assert s_large[best] == pytest.approx(10.0)
    assert all(0.0 < v <= 10.0 + 1e-9 for v in s_small.values())
    # Same best dominates both groups, so the shared frame scores identically
    # regardless of group size.
    assert s_small[shared] == pytest.approx(s_large[shared], abs=1e-9)


# --- Highlights absolute-quality gate (regression) ---

def test_highlight_quality_falls_back_to_burst_score():
    from api.routers import burst_culling as bc
    assert bc._highlight_quality({'burst_score': 6.5}) == pytest.approx(6.5)
    assert bc._highlight_quality(
        {'burst_score': 10.0, 'heuristic_burst_score': 4.0}) == pytest.approx(4.0)
    assert bc._highlight_quality({}) == 0


def test_keeper_preserves_heuristic_score_for_highlights_gate(keeper_db):
    """Regression: keeper rescaling pins the group best's burst_score to 10.0,
    which would defeat the absolute ``highlights_min`` gate (every group best
    would be force-promoted to Highlights). ``_apply_keeper_scores`` must preserve
    the pre-keeper heuristic score and ``_highlight_quality`` must read it, so a
    low-absolute-quality keeper pick is correctly kept OUT of Highlights.
    """
    from api.routers import burst_culling as bc
    signals = _seed_photos(keeper_db, n=40, aggregate="noise")
    _add_culling(keeper_db, signals, count=80)
    kh.train_keeper_head(keeper_db, min_improvement_pp=2.0, force=True)

    ordered = sorted(signals, key=lambda p: signals[p])  # ascending signal
    picks = [ordered[-1], ordered[0], ordered[1]]        # head prefers highest signal
    rows = {r['path']: r for r in _rows(keeper_db, picks)}
    heur = {p: compute_burst_score(rows[p]) for p in picks}
    photos = [{'path': p, 'burst_score': heur[p]} for p in picks]
    group = [{'type': 'burst', 'photos': photos}]

    conn = sqlite3.connect(keeper_db)
    conn.row_factory = sqlite3.Row
    bc._apply_keeper_scores(conn, group, None)
    conn.close()

    best = max(photos, key=lambda p: p['burst_score'])   # keeper-rescaled best (== 10.0)
    assert best['burst_score'] == pytest.approx(10.0)
    assert best['heuristic_burst_score'] == pytest.approx(heur[best['path']])
    # noise aggregate keeps the heuristic score in ~[4.15, 7.35], below the 8.0
    # highlights_min default: the gate must read that, not the rescaled 10.0.
    assert bc._highlight_quality(best) == pytest.approx(heur[best['path']])
    assert bc._highlight_quality(best) < 8.0             # correctly NOT a highlight
    assert best['burst_score'] >= 8.0                    # the pre-fix gate would have promoted it


# --- attach_keeper_probs (trained path) ---

def test_attach_keeper_probs_trained(trained_keeper_db):
    from api.routers import burst_culling as bc
    db_path, signals, ordered = trained_keeper_db
    picks = [ordered[0], ordered[len(ordered) // 2], ordered[-1]]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    groups = [{'type': 'burst',
               'photos': [{'path': p, 'burst_score': 0.0} for p in picks]}]
    bc.attach_keeper_probs(conn, groups, None)
    conn.close()
    assert groups[0]['keeper_best_path'] == ordered[-1]
    probs = [p['keeper_prob'] for p in groups[0]['photos']]
    assert all(isinstance(v, float) for v in probs)
    assert sum(probs) == pytest.approx(1.0, abs=1e-6)


# --- keeper_probs_for_group skip branch ---

def test_keeper_probs_skips_none_and_wrong_dim_embeddings(trained_keeper_db):
    db_path, signals, ordered = trained_keeper_db
    head = _load_head(db_path)
    opt = WeightOptimizer(db_path, 'scoring_config.json')
    picks = ordered[-4:]
    by_path = {r['path']: r for r in _rows(db_path, picks)}
    none_row = dict(by_path[picks[0]])
    none_row['clip_embedding'] = None
    bad_row = dict(by_path[picks[1]])
    bad_row['clip_embedding'] = np.full(8, 0.1, dtype=np.float32).tobytes()
    good_a, good_b = dict(by_path[picks[2]]), dict(by_path[picks[3]])
    probs = kh.keeper_probs_for_group(head, opt, [none_row, bad_row, good_a, good_b])
    assert probs is not None
    assert set(probs) == {picks[2], picks[3]}
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-6)
    survivors_only = kh.keeper_probs_for_group(head, opt, [dict(by_path[picks[2]]), none_row])
    assert survivors_only is None


# --- burst_weights_from_config + heuristic_weights ---

def test_burst_weights_defaults_and_partial_override():
    assert burst_weights_from_config(None) == DEFAULT_BURST_WEIGHTS
    assert burst_weights_from_config({}) == DEFAULT_BURST_WEIGHTS
    partial = burst_weights_from_config({'weight_aggregate': 0.9})
    assert partial[0] == 0.9
    assert partial[1:] == DEFAULT_BURST_WEIGHTS[1:]


def test_build_ranker_dataset_heuristic_reflects_custom_weights(keeper_db):
    signals = _seed_photos(keeper_db, n=6)
    _add_culling(keeper_db, signals, count=2)
    opt = WeightOptimizer(keeper_db, 'scoring_config.json')
    conn = sqlite3.connect(keeper_db)
    conn.row_factory = sqlite3.Row
    data = pr.build_ranker_dataset(
        conn, opt, sources=['culling'], with_heuristic=True,
        heuristic_weights=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
    )
    conn.close()
    assert data is not None
    assert len(data['heur_a']) == data['n_pairs'] == len(data['heur_b'])
    np.testing.assert_allclose(data['heur_a'], 10.0)
    np.testing.assert_allclose(data['heur_b'], 10.0)


# --- _keeper_head_for scope fallback ---

def test_keeper_head_for_falls_back_to_global_then_user_wins(keeper_db):
    from api.routers import burst_culling as bc
    conn = sqlite3.connect(keeper_db)
    conn.row_factory = sqlite3.Row
    gh = kh.KeeperHead(w=[0.1, 0.2], col_std=[1.0, 1.0], emb_dim=0, n_metrics=1)
    kh.save_keeper_head(conn, gh, user_id=None, category=None)
    fallback = bc._keeper_head_for(conn, 'alice')
    assert fallback is not None
    np.testing.assert_allclose(fallback.w, [0.1, 0.2])
    uh = kh.KeeperHead(w=[0.9, 0.8], col_std=[1.0, 1.0], emb_dim=0, n_metrics=1)
    kh.save_keeper_head(conn, uh, user_id='alice', category=None)
    scoped = bc._keeper_head_for(conn, 'alice')
    conn.close()
    np.testing.assert_allclose(scoped.w, [0.9, 0.8])


# --- POST /api/photos/keeper_hints endpoint ---

def test_keeper_hints_empty_paths_returns_empty(anonymous_client):
    resp = anonymous_client.post("/api/photos/keeper_hints", json={"paths": []})
    assert resp.status_code == 200
    assert resp.json() == {}


def test_keeper_hints_no_head_returns_empty(anonymous_client, keeper_db):
    _seed_photos(keeper_db, n=4)
    with _get_db_patch(keeper_db):
        resp = anonymous_client.post(
            "/api/photos/keeper_hints", json={"paths": ["/r/p000.jpg"]})
    assert resp.status_code == 200
    assert resp.json() == {}


def test_keeper_hints_flags_weaker_siblings(anonymous_client, trained_keeper_db):
    db_path, signals, ordered = trained_keeper_db
    best, weak_a, weak_b = ordered[-1], ordered[0], ordered[1]
    _set_burst_group(db_path, [best, weak_a, weak_b], gid=1)
    with _get_db_patch(db_path):
        resp = anonymous_client.post(
            "/api/photos/keeper_hints", json={"paths": [best, weak_a, weak_b]})
    assert resp.status_code == 200
    hints = resp.json()
    assert set(hints) == {best, weak_a, weak_b}
    assert hints[best]['has_better'] is False
    assert hints[best]['best_path'] is None
    assert isinstance(hints[best]['keeper_prob'], float)
    for weak in (weak_a, weak_b):
        assert hints[weak]['has_better'] is True
        assert hints[weak]['best_path'] == best
        assert isinstance(hints[weak]['keeper_prob'], float)


def test_keeper_hints_omits_photo_without_burst_group(anonymous_client, trained_keeper_db):
    db_path, signals, ordered = trained_keeper_db
    grouped = [ordered[-1], ordered[0], ordered[1]]
    loner = ordered[5]
    _set_burst_group(db_path, grouped, gid=1)
    with _get_db_patch(db_path):
        resp = anonymous_client.post(
            "/api/photos/keeper_hints", json={"paths": grouped + [loner]})
    assert resp.status_code == 200
    hints = resp.json()
    assert loner not in hints
    assert set(hints) == set(grouped)


def test_keeper_hints_excludes_rejected_sibling(anonymous_client, trained_keeper_db):
    db_path, signals, ordered = trained_keeper_db
    best, weak_a, weak_b = ordered[-1], ordered[0], ordered[1]
    _set_burst_group(db_path, [best, weak_a, weak_b], gid=1)
    _reject_photo(db_path, best)
    with _get_db_patch(db_path):
        resp = anonymous_client.post(
            "/api/photos/keeper_hints", json={"paths": [best, weak_a, weak_b]})
    assert resp.status_code == 200
    hints = resp.json()
    assert best not in hints
    assert all(h['best_path'] != best for h in hints.values())


def test_keeper_hints_rejects_over_limit(anonymous_client):
    paths = [f"/r/x{i:04d}.jpg" for i in range(1001)]
    resp = anonymous_client.post("/api/photos/keeper_hints", json={"paths": paths})
    assert resp.status_code == 422
