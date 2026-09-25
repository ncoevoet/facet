"""Shared rating-state upsert, extracted from ``xmp_import.import_sidecars``.

Both the XMP sidecar importer and the Lightroom-state importer
(``processing/lightroom_sync.py``) need to write ``star_rating`` /
``is_favorite`` / ``is_rejected`` either to the global ``photos`` columns or,
in multi-user mode, to that user's ``user_preferences`` row -- see
CLAUDE.md's note that ``user_preferences`` holds the per-user ratings while
the ``photos`` columns are the single-user/global fallback.

Each of the three fields is independently optional: a caller passes ``UNSET``
(the module default) for any field it does not want to touch, so a caller
with only a rating leaves the pick flags alone and vice versa.
"""

from __future__ import annotations


class _Unset:
    def __repr__(self):
        return "UNSET"


UNSET = _Unset()


def resolve_per_user(user_id, per_user):
    """Resolve the multi-user write scope, shared by every rating writer.

    ``per_user``, when explicitly passed (``True``/``False``), is used as-is:
    the caller has already resolved multi-user mode against the SAME config
    that validated ``user_id`` (see ``facet.py --import-lightroom`` / I4) and
    that resolution must not be re-derived from a possibly different file.
    When ``per_user`` is left at its default ``None``, this falls back to
    ``api.config.is_multi_user_enabled()`` -- ``import_sidecars``'s existing
    behaviour, unchanged. Either way, ``user_id`` still gates it: a falsy
    ``user_id`` always resolves to the global ``photos`` columns.
    """
    if per_user is None:
        from api.config import is_multi_user_enabled
        return bool(user_id and is_multi_user_enabled())
    return bool(user_id and per_user)


def upsert_rating_state(conn, photo_path, user_id, *,
                         star_rating=UNSET, is_favorite=UNSET, is_rejected=UNSET, per_user=None):
    """Write present fields to ``photos`` (global) or ``user_preferences`` (per-user).

    See :func:`resolve_per_user` for how ``per_user`` is resolved. When
    writing per-user and there is no existing ``user_preferences`` row, the
    insert is skipped entirely if every present field is its all-zero/default
    value -- this avoids inserting a meaningless all-zero row for every
    unrated/unflagged photo (N9).
    """
    per_user = resolve_per_user(user_id, per_user)

    if per_user:
        row = conn.execute(
            "SELECT star_rating, is_favorite, is_rejected FROM user_preferences "
            "WHERE user_id = ? AND photo_path = ?",
            (user_id, photo_path),
        ).fetchone()
        exists = row is not None
        cur_star = row["star_rating"] if row else 0
        cur_fav = row["is_favorite"] if row else 0
        cur_rej = row["is_rejected"] if row else 0

        new_star = cur_star if star_rating is UNSET else int(star_rating)
        new_fav = cur_fav if is_favorite is UNSET else int(bool(is_favorite))
        new_rej = cur_rej if is_rejected is UNSET else int(bool(is_rejected))

        if not exists and new_star == 0 and not new_fav and not new_rej:
            return

        conn.execute(
            "INSERT INTO user_preferences "
            "(user_id, photo_path, star_rating, is_favorite, is_rejected) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, photo_path) DO UPDATE SET "
            "star_rating = excluded.star_rating, is_favorite = excluded.is_favorite, "
            "is_rejected = excluded.is_rejected",
            (user_id, photo_path, new_star, new_fav, new_rej),
        )
        return

    sets = []
    params = []
    if star_rating is not UNSET:
        sets.append("star_rating = ?")
        params.append(int(star_rating))
    if is_favorite is not UNSET:
        sets.append("is_favorite = ?")
        params.append(int(bool(is_favorite)))
    if is_rejected is not UNSET:
        sets.append("is_rejected = ?")
        params.append(int(bool(is_rejected)))
    if not sets:
        return
    params.append(photo_path)
    conn.execute(f"UPDATE photos SET {', '.join(sets)} WHERE path = ?", params)
