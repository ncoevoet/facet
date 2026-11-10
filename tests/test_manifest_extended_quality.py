"""Extended scores survive portable JSON export without changing XMP/user data."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from db.schema import init_database
from processing.xmp_export import build_manifest

METRICS = ("qrealign_score", "aesthetic_v25", "deqa_score")
LEGACY = {
    "aggregate": 7.0,
    "aesthetic": 6.0,
    "comp_score": 5.0,
    "face_quality": 4.0,
    "tech_sharpness": 3.0,
    "exposure_score": 2.0,
    "color_score": 1.0,
}


def seed(tmp_path):
    db = str(tmp_path / "manifest.db")
    init_database(db)
    paths = []
    with sqlite3.connect(db) as conn:
        for name, value in [("zero", 0.0), ("missing", None), ("scored", 7.25)]:
            path = tmp_path / (name + ".jpg")
            path.write_bytes(b"synthetic-original")
            path.with_suffix(".xmp").write_text(
                '<foreign:metadata xmlns:foreign="urn:synthetic:test">keep</foreign:metadata>'
            )
            paths.append(str(path))
            row = dict(
                LEGACY,
                path=str(path),
                filename=path.name,
                tags="generated",
                star_rating=4,
                is_favorite=1,
                is_rejected=0,
                **{key: value for key in METRICS},
            )
            cols = list(row)
            conn.execute(
                "INSERT INTO photos("
                + ",".join(cols)
                + ") VALUES("
                + ",".join("?" for _ in cols)
                + ")",
                [row[c] for c in cols],
            )
            conn.execute(
                "INSERT INTO photo_manual_tags(photo_path,tag,source) VALUES(?,?,'user')",
                (str(path), "owner-keyword"),
            )
    return db, paths


@pytest.mark.parametrize("scope", ["all", "paths", "root"])
def test_json_roundtrip_preserves_extended_zero_null_and_legacy_user_data(
    tmp_path, scope
):
    db, paths = seed(tmp_path)
    before = {p: Path(p).read_bytes() for p in paths}
    sidecars = {p: Path(p).with_suffix(".xmp").read_bytes() for p in paths}
    kwargs = (
        {"paths": list(reversed(paths))}
        if scope == "paths"
        else {"root": str(tmp_path)}
        if scope == "root"
        else {}
    )
    output = json.loads(json.dumps(build_manifest(db, **kwargs), allow_nan=False))
    assert output["version"] == 2
    photos = {p["filename"]: p for p in output["photos"]}
    for name, value in [("zero", 0.0), ("missing", None), ("scored", 7.25)]:
        p = photos[name + ".jpg"]
        assert {k: p["scores"][k] for k in METRICS} == dict.fromkeys(METRICS, value)
        assert {k: p["scores"][k] for k in LEGACY} == LEGACY
        assert (
            p["star_rating"] == 4
            and p["is_favorite"] is True
            and p["is_rejected"] is False
        )
        assert p["tags"] == "generated, owner-keyword"
    assert before == {p: Path(p).read_bytes() for p in paths}
    assert sidecars == {p: Path(p).with_suffix(".xmp").read_bytes() for p in paths}


@pytest.mark.parametrize("scope", ["all", "paths", "root"])
@pytest.mark.parametrize("present", [(), ("qrealign_score",)])
def test_older_schema_omits_unsupported_scores_without_fabricated_nulls(
    tmp_path, present, scope
):
    db, paths = seed(tmp_path)
    removed = set(METRICS) - set(present)
    with sqlite3.connect(db) as conn:
        # Rebuild without ALTER TABLE DROP COLUMN (needs SQLite 3.35; floor is 3.31.1).
        kept = [
            row[1]
            for row in conn.execute("PRAGMA table_info(photos)")
            if row[1] not in removed
        ]
        cols = ",".join('"' + c + '"' for c in kept)
        conn.execute("CREATE TABLE photos_reduced AS SELECT " + cols + " FROM photos")
        # This fixture models older photo columns, before history/edit receipts.
        # Remove both modern trigger families before the table swap: preference
        # triggers otherwise reference photos while it is temporarily absent.
        triggers = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND (name GLOB 'organization_*' OR name GLOB 'metadata_review_*' OR name GLOB 'logical_*')"
        ).fetchall()
        for (name,) in triggers:
            conn.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        conn.execute("DROP TABLE photos")
        conn.execute("ALTER TABLE photos_reduced RENAME TO photos")
    kwargs = (
        {"paths": list(reversed(paths))}
        if scope == "paths"
        else {"root": str(tmp_path)}
        if scope == "root"
        else {}
    )
    photos = {p["filename"]: p for p in build_manifest(db, **kwargs)["photos"]}
    assert set(photos) == {"zero.jpg", "missing.jpg", "scored.jpg"}
    for name, value in [("zero", 0.0), ("missing", None), ("scored", 7.25)]:
        scores = photos[name + ".jpg"]["scores"]
        assert set(scores) == set(LEGACY) | set(present)
        assert {k: scores[k] for k in LEGACY} == LEGACY
        assert {k: scores[k] for k in present} == dict.fromkeys(present, value)


def test_cli_manifest_carries_extended_null_and_zero(tmp_path):
    db, _ = seed(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "facet.py"),
            "--db",
            db,
            "--export-manifest",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads((tmp_path / "facet_manifest.json").read_text())
    photos = {p["filename"]: p for p in output["photos"]}
    assert all(photos["zero.jpg"]["scores"][k] == 0 for k in METRICS)
    assert all(photos["missing.jpg"]["scores"][k] is None for k in METRICS)


def test_api_manifest_preserves_extended_null_and_zero(
    edition_client, seed_photos_prefix
):
    prefix = "/manifest-extended-quality-api/"
    rows = [
        dict(
            path=prefix + name + ".jpg",
            filename=name + ".jpg",
            aggregate=7.0,
            **dict.fromkeys(METRICS, value),
        )
        for name, value in [("zero", 0.0), ("missing", None), ("scored", 7.25)]
    ]
    seed_photos_prefix(prefix, rows)
    response = edition_client.post(
        "/api/lightroom/manifest", json={"paths": [r["path"] for r in rows]}
    )
    assert response.status_code == 200
    photos = {p["filename"]: p for p in response.json()["photos"]}
    for name, value in [("zero", 0.0), ("missing", None), ("scored", 7.25)]:
        assert {
            k: photos[name + ".jpg"]["scores"][k] for k in METRICS
        } == dict.fromkeys(METRICS, value)
