"""Pydantic models for the filter-options, caption, critique, saliency and
social-crop-preview endpoints (`api/routers/filter_options.py`, `caption.py`,
`critique.py`, `saliency.py`, `social_crop.py`).

Several filter-option endpoints put raw ``(value, count)`` / ``(id, name,
count)`` tuples on the wire, not objects -- the client types them the same
way (e.g. ``[number, string | null, number][]``). They are declared as fixed
positional tuples here rather than objects so the shape is pinned without
renaming keys the client never sent.

The critique endpoint's category-mismatch payload (``required`` / ``actual``
on ``MediaCritiqueCategoryMismatch``, ``value`` / ``threshold`` on
``MediaCritiqueCategoryReasonDetail``, and the whole ``penalties`` map) is
genuinely polymorphic at the Python level -- a filter's "required"/"actual"
can be a bool, a number or a list of tags depending which filter tripped, a
numeric detail can be an int or a float depending on how the matching
config value was authored, and a penalty value can be ``True``, a rounded
float or a skin-tone-cast dict. The client itself types the mismatch pair as
`unknown` and the penalty map as a union it never narrows, so all of these
are declared ``Any`` here rather than guessed into a ``Union`` that risks
silently coercing one branch (e.g. ``True`` -> ``1.0``).
"""

from typing import Any, Optional

from pydantic import BaseModel


class MediaFilterOptionPersonsResponse(BaseModel):
    persons: list[tuple[int, Optional[str], int]] = []
    cached: bool


class MediaFilterOptionJunkKindsResponse(BaseModel):
    junk_kinds: list[tuple[str, int]] = []
    cached: bool


class MediaFilterOptionCamerasResponse(BaseModel):
    cameras: list[tuple[str, int]] = []
    cached: bool


class MediaFilterOptionLensesResponse(BaseModel):
    lenses: list[tuple[str, int]] = []
    cached: bool


class MediaFilterOptionTagsResponse(BaseModel):
    tags: list[tuple[str, int]] = []
    cached: bool


class MediaLocationNameResponse(BaseModel):
    display_name: str


class MediaCaptionResponse(BaseModel):
    caption: Optional[str] = None
    source: str
    lang: Optional[str] = None


class MediaCritiqueBreakdownItem(BaseModel):
    metric: str
    metric_key: str
    value: float
    weight: float
    contribution: float


class MediaCritiqueMetricRef(BaseModel):
    metric_key: str
    value: float


class MediaCritiqueCategoryReasonDetail(BaseModel):
    key: str
    value: Any = None
    threshold: Any = None
    tags: Optional[list[str]] = None


class MediaCritiqueCategoryMismatch(BaseModel):
    key: str
    required: Any = None
    actual: Any = None


class MediaCritiqueRejectedCategory(BaseModel):
    category: str
    mismatch: MediaCritiqueCategoryMismatch


class MediaCritiqueCategoryReason(BaseModel):
    reason_key: str
    category: str
    details: list[MediaCritiqueCategoryReasonDetail] = []
    rejected: list[MediaCritiqueRejectedCategory] = []


class MediaCritiqueResponse(BaseModel):
    category: str
    category_reason: MediaCritiqueCategoryReason
    aggregate: Optional[float] = None
    breakdown: list[MediaCritiqueBreakdownItem] = []
    strengths: list[MediaCritiqueMetricRef] = []
    weaknesses: list[MediaCritiqueMetricRef] = []
    suggestions: list[str] = []
    penalties: dict[str, Any] = {}
    distortions: list[str] = []
    vlm_critique: Optional[str] = None
    vlm_source: Optional[str] = None
    vlm_available: Optional[bool] = None


class MediaFaceMarker(BaseModel):
    bbox: Optional[list[float]] = None
    eyes: list[list[float]] = []
    eyes_open_score: Optional[float] = None
    is_blink: bool


class MediaFaceMarkersResponse(BaseModel):
    faces: list[MediaFaceMarker] = []


class MediaSocialCropRect(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class MediaSocialCropPreviewResponse(BaseModel):
    preset: str
    aspect: str
    source: str
    rect: MediaSocialCropRect
