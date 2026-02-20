"""
i18n router — serve translation JSON files.

Replaces Flask-integrated i18n — Angular loads translations client-side.
"""

import json
import os
from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["i18n"])

_TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'i18n', 'translations')
SUPPORTED_LANGUAGES = ['en', 'fr', 'de', 'it', 'es']

_translations_cache: dict[str, dict] = {}


def _load_translations(lang: str) -> dict:
    """Load translation file for the specified language (cached in memory)."""
    if lang not in SUPPORTED_LANGUAGES:
        return {}
    if lang in _translations_cache:
        return _translations_cache[lang]
    filepath = os.path.join(_TRANSLATIONS_DIR, f'{lang}.json')
    real_filepath = os.path.realpath(filepath)
    real_dir = os.path.realpath(_TRANSLATIONS_DIR)
    if not real_filepath.startswith(real_dir + os.sep):
        return {}
    try:
        with open(real_filepath, 'r', encoding='utf-8') as f:
            translations = json.load(f)
            _translations_cache[lang] = translations
            return translations
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@router.get("/api/i18n/languages")
async def get_languages():
    """List supported languages."""
    return {'languages': SUPPORTED_LANGUAGES, 'default': 'en'}


@router.get("/api/i18n/{lang}")
async def get_translations(lang: str):
    """Serve translation JSON for the specified language."""
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not supported")

    translations = _load_translations(lang)
    return translations
