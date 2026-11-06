"""DB-backed checks for the capsule generators' fixed-width date predicates.

``date_taken`` is stored in EXIF form (``2025:03:01 10:00:00``). The generators
slice it with SUBSTR instead of converting each row through strftime, so these
tests pin what that must still produce: the user-visible ``2025-03`` month key
(which also feeds ``_stable_id``) and the exclusion of malformed dates.
"""

import sqlite3

import pytest

import analyzers.capsule_generator as capsule_generator
from analyzers.capsule_generator import _generate_color_palette, _generate_dimension_capsules, _stable_id
from db.schema import init_database

_ALL_VISIBLE = ("1=1", [])


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "capsules.db"
    init_database(str(db_path))
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    monkeypatch.setattr("api.db_helpers.is_photo_tags_available", lambda: False)
    yield connection
    connection.close()


def _seed(conn, dates):
    conn.executemany(
        "INSERT INTO photos (path, filename, date_taken, aggregate, mean_saturation, is_monochrome) "
        "VALUES (?, ?, ?, 8.0, 0.9, 0)",
        [(f"/lib/{i}.jpg", f"{i}.jpg", d) for i, d in enumerate(dates)],
    )
    conn.commit()


def _capsules_of(conn, dim_type):
    return [c for c in _generate_dimension_capsules(conn, {}, 0, _ALL_VISIBLE, None) if c["type"] == dim_type]


def test_month_capsule_keeps_dash_form_and_stable_id(conn):
    _seed(conn, [f"2025:03:{d:02d} 10:00:00" for d in range(1, 13)])

    (month,) = _capsules_of(conn, "month")

    assert month["title"] == "2025-03"
    assert month["title_params"] == {"date": "2025-03"}
    assert month["id"] == f"month_{_stable_id('month', '2025-03')}"


def test_year_capsule_reads_the_year_slice(conn):
    _seed(conn, [f"2024:{m:02d}:01 10:00:00" for m in range(1, 13)] * 2)

    (year,) = _capsules_of(conn, "year")

    assert year["title"] == "2024"


def test_malformed_dates_are_excluded_from_month_groups(conn):
    # Twelve well-formed rows form the group; eight garbage rows sharing a
    # 7-char prefix must not form a second one.
    _seed(conn, [f"2025:03:{d:02d} 10:00:00" for d in range(1, 13)] + ["garbage-value"] * 8 + ["0000"] * 8)

    titles = [c["title"] for c in _capsules_of(conn, "month")]

    assert titles == ["2025-03"]


def test_color_palette_month_key_keeps_dash_form(conn):
    _seed(conn, [f"2025:03:{d:02d} 10:00:00" for d in range(1, 13)])

    capsules = _generate_color_palette(conn, {"color_palette": {"min_photos": 3}}, 0, _ALL_VISIBLE, None)

    assert [c["title_params"]["date"] for c in capsules] == ["2025-03"]
    assert capsules[0]["id"] == f"color_palette_{_stable_id('color_palette', '2025-03', 'Vibrant')}"


def test_year_month_expression_is_shared():
    assert capsule_generator._DIMENSIONS["month"]["sql_expr"] == capsule_generator._YEAR_MONTH
