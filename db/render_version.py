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

``photos.metrics_render`` is the sibling stamp on the SCORING side — 0 for the
metrics demosaic, 1 for the camera-embedded preview that
``raw_decode.metrics_from_embedded_preview`` opts into — and it is not a version
number: the two renderings are both current, and which one is right is the
user's setting. ``count_metrics_render`` below reports the split, so a library
toggled part-way through a rescan is visible instead of silently mixed.
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


def count_metrics_render(conn):
    """How many RAW rows were scored from each metrics rendering.

    Returns ``{'preview': n, 'demosaic': n, 'unset': n}``. The two counts are
    not interchangeable — a preview row carries the camera's tone curve,
    sharpening and noise reduction, so its technical scores are not comparable
    to a demosaiced row's — and ``unset`` is a row written before
    ``photos.metrics_render`` existed (or a file whose only readable pixels came
    from the LibRaw-unsupported rescue path). A library with more than one
    non-zero count was rescanned with ``metrics_from_embedded_preview`` toggled
    part-way, which is exactly what this report is for.

    Status/report use only: it scans ``photos``, so never call it on a request
    path. ``python database.py --info`` is the caller.
    """
    import sqlite3

    from utils.image_loading import METRICS_DEMOSAIC_RENDER, METRICS_PREVIEW_RENDER

    counts = {'preview': 0, 'demosaic': 0, 'unset': 0}
    try:
        row = conn.execute(
            "SELECT "
            f"COALESCE(SUM(CASE WHEN metrics_render = {METRICS_PREVIEW_RENDER} "
            "THEN 1 ELSE 0 END), 0), "
            f"COALESCE(SUM(CASE WHEN metrics_render = {METRICS_DEMOSAIC_RENDER} "
            "THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(CASE WHEN metrics_render IS NULL THEN 1 ELSE 0 END), 0) "
            f"FROM photos WHERE ({raw_path_predicate()})"
        ).fetchone()
    except sqlite3.OperationalError:
        return counts
    if row:
        counts['preview'], counts['demosaic'], counts['unset'] = (int(value) for value in row)
    return counts
