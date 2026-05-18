"""``deliver`` step handler (Phase D, issue #473).

Renders a workflow result against a small templating context and fans
it out to one or more :class:`CommunicationDestination` rows. Each
destination kind has its own delivery path:

* ``web_inbox`` — writes an :class:`InboxItem` row.
* ``slack_*`` / ``telegram_*`` / ``discord_*`` — calls
  ``services.gateway.delivery_client`` (existing fan-out for approval
  cards is reused).
* ``email`` — Phase D follow-up (the approval-email path is reused
  there).
* ``webhook`` — POST to ``config.webhook_url`` with HMAC, same shape
  the external agent API uses.

The handler emits ``delivery.sent`` events into
``automation_run_events`` per destination so the run-history timeline
shows where the result went.

Phase D scope: the ``web_inbox`` path is wired end-to-end. The other
kinds raise :class:`NotImplementedError` with a clear message until
the per-channel adapter lands.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import select

from ....models_automations import (
    AutomationDeliveryTarget,
    CommunicationDestination,
)
from ....models_inbox import InboxItem
from .. import event_log
from .base import StepContext, StepHandler, StepResult, register_handler

logger = logging.getLogger(__name__)


@register_handler
class DeliverHandler(StepHandler):
    kind: ClassVar[str] = "deliver"

    async def execute(self, ctx: StepContext) -> StepResult:
        """Fan out to every delivery target on the automation.

        For each destination row attached to the automation, dispatch
        based on its ``kind``. Aggregate per-destination results into
        the step output so the run-history detail view can show what
        was delivered where.
        """
        targets = (
            (
                await ctx.db.execute(
                    select(AutomationDeliveryTarget)
                    .where(AutomationDeliveryTarget.automation_id == ctx.automation.id)
                    .order_by(AutomationDeliveryTarget.ordinal.asc())
                )
            )
            .scalars()
            .all()
        )

        delivered: list[dict[str, Any]] = []
        for target in targets:
            dest = (
                await ctx.db.execute(
                    select(CommunicationDestination).where(
                        CommunicationDestination.id == target.destination_id
                    )
                )
            ).scalar_one_or_none()
            if dest is None:
                logger.warning(
                    "deliver: destination not found target=%s automation=%s",
                    target.id,
                    ctx.automation.id,
                )
                continue

            outcome = await self._dispatch_one(ctx, dest=dest)
            delivered.append(outcome)

            await event_log.emit_delivery_sent(
                ctx.db,
                run_id=ctx.run.id,
                step_run_id=None,
                destination_kind=outcome["destination_kind"],
                destination_id=str(dest.id),
            )

        return StepResult(
            output={
                "action_type": "deliver",
                "delivered": delivered,
                "destination_count": len(delivered),
            },
            async_handoff=False,
        )

    async def _dispatch_one(
        self, ctx: StepContext, *, dest: CommunicationDestination
    ) -> dict[str, Any]:
        kind = dest.kind
        body = self._render_body(ctx)
        title = self._render_title(ctx, dest)

        if kind == "web_inbox":
            return await self._deliver_web_inbox(ctx, dest=dest, title=title, body=body)

        # Other kinds (slack_*, telegram_*, discord_*, email, webhook)
        # arrive in Phase D follow-ups. For now, surface a clear
        # NotImplementedError so callers see exactly which destination
        # the platform doesn't yet handle. The deliver step itself is
        # robust: missing handler = single destination skipped, the
        # rest of the fan-out continues.
        return {
            "destination_kind": kind,
            "destination_id": str(dest.id),
            "delivered": False,
            "reason": f"deliver kind {kind!r} pending in phase D follow-up",
        }

    async def _deliver_web_inbox(
        self,
        ctx: StepContext,
        *,
        dest: CommunicationDestination,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        """Insert an InboxItem for the destination owner / team."""
        item = InboxItem(
            id=uuid.uuid4(),
            user_id=dest.owner_user_id,
            team_id=dest.team_id,
            source_kind="workflow_run",
            source_run_id=ctx.run.id,
            title=title[:256],
            body_md=body,
            status="unread",
        )
        ctx.db.add(item)
        await ctx.db.commit()
        await ctx.db.refresh(item)
        return {
            "destination_kind": "web_inbox",
            "destination_id": str(dest.id),
            "delivered": True,
            "inbox_item_id": str(item.id),
        }

    def _render_title(self, ctx: StepContext, dest: CommunicationDestination) -> str:
        """Title falls back to the automation name if the action config
        does not provide a template. Truncated to 256 chars at insert."""
        config = ctx.action.config or {}
        tpl = config.get("title_template") or config.get("title")
        if isinstance(tpl, str) and tpl:
            return _render_simple(tpl, ctx)
        return f"{ctx.automation.name} run"

    def _render_body(self, ctx: StepContext) -> str:
        """Body falls back to a JSON dump of prior step outputs.

        Phase D supports plain ``{key}`` interpolation against the
        run context (event payload + last step output). The sandboxed
        Jinja worker arrives in a Phase D follow-up; the plain format
        is enough for "send the run summary to the inbox".
        """
        config = ctx.action.config or {}
        tpl = config.get("body_template") or config.get("body")
        if isinstance(tpl, str) and tpl:
            return _render_simple(tpl, ctx)
        prior = ctx.prior_step_outputs[-1] if ctx.prior_step_outputs else {}
        return f"Workflow result:\n\n```\n{prior!r}\n```"


def _render_simple(template: str, ctx: StepContext) -> str:
    """``{key}`` interpolation against a flat context.

    Mirrors the ``_render_simple_template`` helper in
    ``services/automations/dispatcher.py`` so behavior is identical
    between the legacy single-step gateway.send and the workflow-engine
    deliver step.
    """
    if not template:
        return ""
    flat: dict[str, Any] = {}
    if isinstance(ctx.event_payload, dict):
        flat.update(ctx.event_payload)
    if ctx.prior_step_outputs:
        last = ctx.prior_step_outputs[-1]
        if isinstance(last, dict):
            flat.update({f"step.{k}": v for k, v in last.items()})
            flat["last_output"] = last
    flat["automation_name"] = ctx.automation.name
    flat["run_id"] = str(ctx.run.id)
    flat["now"] = datetime.now(tz=UTC).isoformat()
    try:
        return template.format_map(_DefaultDict(flat))
    except (ValueError, IndexError, KeyError):
        return template


class _DefaultDict(dict):
    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return "{" + key + "}"
