"""One-way push of Facet ratings/favorites into an Immich server via its REST API.

Facet photo paths are mapped to Immich ``originalPath`` values through the
configured ``immich.path_map`` prefix pairs, resolved to asset ids with
``POST /api/search/metadata``, and updated with batched ``PUT /api/assets``
calls grouped by identical payload. Only ratings 1-5 are ever pushed (never 0,
never -1); an optional single top-picks album is filled from a minimum-rating
threshold. Immich's database is never touched — REST only.

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


def _fetch_rating_rows(conn, user_id: str | None) -> list:
    """Read only paths that can push a rating 1-5 or ``isFavorite=true``.

    Mirrors the xmp_export overlay: when *user_id* is given the per-user
    ``user_preferences`` overlay replaces the global rating columns (COALESCE-d
    to 0), same as ``export_sidecars``. Pure-rejected rows (no rating, not a
    favorite) are excluded — they can never push anything.
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
    return conn.execute(
        f"SELECT photos.path AS path, {star_expr} AS star_rating, "
        f"{fav_expr} AS is_favorite FROM photos {join} "
        f"WHERE ({star_expr} BETWEEN 1 AND 5) OR {fav_expr} = 1",
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
    with get_connection(db_path) as conn:
        rows = _fetch_rating_rows(conn, user_id if multi_user else None)
    summary = {"matched": 0, "unmatched": 0, "updated": 0,
               "skipped_unrated": 0, "albums_created": 0}
    groups: dict[tuple, list[str]] = {}
    album_asset_ids: list[str] = []
    unmatched_paths: list[str] = []

    # First pass (no network): compute each row's push payload and target path.
    resolvable: list[tuple] = []
    for row in rows:
        rating = _effective_rating(row["star_rating"])
        favorite = bool(row["is_favorite"])
        fields: dict = {}
        if push_ratings and rating is not None:
            fields["rating"] = rating
        if push_favorites and (favorite or fields):
            fields["isFavorite"] = favorite
        if not fields:
            summary["skipped_unrated"] += 1
            continue
        resolvable.append(
            (row["path"], map_facet_path(row["path"], path_map), fields, rating))

    try:
        # One bulk pass builds a local path index; misses fall back to per-path.
        path_index = dict(client.iter_asset_paths()) if resolvable else {}
        for facet_path, immich_path, fields, rating in resolvable:
            asset_id = None
            if immich_path:
                asset_id = path_index.get(immich_path) or client.search_asset_id(immich_path)
            if asset_id is None:
                summary["unmatched"] += 1
                unmatched_paths.append(facet_path)
                continue
            summary["matched"] += 1
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
    except (urllib_error.URLError, TimeoutError) as e:
        e.partial_summary = dict(summary)
        raise
    for path in unmatched_paths[:UNMATCHED_LOG_LIMIT]:
        logger.warning("No Immich asset found for %s", path)
    if len(unmatched_paths) > UNMATCHED_LOG_LIMIT:
        logger.warning("... and %d more unmatched paths",
                       len(unmatched_paths) - UNMATCHED_LOG_LIMIT)
    return summary
