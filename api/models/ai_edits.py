"""Request and response models for AI edits (``api/routers/ai_edits.py``)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

AiEditPath = Field(min_length=1, max_length=4096)


class AiEditImport(BaseModel):
    """Bring a file an AI tool made into the library, beside the photo it was made from."""

    original_path: str = AiEditPath
    source_file: str = AiEditPath
    mode: Literal['move', 'copy']
    tool: str = Field(min_length=1, max_length=64)
    model: Optional[str] = Field(default=None, max_length=200)
    note: Optional[str] = Field(default=None, max_length=1000)
    # A few words on what changed; stored on the edit as the manual tag "ai: <tag>".
    tag: Optional[str] = Field(default=None, max_length=64)


class AiEditScan(BaseModel):
    started: bool
    # Why no scan started (scanning off, another job running); the edit shows after the next scan.
    detail: Optional[str] = None


class AiEditImportResponse(BaseModel):
    edit_path: str
    revision: int
    # The manual tag the edit gets once scanned ("ai: ..."), or None.
    tag: Optional[str] = None
    mode: Literal['move', 'copy']
    # False only for a move whose source could not be deleted after the verified copy.
    source_removed: bool
    scan: AiEditScan


class AiEdit(BaseModel):
    edit_path: str
    source_path: str
    tool: str
    model: Optional[str] = None
    note: Optional[str] = None
    tag: Optional[str] = None
    revision: int
    created_at: Optional[str] = None


class AiEditsResponse(BaseModel):
    """For one photo: the original it was made from, if it is an edit, and its own scanned edits."""

    edit_of: Optional[AiEdit] = None
    edits: list[AiEdit]
