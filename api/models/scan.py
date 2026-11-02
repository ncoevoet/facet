"""Pydantic models for scan, export, updates, i18n, folders and ranker endpoints."""

from typing import Optional

from pydantic import BaseModel, Field


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
    started_at: Optional[float] = None
    scope: Optional[str] = None


class RecomputeStatusResponse(BaseModel):
    """``GET /api/scan/recompute_status`` -- see ``ScanStatusResponse`` for why
    ``progress`` stays an untyped passthrough."""

    running: bool
    kind: Optional[str] = None
    progress: Optional[dict] = None
    exit_code: Optional[int] = None
    started_at: Optional[float] = None
    scope: Optional[str] = None


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
    preview_digest: Optional[str] = None
    thumbnail_paths: Optional[dict[str, str]] = Field(default=None,
        description="Dry-run disk file paths mapped to authorized library identities for thumbnail requests. Companions without their own entry may have no thumbnail.")
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


class PhotoDeleteResponse(BaseModel):
    """``POST /api/photo/delete`` -- see ``api.routers.export.api_photo_delete``
    for the invariants the fields carry.

    Per-path rather than per-count, unlike ``CullApplyResponse``: the request
    can mix visible and invisible paths, and ordinary frames with refused
    bracket leads, in one call, and the gallery's bulk surface needs to know
    WHICH path landed in which bucket to report a partial result ("3 deleted,
    1 refused") rather than an all-or-nothing outcome. ``sequence_siblings``
    is the one field kept per-path rather than per-count even though
    ``CullApplyResponse`` reports the same thing as a count: it is populated
    the same way -- every frame ``include_sequence_siblings`` pulled in by
    sharing a requested path's ``(sequence_kind, sequence_group_id)`` -- but
    named here so the caller can tell WHICH frames were added, matching this
    response's own per-path idiom.

    A trashed ``include_companions`` RAW/``.xmp`` that is itself a separate
    ``photos`` row is folded into ``deleted``, not a distinct bucket -- its
    file is gone the moment the trash succeeds, so it is exactly as deleted
    as any path the caller named directly. ``skipped`` mirrors
    ``CullApplyResponse``'s field of the same name: a path that was visible,
    in ``photos``, and not a refused bracket lead, but whose file could not
    be resolved on disk (already missing) -- landing in no other bucket.
    With ``remove_missing`` those same paths have their rows removed instead,
    and are reported in ``removed_missing`` rather than ``skipped``.
    """

    dry_run: bool
    would_trash: Optional[list[str]] = None
    deleted: list[str]
    not_found: list[str]
    not_visible: list[str]
    refused_bracket_lead: list[str]
    sequence_siblings: list[str]
    skipped: list[str]
    # Paths whose file was already missing from disk and whose row was removed
    # anyway (`remove_missing`), so the caller can tell a reconciled row from
    # a trashed one. Empty unless the flag was set.
    removed_missing: list[str]
    trashed: int
    errors: dict[str, str]


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
    preview_revision: Optional[str] = None


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
