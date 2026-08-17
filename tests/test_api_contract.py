"""Contract test between the API's responses and the types the client declares.

The Angular client is the consumer: it declares, per endpoint, an interface whose
non-optional fields it will read unconditionally. Nothing checks that the server
still sends them. That is how ``is_best_of_burst`` survived — a field the client
declared as required that no backend has ever produced, so the badge keyed on it
could never fire, and how ``photos_with_learned_scores`` survived one layer up.
Both were found by reading, not by a failing test.

This reads the required fields straight out of the ``.ts`` sources with a regex —
crude, but it means the contract has exactly one definition and the test cannot
drift from it — then drives the real endpoints against a seeded database and
fails on "declared required but absent".

Two things this deliberately does NOT do:

* It does not enumerate from OpenAPI. Four of 188 routes declare a
  ``response_model``, so the schema says nothing about response fields, and the
  14 WebDAV routes are registered with ``include_in_schema=False``.
* It does not assert the reverse direction. A server that sends more than the
  client reads is normal here; the failure mode being pinned is the client
  reading something absent.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

import pytest

from api.db_helpers import PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_SRC = REPO_ROOT / 'client' / 'src' / 'app'

DB_PATH = os.environ["DB_PATH"]

# Seeded rows live under one prefix so cleanup is a prefix DELETE and cannot
# touch whatever another module put in the shared session database.
PREFIX = "/apicontract/"
PHOTO = PREFIX + "a.jpg"

# Fields the client declares as required but the *server* is not the source of:
# the client fills them in itself, so their absence from a payload is correct.
CLIENT_DERIVED = {
    # shared-view builds this from `tags` when a payload omits it
    # (shared-view.component.ts, applyPhotos).
    'tags_list',
}

INTERFACE_SOURCES = {
    'Photo': CLIENT_SRC / 'shared' / 'models' / 'photo.model.ts',
    'PhotoSet': CLIENT_SRC / 'shared' / 'models' / 'photo.model.ts',
    'PhotoSetMember': CLIENT_SRC / 'shared' / 'models' / 'photo.model.ts',
    'PhotosResponse': CLIENT_SRC / 'features' / 'gallery' / 'gallery.store.ts',
    'ReleaseCheck': CLIENT_SRC / 'app.ts',
}

_FIELD = re.compile(r'^\s*([a-z_][a-zA-Z0-9_]*)(\?)?\s*:')


def required_fields(interface: str) -> list[str]:
    """The non-optional field names of a TypeScript interface.

    A field without ``?`` is one the client reads unconditionally, which is
    exactly the set the server must send.
    """
    source = INTERFACE_SOURCES[interface].read_text(encoding='utf-8')
    match = re.search(r'interface %s \{(.*?)\n\}' % re.escape(interface), source, re.S)
    assert match, f"interface {interface} not found in {INTERFACE_SOURCES[interface]}"
    body = re.sub(r'//.*', '', re.sub(r'/\*.*?\*/', '', match.group(1), flags=re.S))
    return [m.group(1) for m in (_FIELD.match(line) for line in body.splitlines())
            if m and not m.group(2)]


def assert_satisfies(payload: dict, interface: str, endpoint: str) -> None:
    absent = [f for f in required_fields(interface)
              if f not in payload and f not in CLIENT_DERIVED]
    assert not absent, (
        f"{endpoint} omits {len(absent)} field(s) that {interface} declares as required: "
        f"{absent}. Either the endpoint stopped sending them or the client declares a "
        f"field the server never had."
    )


@pytest.fixture()
def seeded():
    """One fully-populated photo plus a three-frame bracket, in the shared DB.

    Writes to the session database from ``tests/conftest.py`` rather than a
    private one, so the rows are visible to the app the client fixtures build.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO photos (path, filename, aggregate, aesthetic, comp_score, "
            "tech_sharpness, color_score, exposure_score, isolation_bonus, face_count, "
            "face_ratio, eye_sharpness, face_sharpness, is_blink, camera_model, lens_model, "
            "iso, f_stop, shutter_speed, focal_length, category, date_taken, image_width, "
            "image_height, is_burst_lead, burst_group_id, tags, thumbnail) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (PHOTO, "a.jpg", 7.5, 8.0, 6.5, 7.0, 6.0, 5.5, 0.2, 1, 0.3, 7.1, 7.2, 0,
             "Canon EOS R5", "RF 50mm", 400, 1.8, "1/200", 50.0, "portrait",
             "2026:01:01 12:00:00", 6000, 4000, 1, "bg1", "portrait,indoor", b"\xff\xd8\xff\xd9"),
        )
        frames = [(f"{PREFIX}br{i}.cr2", f"br{i}.cr2", 6.0, 'bracket', 900, ev, 1 if ev == 0 else 0)
                  for i, ev in enumerate((-2.0, 0.0, 2.0))]
        conn.executemany(
            "INSERT OR REPLACE INTO photos (path, filename, aggregate, sequence_kind, "
            "sequence_group_id, sequence_ev_offset, is_sequence_lead) VALUES (?,?,?,?,?,?,?)",
            frames,
        )
        conn.commit()
        yield
    finally:
        conn.execute("DELETE FROM photos WHERE path LIKE ?", (PREFIX + '%',))
        conn.commit()
        conn.close()


class TestFixtureIsRepresentative:
    """Without this, "field absent" and "column absent from the fixture" look alike.

    ``build_photo_select_columns`` intersects ``PHOTO_OPTIONAL_COLS`` with the
    columns the database actually has, so a fixture schema missing a column makes
    the endpoint legitimately omit the field and every assertion below go quiet.
    """

    def test_fixture_db_has_every_column_the_gallery_can_select(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            present = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
        finally:
            conn.close()
        expected = set(PHOTO_BASE_COLS) | set(PHOTO_OPTIONAL_COLS)
        assert not expected - present, (
            f"fixture photos table is missing {sorted(expected - present)}; the gallery would "
            "omit those fields for a reason that has nothing to do with the API contract"
        )


class TestPhotoContract:
    def test_gallery_row_satisfies_photo(self, edition_client, seeded):
        resp = edition_client.get('/api/photos', params={'per_page': 50, 'hide_bursts': '0'})
        assert resp.status_code == 200
        rows = {r['path']: r for r in resp.json()['photos']}
        assert PHOTO in rows, "seeded photo is not visible to the gallery"
        assert_satisfies(rows[PHOTO], 'Photo', 'GET /api/photos')

    def test_photo_detail_satisfies_photo(self, edition_client, seeded):
        resp = edition_client.get('/api/photo', params={'path': PHOTO})
        assert resp.status_code == 200
        body = resp.json()
        assert_satisfies(body.get('photo', body), 'Photo', 'GET /api/photo')

    def test_gallery_envelope_satisfies_photos_response(self, edition_client, seeded):
        resp = edition_client.get('/api/photos', params={'per_page': 5})
        assert resp.status_code == 200
        assert_satisfies(resp.json(), 'PhotosResponse', 'GET /api/photos')


class TestPhotoSetContract:
    def test_set_payload_satisfies_photo_set(self, edition_client, seeded):
        resp = edition_client.get('/api/photo/set', params={'path': f'{PREFIX}br1.cr2'})
        assert resp.status_code == 200
        body = resp.json()
        assert_satisfies(body, 'PhotoSet', 'GET /api/photo/set')
        assert body['members'], 'a three-frame bracket returned no members'
        for member in body['members']:
            assert_satisfies(member, 'PhotoSetMember', 'GET /api/photo/set members[]')


class TestReleaseCheckContract:
    """Pins the endpoint whose path the client got wrong for its whole existence.

    The client asked ``ApiService`` for ``/api/updates/check`` while the service
    prepends ``/api`` itself, so every request 404'd into a swallowed catch.
    """

    def test_updates_check_satisfies_release_check(self, edition_client):
        resp = edition_client.get('/api/updates/check')
        assert resp.status_code == 200
        assert_satisfies(resp.json(), 'ReleaseCheck', 'GET /api/updates/check')


class TestTheContractIsActuallyChecked:
    """Guards against this file degrading into a no-op.

    Every assertion above is only as good as the field lists behind it: if the
    regex stopped matching, or an interface were renamed, the loops would run
    over nothing and pass.
    """

    @pytest.mark.parametrize('interface,minimum', [
        ('Photo', 25),
        ('PhotosResponse', 5),
        ('PhotoSet', 5),
        ('PhotoSetMember', 3),
        ('ReleaseCheck', 5),
    ])
    def test_required_fields_were_extracted(self, interface, minimum):
        fields = required_fields(interface)
        assert len(fields) >= minimum, (
            f"only extracted {len(fields)} required fields from {interface} "
            f"({fields}) — the parser has probably stopped matching"
        )

    def test_photo_contract_covers_the_field_the_client_once_invented(self):
        # `is_burst_lead` is the real column name; the client declared
        # `is_best_of_burst` instead. Renaming the column server-side must fail
        # this file, which is only true while the field stays in the required set.
        assert 'is_burst_lead' in required_fields('Photo')
        assert 'is_best_of_burst' not in required_fields('Photo')
