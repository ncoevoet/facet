"""Tests for the run_moment_detection orchestration glue (facet.py).

The classifier and the Viterbi smoother are unit-tested in isolation; this pins
the wiring between them, which is the part the feature actually ships:
caption-vs-image signal selection, and the rule that a per-frame 'other' gate
overrides the smoothed label and stores a fixed neutral 0.5 confidence.
"""

import sqlite3

import pytest

import facet
from models.moment_classifier import OTHER

_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY, clip_embedding BLOB, caption TEXT,
        caption_embedding BLOB, face_count INTEGER, face_ratio REAL,
        is_group_portrait INTEGER, tags TEXT, date_taken TEXT,
        narrative_moment TEXT, narrative_moment_confidence REAL
    );
"""

# Row A: has a caption embedding -> scored on the 'caption' signal, confident moment.
# Row B: no caption -> scored on the 'image' signal, gated to 'other'.
_PHOTOS = [
    ("/a.jpg", b"imgA", "a party", b"capA", 0, 0.0, 0, None, "2024:06:15 10:00:00"),
    ("/b.jpg", b"imgB", None, None, 0, 0.0, 0, None, "2024:06:15 10:05:00"),
]


class _StubConfig:
    def get_narrative_moments_config(self):
        return {'enabled': True}

    def get_moment_transitions(self):
        return {'order': ['beach', 'celebration'], 'weight': 0.0}

    def get_moment_vlm_tiebreak(self):
        return {'enabled': False, 'min_confidence': 0.0, 'min_margin': 0.04}


class _StubManager:
    device = 'cpu'

    def load_model_only(self, name):
        return {'model': None, 'model_name': 'm', 'backend': 'transformers', 'embedding_dim': 3}


class _FakeClassifier:
    moments = ['beach', 'celebration']

    def __init__(self, *args, **kwargs):
        _FakeClassifier.classify_calls = []

    def classify_with_probs(self, emb, photo_data, signal=None):
        _FakeClassifier.classify_calls.append((emb, signal))
        if emb == b"imgB":
            return [0.5, 0.5], OTHER         # gated 'other'
        return [0.5, 0.5], 'celebration'     # confident moment


def _fake_smooth(prob_vectors, timestamps, transitions):
    # Frame A -> moment index 1 ('celebration') @ 0.95; frame B -> index 0 @ 0.30.
    return [(1, 0.95), (0, 0.30)]


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "moments.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO photos (path, clip_embedding, caption, caption_embedding, "
        "face_count, face_ratio, is_group_portrait, tags, date_taken) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        _PHOTOS,
    )
    conn.commit()
    conn.close()
    return path


def test_signal_selection_and_other_gate_override(db_path, monkeypatch):
    monkeypatch.setattr('models.moment_classifier.MomentClassifier', _FakeClassifier)
    monkeypatch.setattr('models.moment_smoothing.smooth', _fake_smooth)

    result = facet.run_moment_detection(db_path, _StubConfig(), model_manager=_StubManager())

    assert result['labeled'] == 2

    # Signal selection: the captioned row is scored on its caption embedding
    # ('caption'); the uncaptioned row on its image embedding ('image').
    calls = dict(_FakeClassifier.classify_calls)
    assert calls[b"capA"] == 'caption'
    assert calls[b"imgB"] == 'image'

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stored = {
        r['path']: (r['narrative_moment'], r['narrative_moment_confidence'])
        for r in conn.execute(
            "SELECT path, narrative_moment, narrative_moment_confidence FROM photos"
        )
    }
    conn.close()

    # Confident frame takes the smoothed moment + its forward-backward posterior.
    assert stored["/a.jpg"] == ('celebration', 0.95)
    # 'other'-gated frame keeps 'other' on the neutral 0.5 scale, NOT the smoothed
    # label ('beach') nor the non-other state's posterior (0.30).
    assert stored["/b.jpg"] == ('other', 0.5)
