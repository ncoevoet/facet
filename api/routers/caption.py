"""
AI Caption router — on-demand photo captioning via VLM.

Returns a cached caption from the DB if available, otherwise generates one
using the VLM tagger (Qwen3-VL / Qwen2.5-VL) and stores it for future use.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG, _FULL_CONFIG
from api.database import get_db_connection
from api.db_helpers import get_existing_columns, get_visibility_clause

from api.model_cache import get_or_load_vlm_tagger

router = APIRouter(tags=["caption"])
logger = logging.getLogger(__name__)


@router.get("/api/caption")
async def api_caption(
    path: str = Query(...),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get an AI-generated caption for a photo.

    Returns a cached caption if available, otherwise generates one via VLM.
    Returns 503 if no cached caption exists and VLM is unavailable.
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_captions', False):
        raise HTTPException(status_code=403, detail="Caption feature is disabled")

    conn = get_db_connection()
    try:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        # Check the photo exists
        photo = conn.execute(
            f"SELECT path FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params,
        ).fetchone()

        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        # Check if caption column exists and return cached caption
        existing_cols = get_existing_columns(conn)
        if 'caption' in existing_cols:
            row = conn.execute(
                "SELECT caption FROM photos WHERE path = ?", [path]
            ).fetchone()
            if row and row['caption']:
                return {"caption": row['caption'], "source": "cached"}

        # Try to generate via VLM
        caption = _generate_caption(path)
        if caption is None:
            raise HTTPException(
                status_code=503,
                detail="No cached caption and VLM is unavailable",
            )

        # Store in DB if the column exists
        if 'caption' in existing_cols:
            conn.execute(
                "UPDATE photos SET caption = ? WHERE path = ?",
                [caption, path],
            )
            conn.commit()

        return {"caption": caption, "source": "generated"}

    finally:
        conn.close()


def _resolve_vlm_config() -> Optional[dict]:
    """Resolve the VLM tagger config dict from the active profile.

    Returns the model config dict (with model_path, etc.) or None if
    the active profile doesn't use a VLM tagger.
    """
    models_config = _FULL_CONFIG.get('models', {})
    profile_name = models_config.get('vram_profile', 'legacy')
    profile = models_config.get('profiles', {}).get(profile_name, {})
    tagging_model = profile.get('tagging_model', '')

    # Map tagging_model name to config key
    model_key_map = {
        'qwen3-vl-2b': 'qwen3_vl_2b',
        'qwen2.5-vl-7b': 'qwen2_5_vl_7b',
    }
    config_key = model_key_map.get(tagging_model)
    if not config_key:
        return None

    vlm_config = models_config.get(config_key, {})
    return vlm_config if vlm_config.get('model_path') else None


def _generate_caption(photo_path: str) -> Optional[str]:
    """Generate a caption for a photo using the VLM tagger.

    Returns None if VLM is unavailable (wrong profile, missing config, etc.).
    """
    try:
        vlm_config = _resolve_vlm_config()
        if not vlm_config:
            return None

        from api.config import map_disk_path
        from PIL import Image

        tagger = get_or_load_vlm_tagger(vlm_config, _FULL_CONFIG)

        disk_path = map_disk_path(photo_path)
        img = Image.open(disk_path).convert('RGB')
        img.thumbnail((640, 640))

        caption = tagger.generate(
            img,
            "Describe this photo in one concise sentence.",
            max_new_tokens=100,
        )
        return caption.strip() if caption else None

    except Exception:
        logger.exception("VLM caption generation failed")
        return None
