"""
Internationalization (i18n) module for Facet viewer.

Single source of truth for the supported-language list. Translation JSON
files are served to the Angular client by ``api/routers/i18n.py``.
"""

# Supported languages — single source of truth (code -> native name).
# Add a language here and drop its translations/<code>.json bundle; the API
# endpoint and the Angular switcher both derive their list from this.
LANGUAGES = [
    {'code': 'en', 'name': 'English'},
    {'code': 'fr', 'name': 'Français'},
    {'code': 'de', 'name': 'Deutsch'},
    {'code': 'it', 'name': 'Italiano'},
    {'code': 'es', 'name': 'Español'},
    {'code': 'pt', 'name': 'Português'},
]
DEFAULT_LANGUAGE = 'en'
SUPPORTED_LANGUAGES = [lang['code'] for lang in LANGUAGES]
