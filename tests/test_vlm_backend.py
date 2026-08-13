"""Tests for the pluggable VLM backend (local | ollama | openai_compatible).

Covers backend selection, request shaping for the two remote backends (mocked
HTTP transport — no real network), error surfacing, the remote-backed VLMTagger
delegation, and the resolve_vlm_config un-gate on low-VRAM profiles.
"""

import base64
import json
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

    def test_create_remote_tagger_misconfigured_returns_none(self):
        assert vb.create_remote_vlm_tagger(
            {"vlm_backend": {"type": "ollama", "ollama": {"base_url": "http://h:1"}}}, None) is None

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


# --- Qwen2.5-VL batched generation must left-pad for correct decoding ------

class _FakeTokenizer:
    def __init__(self):
        self.pad_token_id = 0
        self.padding_side = "right"


class _FakeQwen25Processor:
    def __init__(self, captured_padding_sides, seq_len, batch_size):
        self.tokenizer = _FakeTokenizer()
        self._captured = captured_padding_sides
        self._seq_len = seq_len
        self._batch_size = batch_size

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        return "prompt text"

    def __call__(self, text, images, return_tensors, padding):
        import torch
        self._captured.append(self.tokenizer.padding_side)
        return {
            "input_ids": torch.zeros((self._batch_size, self._seq_len), dtype=torch.long),
            "attention_mask": torch.ones((self._batch_size, self._seq_len), dtype=torch.long),
        }

    def decode(self, ids, skip_special_tokens=True):
        return "cat, dog"


class _FakeQwen25Model:
    device = "cpu"

    def __init__(self, seq_len, batch_size, new_tokens):
        self._seq_len = seq_len
        self._batch_size = batch_size
        self._new_tokens = new_tokens

    def generate(self, **kwargs):
        import torch
        return torch.zeros((self._batch_size, self._seq_len + self._new_tokens), dtype=torch.long)


class TestBatchQwen25Padding:
    def test_batches_with_left_padding(self):
        pytest.importorskip("torch")
        from models.vlm_tagger import VLMTagger, _ensure_imports

        _ensure_imports()
        captured_padding_sides = []
        seq_len, batch_size, new_tokens = 8, 2, 3
        tagger = VLMTagger({"family": "qwen2_5"}, None)
        tagger.processor = _FakeQwen25Processor(captured_padding_sides, seq_len, batch_size)
        tagger.model = _FakeQwen25Model(seq_len, batch_size, new_tokens)

        results = tagger._batch_qwen2_5(
            [_image(), _image()], prompt="Tags:", max_new_tokens=new_tokens, max_tags=5)

        assert captured_padding_sides == ["left"]
        assert tagger.processor.tokenizer.padding_side == "right"
        assert results == [["cat", "dog"], ["cat", "dog"]]


# --- Qwen3/Qwen3.5 batching must left-pad every per-token key ---------------
#
# transformers >= 5.3 adds mm_token_type_ids (a per-token tensor) to the Qwen3.5
# processor output. Concatenating it raw on dim 0 across differing sequence
# lengths raises "Sizes of tensors must match except in dimension 0".

class _FakeQwen3Processor:
    """Emits per-image inputs with differing sequence lengths and patch counts."""

    def __init__(self, seq_lens, patch_counts, extra_token_keys=()):
        self.tokenizer = _FakeTokenizer()
        self._seq_lens = list(seq_lens)
        self._patch_counts = list(patch_counts)
        self._extra_token_keys = tuple(extra_token_keys)
        self._call = 0
        self.template_kwargs = []

    def apply_chat_template(self, messages, tokenize=True, add_generation_prompt=True,
                            return_dict=True, return_tensors="pt", **kwargs):
        import torch

        self.template_kwargs.append(kwargs)
        idx = self._call
        self._call += 1
        seq_len = self._seq_lens[idx]
        patches = self._patch_counts[idx]
        inputs = {
            "input_ids": torch.full((1, seq_len), idx + 1, dtype=torch.long),
            "attention_mask": torch.ones((1, seq_len), dtype=torch.long),
        }
        for key in self._extra_token_keys:
            inputs[key] = torch.full((1, seq_len), idx + 1, dtype=torch.long)
        inputs["pixel_values"] = torch.full((patches, 8), float(idx + 1))
        inputs["image_grid_thw"] = torch.tensor([[1, 2, patches]], dtype=torch.long)
        return inputs

    def decode(self, ids, skip_special_tokens=True):
        return "cat, dog"


class _FakeQwen3Model:
    device = "cpu"

    def __init__(self, new_tokens):
        self._new_tokens = new_tokens
        self.captured = None

    def generate(self, **kwargs):
        import torch

        self.captured = kwargs
        batch, seq_len = kwargs["input_ids"].shape
        return torch.zeros((batch, seq_len + self._new_tokens), dtype=torch.long)


def _run_batch_qwen3(extra_token_keys, family="qwen3_5"):
    pytest.importorskip("torch")
    from models.vlm_tagger import VLMTagger, _ensure_imports

    _ensure_imports()
    tagger = VLMTagger({"family": family}, None)
    tagger.processor = _FakeQwen3Processor(
        seq_lens=(5, 8), patch_counts=(4, 6), extra_token_keys=extra_token_keys)
    tagger.model = _FakeQwen3Model(new_tokens=3)
    results = tagger._batch_qwen3(
        [_image(), _image()], prompt="Tags:", max_new_tokens=3, max_tags=5)
    return tagger, results


class TestBatchQwen3Padding:
    def _run(self, extra_token_keys):
        return _run_batch_qwen3(extra_token_keys)

    def test_pads_mm_token_type_ids_added_by_transformers_5_3(self):
        tagger, results = self._run(("mm_token_type_ids",))
        captured = tagger.model.captured

        assert results == [["cat", "dog"], ["cat", "dog"]]
        for key in ("input_ids", "attention_mask", "mm_token_type_ids"):
            assert tuple(captured[key].shape) == (2, 8), key
        assert captured["input_ids"][0].tolist() == [0, 0, 0] + [1] * 5
        assert captured["attention_mask"][0].tolist() == [0, 0, 0] + [1] * 5
        assert captured["mm_token_type_ids"][0].tolist() == [0, 0, 0] + [1] * 5
        assert captured["input_ids"][1].tolist() == [2] * 8

    def test_vision_keys_concatenate_on_batch_dim(self):
        tagger, _ = self._run(("mm_token_type_ids",))
        captured = tagger.model.captured

        assert tuple(captured["pixel_values"].shape) == (10, 8)
        assert tuple(captured["image_grid_thw"].shape) == (2, 3)

    def test_pre_5_3_processor_output_still_batches(self):
        tagger, results = self._run(())
        captured = tagger.model.captured

        assert results == [["cat", "dog"], ["cat", "dog"]]
        assert "mm_token_type_ids" not in captured
        assert tuple(captured["input_ids"].shape) == (2, 8)
        assert tuple(captured["attention_mask"].shape) == (2, 8)
        assert tuple(captured["pixel_values"].shape) == (10, 8)


# --- Qwen3.5 must render its chat template with thinking disabled -----------
#
# The only line that differs between Qwen3.5-2B's and Qwen3.5-4B's
# chat_template.jinja is the generation-prompt branch: the 2B defaults thinking
# off ("enable_thinking is true" opt-in), the 4B defaults it on
# ("enable_thinking is false" opt-out). Left on, the 4B's prompt ends inside an
# open <think> block and it burns the whole max_new_tokens budget on reasoning
# prose instead of emitting tags. Passing the flag renders the 2B prompt
# byte-identically, so this cannot regress the validated 2B output.

class TestThinkingDisabled:
    def test_qwen3_5_disables_thinking(self):
        tagger, _ = _run_batch_qwen3((), family="qwen3_5")
        assert tagger.processor.template_kwargs == [{"enable_thinking": False}] * 2

    def test_qwen3_leaves_template_defaults_alone(self):
        tagger, _ = _run_batch_qwen3((), family="qwen3")
        assert tagger.processor.template_kwargs == [{}] * 2

    def test_qwen2_5_gets_no_template_kwargs(self):
        from models.vlm_tagger import VLMTagger

        assert VLMTagger({"family": "qwen2_5"}, None)._template_kwargs == {}


# --- Tag parsing must reject prose rather than snake-case it ----------------


class TestParseTagsRejectsProse:
    def _parse(self, text, max_tags=5):
        from models.vlm_tagger import VLMTagger

        return VLMTagger({}, None)._parse_tags(text, max_tags)

    def test_clean_comma_list_is_unchanged(self):
        # The validated Qwen3.5-2B output shape must survive the hardening.
        assert self._parse("night,city lights,bridge,architecture,urban") == [
            "night", "city_lights", "bridge", "architecture", "urban"]

    def test_markdown_prose_yields_no_tags(self):
        # The exact Qwen3.5-4B failure: a bulleted description previously became
        # tags like "-_the_image_shows_a_tall".
        text = ("**\n- The image shows a tall, illuminated structure at night. "
                "It looks like a ride or a tower.")
        assert self._parse(text) == []

    def test_reasoning_preamble_is_dropped(self):
        # <think>/</think> are ordinary tokens in the Qwen3.5 vocabulary, so they
        # survive skip_special_tokens=True decoding.
        text = ("Okay, the user wants tags. I can see a bridge lit up at night.\n"
                "</think>\n\nnight, bridge, urban")
        assert self._parse(text) == ["night", "bridge", "urban"]

    def test_long_candidates_dropped_short_ones_kept(self):
        assert self._parse("night, a wide sweeping view of the valley, bridge") == [
            "night", "bridge"]

    def test_trailing_sentence_punctuation_stripped(self):
        assert self._parse("night, urban.") == ["night", "urban"]

    def test_existing_prefix_and_bullet_cleanups_still_apply(self):
        assert self._parse("Tags: 1. sunset, 2. beach") == ["sunset", "beach"]
        assert self._parse("Art: painting, Mood: moody") == ["painting", "moody"]
