"""Tests for burst culling helpers and endpoints (api/routers/burst_culling.py)."""

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


def _cm(conn):
    @contextmanager
    def _ctx():
        yield conn
    return _ctx()


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
    """

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
        conn = self._db()
        resp = self._confirm(client, conn, {"paths": [], "keep_paths": []})
        assert resp.status_code == 400
        assert 'paths is required' in resp.json()['detail']


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
            aesthetic REAL, tech_sharpness REAL, is_blink INTEGER, is_burst_lead INTEGER,
            burst_group_id INTEGER, burst_reviewed INTEGER, eyes_open_score REAL,
            expression_score REAL, face_count INTEGER, category TEXT,
            sequence_kind TEXT, sequence_ev_offset REAL
        );
        CREATE TABLE album_photos (
            id INTEGER PRIMARY KEY, album_id INTEGER, photo_path TEXT
        );
    """

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

