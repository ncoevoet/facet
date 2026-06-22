"""
OCR text-in-image extraction for Facet (opt-in, lazy).

Used only by the ``--recompute-ocr`` pass — never by the default scan pipeline.
The OCR engine is imported lazily and the module degrades to a graceful no-op
when no engine (or its native binary/model) is installed: every extraction call
returns ``None`` and a single warning is logged so the recompute pass can run
to completion without writing anything.

Engine preference order:
  1. ``pytesseract`` (only if the ``tesseract`` binary is on PATH)
  2. ``easyocr``
  3. ``paddleocr``
"""

import logging
import threading

logger = logging.getLogger("facet.ocr")

# Resolved engine cache. ``_ENGINE`` is one of:
#   None      — not yet probed
#   False     — probed, nothing usable (no-op mode)
#   callable  — a function (pil_image) -> str that runs OCR
_ENGINE = None
_ENGINE_LOCK = threading.Lock()
_NO_ENGINE_WARNED = False


def _build_pytesseract_engine():
    """Return a pytesseract OCR callable, or None if unusable.

    Requires both the ``pytesseract`` package AND the ``tesseract`` binary on
    PATH (pytesseract is a thin wrapper that shells out to it).
    """
    try:
        import shutil

        import pytesseract
    except ImportError:
        return None
    if shutil.which("tesseract") is None:
        # Package present but no native binary — unusable, fall through.
        return None

    def _run(pil_image):
        return pytesseract.image_to_string(pil_image)

    logger.info("OCR engine: pytesseract (tesseract binary found)")
    return _run


def _build_easyocr_engine():
    """Return an easyocr OCR callable, or None if unusable."""
    try:
        import numpy as np
        import easyocr
    except ImportError:
        return None
    try:
        reader = easyocr.Reader(["en"], gpu=False)
    except Exception:
        logger.warning("easyocr present but failed to initialise", exc_info=True)
        return None

    def _run(pil_image):
        results = reader.readtext(np.asarray(pil_image.convert("RGB")), detail=0)
        return " ".join(results)

    logger.info("OCR engine: easyocr")
    return _run


def _build_paddleocr_engine():
    """Return a paddleocr OCR callable, or None if unusable."""
    try:
        import numpy as np
        from paddleocr import PaddleOCR
    except ImportError:
        return None
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    except Exception:
        logger.warning("paddleocr present but failed to initialise", exc_info=True)
        return None

    def _run(pil_image):
        result = ocr.ocr(np.asarray(pil_image.convert("RGB")), cls=True)
        lines = []
        for page in result or []:
            for entry in page or []:
                # entry = [box, (text, confidence)]
                try:
                    lines.append(entry[1][0])
                except (IndexError, TypeError):
                    continue
        return " ".join(lines)

    logger.info("OCR engine: paddleocr")
    return _run


def _resolve_engine():
    """Resolve (and cache) the OCR engine callable, or False if none usable."""
    global _ENGINE, _NO_ENGINE_WARNED
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        for builder in (
            _build_pytesseract_engine,
            _build_easyocr_engine,
            _build_paddleocr_engine,
        ):
            engine = builder()
            if engine is not None:
                _ENGINE = engine
                return _ENGINE
        if not _NO_ENGINE_WARNED:
            logger.warning(
                "No OCR engine available (install pytesseract+tesseract, "
                "easyocr, or paddleocr). --recompute-ocr will be a no-op."
            )
            _NO_ENGINE_WARNED = True
        _ENGINE = False
        return _ENGINE


def is_ocr_available():
    """True if an OCR engine could be resolved (without crashing if not)."""
    return bool(_resolve_engine())


def extract_text(pil_image):
    """Run OCR on a PIL image, returning normalized text or None.

    Returns ``None`` (never raises) when:
      - no OCR engine is installed/usable,
      - the image is missing,
      - the engine raises, or
      - no text was detected.

    The returned string is whitespace-collapsed; empty results map to None so
    callers can store NULL and FTS does not index blank rows.
    """
    if pil_image is None:
        return None
    engine = _resolve_engine()
    if not engine:
        return None
    try:
        raw = engine(pil_image)
    except Exception:
        logger.warning("OCR extraction failed", exc_info=True)
        return None
    if not raw:
        return None
    text = " ".join(str(raw).split())
    return text or None


def reset_engine_cache():
    """Clear the resolved-engine cache (test helper)."""
    global _ENGINE, _NO_ENGINE_WARNED
    with _ENGINE_LOCK:
        _ENGINE = None
        _NO_ENGINE_WARNED = False
