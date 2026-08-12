"""CPU-only tests for scripts/qrealign_ab.py (Q-ReAlign vs Q-Align A/B eval).

Covers the pure-function surface only: stratified sampling, resume
bookkeeping, and the SRCC/PLCC/verdict math. No model is loaded and no pyiqa
metric is ever constructed — those paths are exercised by the maintainer's
GPU-box run and the CPU smoke test, not by this suite.
"""

import importlib.util
import json
import os
import sqlite3

import pytest

from db.schema import init_database

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "qrealign_ab", os.path.join(_REPO_ROOT, "scripts", "qrealign_ab.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qab = _load_module()


# --- stratified sampling ---

def _rows(n, seed=0):
    """n synthetic (path, aggregate) rows, aggregate spread uniformly over [0, 10)."""
    return [(f"/lib/p{i:04d}.jpg", (i / n) * 10.0) for i in range(n)]


def test_stratified_sample_respects_cap():
    rows = _rows(500)
    sample = qab.stratified_sample_rows(rows, 50, seed=1)
    assert len(sample) == 50
    assert len(set(sample)) == 50  # no duplicates


def test_stratified_sample_deterministic_for_same_seed():
    rows = _rows(500)
    a = qab.stratified_sample_rows(rows, 50, seed=7)
    b = qab.stratified_sample_rows(rows, 50, seed=7)
    assert a == b


def test_stratified_sample_differs_across_seeds():
    rows = _rows(500)
    a = qab.stratified_sample_rows(rows, 50, seed=1)
    b = qab.stratified_sample_rows(rows, 50, seed=2)
    assert a != b


def test_stratified_sample_covers_the_range():
    """The gate depends on the sample spanning low- and high-aggregate photos."""
    rows = _rows(1000)
    sample = qab.stratified_sample_rows(rows, 100, seed=3)
    aggs = [agg for _path, agg in sample]
    assert min(aggs) < 1.5   # bottom decile represented
    assert max(aggs) > 8.5   # top decile represented


def test_stratified_sample_n_exceeds_population_returns_all():
    rows = _rows(7)
    sample = qab.stratified_sample_rows(rows, 1000, seed=1)
    assert len(sample) == 7
    assert set(sample) == set(rows)


def test_stratified_sample_empty_rows():
    assert qab.stratified_sample_rows([], 10, seed=1) == []


def test_stratified_sample_zero_n():
    assert qab.stratified_sample_rows(_rows(20), 0, seed=1) == []


def test_fetch_stratified_sample_against_real_schema(tmp_path):
    """End-to-end against the real photos table — catches SQL/column typos
    the pure-function tests above can't."""
    db_path = str(tmp_path / "sample.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    for i in range(40):
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate) VALUES (?, ?, ?)",
            (f"/lib/p{i:03d}.jpg", f"p{i:03d}.jpg", float(i) / 4.0),  # 0..9.75
        )
    conn.commit()

    sample = qab.fetch_stratified_sample(conn, 10, seed=5)
    conn.close()

    assert len(sample) == 10
    aggs = [agg for _path, agg in sample]
    assert min(aggs) < 2.0
    assert max(aggs) > 8.0


# --- resume bookkeeping ---

def test_append_and_load_partial_round_trip(tmp_path):
    partial_file = str(tmp_path / "out.json.partial.jsonl")
    qab.append_partial(partial_file, {"model": "qalign", "path": "/a.jpg", "score": 3.5, "latency_s": 1.2})
    qab.append_partial(partial_file, {"model": "qrealign", "path": "/a.jpg", "score": 0.7, "latency_s": 0.4})

    records = qab.load_partial_records(partial_file)
    assert len(records) == 2
    assert records[0]["model"] == "qalign"
    assert records[1]["score"] == pytest.approx(0.7)


def test_load_partial_records_skips_malformed_lines(tmp_path):
    partial_file = tmp_path / "out.json.partial.jsonl"
    partial_file.write_text(
        json.dumps({"model": "qalign", "path": "/a.jpg", "score": 1.0}) + "\n"
        + "not json at all\n"
        + "\n"
        + json.dumps({"model": "qalign", "path": "/b.jpg", "score": 2.0}) + "\n"
    )
    records = qab.load_partial_records(str(partial_file))
    assert [r["path"] for r in records] == ["/a.jpg", "/b.jpg"]


def test_load_partial_records_missing_file_returns_empty(tmp_path):
    assert qab.load_partial_records(str(tmp_path / "does_not_exist.jsonl")) == []


def test_done_keys_includes_skipped_entries():
    records = [
        {"model": "qalign", "path": "/a.jpg", "score": 1.0},
        {"model": "qalign", "path": "/b.jpg", "score": None, "skipped": True},
        {"model": "qrealign", "path": "/a.jpg", "score": 0.5},
    ]
    keys = qab.done_keys(records)
    assert keys == {("qalign", "/a.jpg"), ("qalign", "/b.jpg"), ("qrealign", "/a.jpg")}


def test_filter_todo_skips_done_pairs_only():
    sample = [("/a.jpg", 5.0), ("/b.jpg", 6.0), ("/c.jpg", 7.0)]
    done = {("qalign", "/a.jpg"), ("qrealign", "/b.jpg")}
    assert qab.filter_todo(sample, "qalign", done) == ["/b.jpg", "/c.jpg"]
    assert qab.filter_todo(sample, "qrealign", done) == ["/a.jpg", "/c.jpg"]


def test_filter_todo_resume_shrinks_as_partial_file_grows(tmp_path):
    """Simulates an interrupted-then-resumed run: the second pass only sees
    the photos the first pass didn't already record."""
    partial_file = str(tmp_path / "out.json.partial.jsonl")
    sample = [(f"/p{i}.jpg", float(i)) for i in range(5)]

    first_pass = qab.filter_todo(sample, "qalign", set())
    assert first_pass == [p for p, _ in sample]
    for path in first_pass[:3]:
        qab.append_partial(partial_file, {"model": "qalign", "path": path, "score": 1.0})

    done = qab.done_keys(qab.load_partial_records(partial_file))
    resumed = qab.filter_todo(sample, "qalign", done)
    assert resumed == [p for p, _ in sample][3:]


# --- SRCC / PLCC / verdict ---

def test_correlate_perfect_positive():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0, 4.0, 6.0, 8.0, 10.0]
    srcc, plcc = qab._correlate(xs, ys)
    assert srcc == pytest.approx(1.0)
    assert plcc == pytest.approx(1.0)


def test_correlate_perfect_negative():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [5.0, 4.0, 3.0, 2.0, 1.0]
    srcc, plcc = qab._correlate(xs, ys)
    assert srcc == pytest.approx(-1.0)
    assert plcc == pytest.approx(-1.0)


def test_correlate_undefined_with_no_variance():
    xs = [1.0, 1.0, 1.0]
    ys = [1.0, 2.0, 3.0]
    srcc, plcc = qab._correlate(xs, ys)
    assert srcc is None
    assert plcc is None


def test_correlate_undefined_below_min_pairs():
    srcc, plcc = qab._correlate([1.0, 2.0], [1.0, 2.0])
    assert srcc is None
    assert plcc is None


def _records(scores, latency=1.0):
    return {path: {"score": s, "latency_s": latency} for path, s in scores.items()}


def test_compute_per_model_stats_mean_srcc_across_columns():
    records = _records({"/a.jpg": 1.0, "/b.jpg": 2.0, "/c.jpg": 3.0, "/d.jpg": 4.0})
    stored = {
        "/a.jpg": {"topiq_score": 1.0, "liqe_score": 4.0, "aesthetic": 1.0},
        "/b.jpg": {"topiq_score": 2.0, "liqe_score": 3.0, "aesthetic": 2.0},
        "/c.jpg": {"topiq_score": 3.0, "liqe_score": 2.0, "aesthetic": 3.0},
        "/d.jpg": {"topiq_score": 4.0, "liqe_score": 1.0, "aesthetic": 4.0},
    }
    stats = qab.compute_per_model_stats(records, stored, peak_vram_gb=2.5, n_skipped=1)
    assert stats["n_scored"] == 4
    assert stats["n_skipped"] == 1
    assert stats["mean_latency_s"] == pytest.approx(1.0)
    assert stats["peak_vram_gb"] == pytest.approx(2.5)
    assert stats["vs_stored"]["topiq_score"]["srcc"] == pytest.approx(1.0)
    assert stats["vs_stored"]["liqe_score"]["srcc"] == pytest.approx(-1.0)
    assert stats["vs_stored"]["aesthetic"]["srcc"] == pytest.approx(1.0)
    # mean of [+1, -1, +1] == 1/3
    assert stats["mean_srcc_vs_stored"] == pytest.approx(1.0 / 3.0)


def test_compute_per_model_stats_missing_stored_column_is_excluded():
    records = _records({"/a.jpg": 1.0, "/b.jpg": 2.0, "/c.jpg": 3.0})
    stored = {
        "/a.jpg": {"topiq_score": 1.0, "liqe_score": None, "aesthetic": 1.0},
        "/b.jpg": {"topiq_score": 2.0, "liqe_score": None, "aesthetic": 2.0},
        "/c.jpg": {"topiq_score": 3.0, "liqe_score": None, "aesthetic": 3.0},
    }
    stats = qab.compute_per_model_stats(records, stored)
    assert stats["vs_stored"]["liqe_score"]["srcc"] is None
    assert stats["vs_stored"]["liqe_score"]["n"] == 0
    assert stats["vs_stored"]["topiq_score"]["srcc"] == pytest.approx(1.0)


def test_compute_inter_model_srcc_uses_common_paths_only():
    by_model = {
        "qalign": _records({"/a.jpg": 1.0, "/b.jpg": 2.0, "/c.jpg": 3.0, "/only_qalign.jpg": 9.0}),
        "qrealign": _records({"/a.jpg": 0.1, "/b.jpg": 0.2, "/c.jpg": 0.3, "/only_qrealign.jpg": 0.9}),
    }
    out = qab.compute_inter_model_srcc(["qalign", "qrealign"], by_model)
    assert out["qalign_vs_qrealign"]["n"] == 3
    assert out["qalign_vs_qrealign"]["srcc"] == pytest.approx(1.0)


def test_compute_verdict_ships_when_srcc_and_latency_both_favor_qrealign():
    per_model = {
        "qalign": {"mean_srcc_vs_stored": 0.80, "mean_latency_s": 5.0},
        "qrealign": {"mean_srcc_vs_stored": 0.82, "mean_latency_s": 1.0},
    }
    verdict = qab.compute_verdict(per_model, ["qalign", "qrealign"])
    assert verdict["ship"] is True
    assert verdict["srcc_ok"] is True
    assert verdict["latency_ok"] is True


def test_compute_verdict_ships_within_tolerance_band():
    """0.01 below qalign is still within the recorded tolerance."""
    per_model = {
        "qalign": {"mean_srcc_vs_stored": 0.80, "mean_latency_s": 5.0},
        "qrealign": {"mean_srcc_vs_stored": 0.79, "mean_latency_s": 5.0},
    }
    verdict = qab.compute_verdict(per_model, ["qalign", "qrealign"])
    assert verdict["ship"] is True


def test_compute_verdict_blocks_on_srcc_regression_beyond_tolerance():
    per_model = {
        "qalign": {"mean_srcc_vs_stored": 0.80, "mean_latency_s": 5.0},
        "qrealign": {"mean_srcc_vs_stored": 0.78, "mean_latency_s": 1.0},
    }
    verdict = qab.compute_verdict(per_model, ["qalign", "qrealign"])
    assert verdict["ship"] is False
    assert verdict["srcc_ok"] is False
    assert verdict["latency_ok"] is True


def test_compute_verdict_blocks_on_slower_latency():
    per_model = {
        "qalign": {"mean_srcc_vs_stored": 0.80, "mean_latency_s": 5.0},
        "qrealign": {"mean_srcc_vs_stored": 0.85, "mean_latency_s": 5.1},
    }
    verdict = qab.compute_verdict(per_model, ["qalign", "qrealign"])
    assert verdict["ship"] is False
    assert verdict["srcc_ok"] is True
    assert verdict["latency_ok"] is False


def test_compute_verdict_none_without_exactly_one_pair_of_each_family():
    per_model = {
        "qalign": {"mean_srcc_vs_stored": 0.8, "mean_latency_s": 5.0},
        "qalign_8bit": {"mean_srcc_vs_stored": 0.8, "mean_latency_s": 5.0},
        "qrealign": {"mean_srcc_vs_stored": 0.8, "mean_latency_s": 1.0},
    }
    assert qab.compute_verdict(per_model, list(per_model)) is None


def test_compute_verdict_inconclusive_on_missing_srcc():
    per_model = {
        "qalign": {"mean_srcc_vs_stored": None, "mean_latency_s": 5.0},
        "qrealign": {"mean_srcc_vs_stored": 0.8, "mean_latency_s": 1.0},
    }
    verdict = qab.compute_verdict(per_model, ["qalign", "qrealign"])
    assert verdict["ship"] is None
    assert "SRCC" in verdict["reason"]
