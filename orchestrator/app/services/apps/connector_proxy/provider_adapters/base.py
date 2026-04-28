"""Base types for Connector Proxy provider adapters.

A ``ProviderAdapter`` describes one upstream provider (Slack, GitHub, …):

* base URL,
* OAuth scheme + auth header name (so providers that diverge from
  ``Authorization: Bearer`` like GitHub's ``token …`` can opt in),
* curated endpoint allowlist (method + path, no wildcards),
* default request timeout,
* an optional OAuth refresh hook for 401 retries.

The proxy intentionally does NOT pass arbitrary paths through to the
upstream — every endpoint must be explicitly allowlisted so a leak from
``path:path`` injection becomes impossible by construction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Awaitable
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession


class AuthScheme(StrEnum):
    """How the proxy injects credentials on the upstream request."""

    BEARER = "bearer"  # Authorization: Bearer <token>
    TOKEN = "token"  # Authorization: token <token>  (GitHub style)
    BASIC = "basic"  # Authorization: Basic base64(token:)
    API_KEY_HEADER = "api_key_header"  # custom header (e.g., X-Api-Key)
    NONE = "none"  # the credential is in the body / not used


# Type alias for the optional refresh hook signature. Adapters that do NOT
# support refresh leave this as None and a 401 propagates to the caller.
RefreshHook = Callable[
    ["AsyncSession", UUID],  # db session + oauth_connection_id
    Awaitable[str],  # returns the new access_token
]


class OAuthRefreshFailed(RuntimeError):
    """Raised by a refresh hook when refresh is impossible (no refresh
    token, refresh endpoint returned a permanent error, etc.)."""


@dataclass(frozen=True)
class AllowedEndpoint:
    """One allowlisted upstream endpoint.

    ``method`` is matched case-insensitively. ``path`` is matched as an
    exact string (no wildcards, no path-pattern interpretation). Providers
    with parameterised paths (e.g., GitHub's ``repos/{owner}/{repo}``)
    declare the *full path template literally* using ``{}`` as the
    placeholder marker; matching is implemented in
    :meth:`ProviderAdapter.is_allowed` via segment-shape comparison so the
    user can call ``repos/octocat/hello-world`` against
    ``repos/{owner}/{repo}`` without us reaching for regex.
    """

    method: str
    path: str

    def matches(self, method: str, path: str) -> bool:
        if method.upper() != self.method.upper():
            return False
        # Strip leading/trailing slashes so callers don't depend on prefix.
        request_segments = [s for s in path.strip("/").split("/") if s]
        pattern_segments = [
            s for s in self.path.strip("/").split("/") if s
        ]
        if len(request_segments) != len(pattern_segments):
            return False
        for req, pat in zip(request_segments, pattern_segments, strict=True):
            if pat.startswith("{") and pat.endswith("}"):
                # Placeholder — accept any non-empty single segment that
                # doesn't contain shenanigan characters. The proxy already
                # rejects path traversal at the FastAPI level, but defense
                # in depth: refuse '..' and empty segments.
                if not req or req == ".." or req == ".":
                    return False
                continue
            if req != pat:
                return False
        return True


@dataclass(frozen=True)
class ProviderAdapter:
    """Per-provider configuration for the Connector Proxy."""

    connector_id: str
    base_url: str
    auth_scheme: AuthScheme
    allowed_endpoints: tuple[AllowedEndpoint, ...]
    auth_header_name: str = "Authorization"
    timeout_seconds: float = 15.0
    refresh_hook: RefreshHook | None = field(default=None)

    def is_allowed(self, method: str, path: str) -> bool:
        return any(
            ep.matches(method, path) for ep in self.allowed_endpoints
        )

    def build_auth_header(self, token: str) -> tuple[str, str]:
        """Return the ``(header_name, header_value)`` to inject."""
        scheme = self.auth_scheme
        if scheme is AuthScheme.BEARER:
            return self.auth_header_name, f"Bearer {token}"
        if scheme is AuthScheme.TOKEN:
            return self.auth_header_name, f"token {token}"
        if scheme is AuthScheme.BASIC:
            import base64

            encoded = base64.b64encode(f"{token}:".encode("utf-8")).decode(
                "ascii"
            )
            return self.auth_header_name, f"Basic {encoded}"
        if scheme is AuthScheme.API_KEY_HEADER:
            return self.auth_header_name, token
        # AuthScheme.NONE: caller is responsible for supplying the token
        # in the body or query string. We still emit a header so callers
        # can detect the no-op case.
        return "X-OpenSail-Auth-NoOp", "1"

    def build_url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


class AdapterRegistry:
    """Registry of provider adapters, keyed on ``connector_id``."""

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        if adapter.connector_id in self._adapters:
            raise ValueError(
                f"adapter for connector_id={adapter.connector_id!r} already "
                "registered"
            )
        self._adapters[adapter.connector_id] = adapter

    def get(self, connector_id: str) -> ProviderAdapter | None:
        return self._adapters.get(connector_id)

    def keys(self) -> list[str]:
        return list(self._adapters.keys())


__all__ = [
    "AdapterRegistry",
    "AllowedEndpoint",
    "AuthScheme",
    "OAuthRefreshFailed",
    "ProviderAdapter",
    "RefreshHook",
]
