"""Tests for burst culling helpers and endpoints (api/routers/burst_culling.py)."""

import sqlite3
from contextlib import contextmanager
from unittest import mock

import pytest

from api.routers.burst_culling import (
    _CULLING_GROUP_BY,
    _CULLING_SORT_DESC,
    _CULLING_SORTS,
    _compute_burst_score,
    _compute_cull_reason,
    _culling_sort_key,
    _culling_sort_reverse,
    _format_group,
    _group_sequence_kind,
    _order_group_photos_by_capture,
)
from db.schema import init_database


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


def _real_schema_db(tmp_path, var_limit=None):
    """An empty database carrying the real schema, open for the whole test.

    Never a hand-rolled ``CREATE TABLE photos``: ``build_photo_select_columns``
    intersects the optional column list with the columns the database actually
    has, so a short fixture makes an endpoint legitimately drop a field and the
    assertion pass for the wrong reason -- the test stops testing rather than
    turning red.

    ``var_limit`` constrains ``SQLITE_LIMIT_VARIABLE_NUMBER`` so a query that
    forgot to chunk its ``IN (...)`` list fails here instead of only on the
    builds whose limit is lower than this one's.
    """
    db_path = str(tmp_path / "burst_culling.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if var_limit is not None:
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, var_limit)
    return conn


# Every culling feed reports each frame's pending panorama correction, so this
# side table is part of the schema they query even when no correction exists.
_SEQUENCE_OVERRIDES_SCHEMA = """
    CREATE TABLE photo_sequence_overrides (
        photo_path TEXT PRIMARY KEY, sequence_kind TEXT, override_group_key TEXT,
        source TEXT, created_at TEXT, created_by TEXT, applied_at TEXT
    );
"""


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestComputeBurstScore:
    def test_perfect_photo_no_blink(self):
        photo = {'aggregate': 10, 'aesthetic': 10, 'tech_sharpness': 10, 'is_blink': 0}
        score = _compute_burst_score(photo)
        # 10*0.4 + 10*0.25 + 10*0.2 + 10*0.15 = 10.0
        assert score == pytest.approx(10.0)

    def test_blink_penalty(self):
        no_blink = {'aggregate': 8, 'aesthetic': 8, 'tech_sharpness': 8, 'is_blink': 0}
        blink = {'aggregate': 8, 'aesthetic': 8, 'tech_sharpness': 8, 'is_blink': 1}
        score_ok = _compute_burst_score(no_blink)
        score_blink = _compute_burst_score(blink)
        # blink_score goes from 10 to 0, so penalty is 10 * 0.15 = 1.5
        assert score_ok - score_blink == pytest.approx(1.5)

    def test_none_values_treated_as_zero(self):
        photo = {'aggregate': None, 'aesthetic': None, 'tech_sharpness': None, 'is_blink': None}
        score = _compute_burst_score(photo)
        # All zero except blink_score = 10 (not blinked) * 0.15 = 1.5
        assert score == pytest.approx(1.5)

    def test_missing_keys_treated_as_zero(self):
        score = _compute_burst_score({})
        assert score == pytest.approx(1.5)


class TestFormatGroup:
    def test_sorts_by_burst_score_descending(self):
        photos = [
            {'path': '/low.jpg', 'filename': 'low.jpg', 'aggregate': 2, 'aesthetic': 2,
             'tech_sharpness': 2, 'is_blink': 0, 'is_burst_lead': 0, 'date_taken': '2024:01:01'},
            {'path': '/high.jpg', 'filename': 'high.jpg', 'aggregate': 10, 'aesthetic': 10,
             'tech_sharpness': 10, 'is_blink': 0, 'is_burst_lead': 0, 'date_taken': '2024:01:01'},
        ]
        result = _format_group(photos, 42)
        assert result['burst_id'] == 42
        assert result['count'] == 2
        assert result['best_path'] == '/high.jpg'
        assert result['photos'][0]['path'] == '/high.jpg'

    def test_empty_photos_list(self):
        result = _format_group([], 1)
        assert result['count'] == 0
        assert result['best_path'] is None
        assert result['photos'] == []

    def test_burst_score_is_rounded(self):
        photos = [
            {'path': '/a.jpg', 'filename': 'a.jpg', 'aggregate': 7.3, 'aesthetic': 8.1,
             'tech_sharpness': 6.7, 'is_blink': 0, 'is_burst_lead': 1, 'date_taken': '2024:06:15'},
        ]
        result = _format_group(photos, 5)
        score = result['photos'][0]['burst_score']
        # Should be rounded to 2 decimal places
        assert score == round(score, 2)

    def test_attaches_cull_reason_to_every_photo(self):
        photos = [
            {'path': '/low.jpg', 'filename': 'low.jpg', 'aggregate': 2, 'aesthetic': 2,
             'tech_sharpness': 2, 'is_blink': 0, 'is_burst_lead': 0, 'date_taken': '2024:01:01'},
            {'path': '/high.jpg', 'filename': 'high.jpg', 'aggregate': 10, 'aesthetic': 10,
             'tech_sharpness': 10, 'is_blink': 0, 'is_burst_lead': 0, 'date_taken': '2024:01:01'},
        ]
        result = _format_group(photos, 7)
        # Best photo (first after sort) gets the 'best' key.
        assert result['photos'][0]['path'] == '/high.jpg'
        assert result['photos'][0]['cull_reason']['key'] == 'best'
        # The weaker photo gets a non-'best' reason.
        assert result['photos'][1]['path'] == '/low.jpg'
        assert result['photos'][1]['cull_reason']['key'] != 'best'


class TestComputeCullReason:
    def _best(self, **kw):
        base = {'path': '/best.jpg', 'aggregate': 9.0, 'aesthetic': 9.0,
                'tech_sharpness': 9.0, 'is_blink': 0, 'face_count': 0}
        base.update(kw)
        return base

    def test_best_photo_returns_best_key(self):
        best = self._best()
        assert _compute_cull_reason(best, best) == {'key': 'best', 'value': None}

    def test_best_matched_by_path(self):
        best = self._best()
        same_path = dict(best)
        assert _compute_cull_reason(same_path, best)['key'] == 'best'

    def test_blink_flag_wins(self):
        best = self._best()
        photo = self._best(path='/x.jpg', is_blink=1)
        assert _compute_cull_reason(photo, best)['key'] == 'eyes_closed'

    def test_eyes_closed_score(self):
        best = self._best(face_count=1, eyes_open_score=9.0)
        photo = self._best(path='/x.jpg', face_count=1, eyes_open_score=2.0)
        assert _compute_cull_reason(photo, best)['key'] == 'eyes_closed'

    def test_eyes_score_ignored_without_face(self):
        # face_count=0 means eyes_open_score must not trigger eyes_closed.
        best = self._best(eyes_open_score=9.0)
        photo = self._best(path='/x.jpg', eyes_open_score=1.0, tech_sharpness=9.0,
                           aesthetic=9.0, aggregate=9.0)
        assert _compute_cull_reason(photo, best)['key'] != 'eyes_closed'

    def test_soft_when_sharpness_lower(self):
        best = self._best(tech_sharpness=9.0)
        photo = self._best(path='/x.jpg', tech_sharpness=7.0)
        assert _compute_cull_reason(photo, best)['key'] == 'soft'

    def test_expression_when_poorer_expression(self):
        # Face photo, equally sharp but a weaker expression than the best frame.
        best = self._best(face_count=1, eyes_open_score=9.0, expression_score=5.0)
        photo = self._best(path='/x.jpg', face_count=1, eyes_open_score=9.0,
                           tech_sharpness=9.0, expression_score=3.0)
        assert _compute_cull_reason(photo, best)['key'] == 'expression'

    def test_lower_aesthetic(self):
        best = self._best(aesthetic=9.0)
        photo = self._best(path='/x.jpg', aesthetic=8.0)
        assert _compute_cull_reason(photo, best)['key'] == 'lower_aesthetic'

    def test_lower_overall_catch_all(self):
        best = self._best(aggregate=9.0)
        photo = self._best(path='/x.jpg', aggregate=8.0)
        assert _compute_cull_reason(photo, best)['key'] == 'lower_overall'

    def test_near_duplicate_when_no_clear_defect(self):
        best = self._best()
        photo = self._best(path='/x.jpg')  # identical metrics, different path
        assert _compute_cull_reason(photo, best)['key'] == 'near_duplicate'


class TestGroupSequenceKind:
    """A group is only called a bracket when every frame is one. A burst that
    merely contains a bracket still needs culling, and labelling it would tell
    the user not to choose exactly where choosing is the remaining work."""

    def test_all_frames_bracketed(self):
        assert _group_sequence_kind([{'sequence_kind': 'bracket'}] * 3) == 'bracket'

    def test_mixed_group_is_unlabelled(self):
        photos = [{'sequence_kind': 'bracket'}, {'sequence_kind': 'bracket'}, {'sequence_kind': None}]
        assert _group_sequence_kind(photos) is None

    def test_ordinary_burst_is_unlabelled(self):
        assert _group_sequence_kind([{'sequence_kind': None}] * 3) is None

    def test_missing_key_is_treated_as_unlabelled(self):
        assert _group_sequence_kind([{}, {}]) is None

    def test_format_group_labels_a_wholly_bracketed_burst(self):
        photos = [
            {'path': f'/b{i}.jpg', 'filename': f'b{i}.jpg', 'aggregate': 5.0 + i,
             'sequence_kind': 'bracket', 'sequence_ev_offset': ev}
            for i, ev in enumerate((-2.0, 0.0, 2.0))
        ]
        group = _format_group(photos, burst_group_id=7)
        assert group['sequence_kind'] == 'bracket'
        assert {p['sequence_ev_offset'] for p in group['photos']} == {-2.0, 0.0, 2.0}

    def test_format_group_leaves_an_ordinary_burst_unlabelled(self):
        photos = [{'path': f'/p{i}.jpg', 'filename': f'p{i}.jpg', 'aggregate': 5.0} for i in range(3)]
        assert _format_group(photos, burst_group_id=7)['sequence_kind'] is None


class TestSortDirectionOverride:
    """The direction toggle. An explicit choice wins outright rather than
    XOR-ing with each mode's default, so one button cannot mean 'ascending' in
    some modes and 'descending' in others."""

    def test_empty_direction_keeps_each_mode_natural(self):
        assert _culling_sort_reverse('easiest', '') is True
        assert _culling_sort_reverse('recent', '') is True
        assert _culling_sort_reverse('chronological', '') is False

    def test_explicit_asc_wins_everywhere(self):
        for mode in _CULLING_SORTS:
            assert _culling_sort_reverse(mode, 'asc') is False

    def test_explicit_desc_wins_everywhere(self):
        for mode in _CULLING_SORTS:
            assert _culling_sort_reverse(mode, 'desc') is True

    def test_unknown_direction_falls_back_to_natural(self):
        assert _culling_sort_reverse('chronological', 'sideways') is False
        assert _culling_sort_reverse('best', 'sideways') is True

    def test_reversing_recent_yields_oldest_first(self):
        groups = [
            {'group_id': 1, 'count': 1, 'photos': [{'date_taken': '2024:01:01 08:00:00'}]},
            {'group_id': 2, 'count': 1, 'photos': [{'date_taken': '2025:06:01 12:00:00'}]},
        ]
        groups.sort(key=lambda g: _culling_sort_key(g, 'recent', {}, 0),
                    reverse=_culling_sort_reverse('recent', 'asc'))
        assert [g['group_id'] for g in groups] == [1, 2]


class TestBracketGranularity:
    def test_bracket_is_a_grouping(self):
        assert 'bracket' in _CULLING_GROUP_BY

    def test_bracket_is_not_folded_into_the_merged_feed(self):
        # `all` is burst+similar. A bracket surfacing there would be read as a
        # set of competing takes, which is exactly what the granularity avoids.
        assert _CULLING_GROUP_BY[0] == 'all'


class TestChronologicalSort:
    """`chronological` is the one mode that runs ascending, so the direction map
    matters as much as the key: a regression that reverted it would silently
    serve newest-first under a label promising the opposite."""

    @staticmethod
    def _group(gid, dates):
        return {'group_id': gid, 'count': len(dates),
                'photos': [{'date_taken': d, 'path': f'/{gid}-{i}.jpg', 'burst_score': 1}
                           for i, d in enumerate(dates)]}

    @staticmethod
    def _sorted(groups, sort):
        groups.sort(key=lambda g: _culling_sort_key(g, sort, {}, 0),
                    reverse=_CULLING_SORT_DESC.get(sort, True))
        return [g['group_id'] for g in groups]

    def test_registered_as_a_sort_mode(self):
        assert 'chronological' in _CULLING_SORTS

    def test_only_chronological_runs_ascending(self):
        for mode in ('easiest', 'redundant', 'best', 'recent', 'needs_comparisons'):
            assert _CULLING_SORT_DESC.get(mode, True) is True
        assert _CULLING_SORT_DESC['chronological'] is False

    def test_groups_ordered_by_their_earliest_frame(self):
        groups = [
            self._group(1, ['2025:03:02 10:00:00', '2025:03:02 09:00:00']),
            self._group(2, ['2024:01:01 08:00:00']),
            self._group(3, ['2025:06:01 12:00:00']),
        ]
        assert self._sorted(groups, 'chronological') == [2, 1, 3]

    def test_undated_groups_sink_to_the_end(self):
        groups = [self._group(1, [None]), self._group(2, ['2024:01:01 08:00:00'])]
        assert self._sorted(groups, 'chronological') == [2, 1]

    def test_recent_still_ranks_newest_first(self):
        groups = [
            self._group(1, ['2024:01:01 08:00:00']),
            self._group(2, ['2025:06:01 12:00:00']),
        ]
        assert self._sorted(groups, 'recent') == [2, 1]

    def test_group_photos_reordered_into_capture_order(self):
        groups = [self._group(1, ['2025:03:02 10:00:00', '2025:03:02 09:00:00'])]
        _order_group_photos_by_capture(groups)
        assert [p['date_taken'] for p in groups[0]['photos']] == [
            '2025:03:02 09:00:00', '2025:03:02 10:00:00']

    def test_reordering_preserves_the_recorded_best(self):
        groups = [self._group(1, ['2025:03:02 10:00:00', '2025:03:02 09:00:00'])]
        groups[0]['best_path'] = '/1-0.jpg'  # the later frame scored best
        _order_group_photos_by_capture(groups)
        assert groups[0]['best_path'] == '/1-0.jpg'
        assert groups[0]['photos'][0]['path'] == '/1-1.jpg'


# ---------------------------------------------------------------------------
# Endpoint tests via TestClient
# ---------------------------------------------------------------------------

class TestBurstGroupsEndpoint:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from api import create_app
        from api.auth import get_optional_user, require_edition, CurrentUser

        app = create_app()
        fake_user = CurrentUser(user_id="test", edition_authenticated=True)
        app.dependency_overrides[get_optional_user] = lambda: fake_user
        app.dependency_overrides[require_edition] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_get_burst_groups_empty(self, client):
        """No burst groups returns empty list with pagination."""
        mock_conn = mock.MagicMock()

        # Count query returns 0
        count_row = mock.MagicMock()
        count_row.__getitem__ = lambda self, k: 0
        mock_conn.execute.return_value.fetchone.return_value = count_row

        # Group IDs query returns empty
        mock_conn.execute.return_value.fetchall.return_value = []

        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.burst_culling.get_visibility_clause", return_value=("1=1", [])),
        ):
            resp = client.get("/api/burst-groups")

        assert resp.status_code == 200
        body = resp.json()
        assert body["groups"] == []
        assert body["total_groups"] == 0
        assert body["page"] == 1

    def test_select_burst_group_not_found(self, client):
        """Selecting from a non-existent burst group returns 404."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.burst_culling.get_visibility_clause", return_value=("1=1", [])),
        ):
            resp = client.post(
                "/api/burst-groups/select",
                json={"burst_id": 999, "keep_paths": ["/a.jpg"]},
            )

        assert resp.status_code == 404

    def test_select_burst_invalid_paths(self, client):
        """Selecting paths not in the burst group returns 400."""
        mock_conn = mock.MagicMock()
        # Simulate burst group with paths /a.jpg and /b.jpg
        row_a = mock.MagicMock()
        row_a.__getitem__ = lambda self, k: '/a.jpg'
        row_b = mock.MagicMock()
        row_b.__getitem__ = lambda self, k: '/b.jpg'
        mock_conn.execute.return_value.fetchall.return_value = [row_a, row_b]

        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.burst_culling.get_visibility_clause", return_value=("1=1", [])),
        ):
            resp = client.post(
                "/api/burst-groups/select",
                json={"burst_id": 1, "keep_paths": ["/not_in_group.jpg"]},
            )

        assert resp.status_code == 400
        assert "not in burst group" in resp.json()["detail"].lower()


class TestCullingGroupsEndpoint:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from api import create_app
        from api.auth import get_optional_user, require_edition, CurrentUser

        app = create_app()
        fake_user = CurrentUser(user_id="test", edition_authenticated=True)
        app.dependency_overrides[get_optional_user] = lambda: fake_user
        app.dependency_overrides[require_edition] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_get_culling_groups_exclude_rejected(self, client):
        mock_conn = mock.MagicMock()

        count_row = mock.MagicMock()
        count_row.__getitem__ = lambda self, k: 0
        mock_conn.execute.return_value.fetchone.return_value = count_row
        mock_conn.execute.return_value.fetchall.return_value = []

        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.burst_culling.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.burst_culling.compute_similarity_groups", return_value=[]),
        ):
            resp = client.get("/api/culling-groups?exclude_rejected=true")

        assert resp.status_code == 200
        body = resp.json()
        assert body["groups"] == []
        assert body["total_groups"] == 0

    def test_group_by_scene_returns_scene_groups(self, client):
        mock_conn = mock.MagicMock()
        scene_groups = [{
            "group_id": 0, "type": "scene", "reason": "beach",
            "photos": [{"path": "/s1.jpg"}], "best_path": "/s1.jpg", "count": 1,
            "category": None, "start": "2026:01:01 10:00:00", "end": "2026:01:01 10:05:00",
            "moment": "beach", "moment_confidence": 0.8,
        }]
        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.burst_culling.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.burst_culling._fetch_scene_groups", return_value=scene_groups) as scene_fetch,
        ):
            resp = client.get("/api/culling-groups?group_by=scene")
        assert resp.status_code == 200
        body = resp.json()
        assert [g["type"] for g in body["groups"]] == ["scene"]
        assert body["groups"][0]["moment"] == "beach"
        scene_fetch.assert_called_once()

    def test_group_by_burst_skips_similar_feed(self, client):
        mock_conn = mock.MagicMock()
        burst_groups = [{
            "group_id": 1, "type": "burst", "reason": "burst", "photos": [],
            "best_path": None, "count": 0, "category": None,
        }]
        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.burst_culling.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.burst_culling._fetch_unreviewed_burst_groups", return_value=burst_groups),
            mock.patch("api.routers.burst_culling._count_unreviewed_similar_groups") as similar_count,
        ):
            resp = client.get("/api/culling-groups?group_by=burst")
        assert resp.status_code == 200
        assert [g["type"] for g in resp.json()["groups"]] == ["burst"]
        # The similar feed must not be queried when grouping by burst only.
        similar_count.assert_not_called()

    def test_confirm_group_scene_delegates_to_scene_cull(self, client):
        with mock.patch(
            "api.routers.burst_culling.apply_scene_cull", new_callable=mock.AsyncMock,
        ) as scene_cull:
            scene_cull.return_value = {"status": "ok", "kept": 1, "rejected": 1}
            resp = client.post("/api/culling-groups/confirm", json={
                "group_id": 0, "type": "scene",
                "paths": ["/a.jpg", "/b.jpg"], "keep_paths": ["/a.jpg"],
            })
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "kept": 1, "rejected": 1}
        scene_cull.assert_awaited_once()

    def test_group_by_bracket_serves_bracket_groups(self, client):
        mock_conn = mock.MagicMock()
        bracket_groups = [{
            "group_id": 1, "type": "bracket", "reason": "bracket", "sequence_kind": "bracket",
            "photos": [{"path": "/k0.jpg", "sequence_ev_offset": -2.0},
                       {"path": "/k1.jpg", "sequence_ev_offset": 0.0}],
            "best_path": "/k1.jpg", "count": 2, "category": None,
        }]
        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.burst_culling.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.routers.burst_culling._fetch_bracket_groups",
                       return_value=bracket_groups) as bracket_fetch,
            mock.patch("api.routers.burst_culling._fetch_unreviewed_burst_groups") as burst_fetch,
            mock.patch("api.routers.burst_culling._count_unreviewed_similar_groups") as similar_count,
        ):
            resp = client.get("/api/culling-groups?group_by=bracket")
        assert resp.status_code == 200
        assert [g["type"] for g in resp.json()["groups"]] == ["bracket"]
        bracket_fetch.assert_called_once()
        # A bracket is its own granularity: neither competing-takes feed is consulted.
        burst_fetch.assert_not_called()
        similar_count.assert_not_called()


class TestConfirmBracketGroup:
    """The bracket branch of POST /api/culling-groups/confirm.

    It rejects like the other granularities but records no comparison pairs,
    and is bounded to the paths that really carry the bracket kind — a
    malformed body must not be able to reject arbitrary photos through it.
    """

    _SCHEMA = """
        CREATE TABLE photos (
            path TEXT PRIMARY KEY, filename TEXT, sequence_group_id INTEGER,
            sequence_kind TEXT, sequence_ev_offset REAL, is_rejected INTEGER DEFAULT 0
        );
        CREATE TABLE comparisons (
            id INTEGER PRIMARY KEY, photo_a_path TEXT, photo_b_path TEXT, winner TEXT,
            category TEXT, session_id TEXT, user_id TEXT, source TEXT
        );
    """ + _SEQUENCE_OVERRIDES_SCHEMA

    @staticmethod
    def _db():
        import sqlite3
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(TestConfirmBracketGroup._SCHEMA)
        rungs = (('/k0.jpg', -2.0), ('/k1.jpg', 0.0), ('/k2.jpg', 2.0))
        for path, ev in rungs:
            conn.execute(
                "INSERT INTO photos (path, filename, sequence_group_id, sequence_kind, "
                "sequence_ev_offset) VALUES (?, ?, 1, 'bracket', ?)",
                (path, path.lstrip('/'), ev),
            )
        conn.execute(
            "INSERT INTO photos (path, filename, sequence_kind) VALUES ('/plain.jpg', 'plain.jpg', NULL)"
        )
        conn.commit()
        return conn

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from api import create_app
        from api.auth import get_optional_user, require_edition, CurrentUser

        app = create_app()
        fake_user = CurrentUser(user_id="test", edition_authenticated=True)
        app.dependency_overrides[get_optional_user] = lambda: fake_user
        app.dependency_overrides[require_edition] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    @staticmethod
    def _confirm(client, conn, body):
        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
            mock.patch("api.db_helpers.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
        ):
            return client.post("/api/culling-groups/confirm", json={
                "group_id": 1, "type": "bracket", **body,
            })

    def _rejected(self, conn):
        return {r['path'] for r in conn.execute(
            "SELECT path FROM photos WHERE is_rejected = 1").fetchall()}

    def test_rejects_the_frames_that_were_not_kept(self, client):
        conn = self._db()
        resp = self._confirm(client, conn, {
            "paths": ["/k0.jpg", "/k1.jpg", "/k2.jpg"], "keep_paths": ["/k1.jpg"],
        })
        assert resp.status_code == 200
        assert resp.json() == {'success': True, 'kept': 1, 'rejected': 2, 'skipped': 0}
        assert self._rejected(conn) == {"/k0.jpg", "/k2.jpg"}

    def test_records_no_comparison_pairs(self, client):
        conn = self._db()
        self._confirm(client, conn, {
            "paths": ["/k0.jpg", "/k1.jpg", "/k2.jpg"], "keep_paths": ["/k1.jpg"],
        })
        # Preferring one rung of an exposure ladder describes the exposure, not
        # the photograph; feeding it to the ranker would bias every later ranking.
        assert conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 0

    def test_keeping_every_frame_rejects_nothing(self, client):
        conn = self._db()
        resp = self._confirm(client, conn, {
            "paths": ["/k0.jpg", "/k1.jpg", "/k2.jpg"],
            "keep_paths": ["/k0.jpg", "/k1.jpg", "/k2.jpg"],
        })
        assert resp.json() == {'success': True, 'kept': 3, 'rejected': 0, 'skipped': 0}
        assert self._rejected(conn) == set()

    def test_a_path_outside_the_bracket_is_skipped_not_rejected(self, client):
        conn = self._db()
        resp = self._confirm(client, conn, {
            "paths": ["/k0.jpg", "/plain.jpg"], "keep_paths": [],
        })
        assert resp.json()['skipped'] == 1
        assert self._rejected(conn) == {"/k0.jpg"}

    def test_an_unknown_path_is_skipped_not_rejected(self, client):
        conn = self._db()
        resp = self._confirm(client, conn, {
            "paths": ["/k0.jpg", "/nowhere.jpg"], "keep_paths": [],
        })
        assert resp.json()['skipped'] == 1
        assert self._rejected(conn) == {"/k0.jpg"}

    def test_empty_paths_is_rejected_as_a_bad_request(self, client):
        """`paths` is now a required, non-empty field on the request body

        itself, so a malformed body 422s before the handler -- and before
        `_confirm_sequence_group`'s own `paths is required` guard -- runs.
        """
        conn = self._db()
        resp = self._confirm(client, conn, {"paths": [], "keep_paths": []})
        assert resp.status_code == 422
        assert self._rejected(conn) == set()


class TestConfirmPanoramaServedAsBurst(TestConfirmBracketGroup):
    """A sweep arrives shredded across burst groups, so it is confirmed as one.

    That is the case this whole feature exists to correct, and it is typed
    'burst' by the feed it came through. Branching on that type sent it down the
    path that records comparison pairs -- teaching the ranker that one arbitrary
    slice of a panorama beat the others, which is an artefact of how the set was
    shot rather than anything about the picture.
    """

    @staticmethod
    def _db():
        import sqlite3
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(TestConfirmBracketGroup._SCHEMA)
        conn.execute("ALTER TABLE photos ADD COLUMN burst_group_id INTEGER")
        conn.execute("ALTER TABLE photos ADD COLUMN burst_reviewed INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE photos ADD COLUMN is_burst_lead INTEGER DEFAULT 0")
        # `record_culling_pairs` reads it, so without it the pair-writing path
        # raises and "no pairs were written" would hold for the wrong reason.
        conn.execute("ALTER TABLE photos ADD COLUMN category TEXT DEFAULT 'default'")
        conn.execute("ALTER TABLE photos ADD COLUMN timestamp TEXT")
        for index in range(3):
            conn.execute(
                "INSERT INTO photos (path, filename, sequence_group_id, sequence_kind, "
                "burst_group_id) VALUES (?, ?, 1, 'panorama', 7)",
                (f'/s{index}.jpg', f's{index}.jpg'))
        conn.commit()
        return conn

    @staticmethod
    def _confirm(client, conn, body):
        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
            mock.patch("api.db_helpers.get_visibility_clause", return_value=("1=1", [])),
            mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
        ):
            return client.post("/api/culling-groups/confirm", json={
                "group_id": 7, "type": "burst", **body,
            })

    _SWEEP = ["/s0.jpg", "/s1.jpg", "/s2.jpg"]

    def test_rejects_the_frames_that_were_not_kept(self, client):
        conn = self._db()
        resp = self._confirm(client, conn, {"paths": self._SWEEP, "keep_paths": ["/s1.jpg"]})
        assert resp.status_code == 200
        assert resp.json() == {'success': True, 'kept': 1, 'rejected': 2, 'skipped': 0}
        assert self._rejected(conn) == {"/s0.jpg", "/s2.jpg"}

    def test_records_no_comparison_pairs(self, client):
        conn = self._db()
        self._confirm(client, conn, {"paths": self._SWEEP, "keep_paths": ["/s1.jpg"]})
        assert conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 0

    def test_keeping_every_frame_rejects_nothing(self, client):
        conn = self._db()
        resp = self._confirm(client, conn, {"paths": self._SWEEP, "keep_paths": self._SWEEP})
        assert resp.json() == {'success': True, 'kept': 3, 'rejected': 0, 'skipped': 0}
        assert self._rejected(conn) == set()

    def test_the_burst_group_is_still_marked_reviewed(self, client):
        """Otherwise a set confirmed once comes back unreviewed on the next load."""
        conn = self._db()
        self._confirm(client, conn, {"paths": self._SWEEP, "keep_paths": ["/s1.jpg"]})
        unreviewed = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE burst_group_id = 7 "
            "AND COALESCE(burst_reviewed, 0) = 0").fetchone()[0]
        assert unreviewed == 0

    def test_a_mixed_group_is_still_culled_as_competing_takes(self, client):
        """Only an unmixed set gets the group-wide no-pairs treatment.

        A burst that merely contains a panorama frame still reaches
        `select_burst_photos` -- it is not routed to `_confirm_sequence_group`
        -- so the group as a whole still resolves keep/reject exactly like an
        ordinary burst, and saying otherwise would tell the user not to choose
        where choosing is exactly what is left to do. The panorama frame's own
        protection from comparison pairs is a separate, narrower guarantee --
        see test_sequence_member_is_excluded_from_pairs_but_ordinary_members_still_pair.
        """
        conn = self._db()
        conn.execute("INSERT INTO photos (path, filename, sequence_kind, burst_group_id) "
                     "VALUES ('/other.jpg', 'other.jpg', NULL, 7)")
        conn.commit()
        resp = self._confirm(client, conn, {
            "paths": self._SWEEP + ["/other.jpg"], "keep_paths": ["/s1.jpg"]})
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ok', 'kept': 1, 'rejected': 3}
        assert self._rejected(conn) == {"/s0.jpg", "/s2.jpg", "/other.jpg"}

    def test_sequence_member_is_excluded_from_pairs_but_ordinary_members_still_pair(self, client):
        """A mixed group's sequence-kind frame stays out of comparisons entirely,

        win or lose, while two ordinary members choosing between each other
        still records a pair -- that comparison says nothing about how the set
        was shot, unlike one panorama tile beating another.
        """
        conn = self._db()
        conn.execute("INSERT INTO photos (path, filename, sequence_kind, burst_group_id) "
                     "VALUES ('/other_a.jpg', 'other_a.jpg', NULL, 7)")
        conn.execute("INSERT INTO photos (path, filename, sequence_kind, burst_group_id) "
                     "VALUES ('/other_b.jpg', 'other_b.jpg', NULL, 7)")
        conn.commit()
        resp = self._confirm(client, conn, {
            "paths": self._SWEEP + ["/other_a.jpg", "/other_b.jpg"],
            "keep_paths": ["/other_a.jpg"],
        })
        assert resp.status_code == 200
        assert self._rejected(conn) == {"/s0.jpg", "/s1.jpg", "/s2.jpg", "/other_b.jpg"}
        rows = conn.execute(
            "SELECT photo_a_path, photo_b_path, winner FROM comparisons").fetchall()
        assert len(rows) == 1
        a, b, winner = rows[0]
        assert {a, b} == {'/other_a.jpg', '/other_b.jpg'}
        assert (a if winner == 'a' else b) == '/other_a.jpg'

    # Inherited from TestConfirmBracketGroup but not applicable to a
    # burst-typed feed: a present-but-different-kind path never reaches the
    # per-path skip logic here -- it makes the group mixed instead, which
    # test_a_mixed_group_is_still_culled_as_competing_takes above already
    # covers.
    #
    # `test_empty_paths_is_rejected_as_a_bad_request` used to need the same
    # treatment: before `CullingConfirmBody.paths` carried `Field(min_length=1)`,
    # an empty `paths` skipped `_confirm_sequence_group`'s own guard and fell
    # through to `select_burst_photos`, which ignores `paths` and rejects the
    # whole group instead of 422ing. That bound now lives on the model and is
    # enforced before `type`-based routing ever runs, so the inherited version
    # holds unmodified here too and is left un-shadowed. The burst-specific
    # `test_empty_paths_on_a_burst_feed_is_rejected_as_a_bad_request` below adds
    # the `unreviewed` assertion the inherited one doesn't make.
    test_a_path_outside_the_bracket_is_skipped_not_rejected = None

    def test_an_unknown_path_is_skipped_not_rejected(self, client):
        """An unmatched path is invisible to `_keep_whole_kind_for`, not mixed.

        Unlike a present-but-different-kind path (test_a_mixed_group above),
        a path absent from the DB contributes no row to the kind lookup, so
        the group still resolves to the single 'panorama' kind and reaches
        `_confirm_sequence_group`, which is where the per-path skip actually
        happens -- the same mechanism the bracket-typed tests exercise.
        """
        conn = self._db()
        resp = self._confirm(client, conn, {
            "paths": self._SWEEP + ["/nowhere.jpg"], "keep_paths": ["/s1.jpg"]})
        assert resp.json() == {'success': True, 'kept': 1, 'rejected': 2, 'skipped': 1}
        assert self._rejected(conn) == {"/s0.jpg", "/s2.jpg"}

    def test_empty_paths_on_a_burst_feed_is_rejected_as_a_bad_request(self, client):
        """An empty `paths` list no longer reaches `select_burst_photos`.

        `_keep_whole_kind_for([])` finds nothing to look up and returns None,
        so an empty-`paths` request used to fall through to
        `select_burst_photos`, which ignores `paths` entirely and operates on
        the whole `burst_id` -- an empty `keep_paths` then rejected every
        photo in the group. `paths` is now a required, non-empty field on
        `CullingConfirmBody`, so the request 422s for every feed type, not
        just the sequence-kind branch that already guarded itself.
        """
        conn = self._db()
        resp = self._confirm(client, conn, {"paths": [], "keep_paths": []})
        assert resp.status_code == 422
        assert self._rejected(conn) == set()
        unreviewed = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE burst_group_id = 7 "
            "AND COALESCE(burst_reviewed, 0) = 0").fetchone()[0]
        assert unreviewed == 3

    def test_a_mixed_group_with_empty_keep_paths_rejects_the_whole_group(self, client):
        """Empty `keep_paths` legitimately means "reject all of these".

        The defect the guard above closes is an empty `paths`, not an empty
        `keep_paths` -- with a non-empty `paths` this still reaches
        `select_burst_photos` (via the mixed-kind group used by
        `test_a_mixed_group_is_still_culled_as_competing_takes` above) and
        rejects the whole group, exactly as an explicit "keep nothing"
        selection should.
        """
        conn = self._db()
        conn.execute("INSERT INTO photos (path, filename, sequence_kind, burst_group_id) "
                     "VALUES ('/other.jpg', 'other.jpg', NULL, 7)")
        conn.commit()
        resp = self._confirm(client, conn, {
            "paths": self._SWEEP + ["/other.jpg"], "keep_paths": []})
        assert resp.status_code == 200
        assert resp.json() == {'status': 'ok', 'kept': 0, 'rejected': 4}
        assert self._rejected(conn) == {"/s0.jpg", "/s1.jpg", "/s2.jpg", "/other.jpg"}


class TestConfirmSimilarWithSequenceMember:
    """Finding 3: only the burst feed filtered sequence-kind members out of
    `record_culling_pairs` (see
    `TestConfirmPanoramaServedAsBurst.test_sequence_member_is_excluded_from_pairs_but_ordinary_members_still_pair`
    above). The similar feed (`select_similar_photos`) did not, so a mixed
    similarity group would still train the ranker on which panorama tile
    "won" -- an artefact of how the set was shot, not a quality judgement.
    """

    @staticmethod
    def _db(tmp_path):
        conn = _real_schema_db(tmp_path)
        for index in range(2):
            conn.execute(
                "INSERT INTO photos (path, filename, sequence_group_id, sequence_kind, "
                "category) VALUES (?, ?, 1, 'panorama', 'default')",
                (f'/s{index}.jpg', f's{index}.jpg'))
        conn.execute(
            "INSERT INTO photos (path, filename, sequence_kind, category) "
            "VALUES ('/other.jpg', 'other.jpg', NULL, 'default')"
        )
        conn.commit()
        return conn

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from api import create_app
        from api.auth import get_optional_user, require_edition, CurrentUser

        app = create_app()
        fake_user = CurrentUser(user_id="test", edition_authenticated=True)
        app.dependency_overrides[get_optional_user] = lambda: fake_user
        app.dependency_overrides[require_edition] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    @staticmethod
    def _confirm(client, conn, body):
        with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
            return client.post("/api/culling-groups/confirm", json={
                "group_id": 1, "type": "similar", **body,
            })

    def test_sequence_member_records_no_pair_via_similar_feed(self, client, tmp_path):
        conn = self._db(tmp_path)
        resp = self._confirm(client, conn, {
            "paths": ["/s0.jpg", "/s1.jpg", "/other.jpg"],
            "keep_paths": ["/other.jpg"],
        })
        assert resp.status_code == 200
        assert {r['path'] for r in conn.execute(
            "SELECT path FROM photos WHERE is_rejected = 1").fetchall()} == {"/s0.jpg", "/s1.jpg"}
        assert conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 0

    def test_two_ordinary_photos_still_record_a_pair_via_similar_feed(self, client, tmp_path):
        """The positive control for the assertion above.

        `COUNT(*) == 0` holds just as well if the similar feed stopped
        recording ranker training pairs altogether, so the exclusion is only
        proven alongside a group of ordinary frames that does record one.
        """
        conn = self._db(tmp_path)
        conn.execute(
            "INSERT INTO photos (path, filename, sequence_kind, category) "
            "VALUES ('/other_b.jpg', 'other_b.jpg', NULL, 'default')"
        )
        conn.commit()
        resp = self._confirm(client, conn, {
            "paths": ["/other.jpg", "/other_b.jpg"],
            "keep_paths": ["/other.jpg"],
        })
        assert resp.status_code == 200
        rows = conn.execute(
            "SELECT photo_a_path, photo_b_path, winner, session_id, source "
            "FROM comparisons").fetchall()
        assert len(rows) == 1
        assert rows[0]['session_id'] == 'cull-similar'
        assert rows[0]['source'] == 'culling'
        a, b, winner = rows[0]['photo_a_path'], rows[0]['photo_b_path'], rows[0]['winner']
        assert {a, b} == {'/other.jpg', '/other_b.jpg'}
        assert (a if winner == 'a' else b) == '/other.jpg'


class TestConfirmSceneWithSequenceMember:
    """Finding 3, scene feed: `apply_scene_cull` also called `record_culling_pairs`
    on the raw keep/reject sets without excluding sequence-kind members.
    """

    @staticmethod
    def _db(tmp_path):
        conn = _real_schema_db(tmp_path)
        for index in range(2):
            conn.execute(
                "INSERT INTO photos (path, filename, sequence_group_id, sequence_kind, "
                "category) VALUES (?, ?, 1, 'bracket', 'default')",
                (f'/k{index}.jpg', f'k{index}.jpg'))
        conn.execute(
            "INSERT INTO photos (path, filename, sequence_kind, category) "
            "VALUES ('/other.jpg', 'other.jpg', NULL, 'default')"
        )
        conn.commit()
        return conn

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from api import create_app
        from api.auth import get_optional_user, require_edition, CurrentUser

        app = create_app()
        fake_user = CurrentUser(user_id="test", edition_authenticated=True)
        app.dependency_overrides[get_optional_user] = lambda: fake_user
        app.dependency_overrides[require_edition] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    @staticmethod
    def _confirm(client, conn, body):
        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
            mock.patch("api.routers.scenes.get_db", lambda: _cm(conn)),
        ):
            return client.post("/api/culling-groups/confirm", json={
                "group_id": 1, "type": "scene", **body,
            })

    def test_sequence_member_records_no_pair_via_scene_feed(self, client, tmp_path):
        conn = self._db(tmp_path)
        resp = self._confirm(client, conn, {
            "paths": ["/k0.jpg", "/k1.jpg", "/other.jpg"],
            "keep_paths": ["/other.jpg"],
        })
        assert resp.status_code == 200
        assert {r['path'] for r in conn.execute(
            "SELECT path FROM photos WHERE is_rejected = 1").fetchall()} == {"/k0.jpg", "/k1.jpg"}
        assert conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 0


class TestConfirmPathsBound:
    """Finding 4: `CullingConfirmBody.paths` had `min_length=1` but no upper
    bound, unlike every sibling model in this file (`max_length=1000`),
    letting an oversized array reach the unchunked `IN (...)` in
    `_keep_whole_kind_for`.
    """

    @staticmethod
    def _db(tmp_path, var_limit=None):
        return _real_schema_db(tmp_path, var_limit=var_limit)

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from api import create_app
        from api.auth import require_edition, CurrentUser

        app = create_app()
        fake_user = CurrentUser(user_id="test", edition_authenticated=True)
        app.dependency_overrides[require_edition] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_an_oversized_paths_list_422s_before_any_handler_runs(self, client, tmp_path):
        conn = self._db(tmp_path)
        with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
            resp = client.post("/api/culling-groups/confirm", json={
                "group_id": 1, "type": "burst",
                "paths": [f"/p{i}.jpg" for i in range(1001)],
                "keep_paths": [],
            })
        assert resp.status_code == 422

    def test_the_model_cap_still_needs_chunking_to_avoid_a_500(self, client, tmp_path):
        """At exactly the model's new cap (1000 paths), SQLite's variable-number
        limit can be lower than this environment's default in the wild (the
        reviewer's own probe used 250000; other builds go lower) -- so the
        lookup must chunk, not merely rely on the cap alone. This connection's
        variable-number limit is constrained to 901 (just above the file's
        existing `select_in_chunks` default chunk size of 900), so 1000 paths
        only survives if the query is actually chunked.
        """
        conn = self._db(tmp_path, var_limit=901)
        with mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)):
            resp = client.post("/api/culling-groups/confirm", json={
                "group_id": 1, "type": "burst",
                "paths": [f"/p{i}.jpg" for i in range(1000)],
                "keep_paths": [],
            })
        # No burst group named 1 exists in this DB -- 404, not a 500 crash.
        assert resp.status_code == 404


class TestKeepWholeKindVisibilityLeak:
    """Finding 5: `_keep_whole_kind_for` queried with no visibility clause and
    ran BEFORE any scoping, so its 200-vs-404 routing decision let a
    directory-scoped caller learn whether a guessed foreign path exists and is
    a bracket/panorama frame -- exactly the leak `_confirm_sequence_group`'s
    own docstring says it exists to prevent.
    """

    @staticmethod
    def _db(tmp_path):
        conn = _real_schema_db(tmp_path)
        conn.execute(
            "INSERT INTO photos (path, filename, sequence_group_id, sequence_kind) "
            "VALUES ('/foreign_panorama.jpg', 'foreign_panorama.jpg', 1, 'panorama')"
        )
        conn.execute(
            "INSERT INTO photos (path, filename, sequence_kind) "
            "VALUES ('/foreign_plain.jpg', 'foreign_plain.jpg', NULL)"
        )
        conn.commit()
        return conn

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from api import create_app
        from api.auth import require_edition, CurrentUser

        app = create_app()
        fake_user = CurrentUser(user_id="scoped", edition_authenticated=True)
        app.dependency_overrides[require_edition] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    @staticmethod
    def _confirm(client, conn, path):
        # A directory-scoped caller who cannot see either foreign path -- mirrors
        # the reviewer's multi-user probe (foreign panorama -> 200, foreign
        # plain / nonexistent -> 404, before this fix).
        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(conn)),
            mock.patch("api.routers.burst_culling.get_visibility_clause",
                       return_value=("photos.path NOT LIKE '/foreign%'", [])),
        ):
            return client.post("/api/culling-groups/confirm", json={
                "group_id": 999, "type": "burst", "paths": [path], "keep_paths": [],
            })

    def test_foreign_panorama_frame_is_indistinguishable_from_nonexistent(self, client, tmp_path):
        conn = self._db(tmp_path)
        resp_foreign_panorama = self._confirm(client, conn, "/foreign_panorama.jpg")
        resp_nonexistent = self._confirm(client, conn, "/nowhere.jpg")
        assert resp_foreign_panorama.status_code == resp_nonexistent.status_code == 404

    def test_foreign_plain_photo_is_also_404(self, client, tmp_path):
        conn = self._db(tmp_path)
        resp = self._confirm(client, conn, "/foreign_plain.jpg")
        assert resp.status_code == 404


class TestFilterSimilarGroups:
    """Unit tests for read-time rejected-photo filtering of cached similar groups."""

    def _conn_with_rejected(self, rejected_paths):
        conn = mock.MagicMock()
        conn.execute.return_value.fetchall.return_value = [
            {'path': p} for p in rejected_paths
        ]
        return conn

    def test_drops_rejected_path_and_preserves_count_semantic(self):
        from api.routers.burst_culling import _filter_similar_groups

        all_groups = [{
            'paths': ['/a.jpg', '/b.jpg', '/c.jpg'],
            'best_path': '/a.jpg',
            'count': 3,
        }]
        conn = self._conn_with_rejected(['/a.jpg'])

        filtered = _filter_similar_groups(conn, all_groups, user_id=None)

        assert len(filtered) == 1
        assert filtered[0]['paths'] == ['/b.jpg', '/c.jpg']
        assert filtered[0]['count'] == 2
        assert filtered[0]['best_path'] == '/a.jpg'

    def test_drops_groups_below_min_size(self):
        from api.routers.burst_culling import _filter_similar_groups

        all_groups = [{
            'paths': ['/a.jpg', '/b.jpg'],
            'best_path': '/a.jpg',
            'count': 2,
        }]
        conn = self._conn_with_rejected(['/a.jpg'])

        filtered = _filter_similar_groups(conn, all_groups, user_id=None)

        assert filtered == []

    def test_no_rejected_returns_input_unchanged(self):
        from api.routers.burst_culling import _filter_similar_groups

        all_groups = [{'paths': ['/a.jpg', '/b.jpg'], 'best_path': '/a.jpg', 'count': 2}]
        conn = self._conn_with_rejected([])

        filtered = _filter_similar_groups(conn, all_groups, user_id=None)

        assert filtered is all_groups


class TestSelectSimilarInvalidatesCache:
    """Verify the similarity_groups_* cache is dropped when a similar group is reviewed,
    so kept (similarity_reviewed=1) photos don't linger in the 1h cache.
    """

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from api import create_app
        from api.auth import require_edition, CurrentUser

        app = create_app()
        fake_user = CurrentUser(user_id="test", edition_authenticated=True)
        app.dependency_overrides[require_edition] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_select_similar_deletes_stats_cache(self, client):
        mock_conn = mock.MagicMock()
        # record_culling_pairs derives its inserted-row count from
        # conn.total_changes; a bare MagicMock attribute isn't a real int, so
        # give it one to keep the downstream trigger_auto_retrain(added <= 0)
        # comparison meaningful rather than incidentally crashing.
        mock_conn.total_changes = 0

        with (
            mock.patch("api.routers.burst_culling.get_db", lambda: _cm(mock_conn)),
            mock.patch("api.routers.burst_culling.get_visibility_clause", return_value=("1=1", [])),
        ):
            resp = client.post(
                "/api/similar-groups/select",
                json={"paths": ["/a.jpg", "/b.jpg"], "keep_paths": ["/a.jpg"]},
            )

        assert resp.status_code == 200
        executed_sql = [c.args[0] for c in mock_conn.execute.call_args_list]
        assert any(
            "DELETE FROM stats_cache" in s and "similarity_groups_" in s
            for s in executed_sql
        ), f"cache invalidation DELETE missing from: {executed_sql}"


# ---------------------------------------------------------------------------
# Album + capture-time-window scope on burst group selection (real SQLite)
# ---------------------------------------------------------------------------

class TestQueryBurstGroupsScope:
    _SCHEMA = """
        CREATE TABLE photos (
            path TEXT PRIMARY KEY, filename TEXT, date_taken TEXT, aggregate REAL,
            aesthetic REAL, tech_sharpness REAL, is_blink INTEGER, is_burst_lead INTEGER, is_sequence_lead INTEGER DEFAULT 0,
            burst_group_id INTEGER, burst_reviewed INTEGER, eyes_open_score REAL,
            expression_score REAL, face_count INTEGER, category TEXT,
            sequence_kind TEXT, sequence_ev_offset REAL
        );
        CREATE TABLE album_photos (
            id INTEGER PRIMARY KEY, album_id INTEGER, photo_path TEXT
        );
    """ + _SEQUENCE_OVERRIDES_SCHEMA

    # g1: two frames inside the window; g2: outside; g3: two frames inside +
    # a tail frame 3s AFTER the window end (boundary burst).
    _PHOTOS = [
        ("/g1a.jpg", "2024:06:15 10:00:00", 1),
        ("/g1b.jpg", "2024:06:15 10:00:01", 1),
        ("/g2a.jpg", "2024:06:15 12:00:00", 2),
        ("/g2b.jpg", "2024:06:15 12:00:01", 2),
        ("/g3a.jpg", "2024:06:15 10:29:58", 3),
        ("/g3b.jpg", "2024:06:15 10:29:59", 3),
        ("/g3c.jpg", "2024:06:15 10:30:03", 3),
    ]

    def _db(self):
        import sqlite3
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(self._SCHEMA)
        conn.executemany(
            "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, "
            "tech_sharpness, is_blink, is_burst_lead, burst_group_id, burst_reviewed, "
            "eyes_open_score, expression_score, face_count, category) "
            "VALUES (?, ?, ?, 7.0, 7.0, 7.0, 0, 0, ?, 0, 8.0, 8.0, 0, NULL)",
            [(p, p.lstrip('/'), dt, gid) for p, dt, gid in self._PHOTOS],
        )
        conn.executemany(
            "INSERT INTO album_photos (album_id, photo_path) VALUES (1, ?)",
            [("/g1a.jpg",), ("/g1b.jpg",)],
        )
        conn.commit()
        return conn

    def test_window_scopes_selection(self):
        from api.routers.burst_culling import _query_burst_groups
        conn = self._db()
        groups, total, _ = _query_burst_groups(
            conn, "1=1", [], exclude_rejected=False,
            date_from="2024:06:15 10:00:00", date_to="2024:06:15 10:30:00",
        )
        gids = {g["burst_id"] for g in groups}
        assert gids == {1, 3}  # g2 (12:00) excluded by window
        assert total == 2

    def test_boundary_burst_member_fetch_ignores_window(self):
        """A burst selected by the window returns ALL its frames, including the
        tail frame captured after the window end (member fetch is album-only)."""
        from api.routers.burst_culling import _query_burst_groups
        conn = self._db()
        groups, _, _ = _query_burst_groups(
            conn, "1=1", [], exclude_rejected=False,
            date_from="2024:06:15 10:00:00", date_to="2024:06:15 10:30:00",
        )
        g3 = next(g for g in groups if g["burst_id"] == 3)
        assert g3["count"] == 3  # 10:30:03 tail frame NOT clipped by the window

    def test_album_scopes_selection(self):
        from api.routers.burst_culling import _query_burst_groups
        conn = self._db()
        groups, total, _ = _query_burst_groups(
            conn, "1=1", [], exclude_rejected=False, album_id=1,
        )
        assert {g["burst_id"] for g in groups} == {1}
        assert total == 1



class TestFetchBracketGroups:
    """The browse path behind `group_by=bracket`.

    Auto-cull's trimming reaches this function too, but only ever with
    `redundant_only=True`, so the plain browse — grouping, base-first ordering
    and the small-set exclusion — had no coverage of its own.
    """

    _SCHEMA = """
        CREATE TABLE photos (
            path TEXT PRIMARY KEY, filename TEXT, date_taken TEXT, aggregate REAL,
            aesthetic REAL, tech_sharpness REAL, is_blink INTEGER DEFAULT 0,
            is_burst_lead INTEGER DEFAULT 0, burst_group_id INTEGER,
            eyes_open_score REAL, expression_score REAL, face_count INTEGER DEFAULT 0,
            category TEXT, is_rejected INTEGER DEFAULT 0,
            sequence_group_id INTEGER, sequence_kind TEXT, sequence_ev_offset REAL,
            shadow_clipped INTEGER, highlight_clipped INTEGER
        );
    """ + _SEQUENCE_OVERRIDES_SCHEMA

    @staticmethod
    def _db(rows):
        import sqlite3
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(TestFetchBracketGroups._SCHEMA)
        conn.executemany(
            "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, "
            "tech_sharpness, sequence_group_id, sequence_kind, sequence_ev_offset, "
            "is_rejected) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        return conn

    @staticmethod
    def _rung(path, when, seq, ev, score=5.0, rejected=0):
        return (path, path.lstrip('/'), when, score, score, score, seq, 'bracket', ev, rejected)

    @staticmethod
    def _fetch(conn, **kwargs):
        from api.routers.burst_culling import _fetch_bracket_groups
        with mock.patch("api.routers.burst_culling.get_photos_from_clause",
                        return_value=("photos", [])), \
                mock.patch("api.routers.burst_culling.is_multi_user_enabled",
                           return_value=False):
            return _fetch_bracket_groups(conn, None, "1=1", [], **kwargs)

    def test_groups_by_sequence_and_leads_with_the_base_exposure(self):
        conn = self._db([
            self._rung('/k2.jpg', '2025:04:15 19:59:07', 1, 2.0, score=9.0),
            self._rung('/k0.jpg', '2025:04:15 19:59:05', 1, -2.0, score=4.0),
            self._rung('/k1.jpg', '2025:04:15 19:59:06', 1, 0.0, score=5.0),
        ])
        groups = self._fetch(conn)
        assert len(groups) == 1
        group = groups[0]
        assert group['type'] == 'bracket'
        # Base first regardless of score: the +2 frame scores highest and the
        # feed must still open on the exposure the set was built around.
        assert [p['path'] for p in group['photos']] == ['/k1.jpg', '/k0.jpg', '/k2.jpg']

    def test_separate_sets_are_separate_groups(self):
        conn = self._db([
            self._rung('/a0.jpg', '2025:04:15 19:59:05', 1, -1.0),
            self._rung('/a1.jpg', '2025:04:15 19:59:06', 1, 0.0),
            self._rung('/b0.jpg', '2025:04:15 20:10:05', 2, 0.0),
            self._rung('/b1.jpg', '2025:04:15 20:10:06', 2, 1.0),
        ])
        assert len(self._fetch(conn)) == 2

    def test_a_set_left_with_one_frame_is_not_a_group(self):
        conn = self._db([self._rung('/lonely.jpg', '2025:04:15 19:59:05', 1, 0.0)])
        assert self._fetch(conn) == []

    def test_rejected_frames_are_excluded_by_default(self):
        conn = self._db([
            self._rung('/k0.jpg', '2025:04:15 19:59:05', 1, -1.0),
            self._rung('/k1.jpg', '2025:04:15 19:59:06', 1, 0.0),
            self._rung('/k2.jpg', '2025:04:15 19:59:07', 1, 1.0, rejected=1),
        ])
        paths = [p['path'] for p in self._fetch(conn)[0]['photos']]
        assert '/k2.jpg' not in paths

    def test_a_photo_that_is_not_bracketed_never_appears(self):
        conn = self._db([
            self._rung('/k0.jpg', '2025:04:15 19:59:05', 1, -1.0),
            self._rung('/k1.jpg', '2025:04:15 19:59:06', 1, 0.0),
        ])
        conn.execute("INSERT INTO photos (path, filename, sequence_kind) "
                     "VALUES ('/plain.jpg', 'plain.jpg', NULL)")
        conn.commit()
        paths = [p['path'] for g in self._fetch(conn) for p in g['photos']]
        assert '/plain.jpg' not in paths


class TestPanoramaGroupsCarryTheOverride:
    """A culling group reports each frame's pending correction.

    Suppressing a set from culling writes to `photo_sequence_overrides` and
    changes nothing in `photos` until the next detection run, so the set is
    still served here afterwards. Without the frame carrying its correction the
    feed would look exactly as it did before the click.
    """

    _SCHEMA = """
        CREATE TABLE photos (
            path TEXT PRIMARY KEY, filename TEXT, date_taken TEXT, aggregate REAL,
            aesthetic REAL, tech_sharpness REAL, is_blink INTEGER DEFAULT 0,
            is_burst_lead INTEGER DEFAULT 0, burst_group_id INTEGER,
            eyes_open_score REAL, expression_score REAL, face_count INTEGER DEFAULT 0,
            category TEXT, is_rejected INTEGER DEFAULT 0,
            sequence_group_id INTEGER, sequence_kind TEXT, sequence_ev_offset REAL
        );
    """ + _SEQUENCE_OVERRIDES_SCHEMA

    def _db(self, overrides=()):
        import sqlite3
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(self._SCHEMA)
        conn.executemany(
            "INSERT INTO photos (path, filename, date_taken, aggregate, aesthetic, "
            "tech_sharpness, sequence_group_id, sequence_kind) VALUES (?,?,?,5.0,5.0,5.0,1,'panorama')",
            [(f'/p{i}.jpg', f'p{i}.jpg', f'2025:04:15 12:00:0{i}') for i in range(3)])
        conn.executemany(
            "INSERT INTO photo_sequence_overrides "
            "(photo_path, sequence_kind, override_group_key, source) VALUES (?,?,?,'user')",
            overrides)
        conn.commit()
        return conn

    def _fetch(self, conn):
        from api.routers.burst_culling import _fetch_panorama_groups
        with mock.patch("api.routers.burst_culling.get_photos_from_clause",
                        return_value=("photos", [])), \
                mock.patch("api.routers.burst_culling.is_multi_user_enabled",
                           return_value=False):
            return _fetch_panorama_groups(conn, None, 'panorama', "1=1", [])

    def test_an_uncorrected_set_reports_nothing(self):
        photos = self._fetch(self._db())[0]['photos']
        assert {p['sequence_override'] for p in photos} == {None}

    def test_a_suppressed_set_reports_it_on_every_frame(self):
        conn = self._db([(f'/p{i}.jpg', None, None) for i in range(3)])
        photos = self._fetch(conn)[0]['photos']
        assert {p['sequence_override'] for p in photos} == {'suppressed'}

    def test_a_relabel_reports_the_forced_kind(self):
        conn = self._db([(f'/p{i}.jpg', 'hdr_panorama', '/p0.jpg') for i in range(3)])
        photos = self._fetch(conn)[0]['photos']
        assert {p['sequence_override'] for p in photos} == {'hdr_panorama'}
