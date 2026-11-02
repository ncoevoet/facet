"""Reviewed, catalog-only logical photo identity changes."""
import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from api.auth import CurrentUser, require_authenticated, require_edition
from api.database import get_db
from api import logical_asset_changes
from api.models.logical_assets import LogicalAssetApply, LogicalAssetChange, LogicalAssetPreview, LogicalAssetResult

router = APIRouter(prefix='/api/logical_assets', tags=['logical_assets'])
logger = logging.getLogger(__name__)


@router.post('/preview', response_model=LogicalAssetPreview)
def preview_change(body: LogicalAssetChange, user: CurrentUser = Depends(require_authenticated)):
    try:
        with get_db() as conn:
            conn.execute('BEGIN')
            return logical_asset_changes.preview(conn, body, user.user_id)
    except sqlite3.Error:
        logger.exception('Logical photo preview failed')
        raise HTTPException(503, 'Logical photo preview is unavailable') from None


@router.post('/apply', response_model=LogicalAssetResult)
def apply_change(body: LogicalAssetApply, user: CurrentUser = Depends(require_edition)):
    try:
        with get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            result = logical_asset_changes.apply(conn, body, user.user_id)
            conn.commit()
            return result
    except sqlite3.Error:
        logger.exception('Logical photo change failed')
        raise HTTPException(503, 'Logical photo change was not accepted') from None
