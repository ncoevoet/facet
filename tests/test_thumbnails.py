"""Tests for the thumbnails API router (api/routers/thumbnails.py)."""

import os
import threading
import time
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from unittest import mock
from concurrent.futures import Future

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, get_optional_user
from utils import image_loading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cm(conn):
    """Wrap a mock connection in a context manager compatible with get_db()."""
    @contextmanager
    def _ctx():
        yield conn
    return _ctx


def _make_jpeg_bytes(size=(1, 1)) -> bytes:
    """Create a minimal valid JPEG image, 1x1 unless ``size`` says otherwise."""
    from PIL import Image
    buf = BytesIO()
    img = Image.new("RGB", size, (255, 0, 0))
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture()
def jpeg_bytes():
    return _make_jpeg_bytes()


@pytest.fixture()
def client():
    app = create_app()
    # Override auth so all requests are treated as authenticated
    app.dependency_overrides[get_optional_user] = lambda: CurrentUser(
        user_id="u1", role="admin"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /thumbnail
# ---------------------------------------------------------------------------

class TestGetThumbnail:
    """GET /thumbnail?path=... — photo thumbnail."""

    def test_thumbnail_returns_jpeg(self, client, jpeg_bytes):
        mock_conn = mock.MagicMock()
        mock_row = {"thumbnail": jpeg_bytes}
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)):
            resp = client.get("/thumbnail", params={"path": "/photo.jpg"})

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert len(resp.content) > 0

    def test_thumbnail_not_found(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)):
            resp = client.get("/thumbnail", params={"path": "/missing.jpg"})

        assert resp.status_code == 404

    def test_thumbnail_resize(self, client):
        """Requesting size=200 should return resized (smaller) bytes."""
        # Create a larger image so resize actually shrinks it
        from PIL import Image
        buf = BytesIO()
        img = Image.new("RGB", (640, 640), (0, 128, 255))
        img.save(buf, format="JPEG")
        large_jpeg = buf.getvalue()

        mock_conn = mock.MagicMock()
        mock_row = {"thumbnail": large_jpeg}
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)):
            resp = client.get("/thumbnail", params={"path": "/photo.jpg", "size": 200})

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        # Resized image should be smaller than the original 640x640
        assert len(resp.content) < len(large_jpeg)


def _image_size(image_bytes):
    from PIL import Image
    return Image.open(BytesIO(image_bytes)).size


def _noise(size):
    """Noisy, so a change to the resize or JPEG quality changes the bytes."""
    from PIL import Image
    pixels = np.random.default_rng(0).integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(pixels)


class TestThumbnailRenderedFromOriginal:
    """GET /thumbnail?size=N above 640 renders the original. Real rows, so the
    visibility-filtered SELECT runs."""

    STORED = (640, 427)

    @pytest.fixture(autouse=True)
    def _fresh_render_cache(self):
        from api.routers import thumbnails
        thumbnails._render_from_original_cached.cache_clear()
        thumbnails._no_signal_renders.clear()
        yield
        thumbnails._render_from_original_cached.cache_clear()
        thumbnails._no_signal_renders.clear()

    @pytest.fixture()
    def photo(self, tmp_path, seed_photos_prefix):
        """Seed one row whose original is ``tmp_path/<name>``; returns that path."""
        def make(name="photo.jpg", original=None, stored=self.STORED, sequence_kind=None):
            path = tmp_path / name
            if original is not None:
                path.write_bytes(original)
            seed_photos_prefix(str(tmp_path) + os.sep, [{
                "path": str(path), "filename": name,
                "thumbnail": _make_jpeg_bytes(stored), "sequence_kind": sequence_kind,
            }])
            return path
        return make

    def _get(self, client, path, size):
        return client.get("/thumbnail", params={"path": str(path), "size": size})

    def test_renders_from_the_original(self, client, photo):
        path = photo(original=_make_jpeg_bytes((3000, 2000)))

        resp = self._get(client, path, 1920)

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert _image_size(resp.content) == (1920, 1280)
        assert resp.headers["cache-control"] == "public, max-age=31536000"

    def test_every_size_above_640_shares_one_1920_render(self, client, photo):
        path = photo(original=_make_jpeg_bytes((3000, 2000)))

        with mock.patch("utils.image_loading.load_display_image",
                        wraps=image_loading.load_display_image) as load:
            sizes = {_image_size(self._get(client, path, size).content)
                     for size in (641, 1280, 1920, 100000)}

        assert sizes == {(1920, 1280)}
        assert load.call_count == 1

    def test_never_upscales_a_small_original(self, client, photo):
        path = photo(original=_make_jpeg_bytes((1200, 800)))

        assert _image_size(self._get(client, path, 1920).content) == (1200, 800)

    # A viewer DB export stores 320 px thumbnails and grids ask for 640.
    @pytest.mark.parametrize("stored", [(640, 427), (320, 213)])
    @pytest.mark.parametrize("size", [None, -1, 0, 320, 640])
    def test_sizes_up_to_640_never_read_the_original(self, client, photo, stored, size):
        path = photo(original=_make_jpeg_bytes((3000, 2000)), stored=stored)

        with mock.patch("utils.image_loading.load_display_image") as load:
            resp = client.get("/thumbnail", params={"path": str(path),
                                                    **({"size": size} if size is not None else {})})

        assert resp.status_code == 200
        assert _image_size(resp.content) == (stored if size != 320
                                             else (320, round(320 * stored[1] / stored[0])))
        load.assert_not_called()

    def test_a_small_stored_thumbnail_still_renders_above_640(self, client, photo):
        path = photo(original=_make_jpeg_bytes((3000, 2000)), stored=(320, 213))

        assert _image_size(self._get(client, path, 1920).content) == (1920, 1280)

    def test_a_missing_original_serves_the_stored_thumbnail_briefly(self, client, photo):
        path = photo(original=None)

        resp = self._get(client, path, 1920)

        assert resp.status_code == 200
        assert _image_size(resp.content) == self.STORED
        assert resp.headers["cache-control"] == "public, max-age=60"

    def test_an_undecodable_original_serves_the_stored_thumbnail_briefly(self, client, photo):
        path = photo(original=b"not an image")

        resp = self._get(client, path, 1920)

        assert resp.status_code == 200
        assert _image_size(resp.content) == self.STORED
        assert resp.headers["cache-control"] == "public, max-age=60"

    @pytest.mark.parametrize("error", [OSError, ValueError, RuntimeError])
    def test_a_failing_render_serves_the_stored_thumbnail(self, client, photo, error):
        path = photo(original=_make_jpeg_bytes((3000, 2000)))

        with mock.patch("utils.image_loading.load_display_image",
                        side_effect=error("boom")) as load:
            resp = self._get(client, path, 1920)

        load.assert_called_once()
        assert resp.status_code == 200
        assert _image_size(resp.content) == self.STORED

    def test_the_render_is_cached_until_the_original_changes(self, client, photo):
        path = photo(original=_make_jpeg_bytes((3000, 2000)))

        with mock.patch("utils.image_loading.load_display_image",
                        wraps=image_loading.load_display_image) as load:
            first = self._get(client, path, 1920).content
            assert self._get(client, path, 1920).content == first
            assert load.call_count == 1

            path.write_bytes(_make_jpeg_bytes((2000, 3000)))
            mtime = path.stat().st_mtime + 10
            os.utime(path, (mtime, mtime))
            second = self._get(client, path, 1920).content

        assert load.call_count == 2
        assert _image_size(second) == (1280, 1920)

    def test_raw_renders_through_the_viewer_display_loader(self, client, photo):
        path = photo(name="photo.cr2", original=b"raw bytes", sequence_kind="bracket")

        with mock.patch("utils.image_loading.get_raw_decode_settings",
                        return_value={"preview_min_sensor_ratio": 0.37}), \
             mock.patch("utils.image_loading.load_display_image",
                        return_value=_noise((3000, 2000))) as load:
            resp = self._get(client, path, 1920)

        load.assert_called_once_with(os.path.realpath(path), min_preview_sensor_ratio=0.37,
                                     decode_budget="viewer", sequence_kind="bracket",
                                     draft_edge=1920)
        from PIL import Image
        expected = _noise((3000, 2000))
        expected.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
        buf = BytesIO()
        expected.save(buf, format="JPEG", quality=85)
        assert resp.content == buf.getvalue()

    def test_renders_are_bounded_to_four_at_once(self, tmp_path):
        import time
        from api.routers import thumbnails

        state = {"inside": 0, "peak": 0}
        guard = threading.Lock()
        release = threading.Event()

        def _held_load(*_a, **_k):
            with guard:
                state["inside"] += 1
                state["peak"] = max(state["peak"], state["inside"])
            release.wait(5)
            with guard:
                state["inside"] -= 1
            return _noise((8, 8))

        with mock.patch("utils.image_loading.load_display_image", side_effect=_held_load):
            threads = [threading.Thread(target=thumbnails._render_from_original_cached,
                                        args=(str(tmp_path / f"{i}.jpg"), 0.0, None))
                       for i in range(8)]
            for t in threads:
                t.start()
            deadline = time.monotonic() + 5
            while state["inside"] < 4 and time.monotonic() < deadline:
                time.sleep(0.01)
            # Give a fifth render the chance to get in.
            time.sleep(0.1)
            peak_while_held = state["peak"]
            release.set()
            for t in threads:
                t.join()

        assert peak_while_held == 4

    def test_a_render_that_cannot_start_in_time_serves_the_stand_in(self, client, photo):
        from api.routers import thumbnails

        path = photo(original=_make_jpeg_bytes((3000, 2000)))

        with mock.patch.object(thumbnails, "_RENDER_WAIT_SECONDS", 0.01), \
             mock.patch.object(thumbnails, "_render_slots", threading.BoundedSemaphore(0)), \
             mock.patch("utils.image_loading.load_display_image") as load:
            # In a thread, so a wait that never times out fails instead of hanging.
            result = {}
            worker = threading.Thread(
                target=lambda: result.update(resp=self._get(client, path, 1920)), daemon=True)
            worker.start()
            worker.join(2)
            assert not worker.is_alive(), "the render waited for a slot instead of standing in"

        load.assert_not_called()
        assert _image_size(result["resp"].content) == self.STORED
        assert result["resp"].headers["cache-control"] == "public, max-age=60"

    def _two_identical_requests(self, client, path, decode, first_decode):
        """Hold one decode, join a second request to it, release, return both responses.

        `decode` is the patched `load_viewer_image`, which the caller keeps
        patched for any follow-up request. `first_decode` is None to succeed, or a callable run in place of the first
        decode. The join is observed on the flight's own future, which the leader
        publishes in `_render_inflight`.
        """
        from api.routers import thumbnails
        started, waiting, release = threading.Event(), threading.Event(), threading.Event()
        results, errors = [], []
        def load(*args, **kwargs):
            started.set()
            assert release.wait(3), 'test did not release held decode'
            if first_decode is not None and decode.call_count == 1:
                return first_decode()
            return _noise((32, 24))
        def request():
            try:
                results.append(self._get(client, path, 1920))
            except BaseException as ex:
                errors.append(ex)
        threads = [threading.Thread(target=request, daemon=True) for _ in range(2)]
        decode.side_effect = load
        try:
            threads[0].start()
            assert started.wait(2)
            assert len(thumbnails._render_inflight) == 1
            flight = next(iter(thumbnails._render_inflight.values()))
            real_result = flight.result
            def observed_result(timeout=None):
                waiting.set()
                return real_result(timeout)
            with mock.patch.object(flight, 'result', side_effect=observed_result):
                threads[1].start()
                assert waiting.wait(2), 'second request did not join the held render'
                assert decode.call_count == 1
                release.set()
        finally:
            release.set()
            for thread in threads:
                if thread.ident is not None:
                    thread.join(4)
        assert not errors and len(results) == 2
        assert all(not thread.is_alive() for thread in threads)
        assert not thumbnails._render_inflight
        assert results[0].content == results[1].content
        return results

    def test_identical_inflight_requests_share_one_decode(self, client, photo):
        path = photo(original=_make_jpeg_bytes((3000, 2000)))
        with mock.patch('api.raw_processing.load_viewer_image') as decode:
            results = self._two_identical_requests(client, path, decode, None)
            assert _image_size(results[0].content) == (32, 24)
            assert self._get(client, path, 1920).content == results[0].content
            assert decode.call_count == 1

    def test_a_failed_shared_decode_stands_in_for_both_then_retries(self, client, photo):
        from api.routers import thumbnails
        def fail():
            raise OSError('original temporarily unavailable')
        path = photo(original=_make_jpeg_bytes((3000, 2000)))
        with mock.patch('api.raw_processing.load_viewer_image') as decode:
            results = self._two_identical_requests(client, path, decode, fail)
            for response in results:
                self._assert_stand_in(response)
            retry = self._get(client, path, 1920)
            assert _image_size(retry.content) == (32, 24)
            assert decode.call_count == 2
            assert self._get(client, path, 1920).content == retry.content
            assert decode.call_count == 2
            assert not thumbnails._render_inflight

    def test_a_no_signal_shared_decode_is_not_retried_until_the_file_changes(self, client, photo):
        from api.routers import thumbnails
        path = photo(original=_make_jpeg_bytes((3000, 2000)))
        with mock.patch('api.raw_processing.load_viewer_image') as decode:
            results = self._two_identical_requests(client, path, decode, self._black_render)
            for response in results:
                self._assert_stand_in(response)
            self._assert_stand_in(self._get(client, path, 1920))
            assert decode.call_count == 1
            current = path.stat()
            os.utime(path, ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000_000))
            retry = self._get(client, path, 1920)
            assert _image_size(retry.content) == (32, 24)
            assert decode.call_count == 2
            assert self._get(client, path, 1920).content == retry.content
            assert decode.call_count == 2
            assert not thumbnails._render_inflight

    def test_a_waiting_render_timeout_does_not_cancel_or_duplicate_its_owner(self, client, photo):
        from api.routers import thumbnails
        started, release = threading.Event(), threading.Event()
        path = photo(original=_make_jpeg_bytes((3000, 2000)))
        result = {}
        def load(*args, **kwargs):
            started.set()
            assert release.wait(3)
            return _noise((32, 24))
        worker = threading.Thread(target=lambda: result.update(response=self._get(client, path, 1920)), daemon=True)
        with mock.patch.object(thumbnails, '_RENDER_WAIT_SECONDS', 0.01), \
                mock.patch('api.raw_processing.load_viewer_image', side_effect=load) as decode:
            try:
                worker.start()
                assert started.wait(2)
                self._assert_stand_in(self._get(client, path, 1920))
                assert decode.call_count == 1
                assert len(thumbnails._render_inflight) == 1
            finally:
                release.set()
                worker.join(4)
            assert not worker.is_alive() and not thumbnails._render_inflight
            assert _image_size(result['response'].content) == (32, 24)
            assert self._get(client, path, 1920).content == result['response'].content
            assert decode.call_count == 1

    def test_jpeg_can_render_while_three_slow_renders_hold_their_budget(self, client, tmp_path, seed_photos_prefix):
        from api.routers import thumbnails
        release, fourth_attempt = threading.Event(), threading.Event()
        guard = threading.Lock()
        attempts = 0
        class ObservedBudget(threading.BoundedSemaphore):
            def acquire(self, *args, **kwargs):
                nonlocal attempts
                with guard:
                    attempts += 1
                    if attempts == 4:
                        fourth_attempt.set()
                return super().acquire(*args, **kwargs)
        raws = [tmp_path / f'{index}.rw2' for index in range(4)]
        jpeg = tmp_path / 'ready.jpg'
        for path in [*raws, jpeg]:
            path.write_bytes(_make_jpeg_bytes((8, 8)))
        seed_photos_prefix(str(tmp_path) + os.sep, [
            {'path': str(path), 'filename': path.name, 'thumbnail': _make_jpeg_bytes(self.STORED)}
            for path in [*raws, jpeg]])
        slots = threading.BoundedSemaphore(thumbnails._RENDER_SLOTS)
        free_slots_during_jpeg = []
        def load(path, *args, **kwargs):
            if Path(path).suffix == '.rw2':
                assert release.wait(3), 'test did not release slow render'
            else:
                free_slots_during_jpeg.append(slots._value)
            return _noise((32, 24))
        errors = []
        def request(path):
            try:
                response = self._get(client, path, 1920)
                assert _image_size(response.content) == (32, 24)
            except BaseException as ex:
                errors.append(ex)
        threads = [threading.Thread(target=request, args=(path,), daemon=True) for path in raws]
        with mock.patch.object(thumbnails, '_nonjpeg_render_slots', ObservedBudget(3)), \
                mock.patch.object(thumbnails, '_render_slots', slots), \
                mock.patch('api.raw_processing.load_viewer_image', side_effect=load):
            try:
                for thread in threads:
                    thread.start()
                assert fourth_attempt.wait(2), 'fourth slow render did not reach its reserved budget'
                deadline = time.monotonic() + 2
                while slots._value != 1 and time.monotonic() < deadline:
                    time.sleep(0.005)
                assert slots._value == 1, 'the slow RAWs did not take their render slots'
                response = self._get(client, jpeg, 1920)
                assert _image_size(response.content) == (32, 24)
                # Three slow RAWs hold three of the four slots; the JPEG took the last.
                assert free_slots_during_jpeg == [0]
            finally:
                release.set()
                for thread in threads:
                    thread.join(4)
        assert not errors and all(not thread.is_alive() for thread in threads)
        assert not thumbnails._render_inflight

    def _get_in_thread(self, client, path):
        """GET size=1920 in a thread, so a wait that never times out fails instead of hanging."""
        result = {}
        worker = threading.Thread(
            target=lambda: result.update(resp=self._get(client, path, 1920)), daemon=True)
        worker.start()
        worker.join(3)
        assert not worker.is_alive(), "the render waited past its budget instead of standing in"
        return result["resp"]

    def test_a_busy_non_jpeg_gate_serves_the_stand_in_and_keeps_its_permits(self, client, photo):
        from api.routers import thumbnails
        path = photo(name="photo.cr3", original=_make_jpeg_bytes((3000, 2000)))
        gate = threading.BoundedSemaphore(1)
        assert gate.acquire(timeout=0)
        with mock.patch.object(thumbnails, "_RENDER_WAIT_SECONDS", 0.05), \
                mock.patch.object(thumbnails, "_nonjpeg_render_slots", gate), \
                mock.patch.object(thumbnails, "_render_slots", threading.BoundedSemaphore(4)) as slots, \
                mock.patch("api.raw_processing.load_viewer_image") as load:
            resp = self._get_in_thread(client, path)
            assert slots._value == 4
        load.assert_not_called()
        self._assert_stand_in(resp)
        gate.release()
        assert gate._value == 1

    def test_a_render_slot_timeout_shares_the_gate_deadline_and_releases_the_gate(self, client, photo):
        from api.routers import thumbnails
        path = photo(name="photo.png", original=_make_jpeg_bytes((3000, 2000)))
        budget = 0.5
        slot_timeouts = []
        class SlowGate(threading.BoundedSemaphore):
            def acquire(self, *args, **kwargs):
                time.sleep(budget * 0.6)
                return super().acquire(*args, **kwargs)
        class ObservedSlots(threading.BoundedSemaphore):
            def acquire(self, blocking=True, timeout=None):
                slot_timeouts.append(timeout)
                return super().acquire(blocking, timeout)
        gate = SlowGate(3)
        with mock.patch.object(thumbnails, "_RENDER_WAIT_SECONDS", budget), \
                mock.patch.object(thumbnails, "_nonjpeg_render_slots", gate), \
                mock.patch.object(thumbnails, "_render_slots", ObservedSlots(0)), \
                mock.patch("api.raw_processing.load_viewer_image") as load:
            resp = self._get_in_thread(client, path)
        load.assert_not_called()
        self._assert_stand_in(resp)
        # The slot wait gets what the gate left of one budget, not a fresh one.
        assert len(slot_timeouts) == 1 and slot_timeouts[0] <= budget * 0.5
        assert gate._value == 3

    def test_a_decode_error_releases_both_permits(self, client, photo):
        from api.routers import thumbnails
        path = photo(name="photo.png", original=_make_jpeg_bytes((3000, 2000)))
        gate, slots = threading.BoundedSemaphore(3), threading.BoundedSemaphore(4)
        with mock.patch.object(thumbnails, "_nonjpeg_render_slots", gate), \
                mock.patch.object(thumbnails, "_render_slots", slots), \
                mock.patch("api.raw_processing.load_viewer_image",
                           side_effect=OSError("corrupt original")) as load:
            resp = self._get_in_thread(client, path)
        assert load.call_count == 1
        self._assert_stand_in(resp)
        assert gate._value == 3 and slots._value == 4
        assert not thumbnails._render_inflight

    def test_a_joined_render_timing_out_serves_the_stand_in(self, client, photo, caplog):
        """On Python 3.10 a future's timeout is not an OSError; emulate that on 3.11+."""
        from api.routers import thumbnails
        path = photo(name="photo.png", original=_make_jpeg_bytes((3000, 2000)))
        class Py310FuturesTimeout(Exception):
            pass
        class TimingOutFlight(Future):
            def result(self, timeout=None):
                raise Py310FuturesTimeout()
        key = (thumbnails.resolve_photo_disk_path(str(path)), os.path.getmtime(path), None, None)
        with mock.patch.object(thumbnails, "FuturesTimeoutError", Py310FuturesTimeout), \
                mock.patch.dict(thumbnails._render_inflight, {key: TimingOutFlight()}), \
                mock.patch("api.raw_processing.load_viewer_image") as load:
            resp = self._get(client, path, 1920)
        load.assert_not_called()
        self._assert_stand_in(resp)
        assert not thumbnails._render_inflight
        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1 and "()" not in warnings[0]
        assert "Py310FuturesTimeout" in warnings[0]

    def test_a_leader_rechecks_the_no_signal_cache_before_decoding(self, client, photo):
        """_render_from_original checks first, so only a direct call reaches the leader's recheck."""
        from api.routers import thumbnails
        path = photo(name="photo.png", original=_make_jpeg_bytes((3000, 2000)))
        key = (thumbnails.resolve_photo_disk_path(str(path)), os.path.getmtime(path), None, None)
        thumbnails._no_signal_renders[key] = True
        with mock.patch("api.raw_processing.load_viewer_image") as load:
            assert thumbnails._coalesced_render(key) is None
        load.assert_not_called()
        assert not thumbnails._render_inflight

    @staticmethod
    def _black_render(*_a, **_k):
        from PIL import Image
        return Image.new("RGB", (3000, 2000), (0, 0, 0))

    def _assert_stand_in(self, resp):
        assert resp.status_code == 200
        assert _image_size(resp.content) == self.STORED
        assert resp.headers["cache-control"] == "public, max-age=60"
        from PIL import Image
        assert Image.open(BytesIO(resp.content)).convert("L").getextrema()[1] > 0

    def test_a_render_with_no_signal_serves_the_stored_thumbnail_briefly(self, client, photo):
        path = photo(original=_make_jpeg_bytes((3000, 2000)))

        with mock.patch("api.raw_processing.load_viewer_image", side_effect=self._black_render):
            resp = self._get(client, path, 1920)

        self._assert_stand_in(resp)

    @pytest.mark.raw_brand_samples
    def test_a_truncated_rw2_serves_the_stored_thumbnail_briefly(self, client, photo, tmp_path):
        pytest.importorskip("rawpy")
        sample = Path(os.environ.get("FACET_RAW_SAMPLE_DIR", ".")) / "sample.rw2"
        if not sample.exists():
            pytest.skip("sample.rw2 not available")
        path = photo(name="truncated.rw2", original=sample.read_bytes()[:4096])

        resp = self._get(client, path, 1920)

        self._assert_stand_in(resp)

    def test_the_render_slot_is_held_until_the_jpeg_is_encoded(self, client, photo):
        from api.routers import thumbnails
        from utils import image_transforms

        path = photo(original=_make_jpeg_bytes((3000, 2000)))
        real = image_transforms.generate_photo_thumbnail
        seen = {}

        def _probe(img, size, quality):
            got = thumbnails._render_slots.acquire(blocking=False)
            seen["acquired"] = got
            if got:
                thumbnails._render_slots.release()
            return real(img, size, quality)

        with mock.patch.object(thumbnails, "_render_slots", threading.BoundedSemaphore(1)), \
             mock.patch("utils.image_transforms.generate_photo_thumbnail", side_effect=_probe):
            resp = self._get(client, path, 1920)

        assert resp.status_code == 200
        assert seen["acquired"] is False

    def test_a_no_signal_render_is_not_decoded_twice(self, client, photo, caplog):
        path = photo(original=_make_jpeg_bytes((3000, 2000)))

        with mock.patch("api.raw_processing.load_viewer_image",
                        side_effect=self._black_render) as load:
            first = self._get(client, path, 1920)
            caplog.clear()
            second = self._get(client, path, 1920)

        assert load.call_count == 1
        self._assert_stand_in(first)
        self._assert_stand_in(second)
        assert not [r for r in caplog.records if r.levelname == "WARNING"]


# ---------------------------------------------------------------------------
# GET /face_thumbnail/{face_id}
# ---------------------------------------------------------------------------

class TestFaceThumbnail:
    """GET /face_thumbnail/{face_id} — cropped face thumbnail."""

    def test_face_thumbnail_not_found(self, client):
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with mock.patch("api.routers.thumbnails.get_db_connection", return_value=mock_conn):
            resp = client.get("/face_thumbnail/99999")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /image
# ---------------------------------------------------------------------------

class TestImage:
    """GET /image?path=... — full-size image."""

    def test_image_path_traversal_blocked(self, client):
        """A path not present in the database returns 404."""
        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)):
            resp = client.get("/image", params={"path": "/etc/passwd"})

        assert resp.status_code == 404

    def test_image_raw_decode_failure_falls_back_to_thumbnail(self, client, jpeg_bytes, tmp_path):
        """fallback=thumbnail degrades to the stored thumbnail on a RuntimeError, not a 500."""
        raw_file = tmp_path / "photo.cr2"
        raw_file.write_bytes(b"not a real raw file")

        mock_conn = mock.MagicMock()
        photo_row = {"path": "/library/photo.cr2", "sequence_kind": None, "preview_revision": None}
        thumbnail_row = {"thumbnail": jpeg_bytes}
        mock_conn.execute.side_effect = [
            mock.Mock(fetchone=mock.Mock(return_value=photo_row)),
            mock.Mock(fetchone=mock.Mock(return_value=thumbnail_row)),
        ]

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)), \
             mock.patch("api.routers.thumbnails.resolve_photo_disk_path", return_value=str(raw_file)), \
             mock.patch(
                 "api.routers.thumbnails._convert_raw_cached",
                 side_effect=RuntimeError(f"RAW decode failed: {raw_file}"),
             ):
            resp = client.get(
                "/image", params={"path": "/library/photo.cr2", "fallback": "thumbnail"}
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content == jpeg_bytes
        assert resp.headers["cache-control"] == "public, max-age=60"

    def test_image_raw_decode_failure_without_fallback_returns_500(self, client, tmp_path):
        """Without fallback=thumbnail, a RAW decode failure still surfaces as a 500."""
        raw_file = tmp_path / "photo.cr2"
        raw_file.write_bytes(b"not a real raw file")

        mock_conn = mock.MagicMock()
        photo_row = {"path": "/library/photo.cr2", "sequence_kind": None, "preview_revision": None}
        mock_conn.execute.return_value.fetchone.return_value = photo_row

        with mock.patch("api.routers.thumbnails.get_db", _cm(mock_conn)), \
             mock.patch("api.routers.thumbnails.resolve_photo_disk_path", return_value=str(raw_file)), \
             mock.patch(
                 "api.routers.thumbnails._convert_raw_cached",
                 side_effect=RuntimeError(f"RAW decode failed: {raw_file}"),
             ):
            resp = client.get("/image", params={"path": "/library/photo.cr2"})

        assert resp.status_code == 500


def test_heif_conversion_uses_shared_loader():
    """_convert_nonraw_cached routes through open_nonraw_image (EXIF orientation + PQ tone map).

    Before the Canon .HIF fix the viewer decoded HEIF directly with PIL, so the
    browser showed a dark/rotated image relative to what the scanner scored.
    """
    from PIL import Image as PILImage
    from api.routers import thumbnails

    sentinel = PILImage.new("RGB", (2, 2), (10, 20, 30))
    thumbnails._convert_nonraw_cached.cache_clear()
    try:
        with mock.patch("utils.image_loading.open_nonraw_image", return_value=sentinel) as m:
            out = thumbnails._convert_nonraw_cached("/library/photo.heif", 1.0, 96)
            m.assert_called_once_with("/library/photo.heif")
        im = PILImage.open(BytesIO(out))
        assert im.size == (2, 2)
        assert im.getpixel((0, 0)) == (10, 20, 30)
    finally:
        thumbnails._convert_nonraw_cached.cache_clear()


@pytest.mark.skipif(not image_loading._heif_available, reason='pillow-heif not installed')
def test_heif_conversion_matches_what_the_scanner_scored():
    """The browser JPEG and the scored buffer must come from one decode.

    Run on the real Canon HDR PQ frame: before the shared loader the viewer
    decoded HEIF with a bare PIL open, so it showed the untone-mapped, dark
    image while the models scored a different one.
    """
    from api.routers import thumbnails
    from PIL import Image as PILImage

    fixture = str(Path(__file__).parent / 'fixtures' / 'canon_eos_r8_hdr_pq.hif')
    thumbnails._convert_nonraw_cached.cache_clear()
    try:
        jpeg = thumbnails._convert_nonraw_cached(fixture, 1.0, 100)
    finally:
        thumbnails._convert_nonraw_cached.cache_clear()

    served = np.asarray(PILImage.open(BytesIO(jpeg)).convert('RGB')).astype(int)
    scored = np.asarray(image_loading.open_nonraw_image(fixture)).astype(int)
    assert served.shape == scored.shape
    # JPEG at quality 100 is still lossy; the two must agree to within it, and
    # nowhere near the gulf a missing tone map would open.
    assert np.abs(served - scored).mean() < 2.0
