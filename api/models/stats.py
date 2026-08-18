"""Pydantic models for the stats-tab endpoints (`api/routers/stats.py`).

Numeric fields that trace back to a handler's ``value or 0`` fallback are typed
``Union[int, float]`` rather than ``float``: Python's ``or`` treats a real
``0.0`` average as falsy, so the handler emits the *int* ``0`` on that branch
while every non-fallback row emits a ``ROUND(...)`` ``float``. Declaring
``float`` alone would make Pydantic coerce the int branch's ``0`` into
``0.0`` on the wire, which is exactly the silent retyping this phase pins
against.
"""

from typing import Dict, List, Optional, Union

from pydantic import BaseModel


class StatsOverviewResponse(BaseModel):
    total_photos: int
    total_persons: int
    avg_score: Union[int, float]
    avg_aesthetic: Union[int, float]
    avg_composition: Union[int, float]
    total_faces: int
    total_tags: int
    date_range_start: str
    date_range_end: str


class StatsScoreDistributionBin(BaseModel):
    range: str
    min: float
    max: float
    count: int
    percentage: float


class StatsTopCamera(BaseModel):
    name: Optional[str] = None
    count: int
    avg_score: Optional[float] = None
    avg_aesthetic: Optional[float] = None


class StatsCategoryStat(BaseModel):
    category: str
    count: int
    percentage: float
    avg_score: Union[int, float]
    avg_aesthetic: Union[int, float]
    avg_composition: Union[int, float]
    avg_sharpness: Union[int, float]
    avg_color: Union[int, float]
    avg_exposure: Union[int, float]
    avg_iso: Union[int, float]
    avg_f_stop: Union[int, float]
    avg_focal_length: Union[int, float]
    avg_face_quality: Union[int, float]
    avg_contrast: Union[int, float]
    top_camera: Optional[str] = None
    top_lens: Optional[str] = None


class StatsGearHistoryPoint(BaseModel):
    date: str
    count: int


class StatsGearItem(BaseModel):
    name: Optional[str] = None
    count: int
    avg_aggregate: Optional[float] = None
    avg_aesthetic: Optional[float] = None
    avg_sharpness: Optional[float] = None
    avg_composition: Optional[float] = None
    avg_exposure: Optional[float] = None
    avg_color: Optional[float] = None
    avg_iso: Union[int, float]
    avg_f_stop: Union[int, float]
    avg_focal_length: Union[int, float]
    avg_face_count: Union[int, float]
    avg_monochrome: Union[int, float]
    avg_dynamic_range: Union[int, float]
    history: List[StatsGearHistoryPoint]


class StatsGearCategoryCount(BaseModel):
    name: Optional[str] = None
    count: int


class StatsGearResponse(BaseModel):
    cameras: List[StatsGearItem]
    lenses: List[StatsGearItem]
    combos: List[StatsGearItem]
    categories: List[StatsGearCategoryCount]


class StatsCorrelationBucket(BaseModel):
    """A single (x_bucket, group) cell.

    ``count`` is the only fixed key; the remaining keys are whichever metrics
    the caller requested (``y=aggregate,comp_score,...``), each a
    ``ROUND(AVG(...), 3)`` float or ``None``. ``extra='allow'`` carries those
    dynamic keys through unvalidated so a metric name never has to be
    enumerated here and its float/None value is never coerced.
    """

    count: int

    model_config = {'extra': 'allow'}


class StatsCorrelationsGroupedResponse(BaseModel):
    labels: List[str]
    groups: Dict[str, Dict[str, StatsCorrelationBucket]]
    metrics: List[str]
    x_axis: str
    group_by: str


class StatsCorrelationsUngroupedResponse(BaseModel):
    labels: List[str]
    metrics: Dict[str, List[Optional[float]]]
    counts: List[int]
    x_axis: str
    group_by: str


class StatsCategoryCorrelationsResponse(BaseModel):
    correlations: Dict[str, Dict[str, Optional[Union[float, int]]]]
    configured_weights: Dict[str, Dict[str, Optional[Union[int, float]]]]
    dimensions: List[str]


class StatsOverlapPair(BaseModel):
    pair: List[str]
    count: int


class StatsCategoryOverlapSummary(BaseModel):
    name: str
    priority: Optional[Union[int, float]] = None
    assigned: int
    matched: int
    captured_by_higher: int


class StatsCategoryOverlapResponse(BaseModel):
    overlaps: List[StatsOverlapPair]
    per_category: List[StatsCategoryOverlapSummary]
    uncategorized: int
    total: int


class StatsCategoryRecomputeResponse(BaseModel):
    success: bool
    message: str
    output: str
