"""
Lazy-loaded model cache for the API server.

Keeps heavy GPU models (VLM tagger) loaded across requests to avoid
repeated load/unload cycles. Models are loaded on first use. Also hosts
the shared VLM config resolution and the inference lock that serializes
concurrent generate() calls on the single cached model instance.
"""

import logging
import threading

from models.caption_translator import LANG_MODELS

logger = logging.getLogger("facet.api.model_cache")

_vlm_tagger = None
_vlm_lock = threading.Lock()

_caption_translator = None
_translator_lock = threading.Lock()

_saliency_scorer = None
_saliency_lock = threading.Lock()

_resolved_profile = None

vlm_generate_lock = threading.Lock()

SUPPORTED_TRANSLATION_LANGS = frozenset(LANG_MODELS)

_VLM_MODEL_KEY_MAP = {
    'qwen3-vl-2b': 'qwen3_vl_2b',
    'qwen2.5-vl-7b': 'qwen2_5_vl_7b',
    'qwen3.5-2b': 'qwen3_5_2b',
    'qwen3.5-4b': 'qwen3_5_4b',
}


def resolve_vram_profile():
    """Return the active VRAM profile name, resolving 'auto' via hardware detection once."""
    global _resolved_profile
    from api.config import _FULL_CONFIG

    profile = _FULL_CONFIG.get('models', {}).get('vram_profile', 'legacy')
    if profile != 'auto':
        return profile

    if _resolved_profile is None:
        from config import ScoringConfig

        _resolved_profile, _, msg = ScoringConfig.suggest_vram_profile()
        logger.info("Resolved vram_profile 'auto' for the API: %s", msg)
    return _resolved_profile


def resolve_vlm_config():
    """Resolve the active profile's VLM tagger model config dict, or None.

    Returns None when the active profile (after 'auto' resolution) does not
    use a VLM tagger or its model config lacks a model_path. A configured remote
    ``vlm_backend`` (ollama / openai_compatible) short-circuits to a truthy config
    regardless of the VRAM profile, so captioning and critique work on
    legacy/8gb — ``get_or_load_vlm_tagger`` then builds the remote-backed tagger.
    """
    from api.config import _FULL_CONFIG
    from models.vlm_backend import BACKEND_LOCAL, vlm_backend_type

    if vlm_backend_type(_FULL_CONFIG) != BACKEND_LOCAL:
        return _FULL_CONFIG.get('vlm_backend', {})

    models_config = _FULL_CONFIG.get('models', {})
    profile = models_config.get('profiles', {}).get(resolve_vram_profile(), {})
    config_key = _VLM_MODEL_KEY_MAP.get(profile.get('tagging_model', ''))
    if not config_key:
        return None

    vlm_config = models_config.get(config_key, {})
    return vlm_config if vlm_config.get('model_path') else None


def translation_target(lang):
    """Return the configured translation target when ``lang`` requests it, else None."""
    from api.config import _FULL_CONFIG

    if not lang or lang not in SUPPORTED_TRANSLATION_LANGS:
        return None
    target = _FULL_CONFIG.get('translation', {}).get('target_language', '')
    return target if lang == target else None


def translate_text(text, target_lang):
    """Translate ``text`` via the cached MarianMT translator; None on failure."""
    try:
        translator = get_or_load_caption_translator(target_lang)
        return translator.translate(text)
    except Exception:
        logger.exception("Translation failed for lang=%s", target_lang)
        return None


def get_or_load_saliency_scorer():
    """Get or lazily load the BiRefNet saliency scorer singleton for the API.

    Loaded once and reused across requests (the overlay endpoint runs it on the
    stored 640px thumbnail, so per-request cost is trivial once the model is in).
    """
    global _saliency_scorer
    if _saliency_scorer is not None:
        return _saliency_scorer

    with _saliency_lock:
        if _saliency_scorer is not None:
            return _saliency_scorer

        from models.saliency_scorer import SaliencyScorer

        scorer = SaliencyScorer()
        scorer.load()
        _saliency_scorer = scorer
        logger.info("Saliency scorer loaded and cached for API use")
        return _saliency_scorer


def get_or_load_vlm_tagger(vlm_config):
    """Get or lazily load the VLM tagger singleton.

    Args:
        vlm_config: The resolved VLM model config (see ``resolve_vlm_config``).

    Returns:
        A loaded VLMTagger instance ready for ``.generate()`` calls. Callers
        must hold ``vlm_generate_lock`` around ``.generate()`` — the cache
        lock only guards loading, not inference.
    """
    global _vlm_tagger
    if _vlm_tagger is not None:
        return _vlm_tagger

    with _vlm_lock:
        if _vlm_tagger is not None:
            return _vlm_tagger

        from api.config import _FULL_CONFIG
        from models.vlm_backend import create_vlm_backend
        from models.vlm_tagger import VLMTagger

        backend = create_vlm_backend(_FULL_CONFIG)
        if backend is not None:
            _vlm_tagger = VLMTagger({}, backend=backend)
            logger.info("Remote VLM backend attached and cached for API use")
            return _vlm_tagger

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
