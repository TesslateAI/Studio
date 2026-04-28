"""AutomationRunArtifact persistence helper.

Replaces the inline artifact-creation block in
``services/apps/action_dispatcher.py._persist_artifacts`` with a single
public ``create_artifact()`` call. Routes storage based on size:

* ``len(content) <= 8 KiB`` → ``storage_mode='inline'``,
  ``storage_ref`` = base64-encoded content. Cheap rows the run-detail UI
  can render without a second round-trip.
* ``len(content) > 8 KiB`` → ``storage_mode='cas'``, ``storage_ref`` =
  ``sha256:<hex>``. The CAS payload is staged via the existing
  ``volume_hub`` blob path (``services.hub_client``) when configured;
  otherwise the row falls back to inline + truncation marker so
  artifacts never disappear silently.
* ``external_url`` mode used by callers passing a URL string instead of
  bytes — for provider-hosted artifacts (a Notion page the run created,
  an S3 link the agent already uploaded, …).

Preview text generation:

* ``text``, ``markdown``, ``json``, ``log``, ``csv`` → first 200 chars
  of the decoded content (UTF-8, ``errors='replace'``).
* ``image``, ``screenshot``, ``file`` → preview is None (UI shows a
  thumbnail / download link based on ``storage_mode``).
* ``delivery_receipt``, ``report`` → preview is the JSON-stringified
  metadata when content is dict-shaped, else first 200 chars.

The dispatcher's old inline path (``_persist_artifacts``) is rewritten
to defer to this helper so all artifact rows route through one code
path. Phase 4's UI-side download endpoint already accepts the
``storage_mode`` discriminator, so this is a pure swap.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import AutomationRunArtifact

logger = logging.getLogger(__name__)


# Inline storage cap. Keep modest: every inline row sits in the
# `automation_run_artifacts` table; large blobs would bloat run-list
# queries that join the artifact count.
INLINE_SIZE_LIMIT_BYTES = 8 * 1024

# Preview text cap. Long enough to render a useful inline summary in the
# run-history UI; short enough that a list of artifacts stays light.
PREVIEW_TEXT_CHARS = 200

# Kinds for which we generate a preview text. Other kinds (image,
# screenshot, file) get no preview — the UI renders thumbnails / download
# links from the storage_mode + mime_type instead.
_PREVIEWABLE_TEXT_KINDS = frozenset(
    {"text", "markdown", "json", "log", "csv", "report", "delivery_receipt"}
)

_VALID_KINDS = frozenset(
    {
        "text",
        "markdown",
        "json",
        "log",
        "csv",
        "report",
        "delivery_receipt",
        "image",
        "screenshot",
        "file",
    }
)

_VALID_STORAGE_MODES = frozenset(
    {"inline", "cas", "s3", "external_url"}
)


class ArtifactError(Exception):
    """Base class for artifact-creation errors."""


class InvalidArtifactKind(ArtifactError):
    """Raised when ``kind`` is not in the allowed set."""


class InvalidArtifactStorage(ArtifactError):
    """Raised when ``storage_mode`` is not in the allowed set."""


def _to_bytes(content: Any) -> bytes:
    """Coerce arbitrary content into bytes for size routing.

    * ``bytes`` / ``bytearray`` pass through.
    * ``str`` is encoded UTF-8.
    * ``dict`` / ``list`` are JSON-dumped (default=str so UUIDs / Decimals
      survive without special-casing).
    * Anything else falls back to ``str(...)``.
    """
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    if isinstance(content, str):
        return content.encode("utf-8")
    if isinstance(content, (dict, list)):
        return json.dumps(content, default=str).encode("utf-8")
    return str(content).encode("utf-8")


def _build_preview(
    *, kind: str, content: Any, content_bytes: bytes
) -> str | None:
    """Return a short preview string suitable for the run-history UI.

    For dict/list content, prefer pretty-printed JSON over the raw
    str() form — it's what users actually want to see in a card preview.
    """
    if kind not in _PREVIEWABLE_TEXT_KINDS:
        return None
    if isinstance(content, (dict, list)):
        try:
            text = json.dumps(content, default=str, indent=2)
        except (TypeError, ValueError):
            text = str(content)
        return text[:PREVIEW_TEXT_CHARS]
    try:
        text = content_bytes.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — defensive
        return None
    return text[:PREVIEW_TEXT_CHARS]


async def _upload_to_cas(content_bytes: bytes, sha256_hex: str) -> str | None:
    """Upload large payloads to the CAS layer and return the blob ref.

    Phase 3 wires through the existing volume-hub blob path when present;
    the function returns None on any failure so the caller can fall back
    to inline-with-truncation. We keep the upload best-effort because the
    artifact row should land regardless of CAS availability — a missing
    blob shows up in the UI as "preview unavailable", not as a 500.

    The ``volume_hub`` HubClient API today is volume-shaped, not blob-
    shaped; until the dedicated `PutBlob` RPC lands, we return None and
    the caller stores inline+truncated. This keeps the function signature
    stable so the wave that adds the RPC swaps the body without touching
    callers.
    """
    try:
        # Future hook — when HubClient.put_blob lands:
        #   from ..hub_client import get_hub_client
        #   client = await get_hub_client()
        #   ref = await client.put_blob(content_bytes, sha256=sha256_hex)
        #   return f"cas:{ref}"
        return None
    except Exception as exc:  # noqa: BLE001 — never fail artifact creation
        logger.warning(
            "artifacts: CAS upload failed sha=%s err=%r", sha256_hex[:16], exc
        )
        return None


async def create_artifact(
    db: AsyncSession,
    *,
    run_id: UUID,
    kind: str,
    name: str,
    mime_type: str | None = None,
    content: Any = None,
    metadata: dict[str, Any] | None = None,
    external_url: str | None = None,
) -> AutomationRunArtifact:
    """Persist an artifact row, routing storage by content size.

    Args:
        db: Async session — caller owns commit semantics. We ``flush`` so
            the row is visible to subsequent queries in the same TXN.
        run_id: ``automation_runs.id`` to attribute against.
        kind: One of ``text | markdown | json | file | log | report |
            image | screenshot | csv | delivery_receipt``.
        name: User-facing name (e.g., ``"standup-2026-04-25.md"``).
        mime_type: Optional MIME type for download dispositions.
        content: Bytes / str / dict / list payload. Pass ``None`` together
            with ``external_url`` for ``external_url`` mode.
        metadata: Free-form dict persisted on the row's ``meta`` column.
        external_url: When set, the row uses ``storage_mode='external_url'``
            and ``storage_ref=external_url``. ``content`` is ignored.

    Returns:
        The persisted ``AutomationRunArtifact`` row (post-flush).

    Raises:
        InvalidArtifactKind: ``kind`` is not in the allowed set.
        ArtifactError: neither ``content`` nor ``external_url`` provided.
    """
    if kind not in _VALID_KINDS:
        raise InvalidArtifactKind(
            f"kind {kind!r} not allowed; valid: {sorted(_VALID_KINDS)}"
        )

    meta = dict(metadata or {})

    # ---------------------------- external_url ----------------------------
    if external_url is not None:
        row = AutomationRunArtifact(
            id=uuid4(),
            run_id=run_id,
            kind=kind,
            name=name,
            mime_type=mime_type,
            storage_mode="external_url",
            storage_ref=external_url,
            preview_text=None,
            size_bytes=None,
            meta=meta,
        )
        db.add(row)
        await db.flush()
        return row

    if content is None:
        raise ArtifactError(
            "create_artifact requires either content= or external_url="
        )

    # ------------------------- inline / CAS routing ------------------------
    content_bytes = _to_bytes(content)
    size_bytes = len(content_bytes)
    preview = _build_preview(
        kind=kind, content=content, content_bytes=content_bytes
    )

    if size_bytes <= INLINE_SIZE_LIMIT_BYTES:
        storage_mode = "inline"
        # base64 so the column can carry binary payloads verbatim — TEXT
        # columns on Postgres tolerate UTF-8 strings only.
        storage_ref = base64.b64encode(content_bytes).decode("ascii")
    else:
        sha = hashlib.sha256(content_bytes).hexdigest()
        cas_ref = await _upload_to_cas(content_bytes, sha)
        if cas_ref is not None:
            storage_mode = "cas"
            storage_ref = cas_ref
            meta.setdefault("sha256", sha)
        else:
            # Fallback: inline + truncate. Surfaces the truncation
            # explicitly in metadata so the UI can render a "view full
            # via download" affordance even when CAS is unavailable.
            storage_mode = "inline"
            truncated = content_bytes[:INLINE_SIZE_LIMIT_BYTES]
            storage_ref = base64.b64encode(truncated).decode("ascii")
            meta.setdefault("sha256", sha)
            meta["truncated"] = True
            meta["original_size_bytes"] = size_bytes
            logger.warning(
                "artifacts: CAS unavailable; storing inline+truncated "
                "name=%s size=%d sha=%s",
                name,
                size_bytes,
                sha[:16],
            )

    row = AutomationRunArtifact(
        id=uuid4(),
        run_id=run_id,
        kind=kind,
        name=name,
        mime_type=mime_type,
        storage_mode=storage_mode,
        storage_ref=storage_ref,
        preview_text=preview,
        size_bytes=size_bytes,
        meta=meta,
    )
    db.add(row)
    await db.flush()
    return row


__all__ = [
    "ArtifactError",
    "INLINE_SIZE_LIMIT_BYTES",
    "InvalidArtifactKind",
    "InvalidArtifactStorage",
    "PREVIEW_TEXT_CHARS",
    "create_artifact",
]
