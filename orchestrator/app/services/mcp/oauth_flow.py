"""Manual OAuth 2.1 initial flow for MCP connectors.

The MCP SDK ships an ``async_auth_flow`` generator that drives the full OAuth
dance in-process. That assumption breaks in a horizontally scaled FastAPI
deployment: the ``/start`` request may land on pod A while the ``/callback``
lands on pod B. To survive the split, we implement a small state machine
that persists PKCE verifier + client_info in Redis between the two HTTP
requests, then hands the resulting tokens to :class:`PostgresTokenStorage` so
the SDK's *runtime* refresh-on-401 path can take over from there.

Registration methods supported
------------------------------
``dcr``          — RFC 7591 Dynamic Client Registration (default for Linear, Notion, Atlassian)
``byo``          — Bring-your-own client_id / client_secret (custom connectors)
``platform_app`` — Tesslate-owned OAuth app credentials from settings (GitHub, Slack)

Exceptions
----------
``ReauthRequired``   — connector exists but has no usable tokens; UI should prompt.
``OAuthFlowError``   — generic failure during discovery / registration.
``OAuthTokenError``  — token endpoint rejected our exchange.
"""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlencode, urlparse, urlunparse
from uuid import UUID, uuid4

import httpx
from mcp.client.auth.oauth2 import PKCEParameters
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
)
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...models import MarketplaceAgent, McpOAuthConnection, UserMcpConfig
from ..cache_service import get_redis_client
from ..channels.registry import encrypt_credentials

logger = logging.getLogger(__name__)

_REDIS_PREFIX = "mcp:oauth:flow"
_FLOW_TTL_SECONDS = 600  # 10 minutes — user has this long to complete authorize
_DEFAULT_SCOPES: list[str] = []  # providers advertise their own defaults via PRM

RegistrationMethod = Literal["dcr", "byo", "platform_app"]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OAuthFlowError(Exception):
    """Generic error during MCP OAuth flow (discovery / registration)."""


class OAuthTokenError(OAuthFlowError):
    """Token endpoint returned an error or an invalid response."""


class ReauthRequired(Exception):
    """Raised when a runtime MCP connect lacks valid tokens.

    Callers should surface this to the UI as a "Reconnect" prompt linking to
    Settings → Connectors.
    """

    def __init__(self, *, server_url: str, config_id: UUID | None = None,
                 message: str = "OAuth re-authorisation required") -> None:
        super().__init__(message)
        self.server_url = server_url
        self.config_id = config_id
        self.message = message


# ---------------------------------------------------------------------------
# Flow state persisted to Redis between /start and /callback
# ---------------------------------------------------------------------------


class FlowState(BaseModel):
    """Serialised mid-flight OAuth state.

    Held in Redis under ``mcp:oauth:flow:{state}`` for up to 10 minutes.
    """

    flow_id: str
    user_id: str
    server_url: str
    auth_server_url: str
    token_endpoint: str
    registration_endpoint: str | None = None
    scope: str | None = None
    code_verifier: str
    code_challenge: str
    client_info: dict[str, Any]
    registration_method: RegistrationMethod
    marketplace_agent_id: str | None = None
    scope_level: str = "user"  # team | user | project
    team_id: str | None = None
    project_id: str | None = None
    redirect_uri: str
    resource: str  # RFC 8707 resource indicator
    protocol_version: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class StartResult:
    authorize_url: str
    flow_id: str
    state: str


async def start_oauth_flow(
    *,
    db: AsyncSession,
    user_id: UUID,
    server_url: str,
    registration_method: RegistrationMethod,
    redirect_uri: str,
    marketplace_agent_id: UUID | None = None,
    scope_level: str = "user",
    team_id: UUID | None = None,
    project_id: UUID | None = None,
    byo_client_id: str | None = None,
    byo_client_secret: str | None = None,
    scope: str | None = None,
    endpoint_overrides: dict | None = None,
) -> StartResult:
    """Discover AS metadata, register client (per method), return authorize URL.

    Persists PKCE verifier + client_info to Redis under a freshly minted state.
    """
    settings = get_settings()
    redis = await get_redis_client()
    if redis is None:
        raise OAuthFlowError("Redis is required for MCP OAuth flow coordination")

    # Canonicalize the resource indicator once (RFC 8707 §2) so the authorize
    # and token-exchange URIs match exactly.
    server_url = _canonicalize_resource(server_url)

    # -------------------- 1. Discover PRM / AS metadata -------------------
    # If the caller supplies explicit endpoint overrides (e.g. GitHub's
    # platform_app config — GitHub doesn't publish RFC 8414 discovery docs),
    # skip the network discovery entirely and use them directly.
    overrides = endpoint_overrides or {}
    override_authorize = overrides.get("authorization_endpoint")
    override_token = overrides.get("token_endpoint")
    override_registration = overrides.get("registration_endpoint")

    if override_authorize and override_token:
        auth_server_url = overrides.get("authorization_server", server_url)
        authorize_endpoint = str(override_authorize)
        token_endpoint = str(override_token)
        registration_endpoint = str(override_registration) if override_registration else None
    else:
        async with httpx.AsyncClient(timeout=20) as http:
            prm = await _discover_protected_resource(http, server_url)
            auth_server_url = _pick_auth_server(prm, server_url)
            as_metadata = await _discover_authorization_server(http, auth_server_url)
        authorize_endpoint = str(as_metadata.authorization_endpoint)
        token_endpoint = str(as_metadata.token_endpoint)
        registration_endpoint = (
            str(as_metadata.registration_endpoint)
            if as_metadata.registration_endpoint
            else None
        )

    # -------------------- 2. Resolve client_info -------------------------
    client_info: OAuthClientInformationFull
    if registration_method == "dcr":
        if not registration_endpoint:
            raise OAuthFlowError(
                f"DCR requested but AS {auth_server_url} advertises no registration_endpoint"
            )
        client_info = await _dynamic_register(
            registration_endpoint=registration_endpoint,
            redirect_uri=redirect_uri,
            scope=scope,
        )
    elif registration_method == "byo":
        if not byo_client_id:
            raise OAuthFlowError("byo registration_method requires client_id")
        client_info = _make_byo_client_info(
            client_id=byo_client_id,
            client_secret=byo_client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
        )
    elif registration_method == "platform_app":
        platform_app = _lookup_platform_app(settings, server_url)
        if not platform_app:
            host = urlparse(server_url).hostname or server_url
            raise OAuthFlowError(
                "This connector uses a Tesslate-owned OAuth app which hasn't "
                "been configured on this environment. Register an OAuth app "
                f"with the provider ({host}), set the matching "
                "MCP_OAUTH_APP_<PROVIDER>_CLIENT_ID and CLIENT_SECRET "
                "environment variables, and restart the orchestrator. "
                "Alternatively add the server as a custom connector with "
                "your own client_id / client_secret."
            )
        client_info = _make_byo_client_info(
            client_id=platform_app["client_id"],
            client_secret=platform_app.get("client_secret"),
            redirect_uri=redirect_uri,
            scope=scope,
            token_endpoint_auth_method=platform_app.get(
                "auth_method", "client_secret_basic"
            ),
        )
    else:
        raise OAuthFlowError(f"unknown registration_method: {registration_method}")

    # -------------------- 3. PKCE + state --------------------------------
    pkce = PKCEParameters.generate()
    state = secrets.token_urlsafe(32)
    flow_id = str(uuid4())

    flow_state = FlowState(
        flow_id=flow_id,
        user_id=str(user_id),
        server_url=server_url,
        auth_server_url=auth_server_url,
        token_endpoint=token_endpoint,
        registration_endpoint=registration_endpoint,
        scope=scope,
        code_verifier=pkce.code_verifier,
        code_challenge=pkce.code_challenge,
        client_info=client_info.model_dump(mode="json", exclude_none=True),
        registration_method=registration_method,
        marketplace_agent_id=str(marketplace_agent_id) if marketplace_agent_id else None,
        scope_level=scope_level,
        team_id=str(team_id) if team_id else None,
        project_id=str(project_id) if project_id else None,
        redirect_uri=redirect_uri,
        resource=server_url,
        protocol_version=None,
    )
    await redis.setex(
        f"{_REDIS_PREFIX}:{state}",
        _FLOW_TTL_SECONDS,
        flow_state.model_dump_json(),
    )
    # Allow status polling by flow_id.
    await redis.setex(
        f"{_REDIS_PREFIX}:id:{flow_id}",
        _FLOW_TTL_SECONDS,
        json.dumps({"state": state, "status": "pending"}),
    )

    # -------------------- 4. Build authorize URL -------------------------
    params = {
        "response_type": "code",
        "client_id": client_info.client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": pkce.code_challenge,
        "code_challenge_method": "S256",
        "resource": server_url,
    }
    if scope:
        params["scope"] = scope
    elif client_info.scope:
        params["scope"] = client_info.scope
    authorize_url = f"{authorize_endpoint}?{urlencode(params)}"
    logger.info(
        "MCP OAuth flow started: user=%s server=%s method=%s flow=%s",
        user_id, server_url, registration_method, flow_id,
    )
    return StartResult(authorize_url=authorize_url, flow_id=flow_id, state=state)


async def complete_oauth_flow(
    *,
    db: AsyncSession,
    state: str,
    code: str,
) -> UserMcpConfig:
    """Exchange code for tokens and persist UserMcpConfig + McpOAuthConnection.

    Returns the resulting :class:`UserMcpConfig` (created or updated).
    """
    redis = await get_redis_client()
    if redis is None:
        raise OAuthFlowError("Redis is required for MCP OAuth flow coordination")

    raw = await redis.get(f"{_REDIS_PREFIX}:{state}")
    if not raw:
        raise OAuthFlowError("OAuth flow state missing or expired")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    flow = FlowState.model_validate_json(raw)

    client_info = OAuthClientInformationFull.model_validate(flow.client_info)

    # ---------- 1. Exchange code for tokens ----------
    async with httpx.AsyncClient(timeout=30) as http:
        tokens = await _exchange_code(
            http=http,
            token_endpoint=flow.token_endpoint,
            code=code,
            redirect_uri=flow.redirect_uri,
            code_verifier=flow.code_verifier,
            client_info=client_info,
            resource=flow.resource,
        )

    # ---------- 2. Upsert UserMcpConfig ----------
    config = await _upsert_user_mcp_config(db, flow=flow)

    # ---------- 3. Upsert McpOAuthConnection ----------
    await _upsert_oauth_connection(
        db,
        user_mcp_config_id=config.id,
        flow=flow,
        tokens=tokens,
        client_info=client_info,
    )

    # Flip status marker for /status polling (belt-and-braces alongside postMessage).
    await redis.setex(
        f"{_REDIS_PREFIX}:id:{flow.flow_id}",
        _FLOW_TTL_SECONDS,
        json.dumps({"state": state, "status": "success", "config_id": str(config.id)}),
    )
    # State is single-use — remove it so a replayed callback doesn't reapply it.
    await redis.delete(f"{_REDIS_PREFIX}:{state}")

    logger.info(
        "MCP OAuth flow complete: user=%s server=%s config=%s",
        flow.user_id, flow.server_url, config.id,
    )
    return config


async def get_flow_status(flow_id: str) -> dict[str, Any] | None:
    """Return the latest status marker for a flow, if any."""
    redis = await get_redis_client()
    if redis is None:
        return None
    raw = await redis.get(f"{_REDIS_PREFIX}:id:{flow_id}")
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


async def _discover_protected_resource(
    http: httpx.AsyncClient, server_url: str
) -> ProtectedResourceMetadata | None:
    """Try RFC 9728 PRM discovery; None on 404s (AS metadata fallback)."""
    candidates = build_protected_resource_metadata_discovery_urls(
        www_auth_url=None, server_url=server_url
    )
    for url in candidates:
        try:
            resp = await http.get(url)
        except httpx.RequestError as exc:
            logger.debug("PRM discovery failed at %s: %s", url, exc)
            continue
        if resp.status_code == 404:
            continue
        if resp.status_code != 200:
            logger.debug("PRM discovery non-200 at %s: %s", url, resp.status_code)
            continue
        try:
            return ProtectedResourceMetadata.model_validate(resp.json())
        except Exception as exc:
            logger.debug("PRM parse failed at %s: %s", url, exc)
    return None


def _pick_auth_server(
    prm: ProtectedResourceMetadata | None, server_url: str
) -> str:
    """Return the authorization_server URL. Falls back to the server origin."""
    if prm and prm.authorization_servers:
        return str(prm.authorization_servers[0])
    # Fallback: treat the resource server as its own AS (common for first-party providers).
    return server_url


async def _discover_authorization_server(
    http: httpx.AsyncClient, auth_server_url: str
) -> OAuthMetadata:
    """RFC 8414 authorization server metadata discovery."""
    candidates = build_oauth_authorization_server_metadata_discovery_urls(
        auth_server_url=None, server_url=auth_server_url
    )
    last_err: Exception | None = None
    for url in candidates:
        try:
            resp = await http.get(url)
        except httpx.RequestError as exc:
            last_err = exc
            continue
        if resp.status_code == 404:
            continue
        if resp.status_code != 200:
            last_err = OAuthFlowError(
                f"AS metadata discovery returned {resp.status_code} at {url}"
            )
            continue
        try:
            return OAuthMetadata.model_validate(resp.json())
        except Exception as exc:
            last_err = exc
    raise OAuthFlowError(
        f"Could not discover AS metadata for {auth_server_url}: {last_err}"
    )


# ---------------------------------------------------------------------------
# Client registration paths
# ---------------------------------------------------------------------------


def _build_client_metadata(
    *, redirect_uri: str, scope: str | None
) -> OAuthClientMetadata:
    return OAuthClientMetadata(
        redirect_uris=[redirect_uri],
        token_endpoint_auth_method="client_secret_basic",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        client_name="Tesslate Studio",
        client_uri="https://tesslate.com",
        scope=scope,
    )


async def _dynamic_register(
    *,
    registration_endpoint: str,
    redirect_uri: str,
    scope: str | None,
) -> OAuthClientInformationFull:
    """RFC 7591 Dynamic Client Registration."""
    meta = _build_client_metadata(redirect_uri=redirect_uri, scope=scope)
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.post(
            registration_endpoint,
            json=meta.model_dump(mode="json", exclude_none=True),
            headers={"content-type": "application/json", "accept": "application/json"},
        )
    if resp.status_code not in (200, 201):
        raise OAuthFlowError(
            f"DCR failed: {resp.status_code} {resp.text[:500]}"
        )
    return OAuthClientInformationFull.model_validate(resp.json())


def _make_byo_client_info(
    *,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    scope: str | None,
    token_endpoint_auth_method: str = "client_secret_basic",
) -> OAuthClientInformationFull:
    """Build a fully-populated client_info when the client is pre-registered."""
    return OAuthClientInformationFull(
        redirect_uris=[redirect_uri],
        token_endpoint_auth_method=token_endpoint_auth_method,
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        client_name="Tesslate Studio",
        client_uri="https://tesslate.com",
        scope=scope,
        client_id=client_id,
        client_secret=client_secret,
    )


def _lookup_platform_app(settings: Any, server_url: str) -> dict[str, Any] | None:
    """Map a server URL to a Tesslate-owned OAuth app via settings.

    Matches the configured key against the URL *host* (not the full URL) to
    avoid accidental matches against unrelated domains.
    """
    apps = getattr(settings, "mcp_platform_oauth_apps", {}) or {}
    host = urlparse(server_url).hostname or ""
    host = host.lower()
    for key, cfg in apps.items():
        k = key.lower()
        parts = host.replace(".", " ").split()
        if (
            k in parts
            or any(p.startswith(k) for p in parts)
            or any(p.endswith("-" + k) for p in parts)
        ):
            return cfg
    return None


def _canonicalize_resource(url: str) -> str:
    """Canonicalize an MCP server URL for use as an RFC 8707 resource indicator.

    Strips fragment; leaves path + trailing-slash exactly as the server advertises
    it (providers vary — Linear expects ``/mcp``; some use ``/mcp/``).
    """
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


async def _exchange_code(
    *,
    http: httpx.AsyncClient,
    token_endpoint: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_info: OAuthClientInformationFull,
    resource: str,
) -> OAuthToken:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "resource": resource,  # RFC 8707 resource indicator
    }

    auth = None
    method = client_info.token_endpoint_auth_method
    if method == "client_secret_basic":
        if client_info.client_secret:
            auth = (client_info.client_id, client_info.client_secret)
        else:
            data["client_id"] = client_info.client_id
    elif method in ("client_secret_post", "none"):
        data["client_id"] = client_info.client_id
        if client_info.client_secret:
            data["client_secret"] = client_info.client_secret
    else:
        data["client_id"] = client_info.client_id
        if client_info.client_secret:
            data["client_secret"] = client_info.client_secret

    resp = await http.post(
        token_endpoint,
        data=data,
        auth=auth,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "accept": "application/json",
        },
    )
    if resp.status_code != 200:
        raise OAuthTokenError(
            f"Token endpoint {token_endpoint} returned {resp.status_code}: {resp.text[:500]}"
        )
    try:
        return OAuthToken.model_validate(resp.json())
    except Exception as exc:
        raise OAuthTokenError(f"Invalid token response: {exc}") from exc


# ---------------------------------------------------------------------------
# DB upserts
# ---------------------------------------------------------------------------


async def _upsert_user_mcp_config(
    db: AsyncSession, *, flow: FlowState
) -> UserMcpConfig:
    """Create or update the UserMcpConfig row matching the flow's scope.

    Uniqueness key: ``(user_id, marketplace_agent_id|server_url, scope_level,
    team_id, project_id)`` — always evaluated, so reconnects to the same
    (provider, scope) mutate the existing row while different scopes never
    collide.
    """
    user_id = UUID(flow.user_id)
    marketplace_agent_id = (
        UUID(flow.marketplace_agent_id) if flow.marketplace_agent_id else None
    )
    team_id = UUID(flow.team_id) if flow.team_id else None
    project_id = UUID(flow.project_id) if flow.project_id else None

    # Scope-bound team/project filters — always evaluated so cross-scope rows
    # never collide during upsert.
    scope_team = team_id if flow.scope_level == "team" else None
    scope_project = project_id if flow.scope_level == "project" else None

    team_filter = (
        UserMcpConfig.team_id == scope_team
        if scope_team is not None
        else UserMcpConfig.team_id.is_(None)
    )
    project_filter = (
        UserMcpConfig.project_id == scope_project
        if scope_project is not None
        else UserMcpConfig.project_id.is_(None)
    )

    if marketplace_agent_id:
        stmt = select(UserMcpConfig).where(
            UserMcpConfig.user_id == user_id,
            UserMcpConfig.marketplace_agent_id == marketplace_agent_id,
            UserMcpConfig.scope_level == flow.scope_level,
            team_filter,
            project_filter,
        )
    else:
        # Custom connector: match on joined server URL within the exact scope.
        stmt = (
            select(UserMcpConfig)
            .join(
                McpOAuthConnection,
                McpOAuthConnection.user_mcp_config_id == UserMcpConfig.id,
            )
            .where(
                UserMcpConfig.user_id == user_id,
                UserMcpConfig.marketplace_agent_id.is_(None),
                UserMcpConfig.scope_level == flow.scope_level,
                team_filter,
                project_filter,
                McpOAuthConnection.server_url == flow.server_url,
            )
        )

    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        existing.is_active = True
        existing.team_id = scope_team
        existing.project_id = scope_project
        await db.flush()
        return existing

    config = UserMcpConfig(
        user_id=user_id,
        marketplace_agent_id=marketplace_agent_id,
        team_id=scope_team,
        project_id=scope_project,
        scope_level=flow.scope_level,
        is_active=True,
        enabled_capabilities=["tools", "resources", "prompts"],
    )
    db.add(config)
    await db.flush()
    return config


async def _upsert_oauth_connection(
    db: AsyncSession,
    *,
    user_mcp_config_id: UUID,
    flow: FlowState,
    tokens: OAuthToken,
    client_info: OAuthClientInformationFull,
) -> McpOAuthConnection:
    existing = (
        await db.execute(
            select(McpOAuthConnection).where(
                McpOAuthConnection.user_mcp_config_id == user_mcp_config_id,
            )
        )
    ).scalar_one_or_none()

    tokens_json = tokens.model_dump(mode="json", exclude_none=True)
    client_info_json = client_info.model_dump(mode="json", exclude_none=True)
    tokens_enc = encrypt_credentials(tokens_json)
    client_enc = encrypt_credentials(client_info_json)
    expires_at = _expiry_from_tokens(tokens)

    if existing:
        existing.server_url = flow.server_url
        existing.tokens_encrypted = tokens_enc
        existing.client_info_encrypted = client_enc
        existing.token_expires_at = expires_at
        existing.last_refresh_at = datetime.now(UTC)
        existing.auth_server_url = flow.auth_server_url
        existing.registration_method = flow.registration_method
        existing.protocol_version = flow.protocol_version
        await db.flush()
        return existing

    row = McpOAuthConnection(
        user_mcp_config_id=user_mcp_config_id,
        server_url=flow.server_url,
        tokens_encrypted=tokens_enc,
        client_info_encrypted=client_enc,
        token_expires_at=expires_at,
        last_refresh_at=datetime.now(UTC),
        auth_server_url=flow.auth_server_url,
        registration_method=flow.registration_method,
        protocol_version=flow.protocol_version,
    )
    db.add(row)
    await db.flush()
    return row


def _expiry_from_tokens(tokens: OAuthToken) -> datetime | None:
    expires_in = getattr(tokens, "expires_in", None)
    if expires_in is None:
        return None
    from datetime import timedelta

    try:
        return datetime.now(UTC) + timedelta(seconds=int(expires_in))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Convenience: resolve MarketplaceAgent's config.url when starting a flow by slug
# ---------------------------------------------------------------------------


async def resolve_catalog_server(
    db: AsyncSession, slug: str
) -> tuple[MarketplaceAgent, str]:
    """Return a published MCP MarketplaceAgent and its server URL by slug."""
    result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.slug == slug,
            MarketplaceAgent.item_type == "mcp_server",
            MarketplaceAgent.is_published.is_(True),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise OAuthFlowError(f"No published MCP server with slug {slug!r}")
    url = (agent.config or {}).get("url")
    if not url:
        raise OAuthFlowError(f"MCP server {slug!r} has no config.url")
    return agent, url


# Re-export for callers that only import this module.
__all__ = [
    "start_oauth_flow",
    "complete_oauth_flow",
    "get_flow_status",
    "resolve_catalog_server",
    "ReauthRequired",
    "OAuthFlowError",
    "OAuthTokenError",
    "FlowState",
    "RegistrationMethod",
    "StartResult",
]
