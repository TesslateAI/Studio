"""``gateway.send`` step handler.

Wraps :func:`app.services.automations.dispatcher._dispatch_gateway_send`
which renders ``config.body_template`` and XADDs an envelope to the
gateway delivery stream. Synchronous: the XADD completes inline.
Becomes a no-op (returns an empty result dict) if Redis is unavailable,
matching the legacy dispatcher's tolerant behavior.
"""

from __future__ import annotations

from typing import ClassVar

from .base import StepContext, StepHandler, StepResult, register_handler


@register_handler
class GatewaySendHandler(StepHandler):
    kind: ClassVar[str] = "gateway.send"

    async def execute(self, ctx: StepContext) -> StepResult:
        from ...automations.dispatcher import _dispatch_gateway_send

        output = await _dispatch_gateway_send(
            ctx.db,
            run=ctx.run,
            automation=ctx.automation,
            action=ctx.action,
            event_payload=ctx.event_payload,
        )
        return StepResult(output=output, async_handoff=False)
