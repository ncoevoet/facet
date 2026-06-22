"""Tests for burst culling helpers and endpoints (api/routers/burst_culling.py)."""

from contextlib import contextmanager
from unittest import mock

import pytest

from api.routers.burst_culling import (
    _compute_burst_score,
    _compute_cull_reason,
    _format_group,
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

