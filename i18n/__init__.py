"""
Internationalization (i18n) module for Facet viewer.

Provides lightweight JSON-based translation support with:
- Browser language auto-detection (Accept-Language header)
- Cookie-based persistence for user preference
- URL parameter override (?lang=xx)
- Flask integration via context processor (optional)
- Standalone use from FastAPI or CLI (no Flask required)
"""

import json
import os
from functools import lru_cache

try:
    from flask import request, g
except ImportError:
    request = None
    g = None

# Supported languages
SUPPORTED_LANGUAGES = ['en', 'fr', 'de', 'it', 'es']
DEFAULT_LANGUAGE = 'en'

# Module directory
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_TRANSLATIONS_DIR = os.path.join(_MODULE_DIR, 'translations')

# Cached translations (loaded once per language)
_translations_cache = {}


def get_locale():
    """Detect the user's preferred language (Flask context only).

    Priority order:
    1. URL parameter (?lang=xx)
    2. Cookie (facet_lang)
    3. Browser Accept-Language header
    4. Default language (en)

    Returns:
        str: Language code (e.g. 'en', 'fr', 'de', 'it', 'es')
    """
    if request is None:
        return DEFAULT_LANGUAGE

    # 1. Check URL parameter
    lang = request.args.get('lang')
    if lang and lang in SUPPORTED_LANGUAGES:
        return lang

    # 2. Check cookie
    lang = request.cookies.get('facet_lang')
    if lang and lang in SUPPORTED_LANGUAGES:
        return lang

    # 3. Parse Accept-Language header
    accept_lang = request.headers.get('Accept-Language', '')
    for part in accept_lang.split(','):
        # Parse language tag (e.g., "fr-FR;q=0.9" -> "fr")
        lang_tag = part.split(';')[0].strip()
        lang_code = lang_tag.split('-')[0].lower()
        if lang_code in SUPPORTED_LANGUAGES:
            return lang_code

    # 4. Default
    return DEFAULT_LANGUAGE


def load_translations(lang):
    """Load translation file for the specified language.

    Args:
        lang: Language code ('en' or 'fr')

    Returns:
        dict: Translation dictionary, or empty dict if file not found
    """
    if lang not in SUPPORTED_LANGUAGES:
        return {}
    if lang in _translations_cache:
        return _translations_cache[lang]

    filepath = os.path.join(_TRANSLATIONS_DIR, f'{lang}.json')
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            translations = json.load(f)
            _translations_cache[lang] = translations
            return translations
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load translations for '{lang}': {e}")
        _translations_cache[lang] = {}
        return {}


def get_nested_value(d, key_path):
    """Get a value from a nested dictionary using dot notation.

    Args:
        d: Dictionary to search
        key_path: Dot-separated key path (e.g., 'ui.filters.type')

    Returns:
        Value at the key path, or None if not found
    """
    keys = key_path.split('.')
    value = d
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value


def _(key, **kwargs):
    """Get a translated string by key.

    Args:
        key: Translation key using dot notation (e.g., 'ui.filters.type')
        **kwargs: Variables for interpolation (e.g., name='John')

    Returns:
        str: Translated string with variables interpolated, or the key if not found
    """
    lang = getattr(g, 'lang', DEFAULT_LANGUAGE)
    translations = load_translations(lang)

    value = get_nested_value(translations, key)

    if value is None:
        # Fallback to English if current language doesn't have the key
        if lang != DEFAULT_LANGUAGE:
            en_translations = load_translations(DEFAULT_LANGUAGE)
            value = get_nested_value(en_translations, key)

        # If still not found, return the key itself
        if value is None:
            return key

    # Handle interpolation (e.g., "Hello, {name}!")
    if kwargs and isinstance(value, str):
        try:
            return value.format(**kwargs)
        except KeyError:
            return value

    return value


def get_translations_for_js(keys=None):
    """Get a subset of translations for use in JavaScript.

    Args:
        keys: List of top-level keys to include, or None for all
              (e.g., ['notifications', 'dialogs'])

    Returns:
        dict: Translation dictionary for JS
    """
    lang = getattr(g, 'lang', DEFAULT_LANGUAGE)
    translations = load_translations(lang)

    if keys is None:
        return translations

    # Return only specified keys
    return {k: translations.get(k, {}) for k in keys if k in translations}


def init_i18n(app):
    """Initialize i18n support for a Flask application.

    This sets up:
    - before_request hook to detect language
    - context processor to make _ and lang available in templates
    - Response hook to set language cookie

    Args:
        app: Flask application instance
    """

    @app.before_request
    def before_request_i18n():
        """Detect and store the user's language preference."""
        g.lang = get_locale()

    @app.after_request
    def after_request_i18n(response):
        """Set language cookie if changed via URL parameter."""
        lang_param = request.args.get('lang')
        if lang_param and lang_param in SUPPORTED_LANGUAGES:
            # Set cookie for 1 year
            response.set_cookie('facet_lang', lang_param,
                              max_age=365*24*60*60,
                              samesite='Lax')
        return response

    @app.context_processor
    def i18n_context():
        """Make i18n functions available in templates."""
        return {
            '_': _,
            'lang': getattr(g, 'lang', DEFAULT_LANGUAGE),
            'js_translations': lambda keys=None: get_translations_for_js(keys),
            'supported_languages': SUPPORTED_LANGUAGES,
        }


# Convenience function for direct imports
def translate(key, **kwargs):
    """Alias for _ function for clearer imports."""
    return _(key, **kwargs)
