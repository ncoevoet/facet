"""The ``photos.render_version`` stamp: which display render built a row's thumbnail.

A stored thumbnail is a *baked* artifact. When the RAW display profile changed
(camera-embedded preview first, faithful demosaic as fallback — see
``utils.image_loading.load_display_image``), every thumbnail already in the
database stayed on the old, exposure-equalizing rendering. ``/image`` renders on
the fly and self-corrects; the gallery grid reads ``photos.thumbnail`` and does
not. This column says which rows are still on the wrong rendering, so the
migration can be reported and resumed instead of forcing a full rescan.

The stamp records WHICH of the two RAW display renderings baked the thumbnail,
not merely how old it is, because the right one depends on the row's
``sequence_kind``: a bracketed frame renders with no correction at all, anything
else through the camera preview. Sequence detection runs after a scan, so a scan
can only ever bake the display rendering — a frame a later pass groups into a
bracket therefore ends up carrying ``DISPLAY_RENDER_VERSION`` while its kind now
demands ``FAITHFUL_RENDER_VERSION``, and comparing the stamp against the kind is
what surfaces it to the migration instead of leaving it silently wrong.

The stamp is DERIVED state, so it belongs on ``photos`` even though
``processing/scorer.py`` rewrites that table wholesale: a rescan regenerates the
thumbnail with current code, and the stamp must be rewritten with it. Every
writer of a fresh thumbnail therefore stamps the rendering it used, and a NULL
means "written before the stamp existed", never "unknown but fine".

Only RAW rows are ever pending: JPEG and HEIF display rendering never changed,
so any pipeline version produces the same bytes for them.
"""

# Camera-embedded preview first, configured `bright` gain on the demosaic
# fallback: what a scan bakes and what every non-bracketed RAW should show.
DISPLAY_RENDER_VERSION = 1

# No preview and no gain: what a frame of a bracketed set should show, and what
# only `--refresh-thumbnails` can bake, since it is the first pass that knows
# the frame is bracketed.
FAITHFUL_RENDER_VERSION = 2


def render_version_for(sequence_kind):
    """The stamp for a thumbnail just rendered for a row of this sequence kind."""
    from utils.image_loading import renders_faithfully

    return FAITHFUL_RENDER_VERSION if renders_faithfully(sequence_kind) else DISPLAY_RENDER_VERSION


def raw_path_predicate(alias=''):
    """SQL predicate matching RAW paths (LIKE is case-insensitive over ASCII)."""
    from utils.image_loading import RAW_EXTENSIONS

    column = f"{alias}.path" if alias else "path"
    return " OR ".join(f"{column} LIKE '%{ext}'" for ext in sorted(RAW_EXTENSIONS))


def expected_render_version_sql(alias=''):
    """SQL for the stamp a row's CURRENT sequence kind demands.

    Built from ``renders_faithfully`` rather than from the kind list directly,
    so turning ``raw_decode.faithful_bracket_render`` off cannot leave brackets
    permanently pending against a rendering nothing will ever produce.
    """
    from utils.image_loading import BRACKETED_SEQUENCE_KINDS, renders_faithfully

    faithful = sorted(kind for kind in BRACKETED_SEQUENCE_KINDS if renders_faithfully(kind))
    if not faithful:
        return str(DISPLAY_RENDER_VERSION)
    column = f"{alias}.sequence_kind" if alias else "sequence_kind"
    kinds = ', '.join(f"'{kind}'" for kind in faithful)
    return (f"CASE WHEN {column} IN ({kinds}) THEN {FAITHFUL_RENDER_VERSION} "
            f"ELSE {DISPLAY_RENDER_VERSION} END")


def pending_render_predicate(alias=''):
    """SQL predicate matching RAW rows whose thumbnail is not the render they need."""
    column = f"{alias}.render_version" if alias else "render_version"
    return (f"({column} IS NULL OR {column} <> {expected_render_version_sql(alias)}) "
            f"AND ({raw_path_predicate(alias)})")


def count_pending_render(conn):
    """How many RAW rows carry a thumbnail from the wrong display render.

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
