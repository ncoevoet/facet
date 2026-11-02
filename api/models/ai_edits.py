"""Request and response models for AI edits (``api/routers/ai_edits.py``)."""

from typing import Optional

from pydantic import BaseModel, Field, model_validator

AiEditPath = Field(min_length=1, max_length=4096)
# The largest edit an import accepts, decoded. base64 spends 4 characters per 3 bytes.
MAX_EDIT_BYTES = 50 * 1024 * 1024
_MAX_IMAGE_DATA_CHARS = (MAX_EDIT_BYTES + 2) // 3 * 4


class AiEditImport(BaseModel):
    """Bring an image an AI tool made into the library, beside the photo it was made from.

    The image comes as bytes, never as "take this path": exactly one of ``image_data`` (base64)
    or ``source_file`` (a file inside ``ai_edits.drop_dir``, read and left in place).
    """

    original_path: str = AiEditPath
    image_data: Optional[str] = Field(default=None, min_length=1, max_length=_MAX_IMAGE_DATA_CHARS)
    source_file: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    tool: str = Field(min_length=1, max_length=64)
    model: Optional[str] = Field(default=None, max_length=200)
    note: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode='after')
    def _one_image(self):
        if (self.image_data is None) == (self.source_file is None):
            raise ValueError('Send exactly one of image_data or source_file')
        return self


class AiEditScan(BaseModel):
    started: bool
    # Why no scan started (scanning off, another job running); the edit shows after the next scan.
    detail: Optional[str] = None


class AiEditImportResponse(BaseModel):
    edit_path: str
    revision: int
    scan: AiEditScan


class AiEdit(BaseModel):
    edit_path: str
    source_path: str
    tool: str
    model: Optional[str] = None
    note: Optional[str] = None
    revision: int
    created_at: Optional[str] = None


class AiEditsResponse(BaseModel):
    """For one photo: the original it was made from, if it is an edit, and its own scanned edits."""

    edit_of: Optional[AiEdit] = None
    edits: list[AiEdit]
