"""``photos.date_added``: written once on insert, kept by every rescan, sorted with NULLs last."""

import os
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("imagehash")
pytest.importorskip("cv2")

from api.types import reset_data_gate_cache  # noqa: E402
from db import get_connection  # noqa: E402
from db.schema import init_database  # noqa: E402
from processing.scorer import Facet  # noqa: E402
from tests.test_photo_tags_sync import _IMG, _result  # noqa: E402

ISO_UTC = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
PREFIX = '/date-added/'


@pytest.fixture()
def lib(tmp_path):
    db = str(tmp_path / 'date_added.db')
    init_database(db)
    facet = Facet.__new__(Facet)  # bypass the model-loading __init__
    facet._pending_centroid_persons = set()
    facet.db_path = db
    facet.config = SimpleNamespace(version_hash='v1')
    return SimpleNamespace(db=db, facet=facet, a=str((tmp_path / 'a.jpg').resolve()))


def _save(lib, partial):
    """One real scanner save of photo ``a``: the full batch UPSERT or a restricted pass."""
    if partial:
        lib.facet.save_photos_partial([(_result(lib.a, None), _IMG, ('liqe_score',))], refresh_faces=False)
    else:
        lib.facet.save_photos_batch([_result(lib.a, None)])


def _execute(lib, sql, *params):
    with get_connection(lib.db, row_factory=False) as conn:
        result = conn.execute(sql, params).fetchall()
        conn.commit()
        return result


def _date_added(lib):
    return _execute(lib, 'SELECT date_added FROM photos WHERE path=?', lib.a)[0][0]


@pytest.fixture()
def far_from_utc():
    """Run at UTC+5, so a local-time stamp misses the UTC bounds even on a UTC CI runner."""
    if not hasattr(time, 'tzset'):  # Windows: the bounds still catch a local-time stamp off UTC
        yield
        return
    saved = os.environ.get('TZ')
    os.environ['TZ'] = 'FAR-05'
    time.tzset()
    yield
    if saved is None:
        del os.environ['TZ']
    else:
        os.environ['TZ'] = saved
    time.tzset()


def _assert_stamped_now(lib, partial):
    before = datetime.now(timezone.utc).replace(microsecond=0)
    _save(lib, partial)
    after = datetime.now(timezone.utc)
    stamp = _date_added(lib)
    assert ISO_UTC.match(stamp)
    assert before <= datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc) <= after


@pytest.mark.parametrize('partial', [False, True])
def test_insert_stamps_iso_utc(lib, partial, far_from_utc):
    _assert_stamped_now(lib, partial)


@pytest.mark.parametrize('partial', [False, True])
def test_rescan_keeps_existing_date(lib, partial):
    _execute(lib, "INSERT INTO photos(path, scanned_at, date_added) "
                  "VALUES (?, '2030-01-01 00:00:00', '2020-05-06T07:08:09Z')", lib.a)
    _save(lib, partial)
    assert _date_added(lib) == '2020-05-06T07:08:09Z'


@pytest.mark.parametrize('partial', [False, True])
def test_row_predating_the_column_inherits_its_old_scan_time(lib, partial):
    _execute(lib, "INSERT INTO photos(path, scanned_at) VALUES (?, '2021-02-03 04:05:06')", lib.a)
    _save(lib, partial)
    assert _date_added(lib) == '2021-02-03T04:05:06Z'


@pytest.mark.parametrize('partial', [False, True])
def test_row_with_no_scan_time_gets_now(lib, partial, far_from_utc):
    _execute(lib, 'INSERT INTO photos(path) VALUES (?)', lib.a)
    _assert_stamped_now(lib, partial)


def _rows():
    return [
        {'path': PREFIX + 'a_null.jpg', 'filename': 'a_null.jpg', 'aggregate': 9.0},
        {'path': PREFIX + 'b_old.jpg', 'filename': 'b_old.jpg', 'aggregate': 1.0, 'date_added': '2024-01-01T00:00:00Z'},
        {'path': PREFIX + 'c_new.jpg', 'filename': 'c_new.jpg', 'aggregate': 5.0, 'date_added': '2026-01-01T00:00:00Z'},
    ]


@pytest.mark.parametrize('direction,expected', [
    ('DESC', ['c_new.jpg', 'b_old.jpg', 'a_null.jpg']),
    ('ASC', ['b_old.jpg', 'c_new.jpg', 'a_null.jpg']),
])
def test_gallery_sorts_by_date_added_with_null_last(direction, expected, seed_photos_prefix, anonymous_client):
    seed_photos_prefix(PREFIX, _rows())
    resp = anonymous_client.get('/api/photos', params={
        'sort': 'date_added', 'sort_direction': direction, 'path_prefix': PREFIX})
    assert resp.status_code == 200, resp.text
    photos = resp.json()['photos']
    assert [p['filename'] for p in photos] == expected
    assert {p['filename']: p['date_added'] for p in photos}['c_new.jpg'] == '2026-01-01T00:00:00Z'


def test_date_added_is_a_configured_sort_option(seed_photos_prefix, anonymous_client):
    # The option is data-gated (test_data_gated_sort_options): it needs one dated photo.
    seed_photos_prefix(f'{PREFIX}option/', [{'path': f'{PREFIX}option/a.jpg', 'filename': 'a.jpg',
                                             'date_added': '2026-11-23T09:00:00Z'}])
    reset_data_gate_cache()
    options = anonymous_client.get('/api/config').json()['sort_options_grouped']
    reset_data_gate_cache()
    assert any(o['column'] == 'date_added' for group in options.values() for o in group)


@pytest.mark.parametrize('smart', [False, True])
def test_shared_album_neither_shows_nor_sorts_by_date_added(smart, seed_photos_prefix, album_factory,
                                                            anonymous_client):
    prefix = f'{PREFIX}shared/{smart}/'
    seed_photos_prefix(prefix, [{**row, 'path': prefix + row['filename']} for row in _rows()])
    album_id = album_factory(prefix, 'date-added-token', 'Shared')(
        smart_filter={'path_prefix': prefix, 'sort': 'date_added'} if smart else None,
        member_names=('a_null.jpg', 'b_old.jpg', 'c_new.jpg'))
    scope = {'token': 'date-added-token'}
    listing = anonymous_client.get(f'/api/shared/album/{album_id}', params={**scope, 'sort': 'date_added'})
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body['effective_sort'] == 'aggregate'
    assert [p['filename'] for p in body['photos']] == ['a_null.jpg', 'c_new.jpg', 'b_old.jpg']
    assert not any(o['column'] == 'date_added'
                   for group in body.get('sort_options_grouped', {}).values() for o in group)
    single = anonymous_client.get(f'/api/shared/album/{album_id}/photo',
                                  params={**scope, 'asset_id': body['photos'][0]['asset_id']})
    assert single.status_code == 200, single.text
    for response in (listing, single):
        assert 'date_added' not in response.text and '2026-01-01T00:00:00Z' not in response.text
