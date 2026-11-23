"""Synthetic API/UI-contract coverage for the data-gated metric sort options."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict

import pytest

import licensing
from api.database import get_db
from api.types import DATA_GATED_SORT_COLS, VALID_SORT_COLS, reset_data_gate_cache

# Reads client, i18n or docs files: runs on every pull request (see ci.yml).
pytestmark = pytest.mark.cross_file

KEYS_TS = (Path(__file__).resolve().parents[1] / "client/src/app/core/i18n/keys.ts").read_text()


def _check_qrealign(lang: str, labels: Dict[str, str]) -> None:
    label = labels["qrealign_score"].strip()
    assert label.startswith("Q-ReAlign")
    if lang == "zh":
        assert label != labels["aesthetic"] and labels["aesthetic"] in label


def _check_deqa(lang: str, labels: Dict[str, str]) -> None:
    assert labels["deqa_score"].strip()


def _check_aesthetic_v25(lang: str, labels: Dict[str, str]) -> None:
    label = labels["aesthetic_v25"].strip()
    assert label.endswith("v2.5")
    if lang == "en":
        assert label == "Aesthetic v2.5"
    elif lang == "zh":
        assert label != labels["aesthetic"] and label != "Aesthetic v2.5"
    else:
        assert label.startswith(labels["aesthetic"]) and label != "Aesthetic v2.5"


# Not a model metric (no loader, a TEXT stamp): gated only because an upgraded library
# has no date until a scan rewrites its rows. Covered by its own tests below.
DATE_ADDED = 'date_added'


@dataclass(frozen=True)
class Spec:
    column: str
    loader: str
    label: str
    prefix: str
    check_label: Callable[[str, Dict[str, str]], None]


SPECS = [
    Spec('qrealign_score', 'qrealign', 'Q-ReAlign (Aesthetic)', "/qrealign_score-sort/", _check_qrealign),
    Spec('deqa_score', 'deqa', 'DeQA', "/deqa_score-sort/", _check_deqa),
    Spec('aesthetic_v25', 'aesthetic_v25', 'Aesthetic v2.5', "/aesthetic_v25-sort/", _check_aesthetic_v25),
]


@pytest.fixture(params=SPECS, ids=[s.column for s in SPECS])
def spec(request):
    return request.param


@pytest.fixture
def populated(spec, seed_photos_prefix):
    """One scored photo, so the data gate lists the sort; the cache is dropped around it."""
    reset_data_gate_cache()
    seed_photos_prefix(spec.prefix + "gate/", [
        {"path": spec.prefix + "gate/a.jpg", "filename": "a.jpg", "aggregate": 5.0, spec.column: 6.0}])
    reset_data_gate_cache()
    yield
    reset_data_gate_cache()


def _advertised(body):
    flat = [column for column, _ in body["sort_options"]]
    grouped = [option["column"] for options in body["sort_options_grouped"].values()
               for option in options]
    return flat, grouped


def test_every_data_gated_column_is_covered():
    assert set(DATA_GATED_SORT_COLS) == {s.column for s in SPECS} | {DATE_ADDED}


def test_metric_is_advertised_and_allowed(spec, populated, anonymous_client):
    response = anonymous_client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert [spec.column, spec.label] in body["sort_options"]
    assert spec.column in _advertised(body)[1]
    assert spec.column in VALID_SORT_COLS


def test_sort_hidden_while_no_photo_has_a_score(spec, anonymous_client):
    column = spec.column  # trusted constant from SPECS, interpolated into SQL
    reset_data_gate_cache()
    with get_db() as conn:
        scored = conn.execute(
            f"SELECT path, {column} FROM photos WHERE {column} IS NOT NULL").fetchall()
        conn.execute(f"UPDATE photos SET {column} = NULL")
        conn.commit()
    try:
        response = anonymous_client.get("/api/config")
        assert response.status_code == 200
        flat, grouped = _advertised(response.json())
        assert column not in flat and column not in grouped
        assert column in VALID_SORT_COLS
    finally:
        with get_db() as conn:
            conn.executemany(f"UPDATE photos SET {column} = ? WHERE path = ?",
                             [(row[column], row['path']) for row in scored])
            conn.commit()
        reset_data_gate_cache()


@pytest.mark.parametrize("lang", ["en", "fr", "de", "it", "es", "pt", "zh"])
def test_metric_label_is_translated(spec, lang, anonymous_client):
    response = anonymous_client.get(f"/api/i18n/{lang}")
    assert response.status_code == 200
    spec.check_label(lang, response.json()["sort_options"])
    assert f'sort_options.{spec.column}' in KEYS_TS


@pytest.mark.parametrize("direction,expected", [
    ("ASC", ["b_zero", "c_tie", "d_tie", "e_high", "a_null"]),
    ("DESC", ["e_high", "c_tie", "d_tie", "b_zero", "a_null"]),
])
def test_gallery_numeric_order_null_ties_and_pages(
    spec, direction, expected, seed_photos_prefix, anonymous_client,
):
    column, prefix = spec.column, spec.prefix
    values = [("a_null", None), ("b_zero", 0.0), ("c_tie", 3.0),
              ("d_tie", 3.0), ("e_high", 8.0)]
    seed_photos_prefix(prefix, [
        {"path": prefix + name + ".jpg", "filename": name + ".jpg",
         "aggregate": 5.0, column: score} for name, score in values
    ])
    params = {"sort": column, "sort_direction": direction, "path_prefix": prefix}
    response = anonymous_client.get("/api/photos", params=params)
    assert response.status_code == 200, response.text
    photos = response.json()["photos"]
    assert [photo["filename"] for photo in photos] == [name + ".jpg" for name in expected]
    assert photos[-1][column] is None
    assert {photo[column] for photo in photos[:-1]} == {0.0, 3.0, 8.0}
    paged = []
    for page in (1, 2, 3):
        response = anonymous_client.get("/api/photos", params={**params, "page": page, "per_page": 2})
        assert response.status_code == 200, response.text
        paged.extend(photo["filename"] for photo in response.json()["photos"])
    assert paged == [name + ".jpg" for name in expected]


@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_all_unscored_rows_remain_visible(spec, direction, seed_photos_prefix, anonymous_client):
    seed_photos_prefix(spec.prefix, [
        {"path": spec.prefix + name, "filename": name, "aggregate": 5.0}
        for name in ("a.jpg", "b.jpg")
    ])
    response = anonymous_client.get("/api/photos", params={
        "sort": spec.column, "sort_direction": direction, "path_prefix": spec.prefix,
    })
    assert response.status_code == 200, response.text
    assert [photo["filename"] for photo in response.json()["photos"]] == ["a.jpg", "b.jpg"]


@pytest.mark.parametrize("mode,allow_unclear", [
    ("default", False), ("commercial", False), ("commercial", True),
])
def test_sort_visibility_follows_existing_loader_license(
    spec, mode, allow_unclear, populated, anonymous_client,
):
    licensing.set_policy(mode, allow_unclear=allow_unclear)
    allowed = licensing.loader_allowed(spec.loader)
    response = anonymous_client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    flat = {column for column, _ in body["sort_options"]}
    grouped = {option["column"] for options in body["sort_options_grouped"].values()
               for option in options}
    assert (spec.column in flat) is allowed
    assert (spec.column in grouped) is allowed
    assert (spec.column in body["unavailable_metrics"]) is not allowed


def _advertises_date_added(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    flat, grouped = _advertised(response.json())
    assert (DATE_ADDED in flat) == (DATE_ADDED in grouped)
    return DATE_ADDED in flat


def test_date_added_sort_waits_for_a_dated_photo(seed_photos_prefix, anonymous_client):
    """An upgraded, unrescanned library has no Date Added: the sort would only order by path."""
    with get_db() as conn:
        dated = conn.execute("SELECT path, date_added FROM photos WHERE date_added IS NOT NULL").fetchall()
        conn.execute("UPDATE photos SET date_added = NULL")
        conn.commit()
    try:
        reset_data_gate_cache()
        assert not _advertises_date_added(anonymous_client)
        assert DATE_ADDED in VALID_SORT_COLS
        prefix = "/date_added-sort/gate/"
        seed_photos_prefix(prefix, [{"path": prefix + "a.jpg", "filename": "a.jpg", "aggregate": 5.0,
                                     DATE_ADDED: "2026-11-23T09:00:00Z"}])
        reset_data_gate_cache()
        assert _advertises_date_added(anonymous_client)
    finally:
        with get_db() as conn:
            conn.executemany("UPDATE photos SET date_added = ? WHERE path = ?",
                             [(row["date_added"], row["path"]) for row in dated])
            conn.commit()
        reset_data_gate_cache()
