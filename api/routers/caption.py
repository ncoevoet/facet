"""
AI Caption router — on-demand photo captioning via VLM.

Returns a cached caption from the DB if available, otherwise generates one
using the VLM tagger (Qwen3-VL / Qwen2.5-VL) and stores it for future use.
Optionally translates captions to a configured target language via MarianMT.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition, is_edition_authenticated
from api.config import VIEWER_CONFIG, _FULL_CONFIG
from api.database import get_async_db, get_db
from api.db_helpers import get_existing_columns, get_visibility_clause
from api.path_validation import resolve_photo_disk_path

from api.model_cache import (
    get_or_load_vlm_tagger,
    resolve_vlm_config,
    translate_text,
    translation_target,
    vlm_generate_lock,
)

router = APIRouter(tags=["caption"])
logger = logging.getLogger(__name__)


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

    async with get_async_db() as conn:
        user_id = user.user_id if user else None
        vis_sql, vis_params = get_visibility_clause(user_id)

        # Check the photo exists
        cur = await conn.execute(
            f"SELECT path FROM photos WHERE path = ? AND {vis_sql}",
            [path] + vis_params,
        )
        photo = await cur.fetchone()
        await cur.close()

        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        # get_existing_columns() with no args reads the cached column set
        # (or opens its own sync connection); it must not receive the
        # aiosqlite conn, whose execute() is a coroutine.
        existing_cols = get_existing_columns()

        # Determine if we should return a translation
        target_lang = translation_target(lang)
        wants_translation = target_lang is not None

        # Check if caption column exists and return cached caption/translation
        if 'caption' in existing_cols:
            cols_to_fetch = 'caption'
            if wants_translation and 'caption_translated' in existing_cols:
                cols_to_fetch = 'caption, caption_translated'

            cur = await conn.execute(
                f"SELECT {cols_to_fetch} FROM photos WHERE path = ?", [path]
            )
            row = await cur.fetchone()
            await cur.close()

            if row and row['caption']:
                # If translation requested and cached, return it
                if wants_translation and 'caption_translated' in existing_cols:
                    if row['caption_translated']:
                        return {
                            "caption": row['caption_translated'],
                            "source": "cached",
                            "lang": target_lang,
                        }
                    # Translate on-demand and cache. Translation is a blocking
                    # model call — offload it from the event loop.
                    translated = await asyncio.to_thread(
                        translate_text, row['caption'], target_lang
                    )
                    if translated:
                        await conn.execute(
                            "UPDATE photos SET caption_translated = ? WHERE path = ?",
                            [translated, path],
                        )
                        await conn.commit()
                        return {
                            "caption": translated,
                            "source": "translated",
                            "lang": target_lang,
                        }

                # Return English caption
                return {"caption": row['caption'], "source": "cached"}

        # F5 quality gate: when narrative_moments.caption_min_confidence > 0, skip
        # on-demand generation for unlabelled / 'other' / low-confidence photos so
        # the gate holds on the API path too (default 0 = generate for any photo).
        caption_min_conf = float((_FULL_CONFIG.get('narrative_moments', {}) or {}).get('caption_min_confidence', 0) or 0)
        if caption_min_conf > 0 and {'narrative_moment', 'narrative_moment_confidence'} <= set(existing_cols):
            cur = await conn.execute(
                "SELECT narrative_moment, narrative_moment_confidence FROM photos WHERE path = ?", [path]
            )
            mrow = await cur.fetchone()
            await cur.close()
            moment = mrow['narrative_moment'] if mrow else None
            mconf = mrow['narrative_moment_confidence'] if mrow else None
            if not moment or moment == 'other' or mconf is None or mconf < caption_min_conf:
                return {"caption": None, "source": "gated"}

        if not is_edition_authenticated(user):
            return {"caption": None, "source": "edition_required"}

        # Try to generate via VLM. Generation is a blocking GPU/CPU call —
        # offload it from the event loop.
        caption = await asyncio.to_thread(_generate_caption, path)
        if caption is None:
            raise HTTPException(
                status_code=503,
                detail="No cached caption and VLM is unavailable",
            )

        # Store in DB if the column exists
        if 'caption' in existing_cols:
            await conn.execute(
                "UPDATE photos SET caption = ? WHERE path = ?",
                [caption, path],
            )
            await conn.commit()

        # If translation requested, translate the freshly generated caption
        if wants_translation:
            translated = await asyncio.to_thread(
                translate_text, caption, target_lang
            )
            if translated and 'caption_translated' in existing_cols:
                await conn.execute(
                    "UPDATE photos SET caption_translated = ? WHERE path = ?",
                    [translated, path],
                )
                await conn.commit()
                return {
                    "caption": translated,
                    "source": "translated",
                    "lang": target_lang,
                }

        return {"caption": caption, "source": "generated"}


def _generate_caption(photo_path: str) -> Optional[str]:
    """Generate a caption for a photo using the VLM tagger.

    ``photo_path`` must already be a DB-validated, user-visible path. The disk
    path is resolved through the scan-directory allowlist before the image is
    opened. Returns None if VLM is unavailable (wrong profile, missing config,
    or a generation error).
    """
    vlm_config = resolve_vlm_config()
    if not vlm_config:
        return None

    disk_path = resolve_photo_disk_path(photo_path)

    try:
        from PIL import Image

        tagger = get_or_load_vlm_tagger(vlm_config)

        img = Image.open(disk_path).convert('RGB')
        img.thumbnail((640, 640))

        with vlm_generate_lock:
            caption = tagger.generate(
                img,
                "Describe this photo in one concise sentence.",
                max_new_tokens=100,
            )
        return caption.strip() if caption else None

    except Exception:
        logger.exception("VLM caption generation failed")
        return None


class CaptionUpdate(BaseModel):
    path: str
    caption: str


@router.put("/api/caption")
def api_update_caption(
    body: CaptionUpdate,
    user: CurrentUser = Depends(require_edition),
):
    """Update the caption for a photo (edition mode required).

    Clears the cached translation so it gets regenerated on next request.
    """
    with get_db() as conn:
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
