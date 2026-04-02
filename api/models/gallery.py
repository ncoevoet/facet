"""Pydantic models for gallery endpoints."""

from pydantic import BaseModel, Field
from typing import Optional


class PhotoPerson(BaseModel):
    id: int
    name: str


class Photo(BaseModel):
    path: str
    filename: Optional[str] = None
    date_taken: Optional[str] = None
    date_formatted: Optional[str] = None
    camera_model: Optional[str] = None
    lens_model: Optional[str] = None
    iso: Optional[int] = None
    f_stop: Optional[float] = None
    shutter_speed: Optional[float] = None
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
    aggregate: Optional[float] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    tags_list: list[str] = []
    composition_pattern: Optional[str] = None
    is_blink: Optional[int] = None
    is_burst_lead: Optional[int] = None
    is_monochrome: Optional[int] = None
    noise_sigma: Optional[float] = None
    contrast_score: Optional[float] = None
    dynamic_range_stops: Optional[float] = None
    mean_saturation: Optional[float] = None
    mean_luminance: Optional[float] = None
    histogram_spread: Optional[float] = None
    power_point_score: Optional[float] = None
    leading_lines_score: Optional[float] = None
    quality_score: Optional[float] = None
    star_rating: Optional[int] = None
    is_favorite: Optional[int] = None
    is_rejected: Optional[int] = None
    duplicate_group_id: Optional[int] = None
    is_duplicate_lead: Optional[int] = None
    top_picks_score: Optional[float] = None
    persons: list[PhotoPerson] = []
    unassigned_faces: int = 0

    model_config = {'from_attributes': True}


class GalleryResponse(BaseModel):
    photos: list[dict]  # Using dict for flexibility with optional columns
    page: int
    total_pages: int
    total_count: int
    has_more: bool
    sort_col: str


class TypeCountItem(BaseModel):
    id: str
    label: str
    count: int


class TypeCountsResponse(BaseModel):
    types: list[TypeCountItem]


class SimilarPhoto(BaseModel):
    path: str
    filename: Optional[str] = None
    similarity: float
    breakdown: dict
    aggregate: Optional[float] = None
    aesthetic: Optional[float] = None
    date_taken: Optional[str] = None


class SimilarPhotosResponse(BaseModel):
    source: str
    weights: dict
    similar: list[SimilarPhoto]


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
    # Saliency
    min_subject_sharpness: str = ''
    max_subject_sharpness: str = ''
    min_subject_prominence: str = ''
    max_subject_prominence: str = ''
    min_subject_placement: str = ''
    max_subject_placement: str = ''
    min_bg_separation: str = ''
    max_bg_separation: str = ''
    # Path
    path_prefix: str = ''

    model_config = {'extra': 'ignore'}
