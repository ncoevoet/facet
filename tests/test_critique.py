"""Tests for the critique API router (api/routers/critique.py).

GET /api/critique is async (Topic 2 step 7), so endpoint-level tests patch
get_async_db with a real aiosqlite-backed temp DB rather than a MagicMock
(a MagicMock is not awaitable). VLM inference (_get_vlm_critique) is patched
with a plain stub since it is wrapped in asyncio.to_thread in the handler.
"""

import sqlite3
from contextlib import asynccontextmanager
from unittest import mock

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from api import create_app


# Columns selected by the critique endpoint (must all exist in the test DB).
_CRITIQUE_COLS = [
    'path', 'category', 'aggregate', 'aesthetic', 'tech_sharpness',
    'face_quality', 'eye_sharpness', 'face_sharpness', 'comp_score',
    'exposure_score', 'color_score', 'contrast_score', 'isolation_bonus',
    'noise_sigma', 'dynamic_range_stops', 'leading_lines_score',
    'power_point_score', 'aesthetic_iaa', 'face_quality_iqa', 'liqe_score',
    'subject_sharpness', 'subject_prominence', 'subject_placement',
    'bg_separation', 'mean_saturation', 'mean_luminance',
    'face_ratio', 'face_count', 'is_monochrome', 'is_blink',
    'is_silhouette', 'is_group_portrait',
    'highlight_clipped', 'shadow_clipped', 'tags', 'shutter_speed',
    'focal_length', 'f_stop', 'iso',
]

_CRITIQUE_SCHEMA = (
    "CREATE TABLE photos (path TEXT PRIMARY KEY, "
    + ", ".join(f"{c} TEXT" for c in _CRITIQUE_COLS if c != 'path')
    + ", is_rejected INTEGER DEFAULT 0);"
)


def _make_db(path, photos):
    conn = sqlite3.connect(path)
    conn.executescript(_CRITIQUE_SCHEMA)
    for p in photos:
        cols = list(p.keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO photos ({', '.join(cols)}) VALUES ({placeholders})",
            [p[c] for c in cols],
        )
    conn.commit()
    conn.close()


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


def _fake_vis(user_id, table_alias=None):
    return ("1=1", [])


def _make_photo(**overrides):
    """Return a photo dict with sensible defaults for critique tests."""
    defaults = {
        "path": "/photos/test.jpg",
        "category": "landscape",
        "aggregate": 7.5,
        "aesthetic": 8.0,
        "tech_sharpness": 7.0,
        "face_quality": None,
        "eye_sharpness": None,
        "face_sharpness": None,
        "comp_score": 6.5,
        "exposure_score": 7.2,
        "color_score": 6.8,
        "contrast_score": 7.1,
        "isolation_bonus": None,
        "noise_sigma": 2.5,
        "dynamic_range_stops": 8.0,
        "leading_lines_score": 5.0,
        "power_point_score": 4.5,
        "aesthetic_iaa": 6.9,
        "face_quality_iqa": None,
        "liqe_score": 7.3,
        "subject_sharpness": 7.8,
        "subject_prominence": 6.0,
        "subject_placement": 5.5,
        "bg_separation": 6.2,
        "mean_saturation": 0.45,
        "mean_luminance": 0.52,
        "face_ratio": None,
        "face_count": 0,
        "is_monochrome": 0,
        "is_blink": 0,
        "highlight_clipped": 0,
        "shadow_clipped": 0,
        "tags": '["landscape", "mountain"]',
        "shutter_speed": None,
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Endpoint-level tests (mock _build_rule_critique for isolation)
# ---------------------------------------------------------------------------


class TestCritiqueEndpoint:
    """Tests for GET /api/critique — endpoint routing and guards."""

    def test_critique_disabled(self, client):
        """When show_critique=False the endpoint returns 403."""
        with mock.patch(
            "api.routers.critique.VIEWER_CONFIG",
            {"features": {"show_critique": False}},
        ):
            resp = client.get("/api/critique", params={"path": "/photos/test.jpg"})

        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()

    def test_photo_not_found(self, client, tmp_path):
        """Unknown path returns 404."""
        db = str(tmp_path / "critique.db")
        _make_db(db, [])  # empty -> path not found

        with (
            mock.patch("api.routers.critique.VIEWER_CONFIG", {"features": {"show_critique": True}}),
            mock.patch("api.routers.critique.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.critique.get_visibility_clause", _fake_vis),
        ):
            resp = client.get("/api/critique", params={"path": "/photos/missing.jpg"})

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


    def test_rule_critique_success(self, client, tmp_path):
        """Rule mode returns breakdown, strengths, weaknesses, and category."""
        db = str(tmp_path / "critique.db")
        _make_db(db, [_make_photo()])

        fake_result = {
            "category": "landscape",
            "category_reason": {"reason_key": "matched", "category": "landscape", "details": []},
            "aggregate": 7.5,
            "breakdown": [
                {"metric": "Aesthetic Quality", "metric_key": "aesthetic", "value": 8.0, "weight": 0.35, "contribution": 2.80},
            ],
            "strengths": [{"metric_key": "aesthetic", "value": 8.0}],
            "weaknesses": [],
            "suggestions": [],
            "penalties": {},
        }

        with (
            mock.patch("api.routers.critique.VIEWER_CONFIG", {"features": {"show_critique": True}}),
            mock.patch("api.routers.critique.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.critique.get_visibility_clause", _fake_vis),
            mock.patch("api.routers.critique._build_rule_critique", return_value=fake_result),
        ):
            resp = client.get("/api/critique", params={"path": "/photos/test.jpg"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["category"] == "landscape"
        assert body["aggregate"] == 7.5
        assert len(body["breakdown"]) == 1
        assert isinstance(body["strengths"], list)
        assert isinstance(body["weaknesses"], list)


    def test_vlm_mode_unavailable(self, client, tmp_path):
        """When mode=vlm but VLM returns nothing, vlm_available=False in response.

        _get_vlm_critique is the blocking inference call (wrapped in
        asyncio.to_thread by the handler); patch it with a plain stub returning
        None to simulate an unavailable VLM.
        """
        db = str(tmp_path / "critique.db")
        _make_db(db, [_make_photo()])

        fake_rule = {
            "category": "landscape",
            "category_reason": {"reason_key": "default", "category": "landscape", "details": []},
            "aggregate": 7.5,
            "breakdown": [],
            "strengths": [],
            "weaknesses": [],
            "suggestions": [],
            "penalties": {},
        }

        with (
            mock.patch("api.routers.critique.VIEWER_CONFIG", {"features": {"show_critique": True}}),
            mock.patch("api.routers.critique.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.critique.get_visibility_clause", _fake_vis),
            mock.patch("api.routers.critique._build_rule_critique", return_value=fake_rule),
            mock.patch("api.routers.critique._get_vlm_critique", return_value=None),
        ):
            resp = client.get("/api/critique", params={"path": "/photos/test.jpg", "mode": "vlm"})

        assert resp.status_code == 200
        body = resp.json()
        assert body.get("vlm_available") is False
        assert "vlm_critique" not in body

    def test_vlm_mode_available(self, client, tmp_path):
        """When mode=vlm and VLM returns text, it appears as vlm_critique."""
        db = str(tmp_path / "critique.db")
        _make_db(db, [_make_photo()])

        fake_rule = {
            "category": "landscape",
            "category_reason": {"reason_key": "default", "category": "landscape", "details": []},
            "aggregate": 7.5,
            "breakdown": [],
            "strengths": [],
            "weaknesses": [],
            "suggestions": [],
            "penalties": {},
        }

        with (
            mock.patch("api.routers.critique.VIEWER_CONFIG", {"features": {"show_critique": True}}),
            mock.patch("api.routers.critique.get_async_db", _async_conn_factory(db)),
            mock.patch("api.routers.critique.get_visibility_clause", _fake_vis),
            mock.patch("api.routers.critique._build_rule_critique", return_value=fake_rule),
            mock.patch("api.routers.critique._get_vlm_critique", return_value="A lovely landscape."),
        ):
            resp = client.get("/api/critique", params={"path": "/photos/test.jpg", "mode": "vlm"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["vlm_critique"] == "A lovely landscape."
        assert "vlm_available" not in body



# ---------------------------------------------------------------------------
# Direct _build_rule_critique tests (mock ScoringConfig)
# ---------------------------------------------------------------------------


class TestBuildRuleCritique:
    """Unit tests for _build_rule_critique with mocked ScoringConfig."""

    def _mock_scoring_config(self, weights, category_config=None):
        """Return a mock ScoringConfig class whose instances return *weights*."""
        instance = mock.MagicMock()
        instance.get_weights.return_value = weights
        instance.get_category_config.return_value = category_config or {}
        cls = mock.MagicMock(return_value=instance)
        return cls

    def test_rule_critique_with_penalties(self):
        """Photo with is_blink=1 and high noise_sigma produces penalties."""
        from api.routers.critique import _build_rule_critique

        weights = {
            "aesthetic": 0.35,
            "tech_sharpness": 0.25,
            "composition": 0.20,
            "noise": 0.10,
            "exposure": 0.10,
        }
        photo = _make_photo(
            is_blink=1,
            noise_sigma=10.0,
            aesthetic=8.0,
            tech_sharpness=6.0,
            comp_score=5.5,
            exposure_score=7.0,
        )

        with mock.patch("config.ScoringConfig", self._mock_scoring_config(weights)):
            result = _build_rule_critique(photo)

        penalties = result["penalties"]
        assert penalties.get("blink") is True
        assert "noise" in penalties
        assert penalties["noise"] < 0  # negative penalty value

    def test_critique_fields(self):
        """Verify all expected keys are present in the result."""
        from api.routers.critique import _build_rule_critique

        weights = {
            "aesthetic": 0.40,
            "tech_sharpness": 0.30,
            "composition": 0.15,
            "exposure": 0.15,
        }
        photo = _make_photo()

        with mock.patch("config.ScoringConfig", self._mock_scoring_config(weights)):
            result = _build_rule_critique(photo)

        expected_keys = {
            "category",
            "category_reason",
            "aggregate",
            "breakdown",
            "strengths",
            "weaknesses",
            "suggestions",
            "penalties",
        }
        assert expected_keys == set(result.keys())

        # Verify sub-structure types
        assert isinstance(result["breakdown"], list)
        assert isinstance(result["strengths"], list)
        assert isinstance(result["weaknesses"], list)
        assert isinstance(result["suggestions"], list)
        assert isinstance(result["penalties"], dict)
        assert isinstance(result["category_reason"], dict)
        assert result["aggregate"] == photo["aggregate"]
        assert result["category"] == photo["category"]

    def test_breakdown_item_structure(self):
        """Each breakdown item has metric, metric_key, value, weight, contribution."""
        from api.routers.critique import _build_rule_critique

        weights = {"aesthetic": 0.50, "composition": 0.50}
        photo = _make_photo(aesthetic=8.5, comp_score=6.0)

        with mock.patch("config.ScoringConfig", self._mock_scoring_config(weights)):
            result = _build_rule_critique(photo)

        assert len(result["breakdown"]) >= 1
        item = result["breakdown"][0]
        assert set(item.keys()) == {"metric", "metric_key", "value", "weight", "contribution"}
        assert isinstance(item["value"], float)
        assert isinstance(item["weight"], float)

    def test_strengths_and_weaknesses_classification(self):
        """High-scoring metrics appear in strengths, low-scoring in weaknesses."""
        from api.routers.critique import _build_rule_critique

        weights = {
            "aesthetic": 0.40,
            "tech_sharpness": 0.30,
            "composition": 0.30,
        }
        photo = _make_photo(aesthetic=9.0, tech_sharpness=3.0, comp_score=9.5)

        with mock.patch("config.ScoringConfig", self._mock_scoring_config(weights)):
            result = _build_rule_critique(photo)

        strength_keys = [s["metric_key"] for s in result["strengths"]]
        weakness_keys = [w["metric_key"] for w in result["weaknesses"]]

        assert "aesthetic" in strength_keys
        assert "comp_score" in strength_keys
        assert "tech_sharpness" in weakness_keys

    def test_no_penalties_for_clean_photo(self):
        """A photo with no issues produces an empty penalties dict."""
        from api.routers.critique import _build_rule_critique

        weights = {"aesthetic": 0.50, "composition": 0.50}
        photo = _make_photo(is_blink=0, noise_sigma=1.5, highlight_clipped=0, shadow_clipped=0)

        with mock.patch("config.ScoringConfig", self._mock_scoring_config(weights)):
            result = _build_rule_critique(photo)

        assert result["penalties"] == {}
