"""On-demand score distributions respect the reader's scope and one snapshot."""
from contextlib import contextmanager
from unittest import mock

import pytest

from api.database import get_db

PREFIX = '/test_metric_distribution/'
MINE = PREFIX + 'mine/'


@pytest.fixture(autouse=True)
def _fresh_stats_cache():
    from api.config import invalidate_stats_cache
    invalidate_stats_cache()
    yield
    invalidate_stats_cache()


@contextmanager
def _visible_library():
    with mock.patch('api.db_helpers.is_multi_user_enabled', return_value=True), mock.patch(
            'api.db_helpers.get_user_directories', return_value=[MINE.rstrip('/')]):
        yield


@pytest.mark.parametrize('column', ['aesthetic', 'form_fractal', 'qrealign_score'])
def test_visible_library_category_and_current_buckets(regular_client, seed_people, column):
    for index, (value, category) in enumerate([(0, 'group-a'), (5, 'group-a'), (10, 'group-b')]):
        seed_people.photo(MINE, f'{index}.jpg', **{column: value, 'category': category})
    seed_people.photo(PREFIX + 'theirs/', 'hidden.jpg', **{column: 999, 'category': 'group-a'})
    with _visible_library():
        whole = regular_client.get('/api/stats/metric_distribution', params={'column': column})
        category = regular_client.get('/api/stats/metric_distribution', params={'column': column, 'category': 'group-a'})
    assert whole.status_code == category.status_code == 200
    assert whole.json()['count'] == 3 and category.json()['count'] == 2
    for response, maximum in [(whole, 10), (category, 5)]:
        distribution = response.json()['distribution']
        assert distribution['min'] == 0 and distribution['max'] == maximum
        assert distribution['column'] == column
        assert sum(distribution['buckets']) == response.json()['count']
        assert distribution['buckets'][0] == distribution['buckets'][-1] == 1


def test_constant_zero_and_missing_values(regular_client, seed_people):
    for index, value in enumerate([0, 0, None, float('inf'), float('-inf')]):
        seed_people.photo(MINE, f'{index}.jpg', form_fractal=value)
    with _visible_library():
        result = regular_client.get('/api/stats/metric_distribution', params={'column': 'form_fractal'}).json()
        empty = regular_client.get('/api/stats/metric_distribution', params={'column': 'form_fractal', 'category': 'absent'}).json()
    assert result == {'distribution': {'column': 'form_fractal', 'min': 0, 'max': 0, 'buckets': [2]}, 'count': 2}
    assert empty == {'distribution': None, 'count': 0}


def test_metric_identifier_and_auth_are_checked(regular_client, anonymous_client):
    for column in ['path', 'star_rating']:
        assert regular_client.get('/api/stats/metric_distribution', params={'column': column}).status_code == 422
    assert regular_client.get('/api/stats/metric_distribution', params={'column': 'aggregate);DELETE FROM photos;--'}).status_code == 422
    # require_authenticated refuses an anonymous caller whatever the viewer password is.
    assert anonymous_client.get('/api/stats/metric_distribution').status_code == 401


def test_bounds_and_buckets_share_snapshot(regular_client, seed_people):
    seed_people.photo(MINE, 'one.jpg', form_fractal=1)
    seed_people.photo(MINE, 'two.jpg', form_fractal=2)
    from api.routers import stats

    class Connection:
        def __init__(self, conn):
            self.conn = conn
            self.inserted = False

        def execute(self, sql, params=()):
            cursor = self.conn.execute(sql, params)
            if sql.startswith('SELECT MIN(') and not self.inserted:
                self.inserted = True
                with get_db() as writer, writer:
                    writer.execute('UPDATE photos SET form_fractal=100 WHERE path=?', (MINE + 'two.jpg',))
            return cursor

    @contextmanager
    def snapshot_connection():
        with get_db() as conn:
            yield Connection(conn)

    with _visible_library(), mock.patch.object(stats, 'get_db', snapshot_connection):
        result = regular_client.get('/api/stats/metric_distribution', params={'column': 'form_fractal'}).json()
    assert result['count'] == 2
    assert result['distribution']['max'] == 2
    assert sum(result['distribution']['buckets']) == 2
    with get_db() as conn:
        assert conn.execute('SELECT form_fractal FROM photos WHERE path=?', (MINE + 'two.jpg',)).fetchone()[0] == 100


@pytest.mark.parametrize('values,indices', [([-1e308, 0, 1e308], [0, 16, 31]), ([0, 1e307, 1e308], [0, 3, 31])])
def test_finite_extremes_do_not_overflow_buckets(regular_client, seed_people, values, indices):
    for index, value in enumerate(values):
        seed_people.photo(MINE, f'{index}.jpg', form_fractal=value)
    with _visible_library():
        response = regular_client.get('/api/stats/metric_distribution', params={'column': 'form_fractal'})
    assert response.status_code == 200
    buckets = response.json()['distribution']['buckets']
    assert sum(buckets) == len(values)
    assert [index for index, total in enumerate(buckets) if total] == indices


def test_repeat_reads_are_served_from_the_stats_cache_per_scope(regular_client, seed_people):
    """Form metrics have no index, so each uncached read walks every photo's overflow pages."""
    from api.config import invalidate_stats_cache
    from api.routers import stats
    seed_people.photo(MINE, 'one.jpg', form_fractal=1, category='group-a')
    seed_people.photo(MINE, 'two.jpg', form_fractal=2, category='group-b')
    opened = []

    @contextmanager
    def counting_connection():
        with get_db() as conn:
            opened.append(1)
            yield conn

    params = {'column': 'form_fractal'}
    with _visible_library(), mock.patch.object(stats, 'get_db', counting_connection):
        first = regular_client.get('/api/stats/metric_distribution', params=params).json()
        assert opened == [1]
        assert regular_client.get('/api/stats/metric_distribution', params=params).json() == first
        assert opened == [1], 'an identical read must not touch the database again'
        scoped = regular_client.get('/api/stats/metric_distribution', params={**params, 'category': 'group-a'}).json()
        assert opened == [1, 1] and scoped['count'] == 1, 'a category is a separate cache entry'
        with get_db() as writer, writer:
            writer.execute('UPDATE photos SET form_fractal=50 WHERE path=?', (MINE + 'two.jpg',))
        invalidate_stats_cache()
        refreshed = regular_client.get('/api/stats/metric_distribution', params=params).json()
    assert opened == [1, 1, 1] and refreshed['distribution']['max'] == 50
