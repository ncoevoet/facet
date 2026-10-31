"""Shared fixtures for the Facet test suite.

Existing test files define their own ``client`` fixture locally, which takes
precedence over conftest-level fixtures.  The fixtures here are additive —
they provide common helpers so new tests can import less boilerplate.

**Auth fixtures**: use ``edition_client`` / ``regular_client`` /
``superadmin_client`` / ``anonymous_client`` instead of ``mock.patch`` on
``api.routers.X.require_*``. FastAPI captures dependency callables inside
``Depends()`` at route registration; module-level ``mock.patch`` rebinds the
symbol but not the captured reference, so it's silently inert and tests
pass-by-accident. ``app.dependency_overrides`` is the documented FastAPI
mechanism that actually bypasses the captured reference.
"""

import contextlib
import json
import os
import sqlite3
import tempfile

# Point ``DB_PATH`` at a per-session tmp file BEFORE any project module is
# imported. ``db.connection.DEFAULT_DB_PATH`` and every ``from db import
# DEFAULT_DB_PATH`` re-export (api.database, api.routers.comparison,
# comparison.comparison_manager, …) capture the env value at import time,
# so a late ``monkeypatch`` would only patch the symbol in one module while
# the rest keep their original captured copy. Setting the env up-front
# routes every captured copy at the same fresh, schema-initialised DB.
# Under pytest-xdist every worker is its own process and imports this module itself, so
# each gets its own file; the worker id in the name only makes that visible (and a
# leftover attributable). The controller process creates one it never uses.
# LibraryLock and other caches live beside the database, so distinct filenames
# in the shared system temp directory do not isolate xdist workers. Give each
# session its own parent before any module captures DB_PATH.
_TEST_DB_DIRECTORY = tempfile.mkdtemp(
    prefix="intraswitch_facet_" + os.environ.get("PYTEST_XDIST_WORKER", "main") + "_")
_TEST_DB_FILE = tempfile.NamedTemporaryFile(
    prefix="intraswitch_facet_" + os.environ.get("PYTEST_XDIST_WORKER", "main") + "_",
    suffix=".db", dir=_TEST_DB_DIRECTORY, delete=False)
_TEST_DB_FILE.close()
os.environ["DB_PATH"] = _TEST_DB_FILE.name

# Drop ``FACET_CONFIG`` for the same reason, in the other direction: the shipped
# docker-compose.yml sets it to /config/scoring_config.json, so running the suite
# inside the container -- or on any host that exports it -- pointed every bare
# ``ScoringConfig()`` and every module-level ``_CONFIG_PATH`` at a file the tests
# do not own. ``tests/test_api_config.py`` passes os.environ to a subprocess and
# asserts what that child resolves, so the variable also has to be gone from the
# environment itself, not merely patched per test. Tests that exercise the
# variable set it back with ``monkeypatch.setenv``.
os.environ.pop("FACET_CONFIG", None)

from unittest import mock  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api import create_app  # noqa: E402
from api.auth import (  # noqa: E402
    CurrentUser, get_optional_user, require_authenticated,
    require_edition, require_superadmin,
)
from db.schema import init_database  # noqa: E402
from tests._sharding import SHARD_ENV, files_for_shard, parse_shard  # noqa: E402

init_database(_TEST_DB_FILE.name)


def pytest_collection_modifyitems(config, items):
    """Keep only this CI slice's files when ``FACET_TEST_SHARD`` is set."""
    value = os.environ.get(SHARD_ENV)
    if not value:
        return
    index, total = parse_shard(value)
    files = files_for_shard([item.nodeid for item in items], index, total)
    kept = [item for item in items if item.nodeid.split("::", 1)[0] in files]
    dropped = [item for item in items if item.nodeid.split("::", 1)[0] not in files]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept


@pytest.fixture(autouse=True)
def _reset_count_cache_and_change_token():
    """The count cache is keyed on a per-database change token, so neither it nor
    the token's sentinel connections may outlive the test that filled them.

    A key from another test's database must never be a hit, and an open sentinel
    would hold a file handle on a tmp DB the test is about to delete.
    """
    from api import config as api_config
    from api.change_token import close_change_token_sentinels
    with api_config._count_cache_lock:
        api_config._count_cache.clear()
    yield
    close_change_token_sentinels()


@pytest.fixture(autouse=True)
def _reset_index_build_status():
    """The gallery index build status is process-global (one lifespan per server):
    a lifespan test's final state must not reach the next test's /health or the
    write-retry decorator, which skips retries while it reads ``building``."""
    from api import schema_startup
    schema_startup._set_status(state=schema_startup.STATE_READY, done=0, total=0)
    yield
    schema_startup._set_status(state=schema_startup.STATE_READY, done=0, total=0)


def reset_place_search():
    """The provider cache, throttle and in-flight flag are process-wide."""
    from api import place_search
    with place_search._lock:
        place_search._cache.clear()
        place_search._next_request = 0
        place_search._inflight = False


@pytest.fixture(autouse=True)
def _reset_place_search():
    reset_place_search()
    yield


@pytest.fixture(autouse=True)
def _reset_culling_groups_cache():
    """The culling-groups memo is process-global with a 45 s TTL: a result one test
    computed (an empty feed, say) would otherwise be served to the next test that
    asks with the same parameters."""
    from api.routers.burst_culling import _invalidate_culling_groups_cache
    _invalidate_culling_groups_cache()
    yield
    _invalidate_culling_groups_cache()


@pytest.fixture(autouse=True)
def _reset_licensing_policy():
    """Licensing policy is process-global state: never let one test's mode leak.

    Pinned to default rather than reset, so a test never lazily resolves the
    operator's own repo-root scoring_config.json. A test of lazy resolution
    calls ``licensing.reset_policy()`` itself.
    """
    import licensing
    licensing.set_policy(licensing.MODE_DEFAULT)
    yield
    licensing.reset_policy()


# ---------------------------------------------------------------------------
# Minimal config constants — enough to satisfy most API code paths.
# ---------------------------------------------------------------------------

MINIMAL_VIEWER_CONFIG: dict = {
    "password": "",
    "edition_password": "",
    "pagination": {"default_per_page": 50},
    "defaults": {
        "hide_blinks": True,
        "hide_bursts": True,
        "hide_duplicates": True,
        "hide_details": True,
        "hide_rejected": True,
        "sort": "aggregate",
        "sort_direction": "DESC",
    },
    "features": {
        "show_semantic_search": True,
        "show_albums": True,
        "show_critique": True,
        "show_vlm_critique": False,
        "show_memories": True,
        "show_captions": True,
        "show_timeline": True,
        "show_map": False,
        "show_capsules": True,
        "show_similar_button": True,
        "show_merge_suggestions": True,
        "show_rating_controls": True,
        "show_folders": True,
    },
    "dropdowns": {"max_cameras": 50, "max_lenses": 50, "max_persons": 50, "max_tags": 20},
    "display": {"tags_per_photo": 3},
    "quality_thresholds": {"good": 6, "great": 7, "excellent": 8, "best": 9},
    "photo_types": {"top_picks_min_score": 7, "low_light_max_luminance": 0.2},
    "cache_ttl_seconds": 0,
    "notification_duration_ms": 2000,
    "raw_processor": {"darktable": {"executable": "darktable-cli", "profiles": []}},
    "face_thumbnails": {"output_size_px": 64, "jpeg_quality": 80, "crop_padding_ratio": 0.2, "min_crop_size_px": 20},
}

MINIMAL_SCORING_CONFIG: dict = {
    "viewer": MINIMAL_VIEWER_CONFIG,
    "burst_detection": {"similarity_threshold_percent": 70, "time_window_minutes": 0.8},
    "face_detection": {"min_confidence_percent": 65, "blink_ear_threshold": 0.28},
    "face_clustering": {"min_faces_per_person": 2, "min_samples": 2, "thresholds_by_model": {"arcface_buffalo_l": {"auto_merge_distance_percent": 15, "merge_threshold": 0.6}, "sface": {"auto_merge_distance_percent": 27.5, "merge_threshold": 0.65}}},
}


# ---------------------------------------------------------------------------
# App / client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app():
    """Create a fresh FastAPI application.

    The session DB (pointed at via ``DB_PATH`` env var set at module top)
    is already schema-initialised, so routes that read core tables
    (``photos``, ``albums``, ``persons``, ``comparisons``, …) return
    empty results instead of 500-ing on missing tables.
    """
    return create_app()


@pytest.fixture()
def client(app):
    """TestClient wrapping the Facet FastAPI app, no auth overrides.

    Use this only for endpoints that don't require auth. For auth-protected
    endpoints use ``edition_client`` / ``regular_client`` / ``superadmin_client``
    / ``anonymous_client`` so the test exercises the actual ``Depends()`` chain.
    """
    return TestClient(app)


def _make_client_with_user(user):
    """Build a TestClient where every auth dependency yields ``user``.

    Yields a cleanup-aware fixture body (caller wraps in ``yield ... clear()``).
    """
    app = create_app()
    for dep in (require_edition, require_authenticated, require_superadmin, get_optional_user):
        # Bind ``user`` via default arg so the lambda doesn't close over a
        # mutating outer ``user`` reference.
        app.dependency_overrides[dep] = lambda u=user: u
    return app


@pytest.fixture()
def edition_client():
    """TestClient where every auth dependency yields an edition-authenticated user.

    Use this for endpoints decorated with ``Depends(require_edition)``.
    """
    user = CurrentUser(user_id="test", role="admin", edition_authenticated=True)
    app = _make_client_with_user(user)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def edition_session_client():
    """Single-user client carrying an edition-claim token on a LOCKED install.

    Shared by the caption / critique generation tests, whose REAL edition gate
    must run. The install is pinned locked (edition password set, no
    multi-user, no config-load failure) rather than read from the developer's
    ambient ``VIEWER_CONFIG``: an open install is read-only and ignores the
    claim, so the outcome would otherwise depend on the local config.
    """
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: CurrentUser(
        user_id="admin", role="admin", edition_authenticated=True
    )
    with (
        mock.patch("api.auth.VIEWER_CONFIG", {"password": "", "edition_password": "x", "features": {}}),
        mock.patch("api.auth.is_multi_user_enabled", return_value=False),
        mock.patch("api.auth.config_load_failed", return_value=False),
    ):
        yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def superadmin_client():
    """TestClient where every auth dependency yields a superadmin user.

    Use this for endpoints decorated with ``Depends(require_superadmin)``
    (e.g. ``/api/scan/*``).
    """
    user = CurrentUser(
        user_id="root", role="superadmin", display_name="Super Admin",
        edition_authenticated=True,
    )
    app = _make_client_with_user(user)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def regular_client():
    """TestClient with a non-edition authenticated user.

    ``require_edition`` is intentionally NOT overridden — endpoints that need
    it hit the real dependency and return 403, exercising the access-denied
    path. An ``edition_password`` is set for the fixture's lifetime so the
    install is locked (not an open, read-only one) and the 403 this
    ``edition_authenticated=False`` user receives is the locked-install
    refusal rather than the open-install one.
    """
    from api.auth import VIEWER_CONFIG
    user = CurrentUser(user_id="u1", role="user", display_name="User One")
    prev_edition_password = VIEWER_CONFIG.get("edition_password", "")
    VIEWER_CONFIG["edition_password"] = "test-edition-lock"
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        VIEWER_CONFIG["edition_password"] = prev_edition_password


@pytest.fixture()
def anonymous_client():
    """TestClient with no authenticated user — exercises the public path."""
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seeded photos (shared session database)
# ---------------------------------------------------------------------------

# Rows live under one path prefix so teardown is a single prefix-scoped
# DELETE that cannot touch another module's rows in the shared session DB.
SEEDED_PHOTOS_PREFIX = "/conftest-seeded/"

_SEEDED_PHOTOS = [
    {"path": SEEDED_PHOTOS_PREFIX + "a.jpg", "filename": "a.jpg", "aggregate": 8.5,
     "category": "portrait", "date_taken": "2026:01:01 10:00:00"},
    {"path": SEEDED_PHOTOS_PREFIX + "b.jpg", "filename": "b.jpg", "aggregate": 5.0,
     "category": "landscape", "date_taken": "2026:01:02 10:00:00"},
    {"path": SEEDED_PHOTOS_PREFIX + "c.jpg", "filename": "c.jpg", "aggregate": 2.0,
     "category": "default", "date_taken": "2026:01:03 10:00:00"},
]


@pytest.fixture()
def seed_photos_prefix():
    """Factory: insert arbitrary photo rows into the SHARED session database.

    Writes into the DB behind ``DB_PATH`` (the one every ``client`` /
    ``edition_client`` / ``regular_client`` / ``superadmin_client`` /
    ``anonymous_client`` fixture builds its app against) instead of a
    private tmp DB, so a test can combine this with an auth-overridden
    client fixture and see the rows without standing up a second
    ``create_app()``. Modeled on tests/test_immich_webhook.py's
    ``_seed_photos`` / ``_clear_side_state`` idiom.

    Yields a ``seed(prefix, rows)`` function. ``rows`` is a list of dicts
    keyed by column name — rows may have different column sets from each
    other, since each is inserted with its own column list (a full contract
    row and a bare-bones sequence-set frame both fit through the same call).
    Every ``prefix`` a test passes is deleted in teardown, along with the ``user_preferences``,
    ``rating_provenance`` and ``comparisons`` rows under it, so callers with
    different row shapes can share one connection and one cleanup pass
    instead of each hand-rolling "seed under a prefix, delete the prefix".
    """
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    prefixes: list[str] = []

    def seed(prefix, rows):
        # Cleanup deletes by prefix: a row outside it would leak into the shared DB
        # (a hard-coded "/" against backslash paths on Windows did exactly that).
        for row in rows:
            assert row["path"].startswith(prefix), f"{row['path']!r} is outside the seeded prefix {prefix!r}"
        prefixes.append(prefix)
        for row in rows:
            cols = list(row.keys())
            placeholders = ", ".join("?" for _ in cols)
            conn.execute(
                f"INSERT OR REPLACE INTO photos ({', '.join(cols)}) VALUES ({placeholders})",
                [row[c] for c in cols],
            )
        conn.commit()
        return rows

    try:
        yield seed
    finally:
        for prefix in prefixes:
            conn.execute("DELETE FROM photos WHERE path LIKE ?", (prefix + "%",))
            conn.execute("DELETE FROM user_preferences WHERE photo_path LIKE ?", (prefix + "%",))
            conn.execute("DELETE FROM rating_provenance WHERE photo_path LIKE ?", (prefix + "%",))
            conn.execute("DELETE FROM comparisons WHERE photo_a_path LIKE ? OR photo_b_path LIKE ?",
                         (prefix + "%", prefix + "%"))
        conn.commit()
        conn.close()


ALBUM_OWNER = "test"  # the user_id the edition_client fixture authenticates as


def photo_names(resp):
    """Basenames of the ``photos`` in a gallery/album response, in response order."""
    assert resp.status_code == 200, resp.text
    return [p["path"].rsplit("/", 1)[1] for p in resp.json()["photos"]]


@pytest.fixture()
def album_factory():
    """Factory of factories: ``album_factory(prefix, token, name)`` returns ``make``.

    ``make(smart_filter=None, member_names=())`` inserts an album row (owned by
    ``ALBUM_OWNER``, members stored as ``prefix + name``) into the shared DB;
    every album made is deleted on teardown.
    """
    ids = []

    def factory(prefix, token, name):
        def make(*, smart_filter=None, member_names=()):
            with sqlite3.connect(_TEST_DB_FILE.name) as conn:
                cur = conn.execute(
                    "INSERT INTO albums (user_id, name, is_smart, smart_filter_json, share_token) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ALBUM_OWNER, name, 1 if smart_filter is not None else 0,
                     json.dumps(smart_filter) if smart_filter is not None else None, token),
                )
                album_id = cur.lastrowid
                ids.append(album_id)
                for pos, member in enumerate(member_names):
                    conn.execute(
                        "INSERT INTO album_photos (album_id, photo_path, position) VALUES (?, ?, ?)",
                        (album_id, prefix + member, pos),
                    )
            return album_id
        return make

    yield factory
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        for album_id in ids:
            conn.execute("DELETE FROM album_photos WHERE album_id = ?", (album_id,))
            conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))


@pytest.fixture()
def seeded_photos(seed_photos_prefix):
    """Insert a small set of photo rows into the SHARED session database.

    Yields the seeded photo dicts (``path``, ``filename``, ``aggregate``,
    ``category``, ``date_taken``).
    """
    return seed_photos_prefix(SEEDED_PHOTOS_PREFIX, _SEEDED_PHOTOS)


class _PeopleSeeder:
    """Persons and faces on top of ``seed_photos_prefix``; see ``seed_people``."""

    def __init__(self, conn, seed_photos):
        self._conn = conn
        self._seed_photos = seed_photos
        self.prefixes: list[str] = []
        self.person_ids: list[int] = []

    def photo(self, prefix, name, **columns):
        """Insert one photo under ``prefix`` and return its path."""
        if prefix not in self.prefixes:
            self.prefixes.append(prefix)
        path = prefix + name
        self._seed_photos(prefix, [{"path": path, "filename": name, **columns}])
        return path

    def person(self, name=None, is_hidden=0):
        """Insert a person with no faces yet and return its (autoincrement) id."""
        cur = self._conn.execute(
            "INSERT INTO persons (name, face_count, is_hidden) VALUES (?, 0, ?)", (name, is_hidden))
        self._conn.commit()
        self.person_ids.append(cur.lastrowid)
        return cur.lastrowid

    def face(self, path, person_id=None, bbox=(10, 10, 60, 60), confidence=0.9, embedding=None):
        """Insert a face on ``path`` and keep its person's ``face_count`` in step.

        ``embedding`` defaults to 4 distinct bytes, which no embedding-space scan
        reads (wrong length); pass real float32 bytes for one that should.
        """
        index = self._conn.execute(
            "SELECT COUNT(*) FROM faces WHERE photo_path = ?", (path,)).fetchone()[0]
        cur = self._conn.execute(
            "INSERT INTO faces (photo_path, face_index, embedding, bbox_x1, bbox_y1, bbox_x2, "
            "bbox_y2, confidence, person_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (path, index, sqlite3.Binary(embedding or index.to_bytes(4, "little")), *bbox,
             confidence, person_id))
        if person_id is not None:
            self._conn.execute(
                "UPDATE persons SET face_count = face_count + 1 WHERE id = ?", (person_id,))
        self._conn.commit()
        return cur.lastrowid

    def cleanup(self):
        for prefix in self.prefixes:
            self._conn.execute("DELETE FROM faces WHERE photo_path LIKE ?", (prefix + "%",))
        if self.person_ids:
            self._conn.execute(
                f"DELETE FROM persons WHERE id IN ({','.join('?' * len(self.person_ids))})",
                self.person_ids)
        self._conn.commit()


@pytest.fixture()
def seed_people(seed_photos_prefix):
    """Persons and faces in the SHARED session database, cleaned up afterwards.

    Photos go through ``seed_photos_prefix`` (the real schema, prefix-scoped
    teardown); persons take autoincrement ids rather than fixed ones, so no test
    can collide with a row another module left behind. Every face and person the
    test created is deleted on teardown, before the photos.
    """
    conn = sqlite3.connect(_TEST_DB_FILE.name)
    seeder = _PeopleSeeder(conn, seed_photos_prefix)
    try:
        yield seeder
    finally:
        seeder.cleanup()
        conn.close()


CGROUP_PATH_CONSTANTS = {
    'v2_limit': 'CGROUP_V2_LIMIT_PATH',
    'v2_usage': 'CGROUP_V2_USAGE_PATH',
    'v2_stat': 'CGROUP_V2_STAT_PATH',
    'v1_limit': 'CGROUP_V1_LIMIT_PATH',
    'v1_usage': 'CGROUP_V1_USAGE_PATH',
    'v1_stat': 'CGROUP_V1_STAT_PATH',
}


@pytest.fixture()
def fake_cgroup(monkeypatch, tmp_path):
    """Point EVERY cgroup path constant into ``tmp_path``, writing those named.

    All six, which is the whole point of sharing this. Three suites each kept
    their own copy naming five, and each omitted the same one --
    ``CGROUP_V1_STAT_PATH``. ``_cgroup_used_bytes`` consults the v1 stat file
    after the v2 one and before either usage file, so on a cgroup v1 host
    (Synology DSM, and every older Docker) those tests fell through to the
    real ``/sys/fs/cgroup/memory/memory.stat`` and asserted against the
    runner's own live memory.

    Contents are written verbatim so a test can pass ``max``, a blank file or
    garbage. A path left unnamed is pointed at a file that does not exist,
    which is what a host lacking that hierarchy -- or cgroups entirely --
    looks like.

    Returns:
        A callable taking the file contents by key, returning ``tmp_path``.
    """
    from utils import system_memory

    def point(**contents):
        for key, constant in CGROUP_PATH_CONSTANTS.items():
            target = tmp_path / key
            if key in contents:
                target.write_text(contents[key])
            monkeypatch.setattr(system_memory, constant, str(target))
        return tmp_path

    return point


def symlink_or_skip(link, target):
    """Create ``link`` -> ``target``, or skip where the platform will not allow it.

    Windows grants ``SeCreateSymbolicLinkPrivilege`` only to elevated accounts
    (or with Developer Mode on), so ``os.symlink`` raises ``WinError 1314`` for an
    ordinary developer. That is an environment limit and skips; on any other
    platform the same error is a real failure and is re-raised, so a skip can
    never hide a broken symlink on Linux CI.
    """
    import sys

    try:
        os.symlink(target, link)
    except OSError as ex:
        if sys.platform != "win32":
            raise
        pytest.skip(f"cannot create a symlink here: {ex}")


def initialize_photo_database(conn):
    """Populate an existing in-memory connection with the production schema."""
    with tempfile.TemporaryDirectory() as directory:
        db_path = os.path.join(directory, "schema.db")
        init_database(db_path)
        with contextlib.closing(sqlite3.connect(db_path)) as source:
            source.backup(conn)
# ---------------------------------------------------------------------------
# Agent (MCP) app: REAL auth, REAL lifespan
# ---------------------------------------------------------------------------

AGENT_PROTOCOL = "2025-11-25"
AGENT_MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": AGENT_PROTOCOL,
}
AGENT_USER_PASSWORDS = {"alice": "alice-pw", "bob": "bob-pw", "root": "root-pw"}
AGENT_VIEW_PASSWORD = "view-pw"
AGENT_EDITION_PASSWORD = "edition-pw"
AGENT_DIR = "/agent-seeded/"


def agent_db(sql, *args):
    """Run one statement against the shared session database and return its rows."""
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        return conn.execute(sql, args).fetchall()


def visual_ranking(hits):
    """A ``_find_similar_visual`` stand-in serving ``hits`` as its full ranking, one page at a time."""
    def find(conn, source, photo_path, min_similarity, vis_sql, vis_params, offset, limit, change_token):
        return hits[offset:offset + limit], len(hits), None
    return find


def intercept_internal_call(monkeypatch, handler):
    """Wrap ``InternalClient.call``: ``handler(tool, kwargs)`` returns a replacement result, or None to fall through."""
    from api.agent.internal_client import InternalClient
    original = InternalClient.call

    async def call(self, grant, tool, **kwargs):
        replaced = handler(tool, kwargs)
        return replaced if replaced is not None else await original(self, grant, tool, **kwargs)

    monkeypatch.setattr(InternalClient, "call", call)


@contextlib.contextmanager
def serve_app(app, **config):
    """Run ``app`` under a live uvicorn on a free local port; yield the port, stop the server on exit."""
    import threading
    import time
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", **config))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(timeout=10)


class AgentEnv:
    """A plain ``create_app()`` whose auth and lifespan are the production ones.

    Unlike ``edition_client`` / ``regular_client`` this carries NO
    ``dependency_overrides``: the internal JWT, the grant level and the token
    generations are only meaningful when the real ``Depends()`` chain runs.
    """

    def __init__(self, client, mode, mint_client=None):
        self.client = client
        self.app = client.app
        self.mode = mode
        # The client that calls the token routes. ``agent_app.build`` hands an open install a
        # loopback browser here (those routes are local-only there); every other env mints
        # through its own peer.
        self.mint_client = mint_client or client

    def login(self, user=None, edition=False):
        """Bearer headers for a real session, obtained through the real login routes."""
        if self.mode == "multi":
            resp = self.client.post(
                "/api/auth/login", json={"username": user, "password": AGENT_USER_PASSWORDS[user]})
        elif self.mode == "legacy":
            resp = self.client.post("/api/auth/login", json={"password": AGENT_VIEW_PASSWORD})
            if edition:
                resp = self.client.post(
                    "/api/auth/edition/login", json={"password": AGENT_EDITION_PASSWORD})
        else:
            resp = self.client.post("/api/auth/login", json={"password": ""})
        assert resp.status_code == 200, resp.text
        self.client.cookies.clear()
        return {"Authorization": "Bearer " + resp.json()["access_token"]}

    def mint(self, headers, level="readonly", name="test"):
        return self.mint_client.post("/api/mcp/tokens", json={"name": name, "level": level}, headers=headers)

    def token(self, headers, level="readonly", name="test"):
        resp = self.mint(headers, level, name)
        assert resp.status_code == 200, resp.text
        return resp.json()["token"]

    def rpc(self, token, method, params=None, rpc_id=1, headers=None):
        hdrs = dict(AGENT_MCP_HEADERS)
        if token is not None:
            hdrs["Authorization"] = "Bearer " + token
        hdrs.update(headers or {})
        body = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
        if params is not None:
            body["params"] = params
        return self.client.post("/mcp", json=body, headers=hdrs, follow_redirects=False)

    def call(self, token, tool, arguments=None):
        """Call a tool; return its decoded result envelope (``{ok: ..}``)."""
        resp = self.rpc(token, "tools/call", {"name": tool, "arguments": arguments or {}})
        assert resp.status_code == 200, resp.text
        result = resp.json()["result"]
        return json.loads(result["content"][0]["text"])

    def tool_names(self, token):
        resp = self.rpc(token, "tools/list")
        assert resp.status_code == 200, resp.text
        return {t["name"] for t in resp.json()["result"]["tools"]}


@pytest.fixture()
def agent_app():
    """Factory: ``agent_app(mode, mcp_enabled=True, **mcp)`` -> :class:`AgentEnv`.

    ``mode`` is ``"legacy"`` (viewer + edition passwords), ``"multi"`` (users
    alice/bob = role user, root = admin, each with the :data:`AGENT_DIR` library)
    or ``"open"`` (no passwords). Config is mutated IN PLACE on ``VIEWER_CONFIG``
    / ``_FULL_CONFIG`` (the dicts every module holds) and restored on teardown.
    The lifespan runs (``with TestClient(app)``), and the fixture refuses to
    build an app carrying ``dependency_overrides``.
    """
    import copy
    from api import auth as api_auth
    from api import config as api_config
    from api.auth import hash_password
    from api.agent import limits as agent_limits

    saved_viewer = copy.deepcopy(api_config.VIEWER_CONFIG)
    saved_full_users = copy.deepcopy(api_config._FULL_CONFIG.get("users", None))
    had_users = "users" in api_config._FULL_CONFIG
    entered = []

    def build(mode, mcp_enabled=True, **mcp):
        viewer = api_config.VIEWER_CONFIG
        viewer["password"] = AGENT_VIEW_PASSWORD if mode == "legacy" else ""
        viewer["edition_password"] = AGENT_EDITION_PASSWORD if mode == "legacy" else ""
        viewer["mcp"] = {**api_config.MCP_SETTINGS_DEFAULTS, "enabled": mcp_enabled, **mcp}
        if mode == "multi":
            api_config._FULL_CONFIG["users"] = {
                "alice": {"password_hash": hash_password("alice-pw"), "role": "user",
                          "directories": [AGENT_DIR]},
                "bob": {"password_hash": hash_password("bob-pw"), "role": "user",
                        "directories": ["/agent-bob-only/"]},
                "root": {"password_hash": hash_password("root-pw"), "role": "admin",
                         "directories": [AGENT_DIR]},
            }
        else:
            api_config._FULL_CONFIG.pop("users", None)
        api_auth._login_limiter._attempts.clear()
        agent_limits.reset_limits()
        app = create_app()
        assert not app.dependency_overrides, "agent_app must run the real auth chain"
        client = TestClient(app)
        client.__enter__()
        entered.append(client)
        local = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 12345)) if mode == "open" else None
        return AgentEnv(client, mode, mint_client=local)

    yield build
    for client in reversed(entered):
        client.__exit__(None, None, None)
    api_config.VIEWER_CONFIG.clear()
    api_config.VIEWER_CONFIG.update(saved_viewer)
    if had_users:
        api_config._FULL_CONFIG["users"] = saved_full_users
    else:
        api_config._FULL_CONFIG.pop("users", None)
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute("DELETE FROM mcp_tokens")


class FakeTab:
    """A scripted browser tab on ``/api/mcp/bridge`` (runs on its own thread).

    ``reply(call_frame)`` returns the ``result`` frame body to send back, or ``None``
    to stay silent, or ``"close"`` to hang up. Every frame the server sent is kept in ``inbox``. The server's
    pings (patched fast by the ``fake_tab`` fixture) are what wake the receive loop so
    :meth:`stop` can end the thread.
    """

    def __init__(self, env, jwt, tab_id="tab-1", *, tools=None, version="__current__", route="/",
                 focused=True, origin="http://testserver", reply=None, answer_pings=True):
        import threading
        from api.agent.ui_tools import UI_TOOLS, tools_version
        self.env = env
        self.inbox = []
        self.ready = None
        self.close_code = None
        self.reply = reply or (lambda call: {"ok": True, "data": {"echo": call["tool"]}})
        self.answer_pings = answer_pings
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._frames = []
        self.auth = {
            "type": "auth", "token": jwt, "tab_id": tab_id, "route": route, "focused": focused,
            "tools": [t.name for t in UI_TOOLS] if tools is None else tools,
            "tools_version": tools_version() if version == "__current__" else version,
        }
        self._origin = origin
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        from starlette.websockets import WebSocketDisconnect
        try:
            with self.env.client.websocket_connect(
                    "/api/mcp/bridge", headers={"origin": self._origin}) as ws:
                self._ws = ws
                ws.send_json(self.auth)
                self.ready = ws.receive_json()
                self._ready.set()
                while not self._stop.is_set():
                    for frame in self._outgoing():
                        if isinstance(frame, tuple):
                            ws.send_text(frame[1])
                        else:
                            ws.send_json(frame)
                    msg = ws.receive_json()
                    self.inbox.append(msg)
                    if msg.get("type") == "ping" and self.answer_pings:
                        ws.send_json({"type": "pong"})
                    elif msg.get("type") == "call":
                        body = self.reply(msg)
                        if body == "close":
                            break
                        if body is not None:
                            ws.send_json({"type": "result", "id": msg["id"], **body})
        except WebSocketDisconnect as ex:
            self.close_code = ex.code
        finally:
            self._ready.set()

    def _outgoing(self):
        frames, self._frames = self._frames, []
        return frames

    def send_raw(self, text):
        """Queue a raw text frame (not JSON-encoded); sent on the next server ping."""
        self._frames.append(("raw", text))

    def send_later(self, frame):
        """Queue a frame; it goes out the next time the server wakes the thread (a ping)."""
        self._frames.append(frame)

    @property
    def calls(self):
        return [m for m in self.inbox if m.get("type") == "call"]

    def start(self, wait=True):
        self._thread.start()
        if wait:
            assert self._ready.wait(60), "fake tab never became ready"
        return self

    def wait_closed(self, timeout=10):
        self._thread.join(timeout)
        assert not self._thread.is_alive(), "tab socket stayed open"
        return self.close_code

    def stop(self):
        self._stop.set()
        self._thread.join(10)


@pytest.fixture()
def fake_tab(monkeypatch):
    """Factory ``fake_tab(env, jwt, tab_id=..., **FakeTab kwargs)`` -> a STARTED tab.

    Server pings are patched to 0.1 s so tab threads stay responsive and expiry /
    silence handling is observable without long sleeps.
    """
    from api.agent import bridge
    monkeypatch.setattr(bridge, "PING_INTERVAL_S", 0.1)
    tabs = []

    def make(env, jwt, tab_id="tab-1", wait=True, **kwargs):
        tab = FakeTab(env, jwt, tab_id, **kwargs)
        tabs.append(tab)
        return tab.start(wait)

    yield make
    for tab in tabs:
        tab.stop()


@pytest.fixture()
def off_event_loop():
    """Wrap a sync callable so it fails the test when run on the event loop.

    ``asyncio.get_running_loop()`` returns the loop from a coroutine and raises
    ``RuntimeError`` from a worker thread, so a wrapped function reached through
    ``asyncio.to_thread`` passes and one called directly from async code fails.
    Returns ``guard(function, message)``.
    """
    import asyncio
    import functools

    def guard(function, message):
        @functools.wraps(function)
        def guarded(*args, **kwargs):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return function(*args, **kwargs)
            pytest.fail(message)
        return guarded

    return guard


LITERAL_KEYWORD_NAMES = ['true', 'false', 'null', '1.50', '1e3', '2024']


@pytest.fixture()
def seed_keywords():
    """Factory: ``seed_keywords(targets, names=None, *extra)`` writes ``names`` as
    ``XMP-dc:Subject`` on each target with the real ExifTool (``extra`` are more
    exiftool arguments) and returns the names.

    The default names are the ones an ExifTool JSON read would coerce to
    booleans / numbers / null, so a round trip must preserve their spelling.
    """
    import subprocess

    def seed(targets, names=None, *extra):
        names = list(LITERAL_KEYWORD_NAMES if names is None else names)
        for target in targets:
            subprocess.run(['exiftool', '-overwrite_original', *[f'-XMP-dc:Subject={name}' for name in names],
                            *extra, str(target)], check=True, capture_output=True)
        return names

    return seed


def added_region(args):
    """The first ``-XMP-mwg-rs:RegionList+=`` JSON value in an exiftool argv, decoded."""
    addition = next(arg for arg in args if arg.startswith('-XMP-mwg-rs:RegionList+='))
    return json.loads(addition.split('=', 1)[1])
