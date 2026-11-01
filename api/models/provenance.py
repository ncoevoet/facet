"""Read-only current metadata authority, deliberately excluding private paths/actors."""

from typing import Literal

from pydantic import BaseModel


class ReviewFieldSource(BaseModel):
    field: Literal['star_rating', 'is_favorite', 'is_rejected', 'is_kept']
    value: int
    source: Literal['local', 'xmp', 'unrecorded']
    changed_at: str | None
    source_at: str | None


class ManualTagSource(BaseModel):
    tag: str
    source: Literal['user', 'xmp', 'unrecorded']


class PhotoProvenance(BaseModel):
    review_scope: Literal['personal', 'catalog']
    review: list[ReviewFieldSource]
    manual_tags: list[ManualTagSource]
    manual_tags_truncated: bool
    capture_date_override: bool
    gps_override: bool
