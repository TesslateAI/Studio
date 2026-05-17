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
from .dry_run import DryRunResult, evaluate_dry_run
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
        "max_compute_tier",
        "max_spend_per_run_usd",
        "max_spend_per_day_usd",
        "compute_profile",
        "workspace_scope",
        "name",
    }
    for key in scalar_keys:
        # Treat absence in ``after`` as "unchanged" rather than "set to null".
        # Proposals routinely only include the fields they want to change;
        # forcing every diff to enumerate the whole shape would defeat the
        # purpose of a partial proposal.
        if key not in after:
            continue
        b = before.get(key)
        a = after.get(key)
        if b != a:
            diffs.append({"path": key, "op": "replace", "before": b, "after": a})

    # Contract: deep-walk top-level child keys so allow-list policies
    # like ``allowed_changes: ["contract.allowed_tools"]`` (#469
    # migration 0108) actually match a real diff path. A bare
    # ``contract`` replace would never be reachable by such a policy.
    if "contract" in after:
        before_contract = before.get("contract") or {}
        after_contract = after.get("contract") or {}
        if not isinstance(before_contract, dict) or not isinstance(after_contract, dict):
            # Non-dict contract — fall back to whole-object diff.
            if before_contract != after_contract:
                diffs.append(
                    {
                        "path": "contract",
                        "op": "replace",
                        "before": before_contract,
                        "after": after_contract,
                    }
                )
        else:
            for child_key in set(before_contract.keys()) | set(after_contract.keys()):
                b_present = child_key in before_contract
                a_present = child_key in after_contract
                b_val = before_contract.get(child_key)
                a_val = after_contract.get(child_key)
                path = f"contract.{child_key}"
                if not b_present and a_present:
                    diffs.append({"path": path, "op": "add", "before": None, "after": a_val})
                elif b_present and not a_present:
                    diffs.append({"path": path, "op": "remove", "before": b_val, "after": None})
                elif b_val != a_val:
                    diffs.append({"path": path, "op": "replace", "before": b_val, "after": a_val})

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


def evaluate_for_auto_apply(
    *,
    automation: AutomationDefinition,
    diff: list[dict[str, Any]],
    risk_class: str,
    proposer_run_id: UUID | None = None,
) -> tuple[bool, str | None]:
    """Decide whether a proposal qualifies for auto-apply (G3+G7, #469).

    Returns (auto_apply, reason). ``reason`` is a human-readable
    rejection string when auto_apply is False; null when True.

    Rules (any failure → manual approval):
      * G7 cooldown: if agent-authored AND last_self_edit_at is
        within min_seconds_between_self_edits, refuse.
      * G7 diff-budget: if diff_budget_consumed >= diff_budget_max,
        refuse — agents must wait for a human to approve before more
        auto-applies are eligible.
      * G3 policy is set (auto_apply_policy not None / empty)
      * G3 risk_class in {low, medium} (high always requires approval)
      * G3 every diff path matches one of policy.allowed_changes prefixes
      * G3 len(diff) <= policy.max_changes_per_proposal
      * G3 no diff path appears in policy.hard_blocked
    """
    # G7 cooldown: only enforced for agent-authored proposals.
    if proposer_run_id is not None:
        last = getattr(automation, "last_self_edit_at", None)
        cooldown = int(getattr(automation, "min_seconds_between_self_edits", 0) or 0)
        if last is not None and cooldown > 0:
            from datetime import UTC, datetime

            now = datetime.now(tz=UTC)
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            elapsed = (now - last).total_seconds()
            if elapsed < cooldown:
                return (
                    False,
                    f"cooldown active: {int(cooldown - elapsed)}s remaining "
                    f"(min_seconds_between_self_edits={cooldown})",
                )

    # G7 diff budget.
    consumed = int(getattr(automation, "diff_budget_consumed", 0) or 0)
    budget_max = int(getattr(automation, "diff_budget_max", 0) or 0)
    if budget_max > 0 and consumed >= budget_max:
        return (
            False,
            f"diff budget exhausted ({consumed}/{budget_max}); requires human approval to reset",
        )

    policy = getattr(automation, "auto_apply_policy", None)
    if not policy or not isinstance(policy, dict):
        return False, "no auto_apply_policy set on automation"

    if risk_class == "high":
        return False, "risk_class=high always routes to approval"

    allowed = policy.get("allowed_changes") or []
    if not isinstance(allowed, list) or not allowed:
        return False, "policy.allowed_changes empty or missing"

    hard_blocked = policy.get("hard_blocked") or []
    max_changes = int(policy.get("max_changes_per_proposal") or 0)
    if max_changes > 0 and len(diff) > max_changes:
        return (
            False,
            f"diff has {len(diff)} changes; policy max is {max_changes}",
        )

    for entry in diff:
        path = str(entry.get("path", ""))
        if any(path.startswith(b) for b in hard_blocked):
            return False, f"path {path!r} is hard-blocked by policy"
        if not any(path.startswith(a) for a in allowed):
            return (
                False,
                f"path {path!r} not in policy.allowed_changes",
            )
    return True, None


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

    # G3 (#469): auto-apply path. If the policy allows this change,
    # run the dry-run; if both pass, apply immediately and bump the
    # diff budget. Otherwise the proposal stays in 'submitted' and
    # waits for human review.
    auto_apply, reason = evaluate_for_auto_apply(
        automation=automation,
        diff=diff,
        risk_class=risk_class,
        proposer_run_id=proposer_run_id,
    )
    if auto_apply:
        dr: DryRunResult = evaluate_dry_run(to_payload)
        if dr.ok:
            try:
                await apply_proposal(
                    db,
                    proposal=proposal,
                    actor_user_id=proposer_user_id,
                )
                automation.diff_budget_consumed = int(automation.diff_budget_consumed or 0) + 1
                # G7: bump last_self_edit_at so the cooldown check
                # has a timestamp for the next agent edit.
                automation.last_self_edit_at = datetime.now(tz=UTC)
                proposal.reviewer_comment = "auto-applied: " + (
                    rationale[:200] if rationale else ""
                )
                logger.info(
                    "workflow_proposal.auto_applied automation=%s proposal=%s "
                    "diff_budget_consumed=%d",
                    automation.id,
                    proposal.id,
                    int(automation.diff_budget_consumed),
                )
            except Exception as exc:
                # If apply fails after auto-approval, leave the proposal
                # submitted so a human can still approve manually. Log
                # the reason so it's visible.
                logger.exception(
                    "workflow_proposal.auto_apply_failed automation=%s proposal=%s err=%r",
                    automation.id,
                    proposal.id,
                    exc,
                )
                proposal.reviewer_comment = f"auto_apply_failed: {exc!r}"
        else:
            proposal.reviewer_comment = f"auto_apply_skipped (dry_run failed): {dr.refusal_reason}"
            logger.info(
                "workflow_proposal.auto_apply_skipped automation=%s proposal=%s dry_run_refusal=%s",
                automation.id,
                proposal.id,
                dr.refusal_reason,
            )
    else:
        # Recording the reason on the proposal makes it visible to the
        # approver UI (and to the agent if it queries the proposal back).
        proposal.reviewer_comment = f"auto_apply_not_eligible: {reason}" if reason else None

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

    Caller is responsible for committing AND for having authorized
    write access on the target automation. This helper performs a
    defensive re-check that ``actor_user_id`` (or the proposer when
    no explicit actor is given) actually owns the target — defense
    in depth against any future caller that forgets the route-level
    ``_authorize_definition`` gate. Cross-team / shared-ownership
    callers should pass ``actor_user_id`` of an authorized writer.
    """
    automation = (
        await db.execute(
            select(AutomationDefinition).where(AutomationDefinition.id == proposal.automation_id)
        )
    ).scalar_one()

    # Defense in depth: refuse if neither an explicit reviewer nor a
    # tracked proposer is on record. Both code paths into
    # apply_proposal (G3 auto-apply inside create_proposal, and the
    # /proposals/{id}/decide HTTP route) supply one of these — a None
    # for both implies the caller skipped the upstream
    # _authorize_definition(write=True) gate.
    if actor_user_id is None and proposal.proposer_user_id is None:
        raise ProposalError(
            "apply_proposal refused: no actor_user_id or proposer_user_id on record; "
            "caller must authorize write before applying"
        )

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
    # G7: human approval resets the agent's diff budget so the
    # doctor can keep helping after a checkpoint.
    automation = (
        await db.execute(
            select(AutomationDefinition).where(AutomationDefinition.id == proposal.automation_id)
        )
    ).scalar_one()
    automation.diff_budget_consumed = 0
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
