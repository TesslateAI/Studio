"""Unit tests for the approval-delivery fallback chain.

Uses an in-memory SQLite session + a stub gateway client / email
service so we can drive the chain without standing up Slack/Telegram
adapters.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import PlatformIdentity
from app.models_auth import User
from app.models_automations import (
    AutomationApprovalRequest,
    AutomationDefinition,
    AutomationRun,
)
from app.services.automations.delivery_fallback import send_with_fallback


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass
class StubGatewayClient:
    """Records every send call. Configurable per-platform success."""

    slack_ok: bool = True
    telegram_ok: bool = True
    raise_for: str | None = None
    calls: list[dict] = None

    def __post_init__(self) -> None:
        self.calls = []

    async def send_approval_card_to_dm(
        self,
        *,
        platform: str,
        platform_user_id: str,
        input_id: str,
        automation_id: str,
        tool_name: str,
        summary: str,
        actions: list[str],
    ) -> bool:
        self.calls.append(
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "input_id": input_id,
            }
        )
        if self.raise_for == platform:
            raise RuntimeError(f"forced failure for {platform}")
        if platform == "slack":
            return self.slack_ok
        if platform == "telegram":
            return self.telegram_ok
        return False


class StubEmailService:
    """Captures email send calls; ``is_configured`` controls whether the
    SMTP send is even attempted."""

    def __init__(self, *, configured: bool = True, raise_on_send: bool = False):
        self.is_configured = configured
        self.raise_on_send = raise_on_send
        self.sent: list[tuple[str, str, str, str]] = []

    async def _send(self, to_email: str, subject: str, plain: str, html: str) -> None:
        if self.raise_on_send:
            raise RuntimeError("smtp explode")
        self.sent.append((to_email, subject, plain, html))


# ---------------------------------------------------------------------------
# Fixtures — ephemeral SQLite session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed(
    db: AsyncSession,
    *,
    paired_slack: bool = False,
    paired_telegram: bool = False,
    user_email: str | None = "owner@example.com",
):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        name="Test Owner",
        username=f"test-owner-{suffix}",
        slug=f"test-owner-{suffix}",
        handle=f"test-owner-{suffix}",
        email=user_email or "noemail@example.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    if user_email is None:
        user.email = ""  # type: ignore[assignment]
    db.add(user)

    automation = AutomationDefinition(
        id=uuid.uuid4(),
        name="standup",
        owner_user_id=user.id,
        contract={"max_spend_per_run_usd": 1.0},
        is_active=True,
    )
    db.add(automation)

    run = AutomationRun(
        id=uuid.uuid4(),
        automation_id=automation.id,
        status="waiting_approval",
    )
    db.add(run)

    request = AutomationApprovalRequest(
        id=uuid.uuid4(),
        run_id=run.id,
        reason="contract_violation",
        context={"tool_name": "bash_exec", "summary": "Run a thing"},
        options=["allow_once", "deny"],
    )
    db.add(request)

    if paired_slack:
        db.add(
            PlatformIdentity(
                id=uuid.uuid4(),
                user_id=user.id,
                platform="slack",
                platform_user_id="UPAIRED",
                is_verified=True,
            )
        )
    if paired_telegram:
        db.add(
            PlatformIdentity(
                id=uuid.uuid4(),
                user_id=user.id,
                platform="telegram",
                platform_user_id="888777",
                is_verified=True,
            )
        )

    await db.commit()
    return request, run, automation, user


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slack_dm_wins_when_paired(db):
    request, *_ = await _seed(db, paired_slack=True, paired_telegram=True)
    client = StubGatewayClient(slack_ok=True)

    result = await send_with_fallback(request.id, db, client)

    assert result.kind == "slack_dm"
    assert result.surface == "UPAIRED"
    assert client.calls and client.calls[0]["platform"] == "slack"
    # Telegram NOT called once Slack succeeds.
    assert all(c["platform"] != "telegram" for c in client.calls)
    # Audit row written.
    await db.refresh(request)
    assert request.delivered_to and request.delivered_to[0]["kind"] == "slack_dm"


@pytest.mark.asyncio
async def test_telegram_dm_when_slack_fails(db):
    request, *_ = await _seed(db, paired_slack=True, paired_telegram=True)
    client = StubGatewayClient(slack_ok=False, telegram_ok=True)

    result = await send_with_fallback(request.id, db, client)

    assert result.kind == "telegram_dm"
    assert result.surface == "888777"
    assert {c["platform"] for c in client.calls} == {"slack", "telegram"}


@pytest.mark.asyncio
async def test_email_when_no_paired_identities(db):
    request, *_ = await _seed(
        db, paired_slack=False, paired_telegram=False
    )
    email = StubEmailService(configured=True)

    result = await send_with_fallback(
        request.id, db, gateway_client=None, email_service=email
    )

    assert result.kind == "email"
    assert result.surface == "owner@example.com"
    assert len(email.sent) == 1
    to, subject, plain, html = email.sent[0]
    assert to == "owner@example.com"
    assert "Approval needed" in subject
    assert str(request.id) in plain
    await db.refresh(request)
    assert request.delivered_to[-1]["kind"] == "email"


@pytest.mark.asyncio
async def test_web_only_when_no_email(db):
    request, *_ = await _seed(db, user_email=None)

    result = await send_with_fallback(request.id, db, gateway_client=None)

    assert result.kind == "web_only"
    await db.refresh(request)
    assert request.delivered_to[-1]["kind"] == "web_only"


@pytest.mark.asyncio
async def test_slack_exception_falls_through(db):
    request, *_ = await _seed(db, paired_slack=True, paired_telegram=True)
    client = StubGatewayClient(raise_for="slack", telegram_ok=True)

    result = await send_with_fallback(request.id, db, client)

    assert result.kind == "telegram_dm"
    # Slack attempt must be recorded as failed in the result.attempts trail.
    slack_attempt = next(a for a in result.attempts if a["step"] == "slack_dm")
    assert slack_attempt["ok"] is False


@pytest.mark.asyncio
async def test_missing_request_returns_failed(db):
    result = await send_with_fallback(uuid.uuid4(), db, None)
    assert result.kind == "failed"
    assert result.surface == "approval_request_missing"
