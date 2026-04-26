"""Gmail provider adapter for the Connector Proxy.

Gmail uses ``Authorization: Bearer <oauth_access_token>``; tokens expire
after 1 hour and must be refreshed using the OAuth refresh token. The
refresh hook delegates to the existing
``services.mcp.oauth_storage.PostgresTokenStorage.refresh_tokens`` flow —
on 401 the proxy will retry once with a fresh token.

The endpoint allowlist covers the read+send paths most automations need:
list/read messages, send drafts, manage labels.
"""

from __future__ import annotations

from .base import AllowedEndpoint, AuthScheme, ProviderAdapter


GMAIL_ALLOWED_ENDPOINTS: tuple[AllowedEndpoint, ...] = (
    # ---- Messages ----
    AllowedEndpoint(method="GET", path="gmail/v1/users/{userId}/messages"),
    AllowedEndpoint(
        method="GET", path="gmail/v1/users/{userId}/messages/{id}"
    ),
    AllowedEndpoint(
        method="POST", path="gmail/v1/users/{userId}/messages/send"
    ),
    AllowedEndpoint(
        method="POST", path="gmail/v1/users/{userId}/messages/{id}/modify"
    ),
    AllowedEndpoint(
        method="POST", path="gmail/v1/users/{userId}/messages/{id}/trash"
    ),
    # ---- Drafts ----
    AllowedEndpoint(method="GET", path="gmail/v1/users/{userId}/drafts"),
    AllowedEndpoint(method="POST", path="gmail/v1/users/{userId}/drafts"),
    # ---- Labels ----
    AllowedEndpoint(method="GET", path="gmail/v1/users/{userId}/labels"),
    AllowedEndpoint(method="POST", path="gmail/v1/users/{userId}/labels"),
    # ---- Threads ----
    AllowedEndpoint(method="GET", path="gmail/v1/users/{userId}/threads"),
    AllowedEndpoint(
        method="GET", path="gmail/v1/users/{userId}/threads/{id}"
    ),
    # ---- Profile ----
    AllowedEndpoint(method="GET", path="gmail/v1/users/{userId}/profile"),
)


GMAIL = ProviderAdapter(
    connector_id="gmail",
    # Gmail's REST API lives on googleapis.com; the userId route
    # convention is included in each path so we keep one consistent base.
    base_url="https://gmail.googleapis.com",
    auth_scheme=AuthScheme.BEARER,
    allowed_endpoints=GMAIL_ALLOWED_ENDPOINTS,
    timeout_seconds=20.0,
    # Gmail tokens expire in ~1h. The router wires its own
    # default-refresh-via-MCP-oauth-storage path that all bearer adapters
    # opt into when refresh_hook is None — explicit hook here is reserved
    # for adapters that need provider-specific refresh logic (e.g., when
    # the OAuth token store lives outside McpOAuthConnection).
    refresh_hook=None,
)


__all__ = ["GMAIL", "GMAIL_ALLOWED_ENDPOINTS"]
