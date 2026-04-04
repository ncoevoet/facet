"""Tests for burst culling helpers and endpoints (api/routers/burst_culling.py)."""

from contextlib import contextmanager
from unittest import mock

import pytest

from api.routers.burst_culling import _compute_burst_score, _format_group


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
