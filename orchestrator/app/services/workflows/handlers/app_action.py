"""``app.invoke`` step handler.

Wraps :func:`app.services.automations.dispatcher._dispatch_app_action`
which delegates to ``services.apps.action_dispatcher`` for the actual
HTTP / Job / hosted-agent dispatch. Synchronous: the action dispatcher
blocks until the action returns or its bounded timeout fires.
"""

from __future__ import annotations

from typing import ClassVar

from .base import StepContext, StepHandler, StepResult, register_handler


@register_handler
class AppActionHandler(StepHandler):
    kind: ClassVar[str] = "app.invoke"

    async def execute(self, ctx: StepContext) -> StepResult:
        from ...automations.dispatcher import _dispatch_app_action

        output = await _dispatch_app_action(
            ctx.db,
            run=ctx.run,
            automation=ctx.automation,
            action=ctx.action,
            event_payload=ctx.event_payload,
        )
        return StepResult(output=output, async_handoff=False)
