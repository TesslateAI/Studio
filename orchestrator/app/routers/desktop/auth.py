"""Cloud pairing endpoints (auth status, token get/set/clear)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...config import get_settings
from ...models import User
from ...services import token_store
from ...users import current_active_user

router = APIRouter()


class CloudTokenBody(BaseModel):
    token: str = Field(..., min_length=1, max_length=512)


@router.get("/auth/status")
async def auth_status(_user: User = Depends(current_active_user)) -> dict[str, Any]:
    """Cheap, network-free pairing probe."""
    return {
        "paired": token_store.is_paired(),
        "cloud_url": get_settings().tesslate_cloud_url,
    }


@router.post("/auth/token")
async def set_auth_token(
    body: CloudTokenBody,
    _user: User = Depends(current_active_user),
) -> dict[str, Any]:
    """Persist a cloud bearer token (called by the Tauri deep-link handler)."""
    token_store.set_cloud_token(body.token)
    return {"paired": True}


@router.delete("/auth/token")
async def clear_auth_token(_user: User = Depends(current_active_user)) -> dict[str, Any]:
    """Forget the cloud bearer token (desktop logout)."""
    token_store.clear_cloud_token()
    return {"paired": False}
