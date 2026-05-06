"""
Server-side governance helpers for the yank lifecycle.

The two-admin policy for ``severity == 'critical'`` lives here so the
marketplace service is the single point of enforcement. Orchestrators just
forward yank requests; the marketplace decides when a yank is terminal,
when it needs a second hand, and whether an appellant is the same admin
who filed the original request (and is therefore disallowed under the
two-admin policy).

Wave 8 moves the decision logic out of the orchestrator and into this
module. The orchestrator-side ``services/apps/yanks.py`` keeps its DB-row
service for local cache rows, but the *authority* for whether a critical
yank is resolved or open lives here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from ..models import YankAppeal, YankRequest

__all__ = [
    "AppealDecision",
    "PolicyDecision",
    "Severity",
    "appeal_can_resolve",
    "compute_initial_state",
    "decide_appeal",
]

Severity = Literal["low", "medium", "critical"]


@dataclass(frozen=True)
class PolicyDecision:
    """Outcome of evaluating policy against an incoming yank request."""

    state: Literal["open", "resolved"]
    resolution: str | None
    resolved_at: datetime | None
    requires_second_admin: bool


@dataclass(frozen=True)
class AppealDecision:
    """Outcome of evaluating policy against an incoming appeal."""

    appeal_state: Literal["open", "resolved"]
    appeal_decision: str | None
    yank_state: Literal["open", "resolved"]
    yank_resolution: str | None
    yank_resolved_at: datetime | None


def compute_initial_state(severity: Severity) -> PolicyDecision:
    """Decide initial yank state based on severity.

    Non-critical yanks resolve immediately ("applied"). Critical yanks
    stay ``open`` until a second admin confirms via the appeal endpoint.
    """
    now = datetime.now(timezone.utc)
    if severity == "critical":
        return PolicyDecision(
            state="open",
            resolution=None,
            resolved_at=None,
            requires_second_admin=True,
        )
    return PolicyDecision(
        state="resolved",
        resolution="applied",
        resolved_at=now,
        requires_second_admin=False,
    )


def appeal_can_resolve(
    yank: YankRequest,
    *,
    appellant_handle: str | None,
    appellant_token_id: uuid.UUID | None,
) -> tuple[bool, str | None]:
    """Two-admin policy gate for critical yank appeals.

    Returns ``(allowed, reason)``. When ``allowed`` is ``False`` the caller
    raises and the appeal is rejected; ``reason`` is the wire-stable error
    token surfaced to the caller.

    The check is identity-aware: matching on the human handle alone would
    let two different admins share a handle and bypass the gate, so we
    also compare the token id (which is unique per static or DB-issued
    bearer). Matching on either dimension is enough to refuse — the
    requester cannot use a freshly-minted token to "pretend" to be a
    second admin.
    """
    if yank.severity != "critical":
        return True, None
    if yank.state != "open":
        return True, None

    same_handle = bool(yank.requested_by) and yank.requested_by == appellant_handle
    same_token = (
        yank.requested_by_token_id is not None
        and appellant_token_id is not None
        and yank.requested_by_token_id == appellant_token_id
    )
    if same_handle or same_token:
        return False, "cannot_self_appeal_critical_yank"
    return True, None


def decide_appeal(
    yank: YankRequest,
    appeal: YankAppeal,  # noqa: ARG001 — kept for future extension; signature lives in service contract
    *,
    appellant_handle: str | None,
    appellant_token_id: uuid.UUID | None,
) -> AppealDecision:
    """Compute the post-appeal state for both rows.

    For critical, open yanks the appeal acts as the second-admin
    confirmation: resolves the yank with ``second_admin_confirmed`` and
    marks the appeal ``resolved``. For everything else the appeal records
    a creator-driven dispute and stays ``open`` for human review (the
    yank is unaffected).
    """
    allowed, _ = appeal_can_resolve(
        yank,
        appellant_handle=appellant_handle,
        appellant_token_id=appellant_token_id,
    )
    if not allowed:
        # Caller should have refused before calling decide_appeal; we treat
        # this as a no-op and surface the original yank state so callers
        # never accidentally resolve on a refused appeal.
        return AppealDecision(
            appeal_state="open",
            appeal_decision=None,
            yank_state=yank.state,  # type: ignore[arg-type]
            yank_resolution=yank.resolution,
            yank_resolved_at=yank.resolved_at,
        )

    now = datetime.now(timezone.utc)
    if yank.severity == "critical" and yank.state == "open":
        return AppealDecision(
            appeal_state="resolved",
            appeal_decision="second_admin_confirmed",
            yank_state="resolved",
            yank_resolution="second_admin_confirmed",
            yank_resolved_at=now,
        )
    # Non-critical / already-resolved yanks: appeal stays open for human
    # review. The creator can use this lane to dispute a non-critical yank
    # without changing the underlying state of the catalog.
    return AppealDecision(
        appeal_state="open",
        appeal_decision=None,
        yank_state=yank.state,  # type: ignore[arg-type]
        yank_resolution=yank.resolution,
        yank_resolved_at=yank.resolved_at,
    )
