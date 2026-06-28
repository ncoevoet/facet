"""
i18n router — serve translation JSON files.

Replaces Flask-integrated i18n — Angular loads translations client-side.
"""

import json
import os
from fastapi import APIRouter, HTTPException

from i18n import LANGUAGES, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE

router = APIRouter(tags=["i18n"])

_TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'i18n', 'translations')

_translations_cache: dict[str, tuple[float, dict]] = {}


def _load_translations(lang: str) -> dict:
    """Load translation file for the specified language.

    Cached in memory, invalidated when the file's mtime changes so updated
    translations are served without a server restart.
    """
    if lang not in SUPPORTED_LANGUAGES:
        return {}
    filepath = os.path.join(_TRANSLATIONS_DIR, f'{lang}.json')
    real_filepath = os.path.realpath(filepath)
    real_dir = os.path.realpath(_TRANSLATIONS_DIR)
    if not real_filepath.startswith(real_dir + os.sep):
        return {}
    try:
        mtime = os.path.getmtime(real_filepath)
        cached = _translations_cache.get(lang)
        if cached and cached[0] == mtime:
            return cached[1]
        with open(real_filepath, 'r', encoding='utf-8') as f:
            translations = json.load(f)
            _translations_cache[lang] = (mtime, translations)
            return translations
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@router.get("/api/i18n/languages")
def get_languages():
    """List supported languages as ``[{code, name}]`` plus the default code."""
    return {'languages': LANGUAGES, 'default': DEFAULT_LANGUAGE}


@router.get("/api/i18n/{lang}")
def get_translations(lang: str):
    """Serve translation JSON for the specified language."""
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not supported")

    translations = _load_translations(lang)
    return translations
