"""Provider adapters for the Connector Proxy.

Each adapter declares the upstream base URL, OAuth scheme, allowlisted
endpoints, and an OAuth refresh hook. The registry lookup is the single
extension point — adding a new provider is one new module + one
registration call.

Adapters are intentionally NOT a passthrough proxy. Endpoints are
explicitly enumerated per-provider so `?path=../../arbitrary` cannot reach
upstream endpoints the user never consented to.
"""

from __future__ import annotations

from .base import (
    AdapterRegistry,
    AllowedEndpoint,
    AuthScheme,
    OAuthRefreshFailed,
    ProviderAdapter,
)
from .github import GITHUB
from .gmail import GMAIL
from .linear import LINEAR
from .slack import SLACK

ADAPTER_REGISTRY: AdapterRegistry = AdapterRegistry()
ADAPTER_REGISTRY.register(SLACK)
ADAPTER_REGISTRY.register(GITHUB)
ADAPTER_REGISTRY.register(LINEAR)
ADAPTER_REGISTRY.register(GMAIL)


__all__ = [
    "ADAPTER_REGISTRY",
    "AdapterRegistry",
    "AllowedEndpoint",
    "AuthScheme",
    "OAuthRefreshFailed",
    "ProviderAdapter",
]
