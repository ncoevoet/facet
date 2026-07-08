"""Tests for the PIAA cold-start prior + blend (roadmap 2.5).

Covers: prior load/score round-trip; fitter determinism; the flag-off
byte-identical guarantee for train_ranker; flag-on zero-comparison prior-only
scores matching the standalone head; the calibration property (blend applied on
RAW scores BEFORE percentile normalization); and lambda(n) shape.
"""

import importlib.util
import json
import os
import sqlite3

import numpy as np
import pytest

from db.schema import init_database
from models.piaa_prior import PiaaPrior, prior_path, save_prior
from optimization import personal_ranker as pr
from optimization.weight_optimizer import WeightOptimizer
from tests.test_personal_ranker import _add_comparisons, _seed_photos

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REAL_CONFIG = os.path.join(_REPO_ROOT, "scoring_config.json")

_EMB_DIM = 16  # matches tests.test_personal_ranker._emb_bytes default


def _load_fitter():
    spec = importlib.util.spec_from_file_location(
        "fit_piaa_prior", os.path.join(_REPO_ROOT, "scripts", "fit_piaa_prior.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_prior(dim=_EMB_DIM, k=3, seed=0, version="test-v1"):
    rng = np.random.default_rng(seed)
    weights = rng.normal(size=(k, dim)).astype(np.float32)
    bias = rng.normal(size=k).astype(np.float32)
    names = [f"head{i}" for i in range(k)]
    meta = {"version": version, "dim": dim, "datasets": ["synthetic"]}
    return weights, bias, names, meta


def _write_prior_file(models_dir, dim=_EMB_DIM, **kw):
    weights, bias, names, meta = _make_prior(dim=dim, **kw)
    path = prior_path(dim, models_dir)
    save_prior(path, weights, bias, names, meta)
    return path, weights, bias, names, meta


# --- prior storage + scoring round-trip ---

def test_prior_load_score_round_trip(tmp_path):
    path, weights, bias, names, meta = _write_prior_file(str(tmp_path))
    prior = PiaaPrior.load_file(path)
    assert prior is not None
    assert prior.dim == _EMB_DIM
    assert prior.k == 3
    assert prior.version == "test-v1"
    assert prior.head_names == names

    rng = np.random.default_rng(1)
    emb = rng.normal(size=(5, _EMB_DIM))
    emb = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    expected = emb @ weights.T + bias
    np.testing.assert_allclose(prior.score(emb), expected, rtol=1e-6)

    mix = np.full(3, 1.0 / 3)
    np.testing.assert_allclose(prior.mixed_score(emb), expected @ mix, rtol=1e-6)
    # 1-D input -> scalar float
    assert isinstance(prior.mixed_score(emb[0]), float)


def test_prior_missing_file_is_none(tmp_path):
    assert PiaaPrior.load(_EMB_DIM, str(tmp_path)) is None
    assert PiaaPrior.load_file(str(tmp_path / "nope.npz")) is None


def test_prior_dim_mismatch_ignored(tmp_path):
    _write_prior_file(str(tmp_path), dim=_EMB_DIM)
    # Ask for a different dim -> canonical name differs -> None.
    assert PiaaPrior.load(32, str(tmp_path)) is None


# --- fitter determinism ---

def _cache_file(path, n, dim, seed):
    rng = np.random.default_rng(seed)
    emb = rng.normal(size=(n, dim)).astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    # A learnable target: correlated with the first embedding coordinate.
    scores = (emb[:, 0] * 5.0 + rng.normal(scale=0.1, size=n)).astype(np.float32)
    np.savez(path, embeddings=emb, scores=scores)
    return path


def test_fitter_is_deterministic(tmp_path):
    fitter = _load_fitter()
    c1 = _cache_file(str(tmp_path / "ava.npz"), 300, _EMB_DIM, seed=7)
    c2 = _cache_file(str(tmp_path / "tad.npz"), 250, _EMB_DIM, seed=8)

    w1, b1, n1, _ = fitter.fit_prior([c1, c2], _EMB_DIM, clusters=2, alpha=1.0, version="v1")
    w2, b2, n2, _ = fitter.fit_prior([c1, c2], _EMB_DIM, clusters=2, alpha=1.0, version="v1")

    np.testing.assert_array_equal(w1, w2)
    np.testing.assert_array_equal(b1, b2)
    assert n1 == n2
    # one head per dataset + up to 2 cluster heads, capped at 6
    assert n1[:2] == ["dataset:ava", "dataset:tad"]
    assert 2 <= len(n1) <= 6


def test_fitter_writes_loadable_prior(tmp_path):
    fitter = _load_fitter()
    c1 = _cache_file(str(tmp_path / "ava.npz"), 200, _EMB_DIM, seed=1)
    out = str(tmp_path / "piaa_prior_16.npz")
    weights, bias, names, meta = fitter.fit_prior([c1], _EMB_DIM, clusters=1, alpha=1.0, version="v2")
    save_prior(out, weights, bias, names, meta)
    prior = PiaaPrior.load_file(out)
    assert prior is not None and prior.version == "v2" and prior.dim == _EMB_DIM


# --- lambda(n) shape ---

def test_lambda_zero_and_monotone():
    assert pr._lambda_n(0, 10) == 0.0
    vals = [pr._lambda_n(n, 10) for n in range(0, 200, 5)]
    assert all(b >= a for a, b in zip(vals, vals[1:]))  # non-decreasing
    assert vals[-1] < 1.0 and vals[-1] > vals[0]


# --- flag-off byte-identical train_ranker ---

def _config_variants(tmp_path):
    """(config_without_block, config_with_enabled_false) as temp files."""
    with open(_REAL_CONFIG) as f:
        cfg = json.load(f)
    cfg.pop("piaa_prior", None)
    without = str(tmp_path / "cfg_absent.json")
    with open(without, "w") as f:
        json.dump(cfg, f)
    cfg["piaa_prior"] = {"enabled": False, "shrinkage_k": 10, "models_dir": "pretrained_models"}
    disabled = str(tmp_path / "cfg_disabled.json")
    with open(disabled, "w") as f:
        json.dump(cfg, f)
    return without, disabled


def _learned(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute(
            "SELECT photo_path, learned_score FROM learned_scores "
            "WHERE user_id IS NULL AND category IS NULL").fetchall())
    finally:
        conn.close()


def test_flag_off_is_byte_identical(tmp_path):
    db_path = str(tmp_path / "off.db")
    init_database(db_path)
    signals = _seed_photos(db_path, n=40, aggregate="noise")
    _add_comparisons(db_path, signals, count=80)

    without, disabled = _config_variants(tmp_path)
    pr.train_ranker(db_path, config_path=without, force=True)
    scores_absent = _learned(db_path)
    pr.train_ranker(db_path, config_path=disabled, force=True)
    scores_disabled = _learned(db_path)

    assert scores_absent  # something was written
    assert scores_absent.keys() == scores_disabled.keys()
    for path in scores_absent:
        assert scores_absent[path] == scores_disabled[path]


# --- flag-on: zero comparisons -> prior-only == standalone head ---

def _enabled_config(tmp_path, models_dir, shrinkage_k=10):
    with open(_REAL_CONFIG) as f:
        cfg = json.load(f)
    cfg["piaa_prior"] = {"enabled": True, "shrinkage_k": shrinkage_k, "models_dir": models_dir}
    path = str(tmp_path / "cfg_on.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    return path


def _percentile_normalize(raws):
    order = np.argsort(np.argsort(raws))
    return 10.0 * order / max(1, len(raws) - 1)


def test_flag_on_zero_comparisons_writes_prior_only(tmp_path):
    db_path = str(tmp_path / "cold.db")
    init_database(db_path)
    _seed_photos(db_path, n=25, aggregate="noise")  # photos, but NO comparisons

    models_dir = str(tmp_path / "models")
    os.makedirs(models_dir, exist_ok=True)
    prior_file, *_ = _write_prior_file(models_dir)
    prior = PiaaPrior.load_file(prior_file)
    config_path = _enabled_config(tmp_path, models_dir)

    result = pr.train_ranker(db_path, config_path=config_path)
    assert result.get("mode") == "prior_only"
    assert result["written"] > 0
    assert result["prior_version"] == prior.version

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT path, clip_embedding FROM photos ORDER BY path").fetchall()]
    written = dict(conn.execute(
        "SELECT photo_path, learned_score FROM learned_scores").fetchall())
    conn.close()

    from utils.embedding import bytes_to_normalized_embedding
    paths = [r["path"] for r in rows]
    embs = np.array([bytes_to_normalized_embedding(r["clip_embedding"]) for r in rows])
    raws = prior.mixed_score(embs)
    expected = _percentile_normalize(raws)
    for path, exp in zip(paths, expected):
        assert written[path] == pytest.approx(float(exp))


# --- calibration property: blend applied on RAW scores before normalization ---

def test_blend_differs_from_prior_only_by_delta_pre_normalization(tmp_path):
    db_path = str(tmp_path / "calib.db")
    init_database(db_path)
    _seed_photos(db_path, n=30, aggregate="noise")

    prior_file, *_ = _write_prior_file(str(tmp_path))
    prior = PiaaPrior.load_file(prior_file)
    optimizer = WeightOptimizer(db_path, _REAL_CONFIG)

    n_metrics = len(WeightOptimizer.SCORE_COMPONENTS)
    feat_dim = _EMB_DIM + n_metrics + 1
    col_std = np.ones(feat_dim)
    rng = np.random.default_rng(3)
    delta = rng.normal(size=feat_dim)
    lam = pr._lambda_n(20, 10)

    prior_raw = dict(pr._collect_scored(
        db_path, _EMB_DIM, lambda row, emb: prior.mixed_score(emb)))

    def blend_fn(row, emb):
        feat = pr._scaled_feature(row, emb, optimizer, None, col_std)
        return prior.mixed_score(emb) + lam * float(feat @ delta)

    blend_raw = dict(pr._collect_scored(db_path, _EMB_DIM, blend_fn))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM photos WHERE clip_embedding IS NOT NULL").fetchall()]
    conn.close()

    from utils.embedding import bytes_to_normalized_embedding
    assert set(prior_raw) == set(blend_raw)
    for row in rows:
        emb = bytes_to_normalized_embedding(row["clip_embedding"])
        feat = pr._scaled_feature(row, emb, optimizer, None, col_std)
        expected_delta = lam * float(feat @ delta)
        assert blend_raw[row["path"]] - prior_raw[row["path"]] == pytest.approx(expected_delta)


def test_flag_on_below_threshold_writes_prior_only(tmp_path):
    db_path = str(tmp_path / "few.db")
    init_database(db_path)
    signals = _seed_photos(db_path, n=20, aggregate="noise")
    _add_comparisons(db_path, signals, count=10)  # < MIN_COMPARISONS

    models_dir = str(tmp_path / "models")
    os.makedirs(models_dir, exist_ok=True)
    _write_prior_file(models_dir)
    config_path = _enabled_config(tmp_path, models_dir)

    result = pr.train_ranker(db_path, config_path=config_path)
    assert result.get("mode") == "prior_only"
    assert result["written"] > 0

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM learned_scores").fetchone()[0]
    conn.close()
    assert count == result["written"]


def test_flag_on_above_threshold_writes_blend(tmp_path):
    db_path = str(tmp_path / "blend.db")
    init_database(db_path)
    signals = _seed_photos(db_path, n=40, aggregate="noise")
    _add_comparisons(db_path, signals, count=80)

    models_dir = str(tmp_path / "models")
    os.makedirs(models_dir, exist_ok=True)
    _write_prior_file(models_dir)
    config_path = _enabled_config(tmp_path, models_dir)

    result = pr.train_ranker(db_path, config_path=config_path, force=True)
    assert result.get("mode") == "blend"
    assert result["written"] > 0
    assert 0.0 < result["lambda"] < 1.0
