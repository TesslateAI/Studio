"""Connector Proxy audit writes — one row per upstream call.

The audit row is the only persistent artifact of a proxy call; the
upstream response body is forwarded to the caller and **not** stored.
Errors carry a 500-char prefix of the upstream body so operators can
debug without re-running the call — but only after the writer scrubs any
``Authorization`` header echo or ``Bearer …`` token shape.

The writer is best-effort: a DB error during audit MUST NOT crash the
proxy call (the user got their response already). Failure is logged and
swallowed.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from ....models_automations import ConnectorProxyCall

logger = logging.getLogger(__name__)


# Two scrubbers: explicit "Authorization: …" headers (as a defensive
# measure if upstream echoes them in error JSON) and naked "Bearer …"
# token shapes anywhere in the body. We intentionally do NOT try to scrub
# every possible secret format — the goal is to defang the obvious self-
# inflicted leak (an error envelope that quoted the request header back).
_AUTH_HEADER_RE = re.compile(
    r"(authorization\s*[:=]\s*)([^\s,;\"\\\']+)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(
    r"\b(Bearer|token)\s+([A-Za-z0-9._\-+/=]{16,})",
    re.IGNORECASE,
)
_ERROR_PREFIX_LIMIT = 500


def scrub_error_body(body: str | None) -> str | None:
    """Strip Authorization headers and Bearer tokens from an error string.

    Returns at most ``_ERROR_PREFIX_LIMIT`` characters. None passes through.
    """
    if not body:
        return body
    # Bound the work — don't scrub a 5MB log line forever.
    truncated = body[:_ERROR_PREFIX_LIMIT * 4]
    scrubbed = _AUTH_HEADER_RE.sub(r"\1[REDACTED]", truncated)
    scrubbed = _BEARER_RE.sub(r"\1 [REDACTED]", scrubbed)
    return scrubbed[:_ERROR_PREFIX_LIMIT]


async def record_call(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
    requirement_id: UUID | None,
    connector_id: str,
    endpoint: str,
    method: str,
    status_code: int,
    bytes_in: int,
    bytes_out: int,
    duration_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Write one ``ConnectorProxyCall`` row. Failures are swallowed.

    The caller has already returned the upstream response to the app pod;
    a DB hiccup here must not surface as a 5xx for the user.
    """
    try:
        row = ConnectorProxyCall(
            id=uuid4(),
            app_instance_id=app_instance_id,
            requirement_id=requirement_id,
            connector_id=connector_id,
            endpoint=endpoint,
            method=(method or "POST").upper()[:8],
            status_code=int(status_code),
            bytes_in=int(bytes_in or 0),
            bytes_out=int(bytes_out or 0),
            duration_ms=duration_ms,
            error=scrub_error_body(error) if status_code >= 400 else None,
        )
        db.add(row)
        # Commit so the audit row survives even if the caller's session
        # closes without an explicit commit. The proxy is the only writer
        # in this transaction so a commit here cannot interleave with
        # other in-flight work.
        await db.commit()
    except Exception as exc:  # pragma: no cover — best-effort path
        logger.warning(
            "connector_proxy_calls audit write failed: connector=%s "
            "endpoint=%s status=%s error=%r",
            connector_id,
            endpoint,
            status_code,
            exc,
        )
        try:
            await db.rollback()
        except Exception:
            pass


__all__ = ["record_call", "scrub_error_body"]
