"""
Lazy-loaded model cache for the API server.

Keeps heavy GPU models (VLM tagger) loaded across requests to avoid
repeated load/unload cycles. Models are loaded on first use.
"""

import logging
import threading

logger = logging.getLogger("facet.api.model_cache")

_vlm_tagger = None
_vlm_lock = threading.Lock()

_caption_translator = None
_translator_lock = threading.Lock()


def get_or_load_vlm_tagger(vlm_config, full_config):
    """Get or lazily load the VLM tagger singleton.

    Args:
        vlm_config: The ``models.vlm_tagger`` section of scoring_config.
        full_config: The full scoring_config dict (unused, kept for call-site compat).

    Returns:
        A loaded VLMTagger instance ready for ``.generate()`` calls.
    """
    global _vlm_tagger
    if _vlm_tagger is not None:
        return _vlm_tagger

    with _vlm_lock:
        if _vlm_tagger is not None:
            return _vlm_tagger

        from models.vlm_tagger import VLMTagger

        tagger = VLMTagger(vlm_config)
        tagger.load()
        _vlm_tagger = tagger
        logger.info("VLM tagger loaded and cached for API use")
        return _vlm_tagger


def get_or_load_caption_translator(target_lang):
    """Get or lazily load the CaptionTranslator singleton.

    If the requested language differs from the cached translator's language,
    the old translator is unloaded and a new one is created.

    Args:
        target_lang: Target language code (fr, de, es, it).

    Returns:
        A loaded CaptionTranslator instance.
    """
    global _caption_translator
    if _caption_translator is not None and _caption_translator.target_lang == target_lang:
        return _caption_translator

    with _translator_lock:
        if _caption_translator is not None and _caption_translator.target_lang == target_lang:
            return _caption_translator

        if _caption_translator is not None:
            _caption_translator.unload()

        from models.caption_translator import CaptionTranslator

        translator = CaptionTranslator(target_lang)
        translator.load()
        _caption_translator = translator
        logger.info("Caption translator loaded for %s", target_lang)
        return _caption_translator
