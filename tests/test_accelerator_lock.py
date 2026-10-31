"""``api.model_cache.accelerator_lock``: one lock for every model the viewer
runs on MPS.

PyTorch's MPS backend is not thread-safe, and every model shares the one
device, so a search encoding while a saliency overlay renders aborts the
viewer inside Metal exactly as two searches do. CUDA and CPU stay unserialized.
"""

import contextlib
import io
import sys
import threading
import time
from unittest import mock

import numpy as np
import pytest
from PIL import Image

from api.model_cache import AcceleratorBusy, _mps_lock, accelerator_lock, vlm_accelerator_lock


def test_mps_devices_share_one_lock():
    assert accelerator_lock("mps") is _mps_lock
    assert accelerator_lock("mps:0") is _mps_lock


def test_cuda_cpu_and_no_device_are_not_serialized():
    for device in ("cuda", "cuda:0", "cpu", None):
        assert accelerator_lock(device) is not _mps_lock


@contextlib.contextmanager
def _mps_lock_held_elsewhere():
    """Hold the MPS lock from another thread, as a running caption would.

    Self-releasing after 5 s, so a regression that waits forever fails an
    assertion instead of hanging the suite.
    """
    held, release = threading.Event(), threading.Event()

    def _hold():
        with _mps_lock:
            held.set()
            release.wait(5)

    holder = threading.Thread(target=_hold, daemon=True)
    holder.start()
    assert held.wait(2)
    try:
        yield
    finally:
        release.set()
        holder.join(2)


def _finishes_within(seconds, job):
    """True when ``job`` returns on its own thread within ``seconds``."""
    done = threading.Event()

    def _run():
        job()
        done.set()

    threading.Thread(target=_run, daemon=True).start()
    return done.wait(seconds)


def test_off_mps_never_waits_on_the_lock_even_with_a_timeout():
    def _enter(device, timeout):
        with accelerator_lock(device, timeout):
            pass

    with _mps_lock_held_elsewhere():
        for device in ("cuda", "cuda:0", "cpu", None):
            assert _finishes_within(2, lambda: _enter(device, None)), device
            assert _finishes_within(2, lambda: _enter(device, 0.01)), device


def test_without_a_timeout_mps_still_blocks_until_the_lock_is_free():
    entered = threading.Event()

    def _enter():
        with accelerator_lock("mps"):
            entered.set()

    with _mps_lock_held_elsewhere():
        threading.Thread(target=_enter, daemon=True).start()
        assert not entered.wait(0.2)
    assert entered.wait(2)


def test_a_timeout_on_mps_raises_busy_and_leaves_the_holder_in_place():
    assert issubclass(AcceleratorBusy, TimeoutError)
    with _mps_lock_held_elsewhere():
        started = time.monotonic()
        with pytest.raises(AcceleratorBusy):
            with accelerator_lock("mps", 0.05):
                pytest.fail("entered while another thread held the MPS lock")
        assert time.monotonic() - started >= 0.04
        assert _mps_lock.locked()
    assert not _mps_lock.locked()


def test_a_timeout_on_a_free_mps_lock_takes_and_releases_it():
    with accelerator_lock("mps", 1):
        assert _mps_lock.locked()
    assert not _mps_lock.locked()


def test_a_remote_vlm_backend_takes_no_lock_even_on_a_mac():
    local = mock.Mock(backend=None, device="mps")
    remote = mock.Mock(backend=object(), device="mps")
    assert vlm_accelerator_lock(local) is _mps_lock
    assert vlm_accelerator_lock(remote) is not _mps_lock


def test_a_search_and_a_saliency_overlay_never_run_on_mps_at_once():
    from api.routers import saliency, search

    state = {"inside": 0, "peak": 0}
    guard = threading.Lock()

    def _occupy():
        with guard:
            state["inside"] += 1
            state["peak"] = max(state["peak"], state["inside"])
        time.sleep(0.02)
        with guard:
            state["inside"] -= 1

    class _Features:
        def cpu(self):
            return self

        def numpy(self):
            return np.ones((1, 4))

    def _fake_encode(*_a, **_k):
        _occupy()
        return _Features()

    class _FakeScorer:
        device = "mps"

        def get_saliency_soft(self, _pil):
            _occupy()
            return np.zeros((8, 8), dtype=np.float32)

    def _thumbnail(shade):
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (shade, shade, shade)).save(buf, format="JPEG")
        return buf.getvalue()

    start = threading.Barrier(4)
    errors = []

    def _run(job):
        start.wait()
        try:
            job()
        except Exception as exc:  # surfaced below; a thread swallows it otherwise
            errors.append(exc)

    jobs = [
        lambda: search._encode_texts(["person"]),
        lambda: search._encode_texts(["beach"]),
        lambda: saliency._render_overlay(_thumbnail(10)),
        lambda: saliency._render_overlay(_thumbnail(200)),
    ]
    encoder = {"backend": "open_clip", "model": object(), "model_name": "ViT-L-14", "device": "mps"}
    saliency._render_overlay.cache_clear()
    try:
        with mock.patch.object(search, "_text_encoder", encoder), \
             mock.patch("models.tagger.encode_text_prompts", side_effect=_fake_encode), \
             mock.patch("api.model_cache.get_or_load_saliency_scorer", return_value=_FakeScorer()):
            threads = [threading.Thread(target=_run, args=(job,)) for job in jobs]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
    finally:
        saliency._render_overlay.cache_clear()

    assert errors == []
    assert state["peak"] == 1


def _encoder(device):
    return {"backend": "open_clip", "model": object(), "model_name": "ViT-L-14", "device": device}


class _Features:
    def cpu(self):
        return self

    def numpy(self):
        return np.ones((1, 4))


def test_a_search_behind_a_busy_mps_lock_answers_busy_within_the_timeout(client):
    from api.routers import search

    started = time.monotonic()
    with (
        _mps_lock_held_elsewhere(),
        mock.patch.dict(search.VIEWER_CONFIG, {"features": {"show_semantic_search": True}}),
        mock.patch.object(search, "_text_encoder", _encoder("mps")),
        mock.patch.object(search, "_MPS_WAIT_SECONDS", 0.05),
        mock.patch("models.tagger.encode_text_prompts", return_value=_Features()) as encode,
    ):
        resp = client.get("/api/search", params={"q": "beach", "threshold": 0.1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["photos"] == []
    assert body["total"] == 0
    assert body["query"] == "beach"
    assert "busy" in body["error"]
    assert time.monotonic() - started < 5
    encode.assert_not_called()


def test_a_cold_search_behind_a_busy_mps_lock_gives_up_loading_the_encoder():
    from api.routers import search

    config = {"backend": "open_clip", "model_name": "ViT-L-14", "pretrained": "openai"}
    # Stubbed rather than patched in place: CI installs neither package.
    open_clip = mock.MagicMock()
    with (
        _mps_lock_held_elsewhere(),
        mock.patch.object(search, "_text_encoder", None),
        mock.patch.object(search, "_MPS_WAIT_SECONDS", 0.05),
        mock.patch.object(search, "_resolve_clip_config", return_value=config),
        mock.patch("utils.device.get_device", return_value="mps"),
        mock.patch.dict(sys.modules, {"open_clip": open_clip, "torch": mock.MagicMock()}),
    ):
        with pytest.raises(AcceleratorBusy):
            search._encode_texts(["beach"])
        assert search._text_encoder is None
        assert not search._text_encoder_lock.locked()
    open_clip.create_model_and_transforms.assert_not_called()


def test_concurrent_cold_searches_share_one_mps_wait_budget():
    from api.routers import search

    config = {"backend": "open_clip", "model_name": "ViT-L-14", "pretrained": "openai"}
    open_clip = mock.MagicMock()
    start = threading.Barrier(8)
    elapsed, errors = [], []

    def query():
        start.wait()
        began = time.monotonic()
        try:
            search._encode_texts(["beach"])
        except Exception as exc:
            errors.append(exc)
        finally:
            elapsed.append(time.monotonic() - began)

    with (
        _mps_lock_held_elsewhere(),
        mock.patch.object(search, "_text_encoder", None),
        mock.patch.object(search, "_MPS_WAIT_SECONDS", 0.1),
        mock.patch.object(search, "_resolve_clip_config", return_value=config),
        mock.patch("utils.device.get_device", return_value="mps"),
        mock.patch.dict(sys.modules, {"open_clip": open_clip, "torch": mock.MagicMock()}),
    ):
        threads = [threading.Thread(target=query) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        assert all(not thread.is_alive() for thread in threads)
    assert len(errors) == 8
    assert all(isinstance(exc, AcceleratorBusy) for exc in errors)
    assert max(elapsed) < 0.3
    assert not search._text_encoder_lock.locked()
    open_clip.create_model_and_transforms.assert_not_called()


@pytest.mark.parametrize("device", ["cuda", "cpu"])
def test_a_search_on_cuda_or_cpu_never_times_out_on_the_mps_lock(device):
    from api.routers import search

    with (
        _mps_lock_held_elsewhere(),
        mock.patch.object(search, "_text_encoder", _encoder(device)),
        mock.patch.object(search, "_MPS_WAIT_SECONDS", 0.01),
        mock.patch("models.tagger.encode_text_prompts", return_value=_Features()),
    ):
        assert search._encode_texts(["beach"]).shape == (1, 4)


@pytest.mark.parametrize("device", ["cuda", "cpu"])
def test_warm_searches_still_encode_concurrently_off_mps(device):
    from api.routers import search

    encode_together = threading.Barrier(2)
    errors = []

    def encode(*_args):
        encode_together.wait(timeout=1)
        return _Features()

    def query():
        try:
            search._encode_texts(["beach"])
        except Exception as exc:
            errors.append(exc)

    with (
        mock.patch.object(search, "_text_encoder", _encoder(device)),
        mock.patch("models.tagger.encode_text_prompts", side_effect=encode),
    ):
        threads = [threading.Thread(target=query) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        assert all(not thread.is_alive() for thread in threads)
    assert errors == []


class _MpsTagger:
    """A local VLM on MPS whose ``generate`` records whether the MPS lock was held."""

    backend = None
    device = "mps"

    def __init__(self):
        self.held = []

    def generate(self, *_args, **_kwargs):
        self.held.append(_mps_lock.locked())
        return "A stubbed model reply."


_LOCK_PREFIX = "/accelerator-lock/"


def _jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 90, 160)).save(buf, format="JPEG")
    return buf.getvalue()


def _seed_photo(seed_photos_prefix):
    path = _LOCK_PREFIX + "a.jpg"
    seed_photos_prefix(_LOCK_PREFIX, [{
        "path": path, "filename": "a.jpg", "aggregate": 7.0, "category": "landscape",
        "date_taken": "2026:01:01 10:00:00", "thumbnail": _jpeg(),
    }])
    return path


def test_a_local_caption_is_generated_with_the_mps_lock_held(edition_session_client, seed_photos_prefix):
    path = _seed_photo(seed_photos_prefix)
    tagger = _MpsTagger()
    with (
        mock.patch("api.routers.caption.VIEWER_CONFIG", {"features": {"show_captions": True}}),
        mock.patch("api.routers.caption._FULL_CONFIG", {}),
        mock.patch("api.routers.caption.resolve_vlm_config", return_value={"model_path": "stub"}),
        mock.patch("api.routers.caption.resolve_photo_disk_path", return_value=path),
        mock.patch("api.routers.caption.get_or_load_vlm_tagger", return_value=tagger),
        mock.patch("utils.image_loading.load_image_from_path", return_value=(Image.new("RGB", (8, 8)), None)),
    ):
        resp = edition_session_client.post("/api/caption", json={"path": path})
    assert resp.status_code == 200, resp.text
    assert resp.json()["source"] == "generated"
    assert tagger.held == [True]
    assert not _mps_lock.locked()


def test_a_local_critique_is_generated_with_the_mps_lock_held(edition_session_client, seed_photos_prefix):
    path = _seed_photo(seed_photos_prefix)
    tagger = _MpsTagger()
    with (
        mock.patch("api.routers.critique.VIEWER_CONFIG", {"features": {"show_critique": True, "show_vlm_critique": True}}),
        mock.patch("api.routers.critique.resolve_vlm_config", return_value={"model_path": "stub"}),
        mock.patch("api.routers.critique.get_or_load_vlm_tagger", return_value=tagger),
    ):
        resp = edition_session_client.post("/api/critique/vlm", json={"path": path})
    assert resp.status_code == 200, resp.text
    assert resp.json()["vlm_critique"] == "A stubbed model reply."
    assert tagger.held == [True]
    assert not _mps_lock.locked()
