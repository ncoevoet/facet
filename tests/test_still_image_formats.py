"""Tests for PNG/GIF/WebP/BMP/TIFF/AVIF still-image format support (issue #152).

Ground truth for every fact cited in a comment here (Pillow decode behaviour,
mode names, the three decode-defect measurements) was verified in-session and
is recorded in ``.claude/specs/still-image-formats-findings.md`` and
``.claude/specs/still-image-format-support.md`` -- this module implements the
plan's Steps 1-10, it does not re-derive that investigation.

Every fixture below is generated on the fly with Pillow, or -- for the AVIF
``colr``/``nclx`` box -- hand-built as raw ``bytes``. Nothing is vendored
(the amended decision 9: not even the permissively-licensed PngSuite).

The AVIF ``colr``/``nclx`` true-positive parse path (Step 6) has NO possible
end-to-end coverage: Pillow's own AVIF encoder cannot write a CICP/``nclx``
colour box at all (confirmed in the findings doc), so a real HDR-PQ AVIF
fixture cannot be produced by round-tripping through Pillow. The
synthesized-bytes unit tests in ``TestAvifNclxParsing`` are therefore the
ONLY coverage for that path -- they are not redundant with the separate
end-to-end SDR-AVIF test beside them, which only proves the negative
(non-PQ) case.
"""

import struct
import mimetypes
import sys

import numpy as np
import pytest
from PIL import Image

from utils import image_loading


# ---------------------------------------------------------------------------
# Step 1 -- extension tables
# ---------------------------------------------------------------------------

class TestExtensionTables:
    def test_five_unconditional_formats_are_scannable(self):
        # PNG/GIF/WebP/BMP/TIFF decode with no optional Pillow plugin, so
        # unlike HEIF/AVIF none of these five is gated on availability.
        assert {'.png', '.gif', '.webp', '.bmp', '.tif', '.tiff'} <= image_loading.SCANNABLE_IMAGE_EXTENSIONS

    def test_avif_scannable_iff_decoder_available(self):
        if image_loading._avif_available:
            assert '.avif' in image_loading.AVIF_EXTENSIONS
            assert '.avif' in image_loading.SCANNABLE_IMAGE_EXTENSIONS
        else:
            assert image_loading.AVIF_EXTENSIONS == frozenset()
            assert '.avif' not in image_loading.SCANNABLE_IMAGE_EXTENSIONS

    def test_watchable_gains_the_five_unconditional_formats_plus_known_avif(self):
        # WATCHABLE uses KNOWN_AVIF_EXTENSIONS (the container set), never the
        # decoder-gated AVIF_EXTENSIONS: a filesystem event is only a note
        # that the path changed, and a library that later gains the AVIF
        # codec must still see .avif files it already holds.
        assert {'.png', '.gif', '.webp', '.bmp', '.tif', '.tiff', '.avif'} <= image_loading.WATCHABLE_IMAGE_EXTENSIONS
        assert image_loading.KNOWN_AVIF_EXTENSIONS <= image_loading.WATCHABLE_IMAGE_EXTENSIONS


# ---------------------------------------------------------------------------
# Step 1b -- RAW pairing stays JPEG+HEIF only (facet.py:1505 jpeg_like)
# ---------------------------------------------------------------------------

class _FakeFacet:
    """Mirrors tests/test_scan_interrupt.py's _FakeFacet: enough of Facet's
    surface for facet.main()'s file-collection/pairing logic to run without
    loading any real model."""

    def __init__(self, db_path=None, config_path=None, multi_pass=False):
        from config import ScoringConfig
        self.db_path = db_path
        self.config = ScoringConfig(config_path)
        self.model_manager = None

    def preflight_models(self):
        pass

    def filter_unscanned_paths(self, paths):
        return set(paths)

    def commit(self):
        pass


def _run_dry_scan(tmp_path, photo_dir, monkeypatch, processed):
    """Drive facet.main() in --dry-run over photo_dir, recording every
    filename process_single_photo was called with (i.e. survived RAW/JPEG
    pairing and the unscanned filter) into `processed`.

    Stubs out every heavy dependency the same way test_scan_interrupt.py
    does, so this exercises the REAL pairing predicate in facet.py's
    _run_scan (jpeg_like = JPEG_EXTENSIONS | HEIF_EXTENSIONS) against the
    real SCANNABLE_IMAGE_EXTENSIONS constants, without a GPU or any model.
    """
    import facet

    db_path = str(tmp_path / "scan.db")
    from db.schema import init_database
    init_database(db_path)

    def _fake_process_single_photo(photo_path, scorer):
        processed.append(photo_path.name)
        return (
            {'category': 'x', 'aesthetic': 1, 'comp_score': 1,
             'aggregate': 1, 'face_quality': 1},
            None,
        )

    monkeypatch.setattr("processing.scorer.Facet", _FakeFacet)
    monkeypatch.setattr("models.model_manager.ModelManager", lambda *a, **k: object())
    monkeypatch.setattr("plugins.init_global_plugin_manager", lambda *a, **k: None)
    monkeypatch.setattr("processing.scorer.process_single_photo", _fake_process_single_photo)
    monkeypatch.setattr(
        sys, "argv",
        ["facet.py", str(photo_dir), "--db", db_path, "--dry-run", "--dry-run-count", "10"],
    )

    with pytest.raises(SystemExit):
        facet.main()


class TestRawPairingStaysJpegHeifOnly:
    @pytest.mark.timeout(30)
    def test_raw_and_tif_sibling_both_scan(self, tmp_path, monkeypatch):
        # decision (this session): jpeg_like is NOT widened to include TIFF/PNG,
        # so a darktable/Lightroom "RAW + edited TIFF export" layout scans as
        # TWO photos rather than the TIFF silently suppressing the RAW.
        photo_dir = tmp_path / "photos_tif"
        photo_dir.mkdir()
        (photo_dir / "x.cr2").write_bytes(b"not a real raw -- pairing never decodes it")
        Image.new("RGB", (8, 8), (10, 20, 30)).save(photo_dir / "x.tif", "TIFF")

        processed = []
        _run_dry_scan(tmp_path, photo_dir, monkeypatch, processed)

        assert sorted(processed) == ["x.cr2", "x.tif"]

    @pytest.mark.timeout(30)
    def test_raw_and_jpg_sibling_still_suppresses_raw(self, tmp_path, monkeypatch):
        # Existing behaviour, unchanged: a sibling JPEG still suppresses the RAW.
        photo_dir = tmp_path / "photos_jpg"
        photo_dir.mkdir()
        (photo_dir / "y.cr2").write_bytes(b"not a real raw -- pairing never decodes it")
        Image.new("RGB", (8, 8), (1, 2, 3)).save(photo_dir / "y.jpg", "JPEG")

        processed = []
        _run_dry_scan(tmp_path, photo_dir, monkeypatch, processed)

        assert processed == ["y.jpg"]


# ---------------------------------------------------------------------------
# Step 2 -- alpha compositing over white
# ---------------------------------------------------------------------------

def _half_transparent_rgba(width=20, height=40):
    """Top half fully-transparent red, bottom half opaque blue -- the exact
    findings-doc probe shape (mirrored: findings doc used a wide image; the
    dimensions here don't matter, only top/bottom halves differing)."""
    arr = np.zeros((height, width, 4), dtype=np.uint8)
    arr[: height // 2, :, :] = [255, 0, 0, 0]
    arr[height // 2:, :, :] = [0, 0, 255, 255]
    return Image.fromarray(arr, 'RGBA')


class TestAlphaCompositedOverWhite:
    """BMP is deliberately excluded: Pillow's BMP writer drops alpha on save
    (verified -- an RGBA image saved as BMP reads back plain RGB), so there is
    no way to generate a BMP-with-alpha fixture and no BMP-alpha assertion
    should exist."""

    @pytest.mark.parametrize("fmt,ext,save_kwargs", [
        ("PNG", ".png", {}),
        ("WEBP", ".webp", {"lossless": True}),
        ("TIFF", ".tiff", {}),
        ("AVIF", ".avif", {}),
    ])
    def test_rgba_transparent_region_becomes_white(self, tmp_path, fmt, ext, save_kwargs):
        if fmt == "AVIF" and not image_loading._avif_available:
            pytest.skip("AVIF codec not available in this Pillow build")
        img = _half_transparent_rgba()
        path = tmp_path / f"alpha{ext}"
        img.save(path, fmt, **save_kwargs)

        out = image_loading.open_nonraw_image(path)
        arr = np.asarray(out)
        assert out.mode == 'RGB'
        assert tuple(arr[0, 0]) == (255, 255, 255)  # transparent red -> white
        # AVIF is lossy even at default quality, so allow a small compression
        # tolerance on the opaque region; every other format round-trips exactly.
        tol = 5 if fmt == "AVIF" else 0
        assert all(abs(int(c) - e) <= tol for c, e in zip(arr[-1, 0], (0, 0, 255)))

    def test_palette_gif_with_transparency_key_becomes_white(self, tmp_path):
        # split() on a palette image returns a 'P' band, not alpha (verified:
        # raises ValueError: bad transparency mask) -- this is the fixture
        # for the P + convert('RGBA') leg of the alpha-detection branch.
        # Index 0 must actually be USED by a pixel: Pillow's GIF palette
        # optimizer drops an unused index (and its transparency info) on save.
        pal_img = Image.new('P', (10, 10))
        palette = [0, 0, 0, 255, 0, 0, 0, 0, 255] + [0] * (768 - 9)
        pal_img.putpalette(palette)
        arr = np.zeros((10, 10), dtype=np.uint8)
        arr[:5, :] = 0   # index 0 -> will be marked transparent
        arr[5:, :] = 2   # index 2 -> blue
        pal_img.putdata(arr.flatten().tolist())
        path = tmp_path / "palette_alpha.gif"
        pal_img.save(path, transparency=0)

        reloaded = Image.open(path)
        assert reloaded.mode == 'P'
        assert reloaded.info.get('transparency') == 0

        out = image_loading.open_nonraw_image(path)
        out_arr = np.asarray(out)
        assert out.mode == 'RGB'
        assert tuple(out_arr[0, 0]) == (255, 255, 255)
        assert tuple(out_arr[-1, 0]) == (0, 0, 255)

    def test_alpha_mask_taken_after_exif_transpose_not_before(self, tmp_path):
        # BLOCKER 2 regression: an RGBA source carrying EXIF Orientation 6
        # changes SIZE through exif_transpose ((40, 20) -> (20, 40), verified).
        # A mask split from the PRE-transpose image no longer matches the
        # post-transpose image's size, and background.paste(mask=...) raises
        # ValueError: images do not match. Must not raise here.
        arr = np.zeros((20, 40, 4), dtype=np.uint8)
        arr[..., :3] = 100
        arr[..., 3] = 128
        img = Image.fromarray(arr, 'RGBA')
        exif = Image.Exif()
        exif[0x0112] = 6  # Orientation
        path = tmp_path / "oriented.webp"
        img.save(path, exif=exif, lossless=True)

        out = image_loading.open_nonraw_image(path)  # must not raise
        assert out.size == (20, 40)
        assert out.mode == 'RGB'


# ---------------------------------------------------------------------------
# Step 3 -- 16-bit / float single-channel scaling
# ---------------------------------------------------------------------------

class TestSixteenBitScaling:
    def test_le_png_and_be_tiff_scale_to_the_same_mean(self, tmp_path):
        # BLOCKER 1 regression: a bare point() RAISES ValueError on I;16B/
        # I;16L, so a verify naming only the I;16 (little-endian) PNG case
        # cannot fail on that defect. Both legs must be exercised.
        arr = np.linspace(0, 65535, 64 * 64, dtype=np.uint16).reshape(64, 64)

        png_path = tmp_path / "gray16le.png"
        Image.fromarray(arr).save(png_path)  # mode I;16
        assert Image.open(png_path).mode == 'I;16'

        tiff_path = tmp_path / "gray16be.tiff"
        be_img = Image.frombytes('I;16B', (64, 64), arr.astype('>u2').tobytes())
        be_img.save(tiff_path)
        assert Image.open(tiff_path).mode == 'I;16B'

        out_le = np.asarray(image_loading.open_nonraw_image(png_path))
        out_be = np.asarray(image_loading.open_nonraw_image(tiff_path))

        # Verified on Pillow 12.3.0: convert('I') + point(i * 1/256) +
        # convert('L') yields mean 127.50 on every 16-bit mode for a uint16
        # ramp of source mean 32767.5 -- not the ~254.5/clip-to-white the
        # unfixed convert('RGB') path produces.
        assert out_le.mean() == pytest.approx(127.5, abs=1.0)
        assert out_be.mean() == pytest.approx(127.5, abs=1.0)

    def test_findings_doc_measurement_mean_36970(self, tmp_path):
        # png/basn0g16.png-equivalent: source min/max/mean 0/65535/36970
        # decoded (pre-fix) to output mean 254.8 -- must now decode to a mean
        # proportional to 36970/257 =~ 143.9, not near-white.
        arr = np.full((32, 32), 36970, dtype=np.uint16)
        arr[0, 0] = 0
        arr[0, 1] = 65535
        path = tmp_path / "mean36970.png"
        Image.fromarray(arr).save(path)

        out = np.asarray(image_loading.open_nonraw_image(path))
        assert out.mean() == pytest.approx(143.9, abs=3.0)

    def test_findings_doc_measurement_near_white_not_saturated(self, tmp_path):
        # png/tbwn0g16.png-equivalent: source min/max/mean 2023/65535/44126
        # decoded (pre-fix) to output min/max/mean 255/255/255.0 -- solid
        # white. Must now decode to a mean scaled from 44126 (=~171), not
        # uniformly saturated.
        arr = np.full((32, 32), 44126, dtype=np.uint16)
        arr[0, 0] = 2023
        path = tmp_path / "near_white.png"
        Image.fromarray(arr).save(path)

        out = np.asarray(image_loading.open_nonraw_image(path))
        assert out.mean() == pytest.approx(171.0, abs=3.0)
        assert not np.all(out == 255)  # not uniformly saturated

    def test_i16b_point_would_raise_without_the_convert_i_hop(self, tmp_path):
        # Direct proof of the BLOCKER-1 mechanism this fix works around: a
        # bare point() call on I;16B raises. open_nonraw_image must not use it.
        arr = np.linspace(0, 65535, 64 * 64, dtype=np.uint16).reshape(64, 64)
        be_img = Image.frombytes('I;16B', (64, 64), arr.astype('>u2').tobytes())
        with pytest.raises(ValueError, match="point operation not supported"):
            be_img.point(lambda i: i * (1 / 256))

    def test_convert_i16_hop_would_silently_corrupt(self, tmp_path):
        # Direct proof of the NOTE-7 trap: normalising through convert('I;16')
        # instead of convert('I') yields mean 0.00, not a decode error --
        # documents why open_nonraw_image must use convert('I').
        arr = np.linspace(0, 65535, 64 * 64, dtype=np.uint16).reshape(64, 64)
        be_img = Image.frombytes('I;16B', (64, 64), arr.astype('>u2').tobytes())
        wrong = be_img.convert('I;16').point(lambda i: i * (1 / 256)).convert('L')
        assert np.asarray(wrong).mean() == pytest.approx(0.0, abs=1e-6)

    @pytest.mark.parametrize("arr,mode", [
        (np.full((16, 16), 200.0, dtype=np.float32), 'F'),
        (np.full((16, 16), 200, dtype=np.int32), 'I'),
    ])
    def test_thirty_two_bit_modes_are_not_scaled_down(self, tmp_path, arr, mode):
        # Review finding 1: including 'I'/'F' in the scale-down branch turned a
        # 32-bit TIFF whose samples already span 0..255 into solid black --
        # mean 0.00, no exception, so no scan_failures row and a black
        # thumbnail agreeing with black scored pixels. 32-bit modes keep
        # convert('RGB')'s clip.
        path = tmp_path / f"{mode}.tif"
        Image.fromarray(arr).save(path, format='TIFF')
        assert Image.open(path).mode == mode
        assert np.asarray(image_loading.open_nonraw_image(str(path))).mean() == pytest.approx(200.0, abs=0.5)

    @pytest.mark.parametrize("fmt,ext", [('PNG', '.png'), ('TIFF', '.tif')])
    def test_sixteen_bit_sources_never_open_as_a_thirty_two_bit_mode(self, tmp_path, fmt, ext):
        # The premise excluding 'I'/'F' above is only safe because a real
        # 16-bit source always lands in an I;16* mode. Pin that premise.
        path = tmp_path / f"g16{ext}"
        Image.frombytes('I;16', (16, 16), (np.ones((16, 16), dtype=np.uint16) * 32768).tobytes()).save(
            path, format=fmt)
        assert Image.open(path).mode in image_loading._SIXTEEN_BIT_MODES
        assert np.asarray(image_loading.open_nonraw_image(str(path))).mean() == pytest.approx(128.0, abs=0.5)


# ---------------------------------------------------------------------------
# Step 4 -- animated GIF/WebP: frame 0, silently
# ---------------------------------------------------------------------------

class TestAnimatedFramesScoreFrameZeroSilently:
    def test_animated_gif_decodes_frame_zero_no_warning(self, tmp_path, caplog):
        frame1 = Image.new('RGB', (10, 10), (255, 0, 0))
        frame2 = Image.new('RGB', (10, 10), (0, 0, 255))
        path = tmp_path / "anim.gif"
        frame1.save(path, save_all=True, append_images=[frame2])

        reloaded = Image.open(path)
        assert reloaded.n_frames == 2

        with caplog.at_level("WARNING"):
            out = image_loading.open_nonraw_image(path)
        assert not any(r.levelno >= 30 for r in caplog.records)
        assert out.mode == 'RGB'
        assert tuple(np.asarray(out)[5, 5]) == (255, 0, 0)  # frame 0, not frame 1

    def test_animated_webp_decodes_frame_zero_no_warning(self, tmp_path, caplog):
        frame1 = Image.new('RGB', (10, 10), (10, 20, 30))
        frame2 = Image.new('RGB', (10, 10), (200, 100, 50))
        path = tmp_path / "anim.webp"
        frame1.save(path, save_all=True, append_images=[frame2], lossless=True)

        reloaded = Image.open(path)
        assert reloaded.n_frames == 2

        with caplog.at_level("WARNING"):
            out = image_loading.open_nonraw_image(path)
        assert not any(r.levelno >= 30 for r in caplog.records)
        assert out.mode == 'RGB'
        assert tuple(np.asarray(out)[5, 5]) == (10, 20, 30)


# ---------------------------------------------------------------------------
# Step 5 -- no mtime fallback for date_taken/camera_model
# ---------------------------------------------------------------------------

class TestNoMtimeFallback:
    """processing/scorer.py:2221 Facet.get_exif_data has no mtime fallback and
    the locked decision is to add none. get_exif_data never reads `self`, so
    it's called unbound here rather than standing up a full Facet -- this is
    a regression guard against a future contributor "helpfully" adding one,
    not a defect fix (Step 5 makes no source change)."""

    @pytest.mark.parametrize("fmt,ext", [("PNG", ".png"), ("TIFF", ".tiff")])
    def test_no_exif_png_tiff_yields_null_date_and_camera(self, tmp_path, fmt, ext):
        from processing.scorer import Facet
        path = tmp_path / f"noexif{ext}"
        Image.new('RGB', (8, 8), (1, 2, 3)).save(path, fmt)

        result = Facet.get_exif_data(None, str(path))
        assert result['date_taken'] is None
        assert result['camera_model'] is None

    def test_no_exif_avif_yields_null_date_and_camera(self, tmp_path):
        if not image_loading._avif_available:
            pytest.skip("AVIF codec not available in this Pillow build")
        from processing.scorer import Facet
        path = tmp_path / "noexif.avif"
        Image.new('RGB', (8, 8), (1, 2, 3)).save(path, "AVIF")

        result = Facet.get_exif_data(None, str(path))
        assert result['date_taken'] is None
        assert result['camera_model'] is None


# ---------------------------------------------------------------------------
# Step 6 -- AVIF colr/nclx parsing and PQ tone mapping
# ---------------------------------------------------------------------------

def _bmff_box(box_type, payload):
    return struct.pack('>I4s', 8 + len(payload), box_type) + payload


def _bmff_fullbox(box_type, payload):
    return _bmff_box(box_type, struct.pack('>I', 0) + payload)


def _synthesize_avif_nclx(primaries, transfer, matrix, full_range=0):
    """Hand-build a minimal ftyp+meta/iprp/ipco/colr(nclx) ISO-BMFF byte string."""
    colr = _bmff_box(b'colr', b'nclx' + struct.pack('>HHH', primaries, transfer, matrix)
                     + bytes([full_range]))
    ipco = _bmff_box(b'ipco', colr)
    iprp = _bmff_box(b'iprp', ipco)
    meta = _bmff_fullbox(b'meta', iprp)
    ftyp = _bmff_box(b'ftyp', b'avif' + b'\x00' * 4 + b'avifmif1miaf')
    return ftyp + meta


class TestAvifNclxParsing:
    def test_pq_transfer_16_parses(self, tmp_path):
        path = tmp_path / "pq.bin"
        path.write_bytes(_synthesize_avif_nclx(9, 16, 9))
        assert image_loading._avif_nclx_transfer_characteristics(str(path)) == 16
        assert image_loading._avif_is_pq(str(path)) is True

    def test_srgb_transfer_13_parses_and_is_not_pq(self, tmp_path):
        path = tmp_path / "sdr.bin"
        path.write_bytes(_synthesize_avif_nclx(1, 13, 6))
        assert image_loading._avif_nclx_transfer_characteristics(str(path)) == 13
        assert image_loading._avif_is_pq(str(path)) is False

    def test_truncated_garbage_returns_none_without_raising(self, tmp_path):
        path = tmp_path / "garbage.bin"
        path.write_bytes(b'\x00\x00\x00\x04junk' + b'not a box tree at all, deliberately')
        assert image_loading._avif_nclx_transfer_characteristics(str(path)) is None

    def test_missing_file_returns_none_without_raising(self, tmp_path):
        assert image_loading._avif_nclx_transfer_characteristics(str(tmp_path / "nope.bin")) is None

    def test_empty_file_returns_none_without_raising(self, tmp_path):
        path = tmp_path / "empty.bin"
        path.write_bytes(b"")
        assert image_loading._avif_nclx_transfer_characteristics(str(path)) is None

    def test_bodyless_colr_does_not_read_into_the_next_box(self, tmp_path):
        # Review finding 4: a colr box declaring only header + 'nclx' with no
        # body let f.read(6) spill into the FOLLOWING box's header and return
        # its bytes as a transfer characteristic -- verified to yield 16, i.e.
        # the PQ tone map forced onto an SDR image. The read is now bounded by
        # the colr box's own end.
        bodyless_colr = struct.pack('>I4s', 12, b'colr') + b'nclx'
        next_box = struct.pack('>I4s', 16, b'free') + bytes(8)
        ipco = _bmff_box(b'ipco', bodyless_colr + next_box)
        blob = (_bmff_box(b'ftyp', b'avif' + b'\x00' * 4 + b'avifmif1miaf')
                + _bmff_fullbox(b'meta', _bmff_box(b'iprp', ipco)))
        path = tmp_path / "bodyless.bin"
        path.write_bytes(blob)
        assert image_loading._avif_nclx_transfer_characteristics(str(path)) is None
        assert image_loading._avif_is_pq(str(path)) is False

    def test_a_later_well_formed_colr_still_resolves_past_a_bodyless_one(self, tmp_path):
        # The bound must skip the malformed box, not abandon the walk.
        bodyless_colr = struct.pack('>I4s', 12, b'colr') + b'nclx'
        good_colr = _bmff_box(b'colr', b'nclx' + struct.pack('>HHH', 9, 16, 9) + b'\x00')
        ipco = _bmff_box(b'ipco', bodyless_colr + good_colr)
        blob = (_bmff_box(b'ftyp', b'avif' + b'\x00' * 4 + b'avifmif1miaf')
                + _bmff_fullbox(b'meta', _bmff_box(b'iprp', ipco)))
        path = tmp_path / "bodyless_then_good.bin"
        path.write_bytes(blob)
        assert image_loading._avif_nclx_transfer_characteristics(str(path)) == 16


class TestAvifEndToEnd:
    def test_real_sdr_avif_is_treated_as_non_pq(self, tmp_path):
        # Pillow's own AVIF encoder cannot write a CICP/nclx PQ box (confirmed
        # in-session -- AvifImagePlugin._save has no CICP option), so this is
        # the only end-to-end AVIF coverage possible: a real, Pillow-encoded
        # SDR AVIF must decode through the ordinary (non-tone-mapped) path.
        if not image_loading._avif_available:
            pytest.skip("AVIF codec not available in this Pillow build")
        path = tmp_path / "sdr.avif"
        Image.new('RGB', (16, 16), (40, 80, 120)).save(path, "AVIF")

        assert image_loading._avif_nclx_transfer_characteristics(str(path)) != 16

        out = image_loading.open_nonraw_image(path)
        arr = np.asarray(out)
        # Not tone-mapped: pixel values stay close to the source (small
        # deviation only from AVIF's own lossy encode).
        assert abs(int(arr[8, 8][0]) - 40) < 20
        assert abs(int(arr[8, 8][1]) - 80) < 20
        assert abs(int(arr[8, 8][2]) - 120) < 20

    def test_avif_pq_plus_alpha_composites_after_tonemap(self, tmp_path, monkeypatch):
        # Open question in the spec: AVIF + alpha + PQ combined has no measured
        # coverage in the findings doc (the two source bugs were probed
        # separately). Forces the PQ branch via a monkeypatched _avif_is_pq
        # (Pillow cannot encode a genuine PQ AVIF -- see TestAvifNclxParsing's
        # docstring) on a real RGBA AVIF, and asserts the ordering Step 2
        # specifies: the transparent region reads pure white regardless of
        # what the tone map did to the (arbitrary, non-PQ) code values
        # underneath it, and the opaque region visibly changed (proving the
        # tone map actually ran).
        if not image_loading._avif_available:
            pytest.skip("AVIF codec not available in this Pillow build")
        arr = np.zeros((20, 20, 4), dtype=np.uint8)
        arr[:10, :, :] = [200, 150, 100, 0]
        arr[10:, :, :] = [50, 60, 70, 255]
        path = tmp_path / "rgba.avif"
        Image.fromarray(arr, 'RGBA').save(path)

        monkeypatch.setattr(image_loading, "_avif_is_pq", lambda p: True)
        out = image_loading.open_nonraw_image(path)
        out_arr = np.asarray(out)

        assert tuple(out_arr[0, 0]) == (255, 255, 255)
        assert tuple(out_arr[-1, 0]) != (50, 60, 70)  # visibly tone-mapped


# ---------------------------------------------------------------------------
# Step 7 -- TIFF -> JPEG in /api/image; PNG/GIF/WebP/BMP/AVIF unconverted
# ---------------------------------------------------------------------------

class TestImageEndpointConversion:
    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from api import create_app
        from api.auth import CurrentUser, get_optional_user
        app = create_app()
        app.dependency_overrides[get_optional_user] = lambda: CurrentUser(user_id="u1", role="admin")
        yield TestClient(app)
        app.dependency_overrides.clear()

    def _mock_photo_row(self, monkeypatch, real_disk):
        from contextlib import contextmanager
        from unittest import mock
        from api.routers import thumbnails

        mock_conn = mock.MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {
            "path": "/library/photo", "sequence_kind": None, "preview_revision": None,
        }

        @contextmanager
        def _ctx():
            yield mock_conn

        monkeypatch.setattr(thumbnails, "get_db", _ctx)
        monkeypatch.setattr(thumbnails, "resolve_photo_disk_path", lambda p: str(real_disk))

    def test_tiff_is_converted_to_jpeg(self, tmp_path, client, monkeypatch):
        from api.routers import thumbnails
        thumbnails._convert_nonraw_cached.cache_clear()
        real_disk = tmp_path / "photo.tiff"
        Image.new('RGB', (8, 8), (10, 20, 30)).save(real_disk, "TIFF")
        self._mock_photo_row(monkeypatch, real_disk)

        resp = client.get("/image", params={"path": "/library/photo"})

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert "etag" in resp.headers

    @pytest.mark.parametrize("fmt,ext,content_type", [
        ("PNG", ".png", "image/png"),
        ("GIF", ".gif", "image/gif"),
        ("WEBP", ".webp", "image/webp"),
        ("BMP", ".bmp", "image/bmp"),
    ])
    def test_browser_renderable_formats_pass_through_unconverted(
        self, tmp_path, client, monkeypatch, fmt, ext, content_type,
    ):
        real_disk = tmp_path / f"photo{ext}"
        Image.new('RGB', (8, 8), (10, 20, 30)).save(real_disk, fmt)
        self._mock_photo_row(monkeypatch, real_disk)

        resp = client.get("/image", params={"path": "/library/photo"})

        assert resp.status_code == 200
        assert resp.headers["content-type"] == content_type
        assert resp.content == real_disk.read_bytes()

    @pytest.mark.parametrize("registry_kind", ["missing", "incorrect"])
    @pytest.mark.parametrize("fmt,ext,content_type", [
        ("JPEG", ".jpg", "image/jpeg"),
        ("JPEG", ".JPEG", "image/jpeg"),
        ("PNG", ".png", "image/png"),
        ("GIF", ".gif", "image/gif"),
        ("WEBP", ".WEBP", "image/webp"),
        ("BMP", ".bmp", "image/bmp"),
    ])
    def test_native_headers_bytes_and_ranges_ignore_system_registry(
        self, tmp_path, client, monkeypatch, registry_kind, fmt, ext, content_type,
    ):
        # Minimal images have no /etc/mime.types; a local registry may also
        # mislabel a supported image as HTML. Exercise the real FileResponse.
        registry = mimetypes.MimeTypes()
        for types in registry.types_map:
            types.clear()
        if registry_kind == "incorrect":
            registry.add_type("text/html", ext.lower())
        monkeypatch.setattr(mimetypes, "_db", registry)
        monkeypatch.setattr(mimetypes, "inited", True)
        real_disk = tmp_path / f"photo{ext}"
        Image.new('RGB', (8, 8), (10, 20, 30)).save(real_disk, fmt)
        original = real_disk.read_bytes()
        self._mock_photo_row(monkeypatch, real_disk)

        response = client.get("/image", params={"path": "/library/photo"})
        assert response.status_code == 200
        assert response.headers["content-type"] == content_type
        assert response.content == original
        assert response.headers["content-length"] == str(len(original))
        assert response.headers["accept-ranges"] == "bytes"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "content-disposition" not in response.headers
        assert "etag" in response.headers and "last-modified" in response.headers

        partial = client.get("/image", params={"path": "/library/photo"}, headers={"Range": "bytes=0-15"})
        assert partial.status_code == 206
        assert partial.headers["content-type"] == content_type
        assert partial.headers["content-range"] == f"bytes 0-15/{len(original)}"
        assert partial.content == original[:16]
        assert partial.headers["etag"] == response.headers["etag"]

    def test_unknown_extension_is_not_promoted_to_image_by_sniffing(self, tmp_path, client, monkeypatch):
        registry = mimetypes.MimeTypes()
        for types in registry.types_map:
            types.clear()
        monkeypatch.setattr(mimetypes, "_db", registry)
        monkeypatch.setattr(mimetypes, "inited", True)
        real_disk = tmp_path / "photo.unknown"
        payload = b'<html><script>not an image</script></html>'
        real_disk.write_bytes(payload)
        self._mock_photo_row(monkeypatch, real_disk)
        response = client.get("/image", params={"path": "/library/photo"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.content == payload

    def test_original_webp_download_remains_an_attachment(self, tmp_path, client, monkeypatch):
        from api.routers import comparison
        real_disk = tmp_path / "photo.webp"
        Image.new('RGB', (8, 8), (10, 20, 30)).save(real_disk, "WEBP")
        monkeypatch.setattr(comparison, "_validate_and_resolve", lambda path, user: (path, str(real_disk), None))
        response = client.get("/api/download", params={"path": "/library/photo", "type": "original"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"] == 'attachment; filename="photo.webp"'
        assert response.content == real_disk.read_bytes()

    @pytest.mark.parametrize("registry_kind", ["default", "missing", "incorrect"])
    def test_avif_passes_through_unconverted(self, tmp_path, client, monkeypatch, registry_kind):
        if not image_loading._avif_available:
            pytest.skip("AVIF codec not available in this Pillow build")
        if registry_kind != "default":
            registry = mimetypes.MimeTypes()
            for types in registry.types_map:
                types.pop(".avif", None)
            if registry_kind == "incorrect":
                registry.add_type("text/html", ".avif")
            monkeypatch.setattr(mimetypes, "_db", registry)
            monkeypatch.setattr(mimetypes, "inited", True)
        real_disk = tmp_path / "photo.avif"
        Image.new('RGB', (8, 8), (10, 20, 30)).save(real_disk, "AVIF")
        self._mock_photo_row(monkeypatch, real_disk)

        resp = client.get("/image", params={"path": "/library/photo"})

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/avif"
        assert resp.content == real_disk.read_bytes()


# ---------------------------------------------------------------------------
# Adversarial finding 6 -- SAFE_EMBED_EXTS dispatch (processing/xmp_export.py)
# ---------------------------------------------------------------------------

class TestSafeEmbedExtsDispatch:
    """SAFE_EMBED_EXTS already lists tif/tiff/png (processing/xmp_export.py:396) --
    Step 1 makes those newly REACHABLE since TIFF/PNG are now scanned. Adjudicated
    as correct (embed_original defaults False; only an explicit opt-in reaches
    it), but requires this test asserting TIFF/PNG take the embed path and
    GIF/WebP/BMP/AVIF take the sidecar-only path."""

    @pytest.fixture()
    def _stub_exiftool(self, monkeypatch):
        from processing import xmp_export
        calls = []
        monkeypatch.setattr(xmp_export, "exiftool_available", lambda: True)
        monkeypatch.setattr(
            xmp_export, "_run_exiftool",
            lambda target, rating, timeout, reconcile=False, precomputed_args=None: calls.append(target),
        )
        return calls

    @pytest.mark.parametrize("ext", ["tif", "tiff", "png"])
    def test_tif_tiff_png_take_the_embed_path(self, tmp_path, _stub_exiftool, ext):
        from processing.xmp_export import XmpRating, write_metadata
        image_path = str(tmp_path / f"photo.{ext}")
        result = write_metadata(image_path, XmpRating(), embed_original=True)
        assert result["embedded"] == image_path

    @pytest.mark.parametrize("ext", ["gif", "webp", "bmp", "avif"])
    def test_gif_webp_bmp_avif_take_the_sidecar_only_path(self, tmp_path, _stub_exiftool, ext):
        from processing.xmp_export import XmpRating, write_metadata
        image_path = str(tmp_path / f"photo.{ext}")
        result = write_metadata(image_path, XmpRating(), embed_original=True)
        assert result["embedded"] is None
