"""Pydantic models for gallery endpoints."""

from pydantic import BaseModel, Field
from typing import Optional

from api.models.common import PaginationEnvelope


class PhotoPerson(BaseModel):
    id: int
    name: str


class Photo(BaseModel):
    """A photo row exactly as the gallery endpoints put it on the wire.

    Every column-backed field carries the SQLite affinity of its column in
    ``db/schema.py``, never the type its name suggests. ``shutter_speed`` is a
    TEXT column that reads back as the string ``'0.0125'``, and the flags are
    0/1 integers because SQLite has no boolean. Declaring either as what it
    means rather than what it is makes Pydantic coerce the value and silently
    change the wire.

    The field set is a SUPERSET of everything ``build_photo_select_columns``
    can emit, because ``response_model`` filters: a column absent here is a
    column dropped from the response. ``tests/test_response_models.py`` pins
    that against ``PHOTO_BASE_COLS`` and ``PHOTO_OPTIONAL_COLS``.

    The trailing fields are computed by the handlers rather than selected.
    ``top_picks_score``, ``learned_score`` and ``similarity`` are conditional --
    only the request that sorts or filters by them carries them -- so they must
    stay optional or the requests that do not trigger them would 500.
    """

    path: str
    filename: Optional[str] = None
    date_taken: Optional[str] = None
    camera_model: Optional[str] = None
    lens_model: Optional[str] = None
    iso: Optional[int] = None
    f_stop: Optional[float] = None
    shutter_speed: Optional[str] = None
    focal_length: Optional[float] = None
    aesthetic: Optional[float] = None
    face_count: Optional[int] = None
    face_quality: Optional[float] = None
    eye_sharpness: Optional[float] = None
    face_sharpness: Optional[float] = None
    face_ratio: Optional[float] = None
    tech_sharpness: Optional[float] = None
    color_score: Optional[float] = None
    exposure_score: Optional[float] = None
    comp_score: Optional[float] = None
    isolation_bonus: Optional[float] = None
    is_blink: Optional[int] = None
    phash: Optional[str] = None
    is_burst_lead: Optional[int] = None
    aggregate: Optional[float] = None
    category: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    histogram_spread: Optional[float] = None
    mean_luminance: Optional[float] = None
    power_point_score: Optional[float] = None
    shadow_clipped: Optional[int] = None
    highlight_clipped: Optional[int] = None
    is_silhouette: Optional[int] = None
    is_group_portrait: Optional[int] = None
    leading_lines_score: Optional[float] = None
    channel_clip_shadow_pct: Optional[float] = None
    channel_clip_highlight_pct: Optional[float] = None
    face_confidence: Optional[float] = None
    is_monochrome: Optional[int] = None
    mean_saturation: Optional[float] = None
    dynamic_range_stops: Optional[float] = None
    noise_sigma: Optional[float] = None
    contrast_score: Optional[float] = None
    tags: Optional[str] = None
    composition_pattern: Optional[str] = None
    quality_score: Optional[float] = None
    topiq_score: Optional[float] = None
    aesthetic_iaa: Optional[float] = None
    face_quality_iqa: Optional[float] = None
    liqe_score: Optional[float] = None
    qrealign_score: Optional[float] = None
    aesthetic_v25: Optional[float] = None
    deqa_score: Optional[float] = None
    subject_sharpness: Optional[float] = None
    subject_prominence: Optional[float] = None
    subject_placement: Optional[float] = None
    bg_separation: Optional[float] = None
    star_rating: Optional[int] = None
    is_favorite: Optional[int] = None
    is_rejected: Optional[int] = None
    duplicate_group_id: Optional[int] = None
    is_duplicate_lead: Optional[int] = None
    burst_group_id: Optional[int] = None
    caption: Optional[str] = None
    caption_translated: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    dominant_hue: Optional[float] = None
    color_temp: Optional[str] = None
    form_symmetry: Optional[float] = None
    form_balance: Optional[float] = None
    form_edge_entropy: Optional[float] = None
    form_fractal: Optional[float] = None
    color_harmony: Optional[float] = None
    narrative_moment: Optional[str] = None
    narrative_moment_confidence: Optional[float] = None
    junk_kind: Optional[str] = None
    sequence_group_id: Optional[int] = None
    sequence_kind: Optional[str] = None
    sequence_ev_offset: Optional[float] = None
    image_aspect: Optional[float] = None
    sequence_override: Optional[str] = None
    sequence_override_pending: Optional[int] = None
    date_formatted: Optional[str] = None
    tags_list: list[str] = []
    persons: list[PhotoPerson] = []
    unassigned_faces: Optional[int] = None
    top_picks_score: Optional[float] = None
    learned_score: Optional[float] = None
    similarity: Optional[float] = None

    model_config = {'from_attributes': True}


class HiddenSummary(BaseModel):
    """How many rows the gallery's hide toggles removed from this page's count."""

    total: int
    blinks: int
    bursts: int
    duplicates: int
    brackets: int
    panoramas: int


class PhotosResponse(PaginationEnvelope):
    """The gallery listing.

    Both ``total`` and ``total_pages`` are on the wire: the gallery store reads
    ``total``, junk-sweep reads ``total_pages``. Neither may be dropped.
    """

    photos: list[Photo]
    sort_col: str
    hidden_summary: Optional[HiddenSummary] = None


# --- Gallery query parameters ---

class GalleryParams(BaseModel):
    """Typed gallery filter parameters.

    All fields default to empty string to match current behavior where
    unset params are treated as empty strings by _build_gallery_where.
    """
    page: int = 1
    per_page: int = Field(default=64, ge=1, le=500)
    sort: str = ''
    dir: str = ''
    camera: str = ''
    lens: str = ''
    quality: str = ''
    type: str = ''
    hide_blinks: str = '0'
    hide_bursts: str = '0'
    hide_duplicates: str = '0'
    hide_brackets: str = '0'
    hide_panoramas: str = '0'
    burst_only: str = ''
    no_blink: str = ''
    search: str = ''
    tag: str = ''
    person: str = ''
    # Score ranges
    min_score: str = ''
    max_score: str = ''
    min_aesthetic: str = ''
    max_aesthetic: str = ''
    min_sharpness: str = ''
    max_sharpness: str = ''
    min_exposure: str = ''
    max_exposure: str = ''
    min_face_count: str = ''
    max_face_count: str = ''
    min_face_ratio: str = ''
    max_face_ratio: str = ''
    min_face_quality: str = ''
    max_face_quality: str = ''
    min_eye_sharpness: str = ''
    max_eye_sharpness: str = ''
    min_face_sharpness: str = ''
    max_face_sharpness: str = ''
    min_face_confidence: str = ''
    max_face_confidence: str = ''
    # EXIF ranges
    min_iso: str = ''
    max_iso: str = ''
    min_aperture: str = ''
    max_aperture: str = ''
    min_focal_length: str = ''
    max_focal_length: str = ''
    # Date filters
    date_from: str = ''
    date_to: str = ''
    # Content flags
    is_monochrome: str = ''
    category: str = ''
    narrative_moment: str = ''
    junk_kind: str = ''         # exact kind, or 'any' for any junk
    sequence_override: str = '' # any | suppressed | forced (pending panorama corrections)
    # Color facet (opt-in extraction, always-on filter)
    color_temp: str = ''        # warm | cool | neutral
    hue_bucket: str = ''        # red | orange | yellow | green | cyan | blue | purple | magenta
    # Quality tier (on-the-fly, derived from aggregate thresholds; no schema column)
    quality_tier: str = ''      # excellent | good | fair | poor
    min_aggregate: str = ''
    is_silhouette: str = ''
    require_tags: str = ''
    exclude_tags: str = ''
    exclude_art: str = ''
    top_picks_filter: str = ''
    # Preferences
    min_rating: str = ''
    favorites_only: str = ''
    hide_rejected: str = ''
    show_rejected: str = ''
    # Extended scores
    min_dynamic_range: str = ''
    max_dynamic_range: str = ''
    min_contrast: str = ''
    max_contrast: str = ''
    min_noise: str = ''
    max_noise: str = ''
    min_color: str = ''
    max_color: str = ''
    min_composition: str = ''
    max_composition: str = ''
    min_isolation: str = ''
    max_isolation: str = ''
    min_luminance: str = ''
    max_luminance: str = ''
    min_histogram_spread: str = ''
    max_histogram_spread: str = ''
    # Per-channel clipping (percent of pixels, worst of R/G/B). A row that was
    # never measured is NULL and is excluded by either bound -- unknown is not
    # clean, so it must not answer a "show me clipped photos" filter either way.
    min_channel_clip_shadow: str = ''
    max_channel_clip_shadow: str = ''
    min_channel_clip_highlight: str = ''
    max_channel_clip_highlight: str = ''
    min_power_point: str = ''
    max_power_point: str = ''
    min_leading_lines: str = ''
    max_leading_lines: str = ''
    min_quality_score: str = ''
    max_quality_score: str = ''
    min_saturation: str = ''
    max_saturation: str = ''
    min_star_rating: str = ''
    max_star_rating: str = ''
    min_topiq: str = ''
    max_topiq: str = ''
    composition_pattern: str = ''
    album_id: str = ''
    # GPS
    gps_lat: str = ''
    gps_lng: str = ''
    gps_radius_km: str = ''
    # Supplementary IQA
    min_aesthetic_iaa: str = ''
    max_aesthetic_iaa: str = ''
    min_face_quality_iqa: str = ''
    max_face_quality_iqa: str = ''
    min_liqe: str = ''
    max_liqe: str = ''
    # Extended IQA tier (config-gated; columns NULL unless iqa_extended is enabled)
    min_qrealign: str = ''
    max_qrealign: str = ''
    min_aesthetic_v25: str = ''
    max_aesthetic_v25: str = ''
    min_deqa: str = ''
    max_deqa: str = ''
    # Saliency
    min_subject_sharpness: str = ''
    max_subject_sharpness: str = ''
    min_subject_prominence: str = ''
    max_subject_prominence: str = ''
    min_subject_placement: str = ''
    max_subject_placement: str = ''
    min_bg_separation: str = ''
    max_bg_separation: str = ''
    # Narrative moment confidence (posterior 0..1)
    min_moment_confidence: str = ''
    max_moment_confidence: str = ''
    # Path
    path_prefix: str = ''
    # Set scope (photo-detail "open this set in the gallery"). Ephemeral: never
    # round-tripped through the URL, because sequence_group_id is renumbered
    # from 1 on every detection pass -- see gallery-filters.util.ts.
    sequence_group_id: str = ''
    sequence_kind: str = ''
    burst_group_id: str = ''
    duplicate_group_id: str = ''

    model_config = {'extra': 'ignore'}
