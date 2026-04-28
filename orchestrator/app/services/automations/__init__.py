"""Automation Runtime services (Phase 1 + Phase 2 Wave 2A).

The dispatcher is the heavy worker that turns an :class:`AutomationEvent`
into a terminal :class:`AutomationRun`. It owns idempotency, contract
preflight, and routing to action executors (``agent.run`` / ``app.invoke``
/ ``gateway.send``).

Phase 1 ships a single-job dispatcher: ``dispatch_automation`` runs the
entire flow (preflight + execute + delivery) inside one ARQ task. The
three-job split (dispatch -> provision -> execute) lands in Phase 4 with
the controller; Phase 1 just stamps ``worker_id`` + ``heartbeat_at`` so
the Phase 4 sweep has the data it needs from day one.

Phase 2 Wave 2A layers non-blocking HITL on top: when ContractGate denies
a tool call, the dispatcher writes an :class:`AutomationApprovalRequest`
plus a :class:`RunCheckpoint`, transitions the run to
``status='waiting_approval'``, and returns cleanly so the worker exits.
The user resolves the approval card via the router; that handler enqueues
``resume_automation_run`` which calls :func:`resume_run` here to continue.

See ``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
sections "dispatcher.py", "Idempotency - at the run, not just the event",
"Three-job dispatch split", and "Non-blocking HITL pattern".
"""

from __future__ import annotations

from .checkpoint import (
    ResumeStrategy,
    RunCheckpoint,
    determine_resume_strategy,
    hydrate_checkpoint,
    serialize_checkpoint,
)
from .dispatcher import (
    ActionDispatchFailed,
    AutomationDefinitionMissing,
    ContractInvalid,
    DispatchResult,
    DispatchStatus,
    dispatch_automation,
    resume_run,
    update_run_heartbeat,
)

__all__ = [
    "ActionDispatchFailed",
    "AutomationDefinitionMissing",
    "ContractInvalid",
    "DispatchResult",
    "DispatchStatus",
    "ResumeStrategy",
    "RunCheckpoint",
    "determine_resume_strategy",
    "dispatch_automation",
    "hydrate_checkpoint",
    "resume_run",
    "serialize_checkpoint",
    "update_run_heartbeat",
]
