"""Reviewed, catalog-only logical photo identity changes."""
import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import CurrentUser, require_authenticated, require_edition, require_auth
from api.database import get_db
from api import logical_asset_changes, logical_reviews
from api.models.logical_assets import LogicalAssetApply, LogicalAssetChange, LogicalAssetPreview, LogicalAssetResult, LogicalAssetContext, LogicalReviewState, LogicalReviewChange

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


@router.get('/by-photo', response_model=LogicalAssetContext)
def photo_context(path: str = Query(...), user: CurrentUser = Depends(require_authenticated)):
    try:
        with get_db() as conn:
            conn.execute('BEGIN')
            return logical_asset_changes.context(conn, path, user.user_id)
    except sqlite3.Error:
        logger.exception('Logical photo context failed')
        raise HTTPException(503, 'Logical photo context is unavailable') from None


@router.get('/review', response_model=LogicalReviewState)
def review_state(asset_id: str = Query(..., pattern=r'^[a-f0-9]{32}$'), user: CurrentUser = Depends(require_authenticated)):
    try:
        with get_db() as conn:
            conn.execute('BEGIN')
            return logical_reviews.read(conn, asset_id, user.user_id)
    except sqlite3.Error:
        logger.exception('Logical review read failed')
        raise HTTPException(503, 'Logical review is unavailable') from None


@router.post('/review', response_model=LogicalReviewState)
def change_review(body: LogicalReviewChange, user: CurrentUser = Depends(require_auth)):
    try:
        with get_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            result = logical_reviews.apply(conn, body, user)
            conn.commit()
            return result
    except sqlite3.Error:
        logger.exception('Logical review change failed')
        raise HTTPException(503, 'Logical review was not accepted') from None
