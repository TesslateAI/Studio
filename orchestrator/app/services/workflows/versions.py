"""WorkflowVersion writer + reader (G1, issue #469).

One public function: :func:`snapshot_definition_to_version` reads the
current live state of an ``AutomationDefinition`` (its contract
columns + child rows) and persists a new immutable
:class:`~app.models_workflows.WorkflowVersion`. Returns the new
version row. Idempotent on payload content (UNIQUE on
``automation_id`` + ``payload_sha256`` returns the existing row
without inserting).

The router and the engine reach this through one entry point so the
snapshot shape lives in exactly one place.

The reader-side helpers (``materialize_actions_from_version``,
``get_head_version``) let the engine and dispatcher read from the
snapshot when a run is bound to a specific version, without forcing
the rest of the codebase to crack JSON.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import (
    AutomationAction,
    AutomationDefinition,
    AutomationDeliveryTarget,
    AutomationTrigger,
)
from ...models_workflows import WorkflowVersion

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Payload shape: a single complete snapshot of a definition.
# ----------------------------------------------------------------------


def _serialize_value(value: Any) -> Any:
    """Best-effort JSON-friendly coercion.

    Decimals and UUIDs come out as strings so the SHA stays stable.
    datetimes get isoformatted. Nested dicts / lists recurse.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    return str(value)


def _action_dict(a: AutomationAction) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "ordinal": int(a.ordinal),
        "action_type": str(a.action_type),
        "config": _serialize_value(a.config) or {},
        "app_action_id": str(a.app_action_id) if a.app_action_id else None,
        "parent_action_id": str(a.parent_action_id) if a.parent_action_id else None,
        "branch_condition": _serialize_value(a.branch_condition),
    }


def _trigger_dict(t: AutomationTrigger) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "kind": str(t.kind),
        "config": _serialize_value(t.config) or {},
        "is_active": bool(t.is_active),
    }


def _target_dict(d: AutomationDeliveryTarget) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "destination_id": str(d.destination_id),
        "ordinal": int(d.ordinal),
        "on_failure": _serialize_value(d.on_failure) or {},
        "artifact_filter": str(d.artifact_filter),
    }


async def build_payload(db: AsyncSession, *, definition: AutomationDefinition) -> dict[str, Any]:
    """Read the definition's children and build the canonical snapshot."""
    actions = (
        (
            await db.execute(
                select(AutomationAction)
                .where(AutomationAction.automation_id == definition.id)
                .order_by(AutomationAction.ordinal.asc())
            )
        )
        .scalars()
        .all()
    )
    triggers = (
        (
            await db.execute(
                select(AutomationTrigger)
                .where(AutomationTrigger.automation_id == definition.id)
                .order_by(AutomationTrigger.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    targets = (
        (
            await db.execute(
                select(AutomationDeliveryTarget)
                .where(AutomationDeliveryTarget.automation_id == definition.id)
                .order_by(AutomationDeliveryTarget.ordinal.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "contract": _serialize_value(definition.contract) or {},
        "max_compute_tier": int(definition.max_compute_tier or 0),
        "max_spend_per_run_usd": _serialize_value(definition.max_spend_per_run_usd),
        "max_spend_per_day_usd": _serialize_value(definition.max_spend_per_day_usd),
        "compute_profile": str(
            getattr(definition, "compute_profile", None) or "persistent_workspace"
        ),
        "workspace_scope": str(definition.workspace_scope or "none"),
        "name": str(definition.name),
        "actions": [_action_dict(a) for a in actions],
        "triggers": [_trigger_dict(t) for t in triggers],
        "delivery_targets": [_target_dict(d) for d in targets],
    }


def canonical_sha256(payload: dict[str, Any]) -> str:
    """Stable hash of a payload. Sort keys for cross-process repeatability."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


@dataclass
class SnapshotResult:
    """Outcome of a snapshot attempt.

    ``version`` is always the row that's now the canonical record for
    this content. ``inserted`` is True when we wrote a new row, False
    when we found an existing row with the same SHA.
    """

    version: WorkflowVersion
    inserted: bool


async def snapshot_definition_to_version(
    db: AsyncSession,
    *,
    definition: AutomationDefinition,
    rationale: str | None = None,
    actor_user_id: UUID | None = None,
    actor_run_id: UUID | None = None,
    update_head: bool = True,
) -> SnapshotResult:
    """Persist a new WorkflowVersion from the definition's current state.

    Idempotent: if the SHA already exists for this automation, returns
    that row (and still optionally updates ``head_version_id``). The
    caller is responsible for committing.

    ``update_head``: when True (default), also sets
    ``definition.head_version_id`` to the (new or existing) version.
    Routers always want this; backfill / pure-snapshot callers may not.
    """
    payload = await build_payload(db, definition=definition)
    sha = canonical_sha256(payload)

    # Dedupe path: identical content already exists.
    existing = (
        await db.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.automation_id == definition.id,
                WorkflowVersion.payload_sha256 == sha,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if update_head and definition.head_version_id != existing.id:
            definition.head_version_id = existing.id
        return SnapshotResult(version=existing, inserted=False)

    # Compute next generation.
    parent = (
        await db.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.automation_id == definition.id)
            .order_by(WorkflowVersion.generation.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    next_generation = (parent.generation + 1) if parent is not None else 1

    version = WorkflowVersion(
        id=uuid.uuid4(),
        automation_id=definition.id,
        generation=next_generation,
        parent_version_id=parent.id if parent is not None else None,
        payload=payload,
        payload_sha256=sha,
        created_by_user_id=actor_user_id,
        created_by_run_id=actor_run_id,
        rationale=rationale,
    )
    db.add(version)
    try:
        await db.flush()
    except IntegrityError:
        # Concurrent insert by another worker raced us to the same
        # SHA. Re-query and return the winner.
        await db.rollback()
        winner = (
            await db.execute(
                select(WorkflowVersion).where(
                    WorkflowVersion.automation_id == definition.id,
                    WorkflowVersion.payload_sha256 == sha,
                )
            )
        ).scalar_one()
        if update_head and definition.head_version_id != winner.id:
            definition.head_version_id = winner.id
        return SnapshotResult(version=winner, inserted=False)

    if update_head:
        definition.head_version_id = version.id

    logger.info(
        "workflow_version.created automation=%s generation=%d sha=%s actor_user=%s actor_run=%s",
        definition.id,
        next_generation,
        sha[:12],
        actor_user_id,
        actor_run_id,
    )
    return SnapshotResult(version=version, inserted=True)


async def get_head_version(db: AsyncSession, *, automation_id: UUID) -> WorkflowVersion | None:
    """Return the live head WorkflowVersion for an automation, or None."""
    definition = (
        await db.execute(
            select(AutomationDefinition).where(AutomationDefinition.id == automation_id)
        )
    ).scalar_one_or_none()
    if definition is None or definition.head_version_id is None:
        return None
    return (
        await db.execute(
            select(WorkflowVersion).where(WorkflowVersion.id == definition.head_version_id)
        )
    ).scalar_one_or_none()


async def ensure_head_version(
    db: AsyncSession, *, definition: AutomationDefinition
) -> WorkflowVersion:
    """Lazy-create the bootstrap (generation 1) version if missing.

    Used by the dispatcher for definitions created before G1: the
    first time we dispatch one, snapshot the current state and stamp
    head_version_id. Subsequent dispatches see the pointer and use
    the snapshot directly.
    """
    if definition.head_version_id is not None:
        existing = (
            await db.execute(
                select(WorkflowVersion).where(WorkflowVersion.id == definition.head_version_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    result = await snapshot_definition_to_version(
        db,
        definition=definition,
        rationale="G1 bootstrap (lazy-created on first dispatch)",
        update_head=True,
    )
    return result.version


# ----------------------------------------------------------------------
# Engine read-side: reconstruct action-shaped objects from a snapshot.
# ----------------------------------------------------------------------


@dataclass
class SnapshotAction:
    """Lightweight stand-in for AutomationAction when reading from a snapshot.

    The engine handlers only touch ``id``, ``ordinal``, ``action_type``,
    ``config`` (and a couple of optional fields). Using a dataclass
    instead of the ORM model avoids loading the row by id (the snapshot
    is authoritative for version-bound runs) and keeps the engine's
    code path unchanged.
    """

    id: UUID
    automation_id: UUID
    ordinal: int
    action_type: str
    config: dict[str, Any]
    app_action_id: UUID | None = None
    parent_action_id: UUID | None = None
    branch_condition: Any | None = None


def materialize_actions_from_version(
    version: WorkflowVersion,
) -> list[SnapshotAction]:
    """Reconstruct the engine-readable actions from a snapshot payload."""
    payload = version.payload or {}
    raw_actions = payload.get("actions") or []
    actions: list[SnapshotAction] = []
    for entry in raw_actions:
        if not isinstance(entry, dict):
            continue
        try:
            action_id = UUID(str(entry.get("id")))
        except (TypeError, ValueError):
            action_id = uuid.uuid4()
        actions.append(
            SnapshotAction(
                id=action_id,
                automation_id=version.automation_id,
                ordinal=int(entry.get("ordinal", 0)),
                action_type=str(entry.get("action_type", "")),
                config=dict(entry.get("config") or {}),
                app_action_id=(
                    UUID(str(entry["app_action_id"])) if entry.get("app_action_id") else None
                ),
                parent_action_id=(
                    UUID(str(entry["parent_action_id"])) if entry.get("parent_action_id") else None
                ),
                branch_condition=entry.get("branch_condition"),
            )
        )
    actions.sort(key=lambda a: a.ordinal)
    return actions
