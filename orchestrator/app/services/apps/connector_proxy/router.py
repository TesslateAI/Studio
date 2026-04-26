"""Connector Proxy FastAPI router.

Mounted on the orchestrator at ``/api/v1/connector-proxy`` (Phase 3).
Phase 4 will lift this into a dedicated ``opensail-runtime`` Deployment +
Service so NetworkPolicy can isolate it from arbitrary cluster traffic.

Request flow
------------

1. Verify ``X-OpenSail-AppInstance`` and resolve the ``AppInstance`` row.
2. Look up the ``AppConnectorGrant`` for ``(instance, connector_id)``;
   refuse if missing, revoked, or pinned to ``exposure='env'``.
3. Look up the per-provider ``ProviderAdapter``; refuse if not registered.
4. Validate the requested ``(method, path)`` against the adapter's
   endpoint allowlist.
5. Resolve the credential from ``grant.resolved_ref`` (OAuth connection,
   user MCP config, or container-encrypted secret) and decrypt
   server-side.
6. Forward to upstream with the injected auth header. **Strip
   ``X-OpenSail-AppInstance`` and any ``Authorization`` header that the
   app pod might have sent before forwarding.**
7. On 401 + bearer scheme + adapter has refresh hook: refresh once,
   retry once.
8. Audit row written for every call (success and failure).
9. Return upstream response — but with the ``Authorization`` header
   stripped so the app pod never sees the bearer token in the response
   echo, even if the upstream reflected it.

Token isolation guarantees (the load-bearing properties)
--------------------------------------------------------

* The decrypted token never appears in the audit row (``error`` column
  is scrubbed by ``audit.scrub_error_body``).
* The decrypted token never appears in any structured log emission from
  this module.
* The decrypted token is bound to a local variable in
  :func:`_proxy_call`'s scope and never returned in the response.
* The ``Authorization`` header on the response sent back to the app pod
  is explicitly removed.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....database import get_db
from ....models import McpOAuthConnection
from ....models_automations import (
    AppConnectorGrant,
    AppConnectorRequirement,
    AppInstance,
)
from ...channels.registry import decrypt_credentials
from . import audit
from .auth import APP_INSTANCE_HEADER, verify_app_instance
from .provider_adapters import ADAPTER_REGISTRY, AuthScheme, OAuthRefreshFailed

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/connector-proxy", tags=["connector-proxy"])


# Request/response headers we never forward in either direction. Authorization
# is stripped from both forwarded request (so the app pod can't smuggle its
# own credentials) and returned response (so the app pod can't see the
# upstream's reflected Authorization header even if the upstream echoed it).
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)


def _strip_request_headers(
    headers: dict[str, str],
) -> dict[str, str]:
    """Return a copy of ``headers`` safe to forward to the upstream.

    Removes hop-by-hop headers, the OpenSail auth header, and any
    Authorization the app pod tried to set (we always inject our own).
    """
    cleaned: dict[str, str] = {}
    for key, value in headers.items():
        lk = key.lower()
        if lk in _HOP_BY_HOP_HEADERS:
            continue
        if lk == APP_INSTANCE_HEADER.lower():
            continue
        if lk == "authorization":
            continue
        cleaned[key] = value
    return cleaned


def _strip_response_headers(headers: httpx.Headers) -> dict[str, str]:
    """Return upstream response headers minus any Authorization echo."""
    cleaned: dict[str, str] = {}
    for key, value in headers.items():
        lk = key.lower()
        if lk in _HOP_BY_HOP_HEADERS:
            continue
        if lk == "authorization":
            continue
        # content-encoding lies if we don't pass the body through
        # decompressed, so let httpx handle that under the hood: drop
        # content-encoding too.
        if lk == "content-encoding":
            continue
        cleaned[key] = value
    return cleaned


async def _resolve_grant(
    db: AsyncSession, instance: AppInstance, connector_id: str
) -> AppConnectorGrant:
    """Find the live grant for ``(instance, connector_id)``.

    Joins ``app_connector_requirements`` to filter by ``connector_id`` —
    the grant row itself only carries ``requirement_id``.
    """
    stmt = (
        select(AppConnectorGrant)
        .join(
            AppConnectorRequirement,
            AppConnectorRequirement.id == AppConnectorGrant.requirement_id,
        )
        .where(
            AppConnectorGrant.app_instance_id == instance.id,
            AppConnectorRequirement.connector_id == connector_id,
            AppConnectorGrant.revoked_at.is_(None),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    grant = result.scalar_one_or_none()
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"app instance has no active grant for connector "
                f"'{connector_id}'"
            ),
        )
    if grant.exposure_at_grant != "proxy":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"connector '{connector_id}' is grant exposure="
                f"'{grant.exposure_at_grant}'; the proxy only handles "
                "exposure='proxy' grants"
            ),
        )
    return grant


async def _resolve_token(
    db: AsyncSession, grant: AppConnectorGrant
) -> tuple[str, UUID | None]:
    """Decrypt the credential pointed at by ``grant.resolved_ref``.

    Returns ``(access_token, oauth_connection_id_or_None)``. The second
    element is used by the 401-refresh path; non-OAuth credentials return
    None and refresh is skipped.

    Raises HTTPException(500) if the resolved_ref points at a row that
    no longer exists or whose ciphertext can't be decrypted.
    """
    ref: dict[str, Any] = grant.resolved_ref or {}
    kind = ref.get("kind")
    raw_id = ref.get("id")
    if not kind or not raw_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="grant.resolved_ref is malformed",
        )

    if kind == "oauth_connection":
        try:
            conn_id = UUID(str(raw_id))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="grant.resolved_ref.id not a UUID",
            ) from None
        oauth = await db.get(McpOAuthConnection, conn_id)
        if oauth is None or not oauth.tokens_encrypted:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="oauth connection missing or has no token",
            )
        try:
            tokens = decrypt_credentials(oauth.tokens_encrypted)
        except Exception as exc:
            logger.error(
                "connector_proxy: oauth decrypt failed conn=%s err=%r",
                conn_id,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="oauth token decrypt failed",
            ) from None
        access_token = tokens.get("access_token")
        if not access_token or not isinstance(access_token, str):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="oauth token payload missing access_token",
            )
        return access_token, conn_id

    if kind == "api_key_secret":
        # Phase 3 stub: api_key_secret resolution wires through
        # services.secret_manager_env. For this wave we leave the path
        # explicit so a caller hitting it gets a clear 501 instead of
        # silently passing the wrong credential.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "api_key_secret grants not yet implemented in connector "
                "proxy (Phase 3.1)"
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"unknown grant.resolved_ref.kind '{kind}'",
    )


@router.api_route(
    "/connectors/{connector_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy_call(
    connector_id: str,
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The Connector Proxy entry point.

    See module docstring for the full request flow.
    """
    # 1. Auth → AppInstance.
    instance = await verify_app_instance(request, db)

    # 2. Grant lookup. Refuses non-proxy grants and missing/revoked grants.
    grant = await _resolve_grant(db, instance, connector_id)

    # 3. Provider adapter.
    adapter = ADAPTER_REGISTRY.get(connector_id)
    if adapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no provider adapter registered for '{connector_id}'",
        )

    # 4. Endpoint allowlist.
    if not adapter.is_allowed(request.method, path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"endpoint '{request.method} {path}' is not in the "
                f"allowlist for '{connector_id}'"
            ),
        )

    # 5. Resolve credential. The decrypted token lives only inside this
    #    function's scope from here on — never logged, never returned.
    access_token, oauth_connection_id = await _resolve_token(db, grant)

    # 6. Build forwarded request shape.
    upstream_url = adapter.build_url(path)
    forwarded_headers = _strip_request_headers(dict(request.headers))
    auth_header_name, auth_header_value = adapter.build_auth_header(
        access_token
    )
    forwarded_headers[auth_header_name] = auth_header_value
    body = await request.body()

    # 7. Forward + 401-refresh-once retry.
    started = time.monotonic()
    upstream_resp = await _do_upstream_request(
        method=request.method,
        url=upstream_url,
        headers=forwarded_headers,
        params=dict(request.query_params),
        content=body,
        timeout_seconds=adapter.timeout_seconds,
    )

    if (
        upstream_resp.status_code == status.HTTP_401_UNAUTHORIZED
        and adapter.auth_scheme is AuthScheme.BEARER
        and adapter.refresh_hook is not None
        and oauth_connection_id is not None
    ):
        try:
            new_token = await adapter.refresh_hook(db, oauth_connection_id)
        except OAuthRefreshFailed as exc:
            logger.info(
                "connector_proxy: refresh failed for connector=%s instance=%s "
                "err=%s",
                connector_id,
                instance.id,
                exc,
            )
            # Fall through with the original 401 response.
        else:
            forwarded_headers[auth_header_name] = (
                adapter.build_auth_header(new_token)[1]
            )
            upstream_resp = await _do_upstream_request(
                method=request.method,
                url=upstream_url,
                headers=forwarded_headers,
                params=dict(request.query_params),
                content=body,
                timeout_seconds=adapter.timeout_seconds,
            )

    duration_ms = int((time.monotonic() - started) * 1000)

    # 8. Audit row. Best-effort; failures are swallowed inside record_call.
    upstream_text: str | None
    if upstream_resp.status_code >= 400:
        try:
            upstream_text = upstream_resp.text
        except Exception:  # pragma: no cover — defensive
            upstream_text = None
    else:
        upstream_text = None
    await audit.record_call(
        db,
        app_instance_id=instance.id,
        requirement_id=grant.requirement_id,
        connector_id=connector_id,
        endpoint=path,
        method=request.method,
        status_code=upstream_resp.status_code,
        bytes_in=len(body or b""),
        bytes_out=len(upstream_resp.content or b""),
        duration_ms=duration_ms,
        error=upstream_text,
    )

    # 9. Return upstream response — Authorization stripped.
    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers=_strip_response_headers(upstream_resp.headers),
        media_type=upstream_resp.headers.get("content-type"),
    )


async def _do_upstream_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, str],
    content: bytes,
    timeout_seconds: float,
) -> httpx.Response:
    """Single upstream call with bounded timeout.

    Wrapped so the 401-refresh path can retry without duplicating the
    httpx wiring. Network errors are surfaced as 502.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            return await client.request(
                method,
                url,
                headers=headers,
                params=params,
                content=content,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"upstream timeout after {timeout_seconds}s",
        ) from exc
    except httpx.HTTPError as exc:
        # Don't reflect exception details (could include URLs / hostnames
        # we'd rather not put in app pod stack traces).
        logger.warning(
            "connector_proxy: upstream transport error url=%s err=%r",
            url,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="upstream transport error",
        ) from exc


__all__ = ["router"]
