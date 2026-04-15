"""Project-scoped secret scrubber for agent-visible output.

Replaces any substring match of known project secrets in stdout/stderr with
``«secret:KEY»`` before the bytes ever reach the agent's context. Short
secrets (< 6 chars) are skipped to avoid noisy false positives.

The secrets dict is loaded lazily per-task and cached on the ``context``
dict under ``__secret_scrub_map__``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_KEY = "__secret_scrub_map__"
_MIN_LEN = 6


async def _load_project_secrets(context: dict[str, Any]) -> dict[str, str]:
    """Load {plaintext_value: env_key_name} for every secret in the project."""
    project_id = context.get("project_id")
    db = context.get("db")
    if not project_id or db is None:
        return {}

    from sqlalchemy import select

    from ...models import Container
    from ...services.deployment_encryption import (
        DeploymentEncryptionError,
        get_deployment_encryption_service,
    )

    try:
        enc = get_deployment_encryption_service()
    except Exception:
        logger.debug("[secret_scrubber] no encryption service available")
        return {}

    result = await db.execute(
        select(Container).where(Container.project_id == project_id)
    )
    mapping: dict[str, str] = {}
    for container in result.scalars().all():
        encrypted = container.encrypted_secrets or {}
        for key, enc_val in encrypted.items():
            if not isinstance(enc_val, str) or not enc_val:
                continue
            try:
                plaintext = enc.decrypt(enc_val)
            except DeploymentEncryptionError:
                continue
            except Exception:
                continue
            if plaintext and len(plaintext) >= _MIN_LEN:
                mapping[plaintext] = key
    return mapping


async def get_scrub_map(context: dict[str, Any]) -> dict[str, str]:
    """Return a cached secret->key map for the current tool-execution context."""
    cached = context.get(_CACHE_KEY)
    if cached is not None:
        return cached
    mapping = await _load_project_secrets(context)
    context[_CACHE_KEY] = mapping
    return mapping


def scrub_text(text: str, scrub_map: dict[str, str]) -> str:
    """Replace every secret substring in *text* with a reference marker."""
    if not text or not scrub_map:
        return text
    out = text
    # Longest first so nested/overlapping secrets don't corrupt markers.
    for value in sorted(scrub_map, key=len, reverse=True):
        if value and value in out:
            out = out.replace(value, f"«secret:{scrub_map[value]}»")
    return out


async def scrub_tool_result(result: Any, context: dict[str, Any]) -> Any:
    """Best-effort scrub of common output-bearing fields on a tool result dict."""
    if not isinstance(result, dict):
        return result
    scrub_map = await get_scrub_map(context)
    if not scrub_map:
        return result
    for key in ("output", "stdout", "stderr", "message"):
        if isinstance(result.get(key), str):
            result[key] = scrub_text(result[key], scrub_map)
    details = result.get("details")
    if isinstance(details, dict):
        for key in ("output", "stdout", "stderr"):
            if isinstance(details.get(key), str):
                details[key] = scrub_text(details[key], scrub_map)
    return result
