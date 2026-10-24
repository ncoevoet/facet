"""Portable organization metadata survives explicit export/import."""
import sqlite3
from pathlib import Path
import pytest
from db.schema import init_database
from processing.xmp_export import XmpRating, build_xmp, write_metadata, exiftool_available
from processing.xmp_import import parse_sidecar, import_sidecars


def database(tmp_path):
    db = tmp_path / 'test.db'
    init_database(str(db))
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.mark.parametrize('decision', ['kept', 'rejected', 'undecided'])
def test_roundtrip_decision_gps(tmp_path, decision):
    image = tmp_path / 'image.jpg'
    sidecar = Path(str(image) + '.xmp')
    rating = XmpRating.from_row(dict(star_rating=4, is_favorite=1,
        is_kept=decision == 'kept', is_rejected=decision == 'rejected',
        gps_manually_set=1, gps_latitude=-33.25, gps_longitude=151.5))
    sidecar.write_text(build_xmp(rating))
    parsed = parse_sidecar(str(sidecar))
    assert parsed['review_decision'] == decision
    assert parsed['gps'] == (-33.25, 151.5)
    conn = database(tmp_path)
    conn.execute('INSERT INTO photos(path) VALUES (?)', (str(image),))
    assert import_sidecars(conn)['updated'] == 1
    row = conn.execute('SELECT * FROM photos').fetchone()
    assert (row['is_kept'], row['is_rejected']) == (decision == 'kept', decision == 'rejected')
    assert (row['star_rating'], row['is_favorite']) == ((0, 0) if decision == 'rejected' else (4, 1))
    assert (row['gps_latitude'], row['gps_longitude'], row['gps_manually_set']) == (-33.25, 151.5, 1)
    assert import_sidecars(conn)['unchanged'] == 1


def test_manual_clear_and_conflict_policy(tmp_path):
    image = tmp_path / 'image.jpg'
    Path(str(image) + '.xmp').write_text(build_xmp(XmpRating.from_row({'gps_manually_set': 1})))
    conn = database(tmp_path)
    conn.execute('INSERT INTO photos(path,gps_latitude,gps_longitude,gps_manually_set) VALUES (?,1,2,1)', (str(image),))
    import_sidecars(conn)
    assert conn.execute('SELECT gps_latitude FROM photos').fetchone()[0] == 1
    import_sidecars(conn, overwrite_manual_gps=True)
    assert tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos').fetchone()) == (None, None, 1)


def test_scanned_coordinates_are_not_exported(tmp_path):
    sidecar = tmp_path / 'photo.xmp'
    sidecar.write_text(build_xmp(XmpRating.from_row({'gps_latitude': 10, 'gps_longitude': 20})))
    assert parse_sidecar(str(sidecar))['gps'] is None


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_real_exiftool_preserves_foreign_metadata_and_original(tmp_path):
    import subprocess
    from PIL import Image
    image = tmp_path / 'image.jpg'
    Image.new('RGB', (20, 20), 'blue').save(image)
    original = image.read_bytes()
    sidecar = Path(str(image) + '.xmp')
    subprocess.run(['exiftool', '-o', str(sidecar), '-XMP-dc:Creator=Foreign artist', str(image)], check=True, capture_output=True)
    for decision in ['kept', 'rejected', 'undecided']:
        write_metadata(str(image), XmpRating.from_row(dict(is_kept=decision == 'kept',
            is_rejected=decision == 'rejected', gps_manually_set=1,
            gps_latitude=-33.25, gps_longitude=151.5)))
        parsed = parse_sidecar(str(sidecar))
        assert parsed['review_decision'] == decision
        assert parsed['gps'] == (-33.25, 151.5)
        assert 'Foreign artist' in sidecar.read_text()
        assert image.read_bytes() == original


def test_fallback_repeated_export_import(tmp_path, monkeypatch):
    monkeypatch.setattr('processing.xmp_export.exiftool_available', lambda: False)
    image = tmp_path / 'fallback.jpg'
    image.write_bytes(b'original')
    write_metadata(str(image), XmpRating.from_row({'is_kept': 1}))
    write_metadata(str(image), XmpRating.from_row({'is_kept': 0, 'gps_manually_set': 1}))
    conn = database(tmp_path)
    conn.execute('INSERT INTO photos(path,is_kept,gps_latitude,gps_longitude) VALUES (?,1,1,2)', (str(image),))
    import_sidecars(conn)
    row = conn.execute('SELECT * FROM photos').fetchone()
    assert row['is_kept'] == 0
    assert row['gps_manually_set'] == 1
    assert row['gps_latitude'] is None


@pytest.mark.parametrize('state,latitude,longitude', [
    ('set', '91,0N', '10,0E'), ('set', '10,0N', '181,0E'),
    ('set', '10,60N', '10,0E'), ('set', 'NaN', '10,0E'),
    ('set', '10,0E', '10,0N'), ('set', '10,0N', ''), ('invalid', '10,0N', '10,0E'),
])
def test_invalid_override_does_not_clear(tmp_path, state, latitude, longitude):
    from xml.etree import ElementTree as ET
    from processing.xmp_export import NS_FACET, NS_EXIF, NS_RDF
    packet = ET.fromstring(build_xmp(XmpRating()))
    desc = packet.find(f'.//{{{NS_RDF}}}Description')
    desc.set(f'{{{NS_FACET}}}GPSState', state)
    desc.set(f'{{{NS_EXIF}}}GPSLatitude', latitude)
    desc.set(f'{{{NS_EXIF}}}GPSLongitude', longitude)
    sidecar = tmp_path / 'invalid.xmp'
    sidecar.write_bytes(ET.tostring(packet))
    assert parse_sidecar(str(sidecar))['gps'] is None


def test_user_decision_is_private_and_absent_fields_preserve_state(tmp_path, monkeypatch):
    monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: True)
    image = tmp_path / 'user.jpg'
    conn = database(tmp_path)
    conn.execute('INSERT INTO photos(path,is_rejected,gps_latitude,gps_longitude,gps_manually_set) VALUES (?,1,1,2,1)', (str(image),))
    conn.execute('INSERT INTO user_preferences(user_id,photo_path,is_kept) VALUES (?,?,1)', ('bob', str(image)))
    sidecar = Path(str(image) + '.xmp')
    sidecar.write_text(build_xmp(XmpRating.from_row({'is_kept': 1, 'star_rating': 3})))
    import_sidecars(conn, user_id='alice')
    assert tuple(conn.execute('SELECT is_kept,star_rating FROM user_preferences WHERE user_id="alice"').fetchone()) == (1,3)
    assert conn.execute('SELECT is_kept FROM user_preferences WHERE user_id="bob"').fetchone()[0] == 1
    assert tuple(conn.execute('SELECT is_rejected,gps_latitude FROM photos').fetchone()) == (1,1)
    sidecar.write_text('<x xmlns="adobe:ns:meta/"/>')
    import_sidecars(conn, user_id='alice')
    assert conn.execute('SELECT is_kept FROM user_preferences WHERE user_id="alice"').fetchone()[0] == 1


def test_named_user_import_export_cannot_touch_hidden_photos(tmp_path, monkeypatch):
    from processing.xmp_export import export_sidecars
    monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: True)
    monkeypatch.setattr('api.db_helpers.is_multi_user_enabled', lambda: True)
    visible = tmp_path / 'visible'
    visible.mkdir()
    monkeypatch.setattr('api.db_helpers.get_user_directories', lambda user: [str(visible)])
    conn = database(tmp_path)
    for image in (visible / 'yes.jpg', tmp_path / 'hidden.jpg'):
        image.write_bytes(b'original')
        conn.execute('INSERT INTO photos(path) VALUES (?)', (str(image),))
        Path(str(image) + '.xmp').write_text(build_xmp(XmpRating.from_row({'is_kept': 1, 'gps_manually_set': 1, 'gps_latitude': 1, 'gps_longitude': 2})))
    assert import_sidecars(conn, root=str(tmp_path), user_id='alice')['updated'] == 1
    assert conn.execute('SELECT gps_manually_set FROM photos WHERE path=?', (str(tmp_path / 'hidden.jpg'),)).fetchone()[0] == 0
    monkeypatch.setattr('processing.xmp_export.exiftool_available', lambda: False)
    assert export_sidecars(conn, root=str(tmp_path), user_id='alice')['written'] == 1


@pytest.fixture(autouse=True)
def _user_directories(tmp_path, monkeypatch):
    monkeypatch.setattr('api.db_helpers.get_user_directories', lambda user: [str(tmp_path)])


@pytest.mark.skipif(not exiftool_available(), reason='requires ExifTool')
def test_explicit_embed_sets_and_clears_both_gps_channels(tmp_path):
    import json
    import subprocess
    from PIL import Image
    image = tmp_path / 'embed.jpg'
    Image.new('RGB', (20, 20)).save(image)
    write_metadata(str(image), XmpRating.from_row({'gps_manually_set': 1, 'gps_latitude': -33.25, 'gps_longitude': 151.5}), embed_original=True)
    def metadata():
        return json.loads(subprocess.check_output(['exiftool', '-j', '-n', '-G1', str(image)]))[0]
    data = metadata()
    assert data['GPS:GPSLatitude'] == 33.25
    assert data['GPS:GPSLatitudeRef'] == 'S'
    assert data['GPS:GPSLongitudeRef'] == 'E'
    assert data['XMP-exif:GPSLatitude'] == -33.25
    # Database GPS from a scan must not overwrite coordinates already in the file.
    write_metadata(str(image), XmpRating.from_row({'gps_latitude': 1, 'gps_longitude': 2}), embed_original=True)
    assert metadata()['XMP-exif:GPSLatitude'] == -33.25
    write_metadata(str(image), XmpRating.from_row({'gps_manually_set': 1}), embed_original=True)
    data = metadata()
    assert not any(key in data for key in ('GPS:GPSLatitude', 'GPS:GPSLongitude', 'GPS:GPSLatitudeRef', 'GPS:GPSLongitudeRef', 'XMP-exif:GPSLatitude', 'XMP-exif:GPSLongitude'))
    assert parse_sidecar(str(image) + '.xmp')['gps'] == (None, None)


def test_sidecar_source_uses_file_mtime_not_metadata_date(tmp_path):
    import os
    from xml.etree import ElementTree as ET
    from processing.xmp_export import NS_XMP, NS_RDF
    image = tmp_path / 'source.jpg'
    conn = database(tmp_path)
    conn.execute('INSERT INTO photos(path) VALUES (?)', (str(image),))
    primary = Path(str(image) + '.xmp')
    primary.write_text(build_xmp(XmpRating.from_row({'is_kept': 1})))
    fallback = Path(str(image) + '.facet.xmp')
    tree = ET.fromstring(build_xmp(XmpRating(tags=['foreign keyword'])))
    tree.find(f'.//{{{NS_RDF}}}Description').set(f'{{{NS_XMP}}}MetadataDate', '2000-01-01T00:00:00Z')
    fallback.write_bytes(ET.tostring(tree))
    os.utime(primary, (100,100))
    os.utime(fallback, (200,200))
    import_sidecars(conn)
    assert conn.execute('SELECT is_kept FROM photos').fetchone()[0] == 0
    assert conn.execute('SELECT tag FROM photo_manual_tags').fetchone()[0] == 'foreign keyword'


def test_keep_is_manual_review_signal_for_unrated_score_mapping():
    rating = XmpRating.from_row({'is_kept': 1, 'aggregate': 9.5})
    rating.apply_score_mapping({'score_to_rating': {'enabled': True, 'only_when_unrated': True}})
    assert rating.star_rating == 0
    assert rating.is_favorite is False


def test_decision_only_import_preserves_stars_favorite(tmp_path):
    image = tmp_path / 'decision.jpg'
    conn = database(tmp_path)
    conn.execute('INSERT INTO photos(path,star_rating,is_favorite,is_kept) VALUES (?,4,1,1)', (str(image),))
    sidecar = Path(str(image) + '.xmp')
    sidecar.write_text('<x xmlns:facet="https://github.com/ncoevoet/facet/ns/1.0/" facet:ReviewDecision="undecided"/>')
    import_sidecars(conn)
    assert tuple(conn.execute('SELECT star_rating,is_favorite,is_kept,is_rejected FROM photos').fetchone()) == (4,1,0,0)
    sidecar.write_text('<x xmlns:facet="https://github.com/ncoevoet/facet/ns/1.0/" facet:ReviewDecision="rejected"/>')
    import_sidecars(conn)
    assert tuple(conn.execute('SELECT star_rating,is_favorite,is_kept,is_rejected FROM photos').fetchone()) == (0,0,0,1)


@pytest.mark.parametrize('user', [None, 'alice'])
def test_cli_export_effective_decision(tmp_path, monkeypatch, user):
    from processing.xmp_export import export_sidecars
    monkeypatch.setattr('api.config.is_multi_user_enabled', lambda: True)
    monkeypatch.setattr('processing.xmp_export.exiftool_available', lambda: False)
    image = tmp_path / 'cli.jpg'
    image.write_bytes(b'original')
    conn = database(tmp_path)
    conn.execute('INSERT INTO photos(path,is_kept) VALUES (?,1)', (str(image),))
    conn.execute('INSERT INTO user_preferences(user_id,photo_path,is_kept) VALUES (?,?,1)', ('alice', str(image)))
    assert export_sidecars(conn, user_id=user)['written'] == 1
    assert parse_sidecar(str(image) + '.xmp')['review_decision'] == 'kept'


@pytest.mark.parametrize('decision,external_rating,expected', [
    ('undecided', -1, (0, 1, 0)),
    ('kept', -1, (0, 1, 0)),
    ('rejected', 4, (4, 0, 0)),
])
def test_external_editor_review_changes_override_preserved_private_decision(
        tmp_path, decision, external_rating, expected):
    from xml.etree import ElementTree as ET
    from processing.xmp_export import NS_XMP, NS_RDF
    image = tmp_path / 'external.jpg'
    rating = XmpRating.from_row({'is_kept': decision == 'kept',
                                'is_rejected': decision == 'rejected'})
    packet = ET.fromstring(build_xmp(rating))
    desc = packet.find(f'.//{{{NS_RDF}}}Description')
    # Editors preserve unfamiliar namespace tags while changing standard fields.
    desc.set(f'{{{NS_XMP}}}Rating', str(external_rating))
    desc.attrib.pop(f'{{{NS_XMP}}}Label', None)
    Path(str(image) + '.xmp').write_bytes(ET.tostring(packet))
    conn = database(tmp_path)
    conn.execute('INSERT INTO photos(path,is_kept,is_rejected) VALUES (?,?,?)',
                 (str(image), rating.is_kept, rating.is_rejected))
    import_sidecars(conn)
    assert tuple(conn.execute('SELECT star_rating,is_rejected,is_kept FROM photos').fetchone()) == expected


def test_conflicting_standard_review_still_respects_legacy_timestamp_gate(tmp_path):
    from xml.etree import ElementTree as ET
    from processing.xmp_export import NS_XMP, NS_RDF
    image = tmp_path / 'older.jpg'
    packet = ET.fromstring(build_xmp(XmpRating(is_rejected=True)))
    desc = packet.find(f'.//{{{NS_RDF}}}Description')
    desc.set(f'{{{NS_XMP}}}Rating', '4')
    desc.set(f'{{{NS_XMP}}}MetadataDate', '2000-01-01T00:00:00Z')
    desc.attrib.pop(f'{{{NS_XMP}}}Label', None)
    Path(str(image) + '.xmp').write_bytes(ET.tostring(packet))
    conn = database(tmp_path)
    conn.execute('INSERT INTO photos(path,star_rating,is_favorite,is_kept,scanned_at) VALUES (?,5,1,1,?)',
                 (str(image), '2020-01-01T00:00:00Z'))
    import_sidecars(conn)
    assert tuple(conn.execute('SELECT star_rating,is_favorite,is_rejected,is_kept FROM photos').fetchone()) == (5,1,0,1)


@pytest.mark.parametrize('latitude,longitude,expected', [
    ('48,51N', '2,21E', (48.85, 2.35)),
    ('48,51N', None, None), (None, '2,21E', None),
    ('invalid', '2,21E', None), ('91N', '2E', None),
    ('48N', '', None), (None, None, (None, None)),
    ('', '  ', (None, None)),
])
@pytest.mark.parametrize('manual,overwrite', [(False, False), (True, False), (True, True)])
def test_exported_clear_external_coordinates_import(tmp_path, monkeypatch, latitude, longitude, expected, manual, overwrite):
    from xml.etree import ElementTree as ET
    from processing.xmp_export import NS_EXIF, NS_RDF
    monkeypatch.setattr('processing.xmp_export.exiftool_available', lambda: False)
    image = tmp_path / 'external-gps.jpg'
    image.write_bytes(b'original')
    write_metadata(str(image), XmpRating.from_row({'gps_manually_set': 1}))
    sidecar = Path(str(image) + '.xmp')
    packet = ET.fromstring(sidecar.read_bytes())
    desc = packet.find(f'.//{{{NS_RDF}}}Description')
    for name, value in [('GPSLatitude', latitude), ('GPSLongitude', longitude)]:
        if value is not None:
            desc.set(f'{{{NS_EXIF}}}{name}', value)
    sidecar.write_bytes(ET.tostring(packet))
    assert parse_sidecar(str(sidecar))['gps'] == expected
    conn = database(tmp_path)
    conn.execute('INSERT INTO photos(path,gps_latitude,gps_longitude,gps_manually_set) VALUES (?,10,20,?)', (str(image), int(manual)))
    import_sidecars(conn, overwrite_manual_gps=overwrite)
    actual = tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos').fetchone())
    assert actual == ((*expected, 1) if expected is not None and (not manual or overwrite) else (10, 20, int(manual)))
    assert image.read_bytes() == b'original'
