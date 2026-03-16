"""
MarianMT-based caption translator for OPUS-MT models.

Translates English captions to a target language using Helsinki-NLP/OPUS-MT
models (~300MB each, CPU-only). Supports fr, de, es, it.
"""

import logging

logger = logging.getLogger("facet.caption_translator")

LANG_MODELS = {
    'fr': 'Helsinki-NLP/opus-mt-en-fr',
    'de': 'Helsinki-NLP/opus-mt-en-de',
    'es': 'Helsinki-NLP/opus-mt-en-es',
    'it': 'Helsinki-NLP/opus-mt-en-it',
}


class CaptionTranslator:
    """Translates English captions using MarianMT (OPUS-MT) on CPU."""

    def __init__(self, target_lang: str):
        if target_lang not in LANG_MODELS:
            raise ValueError(
                f"Unsupported target language: {target_lang!r}. "
                f"Supported: {', '.join(sorted(LANG_MODELS))}"
            )
        self.target_lang = target_lang
        self._model_name = LANG_MODELS[target_lang]
        self._model = None
        self._tokenizer = None

    def load(self) -> None:
        """Load the MarianMT model and tokenizer (lazy, CPU-only)."""
        if self._model is not None:
            return

        from transformers import MarianMTModel, MarianTokenizer

        logger.info("Loading translation model %s ...", self._model_name)
        self._tokenizer = MarianTokenizer.from_pretrained(self._model_name)
        self._model = MarianMTModel.from_pretrained(self._model_name)
        self._model.eval()
        logger.info("Translation model loaded (%s).", self.target_lang)

    def translate(self, text: str) -> str:
        """Translate a single English sentence to the target language."""
        self.load()
        inputs = self._tokenizer(text, return_tensors="pt", truncation=True)
        translated = self._model.generate(**inputs)
        return self._tokenizer.decode(translated[0], skip_special_tokens=True)

    def unload(self) -> None:
        """Free model memory."""
        self._model = None
        self._tokenizer = None
        logger.info("Translation model unloaded.")
