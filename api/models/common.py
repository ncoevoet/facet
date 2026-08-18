"""Base classes shared by more than one module under ``api/models/``."""

from pydantic import BaseModel


class PaginationEnvelope(BaseModel):
    """The ``{page, per_page, total, total_pages, has_more}`` shape shared by
    ``PhotosResponse``, ``AlbumPhotosResponse`` and ``SharedAlbumResponse``.

    Other paginated responses have already drifted from this exact shape --
    ``CapsulesResponse`` drops ``total_pages``, ``ScenesResponse`` drops
    ``has_more``, ``BurstGroupsResponse``/``CullingGroupsResponse`` use
    ``total_groups`` instead of ``total`` -- and must not be forced onto it.
    """

    page: int
    per_page: int
    total: int
    total_pages: int
    has_more: bool
