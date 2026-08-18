"""Pydantic response models for burst_culling.py, faces.py and persons.py."""

from typing import Any, Optional, Union

from pydantic import BaseModel


class CullReason(BaseModel):
    """Why a burst-group photo lost to the group's best, keyed for i18n
    translation client-side (``culling.reason.*``). ``value`` is currently
    always None -- every branch of ``_compute_cull_reason`` returns it that
    way -- but stays optional rather than dropped, since the reason a photo
    lost is derived per-branch and a future branch may want to carry one.
    """

    key: str
    value: Optional[float] = None


class BurstGroupPhoto(BaseModel):
    """One photo as ``_format_group`` places it in a burst group."""

    path: str
    filename: Optional[str] = None
    aggregate: Optional[float] = None
    aesthetic: Optional[float] = None
    tech_sharpness: Optional[float] = None
    is_blink: int
    eyes_open_score: Optional[float] = None
    expression_score: Optional[float] = None
    face_count: int
    is_burst_lead: int
    date_taken: Optional[str] = None
    burst_score: float
    sequence_kind: Optional[str] = None
    sequence_ev_offset: Optional[float] = None
    cull_reason: CullReason


class BurstGroup(BaseModel):
    burst_id: int
    photos: list[BurstGroupPhoto]
    best_path: Optional[str] = None
    count: int
    category: Optional[str] = None
    sequence_kind: Optional[str] = None


class BurstGroupsResponse(BaseModel):
    """``GET /api/burst-groups``."""

    groups: list[BurstGroup]
    total_groups: int
    page: int
    per_page: int
    total_pages: int


class CullingGroupsResponse(BaseModel):
    """``GET /api/culling-groups``.

    ``groups`` stays a loosely typed passthrough on purpose. The feed merges
    five materially different fetchers -- burst, similar, scene, bracket and
    panorama -- each adding its own keys (``reason``, ``start``, ``end``,
    ``moment``, ``moment_confidence``, ``similarity_percent``,
    ``keeper_best_path`` when a keeper head is trained ...) on top of a shared
    core. A field-by-field union model would either 500 on whichever shape it
    was not built from, or duplicate every fetcher's dict-building logic here
    just to keep it in sync -- exactly the "tidy the handler to fit the model"
    the phase rules out. The outer pagination envelope is still fully typed.
    """

    groups: list[dict[str, Any]]
    total_groups: int
    page: int
    per_page: int
    total_pages: int


class CullProfile(BaseModel):
    id: str
    label_key: str
    strictness: Optional[Union[int, float]] = None
    eyes_closed_max: Optional[float] = None
    poor_expression_min: Optional[float] = None
    keep_min_per_group: Optional[int] = None
    similarity_threshold: Optional[Union[int, float]] = None


class CullProfilesResponse(BaseModel):
    """``GET /api/culling/profiles``."""

    profiles: list[CullProfile]
    default: str


class ShootTypeEvidence(BaseModel):
    """Per-genre photo counts behind a shoot-type suggestion.

    The genre keys mirror ``_SUGGEST_CATEGORIES`` -- a fixed set defined in
    code, not user-configurable -- so they are named fields rather than a
    free-form mapping.
    """

    photos: int
    wedding: int = 0
    sports: int = 0
    concert: int = 0
    wildlife: int = 0

    model_config = {'extra': 'allow'}


class SuggestCullProfileResponse(BaseModel):
    """``GET /api/culling/suggest_profile``."""

    profile: Optional[str] = None
    confidence: float
    evidence: ShootTypeEvidence


class AutoCullPreviewItem(BaseModel):
    group_id: int
    type: str
    keep_paths: list[str]
    reject_paths: list[str]
    best_path: str


class AutoCullResponse(BaseModel):
    """``POST /api/culling/auto``."""

    groups_processed: int
    kept: int
    rejected: int
    highlights_added: int
    dry_run: bool
    preview: list[AutoCullPreviewItem]
    preview_truncated: bool


class KeeperHint(BaseModel):
    """One entry of ``POST /api/photos/keeper_hints``'s ``{path: hint}`` map."""

    has_better: bool
    best_path: Optional[str] = None
    keeper_prob: float


class PersonFace(BaseModel):
    """A face row as ``GET /api/person/{person_id}/faces`` emits it."""

    id: int
    photo_path: str
    face_index: int
    bbox_x1: Optional[int] = None
    bbox_y1: Optional[int] = None
    bbox_x2: Optional[int] = None
    bbox_y2: Optional[int] = None


class PersonFacesResponse(BaseModel):
    faces: list[PersonFace]


class PhotoFace(BaseModel):
    """A face row as ``GET /api/photo/faces`` emits it, with its assignment."""

    id: int
    face_index: int
    bbox_x1: Optional[int] = None
    bbox_y1: Optional[int] = None
    bbox_x2: Optional[int] = None
    bbox_y2: Optional[int] = None
    person_id: Optional[int] = None
    person_name: Optional[str] = None


class PhotoFacesResponse(BaseModel):
    faces: list[PhotoFace]


class ToggleFavoriteResponse(BaseModel):
    """``POST /api/photo/toggle_favorite``.

    The handler computes real Python booleans (``new_value == 1``), never the
    photo row's raw 0/1 -- this is not the ``Photo`` model's flag convention.
    """

    success: bool
    is_favorite: bool
    is_rejected: Optional[bool] = None


class ToggleRejectedResponse(BaseModel):
    """``POST /api/photo/toggle_rejected``. Same real-boolean convention as
    ``ToggleFavoriteResponse``; ``star_rating`` is a real int the handler
    resets to 0 on rejection, not a photo-row passthrough.
    """

    success: bool
    is_rejected: bool
    star_rating: Optional[int] = None
    is_favorite: Optional[bool] = None


class PersonListEntry(BaseModel):
    id: int
    name: Optional[str] = None
    representative_face_id: Optional[int] = None
    face_count: Optional[int] = None
    is_hidden: int
    face_thumbnail: int
    rep_quality: float


class PersonsListResponse(BaseModel):
    """``GET /api/persons``."""

    persons: list[PersonListEntry]
    total: int
    sort: str


class PersonNeedsNamingEntry(BaseModel):
    id: int
    name: Optional[str] = None
    representative_face_id: Optional[int] = None
    face_count: Optional[int] = None
    face_thumbnail: int


class PersonsNeedsNamingResponse(BaseModel):
    """``GET /api/persons/needs_naming``."""

    persons: list[PersonNeedsNamingEntry]
    min_faces: int
    total: int
