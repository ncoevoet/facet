"""The OCR extractor degrades to a clean no-op when no engine is installed,
applies the configured confidence gate, and honours the None / '' contract that
``photos.ocr_text`` stores verbatim.

No test here requires a real OCR binary or model — engine resolution is patched
so the suite stays hermetic. The real-model pass lives in ``test_ocr_pass.py``.
"""

from unittest import mock

import pytest

from analyzers import ocr


@pytest.fixture(autouse=True)
def _reset_engine_cache():
    """Each test starts with a fresh engine-resolution cache and default config."""
    ocr.configure(None)
    yield
    ocr.configure(None)


def _engine(*detections):
    """A stand-in engine returning ``(text, confidence)`` pairs."""
    return mock.Mock(return_value=list(detections))


def _with_engine(engine):
    """Patch the easyocr builder (first in the preference order) to yield ``engine``."""
    return mock.patch.object(ocr, "_build_easyocr_engine", return_value=engine)


# --- no engine available -> graceful no-op --------------------------------- #

def test_no_engine_returns_none():
    with (
        mock.patch.object(ocr, "_build_easyocr_engine", return_value=None),
        mock.patch.object(ocr, "_build_pytesseract_engine", return_value=None),
    ):
        assert ocr.is_ocr_available() is False
        # A dummy non-None image still yields None (never raises).
        assert ocr.extract_text(object()) is None


def test_no_engine_warns_once():
    with (
        mock.patch.object(ocr, "_build_easyocr_engine", return_value=None),
        mock.patch.object(ocr, "_build_pytesseract_engine", return_value=None),
        mock.patch.object(ocr.logger, "warning") as warn,
    ):
        ocr.extract_text(object())
        ocr.extract_text(object())
        ocr.extract_text(object())
    assert warn.call_count == 1


def test_none_image_returns_none_without_resolving_engine():
    with mock.patch.object(ocr, "_resolve_engine") as resolve:
        assert ocr.extract_text(None) is None
        resolve.assert_not_called()


# --- the None / '' sentinel contract --------------------------------------- #

def test_engine_that_finds_nothing_returns_empty_string_not_none():
    """'' means "evaluated, no text" — the sentinel that stops --detect-text
    from re-OCRing every textless photo on the next run."""
    with _with_engine(_engine()):
        assert ocr.extract_text("img") == ""


def test_whitespace_only_detection_is_treated_as_no_text():
    with _with_engine(_engine(("   \n\t ", 0.99))):
        assert ocr.extract_text("img") == ""


def test_engine_exception_returns_none_so_the_row_stays_unevaluated():
    """A transient engine failure must not be recorded as "evaluated, no text",
    or the photo would never be retried."""
    with _with_engine(mock.Mock(side_effect=RuntimeError("boom"))):
        assert ocr.extract_text("img") is None


# --- text extraction and normalization ------------------------------------- #

def test_detections_are_joined_and_whitespace_collapsed():
    with _with_engine(_engine(("  Hello\n\n ", 0.9), ("WORLD  \t", 0.8))):
        assert ocr.extract_text("img") == "Hello WORLD"


def test_engine_receives_the_image():
    engine = _engine(("text", 0.9))
    with _with_engine(engine):
        ocr.extract_text("img-stand-in")
    engine.assert_called_once_with("img-stand-in")


def test_engine_resolution_is_cached():
    builder = mock.Mock(return_value=_engine(("text", 0.9)))
    with mock.patch.object(ocr, "_build_easyocr_engine", builder):
        ocr.extract_text("a")
        ocr.extract_text("b")
    assert builder.call_count == 1


def test_easyocr_is_preferred_over_pytesseract():
    """CRAFT beats tesseract on scene text, which is what in-photo search is for."""
    easy = _engine(("from easyocr", 0.9))
    tess = _engine(("from tesseract", 0.9))
    with (
        mock.patch.object(ocr, "_build_easyocr_engine", return_value=easy),
        mock.patch.object(ocr, "_build_pytesseract_engine", return_value=tess),
    ):
        assert ocr.extract_text("img") == "from easyocr"


def test_pytesseract_is_used_when_easyocr_is_absent():
    tess = _engine(("from tesseract", 0.9))
    with (
        mock.patch.object(ocr, "_build_easyocr_engine", return_value=None),
        mock.patch.object(ocr, "_build_pytesseract_engine", return_value=tess),
    ):
        assert ocr.extract_text("img") == "from tesseract"


# --- confidence gate ------------------------------------------------------- #

def test_detections_below_min_confidence_are_dropped():
    ocr.configure({"min_confidence": 0.5})
    with _with_engine(_engine(("solid", 0.9), ("noise", 0.1))):
        assert ocr.extract_text("img") == "solid"


def test_min_confidence_boundary_is_inclusive():
    ocr.configure({"min_confidence": 0.4})
    with _with_engine(_engine(("exactly", 0.4))):
        assert ocr.extract_text("img") == "exactly"


def test_all_detections_below_threshold_yield_the_empty_sentinel():
    ocr.configure({"min_confidence": 0.8})
    with _with_engine(_engine(("blurry", 0.2))):
        assert ocr.extract_text("img") == ""


# --- configure() ----------------------------------------------------------- #

def test_configure_applies_languages_and_confidence():
    ocr.configure({"languages": ["de", "it"], "min_confidence": 0.75})
    assert ocr.get_settings() == (["de", "it"], 0.75)


def test_configure_falls_back_to_defaults_for_junk_values():
    ocr.configure({"languages": "not-a-list", "min_confidence": "nonsense"})
    assert ocr.get_settings() == (list(ocr.DEFAULT_LANGUAGES), ocr.DEFAULT_MIN_CONFIDENCE)


def test_configure_with_empty_language_list_falls_back_to_defaults():
    ocr.configure({"languages": []})
    assert ocr.get_settings()[0] == list(ocr.DEFAULT_LANGUAGES)


def test_configure_drops_a_cached_engine_so_languages_take_effect():
    """The language list is baked into the loaded reader, so a stale engine
    would keep answering with the previous languages."""
    builder = mock.Mock(return_value=_engine(("text", 0.9)))
    with mock.patch.object(ocr, "_build_easyocr_engine", builder):
        ocr.extract_text("a")
        ocr.configure({"languages": ["de"]})
        ocr.extract_text("b")
    assert builder.call_count == 2
