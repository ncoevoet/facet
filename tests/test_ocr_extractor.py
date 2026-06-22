"""Part A: the OCR extractor degrades to a clean no-op when no engine is
installed, and returns normalized text when an engine is mocked in.

No test here requires a real OCR binary or model — the engine resolution is
patched so the suite stays hermetic.
"""

from unittest import mock

import pytest

from analyzers import ocr


@pytest.fixture(autouse=True)
def _reset_engine_cache():
    """Each test starts with a fresh engine-resolution cache."""
    ocr.reset_engine_cache()
    yield
    ocr.reset_engine_cache()


# --- no engine available -> graceful no-op --------------------------------- #

def test_no_engine_returns_none(caplog):
    # All three builders report "nothing usable".
    with (
        mock.patch.object(ocr, "_build_pytesseract_engine", return_value=None),
        mock.patch.object(ocr, "_build_easyocr_engine", return_value=None),
        mock.patch.object(ocr, "_build_paddleocr_engine", return_value=None),
    ):
        assert ocr.is_ocr_available() is False
        # A dummy non-None image still yields None (never raises).
        assert ocr.extract_text(object()) is None


def test_no_engine_warns_once():
    with (
        mock.patch.object(ocr, "_build_pytesseract_engine", return_value=None),
        mock.patch.object(ocr, "_build_easyocr_engine", return_value=None),
        mock.patch.object(ocr, "_build_paddleocr_engine", return_value=None),
        mock.patch.object(ocr.logger, "warning") as warn,
    ):
        ocr.extract_text(object())
        ocr.extract_text(object())
        ocr.extract_text(object())
    # Warning emitted exactly once despite three calls.
    assert warn.call_count == 1


def test_none_image_returns_none_without_resolving_engine():
    # Should short-circuit before touching the engine.
    with mock.patch.object(ocr, "_resolve_engine") as resolve:
        assert ocr.extract_text(None) is None
        resolve.assert_not_called()


# --- engine mocked in -> returns normalized text --------------------------- #

def test_mocked_engine_returns_normalized_text():
    fake_engine = mock.Mock(return_value="  Hello\n\n  WORLD  \t")
    with mock.patch.object(ocr, "_build_pytesseract_engine", return_value=fake_engine):
        assert ocr.is_ocr_available() is True
        assert ocr.extract_text("img-stand-in") == "Hello WORLD"
    fake_engine.assert_called_once_with("img-stand-in")


def test_mocked_engine_empty_text_maps_to_none():
    fake_engine = mock.Mock(return_value="   \n\t  ")
    with mock.patch.object(ocr, "_build_pytesseract_engine", return_value=fake_engine):
        assert ocr.extract_text("img") is None


def test_engine_exception_is_swallowed():
    fake_engine = mock.Mock(side_effect=RuntimeError("boom"))
    with mock.patch.object(ocr, "_build_pytesseract_engine", return_value=fake_engine):
        # Engine raising must not propagate.
        assert ocr.extract_text("img") is None


def test_engine_resolution_is_cached():
    fake_engine = mock.Mock(return_value="text")
    builder = mock.Mock(return_value=fake_engine)
    with mock.patch.object(ocr, "_build_pytesseract_engine", builder):
        ocr.extract_text("a")
        ocr.extract_text("b")
    # Builder only invoked once — second call hits the cache.
    assert builder.call_count == 1
