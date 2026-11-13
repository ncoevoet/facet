"""File size + extra EXIF fields: parsing, domain checks, save round-trip, wire types."""
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

from db import get_connection, init_database
from exiftool.exiftool_batch import parse_exif_data

EXIFTOOL = shutil.which('exiftool')
NEW_COLUMNS = ('file_size', 'exposure_compensation', 'flash', 'white_balance',
               'metering_mode', 'artist', 'copyright')


def test_schema_has_the_new_columns(tmp_path):
    db = str(tmp_path / 'scratch.db')
    init_database(db)
    with get_connection(db, row_factory=False) as conn:
        names = [row[1] for row in conn.execute('PRAGMA table_info(photos)')]
    assert set(NEW_COLUMNS) <= set(names)
    assert names[-7:] == list(NEW_COLUMNS)


def test_parse_standard_values():
    parsed = parse_exif_data({'FileSize': 12345, 'ExposureCompensation': -0.7, 'Flash': 16,
                              'WhiteBalance': 1, 'MeteringMode': 5, 'Artist': ' Ann ',
                              'Copyright': '(c) 2024'})
    assert parsed['file_size'] == 12345
    assert parsed['exposure_compensation'] == -0.7
    assert (parsed['flash'], parsed['white_balance'], parsed['metering_mode']) == (16, 1, 5)
    assert parsed['artist'] == 'Ann'
    assert parsed['copyright'] == '(c) 2024'


def test_parse_missing_values_are_none():
    parsed = parse_exif_data({})
    assert all(parsed[key] is None for key in NEW_COLUMNS)


@pytest.mark.parametrize('raw', [
    {'WhiteBalance': 'PRESET0'}, {'WhiteBalance': 2}, {'MeteringMode': 7},
    {'MeteringMode': 'Multi-segment'}, {'Flash': 128}, {'Flash': -1}, {'Flash': 'Off'},
    {'ExposureCompensation': 16}, {'ExposureCompensation': 'inf'}, {'FileSize': 0},
    {'FileSize': '12 kB'}, {'Flash': 1.5},
])
def test_parse_rejects_out_of_domain(raw):
    parsed = parse_exif_data(raw)
    assert all(parsed[key] is None for key in NEW_COLUMNS)


def test_parse_metering_other_is_kept():
    assert parse_exif_data({'MeteringMode': 255})['metering_mode'] == 255


def test_parse_text_coercion():
    assert parse_exif_data({'Copyright': 2024})['copyright'] == '2024'
    assert parse_exif_data({'Artist': ['Ann', 'Bob']})['artist'] == 'Ann, Bob'
    assert parse_exif_data({'Artist': 'Ann\x00Bob'})['artist'] == 'Ann; Bob'
    assert parse_exif_data({'Artist': '  '})['artist'] is None
    assert parse_exif_data({'Copyright': ''})['copyright'] is None


@pytest.mark.skipif(EXIFTOOL is None, reason='exiftool not installed')
def test_real_exiftool_jpeg(tmp_path):
    from exiftool import get_exif_batch
    path = tmp_path / 'a.jpg'
    Image.new('RGB', (16, 16), (1, 2, 3)).save(path)
    subprocess.run([EXIFTOOL, '-overwrite_original', '-n', '-EXIF:Flash=1', '-EXIF:WhiteBalance=1',
                    '-EXIF:MeteringMode=5', '-EXIF:ExposureCompensation=0.7', '-Artist=Ann',
                    '-Copyright=(c) 2024', str(path)], check=True, capture_output=True)
    parsed = get_exif_batch([str(path)])[str(path.resolve())]
    assert parsed['file_size'] == path.stat().st_size
    assert parsed['exposure_compensation'] == 0.7
    assert (parsed['flash'], parsed['white_balance'], parsed['metering_mode']) == (1, 1, 5)
    assert (parsed['artist'], parsed['copyright']) == ('Ann', '(c) 2024')


def test_get_exif_data_fallback_reports_file_size(tmp_path, monkeypatch):
    pytest.importorskip('imagehash')
    pytest.importorskip('cv2')
    from processing.scorer import Facet
    path = tmp_path / 'plain.jpg'
    Image.new('RGB', (8, 8)).save(path)
    monkeypatch.setattr('exiftool.get_exif_single', lambda p: {'camera_model': None})
    monkeypatch.setattr('subprocess.run', lambda *a, **k: (_ for _ in ()).throw(OSError('no exiftool')))
    data = Facet.__new__(Facet).get_exif_data(str(path))
    assert data['file_size'] == path.stat().st_size
    assert data['flash'] is None and data['artist'] is None


def test_save_photos_batch_round_trips(tmp_path):
    pytest.importorskip('imagehash')
    pytest.importorskip('cv2')
    from tests.test_rescan_preservation import _base_result
    from processing.scorer import Facet
    db = str(tmp_path / 'save.db')
    init_database(db)
    facet = Facet.__new__(Facet)
    facet._pending_centroid_persons = set()
    facet.db_path = db
    facet.config = SimpleNamespace(version_hash='v1')
    with_values = _base_result('/p/a.jpg', 5.0)
    with_values.update(file_size=999, exposure_compensation=-1.3, flash=9, white_balance=0,
                       metering_mode=2, artist='Ann', copyright='(c) 2024')
    facet.save_photos_batch([with_values, _base_result('/p/b.jpg', 5.0)])
    with get_connection(db, row_factory=True) as conn:
        row = dict(conn.execute('SELECT * FROM photos WHERE path="/p/a.jpg"').fetchone())
        bare = dict(conn.execute('SELECT * FROM photos WHERE path="/p/b.jpg"').fetchone())
    assert {key: row[key] for key in NEW_COLUMNS} == {
        'file_size': 999, 'exposure_compensation': -1.3, 'flash': 9, 'white_balance': 0,
        'metering_mode': 2, 'artist': 'Ann', 'copyright': '(c) 2024'}
    assert all(bare[key] is None for key in NEW_COLUMNS)


def test_api_photo_serves_new_fields_with_wire_types(edition_client, seed_photos_prefix, tmp_path):
    path = str(tmp_path / 'wire.jpg')
    seed_photos_prefix(str(tmp_path), [dict(
        path=path, filename='wire.jpg', thumbnail=b'x', file_size=4096, exposure_compensation=0.7,
        flash=1, white_balance=0, metering_mode=5, artist='Ann', copyright='(c) 2024',
        focal_length=50.0, focal_length_35mm=75.0)])
    body = edition_client.get('/api/photo', params={'path': path}).json()
    assert body['file_size'] == 4096 and isinstance(body['file_size'], int)
    assert body['exposure_compensation'] == 0.7
    assert (body['flash'], body['white_balance'], body['metering_mode']) == (1, 0, 5)
    assert all(isinstance(body[key], int) for key in ('flash', 'white_balance', 'metering_mode'))
    assert (body['artist'], body['copyright']) == ('Ann', '(c) 2024')
    assert body['focal_length_35mm'] == 75.0


def test_pillow_fallback_bad_value_keeps_later_tags(tmp_path, monkeypatch):
    # Pillow yields this IFD as FocalLength, ExposureBiasValue, FNumber; an
    # unparsable bias must not end the loop and lose the FNumber after it.
    pytest.importorskip('imagehash')
    pytest.importorskip('cv2')
    import sys
    from processing.scorer import Facet
    path = tmp_path / 'bad-bias.jpg'
    exif = Image.Exif()
    exif.get_ifd(0x8769).update({0x829D: 2.8, 0x9204: 'not-a-number', 0x920A: 50.0})
    Image.new('RGB', (8, 8)).save(path, exif=exif)
    monkeypatch.setattr('exiftool.get_exif_single', lambda p: {'camera_model': None})
    monkeypatch.setattr('subprocess.run', lambda *a, **k: (_ for _ in ()).throw(OSError('no exiftool')))
    monkeypatch.setitem(sys.modules, 'exifread', None)
    data = Facet.__new__(Facet).get_exif_data(str(path))
    assert list(Image.open(path).getexif().get_ifd(0x8769)) == [0x920A, 0x9204, 0x829D]
    assert data['exposure_compensation'] is None
    assert (data['focal_length'], data['f_stop']) == (50.0, 2.8)
