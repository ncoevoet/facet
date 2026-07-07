"""Shared parsing for the persisted ``photos.subject_bbox`` normalized box.

A single strict parser used by both the subject close-up culling endpoint
(``/api/culling-group/subjects``) and the social-export crop
(``/api/photo/social_crop``): it clamps to ``[0, 1]``, rejects
malformed/degenerate boxes, and rejects near-full-frame boxes (a box over
``FULLFRAME_MAX_AREA`` of the frame means BiRefNet found no subject distinct
from the background).
"""

import json

FULLFRAME_MAX_AREA = 0.9


def parse_subject_bbox(raw):
    """Parse a stored ``subject_bbox`` into a valid normalized ``[x0,y0,x1,y1]``.

    Returns None for a missing / malformed / degenerate box, or one covering
    more than ``FULLFRAME_MAX_AREA`` of the frame — a near-full-frame box means
    BiRefNet found no subject distinct from the background, so there is nothing
    to frame on.
    """
    if not raw:
        return None
    try:
        box = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in box)
    except (ValueError, TypeError):
        return None
    x0, y0 = max(0.0, min(1.0, x0)), max(0.0, min(1.0, y0))
    x1, y1 = max(0.0, min(1.0, x1)), max(0.0, min(1.0, y1))
    if x1 <= x0 or y1 <= y0:
        return None
    if (x1 - x0) * (y1 - y0) > FULLFRAME_MAX_AREA:
        return None
    return [x0, y0, x1, y1]
