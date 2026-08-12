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

from api.routers.burst_culling import _score_shoot_types

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
