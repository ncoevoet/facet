"""Per-photo RGB + luminance histogram, served from the stored BLOB.

The bins come from ``photos.histogram_data``, which is computed during the scan
on the full-resolution *metrics* decode of the file — the faithful demosaic for
a RAW, not the embedded camera preview. That is strictly better than what the
client can measure for itself: the widget's fallback samples a <=160px q80 JPEG
thumbnail whose chroma is 4:2:0 subsampled, so its R and B curves are largely
interpolated.

A photo whose row predates the RGB format still answers with luminance only
(``r``/``g``/``b`` null); a row with no blob at all 404s, which is the client's
signal to fall back to sampling the thumbnail.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.auth import CurrentUser, get_optional_user
from api.database import get_db
from api.db_helpers import get_visibility_clause
from utils.histogram import clip_percents, display_channels, unpack_histogram

router = APIRouter(tags=["histogram"])

# Divisors of the stored 256 bins, so downsampling is an exact regroup rather
# than a resample. 64 matches the width the widget draws at.
DISPLAY_BIN_CHOICES = (32, 64, 128, 256)
DEFAULT_DISPLAY_BINS = 64

# The blob only changes on a rescan, and the widget is re-rendered on every
# gallery hover, so a short private cache saves a request per re-hover.
_CACHE_CONTROL = "private, max-age=300"


@router.get("/api/photo/histogram")
def api_photo_histogram(
    response: Response,
    path: str = Query(...),
    bins: int = Query(DEFAULT_DISPLAY_BINS),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Draw-ready luminance + R/G/B bins for one photo, in ``[0, 1]``.

    Every channel is divided by the single largest bin across all four, never by
    its own maximum: per-channel scaling would stretch a near-empty channel to
    full height and show a colour cast the photo does not have.

    The curves cover the interior bins only. ``clipped`` carries what bins 0 and
    255 hold, as a percentage of pixels per channel, for the end markers — it is
    ``null`` for a pre-RGB histogram, which means *unknown*, not clean.
    """
    if bins not in DISPLAY_BIN_CHOICES:
        raise HTTPException(
            status_code=400,
            detail=f"bins must be one of {', '.join(str(b) for b in DISPLAY_BIN_CHOICES)}",
        )

    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    with get_db() as conn:
        row = conn.execute(
            f"SELECT histogram_data FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params,
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Unknown photo")

    decoded = unpack_histogram(row["histogram_data"])
    if decoded is None:
        raise HTTPException(status_code=404, detail="No histogram for this photo")

    response.headers["Cache-Control"] = _CACHE_CONTROL
    return {
        "bins": bins,
        **display_channels(decoded, bins),
        "clipped": clip_percents(decoded),
    }
