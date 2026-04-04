"""Tests for the i18n API router (api/routers/i18n.py)."""

import pytest
from fastapi.testclient import TestClient

from api import create_app


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
        langs = body["languages"]
        assert isinstance(langs, list)
        assert len(langs) > 0
        # Each entry should be a language code string
        for code in langs:
            assert isinstance(code, str)
            assert len(code) == 2


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
