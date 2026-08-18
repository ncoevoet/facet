"""Pydantic response models for the comparison / tuning-config endpoints."""

from typing import Literal, Optional, Union

from pydantic import BaseModel


class NextPairResponse(BaseModel):
    """A pair of photos to compare, or ``error`` when none is available."""

    a: Optional[str] = None
    b: Optional[str] = None
    score_a: Optional[float] = None
    score_b: Optional[float] = None
    error: Optional[str] = None


class DownloadOption(BaseModel):
    type: Literal['original', 'darktable', 'raw']
    label: str
    profile: Optional[str] = None
    extension: Optional[str] = None


class DownloadOptionsResponse(BaseModel):
    options: list[DownloadOption] = []


class CategoryPriorityItem(BaseModel):
    name: str
    priority: Optional[Union[int, float]] = 100
    filters: Optional[dict] = {}


class CategoryPrioritiesResponse(BaseModel):
    categories: list[CategoryPriorityItem] = []


class ScoringContextItem(BaseModel):
    name: str
    label_key: Optional[str] = None
    promote: Optional[list[str]] = []
    excluded: Optional[list[str]] = []
    suggest_from_moments: Optional[list[str]] = []
    effective_order: list[str] = []


class ScoringContextsResponse(BaseModel):
    contexts: list[ScoringContextItem] = []


class ComparisonCategoryCount(BaseModel):
    """One row of ``SELECT category, COUNT(*) AS count ... GROUP BY category``."""

    category: str
    count: int


class ComparisonStatsResponse(BaseModel):
    total_comparisons: Optional[int] = None
    winner_breakdown: dict[str, int] = {}
    category_breakdown: list[ComparisonCategoryCount] = []
    unique_photos_compared: Optional[int] = None
    recent_optimization_runs: list[dict] = []
    min_comparisons_for_optimization: Optional[int] = None


class CategoryWeightsResponse(BaseModel):
    """Either a single category's weights (``category`` given) or the full list."""

    category: Optional[str] = None
    weights: Optional[dict] = None
    modifiers: Optional[dict] = None
    filters: Optional[dict] = None
    priority: Optional[int] = None
    categories: Optional[list[dict]] = None


class LearnedWeightsResponse(BaseModel):
    """Weight-optimization suggestion.

    ``accuracy_before`` / ``accuracy_after`` / ``improvement`` are a rounded
    float on the direct-optimization path but fall back to the plain int
    default ``0`` on the cross-validated path, which does not compute them --
    ``Union[float, int]`` keeps whichever the handler actually sent instead of
    coercing an int default into ``0.0``.
    """

    available: bool
    message: Optional[str] = None
    comparisons: Optional[int] = None
    min_required: Optional[int] = None
    current_weights: Optional[dict] = None
    suggested_weights: Optional[dict] = None
    accuracy_before: Optional[Union[float, int]] = None
    accuracy_after: Optional[Union[float, int]] = None
    improvement: Optional[Union[float, int]] = None
    suggest_changes: Optional[bool] = None
    comparisons_used: Optional[int] = None
    ties_included: Optional[int] = None
    mispredicted_count: Optional[int] = None
    category: Optional[str] = None
    method: Optional[str] = None
    cv_accuracy: Optional[Union[float, int]] = None
    cv_std: Optional[Union[float, int]] = None
    fold_results: Optional[list] = None


class SuggestFiltersResponse(BaseModel):
    """Either the early-exit shape (``message`` only) or the full analysis."""

    current_category: Optional[str] = None
    target_category: Optional[str] = None
    target_filters: Optional[dict] = None
    conflicts: Optional[list[dict]] = None
    suggestions: Optional[list[dict]] = None
    photo_values: Optional[dict] = None
    no_conflicts: Optional[bool] = None
    message: Optional[str] = None


class CategoryOverrideResponse(BaseModel):
    """Shared shape of ``override_category`` and ``clear_category_override``."""

    success: bool
    path: str
    old_category: Optional[str] = None
    new_category: Optional[str] = None
    aggregate: Optional[float] = None


class WeightSnapshotItem(BaseModel):
    id: int
    timestamp: Optional[str] = None
    category: Optional[str] = None
    weights: dict = {}
    description: Optional[str] = None
    accuracy_before: Optional[float] = None
    accuracy_after: Optional[float] = None
    comparisons_used: Optional[int] = None
    created_by: Optional[str] = None


class WeightSnapshotsResponse(BaseModel):
    snapshots: list[WeightSnapshotItem] = []
    has_more: bool = False


class RestoreWeightsResponse(BaseModel):
    success: bool
    restored_weights: dict = {}
    category: Optional[str] = None


class PanoramaDetectionSettingsResponse(BaseModel):
    settings: dict = {}
    defaults: dict = {}


class PanoramaDetectionUpdateResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    backup: Optional[str] = None
    requires_redetection: Optional[bool] = None
