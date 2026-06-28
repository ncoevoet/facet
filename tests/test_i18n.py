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
