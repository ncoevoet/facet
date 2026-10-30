"""Optional NULL inputs must not contribute fabricated quality."""
import numpy as np
import pytest

from config import ScoringConfig
from processing.scorer import build_metric_vector, fold_quality_weight, weights_for_row
from optimization.weight_optimizer import _pairwise_objective, _row_scores_and_gradient, _fit_weights


def test_partial_null_reproducer():
    weights = {'aesthetic': 0.6, 'subject_sharpness': 0.4}
    row = {'aesthetic': 8.0, 'subject_sharpness': None}
    effective = weights_for_row(weights, row)
    assert effective['aesthetic'] == 1.0
    assert effective['subject_sharpness'] == 0.0
    assert weights['aesthetic'] == 0.6


@pytest.mark.parametrize('value', [0.0, 4.0, 10.0])
def test_present_values_including_zero(value):
    weights = {'aesthetic': 0.6, 'subject_sharpness': 0.4}
    assert weights_for_row(weights, {'subject_sharpness': value}) is weights


def test_all_missing_keeps_neutral_imputation():
    weights = {'subject_sharpness': 0.6, 'face_quality_iqa': 0.4}
    effective = weights_for_row(weights, {})
    vector = build_metric_vector({}, None, 'default')
    assert sum(vector[k] * v for k, v in effective.items()) == 5.0


def test_nonnullable_and_licence_exclusions():
    weights = {'aesthetic': 0.6, 'face_quality_iqa': 0.4}
    assert weights_for_row(weights, {'face_quality_iqa': 9}) is weights
    assert weights_for_row(weights, {'face_quality_iqa': 9}, {'face_quality_iqa'})['aesthetic'] == 1


def test_shipped_weights_are_exactly_unchanged(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text('{}')
    cfg = ScoringConfig(str(path), validate=False)
    for category in cfg.config['categories']:
        weights = fold_quality_weight(cfg.get_weights(category['name']))
        assert weights_for_row(weights, {}) is weights


def test_masked_objective_gradient_and_all_missing():
    D = np.array([[[8., np.nan, 0.], [4., 9., np.nan]],
                  [[np.nan, np.nan, np.nan], [0., 3., 8.]]])
    w = np.array([.3, .4, .3])
    y = np.array([1, 0])
    args = (D, y, np.ones(2), w, 2.)
    _, grad = _pairwise_objective(w, *args)
    for i in range(3):
        step = np.eye(3)[i] * 1e-6
        numeric = (_pairwise_objective(w + step, *args)[0]
                   - _pairwise_objective(w - step, *args)[0]) / 2e-6
        assert grad[i] == pytest.approx(numeric, abs=1e-6)
    assert _row_scores_and_gradient(D[:, 0], w)[0][1] == 5.


def test_optimizer_null_pair_matches_removed_column():
    a = np.array([[9., 3.], [2., 7.], [8., 1.]])
    b = np.array([[3., 8.], [5., 2.], [1., 9.]])
    complete = np.stack((a, b), axis=1)
    masked = np.concatenate((complete, np.full((3, 2, 1), np.nan)), axis=2)
    y, rw = np.array([1, -1, 1]), np.ones(3)
    w = np.array([.5, .5])
    # A prior on a component with no data is held, not zeroed or redistributed:
    # the data columns share the remaining 0.6 exactly as they would share 1.0.
    full_w = np.array([.3, .3, .4])
    # The prior penalty acts on weights summing to 0.6, i.e. 0.6**2 of its strength on shares.
    expected = _fit_weights(complete, y, rw, w, 100. * .36, [w], 100)[0]
    actual = _fit_weights(masked, y, rw, full_w, 100., [full_w], 100)[0]
    assert actual[2] == pytest.approx(.4, abs=1e-9)
    assert actual[:2] / actual[:2].sum() == pytest.approx(expected, abs=1e-5)


def test_all_null_column_keeps_prior_through_fit_and_apply_percent():
    from optimization.weight_optimizer import WeightOptimizer
    rng = np.random.RandomState(0)
    n = 60
    a, b = rng.uniform(0, 10, (n, 3)), rng.uniform(0, 10, (n, 3))
    a[:, 2] = np.nan
    b[:, 2] = np.nan
    y = np.where(a[:, 0] + a[:, 1] > b[:, 0] + b[:, 1], 1, -1)
    w0 = np.array([.4, .4, .2])
    D = np.stack((a, b), axis=1)
    fitted = _fit_weights(D, y, np.ones(n), w0, 100., [w0], 300)[0]
    assert fitted[2] == pytest.approx(.2, abs=1e-9)
    assert fitted.sum() == pytest.approx(1.)
    assert fitted.max() <= .6 + 1e-9
    # A licence-excluded column (-inf everywhere) is held the same way.
    lic = D.copy()
    lic[:, :, 2] = -np.inf
    assert _fit_weights(lic, y, np.ones(n), w0, 100., [w0], 300)[0][2] == pytest.approx(.2, abs=1e-9)
    # A subset that happens to lack the column's data must not unpin it when
    # the full-set mask is passed in.
    from optimization.weight_optimizer import _active_columns
    active = _active_columns(D)
    assert active.tolist() == [True, True, False]
    percent = WeightOptimizer._round_percent_weights(dict(zip(('m0', 'm1', 'subject_sharpness'), fitted)))
    assert percent['subject_sharpness'] == 20.0
    assert sum(percent.values()) == pytest.approx(100.)


def test_native_aggregate_and_critique_agree(tmp_path):
    from processing.scorer import Facet
    from api.routers.critique import _calculate_breakdown
    path = tmp_path / 'config.json'
    path.write_text('{}')
    cfg = ScoringConfig(str(path), validate=False)
    # Limit configuration through the existing scoring seam, without a database.
    cfg.get_weights = lambda category: {'aesthetic': .6, 'subject_sharpness': .4}
    scanner = Facet.__new__(Facet)
    scanner.config = cfg
    row = {'aesthetic': 8., 'subject_sharpness': None}
    score, category = scanner.calculate_aggregate_logic(row)
    assert score == 8.
    breakdown = _calculate_breakdown(row, cfg, category)
    assert sum(item['contribution'] for item in breakdown) == 8.
    assert {item['metric_key'] for item in breakdown} == {'aesthetic'}


def test_licence_only_fallback_is_zero():
    values = np.array([[-np.inf, 8.], [np.nan, 8.]])
    scores, _ = _row_scores_and_gradient(values, np.array([1., 0.]))
    assert scores.tolist() == [0., 5.]


def test_positive_nullable_weights_with_all_inputs_present_match_previous_rule(tmp_path, monkeypatch):
    """Positive subject / face-IQA weights, every input present: the aggregate is
    bit-identical to the rule before this change, in the default and the
    commercial licensing mode. (Replaces a test that fed shipped zero weights, which
    cannot reach the new branch; test_shipped_weights_are_exactly_unchanged keeps
    covering the zero-weight identity.)"""
    import struct
    import processing.scorer as scorer
    path = tmp_path / 'config.json'
    path.write_text('{}')
    cfg = ScoringConfig(str(path), validate=False)
    scanner = scorer.Facet.__new__(scorer.Facet)
    scanner.config = cfg
    monkeypatch.setattr(scanner, '_determine_photo_category', lambda m, c: 'default')
    served = {'aesthetic': .4, 'tech_sharpness': .2, 'comp_score': .1,
              'subject_sharpness': .15, 'face_quality_iqa': .15}
    monkeypatch.setattr(cfg, 'get_weights', lambda category: dict(served))
    row = {'aesthetic': 7.3, 'tech_sharpness': 4.1, 'comp_score': 6.2,
           'subject_sharpness': 8., 'face_quality_iqa': 3.5}
    def previous_rule(w, m, unavailable):
        return scorer.renormalise_weights(w, unavailable) if unavailable else w

    for unavailable in (frozenset(), frozenset({'face_quality_iqa'})):
        monkeypatch.setattr(scorer, 'unavailable_for_config', lambda c, u=unavailable: u)
        actual = scanner.calculate_aggregate_logic(row)[0]
        new_rule = scorer.weights_for_row
        monkeypatch.setattr(scorer, 'weights_for_row', previous_rule)
        previous = scanner.calculate_aggregate_logic(row)[0]
        monkeypatch.setattr(scorer, 'weights_for_row', new_rule)
        assert struct.pack('!d', actual) == struct.pack('!d', previous)
