"""Pydantic models for the gallery/map/search/timeline discovery endpoints."""

from typing import Any, Optional
from pydantic import BaseModel

from api.models.gallery import Photo


class PhotoSetMember(BaseModel):
    """One frame in a bracket/panorama/burst/duplicate set."""

    path: str
    ev_offset: Optional[float] = None
    is_lead: bool


class PhotoSetResponse(BaseModel):
    """The bracket/panorama/burst/duplicate set a photo belongs to, if any.

    ``kind``/``group_id``/``ev_span`` are all ``None`` together when the photo
    belongs to no set. Only a bracket carries an ``ev_span`` -- panoramas,
    bursts and duplicate sets have no per-frame exposure offset to span.
    """

    kind: Optional[str] = None
    group_id: Optional[int] = None
    count: int
    ev_span: Optional[float] = None
    members: list[PhotoSetMember] = []


class PhotoTypeCount(BaseModel):
    """One gallery sidebar type entry with its non-zero photo count."""

    id: str
    label: str
    count: int


class PhotoTypeCountsResponse(BaseModel):
    types: list[PhotoTypeCount] = []


class SocialExportPreset(BaseModel):
    key: str
    label_key: str
    aspect: str


class SocialExportPresets(BaseModel):
    presets: list[SocialExportPreset] = []


class CullStyleOption(BaseModel):
    """A configured darktable cull style (empty when darktable-cli is absent)."""

    name: str
    label_key: str


class CullCapabilities(BaseModel):
    """Whether ``POST /api/cull/apply``'s ``trash_rejects`` action can succeed.

    Two booleans, not one, because the endpoint has two independent refusals
    for that action -- 403 when ``viewer.cull.allow_trash`` is off, 400 when
    the ``send2trash`` package is missing -- and a client that hides the
    "Trash rejects" option needs to say which cause applies rather than just
    that trashing won't work. ``allow_trash`` mirrors the config value as-is
    so the client can explain "an operator disabled this"; ``trash_available``
    is the AND of both conditions and is what should actually gate showing
    the option in the first place.
    """

    allow_trash: bool
    trash_available: bool


class RenderMigrationStatus(BaseModel):
    pending: int


class ViewerConfigResponse(BaseModel):
    """Startup configuration for the Angular client.

    Sub-trees copied straight out of ``scoring_config.json``'s ``viewer``
    block (``defaults``, ``pagination``, ``display``, ``badges``, ``clipping``,
    ``quality_thresholds``, ``features``, ``sort_options_grouped``) are typed
    ``dict[str, Any]`` rather than modelled field-by-field: their shape is
    whatever the operator's config declares, and pinning a stricter type
    would coerce -- or reject -- a value the handler itself never validates.
    The same reasoning applies to ``moment_confidence_min`` and
    ``notification_duration_ms``, which are numeric config values whose
    int-vs-float shape depends on how the operator wrote the JSON.
    """

    sort_options: list[tuple[str, str]]
    sort_options_grouped: Optional[dict[str, Any]] = None
    # Photos-column names of metrics the active licensing policy cannot compute
    # (commercial mode: ``liqe_score``, ``aesthetic_iaa``, and ``face_quality_iqa``
    # unless OFIQ is installed). Empty in default mode. ``sort_options`` already
    # excludes them; the client hides the matching filters and disables their weights.
    unavailable_metrics: list[str] = []
    # Extended-IQA score columns (``qrealign_score``, ``deqa_score``, ``aesthetic_v25``)
    # that at least one photo carries, i.e. whose model has run on this library. The
    # client shows "Not computed" for a NULL score only for these and hides the row otherwise.
    populated_scores: list[str] = []
    # Default merge-suggestion threshold of the active face-recognition model
    # (``face_clustering.thresholds_by_model``); absent when the model has no entry.
    face_merge_threshold: Optional[float] = None
    quality_levels: list[tuple[str, str]]
    type_labels: dict[str, str]
    defaults: dict[str, Any]
    pagination: dict[str, Any]
    display: dict[str, Any]
    badges: dict[str, Any]
    clipping: dict[str, Any]
    features: dict[str, Any]
    quality_thresholds: dict[str, Any]
    social_export: SocialExportPresets
    cull_styles: list[CullStyleOption] = []
    cull: CullCapabilities
    moment_confidence_min: Any
    notification_duration_ms: Any
    place_search_enabled: bool
    search_threshold_default: float
    translation_target_language: str
    is_multi_user: bool
    edition_enabled: bool
    edition_authenticated: bool
    render_migration: RenderMigrationStatus


class MapCluster(BaseModel):
    lat: float
    lng: float
    count: int
    representative_path: Optional[str] = None


class MapPhotoPoint(BaseModel):
    path: str
    lat: float
    lng: float
    aggregate: Optional[float] = None
    filename: Optional[str] = None
    date_taken: Optional[str] = None
    category: Optional[str] = None


class PhotoMapResponse(BaseModel):
    """Clustered locations at low zoom, individual points at high zoom -- never both."""

    clusters: list[MapCluster] = []
    photos: list[MapPhotoPoint] = []


class PhotoMapCountResponse(BaseModel):
    count: int


class PhotoSearchResponse(BaseModel):
    """Semantic/text search results.

    ``error`` is only present on the disabled-feature and exception paths;
    it must stay optional or a normal successful search would 500.
    """

    photos: list[Photo] = []
    total: int = 0
    query: str
    error: Optional[str] = None


class TimelineDateEntry(BaseModel):
    # SQLite's DATE() returns NULL for a malformed EXIF date ('2026:13:45',
    # or a non-zero-padded '2026:6:5'), so one corrupt file in a library must
    # not fail the whole year's calendar.
    date: Optional[str] = None
    count: int
    hero_photo_path: Optional[str] = None


class TimelineDatesResponse(BaseModel):
    dates: list[TimelineDateEntry] = []


class TimelineYearEntry(BaseModel):
    year: str
    count: int
    hero_photo_path: Optional[str] = None


class TimelineYearsResponse(BaseModel):
    years: list[TimelineYearEntry] = []


class TimelineMonthEntry(BaseModel):
    month: str
    count: int
    hero_photo_path: Optional[str] = None


class TimelineMonthsResponse(BaseModel):
    months: list[TimelineMonthEntry] = []
