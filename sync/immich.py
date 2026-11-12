"""One-way push of Facet ratings/favorites into an Immich server via its REST API.

Facet photo paths are mapped to Immich ``originalPath`` values through the
configured ``immich.path_map`` prefix pairs, resolved to asset ids with
``POST /api/search/metadata``, and updated with batched ``PUT /api/assets``
calls grouped by identical payload. A never-rated, never-favorited photo never
pushes a clear (that would be noise on the vast majority of the library);
but a photo that WAS pushed as rated/favorite and is later reset in Facet
must still reach Immich as an explicit clear — ``rating: null`` / ``isFavorite:
false``, never ``rating: 0``, which Immich v3 rejects — or the stale value is
stuck there forever. ``stats_cache`` (a generic key/value side table, keyed per
sync scope) remembers which paths were last pushed active so that transition
is detected — see ``_fetch_rating_rows`` and ``_load_synced_state``. An
optional single top-picks album mirrors a minimum-rating threshold: photos at
or above it are members, ones this run can prove dropped below it are removed
(and only on a global sync — a per-user sync adds but never removes), and a
member is never re-added.
Immich's database is never touched — REST only.

Two surfaces share those payload rules: :func:`sync_to_immich` (the whole
library, driven by ``--immich-sync``) and :func:`push_photo_updates` (one
inbound webhook delivery, driven by ``api/routers/immich.py``). Both go
through :func:`_push_fields`, so a rule fixed in one is fixed in both, and
both read the whole library state once per run rather than once per photo.

Expected ``scoring_config.json`` section::

    "immich": {
        "url": "http://immich.local:2283",
        "api_key": "...",
        "path_map": [
            { "facet_prefix": "/photos/", "immich_prefix": "/usr/src/app/upload/" }
        ],
        "push": {
            "ratings": true,
            "favorites": true,
            "rejected": false,
            "top_picks_album": "",
            "top_picks_min_rating": 4
        },
        "webhook": {
            "token_env": "",
            "header": "x-facet-token",
            "max_pending": 500
        },
        "timeout_seconds": 30
    }
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from http import client as http_client
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote, urlparse

from db import get_connection

logger = logging.getLogger(__name__)

UPDATE_CHUNK = 500
# How many paths one ``WHERE path IN (...)`` read may carry. Well under
# SQLite's default 999-variable ceiling, so a large delivery chunks instead
# of raising.
PATH_QUERY_CHUNK = 500
UNMATCHED_LOG_LIMIT = 20
DEFAULT_MAX_PENDING = 500

REJECTED_RATING = -1

RESULT_PUSHED = "pushed"
RESULT_SKIPPED = "skipped"
RESULT_UNMATCHED = "unmatched"
RESULT_UNKNOWN = "unknown"
RESULT_FAILED = "failed"

# What one asset's push may fail with without taking the rest of the delivery
# down with it: a bad config value (``ValueError``, including the
# ``JSONDecodeError`` of a garbled response body), any transport failure
# (urllib's ``URLError`` and ``TimeoutError`` are both ``OSError`` subclasses),
# a protocol-level HTTP failure that is NOT an OSError (``BadStatusLine``,
# ``IncompleteRead`` — and ``RemoteDisconnected``, which is both), or a DB
# error while reading the row.
PUSH_ERRORS = (ValueError, OSError, sqlite3.Error, http_client.HTTPException)

# Serializes the read-modify-write of the ``stats_cache`` side-table blobs
# against other threads of THIS process — concurrent webhook deliveries land
# in the same threadpool. The CLAUDE.md caveat about ``flock`` being host-local
# does not apply: this is an in-process mutex, and the BEGIN IMMEDIATE it is
# paired with covers the cross-process half.
_STATE_LOCK = threading.Lock()


class AssetIdentityError(ValueError):
    """Remote identity is ambiguous or inconsistent; no mutation is safe."""


class ImmichClient:
    """Minimal REST client for the Immich API (``x-api-key`` auth)."""

    response_byte_limit: int | None = None

    def __init__(self, url: str, api_key: str, timeout: int = 30, *,
                 owner_id: str = "", library_id: str = "") -> None:
        self.base_url = self._validate_url(url)
        self.api_key = api_key
        self.timeout = timeout
        self.owner_id = owner_id
        self.library_id = library_id
        # One registry spans in-scope bulk listings, fallback results and
        # verified webhook assets. Broad search hits within the selected
        # owner/library scope can disprove another candidate's identity.
        self._ids_by_path: dict[str, set[str]] = {}
        self._paths_by_id: dict[str, set[str]] = {}

    @staticmethod
    def _validate_url(url: str) -> str:
        if not url:
            raise ValueError("immich.url is not configured")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported Immich URL scheme: {parsed.scheme!r} (use http or https)")
        if not parsed.hostname:
            raise ValueError("Immich URL has no hostname")
        return url.rstrip("/")

    def _request(self, method: str, path: str, payload: dict | None = None):
        headers = {"x-api-key": self.api_key, "Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib_request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        with urllib_request.urlopen(req, timeout=self.timeout) as resp:
            body = resp.read(self.response_byte_limit + 1) if self.response_byte_limit is not None else resp.read()
            if self.response_byte_limit is not None and len(body) > self.response_byte_limit:
                raise ValueError('Immich response exceeds the configured size limit')
        return json.loads(body) if body else None

    def ping(self) -> dict:
        """GET /api/server/about — verifies both connectivity and the API key."""
        return self._request("GET", "/api/server/about") or {}

    def _in_scope(self, item: dict) -> bool:
        # Missing response fields cannot satisfy an explicitly selected scope.
        return ((not self.owner_id or item.get("ownerId") == self.owner_id)
                and (not self.library_id or item.get("libraryId") == self.library_id))

    def _observe_asset(self, item: dict) -> None:
        asset_id, path = item["id"], item["originalPath"]
        self._ids_by_path.setdefault(path, set()).add(asset_id)
        self._paths_by_id.setdefault(asset_id, set()).add(path)

    def assert_asset_identity(self, asset_id: str, original_path: str) -> None:
        """Validate an edge against ALL identities seen during this operation."""
        if (self._ids_by_path.get(original_path) != {asset_id}
                or self._paths_by_id.get(asset_id) != {original_path}):
            raise AssetIdentityError("Immich path and asset id are not a unique consistent pair")

    def observed_paths(self, asset_id: str) -> set[str]:
        """Every ``originalPath`` this operation has seen for *asset_id*."""
        return set(self._paths_by_id.get(asset_id, ()))

    def _iter_search_pages(self, payload: dict[str, object]):
        """Yield the raw items of a paged ``POST /search/metadata`` read;
        fail on malformed pages or non-advancing cursors."""
        page = 1
        while True:
            data = self._request("POST", "/api/search/metadata", {**payload, "page": page}) or {}
            if not isinstance(data, dict) or not isinstance(data.get("assets"), dict):
                raise AssetIdentityError("Immich returned an invalid search response")
            assets = data["assets"]
            if not isinstance(assets.get("items"), list):
                raise AssetIdentityError("Immich returned an invalid asset list")
            yield from assets["items"]
            next_page = assets.get("nextPage")
            if next_page is None:
                return
            if (isinstance(next_page, bool)
                    or not (isinstance(next_page, int)
                            or isinstance(next_page, str) and next_page.isascii() and next_page.isdecimal())):
                raise AssetIdentityError("Immich returned invalid pagination")
            try:
                next_page = int(next_page)
            except (TypeError, ValueError) as ex:
                raise AssetIdentityError("Immich returned invalid pagination") from ex
            if next_page <= page:
                raise AssetIdentityError("Immich returned non-advancing pagination")
            page = next_page

    def _iter_assets(self, original_path: str | None = None):
        """Read every page, including stacked assets; fail on bad cursors."""
        payload: dict[str, object] = {"withStacked": True}
        if original_path is not None:
            payload["originalPath"] = original_path
        for item in self._iter_search_pages(payload):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise AssetIdentityError("Immich returned an asset without a valid id")
            if not isinstance(item.get("originalPath"), str) or not item["originalPath"]:
                raise AssetIdentityError("Immich returned an asset without originalPath")
            if self._in_scope(item):
                self._observe_asset(item)
                yield item

    def search_asset_id(self, original_path: str) -> str | None:
        """Resolve exactly one matching path across ALL pages, never the first hit."""
        ids = {item["id"] for item in self._iter_assets(original_path)
               if item["originalPath"] == original_path}
        if len(ids) > 1:
            raise AssetIdentityError(f"Multiple Immich assets have originalPath {original_path}")
        asset_id = next(iter(ids), None)
        if asset_id is not None:
            self.assert_asset_identity(asset_id, original_path)
        return asset_id

    def iter_asset_paths(self):
        """Yield scoped ``(originalPath, id)`` pairs without hiding duplicates."""
        for item in self._iter_assets():
            yield item["originalPath"], item["id"]

    def verify_asset_id(self, asset_id: str, original_path: str) -> str:
        """Treat a webhook ID as a hint, verified on the configured server."""
        if not isinstance(asset_id, str) or not asset_id:
            raise AssetIdentityError("Immich webhook asset id must be a nonempty string")
        item = self._request("GET", "/api/assets/" + quote(asset_id, safe="")) or {}
        if (not isinstance(item, dict) or item.get("id") != asset_id or item.get("originalPath") != original_path
                or not self._in_scope(item)):
            raise AssetIdentityError("Immich webhook asset id does not match the mapped path or scope")
        self._observe_asset(item)
        if self.search_asset_id(original_path) != asset_id:
            raise AssetIdentityError("Immich webhook asset id is not the unique mapped path identity")
        return asset_id

    def update_assets(self, ids: list[str], fields: dict) -> None:
        for start in range(0, len(ids), UPDATE_CHUNK):
            self._request("PUT", "/api/assets", {"ids": ids[start:start + UPDATE_CHUNK], **fields})

    def find_album_id(self, name: str) -> str | None:
        albums = self._request("GET", "/api/albums") or []
        for album in albums:
            if album.get("albumName") == name:
                return album.get("id")
        return None

    def create_album(self, name: str, asset_ids: list[str]) -> str:
        album = self._request("POST", "/api/albums", {"albumName": name, "assetIds": asset_ids}) or {}
        return album.get("id", "")

    def add_album_assets(self, album_id: str, asset_ids: list[str]) -> None:
        for start in range(0, len(asset_ids), UPDATE_CHUNK):
            self._request("PUT", f"/api/albums/{album_id}/assets",
                          {"ids": asset_ids[start:start + UPDATE_CHUNK]})

    def remove_album_assets(self, album_id: str, asset_ids: list[str]) -> None:
        for start in range(0, len(asset_ids), UPDATE_CHUNK):
            self._request("DELETE", f"/api/albums/{quote(album_id, safe='')}/assets",
                          {"ids": asset_ids[start:start + UPDATE_CHUNK]})

    def album_asset_ids(self, album_id: str) -> list[str] | None:
        """Current member ids of an album, or ``None`` when the read is unusable.

        ``GET /albums/:id`` no longer carries the asset list on current Immich
        (the response is counts and dates only), so membership comes from the
        same paged metadata search the asset resolution uses, filtered by
        ``albumIds``. The diff needs the whole list, so a partially malformed
        response counts as no information at all rather than partial truth:
        the caller degrades to add-only instead of removing on bad data.
        """
        try:
            ids = []
            for item in self._iter_search_pages({"albumIds": [album_id], "withStacked": True}):
                if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                    return None
                ids.append(item["id"])
            return ids
        except AssetIdentityError:
            return None


def _effective_rating(star_rating) -> int | None:
    if star_rating is not None and 1 <= star_rating <= 5:
        return int(star_rating)
    return None


def map_facet_path(path: str, path_map: list[dict]) -> str | None:
    """Translate a Facet absolute path to Immich's ``originalPath``.

    Uses the first literal prefix match (not a directory-boundary match). With no
    configured pairs (or only placeholder empty ones) the path is passed
    through unchanged. Returns *None* when pairs exist but none match.
    """
    pairs = [p for p in path_map if p.get("facet_prefix")]
    if not pairs:
        return path
    for pair in pairs:
        prefix = pair["facet_prefix"]
        if path.startswith(prefix):
            return pair.get("immich_prefix", "") + path[len(prefix):]
    return None


def map_immich_path(original_path: str, path_map: list[dict]) -> str | None:
    """Translate an Immich ``originalPath`` back to a Facet absolute path.

    The inverse of :func:`map_facet_path`, over the pairs that can actually be
    inverted: BOTH prefixes must be set. A pair carrying a ``facet_prefix`` and
    no ``immich_prefix`` maps outbound onto a bare relative path, and matching
    it inbound would mean testing ``startswith("")`` — true of every path, so
    one such pair would shadow every later pair and swallow the whole map.

    Same first-match rule and same two outcomes as the outbound direction: with
    no invertible pair at all the path passes through unchanged, and *None*
    means invertible pairs exist but none matched.
    """
    pairs = [p for p in path_map if p.get("facet_prefix") and p.get("immich_prefix")]
    if not pairs:
        return original_path
    for pair in pairs:
        prefix = pair["immich_prefix"]
        if original_path.startswith(prefix):
            return pair["facet_prefix"] + original_path[len(prefix):]
    return None


def _row_rating(row, push_rejected: bool) -> int | None:
    """The rating a row would push — the album threshold reads the same one.

    Rejection outranks stars exactly as in :func:`_push_fields`: with
    *push_rejected* on, an ``is_rejected`` photo rates Immich's rejected -1
    whatever its stars.
    """
    if push_rejected and row["is_rejected"]:
        return REJECTED_RATING
    return _effective_rating(row["star_rating"])


def _push_fields(row, prev: dict, push_ratings: bool, push_favorites: bool,
                 push_rejected: bool) -> tuple[dict, int | None, bool]:
    """Build one row's Immich update payload; returns ``(fields, rating, favorite)``.

    An empty ``fields`` means there is nothing to send. A row previously pushed
    active (per *prev*, the tracked synced state) that has since gone inactive
    still yields an explicit clear — ``rating: null`` / ``isFavorite: false`` —
    even though a never-touched row never pushes a bare clear. The clear value
    must be null, never 0: Immich v3 rejects rating 0 outright ("null
    (unrated); 0 is not valid").

    Rejection outranks stars: with *push_rejected* on, an ``is_rejected`` photo
    pushes Immich's own rejected value (-1) whatever its star rating, because a
    photo the user threw away is not a 5-star one.
    """
    rating = _row_rating(row, push_rejected)
    favorite = bool(row["is_favorite"])
    fields: dict = {}
    if push_ratings and (rating is not None or prev.get("rating")):
        fields["rating"] = rating
    if push_favorites and (favorite or fields or prev.get("favorite")):
        fields["isFavorite"] = favorite
    return fields, rating, favorite


def _active_state(fields: dict) -> dict:
    """What of *fields* was pushed as ACTIVE, for the synced-state tracker.

    Derived from the fields actually sent (not the raw DB columns) so a field
    disabled via ``push.ratings`` / ``push.favorites`` is never tracked as if
    it had been pushed. ``bool(-1)`` is True, so a rejected push tracks as an
    active rating and un-rejecting therefore still emits its clear.
    """
    return {"rating": bool(fields.get("rating")),
            "favorite": fields.get("isFavorite") is True}


def _resolve_push_flags(immich_cfg: dict) -> tuple[bool, bool, bool]:
    """``(ratings, favorites, rejected)`` from the ``immich.push`` block.

    ``rejected`` is ANDed with ``ratings``: -1 IS a rating write, so a config
    that disabled rating pushes must not smuggle one back in.
    """
    push_cfg = immich_cfg.get("push", {})
    push_ratings = push_cfg.get("ratings", True)
    push_favorites = push_cfg.get("favorites", True)
    return push_ratings, push_favorites, bool(push_cfg.get("rejected", False)) and push_ratings


def _make_client(immich_cfg: dict) -> "ImmichClient":
    api_key = immich_cfg.get("api_key", "")
    if not api_key:
        raise ValueError("immich.api_key is not configured")
    return ImmichClient(immich_cfg.get("url", ""), api_key,
                        timeout=immich_cfg.get("timeout_seconds", 30),
                        owner_id=immich_cfg.get("owner_id", ""),
                        library_id=immich_cfg.get("library_id", ""))


@contextmanager
def _state_write(db_path):
    """One serialized read-modify-write of a ``stats_cache`` side-table blob.

    Both trackers here (the synced-state map, the pending list) are a whole
    JSON document under a single key, so a load-mutate-save that interleaves
    with another one silently drops the other's entries. Two webhook
    deliveries arriving together did exactly that.

    The mutex is doubled on purpose: :data:`_STATE_LOCK` orders the threads of
    this process (the FastAPI threadpool, where the deliveries actually race),
    and ``BEGIN IMMEDIATE`` takes SQLite's RESERVED lock before the *read* so a
    separate process — a ``--immich-sync`` running alongside the viewer —
    cannot slip a write in between. Callers must do their load AND their save
    inside the block; the commit happens on the way out.
    """
    with _STATE_LOCK:
        with get_connection(db_path) as conn:
            conn.isolation_level = None  # explicit transaction control
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            conn.commit()


def _scope_key(scope: str | None) -> str:
    """stats_cache key for the per-scope "paths last pushed active" state."""
    return f"immich_synced_paths:{scope or 'global'}"


def _load_synced_state(conn, scope: str | None) -> dict:
    """Paths whose rating and/or favorite were ACTIVE as of the last successful push.

    ``{path: {"rating": bool, "favorite": bool}}``, persisted in ``stats_cache``
    (a generic key/value side table — no schema change needed). This is what
    lets a photo that gets reset to 0/false be recognised as needing an
    explicit clear even though it no longer matches the "currently active"
    half of the ``_fetch_rating_rows`` WHERE clause.
    """
    row = conn.execute(
        "SELECT value FROM stats_cache WHERE key = ?", (_scope_key(scope),)
    ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return {}


def _save_synced_state(conn, scope: str | None, state: dict) -> None:
    """Write the blob. Call inside :func:`_state_write`, which owns the commit."""
    conn.execute(
        "INSERT INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (_scope_key(scope), json.dumps(state), time.time()),
    )


def _pending_key(scope: str | None) -> str:
    """stats_cache key for the paths a webhook flagged as unknown to Facet."""
    return f"immich_webhook_pending:{scope or 'global'}"


def _load_pending(conn, scope: str | None) -> list:
    row = conn.execute(
        "SELECT value FROM stats_cache WHERE key = ?", (_pending_key(scope),)
    ).fetchone()
    if not row or not row[0]:
        return []
    try:
        data = json.loads(row[0])
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, str)]


def _save_pending(conn, scope: str | None, paths: list) -> None:
    """Write the blob. Call inside :func:`_state_write`, which owns the commit."""
    conn.execute(
        "INSERT INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (_pending_key(scope), json.dumps(paths), time.time()),
    )


def record_pending_paths(db_path, facet_paths,
                         max_pending: int = DEFAULT_MAX_PENDING) -> int:
    """Remember the Immich assets Facet has not scored yet; return the pending count.

    One serialized read-modify-write for the whole batch: a webhook delivery
    carrying several unknown assets costs one connection and one round trip of
    this blob, not one per asset. Deduplicated and bounded (oldest dropped
    first) so a chatty Immich instance can never grow this side-table row
    without limit. Nothing is scanned here — the list exists purely so the next
    ``--immich-sync`` can report the gap.
    """
    with _state_write(db_path) as conn:
        pending = _load_pending(conn, None)
        known = set(pending)
        added = False
        for facet_path in facet_paths:
            if facet_path in known:
                continue
            known.add(facet_path)
            pending.append(facet_path)
            added = True
        if added:
            if max_pending > 0 and len(pending) > max_pending:
                pending = pending[-max_pending:]
            _save_pending(conn, None, pending)
        return len(pending)


def record_pending_path(db_path, facet_path: str,
                        max_pending: int = DEFAULT_MAX_PENDING) -> int:
    """One path's :func:`record_pending_paths`; returns the pending count."""
    return record_pending_paths(db_path, [facet_path], max_pending=max_pending)


def load_pending_paths(db_path) -> list:
    """Paths recorded by the webhook as unknown, oldest first."""
    with get_connection(db_path) as conn:
        return _load_pending(conn, None)


def _report_pending(db_path, dry_run: bool) -> int:
    """Log the still-unscored webhook paths and drop the ones now scored.

    Returns how many remain. A path that has since been scanned AND scored
    leaves the list; the rest are logged so an Immich upload that Facet never
    picked up is visible from an ordinary sync run.
    """
    connection = get_connection(db_path, read_only=True) if dry_run else _state_write(db_path)
    with connection as conn:
        pending = _load_pending(conn, None)
        if not pending:
            return 0
        scored = set(_fetch_scored_photos(conn, pending))
        remaining = [p for p in pending if p not in scored]
        if remaining != pending and not dry_run:
            _save_pending(conn, None, remaining)
    for path in remaining[:UNMATCHED_LOG_LIMIT]:
        logger.warning("Immich webhook saw an asset Facet has not scored: %s", path)
    if len(remaining) > UNMATCHED_LOG_LIMIT:
        logger.warning("... and %d more unscored webhook path(s)",
                       len(remaining) - UNMATCHED_LOG_LIMIT)
    return len(remaining)


def _rating_exprs(user_id: str | None) -> tuple[str, str, str, str, list]:
    """``(join, star_expr, fav_expr, rejected_expr, params)`` for the rating read.

    Mirrors the xmp_export overlay: when *user_id* is given the per-user
    ``user_preferences`` overlay replaces the global rating columns (COALESCE-d
    to 0), same as ``export_sidecars``.
    """
    if user_id:
        return (
            "LEFT JOIN user_preferences up ON up.photo_path = photos.path AND up.user_id = ?",
            "COALESCE(up.star_rating, 0)", "COALESCE(up.is_favorite, 0)",
            "COALESCE(up.is_rejected, 0)", [user_id],
        )
    return "", "star_rating", "is_favorite", "is_rejected", []


def _fetch_rating_rows(conn, user_id: str | None, extra_paths=(),
                       push_rejected: bool = False) -> list:
    """Read paths that can push a rating 1-5 / ``isFavorite=true``, plus any
    path in *extra_paths* whose rating/favorite may have just been reset.

    A row that is neither currently active nor in *extra_paths* is excluded —
    it can never push anything (a never-touched photo has no clear to push
    either). With *push_rejected* on, a rejected row is "active" too: it has a
    -1 to push even with no stars and no favorite.

    The *extra_paths* read (the tracked synced state) runs in chunks of
    :data:`PATH_QUERY_CHUNK`: it grows with the pushed half of the library,
    and one ``IN (...)`` over all of it hits SQLite's host-parameter limit
    and wedges every later sync before any network work happens.
    """
    join, star_expr, fav_expr, rej_expr, params = _rating_exprs(user_id)
    where = f"({star_expr} BETWEEN 1 AND 5) OR {fav_expr} = 1"
    if push_rejected:
        where += f" OR {rej_expr} = 1"
    select = (f"SELECT photos.path AS path, {star_expr} AS star_rating, "
              f"{fav_expr} AS is_favorite, {rej_expr} AS is_rejected FROM photos {join} ")
    rows = {row["path"]: row for row in conn.execute(f"{select}WHERE {where}", params)}
    extra_paths = list(extra_paths)
    for start in range(0, len(extra_paths), PATH_QUERY_CHUNK):
        chunk = extra_paths[start:start + PATH_QUERY_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        for row in conn.execute(
            f"{select}WHERE photos.path IN ({placeholders})", params + chunk):
            rows.setdefault(row["path"], row)  # the active row already won
    return list(rows.values())


def _fetch_scored_photos(conn, facet_paths) -> dict:
    """``{path: row}`` for the scored photos among *facet_paths* — one read.

    A path missing from the result is deliberately ambiguous between "never
    scanned" and "scanned but unscored": the webhook has nothing meaningful to
    push for either, and both belong on the pending list.
    """
    unique = list(dict.fromkeys(facet_paths))
    found: dict = {}
    for start in range(0, len(unique), PATH_QUERY_CHUNK):
        chunk = unique[start:start + PATH_QUERY_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        for row in conn.execute(
            f"SELECT path, star_rating, is_favorite, is_rejected FROM photos "
            f"WHERE path IN ({placeholders}) AND aggregate IS NOT NULL", chunk
        ):
            found[row["path"]] = row
    return found


def _existing_paths(conn, paths) -> set:
    """The subset of *paths* that still exist in ``photos``.

    Chunked like every other path ``IN (...)`` read, so pruning an unbounded
    tracked state cannot itself hit the host-parameter limit.
    """
    wanted = list(paths)
    found: set = set()
    for start in range(0, len(wanted), PATH_QUERY_CHUNK):
        chunk = wanted[start:start + PATH_QUERY_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        found.update(row[0] for row in conn.execute(
            f"SELECT path FROM photos WHERE path IN ({placeholders})", chunk))
    return found


def sync_to_immich(db_path, config: dict, user_id: str | None = None,
                   dry_run: bool = False) -> dict:
    """Push Facet ratings/favorites to the configured Immich server.

    Returns a summary dict: ``matched`` / ``unmatched`` / ``updated`` /
    ``skipped_unrated`` / ``identity_conflicts`` / ``albums_created`` /
    ``album_added`` / ``album_removed`` / ``album_remove_failed`` /
    ``webhook_pending``. Conflicts are refused, not counted as matched. With
    *dry_run* the assets and the album plan are still resolved (read-only
    requests) but nothing is written: ``album_added`` / ``album_removed``
    report what a real run would do.
    """
    immich_cfg = config.get("immich", {})
    client = _make_client(immich_cfg)
    push_cfg = immich_cfg.get("push", {})
    push_ratings, push_favorites, push_rejected = _resolve_push_flags(immich_cfg)
    album_name = push_cfg.get("top_picks_album", "")
    album_min_rating = push_cfg.get("top_picks_min_rating", 4)
    path_map = immich_cfg.get("path_map", [])
    multi_user = any(k != "shared_directories" for k in config.get("users", {}))
    scope = user_id if multi_user else None
    with get_connection(db_path, read_only=dry_run) as conn:
        synced_state = _load_synced_state(conn, scope)
        rows = _fetch_rating_rows(conn, scope, extra_paths=synced_state.keys(),
                                  push_rejected=push_rejected)
    summary = {"matched": 0, "unmatched": 0, "updated": 0,
               "skipped_unrated": 0, "albums_created": 0, "webhook_pending": 0,
               "identity_conflicts": 0, "album_added": 0, "album_removed": 0,
               "album_remove_failed": 0}
    groups: dict[tuple, list[str]] = {}
    album_asset_ids: list[str] = []
    unmatched_paths: list[str] = []
    matched_paths: set[str] = set()
    conflict_messages: list[tuple[str, str]] = []

    def record_conflict(facet_path, error):
        summary["identity_conflicts"] += 1
        if len(conflict_messages) < UNMATCHED_LOG_LIMIT:
            conflict_messages.append((facet_path, str(error)))

    # First pass (no network): compute each row's push payload and target path.
    # _push_fields owns the clear/rejection rules — one rejected batch aborts
    # the whole sync before synced_state advances, wedging every later run.
    resolvable: list[tuple] = []
    for row in rows:
        facet_path = row["path"]
        prev = synced_state.get(facet_path, {})
        fields, rating, favorite = _push_fields(
            row, prev, push_ratings, push_favorites, push_rejected)
        if not fields:
            summary["skipped_unrated"] += 1
            continue
        resolvable.append(
            (facet_path, map_facet_path(facet_path, path_map), fields, rating, favorite))

    try:
        # One bulk pass builds a local path index; misses fall back to per-path.
        # The index is only a lookup shortcut. The client's complete observed
        # registry, not this dictionary, decides whether an identity is unique.
        path_index = {}
        ambiguous = set()
        for path, asset_id in client.iter_asset_paths() if resolvable else ():
            path_index[path] = asset_id
        # Two Facet roots mapping onto one remote path would otherwise push
        # competing ratings into the same asset. Refuse both, even if identical.
        mapped_paths = [entry[1] for entry in resolvable if entry[1]]
        seen = set()
        for path in mapped_paths:
            if path in seen:
                ambiguous.add(path)
            seen.add(path)
        resolved_candidates = []
        for facet_path, immich_path, fields, rating, favorite in resolvable:
            asset_id = None
            try:
                if immich_path in ambiguous:
                    raise AssetIdentityError("Multiple assets or Facet paths map to the same Immich path")
                if immich_path:
                    asset_id = path_index.get(immich_path) or client.search_asset_id(immich_path)
            except AssetIdentityError as ex:
                record_conflict(facet_path, ex)
                continue
            if asset_id is None or not immich_path:
                summary["unmatched"] += 1
                unmatched_paths.append(facet_path)
                continue
            resolved_candidates.append((facet_path, immich_path, asset_id, fields, rating))
        # Separate exact-path fallbacks can each look unique while claiming
        # the same UUID. Validate the complete plan before grouping any writes.
        for facet_path, immich_path, asset_id, fields, rating in resolved_candidates:
            try:
                client.assert_asset_identity(asset_id, immich_path)
            except AssetIdentityError as ex:
                record_conflict(facet_path, ex)
                continue
            summary["matched"] += 1
            matched_paths.add(facet_path)
            groups.setdefault(tuple(sorted(fields.items())), []).append(asset_id)
            if rating is not None and rating >= album_min_rating:
                album_asset_ids.append(asset_id)
        for key, ids in groups.items():
            if not dry_run:
                client.update_assets(ids, dict(key))
            summary["updated"] += len(ids)
        if not dry_run:
            # The tracked state is committed BEFORE the album step: the
            # ratings and favourites above are pushed, so an album hiccup
            # (a key without the delete scope, a mid-step network drop) must
            # cost at most the album work, never a re-push of everything on
            # the next run. Only rows actually confirmed pushed
            # (matched_paths) advance the tracked state; an unmatched row
            # keeps its prior entry so the next sync retries it instead of
            # losing the clear. Re-read inside the serialized write: the pass
            # above is network-bound, so a webhook delivery may have advanced
            # the blob since, and writing back the snapshot taken before it
            # would drop that delivery's entries.
            with _state_write(db_path) as write_conn:
                current = _load_synced_state(write_conn, scope)
                new_state = dict(current)
                for facet_path, _, fields, _, _ in resolvable:
                    if facet_path not in matched_paths:
                        continue
                    active = _active_state(fields)
                    if active["rating"] or active["favorite"]:
                        new_state[facet_path] = active
                    else:
                        new_state.pop(facet_path, None)
                # A photo deleted from Facet can never push another clear, so
                # its tracked entry is dead weight: drop it here, or the blob
                # grows without bound and wedges the chunked fetch above.
                alive = _existing_paths(write_conn, new_state)
                pruned = {p: v for p, v in new_state.items() if p in alive}
                if len(pruned) < len(new_state):
                    logger.info("Dropped %d gone path(s) from the Immich synced state",
                                len(new_state) - len(pruned))
                if pruned != current:
                    _save_synced_state(write_conn, scope, pruned)
        if album_name:
            album_asset_ids = list(dict.fromkeys(album_asset_ids))
            album_id = client.find_album_id(album_name)
            created = False
            if album_id:
                try:
                    current_members = client.album_asset_ids(album_id)
                except PUSH_ERRORS as e:
                    current_members = None
                    logger.warning("Could not read membership of album %s (%s); "
                                   "adding without pruning", album_name, e)
            elif album_asset_ids and not dry_run:
                # The create call carries the first chunk; the remainder goes
                # through the chunked add like every other album write.
                album_id = client.create_album(album_name, album_asset_ids[:UPDATE_CHUNK])
                created = True
                current_members = []
                if album_asset_ids[UPDATE_CHUNK:]:
                    client.add_album_assets(album_id, album_asset_ids[UPDATE_CHUNK:])
            else:
                current_members = None  # nothing qualifies, no album to create
            to_add: list[str] = []
            to_remove: list[str] = []
            if album_id and not created:
                to_add = album_asset_ids
                if current_members is None:
                    logger.warning("Could not read membership of album %s; "
                                   "adding without pruning", album_name)
                else:
                    have = set(current_members)
                    # The album mirrors the threshold, and an existing member
                    # is never re-added. A member is removed only when this
                    # run can PROVE it no longer qualifies: observed on exactly
                    # one remote path, mapped back to a Facet row below the
                    # threshold. Everything it cannot attribute — a photo
                    # deleted from Facet, another app's asset, an identity
                    # that stopped resolving, a row skipped because its push
                    # was disabled — stays. A per-user sync (whose rows are
                    # that user's overlay, not the library the album name is
                    # global to) adds but never removes.
                    to_remove = []
                    if scope is None:
                        to_add = [a for a in album_asset_ids if a not in have]
                        qualifying = set(album_asset_ids)
                        rows_by_path = {row["path"]: row for row in rows}
                        for asset_id in current_members:
                            if asset_id in qualifying:
                                continue
                            seen = client.observed_paths(asset_id)
                            if len(seen) != 1:
                                continue
                            row = rows_by_path.get(
                                map_immich_path(next(iter(seen)), path_map))
                            if row is None:
                                continue
                            rating = _row_rating(row, push_rejected)
                            if rating is None or rating < album_min_rating:
                                to_remove.append(asset_id)
                    else:
                        to_add = [a for a in album_asset_ids if a not in have]
                if dry_run:
                    summary["album_added"] = len(to_add)
                    summary["album_removed"] = len(to_remove)
                else:
                    if to_add:
                        client.add_album_assets(album_id, to_add)
                        summary["album_added"] = len(to_add)
                    if to_remove:
                        try:
                            client.remove_album_assets(album_id, to_remove)
                            summary["album_removed"] = len(to_remove)
                            logger.info("Removed %d asset(s) no longer rated at or above the "
                                        "top-picks threshold from %s", len(to_remove), album_name)
                        except PUSH_ERRORS as e:
                            # The ratings are pushed and recorded; a refused
                            # removal (an API key without the delete scope,
                            # say) must not fail the sync — it is counted so
                            # the operator sees the album drifted less than
                            # the threshold asks.
                            summary["album_remove_failed"] = len(to_remove)
                            logger.warning("Could not remove %d asset(s) from %s: %s",
                                           len(to_remove), album_name, e)
            elif created:
                summary["album_added"] = len(album_asset_ids)
                summary["albums_created"] = 1
            elif album_asset_ids and dry_run:
                # A dry run would create the album with the full qualifying
                # set; report that plan without the create.
                summary["album_added"] = len(album_asset_ids)
    except (urllib_error.URLError, TimeoutError) as e:
        setattr(e, "partial_summary", dict(summary))
        raise
    for path, reason in conflict_messages:
        logger.warning("Immich identity conflict for %s: %s", path, reason)
    if summary["identity_conflicts"] > len(conflict_messages):
        logger.warning("... and %d more identity conflicts",
                       summary["identity_conflicts"] - len(conflict_messages))
    for path in unmatched_paths[:UNMATCHED_LOG_LIMIT]:
        logger.warning("No Immich asset found for %s", path)
    if len(unmatched_paths) > UNMATCHED_LOG_LIMIT:
        logger.warning("... and %d more unmatched paths",
                       len(unmatched_paths) - UNMATCHED_LOG_LIMIT)
    summary["webhook_pending"] = _report_pending(db_path, dry_run)
    return summary


def _commit_pushed_state(db_path, pushed: dict) -> None:
    """Fold one delivery's confirmed pushes into the synced-state blob, atomically.

    Re-read inside the serialized transaction for the same reason
    :func:`sync_to_immich` does: a concurrent CLI sync or a second webhook
    delivery may have advanced the blob while this one was talking to Immich.
    """
    try:
        with _state_write(db_path) as conn:
            state = _load_synced_state(conn, None)
            changed = False
            for facet_path, active in pushed.items():
                if active["rating"] or active["favorite"]:
                    if state.get(facet_path) != active:
                        state[facet_path] = active
                        changed = True
                elif state.pop(facet_path, None) is not None:
                    changed = True
            if changed:
                _save_synced_state(conn, None, state)
    except sqlite3.Error as e:
        # The assets DID reach Immich; only the "was pushed active" memo
        # failed. Losing it costs a redundant push next time, never a wrong
        # one — not worth failing a delivery that already succeeded.
        logger.warning("Could not record Immich synced state for %d path(s): %s",
                       len(pushed), e, exc_info=True)


def push_photo_updates(db_path, config: dict, entries) -> list:
    """Push a whole webhook delivery to Immich; one ``(result, error)`` per entry.

    *entries* is an iterable of ``(facet_path, asset_id_or_None)`` and the
    return value is one pair per entry, in order: :data:`RESULT_PUSHED`,
    :data:`RESULT_SKIPPED` (nothing to send), :data:`RESULT_UNMATCHED` (no
    Immich asset resolvable), :data:`RESULT_UNKNOWN` (path not in the library,
    or not scored yet), or :data:`RESULT_FAILED` carrying the exception that
    isolated that one asset. A supplied ``asset_id`` is verified against the
    mapped path and configured scope on the configured server before updating.

    This is :func:`sync_to_immich`'s own shape applied to the webhook: ONE
    connection reads every row and the synced-state blob once, the per-asset
    decisions run in memory, assets sharing one payload write as one batched
    call, and ONE serialized transaction writes the blob back after the loop.
    Per-asset it was two connections and two full round trips of that blob —
    quadratic in the delivery's size, and lost updates whenever two deliveries
    interleaved.

    It never raises for the classes in :data:`PUSH_ERRORS`: a delivery that
    already pushed three assets must not fail because the fourth's socket
    dropped. Scope is always global — a webhook arrives with no user context,
    so it reads the ``photos`` rating columns, never a ``user_preferences``
    overlay.
    """
    entries = list(entries)
    if not entries:
        return []
    immich_cfg = config.get("immich", {})
    push_ratings, push_favorites, push_rejected = _resolve_push_flags(immich_cfg)
    try:
        client = _make_client(immich_cfg)
        with get_connection(db_path) as conn:
            rows = _fetch_scored_photos(conn, [path for path, _ in entries])
            synced_state = _load_synced_state(conn, None)
    except PUSH_ERRORS as e:
        # Delivery-wide: an unconfigured api_key or an unreadable DB fails
        # every asset identically, and each still gets its own tallied result
        # rather than an exception escaping into the caller's response.
        logger.warning("Immich push could not start for %d asset(s): %s",
                       len(entries), e, exc_info=True)
        return [(RESULT_FAILED, e)] * len(entries)

    # Resolve local collisions BEFORE the first remote write. A payload may
    # contain multiple different Facet paths that collapse through path_map,
    # or claim the same remote ID for different photos. Refuse every eligible
    # entry in those collisions, rather than letting delivery order pick a
    # winning rating. Unknown/unrated entries still keep their usual result.
    target_paths: dict[str, set[str]] = {}
    hint_paths: dict[str, set[str]] = {}
    for facet_path, asset_id in entries:
        row = rows.get(facet_path)
        if row is None:
            continue
        fields, _, _ = _push_fields(row, synced_state.get(facet_path, {}),
                                    push_ratings, push_favorites, push_rejected)
        if not fields:
            continue
        target = map_facet_path(facet_path, immich_cfg.get("path_map", []))
        if target:
            target_paths.setdefault(target, set()).add(facet_path)
        if isinstance(asset_id, str) and asset_id:
            hint_paths.setdefault(asset_id, set()).add(facet_path)
    conflicting_paths = set()
    for paths in (*target_paths.values(), *hint_paths.values()):
        if len(paths) > 1:
            conflicting_paths.update(paths)

    results: list[tuple[str, BaseException | None]] = []
    pushed: dict[str, dict] = {}
    planned: list[tuple[int, str, str, str, dict]] = []
    for facet_path, asset_id in entries:
        row = rows.get(facet_path)
        if row is None:
            results.append((RESULT_UNKNOWN, None))
            continue
        fields, _, _ = _push_fields(row, synced_state.get(facet_path, {}),
                                    push_ratings, push_favorites, push_rejected)
        if not fields:
            results.append((RESULT_SKIPPED, None))
            continue
        try:
            if facet_path in conflicting_paths:
                raise AssetIdentityError("Multiple Facet paths claim the same Immich path or asset id")
            immich_path = map_facet_path(facet_path, immich_cfg.get("path_map", []))
            resolved = None
            if immich_path:
                resolved = (client.verify_asset_id(asset_id, immich_path) if asset_id
                            else client.search_asset_id(immich_path))
            if not resolved or not immich_path:
                results.append((RESULT_UNMATCHED, None))
                continue
        except PUSH_ERRORS as e:
            results.append((RESULT_FAILED, e))
            continue
        planned.append((len(results), facet_path, immich_path, resolved, fields))
        results.append((RESULT_SKIPPED, None))  # filled after every identity is resolved

    # Recheck after EVERY lookup, including observations made by an unmatched
    # or failed entry. They can disprove an earlier candidate's identity.
    # Assets sharing one payload then write as ONE batched call (update_assets
    # chunks it) — a delivery capped at 100 assets cost up to 100 serial
    # round trips before. A batch that is refused falls back to per-asset
    # writes, so one bad id still cannot take the rest down with it.
    write_groups: dict[tuple, list[tuple[int, str, str]]] = {}
    for index, facet_path, immich_path, resolved, fields in planned:
        try:
            if facet_path in conflicting_paths:
                raise AssetIdentityError("Multiple Facet paths resolved to the same Immich asset id")
            client.assert_asset_identity(resolved, immich_path)
        except PUSH_ERRORS as e:
            results[index] = (RESULT_FAILED, e)
            continue
        write_groups.setdefault(tuple(sorted(fields.items())), []).append(
            (index, facet_path, resolved))
    for key, members in write_groups.items():
        fields = dict(key)
        ids = list(dict.fromkeys(asset_id for _, _, asset_id in members))
        try:
            client.update_assets(ids, fields)
            for index, facet_path, _ in members:
                pushed[facet_path] = _active_state(fields)
                results[index] = (RESULT_PUSHED, None)
        except PUSH_ERRORS:
            for index, facet_path, asset_id in members:
                try:
                    client.update_assets([asset_id], fields)
                except PUSH_ERRORS as e:
                    results[index] = (RESULT_FAILED, e)
                    continue
                pushed[facet_path] = _active_state(fields)
                results[index] = (RESULT_PUSHED, None)

    if pushed:
        _commit_pushed_state(db_path, pushed)
    return results


def push_photo_update(db_path, config: dict, facet_path: str,
                      asset_id: str | None = None) -> str:
    """Push exactly one Facet photo's rating/favorite to Immich, right now.

    A single-entry :func:`push_photo_updates` — same payload rules, same
    synced-state tracking — that re-raises the isolated failure so a one-shot
    caller still sees an exception rather than a status string.
    """
    result, error = push_photo_updates(db_path, config, [(facet_path, asset_id)])[0]
    if error is not None:
        raise error
    return result
