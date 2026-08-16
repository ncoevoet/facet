"""The ``photos.render_version`` stamp: which display-render pipeline built a row.

A stored thumbnail is a *baked* artifact. When the RAW display profile changed
(camera-embedded preview first, faithful demosaic as fallback — see
``utils.image_loading.load_display_image``), every thumbnail already in the
database stayed on the old, exposure-equalizing rendering. ``/image`` renders on
the fly and self-corrects; the gallery grid reads ``photos.thumbnail`` and does
not. This column says which rows are still on the old rendering, so the
migration can be reported and resumed instead of forcing a full rescan.

The stamp is DERIVED state, so it belongs on ``photos`` even though
``processing/scorer.py`` rewrites that table wholesale: a rescan regenerates the
thumbnail with current code, and the stamp must be rewritten with it. Every
writer of a fresh thumbnail therefore stamps ``CURRENT_RENDER_VERSION``, and a
NULL means "written before the stamp existed", never "unknown but fine".

Only RAW rows are ever pending: JPEG and HEIF display rendering never changed,
so any pipeline version produces the same bytes for them.
"""

CURRENT_RENDER_VERSION = 1


def raw_path_predicate(alias=''):
    """SQL predicate matching RAW paths (LIKE is case-insensitive over ASCII)."""
    from utils.image_loading import RAW_EXTENSIONS

    column = f"{alias}.path" if alias else "path"
    return " OR ".join(f"{column} LIKE '%{ext}'" for ext in sorted(RAW_EXTENSIONS))


def pending_render_predicate(alias=''):
    """SQL predicate matching RAW rows whose thumbnail predates the current render."""
    column = f"{alias}.render_version" if alias else "render_version"
    return (f"({column} IS NULL OR {column} < {CURRENT_RENDER_VERSION}) "
            f"AND ({raw_path_predicate(alias)})")


def count_pending_render(conn):
    """How many RAW rows still carry a thumbnail from an older render pipeline.

    Never call this on a request path — it reads every unstamped row's path.
    Callers go through the ``stats_cache`` entry instead (see
    ``db.stats_cache.get_pending_render_count``).
    """
    import sqlite3

    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM photos WHERE {pending_render_predicate()}"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        return 0
