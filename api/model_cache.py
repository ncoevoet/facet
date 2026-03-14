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
