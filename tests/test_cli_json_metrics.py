"""Real lightweight CLI export with synthetic SQL only and no neural imports."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from db.schema import init_database
from metric_columns import JSON_SCORE_COLUMNS, SCORE_RANGE_COLUMNS
from tests.conftest import symlink_or_skip
from tests.test_cli import _sanitized_env

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ('aggregate', 'aesthetic', 'comp_score', 'face_quality',
          'tech_sharpness', 'exposure_score', 'color_score')
# Independently named stored metrics from the model-backed sorting features.
MODEL_METRICS = (
    'learned_score', 'aesthetic', 'quality_score', 'aesthetic_iaa', 'liqe_score',
    'face_quality', 'face_quality_iqa', 'eye_sharpness', 'face_sharpness',
    'face_ratio', 'face_count', 'comp_score', 'isolation_bonus',
    'composition_pattern', 'subject_sharpness', 'subject_prominence',
    'subject_placement', 'bg_separation', 'narrative_moment_confidence',
    'qrealign_score', 'deqa_score', 'aesthetic_v25',
)
METADATA = ('path', 'filename', 'date_taken', 'category', 'tags', 'camera_model', 'lens_model')


def seeded_value(index):
    """A distinct number per metric column, so a column mix-up changes the export."""
    return 0.005 + index * 0.02


def database(path, *, extended=False, empty=False):
    if not extended:
        # Deliberate old schema: a pre-metric library that lacks the extended columns.
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE photos (' + ', '.join(
                [name + ' TEXT' for name in METADATA] + [name + ' REAL' for name in LEGACY]
                + ['iso INTEGER', 'f_stop REAL', 'focal_length REAL', 'shutter_speed TEXT',
                   'caption TEXT', 'thumbnail BLOB', 'clip_embedding BLOB', 'star_rating INTEGER']
            ) + ')')
    else:
        init_database(str(path))
    with sqlite3.connect(path) as conn:
        if not empty:
            for name, aggregate in (('high', 8), ('low', 3)):
                values = {column: seeded_value(index) for index, column in enumerate(
                    LEGACY if not extended else JSON_SCORE_COLUMNS)}
                values.update(path='/synthetic/' + name + '.jpg', filename=name + '.jpg',
                              date_taken=None, category='default', tags='manual,雪',
                              camera_model='camera', lens_model=None, aggregate=aggregate,
                              iso=400, f_stop=2.8, focal_length=50, shutter_speed='1/250',
                              caption='not a score', thumbnail=b'not an image', clip_embedding=b'not a feature', star_rating=5)
                if extended:
                    values.update(aesthetic_v25=None, deqa_score='retained text',
                                  composition_pattern='rule_of_thirds')
                columns = list(values)
                conn.execute('INSERT INTO photos (' + ','.join(columns) + ') VALUES ('
                             + ','.join('?' for _ in columns) + ')', list(values.values()))
    return path


def run_export(tmp_path, db, output=None):
    guard = tmp_path / 'guard'
    guard.mkdir(exist_ok=True)
    audit = tmp_path / 'import-audit.json'
    (guard / 'sitecustomize.py').write_text('''import atexit,importlib.abc,json,os,sys
BLOCKED={'torch','tensorflow','transformers','onnxruntime','pyiqa','insightface','open_clip','exllamav3','pynvml','amdsmi','cupy'}
class NoNeuralImports(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in BLOCKED:raise RuntimeError('neural import forbidden: '+fullname)
sys.meta_path.insert(0,NoNeuralImports())
def audit():
 with open(os.environ['CLI_IMPORT_AUDIT'],'w') as stream:json.dump(sorted(BLOCKED.intersection(sys.modules)),stream)
atexit.register(audit)
''')
    env = _sanitized_env({'PYTHONPATH': str(guard), 'FACET_VRAM_PROFILE': 'legacy',
                          'CLI_IMPORT_AUDIT': str(audit)})
    args = [sys.executable, str(ROOT / 'facet.py'), '--db', str(db), '--export-json']
    if output is not None:
        args.append(str(output))
    result = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert audit.exists() and json.loads(audit.read_text()) == []
    return result


def test_real_cli_exports_all_model_metrics_raw_values_and_no_schema_dump(tmp_path):
    db = database(tmp_path / 'library.db', extended=True)
    output = tmp_path / 'export.json'
    with sqlite3.connect(db) as conn:
        before = conn.execute('SELECT * FROM photos ORDER BY path').fetchall()
    result = run_export(tmp_path, db, output)
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text())
    assert list(payload) == ['photos', 'count'] and payload['count'] == 2
    assert [photo['filename'] for photo in payload['photos']] == ['high.jpg', 'low.jpg']
    for photo in payload['photos']:
        assert list(photo) == ['path', 'filename', 'date_taken', 'category', 'scores', 'tags', 'camera_model', 'lens_model']
        scores = photo['scores']
        assert list(scores)[:7] == list(LEGACY)
        assert set(MODEL_METRICS) <= scores.keys()
        assert set(JSON_SCORE_COLUMNS) <= scores.keys()
        for index, column in enumerate(JSON_SCORE_COLUMNS):
            if column == 'aggregate':
                assert scores[column] == (8 if photo['filename'] == 'high.jpg' else 3)
            elif column not in ('aesthetic_v25', 'deqa_score', 'composition_pattern'):
                assert scores[column] == seeded_value(index), column
        assert scores['aesthetic_v25'] is None
        assert scores['deqa_score'] == 'retained text'
        assert scores['composition_pattern'] == 'rule_of_thirds'
        assert photo['tags'] == 'manual,雪'
        assert not set(('iso', 'f_stop', 'focal_length', 'shutter_speed', 'star_rating',
                        'caption', 'thumbnail', 'clip_embedding')).intersection(scores)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT * FROM photos ORDER BY path').fetchall() == before


def test_legacy_schema_keeps_original_seven_and_omits_missing_optional_fields(tmp_path):
    db = database(tmp_path / 'legacy.db')
    output = tmp_path / 'legacy.json'
    result = run_export(tmp_path, db, output)
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text())
    assert payload['count'] == 2
    assert all(tuple(photo['scores']) == LEGACY for photo in payload['photos'])
    with sqlite3.connect(db) as conn:
        assert 'qrealign_score' not in {row[1] for row in conn.execute('PRAGMA table_info(photos)')}


def test_empty_auto_filename_keeps_envelope(tmp_path):
    result = run_export(tmp_path, database(tmp_path / 'empty.db', empty=True))
    assert result.returncode == 0, result.stderr
    outputs = list(tmp_path.glob('facet_export_*.json'))
    assert len(outputs) == 1 and json.loads(outputs[0].read_text()) == {'photos': [], 'count': 0}


@pytest.mark.parametrize('alias', ['same', 'symlink', 'hardlink', '-wal', '-shm', '-journal'])
def test_output_must_not_overwrite_source_database(tmp_path, alias):
    db = database(tmp_path / 'protected.db')
    output = (db if alias == 'same' else Path(str(db) + alias)
              if alias.startswith('-') else tmp_path / 'alias.json')
    if alias == 'symlink':
        symlink_or_skip(output, db)
    elif alias == 'hardlink':
        os.link(db, output)
    result = run_export(tmp_path, db, output)
    assert result.returncode == 1
    assert 'must not overwrite' in result.stderr and 'Traceback' not in result.stderr
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT count(*) FROM photos').fetchone()[0] == 2
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_non_finite_and_blob_scores_export_as_null_in_valid_json(tmp_path):
    db = database(tmp_path / 'odd.db', extended=True)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE photos SET liqe_score = 9e999 WHERE filename = 'high.jpg'")
        conn.execute("UPDATE photos SET qrealign_score = -9e999, deqa_score = x'00ff' WHERE filename = 'high.jpg'")
        conn.execute("UPDATE photos SET face_quality_iqa = x'0102' WHERE filename = 'low.jpg'")
    output = tmp_path / 'odd.json'
    result = run_export(tmp_path, db, output)
    assert result.returncode == 0, result.stderr
    text = output.read_text()
    assert 'Infinity' not in text and 'NaN' not in text
    by_name = {photo['filename']: photo['scores'] for photo in json.loads(text)['photos']}
    assert by_name['high.jpg']['liqe_score'] is None
    assert by_name['high.jpg']['qrealign_score'] is None and by_name['high.jpg']['deqa_score'] is None
    assert by_name['low.jpg']['face_quality_iqa'] is None


def test_gallery_registry_public_name_and_exif_separation():
    from api.routers import gallery
    assert gallery.SCORE_RANGE_COLUMNS is SCORE_RANGE_COLUMNS
    assert not {'iso', 'f_stop', 'focal_length', 'shutter_speed'}.intersection(
        column for column, *_ in SCORE_RANGE_COLUMNS)


def test_writer_emits_first_row_before_fetching_next():
    import io
    from facet import write_json_export

    stream = io.StringIO()
    row = dict.fromkeys(METADATA + LEGACY)
    row.update(path='/synthetic/first.jpg', filename='first.jpg', aggregate=8)

    class Connection:
        def execute(self, sql):
            if sql.startswith('PRAGMA'):
                return [(index, name) for index, name in enumerate(METADATA + LEGACY)]
            assert 'ORDER BY aggregate DESC' in sql
            return self.rows()

        def rows(self):
            yield row
            assert '"filename": "first.jpg"' in stream.getvalue()
            yield dict(row, path='/synthetic/second.jpg', filename='second.jpg', aggregate=3)

    assert write_json_export(Connection(), stream) == 2
    assert json.loads(stream.getvalue())['count'] == 2
