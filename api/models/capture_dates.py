"""Capture date correction contracts."""
from pydantic import BaseModel, Field, field_validator

from api.routers.faces import BatchPhotoRequest


class CaptureDateRequest(BatchPhotoRequest):
    offset_seconds: int = Field(strict=True, ge=-31622400, le=31622400)

    @field_validator('offset_seconds')
    @classmethod
    def nonzero(cls, value: int) -> int:
        if value == 0:
            raise ValueError('Offset must be nonzero')
        return value


class CaptureDateApplyRequest(CaptureDateRequest):
    preview_token: str = Field(min_length=1, max_length=64)


class CaptureDateSample(BaseModel):
    path: str
    old_date: str
    new_date: str


class CaptureDatePreview(BaseModel):
    changed: int
    skipped: int
    samples: list[CaptureDateSample]
    preview_token: str


class CaptureDateReset(BaseModel):
    date_taken: str | None
    date_manually_set: int = 0
