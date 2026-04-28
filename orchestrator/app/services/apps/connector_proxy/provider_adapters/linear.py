"""Linear provider adapter for the Connector Proxy.

Linear's REST surface is minimal — most automation flows hit the GraphQL
endpoint at ``/graphql``. The allowlist surfaces both: the GraphQL endpoint
itself plus a handful of common REST endpoints used by the integrations
team. Linear OAuth uses ``Bearer`` tokens; tokens expire after 10 years
so refresh is a no-op.
"""

from __future__ import annotations

from .base import AllowedEndpoint, AuthScheme, ProviderAdapter


LINEAR_ALLOWED_ENDPOINTS: tuple[AllowedEndpoint, ...] = (
    # GraphQL — the main entry point. Linear requires POST.
    AllowedEndpoint(method="POST", path="graphql"),
    # OAuth helper endpoints (read-only).
    AllowedEndpoint(method="GET", path="oauth/userInfo"),
    # Webhook listing for CRUD on incoming-webhook subscriptions.
    AllowedEndpoint(method="GET", path="webhooks"),
    AllowedEndpoint(method="POST", path="webhooks"),
)


LINEAR = ProviderAdapter(
    connector_id="linear",
    base_url="https://api.linear.app",
    auth_scheme=AuthScheme.BEARER,
    allowed_endpoints=LINEAR_ALLOWED_ENDPOINTS,
    timeout_seconds=15.0,
    refresh_hook=None,
)


__all__ = ["LINEAR", "LINEAR_ALLOWED_ENDPOINTS"]
