"""Real SQLite regression coverage for the NumPy fallback matrix cache."""
import asyncio
import sqlite3
import sys
import threading

import aiosqlite
import numpy as np
import pytest

from api.change_token import close_change_token_sentinels
from api.routers import search
from db.schema import PHOTOS_COLUMNS, _build_create_table_sql, init_database


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    monkeypatch.setattr(search, '_embedding_cache', None)
    monkeypatch.setattr(search, '_embedding_cache_lock', asyncio.Lock())
    yield
    close_change_token_sentinels()


class ObservedLock:
    """Observe real lock admission without relying on wall-clock sleeps."""
    def __init__(self, expected):
        self.lock = asyncio.Lock()
        self.expected = expected
        self.attempts = 0
        self.reached = asyncio.Event()

    async def __aenter__(self):
        self.attempts += 1
        if self.attempts == self.expected:
            self.reached.set()
        await self.lock.acquire()
        return self

    async def __aexit__(self, *_):
        self.lock.release()

    def locked(self):
        return self.lock.locked()


def vector(axis):
    value = np.zeros(4, dtype=np.float32)
    value[axis] = 1
    return value.tobytes()


async def database(path):
    """A photos table built from the real schema; a file database also gets its revision triggers."""
    if str(path) != ':memory:':
        init_database(str(path), build_photo_indexes=False)
        # The schema builder leaves the file in WAL mode; the replacement tests
        # swap whole files, and a leftover -wal/-shm would alias the old one.
        with sqlite3.connect(path) as setup:
            setup.execute('PRAGMA journal_mode=DELETE')
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    if str(path) == ':memory:':
        await conn.execute(_build_create_table_sql('photos', PHOTOS_COLUMNS))
    await conn.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('a', vector(0), 1))
    await conn.commit()
    return conn


async def load(conn):
    async with search._embedding_snapshot(conn) as (reader, key, cacheable):
        return await search._load_snapshot_embedding_matrix(
            reader, key, 4, cacheable=cacheable, vis_sql='1=1', vis_params=[], cohort_key=None)


@pytest.mark.asyncio
async def test_external_same_count_embedding_update_and_delete_add(tmp_path):
    path = tmp_path / 'photos.db'
    conn = await database(path)
    try:
        first, _ = await load(conn)
        with sqlite3.connect(path) as writer:
            writer.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        second, paths = await load(conn)
        np.testing.assert_array_equal(second, [np.frombuffer(vector(1), dtype=np.float32)])
        assert second is not first
        with sqlite3.connect(path) as writer:
            writer.execute('DELETE FROM photos')
            writer.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('b', vector(2), 1))
        third, paths = await load(conn)
        assert paths == ['b']
        np.testing.assert_array_equal(third, [np.frombuffer(vector(2), dtype=np.float32)])
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_database_identity_and_stable_reads_across_connections(tmp_path):
    one = await database(tmp_path / 'one.db')
    two = await database(tmp_path / 'two.db')
    reader = await aiosqlite.connect(tmp_path / 'one.db')
    reader.row_factory = aiosqlite.Row
    try:
        await two.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        await two.commit()
        first, _ = await load(one)
        reused, _ = await load(reader)
        assert reused is first
        second, _ = await load(two)
        assert second is not first
        np.testing.assert_array_equal(second, [np.frombuffer(vector(1), dtype=np.float32)])
    finally:
        await one.close()
        await two.close()
        await reader.close()


@pytest.mark.asyncio
async def test_memory_databases_and_own_writes():
    one = await database(':memory:')
    two = await database(':memory:')
    try:
        first, _ = await load(one)
        np.testing.assert_array_equal((await load(one))[0], first)
        await one.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        await one.commit()
        changed, _ = await load(one)
        np.testing.assert_array_equal(changed, [np.frombuffer(vector(1), dtype=np.float32)])
        other, _ = await load(two)
        np.testing.assert_array_equal(other, [np.frombuffer(vector(0), dtype=np.float32)])
    finally:
        await one.close()
        await two.close()


@pytest.mark.asyncio
async def test_transaction_result_does_not_poison_shared_cache(tmp_path):
    conn = await database(tmp_path / 'photos.db')
    try:
        first, _ = await load(conn)
        await conn.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        pending, _ = await load(conn)
        np.testing.assert_array_equal(pending, [np.frombuffer(vector(1), dtype=np.float32)])
        await conn.rollback()
        assert (await load(conn))[0] is first
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_concurrent_misses_build_once(tmp_path, monkeypatch):
    conn = await database(tmp_path / 'photos.db')
    started = threading.Event()
    release = threading.Event()
    original = search._build_embedding_matrix
    builds = []

    def blocked_build(*args, **kwargs):
        builds.append(1)
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(search, '_build_embedding_matrix', blocked_build)
    lock = ObservedLock(5)
    monkeypatch.setattr(search, '_embedding_cache_lock', lock)
    tasks = [asyncio.create_task(load(conn)) for _ in range(5)]
    try:
        assert await asyncio.to_thread(started.wait, 5)
        await asyncio.wait_for(lock.reached.wait(), 5)
        release.set()
        results = await asyncio.gather(*tasks)
        assert len(builds) == 1
        assert all(matrix is results[0][0] for matrix, _ in results)
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await conn.close()


@pytest.mark.asyncio
async def test_commit_during_build_does_not_publish_under_new_token(tmp_path, monkeypatch):
    path = tmp_path / 'photos.db'
    conn = await database(path)
    await conn.execute('PRAGMA journal_mode=WAL')
    original = search._build_embedding_matrix

    def change_during_build(*args, **kwargs):
        with sqlite3.connect(path) as writer:
            writer.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        return original(*args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(search, '_build_embedding_matrix', change_during_build)
            first, _ = await load(conn)
        second, _ = await load(conn)
        assert second is not first
        np.testing.assert_array_equal(second, [np.frombuffer(vector(1), dtype=np.float32)])
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_empty_matrix_is_reused_until_embedding_appears(tmp_path, monkeypatch):
    conn = await database(tmp_path / 'photos.db')
    try:
        await conn.execute('DELETE FROM photos')
        await conn.commit()
        calls = []
        original = aiosqlite.Connection.execute

        def counted(reader, sql, *args, **kwargs):
            if sql.startswith('SELECT path, clip_embedding'):
                calls.append(1)
            return original(reader, sql, *args, **kwargs)

        # Observe real BLOB reads, including an empty matrix that never stacks.
        monkeypatch.setattr(aiosqlite.Connection, 'execute', counted)
        assert await load(conn) == (None, [])
        assert await load(conn) == (None, [])
        assert len(calls) == 1
        await conn.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('new', vector(0), 1))
        await conn.commit()
        matrix, paths = await load(conn)
        assert paths == ['new']
        assert matrix is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Windows refuses to replace a database file an open reader holds; the scenario is POSIX-only")
async def test_atomic_replacement_old_reader_cannot_poison_new_file(tmp_path):
    path = tmp_path / 'photos.db'
    replacement_path = tmp_path / 'replacement.db'
    old = await database(path)
    replacement = await database(replacement_path)
    fresh = None
    try:
        # Establish the old reader's open inode, and a cached old generation.
        first, _ = await load(old)
        await replacement.execute('DELETE FROM photos')
        await replacement.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('new', vector(1), 1))
        await replacement.commit()
        await replacement.close()
        replacement = None
        replacement_path.replace(path)
        # Prove this is a stale live SQLite handle, not a pathname-only mock.
        async with old.execute('SELECT path FROM photos') as cur:
            assert (await cur.fetchone())[0] == 'a'
        through_old, paths = await load(old)
        assert paths == ['new']
        assert through_old is not first
        fresh = await aiosqlite.connect(path)
        fresh.row_factory = aiosqlite.Row
        current, paths = await load(fresh)
        assert paths == ['new']
        assert current is through_old
        np.testing.assert_array_equal(current, [np.frombuffer(vector(1), dtype=np.float32)])
    finally:
        await old.close()
        if replacement is not None:
            await replacement.close()
        if fresh is not None:
            await fresh.close()


@pytest.mark.asyncio
async def test_cancelled_builder_drains_before_releasing_lock(tmp_path, monkeypatch):
    conn = await database(tmp_path / 'photos.db')
    started = threading.Event()
    release = threading.Event()
    original = search._build_embedding_matrix
    builds = []

    def blocked_build(*args, **kwargs):
        builds.append(1)
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(search, '_build_embedding_matrix', blocked_build)
    lock = ObservedLock(2)
    monkeypatch.setattr(search, '_embedding_cache_lock', lock)
    first = asyncio.create_task(load(conn))
    second = None
    try:
        assert await asyncio.to_thread(started.wait, 5)
        first.cancel()
        second = asyncio.create_task(load(conn))
        await asyncio.wait_for(lock.reached.wait(), 5)
        first.cancel()  # repeated request cancellation cannot release the guard
        checkpoint = asyncio.Event()
        asyncio.get_running_loop().call_soon(checkpoint.set)
        await checkpoint.wait()
        assert not first.done()
        assert not second.done()
        assert len(builds) == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        matrix, paths = await second
        assert paths == ['a']
        assert len(builds) == 1
        assert (await load(conn))[0] is matrix
        assert not search._embedding_cache_lock.locked()
    finally:
        release.set()
        await asyncio.gather(*(t for t in (first, second) if t is not None), return_exceptions=True)
        await conn.close()


@pytest.mark.asyncio
async def test_matrix_and_candidate_tokens_never_run_on_the_event_loop(tmp_path, monkeypatch, off_event_loop):
    from collections import OrderedDict
    from api import change_token
    path = tmp_path / 'off-loop.db'
    conn = await database(path)
    real_token = change_token.db_change_token
    calls = []

    def record_thread(db_path):
        calls.append(threading.get_ident())
        return real_token(db_path)

    guarded_token = off_event_loop(record_thread, 'database sentinel/token read ran on the event loop')

    async def unavailable(*args):
        return False

    async def no_tags(*args):
        return {}

    monkeypatch.setattr(change_token, 'db_change_token', guarded_token)
    monkeypatch.setattr(search, 'db_change_token', guarded_token)
    monkeypatch.setattr(search._database, 'DEFAULT_DB_PATH', str(path))
    monkeypatch.setattr(search, '_candidates_cache', OrderedDict())
    monkeypatch.setattr(search, '_candidate_model_key', lambda: ('test', 4))
    monkeypatch.setattr(search, '_encode_text', lambda _: np.frombuffer(vector(0), dtype=np.float32))
    monkeypatch.setattr(search, 'get_visibility_clause', lambda _: ('1=1', []))
    monkeypatch.setattr(search, '_check_vec_available', unavailable)
    monkeypatch.setattr(search, '_has_fts', unavailable)
    monkeypatch.setattr(search, '_manual_tag_search', no_tags)
    try:
        first, _ = await load(conn)
        reused, _ = await load(conn)
        assert reused is first
        candidates = await search.semantic_candidates(conn, 'off-loop-token', .5, None)
        assert await search.semantic_candidates(conn, 'off-loop-token', .5, None) is candidates
        assert len(calls) == 2  # Only candidate lookups use the synchronous broad token.
        assert set(calls).isdisjoint({threading.get_ident()})
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_rating_commit_reuses_embedding_matrix(tmp_path):
    path = tmp_path / 'ratings.db'
    conn = await database(path)
    try:
        first, _ = await load(conn)
        with sqlite3.connect(path) as writer:
            writer.execute('UPDATE photos SET star_rating=4')
        second, _ = await load(conn)
        assert second is first
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_distinct_cohorts_replace_single_matrix_and_recheck_visibility_before_limit(tmp_path, monkeypatch):
    path = tmp_path / 'users.db'
    conn = await database(path)
    builds = []
    original = search._build_embedding_matrix
    def count_builds(*args, **kwargs):
        builds.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(search, '_build_embedding_matrix', count_builds)
    try:
        await conn.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('b', vector(0), 2))
        await conn.commit()
        query = np.frombuffer(vector(0), dtype=np.float32)
        for owner, expected in [(1, {'a'}), (2, {'b'}), (1, {'a'})]:
            result = await search._search_numpy(conn, query, 1, .5, 'iso=?', [owner])
            assert set(result) == expected
        assert len(builds) == 3
        # ACL membership changes without changing stored embeddings.
        with sqlite3.connect(path) as writer:
            writer.execute('UPDATE photos SET iso=2 WHERE path="a"')
        assert await search._search_numpy(conn, query, None, .5, 'iso=?', [1]) == {}
        assert set(await search._search_numpy(conn, query, None, .5, 'iso=?', [2])) == {'a', 'b'}
        assert len(builds) == 4
    finally:
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Windows refuses to replace a database file an open reader holds; the scenario is POSIX-only")
async def test_replaced_database_uses_fresh_visibility_not_old_request_handle(tmp_path):
    path = tmp_path / 'replace-acl.db'
    old = await database(path)
    replacement_path = tmp_path / 'replacement.db'
    replacement = await database(replacement_path)
    try:
        await replacement.execute('UPDATE photos SET iso=2')
        await replacement.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('b', vector(0), 1))
        await replacement.commit()
        await replacement.close()
        replacement_path.replace(path)
        result = await search._search_numpy(old, np.frombuffer(vector(0), dtype=np.float32), None, .5,
                                            'iso=?', [1])
        assert set(result) == {'b'}
    finally:
        await old.close()


@pytest.mark.asyncio
async def test_fresh_reader_failure_never_publishes_an_empty_matrix(tmp_path, monkeypatch):
    conn = await database(tmp_path / 'failed-read.db')
    try:
        with monkeypatch.context() as patch:
            def unavailable(*args, **kwargs):
                raise sqlite3.OperationalError('read-only reader unavailable')
            patch.setattr(aiosqlite, 'connect', unavailable)
            with pytest.raises(sqlite3.OperationalError, match='reader unavailable'):
                await load(conn)
            assert search._embedding_cache is None
        matrix, paths = await load(conn)
        assert paths == ['a']
        assert matrix is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_shutdown_cancelling_builder_never_publishes_matrix(tmp_path, monkeypatch):
    conn = await database(tmp_path / 'shutdown.db')
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original_build = search._build_embedding_matrix
    def blocked_build(*args, **kwargs):
        started.set()
        try:
            assert release.wait(5)
            return original_build(*args, **kwargs)
        finally:
            finished.set()
    monkeypatch.setattr(search, '_build_embedding_matrix', blocked_build)
    request = asyncio.create_task(load(conn))
    children = []
    try:
        assert await asyncio.to_thread(started.wait, 5)
        children = [t for t in asyncio.all_tasks() if t not in (request, asyncio.current_task())]
        assert len(children) == 1
        children[0].cancel()  # Event-loop shutdown also cancels child worker tasks.
        with pytest.raises(asyncio.CancelledError):
            await request
        assert search._embedding_cache is None
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
        await asyncio.gather(request, *children, return_exceptions=True)
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Windows refuses to replace a database file an open reader holds; the scenario is POSIX-only")
async def test_replacement_between_matrix_and_visibility_keeps_one_snapshot(tmp_path, monkeypatch):
    path, replacement_path = tmp_path / 'live.db', tmp_path / 'replacement.db'
    old, replacement = await database(path), await database(replacement_path)
    try:
        await old.execute('UPDATE photos SET iso=2')
        await old.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('visible-other', vector(1), 1))
        await old.commit()
        await replacement.execute('UPDATE photos SET clip_embedding=?,iso=1', (vector(1),))
        await replacement.commit()
        await replacement.close()
        original = search._load_snapshot_embedding_matrix
        replaced = False

        async def replace_after_matrix(reader, key, dimension, **kwargs):
            nonlocal replaced
            result = await original(reader, key, dimension, **kwargs)
            if not replaced:
                replacement_path.replace(path)
                replaced = True
            return result

        monkeypatch.setattr(search, '_load_snapshot_embedding_matrix', replace_after_matrix)
        query = np.frombuffer(vector(0), dtype=np.float32)
        # Old a is private; replacement a is visible but below threshold. Mixing
        # old vectors with new ACLs incorrectly returned {'a': 1.0} before this fix.
        assert await search._search_numpy(old, query, 1, .5, 'iso=?', [1]) == {}
        assert await search._search_numpy(old, query, None, .5, 'iso=?', [1]) == {}
        assert set(await search._search_numpy(old, np.frombuffer(vector(1), dtype=np.float32), 1, .5,
                                               'iso=?', [1])) == {'a'}
    finally:
        await old.close()
        await replacement.close()


@pytest.mark.asyncio
async def test_search_own_uncommitted_vectors_and_visibility_are_never_shared(tmp_path):
    path = tmp_path / 'own-write.db'
    writer = await database(path)
    observer = await aiosqlite.connect(path)
    observer.row_factory = aiosqlite.Row
    try:
        first, _ = await load(observer)
        await writer.execute('UPDATE photos SET clip_embedding=?,iso=2', (vector(1),))
        assert set(await search._search_numpy(writer, np.frombuffer(vector(1), dtype=np.float32), 1, .5,
                                               'iso=?', [2])) == {'a'}
        assert search._embedding_cache['matrix'] is first
        assert writer.in_transaction  # Search must not roll back caller-owned writes.
        assert set(await search._search_numpy(observer, np.frombuffer(vector(0), dtype=np.float32), 1, .5,
                                               '1=1', [])) == {'a'}
        await writer.rollback()
        assert (await load(writer))[0] is first
    finally:
        await writer.close()
        await observer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['table', 'row'])
async def test_old_readonly_revision_state_is_uncached_without_migration(tmp_path, missing):
    path = tmp_path / 'old.db'
    conn = await database(path)
    try:
        await conn.execute('DROP TABLE embedding_cache_revision' if missing == 'table'
                           else 'DELETE FROM embedding_cache_revision')
        await conn.commit()
        first, paths = await load(conn)
        second, again = await load(conn)
        assert paths == again == ['a']
        assert first is not second
        assert search._embedding_cache is None
        assert set(await search._search_numpy(conn, np.frombuffer(vector(0), dtype=np.float32), 1, .5,
                                               'iso=?', [1])) == {'a'}
        with sqlite3.connect(path) as verify:
            if missing == 'table':
                assert verify.execute("SELECT name FROM sqlite_master WHERE name='embedding_cache_revision'").fetchall() == []
            else:
                assert verify.execute('SELECT * FROM embedding_cache_revision').fetchall() == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_rebuilt_photos_schema_cannot_reuse_an_unchanged_revision(tmp_path):
    from db.embedding_revision import init_schema
    path = tmp_path / 'rebuilt.db'
    conn = await database(path)
    try:
        first, _ = await load(conn)
        with sqlite3.connect(path) as writer:
            before = writer.execute('SELECT revision FROM embedding_cache_revision WHERE id=1').fetchone()[0]
            writer.execute('DROP TABLE photos')
            writer.execute('CREATE TABLE photos(path TEXT PRIMARY KEY, clip_embedding BLOB, iso INTEGER)')
            writer.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('new', vector(1), 1))
            init_schema(writer)
            assert writer.execute('SELECT revision FROM embedding_cache_revision WHERE id=1').fetchone()[0] == before
        matrix, paths = await load(conn)
        assert matrix is not first
        assert paths == ['new']
        np.testing.assert_array_equal(matrix, [np.frombuffer(vector(1), dtype=np.float32)])
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_missing_revision_trigger_disables_reuse(tmp_path):
    path = tmp_path / 'missing-trigger.db'
    conn = await database(path)
    try:
        with sqlite3.connect(path) as writer:
            writer.execute('DROP TRIGGER embedding_cache_photos_update')
        first, _ = await load(conn)
        with sqlite3.connect(path) as writer:
            writer.execute('UPDATE photos SET clip_embedding=?', (vector(1),))
        matrix, _ = await load(conn)
        assert matrix is not first
        np.testing.assert_array_equal(matrix, [np.frombuffer(vector(1), dtype=np.float32)])
    finally:
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('restricted', [False, True])
@pytest.mark.parametrize('bad', [b'bad', 'not a blob'])
async def test_malformed_vector_cannot_break_authorized_cohort(tmp_path, bad, restricted):
    conn = await database(tmp_path / 'malformed.db')
    try:
        await conn.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('private-bad', bad, 2))
        await conn.commit()
        result = await search._search_numpy(conn, np.frombuffer(vector(0), dtype=np.float32), 1, .5,
                                            'iso=?' if restricted else '1=1', [1] if restricted else [])
        assert result == {'a': 1.0}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_requested_encoder_width_survives_mixed_library_before_scoped_limit(tmp_path, monkeypatch):
    from config.scoring_config import ScoringConfig
    from config_resolve import defaults_path

    path = tmp_path / 'mixed-model.db'
    conn = await database(path)
    matching = np.zeros(768, dtype=np.float32)
    matching[0], matching[1] = .8, .6
    hidden = np.zeros(768, dtype=np.float32)
    hidden[0] = 1
    different = np.zeros(1152, dtype=np.float32)
    different[0] = 1
    try:
        await conn.execute('DELETE FROM photos')
        await conn.executemany('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', [
            ('visible', matching.tobytes(), 1),
            *[(f'sample-{i}', hidden.tobytes(), 2) for i in range(999)],
            *[(f'newer-{i}', different.tobytes(), 2) for i in range(1001)],
        ])
        await conn.commit()
        monkeypatch.setattr(search._database, 'DEFAULT_DB_PATH', str(path))
        config = ScoringConfig(defaults_path(), validate=False)
        config.config.setdefault('models', {})['vram_profile'] = '16gb'
        monkeypatch.setattr(search, 'server_scoring_config', lambda: config)
        search._reset_clip_config_cache()
        # The actual bounded model-resolution sample selects768 although the
        # entire library's majority is1152. Filtering by global majority lost it.
        assert search._stored_embedding_dim() == 768
        assert search._resolve_clip_config()['embedding_dim'] == 768
        query = hidden.copy()
        result = await search._search_numpy(conn, query, 1, .5, 'iso=?', [1])
        assert set(result) == {'visible'}  # Hidden higher scores cannot consume LIMIT.
        assert result['visible'] == pytest.approx(.8)
        matrix = search._embedding_cache['matrix']
        assert matrix.shape == (1, 768)
        assert len(await search._search_numpy(conn, query, 1, .5, 'iso=?', [2])) == 1
        assert search._embedding_cache['matrix'] is not matrix
        assert search._embedding_cache['matrix'].shape == (999, 768)
        assert set(await search._search_numpy(conn, query, 1, .5, 'iso=?', [1])) == {'visible'}
        assert search._embedding_cache['matrix'].shape == (1, 768)
    finally:
        search._reset_clip_config_cache()
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('owner, expected_rows', [(1, 1), (99, 0)])
async def test_restricted_cold_search_reads_and_allocates_only_visible_vectors(tmp_path, monkeypatch, owner, expected_rows):
    from utils import embedding
    conn = await database(tmp_path / 'bounded-cohort.db')
    decoded, stacked, blob_reads = [], [], []
    original_decode = embedding.bytes_to_normalized_embedding
    original_build = search._build_embedding_matrix
    original_execute = aiosqlite.Connection.execute
    def decode(data, *args, **kwargs):
        decoded.append(data)
        return original_decode(data, *args, **kwargs)
    def build(rows, dimension):
        matrix, paths = original_build(rows, dimension)
        if matrix is not None:
            stacked.append(len(paths))
        return matrix, paths
    def execute(reader, sql, *args, **kwargs):
        if sql.startswith('SELECT path, clip_embedding'):
            blob_reads.append((sql, args))
        return original_execute(reader, sql, *args, **kwargs)
    monkeypatch.setattr(embedding, 'bytes_to_normalized_embedding', decode)
    monkeypatch.setattr(search, '_build_embedding_matrix', build)
    monkeypatch.setattr(aiosqlite.Connection, 'execute', execute)
    try:
        await conn.executemany('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)',
                              [(f'private-{i}', vector(1), 2) for i in range(256)])
        await conn.commit()
        result = await search._search_numpy(conn, np.frombuffer(vector(0), dtype=np.float32), 1, .5,
                                            'iso=?', [owner])
        assert result == ({'a': 1.0} if expected_rows else {})
        assert len(decoded) == expected_rows
        assert stacked == ([1] if expected_rows else [])
        assert len(blob_reads) == (1 if expected_rows else 0)
        if expected_rows:
            assert '(iso=?)' in blob_reads[0][0]
            assert blob_reads[0][1] == ([owner],)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_equal_access_sets_share_one_cohort_without_account_or_predicate_identity(tmp_path, monkeypatch, off_event_loop):
    conn = await database(tmp_path / 'equal-cohorts.db')
    builds, hash_threads = [], []
    original_build = search._build_embedding_matrix
    original_hash = search._visible_path_fingerprint
    def build(rows, dimension):
        matrix, paths = original_build(rows, dimension)
        builds.append(len(paths))
        return matrix, paths
    def record_thread(paths):
        hash_threads.append(threading.get_ident())
        return original_hash(paths)
    fingerprint = off_event_loop(record_thread, 'cohort fingerprint ran on the event loop')
    monkeypatch.setattr(search, '_build_embedding_matrix', build)
    monkeypatch.setattr(search, '_visible_path_fingerprint', fingerprint)
    try:
        await conn.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('private', vector(0), 2))
        await conn.commit()
        query = np.frombuffer(vector(0), dtype=np.float32)
        for predicate, params in [('iso=?', [1]), ('path=?', ['a']), ('iso IN (?,?)', [99, 1])]:
            assert await search._search_numpy(conn, query, 1, .5, predicate, params) == {'a': 1.0}
        assert builds == [1]
        assert len(hash_threads) == 3
        assert set(hash_threads).isdisjoint({threading.get_ident()})
        assert search._embedding_cache['paths'] == ['a']
    finally:
        await conn.close()



def test_cohort_fingerprint_is_order_independent_and_length_delimited():
    assert search._visible_path_fingerprint({'ab', 'c'}) != search._visible_path_fingerprint({'a', 'bc'})
    assert search._visible_path_fingerprint(['c', 'ab']) == search._visible_path_fingerprint(['ab', 'c'])
    assert search._visible_path_fingerprint(set()) != search._visible_path_fingerprint({''})


@pytest.mark.asyncio
async def test_unrestricted_cohort_needs_no_visibility_query_or_fingerprint(tmp_path, monkeypatch):
    conn = await database(tmp_path / 'full-cohort.db')
    def unexpected(*args):
        pytest.fail('Unrestricted cohort must not enumerate or hash ACL paths')
    monkeypatch.setattr(search, '_visible_embedding_paths', unexpected)
    monkeypatch.setattr(search, '_visible_path_fingerprint', unexpected)
    try:
        query = np.frombuffer(vector(0), dtype=np.float32)
        assert await search._search_numpy(conn, query, 1, .5, '1=1', []) == {'a': 1.0}
        matrix = search._embedding_cache['matrix']
        assert await search._search_numpy(conn, query, 1, .5, '1=1', []) == {'a': 1.0}
        assert search._embedding_cache['matrix'] is matrix
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_restricted_rating_commit_reuses_its_visible_cohort(tmp_path):
    path = tmp_path / 'scoped-rating.db'
    conn = await database(path)
    try:
        await conn.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('private', vector(1), 2))
        await conn.commit()
        query = np.frombuffer(vector(0), dtype=np.float32)
        assert await search._search_numpy(conn, query, 1, .5, 'iso=?', [1]) == {'a': 1.0}
        matrix = search._embedding_cache['matrix']
        with sqlite3.connect(path) as writer:
            writer.execute('UPDATE photos SET star_rating=4')
        assert await search._search_numpy(conn, query, 1, .5, 'iso=?', [1]) == {'a': 1.0}
        assert search._embedding_cache['matrix'] is matrix
        assert search._embedding_cache['paths'] == ['a']
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_same_count_acl_change_rebuilds_cohort_without_vector_revision_change(tmp_path):
    path = tmp_path / 'same-count-acl.db'
    conn = await database(path)
    try:
        await conn.execute('INSERT INTO photos(path,clip_embedding,iso) VALUES (?,?,?)', ('b', vector(1), 2))
        await conn.commit()
        assert await search._search_numpy(conn, np.frombuffer(vector(0), dtype=np.float32), 1, .5,
                                          'iso=?', [1]) == {'a': 1.0}
        old_matrix = search._embedding_cache['matrix']
        with sqlite3.connect(path) as writer:
            before = writer.execute('SELECT revision FROM embedding_cache_revision').fetchone()[0]
            writer.execute('UPDATE photos SET iso=CASE iso WHEN 1 THEN 2 ELSE 1 END')
            assert writer.execute('SELECT revision FROM embedding_cache_revision').fetchone()[0] == before
        assert await search._search_numpy(conn, np.frombuffer(vector(1), dtype=np.float32), 1, .5,
                                          'iso=?', [1]) == {'b': 1.0}
        assert search._embedding_cache['matrix'] is not old_matrix
        assert search._embedding_cache['paths'] == ['b']
    finally:
        await conn.close()
