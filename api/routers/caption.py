"""
AI Caption router — on-demand photo captioning via VLM.

GET returns the stored caption (never generates or writes). POST (edition only)
generates one using the VLM tagger (Qwen3-VL / Qwen2.5-VL), stores it, and
optionally translates it to a configured target language via MarianMT.
"""

import asyncio
import logging

from typing import Optional

import licensing
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import CurrentUser, get_optional_user, require_edition
from api.config import VIEWER_CONFIG, _FULL_CONFIG
from api.database import get_async_db, get_db
from api.db_helpers import get_existing_columns, get_visibility_clause
from api.inflight import GenerationInterrupted, InflightGate
from api.models.media import MediaCaptionResponse
from api.path_validation import resolve_photo_disk_path

from api.model_cache import (
    get_or_load_vlm_tagger,
    resolve_vlm_config,
    translate_text,
    translation_target,
    vlm_accelerator_lock,
    vlm_generate_lock,
)

router = APIRouter(tags=["caption"])
logger = logging.getLogger(__name__)
_caption_flights = InflightGate()


@router.get("/api/caption", response_model=MediaCaptionResponse, response_model_exclude_unset=True)
async def api_caption(
    path: str = Query(...),
    lang: Optional[str] = Query(None),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get the stored AI caption for a photo. Strictly read-only.

    Never generates, translates or writes. With ``lang`` matching the configured
    ``target_language`` the stored translation is returned when there is one,
    otherwise the stored caption. ``source`` is ``none`` when no caption is
    stored; ``POST /api/caption`` produces one.
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_captions', False):
        raise HTTPException(status_code=403, detail="Caption feature is disabled")

    async with get_async_db() as conn:
        await _require_visible_photo(conn, path, user)
        caption, translated = await _stored_caption(conn, path)
        target_lang = translation_target(lang)
        if caption and target_lang and translated:
            return {"caption": translated, "source": "cached", "lang": target_lang}
        if caption:
            return {"caption": caption, "source": "cached"}
        return {"caption": None, "source": "none"}


class CaptionGenerate(BaseModel):
    path: str
    lang: Optional[str] = None


@router.post("/api/caption", response_model=MediaCaptionResponse, response_model_exclude_unset=True)
async def api_generate_caption(
    body: CaptionGenerate,
    user: CurrentUser = Depends(require_edition),
):
    """Generate and store the AI caption for a photo (edition mode required).

    A stored caption is kept as is. Concurrent requests for the same photo share
    one generation. When ``lang`` matches the configured ``target_language`` the
    caption is also translated and the translation stored.
    """
    if not VIEWER_CONFIG.get('features', {}).get('show_captions', False):
        raise HTTPException(status_code=403, detail="Caption feature is disabled")

    path = body.path
    async with get_async_db() as conn:
        await _require_visible_photo(conn, path, user)
        existing_cols = get_existing_columns()
        target_lang = translation_target(body.lang)
        caption, translated = await _stored_caption(conn, path)
        source = "cached"

        if not caption:
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
            async def generate_and_store():
                # Generation is a blocking GPU/CPU call: off the event loop. Only the
                # leader of a shared run stores the caption; joiners resume after it.
                generated = await asyncio.to_thread(_generate_caption, path)
                if generated is not None and 'caption' in existing_cols:
                    await conn.execute("UPDATE photos SET caption = ? WHERE path = ?", [generated, path])
                    await conn.commit()
                return generated

            try:
                caption, _ = await _caption_flights.run(path, generate_and_store)
            except GenerationInterrupted:
                raise HTTPException(status_code=503, detail="Caption generation was interrupted")
            if caption is None:
                raise HTTPException(
                    status_code=503,
                    detail="No cached caption and VLM is unavailable",
                )
            translated = None
            source = "generated"

        if target_lang:
            if not translated:
                translated = await asyncio.to_thread(translate_text, caption, target_lang)
                if translated and 'caption' in existing_cols and 'caption_translated' in existing_cols:
                    await conn.execute(
                        "UPDATE photos SET caption_translated = ? WHERE path = ? AND caption = ?",
                        [translated, path, caption],
                    )
                    await conn.commit()
            if translated:
                return {"caption": translated, "source": "translated", "lang": target_lang}

        return {"caption": caption, "source": source}


async def _require_visible_photo(conn, path, user):
    user_id = user.user_id if user else None
    vis_sql, vis_params = get_visibility_clause(user_id)
    cur = await conn.execute(
        f"SELECT path FROM photos WHERE path = ? AND {vis_sql}",
        [path] + vis_params,
    )
    photo = await cur.fetchone()
    await cur.close()
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")


async def _stored_caption(conn, path):
    """(caption, translated) as stored; either is None when absent or the column is missing."""
    # get_existing_columns() with no args reads the cached column set
    # (or opens its own sync connection); it must not receive the
    # aiosqlite conn, whose execute() is a coroutine.
    existing_cols = get_existing_columns()
    if 'caption' not in existing_cols:
        return None, None
    cols = 'caption, caption_translated' if 'caption_translated' in existing_cols else 'caption'
    cur = await conn.execute(f"SELECT {cols} FROM photos WHERE path = ?", [path])
    row = await cur.fetchone()
    await cur.close()
    if not row:
        return None, None
    return row['caption'], (row['caption_translated'] if 'caption_translated' in existing_cols else None)


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
        from utils.image_loading import load_image_from_path

        tagger = get_or_load_vlm_tagger(vlm_config)

        img, _ = load_image_from_path(disk_path, use_thumbnail=True)
        if img is None:
            return None
        img.thumbnail((640, 640))

        with vlm_generate_lock, vlm_accelerator_lock(tagger):
            caption = tagger.generate(
                img,
                "Describe this photo in one concise sentence.",
                max_new_tokens=100,
            )
        return caption.strip() if caption else None

    except Exception:
        licensing.reraise_if_refused()
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
