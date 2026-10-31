"""Explicit stack requests and revisioned organization responses."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.models.common import CoercedInt
from api.models.gallery import gallery_filter_keys


class StackMember(BaseModel):
    preview_revision: str | None = None
    path: str
    position: int


class PhotoStack(BaseModel):
    id: str
    revision: int
    cover_path: str
    members: list[StackMember]
    editable: bool


class CreateStack(BaseModel):
    paths: list[str] = Field(min_length=2, max_length=1000)
    cover_path: str


class UpdateStack(BaseModel):
    paths: list[str] = Field(max_length=1000)
    cover_path: str | None = None
    expected_revision: int = Field(gt=0)


class StackUndo(BaseModel):
    entry_id: int


class StackMutation(BaseModel):
    stack: PhotoStack | None
    undo: StackUndo | None


class StackRegroupPreviewRequest(BaseModel):
    selected_paths: list[str] = Field(min_length=2, max_length=1000)
    mode: Literal['combine', 'selected'] = 'combine'


class StackRegroupPreview(BaseModel):
    selected_paths: list[str]
    mode: Literal['combine', 'selected']
    paths: list[str]
    cover_path: str
    source_stacks: list[PhotoStack]
    unstacked_paths: list[str]
    affected_paths: list[str]
    expected_state: str


class StackRegroupApply(StackRegroupPreviewRequest):
    paths: list[str] = Field(min_length=2, max_length=1000)
    cover_path: str
    expected_state: str = Field(pattern='^[0-9a-fA-F]{64}$')


class StackRegroupMutation(StackMutation):
    affected_paths: list[str]
    changed: bool


class StackSuggestionsRequest(BaseModel):
    filters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    include_photos: bool = False

    @field_validator('filters')
    @classmethod
    def known_filters(cls, value):
        if value.keys() - gallery_filter_keys():
            raise ValueError('Unknown gallery filter')
        return value


class StackSuggestionPhoto(BaseModel):
    """Darkroom rows in detector order, with the caller's current marks."""
    path: str
    filename: str
    aggregate: float | None
    aesthetic: float | None
    tech_sharpness: float | None
    is_blink: CoercedInt
    is_burst_lead: CoercedInt
    date_taken: str | None
    burst_score: float
    eyes_open_score: float | None
    expression_score: float | None
    is_rejected: CoercedInt
    is_kept: CoercedInt
    is_favorite: CoercedInt
    star_rating: CoercedInt
    preview_revision: str | None


class StackSuggestion(BaseModel):
    key: str
    kind: Literal['duplicate', 'burst']
    group_id: int
    paths: list[str]
    cover_path: str
    photos: list[StackSuggestionPhoto] | None


class StackSuggestionDismissal(BaseModel):
    kind: Literal['duplicate', 'burst']
    paths: list[str] = Field(min_length=2, max_length=1000)


class StackSuggestionsResponse(BaseModel):
    suggestions: list[StackSuggestion]
