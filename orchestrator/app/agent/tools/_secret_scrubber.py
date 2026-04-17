"""Project-scoped secret scrubber for agent-visible output.

Replaces any substring match of known project secrets in stdout/stderr with
``«secret:KEY»`` before the bytes ever reach the agent's context. Short
secrets (< 6 chars) are skipped to avoid noisy false positives.

The secrets dict is loaded lazily per-task and cached on the ``context``
dict under ``__secret_scrub_map__``.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_KEY = "__secret_scrub_map__"
_MIN_LEN = 6
# Minimum length to even consider scrubbing in scrub_text. Values below this
# are too likely to collide with ordinary words ("password", "dev", etc.).
_SCRUB_MIN_LEN = 12
# Shannon entropy floor (bits/char). Below this, the value looks like prose
# rather than a key/token and is skipped to avoid false-positive redactions.
_ENTROPY_FLOOR = 3.0
# Above this entropy OR length > _NAIVE_LEN, treat as unambiguous and use
# naked substring contains. Between the floor and ceiling, require word
# boundaries to avoid over-redaction.
_ENTROPY_CEILING = 4.0
_NAIVE_LEN = 20


def _entropy(s: str) -> float:
    """Shannon entropy of *s* in bits per character."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


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
    """Replace every secret substring in *text* with a reference marker.

    Heuristics to avoid both false positives and false negatives:
      * values shorter than ``_SCRUB_MIN_LEN`` are skipped (likely common words)
      * values with Shannon entropy below ``_ENTROPY_FLOOR`` are skipped
      * mid-length / mid-entropy values use ``\\b`` word boundaries
      * long or high-entropy values use unambiguous substring contains
    """
    if not text or not scrub_map:
        return text
    out = text
    entropy_cache: dict[str, float] = {}
    # Longest first so nested/overlapping secrets don't corrupt markers.
    for value in sorted(scrub_map, key=len, reverse=True):
        if not value or len(value) < _SCRUB_MIN_LEN:
            continue
        ent = entropy_cache.get(value)
        if ent is None:
            ent = _entropy(value)
            entropy_cache[value] = ent
        if ent < _ENTROPY_FLOOR:
            continue
        marker = f"«secret:{scrub_map[value]}»"
        if len(value) > _NAIVE_LEN or ent >= _ENTROPY_CEILING:
            if value in out:
                out = out.replace(value, marker)
        else:
            pattern = re.compile(rf"\b{re.escape(value)}\b")
            out = pattern.sub(marker, out)
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
