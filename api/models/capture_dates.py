"""Capture date correction contracts."""
from pydantic import BaseModel, Field, field_validator, model_validator

from api.routers.faces import BatchPhotoRequest
from utils.capture_dates import parse_capture_date


class CaptureDateRequest(BatchPhotoRequest):
    offset_seconds: int | None = Field(default=None, strict=True, ge=-31622400, le=31622400)
    set_date: str | None = Field(default=None, strict=True, max_length=32)

    @field_validator('offset_seconds')
    @classmethod
    def nonzero(cls, value: int | None) -> int | None:
        if value == 0:
            raise ValueError('Offset must be nonzero')
        return value

    @field_validator('set_date')
    @classmethod
    def parseable(cls, value: str | None) -> str | None:
        if value is not None and parse_capture_date(value) is None:
            raise ValueError('Date must be YYYY:MM:DD HH:MM:SS or YYYY-MM-DD[T ]HH:MM:SS')
        return value

    @model_validator(mode='after')
    def exactly_one(self) -> 'CaptureDateRequest':
        if (self.offset_seconds is None) == (self.set_date is None):
            raise ValueError('Provide exactly one of offset_seconds or set_date')
        return self


class CaptureDateApplyRequest(CaptureDateRequest):
    preview_token: str = Field(min_length=1, max_length=64)


class CaptureDateSample(BaseModel):
    path: str
    old_date: str | None
    new_date: str


class CaptureDatePreview(BaseModel):
    changed: int
    skipped: int
    samples: list[CaptureDateSample]
    preview_token: str


class CaptureDateReset(BaseModel):
    date_taken: str | None
    date_manually_set: int = 0
