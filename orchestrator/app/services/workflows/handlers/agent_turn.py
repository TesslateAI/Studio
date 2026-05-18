"""``agent.run`` step handler.

Wraps the existing ``_dispatch_agent_run`` and ``_dispatch_agent_run_tier1``
functions in :mod:`app.services.automations.dispatcher`. The handler
chooses tier-1 (synchronous ephemeral pod) or tier-0 (async ARQ
enqueue) based on ``automation.max_compute_tier`` exactly as the
legacy single-action dispatcher does.

Tier-0 returns ``async_handoff=True``. Phase A's engine refuses to
schedule a *next* step after a tier-0 step in a multi-step workflow,
because the worker callback that closes the run does not yet advance
the engine. Tier-0 single-step automations stay on the legacy
single-action dispatcher path and are unaffected. Phase B wires the
worker callback so async steps can chain.
"""

from __future__ import annotations

from typing import ClassVar

from .base import StepContext, StepHandler, StepResult, register_handler


@register_handler
class AgentTurnHandler(StepHandler):
    kind: ClassVar[str] = "agent.run"

    async def execute(self, ctx: StepContext) -> StepResult:
        # Lazy import: dispatcher.py is large and pulls in many siblings.
        # Keeping this lazy avoids paying the cost (and the circular-
        # import risk) at module-import time.
        from ...automations.dispatcher import (
            _dispatch_agent_run,
            _dispatch_agent_run_tier1,
        )

        tier = ctx.automation.max_compute_tier
        if isinstance(tier, int) and tier == 1:
            output = await _dispatch_agent_run_tier1(
                ctx.db,
                run=ctx.run,
                automation=ctx.automation,
                action=ctx.action,
                event_payload=ctx.event_payload,
                budget_allocation=ctx.budget_allocation,
            )
            return StepResult(output=output, async_handoff=False)

        output = await _dispatch_agent_run(
            ctx.db,
            run=ctx.run,
            automation=ctx.automation,
            action=ctx.action,
            event_payload=ctx.event_payload,
            budget_allocation=ctx.budget_allocation,
        )
        async_handoff = bool(isinstance(output, dict) and output.get("enqueued") is True)
        return StepResult(output=output, async_handoff=async_handoff)
