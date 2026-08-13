"""Tests for the shoot-type suggestion endpoint (GET /api/culling/suggest_profile).

Covers the genre inference over stored labels (categories, narrative moments,
face counts, capture hour), the confidence ordering between a pure and a diluted
scope, the album / date-window scope filters, the empty-scope and
below-threshold null answers, and the null answer for a custom ``cull_profiles``
set. Auth goes through the conftest fixtures — never mock.patch on auth
dependencies.
"""

import sqlite3
from contextlib import contextmanager
from unittest import mock

import pytest

import api.db_helpers as db_helpers
from api.db_helpers import scope_cache_key
from api.routers.burst_culling import (
    _query_shoot_type_evidence, _score_shoot_types, _shoot_type_evidence,
)

_EVIDENCE_PREFIX = "shoot_type_evidence_"

_SCHEMA = """
    CREATE TABLE photos (
        path TEXT PRIMARY KEY, filename TEXT, date_taken TEXT,
        category TEXT, narrative_moment TEXT, face_count INTEGER DEFAULT 0,
        face_ratio REAL
    );
    CREATE TABLE albums (
        id INTEGER PRIMARY KEY, user_id TEXT, name TEXT, description TEXT,
        cover_photo_path TEXT, is_smart INTEGER DEFAULT 0, smart_filter_json TEXT,
        share_token TEXT, created_at TEXT, updated_at TEXT, scoring_context TEXT
    );
    CREATE TABLE album_photos (
        id INTEGER PRIMARY KEY, album_id INTEGER, photo_path TEXT,
        position INTEGER, added_at TEXT,
        UNIQUE(album_id, photo_path)
    );
    CREATE TABLE stats_cache (
        key TEXT PRIMARY KEY, value TEXT, updated_at REAL
    );
"""

_NOON = "2024:06:15 12:00:00"
_NIGHT = "2024:06:15 22:30:00"


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


def _db(photos):
    """In-memory library. ``photos`` are (path, category, moment, face_count, date_taken)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for path, category, moment, faces, date_taken in photos:
        conn.execute(
            "INSERT INTO photos (path, filename, date_taken, category, "
            "narrative_moment, face_count, face_ratio) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (path, path.lstrip('/'), date_taken, category, moment, faces,
             0.2 if faces else None),
        )
    conn.commit()
    return conn


def _wedding_photos(count, prefix="/w", date_taken=_NOON):
    """A face-driven shoot: portraits and group shots labelled with wedding moments."""
    labels = [('portrait', 'couple_portraits', 2), ('group_portrait', 'family_formals', 6),
              ('portrait_bw', 'vows', 2), ('portrait', 'ceremony', 3)]
    return [
        (f"{prefix}{i}.jpg", *labels[i % len(labels)], date_taken)
        for i in range(count)
    ]


def _wildlife_photos(count, prefix="/a", date_taken=_NOON):
    return [
        (f"{prefix}{i}.jpg", 'wildlife', 'nature_wildlife', 0, date_taken)
        for i in range(count)
    ]


def _get(client, conn, params=None):
    with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
        return client.get("/api/culling/suggest_profile", params=params or {})


# ---------------------------------------------------------------------------
# Scoring unit tests (no HTTP, no DB)
# ---------------------------------------------------------------------------

class TestScoreShootTypes:
    def _row(self, category=None, moment=None, n=1, crowd=0, night=0):
        return {'category': category, 'narrative_moment': moment, 'n': n,
                'crowd_faces': crowd, 'night_faces': night}

    def test_a_first_tier_label_counts_a_whole_photo(self):
        scores, evidence, photos = _score_shoot_types([self._row('wildlife', 'other', n=4)])
        assert photos == 4
        assert scores['wildlife'] == 4.0
        assert evidence['wildlife'] == 4

    def test_support_signals_count_half(self):
        scores, evidence, _ = _score_shoot_types(
            [self._row('landscape', 'other', n=10, night=10)])
        assert scores['concert'] == 5.0
        assert evidence['concert'] == 10

    def test_a_first_tier_photo_never_also_counts_its_support_signal(self):
        # Every frame is a night concert: it must score 1.0, not 1.5.
        scores, _, photos = _score_shoot_types(
            [self._row('concert', 'concert', n=8, night=8)])
        assert scores['concert'] == 8.0
        assert photos == 8

    def test_unlabelled_photos_score_nothing(self):
        scores, evidence, photos = _score_shoot_types([self._row(None, None, n=5)])
        assert photos == 5
        assert set(scores.values()) == {0.0}
        assert set(evidence.values()) == {0}


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

class TestGenreInference:
    def test_a_face_driven_shoot_suggests_the_wedding_preset(self, edition_client):
        conn = _db(_wedding_photos(20))
        body = _get(edition_client, conn).json()
        assert body['profile'] == 'wedding'
        assert body['confidence'] == 1.0
        assert body['evidence']['photos'] == 20
        assert body['evidence']['wedding'] == 20

    def test_an_animal_shoot_suggests_the_wildlife_preset(self, edition_client):
        conn = _db(_wildlife_photos(12))
        body = _get(edition_client, conn).json()
        assert body['profile'] == 'wildlife'
        assert body['evidence']['wildlife'] == 12

    def test_a_sports_shoot_suggests_the_sports_preset(self, edition_client):
        conn = _db([(f"/s{i}.jpg", 'sports', 'sports', 0, _NOON) for i in range(10)])
        assert _get(edition_client, conn).json()['profile'] == 'sports'

    def test_night_frames_with_people_suggest_the_concert_preset(self, edition_client):
        # No concert category anywhere: the answer rides on the support signal
        # alone (half weight), which still clears the dominance floor.
        conn = _db([(f"/n{i}.jpg", 'night', 'other', 2, _NIGHT) for i in range(10)])
        body = _get(edition_client, conn).json()
        assert body['profile'] == 'concert'
        assert body['confidence'] == 0.5

    def test_the_wedding_vocabulary_comes_from_config_not_the_category(self, edition_client):
        # Moments only, no face categories: the wedding event type's own labels
        # are read from narrative_moments.event_types.
        conn = _db([(f"/v{i}.jpg", 'default', 'first_dance', 0, _NOON) for i in range(8)])
        assert _get(edition_client, conn).json()['profile'] == 'wedding'


class TestConfidenceOrdering:
    def test_a_pure_scope_outranks_the_same_shoot_diluted(self, edition_client):
        pure = _get(edition_client, _db(_wedding_photos(20))).json()
        diluted = _get(
            edition_client,
            _db(_wedding_photos(10) + _wildlife_photos(10)),
        ).json()
        assert pure['profile'] == 'wedding'
        assert diluted['confidence'] < pure['confidence']

    def test_an_evenly_mixed_library_names_no_preset(self, edition_client):
        # Four genres at a fifth of the scope each: nothing is dominant.
        photos = (
            _wedding_photos(4)
            + _wildlife_photos(4)
            + [(f"/s{i}.jpg", 'sports', 'sports', 0, _NOON) for i in range(4)]
            + [(f"/c{i}.jpg", 'concert', 'concert', 0, _NOON) for i in range(4)]
            + [(f"/l{i}.jpg", 'landscape', 'other', 0, _NOON) for i in range(4)]
        )
        body = _get(edition_client, _db(photos)).json()
        assert body['profile'] is None
        assert body['confidence'] == 0.2
        assert body['evidence']['photos'] == 20


class TestScopeFilters:
    def _mixed_album_db(self):
        conn = _db(_wedding_photos(10, prefix="/album/w") + _wildlife_photos(30))
        conn.execute("INSERT INTO albums (id, user_id, name) VALUES (1, 'test', 'Shoot')")
        for i in range(10):
            conn.execute(
                "INSERT INTO album_photos (album_id, photo_path, position) VALUES (1, ?, ?)",
                (f"/album/w{i}.jpg", i),
            )
        conn.commit()
        return conn

    def test_album_scope_answers_for_the_album_not_the_library(self, edition_client):
        conn = self._mixed_album_db()
        assert _get(edition_client, conn).json()['profile'] == 'wildlife'
        scoped = _get(edition_client, conn, {'album_id': 1}).json()
        assert scoped['profile'] == 'wedding'
        assert scoped['evidence']['photos'] == 10

    def test_an_unknown_album_is_rejected(self, edition_client):
        conn = self._mixed_album_db()
        assert _get(edition_client, conn, {'album_id': 99}).status_code == 404

    def test_date_window_answers_for_the_window_only(self, edition_client):
        conn = _db(
            _wedding_photos(10, date_taken="2024:06:15 12:00:00")
            + _wildlife_photos(30, date_taken="2024:08:01 12:00:00")
        )
        scoped = _get(edition_client, conn, {
            'date_from': '2024:06:01 00:00:00', 'date_to': '2024:06:30 23:59:59',
        }).json()
        assert scoped['profile'] == 'wedding'
        assert scoped['evidence']['photos'] == 10


class TestNoAnswer:
    def test_an_empty_scope_suggests_nothing(self, edition_client):
        body = _get(edition_client, _db([])).json()
        assert body['profile'] is None
        assert body['confidence'] == 0.0
        assert body['evidence'] == {'photos': 0, 'wedding': 0, 'sports': 0,
                                    'concert': 0, 'wildlife': 0}

    def test_a_genre_below_the_dominance_floor_suggests_nothing(self, edition_client):
        conn = _db(_wedding_photos(4) + [
            (f"/l{i}.jpg", 'landscape', 'scenic_landscape', 0, _NOON) for i in range(36)
        ])
        body = _get(edition_client, conn).json()
        assert body['profile'] is None
        assert body['confidence'] == 0.1
        assert body['evidence']['wedding'] == 4

    def test_a_custom_profile_set_without_the_matching_preset_suggests_nothing(self, edition_client):
        conn = _db(_wedding_photos(20))
        with mock.patch("api.routers.burst_culling._get_cull_profiles",
                        return_value=({'my_preset': {'strictness': 40}}, 'my_preset')):
            body = _get(edition_client, conn).json()
        # The evidence still stands; only the preset name is unavailable.
        assert body['profile'] is None
        assert body['confidence'] == 1.0
        assert body['evidence']['wedding'] == 20


# ---------------------------------------------------------------------------
# Evidence cache (stats_cache) — SEV3 perf fix: _shoot_type_evidence's GROUP BY
# walked the whole photos table (22.9s cold on 126k photos); a second call for
# the same scope must be answered from stats_cache, not by re-running it.
# ---------------------------------------------------------------------------

class TestEvidenceCache:
    def test_a_second_call_is_served_from_cache_without_rerunning_the_aggregate(self):
        conn = _db(_wedding_photos(20))
        with mock.patch(
            "api.routers.burst_culling._query_shoot_type_evidence",
            wraps=_query_shoot_type_evidence,
        ) as spy:
            first = _shoot_type_evidence(conn, None, None, None, None)
            second = _shoot_type_evidence(conn, None, None, None, None)
        assert spy.call_count == 1
        assert first == second

    def test_a_cache_hit_still_answers_the_endpoint_correctly(self, edition_client):
        conn = _db(_wedding_photos(20))
        first = _get(edition_client, conn).json()
        second = _get(edition_client, conn).json()
        assert first == second
        assert second['profile'] == 'wedding'

    def test_an_expired_cache_entry_is_recomputed(self):
        conn = _db(_wedding_photos(20))
        _shoot_type_evidence(conn, None, None, None, None)
        conn.execute("UPDATE stats_cache SET updated_at = 0 WHERE key LIKE 'shoot_type_evidence_%'")
        conn.commit()
        with mock.patch(
            "api.routers.burst_culling._query_shoot_type_evidence",
            wraps=_query_shoot_type_evidence,
        ) as spy:
            _shoot_type_evidence(conn, None, None, None, None)
        assert spy.call_count == 1

    def test_cache_key_varies_by_album_scope(self):
        conn = _db(_wedding_photos(10, prefix="/album/w") + _wildlife_photos(30))
        conn.execute("INSERT INTO albums (id, user_id, name) VALUES (1, 'test', 'Shoot')")
        for i in range(10):
            conn.execute(
                "INSERT INTO album_photos (album_id, photo_path, position) VALUES (1, ?, ?)",
                (f"/album/w{i}.jpg", i),
            )
        conn.commit()
        whole_library = _shoot_type_evidence(conn, None, None, None, None)
        album_scoped = _shoot_type_evidence(conn, None, 1, None, None)
        assert whole_library != album_scoped
        keys = {r['key'] for r in conn.execute("SELECT key FROM stats_cache").fetchall()}
        assert len(keys) == 2

    def test_cache_key_varies_by_date_window(self):
        conn = _db(_wedding_photos(20))
        _shoot_type_evidence(conn, None, None, None, None)
        _shoot_type_evidence(conn, None, None, '2024:06:01 00:00:00', '2024:06:30 23:59:59')
        keys = {r['key'] for r in conn.execute("SELECT key FROM stats_cache").fetchall()}
        assert len(keys) == 2

    def test_cache_key_varies_by_user_id(self):
        conn = _db(_wedding_photos(5))
        _shoot_type_evidence(conn, 'user-a', None, None, None)
        _shoot_type_evidence(conn, 'user-b', None, None, None)
        keys = {r['key'] for r in conn.execute("SELECT key FROM stats_cache").fetchall()}
        assert len(keys) == 2


class TestDateWindowValidation:
    """The window is a pair of raw EXIF timestamps, the only shape a scan writes
    and the shape the scenes feed hands back. Anything else was accepted, matched
    nothing, and was still cached under its own key — so the key set an anonymous
    caller could write was whatever they cared to type."""

    def test_the_shape_the_scenes_feed_sends_is_accepted(self, edition_client):
        conn = _db(_wedding_photos(10))
        response = _get(edition_client, conn, {
            'date_from': '2024:06:01 00:00:00', 'date_to': '2024:06:30 23:59:59',
        })
        assert response.status_code == 200

    @pytest.mark.parametrize("value", [
        "2024-06-01",                 # ISO date: the gallery's filter shape, not this one
        "2024-06-01T00:00:00",        # ISO timestamp
        "2024:06:01",                 # EXIF date without the time half
        "2024:06:01 00:00:00 ",       # trailing space
        "junk",
        "' OR 1=1 --",
        "x" * 4096,                   # the unbounded key this endpoint used to store
    ])
    def test_any_other_shape_is_rejected(self, edition_client, value):
        conn = _db(_wedding_photos(10))
        assert _get(edition_client, conn, {'date_from': value}).status_code == 422
        assert _get(edition_client, conn, {'date_to': value}).status_code == 422

    def test_a_rejected_window_writes_no_cache_row(self, edition_client):
        conn = _db(_wedding_photos(10))
        _get(edition_client, conn, {'date_from': 'x' * 4096})
        assert conn.execute("SELECT COUNT(*) FROM stats_cache").fetchone()[0] == 0

    def test_an_absent_window_is_still_allowed(self, edition_client):
        conn = _db(_wedding_photos(10))
        assert _get(edition_client, conn).status_code == 200


class TestScopeCacheKeyShape:
    """The scope reaches the cache key from the query string, so the key must be
    fixed-width whatever arrives — and keep its prefix, which is how the cull
    paths invalidate."""

    def test_the_key_is_a_prefix_and_a_sha256_digest(self):
        key = scope_cache_key('shoot_type_evidence', None, None, None, None)
        assert key.startswith(_EVIDENCE_PREFIX)
        digest = key[len(_EVIDENCE_PREFIX):]
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")

    def test_key_length_does_not_follow_the_input_length(self):
        short = scope_cache_key('scenes', 1, 'a', 'b', 'c')
        long = scope_cache_key('scenes', 1, 'a' * 10_000, 'b' * 10_000, 'c')
        assert len(short) == len(long)

    def test_distinct_scopes_do_not_collide(self):
        keys = {
            scope_cache_key('scenes', 1, None, None, None),
            scope_cache_key('scenes', 2, None, None, None),
            scope_cache_key('scenes', None, '2024:06:01 00:00:00', None, None),
            scope_cache_key('scenes', None, None, '2024:06:01 00:00:00', None),
            scope_cache_key('scenes', None, None, None, 'user-a'),
        }
        assert len(keys) == 5

    def test_an_absent_part_is_distinct_from_an_empty_one(self):
        assert scope_cache_key('scenes', None) != scope_cache_key('scenes', '')

    def test_a_shifted_boundary_does_not_collide(self):
        """Concatenation alone would make ('ab', 'c') and ('a', 'bc') one key."""
        assert scope_cache_key('scenes', 'ab', 'c') != scope_cache_key('scenes', 'a', 'bc')

    def test_the_evidence_cache_stores_that_shape(self):
        conn = _db(_wedding_photos(5))
        _shoot_type_evidence(conn, None, None, '2024:06:01 00:00:00', None)
        key = conn.execute("SELECT key FROM stats_cache").fetchone()['key']
        assert key.startswith(_EVIDENCE_PREFIX)
        assert len(key) == len(_EVIDENCE_PREFIX) + 64


class TestInvisibleScopesAreNotCached:
    """A caller who can see nothing gets the same empty answer for every scope
    they could name, so a cache row for one stores nothing but the scope string
    — which is exactly the write an anonymous caller on a locked install must
    not be able to make at will."""

    def test_no_cache_row_is_written_for_a_caller_who_sees_nothing(self):
        conn = _db(_wedding_photos(5))
        with mock.patch.dict(db_helpers.VIEWER_CONFIG, {'password': 'secret'}):
            assert _shoot_type_evidence(conn, None, None, None, None) == []
        assert conn.execute("SELECT COUNT(*) FROM stats_cache").fetchone()[0] == 0

    def test_distinct_invisible_scopes_still_write_nothing(self):
        conn = _db(_wedding_photos(5))
        with mock.patch.dict(db_helpers.VIEWER_CONFIG, {'password': 'secret'}):
            for day in range(1, 20):
                _shoot_type_evidence(
                    conn, None, None, f"2024:06:{day:02d} 00:00:00", None)
        assert conn.execute("SELECT COUNT(*) FROM stats_cache").fetchone()[0] == 0

    def test_a_visible_caller_still_gets_a_cache_row(self):
        conn = _db(_wedding_photos(5))
        assert _shoot_type_evidence(conn, None, None, None, None)
        assert conn.execute("SELECT COUNT(*) FROM stats_cache").fetchone()[0] == 1


class TestShootTypeEvidenceIndex:
    def test_the_covering_index_exists_after_init_database(self, tmp_path):
        from db.schema import init_database
        db_path = str(tmp_path / "shoot_type_idx.db")
        init_database(db_path)
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='index' AND name='idx_shoot_type_evidence'"
            ).fetchone()
        assert row is not None
        assert row[0] == (
            "CREATE INDEX idx_shoot_type_evidence ON photos"
            "(category, narrative_moment, face_count, date_taken)"
        )
