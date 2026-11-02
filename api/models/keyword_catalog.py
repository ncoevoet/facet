"""Exact manual keyword identities and captured assignment management."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from db.keyword_hierarchy import keyword_node_id, normalize_path, normalize_segment


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


class KeywordTreeNode(BaseModel):
    id: str
    parent_id: str | None
    name: str
    segments: list[str]
    direct_count: int
    branch_count: int


class KeywordTreeResponse(BaseModel):
    nodes: list[KeywordTreeNode]


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


class HierarchyChangeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['assign', 'remove', 'create_assign', 'rename', 'move', 'delete_branch']
    node_id: str | None = Field(default=None, min_length=1, max_length=36)
    paths: list[str] | None = Field(default=None, min_length=1, max_length=10000)
    segments: list[str] | None = Field(default=None, min_length=1, max_length=16)
    name: str | None = Field(default=None, min_length=1, max_length=64)
    parent_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator('node_id', 'parent_id')
    @classmethod
    def valid_identity(cls, value):
        return keyword_node_id(value) if value is not None else None

    @field_validator('segments')
    @classmethod
    def valid_segments(cls, value):
        return normalize_path(value) if value is not None else None

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        return normalize_segment(value) if value is not None else None

    @model_validator(mode='after')
    def operation(self):
        if self.action == 'create_assign':
            valid = self.paths is not None and self.segments is not None and self.node_id is None and self.name is None and self.parent_id is None
        elif self.action in ('assign', 'remove'):
            valid = self.node_id is not None and self.paths is not None and self.segments is None and self.name is None and self.parent_id is None
        elif self.action == 'rename':
            valid = self.node_id is not None and self.name is not None and self.paths is None and self.segments is None and self.parent_id is None
        else:
            valid = self.node_id is not None and self.paths is None and self.segments is None and self.name is None
            if self.action == 'delete_branch':
                valid = valid and self.parent_id is None
        if not valid:
            raise ValueError('The operation requires exactly its own target and options')
        return self


class HierarchyChangePreview(BaseModel):
    request: HierarchyChangeRequest
    before_path: list[str] | None
    after_path: list[str] | None
    paths: list[str]
    new_assignments: int
    removed_assignments: int
    updated_assignments: int
    definition_change: bool | None  # Unknown entered paths never disclose hidden vocabulary existence.
    preview_token: str
    expires_at: int


class HierarchyChangeApply(HierarchyChangeRequest):
    preview_token: str = Field(min_length=1, max_length=2048)


class HierarchyChangeResult(BaseModel):
    success: bool
    node_id: str | None
    target_photos: int
    affected_photos: int
    changed_assignments: int
