"""Read-only model evaluation against the user's own pairwise picks.

    python facet.py --evaluate-models aesthetic --candidates stored:topiq_score,qrealign-mini:aesthetic

For each candidate in a *slot* (aesthetic, quality, face-quality, end-to-end) this
measures how often the candidate's score ranks the winner of a decisive
``comparisons`` row above the loser. A candidate either reads a stored ``photos``
column (``stored:<column>``) or scores the original files live; live scores are
cached to a resumable JSONL sidecar next to the report, so a long GPU run
survives interruption and a rerun only scores what is missing.

The DB is opened ``mode=ro`` and never written. Other waves add candidates with
:func:`register_candidate`.
"""

import json
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from db.person_carry_over import match_boxes
from optimization.eval_common import (
    append_partial,
    bootstrap_ci,
    done_keys,
    load_original,
    load_partial_records,
    measure,
    pairwise_agreement,
    partial_path,
    ro_connection,
    size_bucket,
    split_halves,
    stratified_sample_rows,
    SIZE_BUCKETS,
    pairwise_f1_grid,
)
from utils.image_bounds import bound_to_inference_size

logger = logging.getLogger("facet.model_eval")

DEFAULT_SEED = 42
DEFAULT_OUT_DIR = os.path.join('.facet_cache', 'eval')

# Slot -> the ``photos`` column a candidate's value replaces in the end-to-end
# aggregate recompute. ``quality_score`` carries no aggregate weight (it is
# redistributed into ``aesthetic``), so a quality candidate is a no-op there.
SLOT_TARGET_COLUMNS = {
    'aesthetic': 'aesthetic',
    'quality': 'quality_score',
    'face-quality': 'face_quality',
}
# Slots scored against the stored InsightFace faces, not against pairwise picks.
FACE_REFERENCE_SLOTS = ('faces-detect', 'faces-recognize', 'faces-centroid', 'blink')
END_TO_END = 'end-to-end'
SLOTS = ('aesthetic', 'quality', 'faces-detect', 'faces-recognize', 'faces-centroid', 'blink', 'face-quality', END_TO_END)

STORED_PREFIX = 'stored:'
_BLOB_COLUMNS = frozenset({
    'thumbnail', 'clip_embedding', 'caption_embedding', 'histogram_data', 'face_embedding',
})


@dataclass(frozen=True)
class StoredColumn:
    """A candidate that reads an already-computed ``photos`` column."""
    column: str


@dataclass(frozen=True)
class Candidate:
    slot: str
    name: str
    # StoredColumn, or ``factory(device) -> score(pil) -> float`` on the 0-10 scale.
    # A scorer may expose ``close()`` to release its model after the run.
    # Face slots: ``factory(device, arg)`` builds a detector / embedder, ``arg`` being
    # the number after ``@`` in ``yunet@0.8`` (None when the name has no ``@``).
    factory: object
    arg: object = None

    def variant(self, name, arg):
        return Candidate(self.slot, name, self.factory, arg)


_REGISTRY: dict[tuple[str, str], Candidate] = {}


def register_candidate(slot: str, name: str, scorer_factory) -> Candidate:
    """Register a candidate for ``slot`` (later waves add theirs here)."""
    if slot not in SLOTS:
        raise ValueError(f"unknown slot {slot!r}; expected one of {SLOTS}")
    cand = Candidate(slot, name, scorer_factory)
    _REGISTRY[(slot, name)] = cand
    return cand


def registered_candidates(slot: str) -> list[Candidate]:
    return [c for (s, _), c in _REGISTRY.items() if s == slot]


def _pyiqa_qrealign_factory(pyiqa_id: str, task: str) -> Callable:
    """Live Q-ReAlign via pyiqa; raw (0, 1) is scaled to 0-10 like production."""
    def factory(device):
        import torch
        from models.pyiqa_scorer import _ensure_pyiqa
        pyiqa = _ensure_pyiqa()
        metric = pyiqa.create_metric(pyiqa_id, device=torch.device(device), as_loss=False)

        def score(pil):
            with torch.no_grad():
                raw = metric(pil, task_=task)
            return float(raw.item() if hasattr(raw, 'item') else raw) * 10.0

        def close():
            nonlocal metric
            if hasattr(metric, 'cpu'):
                metric.cpu()
            metric = None
            if device == 'cuda':
                torch.cuda.empty_cache()

        score.close = close
        return score
    return factory


def _native_qrealign_factory(size: str, task: str) -> Callable:
    """Q-ReAlign through plain transformers (no pyiqa); scores are already 0-10."""
    def factory(device):
        from models.qrealign_native import QReAlignNativeScorer
        scorer = QReAlignNativeScorer(size=size, device=device).load()

        def score(pil):
            return scorer.score(pil, task=task)

        score.close = scorer.unload
        return score
    return factory


def _register_builtins():
    stored = {
        'aesthetic': ('aesthetic', 'topiq_score', 'aesthetic_iaa', 'qrealign_score',
                      'aesthetic_clip', 'aesthetic_v25', 'deqa_score'),
        'quality': ('quality_score', 'topiq_score', 'liqe_score', 'qrealign_score'),
        'face-quality': ('face_quality', 'face_quality_iqa'),
        END_TO_END: ('aggregate',),
    }
    for slot, columns in stored.items():
        for col in columns:
            register_candidate(slot, f'{STORED_PREFIX}{col}', StoredColumn(col))
    # Both heads are offered in both slots: whether the quality head ranks
    # aesthetic picks better than the aesthetic head is part of the question.
    for size in ('mini', 'lite'):
        for task in ('aesthetic', 'quality'):
            factory = _pyiqa_qrealign_factory(f'qrealign-{size}', task)
            for slot in ('aesthetic', 'quality'):
                register_candidate(slot, f'qrealign-{size}:{task}', factory)
            native = _native_qrealign_factory(size, task)
            for slot in ('aesthetic', 'quality'):
                register_candidate(slot, f'qrealign-native-{size}:{task}', native)


_register_builtins()


def fetch_decisive_pairs(conn):
    """(pairs, n_ties): decisive ``(a_path, b_path, winner)`` rows and the tie count."""
    from comparison.training_scope import distinct_photo_sql, read_snapshot
    with read_snapshot(conn):
        distinct = distinct_photo_sql(conn, 'c.photo_a_path', 'c.photo_b_path')
        pairs = [(r[0], r[1], r[2]) for r in conn.execute(
            f"SELECT photo_a_path, photo_b_path, winner FROM comparisons c WHERE winner IN ('a', 'b') AND {distinct}")]
        n_ties = conn.execute(f"SELECT COUNT(*) FROM comparisons c WHERE winner = 'tie' AND {distinct}").fetchone()[0]
        return pairs, n_ties


def _chunks(items, size=500):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_stored_column(conn, column, paths):
    """{path: float|None} for one ``photos`` column."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
    if column not in cols or column in _BLOB_COLUMNS:
        raise ValueError(f"stored candidate column {column!r} is not a scalar photos column")
    out = {}
    for chunk in _chunks(list(paths)):
        marks = ','.join('?' * len(chunk))
        for path, val in conn.execute(
                f"SELECT path, {column} FROM photos WHERE path IN ({marks})", chunk):
            out[path] = float(val) if isinstance(val, (int, float)) else None
    return out


def fetch_metric_rows(conn, paths):
    """{path: metrics dict} (blob columns excluded) with scoring overrides applied."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(photos)") if r[1] not in _BLOB_COLUMNS]
    select = ', '.join(cols)
    rows = {}
    for chunk in _chunks(list(paths)):
        marks = ','.join('?' * len(chunk))
        for row in conn.execute(f"SELECT {select} FROM photos WHERE path IN ({marks})", chunk):
            rows[row['path']] = dict(row)
        for row in conn.execute(
                "SELECT photo_path, scoring_context, category_override "
                f"FROM photo_scoring_overrides WHERE photo_path IN ({marks})", chunk):
            if row[0] in rows:
                rows[row[0]]['scoring_context'] = row[1]
                rows[row[0]]['category_override'] = row[2]
    return rows


def resolve_candidate(slot: str, name: str) -> Candidate:
    """Registered candidate, or an ad-hoc ``stored:<column>``."""
    cand = _REGISTRY.get((slot, name))
    if cand is not None:
        return cand
    if '@' in name and (slot, name.partition('@')[0]) in _REGISTRY:
        base, _, arg = name.partition('@')
        return _REGISTRY[(slot, base)].variant(name, _parse_variant(name, arg))
    if slot == 'face-quality' and name == 'ofiq':
        raise ValueError(_ofiq_unavailable_message())
    if name.startswith(STORED_PREFIX):
        return Candidate(slot, name, StoredColumn(name[len(STORED_PREFIX):]))
    known = ', '.join(c.name for c in registered_candidates(slot)) or '(none)'
    raise ValueError(f"unknown candidate {name!r} for slot {slot!r}; registered: {known}")


def score_live(name, factory, paths, partial_file, device):
    """Score ``paths`` from the originals with a live scorer, resuming from the sidecar.

    Returns ``({path: score|None}, run_stats, mean_latency_s)``. Photos that were
    recorded earlier (scored or skipped) are not rescored; ``run_stats`` is
    empty when nothing needed scoring.
    """
    done = done_keys(load_partial_records(partial_file))
    todo = [p for p in paths if (name, p) not in done]
    run_stats = {}
    if todo:
        logger.info("[%s] loading scorer on %s (%d/%d photos to score)", name, device, len(todo), len(paths))
        with measure() as run_stats:
            score = factory(device)
            try:
                for i, path in enumerate(todo, 1):
                    img = load_original(path)
                    if img is None:
                        append_partial(partial_file, {"model": name, "path": path, "score": None, "skipped": True})
                        continue
                    t0 = time.monotonic()
                    try:
                        value = score(bound_to_inference_size(img))
                    except Exception as e:
                        logger.warning("[%s] inference failed on %s: %s", name, path, e)
                        append_partial(partial_file, {
                            "model": name, "path": path, "score": None, "skipped": True, "error": str(e)})
                        continue
                    append_partial(partial_file, {
                        "model": name, "path": path, "score": float(value),
                        "latency_s": time.monotonic() - t0})
                    if i % 50 == 0:
                        logger.info("[%s] %d/%d", name, i, len(todo))
            finally:
                close = getattr(score, 'close', None)
                if close:
                    close()
    wanted = set(paths)
    scores, latencies = {}, []
    for rec in load_partial_records(partial_file):
        if rec.get("model") != name or rec.get("path") not in wanted:
            continue
        scores[rec["path"]] = rec.get("score")
        if rec.get("score") is not None and rec.get("latency_s") is not None:
            latencies.append(rec["latency_s"])
    mean_latency = sum(latencies) / len(latencies) if latencies else None
    return scores, run_stats, mean_latency


def _candidate_scores(conn, cand, paths, partial_file, device):
    """(scores, run_stats, mean_latency_s) for one candidate on 0-10 scale."""
    if isinstance(cand.factory, StoredColumn):
        return fetch_stored_column(conn, cand.factory.column, paths), {}, None
    return score_live(cand.name, cand.factory, paths, partial_file, device)


def baseline_match_rate(conn, scorer, paths, normalizer, tol=0.01):
    """Fraction of photos whose recomputed, unsubstituted aggregate equals the stored one."""
    from processing.scorer import Facet
    rows = fetch_metric_rows(conn, paths)
    hits = n = 0
    for row in rows.values():
        if row.get('aggregate') is None:
            continue
        agg = scorer.calculate_aggregate_logic(
            Facet.prepare_scoring_row(dict(row), scorer.config, normalizer))[0]
        n += 1
        hits += abs(round(agg, 2) - row['aggregate']) <= tol
    return hits / n if n else None


def _end_to_end_scores(conn, base_slot, cand, paths, partial_file, device, scorer, normalizer=None):
    """Aggregate per photo with the candidate's value substituted into its slot's column.

    ``base_slot`` None means the candidate is the stored aggregate itself.
    """
    if base_slot is None:
        return _candidate_scores(conn, cand, paths, partial_file, device)
    from processing.scorer import Facet
    values, run_stats, mean_latency = _candidate_scores(conn, cand, paths, partial_file, device)
    rows = fetch_metric_rows(conn, paths)
    target = SLOT_TARGET_COLUMNS[base_slot]
    scores = {}
    for path in paths:
        value, row = values.get(path), rows.get(path)
        if value is None or row is None:
            scores[path] = None
            continue
        metrics = Facet.prepare_scoring_row(dict(row), scorer.config, normalizer)
        metrics[target] = value
        scores[path] = scorer.calculate_aggregate_logic(metrics)[0]
    return scores, run_stats, mean_latency


def _resolve_end_to_end(name):
    """``stored:aggregate`` or ``<slot>:<candidate>`` (e.g. ``aesthetic:qrealign-mini:aesthetic``)."""
    if name == f'{STORED_PREFIX}aggregate':
        return None, resolve_candidate(END_TO_END, name)
    base_slot, _, rest = name.partition(':')
    if base_slot not in SLOT_TARGET_COLUMNS or not rest:
        raise ValueError(
            f"end-to-end candidate {name!r} must be 'stored:aggregate' or '<slot>:<candidate>' "
            f"with slot in {tuple(SLOT_TARGET_COLUMNS)}")
    return base_slot, resolve_candidate(base_slot, rest)


def _default_candidates(slot):
    if slot == END_TO_END:
        names = [f'{STORED_PREFIX}aggregate']
        for base in SLOT_TARGET_COLUMNS:
            if base == 'quality':
                continue  # a no-op substitution: would only re-run live models for the baseline
            names += [f'{base}:{c.name}' for c in registered_candidates(base)]
        return names
    return [c.name for c in registered_candidates(slot)]


def evaluate(db_path, slot, candidates=None, out=None, seed=DEFAULT_SEED, config_path=None, device=None,
             limit=None):
    """Run the evaluation and write the JSON report; returns the report dict.

    ``limit`` only applies to the face slots (photos for faces-detect, reference
    faces for faces-recognize).
    """
    if slot not in SLOTS:
        raise ValueError(f"unknown slot {slot!r}; expected one of {SLOTS}")
    if slot in FACE_REFERENCE_SLOTS:
        return _evaluate_faces(db_path, slot, candidates, out, seed, limit)
    names = list(candidates) if candidates else _default_candidates(slot)
    if device is None:
        try:
            import torch
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        except ImportError:
            device = 'cpu'
    if out is None:
        out = os.path.join(DEFAULT_OUT_DIR, f"{slot}-{time.strftime('%Y%m%d-%H%M%S')}.json")
    partial_file = partial_path(os.path.join(os.path.dirname(os.path.abspath(out)), 'live-scores'))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    scorer = None
    if slot == END_TO_END:
        from config import ScoringConfig
        from processing.scorer import Facet
        # Bypass Facet.__init__: it ends in init_database(db_path), which migrates
        # the schema and flips journal_mode to WAL — a write to the evaluated DB.
        # calculate_aggregate_logic only needs ``config``.
        scorer = Facet.__new__(Facet)
        scorer.config = ScoringConfig(config_path)

    conn = ro_connection(db_path)
    try:
        pairs, n_ties = fetch_decisive_pairs(conn)
        paths = sorted({p for a, b, _ in pairs for p in (a, b)})
        logger.info("%s: %d decisive pairs over %d photos (%d ties set aside)",
                    slot, len(pairs), len(paths), n_ties)
        normalizer = match_rate = None
        if scorer is not None:
            from config.percentile_normalizer import PercentileNormalizer
            normalizer = PercentileNormalizer.from_snapshot(
                conn, scorer.config.get_normalization_settings())
            match_rate = baseline_match_rate(conn, scorer, paths, normalizer)
            logger.info("Recomputed baseline reproduces the stored aggregate for %s of photos "
                        "(the rest drifted with config/category changes since the last recompute)",
                        'n/a' if match_rate is None else f'{match_rate:.1%}')
        results = {}
        for name in names:
            if slot == END_TO_END:
                base_slot, cand = _resolve_end_to_end(name)
                scores, run_stats, mean_latency = _end_to_end_scores(
                    conn, base_slot, cand, paths, partial_file, device, scorer, normalizer)
            else:
                scores, run_stats, mean_latency = _candidate_scores(
                    conn, resolve_candidate(slot, name), paths, partial_file, device)
            agree = pairwise_agreement(pairs, scores)
            lo, hi = bootstrap_ci(agree['per_pair'], seed=seed)
            results[name] = {
                'agreement': agree['agreement'],
                'ci_low': lo,
                'ci_high': hi,
                'n_pairs': agree['n_pairs'],
                'coverage': agree['coverage'],
                'mean_latency_s': mean_latency,
                'peak_vram_gb': run_stats.get('peak_vram_gb'),
                'peak_rss_gb': run_stats.get('peak_rss_gb'),
            }
    finally:
        conn.close()

    report = {
        'slot': slot,
        'db': os.path.abspath(db_path),
        'seed': seed,
        'n_decisive_pairs': len(pairs),
        'n_ties': n_ties,
        'candidates': results,
    }
    if slot == END_TO_END:
        report['baseline_match_rate'] = match_rate
    with open(out, 'w') as f:
        json.dump(report, f, indent=2)
    log_report(report)
    logger.info("Report written to %s", out)
    return report


def log_report(report):
    def fmt(v, spec):
        return 'n/a' if v is None else format(v, spec)

    logger.info("%-34s %9s %17s %7s %6s %8s %8s %8s", "candidate", "agree", "95% CI", "pairs",
                "cover", "lat(s)", "VRAM", "RSS")
    for name, r in report['candidates'].items():
        ci = f"[{fmt(r['ci_low'], '.3f')}, {fmt(r['ci_high'], '.3f')}]"
        logger.info("%-34s %9s %17s %7d %6s %8s %8s %8s", name, fmt(r['agreement'], '.3f'), ci,
                    r['n_pairs'], fmt(r['coverage'], '.2f'), fmt(r['mean_latency_s'], '.2f'),
                    fmt(r['peak_vram_gb'], '.2f'), fmt(r['peak_rss_gb'], '.2f'))


# ---------------------------------------------------------------------------
# Face slots (faces-detect, faces-recognize)
#
# Scored against the stored InsightFace faces as the REFERENCE, which is only
# meaningful on a default-mode (buffalo_l) library: the reference is the incumbent
# model, not ground truth, so a match rate is agreement with InsightFace.
# Neither slot writes anything; results go to the JSON report only.
# ---------------------------------------------------------------------------

REFERENCE_EMBEDDING_MODEL = 'arcface_buffalo_l'
DEFAULT_DETECT_PHOTOS = 600
DEFAULT_RECOGNIZE_FACES = 1200
POSITIVE_SHARE = 0.7          # share of the detect sample drawn from photos with stored faces
PER_PERSON_FACES = 8
MIN_PERSON_FACES = 3
IOU_MATCH = 0.5
BLAZEFACE_MAX_SIDE = 1280
DEFAULT_BLAZEFACE_CONFIDENCE = 0.5   # MediaPipe's own default
DEFAULT_YUNET_CONFIDENCE = 0.7       # PermissiveFaceAnalyzer's constructor default
# MediaPipe BlazeFace short-range, pinned to the versioned float16/1 URL like the
# face landmarker. Apache-2.0 per the MediaPipe model card (not re-read from a
# LICENSE file in this repo).
BLAZEFACE_WEIGHTS_FILENAME = 'blaze_face_short_range.tflite'
BLAZEFACE_WEIGHTS_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite")
BLAZEFACE_WEIGHTS_SHA256 = "b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f"


def default_threshold_grid():
    """Cosine thresholds 0.20 .. 0.60 step 0.025 (17 points)."""
    return [round(0.20 + 0.025 * i, 3) for i in range(17)]


def _parse_variant(name, arg):
    try:
        return float(arg)
    except ValueError:
        raise ValueError(f"candidate {name!r}: the part after '@' must be a number") from None


def _ofiq_unavailable_message():
    import importlib.util
    if importlib.util.find_spec('ofiq') is None:
        return ("face-quality candidate 'ofiq' skipped: python-ofiq is not installed. "
                "It is on PyPI (`pip install python-ofiq`) but ships wheels for Linux x86-64 and "
                "macOS arm64 only; on Windows use WSL2 or Docker (docs/FACE_RECOGNITION.md, commercial mode)")
    return "face-quality candidate 'ofiq': ofiq is importable but no adapter is wired yet (UNVERIFIED)"


def _to_bgr(pil):
    import cv2
    return cv2.cvtColor(np.asarray(pil.convert('RGB')), cv2.COLOR_RGB2BGR)


def _load_bgr(path):
    pil = load_original(path)
    return None if pil is None else _to_bgr(pil)


def _yunet_detector_factory(device, conf):
    from analyzers.face_permissive import PermissiveFaceAnalyzer
    an = PermissiveFaceAnalyzer(min_confidence=DEFAULT_YUNET_CONFIDENCE if conf is None else conf)
    an.detect_boxes(np.zeros((64, 64, 3), dtype=np.uint8))  # loads the weights; flips `available` on failure
    if not an.available:
        raise RuntimeError("YuNet is unavailable (OpenCV lacks FaceDetectorYN or the weights failed to load)")
    return an.detect_boxes


def _blazeface_detector_factory(device, conf):
    from pathlib import Path

    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import vision
    from mediapipe.tasks.python.core.base_options import BaseOptions

    from models.weights import download_weights, pretrained_model_path
    path = pretrained_model_path(BLAZEFACE_WEIGHTS_FILENAME)
    if not path.exists():
        download_weights(BLAZEFACE_WEIGHTS_URL, Path(path), BLAZEFACE_WEIGHTS_SHA256)
    detector = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(path)),
        min_detection_confidence=DEFAULT_BLAZEFACE_CONFIDENCE if conf is None else conf))

    def detect(img):
        h, w = img.shape[:2]
        scale = min(1.0, BLAZEFACE_MAX_SIDE / max(h, w))
        small = img if scale >= 1.0 else cv2.resize(
            img, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
        rgb = np.ascontiguousarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        out = []
        for d in result.detections:
            b = d.bounding_box
            x1, y1 = max(0.0, b.origin_x / scale), max(0.0, b.origin_y / scale)
            x2 = min(float(w), (b.origin_x + b.width) / scale)
            y2 = min(float(h), (b.origin_y + b.height) / scale)
            out.append((x1, y1, x2, y2, float(d.categories[0].score)))
        return out

    detect.close = detector.close
    return detect


def _sface_embedder_factory(device, threshold):
    """SFace embeddings of given reference boxes, aligned from YuNet's landmarks.

    SFace's aligner needs the 5 landmarks only a detector provides, so each
    reference box is matched (IoU >= 0.5) to a YuNet detection and a face YuNet
    does not find yields ``None``: that is the production path, and the coverage
    loss it causes is reported rather than hidden.
    """
    from analyzers.face_permissive import PermissiveFaceAnalyzer
    an = PermissiveFaceAnalyzer()
    if not an.available or not an._ensure_models():
        raise RuntimeError("SFace/YuNet are unavailable (OpenCV lacks FaceRecognizerSF or the weights failed to load)")

    def embed(img, bboxes):
        rows = an._detect(img)
        det = [(r[0], r[1], r[0] + r[2], r[1] + r[3]) for r in rows]
        out = [None] * len(bboxes)
        for i, j, _ in match_boxes(bboxes, det, IOU_MATCH):
            out[i] = an._embed(img, rows[j])
        return out
    return embed


def sample_detect_photos(conn, limit, seed):
    """Seeded, aggregate-stratified ``[(path, [ref bbox, ...])]``: ~70% photos with stored
    InsightFace faces, the rest photos with none (the false-positive pool)."""
    pos = list(conn.execute(
        "SELECT p.path, COALESCE(p.aggregate, 0) FROM photos p WHERE EXISTS ("
        "SELECT 1 FROM faces f WHERE f.photo_path = p.path AND f.embedding_model = ? "
        "AND f.bbox_x1 IS NOT NULL)", (REFERENCE_EMBEDDING_MODEL,)))
    if not pos:
        raise ValueError(f"no stored {REFERENCE_EMBEDDING_MODEL} faces: the InsightFace reference "
                         "exists only on a default-mode library")
    neg = list(conn.execute(
        "SELECT p.path, COALESCE(p.aggregate, 0) FROM photos p WHERE COALESCE(p.face_count, 0) = 0 "
        "AND NOT EXISTS (SELECT 1 FROM faces f WHERE f.photo_path = p.path)"))
    n_pos = round(limit * POSITIVE_SHARE)
    chosen = (stratified_sample_rows(pos, n_pos, seed)
              + stratified_sample_rows(neg, limit - n_pos, seed + 1))
    chosen = sorted(p for p, _ in chosen)
    refs = {}
    for chunk in _chunks(chosen):
        marks = ','.join('?' * len(chunk))
        for path, x1, y1, x2, y2 in conn.execute(
                "SELECT photo_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2 FROM faces "
                f"WHERE photo_path IN ({marks}) AND embedding_model = ? AND bbox_x1 IS NOT NULL "
                "ORDER BY face_index", chunk + [REFERENCE_EMBEDDING_MODEL]):
            refs.setdefault(path, []).append((x1, y1, x2, y2))
    return [(p, refs.get(p, [])) for p in chosen]


def score_face_detection(samples, loader, detectors):
    """Run every detector over every sample photo, loading each photo once.

    ``samples``: ``[(path, [ref bbox])]``; ``loader(path) -> BGR ndarray | None``;
    ``detectors``: ``{name: detect(img) -> [(x1, y1, x2, y2, conf)]}``. A photo
    whose reference boxes overrun the loaded frame by > 5% was analysed at another
    resolution and is skipped (counted), as is an unreadable one.
    """
    acc = {n: {'ref': [], 'neg_hits': [], 'neg_dets': [], 'pos_extra': [], 'lat': []} for n in detectors}
    skipped = {'unreadable': 0, 'size_mismatch': 0}
    for path, refs in samples:
        img = loader(path)
        if img is None:
            skipped['unreadable'] += 1
            continue
        h, w = img.shape[:2]
        if any(r[2] > w * 1.05 or r[3] > h * 1.05 for r in refs):
            skipped['size_mismatch'] += 1
            continue
        for name, detect in detectors.items():
            t0 = time.monotonic()
            dets = detect(img)
            acc[name]['lat'].append(time.monotonic() - t0)
            boxes = [d[:4] for d in dets]
            if not refs:
                acc[name]['neg_hits'].append(1.0 if dets else 0.0)
                acc[name]['neg_dets'].append(len(dets))
                continue
            matched = {i for i, _, _ in match_boxes(refs, boxes, IOU_MATCH)}
            for i, r in enumerate(refs):
                acc[name]['ref'].append((size_bucket(r, w, h), 1.0 if i in matched else 0.0))
            acc[name]['pos_extra'].append(len(boxes) - len(matched))
    return acc, skipped


def _rate(vals, seed):
    lo, hi = bootstrap_ci(vals, seed=seed)
    return {'rate': float(np.mean(vals)) if vals else None, 'ci_low': lo, 'ci_high': hi, 'n': len(vals)}


def summarize_face_detection(acc, seed):
    out = {}
    for name, a in acc.items():
        out[name] = {
            'match_rate': _rate([v for _, v in a['ref']], seed),
            'match_rate_by_size': {b: _rate([v for bk, v in a['ref'] if bk == b], seed) for b in SIZE_BUCKETS},
            'false_positive_rate': _rate(a['neg_hits'], seed),
            'mean_detections_per_empty_photo': float(np.mean(a['neg_dets'])) if a['neg_dets'] else None,
            'mean_extra_detections_per_face_photo': float(np.mean(a['pos_extra'])) if a['pos_extra'] else None,
            'mean_latency_s': float(np.mean(a['lat'])) if a['lat'] else None,
        }
    return out


def _build_face_runners(slot, names, device):
    """{name: callable} built from the registry (closed by the caller)."""
    runners = {}
    try:
        for name in names:
            cand = resolve_candidate(slot, name)
            runners[name] = cand.factory(device, cand.arg)
    except Exception:
        _close_all(runners)
        raise
    return runners


def _close_all(runners):
    for fn in runners.values():
        close = getattr(fn, 'close', None)
        if close:
            close()


def _evaluate_faces(db_path, slot, candidates, out, seed, limit, loader=None, device=None):
    names = list(candidates) if candidates else [c.name for c in registered_candidates(slot)]
    if out is None:
        out = os.path.join(DEFAULT_OUT_DIR, f"{slot}-{time.strftime('%Y%m%d-%H%M%S')}.json")
    loader = loader or _load_bgr
    device = device or 'cpu'
    conn = ro_connection(db_path)
    try:
        if slot == 'blink':
            report = _run_blink(conn, loader, seed, limit)
        elif slot == 'faces-detect':
            report = _run_faces_detect(conn, names, loader, device, seed, limit or DEFAULT_DETECT_PHOTOS)
        elif slot == 'faces-centroid':
            report = _run_faces_centroid(conn, names, loader, device, seed, limit or DEFAULT_RECOGNIZE_FACES)
        else:
            report = _run_faces_recognize(conn, names, loader, device, seed, limit or DEFAULT_RECOGNIZE_FACES)
    finally:
        conn.close()
    report.update({'slot': slot, 'db': os.path.abspath(db_path), 'seed': seed,
                   'reference': f'stored {REFERENCE_EMBEDDING_MODEL} faces (agreement, not ground truth)'})
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w') as f:
        json.dump(report, f, indent=2)
    logger.info("Report written to %s", out)
    return report


def _pct(v):
    return 'n/a' if v['rate'] is None else f"{v['rate']:.3f} [{v['ci_low']:.3f}, {v['ci_high']:.3f}]"


def _run_faces_detect(conn, names, loader, device, seed, limit):
    samples = sample_detect_photos(conn, limit, seed)
    n_ref = sum(len(r) for _, r in samples)
    logger.info("faces-detect: %d photos (%d with stored faces, %d reference faces)",
                len(samples), sum(1 for _, r in samples if r), n_ref)
    detectors = _build_face_runners('faces-detect', names, device)
    try:
        with measure() as run_stats:
            acc, skipped = score_face_detection(samples, loader, detectors)
    finally:
        _close_all(detectors)
    summary = summarize_face_detection(acc, seed)
    for name, r in summary.items():
        lat = r['mean_latency_s']
        logger.info("%-14s match %s  fp %s  lat %s s", name, _pct(r['match_rate']),
                    _pct(r['false_positive_rate']), 'n/a' if lat is None else f'{lat:.3f}')
        for b, v in r['match_rate_by_size'].items():
            logger.info("    %-5s %s (n=%d)", b, _pct(v), v['n'])
    return {'n_photos': len(samples), 'n_reference_faces': n_ref, 'skipped': skipped,
            'candidates': summary,
            # one shared pass over all detectors, so memory is for the whole run
            'peak_vram_gb_shared_run': run_stats.get('peak_vram_gb'),
            'peak_rss_gb_shared_run': run_stats.get('peak_rss_gb')}


def sample_recognize_faces(conn, limit, seed):
    """Seeded ``{path: [(bbox, person_id, named)]}`` capped at ``limit`` faces.

    Named persons (>= 3 faces) first, each contributing up to ``PER_PERSON_FACES``
    faces; unnamed InsightFace clusters top the sample up to the cap.
    """
    rows = list(conn.execute(
        "SELECT f.photo_path, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2, f.person_id, "
        "(p.name IS NOT NULL AND p.name != '') FROM faces f JOIN persons p ON p.id = f.person_id "
        "WHERE f.embedding_model = ? AND f.bbox_x1 IS NOT NULL ORDER BY f.id", (REFERENCE_EMBEDDING_MODEL,)))
    by_person = {}
    for path, x1, y1, x2, y2, pid, named in rows:
        by_person.setdefault(pid, {'named': bool(named), 'faces': []})['faces'].append((path, (x1, y1, x2, y2)))
    rng = random.Random(seed)
    groups = {True: [], False: []}
    for pid in sorted(by_person):
        if len(by_person[pid]['faces']) >= MIN_PERSON_FACES:
            groups[by_person[pid]['named']].append(pid)
    chosen, total = [], 0
    for named in (True, False):
        rng.shuffle(groups[named])
        for pid in groups[named]:
            if total >= limit:
                break
            faces = by_person[pid]['faces']
            take = rng.sample(faces, min(PER_PERSON_FACES, len(faces), limit - total))
            if len(take) < MIN_PERSON_FACES:
                continue
            chosen.append((pid, named, take))
            total += len(take)
    if not chosen:
        raise ValueError(f"no {REFERENCE_EMBEDDING_MODEL} persons with >= {MIN_PERSON_FACES} faces")
    photos = {}
    for pid, named, take in chosen:
        for path, bbox in take:
            photos.setdefault(path, []).append((bbox, pid, named))
    return photos


def collect_embeddings(photos, loader, embed):
    """(emb NxD L2-normalised, person ids, named flags, stats) for the faces ``embed`` could embed."""
    vecs, pids, named_flags = [], [], []
    n_req = n_unreadable = 0
    lat = []
    for path in sorted(photos):
        items = photos[path]
        n_req += len(items)
        img = loader(path)
        if img is None:
            n_unreadable += len(items)
            continue
        t0 = time.monotonic()
        result = embed(img, [b for b, _, _ in items])
        lat.append((time.monotonic() - t0) / len(items))
        for (_, pid, named), vec in zip(items, result):
            if vec is None:
                continue
            v = np.asarray(vec, dtype=np.float32).reshape(-1)
            n = float(np.linalg.norm(v))
            vecs.append(v / n if n > 0 else v)
            pids.append(pid)
            named_flags.append(named)
    emb = np.stack(vecs) if vecs else np.zeros((0, 0), np.float32)
    stats = {'n_requested': n_req, 'n_embedded': len(vecs), 'n_unreadable': n_unreadable,
             'mean_latency_per_face_s': float(np.mean(lat)) if lat else None}
    return emb, np.asarray(pids), np.asarray(named_flags, dtype=bool), stats


def _usable(labels, mask=None):
    """Mask keeping only faces whose person still has >= 2 embedded faces (within ``mask``)."""
    keep = np.ones(len(labels), bool) if mask is None else mask.copy()
    ids, counts = np.unique(labels[keep], return_counts=True)
    ok = set(ids[counts >= 2].tolist())
    return keep & np.array([x in ok for x in labels.tolist()], dtype=bool)


def _boot_f1(match, same, weights):
    """F1 at one threshold for a face-resampled population (``weights`` = multiplicities)."""
    w = weights.astype(np.float64)
    tp = float(w @ (match & same).astype(np.float64) @ w) / 2
    n_pred = float(w @ match.astype(np.float64) @ w) / 2
    n_same = float(w @ same.astype(np.float64) @ w) / 2
    if tp == 0 or n_pred == 0 or n_same == 0:
        return 0.0
    p, r = tp / n_pred, tp / n_same
    return 2 * p * r / (p + r)


def sweep_recognition(emb, labels, grid, seed, n_boot=200):
    """Pairwise same-person grid, best-F1 point with a face-bootstrap CI, 1-NN accuracy, ARI."""
    n = len(labels)
    if n < 3:
        return {'n_faces': n, 'grid': [], 'best': None}
    sim = emb @ emb.T
    rows = pairwise_f1_grid(sim, labels, grid)
    best = max(rows, key=lambda r: (r['f1'], -r['threshold']))
    same = labels[:, None] == labels[None, :]
    np.fill_diagonal(same, False)
    match = sim >= best['threshold']
    np.fill_diagonal(match, False)
    rng = np.random.default_rng(seed)
    f1s = [_boot_f1(match, same, np.bincount(rng.integers(0, n, n), minlength=n)) for _ in range(n_boot)]
    lo, hi = np.percentile(f1s, [2.5, 97.5])
    s2 = sim.copy()
    np.fill_diagonal(s2, -np.inf)
    nn_acc = float(np.mean(labels[np.argmax(s2, axis=1)] == labels))
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    from sklearn.metrics import adjusted_rand_score
    dist = np.clip(1.0 - sim, 0.0, None)
    np.fill_diagonal(dist, 0.0)
    clusters = fcluster(linkage(squareform(dist, checks=False), 'average'),
                        t=1.0 - best['threshold'], criterion='distance')
    return {'n_faces': n, 'n_persons': int(len(np.unique(labels))), 'grid': rows,
            'best': dict(best, f1_ci_low=float(lo), f1_ci_high=float(hi)),
            'nearest_neighbour_same_person_accuracy': nn_acc,
            'cluster_ari_at_best_threshold': float(adjusted_rand_score(labels, clusters)),
            'n_clusters_at_best_threshold': int(len(np.unique(clusters)))}


def _run_faces_recognize(conn, names, loader, device, seed, limit):
    photos = sample_recognize_faces(conn, limit, seed)
    logger.info("faces-recognize: %d reference faces over %d photos",
                sum(len(v) for v in photos.values()), len(photos))
    base_cache, results = {}, {}
    for name in names:
        cand = resolve_candidate('faces-recognize', name)
        base = name.partition('@')[0]
        grid = default_threshold_grid()
        if cand.arg is not None and round(cand.arg, 6) not in grid:
            grid = sorted(grid + [round(cand.arg, 6)])
        if base not in base_cache:
            embed = cand.factory(device, None)
            try:
                with measure() as run_stats:
                    collected = collect_embeddings(photos, loader, embed)
            finally:
                close = getattr(embed, 'close', None)
                if close:
                    close()
            base_cache[base] = collected + (run_stats,)
        emb, pids, named, stats, run_stats = base_cache[base]
        keep = _usable(pids)
        full = sweep_recognition(emb[keep], pids[keep], grid, seed)
        named_keep = _usable(pids, named)
        named_only = sweep_recognition(emb[named_keep], pids[named_keep], grid, seed)
        entry = dict(stats, peak_vram_gb=run_stats.get('peak_vram_gb'), peak_rss_gb=run_stats.get('peak_rss_gb'),
                     all_persons=full, named_persons_only=named_only)
        if cand.arg is not None and full['grid']:
            entry['operating_point'] = next(r for r in full['grid'] if r['threshold'] == round(cand.arg, 6))
        results[name] = entry
        b = full['best']
        if b:
            logger.info("%s: best threshold %.3f  F1 %.3f [%.3f, %.3f]  P %.3f R %.3f  (%d faces, %d persons)",
                        name, b['threshold'], b['f1'], b['f1_ci_low'], b['f1_ci_high'], b['precision'],
                        b['recall'], full['n_faces'], full['n_persons'])
    return {'n_reference_faces': sum(len(v) for v in photos.values()), 'n_photos': len(photos),
            'candidates': results}


# ---------------------------------------------------------------------------
# faces-centroid slot: the quantities merge_threshold / auto_merge_distance_percent gate
#
# merge_threshold compares a cluster MEAN with a person CENTROID, so a face-to-face
# F1 sweep (faces-recognize) calibrates the wrong object. Here each reference person
# with >= 4 faces is split into two seeded random halves and each half becomes a unit
# centroid: same-person pairs are the two halves of one person, different-person pairs
# are half A of one person against half B of another.
# auto_merge_distance_percent becomes HDBSCAN's cluster_selection_epsilon (euclidean
# sqrt(2 * d) on unit vectors, i.e. a face-to-face cosine DISTANCE d); the proxy
# measured is the share of different-person face pairs within distance d.
# ---------------------------------------------------------------------------

CENTROID_MIN_FACES = 4
CENTROID_ARCFACE_REFERENCE_THRESHOLD = 0.6      # shipped ArcFace merge_threshold
CENTROID_ARCFACE_REFERENCE_DISTANCE = 0.15      # shipped auto_merge_distance_percent / 100


def centroid_threshold_grid():
    """Cosine thresholds 0.30 .. 0.80 step 0.025 (21 points)."""
    return [round(0.30 + 0.025 * i, 3) for i in range(21)]


def centroid_distance_grid():
    """Cosine distances 0.05 .. 0.80 step 0.025 (31 points)."""
    return [round(0.05 + 0.025 * i, 3) for i in range(31)]


def half_centroids(emb, labels, seed):
    """(A, B, person ids): unit centroids of two random halves of each person with >= 4 faces."""
    rng = np.random.default_rng(seed)
    a_rows, b_rows, ids = [], [], []
    for pid in sorted(np.unique(labels).tolist()):
        idx = np.flatnonzero(labels == pid)
        if len(idx) < CENTROID_MIN_FACES:
            continue
        idx = rng.permutation(idx)
        h = len(idx) // 2
        pair = []
        for part in (idx[:h], idx[h:]):
            c = emb[part].mean(0)
            n = float(np.linalg.norm(c))
            pair.append(c / n if n > 0 else c)
        a_rows.append(pair[0])
        b_rows.append(pair[1])
        ids.append(pid)
    if not ids:
        return np.zeros((0, 0), np.float32), np.zeros((0, 0), np.float32), []
    return np.stack(a_rows), np.stack(b_rows), ids


def centroid_sweep(emb, labels, grid, seed):
    """Per threshold: same-person recall, different-person pairs above it, precision, F1, false-merge rate."""
    A, B, ids = half_centroids(emb, labels, seed)
    n = len(ids)
    if n < 2:
        return {'n_persons': n, 'grid': []}
    S = A @ B.T
    same = np.diag(S)
    diff = S[~np.eye(n, dtype=bool)]
    rows = []
    for t in grid:
        tp = int((same >= t).sum())
        fp = int((diff >= t).sum())
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / n
        rows.append({'threshold': round(float(t), 6), 'same_recall': r, 'diff_pairs_above': fp,
                     'false_merge_rate': fp / len(diff), 'precision': p,
                     'f1': 2 * p * r / (p + r) if (p + r) else 0.0})
    return {'n_persons': n, 'n_same_pairs': n, 'n_diff_pairs': int(len(diff)), 'grid': rows,
            'same_p5': float(np.percentile(same, 5)), 'same_median': float(np.median(same)),
            'diff_p99': float(np.percentile(diff, 99)), 'diff_max': float(diff.max())}


def face_distance_sweep(emb, labels, grid):
    """Per cosine distance d: share of different-person face pairs within d, and same-person recall."""
    sim = emb @ emb.T
    iu, ju = np.triu_indices(len(labels), k=1)
    s = sim[iu, ju]
    same = labels[iu] == labels[ju]
    n_same, n_diff = int(same.sum()), int((~same).sum())
    if not n_same or not n_diff:
        return []
    return [{'distance': round(float(d), 6), 'false_merge_rate': float((s[~same] >= 1 - d).sum()) / n_diff,
             'diff_pairs_within': int((s[~same] >= 1 - d).sum()),
             'same_recall': float((s[same] >= 1 - d).sum()) / n_same} for d in grid]


def choose_centroid_threshold(sface_rows, arcface_rows, ref=CENTROID_ARCFACE_REFERENCE_THRESHOLD):
    """Pre-registered rule: smallest grid threshold whose SFace false-merge rate <= ArcFace's at ``ref``.

    Thresholds are scanned ascending, so the first hit already has the highest recall of any
    qualifying threshold (recall is non-increasing in the threshold); a tie in rate never
    needs a separate break.
    """
    target = next(r for r in arcface_rows if abs(r['threshold'] - ref) < 1e-9)['false_merge_rate']
    for r in sorted(sface_rows, key=lambda r: r['threshold']):
        if r['false_merge_rate'] <= target:
            return {'threshold': r['threshold'], 'arcface_target_rate': target, 'row': r}
    return {'threshold': None, 'arcface_target_rate': target, 'row': None}


def choose_auto_merge_distance(sface_rows, arcface_rows, ref=CENTROID_ARCFACE_REFERENCE_DISTANCE):
    """Largest SFace distance whose false-merge rate is <= ArcFace's at ``ref`` (same rate, most recall)."""
    target = next(r for r in arcface_rows if abs(r['distance'] - ref) < 1e-9)['false_merge_rate']
    ok = [r for r in sface_rows if r['false_merge_rate'] <= target]
    best = max(ok, key=lambda r: r['distance']) if ok else None
    return {'distance': best['distance'] if best else None, 'arcface_target_rate': target, 'row': best}


def stored_arcface(conn, keys):
    """Stored 512-d ArcFace vectors (unit) for ``[(path, bbox)]`` keys, in order; None where missing."""
    out = []
    for path, (x1, y1, x2, y2) in keys:
        row = conn.execute(
            "SELECT embedding FROM faces WHERE photo_path = ? AND embedding_model = ? "
            "AND bbox_x1 = ? AND bbox_y1 = ? AND bbox_x2 = ? AND bbox_y2 = ? LIMIT 1",
            (path, REFERENCE_EMBEDDING_MODEL, x1, y1, x2, y2)).fetchone()
        if not row or row[0] is None:
            out.append(None)
            continue
        v = np.frombuffer(row[0], dtype=np.float32).copy()
        n = float(np.linalg.norm(v))
        out.append(v / n if n > 0 else v)
    return out


CENTROID_N_BOOT = 1000


def split_persons(labels, seed):
    """Seeded 50/50 split of face indices BY PERSON, stratified by the person's face-count tercile.

    Never by face: a person with faces on both sides would leak identity into the held-out half.
    """
    labels = np.asarray(labels)
    ids, counts = np.unique(labels, return_counts=True)
    order = np.argsort(counts, kind='stable')
    tercile = {}
    for rank, j in enumerate(order):
        tercile[ids[j].item()] = min(2, rank * 3 // max(1, len(ids)))
    strata = [tercile[x] for x in labels.tolist()]
    return split_halves(len(labels), seed, strata=strata, groups=labels.tolist())


def centroid_bootstrap(emb, labels, threshold, seed, n_boot=CENTROID_N_BOOT):
    """Person-level bootstrap 95% CIs of half-centroid ``same_recall`` and ``false_merge_rate`` at ``threshold``."""
    A, B, ids = half_centroids(emb, labels, seed)
    n = len(ids)
    if n < 2:
        return {'n_persons': n, 'n_boot': n_boot}
    S = A @ B.T
    same = np.diag(S) >= threshold
    rng = np.random.default_rng(seed + 13)
    recalls, rates = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        distinct = idx[:, None] != idx[None, :]
        if not distinct.any():
            continue
        recalls.append(float(same[idx].mean()))
        rates.append(float(((S[np.ix_(idx, idx)] >= threshold) & distinct).sum()) / float(distinct.sum()))
    out = {'n_persons': n, 'n_boot': n_boot}
    for key, vals in (('same_recall', recalls), ('false_merge_rate', rates)):
        if vals:
            lo, hi = np.percentile(vals, [2.5, 97.5])
            out[key] = {'ci_low': float(lo), 'ci_high': float(hi)}
    return out


def _safe_choose(chooser, rows, ref_rows):
    try:
        return chooser(rows, ref_rows)
    except StopIteration:  # the reference grid has no row at the reference point (empty half)
        return None


def centroid_heldout(sface, arcface, labels, seed, n_boot=CENTROID_N_BOOT):
    """Choose the merge threshold / auto-merge distance on person half A, report them on person half B.

    ``sface`` / ``arcface`` are ``(N, D)`` embeddings aligned with ``labels``. The choice uses ONLY A's
    rows (ArcFace's target rate at its reference threshold is also taken from A); B is scored at the
    chosen point afterwards, with a person-level bootstrap CI.
    """
    labels = np.asarray(labels)
    a, b = split_persons(labels, seed)
    sweeps = {}
    for part, idx in (('A', a), ('B', b)):
        sweeps[part] = {name: (centroid_sweep(e[idx], labels[idx], centroid_threshold_grid(), seed)['grid'],
                               face_distance_sweep(e[idx], labels[idx], centroid_distance_grid()))
                        for name, e in (('sface', sface), ('arcface', arcface))}
    thr = _safe_choose(choose_centroid_threshold, sweeps['A']['sface'][0], sweeps['A']['arcface'][0])
    dist = _safe_choose(choose_auto_merge_distance, sweeps['A']['sface'][1], sweeps['A']['arcface'][1])
    persons_a, persons_b = np.unique(labels[a]), np.unique(labels[b])
    assert not set(persons_a.tolist()) & set(persons_b.tolist())
    selection = {'split': 'A', 'n_faces': int(len(a)), 'n_persons': int(len(persons_a)), 'seed': seed,
                 'chosen': {'merge_threshold': thr, 'auto_merge_distance': dist}}
    held = {'split': 'B', 'n_faces': int(len(b)), 'n_persons': int(len(persons_b)), 'n_boot': n_boot,
            'metric': 'same_recall and false_merge_rate at the threshold chosen on A (half-centroid pairs); '
                      'auto-merge: false_merge_rate / same_recall of face pairs at the chosen distance'}
    if thr and thr['threshold'] is not None:
        t = thr['threshold']
        row = next((r for r in sweeps['B']['sface'][0] if abs(r['threshold'] - t) < 1e-9), None)
        arc_ref = next((r for r in sweeps['B']['arcface'][0]
                        if abs(r['threshold'] - CENTROID_ARCFACE_REFERENCE_THRESHOLD) < 1e-9), None)
        held['merge_threshold'] = {'threshold': t, 'row': row, 'arcface_reference_row': arc_ref,
                                   'ci': centroid_bootstrap(sface[b], labels[b], t, seed, n_boot)}
    else:
        held['merge_threshold'] = None
    if dist and dist['distance'] is not None:
        d = dist['distance']
        held['auto_merge_distance'] = {
            'distance': d, 'row': next((r for r in sweeps['B']['sface'][1] if abs(r['distance'] - d) < 1e-9), None)}
    else:
        held['auto_merge_distance'] = None
    return selection, held


def _run_faces_centroid(conn, names, loader, device, seed, limit):
    photos = sample_recognize_faces(conn, limit, seed)
    cand = resolve_candidate('faces-recognize', 'sface')
    keys = []

    def keyed_loader(path):
        keyed_loader.path = path
        return loader(path)

    base_embed = cand.factory(device, None)

    def embed(img, boxes):
        result = base_embed(img, boxes)
        keys.extend((keyed_loader.path, b) for b, v in zip(boxes, result) if v is not None)
        return result

    try:
        emb, pids, named, stats = collect_embeddings(photos, keyed_loader, embed)
    finally:
        close = getattr(base_embed, 'close', None)
        if close:
            close()
    arc = stored_arcface(conn, keys)
    have = np.array([v is not None for v in arc], dtype=bool)
    spaces = {'sface': emb, 'arcface': np.stack([v for v in arc if v is not None]) if have.any() else emb[:0]}
    results = {}
    held_inputs = None
    for scope, mask in (('all_persons', np.ones(len(pids), bool)), ('named_persons_only', named)):
        m = mask & have
        keep = _usable(pids, m)
        scope_res = {}
        for model, space in spaces.items():
            full = np.zeros((len(pids), space.shape[1]), np.float32) if len(space) else space
            if model == 'arcface':
                full[have] = space
            else:
                full = space
            e, lab = full[keep], pids[keep]
            scope_res[model] = {
                'n_faces': int(keep.sum()),
                'centroid': centroid_sweep(e, lab, centroid_threshold_grid(), seed),
                'face_distance': face_distance_sweep(e, lab, centroid_distance_grid())}
            if scope == 'all_persons':
                held_inputs = held_inputs or {'labels': lab}
                held_inputs[model] = e
        results[scope] = scope_res
    allres = results['all_persons']
    chosen = {
        'merge_threshold': choose_centroid_threshold(allres['sface']['centroid']['grid'],
                                                      allres['arcface']['centroid']['grid']),
        'auto_merge_distance': choose_auto_merge_distance(allres['sface']['face_distance'],
                                                           allres['arcface']['face_distance'])}
    for k, v in chosen.items():
        logger.info("faces-centroid %s (full sample, selection-biased): sface=%s (ArcFace target rate %.5f)", k,
                    v.get('threshold', v.get('distance')), v['arcface_target_rate'])
    selection = held = None
    if held_inputs and len(held_inputs['labels']) and len(held_inputs.get('arcface', ())):
        selection, held = centroid_heldout(held_inputs['sface'], held_inputs['arcface'], held_inputs['labels'], seed)
        logger.info("faces-centroid held-out (split B): %s", held.get('merge_threshold'))
    return dict(stats, n_reference_faces=sum(len(v) for v in photos.values()), n_photos=len(photos),
                results=results, selection=selection, report=held,
                full_sample_selection_biased={
                    'note': 'thresholds chosen AND scored on the same persons (optimistic); kept so D34 is reproducible',
                    'chosen': chosen})


# ---------------------------------------------------------------------------
# blink slot: MediaPipe eyeBlink blendshapes vs the stored InsightFace is_blink
# ---------------------------------------------------------------------------

def blink_threshold_grid():
    """0.30 .. 0.80 step 0.05 (11 points)."""
    return [round(0.30 + 0.05 * i, 2) for i in range(11)]


def sample_blink_faces(conn, limit, seed):
    """``[(path, bbox, label)]``: every single-face photo with ``is_blink = 1`` (capped by
    ``limit`` when given) plus an equal number of ``is_blink = 0`` ones, aggregate-stratified.

    The faces table stores no per-face blink label, so the reference is the photo-level
    ``is_blink`` and only photos with exactly one stored face are usable.
    """
    rows = list(conn.execute(
        "SELECT p.path, p.is_blink, COALESCE(p.aggregate, 0), f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2 "
        "FROM photos p JOIN faces f ON f.photo_path = p.path "
        "WHERE p.is_blink IN (0, 1) AND f.embedding_model = ? AND f.bbox_x1 IS NOT NULL "
        "AND (SELECT COUNT(*) FROM faces g WHERE g.photo_path = p.path AND g.embedding_model = ?) = 1 "
        "ORDER BY p.path", (REFERENCE_EMBEDDING_MODEL, REFERENCE_EMBEDDING_MODEL)))
    if not rows:
        raise ValueError(f"no single-face photos with {REFERENCE_EMBEDDING_MODEL} faces and a stored is_blink")
    box = {r[0]: (r[3], r[4], r[5], r[6]) for r in rows}
    pos = [(r[0], r[2]) for r in rows if r[1] == 1]
    neg = [(r[0], r[2]) for r in rows if r[1] == 0]
    n_pos = min(len(pos), limit) if limit else len(pos)
    n_neg = min(len(neg), n_pos)
    chosen = ([(p, 1) for p, _ in stratified_sample_rows(pos, n_pos, seed)]
              + [(p, 0) for p, _ in stratified_sample_rows(neg, n_neg, seed + 1)])
    return [(p, box[p], lab) for p, lab in sorted(chosen)]


def blink_grid(scores, labels, grid):
    """Precision / recall / F1 of "score >= t" against ``labels`` for each t (unknowns excluded upstream)."""
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=bool)
    rows = []
    for t in grid:
        pred = scores >= t
        tp = int(np.sum(pred & labels))
        fp = int(np.sum(pred & ~labels))
        fn = int(np.sum(~pred & labels))
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        rows.append({'threshold': t, 'precision': p, 'recall': r,
                     'f1': 2 * p * r / (p + r) if p + r else 0.0, 'tp': tp, 'fp': fp, 'fn': fn})
    return rows


def sweep_blink(scores, labels, grid, seed, n_boot=1000):
    """Grid, best-F1 row (ties go to the lower threshold) and bootstrap CIs of its F1 and of
    the best threshold itself (the argmax re-taken on each resample)."""
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=bool)
    n = len(labels)
    if n == 0 or not labels.any():
        return {'n': n, 'grid': [], 'best': None}
    rows = blink_grid(scores, labels, grid)
    best = max(rows, key=lambda r: (r['f1'], -r['threshold']))
    rng = np.random.default_rng(seed)
    f1_at_best, argmax_t = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        if not labels[idx].any():
            continue
        br = blink_grid(scores[idx], labels[idx], grid)
        f1_at_best.append(next(r['f1'] for r in br if r['threshold'] == best['threshold']))
        argmax_t.append(max(br, key=lambda r: (r['f1'], -r['threshold']))['threshold'])
    lo, hi = np.percentile(f1_at_best, [2.5, 97.5])
    tlo, thi = np.percentile(argmax_t, [2.5, 97.5])
    return {'n': n, 'n_positive': int(labels.sum()), 'base_rate': float(labels.mean()), 'grid': rows,
            'best': dict(best, f1_ci_low=float(lo), f1_ci_high=float(hi),
                         threshold_ci_low=float(tlo), threshold_ci_high=float(thi))}


POSE_CUTOFFS = (None, 45, 40, 35, 30, 25, 20)
POSE_MAX_GATED_SHARE = 0.15
BLINK_N_BOOT = 1000
SHIPPED_BLINK_THRESHOLD = 0.55

# Written BEFORE the first measurement run (issue #185, item 6/7). Verbatim in every report.
PRE_REGISTERED_POSE_RULE = (
    "Faces are split 50/50 by seed, stratified by label (split A selects, split B reports; B is never "
    "seen during selection). At the blink threshold t_A chosen on A (maximum library-weighted F1 on A, "
    "ties to the larger threshold), where gated faces count as unflagged (a gated true positive is a lost "
    "recall), choose among the pose cutoffs {none, 45, 40, 35, 30, 25, 20} degrees (applied to "
    "max(|yaw|, |pitch|)) the cutoff that maximises library-weighted F1 on A, provided it gates <= 15% of "
    "the meshed faces of A; ties go to the larger cutoff (none is the largest). Adopt that cutoff only if on "
    "B it also gates <= 15% of meshed faces AND its library-weighted F1 on B is strictly greater than the "
    "ungated library-weighted F1 on B; otherwise ship no gate and record the null result. Library weighting: "
    "negatives are reweighted by (n_pos/n_neg of the split) * ((1 - base_rate)/base_rate), base_rate read "
    "from the DB (single-face photos with a stored is_blink).")
PRE_REGISTERED_THRESHOLD_RULE = (
    "The blink threshold is chosen on split A as the grid point with the highest library-weighted F1 "
    "(ties to the larger threshold) and reported on split B with a seeded bootstrap CI over B faces.")


def library_blink_rate(conn):
    """``(n_positive, n_total, rate)`` over single-face photos with a stored ``is_blink`` (the sample's population)."""
    n_pos, n_tot = conn.execute(
        "SELECT COALESCE(SUM(p.is_blink), 0), COUNT(*) FROM photos p JOIN faces f ON f.photo_path = p.path "
        "WHERE p.is_blink IN (0, 1) AND f.embedding_model = ? AND f.bbox_x1 IS NOT NULL "
        "AND (SELECT COUNT(*) FROM faces g WHERE g.photo_path = p.path AND g.embedding_model = ?) = 1",
        (REFERENCE_EMBEDDING_MODEL, REFERENCE_EMBEDDING_MODEL)).fetchone()
    return int(n_pos), int(n_tot), (n_pos / n_tot if n_tot else None)


def weighted_prf(tp, fp, fn, n_pos, n_neg, base_rate):
    """Library-weighted ``(precision, recall, f1)``: false positives scaled by the negative weight, or None."""
    if not n_pos or not n_neg or not base_rate or not 0 < base_rate < 1:
        return None
    w = (n_pos / n_neg) * ((1 - base_rate) / base_rate)
    fpw = fp * w
    p = tp / (tp + fpw) if tp + fpw else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def _counts(pred, labels):
    return (int(np.sum(pred & labels)), int(np.sum(pred & ~labels)), int(np.sum(~pred & labels)))


def blink_weighted_grid(scores, labels, grid, base_rate, gate_mask=None):
    """Per threshold: unweighted and library-weighted precision / recall / F1 of ``score >= t``.

    ``gate_mask`` (bool per face, True = gated) forces the prediction to "not blinking".
    """
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=bool)
    n_pos, n_neg = int(labels.sum()), int((~labels).sum())
    rows = []
    for t in grid:
        pred = scores >= t
        if gate_mask is not None:
            pred = pred & ~np.asarray(gate_mask, dtype=bool)
        tp, fp, fn = _counts(pred, labels)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        wp = weighted_prf(tp, fp, fn, n_pos, n_neg, base_rate)
        rows.append({'threshold': t, 'precision': p, 'recall': r,
                     'f1': 2 * p * r / (p + r) if p + r else 0.0, 'tp': tp, 'fp': fp, 'fn': fn,
                     'weighted_precision': None if wp is None else wp[0],
                     'weighted_recall': None if wp is None else wp[1],
                     'weighted_f1': None if wp is None else wp[2]})
    return rows


def choose_blink_threshold(scores, labels, grid, base_rate):
    """Pre-registered: highest library-weighted F1 on the given rows, ties to the larger threshold.

    Falls back to the unweighted F1 when no base rate is available. None when ``labels`` has no positive.
    """
    labels = np.asarray(labels, dtype=bool)
    if not len(labels) or not labels.any():
        return None
    rows = blink_weighted_grid(scores, labels, grid, base_rate)
    key = 'weighted_f1' if rows[0]['weighted_f1'] is not None else 'f1'
    return max(rows, key=lambda r: (r[key], r['threshold']))


def blink_bootstrap_ci(scores, labels, threshold, base_rate, seed, n_boot=BLINK_N_BOOT, gate_mask=None):
    """Percentile 95% CIs of F1 / precision / recall / weighted F1 at ``threshold`` over resampled faces."""
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=bool)
    n = len(labels)
    out = {'n_boot': n_boot}
    if n == 0 or not labels.any():
        return out
    mask = np.zeros(n, bool) if gate_mask is None else np.asarray(gate_mask, dtype=bool)
    pred_all = (scores >= threshold) & ~mask
    rng = np.random.default_rng(seed + 11)
    acc = {'f1': [], 'precision': [], 'recall': [], 'weighted_f1': []}
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        lab, pred = labels[idx], pred_all[idx]
        if not lab.any():
            continue
        tp, fp, fn = _counts(pred, lab)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        acc['precision'].append(p)
        acc['recall'].append(r)
        acc['f1'].append(2 * p * r / (p + r) if p + r else 0.0)
        wp = weighted_prf(tp, fp, fn, int(lab.sum()), int((~lab).sum()), base_rate)
        if wp is not None:
            acc['weighted_f1'].append(wp[2])
    for k, vals in acc.items():
        if vals:
            lo, hi = np.percentile(vals, [2.5, 97.5])
            out[k] = {'ci_low': float(lo), 'ci_high': float(hi)}
    return out


def pose_gate_table(scores, labels, poses, threshold, base_rate, cutoffs=POSE_CUTOFFS):
    """Per cutoff: gated share of faces and the metrics at ``threshold`` with gated faces unflagged.

    ``poses`` is the per-face ``max(|yaw|, |pitch|)`` in degrees (NaN = no pose, never gated).
    """
    poses = np.asarray(poses, dtype=float)
    labels = np.asarray(labels, dtype=bool)
    n = len(labels)
    table = []
    for c in cutoffs:
        gated = np.zeros(n, bool) if c is None else np.nan_to_num(poses, nan=-1.0) > c
        row = blink_weighted_grid(scores, labels, [threshold], base_rate, gate_mask=gated)[0]
        row.pop('threshold')
        table.append(dict(row, cutoff=c, n_gated=int(gated.sum()), gated_share=float(gated.mean()) if n else 0.0))
    return table


def _cutoff_rank(c):
    return float('inf') if c is None else float(c)


def choose_pose_cutoff(table_a, table_b, max_share=POSE_MAX_GATED_SHARE):
    """Apply :data:`PRE_REGISTERED_POSE_RULE`: select on A's table, confirm on B's."""
    def value(r):
        return r['weighted_f1'] if r['weighted_f1'] is not None else r['f1']

    eligible = [r for r in table_a if r['gated_share'] <= max_share]
    best = max(eligible, key=lambda r: (value(r), _cutoff_rank(r['cutoff'])))
    cutoff = best['cutoff']
    b_by = {r['cutoff']: r for r in table_b}
    b_best, b_none = b_by[cutoff], b_by[None]
    adopt = (cutoff is not None and b_best['gated_share'] <= max_share and value(b_best) > value(b_none))
    return {'selected_on_a': cutoff, 'adopt': bool(adopt), 'cutoff': cutoff if adopt else None,
            'b_weighted_f1_selected': value(b_best), 'b_weighted_f1_ungated': value(b_none),
            'b_gated_share_selected': b_best['gated_share'],
            'verdict': (f"adopt blink_pose_gate_deg={cutoff}" if adopt else "ship no gate (null result)")}


def _blink_scorer_factory():
    """``score(img, bbox) -> (left, right, yaw, pitch) | None`` through PermissiveFaceAnalyzer's own crop + mesh path.

    ``yaw`` / ``pitch`` are degrees, or None when the bundle returned no transformation matrix.
    """
    from analyzers.face_permissive import PermissiveFaceAnalyzer
    an = PermissiveFaceAnalyzer(enable_blendshapes=True)

    def score(img, bbox):
        res = an._mesh_analysis_pose(img, np.asarray(bbox).astype(int))
        if res is None:
            return None
        names = res[2]
        pose = res[4] if len(res) > 4 else None
        yaw, pitch = (None, None) if pose is None else (float(pose[0]), float(pose[1]))
        return float(names['eyeBlinkLeft']), float(names['eyeBlinkRight']), yaw, pitch
    return score


def blink_heldout(mx, labels, poses, base_rate, seed, grid):
    """Split-A selection / split-B report for the max-blink score and the pose-gate cutoff."""
    labels = np.asarray(labels, dtype=bool)
    mx = np.asarray(mx, dtype=float)
    a, b = split_halves(len(labels), seed, strata=labels.astype(int).tolist())
    out = {'seed': seed, 'n_a': int(len(a)), 'n_b': int(len(b)), 'base_rate': base_rate,
           'rule_threshold': PRE_REGISTERED_THRESHOLD_RULE, 'rule_pose': PRE_REGISTERED_POSE_RULE}
    chosen = choose_blink_threshold(mx[a], labels[a], grid, base_rate)
    out['selection'] = {'split': 'A', 'n': int(len(a)), 'seed': seed,
                        'chosen': None if chosen is None else {'threshold': chosen['threshold'], 'row': chosen}}
    if chosen is None or not len(b) or not labels[b].any():
        out['report'] = {'split': 'B', 'n': int(len(b)), 'metric': None}
        out['pose_gate'] = None
        return out
    t = chosen['threshold']
    out['report'] = {
        'split': 'B', 'n': int(len(b)), 'n_positive': int(labels[b].sum()), 'threshold': t,
        'metric': blink_weighted_grid(mx[b], labels[b], [t], base_rate)[0],
        'at_shipped_threshold': blink_weighted_grid(mx[b], labels[b], [SHIPPED_BLINK_THRESHOLD], base_rate)[0],
        'ci': blink_bootstrap_ci(mx[b], labels[b], t, base_rate, seed),
        'n_boot': BLINK_N_BOOT}
    poses = np.asarray(poses, dtype=float)
    out['pose_gate'] = {
        'n_with_pose': int(np.isfinite(poses).sum()),
        'threshold': t,
        'split_a': pose_gate_table(mx[a], labels[a], poses[a], t, base_rate),
        'split_b': pose_gate_table(mx[b], labels[b], poses[b], t, base_rate),
        'shipped_threshold_split_b': pose_gate_table(mx[b], labels[b], poses[b], SHIPPED_BLINK_THRESHOLD, base_rate)}
    out['pose_gate']['decision'] = choose_pose_cutoff(out['pose_gate']['split_a'], out['pose_gate']['split_b'])
    return out


def _run_blink(conn, loader, seed, limit, scorer=None):
    samples = sample_blink_faces(conn, limit, seed)
    scorer = scorer or _blink_scorer_factory()
    logger.info("blink: %d faces (%d blink-positive)", len(samples), sum(s[2] for s in samples))
    mx, mean, labels, faces = [], [], [], []
    unknown = unreadable = 0
    for i, (path, bbox, label) in enumerate(samples):
        if i % 50 == 0:
            logger.info("blink: %d/%d", i, len(samples))
        img = loader(path)
        if img is None:
            unreadable += 1
            continue
        res = scorer(img, bbox)
        if res is None:
            unknown += 1
            continue
        yaw, pitch = (res[2], res[3]) if len(res) >= 4 else (None, None)
        mx.append(max(res[:2]))
        mean.append(float(np.mean(res[:2])))
        labels.append(label)
        faces.append({'path': path, 'label': label, 'max_blink': mx[-1], 'mean_blink': mean[-1],
                      'yaw': yaw, 'pitch': pitch})
    grid = blink_threshold_grid()
    n_pos_lib, n_lib, rate = library_blink_rate(conn)
    poses = [float('nan') if f['yaw'] is None or f['pitch'] is None else max(abs(f['yaw']), abs(f['pitch']))
             for f in faces]
    out = {'n_sampled': len(samples), 'n_mesh_failed': unknown, 'n_unreadable': unreadable,
           'sampling': 'all blink-positive single-face photos (capped by limit) + equal negatives, stratified',
           'reference_note': 'photo-level is_blink on single-face photos (faces table has no blink label)',
           'library': {'n_positive': n_pos_lib, 'n_single_face': n_lib, 'blink_rate': rate},
           'faces': faces,
           'held_out': blink_heldout(mx, labels, poses, rate, seed, grid) if labels else None,
           'full_sample_selection_biased': {
               'note': 'threshold chosen AND scored on the same faces (optimistic); kept so D33 is reproducible',
               'max_blink': sweep_blink(mx, labels, grid, seed),
               'mean_blink': sweep_blink(mean, labels, grid, seed)}}
    biased = out['full_sample_selection_biased']
    for key in ('max_blink', 'mean_blink'):
        for r in biased[key]['grid']:
            logger.info("%s t=%.2f P %.3f R %.3f F1 %.3f", key, r['threshold'], r['precision'], r['recall'], r['f1'])
    held = out['held_out']
    if held and held['pose_gate']:
        logger.info("pose gate: %s", held['pose_gate']['decision']['verdict'])
    return out


def _register_face_candidates():
    register_candidate('faces-detect', 'yunet', _yunet_detector_factory)
    register_candidate('faces-detect', 'blazeface', _blazeface_detector_factory)
    register_candidate('faces-recognize', 'sface', _sface_embedder_factory)


_register_face_candidates()
