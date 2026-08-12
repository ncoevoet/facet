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
optional single top-picks album is filled from a minimum-rating threshold.
Immich's database is never touched — REST only.

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
            "top_picks_album": "",
            "top_picks_min_rating": 4
        },
        "timeout_seconds": 30
    }
"""

from __future__ import annotations

import json
import logging
import time
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

from db import get_connection

logger = logging.getLogger(__name__)

UPDATE_CHUNK = 500
UNMATCHED_LOG_LIMIT = 20


class ImmichClient:
    """Minimal REST client for the Immich API (``x-api-key`` auth)."""

    def __init__(self, url: str, api_key: str, timeout: int = 30) -> None:
        self.base_url = self._validate_url(url)
        self.api_key = api_key
        self.timeout = timeout

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
            body = resp.read()
        return json.loads(body) if body else None

    def ping(self) -> dict:
        """GET /api/server/about — verifies both connectivity and the API key."""
        return self._request("GET", "/api/server/about") or {}

    def search_asset_id(self, original_path: str) -> str | None:
        """Resolve an Immich asset id by exact ``originalPath`` (paginated)."""
        page = 1
        while True:
            data = self._request(
                "POST", "/api/search/metadata",
                {"originalPath": original_path, "page": page},
            ) or {}
            assets = data.get("assets", {})
            items = assets.get("items", [])
            if items:
                return items[0]["id"]
            next_page = assets.get("nextPage")
            if not next_page:
                return None
            page = int(next_page)

    def iter_asset_paths(self):
        """Yield ``(originalPath, id)`` for every asset by paging the search endpoint.

        One bulk pass builds a local ``originalPath -> id`` index so the sync
        resolves most assets without a per-photo round-trip; only misses fall
        back to :meth:`search_asset_id`.
        """
        page = 1
        while True:
            data = self._request("POST", "/api/search/metadata", {"page": page}) or {}
            assets = data.get("assets", {})
            for item in assets.get("items", []):
                original_path = item.get("originalPath")
                if original_path:
                    yield original_path, item["id"]
            next_page = assets.get("nextPage")
            if not next_page:
                return
            page = int(next_page)

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
        self._request("PUT", f"/api/albums/{album_id}/assets", {"ids": asset_ids})


def _effective_rating(star_rating) -> int | None:
    if star_rating is not None and 1 <= star_rating <= 5:
        return int(star_rating)
    return None


def map_facet_path(path: str, path_map: list[dict]) -> str | None:
    """Translate a Facet absolute path to Immich's ``originalPath``.

    Uses the first ``path_map`` pair whose ``facet_prefix`` matches. With no
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
    conn.execute(
        "INSERT INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (_scope_key(scope), json.dumps(state), time.time()),
    )
    conn.commit()


def _fetch_rating_rows(conn, user_id: str | None, extra_paths=()) -> list:
    """Read paths that can push a rating 1-5 / ``isFavorite=true``, plus any
    path in *extra_paths* whose rating/favorite may have just been reset.

    Mirrors the xmp_export overlay: when *user_id* is given the per-user
    ``user_preferences`` overlay replaces the global rating columns (COALESCE-d
    to 0), same as ``export_sidecars``. A row that is neither currently active
    nor in *extra_paths* is excluded — it can never push anything (a
    never-touched photo has no clear to push either).
    """
    if user_id:
        join = ("LEFT JOIN user_preferences up ON up.photo_path = photos.path "
                "AND up.user_id = ?")
        star_expr = "COALESCE(up.star_rating, 0)"
        fav_expr = "COALESCE(up.is_favorite, 0)"
        params = [user_id]
    else:
        join = ""
        star_expr, fav_expr = "star_rating", "is_favorite"
        params = []
    where = f"({star_expr} BETWEEN 1 AND 5) OR {fav_expr} = 1"
    extra_paths = list(extra_paths)
    if extra_paths:
        where += f" OR photos.path IN ({','.join('?' * len(extra_paths))})"
        params = params + extra_paths
    return conn.execute(
        f"SELECT photos.path AS path, {star_expr} AS star_rating, "
        f"{fav_expr} AS is_favorite FROM photos {join} "
        f"WHERE {where}",
        params,
    ).fetchall()


def sync_to_immich(db_path, config: dict, user_id: str | None = None,
                   dry_run: bool = False) -> dict:
    """Push Facet ratings/favorites to the configured Immich server.

    Returns a summary dict: ``matched`` / ``unmatched`` / ``updated`` /
    ``skipped_unrated`` / ``albums_created``. With *dry_run* the assets are
    still resolved (read-only requests) but nothing is written.
    """
    immich_cfg = config.get("immich", {})
    api_key = immich_cfg.get("api_key", "")
    if not api_key:
        raise ValueError("immich.api_key is not configured")
    client = ImmichClient(
        immich_cfg.get("url", ""), api_key,
        timeout=immich_cfg.get("timeout_seconds", 30),
    )
    push_cfg = immich_cfg.get("push", {})
    push_ratings = push_cfg.get("ratings", True)
    push_favorites = push_cfg.get("favorites", True)
    album_name = push_cfg.get("top_picks_album", "")
    album_min_rating = push_cfg.get("top_picks_min_rating", 4)
    path_map = immich_cfg.get("path_map", [])
    multi_user = any(k != "shared_directories" for k in config.get("users", {}))
    scope = user_id if multi_user else None
    with get_connection(db_path) as conn:
        synced_state = _load_synced_state(conn, scope)
        rows = _fetch_rating_rows(conn, scope, extra_paths=synced_state.keys())
    summary = {"matched": 0, "unmatched": 0, "updated": 0,
               "skipped_unrated": 0, "albums_created": 0}
    groups: dict[tuple, list[str]] = {}
    album_asset_ids: list[str] = []
    unmatched_paths: list[str] = []
    matched_paths: set[str] = set()

    # First pass (no network): compute each row's push payload and target path.
    # A row previously pushed active (tracked in synced_state) that has since
    # gone inactive still gets an explicit clear — null / false — even though a
    # never-touched row never pushes a bare clear. That is the ONLY reason a
    # null rating or false favorite is ever added to fields below. The clear
    # value must be null, never 0: Immich v3 rejects rating 0 outright
    # ("null (unrated); 0 is not valid"), and one rejected batch aborts the
    # whole sync before synced_state advances, wedging every later run.
    resolvable: list[tuple] = []
    for row in rows:
        facet_path = row["path"]
        prev = synced_state.get(facet_path, {})
        rating = _effective_rating(row["star_rating"])
        favorite = bool(row["is_favorite"])
        fields: dict = {}
        if push_ratings and (rating is not None or prev.get("rating")):
            fields["rating"] = rating
        if push_favorites and (favorite or fields or prev.get("favorite")):
            fields["isFavorite"] = favorite
        if not fields:
            summary["skipped_unrated"] += 1
            continue
        resolvable.append(
            (facet_path, map_facet_path(facet_path, path_map), fields, rating, favorite))

    try:
        # One bulk pass builds a local path index; misses fall back to per-path.
        path_index = dict(client.iter_asset_paths()) if resolvable else {}
        for facet_path, immich_path, fields, rating, favorite in resolvable:
            asset_id = None
            if immich_path:
                asset_id = path_index.get(immich_path) or client.search_asset_id(immich_path)
            if asset_id is None:
                summary["unmatched"] += 1
                unmatched_paths.append(facet_path)
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
        if album_name and album_asset_ids and not dry_run:
            album_id = client.find_album_id(album_name)
            if album_id:
                client.add_album_assets(album_id, album_asset_ids)
            else:
                client.create_album(album_name, album_asset_ids)
                summary["albums_created"] = 1
        if not dry_run:
            # Only rows actually confirmed pushed (matched_paths) advance the
            # tracked state; an unmatched row keeps its prior entry so the next
            # sync retries it instead of losing the clear. Derived from the
            # ACTUAL fields sent (not the raw DB rating/favorite) so a field
            # disabled via push_ratings/push_favorites is never tracked as if
            # it had been pushed.
            new_state = dict(synced_state)
            for facet_path, _, fields, _, _ in resolvable:
                if facet_path not in matched_paths:
                    continue
                active = {"rating": bool(fields.get("rating")),
                         "favorite": fields.get("isFavorite") is True}
                if active["rating"] or active["favorite"]:
                    new_state[facet_path] = active
                else:
                    new_state.pop(facet_path, None)
            if new_state != synced_state:
                with get_connection(db_path) as write_conn:
                    _save_synced_state(write_conn, scope, new_state)
    except (urllib_error.URLError, TimeoutError) as e:
        e.partial_summary = dict(summary)
        raise
    for path in unmatched_paths[:UNMATCHED_LOG_LIMIT]:
        logger.warning("No Immich asset found for %s", path)
    if len(unmatched_paths) > UNMATCHED_LOG_LIMIT:
        logger.warning("... and %d more unmatched paths",
                       len(unmatched_paths) - UNMATCHED_LOG_LIMIT)
    return summary
