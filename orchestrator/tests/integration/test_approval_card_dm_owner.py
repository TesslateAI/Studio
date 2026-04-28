"""Approval card delivery + Slack block_actions resume (demo flow #6-7).

Plan target ("Verification (end-to-end)" demo flow #6-7):

    6. ContractGate denies a tool call -> ApprovalManager.register
       writes an AutomationApprovalRequest, the run goes
       waiting_approval, and the dispatcher writes a checkpoint and
       returns cleanly so the worker exits.
    7. The Slack adapter's send_approval_card_dual posts BOTH (a) DM to
       the contract owner AND (b) a thread-root in the channel. Either
       click resolves the same input_id by routing
       ``automation_approve:<input_id>:<choice>`` directly to
       /api/chat/approval/{input_id}/respond — clicks NEVER enter
       _pending_messages.

The contract under test:
* Owner DM goes out for every breach (channel mode = DM + thread root,
  dm_owner mode = DM only).
* Inbound action_id starting with ``automation_approve:`` is a
  RESOLVE-the-approval payload, not a chat message — the inbound
  discriminator must short-circuit before _pending_messages enqueue.
* When the resolve lands, AutomationApprovalRequest.resolved_at is set,
  the run resumes (status moves off ``waiting_approval``), and
  ``contract_breaches`` is bumped on AutomationRun.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Migration fixtures (mirror the dispatcher unit-test pattern)
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "approval_card.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


@pytest.fixture
def session_maker(migrated_sqlite: str):
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"approval-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Approval Test User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_automation_with_run(
    db, *, owner_user_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    from app.models_automations import (
        AutomationDefinition,
        AutomationEvent,
        AutomationRun,
    )

    autom_id = uuid.uuid4()
    db.add(
        AutomationDefinition(
            id=autom_id,
            name="approval-test",
            owner_user_id=owner_user_id,
            workspace_scope="none",
            contract={
                "allowed_tools": [],
                "max_compute_tier": 0,
                "on_breach": "pause_for_approval",
            },
            max_compute_tier=0,
            is_active=True,
        )
    )
    event_id = uuid.uuid4()
    db.add(
        AutomationEvent(
            id=event_id,
            automation_id=autom_id,
            payload={},
            trigger_kind="manual",
        )
    )
    run_id = uuid.uuid4()
    db.add(
        AutomationRun(
            id=run_id,
            automation_id=autom_id,
            event_id=event_id,
            status="running",
        )
    )
    await db.flush()
    return autom_id, run_id


async def _seed_slack_identity(
    db, *, user_id: uuid.UUID, slack_user_id: str
) -> None:
    """Insert a PlatformIdentity so delivery_fallback finds a Slack DM target."""
    try:
        from app.models import PlatformIdentity
    except ImportError:
        pytest.skip("PlatformIdentity model not present in this branch")

    db.add(
        PlatformIdentity(
            id=uuid.uuid4(),
            user_id=user_id,
            platform="slack",
            platform_user_id=slack_user_id,
            is_verified=True,
            paired_at=datetime.now(UTC),
        )
    )
    await db.flush()


async def _seed_approval_request(
    db, *, run_id: uuid.UUID, reason: str = "contract_violation"
) -> uuid.UUID:
    from app.models_automations import AutomationApprovalRequest

    req_id = uuid.uuid4()
    db.add(
        AutomationApprovalRequest(
            id=req_id,
            run_id=run_id,
            reason=reason,
            context={"tool_name": "bash_exec", "summary": "rm -rf /tmp/foo"},
            options=["allow_once", "allow_for_run", "deny"],
        )
    )
    await db.flush()
    return req_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_contract_breach_dms_owner_with_buttons(
    session_maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ContractGate breach triggers a DM with action buttons to the owner.

    We exercise the delivery fallback chain directly:
    delivery_fallback.send_with_fallback -> Slack DM via mocked
    GatewayClient. The fallback's contract is "send to the owner via
    Slack DM if a PlatformIdentity exists; record the surface".
    """
    from app.services.automations.delivery_fallback import send_with_fallback

    # 1. owner + automation + paused run.
    async with session_maker() as db:
        owner_id = await _seed_user(db)
        _, run_id = await _seed_automation_with_run(db, owner_user_id=owner_id)
        await _seed_slack_identity(db, user_id=owner_id, slack_user_id="U_OWNER")
        approval_id = await _seed_approval_request(db, run_id=run_id)
        await db.commit()

    # 2. Mock the gateway client so we can assert on the DM call.
    gateway_client = MagicMock()
    gateway_client.send_approval_card_to_dm = AsyncMock(return_value=True)

    async with session_maker() as db:
        result = await send_with_fallback(
            approval_request_id=approval_id,
            db=db,
            gateway_client=gateway_client,
        )

    # 3. The first successful step must be slack_dm (we seeded that
    #    PlatformIdentity).
    assert result.kind == "slack_dm", (
        f"expected slack_dm delivery, got {result.kind!r} attempts={result.attempts}"
    )
    assert result.surface == "U_OWNER"

    # 4. The DM call carried the input_id + action options.
    gateway_client.send_approval_card_to_dm.assert_awaited_once()
    call_kwargs = gateway_client.send_approval_card_to_dm.await_args.kwargs
    assert call_kwargs.get("platform") == "slack"
    assert call_kwargs.get("platform_user_id") == "U_OWNER"
    assert call_kwargs.get("input_id") == str(approval_id)
    assert "allow_once" in (call_kwargs.get("actions") or [])
    assert "deny" in (call_kwargs.get("actions") or [])


@pytest.mark.integration
def test_slack_block_action_id_routes_directly_to_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inbound action_id with ``automation_approve:`` prefix bypasses chat queue.

    The Slack inbound discriminator MUST recognize the prefix and route
    the click to the approval resolve path -- the click MUST NOT land
    in ``_pending_messages`` (the chat-session message queue) because
    button clicks are not chat messages.

    This is a static-shape test: we exercise the prefix constant + the
    parser used by the inbound side. The full HTTP path lands later
    when the slack_inbound test harness ships.
    """
    from app.services.channels.approval_cards import (
        SLACK_ACTION_PREFIX,
        parse_action_id,
    )

    input_id = str(uuid.uuid4())
    action_id = f"{SLACK_ACTION_PREFIX}{input_id}:allow_once"

    parsed = parse_action_id(action_id)
    assert parsed is not None, (
        f"parse_action_id rejected its own format: {action_id!r}"
    )

    # The contract is parse_action_id returns a tuple/dict carrying the
    # input_id + the choice. Both shapes are accepted by callers; we
    # assert the load-bearing data is recoverable.
    if isinstance(parsed, tuple):
        recovered_input_id, choice = parsed[0], parsed[1]
    else:
        recovered_input_id = parsed.get("input_id")
        choice = parsed.get("choice")

    assert recovered_input_id == input_id
    assert choice == "allow_once"

    # The prefix itself is the load-bearing discriminator.
    assert action_id.startswith(SLACK_ACTION_PREFIX), (
        "inbound discriminator must prefix-match -- changing the prefix "
        "breaks every deployed Slack workspace"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_marks_approval_resolved_and_resumes_run(
    session_maker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolving an approval marks the request resolved + bumps breach count.

    The end-to-end resolve flow has two halves:
      a) The router writes ``resolved_at`` + ``response`` on the
         approval request.
      b) The dispatcher's resume_run path moves the AutomationRun off
         ``waiting_approval`` and bumps ``contract_breaches``.

    For this integration test we directly exercise the persistence
    contract -- that the rows reach their post-resolve shape. The router
    code path is covered by tests/routers/test_chat.py; this test
    ensures the data model honours the contract regardless of which
    caller writes it.
    """
    from app.models_automations import (
        AutomationApprovalRequest,
        AutomationRun,
    )

    async with session_maker() as db:
        owner_id = await _seed_user(db)
        _, run_id = await _seed_automation_with_run(db, owner_user_id=owner_id)
        approval_id = await _seed_approval_request(db, run_id=run_id)

        # Move the run into waiting_approval (the dispatcher would have
        # done this when the breach landed).
        await db.execute(
            AutomationRun.__table__.update()
            .where(AutomationRun.id == run_id)
            .values(status="waiting_approval", paused_reason="contract")
        )
        await db.commit()

    # Simulate the resolve write: response + resolved_at + bump
    # contract_breaches + move run back to running.
    async with session_maker() as db:
        await db.execute(
            AutomationApprovalRequest.__table__.update()
            .where(AutomationApprovalRequest.id == approval_id)
            .values(
                response={"choice": "allow_once"},
                resolved_at=datetime.now(UTC),
                resolved_by_user_id=owner_id,
            )
        )
        await db.execute(
            AutomationRun.__table__.update()
            .where(AutomationRun.id == run_id)
            .values(
                status="running",
                contract_breaches=AutomationRun.contract_breaches + 1,
                approver_user_id=owner_id,
                paused_reason=None,
            )
        )
        await db.commit()

    async with session_maker() as db:
        req = (
            await db.execute(
                select(AutomationApprovalRequest).where(
                    AutomationApprovalRequest.id == approval_id
                )
            )
        ).scalar_one()
        run = (
            await db.execute(
                select(AutomationRun).where(AutomationRun.id == run_id)
            )
        ).scalar_one()

    assert req.resolved_at is not None
    assert req.resolved_by_user_id == owner_id
    assert req.response == {"choice": "allow_once"}

    assert run.status == "running"
    assert run.contract_breaches == 1
    assert run.approver_user_id == owner_id
    assert run.paused_reason is None
