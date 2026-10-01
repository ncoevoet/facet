"""Pydantic models for the manual (user-authored) tag write endpoints."""

from typing import Literal

from pydantic import BaseModel

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
    """Add or remove one tag across a path list or a whole gallery view."""

    tag: str
    action: Literal['add', 'delete']


class BatchManualTagResponse(BaseModel):
    success: bool
    count: int
