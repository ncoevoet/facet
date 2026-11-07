"""Look-alike pairs: near-duplicates the burst and similar feeds leave out."""
import sqlite3
import struct

import pytest

from api import config
from api.lookalike_pairs import MIN_CONFIDENCE, compute_lookalike_pairs, pair_signals
from api.routers.burst_culling import _fetch_lookalike_groups
from db.schema import init_database

SAME_HASH = 'f0f0f0f0f0f0f0f0'
OTHER_HASH = '0f0f0f0f0f0f0f0f'


def vector(*values):
    return struct.pack(f'{len(values)}f', *values)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    database = tmp_path / 'lookalike.db'
    init_database(str(database))
    with sqlite3.connect(database) as handle:
        handle.row_factory = sqlite3.Row
        yield handle


def add(conn, name, embedding, **columns):
    row = {'filename': name, 'aggregate': 5.0, 'clip_embedding': embedding, 'camera_model': 'X100', **columns}
    row['path'] = f'/photos/{name}'
    conn.execute(f'INSERT INTO photos({",".join(row)}) VALUES ({",".join("?" * len(row))})', list(row.values()))
    conn.commit()
    return row['path']


def pairs(conn):
    return compute_lookalike_pairs(conn, None)


def test_a_resaved_copy_is_the_strongest_match_even_without_a_capture_time(conn):
    a = add(conn, 'a.jpg', vector(1, 0, 0), phash=SAME_HASH)
    b = add(conn, 'b.jpg', vector(1, 0.01, 0), phash=SAME_HASH)
    [pair] = pairs(conn)
    assert set(pair['paths']) == {a, b}
    assert pair['hash'] == 1.0 and pair['seconds_apart'] is None
    assert pair['confidence'] > 0.8


def test_a_retake_seconds_apart_on_the_same_camera_is_found_with_its_evidence(conn):
    add(conn, 'a.jpg', vector(1, 0, 0), phash=SAME_HASH, date_taken='2026:10:01 10:00:00')
    add(conn, 'b.jpg', vector(0.95, 0.31, 0), phash=OTHER_HASH, date_taken='2026:10:01 10:00:05')
    [pair] = pairs(conn)
    assert pair['seconds_apart'] == 5 and pair['same_camera'] is True
    assert pair['hash'] == 0.0


def test_unrelated_photos_are_not_paired(conn):
    add(conn, 'a.jpg', vector(1, 0, 0))
    add(conn, 'b.jpg', vector(0, 1, 0))
    assert pairs(conn) == []


def test_frames_of_one_burst_stay_with_the_burst_feed(conn):
    add(conn, 'a.jpg', vector(1, 0, 0), burst_group_id=3)
    add(conn, 'b.jpg', vector(1, 0.01, 0), burst_group_id=3)
    assert pairs(conn) == []


def test_bracket_and_panorama_frames_are_never_paired(conn):
    add(conn, 'a.jpg', vector(1, 0, 0), sequence_kind='bracket')
    add(conn, 'b.jpg', vector(1, 0.01, 0))
    assert pairs(conn) == []


def test_a_rejected_photo_never_appears(conn):
    add(conn, 'a.jpg', vector(1, 0, 0), is_rejected=1)
    add(conn, 'b.jpg', vector(1, 0.01, 0))
    assert pairs(conn) == []


def test_a_pair_both_of_whose_photos_are_already_decided_is_settled(conn):
    add(conn, 'a.jpg', vector(1, 0, 0), similarity_reviewed=1)
    add(conn, 'b.jpg', vector(1, 0.01, 0), burst_reviewed=1)
    assert pairs(conn) == []


def test_two_explicit_keeps_are_a_settled_decision_too(conn):
    add(conn, 'a.jpg', vector(1, 0, 0), is_kept=1)
    add(conn, 'b.jpg', vector(1, 0.01, 0), star_rating=4)
    assert pairs(conn) == []


def test_a_new_shot_meeting_an_earlier_keeper_is_the_missed_case_and_starts_with_the_keeper_kept(conn):
    keeper = add(conn, 'keeper.jpg', vector(1, 0, 0), similarity_reviewed=1, is_kept=1, aggregate=4.0)
    add(conn, 'new.jpg', vector(1, 0.01, 0), aggregate=9.0)
    [pair] = pairs(conn)
    assert pair['best_path'] == keeper and pair['earlier_keeper'] == keeper


def test_an_undecided_pair_prefers_the_higher_scoring_photo(conn):
    add(conn, 'low.jpg', vector(1, 0, 0), aggregate=3.0)
    high = add(conn, 'high.jpg', vector(1, 0.01, 0), aggregate=8.0)
    [pair] = pairs(conn)
    assert pair['best_path'] == high


def test_each_photo_is_in_one_pair_the_strongest(conn):
    add(conn, 'a.jpg', vector(1, 0, 0), phash=SAME_HASH)
    add(conn, 'b.jpg', vector(1, 0.01, 0), phash=SAME_HASH)
    add(conn, 'c.jpg', vector(1, 0.2, 0), phash=OTHER_HASH)
    [pair] = pairs(conn)
    assert {p.rsplit('/', 1)[1] for p in pair['paths']} == {'a.jpg', 'b.jpg'}


def test_a_weak_match_below_the_confidence_floor_is_dropped(conn):
    add(conn, 'a.jpg', vector(1, 0, 0), date_taken='2026:01:01 10:00:00')
    add(conn, 'b.jpg', vector(0.83, 0.558, 0), date_taken='2026:09:01 10:00:00')
    assert pairs(conn) == []


def test_the_feed_group_carries_the_evidence_and_the_lookalike_type(conn):
    keeper = add(conn, 'keeper.jpg', vector(1, 0, 0), similarity_reviewed=1, is_kept=1,
                 date_taken='2026:10:01 10:00:00')
    add(conn, 'new.jpg', vector(1, 0.01, 0), date_taken='2026:10:01 10:00:09')
    [group] = _fetch_lookalike_groups(conn, None, '1=1', [])
    assert group['type'] == 'lookalike' and group['count'] == 2 and len(group['photos']) == 2
    assert group['best_path'] == keeper
    assert group['similarity_percent'] == 100
    assert group['lookalike']['seconds_apart'] == 9 and group['lookalike']['same_camera'] is True
    assert group['lookalike']['earlier_keeper'] == keeper


class TestPairSignals:
    def row(self, **columns):
        return {'phash': None, 'camera_model': 'X100', 'date_taken': None, **columns}

    def test_a_different_camera_cancels_the_time_signal(self):
        taken = {'date_taken': '2026:10:01 10:00:00'}
        same = pair_signals(0.95, self.row(**taken), self.row(**taken))['confidence']
        other = pair_signals(0.95, self.row(**taken), self.row(camera_model='A7', **taken))['confidence']
        assert same > other

    def test_time_fades_with_distance(self):
        early = {'date_taken': '2026:10:01 10:00:00'}
        near = pair_signals(0.9, self.row(**early), self.row(date_taken='2026:10:01 10:00:30'))['confidence']
        later = pair_signals(0.9, self.row(**early), self.row(date_taken='2026:10:01 12:00:00'))['confidence']
        assert near > later > pair_signals(0.9, self.row(**early), self.row(date_taken='2026:10:03 10:00:00'))['confidence']

    def test_a_missing_hash_or_time_contributes_nothing_and_reports_none(self):
        signals = pair_signals(0.99, self.row(), self.row(camera_model=None))
        assert signals['hash'] is None and signals['seconds_apart'] is None and signals['same_camera'] is None
        assert signals['confidence'] > MIN_CONFIDENCE

    def test_a_malformed_hash_is_ignored(self):
        assert pair_signals(0.9, self.row(phash='zz'), self.row(phash=SAME_HASH))['hash'] is None


def test_the_feed_serves_pairs_and_confirming_one_settles_it(edition_client, seed_photos_prefix):
    prefix = '/lookalike-api/'
    seed_photos_prefix(prefix, [
        {'path': f'{prefix}keep.jpg', 'filename': 'keep.jpg', 'aggregate': 8.0, 'clip_embedding': vector(1, 0, 0),
         'phash': SAME_HASH, 'date_taken': '2026:10:01 10:00:00', 'camera_model': 'X100'},
        {'path': f'{prefix}drop.jpg', 'filename': 'drop.jpg', 'aggregate': 4.0, 'clip_embedding': vector(1, 0.01, 0),
         'phash': SAME_HASH, 'date_taken': '2026:10:01 10:00:07', 'camera_model': 'X100'},
    ])

    def mine():
        feed = edition_client.get('/api/culling-groups', params={'group_by': 'lookalike', 'per_page': 100}).json()
        return [g for g in feed['groups'] if g['photos'][0]['path'].startswith(prefix)]

    [group] = mine()
    assert group['type'] == 'lookalike' and group['best_path'] == f'{prefix}keep.jpg'
    assert group['lookalike']['seconds_apart'] == 7

    confirmed = edition_client.post('/api/culling-groups/confirm', json={
        'group_id': group['group_id'], 'type': 'lookalike',
        'paths': [p['path'] for p in group['photos']], 'keep_paths': [f'{prefix}keep.jpg']})
    assert confirmed.status_code == 200 and confirmed.json()['rejected'] == 1
    assert mine() == []
