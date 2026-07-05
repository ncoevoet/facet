"""Tests for the pluggable VLM backend (local | ollama | openai_compatible).

Covers backend selection, request shaping for the two remote backends (mocked
HTTP transport — no real network), error surfacing, the remote-backed VLMTagger
delegation, and the resolve_vlm_config un-gate on low-VRAM profiles.
"""

import base64
import json
from io import BytesIO
from unittest import mock

import pytest

import PIL.Image

from models import vlm_backend as vb


def _image():
    return PIL.Image.new("RGB", (4, 4), color=(10, 20, 30))


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _capture_urlopen(recorder, response_payload):
    def _fake(request, timeout=None):
        recorder["request"] = request
        recorder["timeout"] = timeout
        return _FakeResponse(response_payload)

    return _fake


# --- Backend selection -----------------------------------------------------

class TestBackendSelection:
    def test_default_is_local(self):
        assert vb.vlm_backend_type({}) == vb.BACKEND_LOCAL
        assert vb.vlm_backend_type(None) == vb.BACKEND_LOCAL

    def test_local_returns_none(self):
        assert vb.create_vlm_backend({}) is None
        assert vb.create_vlm_backend({"vlm_backend": {"type": "local"}}) is None

    def test_ollama_selection(self):
        backend = vb.create_vlm_backend({
            "vlm_backend": {"type": "ollama",
                            "ollama": {"base_url": "http://host:11434", "model": "qwen2.5vl"}}
        })
        assert isinstance(backend, vb.OllamaBackend)
        assert backend.base_url == "http://host:11434"
        assert backend.model == "qwen2.5vl"

    def test_openai_selection(self):
        backend = vb.create_vlm_backend({
            "vlm_backend": {"type": "openai_compatible",
                            "openai_compatible": {"base_url": "http://host:1234/v1",
                                                  "api_key": "sk-x", "model": "m"}}
        })
        assert isinstance(backend, vb.OpenAICompatibleBackend)
        assert backend.base_url == "http://host:1234/v1"
        assert backend.api_key == "sk-x"
        assert backend.model == "m"

    def test_unknown_type_raises(self):
        with pytest.raises(vb.VLMBackendError):
            vb.create_vlm_backend({"vlm_backend": {"type": "nope"}})

    def test_missing_model_raises(self):
        with pytest.raises(vb.VLMBackendError):
            vb.create_vlm_backend({"vlm_backend": {"type": "ollama",
                                                   "ollama": {"base_url": "http://h:1"}}})

    def test_bad_url_scheme_raises(self):
        with pytest.raises(vb.VLMBackendError):
            vb.create_vlm_backend({"vlm_backend": {"type": "ollama",
                                                   "ollama": {"base_url": "ftp://h", "model": "m"}}})


# --- Ollama request shaping ------------------------------------------------

class TestOllamaRequest:
    def test_generate_shapes_request(self):
        backend = vb.OllamaBackend("http://host:11434/", "qwen2.5vl", timeout=90)
        recorder = {}
        with mock.patch.object(vb.urllib_request, "urlopen",
                               _capture_urlopen(recorder, {"response": "  a red cat  "})):
            out = backend.generate(_image(), "Describe this.", max_new_tokens=42)

        assert out == "a red cat"
        request = recorder["request"]
        assert request.full_url == "http://host:11434/api/generate"
        assert recorder["timeout"] == 90
        body = json.loads(request.data)
        assert body["model"] == "qwen2.5vl"
        assert body["prompt"] == "Describe this."
        assert body["stream"] is False
        assert body["options"]["num_predict"] == 42
        assert len(body["images"]) == 1
        # the image is valid base64 of a JPEG
        assert base64.b64decode(body["images"][0])[:2] == b"\xff\xd8"


# --- OpenAI-compatible request shaping -------------------------------------

class TestOpenAIRequest:
    def test_generate_shapes_request_with_auth(self):
        backend = vb.OpenAICompatibleBackend("http://host:1234/v1", "sk-secret", "vlm-model", timeout=77)
        recorder = {}
        payload = {"choices": [{"message": {"content": " a dog "}}]}
        with mock.patch.object(vb.urllib_request, "urlopen",
                               _capture_urlopen(recorder, payload)):
            out = backend.generate(_image(), "Caption it.", max_new_tokens=64)

        assert out == "a dog"
        request = recorder["request"]
        assert request.full_url == "http://host:1234/v1/chat/completions"
        # urllib capitalizes header keys
        assert request.headers["Authorization"] == "Bearer sk-secret"
        body = json.loads(request.data)
        assert body["model"] == "vlm-model"
        assert body["max_tokens"] == 64
        content = body["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": "Caption it."}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_no_api_key_omits_auth_header(self):
        backend = vb.OpenAICompatibleBackend("http://host/v1", "", "m")
        recorder = {}
        with mock.patch.object(vb.urllib_request, "urlopen",
                               _capture_urlopen(recorder, {"choices": []})):
            out = backend.generate(_image(), "p", 8)
        assert out == ""
        assert "Authorization" not in recorder["request"].headers


# --- Error surfacing -------------------------------------------------------

class TestErrorSurfacing:
    def test_transport_error_becomes_backend_error(self):
        from urllib import error as urllib_error

        backend = vb.OllamaBackend("http://host:11434", "m")

        def _boom(request, timeout=None):
            raise urllib_error.URLError("connection refused")

        with mock.patch.object(vb.urllib_request, "urlopen", _boom):
            with pytest.raises(vb.VLMBackendError):
                backend.generate(_image(), "p", 10)


# --- Remote-backed VLMTagger delegation ------------------------------------

class _StubBackend(vb.VLMBackend):
    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error
        self.calls = []

    def generate(self, image, prompt, max_new_tokens):
        self.calls.append((prompt, max_new_tokens))
        if self.error is not None:
            raise self.error
        return self.text


class TestRemoteTagger:
    def test_create_remote_tagger_local_is_none(self):
        assert vb.create_remote_vlm_tagger({}, None) is None

    def test_create_remote_tagger_builds_backed_tagger(self):
        tagger = vb.create_remote_vlm_tagger(
            {"vlm_backend": {"type": "ollama",
                             "ollama": {"base_url": "http://h:1", "model": "m"}}}, None)
        assert tagger is not None
        assert tagger.backend is not None
        tagger.load()
        assert tagger.model is None

    def test_generate_delegates_to_backend(self):
        from models.vlm_tagger import VLMTagger

        stub = _StubBackend(text="a sunset over the sea")
        tagger = VLMTagger({}, None, backend=stub)
        assert tagger.generate(_image(), "Describe.", max_new_tokens=100) == "a sunset over the sea"
        assert stub.calls == [("Describe.", 100)]

    def test_tag_batch_parses_backend_text(self):
        from models.vlm_tagger import VLMTagger

        stub = _StubBackend(text="cat, dog")
        tagger = VLMTagger({}, None, backend=stub)
        assert tagger.tag_batch([_image()], max_tags=5) == [["cat", "dog"]]

    def test_tag_batch_isolates_per_image_failure(self):
        from models.vlm_tagger import VLMTagger

        stub = _StubBackend(error=vb.VLMBackendError("down"))
        tagger = VLMTagger({}, None, backend=stub)
        assert tagger.tag_batch([_image(), _image()], max_tags=5) == [[], []]


# --- resolve_vlm_config un-gates remote on low-VRAM profiles ---------------

_LEGACY_LOCAL = {"models": {"vram_profile": "legacy",
                            "profiles": {"legacy": {"tagging_model": "clip"}}}}
_LEGACY_REMOTE = {
    "models": {"vram_profile": "legacy", "profiles": {"legacy": {"tagging_model": "clip"}}},
    "vlm_backend": {"type": "ollama", "ollama": {"base_url": "http://h:1", "model": "m"}},
}


class TestResolveVlmConfigUngate:
    def test_local_legacy_returns_none(self):
        from api.model_cache import resolve_vlm_config

        with mock.patch("api.config._FULL_CONFIG", _LEGACY_LOCAL), \
                mock.patch("api.model_cache._resolved_profile", None):
            assert resolve_vlm_config() is None

    def test_remote_legacy_is_truthy(self):
        from api.model_cache import resolve_vlm_config

        with mock.patch("api.config._FULL_CONFIG", _LEGACY_REMOTE), \
                mock.patch("api.model_cache._resolved_profile", None):
            assert resolve_vlm_config()
