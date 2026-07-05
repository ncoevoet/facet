"""F29 regression: multi-hour recomputes must commit per batch, not once.

Before the fix, ``rescan_samp_composition`` (and the other heavy recompute
loops) buffered every UPDATE into a single transaction and committed once after
the whole library. An interrupt/OOM part-way through closed the connection
without committing, rolling back 100% of completed work. This drives the SAMP
recompute with a scorer that raises on the second batch and asserts the first
batch's writes survived.
"""

import numpy as np
import pytest

pytest.importorskip("cv2")
import cv2  # noqa: E402

from db import get_connection  # noqa: E402
from db.schema import init_database  # noqa: E402
from processing.scorer import Facet, _load_image_modules  # noqa: E402


def _jpeg_blob():
    arr = np.full((400, 400, 3), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", arr)
    assert ok
    return buf.tobytes()


class _RaisingSampScorer:
    def __init__(self):
        self.calls = 0

    def score_batch(self, images):
        self.calls += 1
        if self.calls >= 2:
            raise KeyboardInterrupt()
        return [{"comp_score": 9.9, "pattern": "rule_of_thirds"} for _ in images]


@pytest.mark.timeout(30)
def test_samp_recompute_commits_per_batch(tmp_path, monkeypatch):
    db_path = str(tmp_path / "scores.db")
    init_database(db_path)

    blob = _jpeg_blob()
    paths = [f"/photos/img_{i}.jpg" for i in range(5)]
    with get_connection(db_path, row_factory=False) as conn:
        for p in paths:
            conn.execute(
                "INSERT INTO photos (path, filename, thumbnail, comp_score) VALUES (?, ?, ?, ?)",
                (p, p.rsplit("/", 1)[-1], blob, 0.0),
            )
        conn.commit()

    monkeypatch.setattr("models.samp_net.SAMPNetScorer", _RaisingSampScorer)
    _load_image_modules()  # the real --recompute-composition-gpu path does this first

    facet = Facet(db_path=db_path, config_path="scoring_config.json", lightweight=True)

    with pytest.raises(KeyboardInterrupt):
        facet.rescan_samp_composition(batch_size=2)

    with get_connection(db_path, row_factory=False) as conn:
        committed = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE comp_score = 9.9"
        ).fetchone()[0]

    # The first batch (2 photos) committed before the second batch raised.
    assert committed == 2
