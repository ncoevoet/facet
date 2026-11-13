"""B93/B94 equivalence: the category-analysis endpoints must produce exactly
what the ground-truth semantics produce.

Ground truth:
- correlations — the per-column NULL-filtered Pearson over rows grouped by
  category (the documented formula, computed in this file over the seeded rows);
- overlap — ``CategoryFilter.matches`` over ``with_face_defaults``-ed,
  shutter-parsed photo dicts (the config filter library itself, driven here
  over the same seeded rows).

The correlations endpoint must also answer in ONE scan: a counting
``get_async_db`` wrapper asserts a single ``execute`` (the pre-B93 shape ran
one full-table query per weight column).
"""

import json
import math
from contextlib import asynccontextmanager
from unittest import mock

import aiosqlite
from fastapi.testclient import TestClient

from config.category_filter import CategoryFilter, with_face_defaults

from tests.test_stats import _async_conn_factory, _create_app_no_auth, _make_stats_db, _photo


# --- deterministic category config covering every filter kind ---

TEST_CATEGORIES = [
    {"name": "cats_portrait", "priority": 10,
     "filters": {"has_face": True, "face_ratio_min": 0.05},
     "weights": {"aesthetic_percent": 50, "comp_score_percent": 30}},
    {"name": "cats_night", "priority": 20,
     "filters": {"luminance_max": 0.15},
     "weights": {"aesthetic_percent": 10}},
    {"name": "cats_sports", "priority": 30,
     "filters": {"required_tags": ["action"], "shutter_speed_max": 0.02},
     "weights": {}},
    {"name": "cats_mono", "priority": 40,
     "filters": {"is_monochrome": True}, "weights": {}},
    {"name": "cats_noface", "priority": 50,
     "filters": {"has_face": False}, "weights": {}},
    {"name": "cats_allmode", "priority": 60,
     "filters": {"required_tags": ["a", "b"], "tag_match_mode": "all"}, "weights": {}},
    {"name": "cats_excl", "priority": 70,
     "filters": {"required_tags": ["scenery"], "excluded_tags": ["soft"]}, "weights": {}},
    {"name": "cats_longexp", "priority": 80,
     "filters": {"shutter_speed_min": 1.0, "shutter_speed_max": 10.0}, "weights": {}},
]


class _FakeConfig:
    def __init__(self, cats):
        self._cats = cats

    def get_categories(self):
        return self._cats


# --- seed rows: every filter kind plus boundary and garbage values ---

def _seed_rows():
    return [
        _photo('/r1.jpg', tags='Blue Hour, a', mean_luminance=0.1, aggregate=8.0),
        _photo('/r2.jpg', tags='blue hour, a, soft', mean_luminance=0.1, aggregate=7.0),
        _photo('/r3.jpg', tags='action', shutter_speed='1/250', aggregate=6.5),
        _photo('/r4.jpg', tags='action', shutter_speed='abc', aggregate=6.0),
        _photo('/r5.jpg', tags='action', shutter_speed='2', aggregate=5.5),
        _photo('/r6.jpg', face_count=1, face_ratio=0.3, aggregate=7.5),
        _photo('/r7.jpg', face_count=None, face_ratio=None, tags='scenery', mean_luminance=0.1, aggregate=7.2),
        _photo('/r8.jpg', is_monochrome=1, aggregate=6.8),
        _photo('/r9.jpg', shutter_speed='2', aggregate=7.1),
        _photo('/r10.jpg', tags=' A , b ', aggregate=7.4),
        _photo('/r11.jpg', category='cats_portrait', tags='people', face_count=2,
               face_ratio=0.2, aggregate=8.5),
        _photo('/r12.jpg', category='cats_noface', tags='people', face_count=3, face_ratio=0.4,
               aggregate=7.9),
        _photo('/r13.jpg', face_count=1, face_ratio=0.05, is_monochrome=1, aggregate=6.1),  # boundary min
        _photo('/r14.jpg', face_count='', tags='people', face_ratio=0.1, aggregate=6.3),  # falsy TEXT face_count
    ]


def _ground_truth_overlap(rows, cats):
    """The endpoint's documented semantics, computed over the seeded dicts."""
    compiled = [{'name': c['name'], 'filter': CategoryFilter(c['filters'])} for c in cats]
    overlap_pairs, match_counts, assigned_counts = {}, {}, {}
    uncategorized = 0
    total = 0
    for p in rows:
        pd = dict(p)
        ss = pd.get('shutter_speed')
        if ss and isinstance(ss, str) and '/' in ss:
            try:
                parts = ss.split('/')
                pd['shutter_speed'] = float(parts[0]) / float(parts[1])
            except (ValueError, ZeroDivisionError):
                pd['shutter_speed'] = None
        elif ss:
            try:
                pd['shutter_speed'] = float(ss)
            except (ValueError, TypeError):
                pd['shutter_speed'] = None
        total += 1
        assigned_cat = pd.get('category') or ''
        if assigned_cat:
            assigned_counts[assigned_cat] = assigned_counts.get(assigned_cat, 0) + 1
        else:
            uncategorized += 1
        matched = [c['name'] for c in compiled
                   if c['filter'].matches(with_face_defaults(pd))]
        for name in matched:
            match_counts[name] = match_counts.get(name, 0) + 1
        for i in range(len(matched)):
            for j in range(i + 1, len(matched)):
                pair = tuple(sorted([matched[i], matched[j]]))
                overlap_pairs[pair] = overlap_pairs.get(pair, 0) + 1
    return overlap_pairs, match_counts, assigned_counts, uncategorized, total


def _ground_truth_correlations(rows, cats, weight_columns):
    """Per-column NULL-filtered Pearson, the documented formula, in this file."""
    results = {}
    for cat in {r['category'] for r in rows if r.get('category')}:
        cat_rows = [r for r in rows if r.get('category') == cat]
        for wk, col in weight_columns.items():
            pairs = [(r[col], r['aggregate']) for r in cat_rows
                     if r.get(col) is not None and r.get('aggregate') is not None]
            n = len(pairs)
            if n < 10:
                continue
            sx = sum(float(x) for x, _ in pairs)
            sy = sum(float(y) for _, y in pairs)
            sxy = sum(float(x) * float(y) for x, y in pairs)
            sx2 = sum(float(x) * float(x) for x, _ in pairs)
            sy2 = sum(float(y) * float(y) for _, y in pairs)
            denom = math.sqrt((n * sx2 - sx * sx) * (n * sy2 - sy * sy))
            pearson = (n * sxy - sx * sy) / denom if denom > 0 else 0
            results.setdefault(cat, {})[wk] = round(pearson, 3)
    return results


# --- DB seeding: correlation rows need n >= 10 per column+category ---

def _correlation_rows():
    rows = []
    for i in range(12):  # n = 12 for aesthetic, 9 for comp_score (3 NULLs)
        rows.append(_photo(f'/c{i}.jpg', category='port',
                           aesthetic=float(i + 1),
                           comp_score=None if i % 4 == 3 else float((i * 7) % 11 + 1),
                           aggregate=float(5 + (i % 5))))
    for i in range(9):  # n = 9: exactly below the HAVING threshold
        rows.append(_photo(f'/l{i}.jpg', category='land',
                           aesthetic=float(2 + i),
                           aggregate=float(6 + (i % 3))))
    return rows


def _run_endpoint(monkeypatch, tmp_path, rows, endpoint):
    db_path = str(tmp_path / 'test.db')
    _make_stats_db(db_path, rows)
    cats = json.loads(json.dumps(TEST_CATEGORIES))
    app = _create_app_no_auth()
    with mock.patch('api.routers.stats.server_scoring_config', lambda: _FakeConfig(cats)):
        from tests.test_stats import _cache_passthrough
        with mock.patch('api.routers.stats.get_async_db', _async_conn_factory(db_path)), \
             mock.patch('api.routers.stats._get_stats_cached_async', _cache_passthrough):
            resp = TestClient(app).get(endpoint)
    assert resp.status_code == 200
    return resp.json()


def test_overlap_matches_ground_truth(monkeypatch, tmp_path):
    rows = _seed_rows()
    cats = json.loads(json.dumps(TEST_CATEGORIES))
    data = _run_endpoint(monkeypatch, tmp_path, rows, '/api/stats/categories/overlap')

    gt_pairs, gt_match, gt_assigned, gt_unc, gt_total = _ground_truth_overlap(rows, cats)
    assert data['total'] == gt_total
    assert data['uncategorized'] == gt_unc

    got_pairs = {tuple(o['pair']): o['count'] for o in data['overlaps']}
    assert got_pairs == gt_pairs
    got_match = {c['name']: c['matched'] for c in data['per_category']}
    assert got_match == gt_match  # the endpoint equals the filter-library ground truth
    got_assigned = {c['name']: c['assigned'] for c in data['per_category']}
    assert got_assigned == {name: gt_assigned.get(name, 0) for name in got_assigned}
    captured = {c['name']: c['captured_by_higher'] for c in data['per_category']}
    for name in got_match:
        assert captured[name] == max(0, got_match[name] - got_assigned.get(name, 0))


def test_overlap_semantics_spot_checks(monkeypatch, tmp_path):
    """The tricky rows behave as the filter library dictates, not by accident."""
    rows = _seed_rows()
    data = _run_endpoint(monkeypatch, tmp_path, rows, '/api/stats/categories/overlap')
    got_match = {c['name']: c['matched'] for c in data['per_category']}

    # r1 'Blue Hour, a' + luminance 0.1: case-insensitive tag with an interior
    # space, overlapping the all-mode and scenery categories.
    assert got_match['cats_night'] >= 1
    assert got_match['cats_allmode'] >= 1
    assert got_match['cats_excl'] >= 1
    # r4 garbage shutter fails the sports max closed (NULL-parsed), r5 '2' is
    # above 0.02: neither matches sports, and r9 '2' is inside long-exposure.
    assert got_match['cats_sports'] == 1
    # r13 sits exactly on face_ratio_min — inclusive, like CategoryFilter.
    # Matches: portrait r6/r11/r12/r13; noface every row without face_count > 0;
    # mono r8 + r13; sports only r3 (garbage fails closed, '2' is too slow);
    # longexp r5 + r9; allmode only r10 ('a'+'b' after strip+lower); excl only
    # r7 ('scenery' without 'soft'); night r1/r2/r7.
    assert got_match['cats_portrait'] == 4
    # r14's falsy TEXT face_count counts as no face, like the filter library.
    assert got_match['cats_noface'] == 10
    assert got_match['cats_mono'] == 2
    assert got_match['cats_sports'] == 1
    assert got_match['cats_allmode'] == 1
    assert got_match['cats_excl'] == 1
    assert got_match['cats_night'] == 3
    # Two genuine overlap pairs fall out of the seeds.
    got_pairs = {tuple(o['pair']): o['count'] for o in data['overlaps']}
    assert got_pairs[('cats_mono', 'cats_portrait')] == 1
    assert got_pairs[('cats_excl', 'cats_night')] == 1


def test_overlap_streams_in_chunks(monkeypatch, tmp_path):
    """The chunked streaming path accumulates identically when the fetch spans
    multiple chunks (patch the chunk size below the seed size)."""
    rows = _seed_rows() + _correlation_rows()
    cats = json.loads(json.dumps(TEST_CATEGORIES))
    data_default = _run_endpoint(monkeypatch, tmp_path, rows, '/api/stats/categories/overlap')

    db_path = str(tmp_path / 'chunked.db')
    _make_stats_db(db_path, rows)
    app = _create_app_no_auth()
    with mock.patch('api.routers.stats.server_scoring_config', lambda: _FakeConfig(cats)):
        from tests.test_stats import _cache_passthrough
        with mock.patch('api.routers.stats.get_async_db', _async_conn_factory(db_path)), \
             mock.patch('api.routers.stats._get_stats_cached_async', _cache_passthrough), \
             mock.patch('api.routers.stats._OVERLAP_CHUNK', 3):
            resp = TestClient(app).get('/api/stats/categories/overlap')
    assert resp.status_code == 200
    data_chunked = resp.json()
    assert data_chunked == data_default


def test_correlations_match_ground_truth_and_single_scan(monkeypatch, tmp_path):
    rows = _correlation_rows()
    db_path = str(tmp_path / 'test.db')
    _make_stats_db(db_path, rows)
    cats = json.loads(json.dumps(TEST_CATEGORIES))
    app = _create_app_no_auth()

    # Counting aiosqlite connection: the B93 shape must answer in ONE scan
    # (the pre-B93 shape ran one full-table query per weight column).
    executes = {'n': 0}

    @asynccontextmanager
    async def counting_factory():
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row

        class _Counting:
            def __init__(self, c):
                self._c = c

            async def execute(self, *a, **k):
                executes['n'] += 1
                return await self._c.execute(*a, **k)

            def __getattr__(self, name):
                return getattr(self._c, name)

        try:
            yield _Counting(conn)
        finally:
            await conn.close()

    with mock.patch('api.routers.stats.server_scoring_config', lambda: _FakeConfig(cats)):
        from tests.test_stats import _cache_passthrough
        with mock.patch('api.routers.stats.get_async_db', counting_factory), \
             mock.patch('api.routers.stats._get_stats_cached_async', _cache_passthrough):
            resp = TestClient(app).get('/api/stats/categories/correlations')
    assert resp.status_code == 200
    data = resp.json()

    assert executes['n'] == 1

    from api.routers.stats import _WEIGHT_COLUMNS
    gt = _ground_truth_correlations(rows, cats, _WEIGHT_COLUMNS)
    assert data['correlations'] == gt
    # n = 9 for the 'land' category is below the per-column threshold.
    assert 'land' not in data['correlations']
    # 'port' comp_score has 3 NULLs among 12 rows: n = 9 there too, so it is
    # excluded while every fully-populated constant column yields a 0.0 r.
    assert 'comp_score' not in data['correlations']['port']
    assert data['correlations']['port']['aesthetic'] == gt['port']['aesthetic']
    assert 'aesthetic' in data['dimensions'] and 'composition' in data['dimensions']
    configured = data['configured_weights']
    assert configured['cats_portrait']['aesthetic'] == 50
