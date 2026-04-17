"""Node configuration router.

Three endpoints:

  * ``POST /api/chat/node-config/{input_id}/submit`` — agent-in-the-loop: the
    frontend submits a form the agent is waiting on.
  * ``POST /api/chat/node-config/{input_id}/cancel`` — agent-in-the-loop
    cancellation.
  * ``GET/PATCH /api/projects/{project_id}/containers/{container_id}/config``
    — direct-edit path (no agent involved). Reuses the same merge+encrypt
    logic via ``apply_node_config``.
  * ``POST /api/projects/{project_id}/containers/{container_id}/secrets/{key}/reveal``
    — user-only decryption of a single secret for display in the UI.

All endpoints are user-authenticated. Secret plaintext is never logged, never
returned via GET, and only returned by the explicit reveal endpoint (with an
audit log entry).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..auth_unified import get_authenticated_user
from ..database import get_db
from ..models import Container, Project, User
from ..models_team import AuditLog
from ..services.audit_service import log_event
from ..services.deployment_encryption import (
    DeploymentEncryptionError,
    get_deployment_encryption_service,
)
from ..services.node_config_presets import FormSchema, resolve_schema
from ..services.rate_limit import rate_limited
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class NodeConfigSubmitRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class NodeConfigPatchRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    overrides: list[dict[str, Any]] | None = None
    preset: str | None = None


# ---------------------------------------------------------------------------
# Shared merge/encrypt helper
# ---------------------------------------------------------------------------


def apply_node_config(
    container: Container,
    values: dict[str, Any],
    schema: FormSchema,
) -> dict[str, list[str]]:
    """Apply submitted form values to a container.

    Merge rules (matches the spec):
      * non-secret keys → written to ``environment_vars`` (overwrite).
      * secret keys with an explicit ``{"clear": true}`` → removed from
        ``encrypted_secrets``.
      * secret keys with a non-empty value → encrypted + stored.
      * secret keys absent or with empty string → keep existing.

    Returns a summary ``{updated_keys, rotated_secrets, cleared_secrets}``.
    """
    env_vars: dict[str, Any] = dict(container.environment_vars or {})
    encrypted: dict[str, Any] = dict(container.encrypted_secrets or {})
    secret_keys = schema.secret_keys()

    updated_keys: list[str] = []
    rotated_secrets: list[str] = []
    cleared_secrets: list[str] = []

    enc_service = get_deployment_encryption_service()

    for field in schema.fields:
        if field.key not in values:
            continue
        raw = values[field.key]

        if field.key in secret_keys:
            # Clear request
            if isinstance(raw, dict) and raw.get("clear") is True:
                if field.key in encrypted:
                    encrypted.pop(field.key, None)
                    cleared_secrets.append(field.key)
                    updated_keys.append(field.key)
                continue
            # Empty / sentinel → keep existing
            if raw is None or raw == "" or raw == "__SET__":
                continue
            if not isinstance(raw, str):
                raise HTTPException(
                    status_code=400,
                    detail=f"Secret value for '{field.key}' must be a string",
                )
            encrypted[field.key] = enc_service.encrypt(raw)
            rotated_secrets.append(field.key)
            updated_keys.append(field.key)
        else:
            # Non-secret: overwrite or clear
            if isinstance(raw, dict) and raw.get("clear") is True:
                if field.key in env_vars:
                    env_vars.pop(field.key, None)
                    updated_keys.append(field.key)
                continue
            if raw is None:
                continue
            env_vars[field.key] = raw if isinstance(raw, str) else str(raw)
            updated_keys.append(field.key)

    container.environment_vars = env_vars
    container.encrypted_secrets = encrypted or None
    flag_modified(container, "environment_vars")
    flag_modified(container, "encrypted_secrets")
    if rotated_secrets or cleared_secrets:
        container.needs_restart = True

    return {
        "updated_keys": updated_keys,
        "rotated_secrets": rotated_secrets,
        "cleared_secrets": cleared_secrets,
    }


def build_initial_values(
    container: Container, schema: FormSchema
) -> dict[str, Any]:
    """Build initialValues for the UI — non-secret values verbatim, secret
    keys as ``"__SET__"`` if stored, otherwise absent. Never decrypts."""
    values: dict[str, Any] = {}
    env_vars = container.environment_vars or {}
    encrypted = container.encrypted_secrets or {}
    for field in schema.fields:
        if field.is_secret:
            if field.key in encrypted:
                values[field.key] = "__SET__"
        elif field.key in env_vars:
            values[field.key] = env_vars[field.key]
    return values


# ---------------------------------------------------------------------------
# Agent-loop endpoints
# ---------------------------------------------------------------------------


async def _find_pending(input_id: str):
    from ..agent.tools.approval_manager import (
        get_pending_input_manager,
        publish_pending_input_response,
    )

    return get_pending_input_manager(), publish_pending_input_response


async def _verify_input_ownership(
    db: AsyncSession, current_user: User, input_id: str
) -> dict:
    """Verify the user owns the project tied to this pending input."""
    manager, _ = await _find_pending(input_id)
    req = manager._pending.get(input_id)  # noqa: SLF001 — internal hook for auth
    if req is None or req.kind != "node_config":
        # May be a cached early response — treat as unknown for auth purposes.
        raise HTTPException(status_code=404, detail="Unknown or expired input_id")
    project_id = req.metadata.get("project_id")
    if not project_id:
        raise HTTPException(status_code=404, detail="Pending input has no project")
    project = await db.get(Project, UUID(str(project_id)))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != current_user.id and not getattr(
        current_user, "is_superuser", False
    ):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    return req.metadata


@router.post("/chat/node-config/{input_id}/submit")
async def submit_node_config(
    input_id: str,
    body: NodeConfigSubmitRequest,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused agent with the user's submitted form values.

    The submitted ``values`` dict is never logged. We only log the set of
    keys, never the values.
    """
    await _verify_input_ownership(db, current_user, input_id)
    manager, publish = await _find_pending(input_id)

    logger.info(
        "[node-config] submit for input=%s keys=%s",
        input_id,
        sorted(body.values.keys()),
    )
    manager.submit_input(input_id, body.values)
    await publish(input_id, body.values, kind="node_config")
    return {"ok": True}


@router.post("/chat/node-config/{input_id}/cancel")
async def cancel_node_config(
    input_id: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_input_ownership(db, current_user, input_id)
    manager, publish = await _find_pending(input_id)
    logger.info("[node-config] cancel for input=%s", input_id)
    manager.cancel_input(input_id)
    await publish(input_id, "__cancelled__", kind="node_config")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Direct-edit PATCH + GET
# ---------------------------------------------------------------------------


async def _load_container_for_user(
    db: AsyncSession,
    current_user: User,
    project_id: UUID,
    container_id: UUID,
) -> tuple[Project, Container]:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != current_user.id and not getattr(
        current_user, "is_superuser", False
    ):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    container = await db.get(Container, container_id)
    if container is None or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")
    return project, container


def _resolve_schema_for_container(
    container: Container,
    preset: str | None,
    overrides: list[dict[str, Any]] | None,
) -> FormSchema:
    """Best-effort preset resolution: explicit > service_slug > external_generic."""
    if preset:
        return resolve_schema(preset, overrides)
    # Map some known service slugs to presets.
    slug = (container.service_slug or "").lower()
    if slug in ("supabase", "postgres", "postgresql", "stripe"):
        mapped = "postgres" if slug.startswith("postgres") else slug
        return resolve_schema(mapped, overrides)
    return resolve_schema("external_generic", overrides)


@router.get("/projects/{project_id}/containers/{container_id}/config")
async def get_container_config(
    project_id: UUID,
    container_id: UUID,
    preset: str | None = None,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    _, container = await _load_container_for_user(
        db, current_user, project_id, container_id
    )
    schema = _resolve_schema_for_container(container, preset, None)
    values = build_initial_values(container, schema)
    return {"schema": schema.to_dict(), "values": values, "preset": schema.preset}


@router.patch("/projects/{project_id}/containers/{container_id}/config")
async def patch_container_config(
    project_id: UUID,
    container_id: UUID,
    body: NodeConfigPatchRequest,
    request: Request,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    project, container = await _load_container_for_user(
        db, current_user, project_id, container_id
    )
    schema = _resolve_schema_for_container(container, body.preset, body.overrides)
    summary = apply_node_config(container, body.values, schema)
    await db.flush()

    # Audit — never log values
    if getattr(project, "team_id", None):
        await log_event(
            db=db,
            team_id=project.team_id,
            user_id=current_user.id,
            action="node_config_updated",
            resource_type="container",
            resource_id=container.id,
            project_id=project.id,
            details={**summary, "source": "direct_edit", "preset": schema.preset},
            request=request,
        )

    await db.commit()

    # Publish secret_rotated if needed so listeners can flag a restart.
    if summary["rotated_secrets"] or summary["cleared_secrets"]:
        try:
            from ..services.pubsub import get_pubsub

            pubsub = get_pubsub()
            if pubsub:
                await pubsub.publish_agent_event(
                    f"project:{project.id}",
                    {
                        "type": "secret_rotated",
                        "data": {
                            "container_id": str(container.id),
                            "keys": summary["rotated_secrets"]
                            + summary["cleared_secrets"],
                        },
                    },
                )
        except Exception:
            logger.exception("[node-config] failed to publish secret_rotated")

    return {**summary, "preset": schema.preset}


# ---------------------------------------------------------------------------
# Reveal (user-only; never used by agent)
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/containers/{container_id}/secrets/{key}/reveal"
)
async def reveal_container_secret(
    project_id: UUID,
    container_id: UUID,
    key: str,
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    _rl_burst: User = Depends(
        rate_limited(
            "reveal_secret_burst",
            capacity=10,
            window_seconds=300,
            audit_action="secret_reveal_rate_limited_burst",
        )
    ),
    _rl_daily: User = Depends(
        rate_limited(
            "reveal_secret_daily",
            capacity=100,
            window_seconds=86400,
            audit_action="secret_reveal_rate_limited_daily",
        )
    ),
):
    # Defense in depth: reject any caller whose principal was resolved via an
    # external API key. Plan invariant: reveal is never reachable via the agent
    # auth path, only via a human-session JWT.
    if getattr(current_user, "_api_key_record", None) is not None:
        raise HTTPException(status_code=403, detail="Reveal not permitted for API key auth")
    project, container = await _load_container_for_user(
        db, current_user, project_id, container_id
    )
    encrypted = container.encrypted_secrets or {}
    enc_val = encrypted.get(key)
    if not enc_val:
        raise HTTPException(status_code=404, detail="Secret not set")
    enc_service = get_deployment_encryption_service()
    try:
        plaintext = enc_service.decrypt(enc_val)
    except DeploymentEncryptionError as e:
        raise HTTPException(status_code=500, detail="Failed to decrypt secret") from e

    if getattr(project, "team_id", None):
        await log_event(
            db=db,
            team_id=project.team_id,
            user_id=current_user.id,
            action="secret_revealed",
            resource_type="container",
            resource_id=container.id,
            project_id=project.id,
            details={"key": key},
            request=request,
        )
        await db.commit()

    # Surface rate-limit state from the daily bucket (the broader cap).
    headers: dict[str, str] = {}
    rl_state = getattr(request.state, "rate_limit", None) or {}
    daily = rl_state.get("reveal_secret_daily")
    if daily:
        headers["X-RateLimit-Limit"] = str(daily["limit"])
        headers["X-RateLimit-Remaining"] = str(daily["remaining"])
        headers["X-RateLimit-Reset"] = str(daily["reset"])

    return JSONResponse(content={"value": plaintext}, headers=headers)


# Expose AuditLog import so it is not elided by linters for downstream edits
__all__ = ["router", "apply_node_config", "build_initial_values", "AuditLog"]
