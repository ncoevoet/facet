"""``GET /api/photos`` with ``semantic_q``: the semantic gate combined with every gallery filter.

Also covers ``api.routers.search.semantic_candidates`` (the uncapped, cached resolver the
gallery gate is built on). The text encoder is stubbed with a unit vector; each photo's
embedding is ``(cos, sin, 0, ...)`` so its similarity to the query is exactly ``cos``.
"""

from __future__ import annotations

import asyncio
import math
import sqlite3
from unittest import mock

import numpy as np
import pytest

from api.database import get_async_db
from api.model_cache import AcceleratorBusy
from api.routers import gallery, search
from db import DEFAULT_DB_PATH
from db.connection import HAS_SQLITE_VEC, get_connection

DIM = 8
PREFIX = "/semf/"
THRESHOLD = 0.5
TOTAL = 24
PASSING = 18  # photos 0..17 pass the gate (cos >= 0.72); 18..23 do not (cos 0.2)
QUERY = "red sunset"

HIDE_OFF = {"hide_blinks": "0", "hide_bursts": "0", "hide_duplicates": "0", "hide_brackets": "0",
            "hide_panoramas": "0", "hide_rejected": "0", "type": "", "per_page": "100"}


def _vector(cos: float, dim: int = DIM) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    vec[0] = cos
    vec[1] = math.sqrt(1.0 - cos * cos)
    return vec


def _query_vector(dim: int = DIM) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    vec[0] = 1.0
    return vec


def _cos(i: int) -> float:
    return 0.9 - 0.01 * i if i < PASSING else 0.2


def _path(i: int) -> str:
    return f"{PREFIX}{'a' if i % 2 == 0 else 'b'}/p{i:02d}.jpg"


def _row(i: int) -> dict:
    row = {
        "path": _path(i), "filename": f"p{i:02d}.jpg", "aggregate": 5.0 + (i % 5),
        # Reversed against similarity, so a date sort and a similarity sort disagree.
        "date_taken": f"2026:01:{TOTAL - i:02d} 10:00:00",
        "clip_embedding": _vector(_cos(i)).tobytes(),
        "is_favorite": 1 if i % 3 == 0 else 0,
        "is_rejected": 1 if i % 4 == 1 else 0,
        "tags": "alpine" if i % 5 == 0 else None,
    }
    if i % 6 == 5:
        row.update(is_burst_lead=0, burst_group_id=1)
    return row


ALL = list(range(TOTAL))
GATED = [i for i in ALL if i < PASSING]
ALBUM_MEMBERS = [2, 3, 4, 5, 6, 7, 8, 20]
PERSON_PHOTOS = [i for i in ALL if i % 7 == 0]
PERSON_ID = 987001


def _paths(indices) -> set[str]:
    return {_path(i) for i in indices}


@pytest.fixture(autouse=True)
def _fresh_search_state():
    search._reset_text_encoder_cache()
    search._embedding_cache = None
    search._vec_available = None
    search._vec_success_checked_at = 0.0
    search._vec_failure_checked_at = 0.0
    search._fts_available = None
    yield
    search._reset_text_encoder_cache()
    search._embedding_cache = None
    search._vec_available = None
    search._vec_success_checked_at = 0.0
    search._vec_failure_checked_at = 0.0
    search._fts_available = None


@pytest.fixture()
def encoder():
    with mock.patch("api.routers.search._encode_text", return_value=_query_vector()) as stub:
        yield stub


@pytest.fixture()
def library(seed_photos_prefix, album_factory):
    seed_photos_prefix(PREFIX, [_row(i) for i in ALL])
    make_album = album_factory(PREFIX, "semf-share-token", "semf album")
    album_id = make_album(member_names=[_path(i)[len(PREFIX):] for i in ALBUM_MEMBERS])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.executemany(
            "INSERT INTO faces (photo_path, face_index, person_id, embedding) VALUES (?, 0, ?, ?)",
            [(_path(i), PERSON_ID, np.zeros(4, dtype=np.float32).tobytes()) for i in PERSON_PHOTOS])
    yield {"album_id": album_id}
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("DELETE FROM faces WHERE photo_path LIKE ?", (PREFIX + "%",))
        conn.execute("DELETE FROM photo_tags WHERE photo_path LIKE ?", (PREFIX + "%",))


def _get(client, **params):
    return client.get("/api/photos", params={**HIDE_OFF, "semantic_q": QUERY, "semantic_threshold": THRESHOLD,
                                             **params})


def _listed(client, **params) -> set[str]:
    resp = _get(client, **params)
    assert resp.status_code == 200, resp.text
    return {p["path"] for p in resp.json()["photos"]}


class TestIntersectionWithEveryFilterFamily:
    def test_the_gate_alone_returns_the_passing_photos_with_their_similarity(self, edition_client, library, encoder):
        resp = _get(edition_client)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert {p["path"] for p in body["photos"]} == _paths(GATED)
        assert body["total"] == PASSING
        by_path = {p["path"]: p for p in body["photos"]}
        top = by_path[_path(0)]
        assert top["embedding_similarity"] == pytest.approx(0.9, abs=1e-3)
        assert top["similarity"] == pytest.approx(0.9 * 0.7, abs=1e-3)

    def test_hide_toggles_and_hide_rejected(self, edition_client, library, encoder):
        kept = [i for i in GATED if i % 6 != 5]
        assert _listed(edition_client, hide_bursts="1") == _paths(kept)
        not_rejected = [i for i in GATED if i % 4 != 1]
        assert _listed(edition_client, hide_rejected="1") == _paths(not_rejected)

    def test_favorites_only(self, edition_client, library, encoder):
        assert _listed(edition_client, favorites_only="1") == _paths(i for i in GATED if i % 3 == 0)

    def test_album(self, edition_client, library, encoder):
        expected = _paths(i for i in GATED if i in ALBUM_MEMBERS)
        assert 0 < len(expected) < len(ALBUM_MEMBERS)  # photo 20 is a member that fails the gate
        assert _listed(edition_client, album_id=library["album_id"]) == expected

    def test_person(self, edition_client, library, encoder):
        assert _listed(edition_client, person=PERSON_ID) == _paths(i for i in GATED if i in PERSON_PHOTOS)

    def test_tag(self, edition_client, library, encoder):
        assert _listed(edition_client, tag="alpine") == _paths(i for i in GATED if i % 5 == 0)

    def test_score_range(self, edition_client, library, encoder):
        expected = _paths(i for i in GATED if 6.0 <= 5.0 + (i % 5) <= 7.0)
        assert _listed(edition_client, min_score="6", max_score="7") == expected

    def test_date_range(self, edition_client, library, encoder):
        # photo i is dated 2026-01-(24 - i): the 10th..14th are photos 14..10
        assert _listed(edition_client, date_from="2026-01-10", date_to="2026-01-14") == _paths(range(10, 15))

    def test_path_prefix(self, edition_client, library, encoder):
        expected = _paths(i for i in GATED if i % 2 == 0)
        assert _listed(edition_client, path_prefix=f"{PREFIX}a") == expected

    def test_filters_combine(self, edition_client, library, encoder):
        expected = _paths(i for i in GATED if i % 3 == 0 and i % 2 == 0 and i % 4 != 1)
        assert _listed(edition_client, favorites_only="1", path_prefix=f"{PREFIX}a",
                       hide_rejected="1") == expected

    def test_a_filter_that_matches_nothing_gives_an_empty_page(self, edition_client, library, encoder):
        body = _get(edition_client, min_score="99").json()
        assert body["photos"] == [] and body["total"] == 0 and body["has_more"] is False


class TestPaginationAndSort:
    def test_pages_do_not_overlap_or_skip_and_totals_are_real(self, edition_client, library, encoder):
        seen: list[str] = []
        pages = []
        for page in range(1, 5):
            body = _get(edition_client, per_page="5", page=page, sort="aggregate").json()
            pages.append(body)
            seen.extend(p["path"] for p in body["photos"])
        assert [b["total"] for b in pages] == [PASSING] * 4
        assert [b["total_pages"] for b in pages] == [4] * 4
        assert [b["has_more"] for b in pages] == [True, True, True, False]
        assert len(seen) == PASSING and set(seen) == _paths(GATED)
        whole = _get(edition_client, sort="aggregate").json()["photos"]
        assert seen == [p["path"] for p in whole]

    def test_date_ascending_is_honoured_not_similarity_order(self, edition_client, library, encoder):
        body = _get(edition_client, sort="date_taken", sort_direction="ASC").json()
        dates = [p["date_taken"] for p in body["photos"]]
        assert dates == sorted(dates)
        assert [p["path"] for p in body["photos"]] == [_path(i) for i in reversed(GATED)]


class TestRelevanceSort:
    def test_orders_by_blended_similarity_best_first_and_ascending_reverses(self, edition_client, library, encoder):
        best = _get(edition_client, sort="relevance").json()
        assert best["sort_col"] == "relevance"
        assert [p["path"] for p in best["photos"]] == [_path(i) for i in GATED]
        sims = [p["similarity"] for p in best["photos"]]
        assert sims == sorted(sims, reverse=True)
        worst = _get(edition_client, sort="relevance", sort_direction="ASC").json()
        assert [p["path"] for p in worst["photos"]] == [_path(i) for i in reversed(GATED)]

    def test_equal_similarity_breaks_ties_by_path(self, edition_client, library, encoder):
        body = _get(edition_client, sort="relevance", semantic_threshold="0.1").json()
        tied = [p["path"] for p in body["photos"] if p["similarity"] == body["photos"][-1]["similarity"]]
        assert tied == sorted(tied) and len(tied) > 1

    def test_paging_is_stable_across_pages(self, edition_client, library, encoder):
        seen = []
        for page in range(1, 5):
            body = _get(edition_client, sort="relevance", per_page="5", page=page).json()
            assert body["total"] == PASSING
            seen.extend(p["path"] for p in body["photos"])
        assert seen == [_path(i) for i in GATED]

    def test_needs_a_semantic_query(self, edition_client, library, encoder):
        resp = edition_client.get("/api/photos", params={**HIDE_OFF, "sort": "relevance"})
        assert resp.status_code == 400

    def test_filters_still_intersect(self, edition_client, library, encoder):
        body = _get(edition_client, sort="relevance", favorites_only="1").json()
        expected = [_path(i) for i in GATED if i % 3 == 0]
        assert [p["path"] for p in body["photos"]] == expected
        assert body["total"] == len(expected)

    def test_hide_toggles_and_summary_stay_correct(self, edition_client, library, encoder):
        plain = _get(edition_client, sort="aggregate", hide_bursts="1").json()
        rel = _get(edition_client, sort="relevance", hide_bursts="1").json()
        assert rel["total"] == plain["total"] and rel["hidden_summary"] == plain["hidden_summary"]
        assert {p["path"] for p in rel["photos"]} == {p["path"] for p in plain["photos"]}

    def test_page_query_probes_photos_by_primary_key(self, edition_client, library, encoder):
        resp = _get(edition_client, sort="relevance", per_page="5")
        assert resp.status_code == 200
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            plan = " ".join(r[3] for r in conn.execute(
                f"EXPLAIN QUERY PLAN SELECT photos.path FROM {gallery._RELEVANCE_FROM}photos "
                f"WHERE {gallery._RELEVANCE_CLAUSE} ORDER BY sem.pos ASC LIMIT 5", ['["a"]']))
        assert "SEARCH photos" in plan and "SCAN photos" not in plan and "TEMP B-TREE" not in plan


class TestHiddenSummary:
    def test_counts_only_the_semantic_subset(self, edition_client, library, encoder):
        hidden = [i for i in GATED if i % 6 == 5]
        body = _get(edition_client, hide_bursts="1").json()
        assert body["hidden_summary"]["total"] == len(hidden)
        assert body["hidden_summary"]["bursts"] == len(hidden)
        # Photo 23 is a burst member too, but it fails the gate: it must not be counted.
        assert any(i % 6 == 5 and i >= PASSING for i in ALL)

    def test_toggle_off_hides_nothing(self, edition_client, library, encoder):
        body = _get(edition_client).json()
        assert body["hidden_summary"]["total"] == 0 and body["total"] == PASSING


class TestVisibility:
    def test_a_foreign_directory_never_appears(self, edition_client, library, encoder):
        with (
            mock.patch("api.db_helpers.is_multi_user_enabled", return_value=True),
            mock.patch("api.db_helpers.get_user_directories", return_value=[f"{PREFIX}a"]),
        ):
            found = _listed(edition_client)
        assert found == _paths(i for i in GATED if i % 2 == 0)


class TestEmptyAndInvalid:
    def test_an_empty_candidate_set_is_total_zero(self, edition_client, library, encoder):
        resp = _get(edition_client, semantic_threshold="1.0")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["photos"] == [] and body["total"] == 0 and body["total_pages"] >= 0

    @pytest.mark.parametrize("params", [
        {"semantic_q": "   "}, {"semantic_q": ""}, {"semantic_q": "x" * 501},
        {"semantic_threshold": "1.5"}, {"semantic_threshold": "-0.1"}, {"semantic_threshold": "abc"},
        {"semantic_threshold": "nan"}])
    def test_bad_parameters_are_400(self, edition_client, library, encoder, params):
        assert _get(edition_client, **params).status_code == 400

    def test_a_threshold_without_a_query_is_400(self, edition_client, library, encoder):
        resp = edition_client.get("/api/photos", params={**HIDE_OFF, "semantic_threshold": "0.2"})
        assert resp.status_code == 400

    def test_the_query_is_stripped(self, edition_client, library, encoder):
        assert _listed(edition_client, semantic_q=f"  {QUERY}  ") == _paths(GATED)
        encoder.assert_called_with(QUERY)

    def test_disabled_semantic_search_is_400_not_the_whole_library(self, edition_client, library, encoder):
        with mock.patch.dict("api.routers.gallery.VIEWER_CONFIG", {"features": {"show_semantic_search": False}}):
            assert _get(edition_client).status_code == 400

    def test_a_busy_model_is_503(self, edition_client, library):
        with mock.patch("api.routers.search._encode_text", side_effect=AcceleratorBusy("busy")):
            assert _get(edition_client).status_code == 503

    def test_an_encoder_failure_is_503_never_the_whole_library(self, edition_client, library):
        with mock.patch("api.routers.search._encode_text", side_effect=RuntimeError("no model")):
            assert _get(edition_client).status_code == 503

    def test_no_semantic_keys_leaves_the_listing_unchanged(self, edition_client, library, encoder):
        resp = edition_client.get("/api/photos", params={**HIDE_OFF, "path_prefix": PREFIX.rstrip("/")})
        assert resp.json()["total"] == TOTAL
        encoder.assert_not_called()
        assert all("similarity" not in p for p in resp.json()["photos"])

    def test_by_paths_still_rejects_the_semantic_keys(self, edition_client, library):
        resp = edition_client.post("/api/photos/by_paths", json={
            "paths": [_path(0)], "filters": {"semantic_q": QUERY}})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# semantic_candidates
# ---------------------------------------------------------------------------

BIG = 4200
BIG_PASSING = 4150
BIG_PREFIX = "/semf-big/"


def _big_cos(i: int) -> float:
    return 0.3 + 0.6 * (i / BIG_PASSING) if i < BIG_PASSING else 0.05


@pytest.fixture()
def big_library(seed_photos_prefix):
    seed_photos_prefix(BIG_PREFIX, [
        {"path": f"{BIG_PREFIX}p{i:05d}.jpg", "filename": f"p{i:05d}.jpg",
         "clip_embedding": _vector(_big_cos(i)).tobytes()}
        for i in range(BIG)])
    return {f"{BIG_PREFIX}p{i:05d}.jpg" for i in range(BIG_PASSING)}


@pytest.fixture()
def vec_table(big_library):
    """``photos_vec`` over the big library, dropped again on teardown."""
    if not HAS_SQLITE_VEC:
        pytest.skip("sqlite-vec is not installed")
    with get_connection(DEFAULT_DB_PATH, row_factory=False) as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'photos_vec'").fetchone() is None
        conn.execute(f"CREATE VIRTUAL TABLE photos_vec USING vec0("
                     f"path TEXT PRIMARY KEY, embedding float[{DIM}] distance_metric=cosine)")
        conn.executemany(
            "INSERT INTO photos_vec (path, embedding) VALUES (?, ?)",
            conn.execute("SELECT path, clip_embedding FROM photos WHERE path LIKE ?",
                         (BIG_PREFIX + "%",)).fetchall())
        conn.commit()
    yield
    with get_connection(DEFAULT_DB_PATH, row_factory=False) as conn:
        conn.execute("DROP TABLE IF EXISTS photos_vec")
        conn.commit()


def _candidates(q="zzqq", threshold=0.2, user_id=None):
    async def run():
        async with get_async_db() as conn:
            return await search.semantic_candidates(conn, q, threshold, user_id)
    return asyncio.run(run())


class TestSemanticCandidates:
    def test_numpy_path_is_uncapped(self, big_library, encoder):
        with mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)):
            found = _candidates()
        assert set(found.embedding) == big_library and len(found.embedding) > 4096

    def test_vec_path_runs_and_is_uncapped(self, vec_table, big_library, encoder):
        with mock.patch.object(search, "_vec_threshold_set", wraps=search._vec_threshold_set) as vec, \
                mock.patch.object(search, "_search_numpy", wraps=search._search_numpy) as numpy_path:
            found = _candidates()
        assert vec.call_count == 1 and numpy_path.call_count == 0
        assert len(found.embedding) > 4096
        assert set(found.embedding) == big_library

    def test_vec_and_numpy_return_the_same_set_and_scores(self, vec_table, big_library, encoder):
        with mock.patch.object(search, "_vec_threshold_set", wraps=search._vec_threshold_set) as vec:
            via_vec = _candidates()
        assert vec.call_count == 1
        search._reset_text_encoder_cache()
        with mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)):
            via_numpy = _candidates()
        assert set(via_vec.embedding) == set(via_numpy.embedding)
        for path, similarity in via_numpy.embedding.items():
            assert via_vec.embedding[path] == pytest.approx(similarity, abs=1e-4)

    def test_a_small_vec_result_skips_the_full_scan(self, vec_table, big_library, encoder):
        # Threshold 0.85 leaves well under 4096 hits: the KNN answer is already complete.
        found = _candidates(threshold=0.85)
        expected = {p for i, p in enumerate(sorted(big_library)) if _big_cos(i) >= 0.85}
        assert set(found.embedding) == expected and 0 < len(expected) < 4096

    def test_a_dimension_mismatch_is_an_empty_set_on_the_vec_path(self, vec_table, big_library):
        with mock.patch("api.routers.search._encode_text", return_value=_query_vector(4)):
            assert _candidates().embedding == {}

    def test_a_dimension_mismatch_is_an_empty_set_on_the_numpy_path(self, big_library):
        with mock.patch("api.routers.search._encode_text", return_value=_query_vector(4)), \
                mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)):
            assert _candidates().embedding == {}

    def test_manual_tag_hits_join_the_set_without_an_embedding_score(self, big_library, encoder):
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES (?, 'redsun', 'user')",
                         (f"{BIG_PREFIX}p04199.jpg",))
        try:
            with mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)):
                found = _candidates(q="redsun")
        finally:
            with sqlite3.connect(DEFAULT_DB_PATH) as conn:
                conn.execute("DELETE FROM photo_manual_tags WHERE photo_path LIKE ?", (BIG_PREFIX + "%",))
        tagged = f"{BIG_PREFIX}p04199.jpg"
        assert tagged in found.blended and tagged not in found.embedding
        assert found.blended[tagged] == pytest.approx(0.3)


class TestCandidatesCache:
    def test_a_repeat_is_served_from_the_cache(self, library, encoder):
        with mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)):
            first = _candidates(threshold=THRESHOLD)
            second = _candidates(threshold=THRESHOLD)
        assert first is second and encoder.call_count == 1

    def test_the_cache_is_per_threshold_and_per_user(self, library, encoder):
        with mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)):
            _candidates(threshold=THRESHOLD)
            _candidates(threshold=0.1)
            _candidates(threshold=THRESHOLD, user_id="someone")
        assert encoder.call_count == 3

    def test_a_database_commit_invalidates_it(self, library, encoder):
        with mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)):
            _candidates(threshold=THRESHOLD)
            with sqlite3.connect(DEFAULT_DB_PATH) as conn:
                conn.execute("UPDATE photos SET aggregate = aggregate WHERE path = ?", (_path(0),))
            _candidates(threshold=THRESHOLD)
        assert encoder.call_count == 2

    def test_it_holds_four_entries(self, library, encoder):
        with mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)):
            for i in range(5):
                _candidates(q=f"query {i}", threshold=THRESHOLD)
            assert len(search._candidates_cache) == 4
            _candidates(q="query 0", threshold=THRESHOLD)  # evicted: encodes again
        assert encoder.call_count == 6

    def test_it_expires_after_the_ttl(self, library, encoder):
        with mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)):
            _candidates(threshold=THRESHOLD)
            with mock.patch.object(search, "_CANDIDATES_CACHE_TTL", -1.0):
                _candidates(threshold=THRESHOLD)
        assert encoder.call_count == 2

    def test_an_encoder_reset_clears_it(self, library, encoder):
        with mock.patch("api.routers.search._check_vec_available", mock.AsyncMock(return_value=False)):
            _candidates(threshold=THRESHOLD)
            search._reset_text_encoder_cache()
            assert len(search._candidates_cache) == 0


def test_review_progress_respects_semantic_gate(edition_client, library, encoder):
    response = edition_client.get('/api/photos/review_progress', params={
        **HIDE_OFF, 'path_prefix': PREFIX, 'semantic_q': QUERY, 'semantic_threshold': THRESHOLD,
        'review_status': 'undecided', 'hide_rejected': '1',
    })
    assert response.status_code == 200, response.text
    rejected = sum(i % 4 == 1 for i in GATED)
    assert response.json() == {'total': len(GATED), 'undecided': len(GATED) - rejected, 'kept': 0, 'rejected': rejected}
