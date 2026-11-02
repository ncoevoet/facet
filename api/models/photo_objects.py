"""Pydantic models for user-marked objects (labelled boxes on a photo)."""

from pydantic import BaseModel, Field, field_validator

# A box narrower or shorter than this (as a fraction of the frame) is a stray click.
MIN_OBJECT_SIDE = 0.005


class PhotoObjectCreate(BaseModel):
    """One labelled box. ``box`` is ``[x1, y1, x2, y2]``, normalised to the upright frame."""

    path: str
    label: str
    box: list[float] = Field(min_length=4, max_length=4)

    @field_validator('box')
    @classmethod
    def _valid_box(cls, box: list[float]) -> list[float]:
        x1, y1, x2, y2 = box
        if not all(0.0 <= v <= 1.0 for v in box):
            raise ValueError('box corners must lie within the frame (0 to 1)')
        if x2 - x1 < MIN_OBJECT_SIDE or y2 - y1 < MIN_OBJECT_SIDE:
            raise ValueError('box must have x1 < x2 and y1 < y2')
        return box


class PhotoObject(BaseModel):
    id: int
    label: str
    box: list[float]


class PhotoObjectsResponse(BaseModel):
    objects: list[PhotoObject]


class PhotoObjectDelete(BaseModel):
    success: bool
    removed: bool
