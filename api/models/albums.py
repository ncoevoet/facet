"""Pydantic response models for albums, proofing, capsules, memories,
merge-suggestions and scenes endpoints."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from api.models.common import PaginationEnvelope
from api.models.gallery import Photo, SharedPhoto


class AlbumPhotosResponse(PaginationEnvelope):
    """Paginated photo listing for one album (owner view)."""

    photos: list[Photo]


class PhotoAlbum(BaseModel):
    """One album a photo belongs to, as listed in the photo info panel."""

    id: int
    name: str
    is_smart: bool


class Album(BaseModel):
    """An album's own metadata, as embedded in the shared-album view."""

    id: int
    name: str
    description: Optional[str] = None
    cover_photo_path: Optional[str] = None
    preview_revision: Optional[str] = None
    is_smart: bool
    smart_filter_json: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    is_shared: bool
    scoring_context: Optional[str] = None


class SharedAlbum(Album):
    """Recipient album projection never includes native cover paths or saved rules."""

    cover_photo_path: Optional[str] = Field(None, exclude=True)
    smart_filter_json: Optional[str] = Field(None, exclude=True)
    cover_asset_id: Optional[str] = None


class AlbumFilterOptionItem(BaseModel):
    value: str
    count: int


class AlbumFilterOptions(BaseModel):
    """Filter dropdown options scoped to one manual album's photos."""

    cameras: list[AlbumFilterOptionItem] = []
    lenses: list[AlbumFilterOptionItem] = []
    tags: list[AlbumFilterOptionItem] = []
    patterns: list[AlbumFilterOptionItem] = []
    categories: list[AlbumFilterOptionItem] = []


class SharedAlbumPolicy(BaseModel):
    """Capabilities of this public link, not account edition rights or a frozen delivery."""

    membership: Literal['manual', 'smart']
    membership_can_change: bool
    downloads: Literal['album_member_original']
    photo_metadata: bool
    native_paths: bool
    manual_tags: bool
    saved_rules: bool
    password_protected: bool
    expires_at: Optional[str] = None
    proofing: bool


class SharedAlbumResponse(PaginationEnvelope):
    """The anonymous share-token view of an album.

    Carries the same photo listing shape as the owner-facing album-photos
    endpoint plus the album's own metadata -- it must never widen to include
    anything the owner endpoints do not also expose. ``sort_options_grouped``
    and ``filter_options`` are only populated by the handler for a manual
    album's first page; ``response_model_exclude_unset`` is what keeps them
    off the wire on every other request rather than sending them as null.
    """

    photos: list[SharedPhoto]
    album: SharedAlbum
    effective_sort: str
    effective_sort_direction: str
    proofing_enabled: bool
    sharing_policy: SharedAlbumPolicy
    # Same object as /api/config's, which types it as passthrough. Narrowing it
    # here would drop any key an operator adds to a viewer.sort_options entry.
    sort_options_grouped: Optional[dict[str, Any]] = None
    filter_options: Optional[AlbumFilterOptions] = None


class AlbumPick(BaseModel):
    path: str
    picked: bool
    comment: Optional[str] = None
    client_name: Optional[str] = None
    updated_at: Optional[str] = None


class AlbumPicksResponse(BaseModel):
    picks: list[AlbumPick]
    count: int


class Capsule(BaseModel):
    """A capsule's summary metadata -- never its member photo paths.

    ``_capsule_summary`` in ``api/routers/capsules.py`` is the single place
    that trims a full capsule dict down to this shape for both the list and
    detail routes.
    """

    type: str
    id: str
    title: str
    title_key: str = ''
    title_params: dict[str, str] = {}
    subtitle: str
    cover_photo_path: Optional[str] = None
    preview_revision: Optional[str] = None
    photo_count: int
    icon: str


class CapsulesResponse(BaseModel):
    capsules: list[Capsule]
    total: int
    page: int
    per_page: int
    has_more: bool


class CapsulePhotosResponse(BaseModel):
    photos: list[Photo]
    capsule: Capsule


class MemoriesCheckResponse(BaseModel):
    has_memories: bool


class MemoryYearGroup(BaseModel):
    year: str
    photos: list[Photo]
    total_count: int


class MemoriesResponse(BaseModel):
    years: list[MemoryYearGroup]
    has_memories: bool
    date: str


class MergeSuggestionPerson(BaseModel):
    id: int
    name: Optional[str] = None
    face_count: int


class MergeSuggestion(BaseModel):
    person1: MergeSuggestionPerson
    person2: MergeSuggestionPerson
    similarity: float


class MergeSuggestionsResponse(BaseModel):
    suggestions: list[MergeSuggestion]
    # The similarity threshold the list was computed at: the caller's, or the active
    # embedding model's configured default when none was sent. The client seeds its
    # slider from it, so it never has to know a per-model value.
    threshold: float
    # More eligible, undismissed pairs matched than the response can hold.
    truncated: bool


class ScenePhoto(BaseModel):
    """The lightweight photo shape scenes emit -- not a full ``Photo`` row."""

    path: str
    preview_revision: Optional[str] = None
    filename: Optional[str] = None
    aggregate: Optional[float] = None
    date_taken: Optional[str] = None


class Scene(BaseModel):
    """One chronological scene. ``photos`` is omitted by the handler when
    ``summary=true`` is requested, so it must stay optional."""

    scene_id: int
    start: Optional[str] = None
    end: Optional[str] = None
    count: int
    best_path: str
    photos: Optional[list[ScenePhoto]] = None
    moment: Optional[str] = None
    moment_confidence: Optional[float] = None


class ScenesResponse(BaseModel):
    scenes: list[Scene]
    total: int
    page: int
    per_page: int
    total_pages: int
