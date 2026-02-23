#!/usr/bin/env python3
"""
Facet - AI-powered photo quality assessment system.

CLI entry point. The scoring engine is in processing/scorer.py.
"""
import os
import sys
import time

# Suppress HuggingFace Hub unauthenticated request warnings
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")
import warnings
warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")

# Ensure the script's directory is in Python path for local imports
# This allows running the script from any directory
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

import json
from pathlib import Path
from datetime import datetime
from db import init_database, get_connection

try:
    from tqdm import tqdm
except ImportError:
    # Fallback: simple pass-through iterator
    def tqdm(iterable, **kwargs):
        desc = kwargs.get('desc', '')
        if desc:
            print(f"{desc}...")
        return iterable

# Import config module (lightweight, no cv2/torch dependency)
from config import ScoringConfig, PercentileNormalizer




# ============================================
# EXECUTION
# ============================================
if __name__ == '__main__':
    import argparse

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
                        choices=['quality', 'tags', 'composition', 'faces', 'embeddings'],
                        help='Run specific pass only: quality, tags, composition, faces, embeddings')
    scan_group.add_argument('--dry-run', action='store_true',
                        help='Score sample photos without saving to database (preview mode)')
    scan_group.add_argument('--dry-run-count', type=int, default=10,
                        help='Number of photos to process in dry-run mode (default: 10, requires --dry-run)')

    # Database operations
    db_group = parser.add_argument_group('Database operations')
    db_group.add_argument('--recompute-average', action='store_true',
                        help='Update scores based on current config (uses stored embeddings)')
    db_group.add_argument('--recompute-category', type=str, metavar='CATEGORY',
                        help='Recompute aggregate scores for a single category only')
    db_group.add_argument('--detect-duplicates', action='store_true',
                        help='Detect duplicate photos using pHash comparison')
    db_group.add_argument('--recompute-tags', action='store_true',
                        help='Re-tag all photos using configured tagging model')
    db_group.add_argument('--recompute-tags-vlm', action='store_true',
                        help='Re-tag all photos using VLM model (loads images from disk, defaults to qwen3-vl-2b)')
    db_group.add_argument('--backfill-focal-35mm', action='store_true',
                        help='Backfill focal_length_35mm from EXIF for photos missing it')
    db_group.add_argument('--score-topiq', action='store_true',
                        help='Backfill TOPIQ quality scores from stored thumbnails (requires GPU)')
    db_group.add_argument('--compute-recommendations', action='store_true',
                        help='Analyze database and show scoring recommendations')
    db_group.add_argument('--apply-recommendations', action='store_true',
                        help='Apply scoring recommendations to config (requires --compute-recommendations)')
    db_group.add_argument('--simulate', action='store_true',
                        help='Preview projected score changes without modifying config (use with --compute-recommendations)')
    db_group.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed statistics (use with --compute-recommendations)')

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

    # Weight optimization
    weight_group = parser.add_argument_group('Weight optimization')
    weight_group.add_argument('--comparison-stats', action='store_true',
                        help='Show pairwise comparison statistics')
    weight_group.add_argument('--optimize-weights', action='store_true',
                        help='Optimize and save scoring weights based on pairwise comparisons')

    # Model information
    model_group = parser.add_argument_group('Model information')
    model_group.add_argument('--list-models', action='store_true',
                        help='Show available models and their VRAM requirements')

    # Export
    export_group = parser.add_argument_group('Export')
    export_group.add_argument('--export-csv', type=str, nargs='?', const='auto',
                        help='Export database to CSV file (optional: specify filename)')
    export_group.add_argument('--export-json', type=str, nargs='?', const='auto',
                        help='Export database to JSON file (optional: specify filename)')

    # Configuration
    config_group = parser.add_argument_group('Configuration')
    config_group.add_argument('--config', type=str, default=None,
                        help='Path to custom scoring config JSON file')
    config_group.add_argument('--db', type=str, default='photo_scores_pro.db',
                        help='Path to database file (default: photo_scores_pro.db)')
    config_group.add_argument('--validate-categories', action='store_true',
                        help='Validate category configurations')

    args = parser.parse_args()

    # Validate argument dependencies
    if args.apply_recommendations and not args.compute_recommendations:
        parser.error("--apply-recommendations requires --compute-recommendations")
    if args.simulate and not args.compute_recommendations:
        parser.error("--simulate requires --compute-recommendations")

    if args.dry_run_count != 10 and not args.dry_run:
        parser.error("--dry-run-count requires --dry-run")

    # Category validation mode (lightweight - no GPU needed)
    if args.validate_categories:
        config_path = args.config or 'scoring_config.json'
        config = ScoringConfig(config_path, validate=False)
        config.validate_categories(verbose=True)
        print(f"\nCategories in priority order:")
        for cat in config.get_categories():
            filters = cat.get('filters', {})
            filter_desc = ', '.join(f"{k}={v}" for k, v in filters.items()) or 'fallback'
            print(f"  {cat['priority']:3d}. {cat['name']:20s} [{filter_desc}]")
        exit()

    # Comparison statistics mode (lightweight - no GPU needed)
    if args.comparison_stats:
        from optimization import print_comparison_stats
        print_comparison_stats(args.db)
        exit()

    # Weight optimization mode (lightweight - no GPU needed)
    if args.optimize_weights:
        from optimization import run_weight_optimization
        config_path = args.config or 'scoring_config.json'
        run_weight_optimization(
            db_path=args.db,
            config_path=config_path,
        )
        exit()

    # List models mode (lightweight - no GPU needed)
    if args.list_models:
        from processing.multi_pass import list_available_models
        list_available_models()
        exit()

    # Detect duplicate photos (lightweight - no GPU needed)
    if args.detect_duplicates:
        from utils.duplicate import detect_duplicates
        init_database(args.db)
        detect_duplicates(args.db, config_path=args.config)
        exit()

    # Import scorer (deferred to avoid loading heavy modules for --help)
    from processing.scorer import (
        Facet, process_bursts, process_single_photo,
        _load_image_modules, backup_database,
    )

    # Compute recommendations mode (lightweight - no GPU needed)
    if args.compute_recommendations:
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        norm_settings = scorer.config.get_normalization_settings()
        target_pct = norm_settings.get('percentile_target', 95) if norm_settings else 95
        per_category = norm_settings.get('per_category', False) if norm_settings else False
        category_min_samples = norm_settings.get('category_min_samples', 50) if norm_settings else 50
        normalizer = PercentileNormalizer(
            scorer.db_path,
            target_pct,
            per_category=per_category,
            category_min_samples=category_min_samples
        )
        normalizer.compute_percentiles()

        # Get recommendations if applying or simulating, otherwise just print stats
        apply_recs = getattr(args, 'apply_recommendations', False)
        simulate = getattr(args, 'simulate', False)
        verbose = getattr(args, 'verbose', False)
        recommendations = normalizer.print_database_statistics(
            config=scorer.config,
            return_recommendations=apply_recs or simulate,
            verbose=verbose
        )

        if simulate and recommendations:
            normalizer.simulate_recommendations(recommendations, scorer, conn_factory=get_connection)
        elif apply_recs and recommendations:
            print("\nApplying recommendations...")
            backup = normalizer.apply_recommendations(recommendations, scorer.config)
            if backup:
                print("\nRun 'python facet.py --recompute-average' to apply new weights to scores.")
        elif apply_recs:
            print("\nNo recommendations to apply.")

        exit()

    # Backfill focal_length_35mm from EXIF (lightweight - no GPU needed)
    if args.backfill_focal_35mm:
        from exiftool import get_exif_batch
        from pathlib import Path
        init_database(args.db)
        with get_connection(args.db) as conn:
            cursor = conn.execute(
                "SELECT path FROM photos WHERE focal_length_35mm IS NULL AND focal_length IS NOT NULL"
            )
            paths = [row['path'] for row in cursor.fetchall()]

        if not paths:
            print("No photos need focal_length_35mm backfill.")
            exit()

        print(f"Backfilling focal_length_35mm for {len(paths)} photos...")
        raw_results = get_exif_batch(paths, chunk_size=500, timeout_per_chunk=120)

        updated = 0
        with get_connection(args.db) as conn:
            for path in paths:
                resolved = str(Path(path).resolve())
                exif = raw_results.get(resolved, {})
                val = exif.get('focal_length_35mm')
                if val is not None:
                    conn.execute(
                        "UPDATE photos SET focal_length_35mm = ? WHERE path = ?",
                        (val, path)
                    )
                    updated += 1
            conn.commit()

        print(f"Updated focal_length_35mm for {updated}/{len(paths)} photos.")
        exit()

    # Cluster faces mode (lightweight - no GPU needed)
    if args.cluster_faces_incremental or args.cluster_faces_incremental_named or args.cluster_faces_force:
        from faces import run_face_clustering
        config = ScoringConfig(args.config)
        force = args.cluster_faces_force
        preserve_named_only = args.cluster_faces_incremental_named
        run_face_clustering(args.db, config, force=force, preserve_named_only=preserve_named_only)
        print("Face clustering complete.")
        exit()

    # Suggest person merges mode - opens web viewer
    if args.suggest_person_merges:
        import webbrowser
        import subprocess
        import socket

        threshold = args.merge_threshold
        port = int(os.environ.get('PORT', 5000))
        url = f"http://localhost:{port}/suggest_merges?threshold={threshold}"

        def is_port_in_use(p):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return s.connect_ex(('localhost', p)) == 0

        if not is_port_in_use(port):
            print("Starting web viewer...")
            viewer_process = subprocess.Popen(
                [sys.executable, 'viewer.py'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(2)
        else:
            viewer_process = None
            print("Viewer already running.")

        print(f"Opening merge suggestions at {url}")
        webbrowser.open(url)

        if viewer_process:
            print("Press Ctrl+C to stop the viewer.")
            try:
                viewer_process.wait()
            except KeyboardInterrupt:
                viewer_process.terminate()
        exit()

    # Refill face thumbnails mode
    if args.refill_face_thumbnails_incremental or args.refill_face_thumbnails_force:
        from faces import refill_face_thumbnails
        init_database(args.db)  # Ensure schema is up to date
        config = ScoringConfig(args.config)
        force = args.refill_face_thumbnails_force
        refill_face_thumbnails(args.db, config, force=force)
        print("Face thumbnail regeneration complete.")
        exit()

    # Fix thumbnail rotation using EXIF data (CPU only, fast)
    if args.fix_thumbnail_rotation:
        from processing.scorer import fix_thumbnail_rotation
        init_database(args.db)  # Ensure schema is up to date
        fix_thumbnail_rotation(args.db)
        exit()

    # Recompute blink detection using stored landmarks (CPU only, fast)
    if args.recompute_blinks:
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        scorer.recompute_blink_detection()
        exit()

    # Extract faces mode (needs GPU for face analysis)
    if args.extract_faces_gpu_incremental or args.extract_faces_gpu_force:
        from faces import extract_faces_from_existing
        scorer = Facet(db_path=args.db, config_path=args.config)
        force = args.extract_faces_gpu_force
        extract_faces_from_existing(scorer, force=force)
        print("Face extraction complete.")
        exit()

    # Recompute composition scores using rule-based analysis (CPU only)
    if args.recompute_composition_cpu:
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        scorer.recompute_composition_scores()
        exit()

    # Recompute composition with SAMP-Net (requires GPU)
    if args.recompute_composition_gpu:
        _load_image_modules()  # Load cv2, PIL, numpy
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        batch_size = scorer.config.get_processing_settings().get('gpu_batch_size', 16)
        scorer.rescan_samp_composition(batch_size=batch_size)
        exit()

    # Score TOPIQ from stored thumbnails (requires GPU)
    if args.score_topiq:
        import numpy as np
        import cv2
        from PIL import Image
        from models.pyiqa_scorer import PyIQAScorer

        init_database(args.db)
        scorer_model = PyIQAScorer('topiq')
        scorer_model.load()

        with get_connection(args.db) as conn:
            cursor = conn.execute(
                "SELECT path, thumbnail FROM photos WHERE thumbnail IS NOT NULL"
            )
            rows = list(cursor.fetchall())

        print(f"Scoring {len(rows)} photos with TOPIQ...")
        updated = 0
        batch_paths = []
        batch_images = []
        batch_size = 16

        def _flush_topiq_batch(conn, scorer_model, batch_paths, batch_images):
            scores = scorer_model.score_batch(batch_images)
            for i, score in enumerate(scores):
                conn.execute(
                    "UPDATE photos SET topiq_score = ? WHERE path = ?",
                    (round(score, 2), batch_paths[i])
                )
            return len(scores)

        with get_connection(args.db) as conn:
            for row in tqdm(rows, desc="TOPIQ scoring"):
                thumbnail_blob = row['thumbnail']
                if not thumbnail_blob:
                    continue

                try:
                    img_array = np.frombuffer(thumbnail_blob, dtype=np.uint8)
                    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if img_cv is None:
                        continue
                except Exception:
                    continue

                img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)

                batch_paths.append(row['path'])
                batch_images.append(pil_img)

                if len(batch_images) >= batch_size:
                    updated += _flush_topiq_batch(conn, scorer_model, batch_paths, batch_images)
                    batch_paths = []
                    batch_images = []

            # Flush remaining
            if batch_images:
                updated += _flush_topiq_batch(conn, scorer_model, batch_paths, batch_images)

            conn.commit()

        scorer_model.unload()
        print(f"Updated topiq_score for {updated} photos.")
        exit()

    # Recompute burst detection
    if args.recompute_burst:
        config = ScoringConfig(args.config)
        process_bursts(args.db, config.config_path)
        print("Burst detection complete.")
        exit()



    # Recompute tags using VLM model (loads images from disk)
    if args.recompute_tags_vlm:
        from models.model_manager import ModelManager

        config = ScoringConfig(args.config)
        config.check_vram_profile_compatibility(verbose=True)

        # Use configured VLM or default to qwen3-vl-2b
        tag_model = config.get_model_for_task('tagging')
        if tag_model == 'qwen2.5-vl-7b':
            model_key = 'vlm_tagger'
        else:
            model_key = 'qwen3_vl_tagger'

        model_manager = ModelManager(config)

        # Get all photos from database
        init_database(args.db)
        with get_connection(args.db) as conn:
            cursor = conn.execute("SELECT path FROM photos")
            photos = cursor.fetchall()

        print(f"Re-tagging {len(photos)} photos using VLM ({model_key})...")

        tagger = model_manager.load_model_only(model_key)
        if not tagger:
            print(f"Failed to load VLM tagger")
            exit(1)

        from utils import load_image_from_path, _rawpy_lock, tags_to_string
        tagging_settings = config.get_tagging_settings()
        max_tags = tagging_settings.get('max_tags', 5)
        batch_size = tagger.batch_size
        updated = 0

        with get_connection(args.db) as conn:
            for i in tqdm(range(0, len(photos), batch_size), desc="VLM tagging"):
                batch = photos[i:i + batch_size]
                images = []
                paths = []

                for row in batch:
                    try:
                        pil_img, _ = load_image_from_path(row['path'], lock=_rawpy_lock)
                        if pil_img:
                            images.append(pil_img)
                            paths.append(row['path'])
                    except Exception as e:
                        print(f"Failed to load {row['path']}: {e}")

                if images:
                    tags_batch = tagger.tag_batch(images, max_tags=max_tags)
                    for path, tag_list in zip(paths, tags_batch):
                        tags = tags_to_string(tag_list) if tag_list else None
                        conn.execute(
                            "UPDATE photos SET tags = ? WHERE path = ?",
                            (tags, path)
                        )
                        updated += 1

            conn.commit()

        model_manager.unload_all()
        print(f"Updated tags for {updated} photos")
        exit()

    # Recompute tags mode (needs GPU for tagging model)
    if args.recompute_tags:
        from processing.scorer import Facet
        from models.model_manager import ModelManager

        config = ScoringConfig(args.config)
        config.check_vram_profile_compatibility(verbose=True)  # Resolve 'auto' profile
        tag_model = config.get_model_for_task('tagging')

        print(f"Re-tagging photos using model: {tag_model}")

        # Initialize model manager
        model_manager = ModelManager(config)

        # Count photos to re-tag
        with get_connection(args.db) as conn:
            photo_count = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE clip_embedding IS NOT NULL"
            ).fetchone()[0]

        print(f"Found {photo_count} photos to re-tag")

        if tag_model == 'clip':
            # Use CLIP embeddings for tagging
            scorer = Facet(db_path=args.db, config_path=args.config)
            clip_settings = config.get_clip_settings()
            tagging_settings = config.get_tagging_settings()
            threshold, max_tags = (
                clip_settings.get('similarity_threshold_percent', 22) / 100,
                tagging_settings.get('max_tags', 5)
            )

            updated = 0
            with get_connection(args.db) as conn:
                from utils import tags_to_string
                cursor = conn.execute(
                    "SELECT path, clip_embedding FROM photos WHERE clip_embedding IS NOT NULL"
                )
                for row in tqdm(cursor, desc="Tagging", total=photo_count):
                    if row['clip_embedding']:
                        tag_list = scorer.tagger.get_tags_from_embedding(
                            row['clip_embedding'], threshold=threshold, max_tags=max_tags
                        )
                        tags = tags_to_string(tag_list) if tag_list else None
                        conn.execute(
                            "UPDATE photos SET tags = ? WHERE path = ?",
                            (tags, row['path'])
                        )
                        updated += 1
                conn.commit()
            print(f"Updated tags for {updated} photos")

        elif tag_model in ('ram++', 'qwen2.5-vl-7b', 'qwen3-vl-2b'):
            # Need to load images for VLM/RAM++ tagging
            print(f"Loading {tag_model} model...")
            model_key = {'ram++': 'ram_tagger', 'qwen2.5-vl-7b': 'vlm_tagger', 'qwen3-vl-2b': 'qwen3_vl_tagger'}[tag_model]
            tagger = model_manager.load_model_only(model_key)
            if not tagger:
                print(f"Failed to load {tag_model}")
                exit(1)

            from utils import tags_to_string
            tagging_settings = config.get_tagging_settings()
            max_tags = tagging_settings.get('max_tags', 5)
            updated = 0

            if tag_model == 'ram++':
                # RAM++ uses stored thumbnails to avoid loading full-res images
                # (RAM++ needs ~5 GB+ at full resolution).
                from PIL import Image
                from io import BytesIO

                with get_connection(args.db) as conn:
                    cursor = conn.execute(
                        "SELECT path, thumbnail FROM photos WHERE clip_embedding IS NOT NULL"
                    )
                    for row in tqdm(cursor, desc="Tagging (thumbnail)", total=photo_count):
                        thumb_blob = row['thumbnail']
                        if not thumb_blob:
                            continue
                        try:
                            pil_img = Image.open(BytesIO(thumb_blob)).convert('RGB')
                        except Exception as e:
                            print(f"Failed to decode thumbnail for {row['path']}: {e}")
                            continue

                        tag_list = tagger.tag_image(pil_img, max_tags=max_tags)
                        tags = tags_to_string(tag_list) if tag_list else None
                        conn.execute(
                            "UPDATE photos SET tags = ? WHERE path = ?",
                            (tags, row['path'])
                        )
                        updated += 1
                    conn.commit()
            else:
                # VLM taggers load full images from disk
                from utils import load_image_from_path, _rawpy_lock
                batch_size = 16

                with get_connection(args.db) as conn:
                    photos = conn.execute(
                        "SELECT path FROM photos WHERE clip_embedding IS NOT NULL"
                    ).fetchall()
                    for i in tqdm(range(0, len(photos), batch_size), desc="Tagging batches"):
                        batch = photos[i:i + batch_size]
                        images = []
                        paths = []

                        for row in batch:
                            try:
                                pil_img, _ = load_image_from_path(row['path'], lock=_rawpy_lock)
                                if pil_img:
                                    images.append(pil_img)
                                    paths.append(row['path'])
                            except Exception as e:
                                print(f"Failed to load {row['path']}: {e}")

                        if images:
                            tags_batch = tagger.tag_batch(images, max_tags=max_tags)
                            for path, tag_list in zip(paths, tags_batch):
                                tags = tags_to_string(tag_list) if tag_list else None
                                conn.execute(
                                    "UPDATE photos SET tags = ? WHERE path = ?",
                                    (tags, path)
                                )
                                updated += 1

                    conn.commit()

            model_manager.unload_all()
            print(f"Updated tags for {updated} photos")

        exit()

    # Recompute average scores (lightweight - no GPU needed)
    if args.recompute_average or args.recompute_category:
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        normalizer = None
        norm_settings = scorer.config.get_normalization_settings()
        if norm_settings.get('method') == 'percentile':
            print("Computing percentiles for normalization...")
            per_category = norm_settings.get('per_category', False)
            category_min_samples = norm_settings.get('category_min_samples', 50)
            normalizer = PercentileNormalizer(
                scorer.db_path,
                target_percentile=norm_settings.get('percentile_target', 95),
                per_category=per_category,
                category_min_samples=category_min_samples
            )
            normalizer.compute_percentiles()

        scorer.update_all_aggregates(
            use_embeddings=True,
            normalizer=normalizer,
            category_filter=args.recompute_category,
        )
        if not args.recompute_category:
            process_bursts(scorer.db_path, scorer.config.config_path)
        print("Recalculation Done.")
        exit()

    # Export CSV mode (lightweight - no GPU needed)
    if args.export_csv:
        import csv
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if args.export_csv == 'auto':
            output_file = f"facet_export_{timestamp}.csv"
        else:
            output_file = args.export_csv

        with get_connection(args.db) as conn:
            cursor = conn.execute("""
                SELECT path, filename, date_taken, category, aggregate, aesthetic,
                       comp_score, face_quality, tech_sharpness, exposure_score,
                       color_score, tags, camera_model, lens_model
                FROM photos
                ORDER BY aggregate DESC
            """)

            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'path', 'filename', 'date_taken', 'category', 'aggregate',
                    'aesthetic', 'comp_score', 'face_quality', 'tech_sharpness',
                    'exposure_score', 'color_score', 'tags', 'camera_model', 'lens_model'
                ])
                for row in cursor:
                    writer.writerow([
                        row['path'], row['filename'], row['date_taken'], row['category'],
                        row['aggregate'], row['aesthetic'], row['comp_score'],
                        row['face_quality'], row['tech_sharpness'], row['exposure_score'],
                        row['color_score'], row['tags'], row['camera_model'], row['lens_model']
                    ])
        row_count = sum(1 for _ in open(output_file, encoding='utf-8')) - 1
        print(f"Exported {row_count} photos to {output_file}")
        exit()

    # Export JSON mode (lightweight - no GPU needed)
    if args.export_json:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if args.export_json == 'auto':
            output_file = f"facet_export_{timestamp}.json"
        else:
            output_file = args.export_json

        with get_connection(args.db) as conn:
            cursor = conn.execute("""
                SELECT path, filename, date_taken, category, aggregate, aesthetic,
                       comp_score, face_quality, tech_sharpness, exposure_score,
                       color_score, tags, camera_model, lens_model
                FROM photos
                ORDER BY aggregate DESC
            """)

            photos = []
            for row in cursor:
                photos.append({
                    'path': row['path'],
                    'filename': row['filename'],
                    'date_taken': row['date_taken'],
                    'category': row['category'],
                    'scores': {
                        'aggregate': row['aggregate'],
                        'aesthetic': row['aesthetic'],
                        'comp_score': row['comp_score'],
                        'face_quality': row['face_quality'],
                        'tech_sharpness': row['tech_sharpness'],
                        'exposure_score': row['exposure_score'],
                        'color_score': row['color_score'],
                    },
                    'tags': row['tags'],
                    'camera_model': row['camera_model'],
                    'lens_model': row['lens_model'],
                })

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({'photos': photos, 'count': len(photos)}, f, indent=2)

        print(f"Exported {len(photos)} photos to {output_file}")
        exit()

    # Full mode - initialize with GPU models for photo processing
    # Multi-pass mode skips eager loading of heavy GPU models (CLIP, SAMP-Net)
    # since multi-pass loads its own models per pass via ModelManager
    use_multi_pass = not (args.dry_run or args.single_pass)
    scorer = Facet(db_path=args.db, config_path=args.config, multi_pass=use_multi_pass)

    if not args.photo_paths:
        print("Error: photo_paths is required unless using --recompute-average or --compute-percentiles")
        parser.print_help()
        exit(1)

    # 1. Gather files recursively from subfolders (or single files)
    valid_suffixes = {'.jpg', '.jpeg', '.cr2', '.cr3'}
    all_files = []

    # Get scanning settings
    skip_hidden = scorer.config.get_scanning_settings().get('skip_hidden_directories', True)

    for path_str in args.photo_paths:
        base_path = Path(path_str).resolve()
        if not base_path.exists():
            print(f"Warning: Path does not exist: {path_str}")
            continue
        if base_path.is_file():
            # Single file - check if it's a valid image type
            if base_path.suffix.lower() in valid_suffixes:
                all_files.append(base_path)
            else:
                print(f"Warning: Unsupported file type: {path_str}")
        else:
            # Directory - use os.walk to traverse, optionally skipping hidden directories
            for root, dirs, files in os.walk(base_path):
                # Prune hidden directories if configured
                if skip_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith('.')]

                # Add matching files
                for f in files:
                    p = Path(root) / f
                    if p.suffix.lower() in valid_suffixes:
                        all_files.append(p)

    # Deduplicate (needed for case-insensitive filesystems like Windows)
    all_files = list({f.resolve(): f for f in all_files}.values())

    # Identify JPEGs to avoid double-processing if RAW+JPEG pairs exist
    jpegs_stems = {f.stem.lower() for f in all_files if f.suffix.lower() in ['.jpg', '.jpeg']}
    scanned_set = set() if args.force else scorer.get_already_scanned_set()

    # Filter the list to only include new or un-scanned files
    todo_list = [f for f in all_files if str(f.resolve()) not in scanned_set
                 and not (f.suffix.lower() in ['.cr2', '.cr3'] and f.stem.lower() in jpegs_stems)]

    print(f"Found {len(all_files)} total, processing {len(todo_list)} new files.")

    if not todo_list:
        print("No new files to process.")
        exit()

    # Dry-run mode - score sample photos without saving to database
    if args.dry_run:
        sample_count = min(args.dry_run_count, len(todo_list))
        sample_files = todo_list[:sample_count]
        print(f"\n{'='*80}")
        print(f"DRY RUN MODE - Scoring {sample_count} sample photos (not saving to database)")
        print(f"{'='*80}\n")

        results = []
        for i, photo_path in enumerate(sample_files, 1):
            print(f"[{i}/{sample_count}] Processing {photo_path.name}...", end=' ', flush=True)
            try:
                result, _ = process_single_photo(photo_path, scorer)
                if result:
                    results.append({
                        'filename': photo_path.name,
                        'category': result.get('category', 'unknown'),
                        'aesthetic': result.get('aesthetic', 0),
                        'comp_score': result.get('comp_score', 0),
                        'aggregate': result.get('aggregate', 0),
                        'face_quality': result.get('face_quality', 0),
                    })
                    print(f"OK (aggregate: {result.get('aggregate', 0):.2f})")
                else:
                    print("FAILED")
            except Exception as e:
                print(f"ERROR: {e}")

        # Print results table
        if results:
            print(f"\n{'='*80}")
            print(f"{'Filename':<40} {'Category':<15} {'Aes':>6} {'Comp':>6} {'Face':>6} {'Aggr':>6}")
            print(f"{'-'*40} {'-'*15} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")
            for r in results:
                print(f"{r['filename'][:39]:<40} {r['category'][:14]:<15} "
                      f"{r['aesthetic']:>6.2f} {r['comp_score']:>6.2f} "
                      f"{r['face_quality']:>6.2f} {r['aggregate']:>6.2f}")
            print(f"{'='*80}")

            # Summary stats
            avg_agg = sum(r['aggregate'] for r in results) / len(results)
            avg_aes = sum(r['aesthetic'] for r in results) / len(results)
            print(f"\nSummary: {len(results)} photos scored")
            print(f"  Average aggregate: {avg_agg:.2f}")
            print(f"  Average aesthetic: {avg_aes:.2f}")
        exit()

    # 2. Main Processing Loop
    try:
        # Check for single-pass mode or specific pass
        if args.single_pass_name:
            # Run specific pass only
            from processing.multi_pass import run_single_pass
            from models.model_manager import ModelManager

            model_manager = ModelManager(scorer.config)
            todo_paths = [str(f) for f in todo_list]
            processed = run_single_pass(todo_paths, args.single_pass_name, scorer, model_manager)
            print(f"Processed {processed} photos with {args.single_pass_name} pass")

        elif args.single_pass:
            # Force single-pass mode (old --batch behavior - all models loaded at once)
            from processing.batch_processor import BatchProcessor
            from config import recalculate_batch_settings

            proc_settings = scorer.config.get_processing_settings()
            auto_tuning = proc_settings.get('auto_tuning', {})
            tuning_interval = auto_tuning.get('tuning_interval_images', 50)

            # Start with config defaults
            current_settings = {
                'batch_size': proc_settings.get('gpu_batch_size', 16),
                'num_workers': proc_settings.get('num_workers', 4),
                'auto_tuning': auto_tuning,
            }

            tuning_enabled = auto_tuning.get('enabled', True)
            todo_paths = [str(f) for f in todo_list]

            print(f"Single-pass mode: {current_settings['batch_size']} batch, "
                  f"{current_settings['num_workers']} workers")

            processor = BatchProcessor(
                scorer,
                batch_size=current_settings['batch_size'],
                num_workers=current_settings['num_workers']
            )

            calibration_done = [False]

            def calibration_callback(metrics):
                if calibration_done[0]:
                    return False
                old_workers = current_settings['num_workers']
                new_settings = recalculate_batch_settings(metrics, current_settings)
                current_settings.update(new_settings)
                calibration_done[0] = True
                if current_settings['num_workers'] != old_workers:
                    print(f"  Calibrated: {current_settings['num_workers']} workers")
                    return True
                return False

            def tuning_callback(metrics):
                old_batch_size = current_settings['batch_size']
                new_settings = recalculate_batch_settings(metrics, current_settings)
                current_settings.update(new_settings)
                if current_settings['batch_size'] != old_batch_size:
                    processor.batch_size = current_settings['batch_size']

            remaining_paths = processor.process_stream(
                iter(todo_paths), len(todo_paths),
                tuning_callback=tuning_callback if tuning_enabled else None,
                tuning_interval=tuning_interval,
                calibration_callback=calibration_callback if tuning_enabled else None
            )

            if remaining_paths:
                processor = BatchProcessor(
                    scorer,
                    batch_size=current_settings['batch_size'],
                    num_workers=current_settings['num_workers'],
                    prefetch_multiplier=current_settings.get('prefetch_queue_multiplier', 2)
                )
                processor.process_stream(
                    iter(remaining_paths), len(remaining_paths),
                    tuning_callback=tuning_callback if tuning_enabled else None,
                    tuning_interval=tuning_interval,
                    calibration_callback=None
                )

        else:
            # Default: Multi-pass processing (auto VRAM detection, sequential model loading)
            from processing.multi_pass import ChunkedMultiPassProcessor
            from models.model_manager import ModelManager

            model_manager = ModelManager(scorer.config)
            todo_paths = [str(f) for f in todo_list]

            # Check processing mode from config
            proc_settings = scorer.config.get_processing_settings()
            mode = proc_settings.get('mode', 'auto')

            if mode != 'single-pass':
                processor = ChunkedMultiPassProcessor(
                    scorer, model_manager, scorer.config.config
                )
                processor.process_directory(todo_paths)
            else:
                # Force single-pass mode
                from processing.batch_processor import BatchProcessor

                processor = BatchProcessor(
                    scorer,
                    batch_size=proc_settings.get('gpu_batch_size', 16),
                    num_workers=proc_settings.get('num_workers', 4)
                )
                processor.process_files(todo_paths)

    except KeyboardInterrupt:
        print("\nInterrupted.")

    # 3. Finalization
    scorer.commit()

    # 4. Process bursts
    # Note: Run --cluster-faces-incremental separately if person_ids are needed for grouping
    process_bursts(scorer.db_path, scorer.config.config_path)

    # 6. Auto-tag photos using stored CLIP embeddings
    from tag_existing import run_tagging
    from models.tagger import CLIPTagger

    # Use existing tagger if available, or create one with scorer's model
    tagger = scorer.tagger if scorer.tagger else CLIPTagger(scorer.model, scorer.device, config=scorer.config)

    tagged = run_tagging(scorer.db_path, tagger, scorer.config)
    if tagged:
        print(f"Tagged {tagged} photos with missing tags.")
    elif tagged == 0:
        print("All photos already have tags.")

    print("All tasks complete.")
