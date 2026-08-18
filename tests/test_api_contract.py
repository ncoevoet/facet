"""Contract test between the API's responses and the types the client declares.

The Angular client is the consumer: it declares, per endpoint, an interface whose
non-optional fields it will read unconditionally. Nothing checks that the server
still sends them, or that it sends them as the wire type the client expects. That
is how ``is_best_of_burst`` survived — a field the client declared as required
that no backend has ever produced, so the badge keyed on it could never fire, and
how ``photos_with_learned_scores`` survived one layer up. Both were found by
reading, not by a failing test.

This reads the declared fields straight out of the ``.ts`` sources with a regex —
crude, but it means the contract has exactly one definition and the test cannot
drift from it — then drives the real endpoints against a seeded database and
fails on "declared required but absent" or "present, but the wrong JSON type".

Presence is required-only; the wire type is checked for **every** declared field
that is present, optional ones included. Absence is what ``?`` means and stays
legal. Skipping the optional half is how ``burst_group_id`` kept a ``string``
declaration against an INTEGER column: the fixture seeded a string to match it,
so the one test written to catch this could not.

Two things this deliberately does NOT do:

* It does not enumerate from OpenAPI. Four of 188 routes declare a
  ``response_model``, so the schema says nothing about response fields, and the
  14 WebDAV routes are registered with ``include_in_schema=False``.
* It does not assert the reverse direction. A server that sends more than the
  client reads is normal here; the failure mode being pinned is the client
  reading something absent, or reading something the server sends as a
  different shape than declared.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

from api.db_helpers import PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS

REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_SRC = REPO_ROOT / 'client' / 'src' / 'app'

DB_PATH = os.environ["DB_PATH"]

# Seeded rows live under one prefix per test class so cleanup is a prefix
# DELETE that cannot touch whatever another module put in the shared session
# database. Insertion and cleanup themselves go through conftest's
# ``seed_photos_prefix`` factory rather than each test hand-rolling it.
PREFIX = "/apicontract/"
PHOTO = PREFIX + "a.jpg"

INTERFACE_SOURCES = {
    'Photo': CLIENT_SRC / 'shared' / 'models' / 'photo.model.ts',
    'PhotoSet': CLIENT_SRC / 'shared' / 'models' / 'photo.model.ts',
    'PhotoSetMember': CLIENT_SRC / 'shared' / 'models' / 'photo.model.ts',
    'PhotosResponse': CLIENT_SRC / 'features' / 'gallery' / 'gallery.store.ts',
    'ReleaseCheck': CLIENT_SRC / 'app.ts',
}

# Captures the field name, the ``?`` optional marker, and the declared type —
# everything between the ``:`` and the line's trailing ``;``. Every field in
# the interfaces above is declared on a single line, so this is enough; a
# multi-line field declaration would simply fail to match and the "were the
# fields actually extracted" self-test below would catch the drop in count.
_FIELD = re.compile(r'^\s*([a-z_][a-zA-Z0-9_]*)(\?)?\s*:\s*(.+);\s*$')


def _declared_fields(interface: str, optional: bool) -> dict[str, str]:
    """The fields of a TypeScript interface, mapped to their declared type.

    ``optional`` picks which half of the interface to return — the ``?``-marked
    fields or the ones without it. The type string is what lets
    ``_wire_type_ok`` check the wire shape too, not just presence.
    """
    source = INTERFACE_SOURCES[interface].read_text(encoding='utf-8')
    match = re.search(r'interface %s \{(.*?)\n\}' % re.escape(interface), source, re.S)
    assert match, f"interface {interface} not found in {INTERFACE_SOURCES[interface]}"
    body = re.sub(r'//.*', '', re.sub(r'/\*.*?\*/', '', match.group(1), flags=re.S))
    fields = {}
    for line in body.splitlines():
        m = _FIELD.match(line)
        if m and bool(m.group(2)) is optional:
            fields[m.group(1)] = m.group(3).strip()
    return fields


def required_fields(interface: str) -> dict[str, str]:
    """The non-optional fields — exactly the set the server must send.

    A field without ``?`` is one the client reads unconditionally.
    """
    return _declared_fields(interface, optional=False)


def optional_fields(interface: str) -> dict[str, str]:
    """The ``?``-marked fields — legal to omit, but not to send mistyped.

    Absence is what ``?`` means and is never an error here. A field that IS
    present still has to match its declared type, and for a long time nothing
    checked that: ``burst_group_id`` was declared ``string | null`` against an
    INTEGER column that has only ever served ints, and the badge keyed on it
    could not render for the group whose id is ``0``.
    """
    return _declared_fields(interface, optional=True)


# Field-level overrides of the TS-declared type, for wire formats that are
# genuinely stable, by design, and unrelated to the bug this branch actually
# fixed. Each entry is scoped to one (interface, field) pair with a checked,
# sourced reason — not a blanket "trust the client" escape hatch like the
# removed ``CLIENT_DERIVED`` used to be, which exempted `tags_list` for every
# endpoint regardless of whether that endpoint needed it (2026-08-17 review,
# finding 11).
_KNOWN_WIRE_TYPE_EXCEPTIONS: dict[tuple[str, str], str] = {
    # SQLite has no native boolean type, so every flag column is an INTEGER
    # 0/1. Commit 724fb41 deliberately coerces these two to a real boolean on
    # the CLIENT side rather than the wire ("keeps the response format
    # stable for anything else reading this API") — so 0/1 is correct here,
    # not the bug that commit fixed. `sqlite_boolean` is a synthetic type
    # recognised only by `_wire_type_ok`, never present in a real .ts source.
    ('Photo', 'is_blink'): 'sqlite_boolean | null',
    ('Photo', 'is_burst_lead'): 'sqlite_boolean | null',
    # The same convention, for the rest of the columns the client coerces at
    # ingest. `PHOTO_FLAG_FIELDS` in photo.model.ts is the closed list of six
    # that `normalisePhotoFlags` turns into real booleans, and these four are
    # the remainder of it. They are exempt for the reason the two above are,
    # not because they are optional -- an optional field still has to match
    # its declared type when it is present. `is_silhouette` is here despite
    # not yet appearing in a fixture: it is the same column class with the
    # same declaration, so leaving it out only defers an identical failure.
    ('Photo', 'is_monochrome'): 'sqlite_boolean | null',
    ('Photo', 'is_silhouette'): 'sqlite_boolean | null',
    ('Photo', 'is_favorite'): 'sqlite_boolean | null',
    ('Photo', 'is_rejected'): 'sqlite_boolean | null',
}


def _wire_type_ok(value, ts_type: str) -> bool:
    """Whether ``value`` is a plausible JSON encoding of a required TS type.

    Pragmatic: only the unambiguous scalar types are checked (``string``,
    ``number``, ``boolean``, each optionally unioned with ``null``, plus the
    synthetic ``sqlite_boolean`` used by ``_KNOWN_WIRE_TYPE_EXCEPTIONS``).
    Arrays, object literals and named types are left to the presence check in
    ``assert_satisfies`` — parsing their shape out of the ``.ts`` source is
    not worth the complexity this file exists to avoid. ``boolean`` itself
    accepts only a real ``bool``: a declared boolean field sent as ``1``
    fails, which is the class of bug commit 724fb41 fixed client-side.
    """
    parts = [p.strip() for p in ts_type.split('|')]
    nullable = 'null' in parts
    parts = [p for p in parts if p != 'null']
    if value is None:
        return nullable
    if len(parts) != 1:
        return True
    base = parts[0]
    if base == 'string':
        return isinstance(value, str)
    if base == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if base == 'boolean':
        return isinstance(value, bool)
    if base == 'sqlite_boolean':
        return isinstance(value, bool) or (isinstance(value, int) and value in (0, 1))
    return True


def assert_satisfies(payload: dict, interface: str, endpoint: str) -> None:
    fields = required_fields(interface)
    absent = [f for f in fields if f not in payload]
    assert not absent, (
        f"{endpoint} omits {len(absent)} field(s) that {interface} declares as required: "
        f"{absent}. Either the endpoint stopped sending them or the client declares a "
        f"field the server never had."
    )
    typed = {**optional_fields(interface), **fields}
    mismatched = [
        f"{field} (declared {ts_type!r}, server sent {payload[field]!r} "
        f"[{type(payload[field]).__name__}])"
        for field, ts_type in typed.items()
        if field in payload
        and not _wire_type_ok(payload[field], _KNOWN_WIRE_TYPE_EXCEPTIONS.get((interface, field), ts_type))
    ]
    assert not mismatched, (
        f"{endpoint} sends {len(mismatched)} field(s) whose wire type does not match "
        f"{interface}'s declared wire type: {mismatched}."
    )


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FULL_PHOTO_ROW = {
    "path": PHOTO, "filename": "a.jpg", "aggregate": 7.5, "aesthetic": 8.0, "comp_score": 6.5,
    "tech_sharpness": 7.0, "color_score": 6.0, "exposure_score": 5.5, "isolation_bonus": 0.2,
    "face_count": 1, "face_ratio": 0.3, "eye_sharpness": 7.1, "face_sharpness": 7.2, "is_blink": 0,
    "camera_model": "Canon EOS R5", "lens_model": "RF 50mm", "iso": 400, "f_stop": 1.8,
    "shutter_speed": "1/200", "focal_length": 50.0, "category": "portrait",
    "date_taken": "2026:01:01 12:00:00", "image_width": 6000, "image_height": 4000,
    "is_burst_lead": 1, "burst_group_id": 0, "tags": "portrait,indoor",
    "thumbnail": b"\xff\xd8\xff\xd9",
}

_BRACKET_FRAMES = [
    {"path": f"{PREFIX}br{i}.cr2", "filename": f"br{i}.cr2", "aggregate": 6.0,
     "sequence_kind": "bracket", "sequence_group_id": 900, "sequence_ev_offset": ev,
     "is_sequence_lead": 1 if ev == 0 else 0}
    for i, ev in enumerate((-2.0, 0.0, 2.0))
]

# `aesthetic` and `face_ratio` are declared as non-nullable required numbers
# on `Photo` (unlike `aggregate`, whose doc comment explicitly allows null
# for a mid-scan row) and stay NULL in SQLite until a row is inserted with
# them set. Merged into every bare-bones fixture row below so a test failure
# means the endpoint actually broke the contract, not "the fixture forgot a
# column" — the same principle `TestFixtureIsRepresentative` exists for.
_MINIMAL_SCORED_FIELDS = {"aesthetic": 6.0, "face_ratio": 0.0}


@pytest.fixture()
def seeded(seed_photos_prefix):
    """One fully-populated photo plus a three-frame bracket, in the shared DB.

    Built through the shared ``seed_photos_prefix`` factory in ``conftest.py``
    rather than a private "insert rows, then prefix-DELETE on teardown" copy —
    that factory accepts rows with different column sets in the same call, so
    a fully-populated photo and three bare sequence-set frames go through the
    same helper as the plainer rows ``seeded_photos`` inserts elsewhere.
    """
    seed_photos_prefix(PREFIX, [_FULL_PHOTO_ROW] + _BRACKET_FRAMES)


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


class TestSearchContract:
    """GET /api/search — text scope only, so the check never needs a loaded CLIP/SigLIP model.

    ``scope=text`` skips embedding search entirely (see ``api/routers/search.py``
    ``api_search``) and matches only via the FTS5 ``photos_fts`` table, which the
    schema's insert trigger populates for free as soon as the fixture row lands.
    """

    def test_text_scope_result_satisfies_photo(self, edition_client, seed_photos_prefix):
        prefix = "/apicontract-search/"
        marker = "apicontractmarkerphrase"
        seed_photos_prefix(prefix, [{
            "path": prefix + "a.jpg", "filename": "a.jpg", "aggregate": 6.0,
            "caption": f"a lighthouse at dusk, tagged {marker}",
            **_MINIMAL_SCORED_FIELDS,
        }])
        resp = edition_client.get('/api/search', params={'q': marker, 'scope': 'text'})
        assert resp.status_code == 200
        photos = resp.json()['photos']
        assert photos, "FTS text search found no match for the seeded caption"
        assert_satisfies(photos[0], 'Photo', 'GET /api/search')


class TestAlbumContract:
    """GET /api/albums/{id}/photos and its public GET /api/shared/album/{id} twin.

    Both funnel through ``_fetch_album_photos`` in ``api/routers/albums.py``, but
    they are reached through entirely different auth paths (edition-authenticated
    owner vs. anonymous + share token), so both are driven for real here rather
    than assuming one covers the other.
    """

    def test_album_and_shared_album_photos_satisfy_photo(self, edition_client, seed_photos_prefix):
        prefix = "/apicontract-album/"
        photo = prefix + "a.jpg"
        seed_photos_prefix(prefix, [{"path": photo, "filename": "a.jpg", "aggregate": 6.0,
                                     **_MINIMAL_SCORED_FIELDS}])

        create = edition_client.post('/api/albums', json={'name': 'apicontract test album'})
        assert create.status_code == 200
        album_id = create.json()['id']
        try:
            add = edition_client.post(f'/api/albums/{album_id}/photos', json={'photo_paths': [photo]})
            assert add.status_code == 200

            resp = edition_client.get(f'/api/albums/{album_id}/photos')
            assert resp.status_code == 200
            photos = resp.json()['photos']
            assert photos, "album has no photos"
            assert_satisfies(photos[0], 'Photo', 'GET /api/albums/{id}/photos')

            share = edition_client.post(f'/api/albums/{album_id}/share')
            assert share.status_code == 200
            token = share.json()['share_token']

            shared = edition_client.get(f'/api/shared/album/{album_id}', params={'token': token})
            assert shared.status_code == 200
            shared_photos = shared.json()['photos']
            assert shared_photos, "shared album has no photos"
            assert_satisfies(shared_photos[0], 'Photo', 'GET /api/shared/album/{id}')
        finally:
            edition_client.delete(f'/api/albums/{album_id}')


class TestMemoriesContract:
    """GET /api/memories — a fixed ``date=`` query param makes this deterministic

    regardless of what day the suite happens to run on, unlike the "this week"
    capsule below, whose generator hardcodes ``date.today()`` with no override.
    """

    def test_memories_satisfies_photo(self, edition_client, seed_photos_prefix):
        prefix = "/apicontract-memories/"
        seed_photos_prefix(prefix, [{
            "path": prefix + "a.jpg", "filename": "a.jpg", "aggregate": 6.0,
            "date_taken": "2020:06:15 10:00:00",
            **_MINIMAL_SCORED_FIELDS,
        }])
        resp = edition_client.get('/api/memories', params={'date': '2026-06-15'})
        assert resp.status_code == 200
        years = resp.json()['years']
        assert years, "no memory year group returned for the seeded photo"
        photos = years[0]['photos']
        assert photos, "memory year group has no photos"
        assert_satisfies(photos[0], 'Photo', 'GET /api/memories')


class TestCapsuleContract:
    """GET /api/capsules/{id}/photos, driven through the real ``this_week_years_ago`` generator.

    Of the 14+ capsule generators in ``analyzers/capsule_generator.py``, this one
    is the only one whose trigger condition (N photos within a few days of
    "today", years-ago) is cheap to seed without replicating heuristics for
    faces, GPS journeys, colour clustering or similar — see the report for the
    others.  ``_capsule_cache`` is patched to a throwaway dict so the real
    generator runs against the fixture data instead of a stale cached list from
    an earlier test in this session.
    """

    def test_this_week_capsule_photos_satisfy_photo(self, edition_client, seed_photos_prefix):
        today = date.today()
        year = today.year - 1
        prefix = "/apicontract-capsule/"
        rows = [
            {"path": f"{prefix}{i}.jpg", "filename": f"{i}.jpg", "aggregate": 7.0,
             "date_taken": f"{year}:{today.month:02d}:{today.day:02d} 10:00:00",
             **_MINIMAL_SCORED_FIELDS}
            for i in range(3)
        ]
        seed_photos_prefix(prefix, rows)

        capsule_id = f"thisweek_{year}"
        with mock.patch("api.routers.capsules._capsule_cache", {}):
            resp = edition_client.get(f'/api/capsules/{capsule_id}/photos')
        assert resp.status_code == 200, (
            f"'this week, {year}' capsule was not generated from the seeded photos "
            f"(body: {resp.text})"
        )
        photos = resp.json()['photos']
        assert photos, "capsule has no photos"
        assert_satisfies(photos[0], 'Photo', 'GET /api/capsules/{id}/photos')


class TestSimilarPhotosContract:
    """GET /api/similar_photos/{path} — ``mode=color``, the only mode that needs no

    embedding/pHash model: it compares stored histogram + saturation/luminance
    stats, which the fixture can fabricate directly with
    ``utils.histogram.pack_histogram``.
    """

    def test_full_color_match_satisfies_photo(self, edition_client, seed_photos_prefix):
        import numpy as np

        from utils.histogram import pack_histogram

        luma = np.zeros(256)
        luma[128] = 1000.0
        blob = pack_histogram(luma, luma, luma, luma)

        prefix = "/apicontract-similar/"
        source = prefix + "src.jpg"
        twin = prefix + "twin.jpg"
        seed_photos_prefix(prefix, [
            {"path": source, "filename": "src.jpg", "aggregate": 6.0, "histogram_data": blob,
             "mean_saturation": 5.0, "mean_luminance": 5.0, "is_monochrome": 0, **_MINIMAL_SCORED_FIELDS},
            {"path": twin, "filename": "twin.jpg", "aggregate": 6.0, "histogram_data": blob,
             "mean_saturation": 5.0, "mean_luminance": 5.0, "is_monochrome": 0, **_MINIMAL_SCORED_FIELDS},
        ])
        resp = edition_client.get(
            f'/api/similar_photos/{source}', params={'mode': 'color', 'full': 1},
        )
        assert resp.status_code == 200
        body = resp.json()
        similar = body['similar']
        assert similar, "identical histogram/saturation/luminance twin was not matched"
        assert_satisfies(similar[0], 'Photo', 'GET /api/similar_photos/{path}')


class TestReleaseCheckContract:
    """Pins the endpoint whose path the client got wrong for its whole existence.

    The client asked ``ApiService`` for ``/api/updates/check`` while the service
    prepends ``/api`` itself, so every request 404'd into a swallowed catch.

    The endpoint answers from the ``stats_cache`` row it caches upstream GitHub
    responses into (see ``api/updates.py`` ``check_for_update``); this test
    seeds that row directly and asserts the response echoes it verbatim, so the
    check is served purely from cache. ``_fetch_latest`` is patched to raise if
    it is ever invoked, which turns "silently degrades to a pass when offline"
    into "fails loudly if the cache path is ever bypassed" — including when
    offline, since the network is never touched either way.
    """

    def test_updates_check_satisfies_release_check(self, edition_client):
        cached = {'latest': 'v99.0.0', 'release_url': 'https://example.invalid/releases/999'}
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
                ('update_check', json.dumps(cached), time.time()),
            )
            conn.commit()
            with mock.patch(
                'api.updates._fetch_latest',
                side_effect=AssertionError('update check must be served from cache, not the network'),
            ):
                resp = edition_client.get('/api/updates/check')
            assert resp.status_code == 200
            body = resp.json()
            assert_satisfies(body, 'ReleaseCheck', 'GET /api/updates/check')
            assert body['latest'] == cached['latest'], "response did not reflect the seeded cache row"
            assert body['release_url'] == cached['release_url'], "response did not reflect the seeded cache row"
        finally:
            conn.execute("DELETE FROM stats_cache WHERE key = ?", ('update_check',))
            conn.commit()
            conn.close()


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


class TestWireTypeIsActuallyChecked:
    """Guards the wire-type check the same way the class above guards presence.

    Finding 12 (review 2026-08-17): this same branch fixed a class of bug where
    the API sends ``1``/``0`` for fields the client declares ``boolean`` (commit
    724fb41), and a presence-only contract test cannot catch it. These prove the
    mechanism actually goes red on that mutation.
    """

    def test_boolean_rejects_non_boolean_encodings(self):
        assert _wire_type_ok(True, 'boolean')
        assert _wire_type_ok(False, 'boolean')
        assert not _wire_type_ok('true', 'boolean')
        assert not _wire_type_ok(None, 'boolean')

    def test_sqlite_boolean_override_accepts_native_0_1_but_not_other_ints(self):
        # is_blink / is_burst_lead are routed through `sqlite_boolean` by
        # `_KNOWN_WIRE_TYPE_EXCEPTIONS` — see its docstring for why 0/1 is
        # correct there and not the bug commit 724fb41 fixed.
        assert _wire_type_ok(0, 'sqlite_boolean | null')
        assert _wire_type_ok(1, 'sqlite_boolean | null')
        assert not _wire_type_ok(2, 'sqlite_boolean | null')
        assert _wire_type_ok(True, 'sqlite_boolean | null')

    def test_known_wire_type_exceptions_are_scoped_to_one_field_each(self):
        # Guards against the exceptions map growing into another blanket
        # CLIENT_DERIVED: every entry must name a real (interface, field)
        # pair that Photo actually declares, not a made-up shortcut.
        photo_fields = {**required_fields('Photo'), **optional_fields('Photo')}
        for interface, field in _KNOWN_WIRE_TYPE_EXCEPTIONS:
            assert interface == 'Photo'
            assert field in photo_fields, f"{field} is not a declared Photo field"

    def test_optional_fields_are_extracted_and_disjoint_from_required(self):
        # The split is what the whole optional check rests on: for as long as
        # the parser dropped every `?` field, 50 of Photo's fields were
        # unchecked for presence AND type.
        optional = optional_fields('Photo')
        required = required_fields('Photo')
        assert len(optional) >= 40, f"only {len(optional)} optional fields parsed"
        assert not set(optional) & set(required)
        assert 'burst_group_id' in optional and 'burst_group_id' not in required
        assert 'is_burst_lead' in required and 'is_burst_lead' not in optional

    def test_absent_optional_field_passes_but_a_present_mistyped_one_fails(self, tmp_path, monkeypatch):
        # Absence is what `?` means and must stay legal; only a field that is
        # actually present is type-checked. Driven through a synthetic
        # interface so the two halves are asserted in isolation, without
        # standing up a full Photo payload.
        source = tmp_path / 'synthetic.ts'
        source.write_text(
            'export interface Synthetic {\n  path: string;\n  note?: string;\n}\n',
            encoding='utf-8',
        )
        monkeypatch.setitem(INTERFACE_SOURCES, 'Synthetic', source)

        assert_satisfies({'path': '/x.jpg'}, 'Synthetic', 'synthetic')
        assert_satisfies({'path': '/x.jpg', 'note': 'ok'}, 'Synthetic', 'synthetic')
        with pytest.raises(AssertionError, match='wire type'):
            assert_satisfies({'path': '/x.jpg', 'note': 7}, 'Synthetic', 'synthetic')

    def test_number_accepts_int_float_and_null_but_not_bool_or_string(self):
        assert _wire_type_ok(1, 'number | null')
        assert _wire_type_ok(1.5, 'number | null')
        assert _wire_type_ok(None, 'number | null')
        assert not _wire_type_ok('1', 'number | null')
        assert not _wire_type_ok(True, 'number | null')

    def test_string_rejects_non_string(self):
        assert _wire_type_ok('ok', 'string')
        assert not _wire_type_ok(1, 'string')
        assert not _wire_type_ok(None, 'string')
        assert _wire_type_ok(None, 'string | null')

    def test_assert_satisfies_fails_when_a_real_boolean_field_is_served_as_1(self):
        # `is_lead` is one of the fields the review named as already sending a
        # real boolean on the wire (unlike is_blink/is_burst_lead above), so
        # serving `1` for it is a genuine regression, not the SQLite
        # convention — this is the literal "boolean field served as 1" case.
        payload = {'path': '/x.jpg', 'ev_offset': None, 'is_lead': 1}
        with pytest.raises(AssertionError, match='wire type'):
            assert_satisfies(payload, 'PhotoSetMember', 'synthetic')

    def test_assert_satisfies_passes_when_the_boolean_field_is_a_real_bool(self):
        payload = {'path': '/x.jpg', 'ev_offset': None, 'is_lead': True}
        assert_satisfies(payload, 'PhotoSetMember', 'synthetic')


# ---------------------------------------------------------------------------
# The hand-written client model vs the GENERATED server declaration.
#
# The contract test above compares a client declaration against a live response.
# This compares it against what the server *declares* — the OpenAPI-generated
# `schema.d.ts` — which catches the same class of bug one step earlier and
# without needing the field to be present in a seeded row.
#
# It is what would have caught `junk_kind`: the server has always sent it, the
# junk-sweep view has always read it, and the shared `Photo` model never
# declared it, so every other view was blind to the field.
# ---------------------------------------------------------------------------

GENERATED_SCHEMA = CLIENT_SRC / 'core' / 'api' / 'schema.d.ts'

# (client interface, field) pairs the paired response model legitimately does
# not declare, each with the reason it is absent. Every entry is asserted to
# still describe a real gap by `test_no_client_only_field_is_stale`, so an
# entry cannot outlive the reason it was written for.
_CLIENT_ONLY_FIELDS: dict[tuple[str, str], str] = {
    # Patched onto a row in gallery.store.ts from the separate
    # POST /api/photos/keeper_hints call, never sent with the photo row.
    ('Photo', 'keeper_hint'): 'client-derived, from POST /api/photos/keeper_hints',
    # `GET /api/albums` declares no `response_model`, so its rows are not
    # filtered and carry these two. The server's `Album` model backs only the
    # album metadata embedded in `SharedAlbumResponse`, which has neither.
    ('Album', 'first_photo_path'): 'served unfiltered by GET /api/albums, which has no response_model',
    ('Album', 'photo_count'): 'served unfiltered by GET /api/albums, which has no response_model',
}

# Fields the client attaches itself, which no server response carries.
_CLIENT_ATTACHED_PHOTO_FIELDS = {
    field for interface, field in _CLIENT_ONLY_FIELDS if interface == 'Photo'
}


def _generated_schema_fields(name: str) -> set[str]:
    """Field names of one `components['schemas'][name]` block."""
    source = GENERATED_SCHEMA.read_text(encoding='utf-8')
    match = re.search(r'\n        %s: \{\n(.*?)\n        \};' % re.escape(name), source, re.S)
    assert match, f"schema {name} not found in {GENERATED_SCHEMA} — run `cd client && npm run gen:api`"
    body = re.sub(r'/\*\*.*?\*/', '', match.group(1), flags=re.S)
    return {m.group(1) for line in body.splitlines() if (m := _FIELD.match(line))}


class TestHandWrittenModelMatchesGeneratedSchema:
    """A field the client declares must be one the server actually declares."""

    def test_photo_declares_nothing_the_server_does_not_send(self):
        hand = set(required_fields('Photo')) | set(optional_fields('Photo'))
        generated = _generated_schema_fields('Photo')
        assert generated, "the generated Photo schema is empty"
        unknown = hand - generated - _CLIENT_ATTACHED_PHOTO_FIELDS
        assert not unknown, (
            "client/src/app/shared/models/photo.model.ts declares field(s) no API "
            f"response model carries: {sorted(unknown)}. Either the server dropped "
            "them, or they are client-derived and belong in "
            "_CLIENT_ATTACHED_PHOTO_FIELDS with a reason."
        )

    def test_the_generated_schema_is_actually_parsed(self):
        """Guard: a rename or format change must not silently empty the check."""
        generated = _generated_schema_fields('Photo')
        assert len(generated) > 50, f"only parsed {len(generated)} fields — the regex has drifted"
        assert 'shutter_speed' in generated
        assert 'junk_kind' in generated


# ---------------------------------------------------------------------------
# EVERY hand-written client interface, against the live response model behind it.
#
# `response_model` FILTERS. A field the model does not declare is dropped from
# an otherwise valid 200, and nothing above notices: the endpoint still answers,
# the status is still 200, and every assertion written against the fields that
# survived still passes. Deleting `sort_options_grouped` from
# `ViewerConfigResponse` — read by `app.ts` and `shared-view.component.ts` — left
# the entire suite green, and only `gallery.Photo` was pinned against it.
#
# `schema.d.ts` cannot close that on its own: it is generated FROM the server, so
# regenerating it after a deletion erases the evidence. The client's own
# hand-written interfaces are the one declaration of what the client reads that
# does not move when the server does.
#
# The pairing is DERIVED, not listed: a client interface pairs with the live
# schema of the same name, or with that name plus the `Response` suffix the
# models use. There is no per-model list to maintain, so there is none to rot —
# a new client interface named after its response model is covered the day it
# lands. Interfaces that pair with nothing (dialog data, view models, request
# bodies with invented names) are simply not checked; a speculative alias map
# was tried first and produced false pairs, e.g. `SplitPersonResult` onto
# `SplitPersonRequest`, so name equality is the only pairing rule.
# ---------------------------------------------------------------------------

_INTERFACE_HEAD = re.compile(r'\binterface ([A-Z][A-Za-z0-9_]*)(?:\s+extends\s+[^{]+)?\s*\{')


def _interface_body(source: str, brace: int) -> tuple[str, int]:
    """The text between ``source[brace]`` and its matching close brace."""
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[brace + 1:i], i
    raise AssertionError(f"unbalanced interface body at offset {brace}")


def _top_level_field_names(body: str) -> set[str]:
    """The fields an interface declares itself, ignoring nested object literals.

    Depth-tracked rather than indentation-matched: `ViewerConfig` nests eight
    inline object literals whose members would otherwise be counted as its own
    fields, and `[key: string]` index signatures and `foo(): void` methods must
    not be counted at all — neither matches ``_FIELD``.
    """
    fields: set[str] = set()
    depth, chunk = 0, ''
    for ch in body:
        if ch in '{[(':
            depth += 1
        elif ch in '}])':
            depth -= 1
        elif ch == ';' and depth == 0:
            if (m := _FIELD.match(' '.join(chunk.split()) + ';')):
                fields.add(m.group(1))
            chunk = ''
            continue
        chunk += ch
    return fields


def _client_interfaces() -> dict[str, dict[Path, set[str]]]:
    """Every interface the client hand-writes, mapped to its declared fields.

    Keyed by name then by source file: the same name is declared in more than
    one component (`LearnedWeightsResponse`, `PhotoFace`), and each declaration
    is checked separately so the report names the file that has to change.
    """
    found: dict[str, dict[Path, set[str]]] = {}
    for path in sorted(CLIENT_SRC.rglob('*.ts')):
        if path.name == 'schema.d.ts' or path.name.endswith('.spec.ts'):
            continue
        source = re.sub(r'/\*.*?\*/', '', path.read_text(encoding='utf-8'), flags=re.S)
        pos = 0
        while (head := _INTERFACE_HEAD.search(source, pos)):
            body, end = _interface_body(source, head.end() - 1)
            fields = _top_level_field_names(re.sub(r'//[^\n]*', '', body))
            found.setdefault(head.group(1), {})[path] = fields
            pos = end + 1
    return found


def _paired_response_models(schemas: dict) -> dict[str, str]:
    """Client interface name → the live schema name it mirrors."""
    pairs = {}
    for name in _client_interfaces():
        for candidate in (name, name + 'Response'):
            if candidate in schemas:
                pairs[name] = candidate
                break
    return pairs


def _stripped_fields(schemas: dict) -> list[str]:
    """Fields a paired client interface reads that its response model drops."""
    interfaces = _client_interfaces()
    reports = []
    for interface, schema_name in _paired_response_models(schemas).items():
        declared = set(schemas[schema_name].get('properties', {}))
        for path, fields in interfaces[interface].items():
            missing = sorted(
                f for f in fields - declared
                if (interface, f) not in _CLIENT_ONLY_FIELDS
            )
            if missing:
                reports.append(
                    f"{schema_name} does not declare {missing}, read by {interface} "
                    f"in {path.relative_to(REPO_ROOT)}"
                )
    return reports


class TestResponseModelsCarryWhatTheClientReads:
    """No response model may drop a field a client interface declares."""

    def test_no_paired_response_model_strips_a_field_the_client_declares(self, app):
        stripped = _stripped_fields(app.openapi()['components']['schemas'])
        assert not stripped, (
            f"{len(stripped)} field(s) would be filtered out of a 200 response by their "
            "`response_model` while the client still reads them:\n  " + "\n  ".join(stripped)
            + "\nEither re-declare the field on the model, drop it from the client "
              "interface, or record it in _CLIENT_ONLY_FIELDS with the reason."
        )

    def test_no_client_only_field_is_stale(self, app):
        """An exception that no longer describes a gap must not linger.

        Otherwise the map turns into a place to silence the check, and a field
        the server has since (re-)declared stays permanently unverified.
        """
        schemas = app.openapi()['components']['schemas']
        pairs = _paired_response_models(schemas)
        interfaces = _client_interfaces()
        for (interface, field), reason in _CLIENT_ONLY_FIELDS.items():
            assert reason, f"({interface}, {field}) needs a reason"
            assert interface in pairs, f"{interface} pairs with no response model"
            assert any(field in f for f in interfaces[interface].values()), (
                f"{interface} no longer declares {field} — drop the exception"
            )
            assert field not in schemas[pairs[interface]].get('properties', {}), (
                f"{pairs[interface]} now declares {field}; the exception is obsolete "
                "and is hiding the field from the check"
            )


class TestTheResponseModelCheckIsActuallyChecking:
    """Guards the mechanism above the way `TestTheContractIsActuallyChecked`
    guards the presence check: a parser that quietly matched nothing would make
    every assertion loop over an empty set and pass.
    """

    def test_the_client_interfaces_are_actually_parsed(self):
        interfaces = _client_interfaces()
        assert len(interfaces) >= 140, f"only parsed {len(interfaces)} client interfaces"
        # One flat interface, one with eight nested object literals, one that
        # sits behind the `Response` suffix rule.
        scan_status = next(iter(interfaces['ScanStatus'].values()))
        assert scan_status >= {'running', 'directories', 'exit_code'}
        viewer_config = next(iter(interfaces['ViewerConfig'].values()))
        assert 'sort_options_grouped' in viewer_config
        assert 'show_map' not in viewer_config, "nested object members leaked in as own fields"

    def test_enough_interfaces_pair_with_a_response_model(self, app):
        schemas = app.openapi()['components']['schemas']
        pairs = _paired_response_models(schemas)
        checked = sum(
            len(fields)
            for interface in pairs
            for fields in _client_interfaces()[interface].values()
        )
        assert len(pairs) >= 30, f"only {len(pairs)} interfaces paired: {sorted(pairs)}"
        assert checked >= 250, f"only {checked} client-declared fields are checked"
        # Both halves of the pairing rule, and the model whose deletion the
        # whole suite failed to notice.
        assert pairs['Photo'] == 'Photo'
        assert pairs['ViewerConfig'] == 'ViewerConfigResponse'
        assert pairs['ScanStatus'] == 'ScanStatusResponse'

    def test_a_response_model_that_drops_a_declared_field_is_reported(self, app):
        """The mutation the real thing has to catch, without editing a model."""
        schemas = app.openapi()['components']['schemas']
        assert not _stripped_fields(schemas)

        mutated = dict(schemas)
        properties = dict(mutated['ViewerConfigResponse']['properties'])
        del properties['sort_options_grouped']
        mutated['ViewerConfigResponse'] = {**mutated['ViewerConfigResponse'], 'properties': properties}

        reports = _stripped_fields(mutated)
        assert any('sort_options_grouped' in r for r in reports), reports

    def test_an_exception_only_silences_its_own_interface(self, app):
        """`keeper_hint` is exempt on `Photo`; the same name elsewhere is not."""
        schemas = app.openapi()['components']['schemas']
        mutated = dict(schemas)
        properties = dict(mutated['KeeperHint']['properties'])
        dropped = sorted(properties)[0]
        del properties[dropped]
        mutated['KeeperHint'] = {**mutated['KeeperHint'], 'properties': properties}

        assert any(dropped in r and 'KeeperHint' in r for r in _stripped_fields(mutated))
