"""Pydantic models for authentication endpoints."""

from pydantic import BaseModel
from typing import Optional


class LoginRequest(BaseModel):
    username: Optional[str] = None
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Optional[dict] = None


class EditionLoginRequest(BaseModel):
    password: str


class AuthStatusResponse(BaseModel):
    authenticated: bool
    multi_user: bool
    edition_enabled: bool
    edition_authenticated: bool
    user_id: Optional[str] = None
    user_role: Optional[str] = None
    display_name: Optional[str] = None
    features: dict = {}
    download_profiles: list[str] = []
