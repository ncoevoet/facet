"""The scan-path readers of the file/exposure EXIF fields: real exiftool, its batch
reader, the subprocess / exifread / Pillow fallbacks, and both save paths."""
import json
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from db import get_connection, init_database
from exiftool.exiftool_batch import EXIF_META_COLUMNS, ExifToolBatch, parse_exif_data

EXIFTOOL = shutil.which('exiftool')
needs_exiftool = pytest.mark.skipif(EXIFTOOL is None, reason='exiftool not installed')


def _facet():
    pytest.importorskip('imagehash')
    pytest.importorskip('cv2')
    from processing.scorer import Facet
    return Facet.__new__(Facet)


def _no_exiftool(monkeypatch):
    monkeypatch.setattr('exiftool.get_exif_single', lambda p: {'camera_model': None})
    monkeypatch.setattr('subprocess.run', lambda *a, **k: (_ for _ in ()).throw(OSError('no exiftool')))


@needs_exiftool
def test_real_exiftool_reports_focal_length_35mm(tmp_path):
    path = tmp_path / 'f35.jpg'
    Image.new('RGB', (16, 16)).save(path)
    subprocess.run([EXIFTOOL, '-overwrite_original', '-n', '-FocalLengthIn35mmFormat=50', str(path)],
                   check=True, capture_output=True)
    raw = ExifToolBatch.get_metadata_batch(None, [str(path)])[str(path.resolve())]
    assert parse_exif_data(raw)['focal_length_35mm'] == 50


def test_parse_focal_length_35mm_zero_is_unknown():
    assert parse_exif_data({'FocalLengthIn35mmFormat': 0})['focal_length_35mm'] is None
    assert parse_exif_data({'FocalLengthIn35mmFormat': 28})['focal_length_35mm'] == 28


@needs_exiftool
def test_batch_reader_skips_an_unreadable_file_and_keeps_the_rest(tmp_path):
    good = tmp_path / 'good.jpg'
    Image.new('RGB', (16, 16)).save(good)
    bad = tmp_path / 'bad.jpg'
    bad.write_bytes(bytes(range(256)) * 2)  # binary, no known magic: exiftool's 'File format error'
    found = ExifToolBatch.get_metadata_batch(None, [str(good), str(bad)])
    assert found[str(good.resolve())]['FileSize'] == good.stat().st_size
    assert str(bad.resolve()) not in found


def test_subprocess_fallback_parses_through_parse_exif_data(tmp_path, monkeypatch):
    facet = _facet()
    path = tmp_path / 'sub.jpg'
    Image.new('RGB', (8, 8)).save(path)
    monkeypatch.setattr('exiftool.get_exif_single', lambda p: {'camera_model': None})
    payload = [{'SourceFile': str(path), 'Model': 'Cam', 'FocalLengthIn35mmFormat': 35, 'FileSize': 777,
                'Flash': 16, 'WhiteBalance': 'PRESET0', 'MeteringMode': 5, 'ExposureCompensation': -0.3,
                'Artist': 'Ann', 'Copyright': '(c) 2024'}]
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(stdout=json.dumps(payload)))
    data = facet.get_exif_data(str(path))
    assert data['camera_model'] == 'Cam'
    assert (data['focal_length_35mm'], data['file_size']) == (35, 777)
    assert (data['flash'], data['white_balance'], data['metering_mode']) == (16, None, 5)
    assert data['exposure_compensation'] == -0.3
    assert (data['artist'], data['copyright']) == ('Ann', '(c) 2024')


class _Tag:
    def __init__(self, value):
        self.values = [value]

    def __str__(self):
        return str(self.values[0])


def _exifread_tags(**overrides):
    tags = {'Image Model': 'Cam', 'EXIF FocalLengthIn35mmFilm': 50, 'EXIF ExposureBiasValue': 0.7,
            'EXIF Flash': 1, 'EXIF WhiteBalance': 1, 'EXIF MeteringMode': 5,
            'Image Artist': 'Ann', 'Image Copyright': '(c) 2024'}
    tags.update(overrides)
    return {name: _Tag(value) for name, value in tags.items()}


def _exifread_read(tmp_path, monkeypatch, tags):
    facet = _facet()
    exifread = pytest.importorskip('exifread')
    path = tmp_path / 'er.jpg'
    Image.new('RGB', (8, 8)).save(path)
    _no_exiftool(monkeypatch)
    monkeypatch.setattr(exifread, 'process_file', lambda f, details=False: tags)
    return facet.get_exif_data(str(path)), path


def test_exifread_fallback_reads_the_new_fields(tmp_path, monkeypatch):
    data, path = _exifread_read(tmp_path, monkeypatch, _exifread_tags())
    assert data['camera_model'] == 'Cam'
    assert data['file_size'] == path.stat().st_size
    assert data['exposure_compensation'] == 0.7
    assert (data['flash'], data['white_balance'], data['metering_mode']) == (1, 1, 5)
    assert (data['artist'], data['copyright']) == ('Ann', '(c) 2024')
    assert data['focal_length_35mm'] == 50


def test_exifread_fallback_clamps_out_of_domain_values(tmp_path, monkeypatch):
    tags = _exifread_tags(**{'EXIF ExposureBiasValue': 20.0, 'EXIF Flash': 200, 'EXIF WhiteBalance': 2,
                             'EXIF MeteringMode': 7, 'EXIF FocalLengthIn35mmFilm': 0})
    data, _ = _exifread_read(tmp_path, monkeypatch, tags)
    assert data['camera_model'] == 'Cam'
    assert all(data[key] is None for key in ('exposure_compensation', 'flash', 'white_balance',
                                             'metering_mode', 'focal_length_35mm'))


def _pillow_read(tmp_path, monkeypatch, ifd0, exif_ifd):
    facet = _facet()
    path = tmp_path / 'pil.jpg'
    exif = Image.Exif()
    exif.update(ifd0)
    exif.get_ifd(0x8769).update(exif_ifd)
    Image.new('RGB', (8, 8)).save(path, exif=exif)
    _no_exiftool(monkeypatch)
    monkeypatch.setitem(sys.modules, 'exifread', None)
    return facet.get_exif_data(str(path)), path


def test_pillow_fallback_reads_the_new_fields(tmp_path, monkeypatch):
    data, path = _pillow_read(tmp_path, monkeypatch, {0x013B: 'Ann', 0x8298: '(c) 2024'},
                              {0x9204: -1.0, 0x9209: 16, 0xA403: 0, 0x9207: 2, 0xA405: 28})
    assert data['file_size'] == path.stat().st_size
    assert (data['artist'], data['copyright']) == ('Ann', '(c) 2024')
    assert data['exposure_compensation'] == -1.0
    assert (data['flash'], data['white_balance'], data['metering_mode']) == (16, 0, 2)
    assert data['focal_length_35mm'] == 28


def test_pillow_fallback_clamps_out_of_domain_values(tmp_path, monkeypatch):
    data, _ = _pillow_read(tmp_path, monkeypatch, {},
                           {0x9204: 18.0, 0x9209: 300, 0xA403: 3, 0x9207: 9, 0xA405: 0})
    assert all(data[key] is None for key in ('exposure_compensation', 'flash', 'white_balance',
                                             'metering_mode', 'focal_length_35mm'))


def test_base_record_carries_the_new_exif_columns():
    pytest.importorskip('imagehash')
    pytest.importorskip('cv2')
    from processing.multi_pass import ChunkedMultiPassProcessor
    proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
    exif = {'file_size': 4096, 'exposure_compensation': -0.7, 'flash': 9, 'white_balance': 1,
            'metering_mode': 5, 'artist': 'Ann', 'copyright': '(c) 2024'}
    record = proc._base_record('/p/a.jpg', {'width': 10, 'height': 20, 'exif': exif})
    assert {column: record[column] for column in EXIF_META_COLUMNS} == exif


def _partial_facet(db):
    facet = _facet()
    facet._pending_centroid_persons = set()
    facet.db_path = db
    facet.config = SimpleNamespace(version_hash='v1')
    return facet


def test_save_photos_partial_binds_null_for_unread_exif_columns(tmp_path):
    from tests.test_rescan_preservation import _base_result
    db = str(tmp_path / 'partial.db')
    init_database(db)
    facet = _partial_facet(db)
    with_values = _base_result('/p/a.jpg', 5.0)
    with_values.update(file_size=999, exposure_compensation=-1.3, flash=9, white_balance=0,
                       metering_mode=2, artist='Ann', copyright='(c) 2024')
    bare = _base_result('/p/b.jpg', 5.0)
    assert not set(EXIF_META_COLUMNS) & set(bare)
    img = Image.new('RGB', (8, 8))
    facet.save_photos_partial([(with_values, img, ('aggregate',)), (bare, img, ('aggregate',))],
                              refresh_faces=False)
    with get_connection(db, row_factory=True) as conn:
        rows = {r['path']: dict(r) for r in conn.execute('SELECT * FROM photos')}
    assert {column: rows['/p/a.jpg'][column] for column in EXIF_META_COLUMNS} == {
        'file_size': 999, 'exposure_compensation': -1.3, 'flash': 9, 'white_balance': 0,
        'metering_mode': 2, 'artist': 'Ann', 'copyright': '(c) 2024'}
    assert all(rows['/p/b.jpg'][column] is None for column in EXIF_META_COLUMNS)
