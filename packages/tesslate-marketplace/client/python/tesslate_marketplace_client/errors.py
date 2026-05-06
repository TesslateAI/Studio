"""Typed exceptions raised by the marketplace client."""

from __future__ import annotations


class MarketplaceClientError(Exception):
    """Base exception for client-side errors."""


class HubIdMismatch(MarketplaceClientError):
    """The hub returned a `X-Tesslate-Hub-Id` that doesn't match the pinned id."""

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(f"hub_id mismatch: expected={expected!r} actual={actual!r}")
        self.expected = expected
        self.actual = actual


class UnsupportedCapability(MarketplaceClientError):
    """The hub returned a typed `unsupported_capability` envelope (HTTP 501)."""

    def __init__(self, capability: str, hub_id: str, details: str | None) -> None:
        super().__init__(f"capability {capability!r} not implemented by hub {hub_id}")
        self.capability = capability
        self.hub_id = hub_id
        self.details = details


class InvalidBundle(MarketplaceClientError):
    """Bundle integrity check failed (sha256, size, archive format)."""
