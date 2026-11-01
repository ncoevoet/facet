"""Pydantic models for the manual (user-authored) tag write endpoints."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from api.routers.faces import BatchPhotoRequest


class ManualTagRequest(BaseModel):
    """One tag on one photo. ``tag`` is normalized server-side (422 when invalid)."""

    path: str
    tag: str


class ManualTagResponse(BaseModel):
    success: bool
    tag: str
    skipped_existing: bool = False


class ManualTagDeleteResponse(BaseModel):
    success: bool
    tag: str
    removed: bool


class BatchManualTagRequest(BatchPhotoRequest):
    """Add/delete one tag, replace the manual set, or explicitly clear it."""

    tag: str | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    action: Literal['add', 'delete', 'replace', 'clear']

    @model_validator(mode='after')
    def _operation_fields(self):
        if self.action in ('add', 'delete'):
            if self.tag is None or self.tags is not None:
                raise ValueError('add/delete requires one tag and no tag list')
        elif self.action == 'replace':
            if self.tag is not None or not self.tags:
                raise ValueError('replace requires a non-empty tag list; use clear to remove all manual tags')
        elif self.tag is not None or self.tags is not None:
            raise ValueError('clear does not accept tag values')
        return self


class BatchManualTagResponse(BaseModel):
    success: bool
    count: int
