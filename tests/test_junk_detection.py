"""Tests for the junk sweep: zero-shot classifier, run_junk_detection wiring,
the gallery junk_kind filter, and the clear_junk (Keep) endpoint.

The classifier uses synthetic embeddings + an injected prompt matrix, so no
CLIP/SigLIP model is loaded. Auth-gated endpoints use the shared conftest
fixtures / dependency_overrides (never mock.patch on auth deps).
"""

import sqlite3
from contextlib import asynccontextmanager, contextmanager
from unittest import mock

import aiosqlite
import numpy as np
import pytest
from fastapi.testclient import TestClient

import facet
from api import create_app
from api.auth import get_optional_user
from db.schema import init_database
from models.junk_classifier import JunkClassifier, NOT_JUNK
from utils.embedding import embedding_to_bytes


# --- classifier unit tests (injected prompt matrix, no model) -------------- #

# screenshot -> axis 0, document -> axis 1, not_junk -> axis 2 (the contrast gate).
_KINDS = ('screenshot', 'document')
_PROMPTS_4D = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]
_LABEL_IDX = [0, 1, 2]


def _classifier(kinds=_KINDS, prompts=None, label_idx=None,
                min_confidence=0.3, min_margin=0.05, pooling='max'):
    clf = object.__new__(JunkClassifier)
    clf.kinds = list(kinds)
    clf.labels = list(kinds) + [NOT_JUNK]
    clf._not_junk_idx = len(kinds)
    clf.prompt_matrix = np.array(prompts if prompts is not None else _PROMPTS_4D, dtype=np.float32)
    clf.prompt_label_idx = np.array(label_idx if label_idx is not None else _LABEL_IDX, dtype=np.int64)
    clf.embedding_dim = clf.prompt_matrix.shape[1]
    clf.backend = 'transformers'
    clf.pooling = pooling
    clf.min_confidence = min_confidence
    clf.min_margin = min_margin
    return clf


def _emb(vec):
    return embedding_to_bytes(np.array(vec, dtype=np.float32))


def test_flags_best_junk_kind():
    clf = _classifier()
    kind, conf = clf.classify(_emb([0.9, 0.0, 0.0, 0.1]))
    assert kind == 'screenshot'
    assert conf > 0.5


def test_not_junk_when_contrast_prompt_wins():
    # Most of the mass sits on the not_junk axis, so every junk cosine stays low.
    clf = _classifier(min_confidence=0.5)
    kind, _ = clf.classify(_emb([0.10, 0.10, 0.90, 0.0]))
    assert kind == NOT_JUNK


def test_not_junk_when_margin_over_contrast_too_small():
    # screenshot barely beats not_junk (~0.02 cosine) -> below min_margin.
    clf = _classifier(min_confidence=0.1, min_margin=0.05)
    kind, _ = clf.classify(_emb([0.72, 0.0, 0.70, 0.0]))
    assert kind == NOT_JUNK


def test_below_confidence_is_clean():
    clf = _classifier(min_confidence=0.95, min_margin=0.0)
    kind, _ = clf.classify(_emb([0.30, 0.29, 0.10, 0.0]))  # top cosine ~0.7 < 0.95
    assert kind == NOT_JUNK


def test_dimension_mismatch_returns_none():
    clf = _classifier()
    kind, conf = clf.classify(_emb([1, 0, 0, 0, 0]))  # 5-dim vs 4-dim matrix
    assert kind is None and conf is None


@pytest.mark.parametrize("dim", [768, 1152])
def test_works_at_clip_and_siglip_dims(dim):
    # screenshot on axis 0, not_junk on axis 1, in the real embedding dims.
    prompts = np.zeros((2, dim), dtype=np.float32)
    prompts[0, 0] = 1.0
    prompts[1, 1] = 1.0
    clf = _classifier(kinds=('screenshot',), prompts=prompts, label_idx=[0, 1],
                      min_confidence=0.3, min_margin=0.05)
    hit = np.zeros(dim, dtype=np.float32)
    hit[0] = 1.0
    assert clf.classify(embedding_to_bytes(hit))[0] == 'screenshot'
    miss = np.zeros(dim, dtype=np.float32)
    miss[1] = 1.0  # aligns with the not_junk contrast prompt
    assert clf.classify(embedding_to_bytes(miss))[0] == NOT_JUNK


def test_scores_dict_aligned_to_labels():
    clf = _classifier()
    scores = clf.scores(_emb([1, 0, 0, 0]))
    assert set(scores) == {'screenshot', 'document', NOT_JUNK}
    assert abs(scores['screenshot'] - 1.0) < 1e-6


def test_backend_selects_its_thresholds(monkeypatch):
    # __init__ picks the per-backend gate; a single fake prompt row per label.
    def _fake_encode(model, model_name, backend, device, prompts):
        class _T:
            def detach(self): return self
            def cpu(self): return self
            def numpy(self): return np.ones((len(prompts), 4), dtype=np.float32)
        return _T()

    monkeypatch.setattr('models.junk_classifier.encode_text_prompts', _fake_encode)

    class _Cfg:
        def get_junk_sweep_config(self): return {'enabled': True, 'pooling': 'max'}
        def get_junk_kinds(self): return {'screenshot': ['s'], 'document': ['d']}
        def get_junk_not_junk_prompts(self): return ['p']
        def get_junk_thresholds(self):
            return {'open_clip': {'min_confidence': 0.18, 'min_margin': 0.02},
                    'transformers': {'min_confidence': 0.1, 'min_margin': 0.03}}

    clip = JunkClassifier(None, 'cpu', _Cfg(), 'm', 'transformers', 4)
    assert (clip.min_confidence, clip.min_margin) == (0.1, 0.03)
    cpu = JunkClassifier(None, 'cpu', _Cfg(), 'm', 'open_clip', 4)
    assert (cpu.min_confidence, cpu.min_margin) == (0.18, 0.02)
    assert cpu.kinds == ['screenshot', 'document']


# --- run_junk_detection orchestration -------------------------------------- #

_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY, clip_embedding BLOB, junk_kind TEXT
    );
"""
_PHOTOS = [
    ("/junk.jpg", b"junkemb", None),      # unevaluated -> flagged screenshot
    ("/clean.jpg", b"cleanemb", None),    # unevaluated -> stored not_junk
    ("/done.jpg", b"doneemb", NOT_JUNK),  # already evaluated -> skipped by only_missing
]


class _StubManager:
    device = 'cpu'

    def load_model_only(self, name):
        return {'model': None, 'model_name': 'm', 'backend': 'transformers', 'embedding_dim': 3}


class _FakeClassifier:
    def __init__(self, *args, **kwargs):
        _FakeClassifier.seen = []

    def classify(self, emb):
        _FakeClassifier.seen.append(emb)
        if emb == b"junkemb":
            return 'screenshot', 0.9
        return NOT_JUNK, 0.1

    def scores(self, emb):
        return {'screenshot': 0.9, NOT_JUNK: 0.1}


class _StubConfig:
    def get_junk_sweep_config(self):
        return {'enabled': True}


@pytest.fixture
def junk_db(tmp_path):
    path = str(tmp_path / "junk.db")
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO photos (path, clip_embedding, junk_kind) VALUES (?, ?, ?)", _PHOTOS)
    conn.commit()
    conn.close()
    return path


def test_run_junk_detection_labels_and_scopes(junk_db, monkeypatch):
    monkeypatch.setattr('models.junk_classifier.JunkClassifier', _FakeClassifier)

    result = facet.run_junk_detection(junk_db, _StubConfig(), model_manager=_StubManager())

    assert result['labeled'] == 2
    assert result['junk_count'] == 1
    # only_missing scoping never re-scores the already-evaluated row.
    assert b"doneemb" not in _FakeClassifier.seen

    conn = sqlite3.connect(junk_db)
    stored = dict(conn.execute("SELECT path, junk_kind FROM photos"))
    conn.close()
    assert stored["/junk.jpg"] == 'screenshot'
    assert stored["/clean.jpg"] == NOT_JUNK   # clean marked, not left NULL
    assert stored["/done.jpg"] == NOT_JUNK


def test_run_junk_detection_dry_run_writes_nothing(junk_db, monkeypatch):
    monkeypatch.setattr('models.junk_classifier.JunkClassifier', _FakeClassifier)

    result = facet.run_junk_detection(
        junk_db, _StubConfig(), model_manager=_StubManager(), dry_run=True)

    assert result['labeled'] == 0
    assert result['would_label'] == 2
    conn = sqlite3.connect(junk_db)
    stored = dict(conn.execute("SELECT path, junk_kind FROM photos"))
    conn.close()
    assert stored["/junk.jpg"] is None  # dry-run persisted nothing


def test_run_junk_detection_disabled_skips():
    class _Off:
        def get_junk_sweep_config(self): return {'enabled': False}
    assert facet.run_junk_detection("ignored.db", _Off())['skipped'] == 'disabled'


# --- gallery junk_kind filter ---------------------------------------------- #

def _async_conn_factory(db_path):
    @asynccontextmanager
    async def factory():
        c = await aiosqlite.connect(db_path)
        c.row_factory = aiosqlite.Row
        try:
            yield c
        finally:
            await c.close()
    return factory


def _sync_conn_factory(db_path):
    @contextmanager
    def factory():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()
    return factory


_VIEWER_CONFIG = {
    "display": {"tags_per_photo": 5},
    "pagination": {"default_per_page": 64, "max_per_page": 200},
    "defaults": {
        "sort": "aggregate", "sort_direction": "DESC",
        "hide_blinks": False, "hide_bursts": False,
        "hide_duplicates": False, "type": "",
    },
    "dropdowns": {"min_photos_for_person": 2, "max_persons": 100},
    "quality_thresholds": {"good": 6, "great": 7, "excellent": 8, "best": 9},
    "features": {},
}


@pytest.fixture()
def gallery_db(tmp_path):
    db_path = str(tmp_path / "g.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    rows = [
        ("/g/shot.jpg", 5.0, "screenshot"),
        ("/g/doc.jpg", 5.0, "document"),
        ("/g/clean.jpg", 5.0, NOT_JUNK),
        ("/g/photo.jpg", 5.0, None),
    ]
    for path, agg, junk in rows:
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate, junk_kind) VALUES (?, ?, ?, ?)",
            (path, path.rsplit("/", 1)[-1], agg, junk),
        )
    conn.commit()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
    conn.close()
    return db_path, cols


def _run(db_path, cols, query):
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: None
    with (
        mock.patch("api.routers.gallery.get_db", _sync_conn_factory(db_path)),
        mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(db_path)),
        mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
        mock.patch("api.db_helpers._existing_columns_cache", cols),
        mock.patch.dict("api.config._count_cache", {}, clear=True),
    ):
        return TestClient(app).get(query)


def test_junk_kind_any_excludes_clean_and_null(gallery_db):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, "/api/photos?junk_kind=any")
    assert resp.status_code == 200
    paths = {p["path"] for p in resp.json()["photos"]}
    assert paths == {"/g/shot.jpg", "/g/doc.jpg"}


def test_junk_kind_exact_match(gallery_db):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, "/api/photos?junk_kind=screenshot")
    assert resp.status_code == 200
    paths = {p["path"] for p in resp.json()["photos"]}
    assert paths == {"/g/shot.jpg"}


def test_default_gallery_shows_all_including_junk(gallery_db):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, "/api/photos")
    assert resp.status_code == 200
    paths = {p["path"] for p in resp.json()["photos"]}
    assert paths == {"/g/shot.jpg", "/g/doc.jpg", "/g/clean.jpg", "/g/photo.jpg"}


def test_junk_kind_returned_in_payload(gallery_db):
    db_path, cols = gallery_db
    resp = _run(db_path, cols, "/api/photos?junk_kind=document")
    assert resp.status_code == 200
    assert resp.json()["photos"][0]["junk_kind"] == "document"


# --- clear_junk (Keep) endpoint -------------------------------------------- #

def _faces_db(tmp_path, junk_kind):
    db = str(tmp_path / "f.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE photos (path TEXT PRIMARY KEY, filename TEXT, junk_kind TEXT)")
    conn.execute("INSERT INTO photos (path, filename, junk_kind) VALUES (?, ?, ?)",
                 ("/f/shot.jpg", "shot.jpg", junk_kind))
    conn.commit()
    conn.close()
    return db


def test_clear_junk_marks_evaluated_clean(edition_client, tmp_path):
    db = _faces_db(tmp_path, "screenshot")
    with mock.patch("api.routers.faces.get_db", _sync_conn_factory(db)):
        resp = edition_client.post("/api/photo/clear_junk", json={"photo_path": "/f/shot.jpg"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    conn = sqlite3.connect(db)
    kind = conn.execute("SELECT junk_kind FROM photos WHERE path = ?", ("/f/shot.jpg",)).fetchone()[0]
    conn.close()
    assert kind == NOT_JUNK  # kept photo leaves the queue permanently, not re-flagged


def test_clear_junk_missing_photo_404(edition_client, tmp_path):
    db = _faces_db(tmp_path, "screenshot")
    with mock.patch("api.routers.faces.get_db", _sync_conn_factory(db)):
        resp = edition_client.post("/api/photo/clear_junk", json={"photo_path": "/f/nope.jpg"})
    assert resp.status_code == 404


def test_clear_junk_requires_edition(regular_client, tmp_path):
    db = _faces_db(tmp_path, "screenshot")
    with mock.patch("api.routers.faces.get_db", _sync_conn_factory(db)):
        resp = regular_client.post("/api/photo/clear_junk", json={"photo_path": "/f/shot.jpg"})
    assert resp.status_code == 403
