"""Tests for `POST /api/culling-groups/override_sequence`'s `kind='bracket'`
gate (#162 "mark as bracket", spec step A1).

Uses the shared `seed_photos_prefix` fixture and `edition_client` -- never a
hand-rolled schema or `mock.patch` on the auth dependency -- per
`.claude/patterns/test-fixtures.md` and this repo's own rule against
`mock.patch` on FastAPI auth dependencies.
"""

import sqlite3

from db.sequence_overrides import set_sequence_overrides
from tests.conftest import _TEST_DB_FILE

PREFIX = "/seqoverrideapi/"
URL = "/api/culling-groups/override_sequence"


def _overrides(paths):
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.row_factory = sqlite3.Row
        placeholders = ','.join('?' * len(paths))
        return {
            row['photo_path']: dict(row) for row in conn.execute(
                f"SELECT photo_path, sequence_kind, override_group_key FROM "
                f"photo_sequence_overrides WHERE photo_path IN ({placeholders})", paths)
        }


class TestMarkAsBracket:
    def test_two_distinct_ev_frames_are_accepted(self, edition_client, seed_photos_prefix):
        paths = [PREFIX + "a.jpg", PREFIX + "b.jpg"]
        seed_photos_prefix(PREFIX, [
            {"path": paths[0], "filename": "a.jpg", "f_stop": 4.0,
             "shutter_speed": "0.005", "iso": 100, "date_taken": "2026:01:01 10:00:00"},
            {"path": paths[1], "filename": "b.jpg", "f_stop": 4.0,
             "shutter_speed": "0.01", "iso": 100, "date_taken": "2026:01:01 10:00:05"},
        ])
        resp = edition_client.post(URL, json={"paths": paths, "kind": "bracket"})
        assert resp.status_code == 200
        assert resp.json()["kind"] == "bracket"
        overrides = _overrides(paths)
        assert {row["sequence_kind"] for row in overrides.values()} == {"bracket"}

    def test_one_frame_is_rejected(self, edition_client, seed_photos_prefix):
        path = PREFIX + "single.jpg"
        seed_photos_prefix(PREFIX, [
            {"path": path, "filename": "single.jpg", "f_stop": 4.0,
             "shutter_speed": "0.005", "iso": 100},
        ])
        resp = edition_client.post(URL, json={"paths": [path], "kind": "bracket"})
        assert resp.status_code == 400
        assert "at least 2" in resp.json()["detail"]

    def test_a_frame_missing_exif_needed_for_ev_is_rejected(self, edition_client, seed_photos_prefix):
        paths = [PREFIX + "noexif1.jpg", PREFIX + "noexif2.jpg"]
        seed_photos_prefix(PREFIX, [
            {"path": paths[0], "filename": "noexif1.jpg", "f_stop": 4.0,
             "shutter_speed": "0.005", "iso": 100},
            {"path": paths[1], "filename": "noexif2.jpg", "f_stop": None,
             "shutter_speed": None, "iso": None},
        ])
        resp = edition_client.post(URL, json={"paths": paths, "kind": "bracket"})
        assert resp.status_code == 400
        assert "exposure metadata" in resp.json()["detail"]

    def test_frames_sharing_one_exposure_are_rejected(self, edition_client, seed_photos_prefix):
        paths = [PREFIX + "same1.jpg", PREFIX + "same2.jpg"]
        seed_photos_prefix(PREFIX, [
            {"path": paths[0], "filename": "same1.jpg", "f_stop": 4.0,
             "shutter_speed": "0.01", "iso": 100},
            {"path": paths[1], "filename": "same2.jpg", "f_stop": 4.0,
             "shutter_speed": "0.01", "iso": 100},
        ])
        resp = edition_client.post(URL, json={"paths": paths, "kind": "bracket"})
        assert resp.status_code == 400
        assert "share one exposure" in resp.json()["detail"]

    def test_a_panorama_mark_is_still_accepted(self, edition_client, seed_photos_prefix):
        """The plan's own audit found no existing 200 test for `kind='panorama'`."""
        paths = [PREFIX + "p1.jpg", PREFIX + "p2.jpg"]
        seed_photos_prefix(PREFIX, [
            {"path": paths[0], "filename": "p1.jpg"},
            {"path": paths[1], "filename": "p2.jpg"},
        ])
        resp = edition_client.post(URL, json={"paths": paths, "kind": "panorama"})
        assert resp.status_code == 200
        overrides = _overrides(paths)
        assert {row["sequence_kind"] for row in overrides.values()} == {"panorama"}

    def test_omitted_kind_still_suppresses(self, edition_client, seed_photos_prefix):
        paths = [PREFIX + "s1.jpg", PREFIX + "s2.jpg"]
        seed_photos_prefix(PREFIX, [
            {"path": paths[0], "filename": "s1.jpg"},
            {"path": paths[1], "filename": "s2.jpg"},
        ])
        resp = edition_client.post(URL, json={"paths": paths})
        assert resp.status_code == 200
        overrides = _overrides(paths)
        assert {row["sequence_kind"] for row in overrides.values()} == {None}

    def test_a_panorama_mark_does_not_inherit_an_existing_bracket_key(
        self, edition_client, seed_photos_prefix,
    ):
        """`existing_group_key` must be scoped to the requested kind's own
        family: extending a *panorama* mark onto a path already carrying a
        *bracket* group key must not reuse that key -- reusing it would
        silently attach the panorama's members to the bracket's key, so a
        later query keyed on that key could no longer tell the two sets
        apart."""
        paths = [PREFIX + "m1.jpg", PREFIX + "m3.jpg"]
        seed_photos_prefix(PREFIX, [
            {"path": paths[0], "filename": "m1.jpg"},
            {"path": paths[1], "filename": "m3.jpg"},
        ])
        # m1 already carries a bracket group key, minted by an earlier mark
        # (not through the API, so its value is unambiguous rather than an
        # accident of `min(paths)` collapsing to the same string twice).
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            set_sequence_overrides(conn, [paths[0]], 'bracket', group_key='BRACKETKEY123')
            conn.commit()

        # Marking m1 + m3 as a panorama must mint its own key, never reuse the
        # bracket key m1 already carries.
        edition_client.post(URL, json={"paths": paths, "kind": "panorama"})
        overrides = _overrides(paths)
        assert overrides[paths[0]]["override_group_key"] != 'BRACKETKEY123'
        assert overrides[paths[0]]["override_group_key"] == overrides[paths[1]]["override_group_key"]
        assert overrides[paths[0]]["sequence_kind"] == "panorama"

    def test_reusing_a_key_gates_the_union_not_just_the_submitted_paths(
        self, edition_client, seed_photos_prefix,
    ):
        """#162 review I3: `existing_group_key` lets a second mark merge into an
        already-applied bracket set. The gate must then re-check every member
        the reused key already covers together with the newly submitted paths
        -- not just the paths in this one request -- or a merge that makes the
        combined set fail the ladder rule (two members sharing an exposure)
        can slip through, and an already-applied bracket must survive that
        rejected attempt untouched."""
        a1, a2, b1 = (PREFIX + "a1.jpg", PREFIX + "a2.jpg", PREFIX + "b1.jpg")
        seed_photos_prefix(PREFIX, [
            {"path": a1, "filename": "a1.jpg", "f_stop": 4.0,
             "shutter_speed": "0.005", "iso": 100, "date_taken": "2026:01:01 10:00:00"},
            {"path": a2, "filename": "a2.jpg", "f_stop": 4.0,
             "shutter_speed": "0.01", "iso": 100, "date_taken": "2026:01:01 10:00:05"},
            # Same EV as a1: f/4, 1/200s, ISO 100.
            {"path": b1, "filename": "b1.jpg", "f_stop": 4.0,
             "shutter_speed": "0.005", "iso": 100, "date_taken": "2026:01:01 10:00:10"},
        ])

        first = edition_client.post(URL, json={"paths": [a1, a2], "kind": "bracket"})
        assert first.status_code == 200
        first_overrides = _overrides([a1, a2])
        assert {row["sequence_kind"] for row in first_overrides.values()} == {"bracket"}

        second = edition_client.post(URL, json={"paths": [a2, b1], "kind": "bracket"})
        assert second.status_code == 400
        assert "share one exposure" in second.json()["detail"]

        # The first bracket is untouched by the rejected merge attempt.
        overrides = _overrides([a1, a2, b1])
        assert overrides[a1]["sequence_kind"] == "bracket"
        assert overrides[a2]["sequence_kind"] == "bracket"
        assert overrides[a1]["override_group_key"] == overrides[a2]["override_group_key"]
        assert b1 not in overrides

    def test_a_bracket_mark_does_not_inherit_an_existing_panorama_key(
        self, edition_client, seed_photos_prefix,
    ):
        """The reverse of `test_a_panorama_mark_does_not_inherit_an_existing_bracket_key`:
        marking a frame that already carries a forced PANORAMA override as a
        bracket must mint the bracket its own key, never reuse the panorama's --
        or a later query keyed on that key could no longer tell the two sets
        apart. Guards against passing `kinds=None` to `existing_group_key` on
        the bracket branch, which would let it pick up any kind's key."""
        paths = [PREFIX + "pb1.jpg", PREFIX + "pb2.jpg"]
        seed_photos_prefix(PREFIX, [
            {"path": paths[0], "filename": "pb1.jpg", "f_stop": 4.0,
             "shutter_speed": "0.005", "iso": 100, "date_taken": "2026:01:01 10:00:00"},
            {"path": paths[1], "filename": "pb2.jpg", "f_stop": 4.0,
             "shutter_speed": "0.01", "iso": 100, "date_taken": "2026:01:01 10:00:05"},
        ])
        # pb1 already carries a panorama group key, minted directly rather
        # than through the API.
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            set_sequence_overrides(conn, [paths[0]], 'panorama', group_key='PANOKEY456')
            conn.commit()

        resp = edition_client.post(URL, json={"paths": paths, "kind": "bracket"})
        assert resp.status_code == 200
        overrides = _overrides(paths)
        assert overrides[paths[0]]["override_group_key"] != 'PANOKEY456'
        assert overrides[paths[0]]["override_group_key"] == overrides[paths[1]]["override_group_key"]
        assert {row["sequence_kind"] for row in overrides.values()} == {"bracket"}
