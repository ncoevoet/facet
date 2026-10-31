"""Real JPEG XL discovery, metadata, orientation and browser rendering."""
from io import BytesIO
import os

import numpy as np
import pytest
from PIL import Image, ImageOps
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, get_optional_user
from utils import image_loading

imagecodecs = pytest.importorskip("imagecodecs")


def _native_jpegxl(path, pixels, *, container=False, exif=None, compressed=False, bare_tiff=False):
    import struct
    raw = imagecodecs.jpegxl_encode(pixels, lossless=True, numthreads=1)
    if container or exif is not None:
        def box(kind, payload):
            return struct.pack(">I4s", len(payload) + 8, kind) + payload
        metadata = b''
        if exif is not None:
            payload = exif.tobytes()[6:]
            if not bare_tiff:
                payload = b'\x00' * 4 + payload
            metadata = (box(b'brob', b'Exif' + imagecodecs.brotli_encode(payload))
                        if compressed else box(b'Exif', payload))
        raw = (b'\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a'
               + box(b'ftyp', b'jxl \x00\x00\x00\x00jxl ')
               + metadata + box(b'jxlc', raw))
    path.write_bytes(raw)


def _jpegxl(path, orientation=1):
    pixels = np.zeros((24, 40, 3), dtype=np.uint8)
    pixels[:, :20] = (240, 20, 10)
    pixels[:, 20:] = (10, 40, 230)
    img = Image.fromarray(pixels)
    exif = Image.Exif()
    exif[274] = orientation
    exif[306] = "2024:01:13 11:36:39"
    exif[34665] = {36867: "2024:01:13 11:36:39"}
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif, quality=95)
    original = buf.getvalue()
    encoded = imagecodecs.jpegxl_encode_jpeg(original, numthreads=1)
    path.write_bytes(encoded)
    return original


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_decode_matches_original_jpeg_and_preserves_metadata(tmp_path, orientation):
    path = tmp_path / "award.JXL"
    original = _jpegxl(path, orientation)
    expected = ImageOps.exif_transpose(Image.open(BytesIO(original)))
    actual = image_loading.open_nonraw_image(path)
    assert actual.mode == "RGB"
    assert actual.size == expected.size
    np.testing.assert_array_equal(np.asarray(actual), np.asarray(expected))
    assert actual.getexif()[306] == "2024:01:13 11:36:39"
    assert imagecodecs.jpegxl_decode_jpeg(path.read_bytes(), numthreads=1) == original


def test_native_lossless_jpegxl_alpha_and_discovery(tmp_path):
    from facet import _gather_scan_files
    path = tmp_path / "certificate.JXL"
    _native_jpegxl(path, np.asarray(Image.new("RGBA", (30, 20), (255, 0, 0, 0))))
    actual = image_loading.open_nonraw_image(path)
    assert actual.mode == "RGB"
    assert actual.getpixel((0, 0)) == (255, 255, 255)
    assert _gather_scan_files([str(tmp_path)], {}) == [path]
    assert ".jxl" in image_loading.WATCHABLE_IMAGE_EXTENSIONS


@pytest.fixture
def jxl_client():
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: CurrentUser(user_id=None, role="admin")
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_browser_full_image_and_sharp_thumbnail_are_jpeg(tmp_path, seed_photos_prefix, jxl_client):
    path = tmp_path / "certificate.jxl"
    _jpegxl(path, orientation=6)
    stored = BytesIO()
    Image.new("RGB", (4, 6)).save(stored, format="JPEG")
    seed_photos_prefix(str(tmp_path) + os.sep, [{
        "path": str(path), "filename": path.name, "thumbnail": stored.getvalue(),
    }])
    for endpoint, params in [("/image", {}), ("/thumbnail", {"size": 1920})]:
        response = jxl_client.get(endpoint, params={"path": str(path), **params})
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert Image.open(BytesIO(response.content)).size == (24, 40)
    response = jxl_client.get("/image", params={"path": str(path)})
    cached = jxl_client.get("/image", params={"path": str(path)},
                            headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304


def test_bad_jpegxl_can_fall_back_to_stored_thumbnail(tmp_path, seed_photos_prefix, jxl_client):
    path = tmp_path / "broken.jxl"
    path.write_bytes(b"not JPEG XL")
    stored = BytesIO()
    Image.new("RGB", (4, 6)).save(stored, format="JPEG")
    seed_photos_prefix(str(tmp_path) + os.sep, [{
        "path": str(path), "filename": path.name, "thumbnail": stored.getvalue(),
    }])
    response = jxl_client.get("/image", params={"path": str(path), "fallback": "thumbnail"})
    assert response.status_code == 200
    assert response.content == stored.getvalue()
    assert "Accept" in {v.strip() for v in response.headers["vary"].split(",")}
    assert jxl_client.get("/image", params={"path": str(path)}).status_code == 500


def test_scanner_reads_original_capture_date(tmp_path, monkeypatch, caplog):
    import exiftool
    import processing.scorer as scorer_module
    from processing.scorer import Facet

    def _no_exiftool(*args, **kwargs):
        raise FileNotFoundError("exiftool disabled for this test")

    # Isolate the Pillow fallback (step 4) from the machine: no persistent
    # ExifTool, no exiftool binary, and no module-level Pillow handles that an
    # earlier test or a full Facet.__init__ may have populated.
    monkeypatch.setattr(exiftool, "get_exif_single", lambda *a, **k: {})
    monkeypatch.setattr("subprocess.run", _no_exiftool)
    monkeypatch.setattr(scorer_module, "Image", None)
    monkeypatch.setattr(scorer_module, "ExifTags", None)
    path = tmp_path / "diploma.jxl"
    _jpegxl(path)
    scorer = object.__new__(Facet)
    with caplog.at_level("WARNING"):
        assert scorer.get_exif_data(path)["date_taken"] == "2024:01:13 11:36:39"
    assert "EXIF extraction failed" not in caplog.text


@pytest.mark.parametrize("accept,native", [
    ("image/jxl", True),
    ("image/avif,image/jxl,image/webp,image/*;q=0.8,*/*;q=0.5", True),
    ("image/jxl;q=0.8", True),
    ("IMAGE/JXL; Q = 0.5", True),
    ("image/jxl;q=0", False),
    ("image/*", False),
    ("*/*", False),
    ("image/jxl;q=invalid", False),
    ("image/jxl;q=1.5", False),
    ("image/jxl;q=NaN", False),
])
def test_native_jxl_requires_explicit_browser_support(tmp_path, seed_photos_prefix, jxl_client, accept, native):
    path = tmp_path / "award.jxl"
    _jpegxl(path)
    seed_photos_prefix(str(tmp_path) + os.sep, [{"path": str(path), "filename": path.name}])
    response = jxl_client.get("/image", params={"path": str(path)}, headers={"Accept": accept})
    assert response.status_code == 200
    assert "Accept" in {v.strip() for v in response.headers["vary"].split(",")}
    assert response.headers["content-type"] == ("image/jxl" if native else "image/jpeg")
    if native:
        assert response.content == path.read_bytes()
    else:
        assert response.content.startswith(b"\xff\xd8")
    cached = jxl_client.get("/image", params={"path": str(path)},
                            headers={"Accept": accept, "If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304
    assert "Accept" in {v.strip() for v in cached.headers["vary"].split(",")}
    # An ETag for the other representation must never turn this one into 304.
    other = jxl_client.get("/image", params={"path": str(path)},
                           headers={"Accept": "*/*" if native else "image/jxl",
                                    "If-None-Match": response.headers["etag"]})
    assert other.status_code == 200
    assert other.headers["etag"] != response.headers["etag"]


def test_native_request_still_requires_visible_library_row(tmp_path, jxl_client):
    path = tmp_path / "unindexed.jxl"
    _jpegxl(path)
    response = jxl_client.get("/image", params={"path": str(path)}, headers={"Accept": "image/jxl"})
    assert response.status_code == 404


@pytest.mark.parametrize("accept", ["image/jxl", "*/*"])
def test_missing_original_after_resolution_uses_thumbnail_and_varies_accept(
        tmp_path, seed_photos_prefix, jxl_client, monkeypatch, accept):
    from api.routers import thumbnails
    path = tmp_path / "disappeared.jxl"
    stored = BytesIO()
    Image.new("RGB", (4, 6)).save(stored, format="JPEG")
    seed_photos_prefix(str(tmp_path) + os.sep, [{
        "path": str(path), "filename": path.name, "thumbnail": stored.getvalue(),
    }])
    monkeypatch.setattr(thumbnails, "resolve_photo_disk_path", lambda _: str(path))
    response = jxl_client.get("/image", params={"path": str(path), "fallback": "thumbnail"},
                              headers={"Accept": accept})
    assert response.status_code == 200
    assert response.content == stored.getvalue()
    assert "Accept" in {v.strip() for v in response.headers["vary"].split(",")}


@pytest.mark.parametrize("accept", ["image/jxl", "*/*"])
def test_resolution_failure_fallback_varies_accept(
        tmp_path, seed_photos_prefix, jxl_client, monkeypatch, accept):
    from fastapi import HTTPException
    from api.routers import thumbnails
    path = tmp_path / "offline.jxl"
    stored = BytesIO()
    Image.new("RGB", (4, 6)).save(stored, format="JPEG")
    seed_photos_prefix(str(tmp_path) + os.sep, [{
        "path": str(path), "filename": path.name, "thumbnail": stored.getvalue(),
    }])
    def refuse(_):
        raise HTTPException(status_code=404)
    monkeypatch.setattr(thumbnails, "resolve_photo_disk_path", refuse)
    response = jxl_client.get("/image", params={"path": str(path), "fallback": "thumbnail"},
                              headers={"Accept": accept})
    assert response.status_code == 200
    assert response.content == stored.getvalue()
    assert "Accept" in {v.strip() for v in response.headers["vary"].split(",")}


@pytest.mark.parametrize("size", [(8, 8), (240, 200), (320, 240), (512, 257), (1920, 1080)])
@pytest.mark.parametrize("container", [False, True])
def test_header_dimensions_match_real_decodes(tmp_path, size, container):
    from utils.jpegxl_header import jpegxl_basic_info
    path = tmp_path / "size.jxl"
    _native_jpegxl(path, np.zeros((size[1], size[0], 3), dtype=np.uint8), container=container)
    with path.open("rb") as stream:
        info = jpegxl_basic_info(stream)
        assert (info.width, info.height) == size
        assert stream.tell() == 0
    assert image_loading.open_nonraw_image(path).size == size


@pytest.mark.parametrize("container", [False, True])
def test_pixel_limit_precedes_eager_decoder(tmp_path, monkeypatch, container):
    path = tmp_path / "oversized.jxl"
    _native_jpegxl(path, np.zeros((24, 40, 3), dtype=np.uint8), container=container)
    calls = []
    decoder = imagecodecs.jpegxl_decode
    def observed(*args, **kwargs):
        calls.append(True)
        return decoder(*args, **kwargs)
    monkeypatch.setattr(imagecodecs, "jpegxl_decode", observed)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ValueError, match="MAX_IMAGE_PIXELS"):
        Image.open(path)
    assert calls == []


def test_fragmented_header_and_large_metadata_box(tmp_path):
    import struct
    from utils.jpegxl_header import jpegxl_basic_info
    path = tmp_path / "fragments.jxl"
    raw = imagecodecs.jpegxl_encode(np.zeros((24, 40, 3), dtype=np.uint8), lossless=True, numthreads=1)
    assert raw[:2] == b"\xff\x0a"
    def box(kind, payload):
        return struct.pack(">I4s", len(payload) + 8, kind) + payload
    signature = b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a"
    ftyp = box(b"ftyp", b"jxl \x00\x00\x00\x00jxl ")
    # Metadata is skipped by seeking; it is never read into the prefix buffer.
    metadata = struct.pack(">I4sQ", 1, b"xml ", 16 + 100000) + b" " * 100000
    path.write_bytes(signature + ftyp + metadata
                     + box(b"jxlp", struct.pack(">I", 0) + raw[:5])
                     + box(b"jxlp", struct.pack(">I", 0x80000001) + raw[5:]))
    with path.open("rb") as stream:
        info = jpegxl_basic_info(stream)
        assert (info.width, info.height) == (40, 24)
    assert image_loading.open_nonraw_image(path).size == (40, 24)


@pytest.mark.parametrize("payload", [b"", b"bad", b"\xff\x0a", b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a\x00\x00\x00\x04jxlc"])
def test_invalid_headers_are_refused_without_decoding(payload):
    from utils.jpegxl_header import jpegxl_basic_info
    with pytest.raises(ValueError):
        jpegxl_basic_info(BytesIO(payload))


def test_grayscale_sixteen_bit_jxl_keeps_tonal_range(tmp_path):
    path = tmp_path / "gray.jxl"
    source = np.arange(256, dtype=np.uint16).reshape(16, 16) * 257
    _native_jpegxl(path, source)
    actual = np.asarray(image_loading.open_nonraw_image(path))
    assert len(np.unique(actual)) > 150
    assert actual.min() == 0
    assert actual.max() == 255


def _linear_rgb_profile():
    """A valid ICC profile with linear TRCs, derived from LittleCMS sRGB."""
    import struct
    from PIL import ImageCms
    data = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    for index in range(struct.unpack_from(">I", data, 128)[0]):
        kind, offset, _ = struct.unpack_from(">4sII", data, 132 + 12 * index)
        if kind in (b"rTRC", b"gTRC", b"bTRC"):
            struct.pack_into(">H", data, offset + 8, 0)
            struct.pack_into(">i", data, offset + 12, 65536)
    return bytes(data)


def test_color_managed_fallback_and_source_bytes_are_preserved(tmp_path, seed_photos_prefix, jxl_client):
    from PIL import ImageCms
    path = tmp_path / "linear.jxl"
    profile = _linear_rgb_profile()
    jpeg = BytesIO()
    Image.new("RGB", (40, 24), (64, 128, 192)).save(jpeg, format="JPEG", quality=100, icc_profile=profile)
    path.write_bytes(imagecodecs.jpegxl_encode_jpeg(jpeg.getvalue(), numthreads=1))
    before = path.read_bytes()
    expected = ImageCms.profileToProfile(
        Image.open(BytesIO(jpeg.getvalue())), ImageCms.ImageCmsProfile(BytesIO(profile)),
        ImageCms.createProfile("sRGB"), outputMode="RGB",
    )
    # A color transform, not merely the same source samples without their ICC.
    assert expected.getpixel((0, 0))[0] > 100
    np.testing.assert_array_equal(np.asarray(image_loading.open_nonraw_image(path)), np.asarray(expected))
    seed_photos_prefix(str(tmp_path) + os.sep, [{"path": str(path), "filename": path.name}])
    fallback = jxl_client.get("/image", params={"path": str(path)}, headers={"Accept": "*/*"})
    assert fallback.status_code == 200
    rendered = np.asarray(Image.open(BytesIO(fallback.content))).astype(int)
    assert np.max(np.abs(rendered - np.asarray(expected).astype(int))) <= 3
    native = jxl_client.get("/image", params={"path": str(path)}, headers={"Accept": "image/jxl"})
    assert native.content == before == path.read_bytes()


@pytest.mark.parametrize("kind", ["float", "sixteen_bit_alpha"])
def test_gray_float_and_sixteen_bit_alpha_keep_their_values(tmp_path, kind):
    path = tmp_path / "unsupported.jxl"
    if kind == "float":
        data = np.linspace(0, 1, 960, dtype=np.float32).reshape(24, 40)
    else:
        data = np.full((24, 40, 2), [32768, 65535], dtype=np.uint16)
    path.write_bytes(imagecodecs.jpegxl_encode(data, lossless=True, numthreads=1))
    actual = image_loading.open_nonraw_image(path)
    assert actual.size == (40, 24) and actual.mode == 'RGB'
    if kind == 'float':
        assert actual.getpixel((0, 0)) == (0, 0, 0)
        assert actual.getpixel((39, 23)) == (255, 255, 255)
    else:
        assert np.unique(np.asarray(actual).reshape(-1, 3), axis=0).tolist() == [[128, 128, 128]]


def test_lossy_float_overshoot_is_clipped_not_refused(tmp_path):
    # Lossy coding rings a little past [0, 1] even for SDR content, so a
    # float export must clip like every other sample type rather than fail.
    path = tmp_path / "lossy_float.jxl"
    ramp = np.linspace(0, 1, 512, dtype=np.float32)
    data = np.tile(ramp, (512, 1))
    path.write_bytes(imagecodecs.jpegxl_encode(data, distance=2.0, numthreads=1))
    decoded = imagecodecs.jpegxl_decode(path.read_bytes(), numthreads=1)
    assert decoded.min() < 0 or decoded.max() > 1
    actual = np.asarray(image_loading.open_nonraw_image(path)).astype(int)
    assert actual.shape == (512, 512, 3)
    assert actual[:, :8].max() <= 8 and actual[:, -8:].min() >= 247


def test_non_finite_float_samples_are_refused():
    from utils.jpegxl import _pixel_image
    pixels = np.zeros((4, 4), dtype=np.float32)
    pixels[1, 1] = np.nan
    with pytest.raises(ValueError, match="finite"):
        _pixel_image(pixels, 32)


def test_native_delivery_skips_decode_and_supports_byte_ranges(tmp_path, seed_photos_prefix, jxl_client, monkeypatch):
    from api.routers import thumbnails
    path = tmp_path / "native.jxl"
    _jpegxl(path)
    original = path.read_bytes()
    seed_photos_prefix(str(tmp_path) + os.sep, [{"path": str(path), "filename": path.name}])
    def forbid(*args, **kwargs):
        raise AssertionError("native delivery must not decode or generate a JPEG")
    monkeypatch.setattr(thumbnails, "_encode_nonraw_jpeg", forbid)
    response = jxl_client.get("/image", params={"path": str(path)},
                              headers={"Accept": "image/jxl", "Range": "bytes=0-15"})
    assert response.status_code == 206
    assert response.content == original[:16]
    assert response.headers["content-type"] == "image/jxl"
    assert "Accept" in {v.strip() for v in response.headers["vary"].split(",")}


@pytest.mark.parametrize("accept", ["image/jxl", "*/*"])
def test_another_accounts_jxl_is_not_visible(tmp_path, seed_photos_prefix, jxl_client, monkeypatch, accept):
    from api import db_helpers
    alice = tmp_path / "alice"
    bob = tmp_path / "bob"
    alice.mkdir()
    bob.mkdir()
    paths = [alice / "a.jxl", bob / "b.jxl"]
    for path in paths:
        _jpegxl(path)
    seed_photos_prefix(str(tmp_path) + os.sep, [{"path": str(p), "filename": p.name} for p in paths])
    monkeypatch.setattr(db_helpers, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(db_helpers, "get_user_directories", lambda uid: [str(alice)] if uid == "alice" else [str(bob)])
    jxl_client.app.dependency_overrides[get_optional_user] = lambda: CurrentUser(user_id="alice", role="user")
    own = jxl_client.get("/image", params={"path": str(paths[0])}, headers={"Accept": accept})
    assert own.status_code == 200
    hidden = jxl_client.get("/image", params={"path": str(paths[1]), "fallback": "thumbnail"}, headers={"Accept": accept})
    assert hidden.status_code == 404


@pytest.mark.parametrize("fail_first", [False, True])
def test_concurrent_fallbacks_share_decode_and_retry_failures(
        tmp_path, seed_photos_prefix, jxl_client, monkeypatch, fail_first):
    import threading
    from concurrent.futures import Future
    from api.routers import thumbnails
    path = tmp_path / "shared.jxl"
    _jpegxl(path)
    stored = BytesIO()
    Image.new("RGB", (4, 6), (80, 100, 120)).save(stored, format="JPEG")
    seed_photos_prefix(str(tmp_path) + os.sep, [{"path": str(path), "filename": path.name, "thumbnail": stored.getvalue()}])
    thumbnails._convert_jpegxl_cached.cache_clear()
    started, joined, release = threading.Event(), threading.Event(), threading.Event()
    calls = []
    load = image_loading.open_nonraw_image
    def held_load(*args, **kwargs):
        calls.append(True)
        started.set()
        assert release.wait(5), "test failed to release decoder"
        if fail_first and len(calls) == 1:
            raise ValueError("synthetic decode failure")
        return load(*args, **kwargs)
    class ObservedFuture(Future):
        def result(self, *args, **kwargs):
            joined.set()
            return super().result(*args, **kwargs)
    monkeypatch.setattr(thumbnails, "Future", ObservedFuture)
    monkeypatch.setattr(image_loading, "open_nonraw_image", held_load)
    results, errors = [], []
    def request():
        try:
            results.append(jxl_client.get("/image", params={"path": str(path), "fallback": "thumbnail"}))
        except BaseException as error:
            errors.append(error)
    workers = [threading.Thread(target=request, daemon=True) for _ in range(2)]
    try:
        workers[0].start()
        assert started.wait(3)
        workers[1].start()
        assert joined.wait(3), "second request did not join the first decode"
    finally:
        release.set()
        for worker in workers:
            if worker.ident is not None:
                worker.join(5)
    assert not errors and all(not w.is_alive() for w in workers)
    assert len(calls) == 1
    assert len(results) == 2 and all(r.status_code == 200 for r in results)
    assert results[0].content == results[1].content
    assert not thumbnails._render_inflight
    if fail_first:
        assert results[0].content == stored.getvalue()
        retry = jxl_client.get("/image", params={"path": str(path)})
        assert retry.status_code == 200 and len(calls) == 2
        assert Image.open(BytesIO(retry.content)).size == (40, 24)
    else:
        assert Image.open(BytesIO(results[0].content)).size == (40, 24)
        assert jxl_client.get("/image", params={"path": str(path)}).content == results[0].content
        assert len(calls) == 1
    thumbnails._convert_jpegxl_cached.cache_clear()


def test_fallback_timeout_releases_budget_and_is_retryable(tmp_path, seed_photos_prefix, jxl_client, monkeypatch):
    import threading
    from api.routers import thumbnails
    path = tmp_path / "busy.jxl"
    _jpegxl(path)
    stored = BytesIO()
    Image.new("RGB", (4, 6)).save(stored, format="JPEG")
    seed_photos_prefix(str(tmp_path) + os.sep, [{"path": str(path), "filename": path.name, "thumbnail": stored.getvalue()}])
    thumbnails._convert_jpegxl_cached.cache_clear()
    nonjpeg = threading.BoundedSemaphore(3)
    slots = threading.BoundedSemaphore(0)
    monkeypatch.setattr(thumbnails, "_nonjpeg_render_slots", nonjpeg)
    monkeypatch.setattr(thumbnails, "_render_slots", slots)
    monkeypatch.setattr(thumbnails, "_RENDER_WAIT_SECONDS", 0)
    load = image_loading.open_nonraw_image
    called = []
    def observed(*args, **kwargs):
        called.append(True)
        return load(*args, **kwargs)
    monkeypatch.setattr(image_loading, "open_nonraw_image", observed)
    response = jxl_client.get("/image", params={"path": str(path), "fallback": "thumbnail"})
    assert response.content == stored.getvalue() and response.status_code == 200
    assert called == [] and not thumbnails._render_inflight
    assert all(nonjpeg.acquire(blocking=False) for _ in range(3))
    for _ in range(3):
        nonjpeg.release()
    monkeypatch.setattr(thumbnails, "_render_slots", threading.BoundedSemaphore(4))
    retry = jxl_client.get("/image", params={"path": str(path)})
    assert retry.status_code == 200 and len(called) == 1
    assert Image.open(BytesIO(retry.content)).size == (40, 24)
    thumbnails._convert_jpegxl_cached.cache_clear()


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("tiff_offset", [0, 8])
def test_native_codestream_orientation_wins_and_exif_survives(tmp_path, compressed, tiff_offset):
    import struct
    path = tmp_path / "native-metadata.jxl"
    pixels = np.zeros((24, 40, 3), dtype=np.uint8)
    pixels[:, :20] = (240, 20, 10)
    pixels[:, 20:] = (10, 40, 230)
    raw = imagecodecs.jpegxl_encode(pixels, lossless=True, numthreads=1)
    exif = Image.Exif()
    exif[274] = 6  # Native pixels follow the codestream, not this TIFF hint.
    exif[34665] = {36867: "2024:01:13 11:36:39"}
    payload = struct.pack(">I", tiff_offset) + b"\x00" * tiff_offset + exif.tobytes()[6:]
    def box(kind, data):
        return struct.pack(">I4s", len(data) + 8, kind) + data
    metadata = box(b"brob", b"Exif" + imagecodecs.brotli_encode(payload)) if compressed else box(b"Exif", payload)
    signature = b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a"
    path.write_bytes(signature + box(b"ftyp", b"jxl \x00\x00\x00\x00jxl ") + metadata + box(b"jxlc", raw))
    original = path.read_bytes()
    actual = image_loading.open_nonraw_image(path)
    assert actual.size == (40, 24)
    np.testing.assert_array_equal(np.asarray(actual), pixels)
    assert actual.getexif().get_ifd(34665)[36867] == "2024:01:13 11:36:39"
    assert path.read_bytes() == original


def test_full_jxl_conversions_reserve_a_slot_for_sharp_jpegs(tmp_path, seed_photos_prefix, jxl_client, monkeypatch):
    import threading
    from api.routers import thumbnails
    paths = [tmp_path / f"held-{index}.jxl" for index in range(4)]
    jpeg = tmp_path / "ready.jpg"
    for path in paths:
        original = _jpegxl(path)
    jpeg.write_bytes(original)
    stored = BytesIO()
    Image.new("RGB", (4, 6)).save(stored, format="JPEG")
    seed_photos_prefix(str(tmp_path) + os.sep, [
        {"path": str(p), "filename": p.name, "thumbnail": stored.getvalue()} for p in [*paths, jpeg]])
    thumbnails._convert_jpegxl_cached.cache_clear()
    fourth_attempt, three_entered, release = threading.Event(), threading.Event(), threading.Event()
    guard = threading.Lock()
    attempts, entered = [], []
    class ObservedBudget(threading.BoundedSemaphore):
        def acquire(self, *args, **kwargs):
            with guard:
                attempts.append(True)
                if len(attempts) == 4:
                    fourth_attempt.set()
            return super().acquire(*args, **kwargs)
    load = image_loading.open_nonraw_image
    def held_load(path, *args, **kwargs):
        if str(path).endswith(".jxl"):
            with guard:
                entered.append(True)
                if len(entered) == 3:
                    three_entered.set()
            assert release.wait(5), "test did not release full decodes"
        return load(path, *args, **kwargs)
    monkeypatch.setattr(thumbnails, "_nonjpeg_render_slots", ObservedBudget(3))
    monkeypatch.setattr(thumbnails, "_render_slots", threading.BoundedSemaphore(4))
    monkeypatch.setattr(image_loading, "open_nonraw_image", held_load)
    results, errors = [], []
    def request(path):
        try:
            results.append(jxl_client.get("/image", params={"path": str(path)}))
        except BaseException as error:
            errors.append(error)
    workers = [threading.Thread(target=request, args=(path,), daemon=True) for path in paths]
    try:
        for worker in workers:
            worker.start()
        assert fourth_attempt.wait(3) and three_entered.wait(3)
        assert len(entered) == 3
        response = jxl_client.get("/thumbnail", params={"path": str(jpeg), "size": 1920})
        assert response.status_code == 200
        assert Image.open(BytesIO(response.content)).size == (40, 24)
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
    assert not errors and len(results) == 4 and all(r.status_code == 200 for r in results)
    assert all(not worker.is_alive() for worker in workers)
    assert len(entered) == 4 and not thumbnails._render_inflight
    thumbnails._convert_jpegxl_cached.cache_clear()


@pytest.mark.parametrize("compressed", [False, True])
def test_plugin_written_native_exif_is_preserved(tmp_path, compressed):
    path = tmp_path / "plugin-metadata.jxl"
    exif = Image.Exif()
    exif[274] = 1
    exif[34665] = {36867: "2024:01:13 11:36:39"}
    _native_jpegxl(path, np.full((24, 40, 3), [10, 80, 200], dtype=np.uint8),
                   exif=exif, compressed=compressed, bare_tiff=True)
    original = path.read_bytes()
    actual = image_loading.open_nonraw_image(path)
    assert actual.size == (40, 24)
    assert actual.getexif().get_ifd(34665)[36867] == "2024:01:13 11:36:39"
    assert path.read_bytes() == original


def test_metadata_reads_are_lazy_without_the_gpl_plugin(tmp_path, monkeypatch):
    import sys
    path = tmp_path / "metadata.jxl"
    _jpegxl(path)
    monkeypatch.setitem(sys.modules, "pillow_jxl", None)
    def forbidden(*args, **kwargs):
        raise AssertionError("metadata inspection must not decode pixels")
    monkeypatch.setattr(imagecodecs, "jpegxl_decode", forbidden)
    monkeypatch.setattr(imagecodecs, "jpegxl_decode_jpeg", forbidden)
    with Image.open(path) as image:
        assert image.size == (40, 24)
        assert image.getexif().get_ifd(34665)[36867] == "2024:01:13 11:36:39"


@pytest.mark.parametrize("depth", [1, 2, 4, 6, 7, 8, 10, 12, 16])
def test_integer_depth_uses_declared_range_not_brightest_pixel(tmp_path, depth):
    from utils.jpegxl_header import jpegxl_basic_info
    path = tmp_path / "depth.jxl"
    maximum = (1 << depth) - 1
    samples = np.array([[0, maximum // 4, maximum // 2]], dtype=np.uint8 if depth <= 8 else np.uint16)
    path.write_bytes(imagecodecs.jpegxl_encode(samples, lossless=True, bitspersample=depth, numthreads=1))
    with path.open("rb") as stream:
        actual_depth = jpegxl_basic_info(stream).bits_per_sample
    if actual_depth != depth:
        pytest.skip("this older encoder stores samples at the full dtype depth")
    actual = np.asarray(image_loading.open_nonraw_image(path))[:, :, 0]
    expected = np.floor(samples.astype(float) * 255 / maximum + .5).astype(np.uint8)
    np.testing.assert_array_equal(actual, expected)


def test_fixed_ten_bit_white_decodes_correctly_on_old_and_new_codecs(tmp_path):
    path = tmp_path / "ten-bit.jxl"
    path.write_bytes(bytes.fromhex('ff0a00101450b408080001002c004b188b15c259c11e80fe03'))
    assert image_loading.open_nonraw_image(path).getpixel((0, 0)) == (255, 255, 255)


def test_animation_reads_only_first_frame(tmp_path, monkeypatch):
    path = tmp_path / "animation.jxl"
    frames = np.zeros((2, 24, 40, 3), dtype=np.uint8)
    frames[0, :, :] = (255, 0, 0)
    frames[1, :, :] = (0, 0, 255)
    _native_jpegxl(path, frames)
    decoder = imagecodecs.jpegxl_decode
    calls = []
    def observed(data, *args, **kwargs):
        calls.append(kwargs.get('index'))
        return decoder(data, *args, **kwargs)
    monkeypatch.setattr(imagecodecs, "jpegxl_decode", observed)
    image = image_loading.open_nonraw_image(path)
    assert image.size == (40, 24) and image.getpixel((0, 0)) == (255, 0, 0)
    assert calls == [0]


@pytest.mark.parametrize("oversized", [False, True])
def test_bad_exif_does_not_discard_readable_pixels(tmp_path, monkeypatch, oversized):
    import struct
    from utils import jpegxl
    path = tmp_path / "bad-exif.jxl"
    pixels = np.full((24, 40, 3), [10, 80, 200], dtype=np.uint8)
    raw = imagecodecs.jpegxl_encode(pixels, lossless=True, numthreads=1)
    def box(kind, data):
        return struct.pack('>I4s', len(data) + 8, kind) + data
    if oversized:
        exif = Image.Exif()
        exif[270] = 'description ' * 100
        payload = b'\x00' * 4 + exif.tobytes()[6:]
        monkeypatch.setattr(jpegxl, '_MAX_EXIF_BYTES', 64)
    else:
        payload = b'\x00' * 4 + b'not TIFF'
    path.write_bytes(b'\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a'
                     + box(b'ftyp', b'jxl \x00\x00\x00\x00jxl ')
                     + box(b'Exif', payload) + box(b'jxlc', raw))
    original = path.read_bytes()
    image = image_loading.open_nonraw_image(path)
    np.testing.assert_array_equal(np.asarray(image), pixels)
    assert not image.getexif()
    assert path.read_bytes() == original


@pytest.mark.parametrize("format_name,extension", [('TIFF', '.tiff'), ('HEIF', '.heif')])
def test_existing_non_jxl_conversions_do_not_wait_for_jxl_slots(
        tmp_path, seed_photos_prefix, jxl_client, monkeypatch, format_name, extension):
    import threading
    from api.routers import thumbnails
    if format_name == 'HEIF' and not image_loading._heif_available:
        pytest.skip('HEIF codec unavailable')
    path = tmp_path / ('existing' + extension)
    Image.new('RGB', (40, 24), (10, 80, 200)).save(path, format=format_name)
    seed_photos_prefix(str(tmp_path) + os.sep, [{'path': str(path), 'filename': path.name}])
    thumbnails._convert_nonraw_cached.cache_clear()
    monkeypatch.setattr(thumbnails, '_render_slots', threading.BoundedSemaphore(0))
    monkeypatch.setattr(thumbnails, '_nonjpeg_render_slots', threading.BoundedSemaphore(0))
    monkeypatch.setattr(thumbnails, '_RENDER_WAIT_SECONDS', 0)
    response = jxl_client.get('/image', params={'path': str(path)})
    assert response.status_code == 200
    assert Image.open(BytesIO(response.content)).size == (40, 24)
    assert thumbnails._convert_nonraw_cached.cache_info().maxsize == 32
    thumbnails._convert_nonraw_cached.cache_clear()



def test_lazy_decode_rechecks_changed_stream_before_native_allocation(monkeypatch):
    small = imagecodecs.jpegxl_encode(np.zeros((8, 8, 3), dtype=np.uint8), lossless=True, numthreads=1)
    larger = imagecodecs.jpegxl_encode(np.zeros((24, 40, 3), dtype=np.uint8), lossless=True, numthreads=1)
    stream = BytesIO(small)
    image = Image.open(stream)
    stream.seek(0)
    stream.write(larger)
    stream.truncate()
    def forbidden(*args, **kwargs):
        raise AssertionError("changed oversized stream reached native allocation")
    monkeypatch.setattr(imagecodecs, "jpegxl_decode", forbidden)
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 100)
    try:
        with pytest.raises(ValueError, match='MAX_IMAGE_PIXELS'):
            image.load()
    finally:
        image.close()


def test_truncated_exif_after_codestream_keeps_readable_pixels():
    import struct
    pixels = np.full((8, 12, 3), [10, 80, 200], dtype=np.uint8)
    raw = imagecodecs.jpegxl_encode(pixels, lossless=True, numthreads=1)
    def box(kind, data):
        return struct.pack('>I4s', len(data) + 8, kind) + data
    payload = (b'\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a'
               + box(b'ftyp', b'jxl \x00\x00\x00\x00jxl ') + box(b'jxlc', raw)
               + struct.pack('>I4s', 1000, b'Exif') + b'broken')
    with Image.open(BytesIO(payload)) as image:
        image.load()
        np.testing.assert_array_equal(np.asarray(image), pixels)
        assert not image.getexif()
