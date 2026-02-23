#!/usr/bin/env python3
"""
Script to add tags to existing photos using stored CLIP embeddings.
This is much faster than rescanning as it doesn't require GPU inference.
"""

import sqlite3
import argparse
from pathlib import Path

from models.tagger import CLIPTagger
from utils import tags_to_string, get_tag_params
from db.tags import migrate_tags_to_lookup


def tag_untagged_photos(db_path, tagger, threshold=0.22, max_tags=5, verbose=False, force=False):
    """
    Tag photos that have CLIP embeddings but no tags.

    Args:
        db_path: Path to the SQLite database
        tagger: Initialized CLIPTagger instance
        threshold: Minimum similarity threshold for tags
        max_tags: Maximum tags per image
        verbose: Print each tagged photo
        force: Re-tag all photos, not just untagged ones

    Returns:
        Number of photos tagged
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if force:
            rows = conn.execute('''
                SELECT path, filename, clip_embedding
                FROM photos
                WHERE clip_embedding IS NOT NULL
            ''').fetchall()
        else:
            rows = conn.execute('''
                SELECT path, filename, clip_embedding
                FROM photos
                WHERE clip_embedding IS NOT NULL
                AND (tags IS NULL OR tags = '')
            ''').fetchall()

        if not rows:
            return 0

        tagged_count = 0
        for row in rows:
            tag_list = tagger.get_tags_from_embedding(
                row['clip_embedding'], threshold=threshold, max_tags=max_tags
            )
            if tag_list:
                tags_str = tags_to_string(tag_list)
                conn.execute('UPDATE photos SET tags = ? WHERE path = ?', (tags_str, row['path']))
                tagged_count += 1
                if verbose:
                    print(f"  {row['filename']}: {tags_str}")

        conn.commit()
        return tagged_count


def run_tagging(db_path, tagger, config):
    """
    Run tagging using settings from config.

    Args:
        db_path: Path to SQLite database
        tagger: Initialized CLIPTagger instance
        config: ScoringConfig instance

    Returns:
        Number of photos tagged, or None if disabled
    """
    tag_settings = config.get_tagging_settings()
    if not tag_settings.get('enabled', True):
        return None

    threshold, max_tags = get_tag_params(config)

    return tag_untagged_photos(db_path, tagger, threshold, max_tags)


def main():
    parser = argparse.ArgumentParser(description='Tag existing photos using stored CLIP embeddings')
    parser.add_argument('--db', default='photo_scores_pro.db', help='Database path')
    parser.add_argument('--config', default='scoring_config.json', help='Config file path')
    parser.add_argument('--threshold', type=float, default=None, help='Override similarity threshold')
    parser.add_argument('--max-tags', type=int, default=None, help='Override max tags per image')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be tagged without saving')
    parser.add_argument('--force', action='store_true', help='Re-tag all photos, not just untagged ones')
    args = parser.parse_args()

    # Load config
    from config import ScoringConfig
    config = ScoringConfig(args.config)
    clip_settings = config.get_clip_settings()
    tag_settings = config.get_tagging_settings()

    threshold = args.threshold or clip_settings.get('similarity_threshold_percent', 22) / 100
    max_tags = args.max_tags or tag_settings.get('max_tags', 5)

    print(f"Loading CLIP model for tagging...")
    print(f"  Threshold: {threshold}")
    print(f"  Max tags: {max_tags}")

    # Load CLIP model and tagger
    import torch
    import open_clip

    # Resolve CLIP model from config (supports SigLIP 2 or legacy ViT-L-14)
    model_config = config.get_model_config()
    profiles = model_config.get('profiles', {})
    profile_name = model_config.get('vram_profile', 'legacy')
    active_profile = profiles.get(profile_name, profiles.get('legacy', {}))
    clip_config_key = active_profile.get('clip_config', 'clip')
    clip_cfg = model_config.get(clip_config_key, model_config.get('clip', {}))
    clip_model_name = clip_cfg.get('model_name', 'ViT-L-14')
    clip_pretrained = clip_cfg.get('pretrained', 'laion2b_s32b_b82k')

    model, _, _ = open_clip.create_model_and_transforms(clip_model_name, pretrained=clip_pretrained)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = model.to(device).eval()

    tagger = CLIPTagger(model, device, config=config, model_name=clip_model_name)
    print(f"Tagger initialized with {len(tagger.tag_vocabulary)} tag categories")

    # Count photos to tag
    conn = sqlite3.connect(args.db)
    if args.force:
        count = conn.execute('''
            SELECT COUNT(*) FROM photos WHERE clip_embedding IS NOT NULL
        ''').fetchone()[0]
    else:
        count = conn.execute('''
            SELECT COUNT(*) FROM photos
            WHERE clip_embedding IS NOT NULL AND (tags IS NULL OR tags = '')
        ''').fetchone()[0]
    conn.close()

    mode = "[FORCE] Re-tagging all" if args.force else "Found"
    print(f"\n{mode} {count} photos to tag\n")

    if args.dry_run:
        print(f"[DRY RUN] Would tag up to {count} photos")
    else:
        tagged = tag_untagged_photos(args.db, tagger, threshold, max_tags, verbose=True, force=args.force)
        print(f"\nTagged {tagged} photos")

        # Update photo_tags lookup table for fast queries
        if tagged > 0:
            print("\nUpdating photo_tags lookup table...")
            migrate_tags_to_lookup(args.db)


if __name__ == '__main__':
    main()
