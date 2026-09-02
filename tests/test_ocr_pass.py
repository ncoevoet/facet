"""End-to-end coverage for the ``--detect-text`` / ``--recompute-text`` OCR pass.

These tests drive the real CLI against a temp database seeded with PIL-rendered
thumbnails carrying known text, and run the real OCR model on CPU. They are
skipped when no engine + weights are present, so a bare checkout still gets a
green suite; the hermetic extractor tests live in ``test_ocr_extractor.py``.
"""

import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.schema import init_database  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FACET_SCRIPT = str(_REPO_ROOT / "facet.py")
_REPO_CONFIG = _REPO_ROOT / "config" / "scoring_config.default.json"

# The scope='text' MATCH expression api/routers/search.py builds; pinned here so
# the OCR pass is proven searchable through the same expression the API uses.
_TEXT_SCOPE_MATCH = '{caption caption_translated ocr_text} : ("%s"*)'

SIGN_TEXT = "DANGER HIGH VOLTAGE"
SHOP_TEXT = "Boulangerie Patisserie"


def _real_ocr_available():
    """True when an engine AND its weights are on this host.

    The weight check matters: easyocr imports fine without them and would try to
    download ~113MB mid-test, which is not something a unit suite should do.
    """
    try:
        import easyocr  # noqa: F401
    except ImportError:
        return False
    model_dir = Path(os.environ.get("EASYOCR_MODULE_PATH",
                                    Path.home() / ".EasyOCR")) / "model"
    return (model_dir / "craft_mlt_25k.pth").exists()


requires_ocr = pytest.mark.skipif(
    not _real_ocr_available(),
    reason="no OCR engine + weights on this host (see docs/CONFIGURATION.md 'ocr')",
)


def _font(draw, text, width):
    """Largest DejaVu size that fits ``text`` in ``width``, else the default font."""
    try:
        for points in range(56, 9, -2):
            candidate = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", points)
            left, _, right, _ = draw.textbbox((0, 0), text, font=candidate)
            if right - left <= width - 40:
                return candidate
    except OSError:
        pass
    return ImageFont.load_default(40)


def _render(text, size=(640, 400)):
    """A white JPEG thumbnail with ``text`` centred on it, or blank when None."""
    img = Image.new("RGB", size, "white")
    if text:
        draw = ImageDraw.Draw(img)
        font = _font(draw, text, size[0])
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        draw.text(((size[0] - (right - left)) / 2 - left,
                   (size[1] - (bottom - top)) / 2 - top),
                  text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _seed_db(db_path, rows):
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    for path, text in rows:
        conn.execute(
            "INSERT INTO photos (path, filename, thumbnail) VALUES (?, ?, ?)",
            (path, path.rsplit("/", 1)[-1], _render(text)))
    conn.commit()
    conn.close()


def _write_config(tmp_path, **overrides):
    """The shipped default config with the ``ocr`` block enabled (plus any overrides)."""
    config = json.loads(_REPO_CONFIG.read_text(encoding="utf-8"))
    config["ocr"] = {**config.get("ocr", {}), "enabled": True, **overrides}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return str(config_path)


def _run_facet(*argv):
    return subprocess.run(
        [sys.executable, _FACET_SCRIPT, *argv],
        capture_output=True, text=True, timeout=600, cwd=str(_REPO_ROOT))


def _ocr_text(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return dict(conn.execute("SELECT path, ocr_text FROM photos").fetchall())
    finally:
        conn.close()


def _fts_paths(db_path, match):
    conn = sqlite3.connect(db_path)
    try:
        return {row[0] for row in conn.execute(
            "SELECT path FROM photos_fts WHERE photos_fts MATCH ?", (match,))}
    finally:
        conn.close()


# --- gating (no engine required) ------------------------------------------- #

def test_detect_text_refuses_when_ocr_is_disabled(tmp_path):
    db_path = str(tmp_path / "photos.db")
    _seed_db(db_path, [("/photos/sign.jpg", SIGN_TEXT)])
    config_path = _write_config(tmp_path, enabled=False)

    result = _run_facet("--detect-text", "--db", db_path, "--config", config_path)

    assert "disabled" in (result.stdout + result.stderr)
    assert _ocr_text(db_path) == {"/photos/sign.jpg": None}


def test_detect_text_is_a_classified_library_job():
    """It rewrites photos.ocr_text library-wide, so it must hold the library lock."""
    from facet import LIBRARY_JOB_ARGS

    assert "detect_text" in LIBRARY_JOB_ARGS
    assert "recompute_text" in LIBRARY_JOB_ARGS


# --- the real pass --------------------------------------------------------- #

@pytest.fixture(scope="module")
def detected(tmp_path_factory):
    """One real ``--detect-text`` run over three seeded photos, shared by the
    assertions below so the model is loaded once for the whole module."""
    if not _real_ocr_available():
        pytest.skip("no OCR engine + weights on this host")
    tmp_path = tmp_path_factory.mktemp("ocr")
    db_path = str(tmp_path / "photos.db")
    _seed_db(db_path, [
        ("/photos/sign.jpg", SIGN_TEXT),
        ("/photos/shop.jpg", SHOP_TEXT),
        ("/photos/sky.jpg", None),
    ])
    config_path = _write_config(tmp_path)
    result = _run_facet("--detect-text", "--db", db_path, "--config", config_path)
    assert result.returncode == 0, result.stdout + result.stderr
    return db_path, config_path


@requires_ocr
def test_detect_text_reads_the_text_in_the_photo(detected):
    db_path, _ = detected
    stored = _ocr_text(db_path)

    assert stored["/photos/sign.jpg"] == SIGN_TEXT
    assert stored["/photos/shop.jpg"] == SHOP_TEXT


@requires_ocr
def test_a_photo_without_text_gets_the_empty_sentinel_not_null(detected):
    """'' is "evaluated, no text"; NULL stays "never evaluated"."""
    db_path, _ = detected

    assert _ocr_text(db_path)["/photos/sky.jpg"] == ""


@requires_ocr
def test_detected_text_is_searchable_without_rebuilding_fts(detected):
    """``ocr_text`` is in the FTS trigger's UPDATE OF list, so the pass's own
    UPDATE re-indexes the row — no --rebuild-fts step for an existing DB."""
    db_path, _ = detected

    assert _fts_paths(db_path, "voltage") == {"/photos/sign.jpg"}
    assert _fts_paths(db_path, "boulangerie") == {"/photos/shop.jpg"}


@requires_ocr
def test_detected_text_matches_through_the_api_text_scope_expression(detected):
    """The exact MATCH string api/routers/search.py builds for ?scope=text."""
    db_path, _ = detected

    assert _fts_paths(db_path, _TEXT_SCOPE_MATCH % "voltage") == {"/photos/sign.jpg"}


@requires_ocr
def test_a_blank_photo_never_matches_a_search(detected):
    db_path, _ = detected

    assert "/photos/sky.jpg" not in _fts_paths(db_path, "voltage")
    assert "/photos/sky.jpg" not in _fts_paths(db_path, "boulangerie")


# --- scoping --------------------------------------------------------------- #

@requires_ocr
def test_rerunning_detect_text_skips_already_evaluated_photos(tmp_path):
    """Both a text-bearing row and the '' sentinel must be left alone, or every
    textless photo would be re-OCRed on every run."""
    db_path = str(tmp_path / "photos.db")
    _seed_db(db_path, [("/photos/sign.jpg", SIGN_TEXT), ("/photos/sky.jpg", None)])
    config_path = _write_config(tmp_path)

    assert _run_facet("--detect-text", "--db", db_path,
                      "--config", config_path).returncode == 0

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE photos SET ocr_text = 'SENTINEL MARKER' "
                 "WHERE path = '/photos/sign.jpg'")
    conn.execute("INSERT INTO photos (path, filename, thumbnail) VALUES (?, ?, ?)",
                 ("/photos/new.jpg", "new.jpg", _render(SHOP_TEXT)))
    conn.commit()
    conn.close()

    assert _run_facet("--detect-text", "--db", db_path,
                      "--config", config_path).returncode == 0

    stored = _ocr_text(db_path)
    # Untouched: an evaluated row is out of scope even when its text is wrong.
    assert stored["/photos/sign.jpg"] == "SENTINEL MARKER"
    assert stored["/photos/sky.jpg"] == ""
    # The only never-evaluated row is the one that got read.
    assert stored["/photos/new.jpg"] == SHOP_TEXT


# --- full_resolution ------------------------------------------------------- #

@requires_ocr
def test_full_resolution_reads_the_original_instead_of_the_thumbnail(tmp_path):
    """Discriminating fixture: the thumbnail is blank and only the original on
    disk carries text, so finding it proves the original was the source."""
    original = tmp_path / "plate.jpg"
    _rendered = Image.open(io.BytesIO(_render(SHOP_TEXT, size=(2400, 1600))))
    _rendered.save(original, "JPEG", quality=92)

    db_path = str(tmp_path / "photos.db")
    init_database(db_path)
    blank = io.BytesIO()
    Image.new("RGB", (640, 427), "white").save(blank, "JPEG", quality=80)
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO photos (path, filename, thumbnail) VALUES (?, ?, ?)",
                 (str(original), "plate.jpg", blank.getvalue()))
    conn.commit()
    conn.close()

    # Thumbnail-only: nothing to read, so the row gets the '' sentinel.
    assert _run_facet("--detect-text", "--db", db_path,
                      "--config", _write_config(tmp_path)).returncode == 0
    assert _ocr_text(db_path)[str(original)] == ""

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE photos SET ocr_text = NULL")
    conn.commit()
    conn.close()

    config_path = _write_config(tmp_path, full_resolution=True)
    assert _run_facet("--detect-text", "--db", db_path,
                      "--config", config_path).returncode == 0
    assert _ocr_text(db_path)[str(original)] == SHOP_TEXT


@requires_ocr
def test_full_resolution_falls_back_to_the_thumbnail_when_the_original_is_gone(tmp_path):
    """An offline volume must not turn the pass into a crash or a wrong sentinel."""
    db_path = str(tmp_path / "photos.db")
    _seed_db(db_path, [("/nonexistent/gone.jpg", SIGN_TEXT)])
    config_path = _write_config(tmp_path, full_resolution=True)

    assert _run_facet("--detect-text", "--db", db_path,
                      "--config", config_path).returncode == 0

    assert _ocr_text(db_path)["/nonexistent/gone.jpg"] == SIGN_TEXT


@requires_ocr
def test_recompute_text_re_reads_already_evaluated_photos(tmp_path):
    db_path = str(tmp_path / "photos.db")
    _seed_db(db_path, [("/photos/sign.jpg", SIGN_TEXT)])
    config_path = _write_config(tmp_path)

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE photos SET ocr_text = 'STALE'")
    conn.commit()
    conn.close()

    assert _run_facet("--recompute-text", "--db", db_path,
                      "--config", config_path).returncode == 0

    assert _ocr_text(db_path)["/photos/sign.jpg"] == SIGN_TEXT
