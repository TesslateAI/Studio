"""Postgres-backed OAuth token storage for the MCP SDK.

Implements :class:`mcp.client.auth.TokenStorage` (get/set tokens + client_info)
against :class:`McpOAuthConnection`. Tokens and client_info are encrypted at
rest with Fernet using the shared channel encryption key.

Why this exists
---------------
The MCP SDK's in-memory ``OAuthClientProvider`` can refresh tokens automatically
on 401 — but it relies on a ``TokenStorage`` to persist the refreshed token so
future processes (worker pods, API pods) don't have to re-auth. This class is
that persistence layer.

Concurrency
-----------
``set_tokens`` upserts the row. The storage assumes the row exists after the
initial ``complete_oauth_flow`` run; callers that want to create a brand new
connection must call ``set_client_info`` first (which acts as a row-create
signal). If ``set_tokens`` is called before the row exists we raise — the
initial flow is responsible for ordering.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import McpOAuthConnection
from ..channels.registry import decrypt_credentials, encrypt_credentials

logger = logging.getLogger(__name__)


class PostgresTokenStorage(TokenStorage):
    """Fernet-encrypted Postgres storage bound to one ``McpOAuthConnection`` row.

    Parameters
    ----------
    db:
        Active async SQLAlchemy session.
    user_mcp_config_id:
        UUID of the owning ``UserMcpConfig``. The connection row is located via
        this key (unique on the row).
    """

    def __init__(self, db: AsyncSession, user_mcp_config_id: UUID) -> None:
        self._db = db
        self._user_mcp_config_id = user_mcp_config_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_tokens(self) -> OAuthToken | None:
        row = await self._load()
        if row is None or not row.tokens_encrypted:
            return None
        try:
            raw = decrypt_credentials(row.tokens_encrypted)
        except Exception as exc:  # bad key / tampered ciphertext
            logger.error("MCP oauth token decrypt failed for %s: %s", row.id, exc)
            return None
        try:
            return OAuthToken.model_validate(raw)
        except Exception as exc:
            logger.error("MCP oauth token parse failed for %s: %s", row.id, exc)
            return None

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        row = await self._load()
        if row is None or not row.client_info_encrypted:
            return None
        try:
            raw = decrypt_credentials(row.client_info_encrypted)
        except Exception as exc:
            logger.error("MCP oauth client_info decrypt failed for %s: %s", row.id, exc)
            return None
        try:
            return OAuthClientInformationFull.model_validate(raw)
        except Exception as exc:
            logger.error("MCP oauth client_info parse failed for %s: %s", row.id, exc)
            return None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def set_tokens(self, tokens: OAuthToken) -> None:
        row = await self._load()
        if row is None:
            raise RuntimeError(
                f"PostgresTokenStorage.set_tokens called before set_client_info "
                f"for user_mcp_config_id={self._user_mcp_config_id}"
            )
        payload = _json_dump_model(tokens)
        row.tokens_encrypted = encrypt_credentials(payload)
        row.token_expires_at = _compute_expiry(tokens)
        row.last_refresh_at = datetime.now(UTC)
        await self._db.flush()
        logger.debug("MCP oauth tokens persisted for connection %s", row.id)

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        """Upsert the client_info row. Used as the row-create signal."""
        row = await self._load()
        payload = _json_dump_model(client_info)
        encrypted = encrypt_credentials(payload)
        if row is None:
            # Row must be created by oauth_flow.complete_oauth_flow with server_url
            # etc. set. This branch is only reached if something invokes set_client_info
            # without a prior insert — we surface it clearly instead of silently NOOPing.
            raise RuntimeError(
                f"PostgresTokenStorage.set_client_info called but McpOAuthConnection row "
                f"does not exist for user_mcp_config_id={self._user_mcp_config_id}. "
                f"Create it via oauth_flow.complete_oauth_flow first."
            )
        row.client_info_encrypted = encrypted
        await self._db.flush()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _load(self) -> McpOAuthConnection | None:
        result = await self._db.execute(
            select(McpOAuthConnection).where(
                McpOAuthConnection.user_mcp_config_id == self._user_mcp_config_id,
            )
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_dump_model(obj: object) -> dict:
    """Dump a pydantic v2 model to a plain JSON-serialisable dict."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)  # type: ignore[attr-defined]
    return json.loads(json.dumps(obj))


def _compute_expiry(tokens: OAuthToken) -> datetime | None:
    expires_in = getattr(tokens, "expires_in", None)
    if expires_in is None:
        return None
    try:
        return datetime.now(UTC) + timedelta(seconds=int(expires_in))
    except (TypeError, ValueError):
        return None
