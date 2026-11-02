"""Reviewed catalog identity changes, separate from file metadata writes."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CatalogPath = Annotated[str, Field(min_length=1, max_length=32768)]


class LogicalAssetChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['create', 'primary', 'dissolve']
    paths: list[CatalogPath] = Field(default_factory=list, max_length=16)
    primary_path: CatalogPath | None = None
    asset_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    revision: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode='after')
    def explicit_target(self):
        if self.operation == 'create':
            if (not 2 <= len(self.paths) <= 16 or len(set(self.paths)) != len(self.paths)
                    or self.primary_path not in self.paths or self.asset_id is not None or self.revision is not None):
                raise ValueError('Choose distinct indexed files and an explicit primary')
        elif (self.paths or self.asset_id is None or self.revision is None
              or (self.operation == 'primary') != (self.primary_path is not None)):
            raise ValueError('Choose a current logical photo and revision')
        return self


class LogicalAssetApply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    change: LogicalAssetChange
    preview_token: str = Field(max_length=2048)
    acknowledge_review_conflicts: bool = False


class LogicalAssetMember(BaseModel):
    path: str
    name: str
    star_rating: int | None
    is_kept: bool
    is_rejected: bool
    is_favorite: bool


class LogicalAssetPreview(BaseModel):
    preview_token: str
    expires_at: int
    operation: Literal['create', 'primary', 'dissolve']
    primary_path: str | None
    members: list[LogicalAssetMember]
    review_conflicts: list[Literal['star_rating', 'is_kept', 'is_rejected', 'is_favorite']]
    preserves_file_metadata: Literal[True] = True


class LogicalAssetResult(BaseModel):
    asset_id: str
    revision: int | None
    dissolved: bool
