"""Historical votes stay intact while same-logical-photo pairs cannot train."""
import sqlite3
from pathlib import Path

import pytest

from db import logical_assets
from db.schema import init_database
from optimization.model_eval import fetch_decisive_pairs
from optimization.weight_optimizer import WeightOptimizer
from tests.test_weight_optimizer_sources import _seed


def _catalog(tmp_path, source='vote', winner='a'):
    database = str(tmp_path / 'training.db')
    init_database(database)
    paths = sorted(_seed(database, n_photos=4))
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        raw = str(Path(paths[1]).with_suffix('.CR2'))
        conn.execute('UPDATE photos SET path=?,filename=? WHERE path=?', (raw, Path(raw).name, paths[1]))
        paths[1] = raw
        key = logical_assets.create(conn, paths[:2], paths[0], visibility_sql='1=1')
        conn.executemany('INSERT INTO comparisons(photo_a_path,photo_b_path,winner,source) VALUES (?,?,?,?)', [
            (paths[0], paths[1], winner, source),
            (paths[0], paths[2], 'b', source),
            (paths[1], paths[3], 'tie', 'vote'),
        ])
        conn.commit()
    conn.close()
    return database, paths, key


@pytest.mark.parametrize('source', ['vote', 'rating', 'culling'])
@pytest.mark.parametrize('winner', ['a', 'b', 'tie'])
def test_training_reads_exclude_same_identity_and_preserve_original_votes(tmp_path, source, winner):
    database, paths, _ = _catalog(tmp_path, source, winner)
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        before = [tuple(row) for row in conn.execute('SELECT * FROM comparisons ORDER BY id')]
        optimizer = WeightOptimizer(database)
        comparisons, x_a, x_b, winners, weights = optimizer._fetch_comparison_data(conn)
        assert {(row['photo_a'], row['photo_b']) for row in comparisons} == {(paths[0], paths[2]), (paths[1], paths[3])}
        assert len(winners) == len(weights) == x_a.shape[0] == x_b.shape[0] == 2
        # A historical cross-photo vote still uses the representation judged;
        # choosing another primary does not rewrite its features or meaning.
        assert any(row['photo_a'] == paths[1] for row in comparisons)
        filtered = optimizer._fetch_comparison_data(conn, sources=[source])[0]
        assert len(filtered) == (2 if source == 'vote' else 1)
        pairs, ties = fetch_decisive_pairs(conn)
        assert pairs == [(paths[0], paths[2], 'b')]
        assert ties == 1
        assert [tuple(row) for row in conn.execute('SELECT * FROM comparisons ORDER BY id')] == before
        assert not conn.in_transaction


def test_evaluation_without_logical_schema_is_read_only():
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE comparisons(photo_a_path TEXT,photo_b_path TEXT,winner TEXT)')
        conn.executemany('INSERT INTO comparisons VALUES (?,?,?)', [('a', 'b', 'a'), ('a', 'a', 'tie')])
        conn.commit()
        before = list(conn.execute('SELECT * FROM sqlite_master'))
        assert fetch_decisive_pairs(conn) == ([('a', 'b', 'a')], 0)
        assert list(conn.execute('SELECT * FROM sqlite_master')) == before


def test_snapshot_preserves_caller_transaction_and_cleans_owned_failure():
    from comparison.training_scope import read_snapshot
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE marker(value INTEGER)')
        conn.commit()
        with pytest.raises(RuntimeError):
            with read_snapshot(conn):
                assert conn.in_transaction
                raise RuntimeError('fixture failure')
        assert not conn.in_transaction
        conn.execute('INSERT INTO marker VALUES (1)')
        with read_snapshot(conn):
            assert conn.execute('SELECT value FROM marker').fetchone()[0] == 1
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute('SELECT COUNT(*) FROM marker').fetchone()[0] == 0


def test_optimizer_uses_one_snapshot_during_external_group_and_feature_changes(tmp_path, monkeypatch):
    database, paths, _ = _catalog(tmp_path)
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        old_score = conn.execute('SELECT aesthetic FROM photos WHERE path=?', (paths[2],)).fetchone()[0]
        optimizer = WeightOptimizer(database)
        original = optimizer._metric_vector
        observed = {}

        def vector(row, category, *, mask_missing=False):
            observed[row['path']] = row['aesthetic']
            return original(row, category, mask_missing=mask_missing)

        monkeypatch.setattr(optimizer, '_metric_vector', vector)
        fired, errors = [], []

        def external_commit(statement):
            if fired or 'FROM comparisons c' not in statement or 'JOIN photos p1' not in statement:
                return
            fired.append(True)
            try:
                external = sqlite3.connect(database, timeout=2)
                try:
                    external.execute('DELETE FROM logical_asset_members WHERE photo_path=?', (paths[1],))
                    external.execute('UPDATE photos SET aesthetic=999 WHERE path=?', (paths[2],))
                    external.commit()
                finally:
                    external.close()
            except Exception as error:
                errors.append(error)

        conn.set_trace_callback(external_commit)
        try:
            comparisons = optimizer._fetch_comparison_data(conn)[0]
        finally:
            conn.set_trace_callback(None)
        assert fired and not errors
        assert len(comparisons) == 2
        assert observed[paths[2]] == old_score
        assert not conn.in_transaction
        assert conn.execute('SELECT aesthetic FROM photos WHERE path=?', (paths[2],)).fetchone()[0] == 999
        assert conn.execute('SELECT COUNT(*) FROM logical_asset_members WHERE photo_path=?', (paths[1],)).fetchone()[0] == 0
