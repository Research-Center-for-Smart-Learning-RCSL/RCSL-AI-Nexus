"""Shared knowledge router and upload limit."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["knowledge"])

_UPLOAD_CHUNK = 1024 * 1024
