"""Lightroom-wins importer: fold the plug-in's exported state back into Facet.

Reverse direction of ``processing.xmp_export``'s manifest: Lightroom's own
rating / pick / reject state, exported by ``FacetExportState.lua`` (Step 5a's
file format), is imported here as the winning value for every field a record
carries. Shared by the CLI (``facet.py --import-lightroom``) and the viewer's
``POST /api/lightroom/import`` route so the two callers cannot drift apart.

Path mapping happens ONCE, in Lua, at export time -- this module (and every
Python caller) matches ``path`` exactly as given, with no prefix logic. An
exact match is tried first; if it misses, a case-insensitive fallback is
tried, but only if it resolves to exactly one row (a collision is treated as
unmatched rather than guessing -- mirrors the apply direction's own
``findRecord`` policy).

Field-level Lightroom-wins semantics (locked decision):

* ``pick == 1``  -> ``is_favorite = 1, is_rejected = 0``
* ``pick == -1`` -> ``is_favorite = 0, is_rejected = 1``
* ``pick == 0``  -> clears both
* ``rating`` (0-5) -> ``star_rating`` (0 clears the rating)

Each of ``rating``/``pick`` is applied only if the record's key is present.
Every present field is written unconditionally (Lightroom wins fully); the
``changed`` count is a before/after diff computed purely for reporting, not a
conditional write.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from processing.rating_writer import UNSET, resolve_per_user, upsert_rating_state

FORMAT = "facet-lightroom-state"
FORMAT_VERSION = 1


class InvalidLightroomStateFile(ValueError):
    """Raised when a file fails Step 5a's format/version/record validation."""


@dataclass
class SyncResult:
    matched: int
    unmatched: int
    changed: int


def validate_lightroom_state(data: dict) -> list[dict]:
    """Validate Step 5a's discriminator + per-record shape; return ``photos``.

    Raises :class:`InvalidLightroomStateFile` before any DB write on any
    problem -- including a manifest file fed here by mistake (both files have
    a top-level ``photos[]``, but only this format carries ``format``/
    ``version``).
    """
    if not isinstance(data, dict):
        raise InvalidLightroomStateFile("Lightroom state file must be a JSON object")
    if data.get("format") != FORMAT:
        raise InvalidLightroomStateFile(
            f"Not a Lightroom state file (expected format='{FORMAT}')")
    if data.get("version") != FORMAT_VERSION:
        raise InvalidLightroomStateFile(
            f"Unsupported Lightroom state file version (expected {FORMAT_VERSION})")
    photos = data.get("photos")
    if not isinstance(photos, list):
        raise InvalidLightroomStateFile("'photos' must be a list")

    for i, record in enumerate(photos):
        if not isinstance(record, dict):
            raise InvalidLightroomStateFile(f"photos[{i}] is not an object")
        path = record.get("path")
        if not isinstance(path, str) or not path:
            raise InvalidLightroomStateFile(f"photos[{i}].path must be a non-empty string")
        if "rating" in record:
            rating = record["rating"]
            if not isinstance(rating, int) or isinstance(rating, bool) or not (0 <= rating <= 5):
                raise InvalidLightroomStateFile(f"photos[{i}].rating must be an int 0..5")
        if "pick" in record:
            pick = record["pick"]
            if not isinstance(pick, int) or isinstance(pick, bool) or pick not in (-1, 0, 1):
                raise InvalidLightroomStateFile(f"photos[{i}].pick must be -1, 0 or 1")

    return photos


_MISSING = object()


def _build_path_index(conn, visibility=None):
    """One pass over ``photos.path`` -> ``(exact_set, casefold_index)``.

    ``exact_set`` is every DB path, for O(1) exact-match membership.
    ``casefold_index`` maps ``lower(path) -> db_path | _MISSING``, where
    ``_MISSING`` marks a case-insensitive COLLISION (two or more DB paths that
    fold to the same lower-cased key) -- refused exactly like the old
    per-record ``COLLATE NOCASE`` query did when it found more than one row.

    Built ONCE per import rather than running a query per record: the old
    per-record ``WHERE path = ? COLLATE NOCASE`` scan (case-insensitive
    collation defeats the path index) made a wrong-prefix export -- every
    record unmatched, the common first-run mistake -- take ~4ms/record, about
    3.5 minutes at the 50000-photo import cap (I5).

    ``visibility``, when given, is a caller-resolved ``(sql, params)`` pair
    (e.g. ``api.db_helpers.get_visibility_clause(user_id)``) restricting the
    index to the caller's visible directories -- a directory-scoped caller
    (the viewer route) must never match, and so must never write or probe,
    a record outside its own scope. A record whose path falls outside the
    index simply misses both lookups below and is counted unmatched, exactly
    like a path that does not exist at all. The CLI passes no ``visibility``
    (an operator tool, not scoped to a session), so it is unrestricted.
    """
    exact_set: set = set()
    casefold_index: dict = {}
    if visibility is None:
        rows = conn.execute("SELECT path FROM photos")
    else:
        vis_sql, vis_params = visibility
        rows = conn.execute(f"SELECT path FROM photos WHERE {vis_sql}", vis_params)
    for (path,) in rows:
        exact_set.add(path)
        key = path.lower()
        casefold_index[key] = _MISSING if key in casefold_index else path
    return exact_set, casefold_index


def _find_photo_path(conn, path: str, path_index):
    """Exact match first, else a case-insensitive fallback (refused on collision).

    ``path_index`` is the ``(exact_set, casefold_index)`` pair from
    :func:`_build_path_index`; both lookups are O(1) dict/set membership. The
    sole caller (:func:`import_lightroom_state`) always builds and passes
    ``path_index`` before looping over records, so there is no per-record
    query fallback here -- one would silently reintroduce the exact
    ``COLLATE NOCASE`` scan this index replaced for being too slow (I5).
    """
    exact_set, casefold_index = path_index
    if path in exact_set:
        return path
    hit = casefold_index.get(path.lower())
    return hit if hit is not None and hit is not _MISSING else None


def _current_state(conn, db_path, user_id, per_user):
    if per_user:
        row = conn.execute(
            "SELECT star_rating, is_favorite, is_rejected FROM user_preferences "
            "WHERE user_id = ? AND photo_path = ?", (user_id, db_path),
        ).fetchone()
        if row is None:
            return (0, 0, 0)
        return (row["star_rating"], row["is_favorite"], row["is_rejected"])
    row = conn.execute(
        "SELECT star_rating, is_favorite, is_rejected FROM photos WHERE path = ?",
        (db_path,),
    ).fetchone()
    return (row["star_rating"] or 0, row["is_favorite"] or 0, row["is_rejected"] or 0)


def import_lightroom_state(db_path, records, user_id=None, per_user=None,
                            visibility=None) -> SyncResult:
    """Write Lightroom's rating/pick state into Facet's DB. See module docstring.

    ``records`` is a list of ``{path, rating?, pick?}`` dicts, already
    validated by :func:`validate_lightroom_state`. ``user_id`` is required and
    validated by the caller (CLI: ``facet.py::_resolve_cli_user``; viewer: the
    caller's own session user) -- this function does not itself refuse an
    unresolved user, since it has no config to check that against; it simply
    writes to the scope it is given.

    ``per_user``, when explicitly passed, is the multi-user decision the
    CALLER already made against the config that validated ``user_id`` (CLI:
    ``--config``; viewer: the running server's config, via
    ``api.config.is_multi_user_enabled()``). Left at its default ``None``, it
    falls back to the same resolution here (see
    ``processing.rating_writer.resolve_per_user``) -- which reads
    ``default_config_path()``/``$FACET_CONFIG``, a DIFFERENT file from a CLI
    ``--config`` on a library carrying its own ``scoring_config.json``. That
    silent split let a validated multi-user write land in the global
    ``photos`` columns instead of the user's own ``user_preferences`` row
    (I4) -- the CLI now always passes ``per_user`` explicitly.

    ``visibility``, when given, is a caller-resolved ``(sql, params)``
    visibility clause (e.g. ``api.db_helpers.get_visibility_clause(user_id)``)
    restricting which DB rows a record may match -- the viewer route passes
    the caller's own session-resolved visibility so a directory-scoped user
    cannot use matched/unmatched counts as an existence oracle for, or write
    ratings against, a photo outside their visible directories. A record
    outside ``visibility`` simply counts as unmatched, same as any other
    unmatched path. This module stays free of an ``api`` import for the
    write path itself -- the caller (router or CLI) resolves ``visibility``
    and hands over the finished clause.
    """
    from db.connection import get_connection

    per_user = resolve_per_user(user_id, per_user)

    matched = unmatched = changed = 0
    with get_connection(db_path) as conn:
        path_index = _build_path_index(conn, visibility=visibility)
        for record in records:
            db_row_path = _find_photo_path(conn, record["path"], path_index)
            if db_row_path is None:
                unmatched += 1
                continue
            matched += 1

            before = _current_state(conn, db_row_path, user_id, per_user)

            star_rating: object = UNSET
            is_favorite: object = UNSET
            is_rejected: object = UNSET
            if "rating" in record:
                star_rating = record["rating"]
            if "pick" in record:
                pick = record["pick"]
                if pick == 1:
                    is_favorite, is_rejected = True, False
                elif pick == -1:
                    is_favorite, is_rejected = False, True
                elif pick == 0:
                    is_favorite, is_rejected = False, False

            upsert_rating_state(
                conn, db_row_path, user_id,
                star_rating=star_rating, is_favorite=is_favorite, is_rejected=is_rejected,
                per_user=per_user,
            )

            after = _current_state(conn, db_row_path, user_id, per_user)
            if before != after:
                changed += 1

        conn.commit()

    if changed > 0:
        _nudge_retrain(db_path, user_id, changed, per_user=per_user)

    return SyncResult(matched=matched, unmatched=unmatched, changed=changed)


def _nudge_retrain(db_path, user_id, changed, per_user):
    """Fire the same auto-retrain + label-pair sync as every other rating writer.

    Mirrors ``api/routers/faces.py``'s rating-change path: ``_mint_rating_comparisons``
    calls ``trigger_auto_retrain`` (raw ``user_id``, which resolves its own
    multi-user scope internally) UNGUARDED, then ``_run_rating_sync``, which
    guards only ``sync_label_comparisons`` with ``except (sqlite3.Error,
    ImportError):``. This function is stricter than that mirror, not
    identical to it: because an import runs the sync inline rather than on
    faces.py's debounced timer, BOTH calls here are wrapped in their own
    ``except (sqlite3.Error, ImportError):`` so neither can propagate past an
    import that already committed its rating writes. ``per_user`` is the SAME
    resolution ``import_lightroom_state`` already made (I4) -- reusing it here
    rather than re-deriving from ``api.config.is_multi_user_enabled()`` keeps
    the label-pair scope in lockstep with which table the rating write
    actually landed in.
    """
    scope = user_id if per_user else None
    try:
        from api.db_helpers import trigger_auto_retrain
        trigger_auto_retrain(db_path, user_id, added=changed)
    except (sqlite3.Error, ImportError):
        pass
    try:
        from optimization.label_pairs import sync_label_comparisons
        sync_label_comparisons(db_path, user_id=scope)
    except (sqlite3.Error, ImportError):
        pass
