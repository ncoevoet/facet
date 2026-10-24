"""Edition-only personal saved GPS places."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from api.auth import CurrentUser, require_edition
from api.config import is_multi_user_enabled
from api.database import get_db
from db import places
from api import place_search

router = APIRouter(tags=['places'])
Latitude = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]


def place_owner(user):
    if not is_multi_user_enabled():
        return 'installation'
    if not user.user_id:
        raise HTTPException(status_code=401, detail='Authentication required')
    return user.user_id


class PlaceRequest(BaseModel):
    name: str
    latitude: Latitude
    longitude: Longitude

    @field_validator('name')
    @classmethod
    def validate_name(cls, value):
        value = value.strip()
        if not 1 <= len(value) <= 120:
            raise ValueError('Name must contain 1 to 120 characters')
        return value


class SavedPlace(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    last_used_at: str | None
    use_count: int


class RecentPlace(BaseModel):
    latitude: float
    longitude: float
    last_used_at: str


class PlacesResponse(BaseModel):
    places: list[SavedPlace]
    recent: list[RecentPlace]


class DeletePlaceResponse(BaseModel):
    success: bool


def _write(user, operation, *args):
    owner = place_owner(user)
    with get_db() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            return operation(conn, owner, *args)
        except places.PlaceError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


@router.get('/api/places', response_model=PlacesResponse)
def api_places(user: CurrentUser = Depends(require_edition)):
    with get_db() as conn:
        return places.list_places(conn, place_owner(user))


@router.post('/api/places', response_model=SavedPlace, status_code=201)
def api_create_place(body: PlaceRequest, user: CurrentUser = Depends(require_edition)):
    return _write(user, places.save_place, body.name, body.latitude, body.longitude)


@router.put('/api/places/{place_id}', response_model=SavedPlace)
def api_update_place(place_id: int, body: PlaceRequest, user: CurrentUser = Depends(require_edition)):
    return _write(user, places.save_place, body.name, body.latitude, body.longitude, place_id)


@router.delete('/api/places/{place_id}', response_model=DeletePlaceResponse)
def api_delete_place(place_id: int, user: CurrentUser = Depends(require_edition)):
    _write(user, places.delete_place, place_id)
    return {'success': True}


class PlaceSearchResult(BaseModel):
    label: str
    latitude: Latitude
    longitude: Longitude


class PlaceSearchResponse(BaseModel):
    results: list[PlaceSearchResult]


@router.get('/api/places/search', response_model=PlaceSearchResponse)
def api_search_places(q: Annotated[str, Query(min_length=3, max_length=200)], user: CurrentUser = Depends(require_edition)):
    return {'results': place_search.search(q)}
