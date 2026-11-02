"""The stored thumbnail is made where a photo is decoded (issue #433, step 3).

Goldens (``tests/fixtures/thumbnail_goldens_master.json``) were captured on master
by driving ``save_photos_batch`` over the inputs in ``tests/thumbnail_inputs.py``.
They are compared here, never recomputed from this tree's own formula.
"""
import hashlib
import json
import sqlite3
import sys
from unittest import mock

import pytest

from tests import thumbnail_inputs as ti
from utils import image_loading
from utils.image_transforms import generate_photo_thumbnail

GOLDENS = json.loads(ti.GOLDENS_PATH.read_text(encoding='utf-8'))

# Camera HDR PQ files are tone-mapped from what the platform's libheif build decodes,
# so their bytes differ between the Windows capture and Linux CI. Their branch-vs-master
# identity is covered on every platform by TestMatchesTheUnchangedMasterPath.
GOLDENS_PLATFORM = 'win32'
PLATFORM_DECODED_CASES = {'hif_pq', 'hif_pq_rotated'}


def _skip_unavailable(name):
    if name == 'jxl' and not ti.jxl_available():
        pytest.skip('imagecodecs has no JPEG XL codec')


def _scan_and_save(name, workdir):
    """Decode through the scan entry, save through ``save_photos_batch``."""
    with ti.scan_input(name, workdir) as (path, opens):
        pil, img_cv, thumbnail, seconds = image_loading.load_image_and_thumbnail(path)
        assert pil is not None
        res = ti.base_result(path)
        res['thumbnail'] = thumbnail
        db_path = str(workdir / 'scan.db')
        facet = ti.make_facet(db_path)
        with mock.patch('processing.scorer.get_plugin_manager', return_value=None, create=True):
            facet.save_photos_batch([res])
        return ti.stored_thumbnail(db_path, path), opens['opens'], seconds


class TestByteIdentityWithMaster:

    @pytest.mark.parametrize('name', ti.ALL_CASES)
    def test_thumbnail_bytes_and_render_version_match_master(self, name, tmp_path):
        _skip_unavailable(name)
        if name in PLATFORM_DECODED_CASES and sys.platform != GOLDENS_PLATFORM:
            pytest.skip('golden captured with the Windows libheif build')
        (sha, version), _, _ = _scan_and_save(name, tmp_path)
        assert sha == GOLDENS[name]['sha256']
        assert version == GOLDENS[name]['render_version']

    def test_every_input_has_a_golden(self):
        assert PLATFORM_DECODED_CASES <= set(ti.NONRAW_CASES)
        expected = {n for n in ti.ALL_CASES if n != 'jxl' or ti.jxl_available()}
        assert expected <= set(GOLDENS)


class TestMatchesTheUnchangedMasterPath:
    """Same environment, master's own non-RAW thumbnail path, which this change leaves
    untouched (``load_image_from_path`` then ``thumbnail_source``)."""

    @pytest.mark.parametrize('name', tuple(ti.NONRAW_CASES))
    def test_scan_thumbnail_equals_the_save_time_path(self, name, tmp_path):
        _skip_unavailable(name)
        (sha, _), _, _ = _scan_and_save(name, tmp_path)
        old_dir = tmp_path / 'old'
        old_dir.mkdir()
        with ti.scan_input(name, old_dir) as (path, _):
            pil, _ = image_loading.load_image_from_path(path)
            old = generate_photo_thumbnail(image_loading.thumbnail_source(path, pil))
        assert sha == hashlib.sha256(old).hexdigest()


class TestSingleOpen:

    @pytest.mark.parametrize('name', ti.RAW_CASES)
    def test_decode_entry_opens_each_raw_once(self, name, tmp_path):
        _, opens, seconds = _scan_and_save(name, tmp_path)
        assert opens == 1
        assert seconds > 0

    @pytest.mark.parametrize('name', ti.RAW_CASES)
    def test_a_full_scan_chunk_opens_each_raw_once_and_carries_the_thumbnail(
            self, name, tmp_path, monkeypatch):
        proc = _processor(monkeypatch)
        with ti.scan_input(name, tmp_path) as (path, opens):
            images = proc._load_images([str(path)])
        assert opens['opens'] == 1
        thumbnail = images[str(path)]['thumbnail']
        assert hashlib.sha256(thumbnail).hexdigest() == GOLDENS[name]['sha256']

    def test_the_old_two_open_flow_is_what_the_counter_would_catch(self, tmp_path):
        """Guard on the counter itself: decode then thumbnail_source opens twice."""
        with ti.scan_input('raw_preview_usable', tmp_path) as (path, opens):
            pil, _ = image_loading.load_image_from_path(path)
            image_loading.thumbnail_source(path, pil)
        assert opens['opens'] == 2

    def test_thumbnail_seconds_are_booked_to_the_thumbnail_stage_not_decode(
            self, tmp_path, monkeypatch):
        proc = _processor(monkeypatch)
        with ti.scan_input('raw_preview_usable', tmp_path) as (path, _):
            proc._load_images([str(path)])
        assert proc.metrics['thumbnail_worker_time'] > 0
        assert proc.metrics['decode_worker_time'] >= 0
        assert 'thumbnail_time' not in proc.metrics


class TestSaveContract:

    def test_save_photos_batch_never_derives_a_thumbnail(self, tmp_path):
        facet = ti.make_facet(str(tmp_path / 'c.db'))
        res = ti.base_result('/photos/a.jpg')
        res['thumbnail'] = b'\xff\xd8carried'
        with mock.patch('processing.scorer.thumbnail_source',
                        side_effect=AssertionError('thumbnail_source called')), \
             mock.patch('processing.scorer.generate_photo_thumbnail',
                        side_effect=AssertionError('generate_photo_thumbnail called')), \
             mock.patch('processing.scorer.get_plugin_manager', return_value=None, create=True):
            facet.save_photos_batch([res])
        conn = sqlite3.connect(str(tmp_path / 'c.db'))
        try:
            stored = conn.execute("SELECT thumbnail FROM photos").fetchone()[0]
        finally:
            conn.close()
        assert stored == b'\xff\xd8carried'

    @pytest.mark.parametrize('thumbnail', ['absent', None, b''])
    def test_a_result_without_a_thumbnail_is_refused(self, thumbnail, tmp_path):
        facet = ti.make_facet(str(tmp_path / 'c.db'))
        res = ti.base_result('/photos/a.jpg')
        if thumbnail != 'absent':
            res['thumbnail'] = thumbnail
        with pytest.raises(ValueError, match='thumbnail'):
            facet.save_photos_batch([res])
        conn = sqlite3.connect(str(tmp_path / 'c.db'))
        try:
            assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 0
        finally:
            conn.close()


def _processor(monkeypatch, *, restricted=False):
    from tests.test_scan_decode_overlap import _Manager, _processor as make
    monkeypatch.setattr('exiftool.get_exif_batch',
                        lambda paths, chunk_size=100, stop_event=None: {})
    return make(_Manager(), [['clip']], monkeypatch, restricted=restricted)


class TestRestrictedRun:

    def test_a_restricted_load_makes_no_thumbnail(self, tmp_path, monkeypatch):
        proc = _processor(monkeypatch, restricted=True)
        monkeypatch.setattr(
            'utils.load_image_and_thumbnail',
            mock.Mock(side_effect=AssertionError('restricted run made a thumbnail')))
        with ti.scan_input('raw_preview_usable', tmp_path) as (path, _):
            images = proc._load_images([str(path)])
        assert images[str(path)]['thumbnail'] is None
        assert proc.metrics['thumbnail_worker_time'] == 0.0


class TestBatchProcessorStoresDecodeTimeThumbnail:

    @pytest.mark.parametrize('name,expected_opens', [
        ('jpeg_exif_rotated', 0), ('raw_preview_usable', 1), ('raw_unsupported_fallback', 1)])
    def test_saved_result_carries_the_golden_thumbnail(self, name, expected_opens, tmp_path):
        pytest.importorskip('torch')
        from tests.test_batch_processor_e2e import FakeScorer, _make_processor
        scorer = FakeScorer(tmp_path)
        proc = _make_processor(scorer)
        with ti.scan_input(name, tmp_path) as (path, opens):
            proc.process_files([str(path)], show_metrics=False)
        assert opens['opens'] == expected_opens
        assert len(scorer.saved) == 1
        saved = scorer.saved[0]
        assert hashlib.sha256(saved['thumbnail']).hexdigest() == GOLDENS[name]['sha256']
        assert proc.metrics['total_thumbnail_time'] > 0
