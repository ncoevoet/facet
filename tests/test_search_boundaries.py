"""Actual Unicode61 FTS and API filename searches, no source-photo access."""

import sqlite3
from unittest import mock
import pytest
from fastapi.testclient import TestClient
from api.routers import gallery
from tests.test_gallery import (
    _make_db,
    _photo,
    _create_app_no_auth,
    _VIEWER_CONFIG,
    _existing_columns,
    _async_conn_factory,
)


NAMES = [
    "IMG_0042.JPG",
    "IMG_0042.RAF",
    "DSC-9931.JPG",
    "Trip.Café-Ирина.JPG",
    "OR.JPG",
    "unrelated.JPG",
    "Αθη\u0301να.JPG",
    "한-夜.JPG",
    "AND.NOT.NEAR.JPG",
]


@pytest.fixture(autouse=True)
def reset_fts(monkeypatch):
    from db import fts

    monkeypatch.setattr(fts, "_fts_available", None)
    monkeypatch.setattr(fts, "_fts_checked_at", 0.0)


def sqlite_results(term: str) -> set[str]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE photos_fts USING fts5(filename)")
        connection.executemany(
            "INSERT INTO photos_fts VALUES(?)", [(name,) for name in NAMES]
        )
        query = gallery._fts5_query_from(term)
        if query is None:
            return set()
        return {
            row[0]
            for row in connection.execute(
                "SELECT filename FROM photos_fts WHERE photos_fts MATCH ?", (query,)
            )
        }
    finally:
        connection.close()


@pytest.mark.parametrize(
    "term,expected",
    [
        ("IMG_0042.JPG", {"IMG_0042.JPG"}),
        ("IMG_0042.RAF", {"IMG_0042.RAF"}),
        ("IMG_0042", {"IMG_0042.JPG", "IMG_0042.RAF"}),
        ("DSC-9931.JPG", {"DSC-9931.JPG"}),
        ("Trip.Café-Ирина.JPG", {"Trip.Café-Ирина.JPG"}),
        ("TRIP.CAFE\u0301-ИРИНА", {"Trip.Café-Ирина.JPG"}),
        ("Αθη\u0301να.JPG", {"Αθη\u0301να.JPG"}),
        ("한-夜.JPG", {"한-夜.JPG"}),
        ("AND.NOT.NEAR.JPG", {"AND.NOT.NEAR.JPG"}),
        ("NEAR(IMG DSC)", set()),
        ("Ирина", {"Trip.Café-Ирина.JPG"}),
        ("夜", {"한-夜.JPG"}),
        ("OR", {"OR.JPG"}),
        ("filename:unrelated.JPG", set()),
        ('" OR 1=1 --', set()),
        ('* : () "', set()),
        ("DSC-99", {"DSC-9931.JPG"}),
    ],
)
def test_real_sqlite_punctuation_unicode_literal_operators_and_prefix(term, expected):
    assert sqlite_results(term) == expected


@pytest.mark.parametrize(
    "term,expected",
    [
        ("IMG_0042.JPG", {"IMG_0042.JPG"}),
        ("DSC-9931.JPG", {"DSC-9931.JPG"}),
        ("Trip.Café-Ирина.JPG", {"Trip.Café-Ирина.JPG"}),
        ("IMG_0042", {"IMG_0042.JPG", "IMG_0042.RAF"}),
        ("Αθη\u0301να.JPG", {"Αθη\u0301να.JPG"}),
        ("한-夜.JPG", {"한-夜.JPG"}),
        ("filename:unrelated.JPG", set()),
        ("OR", {"OR.JPG"}),
        ('* : () "', set()),
    ],
)
def test_full_api_uses_real_fts_for_filename(tmp_path, term, expected):
    path = str(tmp_path / "photos.db")
    _make_db(
        path,
        [
            _photo("/fixture/" + name, "2020:01:01 00:00:00", filename=name)
            for name in NAMES
        ],
    )
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM photos_fts").fetchone()[
            0
        ] == len(NAMES)
    app = _create_app_no_auth()
    with (
        mock.patch("api.routers.gallery.get_async_db", _async_conn_factory(path)),
        mock.patch("api.routers.gallery.VIEWER_CONFIG", _VIEWER_CONFIG),
        mock.patch("api.db_helpers._existing_columns_cache", _existing_columns(path)),
        mock.patch.dict("api.config._count_cache", {}, clear=True),
    ):
        response = TestClient(app).get("/api/photos", params={"search": term})
    assert response.status_code == 200, response.text
    assert {row["filename"] for row in response.json()["photos"]} == expected


def test_manual_tag_companion_keeps_exact_literal_input_and_share_exclusion(tmp_path):
    path = str(tmp_path / "photos.db")
    term = "Trip.Café-Ирина.JPG"
    _make_db(path, [_photo("/manual", "2020:01:01 00:00:00", filename="separate.jpg")])
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO photo_manual_tags(photo_path,tag,source) VALUES(?,?,'user')",
            ("/manual", term),
        )
        for include_manual, expected, correlated in (
            (True, {"/manual"}, False), (False, set(), False),
            (True, {"/manual"}, True), (False, set(), True),
        ):
            clauses = []
            parameters = []
            gallery._apply_search_filter(
                clauses, parameters, term, connection, include_manual=include_manual,
                correlated=correlated,
            )
            assert {
                row[0]
                for row in connection.execute(
                    "SELECT path FROM photos WHERE " + " AND ".join(clauses), parameters
                )
            } == expected
