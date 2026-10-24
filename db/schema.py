"""
Database schema definitions and initialization for Facet.

Single source of truth for all table and index definitions.
"""

from typing import Any, Callable
import logging
import re
import sqlite3
import time
from contextlib import closing

from db.connection import apply_pragmas, HAS_SQLITE_VEC
from db.embedding_space import ARCFACE_MODEL

logger = logging.getLogger("facet.schema")

# Schema definitions as (name, type_definition) tuples
# Type definition includes any defaults or constraints

PHOTOS_COLUMNS = [
    # Core metadata
    ('path', 'TEXT PRIMARY KEY'),
    ('filename', 'TEXT'),
    ('date_taken', 'TEXT'),
    ('camera_model', 'TEXT'),
    ('lens_model', 'TEXT'),
    # Affinity is not a constraint: an external EXIF writer's fractional
    # exposure index (e.g. an Immich-sourced ISO) is still accepted and
    # stored as REAL here. `--repair-int-columns` rewrites rows an existing
    # library already holds; the response model coerces the rest.
    ('iso', 'INTEGER'),
    ('f_stop', 'REAL'),
    ('shutter_speed', 'TEXT'),
    ('focal_length', 'REAL'),
    ('focal_length_35mm', 'REAL'),
    ('image_width', 'INTEGER'),
    ('image_height', 'INTEGER'),
    # Display aspect (width / height) for a row whose recorded pixel dimensions
    # had to be cleared. `repair_thumbnail_dimensions` NULLs dimensions that were
    # fabricated from the 640px thumbnail, because every face/crop consumer reads
    # them as the detector's pixel space and a thumbnail-sized number there is a
    # lie that reads as ground truth. The *ratio* those values carried was never
    # wrong (a thumbnail preserves aspect), so it is kept here instead — in a
    # column no consumer can mistake for a resolution. NULL for every row whose
    # dimensions are real: read it only as a fallback, never in preference.
    ('image_aspect', 'REAL'),

    # Score columns
    ('aesthetic', 'REAL'),
    ('face_count', 'INTEGER DEFAULT 0 CHECK (face_count >= 0)'),
    ('face_quality', 'REAL'),
    ('eye_sharpness', 'REAL'),
    ('face_sharpness', 'REAL'),
    ('eyes_open_score', 'REAL'),    # Continuous 0-10 eyes-open (min across faces), from 106-pt landmarks
    ('expression_score', 'REAL'),   # Continuous 0-10 mouth-state quality (mean across faces)
    ('face_ratio', 'REAL CHECK (face_ratio IS NULL OR (face_ratio >= 0 AND face_ratio <= 1))'),
    ('tech_sharpness', 'REAL'),
    ('color_score', 'REAL'),
    ('exposure_score', 'REAL'),
    ('comp_score', 'REAL'),
    ('isolation_bonus', 'REAL'),
    ('aggregate', 'REAL CHECK (aggregate IS NULL OR (aggregate >= 0 AND aggregate <= 10))'),

    # Flags
    ('is_blink', 'INTEGER CHECK (is_blink IS NULL OR is_blink IN (0, 1))'),
    ('is_burst_lead', 'INTEGER DEFAULT 0 CHECK (is_burst_lead IN (0, 1))'),
    ('burst_group_id', 'INTEGER'),
    ('burst_reviewed', 'INTEGER NOT NULL DEFAULT 0 CHECK (burst_reviewed IN (0, 1))'),
    ('similarity_reviewed', 'INTEGER NOT NULL DEFAULT 0 CHECK (similarity_reviewed IN (0, 1))'),
    ('is_monochrome', 'INTEGER DEFAULT 0 CHECK (is_monochrome IN (0, 1))'),
    ('is_silhouette', 'INTEGER'),
    ('is_group_portrait', 'INTEGER'),

    # Duplicate detection
    ('duplicate_group_id', 'INTEGER'),
    ('is_duplicate_lead', 'INTEGER DEFAULT 0 CHECK (is_duplicate_lead IN (0, 1))'),

    # Deliberate multi-frame sequences (--detect-sequences). A bracket is one
    # subject shot at several exposures, so its frames must not be read as
    # competing takes the way a burst's are.
    ('sequence_group_id', 'INTEGER'),
    ('sequence_kind', 'TEXT'),       # 'bracket' | 'panorama' | 'hdr_panorama'
    ('sequence_ev_offset', 'REAL'),  # exposure compensation vs the set's base frame (0.0 = base, + = brighter)
    # Which frame stands for a panorama set in the gallery. A bracket's
    # representative is a fact it already carries (sequence_ev_offset = 0); a
    # panorama has no equivalent, so the pass marks its middle frame here and
    # the hide clause stays an indexed equality rather than a window function
    # evaluated per gallery row.
    ('is_sequence_lead', 'INTEGER DEFAULT 0'),

    # Raw data for recalculation
    ('clip_embedding', 'BLOB'),
    ('raw_sharpness_variance', 'REAL'),
    ('histogram_data', 'BLOB'),
    ('histogram_spread', 'REAL'),
    ('mean_luminance', 'REAL'),
    ('histogram_bimodality', 'REAL'),
    ('power_point_score', 'REAL'),
    ('raw_color_entropy', 'REAL'),
    ('raw_eye_sharpness', 'REAL'),

    # Technical metrics
    ('shadow_clipped', 'INTEGER'),
    ('highlight_clipped', 'INTEGER'),
    # Share of pixels that reached the end of the scale, in the worst of R/G/B:
    # exactly bin 0 and exactly bin 255 of the stored histogram, as a percentage
    # (0-100). A DIFFERENT measurement from the two flags above, which are
    # binary and cover the luminance bands 0-30 / 225-255.
    #
    # NULL means unknown, never clean: a row whose histogram_data is still a
    # legacy 1024-byte luminance-only blob has no per-channel data to derive
    # from, and its bins came from an auto-brightened decode anyway. Every
    # reader treats NULL as "not measured" -- see --backfill-clipping.
    ('channel_clip_shadow_pct', 'REAL'),
    ('channel_clip_highlight_pct', 'REAL'),
    ('dynamic_range_stops', 'REAL'),
    ('noise_sigma', 'REAL'),
    ('contrast_score', 'REAL'),
    ('mean_saturation', 'REAL'),
    ('leading_lines_score', 'REAL'),
    ('face_confidence', 'REAL'),

    # Output columns
    ('thumbnail', 'BLOB'),
    ('phash', 'TEXT'),
    ('config_version', 'TEXT'),
    ('tags', 'TEXT'),
    ('quality_score', 'REAL'),
    ('topiq_score', 'REAL'),
    ('composition_explanation', 'TEXT'),
    ('scoring_model', 'TEXT'),
    ('composition_pattern', 'TEXT'),
    ('category', 'TEXT'),

    # PyIQA extended scores
    ('aesthetic_iaa', 'REAL'),       # TOPIQ IAA (AVA-trained aesthetic merit)
    ('face_quality_iqa', 'REAL'),    # TOPIQ NR-Face (dedicated face quality)
    ('liqe_score', 'REAL'),          # LIQE quality score
    ('aesthetic_clip', 'REAL'),      # CLIP/SigLIP text-projection aesthetic (supplementary, free from cached embedding)
    # Extended IQA tier (optional, config-gated; never replaces TOPIQ)
    ('qrealign_score', 'REAL'),      # Q-ReAlign-Mini LLM-based IQA (normalized 0-10)
    ('aesthetic_v25', 'REAL'),       # Aesthetic Predictor V2.5 (SigLIP head)
    ('deqa_score', 'REAL'),          # DeQA-Score VLM IQA

    # Subject saliency metrics (BiRefNet)
    ('subject_sharpness', 'REAL'),   # Laplacian variance on subject mask
    ('subject_prominence', 'REAL'),  # Subject area ratio
    ('subject_placement', 'REAL'),   # Rule-of-thirds score for subject centroid
    ('bg_separation', 'REAL'),       # Subject-background separation quality
    ('subject_bbox', 'TEXT'),        # JSON [x0,y0,x1,y1] normalized 0..1 subject box (saliency-aware social crop); NULL until saliency runs

    # User ratings and flags
    ('star_rating', 'INTEGER DEFAULT 0 CHECK (star_rating >= 0 AND star_rating <= 5)'),
    ('is_favorite', 'INTEGER DEFAULT 0 CHECK (is_favorite IN (0, 1))'),
    ('is_rejected', 'INTEGER DEFAULT 0 CHECK (is_rejected IN (0, 1))'),
    ('is_kept', 'INTEGER DEFAULT 0 CHECK (is_kept IN (0, 1))'),

    # AI captioning
    ('caption', 'TEXT'),
    ('caption_translated', 'TEXT'),

    # VLM critique cache (regenerated on demand via /api/critique?refresh=true)
    ('vlm_critique', 'TEXT'),
    ('vlm_critique_translated', 'TEXT'),

    # OCR text-in-image (opt-in --detect-text; NULL = not evaluated, '' = evaluated
    # and no text found, else the detected text). The '' sentinel is what lets
    # --detect-text scope to genuinely unevaluated rows instead of re-OCRing every
    # textless photo on each run; FTS5 indexes it as zero tokens so it never matches.
    ('ocr_text', 'TEXT'),

    # Color facet (opt-in --recompute-colors; NULL until that pass runs)
    ('dominant_hue', 'REAL'),       # 0-360 dominant hue, NULL for monochrome/unknown
    ('color_temp', 'TEXT'),         # 'warm' | 'cool' | 'neutral'

    # Form facet + Matsuda color harmony (CPU; scan-time + --recompute-form)
    ('form_symmetry', 'REAL'),      # left-right mirror symmetry, 0-10
    ('form_balance', 'REAL'),       # edge-energy centroid centeredness, 0-10
    ('form_edge_entropy', 'REAL'),  # edge-orientation histogram entropy, 0-10
    ('form_fractal', 'REAL'),       # box-counting fractal dimension mapped to 0-10
    ('color_harmony', 'REAL'),      # Matsuda hue-template harmony, 0-10; NULL for monochrome

    # GPS coordinates
    ('gps_latitude', 'REAL'),
    ('gps_longitude', 'REAL'),

    # Scan bookkeeping (ISO timestamp of last successful scoring)
    ('scanned_at', 'TEXT'),

    # Narrative moment (opt-in --detect-moments; NULL until that pass runs)
    ('narrative_moment', 'TEXT'),              # e.g. 'celebration', 'beach', 'other'
    ('narrative_moment_confidence', 'REAL'),   # confidence in the assigned label: forward-backward posterior (0-1) for a moment, neutral 0.5 for 'other'

    # Junk sweep (opt-in --detect-junk; NULL = not evaluated, 'not_junk' = evaluated clean,
    # else the junk kind: 'screenshot'|'document'|'receipt'|'meme'|'slide')
    ('junk_kind', 'TEXT'),
    ('caption_embedding', 'BLOB'),             # text embedding of the caption (semantic moment signal)
    ('learned_score', 'REAL'),                 # denormalized global personal-ranker score (mirrors learned_scores user_id/category NULL) so the "My Taste" sort is an indexed column read

    # Advisory explainability diagnostics (opt-in recompute passes; never enter the aggregate)
    ('distortion_attributes', 'TEXT'),  # JSON [{attribute, confidence}] from --recompute-distortions (zero-shot ExIQA-style)
    ('skin_tone_delta', 'REAL'),        # worst-face CIEDE2000 distance to the natural skin locus (--recompute-skin-tone)
    ('skin_tone_cast', 'TEXT'),         # 'green'|'magenta'|'blue'|'yellow' when the delta exceeds the cast threshold, else NULL

    # Which of the two RAW display renders produced this row's stored thumbnail,
    # and nothing else: the camera preview one every scan bakes, or the
    # uncorrected demosaic a bracketed frame needs. Says nothing about
    # histogram_data or any other scored column — those come from the metrics
    # demosaic, and --refresh-thumbnails never rewrites them. DERIVED state,
    # which is why it lives here and not in a side table despite the
    # INSERT-OR-REPLACE invariant: a rescan regenerates the thumbnail with
    # current code, so the stamp SHOULD be rewritten with the row. Read against
    # the row's sequence_kind, never on its own. NULL = written before the stamp
    # existed, i.e. before the RAW exposure fix. See db/render_version.py.
    ('render_version', 'INTEGER'),
    # Manual GPS (including intentional clears) survives EXIF rescans.
    ('gps_manually_set', 'INTEGER NOT NULL DEFAULT 0'),
]

FACES_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('photo_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('face_index', 'INTEGER NOT NULL'),
    ('embedding', 'BLOB NOT NULL'),
    ('bbox_x1', 'INTEGER'),
    ('bbox_y1', 'INTEGER'),
    ('bbox_x2', 'INTEGER'),
    ('bbox_y2', 'INTEGER'),
    ('confidence', 'REAL'),
    ('person_id', 'INTEGER'),
    ('face_thumbnail', 'BLOB'),  # Pre-generated face crop from detection time
    ('landmark_2d_106', 'BLOB'),  # 106x2 float32 = 848 bytes for blink detection
    # Per-face geometric quality signals derived from landmark_2d_106 (canonical
    # source for the culling face panel; NULL for rows scanned before these
    # columns existed until --recompute-face-signals backfills them).
    ('eyes_open_score', 'REAL'),  # 0-10 continuous eyes-open (NULL on turned heads)
    ('smile_score', 'REAL'),      # 0-10 mouth-corner-lift smile (5 ~ neutral)
    # Embedding-space marker: which recognition model produced `embedding`.
    # Embeddings from different models are NOT comparable, so clustering loads
    # only the active space (see faces/clusterer.py) — a future model swap can't
    # silently mix spaces. The constant default backfills existing rows (all
    # ArcFace/buffalo_l) on migration and tags new inserts with no code change.
    ('embedding_model', f"TEXT DEFAULT '{ARCFACE_MODEL}'"),
    ('is_manual', 'INTEGER NOT NULL DEFAULT 0'),
    ('manual_key', 'TEXT'),
    ('manual_source', 'TEXT'),
    ('manual_width', 'INTEGER'),
    ('manual_height', 'INTEGER'),
]

# UUIDs are never reused. Explicit deletion survives synchronization with an
# older active copy, and must outlive deletion of the original photo itself.
MANUAL_FACE_DELETIONS_COLUMNS = [('manual_key', 'TEXT PRIMARY KEY NOT NULL')]

# Single shared faces upsert used by every scan-time writer (processing/scorer.py
# single + batch, faces/processor.py). INSERT OR REPLACE regenerates the whole
# row on --force rescans via the UNIQUE(photo_path, face_index) constraint, so a
# writer with a stale column list would silently NULL the columns it misses —
# one shared statement + row builder makes that divergence impossible.
FACES_UPSERT_SQL = """
    INSERT OR REPLACE INTO faces
    (photo_path, face_index, embedding, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
     confidence, face_thumbnail, landmark_2d_106, eyes_open_score, smile_score,
     embedding_model)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def face_upsert_row(photo_path, face, embedding_model):
    """Build the FACES_UPSERT_SQL parameter tuple from a face_details dict.

    The model that produced the embedding is the analyzer's own word: a face
    carrying ``embedding_model`` is tagged with it. ``embedding_model`` (the
    active model) is the fallback for an analyzer that does not report one, and
    is required: the column's schema default is the legacy ArcFace tag, so a
    writer that omitted it would mislabel a 128-d SFace embedding as ArcFace.
    """
    bbox = face.get('bbox', [0, 0, 0, 0])
    return (
        photo_path,
        face['index'],
        face['embedding'],
        bbox[0], bbox[1], bbox[2], bbox[3],
        face.get('confidence', 0),
        face.get('thumbnail'),
        face.get('landmark_2d_106'),
        face.get('eyes_open_score'),
        face.get('smile_score'),
        face.get('embedding_model') or embedding_model,
    )


# Named-person faces remembered across a forced re-extraction. The extraction deletes
# every face row long before it finishes (hours on a large library), so the memory
# has to live in the database, written in the same transaction as the delete: a crash
# or Ctrl-C must not leave named persons with nothing pointing at them. Replayed by
# the extraction itself (and the next run if this one died) and cleared when done.
FACE_REEXTRACT_SNAPSHOT_COLUMNS = [
    ('photo_path', 'TEXT NOT NULL'),
    ('bbox_x1', 'REAL'),
    ('bbox_y1', 'REAL'),
    ('bbox_x2', 'REAL'),
    ('bbox_y2', 'REAL'),
    ('person_id', 'INTEGER NOT NULL'),
]

PERSONS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('name', 'TEXT'),
    ('representative_face_id', 'INTEGER'),
    ('face_count', 'INTEGER DEFAULT 0'),
    ('centroid', 'BLOB'),
    ('auto_clustered', 'INTEGER DEFAULT 1'),
    ('face_thumbnail', 'BLOB'),
    ('is_hidden', 'INTEGER DEFAULT 0'),
    # Which embedding model the centroid was averaged from; NULL = legacy ArcFace.
    # A centroid is only comparable with embeddings of the same model. Kept LAST:
    # an upgrade appends a column (ALTER TABLE ADD COLUMN), so declaring it anywhere
    # else gives a fresh DB and an upgraded one different column orders, and the
    # positional INSERT ... SELECT * between them would shift every value.
    ('centroid_model', 'TEXT'),
    ('person_key', 'TEXT'),
]


def person_not_hidden_clause(alias=''):
    """SQL predicate selecting persons that are not hidden (NULL = not hidden).

    Single source of truth for the ``is_hidden`` visibility test shared by the
    persons router, the filter-options router and the merge analyzer. Pass a
    table alias (e.g. ``'p'``) to qualify the column.
    """
    col = f"{alias}.is_hidden" if alias else "is_hidden"
    return f"({col} = 0 OR {col} IS NULL)"


# The photos columns the gallery's hide / visibility clauses read (HIDE_* and
# HIDDEN_* in api/db_helpers.py plus the single-user `is_rejected` test). A new
# hide column MUST be added here, or the gallery silently reverts to table passes.
GALLERY_VISIBILITY_COLUMNS = (
    'is_blink', 'is_burst_lead', 'burst_group_id', 'is_sequence_lead',
    'is_duplicate_lead', 'duplicate_group_id', 'sequence_kind', 'sequence_ev_offset',
    'is_rejected',
)
# Plus `junk_kind`, so the `junk_kind=any` predicate is evaluated from the index
# entry rather than the table row. On purpose: do not drop it.
GALLERY_COVER_COLUMNS = GALLERY_VISIBILITY_COLUMNS + ('junk_kind',)
_GALLERY_COVER_SQL = ', '.join(GALLERY_COVER_COLUMNS)

# Index definitions as (name, table, column_expression)
INDEXES = [
    ('idx_date_taken', 'photos', 'date_taken'),
    ('idx_scanned_at', 'photos', 'scanned_at'),
    ('idx_aggregate', 'photos', 'aggregate DESC'),
    ('idx_camera_model', 'photos', 'camera_model'),
    ('idx_lens_model', 'photos', 'lens_model'),
    ('idx_face_count', 'photos', 'face_count'),
    ('idx_face_ratio', 'photos', 'face_ratio'),
    ('idx_is_monochrome', 'photos', 'is_monochrome'),
    ('idx_is_burst_lead', 'photos', 'is_burst_lead'),
    ('idx_is_sequence_lead', 'photos', 'is_sequence_lead'),
    ('idx_tags', 'photos', 'tags'),
    ('idx_faces_photo', 'faces', 'photo_path'),
    ('idx_faces_person', 'faces', 'person_id'),
    # Composite indexes for common query patterns
    ('idx_aggregate_date', 'photos', 'aggregate DESC, date_taken DESC'),
    ('idx_burst_aggregate', 'photos', 'is_burst_lead, aggregate DESC'),
    ('idx_face_detection', 'photos', 'face_count, face_ratio'),
    ('idx_faces_person_photo', 'faces', 'person_id, photo_path'),
    ('idx_filename', 'photos', 'filename'),
    ('idx_category', 'photos', 'category'),
    ('idx_category_aggregate', 'photos', 'category, aggregate DESC'),
    ('idx_narrative_moment', 'photos', 'narrative_moment'),
    ('idx_junk_kind', 'photos', 'junk_kind'),
    ('idx_sequence_group', 'photos', 'sequence_group_id'),
    ('idx_sequence_kind', 'photos', 'sequence_kind, sequence_group_id'),
    # Additional composite indexes for viewer sorting performance
    ('idx_aesthetic_aggregate', 'photos', 'aesthetic DESC, aggregate DESC'),
    ('idx_face_quality_sort', 'photos', 'face_quality DESC, eye_sharpness DESC'),
    ('idx_tech_sharpness_sort', 'photos', 'tech_sharpness DESC, aesthetic DESC'),
    # Performance indexes for large databases
    ('idx_date_taken_desc', 'photos', 'date_taken DESC'),
    ('idx_blink_burst', 'photos', 'is_blink, is_burst_lead'),
    ('idx_composition_pattern', 'photos', 'composition_pattern'),
    # Composite index for camera/lens DISTINCT queries
    ('idx_camera_lens', 'photos', 'camera_model, lens_model'),
    # Duplicate detection indexes
    ('idx_burst_group', 'photos', 'burst_group_id'),
    ('idx_burst_reviewed', 'photos', 'burst_reviewed, burst_group_id'),
    ('idx_similarity_reviewed', 'photos', 'similarity_reviewed'),
    ('idx_duplicate_group', 'photos', 'duplicate_group_id'),
    ('idx_duplicate_lead', 'photos', 'is_duplicate_lead'),
    # User rating indexes
    ('idx_star_rating', 'photos', 'star_rating'),
    ('idx_is_favorite', 'photos', 'is_favorite'),
    ('idx_is_rejected', 'photos', 'is_rejected'),
    # Composite indexes that eliminate the temp B-tree sort step on common
    # single-user filter+sort combos. Multi-user mode hits
    # user_preferences instead and has its own indexes.
    ('idx_favorite_aggregate', 'photos', 'is_favorite, aggregate DESC'),
    ('idx_rejected_aggregate', 'photos', 'is_rejected, aggregate DESC'),
    # GPS indexes
    ('idx_gps', 'photos', 'gps_latitude, gps_longitude'),
    # Range-filterable metric columns exposed by the gallery sidebar. Without
    # these, filtering on a metric walks the full idx_aggregate (126k+ rows)
    # because the planner has no usable index for the predicate.
    ('idx_quality_score', 'photos', 'quality_score'),
    ('idx_topiq_score', 'photos', 'topiq_score'),
    ('idx_aesthetic_iaa', 'photos', 'aesthetic_iaa'),
    ('idx_face_quality_iqa', 'photos', 'face_quality_iqa'),
    ('idx_liqe_score', 'photos', 'liqe_score'),
    ('idx_eye_sharpness', 'photos', 'eye_sharpness'),
    ('idx_face_sharpness', 'photos', 'face_sharpness'),
    ('idx_face_confidence', 'photos', 'face_confidence'),
    ('idx_comp_score', 'photos', 'comp_score'),
    ('idx_power_point_score', 'photos', 'power_point_score'),
    ('idx_leading_lines_score', 'photos', 'leading_lines_score'),
    ('idx_isolation_bonus', 'photos', 'isolation_bonus'),
    ('idx_subject_sharpness', 'photos', 'subject_sharpness'),
    ('idx_subject_prominence', 'photos', 'subject_prominence'),
    ('idx_subject_placement', 'photos', 'subject_placement'),
    ('idx_bg_separation', 'photos', 'bg_separation'),
    ('idx_exposure_score', 'photos', 'exposure_score'),
    ('idx_color_score', 'photos', 'color_score'),
    ('idx_contrast_score', 'photos', 'contrast_score'),
    ('idx_mean_saturation', 'photos', 'mean_saturation'),
    ('idx_noise_sigma', 'photos', 'noise_sigma'),
    ('idx_dynamic_range_stops', 'photos', 'dynamic_range_stops'),
    ('idx_mean_luminance', 'photos', 'mean_luminance'),
    ('idx_histogram_spread', 'photos', 'histogram_spread'),
    ('idx_channel_clip_shadow', 'photos', 'channel_clip_shadow_pct'),
    ('idx_channel_clip_highlight', 'photos', 'channel_clip_highlight_pct'),
    ('idx_iso', 'photos', 'iso'),
    ('idx_f_stop', 'photos', 'f_stop'),
    ('idx_focal_length', 'photos', 'focal_length'),
    # Color facet filters (hue bucket + warm/cool/neutral classification)
    ('idx_dominant_hue', 'photos', 'dominant_hue'),
    ('idx_color_temp', 'photos', 'color_temp'),
    # Narrative-moment confidence sort. Without this the "Moment Confidence" sort
    # full-sorts 126k+ rows (~1.5s/page). Standalone (not a (is_burst_lead, …)
    # composite) so the planner scans it in sort order and residual-filters the
    # hide predicates: hide-bursts is "(is_burst_lead = 1 OR is_burst_lead IS
    # NULL OR burst_group_id IS NULL)", whose ORs trigger a MULTI-INDEX OR that
    # defeats a composite's equality seek. Includes path so the DESC order_by
    # needs no temp B-tree.
    ('idx_moment_confidence', 'photos', 'narrative_moment_confidence DESC, path'),
    # "My Taste" (personal ranker) sort. The global learned_score is denormalized
    # into photos.learned_score so this sort reads an index instead of a per-row
    # correlated subquery into learned_scores (~0.5s/page). Standalone (X DESC,
    # path) for the same MULTI-INDEX-OR reason as idx_moment_confidence above.
    ('idx_learned_score', 'photos', 'learned_score DESC, path'),
    # Q-ReAlign sort + min/max_qrealign range filter (the leading column serves both).
    # Same (X DESC, path) shape as idx_learned_score so the DESC order_by needs no
    # temp B-tree; analyzed on build (ANALYZE_ON_BUILD_INDEXES) so the planner uses it
    # on libraries whose gallery indexes are already analyzed. Replaces the bare
    # idx_qrealign_score (dropped on upgrade): CREATE INDEX IF NOT EXISTS cannot
    # reshape an index, hence the new name.
    ('idx_qrealign_sort', 'photos', 'qrealign_score DESC, path'),
    # DeQA sort + min/max_deqa range filter: same (X DESC, path) shape and ANALYZE-on-build
    # as idx_qrealign_sort. Replaces the bare idx_deqa_score (dropped on upgrade).
    ('idx_deqa_sort', 'photos', 'deqa_score DESC, path'),
    # Aesthetic v2.5 sort + min/max_aesthetic_v25 range filter: same shape and ANALYZE-on-build.
    # Replaces the bare idx_aesthetic_v25 (dropped on upgrade).
    ('idx_aesthetic_v25_sort', 'photos', 'aesthetic_v25 DESC, path'),
    # Covering index for _shoot_type_evidence's GROUP BY (category,
    # narrative_moment): leading columns match the GROUP BY exactly, with
    # face_count and date_taken (read by the conditional SUMs) appended so the
    # whole aggregate is answered from the index alone — no table page, and no
    # inline thumbnail BLOB, is ever read. Without it the query walked the full
    # photos B-tree (22.9s cold on a 126k-photo library).
    ('idx_shoot_type_evidence', 'photos', 'category, narrative_moment, face_count, date_taken'),
    # Gallery covering indexes. Every gallery statement (the count, the hidden
    # summary and the page) reads the same nine visibility columns in its hide
    # clauses, and without an index that holds them each statement walks the
    # whole 16 GB table (half a gigabyte of pages per request on a 130k library).
    # `path` follows the sort column because the gallery's ORDER BY always ends
    # in `path ASC` (a bare `aggregate DESC` index forced a temp B-tree). Built
    # from the two tuples above so this list cannot drift from the hide clauses
    # (tests/test_gallery_indexes.py reads both). `junk_kind` rides along so the
    # `junk_kind=any` predicate is answered from the index entry, unrewritten.
    # idx_gallery_aggregate is the aggregate-leading superset: it also carries
    # category / camera_model / lens_model, which serves the lens filter, so
    # there is no separate lens index, and the columns the top-picks score reads
    # (api.top_picks.get_top_picks_score_sql: face_ratio, aesthetic, comp_score,
    # face_quality besides aggregate), so the type=top_picks count and hidden
    # summary are answered from the index instead of two full table scans.
    ('idx_gallery_aggregate', 'photos',
     f'aggregate DESC, path, {_GALLERY_COVER_SQL}, category, camera_model, lens_model, '
     'face_ratio, aesthetic, comp_score, face_quality'),
    ('idx_gallery_date_desc', 'photos', f'date_taken DESC, path, {_GALLERY_COVER_SQL}'),
    # Date-ascending gallery page AND the post-scan reads that walk the library in
    # date order. It supersedes the narrower idx_gallery_date_asc (see the stale
    # drop in init_database): both lead with `date_taken ASC, path`, so one wider
    # B-tree serves them instead of a near-duplicate that every date/path update
    # would also have to maintain. The column list IS the contract. Everything
    # after the cover columns is read by a post-scan statement, and a column
    # added to one of those SELECTs without being added here silently turns it
    # back into a multi-minute table scan:
    #   * utils.sequence._load_photos: camera_model, f_stop, shutter_speed, iso,
    #     phash, shadow_clipped, highlight_clipped (ordered by date_taken, path,
    #     which the index order satisfies with no temp B-tree);
    #   * utils.panorama._load_candidates: focal_length, scanned_at;
    #   * the panorama run signature: scanned_at, render_version and
    #     length(thumbnail) (the expression, so the thumbnail BLOB is never read).
    # `date_taken` leads so `date_taken IS NOT NULL` is a seekable `date_taken > ?`.
    # junk_kind rides in the cover tuple on purpose (see GALLERY_COVER_COLUMNS).
    ('idx_date_asc_cover', 'photos',
     f'date_taken ASC, path, {_GALLERY_COVER_SQL}, camera_model, focal_length, f_stop, '
     'shutter_speed, iso, phash, shadow_clipped, highlight_clipped, scanned_at, '
     'render_version, length(thumbnail)'),
    # Covering index for the post-scan phases that read the whole library by
    # perceptual hash: process_bursts (phash, date_taken, aggregate, face_count,
    # eyes_open_score, expression_score, tech_sharpness, is_burst_lead,
    # burst_group_id) and detect_duplicates (phash, aggregate, face_count,
    # eyes_open_score, expression_score, tech_sharpness, duplicate_group_id,
    # is_duplicate_lead). `path` is last so it adds no ordering. The column list IS
    # the contract: a column added to either SELECT without being added here
    # silently turns the read back into a scan of the 16 GB table. The precedent
    # for this tone is idx_shoot_type_evidence above. No other index leads with
    # phash, so it overlaps none of the gallery indexes.
    ('idx_post_scan', 'photos',
     'phash, date_taken, aggregate, face_count, eyes_open_score, expression_score, '
     'tech_sharpness, is_burst_lead, burst_group_id, duplicate_group_id, '
     'is_duplicate_lead, path'),
    # Category / type dropdown (the most common filter).
    ('idx_gallery_category', 'photos', f'category, aggregate DESC, path, {_GALLERY_COVER_SQL}'),
    # Camera filter (and the camera+lens pair). `camera_model = ?` is the only
    # sargable term (the lens filter is a LIKE, never a seek), so the sort columns
    # follow it directly and the page reads `aggregate DESC, path` off the index;
    # lens_model rides at the end for the pair's filter. With lens_model second the
    # page temp-sorted every row of the camera and the planner preferred the
    # narrower idx_camera_lens for that sort.
    ('idx_gallery_camera', 'photos',
     f'camera_model, aggregate DESC, path, {_GALLERY_COVER_SQL}, lens_model'),
    # Sort by star rating (the rating was a bare idx_star_rating: the ORDER BY
    # ends in path, so that index needed a temp B-tree).
    ('idx_star_rating_path', 'photos', 'star_rating DESC, path'),
    # NULLs-last ascending sort. The expression text must match
    # api.types.order_by_clause's `(aesthetic_iaa IS NULL) ASC, aesthetic_iaa ASC`
    # for the planner to use it; only aesthetic_iaa gets one of the six nullable
    # ASC sorts.
    ('idx_gallery_iaa_asc', 'photos',
     f'(aesthetic_iaa IS NULL), aesthetic_iaa, path, {_GALLERY_COVER_SQL}'),
    # Covering index for /api/stats/categories: its GROUP BY category averages
    # read 13 score columns and the per-category top camera / lens read two more,
    # so the whole request is answered from the index (6.8 GB of table pages
    # without it). Every column the statement names must be in this list
    # (tests/test_stats_category_plan.py pins it).
    ('idx_stats_categories', 'photos',
     'category, aggregate, aesthetic, comp_score, tech_sharpness, color_score, '
     'exposure_score, iso, f_stop, focal_length_35mm, focal_length, face_quality, '
     'contrast_score, camera_model, lens_model'),
]

# Photo tags lookup table for fast exact-match queries (replaces LIKE '%tag%')
PHOTO_TAGS_COLUMNS = [
    ('photo_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('tag', 'TEXT NOT NULL'),
]

PHOTO_TAGS_INDEXES = [
    ('idx_photo_tags_tag', 'photo_tags', 'tag'),
    ('idx_photo_tags_path', 'photo_tags', 'photo_path'),
]

# User-authored tags: a side table, never a `photos` column, because
# save_photo/save_photos_batch rewrite the photo row on rescan and the tagger
# rewrites `photos.tags` on every retag. `source` records who wrote the row:
# 'user' (viewer editor) or 'xmp' (sidecar keyword import). Tags are global in
# multi-user mode; `created_by` is informational (NULL in single-user mode).
# Readers union this table with the AI tags at read time (never mirrored).
PHOTO_MANUAL_TAGS_COLUMNS = [
    ('photo_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('tag', 'TEXT NOT NULL'),
    ('source', "TEXT NOT NULL CHECK(source IN ('user','xmp'))"),
    ('created_by', 'TEXT'),
    ('created_at', "TEXT DEFAULT (datetime('now'))"),
]

PHOTO_MANUAL_TAGS_INDEXES = [
    ('idx_photo_manual_tags_tag', 'photo_manual_tags', 'tag'),
]

# Pairwise comparison results for weight optimization
COMPARISONS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('photo_a_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('photo_b_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('winner', "TEXT NOT NULL CHECK (winner IN ('a', 'b', 'tie', 'skip'))"),
    ('category', 'TEXT'),
    ('timestamp', "TEXT DEFAULT (datetime('now'))"),
    ('session_id', 'TEXT'),
    ('user_id', 'TEXT'),  # NULL for legacy pre-multi-user data
    # 'vote' = explicit A/B vote, 'culling' = derived from burst/similar culling,
    # 'rating' = synthetic pair from star ratings/favorites
    ('source', "TEXT NOT NULL DEFAULT 'vote'"),
]

COMPARISONS_INDEXES = [
    ('idx_comparisons_photo_a', 'comparisons', 'photo_a_path'),
    ('idx_comparisons_photo_b', 'comparisons', 'photo_b_path'),
    ('idx_comparisons_timestamp', 'comparisons', 'timestamp DESC'),
    ('idx_comparisons_category', 'comparisons', 'category'),
    ('idx_comparisons_source', 'comparisons', 'source'),
]

# Learned scores from Bradley-Terry model
LEARNED_SCORES_COLUMNS = [
    ('photo_path', 'TEXT PRIMARY KEY REFERENCES photos(path) ON DELETE CASCADE'),
    ('learned_score', 'REAL NOT NULL'),
    ('comparison_count', 'INTEGER DEFAULT 0'),
    ('category', 'TEXT'),
    ('updated_at', "TEXT DEFAULT (datetime('now'))"),
    ('user_id', 'TEXT'),  # NULL for legacy pre-multi-user data
]

LEARNED_SCORES_INDEXES = [
    ('idx_learned_scores_score', 'learned_scores', 'learned_score DESC'),
    ('idx_learned_scores_category', 'learned_scores', 'category'),
]

# Rejected merge suggestions — person-merge pairs the user dismissed, so the
# merge analyzer stops re-proposing them. Stored canonically (person_a_id < person_b_id).
REJECTED_MERGE_SUGGESTIONS_COLUMNS = [
    ('person_a_id', 'INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE'),
    ('person_b_id', 'INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE'),
    ('rejected_at', "TEXT DEFAULT (datetime('now'))"),
]

# Weight optimization history
WEIGHT_OPTIMIZATION_RUNS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('timestamp', "TEXT DEFAULT (datetime('now'))"),
    ('category', 'TEXT'),
    ('comparisons_used', 'INTEGER'),
    ('old_weights', 'TEXT'),
    ('new_weights', 'TEXT'),
    ('mse_before', 'REAL'),
    ('mse_after', 'REAL'),
]

WEIGHT_OPTIMIZATION_RUNS_INDEXES = [
    ('idx_optimization_timestamp', 'weight_optimization_runs', 'timestamp DESC'),
    ('idx_optimization_category', 'weight_optimization_runs', 'category'),
]

# Scan run bookkeeping: one row per scan invocation, plus per-file failures
SCAN_RUNS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('started_at', "TEXT DEFAULT (datetime('now'))"),
    ('finished_at', 'TEXT'),
    ('status', "TEXT NOT NULL DEFAULT 'running'"),  # running|completed|interrupted|failed
    ('mode', 'TEXT'),          # multi-pass|single-pass|pass:<name>
    ('args_json', 'TEXT'),     # directories + relevant flags for --resume
    ('total_files', 'INTEGER'),
    ('processed_files', 'INTEGER DEFAULT 0'),
    ('failed_files', 'INTEGER DEFAULT 0'),
    ('heartbeat_at', 'TEXT'),  # last liveness write; lets --resume reclaim hard-crashed runs
]

SCAN_FAILURES_COLUMNS = [
    ('scan_run_id', 'INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE'),
    ('path', 'TEXT NOT NULL'),
    ('stage', 'TEXT'),         # load|decode_timeout|score|save
    ('error', 'TEXT'),
    ('timestamp', "TEXT DEFAULT (datetime('now'))"),
]

SCAN_RUNS_INDEXES = [
    ('idx_scan_runs_status', 'scan_runs', 'status'),
    ('idx_scan_failures_run', 'scan_failures', 'scan_run_id'),
]

# Photos a supplementary IQA model answered "no" to on purpose, so --recompute-iqa
# stops re-attempting them on every run (TOPIQ NR-Face: "No face detected" by
# pyiqa's own detector on the thumbnail, though InsightFace found a face on the
# full image). A side table, not a photos column, because a full-row save rewrites
# photos wholesale. For the opposite reason it cannot simply be trusted: the save
# is an UPSERT, which never cascades, so a row here SURVIVES a rescan. It is
# therefore valid only while scan_fingerprint still equals the photo's current
# IQA_SCAN_FINGERPRINT_SQL; a rescan rewrites scanned_at and the thumbnail and so
# invalidates every decline for that photo without anyone deleting a row. The
# fingerprint is nullable on purpose: NULL never equals anything, so a photo with
# no scanned_at is never "declined" (fails open, it is simply retried).
IQA_DECLINED_COLUMNS = [
    ('photo_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('model', 'TEXT NOT NULL'),
    ('scan_fingerprint', 'TEXT'),
]

# What identifies "this scan of this photo" for IQA_DECLINED_COLUMNS. length() of a
# BLOB reads the record header, not the BLOB. Qualified with ``photos.`` so it works
# both in a correlated subquery and in an INSERT ... SELECT FROM photos.
IQA_SCAN_FINGERPRINT_SQL = "photos.scanned_at || '|' || length(photos.thumbnail)"

# Stats cache table for precomputed aggregations (performance optimization)
STATS_CACHE_COLUMNS = [
    ('key', 'TEXT PRIMARY KEY'),
    ('value', 'TEXT'),  # JSON for complex values
    ('updated_at', 'REAL'),  # Unix timestamp
]

# Weight configuration snapshots for undo/restore functionality
WEIGHT_CONFIG_SNAPSHOTS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('timestamp', "TEXT DEFAULT (datetime('now'))"),
    ('category', 'TEXT'),
    ('weights', 'TEXT NOT NULL'),  # JSON of weight config
    ('description', 'TEXT'),  # Optional user description
    ('accuracy_before', 'REAL'),  # Accuracy when snapshot was created
    ('accuracy_after', 'REAL'),  # Accuracy after weights were applied
    ('comparisons_used', 'INTEGER'),
    ('created_by', 'TEXT'),  # 'manual' or 'auto_optimization'
    # The category's modifiers.bonus when the snapshot was taken, so undo restores
    # the bonus an optimizer apply re-centred together with the weights. NULL = not
    # recorded (rows written before the column, calibrate.py snapshots, categories
    # with no categories[] entry): a restore then leaves the bonus alone.
    ('category_bonus', 'REAL'),
]

WEIGHT_CONFIG_SNAPSHOTS_INDEXES = [
    ('idx_snapshots_timestamp', 'weight_config_snapshots', 'timestamp DESC'),
    ('idx_snapshots_category', 'weight_config_snapshots', 'category'),
]

# Recommendation history for oscillation detection
RECOMMENDATION_HISTORY_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('run_timestamp', "TEXT DEFAULT (datetime('now'))"),
    ('config_version_hash', 'TEXT'),
    ('issue_type', 'TEXT NOT NULL'),
    ('target_category', 'TEXT'),
    ('target_key', 'TEXT'),
    ('old_value', 'REAL'),
    ('proposed_value', 'REAL'),
    ('was_applied', 'INTEGER DEFAULT 0'),
]

RECOMMENDATION_HISTORY_INDEXES = [
    ('idx_rec_history_timestamp', 'recommendation_history', 'run_timestamp DESC'),
    ('idx_rec_history_target', 'recommendation_history', 'target_category, target_key'),
]

# Albums for user-curated photo collections
ALBUMS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('user_id', 'TEXT'),
    ('name', 'TEXT NOT NULL'),
    ('description', 'TEXT'),
    ('cover_photo_path', 'TEXT'),
    ('is_smart', 'INTEGER DEFAULT 0'),
    ('smart_filter_json', 'TEXT'),
    ('share_token', 'TEXT'),
    ('created_at', "TEXT DEFAULT (datetime('now'))"),
    ('updated_at', "TEXT DEFAULT (datetime('now'))"),
    ('scoring_context', 'TEXT'),  # the album's declared scoring context, materialized onto member photos
]

ALBUM_PHOTOS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('album_id', 'INTEGER NOT NULL'),
    ('photo_path', 'TEXT NOT NULL'),
    ('position', 'INTEGER DEFAULT 0'),
    ('added_at', "TEXT DEFAULT (datetime('now'))"),
]

# Client proofing picks on shared albums — fully isolated from the owner's
# ratings (photos.is_favorite / user_preferences are never written by proofing)
ALBUM_CLIENT_PICKS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('album_id', 'INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE'),
    ('photo_path', 'TEXT NOT NULL'),
    ('picked', 'INTEGER DEFAULT 1'),
    ('comment', 'TEXT'),
    ('client_name', 'TEXT'),
    ('created_at', "TEXT DEFAULT (datetime('now'))"),
    ('updated_at', "TEXT DEFAULT (datetime('now'))"),
]

ALBUM_INDEXES = [
    ('idx_albums_user', 'albums', 'user_id'),
    ('idx_albums_share_token', 'albums', 'share_token'),
    ('idx_album_photos_album', 'album_photos', 'album_id'),
    ('idx_album_photos_path', 'album_photos', 'photo_path'),
    ('idx_album_photos_position', 'album_photos', 'album_id, position'),
    ('idx_album_client_picks_album', 'album_client_picks', 'album_id'),
]

# Named GPS places belong to an editor owner, independent of photos/rescans.
SAVED_PLACES_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY'),
    ('owner', 'TEXT NOT NULL'),
    ('name', 'TEXT NOT NULL'),
    ('normalized_name', 'TEXT NOT NULL'),
    ('latitude', 'REAL NOT NULL'),
    ('longitude', 'REAL NOT NULL'),
    ('last_used_at', 'TEXT'),
    ('use_count', 'INTEGER NOT NULL DEFAULT 0'),
]

RECENT_PLACES_COLUMNS = [
    ('owner', 'TEXT NOT NULL'),
    ('latitude', 'REAL NOT NULL'),
    ('longitude', 'REAL NOT NULL'),
    ('last_used_at', 'TEXT NOT NULL'),
]


# Reverse geocoding cache — grid-cell to place name mapping
LOCATION_NAMES_COLUMNS = [
    ('lat_grid', 'REAL NOT NULL'),
    ('lon_grid', 'REAL NOT NULL'),
    ('city', 'TEXT'),
    ('region', 'TEXT'),
    ('country', 'TEXT'),
    ('display_name', 'TEXT'),
]

USER_PREFERENCES_COLUMNS = [
    ('user_id', 'TEXT NOT NULL'),
    ('photo_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('star_rating', 'INTEGER DEFAULT 0 CHECK (star_rating >= 0 AND star_rating <= 5)'),
    ('is_favorite', 'INTEGER DEFAULT 0 CHECK (is_favorite IN (0, 1))'),
    ('is_rejected', 'INTEGER DEFAULT 0 CHECK (is_rejected IN (0, 1))'),
    ('is_kept', 'INTEGER DEFAULT 0 CHECK (is_kept IN (0, 1))'),
]

USER_PREFERENCES_INDEXES = [
    ('idx_user_prefs_user', 'user_preferences', 'user_id'),
    ('idx_user_prefs_path', 'user_preferences', 'photo_path'),
    ('idx_user_prefs_fav', 'user_preferences', 'user_id, is_favorite'),
    ('idx_user_prefs_rating', 'user_preferences', 'user_id, star_rating'),
]

# Identity constraints share the registry used by schema diagnostics. Manual
# UUIDs identify annotations only; automatic rows do not own this namespace.
IDENTITY_INDEXES = [
    ('idx_person_key', 'persons', 'person_key'),
    ('idx_manual_face_key', 'faces', 'manual_key'),
]

# Agent (MCP) bearer tokens. A side table, never a column on `photos`. Only the
# SHA-256 of the token is stored (plus a display prefix); `user_gen` and
# `edition_gen` snapshot the owner's credentials at mint (the password hash /
# the viewer and edition password generations) so a rotated password or a
# deleted user kills the token on its next call. The ROLE is not in the
# snapshot: it is read live, so a demotion lowers the token's effective level
# and a promotion never raises it past the level it was minted at.
MCP_TOKENS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('user_id', 'TEXT NOT NULL'),
    ('name', 'TEXT NOT NULL'),
    ('token_prefix', 'TEXT NOT NULL'),
    ('token_hash', 'TEXT NOT NULL UNIQUE'),
    ('level', "TEXT NOT NULL CHECK(level IN ('readonly','user','edition'))"),
    ('user_gen', 'TEXT NOT NULL'),
    ('edition_gen', "TEXT NOT NULL DEFAULT ''"),
    ('created_at', 'TEXT NOT NULL'),
    ('last_used_at', 'TEXT'),
    ('revoked', 'INTEGER NOT NULL DEFAULT 0'),
    ('revoked_at', 'TEXT'),
    # Level of the session that minted the token; NULL (pre-column rows) counts as readonly.
    ('minted_level', 'TEXT'),
]

MCP_TOKENS_INDEXES = [
    ('idx_mcp_tokens_user', 'mcp_tokens', 'user_id'),
]

# Which rating labels an assistant left behind, so the rating-derived comparisons
# (`optimization/label_pairs.py`) never treat them as the user's taste. A side table, not a column on
# `photos`, written by the rating routes themselves when the request is an agent's (an internal `mcp` JWT).
# The row stores the (star_rating, is_favorite, is_rejected) tuple the assistant left; a label that no
# longer equals it was changed by someone else since and counts again. `user_id` is '' in single-user mode.
# The viewer database export drops this table.
RATING_PROVENANCE_COLUMNS = [
    ('user_id', "TEXT NOT NULL DEFAULT ''"),
    ('photo_path', 'TEXT NOT NULL'),
    ('star_rating', 'INTEGER NOT NULL DEFAULT 0'),
    ('is_favorite', 'INTEGER NOT NULL DEFAULT 0'),
    ('is_rejected', 'INTEGER NOT NULL DEFAULT 0'),
]

# Authoritative registry of every CREATE INDEX group. init_database creates all
# of these and db.info.get_schema_info counts them, so the two can never
# disagree on how many indexes the schema declares (they did before: info
# under-reported by the scan-runs / recommendation / album / user-preference
# groups). INDEXES stays first: the migration builds ALL_INDEX_GROUPS[1:], and
# INDEXES is built after it commits (create_photo_indexes), one index at a time.
ALL_INDEX_GROUPS = [
    INDEXES,
    PHOTO_TAGS_INDEXES,
    PHOTO_MANUAL_TAGS_INDEXES,
    COMPARISONS_INDEXES,
    LEARNED_SCORES_INDEXES,
    WEIGHT_OPTIMIZATION_RUNS_INDEXES,
    WEIGHT_CONFIG_SNAPSHOTS_INDEXES,
    SCAN_RUNS_INDEXES,
    RECOMMENDATION_HISTORY_INDEXES,
    ALBUM_INDEXES,
    USER_PREFERENCES_INDEXES,
    IDENTITY_INDEXES,
    MCP_TOKENS_INDEXES,
]

# Sticky per-photo scoring context / category override — a side table, not
# columns on `photos`, because save_photo/save_photos_batch write photos via
# INSERT OR REPLACE (processing/scorer.py), which would silently wipe any new
# column on that row on the next rescan. photo_scoring_overrides is untouched
# by a photo rescan; processing.scorer.Facet._determine_photo_category is the
# single choke point that reads it.
PHOTO_SCORING_OVERRIDES_COLUMNS = [
    ('photo_path', 'TEXT PRIMARY KEY REFERENCES photos(path) ON DELETE CASCADE'),
    ('scoring_context', 'TEXT'),
    ('category_override', 'TEXT'),
    ('source', 'TEXT'),
    ('created_at', "TEXT DEFAULT (datetime('now'))"),
    ('created_by', 'TEXT'),
]

# Sticky per-set panorama override — a side table for the same reason as
# photo_scoring_overrides, and one more: utils.panorama clears and rewrites
# photos.sequence_* on every pass, so a correction stored there would not
# survive its next run. `sequence_kind` NULL suppresses a detected set ("this is
# not a panorama"); a kind forces one ("these frames are one"). Keyed on the
# member path, never on sequence_group_id, which is renumbered from 1 each pass:
# override_group_key ties the members of a forced set together across renumbering.
# utils.panorama.resolve_segments is the single choke point that applies them.
PHOTO_SEQUENCE_OVERRIDES_COLUMNS = [
    ('photo_path', 'TEXT PRIMARY KEY REFERENCES photos(path) ON DELETE CASCADE'),
    ('sequence_kind', 'TEXT'),
    ('override_group_key', 'TEXT'),
    ('source', 'TEXT'),
    ('created_at', "TEXT DEFAULT (datetime('now'))"),
    ('created_by', 'TEXT'),
    # When the detector last acted on this correction. NULL means the labels do
    # not reflect it yet, which is what the viewer's "pending" badge, chip and
    # re-run banner report. Without it the row's mere existence had to stand for
    # "pending", so those never cleared: the correction stays stored for as long
    # as it applies, so the only way to silence them was to delete it -- undoing
    # the correction to stop being told it was waiting.
    ('applied_at', 'TEXT'),
]

# Cache of the panorama detector's RAW per-run measurements, keyed by a content
# signature of the candidate run. Derived data: one panorama pass rebuilds it, so
# it is neither merged nor exported. `segments` is the detector's output before
# overrides are applied (labels are always re-derived from it plus the current
# overrides); `fingerprint` is the settings fingerprint it was measured under.
PANORAMA_RUN_CACHE_COLUMNS = [
    ('signature', 'TEXT PRIMARY KEY'),
    ('fingerprint', 'TEXT NOT NULL'),
    ('segments', 'TEXT NOT NULL'),
    ('measured_at', 'REAL'),
]

# FTS5 full-text search virtual table and sync triggers.
#
# Covering schema: every field the gallery free-text search ever scanned via
# LIKE is now an FTS5 column, so the search clause collapses to a single
# `photos_fts MATCH ?`. Person names are joined separately at query time
# because they live in the `persons` table.
PHOTOS_FTS_COLUMNS = [
    'filename',
    'caption',
    'caption_translated',
    'tags',
    'camera_model',
    'lens_model',
    'category',
    'ocr_text',
]

PHOTOS_FTS_CREATE = """
CREATE VIRTUAL TABLE IF NOT EXISTS photos_fts USING fts5(
    path UNINDEXED,
    filename,
    caption,
    caption_translated,
    tags,
    camera_model,
    lens_model,
    category,
    ocr_text,
    content='photos',
    content_rowid='rowid'
)
"""

_FTS_INSERT_COLS = "rowid, path, " + ", ".join(PHOTOS_FTS_COLUMNS)
_FTS_NEW_VALUES = "new.rowid, new.path, " + ", ".join(f"new.{c}" for c in PHOTOS_FTS_COLUMNS)
_FTS_OLD_VALUES = "old.rowid, old.path, " + ", ".join(f"old.{c}" for c in PHOTOS_FTS_COLUMNS)
_FTS_UPDATE_OF = ", ".join(PHOTOS_FTS_COLUMNS)

PHOTOS_FTS_TRIGGERS = [
    f"""CREATE TRIGGER IF NOT EXISTS photos_fts_ai AFTER INSERT ON photos BEGIN
    INSERT INTO photos_fts({_FTS_INSERT_COLS})
    VALUES ({_FTS_NEW_VALUES});
END""",
    f"""CREATE TRIGGER IF NOT EXISTS photos_fts_ad AFTER DELETE ON photos BEGIN
    INSERT INTO photos_fts(photos_fts, {_FTS_INSERT_COLS})
    VALUES ('delete', {_FTS_OLD_VALUES});
END""",
    f"""CREATE TRIGGER IF NOT EXISTS photos_fts_au AFTER UPDATE OF {_FTS_UPDATE_OF} ON photos BEGIN
    INSERT INTO photos_fts(photos_fts, {_FTS_INSERT_COLS})
    VALUES ('delete', {_FTS_OLD_VALUES});
    INSERT INTO photos_fts({_FTS_INSERT_COLS})
    VALUES ({_FTS_NEW_VALUES});
END""",
]


def fts_schema_is_current(conn) -> bool:
    """Return True if the on-disk photos_fts table matches the current covering schema.

    Used at init time to detect the pre-covering schema (path, caption, tags only)
    and trigger a drop + recreate + rebuild so callers see the same column set
    they expect from `PHOTOS_FTS_COLUMNS`.
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='photos_fts'"
    ).fetchone()
    if row is None:
        return True
    existing = {r[1] for r in conn.execute("PRAGMA table_info(photos_fts)").fetchall()}
    needed = {'path', *PHOTOS_FTS_COLUMNS}
    return needed.issubset(existing)


def _build_create_table_sql(table_name, columns, constraints=None):
    """Build CREATE TABLE IF NOT EXISTS SQL from column definitions."""
    col_defs = [f'{name} {typedef}' for name, typedef in columns]
    if constraints:
        col_defs.extend(constraints)
    cols_sql = ',\n                    '.join(col_defs)
    return f'''CREATE TABLE IF NOT EXISTS {table_name} (
                    {cols_sql}
                )'''


def _migrate_add_missing_columns(conn, table_name, columns):
    """Add any missing columns to an existing table.

    Args:
        conn: SQLite connection
        table_name: Name of the table to migrate
        columns: List of (name, type_definition) tuples defining expected columns
    """
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    existing_cols = {row[1] for row in cursor.fetchall()}

    for col_name, col_type in columns:
        if col_name not in existing_cols:
            # SQLite accepts NOT NULL with a constant DEFAULT in ADD COLUMN and
            # backfills existing rows; fall back to the base type for typedefs
            # it rejects (e.g. REFERENCES with non-constant defaults)
            base_type = col_type.split()[0] if col_type else 'TEXT'
            candidates = [col_type] if col_type and col_type != base_type else []
            candidates.append(base_type)
            for typedef in candidates:
                try:
                    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {typedef}")
                    logger.info("  Added column: %s.%s", table_name, col_name)
                    break
                except sqlite3.OperationalError as e:
                    if 'duplicate column name' in str(e).lower():
                        break
                    if typedef == candidates[-1]:
                        logger.warning("  Could not add %s.%s: %s", table_name, col_name, e)


# Every base (non-virtual) table and its column list. The additive-column sweep
# in init_database walks this registry so a new column added to ANY table lands
# on upgrade — previously only a subset of tables were swept, so a future column
# on the others would have been created on fresh DBs but never on existing ones.
# Virtual tables (photos_fts, photos_vec) are excluded: they are recreated, not
# ALTERed. Order mirrors the CREATE TABLE order in init_database.
_MIGRATED_TABLES = [
    ('photos', PHOTOS_COLUMNS),
    ('faces', FACES_COLUMNS),
    ('manual_face_deletions', MANUAL_FACE_DELETIONS_COLUMNS),
    ('persons', PERSONS_COLUMNS),
    ('photo_tags', PHOTO_TAGS_COLUMNS),
    ('photo_manual_tags', PHOTO_MANUAL_TAGS_COLUMNS),
    ('mcp_tokens', MCP_TOKENS_COLUMNS),
    ('rating_provenance', RATING_PROVENANCE_COLUMNS),
    ('comparisons', COMPARISONS_COLUMNS),
    ('learned_scores', LEARNED_SCORES_COLUMNS),
    ('rejected_merge_suggestions', REJECTED_MERGE_SUGGESTIONS_COLUMNS),
    ('weight_optimization_runs', WEIGHT_OPTIMIZATION_RUNS_COLUMNS),
    ('stats_cache', STATS_CACHE_COLUMNS),
    ('weight_config_snapshots', WEIGHT_CONFIG_SNAPSHOTS_COLUMNS),
    ('recommendation_history', RECOMMENDATION_HISTORY_COLUMNS),
    ('albums', ALBUMS_COLUMNS),
    ('album_photos', ALBUM_PHOTOS_COLUMNS),
    ('album_client_picks', ALBUM_CLIENT_PICKS_COLUMNS),
    ('location_names', LOCATION_NAMES_COLUMNS),
    ('saved_places', SAVED_PLACES_COLUMNS),
    ('recent_places', RECENT_PLACES_COLUMNS),
    ('user_preferences', USER_PREFERENCES_COLUMNS),
    ('photo_scoring_overrides', PHOTO_SCORING_OVERRIDES_COLUMNS),
    ('photo_sequence_overrides', PHOTO_SEQUENCE_OVERRIDES_COLUMNS),
    ('panorama_run_cache', PANORAMA_RUN_CACHE_COLUMNS),
    ('face_reextract_snapshot', FACE_REEXTRACT_SNAPSHOT_COLUMNS),
    ('scan_runs', SCAN_RUNS_COLUMNS),
    ('scan_failures', SCAN_FAILURES_COLUMNS),
    ('iqa_declined', IQA_DECLINED_COLUMNS),
]


def _comparisons_unique_has_user_id(conn):
    """True if the comparisons UNIQUE constraint already scopes by user_id.

    Reads the stored CREATE SQL rather than guessing from a version stamp, so
    the recreate below is idempotent regardless of how a DB reached its state.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='comparisons'"
    ).fetchone()
    if not row or not row[0]:
        return True  # no table yet — the fresh CREATE already uses the new shape
    match = re.search(r'unique\s*\(([^)]*)\)', row[0], re.IGNORECASE)
    return bool(match) and 'user_id' in match.group(1).lower()


def _migrate_comparisons_user_id(conn):
    """Widen comparisons UNIQUE to (photo_a_path, photo_b_path, user_id).

    The original UNIQUE(photo_a_path, photo_b_path) is user-blind, so a second
    user's INSERT OR REPLACE vote on the same pair evicted the first user's row.
    SQLite cannot ALTER a constraint, so rebuild the table and copy every row
    (the old 2-column unique is strictly tighter than the new 3-column one, so
    no copied row can collide). Guarded by _comparisons_unique_has_user_id, so
    it is a no-op once applied and safe to re-run. Must run before the
    comparisons indexes are (re)created in init_database.

    Foreign keys are disabled around the copy (the standard SQLite table-rebuild
    recipe): the recreate only relocates rows that already existed, so it must
    preserve them verbatim rather than newly enforcing the photos FK against a
    row an older, FK-off write may have orphaned.
    """
    if _comparisons_unique_has_user_id(conn):
        return
    logger.info("Migrating comparisons UNIQUE constraint to include user_id...")
    old_cols = {r[1] for r in conn.execute("PRAGMA table_info(comparisons)").fetchall()}
    common = [name for name, _ in COMPARISONS_COLUMNS if name in old_cols]
    col_list = ', '.join(common)

    fk_on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    if fk_on:
        conn.commit()  # PRAGMA foreign_keys is a no-op inside a transaction
        conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("DROP TABLE IF EXISTS comparisons_new")
        conn.execute(_build_create_table_sql(
            'comparisons_new', COMPARISONS_COLUMNS,
            constraints=['UNIQUE(photo_a_path, photo_b_path, user_id)']))
        conn.execute(
            f"INSERT INTO comparisons_new ({col_list}) SELECT {col_list} FROM comparisons")
        conn.execute("DROP TABLE comparisons")
        conn.execute("ALTER TABLE comparisons_new RENAME TO comparisons")
    finally:
        if fk_on:
            conn.commit()
            conn.execute("PRAGMA foreign_keys=ON")
    logger.info("comparisons table rebuilt with user-scoped UNIQUE (rows preserved)")


# Schema version stamped into PRAGMA user_version. The additive column sweep
# (_migrate_add_missing_columns) still bootstraps every DB to the current
# column shape; this ladder exists ONLY for non-additive ops the sweep cannot
# express — renames, type changes, data backfills, index/constraint drops.
SCHEMA_VERSION = 1

# Ordered ladder of non-additive migrations: (target_version, fn(conn)).
# Each fn MUST be idempotent and SHOULD call db.maintenance.backup_database
# before a destructive step. Empty today — the mechanism ships ahead of need.
MIGRATIONS: list[tuple[int, Callable[[Any], None]]] = []


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _run_migration_ladder(conn, is_fresh):
    """Bring an existing DB up the version ladder, or stamp a fresh one.

    A fresh DB is built at the latest shape by CREATE TABLE, so it skips the
    ladder and is stamped straight to SCHEMA_VERSION. An existing DB runs every
    pending step from its stored user_version in order. Note: in legacy sqlite3
    mode, DDL (ALTER/DROP/CREATE) and ``PRAGMA user_version`` auto-commit
    outside the ``with conn`` transaction, so a step that raises is NOT rolled
    back and can leave a half-applied schema. Each migration in MIGRATIONS must
    therefore guard itself (own savepoint, or call backup_database first).
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if not is_fresh and current < SCHEMA_VERSION:
        for target, fn in sorted(MIGRATIONS, key=lambda m: m[0]):
            if target > current:
                logger.info("Running schema migration to v%d: %s",
                            target, getattr(fn, '__name__', repr(fn)))
                fn(conn)
    if current < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    elif current > SCHEMA_VERSION:
        logger.warning(
            "Database user_version %d is newer than this code's SCHEMA_VERSION %d; "
            "leaving it untouched to avoid downgrading a DB written by newer Facet.",
            current, SCHEMA_VERSION)


def init_database(db_path='photo_scores_pro.db', build_photo_indexes=True):
    """
    Initialize the database schema (idempotent).

    Creates all tables and indexes using CREATE IF NOT EXISTS.
    Safe to call on existing databases - automatically adds new columns.

    Two phases. The migration (tables, columns, every index group but ``INDEXES``,
    the photos_fts table and its rebuild, the version ladder) commits as one
    transaction, so an interrupted run never leaves a half-applied step such as
    an empty photos_fts that the next run would take for current. On a schema
    that is already current it takes no write lock at all, so it never waits on
    another connection's CREATE INDEX. Then ``create_photo_indexes`` builds each
    missing ``INDEXES`` entry as its own autocommit statement (a large library
    takes minutes per index): a run killed mid-build keeps every index it
    finished and the next call resumes. ``analyze_photos_if_unanalyzed`` follows.

    Args:
        db_path: Path to the SQLite database file
        build_photo_indexes: When False, stop after the migration: no ``INDEXES``
            entry is built and nothing is analyzed. The viewer passes False and
            builds them on a background thread under the library lock
            (``api.schema_startup``).
    """
    # closing() closes the connection; the inner `conn` block keeps the commit on success.
    with closing(sqlite3.connect(db_path)) as conn, conn:
        apply_pragmas(conn)

        # Detect a brand-new DB before any CREATE runs, so the version ladder
        # can stamp it to SCHEMA_VERSION instead of replaying historical steps.
        is_fresh = not _table_exists(conn, 'photos')

        conn.execute(_build_create_table_sql(
            'saved_places', SAVED_PLACES_COLUMNS,
            constraints=['UNIQUE(owner, normalized_name)']))
        conn.execute(_build_create_table_sql(
            'recent_places', RECENT_PLACES_COLUMNS,
            constraints=['PRIMARY KEY(owner, latitude, longitude)']))

        # Create photos table
        conn.execute(_build_create_table_sql('photos', PHOTOS_COLUMNS))

        # Create faces table with unique constraint
        conn.execute(_build_create_table_sql(
            'faces',
            FACES_COLUMNS,
            constraints=['UNIQUE(photo_path, face_index)']
        ))
        conn.execute(_build_create_table_sql('manual_face_deletions', MANUAL_FACE_DELETIONS_COLUMNS))

        # Create persons table
        conn.execute(_build_create_table_sql('persons', PERSONS_COLUMNS))

        # Create photo_tags lookup table for fast tag queries
        conn.execute(_build_create_table_sql(
            'photo_tags',
            PHOTO_TAGS_COLUMNS,
            constraints=['PRIMARY KEY (photo_path, tag)']
        ))

        # Create photo_manual_tags (user-authored tags; side table, survives rescans)
        conn.execute(_build_create_table_sql(
            'photo_manual_tags',
            PHOTO_MANUAL_TAGS_COLUMNS,
            constraints=['PRIMARY KEY (photo_path, tag)']
        ))

        # Create mcp_tokens (agent bearer tokens, hash only; side table)
        conn.execute(_build_create_table_sql('mcp_tokens', MCP_TOKENS_COLUMNS))

        # Create rating_provenance (which rating labels an assistant left; side table)
        conn.execute(_build_create_table_sql(
            'rating_provenance', RATING_PROVENANCE_COLUMNS, constraints=['PRIMARY KEY (user_id, photo_path)']))

        # Create comparisons table for pairwise comparison feedback. The UNIQUE
        # is user-scoped so one user's vote never clobbers another's; existing
        # DBs on the old user-blind constraint are rebuilt by
        # _migrate_comparisons_user_id below.
        conn.execute(_build_create_table_sql(
            'comparisons',
            COMPARISONS_COLUMNS,
            constraints=['UNIQUE(photo_a_path, photo_b_path, user_id)']
        ))

        # Create learned_scores table for Bradley-Terry derived scores
        conn.execute(_build_create_table_sql(
            'learned_scores',
            LEARNED_SCORES_COLUMNS
        ))

        # Create rejected_merge_suggestions table (dismissed person-merge pairs)
        conn.execute(_build_create_table_sql(
            'rejected_merge_suggestions',
            REJECTED_MERGE_SUGGESTIONS_COLUMNS,
            constraints=['PRIMARY KEY (person_a_id, person_b_id)']
        ))

        # Create weight_optimization_runs table for tracking optimization history
        conn.execute(_build_create_table_sql(
            'weight_optimization_runs',
            WEIGHT_OPTIMIZATION_RUNS_COLUMNS
        ))

        # Create stats_cache table for precomputed statistics
        conn.execute(_build_create_table_sql(
            'stats_cache',
            STATS_CACHE_COLUMNS
        ))

        # Create weight_config_snapshots table for undo/restore
        conn.execute(_build_create_table_sql(
            'weight_config_snapshots',
            WEIGHT_CONFIG_SNAPSHOTS_COLUMNS
        ))

        # Create recommendation_history table for oscillation detection
        conn.execute(_build_create_table_sql(
            'recommendation_history',
            RECOMMENDATION_HISTORY_COLUMNS
        ))

        # Create albums and album_photos tables
        conn.execute(_build_create_table_sql('albums', ALBUMS_COLUMNS))

        conn.execute(_build_create_table_sql(
            'album_photos',
            ALBUM_PHOTOS_COLUMNS,
            constraints=['UNIQUE(album_id, photo_path)']
        ))

        conn.execute(_build_create_table_sql(
            'album_client_picks',
            ALBUM_CLIENT_PICKS_COLUMNS,
            constraints=['UNIQUE(album_id, photo_path)']
        ))

        # Create location_names cache table for reverse geocoding
        conn.execute(_build_create_table_sql(
            'location_names',
            LOCATION_NAMES_COLUMNS,
            constraints=['PRIMARY KEY (lat_grid, lon_grid)']
        ))

        # Create user_preferences table for per-user ratings in multi-user mode
        conn.execute(_build_create_table_sql(
            'user_preferences',
            USER_PREFERENCES_COLUMNS,
            constraints=['PRIMARY KEY (user_id, photo_path)']
        ))

        # Create photo_scoring_overrides table for sticky per-photo scoring
        # context / category overrides
        conn.execute(_build_create_table_sql(
            'photo_scoring_overrides', PHOTO_SCORING_OVERRIDES_COLUMNS
        ))

        # Create photo_sequence_overrides table for sticky per-set panorama
        # corrections, which must outlive the detector's clear-and-rewrite pass
        conn.execute(_build_create_table_sql(
            'photo_sequence_overrides', PHOTO_SEQUENCE_OVERRIDES_COLUMNS
        ))

        # Create panorama_run_cache table (derived; rebuilt by one panorama pass)
        conn.execute(_build_create_table_sql(
            'panorama_run_cache', PANORAMA_RUN_CACHE_COLUMNS
        ))

        conn.execute(_build_create_table_sql(
            'face_reextract_snapshot', FACE_REEXTRACT_SNAPSHOT_COLUMNS
        ))

        # Create scan bookkeeping tables
        conn.execute(_build_create_table_sql('scan_runs', SCAN_RUNS_COLUMNS))
        conn.execute(_build_create_table_sql(
            'scan_failures', SCAN_FAILURES_COLUMNS,
            constraints=['PRIMARY KEY (scan_run_id, path)']
        ))
        conn.execute(_build_create_table_sql(
            'iqa_declined', IQA_DECLINED_COLUMNS,
            constraints=['PRIMARY KEY (photo_path, model)']
        ))

        # Non-additive rebuild before the additive sweep and index creation:
        # widen the comparisons UNIQUE to include user_id on DBs still carrying
        # the user-blind constraint (rows preserved, no-op once applied).
        _migrate_comparisons_user_id(conn)

        # Additive column sweep across EVERY base table (registry-driven, so a
        # future column on any table lands on upgrade). Runs before index
        # creation because new indexes may target columns added here (e.g.
        # comparisons.source), and before the photos_vec init below because that
        # reads photos.clip_embedding, which the sweep backfills on old DBs.
        for table_name, columns in _MIGRATED_TABLES:
            _migrate_add_missing_columns(conn, table_name, columns)

        # Shared pre-upgrade copies share numeric identities. Every NEW person
        # gets a random key, including inserts by scanners and older callers.
        if conn.execute('SELECT 1 FROM persons WHERE person_key IS NULL LIMIT 1').fetchone():
            conn.execute("UPDATE persons SET person_key='legacy:' || id WHERE person_key IS NULL")
        old_manual_index = next((r for r in conn.execute('PRAGMA index_list(faces)')
                                 if r[1] == 'idx_manual_face_key'), None)
        if old_manual_index is not None and not old_manual_index[4]:
            conn.execute('DROP INDEX idx_manual_face_key')
        conn.execute("""CREATE TRIGGER IF NOT EXISTS persons_assign_key AFTER INSERT ON persons
            WHEN NEW.person_key IS NULL BEGIN
              UPDATE persons SET person_key=lower(hex(randomblob(16))) WHERE id=NEW.id;
            END""")

        # A centroid that predates persons.centroid_model was averaged from ArcFace
        # embeddings (the only space that existed), so tag it. After this a NULL
        # centroid_model means only "no centroid yet".
        # Probe first: an UPDATE opens a write transaction even when it matches no
        # row, and the migration must not need the write lock on a current schema
        # (a viewer worker starting while another one holds it for a CREATE INDEX
        # would otherwise fail on busy_timeout).
        if conn.execute(
                "SELECT 1 FROM persons WHERE centroid IS NOT NULL AND centroid_model IS NULL "
                "LIMIT 1").fetchone():
            conn.execute(
                "UPDATE persons SET centroid_model = ? "
                "WHERE centroid IS NOT NULL AND centroid_model IS NULL",
                (ARCFACE_MODEL,))

        # Create photos_vec virtual table for vector search (requires sqlite-vec).
        # After the sweep so detect_embedding_dim can see clip_embedding.
        if HAS_SQLITE_VEC:
            _init_vec_table(conn)

        # Drop indexes that were superseded by a different shape, so DBs that
        # received the earlier version don't keep a now-unused index. The moment /
        # learned_score sorts were first shipped as (is_burst_lead, X) composites,
        # but the hide-bursts "OR IS NULL" filter defeats that shape (MULTI-INDEX
        # OR), so they are now standalone (X DESC, path) — see INDEXES above.
        # idx_qalign_score is here for the other reason: Q-Align was replaced by
        # Q-ReAlign, and the migration is additive-only, so the qalign_score
        # column itself survives on upgraded DBs (its data is still readable).
        # Dropping only its index stops a retired column from taxing every write.
        # idx_render_version never earned its keep: the pending-render count
        # (db.render_version.pending_render_predicate) compares the column
        # against a per-row CASE on sequence_kind, not a constant, so no
        # single- or multi-column shape on render_version is sargable for it —
        # EXPLAIN QUERY PLAN shows a full `SCAN photos` with or without the
        # index. Dropped rather than reshaped.
        # idx_gallery_date_asc is superseded by the wider idx_date_asc_cover (same
        # leading `date_taken ASC, path`, plus the columns the post-scan reads need),
        # so a library the first gallery-index release already upgraded drops its
        # narrow copy instead of maintaining two near-identical B-trees.
        # idx_qrealign_score, idx_deqa_score and idx_aesthetic_v25 are superseded by
        # idx_qrealign_sort, idx_deqa_sort and idx_aesthetic_v25_sort (X DESC, path).
        for stale_idx in ('idx_burst_moment', 'idx_burst_learned', 'idx_qalign_score',
                          'idx_render_version', 'idx_gallery_date_asc', 'idx_qrealign_score',
                          'idx_deqa_score', 'idx_aesthetic_v25'):
            conn.execute(f'DROP INDEX IF EXISTS {stale_idx}')

        # Create every remaining index group (photo_tags, comparisons,
        # learned_scores, weight-optimization, snapshots, scan_runs,
        # recommendation_history, albums, user_preferences). INDEXES is first in
        # the registry and is built after the migration commits (create_photo_indexes).
        for group in ALL_INDEX_GROUPS[1:]:
            for idx_name, table, column_expr in group:
                unique = 'UNIQUE ' if group is IDENTITY_INDEXES else ''
                predicate = ' WHERE is_manual=1' if idx_name == 'idx_manual_face_key' else ''
                conn.execute(
                    f'CREATE {unique}INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr}){predicate}'
                )

        # Create FTS5 full-text search table and sync triggers. If a previous
        # narrower schema is detected (caption+tags only), drop it so the
        # CREATE below installs the covering schema. The FTS data is then
        # repopulated by db.fts.rebuild_fts (or whoever rebuilds next).
        fts_existed = _table_exists(conn, 'photos_fts')
        fts_current = fts_schema_is_current(conn)
        fts_recreated = False
        if not (fts_existed and fts_current) and not conn.in_transaction:
            # The drop, the CREATE and the rebuild must commit together: DDL runs in
            # autocommit when no transaction is open (Python's legacy mode only
            # opens one before DML), and a run killed after the CREATE but before
            # the rebuild would commit an EMPTY photos_fts that every later run
            # takes for current, so text search silently found nothing.
            conn.execute("BEGIN")
        if not fts_current:
            logger.info("photos_fts schema outdated — dropping for recreate")
            for trigger in ('photos_fts_ai', 'photos_fts_ad', 'photos_fts_au'):
                conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            conn.execute("DROP TABLE IF EXISTS photos_fts")
            fts_recreated = True
        conn.execute(PHOTOS_FTS_CREATE)
        for trigger_sql in PHOTOS_FTS_TRIGGERS:
            conn.execute(trigger_sql)

        # A freshly created external-content index starts empty — whether it was
        # dropped for a schema upgrade or created for the first time on a DB that
        # predates FTS. Without a rebuild, text search silently returns nothing
        # for every existing photo until a manual --rebuild-fts. Repopulate it
        # from the photos table.
        if (fts_recreated or not fts_existed) and not is_fresh:
            try:
                conn.execute("INSERT INTO photos_fts(photos_fts) VALUES('rebuild')")
            except sqlite3.DatabaseError:
                logger.warning(
                    "photos_fts rebuild after recreate failed — run 'python database.py --rebuild-fts'"
                )

        # Run the version ladder (no-op today) and stamp PRAGMA user_version.
        _run_migration_ladder(conn, is_fresh)

        conn.commit()

        if build_photo_indexes:
            create_photo_indexes(conn)
            analyze_photos_if_unanalyzed(conn)


# Indexes whose absence from sqlite_stat1 means the photos table must be analyzed: a
# freshly created index has no stats row, and with stale partial stats the planner
# ignores it (the moment / learned_score sorts kept temp-sorting 126k rows until
# ANALYZE ran; with no stats at all the gallery page fell back to an OR plan and a
# temp sort). idx_gallery_aggregate is the second key because a DB upgraded from
# before it already has the moment index analyzed.
ANALYZE_KEY_INDEXES = ('idx_moment_confidence', 'idx_gallery_aggregate')

# Indexes that get their own single-index ``ANALYZE <name>`` in the transaction that
# builds them. ANALYZE_KEY_INDEXES does not cover them: a library the gallery
# indexes already analyzed never refires that gate when these are added later, and
# without a sqlite_stat1 row for the new index the planner ignores it next to
# stale partial stats. A one-index ANALYZE scans the small covering index, not the
# 16 GB table, so it costs seconds where ``ANALYZE photos`` costs the whole file.
ANALYZE_ON_BUILD_INDEXES = ('idx_post_scan', 'idx_date_asc_cover', 'idx_qrealign_sort',
                            'idx_deqa_sort', 'idx_aesthetic_v25_sort')


def missing_photo_indexes(conn):
    """The ``INDEXES`` entries (name, table, column_expr) the database does not have."""
    existing = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'")}
    return [entry for entry in INDEXES if entry[0] not in existing]


def create_photo_indexes(conn, should_stop=None, on_built=None):
    """Build every missing ``INDEXES`` entry, each its own autocommit statement.

    Logs one INFO line before each index and one after it. Each CREATE INDEX
    holds the write lock only for itself (an ``ANALYZE_ON_BUILD_INDEXES`` entry
    together with its single-index ANALYZE, in one transaction), and a run killed or interrupted
    (``sqlite3.Connection.interrupt``) mid-build keeps every index it finished.
    ``should_stop`` is checked before each index; when it returns True the build
    stops there. ``on_built(done, total)`` is called after each finished index.
    Returns the names built.
    """
    if conn.in_transaction:
        conn.commit()
    missing = missing_photo_indexes(conn)
    built = []
    for position, (idx_name, table, column_expr) in enumerate(missing, 1):
        if should_stop is not None and should_stop():
            break
        logger.info("Creating index %s (%d of %d; a large library can take minutes)",
                    idx_name, position, len(missing))
        started = time.monotonic()
        # A stats-on-build index is built and analyzed in ONE transaction: an
        # interrupt between the two would otherwise leave an index the next start
        # takes for finished (it is no longer missing) and the planner ignores.
        analyze_now = (idx_name in ANALYZE_ON_BUILD_INDEXES
                       and conn.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone() is not None)
        try:
            if analyze_now:
                conn.execute('BEGIN')
            conn.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr})')
            if analyze_now:
                conn.execute(f'ANALYZE {idx_name}')
                conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        logger.info("Created index %s in %.1f s", idx_name, time.monotonic() - started)
        built.append(idx_name)
        if on_built is not None:
            on_built(position, len(missing))
    return built


def photos_need_analyze(conn):
    """True when an existing ``ANALYZE_KEY_INDEXES`` index has no stats on a non-empty table.

    An EMPTY photos table cannot be analyzed (ANALYZE writes no sqlite_stat1 row
    for it), so it never counts: the gate would refire on every init.
    """
    try:
        analyzed = {r[0] for r in conn.execute(
            "SELECT idx FROM sqlite_stat1 WHERE idx IS NOT NULL")}
    except sqlite3.OperationalError:
        analyzed = set()  # sqlite_stat1 not created yet (never analyzed)
    existing = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'photos'")}
    unanalyzed = [name for name in ANALYZE_KEY_INDEXES
                  if name in existing and name not in analyzed]
    return bool(unanalyzed) and conn.execute("SELECT 1 FROM photos LIMIT 1").fetchone() is not None


def analyze_photos_if_unanalyzed(conn):
    """Full statistics for the photos table when ``photos_need_analyze``; returns whether it ran.

    One ``ANALYZE photos`` statement. Statistics are never sampled
    (``PRAGMA analysis_limit``): on a 130k-photo library a sampled pass left the
    default gallery count on a MULTI-INDEX OR plan, 0.5 s warm instead of 25 ms.
    The statement holds the write lock for its whole run (about 1.2 s on that
    library with a warm page cache); an interrupted one is rolled back and redone
    by the next call.
    """
    if conn.in_transaction:
        conn.commit()
    if not photos_need_analyze(conn):
        return False
    conn.execute("ANALYZE photos")
    if conn.in_transaction:
        conn.commit()
    return True


def detect_embedding_dim(conn):
    """Detect the embedding dimension from existing data.

    Returns 1152 for SigLIP, 768 for CLIP, or None if no embeddings exist.
    """
    row = conn.execute(
        "SELECT LENGTH(clip_embedding) FROM photos WHERE clip_embedding IS NOT NULL LIMIT 1"
    ).fetchone()
    if not row or not row[0]:
        return None
    return row[0] // 4  # float32 = 4 bytes


def _init_vec_table(conn):
    """Create the photos_vec virtual table if sqlite-vec is available.

    Detects the embedding dimension from existing data. If no embeddings
    exist yet, defers creation until populate_vec_table is called.
    """
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if 'photos_vec' in tables:
        return

    dim = detect_embedding_dim(conn)
    if dim is None:
        return

    try:
        conn.execute(f'''
            CREATE VIRTUAL TABLE IF NOT EXISTS photos_vec USING vec0(
                path TEXT PRIMARY KEY,
                embedding float[{dim}] distance_metric=cosine
            )
        ''')
        logger.info("Created photos_vec virtual table (dim=%d, cosine)", dim)
    except Exception as e:
        logger.warning("Could not create photos_vec: %s", e)
