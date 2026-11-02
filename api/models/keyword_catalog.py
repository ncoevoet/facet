"""Exact manual keyword identities and captured assignment management."""

from pydantic import BaseModel, ConfigDict, Field


class KeywordCatalogItem(BaseModel):
    tag: str
    count: int
    typed: int
    imported: int
    unrecorded: int


class KeywordCatalogResponse(BaseModel):
    items: list[KeywordCatalogItem]
    total: int
    next_after: str | None


class KeywordChangeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: str = Field(min_length=1, max_length=64)
    target: str | None = Field(default=None, min_length=1, max_length=64)


class KeywordChangePreview(BaseModel):
    source: str
    target: str | None
    paths: list[str]
    renamed: int
    merged: int
    ai_matches: int
    removed: int
    preview_token: str
    expires_at: int


class KeywordChangeApply(KeywordChangeRequest):
    preview_token: str = Field(min_length=1, max_length=2048)


class KeywordChangeResult(BaseModel):
    source: str
    target: str | None
    changed: int
