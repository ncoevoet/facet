import numpy as np

from calibrate import METRIC_COLUMNS, build_metric_matrix


def test_build_metric_matrix_preserves_genuine_zero_scores():
    col = next(iter(METRIC_COLUMNS.keys()))
    rows = [{col: 0.0, 'mos': 5.0} for _ in range(10)]

    X, y, col_names = build_metric_matrix(rows)

    assert col in col_names
    idx = col_names.index(col)
    assert np.all(X[:, idx] == 0.0)
