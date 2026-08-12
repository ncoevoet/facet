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

Two surfaces share those payload rules: :func:`sync_to_immich` (the whole
library, driven by ``--immich-sync``) and :func:`push_photo_update` (exactly
one asset, driven by the inbound webhook in ``api/routers/immich.py``). Both
go through :func:`_push_fields`, so a rule fixed in one is fixed in both.

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
import time
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

from db import get_connection

logger = logging.getLogger(__name__)

UPDATE_CHUNK = 500
UNMATCHED_LOG_LIMIT = 20
DEFAULT_MAX_PENDING = 500

REJECTED_RATING = -1

RESULT_PUSHED = "pushed"
RESULT_SKIPPED = "skipped"
RESULT_UNMATCHED = "unmatched"
RESULT_UNKNOWN = "unknown"


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


def map_immich_path(original_path: str, path_map: list[dict]) -> str | None:
    """Translate an Immich ``originalPath`` back to a Facet absolute path.

    Exact inverse of :func:`map_facet_path` — same pair set (those carrying a
    ``facet_prefix``), same first-match rule — so a path that round-trips out
    through the sync round-trips back in through the webhook.
    """
    pairs = [p for p in path_map if p.get("facet_prefix")]
    if not pairs:
        return original_path
    for pair in pairs:
        prefix = pair.get("immich_prefix", "")
        if original_path.startswith(prefix):
            return pair["facet_prefix"] + original_path[len(prefix):]
    return None


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
    if push_rejected and row["is_rejected"]:
        rating = REJECTED_RATING
    else:
        rating = _effective_rating(row["star_rating"])
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
                        timeout=immich_cfg.get("timeout_seconds", 30))


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
    conn.execute(
        "INSERT INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (_pending_key(scope), json.dumps(paths), time.time()),
    )
    conn.commit()


def record_pending_path(db_path, facet_path: str,
                        max_pending: int = DEFAULT_MAX_PENDING) -> int:
    """Remember an Immich asset Facet has not scored yet; return the pending count.

    Deduplicated and bounded (oldest dropped first) so a chatty Immich instance
    can never grow this side-table row without limit. Nothing is scanned here —
    the list exists purely so the next ``--immich-sync`` can report the gap.
    """
    with get_connection(db_path) as conn:
        pending = _load_pending(conn, None)
        if facet_path in pending:
            return len(pending)
        pending.append(facet_path)
        if max_pending > 0 and len(pending) > max_pending:
            pending = pending[-max_pending:]
        _save_pending(conn, None, pending)
        return len(pending)


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
    with get_connection(db_path) as conn:
        pending = _load_pending(conn, None)
        if not pending:
            return 0
        placeholders = ",".join("?" * len(pending))
        scored = {r[0] for r in conn.execute(
            f"SELECT path FROM photos WHERE path IN ({placeholders}) "
            f"AND aggregate IS NOT NULL", pending)}
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
    """
    join, star_expr, fav_expr, rej_expr, params = _rating_exprs(user_id)
    where = f"({star_expr} BETWEEN 1 AND 5) OR {fav_expr} = 1"
    if push_rejected:
        where += f" OR {rej_expr} = 1"
    extra_paths = list(extra_paths)
    if extra_paths:
        where += f" OR photos.path IN ({','.join('?' * len(extra_paths))})"
        params = params + extra_paths
    return conn.execute(
        f"SELECT photos.path AS path, {star_expr} AS star_rating, "
        f"{fav_expr} AS is_favorite, {rej_expr} AS is_rejected FROM photos {join} "
        f"WHERE {where}",
        params,
    ).fetchall()


def _fetch_scored_photo(conn, facet_path: str):
    """One scored photo's rating columns, or None when unknown/unscored.

    An unscored row is deliberately indistinguishable from a missing one here:
    the webhook has nothing meaningful to push for either, and both belong on
    the pending list.
    """
    return conn.execute(
        "SELECT path, star_rating, is_favorite, is_rejected FROM photos "
        "WHERE path = ? AND aggregate IS NOT NULL",
        (facet_path,),
    ).fetchone()


def sync_to_immich(db_path, config: dict, user_id: str | None = None,
                   dry_run: bool = False) -> dict:
    """Push Facet ratings/favorites to the configured Immich server.

    Returns a summary dict: ``matched`` / ``unmatched`` / ``updated`` /
    ``skipped_unrated`` / ``albums_created`` / ``webhook_pending``. With
    *dry_run* the assets are still resolved (read-only requests) but nothing
    is written.
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
    with get_connection(db_path) as conn:
        synced_state = _load_synced_state(conn, scope)
        rows = _fetch_rating_rows(conn, scope, extra_paths=synced_state.keys(),
                                  push_rejected=push_rejected)
    summary = {"matched": 0, "unmatched": 0, "updated": 0,
               "skipped_unrated": 0, "albums_created": 0, "webhook_pending": 0}
    groups: dict[tuple, list[str]] = {}
    album_asset_ids: list[str] = []
    unmatched_paths: list[str] = []
    matched_paths: set[str] = set()

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
            # sync retries it instead of losing the clear.
            new_state = dict(synced_state)
            for facet_path, _, fields, _, _ in resolvable:
                if facet_path not in matched_paths:
                    continue
                active = _active_state(fields)
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
    summary["webhook_pending"] = _report_pending(db_path, dry_run)
    return summary


def push_photo_update(db_path, config: dict, facet_path: str,
                      asset_id: str | None = None) -> str:
    """Push exactly one Facet photo's rating/favorite to Immich, right now.

    The inbound-webhook counterpart of :func:`sync_to_immich`: same payload
    rules (via :func:`_push_fields`), same synced-state tracking, no bulk
    listing pass. Returns one of :data:`RESULT_PUSHED`, :data:`RESULT_SKIPPED`
    (nothing to send), :data:`RESULT_UNMATCHED` (no Immich asset resolvable)
    or :data:`RESULT_UNKNOWN` (path not in the library, or not scored yet).

    *asset_id* short-circuits path resolution when the caller already has it —
    a webhook payload carries the id, so the common case costs one request.

    Scope is always global: a webhook arrives with no user context, so it reads
    the ``photos`` rating columns, never a ``user_preferences`` overlay.
    """
    immich_cfg = config.get("immich", {})
    push_ratings, push_favorites, push_rejected = _resolve_push_flags(immich_cfg)
    client = _make_client(immich_cfg)
    with get_connection(db_path) as conn:
        row = _fetch_scored_photo(conn, facet_path)
        synced_state = _load_synced_state(conn, None)
    if row is None:
        return RESULT_UNKNOWN
    fields, _, _ = _push_fields(row, synced_state.get(facet_path, {}),
                                push_ratings, push_favorites, push_rejected)
    if not fields:
        return RESULT_SKIPPED
    if not asset_id:
        immich_path = map_facet_path(facet_path, immich_cfg.get("path_map", []))
        asset_id = client.search_asset_id(immich_path) if immich_path else None
    if not asset_id:
        return RESULT_UNMATCHED
    client.update_assets([asset_id], fields)
    active = _active_state(fields)
    # Re-read under the write connection: a concurrent CLI sync may have
    # advanced the state between the read above and this write.
    with get_connection(db_path) as write_conn:
        state = _load_synced_state(write_conn, None)
        if active["rating"] or active["favorite"]:
            state[facet_path] = active
        else:
            state.pop(facet_path, None)
        _save_synced_state(write_conn, None, state)
    return RESULT_PUSHED
