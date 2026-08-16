"""Tests for the stored per-photo histogram: packing, the two on-disk formats,
the ``/api/photo/histogram`` endpoint and the colour-similarity consumer.

The library that motivated this change holds ~127k rows in the legacy
1024-byte format, so "both formats decode" is not a nicety — it is the normal
state of a database for as long as a full rescan takes.
"""

import sqlite3
import struct
from contextlib import contextmanager
from unittest import mock

import numpy as np
import pytest

from analyzers.technical import TechnicalAnalyzer
from api.routers.gallery import _find_similar_color
from utils.histogram import (
    HISTOGRAM_BINS, HISTOGRAM_BLOB_SIZE, LEGACY_HISTOGRAM_BLOB_SIZE,
    clip_percents, display_channels, downsample_bins, max_clip_percents,
    pack_histogram, unpack_histogram,
)

_MODULE = "api.routers.histogram"


def _legacy_blob(counts):
    """A pre-RGB blob: 256 float32 luminance bins normalised to sum 1."""
    counts = np.asarray(counts, dtype=np.float64)
    total = counts.sum()
    normalized = counts / total if total else counts
    return struct.pack('256f', *normalized)


def _spike(index, height=1000.0, bins=HISTOGRAM_BINS):
    counts = np.zeros(bins)
    counts[index] = height
    return counts


# ---------------------------------------------------------------------------
# Packing / decoding
# ---------------------------------------------------------------------------

class TestPackUnpack:
    def test_blob_is_four_uint16_channels(self):
        blob = pack_histogram(_spike(0), _spike(1), _spike(2), _spike(3))
        assert len(blob) == HISTOGRAM_BLOB_SIZE == 2048

    def test_round_trips_channel_order_and_shape(self):
        blob = pack_histogram(_spike(10), _spike(20), _spike(30), _spike(40))
        decoded = unpack_histogram(blob)
        assert decoded['luma'].argmax() == 10
        red, green, blue = decoded['rgb']
        assert (red.argmax(), green.argmax(), blue.argmax()) == (20, 30, 40)

    def test_one_scale_factor_preserves_relative_channel_heights(self):
        blob = pack_histogram(_spike(0, 100), _spike(0, 400), _spike(0, 200), _spike(0, 50))
        decoded = unpack_histogram(blob)
        red, green, blue = decoded['rgb']
        assert red.max() == pytest.approx(65535, rel=1e-4)
        assert decoded['luma'].max() / red.max() == pytest.approx(0.25, rel=1e-3)
        assert green.max() / red.max() == pytest.approx(0.5, rel=1e-3)
        assert blue.max() / red.max() == pytest.approx(0.125, rel=1e-3)

    def test_all_zero_histogram_packs_without_dividing_by_zero(self):
        zeros = np.zeros(HISTOGRAM_BINS)
        decoded = unpack_histogram(pack_histogram(zeros, zeros, zeros, zeros))
        assert decoded['luma'].sum() == 0

    def test_legacy_blob_decodes_as_luminance_only(self):
        blob = _legacy_blob(_spike(77))
        assert len(blob) == LEGACY_HISTOGRAM_BLOB_SIZE == 1024
        decoded = unpack_histogram(blob)
        assert decoded['rgb'] is None
        assert decoded['luma'].argmax() == 77
        assert decoded['luma'].sum() == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.parametrize("blob", [None, b'', b'\x00' * 999, b'\x00' * 4096])
    def test_missing_or_unknown_length_returns_none(self, blob):
        assert unpack_histogram(blob) is None


class TestDownsampleBins:
    def test_sums_adjacent_bins(self):
        counts = np.arange(HISTOGRAM_BINS, dtype=np.float64)
        out = downsample_bins(counts, 64)
        assert out.shape == (64,)
        assert out.sum() == counts.sum()
        assert out[0] == 0 + 1 + 2 + 3

    def test_full_resolution_is_a_passthrough(self):
        counts = np.arange(HISTOGRAM_BINS, dtype=np.float64)
        assert np.array_equal(downsample_bins(counts, HISTOGRAM_BINS), counts)

    def test_rejects_a_non_divisor(self):
        with pytest.raises(ValueError):
            downsample_bins(np.zeros(HISTOGRAM_BINS), 50)


class TestDisplayChannels:
    def test_normalizes_every_channel_by_one_global_max(self):
        decoded = unpack_histogram(
            pack_histogram(_spike(100, 100), _spike(100, 400), _spike(100, 200), _spike(100, 50))
        )
        out = display_channels(decoded, bins=HISTOGRAM_BINS)
        assert max(out['r']) == pytest.approx(1.0, abs=1e-3)
        assert max(out['luma']) == pytest.approx(0.25, abs=1e-3)
        assert max(out['g']) == pytest.approx(0.5, abs=1e-3)
        assert max(out['b']) == pytest.approx(0.125, abs=1e-3)

    def test_never_stretches_a_near_empty_channel_to_full_height(self):
        decoded = unpack_histogram(
            pack_histogram(_spike(80, 1000), _spike(80, 1000), _spike(80, 1000), _spike(80, 1))
        )
        out = display_channels(decoded, bins=HISTOGRAM_BINS)
        assert max(out['b']) < 0.01

    def test_legacy_histogram_reports_luma_only(self):
        out = display_channels(unpack_histogram(_legacy_blob(_spike(12))), bins=64)
        assert out['r'] is None and out['g'] is None and out['b'] is None
        assert len(out['luma']) == 64
        assert max(out['luma']) == 1.0

    def test_respects_the_requested_bin_count(self):
        decoded = unpack_histogram(pack_histogram(*[_spike(3)] * 4))
        assert len(display_channels(decoded, bins=32)['luma']) == 32


# ---------------------------------------------------------------------------
# Analyzer output
# ---------------------------------------------------------------------------

class TestAnalyzerChannels:
    def test_channels_track_the_actual_colours(self):
        # Left half saturated red, right half saturated blue (image_cv is BGR).
        img = np.zeros((20, 20, 3), dtype=np.uint8)
        img[:, :10] = (0, 0, 255)
        img[:, 10:] = (255, 0, 0)

        decoded = unpack_histogram(TechnicalAnalyzer.get_histogram_data(img)['histogram_bytes'])
        red, green, blue = decoded['rgb']

        # Half the pixels are fully saturated in red, half in blue.
        assert red[255] == red[0] == red.max()
        assert blue[255] == blue[0] == blue.max()
        # No pixel has any green, so its single bin holds the whole frame and is
        # the tallest bin anywhere -- the one that sets the shared scale factor.
        assert green.argmax() == 0
        assert green[0] == 65535
        assert red.max() == pytest.approx(65535 / 2, rel=1e-3)

    def test_monochrome_frame_gives_identical_channels(self):
        img = np.full((20, 20, 3), 128, dtype=np.uint8)
        decoded = unpack_histogram(TechnicalAnalyzer.get_histogram_data(img)['histogram_bytes'])
        red, green, blue = decoded['rgb']
        assert np.array_equal(red, green) and np.array_equal(green, blue)
        assert np.array_equal(decoded['luma'], red)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

def _db_cm(db_path):
    @contextmanager
    def _cm():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    return _cm


def _seed(tmp_path, rows):
    db = str(tmp_path / "hist.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE photos (path TEXT PRIMARY KEY, histogram_data BLOB, "
        "filename TEXT, mean_saturation REAL, mean_luminance REAL, is_monochrome INTEGER, "
        "date_taken TEXT, aggregate REAL, aesthetic REAL)"
    )
    for path, blob in rows:
        conn.execute(
            "INSERT INTO photos (path, histogram_data, filename, mean_saturation, "
            "mean_luminance, is_monochrome, date_taken, aggregate, aesthetic) "
            "VALUES (?, ?, ?, 0.2, 0.5, 0, '2026-01-01', 7.0, 7.0)",
            (path, blob, path.lstrip('/')),
        )
    conn.commit()
    conn.close()
    return db


class TestHistogramEndpoint:
    def test_serves_all_four_channels_for_a_current_row(self, regular_client, tmp_path):
        blob = pack_histogram(
            _spike(100, 100), _spike(100, 400), _spike(100, 200), _spike(100, 50))
        db = _seed(tmp_path, [("/a.jpg", blob)])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = regular_client.get("/api/photo/histogram", params={"path": "/a.jpg"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["bins"] == 64
        assert len(body["luma"]) == len(body["r"]) == 64
        assert max(body["r"]) == pytest.approx(1.0, abs=1e-3)
        assert max(body["luma"]) == pytest.approx(0.25, abs=1e-3)

    def test_legacy_row_serves_luminance_with_null_channels(self, regular_client, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", _legacy_blob(_spike(200)))])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = regular_client.get("/api/photo/histogram", params={"path": "/a.jpg"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["r"] is None and body["g"] is None and body["b"] is None
        assert body["luma"].index(1.0) == 200 * 64 // 256

    def test_row_without_a_histogram_404s_so_the_client_can_fall_back(
            self, regular_client, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", None)])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = regular_client.get("/api/photo/histogram", params={"path": "/a.jpg"})
        assert resp.status_code == 404

    def test_unknown_photo_404s(self, regular_client, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", _legacy_blob(_spike(1)))])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = regular_client.get("/api/photo/histogram", params={"path": "/nope.jpg"})
        assert resp.status_code == 404

    @pytest.mark.parametrize("bins", [7, 0, 512])
    def test_rejects_a_bin_count_that_does_not_divide_256(
            self, regular_client, tmp_path, bins):
        db = _seed(tmp_path, [("/a.jpg", _legacy_blob(_spike(1)))])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = regular_client.get(
                "/api/photo/histogram", params={"path": "/a.jpg", "bins": bins})
        assert resp.status_code == 400

    def test_serves_the_full_stored_resolution_on_request(self, regular_client, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", pack_histogram(*[_spike(9)] * 4))])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = regular_client.get(
                "/api/photo/histogram", params={"path": "/a.jpg", "bins": 256})
        assert resp.status_code == 200
        assert len(resp.json()["luma"]) == HISTOGRAM_BINS


# ---------------------------------------------------------------------------
# Colour similarity keeps working across both formats
# ---------------------------------------------------------------------------

# An identical colour photo scores 0.9, not 1.0: the last tenth is the
# monochrome bonus, which two colour photos never earn.
_PERFECT_COLOUR_MATCH = 0.9


class TestColorSimilarityAcrossFormats:
    def _conn(self, tmp_path, rows):
        conn = sqlite3.connect(_seed(tmp_path, rows))
        conn.row_factory = sqlite3.Row
        return conn

    def _run(self, conn, source_blob):
        source = {
            'histogram_data': source_blob, 'is_monochrome': 0,
            'mean_saturation': 0.2, 'mean_luminance': 0.5,
        }
        return _find_similar_color(conn, source, '/src.jpg', 0.0, '1=1', [])

    def test_legacy_source_matches_legacy_candidate(self, tmp_path):
        blob = _legacy_blob(_spike(100))
        conn = self._conn(tmp_path, [("/src.jpg", blob), ("/same.jpg", blob)])
        results, reason = self._run(conn, blob)
        assert reason is None
        assert results[0]['path'] == '/same.jpg'
        assert results[0]['similarity'] == pytest.approx(_PERFECT_COLOUR_MATCH, abs=1e-3)

    def test_current_source_matches_current_candidate(self, tmp_path):
        blob = pack_histogram(_spike(100), _spike(10), _spike(20), _spike(30))
        conn = self._conn(tmp_path, [("/src.jpg", blob), ("/same.jpg", blob)])
        results, reason = self._run(conn, blob)
        assert reason is None
        assert results[0]['similarity'] == pytest.approx(_PERFECT_COLOUR_MATCH, abs=1e-3)

    def test_mixed_formats_still_score_the_same_luminance_as_a_match(self, tmp_path):
        counts = _spike(100)
        legacy = _legacy_blob(counts)
        current = pack_histogram(counts, _spike(10), _spike(20), _spike(30))
        conn = self._conn(tmp_path, [("/src.jpg", legacy), ("/current.jpg", current)])
        results, _ = self._run(conn, legacy)
        assert results[0]['path'] == '/current.jpg'
        assert results[0]['similarity'] == pytest.approx(_PERFECT_COLOUR_MATCH, abs=1e-3)

    def test_different_luminance_still_separates(self, tmp_path):
        dark = pack_histogram(*[_spike(5)] * 4)
        bright = pack_histogram(*[_spike(250)] * 4)
        conn = self._conn(tmp_path, [("/src.jpg", dark), ("/bright.jpg", bright)])
        results, _ = self._run(conn, dark)
        assert results[0]['similarity'] < 0.5

    def test_source_without_a_histogram_reports_the_reason(self, tmp_path):
        conn = self._conn(tmp_path, [("/src.jpg", None)])
        assert self._run(conn, None) == ([], 'no_histogram')

    def test_candidate_with_a_corrupt_blob_is_skipped_not_fatal(self, tmp_path):
        blob = _legacy_blob(_spike(100))
        conn = self._conn(tmp_path, [("/src.jpg", blob), ("/bad.jpg", b'\x00' * 7)])
        results, reason = self._run(conn, blob)
        assert reason is None
        assert results == []


# ---------------------------------------------------------------------------
# --recompute-average re-derives exposure_score from the stored blob
# ---------------------------------------------------------------------------

# The columns update_all_aggregates reads back for a photo; only the histogram
# and the fields the exposure formula consumes matter here.
_RECOMPUTE_ROW = {
    'aesthetic': 7.0, 'face_count': 0, 'face_ratio': 0.0, 'tech_sharpness': 7.0,
    'color_score': 7.0, 'exposure_score': 0.0, 'comp_score': 6.0,
    'is_silhouette': 0, 'histogram_bimodality': 1.0, 'is_monochrome': 0,
    'tags': '', 'mean_luminance': 0.5, 'quality_score': 5.0,
}


def _recomputed_exposure(tmp_path, name, blob):
    from db import get_connection, init_database
    from processing.scorer import Facet

    db_path = str(tmp_path / f'{name}.db')
    init_database(db_path)
    columns = ['path', 'histogram_data'] + list(_RECOMPUTE_ROW.keys())
    values = [f'/{name}.jpg', blob] + list(_RECOMPUTE_ROW.values())
    with get_connection(db_path, row_factory=False) as conn:
        conn.execute(
            f"INSERT INTO photos ({','.join(columns)}) "
            f"VALUES ({','.join('?' * len(columns))})", values)
        conn.commit()

    Facet(db_path=db_path, lightweight=True).update_all_aggregates(use_embeddings=False)
    with get_connection(db_path, row_factory=False) as conn:
        return conn.execute(
            "SELECT exposure_score FROM photos WHERE path = ?", (f'/{name}.jpg',)
        ).fetchone()[0]


class TestRecomputeReadsBothFormats:
    def test_both_formats_of_one_distribution_recompute_the_same_score(self, tmp_path):
        counts = np.zeros(HISTOGRAM_BINS)
        counts[60:140] = 500.0
        legacy = _recomputed_exposure(tmp_path, 'legacy', _legacy_blob(counts))
        current = _recomputed_exposure(
            tmp_path, 'current', pack_histogram(counts, counts, counts, counts))
        assert legacy == pytest.approx(current, abs=1e-3)

    def test_a_crushed_frame_still_scores_below_a_well_exposed_one(self, tmp_path):
        dark = np.zeros(HISTOGRAM_BINS)
        dark[:10] = 5000.0
        even = np.full(HISTOGRAM_BINS, 100.0)
        assert (_recomputed_exposure(tmp_path, 'dark', pack_histogram(dark, dark, dark, dark))
                < _recomputed_exposure(tmp_path, 'even', pack_histogram(even, even, even, even)))


# ---------------------------------------------------------------------------
# Per-channel clipping: derivation, the NULL-means-unknown rule, and drawing
# ---------------------------------------------------------------------------

def _frame(pixels_bgr):
    """A 100x100 BGR frame from a list of (count, (b, g, r)) runs."""
    flat = np.zeros((10000, 3), dtype=np.uint8)
    offset = 0
    for count, colour in pixels_bgr:
        flat[offset:offset + count] = colour
        offset += count
    return flat.reshape(100, 100, 3)


class TestClipPercents:
    def test_derived_fractions_match_a_direct_pixel_count(self):
        # 1200 pixels blown out in blue only, 700 crushed in red only.
        img = _frame([
            (1200, (255, 40, 40)),
            (700, (90, 90, 0)),
            (8100, (120, 130, 140)),
        ])
        flat = img.reshape(-1, 3)
        total = flat.shape[0]
        blue, green, red = flat[:, 0], flat[:, 1], flat[:, 2]

        measured = TechnicalAnalyzer.get_histogram_data(img)
        derived = clip_percents(unpack_histogram(measured['histogram_bytes']))

        for name, channel in (('r', red), ('g', green), ('b', blue)):
            assert derived['highlight'][name] == pytest.approx(
                (channel == 255).sum() / total * 100, abs=1e-3)
            assert derived['shadow'][name] == pytest.approx(
                (channel == 0).sum() / total * 100, abs=1e-3)

        # The columns the scan stores are the worst channel of each direction.
        assert measured['channel_clip_highlight_pct'] == pytest.approx(12.0, abs=1e-4)
        assert measured['channel_clip_shadow_pct'] == pytest.approx(7.0, abs=1e-4)

    def test_a_single_blown_channel_is_invisible_to_luminance(self):
        # Deep red: R is pinned at 255 while luma sits near 76, so a luma-only
        # reading reports nothing at all. This is the whole point of the column.
        img = _frame([(10000, (0, 0, 255))])
        derived = clip_percents(unpack_histogram(
            TechnicalAnalyzer.get_histogram_data(img)['histogram_bytes']))
        assert derived['highlight']['r'] == pytest.approx(100.0, abs=1e-3)
        assert derived['highlight']['luma'] == 0.0

    def test_the_stored_columns_take_the_worst_channel_not_luma(self):
        img = _frame([(2000, (255, 0, 0)), (8000, (100, 110, 120))])
        measured = TechnicalAnalyzer.get_histogram_data(img)
        assert measured['channel_clip_highlight_pct'] == pytest.approx(20.0, abs=1e-3)

    def test_exactly_bin_255_counts_never_a_band_below_it(self):
        # 254 is a hot highlight but it is not clipped: it still holds detail.
        img = _frame([(5000, (254, 254, 254)), (5000, (1, 1, 1))])
        measured = TechnicalAnalyzer.get_histogram_data(img)
        assert measured['channel_clip_highlight_pct'] == 0.0
        assert measured['channel_clip_shadow_pct'] == 0.0

    def test_the_coarse_luma_flags_are_left_alone(self):
        # shadow_clipped/highlight_clipped are bands on luminance and feed
        # exposure_score; the new columns must not have changed them.
        img = _frame([(5000, (255, 255, 255)), (5000, (0, 0, 0))])
        measured = TechnicalAnalyzer.get_histogram_data(img)
        assert measured['shadow_clipped'] == 1
        assert measured['highlight_clipped'] == 1
        assert measured['channel_clip_shadow_pct'] == pytest.approx(50.0, abs=1e-3)

    def test_a_legacy_blob_is_unknown_not_clean(self):
        legacy = unpack_histogram(_legacy_blob(_spike(200)))
        assert clip_percents(legacy) is None
        assert max_clip_percents(legacy) == (None, None)

    def test_a_missing_blob_is_unknown_too(self):
        assert clip_percents(unpack_histogram(None)) is None
        assert max_clip_percents(unpack_histogram(None)) == (None, None)

    def test_survives_the_uint16_packing_of_a_dominant_spike(self):
        # 40% of pixels on bin 255 sets the packing scale; the interior bins are
        # squeezed hard, and the RATIO must still come back.
        counts = np.zeros(HISTOGRAM_BINS)
        counts[255] = 4000.0
        counts[60:140] = 12.5
        blob = pack_histogram(counts, counts, counts, counts)
        assert max_clip_percents(unpack_histogram(blob))[1] == pytest.approx(80.0, abs=0.05)


class TestInteriorNormalization:
    def _clipped_decoded(self):
        """A frame whose bin-255 spike dwarfs a real, readable tonal curve."""
        counts = np.zeros(HISTOGRAM_BINS)
        counts[255] = 10000.0
        counts[100] = 300.0
        counts[101] = 150.0
        return unpack_histogram(pack_histogram(counts, counts, counts, counts))

    def test_a_dominant_clip_spike_no_longer_flattens_the_curve(self):
        out = display_channels(self._clipped_decoded(), bins=HISTOGRAM_BINS)
        # Against the spike this bin was 3% of full height -- a hairline.
        assert out['luma'][100] == pytest.approx(1.0, abs=1e-3)
        assert out['luma'][101] == pytest.approx(0.5, abs=1e-3)

    def test_both_clipping_bins_are_dropped_from_the_curve(self):
        out = display_channels(self._clipped_decoded(), bins=HISTOGRAM_BINS)
        assert out['luma'][255] == 0.0
        assert out['luma'][0] == 0.0

    def test_the_shared_scale_across_channels_is_kept(self):
        # Only the interior maximum may set the scale, and it is still ONE
        # maximum for all four channels -- per-channel maxima would invent a cast.
        blob = pack_histogram(
            _spike(90, 100), _spike(90, 400), _spike(90, 200), _spike(90, 50))
        out = display_channels(unpack_histogram(blob), bins=HISTOGRAM_BINS)
        assert max(out['r']) == pytest.approx(1.0, abs=1e-3)
        assert max(out['g']) == pytest.approx(0.5, abs=1e-3)
        assert max(out['b']) == pytest.approx(0.125, abs=1e-3)

    def test_an_all_clipped_frame_draws_a_flat_line_instead_of_dividing_by_zero(self):
        counts = np.zeros(HISTOGRAM_BINS)
        counts[255] = 5000.0
        out = display_channels(unpack_histogram(pack_histogram(*[counts] * 4)), bins=64)
        assert set(out['luma']) == {0.0}


class TestHistogramEndpointClipping:
    def test_serves_the_percentages_for_a_current_row(self, regular_client, tmp_path):
        counts = np.zeros(HISTOGRAM_BINS)
        counts[255] = 100.0
        counts[50] = 900.0
        blob = pack_histogram(counts, counts, counts, np.zeros(HISTOGRAM_BINS))
        db = _seed(tmp_path, [("/a.jpg", blob)])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = regular_client.get("/api/photo/histogram", params={"path": "/a.jpg"})
        assert resp.status_code == 200
        clipped = resp.json()["clipped"]
        assert clipped["highlight"]["r"] == pytest.approx(10.0, abs=1e-2)
        assert clipped["shadow"]["r"] == 0.0

    def test_a_legacy_row_reports_null_so_the_client_shows_no_markers(
            self, regular_client, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", _legacy_blob(_spike(200)))])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = regular_client.get("/api/photo/histogram", params={"path": "/a.jpg"})
        assert resp.status_code == 200
        assert resp.json()["clipped"] is None
