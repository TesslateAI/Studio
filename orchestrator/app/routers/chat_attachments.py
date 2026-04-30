"""Standalone-chat file-upload endpoint.

``POST /api/chats/{chat_id}/attachments`` (multipart, ``file`` field) streams
a single upload to the chat's attached workspace and INSERTs a
``ChatAttachment`` row with ``message_id=NULL``. The id is returned to the
frontend, which carries it back inside the next ``SerializedAttachment``
(``file_reference`` variant) so the orchestrator's chat-send handler can
patch ``message_id`` and the orphan GC leaves the row alone.

Constraints (project-wide convention — see
``services/gateway/runner.py:25``, ``services/channels/telegram.py:542``,
``services/channels/slack.py:408``):

* 25 MiB hard cap, enforced server-side. Returns 413
  ``{"code": "file_too_large", "max_bytes": 26214400}`` on overrun.
* No mime allowlist. Detected mime is recorded as metadata only.

Storage layout: ``<workspace_root>/.chat/<chat_id>/uploads/<sha256>-<name>``.
The ``.chat`` prefix keeps user file trees clean and gives a single delete
target on chat removal.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import mimetypes
import os
import re
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_unified import get_authenticated_user
from ..config import get_settings
from ..database import get_db
from ..models import Chat, ChatAttachment, Project, User

logger = logging.getLogger(__name__)

router = APIRouter()


# Project-wide upload cap (mirrors gateway/channels conventions).
MAX_ATTACHMENT_BYTES: int = 25 * 1024 * 1024
# Stream chunk for the bounded copy. 1 MiB keeps memory flat and cleanly
# crosses the 25 MiB cap on chunk boundaries.
_CHUNK_BYTES: int = 1 * 1024 * 1024

# Filenames are stored as-is for display, but the on-disk path strips path
# separators and control chars to prevent traversal under .chat/.
_UNSAFE_FILENAME = re.compile(r"[\x00-\x1f/\\]")


def _sanitize_filename(raw: str | None) -> str:
    """Strip path separators / control chars, fall back to "upload" if blank."""
    if not raw:
        return "upload"
    cleaned = _UNSAFE_FILENAME.sub("_", os.path.basename(raw)).strip()
    return cleaned or "upload"


async def _resolve_workspace_root(project: Project) -> Path:
    """Resolve the on-disk workspace root for a project regardless of mode.

    The lookup mirrors ``_materialize_empty_workspace`` and the file-tools
    path:

    * desktop / local runtime → ``_get_project_root(project)`` under
      ``$OPENSAIL_HOME/projects/{slug}-{id}``.
    * docker → ``DockerComposeOrchestrator.get_project_path(slug)``.
    * k8s → fall back to a per-volume staging dir under
      ``$OPENSAIL_HOME/cache/chat_uploads/{volume_id}``. K8s file tools
      reach the volume via the Hub anyway; this gives the orchestrator a
      writable surface for the upload pipeline.
    """
    settings = get_settings()
    deployment_mode = (settings.deployment_mode or "").lower()
    runtime = (project.runtime or "").lower()

    if deployment_mode == "kubernetes" or runtime == "k8s":
        from ..services.desktop_paths import ensure_opensail_home

        home = ensure_opensail_home(getattr(settings, "opensail_home", None) or None)
        target = home / "cache" / "chat_uploads" / (project.volume_id or str(project.id))
        target.mkdir(parents=True, exist_ok=True)
        return target

    if deployment_mode == "desktop" or runtime == "local":
        from ..services.orchestration.local import _get_project_root

        return _get_project_root(project)

    # Docker / cloud non-k8s default.
    try:
        from ..services.orchestration import get_orchestrator

        orchestrator = get_orchestrator()
        get_path = getattr(orchestrator, "get_project_path", None)
        if get_path is not None:
            return Path(get_path(project.slug))
    except Exception:
        logger.exception(
            "[chat_attachments] failed to resolve docker project path for %s",
            project.id,
        )
    # Last resort — use desktop paths so the upload doesn't hard-fail.
    from ..services.desktop_paths import ensure_opensail_home

    home = ensure_opensail_home(getattr(settings, "opensail_home", None) or None)
    fallback = home / "cache" / "chat_uploads" / str(project.id)
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


@router.post("/chats/{chat_id}/attachments")
async def upload_chat_attachment(
    chat_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a single file into the chat's attached workspace.

    The server enforces the 25 MiB cap by streaming + counting bytes; the
    advisory ``Content-Length`` is checked first as a fast path but the
    streamed write aborts + cleans up if the body lies about its size.
    """
    chat = await db.get(Chat, chat_id)
    if chat is None or chat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Chat not found")

    if chat.project_id is None:
        # Standalone chat with no workspace — frontend should have triggered
        # WorkspaceAttachCard first. Returning 409 with a code lets the UI
        # branch cleanly.
        return JSONResponse(
            status_code=409,
            content={"code": "no_workspace", "message": "Chat has no attached workspace"},
        )

    project = await db.get(Project, chat.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if project.owner_id != current_user.id and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Not authorized for this workspace")

    # Fast path: trust the advertised Content-Length when oversized.
    advertised = file.size or 0
    if advertised and advertised > MAX_ATTACHMENT_BYTES:
        return JSONResponse(
            status_code=413,
            content={
                "code": "file_too_large",
                "max_bytes": MAX_ATTACHMENT_BYTES,
            },
        )

    workspace_root = await _resolve_workspace_root(project)
    uploads_dir = workspace_root / ".chat" / str(chat_id) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    original_name = _sanitize_filename(file.filename)
    # Stage to a temp filename so we never publish a partial file at the final
    # path — partial files would survive a crash/abort.
    staging_path = uploads_dir / f".staging-{uuid4().hex}"
    sha = hashlib.sha256()
    bytes_written = 0
    aborted_too_large = False

    try:
        with staging_path.open("wb") as fh:
            while True:
                chunk = await file.read(_CHUNK_BYTES)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > MAX_ATTACHMENT_BYTES:
                    aborted_too_large = True
                    break
                fh.write(chunk)
                sha.update(chunk)
        if aborted_too_large:
            try:
                staging_path.unlink()
            except OSError:
                logger.warning(
                    "[chat_attachments] failed to unlink oversized staging file %s",
                    staging_path,
                )
            return JSONResponse(
                status_code=413,
                content={
                    "code": "file_too_large",
                    "max_bytes": MAX_ATTACHMENT_BYTES,
                },
            )
    except Exception:
        # Anything other than a controlled cap-overrun: clean up + 500.
        with contextlib.suppress(OSError):
            staging_path.unlink()
        logger.exception("[chat_attachments] streaming write failed for chat=%s", chat_id)
        raise HTTPException(status_code=500, detail="Failed to save attachment") from None

    digest = sha.hexdigest()
    final_path = uploads_dir / f"{digest}-{original_name}"
    # Idempotent placement: if a previous upload of the same content exists,
    # discard the duplicate staging file rather than overwriting.
    if final_path.exists():
        with contextlib.suppress(OSError):
            staging_path.unlink()
    else:
        os.replace(staging_path, final_path)

    mime_type = file.content_type or mimetypes.guess_type(original_name)[0]

    attachment = ChatAttachment(
        chat_id=chat_id,
        user_id=current_user.id,
        message_id=None,
        file_path=str(final_path),
        original_filename=original_name,
        sha256=digest,
        mime_type=mime_type,
        size_bytes=bytes_written,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    logger.info(
        "[chat_attachments] uploaded chat=%s attachment=%s size=%d sha256=%s",
        chat_id,
        attachment.id,
        bytes_written,
        digest[:12],
    )

    return {
        "attachment_id": str(attachment.id),
        "file_path": str(final_path),
        "filename": original_name,
        "mime_type": mime_type,
        "size_bytes": bytes_written,
        "sha256": digest,
    }


@router.delete("/chats/{chat_id}/attachments/{attachment_id}")
async def cancel_chat_attachment(
    chat_id: UUID,
    attachment_id: UUID,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an unsent attachment (``message_id IS NULL``).

    Bound attachments stay — they're part of the chat's history.
    """
    row = await db.execute(
        select(ChatAttachment).where(
            ChatAttachment.id == attachment_id,
            ChatAttachment.chat_id == chat_id,
            ChatAttachment.user_id == current_user.id,
        )
    )
    attachment = row.scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if attachment.message_id is not None:
        raise HTTPException(
            status_code=409, detail="Cannot delete an attachment already bound to a message"
        )

    try:
        Path(attachment.file_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("[chat_attachments] failed to unlink %s on cancel", attachment.file_path)

    await db.delete(attachment)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Orphan GC
# ---------------------------------------------------------------------------


async def gc_orphan_chat_attachments(
    db: AsyncSession, *, older_than_seconds: int = 24 * 60 * 60
) -> int:
    """Delete ``ChatAttachment`` rows still ``message_id IS NULL`` after the
    cutoff and remove the underlying files. Returns the number of rows
    pruned. Safe to call on any cadence; idempotent.
    """
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    rows = await db.execute(
        select(ChatAttachment).where(
            ChatAttachment.message_id.is_(None),
            ChatAttachment.created_at < cutoff,
        )
    )
    orphans = list(rows.scalars().all())
    pruned = 0
    for row in orphans:
        try:
            Path(row.file_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("[chat_attachments] gc: failed to unlink %s", row.file_path)
        await db.delete(row)
        pruned += 1
    if pruned:
        await db.commit()
        logger.info("[chat_attachments] gc pruned %d orphan attachments", pruned)
    return pruned


__all__ = [
    "router",
    "MAX_ATTACHMENT_BYTES",
    "gc_orphan_chat_attachments",
]
