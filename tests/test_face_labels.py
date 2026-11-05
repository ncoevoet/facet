"""Tests for optimization/face_labels.py (labels schema, sampler, labelme importer).

Every DB is a per-test temp file built with init_database; no test touches a library DB.
"""

import csv
import gc
import hashlib
import json
import sqlite3

import pytest
from PIL import Image

from db.schema import init_database
from optimization import face_labels as fl


def _sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def _labels_file(tmp_path, photos, version=1):
    p = tmp_path / 'labels.json'
    p.write_text(json.dumps({'version': version, 'photos': [
        {'path': a, 'width': w, 'height': h, 'faces': f} for a, w, h, f in photos]}))
    return str(p)


def test_load_labels_rejects_bad_boxes(tmp_path):
    with pytest.raises(ValueError, match='version'):
        fl.load_labels(_labels_file(tmp_path, [], version=2))
    with pytest.raises(ValueError, match='no area'):
        fl.load_labels(_labels_file(tmp_path, [('/a.jpg', 100, 100, [[10, 10, 10, 30]])]))
    with pytest.raises(ValueError, match='outside'):
        fl.load_labels(_labels_file(tmp_path, [('/a.jpg', 100, 100, [[10, 10, 101, 30]])]))


def test_roundtrip(tmp_path):
    photos = [('/a.jpg', 100, 80, [[1.0, 2.0, 30.0, 40.0]]), ('/b.jpg', 50, 50, [])]
    out = tmp_path / 'sub' / 'labels.json'
    fl.write_labels(str(out), photos)
    assert fl.load_labels(str(out)) == photos


def test_import_clips_out_of_frame_corners(tmp_path):
    assert fl.clip_box([-5, 10, 109, 50], 100, 80) == [0.0, 10.0, 100.0, 50.0]
    with pytest.raises(ValueError, match='no area'):
        fl.clip_box([120, 10, 140, 50], 100, 80)


def _labelme_session(tmp_path, shapes_by_index, size=(100, 80)):
    """Manifest with indices 0001.. and one labelme JSON per entry (None = leave the JSON out)."""
    session = tmp_path / 'session'
    session.mkdir()
    with open(session / 'manifest.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fl.MANIFEST_FIELDS)
        w.writeheader()
        for i, shapes in enumerate(shapes_by_index, 1):
            idx = f'{i:04d}'
            w.writerow({'index': idx, 'path': f'/lib/{idx}.jpg', 'kind': 'positive',
                        'width': size[0], 'height': size[1]})
            if shapes is not None:
                (session / f'{idx}.json').write_text(json.dumps(
                    {'imageWidth': size[0], 'imageHeight': size[1], 'shapes': shapes}))
    return str(session), str(session / 'manifest.csv'), str(tmp_path / 'labels.json')


def _rect(points, label='face', shape_type='rectangle'):
    return {'label': label, 'shape_type': shape_type, 'points': points}


def test_import_labelme_converts_rectangles(tmp_path):
    d, m, out = _labelme_session(tmp_path, [[_rect([[40, 30], [10, 5]]), _rect([[50, 50], [60, 70]])]])
    photos = fl.import_labelme(d, m, out)
    assert photos == [('/lib/0001.jpg', 100, 80, [[10.0, 5.0, 40.0, 30.0], [50.0, 50.0, 60.0, 70.0]])]
    assert fl.load_labels(out) == photos


def test_import_refuses_unlabelled_image(tmp_path):
    d, m, out = _labelme_session(tmp_path, [[], None, []])
    with pytest.raises(ValueError, match='0002'):
        fl.import_labelme(d, m, out)


def test_import_refuses_size_mismatch(tmp_path):
    d, m, out = _labelme_session(tmp_path, [[]])
    (tmp_path / 'session' / '0001.json').write_text(json.dumps({'imageWidth': 99, 'imageHeight': 80, 'shapes': []}))
    with pytest.raises(ValueError, match='manifest'):
        fl.import_labelme(d, m, out)


def test_zero_shapes_is_reviewed_negative(tmp_path):
    d, m, out = _labelme_session(tmp_path, [[]])
    assert fl.import_labelme(d, m, out) == [('/lib/0001.jpg', 100, 80, [])]


@pytest.mark.parametrize('shape', [_rect([[0, 0], [5, 5]], label='person'),
                                   _rect([[0, 0], [5, 5]], shape_type='polygon')])
def test_import_refuses_other_shapes_and_labels(tmp_path, shape):
    d, m, out = _labelme_session(tmp_path, [[shape]])
    with pytest.raises(ValueError, match='only rectangles'):
        fl.import_labelme(d, m, out)


@pytest.fixture
def sampler_db(tmp_path):
    db = str(tmp_path / 'lib.db')
    init_database(db)
    conn = sqlite3.connect(db)

    def add(name, face_count, focal, w=4000, h=3000, agg=5.0):
        conn.execute("INSERT INTO photos (path, filename, face_count, focal_length_35mm, image_width, "
                     "image_height, aggregate) VALUES (?,?,?,?,?,?,?)",
                     (f'/lib/{name}.jpg', f'{name}.jpg', face_count, focal, w, h, agg))
    for i in range(12):
        add(f'wide{i}', 5 + i % 3, 24, agg=i % 10)        # many faces, wide angle: eligible
        add(f'tele{i}', 6, 85, agg=i % 10)                # many faces but tele: not eligible
    for i in range(4):
        add(f'big{i}', 2 + i % 2, 50, w=6000, h=4000, agg=i % 10)   # 2-3 faces, 24 MP: eligible stratum
        add(f'small{i}', 2, 50, agg=i % 10)               # 2 faces, 12 MP: not eligible
    for i in range(10):
        add(f'none{i}', 0, 35, agg=i % 10)
    conn.commit()
    conn.close()
    gc.collect()
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.close()
    return db


def _loader(path):
    return Image.new('RGB', (64, 48), (len(path) % 255, 10, 10))


def test_sampler_picks_by_filters_and_is_deterministic(sampler_db, tmp_path):
    before = _sha(sampler_db)
    runs = [fl.sample_photos(sampler_db, str(tmp_path / f'out{i}'), n_pos=8, n_neg=4, loader=_loader)
            for i in range(2)]
    assert _sha(sampler_db) == before
    assert runs[0] == runs[1]
    pos = [m['path'] for m in runs[0] if m['kind'] == 'positive']
    neg = [m['path'] for m in runs[0] if m['kind'] == 'negative']
    assert 5 <= len(pos) <= 8 and 1 <= len(neg) <= 4   # stratified draws under-fill small buckets by design
    conn = sqlite3.connect(sampler_db)
    for p in pos:
        fc, focal, w, h = conn.execute("SELECT face_count, focal_length_35mm, image_width, image_height "
                                       "FROM photos WHERE path = ?", (p,)).fetchone()
        assert (fc >= 4 and focal <= 35) or (2 <= fc <= 3 and w * h >= fl.HIGH_RES_PIXELS), p
    assert 1 <= sum(1 for p in pos if '/big' in p) <= 2
    for p in neg:
        assert conn.execute("SELECT face_count FROM photos WHERE path = ?", (p,)).fetchone()[0] == 0
    conn.close()
    assert (tmp_path / 'out0' / 'images' / '0001.jpg').exists()
    assert [m['index'] for m in runs[0]] == [f'{i:04d}' for i in range(1, len(runs[0]) + 1)]


def test_sampler_refuses_non_empty_output(sampler_db, tmp_path):
    (tmp_path / 'busy').mkdir()
    (tmp_path / 'busy' / 'x').write_text('x')
    with pytest.raises(ValueError, match='not empty'):
        fl.sample_photos(sampler_db, str(tmp_path / 'busy'), n_pos=2, n_neg=1, loader=_loader)
