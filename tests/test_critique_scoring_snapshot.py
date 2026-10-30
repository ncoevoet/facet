"""Real API/scalar SQLite snapshot tests with synthetic metadata and histograms."""

from contextlib import contextmanager
import json
import sqlite3
from threading import Event, Thread
from unittest import mock

from fastapi.testclient import TestClient
import pytest

from api import create_app
from api.routers import critique
from config.percentile_normalizer import PercentileNormalizer
from config.scoring_config import ScoringConfig
from db.schema import PHOTOS_COLUMNS, _build_create_table_sql
from pathlib import Path


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "critique.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_build_create_table_sql("photos", PHOTOS_COLUMNS))
        conn.execute(
            "CREATE TABLE stats_cache(key TEXT PRIMARY KEY,value TEXT,updated_at REAL)"
        )
        conn.execute(
            "CREATE TABLE photo_scoring_overrides(photo_path TEXT PRIMARY KEY,scoring_context TEXT,category_override TEXT)"
        )
        conn.execute(
            "INSERT INTO photos(path,raw_sharpness_variance,tech_sharpness,aggregate,config_version) VALUES('synthetic',20,1,2,'legacy')"
        )
        conn.execute(
            "INSERT INTO stats_cache VALUES('percentiles_snapshot',?,0)",
            (
                json.dumps(
                    {
                        "percentiles": {"raw_sharpness_variance": 100},
                        "category_percentiles": {},
                    }
                ),
            ),
        )
    config = ScoringConfig(
        str(Path(__file__).parents[1] / "config/scoring_config.default.json"),
        validate=False,
    )
    config.get_weights = lambda category: {"tech_sharpness": 1.0}
    queries = []

    @contextmanager
    def database():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.set_trace_callback(queries.append)
        try:
            yield conn
        finally:
            conn.close()

    # Import route modules before patching their shared config factory: a
    # route's module-level import must not retain this fixture's mock.
    app = create_app()
    with (
        mock.patch.object(critique, "get_db", database),
        mock.patch.object(critique, "get_visibility_clause", return_value=("1=1", [])),
        mock.patch("api.config.server_scoring_config", return_value=config),
    ):
        yield path, config, queries, TestClient(app)


def get(client):
    response = client.get("/api/critique", params={"path": "synthetic"})
    assert response.status_code == 200, response.text
    return response.json()


def test_real_api_uses_snapshot_but_never_mislabels_valid_legacy_score(snapshot):
    path, config, queries, client = snapshot
    result = get(client)
    assert result["current_formula_score"] == result["aggregate"] == 2.0
    assert result["stored_score_state"] == "present"
    assert result["stored_score_matches_current_formula"] is True
    assert result["normalization_basis"] == "persisted_percentiles"
    assert result["breakdown"][0]["value"] == 2.0
    assert all(
        not sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE"))
        for sql in queries
    )
    select = next(sql for sql in queries if sql.startswith("SELECT path,"))
    assert "histogram_data" in select
    assert "clip_embedding" not in select and "thumbnail" not in select


def test_snapshot_and_photo_are_not_mixed_across_external_commit(snapshot):
    path, config, queries, client = snapshot
    started = Event()
    committed = Event()
    result = {}
    original = PercentileNormalizer.load_persisted

    def paused(connection):
        started.set()
        assert committed.wait(5)
        return original(connection)

    def request():
        try:
            result["value"] = get(client)
        except BaseException as error:
            result["error"] = error

    with mock.patch.object(PercentileNormalizer, "load_persisted", side_effect=paused):
        reader = Thread(target=request)
        reader.start()
        try:
            assert started.wait(5)
            with sqlite3.connect(path) as writer:
                writer.execute("UPDATE photos SET aggregate=8")
                writer.execute(
                    "UPDATE stats_cache SET value=?",
                    (json.dumps({"percentiles": {"raw_sharpness_variance": 25}}),),
                )
        finally:
            committed.set()
        reader.join(5)
        assert not reader.is_alive() and "error" not in result, result.get("error")
    assert (
        result["value"]["aggregate"] == result["value"]["current_formula_score"] == 2.0
    )
    fresh = get(client)
    assert fresh["aggregate"] == fresh["current_formula_score"] == 8.0


def test_absent_snapshot_explains_the_stored_metrics_the_scan_scored(snapshot):
    """A scan-only library has no snapshot under the default percentile method.
    The scan scored the photo through build_scoring_metrics and
    calculate_aggregate_logic with no normalizer; the explanation of the row it
    stored must reproduce that stored aggregate."""
    from processing.scorer import Facet, build_scoring_metrics

    path, config, queries, client = snapshot
    assert config.get_normalization_settings()["method"] == "percentile"
    metrics = build_scoring_metrics(
        aesthetic=6.0, face_count=0, face_quality=None, eye_sharpness=None,
        face_sharpness=None, face_ratio=0.0, is_group_portrait=0, is_blink=0,
        isolation_bonus=None, sharpness_data={"normalized": 3.7},
        color_data={"normalized": 5.5}, histogram_data={"exposure_score": 6.0},
        mono_data={}, noise_data={}, contrast_data={}, comp_score=5.0,
        power_point_score=5.0, leading_lines_score=0, is_silhouette=0, tags="",
        iso=None, f_stop=None,
    )
    scanner = Facet.__new__(Facet)
    scanner.config = config
    aggregate, category = scanner.calculate_aggregate_logic(metrics)
    stored = round(aggregate, 2)  # what the scan writes to photos.aggregate
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM stats_cache")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
        scanned = {key: value for key, value in metrics.items()
                   if key in columns and value is not None}
        scanned.update(aggregate=stored, category=category)
        conn.execute(
            f"UPDATE photos SET {', '.join(f'{key} = ?' for key in scanned)}",
            list(scanned.values()),
        )
    result = get(client)
    assert "explanation_unavailable_reason" not in result
    assert result["normalization_basis"] == "stored_metrics"
    assert result["aggregate"] == stored == 3.7
    assert result["current_formula_score"] == stored
    assert result["stored_score_matches_current_formula"] is True


def test_absent_stats_cache_table_explains_the_stored_metrics(snapshot):
    path, config, queries, client = snapshot
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE stats_cache")
    result = get(client)
    assert result["normalization_basis"] == "stored_metrics"
    assert result["current_formula_score"] == 1.0


@pytest.mark.parametrize(
    "message, malformed",
    [("no such table: stats_cache", False), ("database is locked", True)],
)
def test_snapshot_probe_treats_only_a_missing_table_as_absent(message, malformed):
    """A locked read must not pass for an absent snapshot: that would explain a
    library the recompute normalized with un-normalized stored metrics."""

    class FailingConnection:
        def execute(self, sql, params=()):
            raise sqlite3.OperationalError(message)

    assert critique._snapshot_malformed(FailingConnection()) is malformed


@pytest.mark.parametrize(
    "value",
    ["[]", "{invalid", '{"percentiles":{"raw_sharpness_variance":"bad"}}'],
)
def test_malformed_snapshot_does_not_invent_an_explanation(snapshot, value):
    path, config, queries, client = snapshot
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE stats_cache SET value=?", (value,))
    result = get(client)
    assert result["aggregate"] == 2.0 and result["stored_score_state"] == "present"
    assert result["current_formula_score"] is None and result["breakdown"] == []
    assert (
        result["explanation_unavailable_reason"] == "normalization_snapshot_unavailable"
    )


def test_old_schema_missing_native_input_is_explicitly_unavailable(snapshot):
    path, config, queries, client = snapshot
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE photos DROP COLUMN histogram_spread")
    result = get(client)
    assert result["aggregate"] == 2.0 and result["current_formula_score"] is None
    assert result["explanation_unavailable_reason"] == "missing_scoring_inputs"


def test_disabled_normalization_uses_stored_metrics_without_library_scan(snapshot):
    path, config, queries, client = snapshot
    config.get_normalization_settings = lambda: {"method": "none"}
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM stats_cache")
    result = get(client)
    assert result["current_formula_score"] == 1.0
    assert result["normalization_basis"] == "stored_metrics"
    assert not any("ORDER BY" in sql.upper() for sql in queries)


def test_visibility_is_applied_before_any_explanation(snapshot):
    path, config, queries, client = snapshot
    with mock.patch.object(critique, "get_visibility_clause", return_value=("0=1", [])):
        response = client.get("/api/critique", params={"path": "synthetic"})
    assert response.status_code == 404


def test_override_is_loaded_for_the_one_selected_photo(snapshot):
    path, config, queries, client = snapshot
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO photo_scoring_overrides VALUES('synthetic',NULL,'portrait')"
        )
        conn.execute(
            "INSERT INTO photo_scoring_overrides VALUES('unrelated',NULL,'landscape')"
        )
    result = get(client)
    assert result["category"] == "portrait"
    assert result["category_reason"]["reason_key"] == "override"
    selected = [sql for sql in queries if sql.startswith("SELECT photo_path")]
    assert len(selected) == 1 and "WHERE photo_path IN ('synthetic')" in selected[0]


def test_malformed_sqlite_numeric_input_preserves_stored_score(snapshot):
    import struct

    path, config, queries, client = snapshot
    histogram = [0.0] * 256
    histogram[128] = 1.0
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE photos SET histogram_data=?,histogram_bimodality=?",
            (struct.pack("256f", *histogram), "bad"),
        )
    result = get(client)
    assert result["aggregate"] == 2.0 and result["stored_score_state"] == "present"
    assert result["current_formula_score"] is None and result["breakdown"] == []
    assert result["explanation_unavailable_reason"] == "invalid_scoring_inputs"


def test_unavailable_normalization_does_not_invent_a_default_category_reason(snapshot):
    path, config, queries, client = snapshot
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE photos SET category='portrait'")
        conn.execute("UPDATE stats_cache SET value='{invalid'")
    result = get(client)
    assert result["category"] == result["category_reason"]["category"] == "portrait"
    assert result["category_reason"]["reason_key"] == "unavailable"
