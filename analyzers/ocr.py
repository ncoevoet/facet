"""
OCR text-in-image extraction for Facet (opt-in, lazy).

Used only by the ``--detect-text`` / ``--recompute-text`` passes — never by the
default scan pipeline. The OCR engine is imported lazily and the module
degrades to a graceful no-op when no engine (or its native binary/model) is
installed, so a pass can run to completion without writing anything.

Return contract — it mirrors the ``photos.ocr_text`` NULL / ``''`` sentinel so
the caller can store the value verbatim:

  ``None``  OCR could not run (no engine, missing image, engine raised). The
            caller must leave ``ocr_text`` NULL, keeping the row "never
            evaluated" so a later run retries it.
  ``''``    OCR ran and found no text above ``min_confidence``. Stored as the
            empty-string sentinel — the analogue of junk's ``not_junk`` — so
            ``--detect-text`` never re-reads the row. FTS5 indexes it as zero
            tokens, so a blank row can never match a query.

Engine preference order:
  1. ``easyocr`` — torch-based, so it rides the stack Facet already ships. Its
     CRAFT detector is markedly better than tesseract on *scene* text (signs,
     storefronts, posters), which is what an in-photo search is actually for.
  2. ``pytesseract`` — only when the ``tesseract`` binary is on PATH. The
     optional-external-tool fallback, in the same spirit as ``exiftool``.
"""

import logging
import threading

logger = logging.getLogger("facet.ocr")

DEFAULT_LANGUAGES = ('en', 'fr')
DEFAULT_MIN_CONFIDENCE = 0.4

# Resolved engine cache. ``_ENGINE`` is one of:
#   None      — not yet probed
#   False     — probed, nothing usable (no-op mode)
#   callable  — a function (pil_image) -> list[(text, confidence)]
_ENGINE = None
_ENGINE_LOCK = threading.RLock()
_NO_ENGINE_WARNED = False

_LANGUAGES = list(DEFAULT_LANGUAGES)
_MIN_CONFIDENCE = DEFAULT_MIN_CONFIDENCE


def configure(ocr_config=None):
    """Apply the ``ocr`` block of scoring_config.json.

    Resolving an engine bakes the language list into the loaded model, so any
    call here drops the cached engine rather than letting a stale reader keep
    answering with the previous languages.
    """
    global _LANGUAGES, _MIN_CONFIDENCE
    cfg = ocr_config if isinstance(ocr_config, dict) else {}

    languages = cfg.get('languages')
    if not isinstance(languages, (list, tuple)) or not languages:
        languages = DEFAULT_LANGUAGES

    try:
        min_confidence = float(cfg.get('min_confidence', DEFAULT_MIN_CONFIDENCE))
    except (TypeError, ValueError):
        min_confidence = DEFAULT_MIN_CONFIDENCE

    with _ENGINE_LOCK:
        _LANGUAGES = [str(lang) for lang in languages]
        _MIN_CONFIDENCE = min_confidence
        reset_engine_cache()


def get_settings():
    """Return the active ``(languages, min_confidence)`` (test/diagnostic helper)."""
    with _ENGINE_LOCK:
        return list(_LANGUAGES), _MIN_CONFIDENCE


def _build_easyocr_engine():
    """Return an easyocr callable, or None if unusable.

    Runs on GPU when Facet has one it can actually use, matching every other
    model pass; on CPU the CRAFT+CRNN pair still handles a 640px thumbnail in
    well under a second. The device question goes through utils.device rather
    than torch.cuda.is_available(): a card this build ships no kernels for
    answers True there, builds a Reader without complaint (moving weights is a
    memcpy, not a kernel), and then fails inside every readtext -- which
    extract_text swallows, so OCR would return nothing at all for the whole
    library instead of falling back to the CPU that works (issue #119).
    """
    try:
        import easyocr
        import numpy as np
    except ImportError:
        return None
    try:
        import torch

        from utils.device import is_device_available
        use_gpu = is_device_available("cuda", torch_module=torch)
    except Exception:
        use_gpu = False
    try:
        reader = easyocr.Reader(list(_LANGUAGES), gpu=use_gpu, verbose=False)
    except Exception:
        logger.warning("easyocr present but failed to initialise", exc_info=True)
        return None

    def _run(pil_image):
        results = reader.readtext(np.asarray(pil_image.convert("RGB")))
        return [(text, float(confidence)) for _box, text, confidence in results]

    logger.info("OCR engine: easyocr (languages=%s, gpu=%s)", ",".join(_LANGUAGES), use_gpu)
    return _run


def _build_pytesseract_engine():
    """Return a pytesseract callable, or None if unusable.

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
        data = pytesseract.image_to_data(
            pil_image, output_type=pytesseract.Output.DICT)
        words = []
        for text, raw_conf in zip(data.get("text", []), data.get("conf", [])):
            try:
                confidence = float(raw_conf)
            except (TypeError, ValueError):
                continue
            # tesseract reports -1 on layout blocks that carry no word.
            if confidence < 0:
                continue
            words.append((text, confidence / 100.0))
        return words

    logger.info("OCR engine: pytesseract (tesseract binary found)")
    return _run


def _resolve_engine():
    """Resolve (and cache) the OCR engine callable, or False if none usable."""
    global _ENGINE, _NO_ENGINE_WARNED
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        for builder in (_build_easyocr_engine, _build_pytesseract_engine):
            engine = builder()
            if engine is not None:
                _ENGINE = engine
                return _ENGINE
        if not _NO_ENGINE_WARNED:
            logger.warning(
                "No OCR engine available — install easyocr (pip install easyocr), "
                "or the tesseract binary plus pytesseract. --detect-text is a no-op."
            )
            _NO_ENGINE_WARNED = True
        _ENGINE = False
        return _ENGINE


def is_ocr_available():
    """True if an OCR engine could be resolved (without crashing if not)."""
    return bool(_resolve_engine())


def extract_text(pil_image):
    """Run OCR on a PIL image, returning normalized text, ``''``, or None.

    Never raises. See the module docstring for the None / ``''`` contract: None
    means "could not evaluate", ``''`` means "evaluated, no text found".
    """
    if pil_image is None:
        return None
    engine = _resolve_engine()
    if not engine:
        return None
    try:
        detections = engine(pil_image)
    except Exception:
        logger.warning("OCR extraction failed", exc_info=True)
        return None

    with _ENGINE_LOCK:
        min_confidence = _MIN_CONFIDENCE

    kept = [str(text) for text, confidence in detections
            if confidence >= min_confidence and str(text).strip()]
    return " ".join(" ".join(kept).split())


def reset_engine_cache():
    """Clear the resolved-engine cache (test helper)."""
    global _ENGINE, _NO_ENGINE_WARNED
    with _ENGINE_LOCK:
        _ENGINE = None
        _NO_ENGINE_WARNED = False
