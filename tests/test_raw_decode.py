"""RAW decode profiles: faithful metrics demosaic vs camera-preview display.

LibRaw's ``no_auto_bright``/``adjust_maximum_thr`` defaults are per-frame
adaptive terms that rescale every frame until it clips at the same place, so a
bracket rendered through them comes out equalised and the exposure ladder the
scoring engine measures is gone. These tests pin the two profiles apart: the
metrics profile every score is computed from, and the display profile the
stored thumbnail and the viewer show — which must never redefine the pixel
space stored face boxes live in.
"""

import io
import sys
import threading
import types

import numpy as np
import pytest
from PIL import Image, ImageOps

from config import ScoringConfig
from utils import image_loading
from utils.image_loading import (
    BRACKETED_SEQUENCE_KINDS,
    FAITHFUL_BRIGHT,
    configure_raw_decode_profile,
    configure_raw_decoding,
    extract_raw_preview,
    load_display_image,
    load_image_from_path,
    raw_postprocess_kwargs,
    renders_faithfully,
    thumbnail_source,
)

DEMOSAIC_SIZE = (2000, 1500)
BIG_PREVIEW_SIZE = (1960, 1470)
SMALL_PREVIEW_SIZE = (320, 240)


@pytest.fixture(autouse=True)
def _reset_decode_profile():
    yield
    image_loading._raw_decode_settings = None
    image_loading._viewer_semaphore = None
    configure_raw_decoding(concurrency=image_loading._auto_decode_concurrency(),
                           timeout_seconds=0)


def _jpeg_bytes(size, colour=90):
    buf = io.BytesIO()
    Image.new('RGB', size, (colour, colour, colour)).save(buf, format='JPEG')
    return buf.getvalue()


class _StubRaw:
    def __init__(self, thumb, flip=0):
        self._thumb = thumb
        self.sizes = types.SimpleNamespace(
            width=DEMOSAIC_SIZE[0], height=DEMOSAIC_SIZE[1], flip=flip)
        self.postprocess_kwargs = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_thumb(self):
        if isinstance(self._thumb, Exception):
            raise self._thumb
        return self._thumb

    def postprocess(self, **kwargs):
        self.postprocess_kwargs = kwargs
        return np.zeros((DEMOSAIC_SIZE[1], DEMOSAIC_SIZE[0], 3), dtype=np.uint8)


def _install_stub_rawpy(monkeypatch, thumb, flip=0):
    """Register a rawpy stand-in and return the raw object every imread yields."""
    raw = _StubRaw(thumb, flip=flip)
    stub = types.ModuleType("rawpy")
    stub.imread = lambda path: raw
    stub.ThumbFormat = types.SimpleNamespace(JPEG="jpeg", BITMAP="bitmap")
    stub.ColorSpace = types.SimpleNamespace(sRGB="srgb")
    monkeypatch.setitem(sys.modules, "rawpy", stub)
    monkeypatch.setattr(image_loading, "_decode_timeout", 0.0)
    return raw


def _jpeg_thumb(size):
    return types.SimpleNamespace(format="jpeg", data=_jpeg_bytes(size))


def _raw_file(tmp_path, name="shot.cr3"):
    path = tmp_path / name
    path.write_bytes(b"fake")
    return str(path)


class TestMetricsProfile:
    def test_disables_every_per_frame_adaptive_term(self, monkeypatch):
        _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile({'bright': 1.62})

        kwargs = raw_postprocess_kwargs()

        assert kwargs['no_auto_bright'] is True
        assert kwargs['adjust_maximum_thr'] == 0.0
        assert kwargs['use_camera_wb'] is True
        assert kwargs['bright'] == 1.62

    def test_configured_bright_reaches_the_decode(self, monkeypatch, tmp_path):
        raw = _install_stub_rawpy(monkeypatch, RuntimeError("no thumb"))
        configure_raw_decode_profile({'bright': 1.2})

        load_image_from_path(_raw_file(tmp_path))

        assert raw.postprocess_kwargs['bright'] == 1.2
        assert raw.postprocess_kwargs['no_auto_bright'] is True
        assert raw.postprocess_kwargs['adjust_maximum_thr'] == 0.0

    def test_auto_bright_restores_the_pre_fix_rendering(self, monkeypatch):
        _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile({'bright': 1.62})

        kwargs = raw_postprocess_kwargs(auto_bright=True)

        assert kwargs['no_auto_bright'] is False
        assert kwargs['adjust_maximum_thr'] == 0.75
        assert kwargs['bright'] == 1.0


class TestDisplayImage:
    def test_prefers_the_camera_preview(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile()

        assert load_display_image(_raw_file(tmp_path)).size == BIG_PREVIEW_SIZE

    def test_falls_back_when_the_preview_is_too_small(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch, _jpeg_thumb(SMALL_PREVIEW_SIZE))
        configure_raw_decode_profile()

        assert load_display_image(_raw_file(tmp_path)).size == DEMOSAIC_SIZE

    def test_falls_back_when_the_codec_is_unsupported(self, monkeypatch, tmp_path):
        """Recent Canon CR3 embed an H.265 preview LibRaw refuses to unpack."""
        _install_stub_rawpy(monkeypatch, RuntimeError("unsupported thumbnail"))
        configure_raw_decode_profile()

        assert load_display_image(_raw_file(tmp_path)).size == DEMOSAIC_SIZE

    def test_falls_back_when_the_preview_bytes_are_corrupt(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch, types.SimpleNamespace(format="jpeg", data=b"nope"))
        configure_raw_decode_profile()

        assert load_display_image(_raw_file(tmp_path)).size == DEMOSAIC_SIZE

    def test_accepts_a_bitmap_preview(self, monkeypatch, tmp_path):
        bitmap = np.full((BIG_PREVIEW_SIZE[1], BIG_PREVIEW_SIZE[0], 3), 80, dtype=np.uint8)
        _install_stub_rawpy(monkeypatch,
                            types.SimpleNamespace(format="bitmap", data=bitmap))
        configure_raw_decode_profile()

        assert load_display_image(_raw_file(tmp_path)).size == BIG_PREVIEW_SIZE

    def test_preference_can_be_turned_off(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile({'prefer_embedded_preview': False})

        assert load_display_image(_raw_file(tmp_path)).size == DEMOSAIC_SIZE

    def test_sensor_ratio_gate_rejects_a_partial_preview(self, monkeypatch, tmp_path):
        """The /image endpoint demosaics rather than upscale a small preview."""
        _install_stub_rawpy(monkeypatch, _jpeg_thumb((800, 600)))
        configure_raw_decode_profile()
        path = _raw_file(tmp_path)

        assert load_display_image(path, min_preview_sensor_ratio=0.5).size == DEMOSAIC_SIZE
        assert load_display_image(path).size == (800, 600)

    def test_non_raw_is_loaded_upright_and_rgb(self, tmp_path):
        path = tmp_path / "shot.jpg"
        Image.new('L', (120, 80), 60).save(path)

        img = load_display_image(str(path))

        assert img.mode == 'RGB'
        assert img.size == (120, 80)

    def test_missing_file_returns_none(self, tmp_path):
        assert load_display_image(str(tmp_path / "gone.cr3")) is None


class TestBracketedFramesRenderUncorrected:
    """A bracket exists to capture highlight headroom in its +EV frames, and
    both display corrections compress highlights: the preview through the
    camera's tone curve, the demosaic through the uniform ``bright`` gain. A
    bracketed frame therefore gets neither."""

    def test_a_bracket_ignores_the_preview_and_demosaics_with_no_gain(self, monkeypatch, tmp_path):
        raw = _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile()

        img = load_display_image(_raw_file(tmp_path), min_preview_sensor_ratio=0.5,
                                 sequence_kind='bracket')

        assert img.size == DEMOSAIC_SIZE
        assert raw.postprocess_kwargs['bright'] == FAITHFUL_BRIGHT

    def test_an_hdr_panorama_is_bracketed_at_every_position(self, monkeypatch, tmp_path):
        raw = _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile()

        img = load_display_image(_raw_file(tmp_path), sequence_kind='hdr_panorama')

        assert img.size == DEMOSAIC_SIZE
        assert raw.postprocess_kwargs['bright'] == FAITHFUL_BRIGHT

    def test_a_plain_panorama_is_not_bracketed(self, monkeypatch, tmp_path):
        """Stitched frames share one exposure — there is no ladder to protect."""
        raw = _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile()

        img = load_display_image(_raw_file(tmp_path), sequence_kind='panorama')

        assert img.size == BIG_PREVIEW_SIZE
        assert raw.postprocess_kwargs is None

    def test_a_photo_in_no_set_keeps_the_display_path(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile()

        assert load_display_image(_raw_file(tmp_path)).size == BIG_PREVIEW_SIZE

    def test_the_behaviour_can_be_turned_off(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile({'faithful_bracket_render': False})

        assert load_display_image(_raw_file(tmp_path), sequence_kind='bracket').size \
            == BIG_PREVIEW_SIZE

    def test_the_uncorrected_render_still_disables_every_adaptive_term(self, monkeypatch, tmp_path):
        """No gain must not be confused with LibRaw's own auto-brightness."""
        raw = _install_stub_rawpy(monkeypatch, RuntimeError("no thumb"))
        configure_raw_decode_profile()

        load_display_image(_raw_file(tmp_path), sequence_kind='bracket')

        assert raw.postprocess_kwargs['no_auto_bright'] is True
        assert raw.postprocess_kwargs['adjust_maximum_thr'] == 0.0
        assert raw.postprocess_kwargs['use_camera_wb'] is True

    def test_the_kinds_match_the_detection_passes_that_write_them(self):
        """Pinned so a rename in either pass cannot silently drop a kind here."""
        from utils.panorama import HDR_PANORAMA, PANORAMA
        from utils.sequence import BRACKET

        assert BRACKETED_SEQUENCE_KINDS == {BRACKET, HDR_PANORAMA}
        assert PANORAMA not in BRACKETED_SEQUENCE_KINDS

    def test_the_metrics_decode_keeps_the_configured_gain(self, monkeypatch, tmp_path):
        """The scoring pixel space must not follow a display decision."""
        raw = _install_stub_rawpy(monkeypatch, RuntimeError("no thumb"))
        configure_raw_decode_profile({'bright': 1.62})
        path = _raw_file(tmp_path)

        load_display_image(path, sequence_kind='bracket')
        assert raw.postprocess_kwargs['bright'] == FAITHFUL_BRIGHT

        pil_img, _ = load_image_from_path(path)

        assert raw.postprocess_kwargs['bright'] == 1.62
        assert pil_img.size == DEMOSAIC_SIZE

    def test_the_predicate_reads_the_config_at_call_time(self):
        configure_raw_decode_profile()
        assert renders_faithfully('bracket') is True
        assert renders_faithfully('panorama') is False
        assert renders_faithfully(None) is False


class TestFaceDetectionSpaceIsUnchanged:
    """``load_image_from_path`` must keep returning the demosaic.

    Stored face boxes and ``image_width``/``image_height`` index that array, so
    a preview-sourced buffer reaching it silently moves every box.
    """

    def test_metrics_loader_ignores_the_preview(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile()
        path = _raw_file(tmp_path)

        pil_img, img_cv = load_image_from_path(path)

        assert pil_img.size == DEMOSAIC_SIZE
        assert img_cv.shape[:2] == (DEMOSAIC_SIZE[1], DEMOSAIC_SIZE[0])
        assert load_display_image(path).size != pil_img.size


class TestThumbnailSource:
    def test_raw_thumbnail_comes_from_the_preview(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch, _jpeg_thumb(BIG_PREVIEW_SIZE))
        configure_raw_decode_profile()
        decoded = Image.new('RGB', DEMOSAIC_SIZE)

        assert thumbnail_source(_raw_file(tmp_path), decoded).size == BIG_PREVIEW_SIZE

    def test_preview_less_raw_reuses_the_decode_it_was_given(self, monkeypatch, tmp_path):
        """Never pay for a second demosaic just to build a thumbnail."""
        raw = _install_stub_rawpy(monkeypatch, RuntimeError("no thumb"))
        configure_raw_decode_profile()
        decoded = Image.new('RGB', DEMOSAIC_SIZE)

        assert thumbnail_source(_raw_file(tmp_path), decoded) is decoded
        assert raw.postprocess_kwargs is None

    def test_non_raw_reuses_the_decode_it_was_given(self, tmp_path):
        decoded = Image.new('RGB', (10, 10))

        assert thumbnail_source(str(tmp_path / "shot.jpg"), decoded) is decoded


class TestPreviewOrientation:
    """``unpack_thumb`` rotates nothing, and some previews carry no EXIF."""

    @pytest.mark.parametrize("exif_orientation,libraw_flip", [(1, 0), (3, 3), (6, 6), (8, 5)])
    def test_host_flip_matches_the_exif_rotation(self, exif_orientation, libraw_flip):
        arr = np.zeros((60, 100, 3), dtype=np.uint8)
        arr[:10, :20] = 255
        buf = io.BytesIO()
        source = Image.fromarray(arr)
        exif = source.getexif()
        exif[274] = exif_orientation
        source.save(buf, format='JPEG', exif=exif, quality=100)
        tagged = Image.open(buf)
        tagged.load()

        by_exif = ImageOps.exif_transpose(tagged)
        by_flip = image_loading._upright_preview(Image.fromarray(np.asarray(tagged)),
                                                 libraw_flip)

        assert by_flip.size == by_exif.size
        assert np.array_equal(np.asarray(by_flip), np.asarray(by_exif))

    def test_preview_without_exif_follows_the_host_file(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch,
                            types.SimpleNamespace(format="bitmap",
                                                  data=np.zeros((1470, 1960, 3), dtype=np.uint8)),
                            flip=6)

        assert extract_raw_preview(_raw_file(tmp_path)).size == (1470, 1960)


class TestDefaultsMatchTheShippedConfig:
    """A fallback that drifts from the shipped config renders a second library
    differently from the first."""

    def test_fallback_matches_documented_defaults(self, tmp_path):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text('{"categories": [{"name": "default", "priority": 999, "filters": {}}]}')

        settings = ScoringConfig(config_path=str(config_path), validate=False).get_raw_decode_settings()

        assert settings == {'bright': 1.62, 'prefer_embedded_preview': True,
                            'preview_min_sensor_ratio': 0.5, 'viewer_concurrency': 3,
                            'faithful_bracket_render': True}

    def test_shipped_config_matches_the_fallback(self):
        assert ScoringConfig(validate=False).get_raw_decode_settings() == {
            'bright': 1.62, 'prefer_embedded_preview': True,
            'preview_min_sensor_ratio': 0.5, 'viewer_concurrency': 3,
            'faithful_bracket_render': True}


class TestViewerDecodeBudget:
    """The /image path draws from its own semaphore so a viewer request never
    queues behind a scan or CLI job holding the library one."""

    def test_viewer_and_library_semaphores_are_independent_objects(self):
        configure_raw_decoding(concurrency=2)

        assert image_loading._get_viewer_semaphore() is not image_loading._raw_semaphore

    def test_viewer_budget_is_sized_from_config(self):
        configure_raw_decode_profile({'viewer_concurrency': 5})
        image_loading._viewer_semaphore = None

        assert image_loading._get_viewer_semaphore()._value == 5

    def test_configure_raw_decoding_rebuilds_both_budgets(self):
        old_library = image_loading._raw_semaphore
        old_viewer = image_loading._get_viewer_semaphore()

        configure_raw_decoding(concurrency=2)

        assert image_loading._raw_semaphore is not old_library
        assert image_loading._raw_semaphore._value == 2
        assert image_loading._viewer_semaphore is not old_viewer

    def test_convert_rawpy_uses_the_viewer_budget(self, monkeypatch, tmp_path):
        from api import raw_processing

        captured = {}

        def fake_load_display_image(path, min_preview_sensor_ratio=0.0, decode_budget='library',
                                    sequence_kind=None):
            captured['decode_budget'] = decode_budget
            return Image.new('RGB', (4, 4))

        monkeypatch.setattr(image_loading, 'load_display_image', fake_load_display_image)

        raw_processing._convert_rawpy(str(tmp_path / "shot.cr3"), 90)

        assert captured['decode_budget'] == 'viewer'

    def test_facet_style_callers_default_to_the_library_budget(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch, RuntimeError("no thumb"))
        configure_raw_decode_profile()
        recorded = {}
        real_decode_raw = image_loading._decode_raw

        def spy(photo, use_thumbnail, started_event=None, decode_budget='library', bright=None):
            recorded['decode_budget'] = decode_budget
            return real_decode_raw(photo, use_thumbnail, started_event, decode_budget, bright)

        monkeypatch.setattr(image_loading, '_decode_raw', spy)

        load_display_image(_raw_file(tmp_path))

        assert recorded['decode_budget'] == 'library'

    def test_viewer_decode_proceeds_while_the_library_semaphore_is_saturated(self, monkeypatch, tmp_path):
        _install_stub_rawpy(monkeypatch, RuntimeError("no thumb"))
        configure_raw_decode_profile()
        configure_raw_decoding(concurrency=1)
        image_loading._raw_semaphore.acquire()
        try:
            result = {}

            def run():
                result['img'] = load_display_image(_raw_file(tmp_path), decode_budget='viewer')

            t = threading.Thread(target=run)
            t.start()
            t.join(timeout=5)

            assert not t.is_alive(), "viewer decode blocked behind the saturated library semaphore"
            assert result['img'] is not None
        finally:
            image_loading._raw_semaphore.release()


class _StubRowDb:
    """Minimal ``get_db()`` stand-in returning one fixed photo row."""

    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *_args):
        return types.SimpleNamespace(fetchone=lambda: self.row)


class TestEverySurfaceAgrees:
    """Every surface that renders a RAW must render a bracket the same way, so
    the sequence kind has to reach ``/image``, ``--refresh-thumbnails`` and the
    download alike. Sequence detection runs after a scan, so none of them can be
    replaced by doing this at scan time."""

    def test_the_image_endpoint_renders_with_the_rows_sequence_kind(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from api import create_app

        raw_file = tmp_path / 'frame.CR3'
        raw_file.write_bytes(b'raw')
        seen = {}

        def _record(path, mtime, quality, sequence_kind):
            seen['sequence_kind'] = sequence_kind
            return b'jpeg-payload'

        monkeypatch.setattr('api.routers.thumbnails._convert_raw_cached', _record)
        monkeypatch.setattr('api.routers.thumbnails.resolve_photo_disk_path',
                            lambda p: str(raw_file))
        monkeypatch.setattr('api.routers.thumbnails.get_db',
                            lambda: _StubRowDb({'path': str(raw_file),
                                                'sequence_kind': 'bracket'}))

        response = TestClient(create_app()).get('/image', params={'path': str(raw_file)})

        assert response.status_code == 200
        assert response.content == b'jpeg-payload'
        assert seen['sequence_kind'] == 'bracket'

    def test_the_conversion_cache_is_keyed_on_the_sequence_kind(self, monkeypatch, tmp_path):
        """A frame relabelled by a later detection pass must not keep serving
        the preview render cached before it."""
        from api.routers import thumbnails

        calls = []
        monkeypatch.setattr('api.raw_processing.convert_raw_to_jpeg',
                            lambda p, q, kind: calls.append(kind) or b'jpeg')
        thumbnails._convert_raw_cached.cache_clear()

        thumbnails._convert_raw_cached('/disk/frame.CR3', 1.0, 96, None)
        thumbnails._convert_raw_cached('/disk/frame.CR3', 1.0, 96, 'bracket')
        thumbnails._convert_raw_cached('/disk/frame.CR3', 1.0, 96, 'bracket')

        assert calls == [None, 'bracket']
        thumbnails._convert_raw_cached.cache_clear()

    def test_the_cli_refresh_renders_each_row_with_its_own_sequence_kind(
            self, monkeypatch, tmp_path):
        import sqlite3

        import facet
        from db.schema import init_database

        db_path = str(tmp_path / 'library.db')
        init_database(db_path)
        conn = sqlite3.connect(db_path)
        conn.executemany(
            "INSERT INTO photos (path, filename, sequence_kind) VALUES (?, ?, ?)",
            [('/photos/a.CR2', 'a.CR2', 'bracket'),
             ('/photos/b.CR2', 'b.CR2', None),
             ('/photos/c.CR2', 'c.CR2', 'panorama')])
        conn.commit()
        conn.close()

        seen = {}

        def _record(path, size, quality, sequence_kind):
            seen[path] = sequence_kind
            return b'thumb'

        monkeypatch.setattr(facet, '_display_thumbnail_bytes', _record)

        facet.refresh_thumbnails(db_path, ScoringConfig(validate=False), workers=2)

        assert seen == {'/photos/a.CR2': 'bracket', '/photos/b.CR2': None,
                        '/photos/c.CR2': 'panorama'}

    def test_the_download_resolver_returns_the_rows_sequence_kind(self, monkeypatch):
        """Folded into the visibility query the download already runs, so the
        rendering decision costs no extra round trip."""
        from api.routers import comparison

        queried = {}

        class _Db:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params):
                queried['sql'] = sql
                return types.SimpleNamespace(
                    fetchone=lambda: {'path': '/photos/a.CR2', 'sequence_kind': 'bracket'})

        monkeypatch.setattr(comparison, 'get_db', _Db)
        monkeypatch.setattr(comparison, 'get_visibility_clause', lambda uid: ('1=1', []))
        monkeypatch.setattr(comparison, 'resolve_photo_disk_path', lambda p: '/disk/a.CR2')

        db_path, real_disk, kind = comparison._validate_and_resolve('/photos/a.CR2', None)

        assert (db_path, real_disk, kind) == ('/photos/a.CR2', '/disk/a.CR2', 'bracket')
        assert queried['sql'].count('SELECT') == 1

    @pytest.mark.parametrize("kind", ['bracket', 'hdr_panorama', 'panorama', None])
    def test_the_download_converts_with_the_rows_sequence_kind(self, monkeypatch, kind):
        """A downloaded bracket frame is on its way to an HDR merge, so it must
        carry the same uncorrected render the loupe showed."""
        from api.routers import comparison

        seen = {}

        def _record(path, quality, sequence_kind):
            seen['kind'] = sequence_kind
            return b'jpeg'

        monkeypatch.setattr('api.raw_processing.convert_raw_to_jpeg', _record)

        comparison._serve_original('/disk/a.CR2', '/photos/a.CR2', 96, kind)

        assert seen['kind'] == kind

