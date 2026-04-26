"""Automation Runtime services (Phase 1).

The dispatcher is the heavy worker that turns an :class:`AutomationEvent`
into a terminal :class:`AutomationRun`. It owns idempotency, contract
preflight, and routing to action executors (``agent.run`` / ``app.invoke``
/ ``gateway.send``).

Phase 1 ships a single-job dispatcher: ``dispatch_automation`` runs the
entire flow (preflight + execute + delivery) inside one ARQ task. The
three-job split (dispatch -> provision -> execute) lands in Phase 4 with
the controller; Phase 1 just stamps ``worker_id`` + ``heartbeat_at`` so
the Phase 4 sweep has the data it needs from day one.

See ``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
sections "dispatcher.py", "Idempotency - at the run, not just the event",
and "Three-job dispatch split" for the full design.
"""

from __future__ import annotations

from .dispatcher import (
    ActionDispatchFailed,
    AutomationDefinitionMissing,
    ContractInvalid,
    DispatchResult,
    DispatchStatus,
    dispatch_automation,
    update_run_heartbeat,
)

__all__ = [
    "ActionDispatchFailed",
    "AutomationDefinitionMissing",
    "ContractInvalid",
    "DispatchResult",
    "DispatchStatus",
    "dispatch_automation",
    "update_run_heartbeat",
]
