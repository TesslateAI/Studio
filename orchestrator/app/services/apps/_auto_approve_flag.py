"""Single source of truth for the apps dev auto-approve flag.

The primary env var is ``TSL_APPS_DEV_AUTO_APPROVE``. ``TSL_APPS_SKIP_APPROVAL``
remains recognized as a deprecated alias; if set, we log a single warning at
import time and honor its value.

Do NOT use this flag in production. ``app.config`` enforces a startup check
that raises if an HTTPS ``app_base_url`` is combined with this flag being on.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_PRIMARY_ENV = "TSL_APPS_DEV_AUTO_APPROVE"
_DEPRECATED_ENV = "TSL_APPS_SKIP_APPROVAL"
_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in _TRUTHY


# Emit the deprecation warning exactly once at module import time.
if os.environ.get(_DEPRECATED_ENV) is not None:
    logger.warning(
        "%s is deprecated; use %s instead.",
        _DEPRECATED_ENV,
        _PRIMARY_ENV,
    )


def is_auto_approve_enabled() -> bool:
    """Return True if the apps dev auto-approve flag is set via either env."""
    if _truthy(os.environ.get(_PRIMARY_ENV)):
        return True
    if _truthy(os.environ.get(_DEPRECATED_ENV)):
        return True
    return False


__all__ = ["is_auto_approve_enabled"]
