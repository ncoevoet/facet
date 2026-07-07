"""Pluggable VLM backend for caption/tag generation.

Abstracts the single image-to-text primitive shared by captioning, VLM tagging,
the VLM critique and the narrative-moment tie-breaker behind three interchangeable
backends selected in ``scoring_config.json`` under ``vlm_backend.type``:

  - ``local``             : in-process transformers Qwen path (default, unchanged)
  - ``ollama``            : Ollama native REST API (``/api/generate``)
  - ``openai_compatible`` : any OpenAI chat-completions endpoint (``/chat/completions``,
                            e.g. LM Studio, vLLM, OpenRouter)

Remote backends send the image as base64 (Ollama ``images``, OpenAI ``image_url``
data URI) and surface transport/HTTP failures as :class:`VLMBackendError` so callers
record a per-photo failure instead of crashing the run. The ``local`` selection
returns ``None`` here — callers keep their existing transformers ``VLMTagger`` path
byte for byte.

Remote backends make VLM captioning/tagging available on the legacy/8gb VRAM
profiles that ship no local VLM: resolution goes through the backend first, so a
configured remote server bypasses the profile gate entirely.

Expected ``scoring_config.json`` section::

    "vlm_backend": {
        "type": "local",
        "ollama": {
            "base_url": "http://localhost:11434",
            "model": "qwen2.5vl:7b",
            "timeout_seconds": 120
        },
        "openai_compatible": {
            "base_url": "http://localhost:1234/v1",
            "api_key": "",
            "model": "qwen2.5-vl-7b",
            "timeout_seconds": 120
        }
    }
"""

from __future__ import annotations

import base64
import json
import logging
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Optional
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

import PIL.Image

logger = logging.getLogger("facet.vlm_backend")

BACKEND_LOCAL = "local"
BACKEND_OLLAMA = "ollama"
BACKEND_OPENAI_COMPATIBLE = "openai_compatible"
REMOTE_BACKEND_TYPES = (BACKEND_OLLAMA, BACKEND_OPENAI_COMPATIBLE)

_CONFIG_SECTION = "vlm_backend"
_TYPE_KEY = "type"
_BASE_URL_KEY = "base_url"
_MODEL_KEY = "model"
_API_KEY_KEY = "api_key"
_TIMEOUT_KEY = "timeout_seconds"

_DEFAULT_TIMEOUT_SECONDS = 120
_IMAGE_FORMAT = "JPEG"
_JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

_OLLAMA_DEFAULT_URL = "http://localhost:11434"
_OLLAMA_GENERATE_PATH = "/api/generate"
_OPENAI_DEFAULT_URL = "http://localhost:1234/v1"
_OPENAI_CHAT_PATH = "/chat/completions"


class VLMBackendError(RuntimeError):
    """Raised when a remote VLM backend request fails or is misconfigured."""


def _validate_url(url: str, section: str) -> str:
    if not url:
        raise VLMBackendError(f"vlm_backend.{section}.base_url is not configured")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise VLMBackendError(
            f"Unsupported vlm_backend.{section}.base_url scheme: {parsed.scheme!r} (use http or https)"
        )
    if not parsed.hostname:
        raise VLMBackendError(f"vlm_backend.{section}.base_url has no hostname")
    return url.rstrip("/")


def _encode_jpeg_base64(image: PIL.Image.Image) -> str:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format=_IMAGE_FORMAT)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _post_json(url: str, payload: dict, timeout: int, headers: Optional[dict] = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request_headers = dict(_JSON_HEADERS)
    if headers:
        request_headers.update(headers)
    request = urllib_request.Request(url, data=data, headers=request_headers, method="POST")
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except (urllib_error.URLError, TimeoutError) as ex:
        raise VLMBackendError(f"VLM backend request to {url} failed: {ex}") from ex
    return json.loads(body) if body else {}


class VLMBackend(ABC):
    """Turns an ``(image, prompt, max_new_tokens)`` triple into generated text."""

    @abstractmethod
    def generate(self, image: PIL.Image.Image, prompt: str, max_new_tokens: int) -> str:
        raise NotImplementedError


class OllamaBackend(VLMBackend):
    """Ollama native REST client (``POST /api/generate`` with base64 images)."""

    def __init__(self, base_url: str, model: str, timeout: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = _validate_url(base_url, BACKEND_OLLAMA)
        if not model:
            raise VLMBackendError("vlm_backend.ollama.model is not configured")
        self.model = model
        self.timeout = timeout

    def generate(self, image: PIL.Image.Image, prompt: str, max_new_tokens: int) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [_encode_jpeg_base64(image)],
            "stream": False,
            "options": {"num_predict": int(max_new_tokens), "temperature": 0},
        }
        data = _post_json(f"{self.base_url}{_OLLAMA_GENERATE_PATH}", payload, self.timeout)
        return (data.get("response") or "").strip()


class OpenAICompatibleBackend(VLMBackend):
    """OpenAI chat-completions client (``POST /chat/completions`` with data-URI images)."""

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self.base_url = _validate_url(base_url, BACKEND_OPENAI_COMPATIBLE)
        if not model:
            raise VLMBackendError("vlm_backend.openai_compatible.model is not configured")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, image: PIL.Image.Image, prompt: str, max_new_tokens: int) -> str:
        data_uri = f"data:image/jpeg;base64,{_encode_jpeg_base64(image)}"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
            "max_tokens": int(max_new_tokens),
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        data = _post_json(f"{self.base_url}{_OPENAI_CHAT_PATH}", payload, self.timeout, headers)
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return (message.get("content") or "").strip()


def vlm_backend_type(full_config: Optional[dict]) -> str:
    """Return the configured ``vlm_backend.type`` (``local`` when unset)."""
    section = (full_config or {}).get(_CONFIG_SECTION) or {}
    return section.get(_TYPE_KEY, BACKEND_LOCAL)


def create_vlm_backend(full_config: Optional[dict]) -> Optional[VLMBackend]:
    """Build the configured remote :class:`VLMBackend`, or ``None`` for ``local``.

    ``None`` means "use the in-process transformers path"; every caller keeps its
    existing local behavior unchanged. A returned backend is profile-independent.
    """
    section = (full_config or {}).get(_CONFIG_SECTION) or {}
    backend_type = section.get(_TYPE_KEY, BACKEND_LOCAL)

    if backend_type == BACKEND_LOCAL:
        return None
    if backend_type == BACKEND_OLLAMA:
        cfg = section.get(BACKEND_OLLAMA) or {}
        return OllamaBackend(
            cfg.get(_BASE_URL_KEY, _OLLAMA_DEFAULT_URL),
            cfg.get(_MODEL_KEY, ""),
            int(cfg.get(_TIMEOUT_KEY, _DEFAULT_TIMEOUT_SECONDS)),
        )
    if backend_type == BACKEND_OPENAI_COMPATIBLE:
        cfg = section.get(BACKEND_OPENAI_COMPATIBLE) or {}
        return OpenAICompatibleBackend(
            cfg.get(_BASE_URL_KEY, _OPENAI_DEFAULT_URL),
            cfg.get(_API_KEY_KEY, ""),
            cfg.get(_MODEL_KEY, ""),
            int(cfg.get(_TIMEOUT_KEY, _DEFAULT_TIMEOUT_SECONDS)),
        )
    raise VLMBackendError(
        f"Unknown vlm_backend.type: {backend_type!r} "
        f"(use {BACKEND_LOCAL}, {BACKEND_OLLAMA} or {BACKEND_OPENAI_COMPATIBLE})"
    )


def create_remote_vlm_tagger(full_config: Optional[dict], scoring_config=None):
    """Return a remote-backed ``VLMTagger``, or ``None`` when the backend is ``local``.

    Gives the CLI VLM entry points (captioning, ``--recompute-tags-vlm``, the moment
    tie-break) one un-gated resolution: a remote backend needs neither a local model
    nor a VRAM profile, so the tagger is built with an empty model config and the
    backend attached.
    """
    try:
        backend = create_vlm_backend(full_config)
    except VLMBackendError as ex:
        logger.warning("Remote VLM backend misconfigured, falling back to local: %s", ex)
        return None
    if backend is None:
        return None
    from models.vlm_tagger import VLMTagger

    return VLMTagger({}, scoring_config, backend=backend)
