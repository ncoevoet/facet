"""Facet CLI argument parser — extracted from facet.py's main() for readability."""

import argparse

from db import DEFAULT_DB_PATH

# Refreshing thumbnails is bound by storage round-trips, not by CPU: each file
# is a small read at the far end of whatever mount the library lives on. The
# default is therefore wider than the scan's decode concurrency, which is sized
# as a memory governor for full demosaics, while still bounding the demosaics a
# preview-less RAW falls back to.
DEFAULT_REFRESH_THUMBNAIL_WORKERS = 8

DEFAULT_CHECK_RAW_SAMPLE = 20

DEFAULT_DRY_RUN_COUNT = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Facet: AI-powered photo quality assessment',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python facet.py /path/to/photos              # Score photos (auto multi-pass mode)
  python facet.py /path/to/photos --single-pass  # Force single-pass (all models at once)
  python facet.py /path/to/photos --force      # Re-scan already processed files
  python facet.py --recompute-average          # Recalculate scores with current config

Single-Pass Modes:
  python facet.py /path --pass quality         # Run quality scoring pass only
  python facet.py /path --pass tags            # Run tagging pass only
  python facet.py /path --pass composition     # Run SAMP-Net composition pass only
  python facet.py /path --pass faces           # Run face detection pass only

Recompute Operations:
  python facet.py --recompute-tags             # Re-tag photos using configured model
  python facet.py --recompute-composition-cpu  # Rule-based composition (CPU only, fast)
  python facet.py --recompute-composition-gpu  # SAMP-Net neural network (requires GPU)

Preview Mode:
  python facet.py /path/to/photos --dry-run              # Preview scoring (default: 10 photos)
  python facet.py /path/to/photos --dry-run --dry-run-count 20

Database:
  python facet.py --compute-recommendations    # Analyze database for scoring recommendations
  python facet.py --compute-recommendations --apply-recommendations
  python facet.py --compute-recommendations --simulate  # Preview projected score changes

Face Recognition:
  python facet.py --extract-faces-gpu-incremental  # Extract faces for new photos only (requires GPU)
  python facet.py --extract-faces-gpu-force        # Re-extract all faces (requires GPU)
  python facet.py --cluster-faces-incremental      # Cluster preserving all existing persons
  python facet.py --cluster-faces-incremental-named  # Cluster preserving only named persons
  python facet.py --cluster-faces-force            # Full re-cluster, deletes all persons
  python facet.py --refill-face-thumbnails-incremental  # Generate missing thumbnails
  python facet.py --refill-face-thumbnails-force   # Regenerate ALL face thumbnails
  python facet.py --recompute-blinks               # Recompute blink detection
  python facet.py --recompute-burst                # Recompute burst detection
  python facet.py --detect-duplicates              # Detect duplicate photos via pHash

Export:
  python facet.py --export-csv                 # Export to CSV (auto-named with timestamp)
  python facet.py --export-json output.json    # Export to JSON with specific filename

Model Information:
  python facet.py --list-models                # Show available models and requirements

Configuration:
  python facet.py --validate-categories        # Validate category configurations
  python facet.py --config my_config.json /path/to/photos  # Use custom config
        '''
    )

    # Positional arguments
    parser.add_argument('photo_paths', nargs='*', help='Folders to scan for photos')

    # Scanning options
    scan_group = parser.add_argument_group('Scanning options')
    scan_group.add_argument('--force', action='store_true',
                        help='Re-scan already processed files (ignores existing DB entries)')
    scan_group.add_argument('--single-pass', action='store_true',
                        help='Force single-pass mode (load all models at once, requires more VRAM)')
    scan_group.add_argument('--pass', type=str, dest='single_pass_name', metavar='NAME',
                        choices=['quality', 'tags', 'composition', 'faces', 'embeddings',
                                 'quality-iaa', 'quality-face', 'quality-liqe', 'saliency'],
                        help='Run specific pass only: quality, tags, composition, faces, embeddings, '
                             'quality-iaa, quality-face, quality-liqe, saliency')
    scan_group.add_argument('--dry-run', action='store_true',
                        help='Score sample photos without saving to database (preview mode)')
    scan_group.add_argument('--dry-run-count', type=int, default=DEFAULT_DRY_RUN_COUNT,
                        help=f'Number of photos to process in dry-run mode (default: '
                             f'{DEFAULT_DRY_RUN_COUNT}, requires --dry-run)')
    scan_group.add_argument('--resume', action='store_true',
                        help='Resume the last interrupted/failed scan run (reuses its directories; '
                             'with --force, skips files already re-scored since that run started)')
    scan_group.add_argument('--retry-failed', nargs='?', const='last', metavar='last|all',
                        help='Re-process only files that failed during the last scan run (or all runs)')
    scan_group.add_argument('--force-since', type=str, metavar='YYYY-MM-DD',
                        help='Like --force, but only re-process photos last scanned before this date')
    scan_group.add_argument('--watch', action='store_true',
                        help='Stay running and re-scan whenever new photos appear in the given '
                             'directories (requires the optional watchdog package)')
    scan_group.add_argument('--watch-debounce', type=int, default=30, metavar='SECONDS',
                        help='Quiet period before a watch-mode scan fires (default: 30)')
    scan_group.add_argument('--force-low-space', action='store_true',
                        help='Proceed with a scan even when the volume looks too small for '
                             'the thumbnails/embeddings it will write (overrides the guard)')

    # Database operations
    db_group = parser.add_argument_group('Database operations')
    db_group.add_argument('--recompute-average', action='store_true',
                        help='Update scores based on current config (uses stored embeddings)')
    db_group.add_argument('--recompute-category', type=str, metavar='CATEGORY',
                        help='Recompute aggregate scores for a single category only')
    db_group.add_argument('--detect-duplicates', action='store_true',
                        help='Detect duplicate photos using pHash comparison')
    db_group.add_argument('--detect-sequences', action='store_true',
                        help='Detect deliberate multi-frame sets: exposure brackets from stored '
                             'EXIF, then panoramas from thumbnail geometry (whole library)')
    db_group.add_argument('--detect-panoramas', action='store_true',
                        help='Detect panorama sets by matching stored thumbnails geometrically. '
                             'Runs the bracket pass first, as --detect-sequences does: an HDR '
                             'panorama is bracketed at every position, so the two must stay in step')
    db_group.add_argument('--sweep-dedup-thresholds', nargs='?', const='', metavar='LABELS_JSON',
                        help='Evaluate near-dup cosine thresholds. With a labels JSON, prints a '
                             'precision/recall table; without, prints the candidate-cosine distribution.')
    db_group.add_argument('--recompute-embeddings', action='store_true',
                        help='Recompute CLIP/SigLIP embeddings for all photos (required after model switch)')
    db_group.add_argument('--tag-untagged', action='store_true',
                        help='Tag only photos that have no tags yet, from stored embeddings '
                             '(no image reads). Same work the scan does at the end; use it to '
                             'fill gaps without re-tagging what is already labelled')
    db_group.add_argument('--recompute-tags', action='store_true',
                        help='Re-tag all photos using configured tagging model')
    db_group.add_argument('--recompute-tags-vlm', action='store_true',
                        help='Re-tag all photos using VLM model (loads images from disk, defaults to qwen3-vl-2b)')
    db_group.add_argument('--detect-moments', action='store_true',
                        help='Label each photo with its narrative moment (zero-shot CLIP + temporal smoothing); skips already-labeled photos')
    db_group.add_argument('--recompute-moments', action='store_true',
                        help='Re-label narrative moments for the whole library (re-smooths the full timeline)')
    db_group.add_argument('--detect-junk', action='store_true',
                        help='Flag non-photo junk (screenshots, documents, receipts, memes, slides) via zero-shot CLIP over stored embeddings; skips already-evaluated photos')
    db_group.add_argument('--recompute-junk', action='store_true',
                        help='Re-evaluate junk_kind for the whole library')
    db_group.add_argument('--limit', type=int, default=None, metavar='N',
                        help='Cap --detect-moments / --recompute-moments to the first N photos (verification / incremental)')
    db_group.add_argument('--discover-moments', action='store_true',
                        help='Propose a library-specific moment vocabulary by clustering the stored '
                             'caption embeddings (writes scoring_config.discovered.json for review; '
                             'never rewrites the active config). Run --detect-moments first to populate caption_embedding.')
    db_group.add_argument('--discover-min-cluster-size', type=int, default=30, metavar='N',
                        help='HDBSCAN granularity for --discover-moments (smaller = more, finer moments; default 30)')
    db_group.add_argument('--refresh-thumbnails', action='store_true',
                        help='Rebuild stored thumbnails for RAW photos: from the camera-embedded '
                             'preview for an ordinary photo, or the uncorrected faithful demosaic '
                             'for a bracketed frame (CPU only, no models, no scoring column '
                             'touched). Bound by storage throughput, so the cost scales with '
                             'library size and link speed. Resumable: re-run it after an '
                             'interrupt to continue.')
    db_group.add_argument('--refresh-thumbnails-workers', type=int, metavar='N',
                        default=DEFAULT_REFRESH_THUMBNAIL_WORKERS,
                        help=f'Parallel reads for --refresh-thumbnails (default '
                             f'{DEFAULT_REFRESH_THUMBNAIL_WORKERS}). The work is storage-bound; '
                             'raise it for a fast network mount, lower it for a slow disk')
    db_group.add_argument('--check-raw-rendering', type=int, nargs='?', metavar='N',
                        const=DEFAULT_CHECK_RAW_SAMPLE, default=None,
                        help=f'Render N sampled RAW photos (default {DEFAULT_CHECK_RAW_SAMPLE}) '
                             'under the pre-fix and current decode settings and print the '
                             'mean-luminance deltas. Read-only — validate settings before a rescan')
    db_group.add_argument('--backfill-focal-35mm', action='store_true',
                        help='Backfill focal_length_35mm from EXIF for photos missing it')
    db_group.add_argument('--backfill-clipping', action='store_true',
                        help='Derive per-channel clipping percentages from stored histograms. '
                             'Database-only (no image decode) and resumable; photos whose '
                             'histogram predates the RGB format stay unknown')
    db_group.add_argument('--score-topiq', action='store_true',
                        help='Backfill TOPIQ quality scores from stored thumbnails (requires GPU)')
    db_group.add_argument('--recompute-iqa', action='store_true',
                        help='Recompute supplementary IQA metrics (TOPIQ IAA, NR-Face, LIQE) from stored thumbnails')
    db_group.add_argument('--detect-text', action='store_true',
                        help='Extract in-image text (signs, documents, posters) into ocr_text via OCR '
                             'over stored thumbnails, then search it from the gallery; skips '
                             'already-evaluated photos. Requires "ocr".enabled in scoring_config.json.')
    db_group.add_argument('--recompute-text', action='store_true',
                        help='Re-run OCR over the whole library (re-reads photos already evaluated by --detect-text)')
    db_group.add_argument('--recompute-colors', action='store_true',
                        help='Extract dominant hue + warm/cool colour temperature from stored thumbnails '
                             '(CPU only, fast) into dominant_hue / color_temp')
    db_group.add_argument('--recompute-form', action='store_true',
                        help='Recompute form facet metrics (symmetry, balance, edge entropy, fractal '
                             'dimension) + Matsuda colour harmony from stored thumbnails (CPU only)')
    db_group.add_argument('--recompute-distortions', action='store_true',
                        help='Zero-shot ExIQA-style distortion attributes from stored CLIP/SigLIP '
                             'embeddings (advisory JSON column + liqe/noise correlation validation report)')
    db_group.add_argument('--recompute-skin-tone', action='store_true',
                        help='Skin-tone naturalness from stored face thumbnails + landmarks '
                             '(cheek CIELAB vs skin locus, CIEDE2000; CPU, no model)')
    db_group.add_argument('--upgrade-db', action='store_true',
                        help='Migrate schema + run the full backfill chain '
                             '(extract-gps, detect-duplicates, recompute-iqa, '
                             'recompute-saliency, recompute-composition-cpu, '
                             'recompute-burst, recompute-blinks, recompute-average). '
                             'Idempotent — re-runs are safe. '
                             'Does NOT run heavy steps like --generate-captions.')
    db_group.add_argument('--compute-recommendations', action='store_true',
                        help='Analyze database and show scoring recommendations')
    db_group.add_argument('--apply-recommendations', action='store_true',
                        help='Apply scoring recommendations to config (requires --compute-recommendations)')
    db_group.add_argument('--simulate', action='store_true',
                        help='Preview projected score changes without modifying config (use with --compute-recommendations)')
    db_group.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed statistics (use with --compute-recommendations)')
    db_group.add_argument('--mine-insights', nargs='?', const='stdout', metavar='REPORT.json',
                        help='Data-mining report: label inventory, metric-label correlations, '
                             'category distribution, percentile drift, comparison health '
                             '(optionally writes the full report as JSON)')
    db_group.add_argument('--sync-label-comparisons', action='store_true',
                        help='Rebuild rating-derived comparison pairs (source=rating) from '
                             'star ratings, favorites and rejections')
    db_group.add_argument('--optimize-sources', type=str, metavar='vote,culling,rating',
                        help='Restrict --optimize-weights training data to these comparison '
                             'sources (default: all, with per-source reliability weighting)')
    db_group.add_argument('--optimize-category', type=str, metavar='CATEGORY',
                        help='Category for --optimize-weights: trains only on that category\'s '
                             'comparisons and writes the result into the v4 categories[].weights '
                             'block (default: pool all comparisons and write to the legacy '
                             "'others' block, which the v4 config does not read)")

    # Face recognition
    face_group = parser.add_argument_group('Face recognition')
    face_group.add_argument('--extract-faces-gpu-incremental', action='store_true',
                        help='Extract faces only for photos not yet processed (requires GPU)')
    face_group.add_argument('--extract-faces-gpu-force', action='store_true',
                        help='Delete all faces and re-extract from all photos (requires GPU)')
    face_group.add_argument('--cluster-faces-incremental', action='store_true',
                        help='Run HDBSCAN clustering preserving all existing persons')
    face_group.add_argument('--cluster-faces-incremental-named', action='store_true',
                        help='Run HDBSCAN clustering preserving only named persons (deletes unnamed)')
    face_group.add_argument('--cluster-faces-force', action='store_true',
                        help='Full re-clustering, deleting all persons including named ones')
    face_group.add_argument('--refill-face-thumbnails-incremental', action='store_true',
                        help='Generate thumbnails only for faces missing them')
    face_group.add_argument('--refill-face-thumbnails-force', action='store_true',
                        help='Clear and regenerate ALL face thumbnails from original images')
    face_group.add_argument('--recompute-blinks', action='store_true',
                        help='Recompute blink detection using stored landmarks (CPU only, fast)')
    face_group.add_argument('--recompute-eyes-expression', action='store_true',
                        help='Recompute eyes-open and expression scores from stored landmarks (CPU only, fast)')
    face_group.add_argument('--recompute-face-signals', action='store_true',
                        help='Backfill per-face eyes-open and smile scores from stored landmarks for '
                             'faces still missing them (CPU only, fast); add --force to rewrite every '
                             'face from geometry, overwriting stored MediaPipe blendshape values')
    face_group.add_argument('--recompute-burst', action='store_true',
                        help='Recompute burst detection groups')
    face_group.add_argument('--suggest-person-merges', action='store_true',
                        help='Analyze persons and suggest potential merges based on centroid similarity')
    face_group.add_argument('--merge-threshold', type=float, default=0.6,
                        help='Similarity threshold for merge suggestions (default: 0.6)')

    # Thumbnail management
    thumb_group = parser.add_argument_group('Thumbnail management')
    thumb_group.add_argument('--fix-thumbnail-rotation', action='store_true',
                        help='Fix rotation of existing thumbnails using EXIF orientation data')

    # Composition analysis
    comp_group = parser.add_argument_group('Composition analysis')
    comp_group.add_argument('--recompute-composition-cpu', action='store_true',
                        help='Recompute composition scores using rule-based analysis (CPU only, fast)')
    comp_group.add_argument('--recompute-composition-gpu', action='store_true',
                        help='Recompute composition scores using SAMP-Net neural network (requires GPU)')
    comp_group.add_argument('--recompute-saliency', action='store_true',
                        help='Recompute subject saliency metrics using BiRefNet from stored thumbnails '
                             '(requires GPU; skips photos that already have subject_bbox unless --force)')

    # Weight optimization
    weight_group = parser.add_argument_group('Weight optimization')
    weight_group.add_argument('--comparison-stats', action='store_true',
                        help='Show pairwise comparison statistics')
    weight_group.add_argument('--optimize-weights', action='store_true',
                        help='Optimize and save scoring weights based on pairwise comparisons '
                             '(applied only if held-out k-fold accuracy beats current weights)')
    weight_group.add_argument('--optimize-force', action='store_true',
                        help='Apply optimized weights even if the held-out accuracy gate is not met')
    weight_group.add_argument('--auto-tune-categories', action='store_true',
                        help='Superadmin only (pass --user in multi-user mode): report per-category '
                             'comparison-label readiness for auto-tuning the SHARED global weights. '
                             'Stub — reports readiness only; the auto-apply loop is deferred pending labels')
    weight_group.add_argument('--train-ranker', action='store_true',
                        help='Train the personal ranker over [embedding + scores] and write '
                             'learned_scores (gated on held-out k-fold accuracy vs the aggregate '
                             'baseline; use --train-ranker-force to write regardless; pass --user '
                             'in multi-user mode to scope to one user)')
    weight_group.add_argument('--train-ranker-force', action='store_true',
                        help='Write learned_scores even if the ranker accuracy gate is not met')
    weight_group.add_argument('--ranker-category', type=str, metavar='CATEGORY',
                        help='Restrict --train-ranker / --train-keeper to one category (default: pool all)')
    weight_group.add_argument('--train-keeper', action='store_true',
                        help='Train the keeper-ranking head over culling decisions '
                             '(source=culling pairs) and persist it only if it beats the '
                             'auto-cull heuristic on held-out k-fold accuracy; use '
                             '--train-keeper-force to persist regardless; pass --user in '
                             'multi-user mode to scope to one user')
    weight_group.add_argument('--train-keeper-force', action='store_true',
                        help='Persist the keeper head even if its accuracy gate is not met')
    weight_group.add_argument('--report-unreviewed-bursts', action='store_true',
                        help='Report how many burst groups remain unreviewed (read-only)')
    weight_group.add_argument('--eval-iqa-srcc', action='store_true',
                        help='Report Spearman SRCC of each IQA/aesthetic metric vs star ratings (read-only)')

    # Model information
    model_group = parser.add_argument_group('Model information')
    model_group.add_argument('--list-models', action='store_true',
                        help='Show available models and their VRAM requirements')
    model_group.add_argument('--doctor', action='store_true',
                        help='Run diagnostic checks (Python, GPU, dependencies, config)')
    model_group.add_argument('--simulate-gpu', type=str, default=None, metavar='NAME',
                        help='Simulate GPU for --doctor (e.g., "RTX 5070 Ti")')
    model_group.add_argument('--simulate-vram', type=float, default=None, metavar='GB',
                        help='Simulate VRAM in GB for --doctor (e.g., 16)')

    # Export
    export_group = parser.add_argument_group('Export')
    export_group.add_argument('--export-csv', type=str, nargs='?', const='auto',
                        help='Export database to CSV file (optional: specify filename)')
    export_group.add_argument('--export-json', type=str, nargs='?', const='auto',
                        help='Export database to JSON file (optional: specify filename)')
    export_group.add_argument('--export-manifest', type=str, nargs='?', const='all', metavar='PATH',
                        help='Export a compact JSON manifest (path, category, scores, tags, ratings) '
                             'for external tools such as a Lightroom Classic plugin feed (optional: '
                             'limit to a path subtree; default: all photos). Writes facet_manifest.json '
                             'in the current directory, overwriting any previous manifest there. Defaults '
                             'to the global rating columns; pass --user for per-user ratings in multi-user mode')
    export_group.add_argument('--import-sidecars', type=str, nargs='?', const='all', metavar='PATH',
                        help='Import ratings/labels/tags from <image>.xmp sidecars back into the DB '
                             '(optional: limit to a path subtree; default: all photos)')
    export_group.add_argument('--export-sidecars', type=str, nargs='?', const='all', metavar='PATH',
                        help='Write/merge <image>.xmp sidecars from the DB ratings/labels/tags/caption '
                             '(optional: limit to a path subtree; default: all photos). Defaults to the '
                             'global rating columns; pass --user for per-user ratings in multi-user mode')
    export_group.add_argument('--embed-originals', action='store_true',
                        help='With --export-sidecars: also embed metadata into the original image files '
                             '(JPEG/HEIC/TIFF/PNG/DNG via exiftool); RAW originals are never modified')
    export_group.add_argument('--score-to-stars', action='store_true',
                        help='With --export-sidecars: derive xmp:Rating from the aggregate score for '
                             'photos the user has not manually rated (overrides xmp_export config for this run)')
    export_group.add_argument('--user', type=str, default=None, metavar='USERNAME',
                        help='With --import-sidecars/--export-sidecars/--export-manifest/--immich-sync in '
                             'multi-user mode: '
                             "read/write that user's ratings (user_preferences) instead of the global columns. "
                             'With --train-ranker: scope the personal ranker to that user (own + legacy '
                             'comparisons -> per-user learned_scores)')
    export_group.add_argument('--immich-sync', action='store_true',
                        help='Push ratings/favorites to the configured Immich server via its REST API '
                             '(one-way; needs the "immich" config block; honors --user and --dry-run)')
    export_group.add_argument('--immich-test', action='store_true',
                        help='Test connectivity and authentication against the configured Immich server')

    # AI features
    ai_group = parser.add_argument_group('AI features')
    ai_group.add_argument('--generate-captions', action='store_true',
                        help='Generate AI captions for photos without one (requires VLM)')
    ai_group.add_argument('--translate-captions', action='store_true',
                        help='Translate English captions to the configured target language (CPU, MarianMT)')
    ai_group.add_argument('--extract-gps', action='store_true',
                        help='Backfill GPS coordinates from EXIF data for photos missing GPS')
    ai_group.add_argument('--rescan-gps', action='store_true',
                        help='Re-extract GPS coordinates from EXIF for ALL photos (overwrites existing)')

    # Configuration
    config_group = parser.add_argument_group('Configuration')
    config_group.add_argument('--config', type=str, default=None,
                        help='Path to custom scoring config JSON file')
    config_group.add_argument('--db', type=str, default=DEFAULT_DB_PATH,
                        help=f'Path to database file (default: {DEFAULT_DB_PATH})')
    config_group.add_argument('--validate-categories', action='store_true',
                        help='Validate category configurations')
    config_group.add_argument('--force-library-lock', action='store_true',
                        help='Run even if another library job holds the lock (unsafe)')

    return parser
