"""The batch write endpoints must not write photos the caller cannot write.

The batch twin of ``tests/test_toggle_missing_photo.py``. All three endpoints
share one helper, ``faces._batch_update``, which had no visibility clause and no
existence check at all:

* multi-user: ``user_preferences.photo_path`` is
  ``TEXT NOT NULL REFERENCES photos(path)`` with ``PRAGMA foreign_keys = ON``,
  so one stale path in a batch of a thousand raised ``IntegrityError``, surfaced
  as a 500, and rolled back the 999 good ones.
* multi-user: nothing stopped an edition user writing ``user_preferences`` rows
  for another tenant's photos — the single-photo oracle, at batch scale.
* both modes: ``count`` was ``len(photo_paths)`` unconditionally, so a batch
  that wrote nothing still reported every path as written.

Unlike the single-photo guard this one drops rather than 404s — answering
per-path would rebuild the existence oracle the guard exists to close — so the
assertions below are about what landed in the database and what ``count`` says,
never about a status code.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from api import config as api_config
from api import create_app
from api.auth import CurrentUser, require_edition
from db import DEFAULT_DB_PATH

ALICE_DIR = "/batch-alice"
BOB_DIR = "/batch-bob"
ALICE_ONE = ALICE_DIR + "/one.jpg"
ALICE_TWO = ALICE_DIR + "/two.jpg"
BOB_PHOTO = BOB_DIR + "/secret.jpg"
MISSING = "/batch-nowhere/gone.jpg"

SEEDED = [ALICE_ONE, ALICE_TWO, BOB_PHOTO]

# In alice's own directory, so what keeps it out of a filtered write is the
# FILTER, not visibility -- the mirror image of BOB_PHOTO.
OTHER_CAM_PHOTO = ALICE_DIR + "/other-cam.jpg"

CAMERA = "Batch Test Cam"
# The gallery query that selects all three seeded rows. Sent as the filter set
# instead of a path list, which is what "select the whole view" puts on the
# wire (issue #126) -- the client cannot name rows it has not paged in.
ALL_SEEDED_FILTERS = {"camera": CAMERA}

# (endpoint, extra body keys beyond photo_paths)
ENDPOINTS = [
    ("/api/photos/batch_favorite", {}),
    ("/api/photos/batch_reject", {}),
    ("/api/photos/batch_rating", {"rating": 4}),
]
ENDPOINT_IDS = [path.rsplit("/", 1)[-1] for path, _ in ENDPOINTS]


@pytest.fixture()
def seeded(seed_photos_prefix):
    """Two photos under alice's directory and one under bob's.

    All three share a camera model so a filter set can select every one of
    them: the filter-scoped tests below need the ONLY thing keeping bob's photo
    out of alice's write to be the visibility clause, not the filter.
    """
    seed_photos_prefix(
        "/batch-",
        [{"path": path, "filename": path.rsplit("/", 1)[-1], "camera_model": CAMERA}
         for path in SEEDED]
        + [{"path": OTHER_CAM_PHOTO, "filename": "other-cam.jpg",
            "camera_model": "Batch Other Cam"}],
    )
    yield
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE '/batch-%'")


def _client_for(user):
    app = create_app()
    app.dependency_overrides[require_edition] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def alice_client():
    """Edition client for alice, with multi-user mode genuinely on.

    ``users`` goes into the live config rather than onto one module, because the
    visibility clause resolves ``is_multi_user_enabled`` and
    ``get_user_directories`` through ``api.config``; patching only
    ``api.routers.faces`` would leave the clause inert and every assertion below
    would pass without exercising anything.
    """
    prev = api_config._FULL_CONFIG.get("users")
    api_config._FULL_CONFIG["users"] = {"alice": {"directories": [ALICE_DIR]}}
    try:
        yield from _client_for(CurrentUser(user_id="alice", role="user", edition_authenticated=True))
    finally:
        if prev is None:
            api_config._FULL_CONFIG.pop("users", None)
        else:
            api_config._FULL_CONFIG["users"] = prev


@pytest.fixture()
def single_user_client():
    """Edition client on a single-user install — no ``users`` block at all."""
    prev = api_config._FULL_CONFIG.get("users")
    api_config._FULL_CONFIG.pop("users", None)
    try:
        yield from _client_for(CurrentUser(user_id=None, role="admin", edition_authenticated=True))
    finally:
        if prev is not None:
            api_config._FULL_CONFIG["users"] = prev


def _photo_flags(paths):
    """The GLOBAL flag columns on ``photos`` — the single-user write target.

    Multi-user writes land in ``user_preferences`` (see ``_written_prefs``);
    single-user writes go straight onto the photo row, so a single-user
    assertion that only read ``user_preferences`` would pass against a write
    that never happened.
    """
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        placeholders = ",".join("?" * len(paths))
        rows = conn.execute(
            f"SELECT path, is_favorite, is_rejected, star_rating FROM photos "
            f"WHERE path IN ({placeholders})",
            list(paths),
        ).fetchall()
    return {row[0]: row[1:] for row in rows}


def _touched(flags):
    """Paths whose global flags are no longer at their seeded defaults."""
    return {path for path, values in flags.items() if any(v for v in values)}


def _written_prefs(paths):
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        placeholders = ",".join("?" * len(paths))
        rows = conn.execute(
            f"SELECT photo_path FROM user_preferences WHERE photo_path IN ({placeholders})",
            list(paths),
        ).fetchall()
    return {row[0] for row in rows}


@pytest.mark.parametrize(("endpoint", "extra"), ENDPOINTS, ids=ENDPOINT_IDS)
class TestMultiUser:
    def test_another_tenants_photo_is_never_written(self, alice_client, seeded, endpoint, extra):
        resp = alice_client.post(endpoint, json={"photo_paths": [BOB_PHOTO], **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 0, (
            f"{endpoint} reported writing another tenant's photo: {resp.json()}"
        )
        assert _written_prefs([BOB_PHOTO]) == set(), (
            f"{endpoint} created a user_preferences row for a photo alice cannot see"
        )

    def test_a_stale_path_does_not_500_the_whole_batch(self, alice_client, seeded, endpoint, extra):
        resp = alice_client.post(endpoint, json={"photo_paths": [ALICE_ONE, MISSING], **extra})
        assert resp.status_code == 200, (
            f"{endpoint} lost the whole batch to one stale path: {resp.status_code} {resp.text}"
        )
        assert resp.json()["count"] == 1, resp.json()
        assert _written_prefs([ALICE_ONE, MISSING]) == {ALICE_ONE}

    def test_a_mixed_batch_writes_only_the_callers_own_photos(self, alice_client, seeded, endpoint, extra):
        paths = [ALICE_ONE, BOB_PHOTO, ALICE_TWO, MISSING]
        resp = alice_client.post(endpoint, json={"photo_paths": paths, **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 2, resp.json()
        assert _written_prefs(paths) == {ALICE_ONE, ALICE_TWO}

    def test_the_callers_own_photos_are_still_written(self, alice_client, seeded, endpoint, extra):
        """Positive control: the guard must not simply refuse everything."""
        resp = alice_client.post(endpoint, json={"photo_paths": [ALICE_ONE, ALICE_TWO], **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 2, resp.json()
        assert _written_prefs([ALICE_ONE, ALICE_TWO]) == {ALICE_ONE, ALICE_TWO}

    def test_duplicate_paths_are_counted_once(self, alice_client, seeded, endpoint, extra):
        resp = alice_client.post(endpoint, json={"photo_paths": [ALICE_ONE, ALICE_ONE], **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 1, resp.json()


@pytest.mark.parametrize(("endpoint", "extra"), ENDPOINTS, ids=ENDPOINT_IDS)
class TestSingleUser:
    def test_a_missing_path_is_not_reported_as_written(self, single_user_client, seeded, endpoint, extra):
        """``UPDATE ... WHERE path IN (...)`` matches nothing, so count must be 0."""
        resp = single_user_client.post(endpoint, json={"photo_paths": [MISSING], **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 0, (
            f"{endpoint} reported writing a photo that does not exist: {resp.json()}"
        )

    def test_present_photos_are_still_written(self, single_user_client, seeded, endpoint, extra):
        """Positive control, and the whole library is visible here — bob's too."""
        paths = [ALICE_ONE, BOB_PHOTO, MISSING]
        resp = single_user_client.post(endpoint, json={"photo_paths": paths, **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 2, resp.json()


# ---------------------------------------------------------------------------
# Filter-scoped batches (issue #126)
# ---------------------------------------------------------------------------
#
# "Select all" in the gallery could only ever cover the pages the client had
# fetched, because the only way to name a target set was a path list. A request
# now carries the gallery filters instead and the server derives the rows, so
# the write reaches photos the client has never seen -- which is the point, and
# also why the visibility clause has to hold on this path without
# ``_writable_photo_paths`` to fall back on.


@pytest.mark.parametrize(("endpoint", "extra"), ENDPOINTS, ids=ENDPOINT_IDS)
class TestFilterScopedMultiUser:
    def test_nothing_outside_the_callers_own_directories_is_written(
        self, alice_client, seeded, endpoint, extra
    ):
        """The tenancy guarantee, on the branch that never sees a path list.

        The filter deliberately matches bob's photo too, so the ONLY thing that
        can keep it out of the write is the visibility clause inside the scope's
        WHERE. If that clause is dropped, ``count`` becomes 3 and a
        ``user_preferences`` row appears for a photo alice cannot see.
        """
        resp = alice_client.post(endpoint, json={"filters": ALL_SEEDED_FILTERS, **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 2, (
            f"{endpoint} wrote {resp.json()['count']} rows for a filter set that spans "
            "two tenants; alice owns 2 of them"
        )
        assert _written_prefs(SEEDED) == {ALICE_ONE, ALICE_TWO}, (
            f"{endpoint} wrote outside alice's directories for a filter-scoped batch"
        )

    def test_the_filter_still_narrows_inside_the_callers_own_photos(
        self, alice_client, seeded, endpoint, extra
    ):
        """Visibility is not the only clause that has to survive the rewrite."""
        resp = alice_client.post(endpoint, json={"filters": ALL_SEEDED_FILTERS, **extra})
        assert resp.status_code == 200, resp.text
        assert _written_prefs([OTHER_CAM_PHOTO]) == set(), (
            f"{endpoint} wrote a photo the filter excludes"
        )

    def test_exclude_is_honoured(self, alice_client, seeded, endpoint, extra):
        resp = alice_client.post(
            endpoint, json={"filters": ALL_SEEDED_FILTERS, "exclude": [ALICE_TWO], **extra}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 1, resp.json()
        assert _written_prefs(SEEDED) == {ALICE_ONE}

    def test_a_filter_matching_nothing_writes_nothing(
        self, alice_client, seeded, endpoint, extra
    ):
        resp = alice_client.post(
            endpoint, json={"filters": {"camera": "No Such Camera"}, **extra}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 0, resp.json()
        assert _written_prefs(SEEDED) == set()


@pytest.mark.parametrize(("endpoint", "extra"), ENDPOINTS, ids=ENDPOINT_IDS)
class TestFilterScopedSingleUser:
    def test_exactly_the_filtered_rows_are_written(
        self, single_user_client, seeded, endpoint, extra
    ):
        """The whole library is visible here, so the filter is the only bound."""
        resp = single_user_client.post(endpoint, json={"filters": ALL_SEEDED_FILTERS, **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 3, resp.json()
        assert _touched(_photo_flags(SEEDED + [OTHER_CAM_PHOTO])) == set(SEEDED), (
            f"{endpoint} wrote a different row set than the filter selects"
        )

    def test_exclude_is_honoured(self, single_user_client, seeded, endpoint, extra):
        resp = single_user_client.post(
            endpoint, json={"filters": ALL_SEEDED_FILTERS, "exclude": [BOB_PHOTO], **extra}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 2, resp.json()
        assert _touched(_photo_flags(SEEDED)) == {ALICE_ONE, ALICE_TWO}

    def test_a_filter_matching_nothing_writes_nothing(
        self, single_user_client, seeded, endpoint, extra
    ):
        resp = single_user_client.post(
            endpoint, json={"filters": {"camera": "No Such Camera"}, **extra}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 0, resp.json()
        assert _touched(_photo_flags(SEEDED)) == set()

    def test_the_hide_toggles_are_honoured(self, single_user_client, seed_photos_prefix,
                                           endpoint, extra):
        """A filter-scoped write must cover the same rows the grid shows.

        The gallery hides a bracket's non-base exposures by default, so a write
        launched from a view with ``hide_brackets`` on must not reach the two
        frames that view is not showing.
        """
        prefix = "/batch-bracket/"
        frames = [
            {"path": f"{prefix}ev{i}.cr2", "filename": f"ev{i}.cr2",
             "camera_model": "Batch Bracket Cam", "sequence_kind": "bracket",
             "sequence_group_id": 7, "sequence_ev_offset": ev,
             "is_sequence_lead": 1 if ev == 0 else 0}
            for i, ev in enumerate((-2.0, 0.0, 2.0))
        ]
        seed_photos_prefix(prefix, frames)
        paths = [f["path"] for f in frames]
        resp = single_user_client.post(endpoint, json={
            "filters": {"camera": "Batch Bracket Cam", "hide_brackets": "1"}, **extra,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 1, resp.json()
        assert _touched(_photo_flags(paths)) == {f"{prefix}ev1.cr2"}


@pytest.mark.parametrize(("endpoint", "extra"), ENDPOINTS, ids=ENDPOINT_IDS)
class TestBatchTargetIsExactlyOne:
    """A batch names its rows one way or the other, never both and never neither."""

    def test_neither_target_is_422(self, single_user_client, seeded, endpoint, extra):
        resp = single_user_client.post(endpoint, json={**extra})
        assert resp.status_code == 422, resp.text
        assert _touched(_photo_flags(SEEDED)) == set()

    def test_both_targets_is_422(self, single_user_client, seeded, endpoint, extra):
        resp = single_user_client.post(endpoint, json={
            "photo_paths": [ALICE_ONE], "filters": ALL_SEEDED_FILTERS, **extra,
        })
        assert resp.status_code == 422, resp.text
        assert _touched(_photo_flags(SEEDED)) == set()

    def test_a_malformed_filter_set_is_422(self, single_user_client, seeded, endpoint, extra):
        """422, not the 500 an escaping ValidationError would produce."""
        resp = single_user_client.post(endpoint, json={
            "filters": {"per_page": "99999"}, **extra,
        })
        assert resp.status_code == 422, resp.text
        assert _touched(_photo_flags(SEEDED)) == set()

    def test_an_empty_path_list_is_still_a_no_op(self, single_user_client, seeded,
                                                 endpoint, extra):
        """``photo_paths: []`` names a target set; it is simply empty."""
        resp = single_user_client.post(endpoint, json={"photo_paths": [], **extra})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 0, resp.json()


@pytest.mark.parametrize(("endpoint", "extra"), ENDPOINTS, ids=ENDPOINT_IDS)
class TestExcludeNarrowsEitherTarget:
    """``exclude`` narrows a named path list too, not only a filter set.

    It was read on the ``filters`` branch only (``_batch_scope_sql`` binds it
    into the scope), while the ``photo_paths`` branch went straight to
    ``_writable_photo_paths`` and never looked at it -- so
    ``{photo_paths, exclude}`` wrote the excluded rows anyway, clearing
    ``star_rating`` and setting ``is_rejected`` on the very photos the caller
    asked to skip. The filter-branch twins are
    ``TestFilterScoped*.test_exclude_is_honoured``; the same fix landed on
    ``POST /api/cull/apply`` (tests/test_cull.py), which shares the shape.
    """

    def test_a_named_path_that_is_also_excluded_is_not_written(
        self, single_user_client, seeded, endpoint, extra
    ):
        resp = single_user_client.post(endpoint, json={
            "photo_paths": [ALICE_ONE, ALICE_TWO], "exclude": [ALICE_TWO], **extra,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 1, resp.json()
        assert _touched(_photo_flags(SEEDED)) == {ALICE_ONE}, (
            f"{endpoint} wrote a row the caller excluded"
        )

    def test_an_empty_exclude_is_a_no_op(self, single_user_client, seeded, endpoint, extra):
        resp = single_user_client.post(endpoint, json={
            "photo_paths": [ALICE_ONE, ALICE_TWO], "exclude": [], **extra,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 2, resp.json()
        assert _touched(_photo_flags(SEEDED)) == {ALICE_ONE, ALICE_TWO}

    def test_excluding_every_named_path_writes_nothing(
        self, single_user_client, seeded, endpoint, extra
    ):
        """Still a target set, simply an empty one — not the no-target 422."""
        resp = single_user_client.post(endpoint, json={
            "photo_paths": [ALICE_ONE, ALICE_TWO], "exclude": [ALICE_ONE, ALICE_TWO], **extra,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 0, resp.json()
        assert _touched(_photo_flags(SEEDED)) == set()

    def test_multi_user_named_paths_are_narrowed_too(self, alice_client, seeded,
                                                     endpoint, extra):
        """The other write target: ``user_preferences``, not ``photos``."""
        resp = alice_client.post(endpoint, json={
            "photo_paths": [ALICE_ONE, ALICE_TWO], "exclude": [ALICE_TWO], **extra,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 1, resp.json()
        assert _written_prefs(SEEDED) == {ALICE_ONE}


ALICE_ALBUM = 88801
BOB_ALBUM = 88802
UNKNOWN_ALBUM = 88899


@pytest.fixture()
def albums(seeded):
    """One unowned album holding ALICE_ONE, and one album owned by bob.

    Written into the shared session database the batch endpoints read, and
    removed again by id -- the same "clean up by what you wrote" contract
    ``seed_photos_prefix`` follows for photo rows.
    """
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("INSERT INTO albums (id, user_id, name) VALUES (?, NULL, 'alice trip')",
                     (ALICE_ALBUM,))
        conn.execute("INSERT INTO albums (id, user_id, name) VALUES (?, 'bob', 'bob trip')",
                     (BOB_ALBUM,))
        conn.execute("INSERT INTO album_photos (album_id, photo_path) VALUES (?, ?)",
                     (ALICE_ALBUM, ALICE_ONE))
        conn.execute("INSERT INTO album_photos (album_id, photo_path) VALUES (?, ?)",
                     (BOB_ALBUM, BOB_PHOTO))
    yield
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("DELETE FROM album_photos WHERE album_id IN (?, ?)",
                     (ALICE_ALBUM, BOB_ALBUM))
        conn.execute("DELETE FROM albums WHERE id IN (?, ?)", (ALICE_ALBUM, BOB_ALBUM))


@pytest.mark.parametrize(("endpoint", "extra"), ENDPOINTS, ids=ENDPOINT_IDS)
class TestFilterScopedAlbumAccess:
    """A filter set naming an album answers like the gallery GET does.

    ``_batch_scope_sql`` called ``gallery_scope_sql`` directly, past the album
    access check the read endpoints applied to the same filter set, so a POST
    body carrying ``filters: {"album_id": N}`` wrote through an album whose GET
    answers 404/403.
    """

    def test_an_album_scoped_write_is_narrowed_to_its_members(
        self, single_user_client, albums, endpoint, extra
    ):
        resp = single_user_client.post(
            endpoint, json={"filters": {"album_id": str(ALICE_ALBUM)}, **extra}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 1, resp.json()
        assert _touched(_photo_flags(SEEDED)) == {ALICE_ONE}

    def test_an_unknown_album_is_404_like_the_gallery_get(
        self, single_user_client, albums, endpoint, extra
    ):
        resp = single_user_client.post(
            endpoint, json={"filters": {"album_id": str(UNKNOWN_ALBUM)}, **extra}
        )
        assert resp.status_code == 404, resp.text
        assert _touched(_photo_flags(SEEDED)) == set()

    def test_another_users_album_is_403_like_the_gallery_get(
        self, alice_client, albums, endpoint, extra
    ):
        """Multi-user is genuinely on here, so ownership is what denies access.

        The visibility clause alone would have made this a silent no-op; the
        403 is what makes it the same answer the grid gives.
        """
        resp = alice_client.post(
            endpoint, json={"filters": {"album_id": str(BOB_ALBUM)}, **extra}
        )
        assert resp.status_code == 403, resp.text
        assert _written_prefs(SEEDED) == set()
        assert _touched(_photo_flags(SEEDED)) == set()
