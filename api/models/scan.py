"""Pydantic models for scan, export, updates, i18n, folders and ranker endpoints."""

from typing import Optional

from pydantic import BaseModel


class ScanStartResponse(BaseModel):
    """``POST /api/scan/start`` success payload."""

    success: bool
    message: str
    directories: list[str]
    pid: int


class ScanStatusResponse(BaseModel):
    """``GET /api/scan/status`` -- a snapshot of ``_scan_state``.

    ``progress`` is the last ``@FACET_PROGRESS`` event parsed from the
    subprocess's stdout, an arbitrary JSON object whose keys vary by job
    phase, so it stays an untyped passthrough rather than a nested model.
    """

    running: bool
    directories: list[str]
    output: list[str]
    elapsed_seconds: Optional[float] = None
    exit_code: Optional[int] = None
    progress: Optional[dict] = None


class ScanStreamTokenResponse(BaseModel):
    """``GET /api/scan/stream_token`` success payload."""

    token: str


class ScanDirectoryEntry(BaseModel):
    path: str
    owner: str


class ScanDirectoriesResponse(BaseModel):
    """``GET /api/scan/directories`` success payload."""

    directories: list[ScanDirectoryEntry]


class LibraryJobStartResponse(BaseModel):
    """Success payload shared by the fixed-argv library jobs (``/detect_panoramas``,
    ``/recompute``) spawned through ``_spawn_fixed_library_job``."""

    success: bool
    message: str
    pid: int


class RecomputeStatusResponse(BaseModel):
    """``GET /api/scan/recompute_status`` -- see ``ScanStatusResponse`` for why
    ``progress`` stays an untyped passthrough."""

    running: bool
    kind: Optional[str] = None
    progress: Optional[dict] = None
    exit_code: Optional[int] = None


class CullApplyResponse(BaseModel):
    """``POST /api/cull/apply`` -- see ``api.routers.export.api_cull_apply`` for
    the invariants the fields carry.

    Exactly one of the ``would_*`` / count fields is present on any given
    response: the ``would_*`` list on a ``dry_run`` preview, the matching
    count on a real run. ``errors`` mirrors that split -- an empty list on a
    dry run (nothing was attempted), an attempt count on a real run.
    """

    action: str
    dry_run: bool
    would_copy: Optional[list[str]] = None
    would_move: Optional[list[str]] = None
    would_trash: Optional[list[str]] = None
    copied: Optional[int] = None
    moved: Optional[int] = None
    trashed: Optional[int] = None
    skipped: list[str]
    excluded_by_state: int
    not_visible: int
    matched: int
    sequence_siblings: int
    errors: int | list[str]


class UpdateCheckResponse(BaseModel):
    """``GET /api/updates/check`` -- matches ``client/src/app/app.ts``'s
    ``ReleaseCheck``, which the contract test already reads."""

    enabled: bool
    current: str
    latest: Optional[str] = None
    update_available: bool
    release_url: str


class LanguageEntry(BaseModel):
    code: str
    name: str


class LanguagesResponse(BaseModel):
    """``GET /api/i18n/languages`` success payload."""

    languages: list[LanguageEntry]
    default: str


class FolderEntry(BaseModel):
    name: str
    path: str
    photo_count: int
    cover_photo_path: Optional[str] = None


class FoldersResponse(BaseModel):
    """``GET /api/folders`` success payload."""

    folders: list[FolderEntry]
    has_direct_photos: bool


class RankerStatusResponse(BaseModel):
    """``GET /api/ranker/status`` success payload.

    The accuracy fields come from the last training run's ``stats_cache``
    snapshot and stay ``None`` until the ranker has trained at least once.
    """

    trained: bool
    gated: bool
    comparison_count: int
    coverage: float
    scored: int
    embedded: int
    cv_accuracy: Optional[float] = None
    baseline_accuracy: Optional[float] = None
    improvement_pp: Optional[float] = None
    updated_at: Optional[str] = None
