"""Captured export preview; confirmation is a separate guarded operation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from api.models.provenance import PhotoProvenance


class ExportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    paths: list[str] | None = Field(default=None, min_length=1, max_length=10000)
    filters: dict | None = None
    album_id: int | None = Field(default=None, ge=1)
    exclude: list[str] = Field(default_factory=list, max_length=1000)
    mode: Literal['sidecars', 'copy', 'symlink'] = 'sidecars'
    target_dir: str | None = None
    overwrite: bool = False
    include_companions: bool = False
    source_job: str | None = Field(default=None, pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

    @model_validator(mode='after')
    def one_scope(self):
        if sum(value is not None for value in (self.paths, self.filters, self.album_id)) != 1:
            raise ValueError('Choose exactly one path, filter or album scope')
        if self.mode != 'sidecars' and not self.target_dir:
            raise ValueError('A destination is required for copy/symlink')
        if self.mode == 'sidecars' and (self.target_dir or self.include_companions):
            raise ValueError('Sidecar writing uses each photo location, without companion copying')
        return self


class ExportFaceRegion(BaseModel):
    name: str
    x: float
    y: float
    w: float
    h: float
    image_width: int
    image_height: int


class ExportMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid')

    star_rating: int
    is_favorite: bool
    is_rejected: bool
    is_kept: bool
    date_taken: str | None
    date_manually_set: bool
    gps_manually_set: bool
    gps_latitude: float | None
    gps_longitude: float | None
    tags: list[str]
    ai_tags: list[str]
    manual_tags: list[str]
    hierarchy_paths: list[str] = Field(default_factory=list)
    caption: str
    category: str
    person_names: list[str]
    regions: list[ExportFaceRegion]
    aggregate: float | None
    xmp_rating: int
    xmp_label: str
    review_decision: Literal['kept', 'rejected', 'undecided']
    manual_date: str | None
    gps_state: Literal['set', 'cleared'] | None
    review_scope: Literal['personal', 'catalog']
    provenance: PhotoProvenance
    keywords: list[str]
    face_regions_supported: bool


class ExportPreviewItem(BaseModel):
    photo_path: str
    source_name: str
    target_name: str | None
    state: Literal['ready', 'missing']
    companion: bool
    target_exists: bool
    metadata: ExportMetadata | None = None


class ExportPreviewResponse(BaseModel):
    preview_token: str
    receipt_id: str
    expires_at: int
    mode: Literal['sidecars', 'copy', 'symlink']
    target_dir: str | None
    selected_paths: list[str]
    items: list[ExportPreviewItem]
    ready: int
    missing: int
    writer: Literal['exiftool', 'xml'] | None
    request: ExportPreviewRequest


class ExportApplyRequest(ExportPreviewRequest):
    preview_token: str = Field(min_length=1, max_length=4096)
    selected_paths: list[str] = Field(min_length=1, max_length=10000)
