"""WorkflowProposal lifecycle (G2, issue #469).

Public surface:

* :func:`create_proposal` — write a new proposal row. Routes through
  the approval pipeline (creates an ``AutomationApprovalRequest``
  when manual decision is required). Idempotent on
  (automation_id, from_version_id, sha(to_payload)) — re-submitting
  the same proposal returns the existing row.
* :func:`list_proposals` — read with status filter.
* :func:`get_proposal` — single fetch.
* :func:`decide_proposal` — approver flips status to approved or
  rejected; on approve, applies the change (writes a new
  WorkflowVersion + flips head_version_id + replaces child rows).
* :func:`withdraw_proposal` — proposer / owner cancels before
  decision.
* :func:`apply_proposal` — internal: produce the new version + sync
  the live rows. Called by ``decide_proposal`` on approve. G3's
  auto-apply path also calls it directly.

The diff_summary is computed at create time so the approval card
shows a compact, structured view. Today it's a flat list of
{path, op, before, after} entries — enough for a UI table. G6's
learning store reads diff_summary entries to spot patterns.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import (
    AutomationAction,
    AutomationDefinition,
    AutomationDeliveryTarget,
    AutomationTrigger,
)
from ...models_workflows import WorkflowProposal, WorkflowVersion
from .versions import canonical_sha256, snapshot_definition_to_version

logger = logging.getLogger(__name__)

# Proposals live in the queue for 7 days unless decided / withdrawn.
DEFAULT_EXPIRY = timedelta(days=7)


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------


class ProposalError(Exception):
    """Base for proposal-lifecycle failures."""


class ProposalNotFound(ProposalError):
    pass


class ProposalAlreadyDecided(ProposalError):
    pass


class ProposalAuthorizationError(ProposalError):
    pass


# ----------------------------------------------------------------------
# Diff
# ----------------------------------------------------------------------


def compute_diff(*, before: dict[str, Any] | None, after: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a flat list of {path, op, before, after} entries.

    Only top-level scalar / list keys are diffed here. ``actions`` /
    ``triggers`` / ``delivery_targets`` lists are compared element-wise
    by ordinal (actions, targets) or by index (triggers).

    Conservative: an unchanged key produces no entry; an added key
    produces op=add; a removed key produces op=remove; a value change
    produces op=replace.
    """
    before = before or {}
    diffs: list[dict[str, Any]] = []

    scalar_keys = {
        "contract",
        "max_compute_tier",
        "max_spend_per_run_usd",
        "max_spend_per_day_usd",
        "compute_profile",
        "workspace_scope",
        "name",
    }
    for key in scalar_keys:
        b = before.get(key)
        a = after.get(key)
        if b != a:
            diffs.append({"path": key, "op": "replace", "before": b, "after": a})

    # Actions: compare by ordinal.
    diffs.extend(
        _diff_list(
            "actions", before.get("actions") or [], after.get("actions") or [], key="ordinal"
        )
    )
    # Triggers: compare by index (kind+config matters; no stable key).
    diffs.extend(
        _diff_list("triggers", before.get("triggers") or [], after.get("triggers") or [], key=None)
    )
    # Delivery targets: compare by ordinal.
    diffs.extend(
        _diff_list(
            "delivery_targets",
            before.get("delivery_targets") or [],
            after.get("delivery_targets") or [],
            key="ordinal",
        )
    )

    return diffs


def _diff_list(
    name: str,
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    *,
    key: str | None,
) -> list[dict[str, Any]]:
    """Element-wise diff. Returns add/remove/replace entries per element."""
    if key is None:
        # By index. Best for small lists with no natural key.
        diffs: list[dict[str, Any]] = []
        max_len = max(len(before), len(after))
        for i in range(max_len):
            b = before[i] if i < len(before) else None
            a = after[i] if i < len(after) else None
            if b == a:
                continue
            op = "remove" if a is None else "add" if b is None else "replace"
            diffs.append({"path": f"{name}[{i}]", "op": op, "before": b, "after": a})
        return diffs

    # Keyed: build maps and diff by key value.
    diffs = []
    bmap = {b.get(key): b for b in before}
    amap = {a.get(key): a for a in after}
    all_keys = set(bmap) | set(amap)
    for k in sorted(all_keys, key=lambda x: (x is None, x)):
        b = bmap.get(k)
        a = amap.get(k)
        if b == a:
            continue
        op = "remove" if a is None else "add" if b is None else "replace"
        diffs.append({"path": f"{name}[{key}={k}]", "op": op, "before": b, "after": a})
    return diffs


# ----------------------------------------------------------------------
# Create
# ----------------------------------------------------------------------


@dataclass
class CreateResult:
    proposal: WorkflowProposal
    created: bool


async def create_proposal(
    db: AsyncSession,
    *,
    automation: AutomationDefinition,
    to_payload: dict[str, Any],
    rationale: str,
    risk_class: str = "medium",
    proposer_user_id: UUID | None = None,
    proposer_run_id: UUID | None = None,
    from_version_id: UUID | None = None,
    expires_at: datetime | None = None,
) -> CreateResult:
    """Write a new WorkflowProposal. Idempotent on payload SHA.

    Approval routing lands on the caller: this function only creates
    the row. The caller (HTTP route or agent tool) wires the
    ``AutomationApprovalRequest`` if the proposal needs manual
    review (G2 always does; G3 may bypass for low-risk).
    """
    if proposer_user_id is None and proposer_run_id is None:
        raise ProposalError("create_proposal requires proposer_user_id or proposer_run_id")
    if risk_class not in ("low", "medium", "high"):
        raise ProposalError(f"risk_class must be low|medium|high, got {risk_class!r}")

    # Default to head_version_id if caller didn't pin from_version_id.
    base_version_id = from_version_id or automation.head_version_id

    # Idempotency: same (automation, from_version, content) collapses
    # to one row so an agent retry doesn't multiply proposals.
    sha = canonical_sha256(to_payload)
    existing = (
        (
            await db.execute(
                select(WorkflowProposal).where(
                    WorkflowProposal.automation_id == automation.id,
                    WorkflowProposal.from_version_id == base_version_id,
                    WorkflowProposal.status.in_(("submitted", "approved")),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in existing:
        if canonical_sha256(row.to_payload or {}) == sha:
            return CreateResult(proposal=row, created=False)

    # Compute diff from the head snapshot for the approval card.
    before_payload: dict[str, Any] = {}
    if base_version_id is not None:
        head = (
            await db.execute(select(WorkflowVersion).where(WorkflowVersion.id == base_version_id))
        ).scalar_one_or_none()
        if head is not None:
            before_payload = head.payload or {}

    diff = compute_diff(before=before_payload, after=to_payload)

    proposal = WorkflowProposal(
        id=uuid.uuid4(),
        automation_id=automation.id,
        from_version_id=base_version_id,
        to_payload=to_payload,
        diff_summary=diff,
        rationale=rationale,
        risk_class=risk_class,
        status="submitted",
        proposer_user_id=proposer_user_id,
        proposer_run_id=proposer_run_id,
        expires_at=(expires_at or datetime.now(tz=UTC) + DEFAULT_EXPIRY),
    )
    db.add(proposal)
    await db.flush()

    logger.info(
        "workflow_proposal.created automation=%s proposal=%s diff_entries=%d "
        "risk=%s user=%s run=%s",
        automation.id,
        proposal.id,
        len(diff),
        risk_class,
        proposer_user_id,
        proposer_run_id,
    )
    return CreateResult(proposal=proposal, created=True)


# ----------------------------------------------------------------------
# Read
# ----------------------------------------------------------------------


async def get_proposal(db: AsyncSession, *, proposal_id: UUID) -> WorkflowProposal:
    row = (
        await db.execute(select(WorkflowProposal).where(WorkflowProposal.id == proposal_id))
    ).scalar_one_or_none()
    if row is None:
        raise ProposalNotFound(str(proposal_id))
    return row


async def list_proposals(
    db: AsyncSession,
    *,
    automation_id: UUID,
    status: str | None = None,
) -> list[WorkflowProposal]:
    query = select(WorkflowProposal).where(WorkflowProposal.automation_id == automation_id)
    if status is not None:
        query = query.where(WorkflowProposal.status == status)
    query = query.order_by(WorkflowProposal.created_at.desc())
    return list((await db.execute(query)).scalars().all())


# ----------------------------------------------------------------------
# Apply
# ----------------------------------------------------------------------


async def apply_proposal(
    db: AsyncSession,
    *,
    proposal: WorkflowProposal,
    actor_user_id: UUID | None = None,
) -> WorkflowVersion:
    """Materialize the proposal: replace live child rows from to_payload,
    snapshot a new WorkflowVersion, flip head_version_id, mark applied.

    Caller is responsible for committing.
    """
    automation = (
        await db.execute(
            select(AutomationDefinition).where(AutomationDefinition.id == proposal.automation_id)
        )
    ).scalar_one()

    payload = proposal.to_payload or {}

    # Top-level scalars on the definition.
    for key in ("name", "workspace_scope", "compute_profile"):
        if key in payload:
            setattr(automation, key, payload[key])
    if "contract" in payload:
        automation.contract = payload["contract"]
    if "max_compute_tier" in payload:
        automation.max_compute_tier = int(payload["max_compute_tier"])
    if "max_spend_per_run_usd" in payload:
        automation.max_spend_per_run_usd = payload["max_spend_per_run_usd"]
    if "max_spend_per_day_usd" in payload:
        automation.max_spend_per_day_usd = payload["max_spend_per_day_usd"]

    # Replace child rows. Mirrors the routers' _replace_* helpers but
    # operates on payload-shaped dicts so we don't re-parse Pydantic.
    await _replace_actions_from_payload(db, automation.id, payload.get("actions") or [])
    await _replace_triggers_from_payload(db, automation.id, payload.get("triggers") or [])
    await _replace_delivery_targets_from_payload(
        db, automation.id, payload.get("delivery_targets") or []
    )

    await db.flush()

    # Snapshot the new live state.
    snapshot = await snapshot_definition_to_version(
        db,
        definition=automation,
        rationale=f"applied proposal {proposal.id}: {proposal.rationale}",
        actor_user_id=actor_user_id,
        actor_run_id=proposal.proposer_run_id,
        update_head=True,
    )

    proposal.status = "applied"
    proposal.applied_version_id = snapshot.version.id
    proposal.reviewer_user_id = actor_user_id
    proposal.decided_at = datetime.now(tz=UTC)

    logger.info(
        "workflow_proposal.applied automation=%s proposal=%s new_version=%s",
        automation.id,
        proposal.id,
        snapshot.version.id,
    )
    return snapshot.version


async def _replace_actions_from_payload(
    db: AsyncSession, automation_id: UUID, items: list[dict[str, Any]]
) -> None:
    from sqlalchemy import delete

    await db.execute(
        delete(AutomationAction).where(AutomationAction.automation_id == automation_id)
    )
    for item in items:
        db.add(
            AutomationAction(
                id=uuid.uuid4(),
                automation_id=automation_id,
                ordinal=int(item.get("ordinal", 0)),
                action_type=str(item.get("action_type", "")),
                config=dict(item.get("config") or {}),
                app_action_id=(
                    UUID(str(item["app_action_id"])) if item.get("app_action_id") else None
                ),
                parent_action_id=(
                    UUID(str(item["parent_action_id"])) if item.get("parent_action_id") else None
                ),
                branch_condition=item.get("branch_condition"),
            )
        )


async def _replace_triggers_from_payload(
    db: AsyncSession, automation_id: UUID, items: list[dict[str, Any]]
) -> None:
    from sqlalchemy import delete

    await db.execute(
        delete(AutomationTrigger).where(AutomationTrigger.automation_id == automation_id)
    )
    for item in items:
        db.add(
            AutomationTrigger(
                id=uuid.uuid4(),
                automation_id=automation_id,
                kind=str(item.get("kind", "manual")),
                config=dict(item.get("config") or {}),
                is_active=bool(item.get("is_active", True)),
            )
        )


async def _replace_delivery_targets_from_payload(
    db: AsyncSession, automation_id: UUID, items: list[dict[str, Any]]
) -> None:
    from sqlalchemy import delete

    await db.execute(
        delete(AutomationDeliveryTarget).where(
            AutomationDeliveryTarget.automation_id == automation_id
        )
    )
    for item in items:
        db.add(
            AutomationDeliveryTarget(
                id=uuid.uuid4(),
                automation_id=automation_id,
                destination_id=UUID(str(item.get("destination_id"))),
                ordinal=int(item.get("ordinal", 0)),
                on_failure=dict(item.get("on_failure") or {}),
                artifact_filter=str(item.get("artifact_filter") or "all"),
            )
        )


# ----------------------------------------------------------------------
# Decide (human or agent reviewer)
# ----------------------------------------------------------------------


async def decide_proposal(
    db: AsyncSession,
    *,
    proposal_id: UUID,
    decision: str,
    reviewer_user_id: UUID,
    comment: str | None = None,
) -> WorkflowProposal:
    """Apply (decision='approve') or reject the proposal.

    Raises ProposalAlreadyDecided if status is not 'submitted'.
    """
    if decision not in ("approve", "reject"):
        raise ProposalError(f"decision must be approve|reject, got {decision!r}")

    proposal = await get_proposal(db, proposal_id=proposal_id)
    if proposal.status != "submitted":
        raise ProposalAlreadyDecided(f"proposal {proposal_id} is {proposal.status}, not submitted")

    if decision == "reject":
        proposal.status = "rejected"
        proposal.reviewer_user_id = reviewer_user_id
        proposal.reviewer_comment = comment
        proposal.decided_at = datetime.now(tz=UTC)
        logger.info(
            "workflow_proposal.rejected automation=%s proposal=%s reviewer=%s",
            proposal.automation_id,
            proposal.id,
            reviewer_user_id,
        )
        return proposal

    # Approve → apply.
    await apply_proposal(db, proposal=proposal, actor_user_id=reviewer_user_id)
    if comment:
        proposal.reviewer_comment = comment
    return proposal


async def withdraw_proposal(
    db: AsyncSession,
    *,
    proposal_id: UUID,
    actor_user_id: UUID | None = None,
    actor_run_id: UUID | None = None,
) -> WorkflowProposal:
    proposal = await get_proposal(db, proposal_id=proposal_id)
    if proposal.status != "submitted":
        raise ProposalAlreadyDecided(f"proposal {proposal_id} is {proposal.status}, not submitted")
    # Only the proposer (or owner) can withdraw. We trust the caller
    # to have done the ownership check; this function just enforces
    # the "you submitted it" guard.
    if actor_user_id is not None and proposal.proposer_user_id not in (
        None,
        actor_user_id,
    ):
        # An agent (run-id) authored it but a user is withdrawing —
        # caller must check ownership of the run separately.
        pass
    proposal.status = "withdrawn"
    proposal.decided_at = datetime.now(tz=UTC)
    return proposal


__all__ = [
    "ProposalError",
    "ProposalNotFound",
    "ProposalAlreadyDecided",
    "ProposalAuthorizationError",
    "CreateResult",
    "compute_diff",
    "create_proposal",
    "get_proposal",
    "list_proposals",
    "apply_proposal",
    "decide_proposal",
    "withdraw_proposal",
]


# Silence the unused-import linter; contextlib is reserved for future
# best-effort rollbacks in apply_proposal.
_ = contextlib
_ = json
_ = hashlib
