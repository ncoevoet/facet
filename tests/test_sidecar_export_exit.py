"""The CLI reports per-file export failures to its calling process."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from PIL import Image
import pytest

from db.schema import init_database


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('good,bad,missing,expected', [
    (0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 1), (1, 1, 0, 1), (0, 0, 1, 0),
])
def test_exit_and_counts_match_the_actual_export(tmp_path, good, bad, missing, expected):
    db = tmp_path / 'library.db'
    init_database(str(db))
    config = tmp_path / 'config.json'
    config.write_text('{}', encoding='utf-8')
    originals = {}
    for kind, count in [('good', good), ('bad', bad), ('missing', missing)]:
        for i in range(count):
            path = tmp_path / f'{kind}-{i}.jpg'
            if kind != 'missing':
                Image.new('RGB', (8, 8), (20, 40, 60)).save(path)
                originals[path] = path.read_bytes()
            if kind == 'bad':
                # A real filesystem refusal, without mocking the writer or CLI.
                Path(str(path) + '.xmp').mkdir()
            with sqlite3.connect(db) as conn:
                conn.execute('INSERT INTO photos(path,filename,star_rating) VALUES(?,?,3)',
                             (str(path), path.name))
    result = subprocess.run(
        [sys.executable, str(ROOT / 'facet.py'), '--db', str(db), '--config', str(config),
         '--export-sidecars', 'all'], cwd=tmp_path,
        env={**os.environ, 'FACET_CONFIG': str(config)},
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert f'{good} written, 0 embedded, {missing} missing, {bad} errors' in result.stdout + result.stderr
    assert all(path.read_bytes() == before for path, before in originals.items())
    assert len(list(tmp_path.glob('good-*.jpg.xmp'))) == good
    assert all(path.is_dir() for path in tmp_path.glob('bad-*.jpg.xmp'))
