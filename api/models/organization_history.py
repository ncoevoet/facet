from typing import Literal
from pydantic import BaseModel


class OrganizationChange(BaseModel):
    path: str
    before: list[str | int | float | None]
    after: list[str | int | float | None]
    revision: int


class OrganizationEntry(BaseModel):
    id: int
    kind: Literal['gps', 'date', 'review']
    created_at: str
    part: int
    parts: int
    reverted: bool
    changes: list[OrganizationChange]


class OrganizationHistory(BaseModel):
    entries: list[OrganizationEntry]


class OrganizationRevert(BaseModel):
    changed: int
