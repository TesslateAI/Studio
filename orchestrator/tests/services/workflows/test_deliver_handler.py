"""Phase D (#473): the deliver step writes InboxItem rows for web_inbox.

Covers:

* A workflow with [agent.run-or-gateway.send -> deliver] writes one
  InboxItem per web_inbox CommunicationDestination on the automation.
* The InboxItem row has source_kind=workflow_run, the run id, and
  status=unread.
* The deliver step emits delivery.sent events into the run-event log.
* The deliver handler is registered for action_type='deliver'.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from .conftest import (
    seed_action,
    seed_automation,
    seed_event,
    seed_user,
)


async def _seed_destination_and_target(
    db,
    *,
    automation_id,
    owner_user_id,
):
    from app.models import ChannelConfig
    from app.models_automations import (
        AutomationDeliveryTarget,
        CommunicationDestination,
    )

    # ChannelConfig is FK-required on CommunicationDestination today
    # (web_inbox is a Phase D destination kind that doesn't actually use
    # the underlying credential; the FK predates the kind). Seed a
    # sentinel so the test row inserts cleanly.
    cc = ChannelConfig(
        id=uuid.uuid4(),
        user_id=owner_user_id,
        channel_type="web_inbox",
        name="sentinel",
        credentials="x",
        webhook_secret="x" * 16,
    )
    db.add(cc)
    await db.flush()

    dest = CommunicationDestination(
        id=uuid.uuid4(),
        owner_user_id=owner_user_id,
        channel_config_id=cc.id,
        kind="web_inbox",
        name="My Inbox",
        config={},
        formatting_policy="text",
    )
    db.add(dest)
    await db.flush()

    target = AutomationDeliveryTarget(
        id=uuid.uuid4(),
        automation_id=automation_id,
        destination_id=dest.id,
        ordinal=0,
        on_failure={},
        artifact_filter="all",
    )
    db.add(target)
    await db.flush()
    return dest.id


def test_deliver_handler_is_registered():
    import app.services.workflows.handlers  # noqa: F401
    from app.services.workflows.handlers.base import get_handler

    cls = get_handler("deliver")
    assert cls.kind == "deliver"


@pytest.mark.asyncio
async def test_deliver_step_writes_inbox_item(session_maker):
    from app.models_automations import AutomationRunEvent
    from app.models_inbox import InboxItem
    from app.services.automations.dispatcher import dispatch_automation

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            config={"body": "hello"},
            ordinal=0,
        )
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="deliver",
            config={
                "title_template": "{automation_name} delivered",
                "body_template": "delivered body for run {run_id}",
            },
            ordinal=1,
        )
        await _seed_destination_and_target(db, automation_id=autom_id, owner_user_id=owner_id)
        event_id = await seed_event(db, automation_id=autom_id)
        await db.commit()

    async with session_maker() as db:
        result = await dispatch_automation(
            db,
            automation_id=autom_id,
            event_id=event_id,
        )

    assert str(result.status) == "succeeded"

    async with session_maker() as db:
        items = (
            (await db.execute(select(InboxItem).where(InboxItem.source_run_id == result.run_id)))
            .scalars()
            .all()
        )
        assert len(items) == 1
        item = items[0]
        assert item.user_id == owner_id
        assert item.source_kind == "workflow_run"
        assert item.status == "unread"
        assert "delivered" in item.title

        # The deliver step emits one delivery.sent event for the
        # web_inbox destination it wrote.
        events = (
            (
                await db.execute(
                    select(AutomationRunEvent).where(
                        AutomationRunEvent.automation_run_id == result.run_id
                    )
                )
            )
            .scalars()
            .all()
        )
        delivery = [e for e in events if e.kind == "delivery.sent"]
        assert len(delivery) == 1
        assert delivery[0].payload.get("destination_kind") == "web_inbox"
