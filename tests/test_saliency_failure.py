"""Issue #184: a failed saliency run stores NULL (or keeps the stored value), never a neutral score.

Covers the three writers (``_pass_saliency`` + restricted save, ``--recompute-saliency``'s
flush) and the aggregate reader that redistributes a NULL metric's weight.
"""

import pytest
from PIL import Image

pytest.importorskip("imagehash")
pytest.importorskip("cv2")

from db import get_connection  # noqa: E402
from tests import test_single_pass_preserves as _sp  # noqa: E402
from processing.multi_pass import (  # noqa: E402
    SALIENCY_FAILED_KEY, SALIENCY_PASS_COLUMNS,
)

_NO_SUBJECT = {'subject_sharpness': None, 'subject_prominence': 0.0, 'subject_placement': None,
               'bg_separation': None, 'subject_bbox': None}
_COLS = ('subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
         'subject_bbox')
_FAILED = {k: None for k in _COLS}
_SALIENCY, _images, _persist, _processor = _sp._SALIENCY, _sp._images, _sp._persist, _sp._processor
seeded = _sp.seeded  # the fixture, shared rather than copied


class _Scorer:
    def __init__(self, scores):
        self.scores = scores

    def score_batch(self, pil, cv):
        return self.scores[:len(pil)]


def _saliency_row(db, path):
    with get_connection(db, row_factory=True) as conn:
        return dict(conn.execute(
            f"SELECT {', '.join(_COLS)} FROM photos WHERE path=?", (path,)).fetchone())


def _run_pass(proc, path, scores):
    results = {path: {}}
    proc._pass_saliency(_Scorer(scores), {path: {'pil': Image.new('RGB', (8, 8))}}, results)
    return results


def test_failed_photo_is_flagged_and_its_five_keys_stay_unset(seeded):
    path, facet, _ = seeded
    results = _run_pass(_processor(facet, [['saliency']]), path, [dict(_FAILED)])
    assert results[path] == {SALIENCY_FAILED_KEY: True}
    assert not (SALIENCY_PASS_COLUMNS & results[path].keys())


def test_successful_photo_keeps_its_values_including_a_legit_no_subject_result(seeded):
    path, facet, _ = seeded
    results = _run_pass(_processor(facet, [['saliency']]), path, [dict(_NO_SUBJECT)])
    assert SALIENCY_FAILED_KEY not in results[path]
    assert results[path]['subject_sharpness'] is None
    assert results[path]['subject_prominence'] == 0.0
    assert results[path]['subject_bbox'] is None


def test_restricted_save_keeps_stored_values_over_a_failure(seeded):
    path, facet, db = seeded
    proc = _processor(facet, [['saliency']])
    _persist(proc, {path: dict(_SALIENCY)}, _images(path))
    before = _saliency_row(db, path)
    assert before['subject_sharpness'] == 7.0

    results = _run_pass(proc, path, [dict(_FAILED)])
    _persist(proc, results, _images(path))

    assert _saliency_row(db, path) == before


def test_full_save_stores_null_over_a_failure_never_a_neutral_score(seeded):
    """A full rescan (restricted=False, e.g. --force) is the one writer that overwrites.

    The photo carries stored saliency; the rescan's saliency fails, so the full
    UPSERT writes the honest NULL in all five columns -- never the old 5.0.
    """
    path, facet, db = seeded
    _persist(_processor(facet, [['saliency']]), {path: dict(_SALIENCY)}, _images(path))
    assert _saliency_row(db, path)['subject_sharpness'] == 7.0

    full = _processor(facet, [['saliency']], restricted=False)
    results = _run_pass(full, path, [dict(_FAILED)])
    assert results[path] == {SALIENCY_FAILED_KEY: True}
    full._save_results(results, _images(path))

    assert _saliency_row(db, path) == _FAILED


def test_a_photo_that_never_had_saliency_stays_null_after_a_failure(seeded):
    path, facet, db = seeded
    proc = _processor(facet, [['saliency']])
    results = _run_pass(proc, path, [dict(_FAILED)])
    _persist(proc, results, _images(path))
    assert _saliency_row(db, path) == _FAILED


def test_null_saliency_redistributes_weight_in_the_aggregate():
    from config.scoring_config import ScoringConfig
    from config_resolve import defaults_path
    from processing.scorer import Facet, build_metric_vector

    cfg = ScoringConfig(defaults_path(), validate=False)
    base = dict(face_count=0, face_ratio=0.0, aesthetic=7, comp_score=6, tech_sharpness=7,
                color_score=6, exposure_score=7, tags='', is_monochrome=0, mean_saturation=0.4)
    nulls = dict(base, **{k: None for k in _COLS})
    neutral = dict(base, subject_sharpness=5.0, subject_prominence=5.0,
                   subject_placement=5.0, bg_separation=5.0)

    vector = build_metric_vector(nulls, cfg, 'default')
    # Model features remain finite; scoring drops the missing inputs' weights.
    for key in ('subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation'):
        assert vector[key] == 5.0

    facet = Facet.__new__(Facet)
    facet.config = cfg
    original = cfg.get_weights

    def weighted(category):
        w = dict(original(category))
        w.update(subject_sharpness=0.2, subject_prominence=0.1,
                 subject_placement=0.1, bg_separation=0.1)
        return w

    cfg.get_weights = weighted
    score_null, _ = facet.calculate_aggregate_logic(nulls)
    score_neutral, _ = facet.calculate_aggregate_logic(neutral)
    cfg.get_weights = original
    score_without_saliency, _ = facet.calculate_aggregate_logic(base)
    assert score_null == pytest.approx(score_without_saliency)
    assert score_null != pytest.approx(score_neutral)
    assert 0.0 < score_null < float('inf')


@pytest.fixture()
def recompute_db(seeded):
    """The seeded row (populated) plus a second row that never had saliency."""
    path, facet, db = seeded
    with get_connection(db, row_factory=False) as conn:
        conn.execute("UPDATE photos SET subject_sharpness=7.0, subject_prominence=5.0, "
                     "subject_placement=6.0, bg_separation=4.0, "
                     "subject_bbox='[0.1, 0.1, 0.9, 0.9]' WHERE path=?", (path,))
        conn.execute("INSERT INTO photos (path, filename, thumbnail) VALUES ('/x/never.jpg', "
                     "'never.jpg', x'00')")
        conn.commit()
    return path, db


def test_recompute_flush_skips_a_failed_photo_and_does_not_count_it(recompute_db):
    import facet as facet_cli
    path, db = recompute_db
    good = {'subject_sharpness': 3.0, 'subject_prominence': 2.0, 'subject_placement': 1.0,
            'bg_separation': 9.0, 'subject_bbox': [0.2, 0.2, 0.4, 0.4]}
    scorer = _Scorer([dict(_FAILED), good])
    with get_connection(db, row_factory=False) as conn:
        written = facet_cli._flush_saliency_batch(
            conn, scorer, [path, '/x/never.jpg'], [object(), object()], [object(), object()])
        conn.commit()
    assert written == 1
    # --force over a populated row: the failure leaves the stored value in place
    assert _saliency_row(db, path)['subject_sharpness'] == 7.0
    assert _saliency_row(db, path)['subject_bbox'] == '[0.1, 0.1, 0.9, 0.9]'
    assert _saliency_row(db, '/x/never.jpg')['subject_sharpness'] == 3.0


def test_recompute_flush_leaves_a_never_scored_row_null_and_reselectable(recompute_db):
    import facet as facet_cli
    _, db = recompute_db
    scorer = _Scorer([dict(_FAILED)])
    with get_connection(db, row_factory=False) as conn:
        written = facet_cli._flush_saliency_batch(
            conn, scorer, ['/x/never.jpg'], [object()], [object()])
        conn.commit()
    assert written == 0
    assert _saliency_row(db, '/x/never.jpg') == _FAILED
    with get_connection(db, row_factory=False) as conn:
        selected = [r[0] for r in conn.execute(
            f"SELECT path FROM photos WHERE {facet_cli._saliency_recompute_where(False)}")]
    assert '/x/never.jpg' in selected


# --- the upgrade selection must not loop over a terminal no-subject result ----------------

def _selected_paths(db):
    import facet as facet_cli
    with get_connection(db, row_factory=False) as conn:
        return {r[0] for r in conn.execute(
            f"SELECT path FROM photos WHERE {facet_cli._saliency_recompute_where(False)}")}


def test_recompute_selection_skips_a_no_subject_photo(recompute_db):
    """prominence 0.0 with no bbox is the answer, not missing data (the 1899-photo loop)."""
    import facet as facet_cli
    _, db = recompute_db
    with get_connection(db, row_factory=False) as conn:
        conn.execute("INSERT INTO photos (path, filename, thumbnail) VALUES "
                     "('/x/nosubject.jpg', 'nosubject.jpg', x'00')")
        facet_cli._flush_saliency_batch(
            conn, _Scorer([dict(_NO_SUBJECT)]), ['/x/nosubject.jpg'], [object()], [object()])
        conn.commit()
    assert _saliency_row(db, '/x/nosubject.jpg') == _NO_SUBJECT
    assert '/x/nosubject.jpg' not in _selected_paths(db)


def test_recompute_selection_keeps_never_scored_and_pre_bbox_rows(recompute_db):
    path, db = recompute_db
    with get_connection(db, row_factory=False) as conn:
        conn.execute("INSERT INTO photos (path, filename, thumbnail) VALUES "
                     "('/x/prebbox.jpg', 'prebbox.jpg', x'00')")
        conn.execute("UPDATE photos SET subject_sharpness=6.0, subject_prominence=4.0, "
                     "subject_placement=5.0, bg_separation=3.0, subject_bbox=NULL "
                     "WHERE path='/x/prebbox.jpg'")
        conn.commit()
    selected = _selected_paths(db)
    assert '/x/never.jpg' in selected          # never scored: retries
    assert '/x/prebbox.jpg' in selected        # scored before the bbox column: backfills
    assert path not in selected                # fully scored: nothing to do


def test_recompute_selection_rewrites_a_pre_184_neutral_no_subject_row_once(recompute_db):
    """Versions before #184 stored 5.0 beside prominence 0.0; one run rewrites it, then it is final."""
    import facet as facet_cli
    _, db = recompute_db
    with get_connection(db, row_factory=False) as conn:
        conn.execute("INSERT INTO photos (path, filename, thumbnail, subject_sharpness, "
                     "subject_prominence, subject_placement, bg_separation) VALUES "
                     "('/x/legacy.jpg', 'legacy.jpg', x'00', 5.0, 0.0, 5.0, 5.0)")
        conn.commit()
    assert '/x/legacy.jpg' in _selected_paths(db)
    with get_connection(db, row_factory=False) as conn:
        facet_cli._flush_saliency_batch(
            conn, _Scorer([dict(_NO_SUBJECT)]), ['/x/legacy.jpg'], [object()], [object()])
        conn.commit()
    assert _saliency_row(db, '/x/legacy.jpg') == _NO_SUBJECT
    assert '/x/legacy.jpg' not in _selected_paths(db)


def test_recompute_selection_force_takes_every_thumbnail(recompute_db):
    import facet as facet_cli
    path, db = recompute_db
    assert facet_cli._saliency_recompute_where(True) == "thumbnail IS NOT NULL"
    with get_connection(db, row_factory=False) as conn:
        all_paths = {r[0] for r in conn.execute(
            f"SELECT path FROM photos WHERE {facet_cli._saliency_recompute_where(True)}")}
    assert path in all_paths and '/x/never.jpg' in all_paths


def test_restricted_save_skips_saliency_columns_of_a_flagged_photo_even_if_present(seeded):
    """The flag itself guards the save, not only the absence of the keys."""
    path, facet, db = seeded
    proc = _processor(facet, [['saliency']])
    _persist(proc, {path: dict(_SALIENCY)}, _images(path))
    before = _saliency_row(db, path)

    _persist(proc, {path: {SALIENCY_FAILED_KEY: True, **_FAILED, 'subject_sharpness': 5.0}},
             _images(path))

    assert _saliency_row(db, path) == before


# --- T8: a photo with no subject stores NULL, not a made-up 5.0 ---------------------------

def _stub_scorer():
    from tests import test_saliency as _ts
    return _ts


def test_below_min_subject_pixels_scores_null_with_zero_prominence():
    pytest.importorskip("torch")
    import numpy as np
    from models.saliency_scorer import SaliencyScorer
    scorer = SaliencyScorer.__new__(SaliencyScorer)
    scorer.min_subject_pixels = 50
    scorer.mask_threshold = 0.3
    img = np.full((12, 16, 3), 120, dtype=np.uint8)
    for mask in (np.zeros((12, 16), np.uint8),                         # empty
                 np.pad(np.full((3, 3), 255, np.uint8), ((0, 9), (0, 13)))):  # 9 px < 50
        assert scorer._score_from_mask(mask, img) == _NO_SUBJECT


def test_batch_logs_no_failure_for_a_no_subject_photo(caplog):
    import numpy as np
    ts = _stub_scorer()
    scorer = ts._fixed_batch(ts._oom_scorer(), 4)
    imgs = ts._tagged_images(2)  # image 0 gets an empty mask, image 1 a full-frame one
    cv = [np.full((12, 16, 3), 200, dtype=np.uint8)] * 2
    with caplog.at_level("ERROR", logger="facet.saliency"):
        results = scorer.score_batch(imgs, cv)
    assert results[0] == _NO_SUBJECT
    assert results[1]['subject_sharpness'] is not None
    assert not [r for r in caplog.records if "Saliency failed" in r.getMessage()]
    # ... and it is not the failure signature the writers test for
    assert not all(results[0][k] is None for k in _COLS[:4])


def test_batch_still_logs_a_genuine_failure(caplog):
    import numpy as np
    ts = _stub_scorer()
    scorer = ts._fixed_batch(ts._oom_scorer(max_ok=0), 4)  # every mask comes back None
    cv = [np.full((12, 16, 3), 200, dtype=np.uint8)] * 2
    with caplog.at_level("ERROR", logger="facet.saliency"):
        results = scorer.score_batch(ts._tagged_images(2), cv)
    assert results == [dict(_FAILED), dict(_FAILED)]
    assert [r for r in caplog.records if "Saliency failed for 2 of 2" in r.getMessage()]


def test_no_subject_photo_is_saved_as_null_with_zero_prominence(seeded):
    path, facet, db = seeded
    proc = _processor(facet, [['saliency']])
    results = _run_pass(proc, path, [dict(_NO_SUBJECT)])
    assert SALIENCY_FAILED_KEY not in results[path]
    _persist(proc, results, _images(path))
    assert _saliency_row(db, path) == _NO_SUBJECT


def test_recompute_flush_writes_a_no_subject_photo_as_null(recompute_db):
    import facet as facet_cli
    _, db = recompute_db
    with get_connection(db, row_factory=False) as conn:
        written = facet_cli._flush_saliency_batch(
            conn, _Scorer([dict(_NO_SUBJECT)]), ['/x/never.jpg'], [object()], [object()])
        conn.commit()
    assert written == 1  # a result, not a failure
    assert _saliency_row(db, '/x/never.jpg') == _NO_SUBJECT
