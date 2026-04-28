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

import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
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
    if updated_keys:
        container.needs_restart = True

    return {
        "updated_keys": updated_keys,
        "rotated_secrets": rotated_secrets,
        "cleared_secrets": cleared_secrets,
    }


# ---------------------------------------------------------------------------
# Restart dispatch — runs after apply_node_config commits.
# ---------------------------------------------------------------------------


async def _compute_restart_targets(
    db: AsyncSession,
    container: Container,
) -> list[Container]:
    """Containers that need a restart after env vars on `container` change.

    Targets:
      * `container` itself if it's an internal container (`deployment_mode == 'container'`).
      * Every container connected to `container` via `ContainerConnection` with
        `connector_type == 'env_injection'` (where `container` is the source).
    External-only sources never need to restart themselves; only their consumers do.
    """
    from sqlalchemy import or_

    from ..models import ContainerConnection

    targets: list[Container] = []
    if container.deployment_mode == "container":
        targets.append(container)

    result = await db.execute(
        select(ContainerConnection).where(
            ContainerConnection.source_container_id == container.id,
            ContainerConnection.connector_type == "env_injection",
        )
    )
    connections = list(result.scalars().all())
    if not connections:
        return targets

    target_ids = {c.target_container_id for c in connections}
    consumer_rows = await db.execute(
        select(Container).where(Container.id.in_(target_ids))
    )
    for consumer in consumer_rows.scalars().all():
        if consumer.deployment_mode == "container":
            targets.append(consumer)
    return targets


async def _restart_one(container_id: UUID, project_id: UUID, user_id: UUID) -> None:
    """Stop+start a single container in a fresh session. Best-effort, logs on failure."""
    from ..database import AsyncSessionLocal
    from ..services.orchestration import get_orchestrator, is_kubernetes_mode

    try:
        async with AsyncSessionLocal() as db:
            container = await db.get(Container, container_id)
            if container is None:
                logger.warning("[restart-on-save] container %s vanished", container_id)
                return
            project = await db.get(Project, project_id)
            if project is None:
                return

            orchestrator = get_orchestrator()
            stop_kwargs: dict[str, Any] = {
                "project_slug": project.slug,
                "project_id": project_id,
                "container_name": container.name,
                "user_id": user_id,
            }
            if is_kubernetes_mode() and getattr(container, "container_type", "base") == "service":
                stop_kwargs["container_type"] = "service"
                stop_kwargs["service_slug"] = container.service_slug
            try:
                await orchestrator.stop_container(**stop_kwargs)
            except Exception:
                logger.warning(
                    "[restart-on-save] stop_container failed for %s — proceeding to start",
                    container.name,
                )

            container = await db.get(Container, container_id)
            if container is None:
                return

            from ..models import ContainerConnection

            all_rows = await db.execute(
                select(Container).where(Container.project_id == project_id)
            )
            all_containers = list(all_rows.scalars().all())
            conn_rows = await db.execute(
                select(ContainerConnection).where(
                    ContainerConnection.project_id == project_id
                )
            )
            connections = list(conn_rows.scalars().all())

            await orchestrator.start_container(
                project=project,
                container=container,
                all_containers=all_containers,
                connections=connections,
                user_id=user_id,
                db=db,
            )
            container.needs_restart = False
            await db.commit()
    except Exception:
        logger.exception(
            "[restart-on-save] restart_one failed for container %s", container_id
        )


async def dispatch_restart_after_config_change(
    db: AsyncSession,
    container: Container,
    summary: dict[str, list[str]],
    project_id: UUID,
    user_id: UUID,
    pubsub_target: str | None,
) -> dict[str, Any]:
    """Schedule restarts for the consumers of a config change. Non-blocking.

    Returns a payload describing what's about to restart so the caller can
    surface it to the agent / UI.
    """
    if not summary["updated_keys"]:
        return {"restart_target_ids": [], "container_names": []}

    targets = await _compute_restart_targets(db, container)
    if not targets:
        return {"restart_target_ids": [], "container_names": []}

    target_ids = [str(c.id) for c in targets]
    target_names = [c.name for c in targets]

    for target in targets:
        asyncio.create_task(
            _restart_one(target.id, project_id, user_id)
        )

    if pubsub_target:
        try:
            from ..services.pubsub import get_pubsub

            pubsub = get_pubsub()
            if pubsub:
                await pubsub.publish_agent_event(
                    pubsub_target,
                    {
                        "type": "containers_restarting",
                        "data": {
                            "trigger_container_id": str(container.id),
                            "restart_target_ids": target_ids,
                            "container_names": target_names,
                        },
                    },
                )
        except Exception:
            logger.exception("[restart-on-save] failed to publish containers_restarting")

    return {
        "restart_target_ids": target_ids,
        "container_names": target_names,
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
    """Best-effort preset resolution: explicit > service_slug > external_generic.

    The known-slug list must stay in sync with the preset registry in
    ``services/node_config_presets.py`` — when a new preset is added there,
    add its slug here too or else the GET endpoint silently falls back to
    the empty ``external_generic`` schema and the UI renders "No fields".
    """
    if preset:
        return resolve_schema(preset, overrides)
    slug = (container.service_slug or "").lower()
    if slug in ("supabase", "stripe", "rest_api", "external_generic"):
        return resolve_schema(slug, overrides)
    if slug.startswith("postgres"):
        return resolve_schema("postgres", overrides)
    return resolve_schema("external_generic", overrides)


@router.get("/projects/{project_id}/config")
async def get_project_config(
    project_id: UUID,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated config view for the project's persistent Config tab.

    Returns one entry per container (external services + internal containers),
    each with its resolved form schema, masked initial values, and
    `pending_input_id` if the agent is currently paused on this container.

    Container.environment_vars + Container.encrypted_secrets stay the source
    of truth; the schema is rebuilt per request so preset changes propagate.
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id != current_user.id and not getattr(
        current_user, "is_superuser", False
    ):
        raise HTTPException(status_code=403, detail="Not authorized for this project")

    rows = await db.execute(
        select(Container).where(Container.project_id == project_id)
    )
    containers = list(rows.scalars().all())

    # Pending-input cross-reference. We snapshot the manager once so the view is
    # consistent — no need for a lock since we're just reading.
    from ..agent.tools.approval_manager import get_pending_input_manager

    manager = get_pending_input_manager()
    pending_by_container: dict[str, str] = {}
    for input_id, req in list(manager._pending.items()):  # noqa: SLF001
        if req.kind != "node_config":
            continue
        meta = req.metadata or {}
        if str(meta.get("project_id")) != str(project_id):
            continue
        cid = str(meta.get("container_id") or "")
        if cid:
            pending_by_container[cid] = input_id

    services: list[dict[str, Any]] = []
    for container in containers:
        schema = _resolve_schema_for_container(container, None, None)
        # For internal containers without a known preset, synthesize a schema
        # from the existing env_vars keys so the user can still edit them.
        if (
            container.deployment_mode == "container"
            and not container.service_slug
            and not schema.fields
            and (container.environment_vars or container.encrypted_secrets)
        ):
            schema = _synthesize_internal_schema(container)
        # Merge in any user-added keys (stored on the container but not in
        # the preset schema) — produced when the user adds custom fields via
        # the "+ Add field" affordance. Without this, the values round-trip
        # in the DB but disappear from the UI on next page load.
        schema = _merge_extra_keys_into_schema(container, schema)
        values = build_initial_values(container, schema)
        services.append(
            {
                "container_id": str(container.id),
                "container_name": container.name,
                "deployment_mode": container.deployment_mode,
                "container_type": container.container_type,
                "service_slug": container.service_slug,
                "preset": schema.preset,
                "schema": schema.to_dict(),
                "initial_values": values,
                "needs_restart": bool(getattr(container, "needs_restart", False)),
                "pending_input_id": pending_by_container.get(str(container.id)),
            }
        )

    # Sort: external first, then internal containers, alphabetically within group.
    services.sort(
        key=lambda s: (0 if s["deployment_mode"] == "external" else 1, s["container_name"].lower())
    )

    # Deployment providers — placeholder for the follow-up PR. Empty for now.
    deployment_providers: list[dict[str, Any]] = []

    return {
        "services": services,
        "deployment_providers": deployment_providers,
    }


def _merge_extra_keys_into_schema(
    container: Container, schema: FormSchema
) -> FormSchema:
    """Append synthesized fields for any stored env/secret key not already
    in ``schema.fields``. Powers the "+ Add field" affordance: once the user
    saves a custom key, the next GET surfaces it as a regular field so they
    can edit / clear / rotate it like any other.

    Heuristic on type: keys in ``encrypted_secrets`` become ``secret`` fields;
    keys in ``environment_vars`` become ``text`` fields. Original schema
    fields are preserved verbatim — we only ever append, never override.
    """
    from ..services.node_config_presets import FieldSchema as _FS

    existing_keys = {f.key for f in schema.fields}
    env_vars = container.environment_vars or {}
    encrypted = container.encrypted_secrets or {}

    extras: list[_FS] = []
    for key in sorted(env_vars.keys()):
        if key in existing_keys:
            continue
        extras.append(_FS(key=key, label=key, type="text", is_secret=False))
        existing_keys.add(key)
    for key in sorted(encrypted.keys()):
        if key in existing_keys:
            continue
        extras.append(_FS(key=key, label=key, type="secret", is_secret=True))
        existing_keys.add(key)

    if not extras:
        return schema
    return FormSchema(
        preset=schema.preset,
        display_name=schema.display_name,
        icon=schema.icon,
        deployment_mode=schema.deployment_mode,
        fields=[*schema.fields, *extras],
    )


def _synthesize_internal_schema(container: Container) -> FormSchema:
    """Build a synthetic schema from a container's existing env/secret keys.

    Used for internal containers that have no preset (e.g., a hand-rolled
    Postgres container). Lets the user edit existing keys via the Config tab
    without having to know the preset name.
    """
    from ..services.node_config_presets import FieldSchema as _FS

    env_vars = container.environment_vars or {}
    encrypted = container.encrypted_secrets or {}
    fields: list = []
    for key in sorted(env_vars.keys()):
        fields.append(_FS(key=key, label=key, type="text", is_secret=False))
    for key in sorted(encrypted.keys()):
        fields.append(_FS(key=key, label=key, type="secret", is_secret=True))
    return FormSchema(
        preset="internal_container",
        display_name=container.name,
        icon="cube",
        deployment_mode="container",
        fields=fields,
    )


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

    restart_payload = await dispatch_restart_after_config_change(
        db,
        container,
        summary,
        project_id=project.id,
        user_id=current_user.id,
        pubsub_target=f"project:{project.id}",
    )

    return {**summary, "preset": schema.preset, **restart_payload}


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
