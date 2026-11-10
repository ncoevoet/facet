"""Private progress receipts for a bounded sidecar export."""
import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SidecarJobStatus(BaseModel):
    id: str
    state: Literal['running', 'completed', 'cancelled', 'failed', 'interrupted']
    started_at: float
    operation: Literal['sidecars', 'copy', 'symlink'] = 'sidecars'
    phase: Literal['validating', 'writing', 'finished'] = 'writing'
    confirmed: bool = False
    total: int = Field(ge=0, le=40000)
    processed: int = Field(ge=0, le=40000)
    written: int = Field(ge=0, le=40000)
    skipped: int = Field(ge=0, le=40000)
    errors: int = Field(ge=0, le=40000)
    first_error: str | None = None
    first_error_code: Literal['metadata_repair', 'write_failed', 'exiftool_upgrade', 'stopped', 'preview_changed'] | None = None
    cancel_requested: bool = False


    @model_validator(mode='after')
    def consistent_counts(self):
        if self.operation == 'sidecars' and self.total > 10000:
            raise ValueError('Sidecar exports are capped at 10000 photos')
        if self.processed > self.total or self.written + self.skipped + self.errors != self.processed:
            raise ValueError('Export progress counts are inconsistent')
        return self


class SidecarJobRecord(SidecarJobStatus):
    """On-disk worker state; validate before ordering or doing retry arithmetic."""
    model_config = ConfigDict(strict=True)

    owner: str | None
    retry: list[int] = Field(max_length=40000)

    @model_validator(mode='after')
    def valid_private_record(self):
        if str(UUID(self.id)) != self.id or not math.isfinite(self.started_at):
            raise ValueError('Invalid export receipt identity/timestamp')
        if (any(index < 0 or index >= self.processed for index in self.retry)
                or len(set(self.retry)) != len(self.retry)
                or len(self.retry) != self.skipped + self.errors):
            raise ValueError('Invalid export retry indices')
        return self


class SidecarJobPlan(BaseModel):
    """Immutable private selection, written by the admitted worker."""
    model_config = ConfigDict(strict=True)

    owner: str | None
    paths: list[str] = Field(max_length=40000)
    overwrite: bool
    confirmation_digest: str | None = None
    operation: Literal['sidecars', 'copy', 'symlink'] = 'sidecars'
    confirmation: dict | None = None
    request: dict | None = None

    @model_validator(mode='after')
    def bounded_operation(self):
        if self.operation == 'sidecars' and len(self.paths) > 10000:
            raise ValueError('Sidecar exports are capped at 10000 photos')
        return self
