"""
Bearer-token authentication for write endpoints.

Tokens come from two places:
1. `STATIC_TOKENS` env var — `token1:scope1:scope2,token2:scope3` form, evaluated
   once on boot. Useful for local dev and for the orchestrator's federation
   client during smoke tests.
2. `api_tokens` rows — opaque token, looked up by SHA-256 hash. Scopes live on
   the row.

Both are checked in order. Public read endpoints don't go through this path at
all — they're anonymous.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..database import get_session
from ..models import ApiToken


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _extract_bearer(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


class Principal:
    """Authenticated subject (token + scopes)."""

    __slots__ = ("handle", "scopes", "token_id", "source")

    def __init__(
        self,
        handle: str,
        scopes: set[str],
        token_id: str | None,
        source: str,
    ) -> None:
        self.handle = handle
        self.scopes = scopes
        self.token_id = token_id
        self.source = source

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes or "*" in self.scopes

    def require_scope(self, scope: str) -> None:
        if not self.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_scope",
                    "required_scope": scope,
                    "actual_scopes": sorted(self.scopes),
                },
            )


async def _resolve_static(token: str, settings: Settings) -> Principal | None:
    table = settings.static_token_table()
    if token not in table:
        return None
    return Principal(
        handle=f"static:{token[:6]}",
        scopes=set(table[token]),
        token_id=None,
        source="static",
    )


async def _resolve_db(token: str, db: AsyncSession) -> Principal | None:
    digest = _hash_token(token)
    # Constant-time comparison via per-row check after lookup.
    result = await db.execute(select(ApiToken).where(ApiToken.token_hash == digest))
    row = result.scalar_one_or_none()
    if row is None or not row.is_active:
        return None
    if not hmac.compare_digest(row.token_hash, digest):
        return None
    row.last_used_at = datetime.now(timezone.utc)
    await db.flush()
    return Principal(
        handle=row.handle,
        scopes=set(row.scopes or []),
        token_id=str(row.id),
        source="db",
    )


async def get_principal(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """Resolve a `Principal` from the `Authorization: Bearer …` header.

    Raises 401 on missing/invalid token. Use `Depends(get_principal)` on every
    mutating endpoint.
    """
    token = _extract_bearer(authorization)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_bearer_token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = await _resolve_static(token, settings)
    if principal is None:
        principal = await _resolve_db(token, db)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_bearer_token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


async def get_optional_principal(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Principal | None:
    """Anonymous-friendly auth: returns None when no token is supplied."""
    token = _extract_bearer(authorization)
    if token is None:
        return None
    principal = await _resolve_static(token, settings)
    if principal is None:
        principal = await _resolve_db(token, db)
    return principal


def hash_token(token: str) -> str:
    """Public helper used by the seed script to insert tokens."""
    return _hash_token(token)
