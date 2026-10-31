"""
Database helper functions for the FastAPI API server.

"""

import asyncio
import functools
import hashlib
import logging
import math
import ntpath
import os
import random
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional

from fastapi import HTTPException, Query
from fastapi.requests import HTTPConnection

from api.config import (
    _existing_columns_cache, _existing_columns_lock,
    _photo_tags_available, _photo_tags_lock, PHOTO_TAGS_CACHE_TTL,
    _count_cache, _count_cache_lock, COUNT_CACHE_TTL,
    is_multi_user_enabled, get_user_directories, _FULL_CONFIG, VIEWER_CONFIG,
    config_load_failed, server_scoring_config, invalidate_stats_cache,
)
from api import database as _database
from api import organization_capture
from api.change_token import db_change_token
from api.database import get_db_connection
from comparison.comparison_manager import record_culling_pairs
from db import DEFAULT_DB_PATH
from db.person_centroids import recompute_person_centroid
from db.manual_tags import TAG_SEPARATOR, normalize_manual_tag, ManualTagError
from utils.detection import DEFAULT_PHOTO_THUMBNAIL_SIZE
from utils.exit_codes import LIBRARY_LOCK_HELD_EXIT_CODE
from utils.panorama import KINDS as PANORAMA_KINDS
from utils.sequence import BRACKET as BRACKET_KIND

logger = logging.getLogger("facet.api.db_helpers")

# Interactive write retry. SQLite allows one writer per database file, so a
# background writer holding the lock (ranker retrain, rating-comparison sync,
# WAL checkpoint, an out-of-process scan) makes a concurrent user write wait out
# busy_timeout and fail. These bursts are short, so a few backed-off retries turn
# a hard error into a slightly slower success.
RETRY_ATTEMPTS = 4
RETRY_BASE_DELAY = 0.05
# Wall clock the RETRIES may spend, counted from the first lock error, attempts
# notwithstanding. The first attempt has already waited out the connection's own
# `busy_timeout` (5 s) when it reports the lock, so a budget counted from the
# call's start was spent before the first retry and no retry ever ran. Each retry
# can wait out busy_timeout again, so an attempt count alone would let one sync
# handler hold one of the 40 anyio threadpool tokens for ~20 s before answering
# 503. Whichever limit is reached first ends the retries, so a burst that clears
# instantly still gets all its attempts. The budget is checked before a retry
# starts, never during one, and it starts at the first lock error, so a retry can
# start up to the whole budget later (after quick failures such as an immediate
# SQLITE_BUSY_SNAPSHOT) and then sit out busy_timeout again: the worst case is
# 5 + 2.5 + 5, about 12.5 s before the 503. No retry is made while this process
# builds the gallery indexes (about 5 s), but the build status is per process:
# with --workers N only the worker that builds skips the retry, and a write that
# reaches another worker can still take up to about 12.5 s.
RETRY_BUDGET_SECONDS = 2.5

# The stable `detail` code of the 503 answered when SQLite reports the database
# locked or busy past every wait (api/__init__.py maps any such error escaping a
# route to it). The client keys its "try again in a moment" message on it.
LIBRARY_BUSY_DETAIL = 'library_busy'
LIBRARY_BUSY_RETRY_AFTER_SECONDS = 5


# SQLITE_BUSY as Python's sqlite3 words it ("database is locked"), plus the
# wording SQLite uses for the same code elsewhere. SQLITE_LOCKED ("database
# table is locked", "database schema is locked") is a conflict inside one
# connection, which waiting does not clear, so it is deliberately not matched.
_BUSY_MESSAGES = ('database is locked', 'database is busy')


def after_commit() -> None:
    """Drop the in-process caches a committed organization/tag write makes stale."""
    # Local import: api.routers.burst_culling imports this module (import cycle).
    from api.routers.burst_culling import _invalidate_culling_groups_cache
    invalidate_stats_cache()
    _invalidate_culling_groups_cache()


def is_locked_error(ex) -> bool:
    """True for a transient SQLite busy error (another writer holds the lock).

    Lets callers tell "come back in a moment" apart from a genuine schema or
    constraint failure, which must still surface as a 500.
    """
    if not isinstance(ex, sqlite3.OperationalError):
        return False
    message = str(ex).lower()
    return any(busy in message for busy in _BUSY_MESSAGES)


def retry_on_locked(attempts=RETRY_ATTEMPTS, base_delay=RETRY_BASE_DELAY,
                    budget_seconds=RETRY_BUDGET_SECONDS):
    """Retry a write handler while SQLite reports the database busy/locked.

    Retries the WHOLE handler rather than just the commit: these handlers read
    the current value before writing the new one (toggles), so a retry has to
    re-read or it would persist a decision made against stale state. Anything
    that is not a lock error propagates untouched on the first raise.

    Retrying stops at ``attempts`` OR once ``budget_seconds`` of wall clock is
    spent after the first lock error, whichever comes first — each attempt can
    itself sit out the connection's ``busy_timeout``, so an attempt count alone
    does not bound how long the caller's threadpool token is held. No retry is
    made while this process builds its gallery indexes: one index is seconds to
    minutes of write lock, so a retry would only hold the token longer. Giving
    up re-raises the lock error, which the app's handler answers with 503
    ``library_busy`` + Retry-After — the write is still possible, the server is
    merely busy, so it is not a 500.
    """
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            first_lock_error_at = None
            for attempt in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except sqlite3.OperationalError as ex:
                    if not is_locked_error(ex):
                        raise
                    now = time.monotonic()
                    if first_lock_error_at is None:
                        first_lock_error_at = now
                    # Exponential backoff, jittered so parallel writers from the
                    # same burst don't line up and collide again in lockstep.
                    delay = base_delay * (2 ** attempt) * (0.5 + random.random())
                    retrying_for = now - first_lock_error_at
                    if (attempt == attempts - 1
                            or retrying_for + delay >= budget_seconds
                            or gallery_index_build_running()):
                        raise
                    time.sleep(delay)
        return wrapper
    return decorate


def gallery_index_build_running() -> bool:
    """True while this process builds the gallery indexes (api/schema_startup.py)."""
    from api.schema_startup import index_build_status
    return index_build_status()['state'] == 'building'


def refuse_while_gallery_index_build_runs() -> None:
    """Refuse, as busy, a ``facet.py`` child that needs the library lock.

    The gallery index build holds ``facet.LibraryLock`` for its whole run, so a
    child spawned meanwhile fails on that lock and its route would answer 500.
    Raising the busy error before spawning answers 503 ``library_busy`` through the
    app's handler (api/__init__.py) instead, like any other write refused during
    the build.
    """
    if gallery_index_build_running():
        raise sqlite3.OperationalError(
            f"{_BUSY_MESSAGES[0]} (the gallery index build holds the library lock)")


def library_lock_held_error(returncode):
    """The busy error for a ``facet.py`` child that exited on a held library lock, else None.

    The library lock, not this process's build status, is the source of truth:
    another worker's index build, a scan or a CLI recompute holds it just the
    same. Raise the route's own 5xx ``from`` it, and the app's handler
    (api/__init__.py) answers 503 ``library_busy`` instead.
    """
    if returncode != LIBRARY_LOCK_HELD_EXIT_CODE:
        return None
    return sqlite3.OperationalError(
        f"{_BUSY_MESSAGES[0]} (another library job holds the library lock)")


def _schema_caches_warm(now: float) -> bool:
    """True when no cached schema probe would open a connection for a while yet."""
    from api import config as _config_mod
    with _existing_columns_lock:
        if _existing_columns_cache is None:
            return False
    with _photo_tags_lock:
        # Refreshed at half its lifetime, so it cannot expire between this check
        # and the handler that reads it.
        if (_photo_tags_available is None
                or now - _config_mod._photo_tags_checked_at >= PHOTO_TAGS_CACHE_TTL / 2):
            return False
    # Refreshed at half its lifetime, like photo_tags above.
    if _manual_tags_cached(str(DEFAULT_DB_PATH), now, PHOTO_TAGS_CACHE_TTL / 2) is None:
        return False
    from api.change_token import change_token_sentinel_open
    return change_token_sentinel_open(DEFAULT_DB_PATH)


def _warm_schema_caches() -> None:
    from api import config as _config_mod
    get_existing_columns()
    with _photo_tags_lock:
        if time.monotonic() - _config_mod._photo_tags_checked_at >= PHOTO_TAGS_CACHE_TTL / 2:
            # Expire it so the call below re-probes instead of answering from cache.
            _config_mod._photo_tags_checked_at = 0.0
    key = str(DEFAULT_DB_PATH)
    if _manual_tags_cached(key, time.monotonic(), PHOTO_TAGS_CACHE_TTL / 2) is None:
        _manual_tags_present.pop(key, None)
    is_photo_tags_available()
    is_manual_tags_available()
    db_change_token(DEFAULT_DB_PATH)


async def warm_schema_caches(request: HTTPConnection) -> None:
    """App-wide dependency: fill the cached schema probes on a worker thread.

    The column list, the photo_tags and photo_manual_tags probes and the
    change-token sentinel are read synchronously deep inside async handlers
    (``build_photo_select_columns``, ``_add_tag_filter``, the count-cache key);
    a cold or expiring entry would open a SQLite connection on the event loop
    and stall every request in flight. Warm, this costs a few lookups. The
    liveness route is skipped: it reads in-process state only and must answer
    without touching the database.
    """
    from api.routers.health import LIVENESS_PATH
    route = request.scope.get("route")
    if getattr(route, "path", None) == LIVENESS_PATH or _schema_caches_warm(time.monotonic()):
        return
    try:
        await asyncio.to_thread(_warm_schema_caches)
    except Exception:
        # Never fail a request over a warm-up: the handler that needs a probe
        # runs it itself and reports its own error.
        logger.debug("Warming the schema caches failed", exc_info=True)


def trigger_auto_retrain(db_path, user_id, added=1, conn=None):
    """Best-effort, non-blocking nudge to the personal-ranker auto-retrain.

    A culling confirm or rating change derives ``added`` new comparison pairs;
    once enough accumulate per user the personal ranker retrains in the
    background. Owns the ``added <= 0`` guard and the multi-user scope
    resolution so every caller (burst-culling confirm, similar-group confirm,
    rating sync) stays consistent. Isolated so a missing optimization dep
    (e.g. sklearn) or any failure never affects the write that already
    committed.

    Args:
        db_path: Path to the SQLite DB.
        user_id: Raw request user id; resolved to a per-user scope only when
            multi-user mode is enabled, else pooled into the global ranker.
        added: How many new comparisons this event contributed.
        conn: An already-open SQLite connection from the request that just
            committed; reused for the counter update so the hot culling-confirm
            path doesn't open a second connection. ``None`` (rating sync, CLI)
            opens a short-lived one.
    """
    if added <= 0:
        return
    try:
        from optimization.auto_retrain import maybe_retrain
        scope = user_id if (user_id and is_multi_user_enabled()) else None
        maybe_retrain(db_path, scope, added=added, conn=conn)
    except Exception:  # noqa: BLE001 — never let retrain bookkeeping break the request
        logger.debug("Auto-retrain trigger skipped", exc_info=True)


@organization_capture.grouped
def record_culling_decision(conn, keep_paths, reject_paths, sequence_members,
                            user_id=None, group_type='burst', commit=True, record=True):
    """Persist keepers, record ranker training pairs, commit, nudge retrain.

    ``sequence_members`` are the paths belonging to a keep-whole sequence set
    (bracket/panorama/hdr_panorama, resolved by
    ``api.routers.burst_culling._sequence_members``). They are dropped from both
    sides first: a comparison pair there would teach the ranker how the set was
    shot -- which frame of a pan, which rung of an exposure ladder -- rather
    than any quality judgement.

    EVERY feed that writes pairs from a culling decision goes through here, so
    that exclusion cannot be forgotten by the next one. That is four: the burst,
    similar and scene confirms, and the ``/api/culling/auto`` sweep. The sweep
    was the counter-example this helper is named for -- it tested the GROUP's
    ``sequence_kind``, which ``_group_sequence_kind`` sets to ``None`` for a
    mixed group, so a scene holding a panorama plus ordinary frames wrote
    "pan tile 3 beat pan tile 5" pairs while looking guarded.

    ``commit=False`` is for exactly that sweep: it batches many groups into one
    transaction and fires ONE ``trigger_auto_retrain`` for the whole run, so
    committing per group would publish a half-finished sweep and nudging per
    group would arm the retrain N times. The caller then owns both. When it is
    left True the commit is part of the contract -- ``trigger_auto_retrain``
    must only ever see a decision that is already durable.

    ``record=False`` is for a decision an assistant made through the agent layer
    (``CurrentUser.is_agent_request``): nothing is paired, so it never trains the
    ranker or arms the auto-retrain counter. The commit stays part of the contract.

    Returns the number of comparison rows inserted.
    """
    set_photos_kept(conn, keep_paths, user_id, agent=not record)
    if not record:
        if commit:
            conn.commit()
        return 0
    pairable_keep = [p for p in keep_paths if p not in sequence_members]
    pairable_reject = [p for p in reject_paths if p not in sequence_members]
    added = record_culling_pairs(
        conn, pairable_keep, pairable_reject, user_id=user_id, group_type=group_type,
    )
    if commit:
        conn.commit()
        trigger_auto_retrain(DEFAULT_DB_PATH, user_id, added, conn=conn)
    return added


# --- DATE FORMATTING ---

def to_exif_date(iso_date: str) -> str:
    """Convert ISO date (2024-03-11) to EXIF format (2024:03:11)."""
    return iso_date.replace('-', ':')


def to_iso_date(exif_date: str) -> str:
    """Convert EXIF date prefix (2024:03:11...) to ISO (2024-03-11)."""
    return exif_date[:10].replace(':', '-')


_TIMESTAMP_FORMS = "'YYYY-MM-DD', 'YYYY-MM-DD HH:MM[:SS]', 'YYYY-MM-DDTHH:MM[:SS]', 'YYYY:MM:DD' or 'YYYY:MM:DD HH:MM:SS'"
_TIMESTAMP_RE = re.compile(
    r"^(\d{4})([-:])(\d{2})\2(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?$")


def parse_timestamp(value: str) -> tuple[datetime, bool]:
    """Parse a date or datetime in ISO or EXIF notation; returns ``(moment, has_time)``.

    Accepts ``YYYY-MM-DD``, ``YYYY-MM-DD[T ]HH:MM[:SS]``, ``YYYY:MM:DD`` and
    ``YYYY:MM:DD HH:MM:SS``. Raises ``ValueError`` naming the accepted forms.
    """
    match = _TIMESTAMP_RE.match(value.strip()) if isinstance(value, str) else None
    if not match:
        raise ValueError(f"{value!r} is not a date; use {_TIMESTAMP_FORMS}")
    year, _, month, day, hour, minute, second = match.groups()
    try:
        moment = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0),
                          int(second or 0))
    except ValueError:
        raise ValueError(f"{value!r} is not a real date; use {_TIMESTAMP_FORMS}") from None
    return moment, hour is not None


def to_second_granularity(value: str, end_of_day: bool = False) -> str:
    """Normalise to ``YYYY:MM:DD HH:MM:SS``; a date-only value gets 00:00:00 (23:59:59 if ``end_of_day``)."""
    moment, has_time = parse_timestamp(value)
    if end_of_day and not has_time:
        moment = moment.replace(hour=23, minute=59, second=59)
    return f"{moment.year:04d}" + moment.strftime(":%m:%d %H:%M:%S")


def window_or_400(date_from: Optional[str], date_to: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """The culling routes' capture-time window in the stored ``YYYY:MM:DD HH:MM:SS`` form.

    ``date_taken`` is EXIF text compared lexicographically, so an ISO bound would match
    nothing. A date-only ``date_to`` covers the whole day. Idempotent on EXIF input; an
    unparseable bound is a 400 naming the accepted forms.
    """
    try:
        return (to_second_granularity(date_from) if date_from else None,
                to_second_granularity(date_to, end_of_day=True) if date_to else None)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=f"date_from/date_to: {ex}") from None


def to_day_granularity(value: str) -> str:
    """Normalise to ``YYYY-MM-DD``; refuses a time component (the route compares whole days)."""
    moment, has_time = parse_timestamp(value)
    if has_time:
        raise ValueError(f"{value!r} has a time of day, but this filter works on whole days; "
                         "use 'YYYY-MM-DD'")
    return f"{moment.year:04d}" + moment.strftime("-%m-%d")


def format_date(date_str):
    """Format EXIF date string (YYYY:MM:DD HH:MM:SS) to DD/MM/YYYY HH:MM."""
    if not date_str or not isinstance(date_str, str):
        return ''
    try:
        parts = date_str.split(' ')
        date_part = parts[0].replace(':', '/')
        date_components = date_part.split('/')
        if len(date_components) == 3:
            date_part = f"{date_components[2]}/{date_components[1]}/{date_components[0]}"
        time_part = parts[1][:5] if len(parts) > 1 else ''
        return f"{date_part} {time_part}".strip()
    except (IndexError, AttributeError):
        return str(date_str)


# --- SQL FRAGMENT CONSTANTS ---
def hide_bursts_sql(table_alias: str = '') -> str:
    """WHERE fragment keeping only photos that hide-bursts must not hide.

    ``burst_group_id IS NULL`` means the photo belongs to no burst at all, so it
    is always visible: an interrupted scan whose burst post-processing never ran
    leaves ``is_burst_lead = 0`` on standalone photos, and without this guard
    they would vanish from the gallery.
    """
    p = f"{table_alias}." if table_alias else ""
    # `is_sequence_lead` is exempted because the two hide clauses are ANDed and
    # pick their representative on unrelated criteria: the burst lead is
    # score-ranked, the panorama lead is the middle frame by capture. A sweep is
    # routinely shredded across several burst groups, so with both toggles on --
    # both ship on -- the two clauses could agree on no frame at all and the
    # whole set vanished from the gallery.
    return (f"({p}is_burst_lead = 1 OR {p}is_burst_lead IS NULL "
            f"OR {p}burst_group_id IS NULL OR {p}is_sequence_lead = 1)")


def hide_duplicates_sql(table_alias: str = '') -> str:
    """WHERE fragment keeping only photos that hide-duplicates must not hide."""
    p = f"{table_alias}." if table_alias else ""
    return (f"({p}is_duplicate_lead = 1 OR {p}is_duplicate_lead IS NULL"
            f" OR {p}duplicate_group_id IS NULL)")


HIDE_BLINKS_SQL = "(is_blink = 0 OR is_blink IS NULL)"
HIDE_BURSTS_SQL = hide_bursts_sql()
HIDE_DUPLICATES_SQL = hide_duplicates_sql()
HIDDEN_BURST_SQL = (
    "(is_burst_lead = 0 AND burst_group_id IS NOT NULL "
    "AND (is_sequence_lead IS NULL OR is_sequence_lead = 0))")
HIDDEN_DUPLICATE_SQL = "(is_duplicate_lead = 0 AND duplicate_group_id IS NOT NULL)"

# Keep every ordinary photo plus the base exposure of each bracket. Deliberately
# independent of burst state: hiding non-leads only collapses a bracket that
# happens to sit alone in a burst group, and a quarter of them share one with
# unrelated frames, where the lead is not the base exposure and the flanking
# exposures stay on show.
HIDE_BRACKETS_SQL = (
    f"(sequence_kind IS NULL OR sequence_kind != '{BRACKET_KIND}' "
    "OR sequence_ev_offset = 0)")
HIDDEN_BRACKET_SQL = f"(sequence_kind = '{BRACKET_KIND}' AND sequence_ev_offset != 0)"

# The same idea for panorama sets, keyed on the marked representative rather
# than on an exposure offset a pan does not have. Scoped by kind on both sides:
# before it was, `hide_brackets` -- on by default -- silently hid every frame of
# every panorama, because their kind is not NULL and their ev_offset is.
PANORAMA_KINDS_SQL = "(" + ", ".join(f"'{kind}'" for kind in PANORAMA_KINDS) + ")"
HIDE_PANORAMAS_SQL = (
    f"(sequence_kind IS NULL OR sequence_kind NOT IN {PANORAMA_KINDS_SQL} "
    "OR is_sequence_lead = 1)")
HIDDEN_PANORAMA_SQL = (
    f"(sequence_kind IN {PANORAMA_KINDS_SQL} AND is_sequence_lead = 0)")


DATE_FILTER_EXPR = "DATE(REPLACE(SUBSTR(date_taken,1,10),':','-'))"


def build_date_range_clauses(date_from, date_to):
    """Build WHERE clauses for date range filtering on EXIF date_taken."""
    clauses, params = [], []
    if date_from:
        clauses.append(f"{DATE_FILTER_EXPR} >= ?")
        params.append(date_from)
    if date_to:
        clauses.append(f"{DATE_FILTER_EXPR} <= ?")
        params.append(date_to)
    return clauses, params


def album_filter_clause(album_id, table_alias='photos'):
    """WHERE fragment restricting photos to an album's membership.

    Returns ``(sql, params)``. An empty/invalid ``album_id`` yields
    ``('1=1', [])`` so the fragment is always safe to AND into a query.
    Shared by the gallery, scenes and culling endpoints so album scoping is
    defined in exactly one place.
    """
    if album_id in (None, '', 0, '0'):
        return '1=1', []
    try:
        aid = int(album_id)
    except (ValueError, TypeError):
        return '1=1', []
    return (
        f"{table_alias}.path IN (SELECT photo_path FROM album_photos WHERE album_id = ?)",
        [aid],
    )


def time_window_clauses(date_from=None, date_to=None, column='date_taken'):
    """WHERE clauses bounding ``date_taken`` to an EXIF capture-time window.

    Used to scope scenes/culling to a single scene's ``[start, end]`` window.
    ``date_from``/``date_to`` are raw EXIF date strings
    (``YYYY:MM:DD HH:MM:SS``) which sort lexicographically against
    ``date_taken``. Returns ``(clauses, params)``.
    """
    clauses, params = [], []
    if date_from:
        clauses.append(f"{column} >= ?")
        params.append(date_from)
    if date_to:
        clauses.append(f"{column} <= ?")
        params.append(date_to)
    return clauses, params


def build_hide_clauses(hide_blinks: str, hide_bursts: str, hide_duplicates: str,
                       hide_brackets: str = '', hide_panoramas: str = '') -> list[str]:
    """Convert hide-toggle string params ('1'/'true') to SQL WHERE fragments.

    `hide_brackets` and `hide_panoramas` default to off here so the many callers
    that pass three toggles keep their exact behaviour; the gallery, which owns
    the user-facing defaults, passes them explicitly.
    """
    clauses = []
    if hide_blinks in ('1', 'true'):
        clauses.append(HIDE_BLINKS_SQL)
    if hide_bursts in ('1', 'true'):
        clauses.append(HIDE_BURSTS_SQL)
    if hide_duplicates in ('1', 'true'):
        clauses.append(HIDE_DUPLICATES_SQL)
    if hide_brackets in ('1', 'true'):
        clauses.append(HIDE_BRACKETS_SQL)
    if hide_panoramas in ('1', 'true'):
        clauses.append(HIDE_PANORAMAS_SQL)
    return clauses


HIDE_TOGGLE_KEYS = ('hide_blinks', 'hide_bursts', 'hide_duplicates',
                    'hide_brackets', 'hide_panoramas', 'hide_rejected')


def resolve_hide_defaults(params: dict) -> dict:
    """Fill absent hide toggles from ``viewer.defaults``, leaving explicit ones alone.

    The hide toggles are runtime view preferences rather than part of any saved
    query, so the surfaces that own no toggle UI of their own — the timeline, the
    folder browser, a smart album's cover — never receive them and would
    otherwise answer over the whole library while the gallery beside them answers
    over the leads only. ``None`` means absent: a caller that genuinely wants
    everything sends ``'0'`` and keeps it.
    """
    resolved = dict(params)
    defaults = VIEWER_CONFIG.get('defaults', {})
    for key in HIDE_TOGGLE_KEYS:
        if resolved.get(key) is None:
            resolved[key] = '1' if defaults.get(key, False) else '0'
    return resolved


def hide_toggle_params(
    hide_blinks: Optional[str] = Query(None),
    hide_bursts: Optional[str] = Query(None),
    hide_duplicates: Optional[str] = Query(None),
    hide_brackets: Optional[str] = Query(None),
    hide_panoramas: Optional[str] = Query(None),
) -> dict:
    """FastAPI dependency declaring the five hide-toggle query params once.

    Every endpoint that owns no toggle UI of its own (the timeline, the folder
    browser, the type-counts sidebar) needs the same five params resolved the
    same way; a ``Depends(hide_toggle_params)`` keeps their declaration and
    ``resolve_hide_defaults`` call from drifting apart across call sites.
    """
    return resolve_hide_defaults({
        'hide_blinks': hide_blinks, 'hide_bursts': hide_bursts,
        'hide_duplicates': hide_duplicates, 'hide_brackets': hide_brackets,
        'hide_panoramas': hide_panoramas,
    })


def hide_clauses_from_toggles(hide_toggles: dict) -> list[str]:
    """Expand a ``hide_toggle_params()``-resolved dict into WHERE fragments."""
    return build_hide_clauses(
        hide_toggles['hide_blinks'], hide_toggles['hide_bursts'],
        hide_toggles['hide_duplicates'], hide_toggles['hide_brackets'],
        hide_toggles['hide_panoramas'],
    )


# Column lists shared by gallery and person viewer
PHOTO_BASE_COLS = [
    'path', 'filename', 'date_taken', 'camera_model', 'lens_model', 'iso',
    'f_stop', 'shutter_speed', 'focal_length', 'aesthetic', 'face_count', 'face_quality',
    'eye_sharpness', 'face_sharpness', 'face_ratio', 'tech_sharpness', 'color_score',
    'exposure_score', 'comp_score', 'isolation_bonus', 'is_blink', 'phash', 'is_burst_lead',
    'aggregate', 'category', 'image_width', 'image_height'
]
PHOTO_OPTIONAL_COLS = [
    'preview_revision',
    'histogram_spread', 'mean_luminance', 'power_point_score',
    'shadow_clipped', 'highlight_clipped', 'is_silhouette', 'is_group_portrait', 'leading_lines_score',
    'channel_clip_shadow_pct', 'channel_clip_highlight_pct',
    'face_confidence', 'is_monochrome', 'mean_saturation',
    'dynamic_range_stops', 'noise_sigma', 'contrast_score', 'tags',
    'composition_pattern', 'quality_score', 'topiq_score',
    'aesthetic_iaa', 'face_quality_iqa', 'liqe_score',
    'qrealign_score', 'aesthetic_v25', 'deqa_score',
    'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
    'star_rating', 'is_favorite', 'is_rejected', 'is_kept',
    'duplicate_group_id', 'is_duplicate_lead',
    'burst_group_id',
    'caption', 'caption_translated', 'gps_latitude', 'gps_longitude', 'gps_manually_set', 'date_manually_set',
    'dominant_hue', 'color_temp',
    'form_symmetry', 'form_balance', 'form_edge_entropy', 'form_fractal', 'color_harmony',
    'narrative_moment', 'narrative_moment_confidence',
    'junk_kind',
    'sequence_group_id', 'sequence_kind', 'sequence_ev_offset',
    # Fallback shape for a row whose fabricated pixel dimensions were cleared;
    # NULL whenever image_width/image_height are real. Optional so a library
    # that has not run the migration yet still serves the gallery.
    'image_aspect',
]

# A photo's manual sequence correction, flattened to one value: 'suppressed'
# when the override says "this is not a panorama" (sequence_kind NULL),
# otherwise the kind it was forced to.
#
# A correlated primary-key lookup rather than a LEFT JOIN because every caller
# of build_photo_select_columns brings its own FROM clause -- from a bare
# `photos` to a three-way join -- and adding the join to each by hand is how the
# feeds drift apart. It reads NOT from `photos`: the detector clears and
# rewrites those columns on every run, so a correction lives only here.
SEQUENCE_OVERRIDE_SELECT = (
    "(SELECT COALESCE(o.sequence_kind, 'suppressed') FROM photo_sequence_overrides o "
    "WHERE o.photo_path = photos.path) AS sequence_override"
)

# A photo's user-authored tags, GROUP_CONCAT'ed with TAG_SEPARATOR (\x1f, which
# normalize_manual_tag rejects, so a stored tag can never contain it). Same
# correlated-lookup rationale as SEQUENCE_OVERRIDE_SELECT. split_photo_tags turns
# the raw alias into the ``manual_tags`` list and removes it from the payload.
MANUAL_TAGS_RAW_COLUMN = 'manual_tags_raw'
MANUAL_TAGS_SELECT = (
    "(SELECT GROUP_CONCAT(tag, char(31)) FROM photo_manual_tags "
    f"WHERE photo_path = photos.path) AS {MANUAL_TAGS_RAW_COLUMN}"
)

# Whether that correction is still waiting on a detection run. Separate from the
# value above because the two answer different questions: the correction stays
# stored for as long as it applies, so its existence cannot mean "pending" --
# reading it that way left the tile badge, the culling chip and the re-run banner
# on screen for ever, silenced only by deleting the correction they described.
SEQUENCE_OVERRIDE_PENDING_SELECT = (
    "(SELECT o.applied_at IS NULL FROM photo_sequence_overrides o "
    "WHERE o.photo_path = photos.path) AS sequence_override_pending"
)


def get_existing_columns(conn=None):
    """Get list of columns that exist in the photos table. Cached after first call."""
    global _existing_columns_cache
    with _existing_columns_lock:
        if _existing_columns_cache is not None:
            return _existing_columns_cache

    if conn is None:
        conn = get_db_connection()
        try:
            cursor = conn.execute('PRAGMA table_info(photos)')
            result = {row[1] for row in cursor.fetchall()}
        finally:
            conn.close()
    else:
        cursor = conn.execute('PRAGMA table_info(photos)')
        result = {row[1] for row in cursor.fetchall()}

    from api import config as _config_mod
    with _existing_columns_lock:
        _existing_columns_cache = result
        _config_mod._existing_columns_cache = result
    return _existing_columns_cache


def invalidate_existing_columns_cache():
    """Clear the existing-columns cache.

    Call after ``init_database()`` if it added columns (e.g. lifespan
    startup, or if a deploy hot-runs schema migrations). Without this,
    queries continue to use the stale PHOTO_OPTIONAL_COLS subset and
    miss newly-added columns until the API restarts.
    """
    global _existing_columns_cache
    from api import config as _config_mod
    with _existing_columns_lock:
        _existing_columns_cache = None
        _config_mod._existing_columns_cache = None
    _manual_tags_present.clear()


def is_photo_tags_available(conn=None):
    """Check if the photo_tags lookup table exists and has data.

    Result is TTL-cached (5 min by default; see ``PHOTO_TAGS_CACHE_TTL``).
    Without a TTL the cache stayed permanently False on a fresh DB even
    after the operator ran ``database.py --migrate-tags`` while the API
    was up — the lookup table would be populated but the API would
    continue using the slow LIKE fallback until restart.

    Cache-warm path (within TTL) returns instantly without touching
    ``conn`` — safe to call from an async context with an aiosqlite
    Connection as long as the lifespan startup or a prior call warmed it.
    """
    global _photo_tags_available
    from api import config as _config_mod
    import time
    now = time.monotonic()
    with _photo_tags_lock:
        if (_photo_tags_available is not None
                and (now - _config_mod._photo_tags_checked_at) < PHOTO_TAGS_CACHE_TTL):
            return _photo_tags_available

    # Cold path / TTL expired: only fire if a sync sqlite3.Connection was
    # provided, or open a fresh one. Passing an aiosqlite Connection here
    # would be a programmer error — refuse rather than emit a
    # coroutine-never-awaited warning.
    if conn is not None and not isinstance(conn, sqlite3.Connection):
        # Fall through to open our own sync connection.
        conn = None

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        # Existence of one row, not a count: the answer is the same and a COUNT
        # walks the whole table (millions of rows on a large library).
        result = conn.execute("SELECT 1 FROM photo_tags LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError:
        logger.debug("photo_tags table not available", exc_info=True)
        result = False

    if close_conn:
        conn.close()

    with _photo_tags_lock:
        _photo_tags_available = result
        _config_mod._photo_tags_available = result
        _config_mod._photo_tags_checked_at = now
    return _photo_tags_available


# Keyed by database file: (found, checked_at). A True never expires -- once
# photo_manual_tags exists it does not go away -- while a False is re-checked
# after PHOTO_TAGS_CACHE_TTL, because a CLI upgrade can create the table while the
# server is up (a lifespan init_database clears this through
# invalidate_existing_columns_cache). Caching the False too keeps a library
# without the table from opening a connection on every request. Table existence
# is the whole check -- no row count -- so a manual-only library and a first-ever
# write are both seen at once.
_manual_tags_present: dict[str, tuple[bool, float]] = {}


def _manual_tags_cached(key: str, now: float, max_age: float):
    """The cached answer for ``key`` when it is still fresh at ``now``, else None."""
    entry = _manual_tags_present.get(key)
    if entry is None:
        return None
    found, checked_at = entry
    if found or now - checked_at < max_age:
        return found
    return None


def is_manual_tags_available(conn=None):
    """True when the ``photo_manual_tags`` table exists (existence only, no row count).

    Readers that touch the table check this first, because a lifespan
    ``init_database`` failure only logs: a server can run against an older
    schema. Safe to call with ``conn=None`` or an aiosqlite connection: any
    connection that is not a synchronous ``sqlite3.Connection`` is replaced by a
    short-lived one of our own on a cache miss.
    """
    key = str(DEFAULT_DB_PATH)
    now = time.monotonic()
    cached = _manual_tags_cached(key, now, PHOTO_TAGS_CACHE_TTL)
    if cached is not None:
        return cached
    close_conn = False
    if not isinstance(conn, sqlite3.Connection):
        conn = get_db_connection()
        close_conn = True
    try:
        found = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'photo_manual_tags'"
        ).fetchone() is not None
    except sqlite3.OperationalError:
        logger.debug("photo_manual_tags availability check failed", exc_info=True)
        found = False
    finally:
        if close_conn:
            conn.close()
    _manual_tags_present[key] = (found, now)
    return found


def _manual_tag_match_key(tag):
    """A viewer-supplied tag in the form manual tags are stored in (lenient).

    A value that cannot be a stored tag (comma, control character, too long)
    simply matches no manual row, so it is returned unchanged rather than
    raised on: the AI-tag half of the filter still runs on the raw value.
    """
    try:
        return normalize_manual_tag(tag)
    except ManualTagError:
        return tag


_art_tags_cache = None


def _add_tag_filter(where_clauses, sql_params, tag=None, require_tags=None, exclude_tags=None, exclude_art_tags=None, conn=None, include_manual=True):
    """Build tag-related WHERE clauses using photo_tags table when available.

    Manual (user-authored) tags are UNIONed in for ``tag`` / ``require_tags``
    (exact match, in both the photo_tags and the ``tags LIKE`` branch) and
    subtracted for ``exclude_tags`` (``AND NOT EXISTS``, never OR: an OR would
    let a photo carrying the excluded tag only as a manual tag survive).
    ``exclude_art_tags`` stays AI-only: it excludes on the classifier's art
    vocabulary. ``include_manual=False`` makes every clause AI-only, which is
    what a share-link request must use so a private annotation cannot be
    probed through the tag filter.
    """
    use_photo_tags = is_photo_tags_available(conn)
    use_manual = include_manual and is_manual_tags_available(conn)
    manual_exists = "EXISTS (SELECT 1 FROM photo_manual_tags m WHERE m.photo_path = photos.path AND m.tag {cond})"

    if tag:
        manual_clause = manual_exists.format(cond="= ?")
        if use_photo_tags:
            ai_clause = "EXISTS (SELECT 1 FROM photo_tags WHERE photo_path = photos.path AND tag = ?)"
            ai_params = [tag]
        else:
            ai_clause = "tags LIKE ?"
            ai_params = [f"%{tag}%"]
        if use_manual:
            where_clauses.append(f"({ai_clause} OR {manual_clause})")
            sql_params.extend([*ai_params, _manual_tag_match_key(tag)])
        else:
            where_clauses.append(ai_clause)
            sql_params.extend(ai_params)

    if require_tags:
        tag_list = [t.strip() for t in require_tags.split(',')]
        if use_photo_tags:
            placeholders = ','.join(['?' for _ in tag_list])
            ai_clause = f"EXISTS (SELECT 1 FROM photo_tags WHERE photo_path = photos.path AND tag IN ({placeholders}))"
            ai_params = list(tag_list)
        else:
            tag_conditions = ' OR '.join(['tags LIKE ?' for _ in tag_list])
            ai_clause = f"({tag_conditions})"
            ai_params = [f"%{tag}%" for tag in tag_list]
        if use_manual:
            placeholders = ','.join(['?' for _ in tag_list])
            where_clauses.append(f"({ai_clause} OR {manual_exists.format(cond=f'IN ({placeholders})')})")
            sql_params.extend([*ai_params, *(_manual_tag_match_key(t) for t in tag_list)])
        else:
            where_clauses.append(ai_clause)
            sql_params.extend(ai_params)

    if exclude_tags:
        tag_list = [t.strip() for t in exclude_tags.split(',')]
        for tag_name in tag_list:
            if use_photo_tags:
                where_clauses.append("NOT EXISTS (SELECT 1 FROM photo_tags WHERE photo_path = photos.path AND tag = ?)")
                sql_params.append(tag_name)
            else:
                where_clauses.append("(tags IS NULL OR tags NOT LIKE ?)")
                sql_params.append(f"%{tag_name}%")
            if use_manual:
                where_clauses.append("NOT " + manual_exists.format(cond="= ?"))
                sql_params.append(_manual_tag_match_key(tag_name))

    if exclude_art_tags:
        if use_photo_tags:
            placeholders = ','.join(['?' for _ in exclude_art_tags])
            where_clauses.append(f"NOT EXISTS (SELECT 1 FROM photo_tags WHERE photo_path = photos.path AND tag IN ({placeholders}))")
            sql_params.extend(exclude_art_tags)
        else:
            art_exclusions = ' AND '.join(['(tags IS NULL OR tags NOT LIKE ?)' for _ in exclude_art_tags])
            where_clauses.append(f"({art_exclusions})")
            sql_params.extend([f"%{tag}%" for tag in exclude_art_tags])


def get_art_tags_from_config():
    """Get list of art tags from scoring config (cached)."""
    global _art_tags_cache
    if _art_tags_cache is not None:
        return _art_tags_cache

    config = server_scoring_config()
    art_config = config.get_category_config('art')
    if art_config:
        filters = art_config.get('filters', {})
        required_tags = filters.get('required_tags', [])
        if required_tags:
            _art_tags_cache = list(required_tags)
            return _art_tags_cache
        tags = art_config.get('tags', {})
        if isinstance(tags, dict):
            _art_tags_cache = list(tags.keys())
            return _art_tags_cache

    _art_tags_cache = ['painting', 'statue', 'mural', 'drawing', 'cartoon', 'anime']
    return _art_tags_cache


def _count_cache_lookup(cache_key):
    """Return cached count if fresh, else None."""
    now = time.time()
    with _count_cache_lock:
        if cache_key in _count_cache:
            count, ts = _count_cache[cache_key]
            if now - ts < COUNT_CACHE_TTL:
                return count
    return None


def _count_cache_store(cache_key, count):
    now = time.time()
    with _count_cache_lock:
        _count_cache[cache_key] = (count, now)
        if len(_count_cache) > 100:
            expired = [k for k, (_, ts) in _count_cache.items() if now - ts > COUNT_CACHE_TTL * 2]
            for k in expired:
                del _count_cache[k]


def _count_cache_key(prefix, from_clause, where_str, sql_params, token=None):
    """Cache key for a count-style query: the query, the database it runs on and
    that database's change token (``api.change_token``). A caller reading inside
    an explicit transaction passes the ``token`` it took BEFORE the transaction
    began (:func:`snapshot_count_token`): a token read later could be newer than
    the snapshot, and the stale count would be stored under the current key.

    The path is read from ``api.database`` AT CALL TIME because that module's
    ``DEFAULT_DB_PATH`` is the global every request connection opens (and the one
    tests patch); this module's own import-time binding would key one database's
    counts under another's.
    """
    db_path = _database.DEFAULT_DB_PATH
    if token is None:
        token = db_change_token(db_path)
    digest = hashlib.sha256(
        f"{db_path}:{from_clause}:{where_str}:{tuple(sql_params)}:{token}".encode()
    ).hexdigest()
    return prefix + digest


def get_cached_count(conn, where_str, sql_params, from_clause="photos"):
    """Cache COUNT results to avoid repeated full-table scans."""
    cache_key = _count_cache_key("", from_clause, where_str, sql_params)
    cached = _count_cache_lookup(cache_key)
    if cached is not None:
        return cached

    row = conn.execute(f"SELECT COUNT(*) FROM {from_clause}{where_str}", sql_params).fetchone()
    count = row[0] if row else 0
    _count_cache_store(cache_key, count)
    return count


async def snapshot_count_token():
    """Change token to key a transaction's counts with; take it before ``BEGIN``."""
    return await asyncio.to_thread(db_change_token, _database.DEFAULT_DB_PATH)


async def get_cached_count_async(conn, where_str, sql_params, from_clause="photos", *, token=None):
    """Async variant of get_cached_count for aiosqlite paths."""
    cache_key = await asyncio.to_thread(_count_cache_key, "", from_clause, where_str, sql_params, token)
    cached = _count_cache_lookup(cache_key)
    if cached is not None:
        return cached

    cursor = await conn.execute(f"SELECT COUNT(*) FROM {from_clause}{where_str}", sql_params)
    row = await cursor.fetchone()
    await cursor.close()
    count = row[0] if row else 0
    _count_cache_store(cache_key, count)
    return count


async def get_cached_hidden_aggregates_async(conn, where_str, sql_params, from_clause="photos", *,
                                             stack_owner=None, token=None):
    """Cached blink/burst/duplicate/bracket aggregates over the no-hide set.

    The gallery builds its hidden_summary from a full-table aggregate (~100ms on a
    large library). It is identical across every page of a filter set, so cache it
    with the same TTL/keying as the count cache instead of re-running it on every
    infinite-scroll fetch.
    """
    # Manual members are restored by the gallery's automatic-hide exception.
    # Use the same membership predicate, in this snapshot and owner scope, so the
    # category counts describe automatic followers that can actually be hidden.
    auto_exclusion = ''
    aggregate_params = list(sql_params)
    if stack_owner is not None:
        from api.stack_gallery import membership_clause
        auto_exclusion = f' AND NOT ({membership_clause()})'
        aggregate_params = [stack_owner, stack_owner, *sql_params]
    cache_key = await asyncio.to_thread(
        _count_cache_key, "hs:", from_clause, where_str + auto_exclusion, aggregate_params, token)
    cached = _count_cache_lookup(cache_key)
    if cached is not None:
        return cached
    cursor = await conn.execute(
        "SELECT COUNT(*) AS unhidden, "
        "SUM(CASE WHEN is_blink = 1 THEN 1 ELSE 0 END) AS blinks, "
        f"SUM(CASE WHEN {HIDDEN_BURST_SQL}{auto_exclusion} THEN 1 ELSE 0 END) AS bursts, "
        f"SUM(CASE WHEN {HIDDEN_DUPLICATE_SQL}{auto_exclusion} THEN 1 ELSE 0 END) AS duplicates, "
        f"SUM(CASE WHEN {HIDDEN_BRACKET_SQL} THEN 1 ELSE 0 END) AS brackets, "
        f"SUM(CASE WHEN {HIDDEN_PANORAMA_SQL} THEN 1 ELSE 0 END) AS panoramas "
        f"FROM {from_clause}{where_str}",
        aggregate_params,
    )
    row = await cursor.fetchone()
    await cursor.close()
    agg = {
        'unhidden': row['unhidden'] if row else 0,
        'blinks': int(row['blinks'] or 0) if row else 0,
        'bursts': int(row['bursts'] or 0) if row else 0,
        'duplicates': int(row['duplicates'] or 0) if row else 0,
        'brackets': int(row['brackets'] or 0) if row else 0,
        'panoramas': int(row['panoramas'] or 0) if row else 0,
    }
    _count_cache_store(cache_key, agg)
    return agg


def paginate(total: int, page: int, per_page: int) -> tuple[int, int]:
    """Calculate pagination values.

    Returns (total_pages, offset).
    """
    total_pages = max(1, math.ceil(total / per_page))
    offset = (page - 1) * per_page
    return total_pages, offset


def select_in_chunks(conn, sql_format, keys, before=(), after=(), chunk=900):
    """Yield rows for a ``... IN (<keys>) ...`` query, chunked under SQLite's
    variable limit.

    ``sql_format`` is a format string carrying a single ``{placeholders}`` field,
    filled with the ``?`` list for each chunk of ``keys``. Per-chunk bind
    parameters are ``before`` (binds appearing before the IN list, e.g. a JOIN
    ``ON up.user_id = ?``) + the chunk keys + ``after`` (binds after the IN list,
    e.g. a visibility clause). Consolidates the copy-pasted 900-key IN loop.
    """
    keys = list(keys)
    before = list(before)
    after = list(after)
    for start in range(0, len(keys), chunk):
        piece = keys[start:start + chunk]
        placeholders = ','.join('?' * len(piece))
        yield from conn.execute(
            sql_format.format(placeholders=placeholders),
            before + piece + after,
        )


def sanitize_float_values(data):
    """Replace NaN/Infinity with None in a list of dicts."""
    for item in data:
        for key, value in item.items():
            if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
                item[key] = None
    return data


def build_photo_select_columns(conn, user_id=None, include_manual_tags=True):
    """Build the SELECT column list for photo queries.

    ``include_manual_tags=False`` leaves the manual-tags subquery out entirely
    (share-link routes): ``split_photo_tags`` then reports ``manual_tags == []``.

    Resolves existing columns, applies user-preference overrides for
    star_rating / is_favorite / is_rejected / is_kept, and returns a list of SQL
    column expressions ready to join into a SELECT clause.
    """
    existing_cols = get_existing_columns(conn)
    pref_cols = get_preference_columns(user_id)
    pref_col_names = {'star_rating', 'is_favorite', 'is_rejected', 'is_kept'}

    # Skip caption_translated when translation is disabled (target_language empty or "en")
    target_lang = _FULL_CONFIG.get('translation', {}).get('target_language', '')
    skip_cols = set()
    if not target_lang or target_lang == 'en':
        skip_cols.add('caption_translated')

    select_cols = list(PHOTO_BASE_COLS)
    for c in PHOTO_OPTIONAL_COLS:
        if c in existing_cols and c not in skip_cols:
            if c in pref_col_names:
                select_cols.append(f"{pref_cols[c]} as {c}")
            else:
                select_cols.append(c)
    select_cols.append(SEQUENCE_OVERRIDE_SELECT)
    select_cols.append(SEQUENCE_OVERRIDE_PENDING_SELECT)
    if include_manual_tags and is_manual_tags_available(conn):
        select_cols.append(MANUAL_TAGS_SELECT)
    return select_cols


def update_person_face_count(conn, person_id):
    """Update a person's face_count from the faces table."""
    conn.execute("""
        UPDATE persons SET face_count = (
            SELECT COUNT(*) FROM faces WHERE person_id = ?
        ) WHERE id = ?
    """, (person_id, person_id))


def repair_stale_representative(conn, person_id):
    """Give a person a representative face when it has none or no longer owns it.

    Moving a face away from its person leaves that person's representative_face_id
    and face_thumbnail pointing at a face now owned by someone else, and a person
    created by a split or by name never had one. Pick the highest-confidence face
    the person owns, or clear both columns when it has no faces left. A
    representative the person still owns is kept.
    """
    person = conn.execute(
        "SELECT representative_face_id FROM persons WHERE id = ?", (person_id,)
    ).fetchone()
    if not person:
        return
    rep_id = person['representative_face_id']
    if rep_id is not None and conn.execute(
        "SELECT 1 FROM faces WHERE id = ? AND person_id = ?", (rep_id, person_id)
    ).fetchone():
        return
    replacement = conn.execute(
        "SELECT id, face_thumbnail FROM faces WHERE person_id = ? ORDER BY confidence DESC LIMIT 1",
        (person_id,)
    ).fetchone()
    if replacement:
        conn.execute(
            "UPDATE persons SET representative_face_id = ?, face_thumbnail = ? WHERE id = ?",
            (replacement['id'], replacement['face_thumbnail'], person_id)
        )
    else:
        conn.execute(
            "UPDATE persons SET representative_face_id = NULL, face_thumbnail = NULL WHERE id = ?",
            (person_id,)
        )


def person_unnamed_clause(alias: str) -> str:
    """SQL predicate selecting persons without a name: NULL or only spaces.

    The one definition of "unnamed" on the server; ``is_unnamed`` is its Python mirror.
    """
    return f"({alias}.name IS NULL OR TRIM({alias}.name) = '')"


def is_unnamed(name: Optional[str]) -> bool:
    """Python mirror of ``person_unnamed_clause``.

    SQLite ``TRIM`` strips only spaces while ``str.strip()`` strips every whitespace
    character, so this strips spaces alone to agree with the SQL exactly.
    """
    return not (name or '').strip(' ')


def reassign_faces_to_person(conn, person_id, face_ids):
    """Reassign a set of faces to ``person_id``; auto-delete emptied old persons.

    Validates that every face_id exists, moves them to the new person, refreshes
    face_count on both old and new persons, and deletes any old person whose
    face_count drops to zero.

    Returns a dict with: ``assigned_count``, ``face_count`` (final count on
    ``person_id``), and ``deleted_persons`` (list of auto-deleted old IDs).
    Raises ``LookupError`` if any face_id is unknown.
    """
    if not face_ids:
        return {"assigned_count": 0, "face_count": 0, "deleted_persons": []}

    # Dedup face_ids so the existence check below isn't tripped up by duplicates
    # collapsing in SQL's IN-set semantics (SELECT IN (5,5,6) returns one row for 5,
    # producing a false-negative len-mismatch even though both IDs exist).
    face_ids = list(dict.fromkeys(face_ids))

    placeholders = ",".join("?" * len(face_ids))
    existing = conn.execute(
        f"SELECT id, person_id FROM faces WHERE id IN ({placeholders})",
        face_ids,
    ).fetchall()
    if len(existing) != len(face_ids):
        raise LookupError("One or more face_ids not found")

    old_person_ids = {
        row["person_id"] for row in existing
        if row["person_id"] is not None and row["person_id"] != person_id
    }

    conn.execute(
        f"UPDATE faces SET person_id = ? WHERE id IN ({placeholders})",
        [person_id] + list(face_ids),
    )

    update_person_face_count(conn, person_id)
    deleted_persons = []
    for old_id in old_person_ids:
        update_person_face_count(conn, old_id)
        row = conn.execute(
            "SELECT face_count FROM persons WHERE id = ?", (old_id,)
        ).fetchone()
        if row and row[0] == 0:
            conn.execute("DELETE FROM persons WHERE id = ?", (old_id,))
            deleted_persons.append(old_id)
        else:
            repair_stale_representative(conn, old_id)
            recompute_person_centroid(conn, old_id)

    # Give the (possibly freshly-created) target a real centroid so incremental
    # re-clustering preserves it instead of orphaning its faces, and a picture:
    # a person created by a split or by name has none, and its card stays blank.
    recompute_person_centroid(conn, person_id)
    repair_stale_representative(conn, person_id)

    row = conn.execute(
        "SELECT face_count FROM persons WHERE id = ?", (person_id,)
    ).fetchone()
    return {
        "assigned_count": len(face_ids),
        "face_count": row[0] if row else 0,
        "deleted_persons": deleted_persons,
    }


def split_photo_tags(rows, tags_limit, include_manual_tags=True):
    """Convert DB rows to dicts with pre-split ``tags_list`` and ``manual_tags``.

    ``tags_list`` is the AI tags truncated to ``tags_limit``. ``manual_tags`` is
    the photo's user-authored tags, sorted and NEVER truncated, and is always
    set (``[]`` when there are none, the table is absent, or
    ``include_manual_tags`` is False): ``response_model_exclude_unset`` would
    otherwise drop the field from the wire. The raw GROUP_CONCAT alias is
    removed even when it is ignored, so it can never leak into a payload.
    """
    photos = []
    for row in rows:
        photo = dict(row)
        raw_manual = photo.pop(MANUAL_TAGS_RAW_COLUMN, None)
        photo['manual_tags'] = (
            sorted(raw_manual.split(TAG_SEPARATOR)) if include_manual_tags and raw_manual else []
        )
        if photo.get('tags'):
            photo['tags_list'] = [t.strip() for t in photo['tags'].split(',')[:tags_limit]]
        else:
            photo['tags_list'] = []
        photos.append(photo)
    return photos


_PERSONS_FOR_PATHS_TMPL = """
    SELECT DISTINCT f.photo_path, f.person_id, p.name
    FROM faces f
    JOIN persons p ON p.id = f.person_id
    WHERE f.photo_path IN ({placeholders})
      AND f.person_id IS NOT NULL
"""

_UNASSIGNED_FOR_PATHS_TMPL = """
    SELECT photo_path, COUNT(*) as unassigned_count
    FROM faces
    WHERE photo_path IN ({placeholders})
      AND person_id IS NULL
    GROUP BY photo_path
"""


def _apply_person_data(photos, person_rows, unassigned_rows):
    """Mutate ``photos`` in place from the two query result sets.

    Extracted from ``attach_person_data_async`` so the post-query mapping
    logic is pure (no DB access) and unit-testable.
    """
    path_to_persons: dict[str, list[dict]] = {}
    for row in person_rows:
        path = row['photo_path']
        path_to_persons.setdefault(path, []).append({
            'id': row['person_id'],
            'name': row['name'] or f"Person {row['person_id']}",
        })
    path_to_unassigned = {row['photo_path']: row['unassigned_count'] for row in unassigned_rows}
    for photo in photos:
        photo['persons'] = path_to_persons.get(photo['path'], [])
        photo['unassigned_faces'] = path_to_unassigned.get(photo['path'], 0)


async def attach_person_data_async(photos, conn):
    """Async variant: same shape, awaits aiosqlite cursors."""
    if not photos:
        return
    try:
        photo_paths = [p['path'] for p in photos]
        placeholders = ','.join(['?'] * len(photo_paths))
        cursor = await conn.execute(
            _PERSONS_FOR_PATHS_TMPL.format(placeholders=placeholders),
            photo_paths,
        )
        person_rows = await cursor.fetchall()
        await cursor.close()
        cursor = await conn.execute(
            _UNASSIGNED_FOR_PATHS_TMPL.format(placeholders=placeholders),
            photo_paths,
        )
        unassigned_rows = await cursor.fetchall()
        await cursor.close()
        _apply_person_data(photos, person_rows, unassigned_rows)
    except Exception:
        logger.exception("Failed to attach person data (async)")
        for photo in photos:
            photo['persons'] = []
            photo['unassigned_faces'] = 0


# --- MULTI-USER VISIBILITY & PREFERENCES ---

def is_access_controlled_install():
    """True when the deployment gates who may see photos — multi-user mode, or a
    single-user viewer password.

    A fully open single-user install (no multi-user, no viewer password) is
    world-readable, so ownership must never deny access there. Shared by
    ``get_visibility_clause`` and the album-access check so both honour the same
    install-mode carve-out.

    Mirrors ``api.auth._is_open_install``: an unparseable ``scoring_config.json``
    yields an empty config carrying no password, which reads exactly like a
    deliberately open install and would hand the whole library to anonymous
    callers. Such an install is treated as access-controlled (fail closed) until
    the config parses again.
    """
    return (config_load_failed()
            or is_multi_user_enabled()
            or bool(VIEWER_CONFIG.get('password', '')))


# The visibility fragment that matches nothing. Named so a caller can test for
# it instead of repeating the literal, and so the two places that produce it
# (an unidentified caller on an access-controlled install; a user scoped to no
# directory) can never drift apart from the places that check for it.
NO_VISIBILITY_SQL = '0=1'


class PathScope:
    """A set of directories and files a headless run is confined to.

    Matching is plain string comparison on the stored (resolved) path, not
    ``LIKE``: ``LIKE`` is ASCII case-insensitive and treats ``%``, ``_`` and
    ``\\`` as wildcards, so ``substr()`` equality is what keeps the SQL filter
    and ``matches`` in exact agreement. Every directory prefix ends in a
    separator, so ``/shoot`` never matches ``/shoot2``.
    """

    def __init__(self, prefixes, files):
        self.prefixes = tuple(prefixes)
        self.files = tuple(files)

    @property
    def roots(self):
        """Every entry as a directory or file path, without the trailing separator."""
        return [p.rstrip(os.sep) or os.sep for p in self.prefixes] + list(self.files)

    def matches(self, path):
        return path in self.files or any(path.startswith(p) for p in self.prefixes)

    def sql(self, column='photos.path'):
        clauses = []
        params = []
        for prefix in self.prefixes:
            clauses.append(f"substr({column}, 1, ?) = ?")
            params += [len(prefix), prefix]
        for file_path in self.files:
            clauses.append(f"{column} = ?")
            params.append(file_path)
        return f"({' OR '.join(clauses)})", params


def _is_windows_shaped(directory):
    """True for ``D:``, ``D:\\x``, ``\\\\host\\share`` and ``\\\\?\\D:\\x``."""
    return ntpath.splitdrive(directory)[0] != ''


# ``stored_path_form`` caches because an offline UNC costs about 130 ms per
# resolve. What it may cache depends on whether the answer can still change: a
# translation whose target EXISTS is the one the scanner stores, so it is kept
# for the life of the process; one whose target does not exist may have been made
# while a mapped drive or share was unreachable (a NAS asleep at viewer start),
# so it is kept for ``_STORED_FORM_RETRY_SECONDS`` only and then resolved again.
# Pinning it forever left that user with an empty library until a restart,
# silently, because a visibility prefix that matches no stored path fails closed.
_STORED_FORM_RETRY_SECONDS = 60.0
_STORED_FORM_CACHE_MAX = 256
_monotonic = time.monotonic              # a name of its own so tests can move the clock
_stored_form_lock = threading.Lock()
_warned_blank_entries: set[tuple[str, str]] = set()  # (user, entry) already warned about
_stored_form_settled: dict[str, str] = {}    # directory -> form whose target exists
_stored_form_provisional: dict[str, tuple[str, float]] = {}  # directory -> (form, monotonic expiry)


def _remember(cache, key, value):
    """Insert into a bounded dict, dropping the oldest entry first. Hold the lock."""
    if key not in cache and len(cache) >= _STORED_FORM_CACHE_MAX:
        cache.pop(next(iter(cache)))
    cache[key] = value


def clear_stored_path_form_cache():
    with _stored_form_lock:
        _stored_form_settled.clear()
        _stored_form_provisional.clear()


def stored_path_form(directory):
    """What the scanner would store for this directory: ``str(Path(p).resolve())``.

    The scanner writes that inline at several sites, so there is no single
    normaliser to import; this is the minimal shared one. A POSIX-shaped path is
    returned untouched (resolving it would add a filesystem round trip and
    change behaviour for symlinked configured paths).

    Cached, with the asymmetry described above ``_STORED_FORM_RETRY_SECONDS``:
    a result whose path exists is cached for good, any other result for a
    minute, so a drive that comes back is picked up without a restart while an
    offline UNC does not cost its ~130 ms on every request.
    """
    if not _is_windows_shaped(directory):
        return directory
    with _stored_form_lock:
        form = _stored_form_settled.get(directory)
        if form is not None:
            return form
        cached = _stored_form_provisional.get(directory)
        if cached is not None and _monotonic() < cached[1]:
            return cached[0]
    # Resolved outside the lock: an offline UNC takes ~130 ms and must not
    # serialise every other request behind it. Two threads racing here both
    # compute the same answer, and the last write wins harmlessly.
    form = _resolve_stored_path_form(directory)
    exists = os.path.exists(form)
    with _stored_form_lock:
        if exists:
            _remember(_stored_form_settled, directory, form)
            _stored_form_provisional.pop(directory, None)
        else:
            _remember(_stored_form_provisional, directory,
                      (form, _monotonic() + _STORED_FORM_RETRY_SECONDS))
    return form


def _resolve_stored_path_form(directory):
    """The uncached half of :func:`stored_path_form` for a Windows-shaped path."""
    text = directory
    if text.startswith('\\\\?\\UNC\\'):
        text = '\\\\' + text[8:]
    elif text.startswith('\\\\?\\'):
        text = text[4:]                       # resolve() does not strip the \\?\ prefix
    drive, rest = ntpath.splitdrive(text)
    if not rest:
        text = drive + '\\'                   # bare `D:` resolves to the drive's CWD, not its root
    if sys.platform == 'win32':
        try:
            return str(Path(text).resolve())  # the scanner's own call: separators, case, mapped drive -> UNC
        except OSError:
            pass
    return ntpath.normpath(text)              # a POSIX host holding a DB scanned on Windows: lexical only


# Rows were written by the filesystem of the machine that scanned them, so the
# viewer's host decides how a POSIX-shaped directory must be compared. APFS is
# case-insensitive by default; NTFS always is. Windows-shaped directories are
# compared case-insensitively on every host (see ``get_visibility_clause``).
_CASE_INSENSITIVE_HOST = sys.platform in ('win32', 'darwin')


def build_path_scope(paths):
    """Resolve ``paths`` into a :class:`PathScope`, or ``None`` for "everything".

    Each entry is normalised to the stored form because the scanner stores
    ``Path(p).resolve()``. A missing entry raises ``ValueError`` rather than
    silently scoping to nothing.
    """
    if not paths:
        return None
    prefixes = []
    files = []
    for entry in paths:
        real = stored_path_form(os.path.realpath(entry))
        if os.path.isdir(real):
            prefixes.append(real.rstrip(os.sep) + os.sep)
        elif os.path.isfile(real):
            files.append(real)
        else:
            raise ValueError(f"Path does not exist: {entry}")
    return PathScope(prefixes, files)


def scope_sql(scope, column='photos.path'):
    """``(fragment, params)`` confining ``column`` to ``scope``; a no-op for ``None``."""
    if scope is None:
        return '1=1', []
    return scope.sql(column)


def scope_cache_key(prefix, *parts):
    """Fixed-width ``stats_cache`` key for a request scope.

    The scoped aggregates cache per (album, date window, user); folding those
    values into the key verbatim let an anonymous caller on a large-enough
    install write an unbounded number of unbounded-length rows, one per URL it
    invented. Hashing bounds both: any scope becomes ``prefix_<64 hex>``.

    ``prefix`` stays in the clear because the invalidation paths delete by it
    (``DELETE FROM stats_cache WHERE key LIKE 'scenes_%'``). Parts are joined on
    the unit separator, which cannot occur in an album id, an EXIF timestamp or
    a user id, and ``None`` is encoded distinctly from ``''`` so an absent bound
    and an empty one never collide.
    """
    raw = '\x1f'.join('\x00' if part is None else str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def get_visibility_clause(user_id, table_alias='photos'):
    """Returns (sql_fragment, params) for photo visibility in multi-user mode.

    Returns ``NO_VISIBILITY_SQL`` when the caller may see nothing at all, which
    a caller can compare against to skip work it would otherwise do for an empty
    result set — see ``_shoot_type_evidence``.

    Args:
        user_id: The current user ID (or None).
        table_alias: Table name or alias to qualify the path column (default: 'photos').
    """
    if not user_id:
        # No identified user. On a protected deployment — multi-user, or a
        # single-user viewer password — an unauthenticated request must see
        # nothing; only a fully open single-user install is world-readable.
        if is_access_controlled_install():
            return NO_VISIBILITY_SQL, []
        return '1=1', []

    if not is_multi_user_enabled():
        return '1=1', []

    all_dirs = get_user_directories(user_id)
    if not all_dirs:
        return NO_VISIBILITY_SQL, []

    conditions = []
    params = []
    for d in all_dirs:
        if not isinstance(d, str) or not d.strip():
            # A blank entry would normalise to the prefix '/', which as a range
            # is every path in the library. Granting nothing is the only safe
            # reading of "no directory". Said once per user and entry: this runs
            # on every request.
            if (user_id, repr(d)) not in _warned_blank_entries:
                _warned_blank_entries.add((user_id, repr(d)))
                logger.warning(
                    "Ignoring a blank directory entry (%r) for user %r: a blank "
                    "entry grants nothing, never the whole library. Remove it from "
                    "this user's directories.", d, user_id)
            continue
        # Match the form the scanner stored (str(Path.resolve())): backslash
        # separators for a Windows-shaped directory, forward slashes otherwise.
        # Measured on a 130k-row library: one native-form LIKE per directory,
        # not two forms and not REPLACE(path, '\', '/') (3x slower).
        form = stored_path_form(d)
        windows = _is_windows_shaped(form)
        prefix = form.rstrip('/\\') + ('\\' if windows else '/')
        if _CASE_INSENSITIVE_HOST or windows:
            # NTFS (and APFS) wrote these rows case-insensitively, and LIKE
            # folds ASCII case. Escape LIKE wildcards so a directory containing
            # % or _ can only match itself: an unescaped `_` matches any single
            # character, so a user scoped to `.../a_b/` would also see
            # `.../axb/` belonging to another user. Backslashes are escaped too
            # (they stay literal path separators, not LIKE escapes) now that we
            # declare ESCAPE. Mirrors folders.py.
            escaped = prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            conditions.append(f"{table_alias}.path LIKE ? ESCAPE '\\'")
            params.append(escaped + '%')
        else:
            # A case-sensitive host: LIKE would fold ASCII case, so a user
            # scoped to /mnt/photos also saw /mnt/Photos (another user's
            # photos). A BINARY half-open range [prefix, prefix with its last
            # character bumped) is exact, needs no escaping, and is a SEARCH on
            # the path primary key, which LIKE can never use.
            conditions.append(f"{table_alias}.path >= ? AND {table_alias}.path < ?")
            params += [prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1)]

    if not conditions:
        return NO_VISIBILITY_SQL, []
    return f"({' OR '.join(conditions)})", params


def person_visibility_exists(user_id, person_col):
    """Returns (sql_fragment, params) restricting a person to those with at least
    one face in a photo the user may see.

    Empty (a no-op) outside multi-user mode, where an authenticated user already
    sees the whole library; in multi-user mode it enforces per-directory
    isolation on the persons/faces surface. ``person_col`` is a caller-supplied
    column reference (e.g. ``'p.id'``), never user input.
    """
    if not is_multi_user_enabled():
        return '', []
    vis_sql, vis_params = get_visibility_clause(user_id, table_alias='pv')
    fragment = (
        f"EXISTS (SELECT 1 FROM faces fv JOIN photos pv ON pv.path = fv.photo_path "
        f"WHERE fv.person_id = {person_col} AND {vis_sql})"
    )
    return fragment, vis_params


def assert_faces_visible(conn, user_id, face_ids):
    """Raise ``LookupError`` if any ``face_id`` sits on a photo the caller may not see.

    A no-op outside multi-user mode, where an authenticated viewer sees the whole
    library. In multi-user mode it enforces the same per-directory isolation as the
    person/face read surface, so an edition user scoped to a subset of directories
    cannot pull foreign faces into a person. Raises ``LookupError`` (mapped to 404
    by callers) rather than 403 so it never leaks the existence of out-of-scope
    faces, matching the unknown-face response.
    """
    if not face_ids or not is_multi_user_enabled():
        return
    face_ids = list(dict.fromkeys(face_ids))
    vis_sql, vis_params = get_visibility_clause(user_id, table_alias='p')
    placeholders = ",".join("?" * len(face_ids))
    rows = conn.execute(
        f"SELECT f.id FROM faces f JOIN photos p ON p.path = f.photo_path "
        f"WHERE f.id IN ({placeholders}) AND {vis_sql}",
        [*face_ids, *vis_params],
    ).fetchall()
    if len({row[0] for row in rows}) != len(face_ids):
        raise LookupError("One or more face_ids not found")


def assert_photo_visible(conn, user_id, photo_path):
    """Raise ``LookupError`` if ``photo_path`` is outside the caller's directories.

    The write-side twin of the photo-visibility precheck used by the face read
    endpoints (``SELECT 1 FROM photos WHERE path = ? AND <visibility>``). A no-op
    outside multi-user mode; in multi-user mode a foreign path raises
    ``LookupError`` so callers map it to the same 404 as a nonexistent photo,
    never leaking existence.
    """
    if not is_multi_user_enabled():
        return
    vis_sql, vis_params = get_visibility_clause(user_id)
    row = conn.execute(
        f"SELECT 1 FROM photos WHERE path = ? AND {vis_sql}",
        [photo_path, *vis_params],
    ).fetchone()
    if not row:
        raise LookupError("Photo not found")


def get_photos_from_clause(user_id=None):
    """Build FROM clause for gallery queries."""
    if user_id and is_multi_user_enabled():
        return ("photos LEFT JOIN user_preferences up "
                "ON up.photo_path = photos.path AND up.user_id = ?"), [user_id]
    return "photos", []


def get_preference_columns(user_id=None):
    """Get SQL column expressions for user-preference columns."""
    if user_id and is_multi_user_enabled():
        return {
            'star_rating': 'COALESCE(up.star_rating, 0)',
            'is_favorite': 'COALESCE(up.is_favorite, 0)',
            'is_rejected': 'COALESCE(up.is_rejected, 0)',
            'is_kept': 'COALESCE(up.is_kept, 0)',
        }
    return {
        'star_rating': 'photos.star_rating',
        'is_favorite': 'photos.is_favorite',
        'is_rejected': 'photos.is_rejected',
        'is_kept': 'photos.is_kept',
    }


_LABEL_CHUNK = 500

# What a review reject (faces.py, single and batch) writes, shared by the ``user_preferences`` upsert and the
# ``photos`` UPDATE (both tables name these columns alike): it clears the rating, favourite and keep so a
# rejected frame carries none. A culling reject (set_photos_rejected) deliberately keeps rating and favourite.
REJECT_SET = "is_rejected = 1, star_rating = 0, is_favorite = 0, is_kept = 0"


class Labels(NamedTuple):
    """One photo's review labels; ``kept`` stays 0 unless the read asked for ``include_kept``."""

    star: int
    favorite: int
    rejected: int
    kept: int = 0


def _read_label_tuples(conn, scope, chunk, include_kept=False):
    """``{path: Labels}`` for ``chunk``; a path with no row reads as unrated."""
    marks = ','.join('?' * len(chunk))
    kept = ', is_kept' if include_kept else ''
    if scope:
        rows = conn.execute(
            f"SELECT photo_path, star_rating, is_favorite, is_rejected{kept} FROM user_preferences "
            f"WHERE user_id = ? AND photo_path IN ({marks})", [scope, *chunk]).fetchall()
    else:
        rows = conn.execute(
            f"SELECT path, star_rating, is_favorite, is_rejected{kept} FROM photos "
            f"WHERE path IN ({marks})", chunk).fetchall()
    found = {r[0]: Labels(*(value or 0 for value in r[1:])) for r in rows}
    return {p: found.get(p, Labels(0, 0, 0)) for p in chunk}


def _label_scope(user_id):
    return user_id if (user_id and is_multi_user_enabled()) else ''


def read_labels(conn, user_id, paths, *, include_kept=False):
    """``{path: Labels}`` from the per-user source (``user_preferences`` in
    multi-user mode, the ``photos`` columns otherwise), read in chunks.

    ``include_kept`` appends the review decision for culling preview guards; taste
    provenance leaves ``Labels.kept`` at 0.
    """
    paths = list(paths)
    scope = _label_scope(user_id)
    labels = {}
    for start in range(0, len(paths), _LABEL_CHUNK):
        labels.update(_read_label_tuples(conn, scope, paths[start:start + _LABEL_CHUNK], include_kept))
    return labels


def snapshot_labels(conn, agent, user_id, paths):
    """The label tuples of ``paths`` BEFORE a write, for :func:`record_label_origin`'s ``before``.

    Only an assistant's write needs it (a person's write just deletes marks), so a human call reads
    nothing and returns ``{}``.
    """
    paths = list(paths)
    if not agent or not paths:
        return {}
    return read_labels(conn, user_id, paths)


def record_label_origin(conn, agent, user_id, paths, before=None):
    """Keep ``rating_provenance`` true to who wrote the labels of ``paths``, in the writer's transaction.

    An agent's write (the internal ``mcp`` JWT, ``user.is_agent_request``) records the tuple it left, so
    the taste model skips it (``optimization.label_pairs``); a person's own write deletes the mark, the
    label being theirs again. Only a path whose tuple the write CHANGED is marked (``before`` is the
    :func:`snapshot_labels` taken ahead of the write): a label the person had already set and the
    assistant merely re-asserted stays theirs and keeps training. A path already marked stays marked,
    with its tuple refreshed. ``before=None`` treats every path as changed.
    """
    paths = list(paths)
    if not paths:
        return
    scope = _label_scope(user_id)
    for start in range(0, len(paths), _LABEL_CHUNK):
        chunk = paths[start:start + _LABEL_CHUNK]
        marks = ','.join('?' * len(chunk))
        if not agent:
            conn.execute(f"DELETE FROM rating_provenance WHERE user_id = ? AND photo_path IN ({marks})",
                         [scope, *chunk])
            continue
        after = _read_label_tuples(conn, scope, chunk)
        marked = {r[0] for r in conn.execute(
            f"SELECT photo_path FROM rating_provenance WHERE user_id = ? AND photo_path IN ({marks})",
            [scope, *chunk])}
        conn.executemany(
            "INSERT INTO rating_provenance (user_id, photo_path, star_rating, is_favorite, is_rejected) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, photo_path) DO UPDATE SET "
            "star_rating = excluded.star_rating, is_favorite = excluded.is_favorite, "
            "is_rejected = excluded.is_rejected",
            [(scope, p, t.star, t.favorite, t.rejected) for p, t in after.items()
             if p in marked or before is None or before.get(p) != t])


def clear_label_origin_for_scope(conn, user_id, from_clause, where_str, scope_params):
    """Delete the provenance marks of every photo a filter scope matches, in one set-based statement.

    A person's filter-scoped write only needs to remove marks, so the scope is never read into Python.
    Run it BEFORE the write, while the scope still matches the same rows.
    """
    conn.execute(
        "DELETE FROM rating_provenance WHERE user_id = ? AND photo_path IN "
        f"(SELECT photos.path FROM {from_clause}{where_str})",
        [_label_scope(user_id), *scope_params])


def set_photos_rejected(conn, paths, user_id, agent=False):
    """Mark photos as rejected, honoring multi-user per-user preferences and visibility.

    Resolves the caller's visible subset of ``paths`` first, then records the
    rejection per-user in ``user_preferences`` (multi-user mode) or in the global
    ``photos`` table (single-user). This keeps bulk culling/scene rejects consistent
    with the per-user read path (``get_preference_columns``) and the single-photo
    toggle in ``api/routers/faces.py``. Returns the number of photos affected. ``agent`` says an
    assistant made the call, which :func:`record_label_origin` records for the taste model.
    """
    if not paths:
        return 0
    vis_sql, vis_params = get_visibility_clause(user_id)
    placeholders = ','.join('?' * len(paths))
    visible = [r[0] for r in conn.execute(
        f"SELECT path FROM photos WHERE path IN ({placeholders}) AND {vis_sql}",
        list(paths) + vis_params,
    ).fetchall()]
    if not visible:
        return 0
    history_before = organization_capture.begin(conn, user_id, 'review', visible)
    before = snapshot_labels(conn, agent, user_id, visible)
    if user_id and is_multi_user_enabled():
        conn.executemany(
            "INSERT INTO user_preferences (user_id, photo_path, is_rejected, is_kept) "
            "VALUES (?, ?, 1, 0) "
            "ON CONFLICT(user_id, photo_path) DO UPDATE SET is_rejected = 1, is_kept = 0",
            [(user_id, p) for p in visible],
        )
    else:
        ph = ','.join('?' * len(visible))
        conn.execute(f"UPDATE photos SET is_rejected = 1, is_kept = 0 WHERE path IN ({ph})", visible)
    record_label_origin(conn, agent, user_id, visible, before)
    organization_capture.finish(conn, user_id, 'review', history_before)
    return len(visible)


def set_photos_kept(conn, paths, user_id, agent=False):
    """Persist visible culling keepers: sets ``is_kept``, clears ``is_rejected``, leaves favorites and ratings.

    Records the label origin for an assistant's call, or for a person's only on a photo that was
    rejected (the write changes its labels); other human keeps just stay theirs.
    """
    if not paths:
        return 0
    vis_sql, vis_params = get_visibility_clause(user_id)
    visible = [row[0] for row in select_in_chunks(
        conn, f"SELECT path FROM photos WHERE path IN ({{placeholders}}) AND {vis_sql}",
        list(paths), after=vis_params,
    )]
    history_before = organization_capture.begin(conn, user_id, 'review', visible)
    before = read_labels(conn, user_id, visible)
    if user_id and is_multi_user_enabled():
        conn.executemany(
            "INSERT INTO user_preferences (user_id, photo_path, is_kept, is_rejected) "
            "VALUES (?, ?, 1, 0) ON CONFLICT(user_id, photo_path) "
            "DO UPDATE SET is_kept = 1, is_rejected = 0",
            [(user_id, path) for path in visible],
        )
    else:
        conn.executemany("UPDATE photos SET is_kept = 1, is_rejected = 0 WHERE path = ?",
                         [(path,) for path in visible])
    origin_paths = visible if agent else [path for path in visible if before[path].rejected]
    record_label_origin(conn, agent, user_id, origin_paths, before)
    organization_capture.finish(conn, user_id, 'review', history_before)
    return len(visible)


# How far outside the frame a face box may legitimately reach. InsightFace does
# not clip its boxes, so a face at the edge overhangs a little; a box beyond this
# is not an overhang but a coordinate-space mismatch — the stored dimensions are
# not the frame the detector saw. Shared by the repair below (which reads it as
# proof) and by normalized_face_box below (which reads it as grounds to distrust
# a box), so the two can never drift apart.
FACE_FRAME_TOLERANCE = 1.25


def normalized_face_box(x1, y1, x2, y2, width, height):
    """Normalise a pixel face box to the frame, or None when it can't be trusted.

    Returns None for a missing/degenerate box, for a photo with no stored
    dimensions, and for a box that overshoots the frame past
    ``FACE_FRAME_TOLERANCE``. InsightFace does not clip its boxes, so a face at
    the edge overhangs a little and a legitimate overhang is clamped to the
    frame; past that bound it is not an overhang but a coordinate-space mismatch
    — the stored dimensions are not the frame the detector saw (see
    ``repair_thumbnail_dimensions`` in api.db_helpers, which clears the ones a
    former startup hook filled from the 640px thumbnail). Such a face is dropped
    rather than clamped: clamping would pin the "key subject" to a frame edge
    and point the zoom at nothing.
    """
    if None in (x1, y1, x2, y2) or not width or not height:
        return None
    if width <= 0 or height <= 0 or x2 <= x1 or y2 <= y1:
        return None
    overhang = FACE_FRAME_TOLERANCE - 1.0
    if (x2 > width * FACE_FRAME_TOLERANCE or y2 > height * FACE_FRAME_TOLERANCE
            or x1 < -width * overhang or y1 < -height * overhang):
        return None
    box = [
        max(0.0, min(1.0, x1 / width)), max(0.0, min(1.0, y1 / height)),
        max(0.0, min(1.0, x2 / width)), max(0.0, min(1.0, y2 / height)),
    ]
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


# Clearing two integers still rewrites the whole photo record, thumbnail BLOB
# and embeddings included, so the repair commits in batches. A library where
# tens of thousands of rows were backfilled would otherwise hold gigabytes of
# rewritten rows in one transaction, and the WAL cannot be checkpointed until it
# commits.
REPAIR_BATCH_SIZE = 500

# One-shot marker: the repair is a correction of a past backfill, not a
# recurring maintenance job, so it belongs to the library rather than to the
# process. Without it the scan below ran on every boot and never got cheaper —
# roughly 50k rows of a 127k library still match the thumbnail-range prefilter
# after the repair (a genuinely small photo keeps its real dimensions), so the
# correlated EXISTS re-ran against `faces` for each of them, 115s cold / 9s warm,
# for a zero-row result. `stats_cache` is the library's own scratch space and is
# created by `init_database` before this ever runs.
THUMBNAIL_DIMS_REPAIRED_KEY = 'thumbnail_dims_repaired'


def repair_thumbnail_dimensions():
    """Clear ``image_width``/``image_height`` values fabricated from a thumbnail.

    Those two columns record the pixel space of the array the scan handed to the
    face detector, which is what makes ``faces.bbox_*`` meaningful: one pass
    reads ``img_cv.shape`` into them and hands the same array to
    ``analyze_faces()``. An earlier startup hook filled NULL dimensions from the
    stored 640px thumbnail instead, silently redefining that space — every
    consumer that normalises a face box by the recorded dimensions then produced
    coordinates several times outside the frame.

    The original size is not recoverable from a thumbnail, so the fabricated
    values are removed rather than corrected: NULL means "not recorded", which
    every consumer already handles, while a thumbnail-sized number is a lie that
    reads as ground truth. A row qualifies only on proof — its dimensions are
    within thumbnail range *and* one of its own face boxes cannot fit inside
    them. A genuinely small image fails the second test (its boxes fit), and a
    row carrying full-size dimensions fails the first, so a mismatch with some
    other cause never costs it real data.

    What the fabricated pair *did* carry correctly is the frame's shape: a
    thumbnail is scaled, not cropped, so 640x427 is the wrong size but the right
    3:2. That ratio is moved to ``image_aspect`` in the same statement, because
    the gallery lays a tile out from it and an unknown aspect there is not a
    skipped overlay but a portrait photo cropped into a landscape box. It lands
    in its own column rather than back in the dimensions so that the readers
    which treat a positive width as a pixel count — the MWG face regions written
    into sidecars on disk, the social-crop rectangle — keep seeing NULL and keep
    skipping.

    Runs once per library: a marker row in ``stats_cache`` records that the
    correction has been applied, and a later call returns 0 without scanning.
    Idempotent either way — a repaired row holds NULL and no longer matches.
    """
    max_thumbnail_edge = (_FULL_CONFIG.get('processing', {}).get('thumbnails', {})
                          .get('photo_size', DEFAULT_PHOTO_THUMBNAIL_SIZE))
    conn = get_db_connection()
    try:
        already_done = conn.execute(
            "SELECT 1 FROM stats_cache WHERE key = ?", (THUMBNAIL_DIMS_REPAIRED_KEY,),
        ).fetchone()
        if already_done:
            logger.debug("Thumbnail-dimension repair already applied to this library")
            return 0

        # Only `path` is selected: `photos` carries the thumbnail, embedding and
        # histogram BLOBs inline, and a bulk scan that names them would drag the
        # whole library through memory.
        fabricated = [row[0] for row in conn.execute(
            "SELECT path FROM photos "
            "WHERE image_width IS NOT NULL AND image_height IS NOT NULL "
            "AND MAX(image_width, image_height) <= ? "
            "AND EXISTS (SELECT 1 FROM faces f WHERE f.photo_path = photos.path "
            "AND (f.bbox_x2 > photos.image_width * ? "
            "OR f.bbox_y2 > photos.image_height * ?))",
            (max_thumbnail_edge, FACE_FRAME_TOLERANCE, FACE_FRAME_TOLERANCE),
        ).fetchall()]
        for start in range(0, len(fabricated), REPAIR_BATCH_SIZE):
            batch = fabricated[start:start + REPAIR_BATCH_SIZE]
            placeholders = ','.join('?' * len(batch))
            # One statement, so the ratio is computed from the pre-update row:
            # SQLite evaluates every SET expression against the original values.
            conn.execute(
                "UPDATE photos SET "
                "image_aspect = CASE WHEN image_height > 0 "
                "THEN ROUND(CAST(image_width AS REAL) / image_height, 6) END, "
                "image_width = NULL, image_height = NULL "
                f"WHERE path IN ({placeholders})", batch
            )
            conn.commit()
        conn.execute(
            "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
            (THUMBNAIL_DIMS_REPAIRED_KEY, str(len(fabricated)), time.time()),
        )
        conn.commit()
        if fabricated:
            logger.info(
                "Cleared thumbnail-sized dimensions on %d photos (aspect kept in "
                "image_aspect): their own face boxes prove the recorded size was "
                "not the detection frame",
                len(fabricated)
            )
        return len(fabricated)
    finally:
        conn.close()
