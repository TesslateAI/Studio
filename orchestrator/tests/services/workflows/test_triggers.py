"""Phase E (#474): Slack-message + email-inbound trigger adapters.

Covers:

* ``slack_message`` trigger fires when an inbound message matches the
  config (channel_id, regex, user mention).
* Mismatched messages are skipped without firing.
* ``email_inbound`` trigger fires when sender/recipient match;
  subject_regex narrows further.
* Idempotency keys collapse retries.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from .conftest import (
    seed_action,
    seed_automation,
    seed_user,
)


async def _seed_trigger(db, *, automation_id, kind: str, config: dict):
    from app.models_automations import AutomationTrigger

    t = AutomationTrigger(
        id=uuid.uuid4(),
        automation_id=automation_id,
        kind=kind,
        config=config,
        is_active=True,
    )
    db.add(t)
    await db.flush()
    return t.id


@pytest.mark.asyncio
async def test_slack_message_trigger_fires_on_match(session_maker):
    from app.models_automations import AutomationEvent
    from app.services.triggers.slack_message import route_inbound_message

    cc_id = uuid.uuid4()

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            ordinal=0,
        )
        await _seed_trigger(
            db,
            automation_id=autom_id,
            kind="slack_message",
            config={
                "channel_config_id": str(cc_id),
                "regex": "^build status",
            },
        )
        await db.commit()

    async with session_maker() as db:
        event_ids = await route_inbound_message(
            db,
            channel_config_id=cc_id,
            channel_id="C123",
            user_id="U456",
            body="build status please",
        )
        assert len(event_ids) == 1
        # Mismatched body does not fire (idempotency key differs, but
        # the regex predicate filters it out).
        no_match = await route_inbound_message(
            db,
            channel_config_id=cc_id,
            channel_id="C123",
            user_id="U456",
            body="totally unrelated message",
        )
        assert no_match == []

        # Event row was persisted with payload.
        evt = (
            await db.execute(select(AutomationEvent).where(AutomationEvent.id == event_ids[0]))
        ).scalar_one()
        assert evt.trigger_kind == "slack_message"
        assert evt.payload.get("channel_id") == "C123"
        assert "build status" in evt.payload.get("body", "")


@pytest.mark.asyncio
async def test_slack_message_idempotency_collapses_retries(session_maker):
    from app.services.triggers.slack_message import route_inbound_message

    cc_id = uuid.uuid4()

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            ordinal=0,
        )
        await _seed_trigger(
            db,
            automation_id=autom_id,
            kind="slack_message",
            config={"channel_config_id": str(cc_id)},
        )
        await db.commit()

    async with session_maker() as db:
        first = await route_inbound_message(
            db,
            channel_config_id=cc_id,
            channel_id="C1",
            user_id="U1",
            body="hello",
        )
        # Same message twice -> idempotency_key collapses to one event.
        second = await route_inbound_message(
            db,
            channel_config_id=cc_id,
            channel_id="C1",
            user_id="U1",
            body="hello",
        )
        assert first == second
        assert len(first) == 1


@pytest.mark.asyncio
async def test_email_inbound_trigger_matches_recipient(session_maker):
    from app.models_automations import AutomationEvent
    from app.services.triggers.email_inbound import route_inbound_email

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            ordinal=0,
        )
        await _seed_trigger(
            db,
            automation_id=autom_id,
            kind="email_inbound",
            config={
                "recipient": "robot@example.com",
                "subject_regex": "^\\[deploy\\]",
            },
        )
        await db.commit()

    async with session_maker() as db:
        match = await route_inbound_email(
            db,
            sender="alice@example.com",
            recipient="robot@example.com",
            subject="[deploy] release v2",
            body="please go",
            message_id="<abc@test>",
        )
        assert len(match) == 1

        # Mismatched recipient: no fire.
        miss = await route_inbound_email(
            db,
            sender="alice@example.com",
            recipient="other@example.com",
            subject="[deploy] release v2",
            body="please go",
            message_id="<def@test>",
        )
        assert miss == []

        # Mismatched subject regex: no fire.
        miss_subj = await route_inbound_email(
            db,
            sender="alice@example.com",
            recipient="robot@example.com",
            subject="random subject",
            body="please go",
            message_id="<ghi@test>",
        )
        assert miss_subj == []

        evt = (
            await db.execute(select(AutomationEvent).where(AutomationEvent.id == match[0]))
        ).scalar_one()
        assert evt.trigger_kind == "email_inbound"
        assert evt.payload.get("subject") == "[deploy] release v2"


@pytest.mark.asyncio
async def test_email_inbound_idempotency_uses_message_id(session_maker):
    from app.services.triggers.email_inbound import route_inbound_email

    async with session_maker() as db:
        owner_id = await seed_user(db)
        autom_id = await seed_automation(db, owner_user_id=owner_id)
        await seed_action(
            db,
            automation_id=autom_id,
            action_type="gateway.send",
            ordinal=0,
        )
        await _seed_trigger(
            db,
            automation_id=autom_id,
            kind="email_inbound",
            config={"recipient": "robot@example.com"},
        )
        await db.commit()

    async with session_maker() as db:
        first = await route_inbound_email(
            db,
            sender="alice@example.com",
            recipient="robot@example.com",
            subject="hi",
            body="hi",
            message_id="<unique-1@test>",
        )
        second = await route_inbound_email(
            db,
            sender="alice@example.com",
            recipient="robot@example.com",
            subject="hi",
            body="hi",
            message_id="<unique-1@test>",
        )
        assert first == second
        assert len(first) == 1
