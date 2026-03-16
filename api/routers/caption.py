"""
AI Caption router — on-demand photo captioning via VLM.

Returns a cached caption from the DB if available, otherwise generates one
using the VLM tagger (Qwen3-VL / Qwen2.5-VL) and stores it for future use.
Optionally translates captions to a configured target language via MarianMT.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition
from api.config import VIEWER_CONFIG, _FULL_CONFIG
from api.database import get_db_connection
from api.db_helpers import get_existing_columns, get_visibility_clause

from api.model_cache import get_or_load_vlm_tagger

router = APIRouter(tags=["caption"])
logger = logging.getLogger(__name__)

SUPPORTED_TRANSLATION_LANGS = {'fr', 'de', 'es', 'it'}


def _get_target_language() -> str:
    """Return the configured translation target language, or '' if disabled."""
    return _FULL_CONFIG.get('translation', {}).get('target_language', '')


@router.get("/api/caption")
async def api_caption(
    path: str = Query(...),
    lang: Optional[str] = Query(None),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get an AI-generated caption for a photo.

    Returns a cached caption if available, otherwise generates one via VLM.
    Returns 503 if no cached caption exists and VLM is unavailable.

    If ``lang`` matches the configured ``target_language``, returns the
    translated caption (generating and caching it on-demand if needed).
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

        existing_cols = get_existing_columns(conn)

        # Determine if we should return a translation
        target_lang = _get_target_language()
        wants_translation = (
            lang
            and lang != 'en'
            and lang in SUPPORTED_TRANSLATION_LANGS
            and lang == target_lang
        )

        # Check if caption column exists and return cached caption/translation
        if 'caption' in existing_cols:
            cols_to_fetch = 'caption'
            if wants_translation and 'caption_translated' in existing_cols:
                cols_to_fetch = 'caption, caption_translated'

            row = conn.execute(
                f"SELECT {cols_to_fetch} FROM photos WHERE path = ?", [path]
            ).fetchone()

            if row and row['caption']:
                # If translation requested and cached, return it
                if wants_translation and 'caption_translated' in existing_cols:
                    if row['caption_translated']:
                        return {
                            "caption": row['caption_translated'],
                            "source": "cached",
                            "lang": target_lang,
                        }
                    # Translate on-demand and cache
                    translated = _translate_caption(row['caption'], target_lang)
                    if translated:
                        conn.execute(
                            "UPDATE photos SET caption_translated = ? WHERE path = ?",
                            [translated, path],
                        )
                        conn.commit()
                        return {
                            "caption": translated,
                            "source": "translated",
                            "lang": target_lang,
                        }

                # Return English caption
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

        # If translation requested, translate the freshly generated caption
        if wants_translation:
            translated = _translate_caption(caption, target_lang)
            if translated and 'caption_translated' in existing_cols:
                conn.execute(
                    "UPDATE photos SET caption_translated = ? WHERE path = ?",
                    [translated, path],
                )
                conn.commit()
                return {
                    "caption": translated,
                    "source": "translated",
                    "lang": target_lang,
                }

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


def _translate_caption(caption: str, target_lang: str) -> Optional[str]:
    """Translate a caption to the target language using MarianMT.

    Returns None if translation fails.
    """
    try:
        from api.model_cache import get_or_load_caption_translator

        translator = get_or_load_caption_translator(target_lang)
        return translator.translate(caption)
    except Exception:
        logger.exception("Caption translation failed for lang=%s", target_lang)
        return None


class CaptionUpdate(BaseModel):
    path: str
    caption: str


@router.put("/api/caption")
async def api_update_caption(
    body: CaptionUpdate,
    user: CurrentUser = Depends(require_edition),
):
    """Update the caption for a photo (edition mode required).

    Clears the cached translation so it gets regenerated on next request.
    """
    conn = get_db_connection()
    try:
        existing_cols = get_existing_columns(conn)
        if 'caption' not in existing_cols:
            raise HTTPException(status_code=400, detail="Caption column not available")

        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        row = conn.execute(
            f"SELECT path FROM photos WHERE path = ? AND {vis_sql}",
            [body.path] + vis_params,
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Photo not found")

        # Clear translation when caption is manually edited
        if 'caption_translated' in existing_cols:
            conn.execute(
                f"UPDATE photos SET caption = ?, caption_translated = NULL WHERE path = ? AND {vis_sql}",
                [body.caption or None, body.path] + vis_params,
            )
        else:
            conn.execute(
                f"UPDATE photos SET caption = ? WHERE path = ? AND {vis_sql}",
                [body.caption or None, body.path] + vis_params,
            )
        conn.commit()
        return {"caption": body.caption, "source": "manual"}
    finally:
        conn.close()
