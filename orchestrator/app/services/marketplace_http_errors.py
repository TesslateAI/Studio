"""HTTPException translation for marketplace client errors.

Centralises the typed-error → HTTPException mapping used by the three
proxy routers (``admin_marketplace``, ``app_submissions``, ``app_yanks``).
``not_found_tag`` lets each router preserve its own resource-specific
error token (e.g. ``marketplace_submission_not_found``) without copy-
pasting the rest of the dispatch.
"""

from __future__ import annotations

from fastapi import HTTPException

from .marketplace_client import (
    MarketplaceAuthError,
    MarketplaceClientError,
    MarketplaceNotFoundError,
    MarketplaceServerError,
    UnsupportedCapabilityError,
)


def propagate_marketplace_error(
    exc: MarketplaceClientError,
    *,
    not_found_tag: str = "marketplace_not_found",
) -> HTTPException:
    if isinstance(exc, MarketplaceAuthError):
        return HTTPException(
            status_code=502,
            detail={
                "error": "marketplace_auth_failed",
                "details": str(exc),
            },
        )
    if isinstance(exc, MarketplaceNotFoundError):
        return HTTPException(
            status_code=404,
            detail={
                "error": not_found_tag,
                "details": str(exc),
            },
        )
    if isinstance(exc, UnsupportedCapabilityError):
        return HTTPException(
            status_code=501,
            detail={
                "error": "marketplace_unsupported_capability",
                "capability": exc.capability,
            },
        )
    if isinstance(exc, MarketplaceServerError):
        return HTTPException(
            status_code=502,
            detail={
                "error": "marketplace_unavailable",
                "details": str(exc),
            },
        )
    return HTTPException(
        status_code=502,
        detail={
            "error": "marketplace_error",
            "details": str(exc),
        },
    )
