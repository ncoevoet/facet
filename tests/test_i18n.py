"""Tests for the i18n API router (api/routers/i18n.py)."""

import json
import os
import re

import pytest
from fastapi.testclient import TestClient

from api import create_app
from i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

# Reads client, i18n or docs files: runs on every pull request (see ci.yml).
pytestmark = pytest.mark.cross_file


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


class TestGetLanguages:
    """GET /api/i18n/languages — list available languages."""

    def test_languages_returns_list(self, client):
        resp = client.get("/api/i18n/languages")
        assert resp.status_code == 200
        body = resp.json()
        assert "languages" in body
        assert body.get("default") == "en"
        langs = body["languages"]
        assert isinstance(langs, list)
        assert len(langs) > 0
        # Each entry is a {code, name} object (data-driven switcher).
        for entry in langs:
            assert isinstance(entry, dict)
            assert isinstance(entry["code"], str) and len(entry["code"]) == 2
            assert isinstance(entry["name"], str) and entry["name"]
        codes = {entry["code"] for entry in langs}
        assert {"en", "pt"} <= codes  # Portuguese now supported

    def test_get_portuguese_bundle(self, client):
        resp = client.get("/api/i18n/pt")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict) and len(resp.json()) > 0


class TestGetTranslations:
    """GET /api/i18n/{lang} — return translation JSON for a language."""

    def test_get_translations_returns_json(self, client):
        resp = client.get("/api/i18n/en")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, dict)
        assert len(body) > 0

    def test_get_translations_unknown_lang_returns_404(self, client):
        resp = client.get("/api/i18n/xx")
        assert resp.status_code == 404


def _flatten(bundle: dict, prefix: str = '') -> dict:
    """Flatten a nested bundle to ``{'a.b.c': value}``.

    Comparing bundles key-by-key at the top level only would pass a bundle that
    has every section but is missing half the strings inside one of them, which
    is exactly the drift this module guards.
    """
    flat = {}
    for key, value in bundle.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


def _load_bundle(lang: str) -> dict:
    with open(os.path.join(TRANSLATIONS_DIR, f'{lang}.json'), 'r', encoding='utf-8') as handle:
        return json.load(handle)


TRANSLATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'i18n', 'translations')
PLACEHOLDER = re.compile(r'\{(\w+)\}')
TRANSLATED_LANGUAGES = [code for code in SUPPORTED_LANGUAGES if code != DEFAULT_LANGUAGE]


class TestBundleParity:
    """What ``scripts/audit_i18n.py`` cannot see.

    That script is the bundle gate — CI runs it as "Translation bundles agree
    with en.json" and it compares every bundle's dotted key paths against
    ``en.json`` in both directions, so missing and extra KEYS are already
    covered. Nothing here duplicates that.

    It compares key names and never values, which is how ``fr.json`` shipped
    ``capsules.camera_title = "{caméra}"``: a corrupted interpolation token
    lives inside a value, so a key-set audit passes it. Empty values it reports
    deliberately as informational, never gating — that policy stays its own.

    It also enumerates by globbing ``translations/*.json``, so the registry and
    the directory can disagree without it noticing, in either direction. That
    matters because ``_load_translations`` answers a missing or unparseable
    bundle with an empty dict and HTTP 200, and the Angular side renders an
    absent key as the key path itself — a language registered with no readable
    bundle looks like a working install serving `gallery.selection.count` as UI
    text.
    """

    def test_every_registered_language_has_a_usable_bundle(self):
        """A code in LANGUAGES with no readable bundle degrades silently, so fail here instead."""
        for code in SUPPORTED_LANGUAGES:
            path = os.path.join(TRANSLATIONS_DIR, f'{code}.json')
            assert os.path.isfile(path), f"'{code}' is registered in i18n.LANGUAGES but {code}.json is missing"
            bundle = _load_bundle(code)
            assert isinstance(bundle, dict) and bundle, f"{code}.json is empty or not an object"

    def test_no_unregistered_bundle_files(self):
        """A bundle nobody registered is dead weight the switcher never offers."""
        on_disk = {name[:-5] for name in os.listdir(TRANSLATIONS_DIR) if name.endswith('.json')}
        assert on_disk == set(SUPPORTED_LANGUAGES), (
            f"bundles on disk {sorted(on_disk)} do not match i18n.LANGUAGES {sorted(SUPPORTED_LANGUAGES)}"
        )

    @pytest.mark.parametrize("lang", TRANSLATED_LANGUAGES)
    def test_placeholders_match_english(self, lang):
        """A dropped ``{count}`` renders the sentence without its number, and an
        invented one renders the brace literally — both are silent at runtime."""
        english = _flatten(_load_bundle(DEFAULT_LANGUAGE))
        bundle = _flatten(_load_bundle(lang))
        mismatched = {
            key: (sorted(set(PLACEHOLDER.findall(value))), sorted(set(PLACEHOLDER.findall(bundle[key]))))
            for key, value in english.items()
            if key in bundle
            and isinstance(value, str)
            and isinstance(bundle[key], str)
            and set(PLACEHOLDER.findall(value)) != set(PLACEHOLDER.findall(bundle[key]))
        }
        assert not mismatched, f"{lang}.json placeholder mismatches (key: en, {lang}): {dict(list(mismatched.items())[:5])}"

    @pytest.mark.parametrize("lang", TRANSLATED_LANGUAGES)
    def test_card_key_hint_names_localised_keys(self, lang):
        """The card hint names the Space and Enter keys; a translated bundle that keeps
        the English cap label ('Space') shows a foreign word on the user's keyboard."""
        hint = _load_bundle(lang)['photoCard']['key_hint']
        assert 'Space' not in hint, f"{lang}.json photoCard.key_hint still names the key 'Space'"

    @pytest.mark.parametrize('lang', SUPPORTED_LANGUAGES)
    def test_default_sort_groups_have_translated_headings(self, lang):
        root = os.path.dirname(os.path.dirname(TRANSLATIONS_DIR))
        with open(os.path.join(root, 'config', 'scoring_config.default.json'), encoding='utf-8') as handle:
            groups = json.load(handle)['viewer']['sort_options']
        labels = _load_bundle(lang)['sort_groups']
        for group in groups:
            key = re.sub(r'\s+', '_', group.lower())
            assert labels.get(key), f'{lang}: missing sort_groups.{key}'

    def test_every_default_sort_column_has_an_option_icon(self):
        """The sort menus fall back to a generic 'sort' glyph for a column the pipe does
        not map, so a new configured sort would silently ship without its own icon."""
        root = os.path.dirname(os.path.dirname(TRANSLATIONS_DIR))
        pipe = os.path.join(root, 'client', 'src', 'app', 'shared', 'pipes', 'sort-option-icon.pipe.ts')
        with open(pipe, encoding='utf-8') as handle:
            mapped = set(re.findall(r"^  (\w+): (?:'|FEATURE_MARK)", handle.read(), re.MULTILINE))
        with open(os.path.join(root, 'config', 'scoring_config.default.json'), encoding='utf-8') as handle:
            groups = json.load(handle)['viewer']['sort_options']
        columns = {option['column'] for options in groups.values() for option in options}
        assert columns
        assert not columns - mapped, f'sort columns without an option icon: {sorted(columns - mapped)}'
