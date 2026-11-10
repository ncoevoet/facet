"""Physical file candidates, not manual-stack membership or an export plan."""

from typing import Literal

from pydantic import BaseModel


class RelatedFile(BaseModel):
    name: str
    kind: Literal['photo', 'raw', 'jpeg', 'xmp_full', 'xmp_basename', 'xmp_fallback']
    state: Literal['available', 'missing', 'unavailable', 'link']
    indexed: bool
    raw_download: bool = False


class RelatedFilesResponse(BaseModel):
    files: list[RelatedFile]
    inventory_state: Literal['checked', 'unavailable']
    indexed_images_only: bool
    multiple_raw_candidates: bool
    basename_sidecar_unverified: bool
