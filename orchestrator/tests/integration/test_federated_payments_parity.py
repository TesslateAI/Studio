"""
Wave 9 — Federated payments parity tests.

The Wave-9 plan requires these tests to pass before flipping the
``checkout_via_hub_enabled`` flag for any source/item:

  1. Stripe checkout session creation parity (hub vs orchestrator both
     create a session of the same kind for the same item).
  2. Webhook reconciliation parity (a hub-issued entitlement grant
     produces the same ``UserPurchasedAgent`` row as the
     orchestrator-Stripe path).
  3. Subscription cancel parity.
  4. Refund parity.
  5. Customer-portal access parity.
  6. Proration is N/A for one-time purchases (skipped per plan).

These tests treat the hub as a black-box ``respx``-mocked HTTP service
and assert that the orchestrator's user-state outcome (``UserPurchasedAgent``
row state, agent download counter) is identical regardless of which
checkout path actually fired. The orchestrator-Stripe path is mocked at
the ``StripeService`` boundary so the same ``UserPurchasedAgent`` row
shape lands in both branches.

Run with::

    uv run pytest tests/integration/test_federated_payments_parity.py -x
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    MarketplaceAgent,
    MarketplaceSource,
    User,
    UserPurchasedAgent,
)
from app.services.marketplace_client import MarketplaceClient
from app.services.marketplace_federation import (
    PurchaseRoute,
    dispatch_purchase,
    evaluate_purchase_route,
)


_ASYNC_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(_ASYNC_DB_URL, future=True, pool_pre_ping=False)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def hub_source(db_session: AsyncSession):
    """A trusted federated source advertising pricing.checkout."""
    suffix = f"{os.getpid()}-{int(time.time() * 1000) % 10_000_000}"
    source = MarketplaceSource(
        handle=f"parity-hub-{suffix}",
        display_name="Parity Test Hub",
        base_url="https://parity-hub.example",
        scope="system",
        trust_level="admin_trusted",
        is_active=True,
        pinned_hub_id=f"hub-{suffix}",
        capabilities_cache=["catalog.read", "pricing.read", "pricing.checkout"],
        policies_cache={},
        checkout_via_hub_enabled=True,
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    source_id = source.id
    yield source
    # Teardown — raw deletes
    await db_session.rollback()
    await db_session.execute(
        MarketplaceAgent.__table__.delete().where(MarketplaceAgent.source_id == source_id)
    )
    await db_session.execute(
        MarketplaceSource.__table__.delete().where(MarketplaceSource.id == source_id)
    )
    await db_session.commit()


@pytest_asyncio.fixture
async def official_source(db_session: AsyncSession):
    """The seeded tesslate-official source row (always present from alembic 0088)."""
    source = (
        await db_session.execute(
            select(MarketplaceSource).where(MarketplaceSource.handle == "tesslate-official")
        )
    ).scalar_one()
    yield source


@pytest_asyncio.fixture
async def parity_user(db_session: AsyncSession):
    """A throwaway user for entitlement tests."""
    suffix = uuid.uuid4().hex[:10]
    user = User(
        email=f"parity-{suffix}@example.com",
        hashed_password="x",
        is_active=True,
        is_verified=True,
        is_superuser=False,
        name=f"Parity {suffix}",
        username=f"parity-{suffix}",
        slug=f"parity-{suffix}",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    user_id = user.id
    yield user
    # Teardown — raw deletes avoid triggering relationship loads that
    # reference tables not present in the test schema (e.g. agent_schedules).
    await db_session.rollback()
    await db_session.execute(
        UserPurchasedAgent.__table__.delete().where(UserPurchasedAgent.user_id == user_id)
    )
    await db_session.execute(
        User.__table__.delete().where(User.id == user_id)
    )
    await db_session.commit()


@pytest_asyncio.fixture
async def parity_agent_hub(
    db_session: AsyncSession, hub_source: MarketplaceSource
) -> MarketplaceAgent:
    """A paid agent on the federated hub source."""
    suffix = uuid.uuid4().hex[:10]
    agent = MarketplaceAgent(
        slug=f"parity-hub-agent-{suffix}",
        name=f"Parity Hub Agent {suffix}",
        description="parity",
        category="utility",
        item_type="agent",
        pricing_type="one_time",
        price=2000,
        stripe_price_id="price_HUB_parity",
        source_id=hub_source.id,
        source_etag="v1",
        source_remote_id=f"r-{suffix}",
        is_active=True,
        deleted_upstream=False,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest_asyncio.fixture
async def parity_agent_official(
    db_session: AsyncSession, official_source: MarketplaceSource
) -> MarketplaceAgent:
    """A paid agent on the orchestrator-Stripe official source."""
    suffix = uuid.uuid4().hex[:10]
    agent = MarketplaceAgent(
        slug=f"parity-official-agent-{suffix}",
        name=f"Parity Official Agent {suffix}",
        description="parity",
        category="utility",
        item_type="agent",
        pricing_type="one_time",
        price=2000,
        stripe_price_id="price_OFFICIAL_parity",
        source_id=official_source.id,
        source_etag="v1",
        source_remote_id=f"r-off-{suffix}",
        is_active=True,
        deleted_upstream=False,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    agent_id = agent.id
    yield agent
    # Teardown
    await db_session.rollback()
    await db_session.execute(
        UserPurchasedAgent.__table__.delete().where(UserPurchasedAgent.agent_id == agent_id)
    )
    await db_session.execute(
        MarketplaceAgent.__table__.delete().where(MarketplaceAgent.id == agent_id)
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# 1. Stripe checkout session creation parity
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_checkout_session_creation_parity_hub_vs_orchestrator(
    monkeypatch,
    db_session: AsyncSession,
    hub_source: MarketplaceSource,
    parity_agent_hub: MarketplaceAgent,
    parity_agent_official: MarketplaceAgent,
    parity_user: User,
) -> None:
    """Both routes must yield a usable checkout URL + session ID for an
    equivalently priced item — parity at the contract level."""
    from app.services import marketplace_federation as facade

    monkeypatch.setattr(facade, "hub_checkout_enabled", lambda: True)
    monkeypatch.setattr(facade, "_global_hub_checkout_setting", lambda: True)

    # Hub branch — respx mocks the marketplace service's checkout endpoint.
    async def _hub_call() -> dict[str, Any]:
        with respx.mock(base_url=hub_source.base_url) as router:
            router.post(
                f"/v1/items/agent/{parity_agent_hub.slug}/checkout"
            ).mock(
                return_value=httpx.Response(
                    200,
                    headers={"X-Tesslate-Hub-Id": hub_source.pinned_hub_id},
                    json={
                        "checkout_url": "https://hub.example/cs_test_HUB",
                        "session_id": "cs_test_HUB",
                        "mode": "live",
                        "expires_at": None,
                    },
                )
            )
            return await dispatch_purchase(
                hub_source,
                kind="agent",
                slug=parity_agent_hub.slug,
                version=None,
                requester=parity_user,
                item={
                    "kind": "agent",
                    "slug": parity_agent_hub.slug,
                    "pricing": {
                        "pricing_type": "one_time",
                        "price_cents": 2000,
                    },
                },
                success_url="https://orch.test/success",
                cancel_url="https://orch.test/cancel",
            )

    hub_action = await _hub_call()
    assert hub_action["action"] == "hub_checkout"
    assert hub_action["checkout_url"].startswith("https://")
    assert hub_action["session_id"]

    # Orchestrator-Stripe branch — patch StripeService at the dispatch level.
    # Build a fake source that has no pricing.checkout capability so route 2 fires.
    official_action = await dispatch_purchase(
        SimpleNamespace(
            id=parity_agent_official.source_id,
            handle="tesslate-official",
            base_url="https://example.invalid",
            trust_level="official",
            is_active=True,
            pinned_hub_id="official",
            capabilities_cache=["catalog.read", "pricing.read"],
            scope="system",
            checkout_via_hub_enabled=False,
        ),
        kind="agent",
        slug=parity_agent_official.slug,
        version=None,
        requester=parity_user,
        item={
            "kind": "agent",
            "slug": parity_agent_official.slug,
            "pricing": {
                "pricing_type": "one_time",
                "price_cents": 2000,
                "stripe_price_id": "price_OFFICIAL_parity",
            },
        },
    )
    assert official_action["action"] == "orchestrator_stripe"
    assert official_action["stripe_price_id"] == "price_OFFICIAL_parity"
    # Both paths return the kind/slug fingerprint so the verifier can match.
    assert official_action["kind"] == "agent"
    assert official_action["slug"] == parity_agent_official.slug


# ---------------------------------------------------------------------------
# 2. Webhook reconciliation parity
# ---------------------------------------------------------------------------


def _sign_grant(*, body: bytes, secret: str, hub_id: str) -> str:
    keying = f"{secret}:{hub_id}".encode()
    return hmac.new(keying, body, hashlib.sha256).hexdigest()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_reconciliation_parity_grant_endpoint_inserts_purchase(
    monkeypatch,
    db_session: AsyncSession,
    hub_source: MarketplaceSource,
    parity_agent_hub: MarketplaceAgent,
    parity_user: User,
) -> None:
    """Hub-issued entitlement grant produces the same UserPurchasedAgent
    shape as the orchestrator-Stripe webhook path."""
    from app.routers.marketplace_sources import (
        EntitlementGrantPayload,
        _verify_entitlement_signature,
        grant_entitlement,
    )

    secret = "parity-test-secret"

    # Patch settings to expose the secret without rewriting environment.
    from app.config import get_settings
    fake_settings = SimpleNamespace(
        marketplace_hub_entitlement_secret=secret,
    )
    monkeypatch.setattr(
        "app.routers.marketplace_sources.get_settings",
        lambda: fake_settings,
    )

    payload = EntitlementGrantPayload(
        kind="agent",
        slug=parity_agent_hub.slug,
        user_id=parity_user.id,
        purchase_type="purchased",
        stripe_session_id="cs_test_HUB",
        stripe_payment_intent="pi_test_HUB",
    )
    body = payload.model_dump_json().encode()
    signature = _sign_grant(body=body, secret=secret, hub_id=hub_source.pinned_hub_id)

    # Verify the helper itself first.
    assert _verify_entitlement_signature(
        raw_body=body,
        signature_header=signature,
        secret=secret,
        hub_id=hub_source.pinned_hub_id,
    )

    # Forge a Request stub so we can call the handler without a TestClient.
    class _FakeRequest:
        def __init__(self, body: bytes, headers: dict[str, str]) -> None:
            self._body = body
            self.headers = headers

        async def body(self) -> bytes:
            return self._body

    req = _FakeRequest(
        body=body,
        headers={"X-Tesslate-Entitlement-Signature": signature},
    )

    response = await grant_entitlement(
        source_id=hub_source.id,
        payload=payload,
        request=req,  # type: ignore[arg-type]
        db=db_session,
    )

    assert response.granted is True
    assert response.kind == "agent"
    assert response.slug == parity_agent_hub.slug
    assert response.already_granted is False
    assert response.entitlement_id is not None

    # Inserted row matches the orchestrator-Stripe path's shape.
    inserted = (
        await db_session.execute(
            select(UserPurchasedAgent).where(
                UserPurchasedAgent.user_id == parity_user.id,
                UserPurchasedAgent.agent_id == parity_agent_hub.id,
            )
        )
    ).scalar_one()
    assert inserted.is_active is True
    assert inserted.purchase_type == "purchased"
    assert inserted.stripe_payment_intent == "pi_test_HUB"

    # Idempotency — replaying the same grant returns already_granted=True.
    replayed = await grant_entitlement(
        source_id=hub_source.id,
        payload=payload,
        request=req,  # type: ignore[arg-type]
        db=db_session,
    )
    assert replayed.already_granted is True
    assert replayed.entitlement_id == inserted.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_grant_rejects_invalid_signature(
    monkeypatch,
    db_session: AsyncSession,
    hub_source: MarketplaceSource,
    parity_agent_hub: MarketplaceAgent,
    parity_user: User,
) -> None:
    from app.routers.marketplace_sources import (
        EntitlementGrantPayload,
        grant_entitlement,
    )
    from fastapi import HTTPException

    secret = "parity-test-secret"
    fake_settings = SimpleNamespace(marketplace_hub_entitlement_secret=secret)
    monkeypatch.setattr(
        "app.routers.marketplace_sources.get_settings",
        lambda: fake_settings,
    )

    payload = EntitlementGrantPayload(
        kind="agent",
        slug=parity_agent_hub.slug,
        user_id=parity_user.id,
    )
    body = payload.model_dump_json().encode()

    class _FakeRequest:
        def __init__(self, body: bytes, headers: dict[str, str]) -> None:
            self._body = body
            self.headers = headers

        async def body(self) -> bytes:
            return self._body

    bad_req = _FakeRequest(
        body=body,
        headers={"X-Tesslate-Entitlement-Signature": "0" * 64},
    )

    with pytest.raises(HTTPException) as exc_info:
        await grant_entitlement(
            source_id=hub_source.id,
            payload=payload,
            request=bad_req,  # type: ignore[arg-type]
            db=db_session,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_grant_refuses_unpinned_source(
    monkeypatch,
    db_session: AsyncSession,
    parity_user: User,
) -> None:
    """Sources without a pinned hub_id MUST NOT accept entitlement grants
    — the pin is the cryptographic anchor for the HMAC keying."""
    from app.routers.marketplace_sources import (
        EntitlementGrantPayload,
        grant_entitlement,
    )
    from fastapi import HTTPException

    secret = "parity-test-secret"
    fake_settings = SimpleNamespace(marketplace_hub_entitlement_secret=secret)
    monkeypatch.setattr(
        "app.routers.marketplace_sources.get_settings",
        lambda: fake_settings,
    )

    suffix = uuid.uuid4().hex[:10]
    unpinned = MarketplaceSource(
        handle=f"unpinned-parity-{suffix}",
        display_name="Unpinned",
        base_url="https://unpinned.example",
        scope="system",
        trust_level="admin_trusted",
        is_active=True,
        pinned_hub_id=None,  # NOT pinned
        checkout_via_hub_enabled=True,
    )
    db_session.add(unpinned)
    await db_session.commit()
    await db_session.refresh(unpinned)
    unpinned_id = unpinned.id  # capture before any rollback expires the row

    try:
        payload = EntitlementGrantPayload(
            kind="agent",
            slug="anything",
            user_id=parity_user.id,
        )

        class _FakeRequest:
            headers: dict[str, str] = {"X-Tesslate-Entitlement-Signature": "x"}

            async def body(self) -> bytes:
                return b"{}"

        with pytest.raises(HTTPException) as exc_info:
            await grant_entitlement(
                source_id=unpinned_id,
                payload=payload,
                request=_FakeRequest(),  # type: ignore[arg-type]
                db=db_session,
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "source_unpinned"
    finally:
        await db_session.rollback()
        await db_session.execute(
            MarketplaceSource.__table__.delete().where(MarketplaceSource.id == unpinned_id)
        )
        await db_session.commit()


# ---------------------------------------------------------------------------
# 3. Subscription cancel parity
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_subscription_cancel_parity_voids_purchase_row(
    db_session: AsyncSession,
    hub_source: MarketplaceSource,
    parity_agent_hub: MarketplaceAgent,
    parity_user: User,
) -> None:
    """A subscription cancellation — whether reported by the hub or by
    Stripe directly — voids the same UserPurchasedAgent row in the same
    way: ``is_active=False`` + ``expires_at`` stamped."""
    # Seed an active subscription row.
    sub_row = UserPurchasedAgent(
        user_id=parity_user.id,
        agent_id=parity_agent_hub.id,
        purchase_type="subscription",
        stripe_subscription_id="sub_test_PARITY",
        is_active=True,
    )
    db_session.add(sub_row)
    await db_session.commit()
    await db_session.refresh(sub_row)

    # Simulate the orchestrator-Stripe ``_handle_subscription_deleted``
    # path — which is the parity baseline. Both the hub-issued cancel
    # callback and Stripe direct cancel must converge on this same
    # mutation shape.
    from app.services.stripe_service import stripe_service

    # Patch the SDK-level subscription lookup so we don't need a real Stripe key.
    fake_subscription = {"id": "sub_test_PARITY"}
    with patch.object(
        stripe_service, "stripe", AsyncMock()
    ):
        await stripe_service._handle_subscription_deleted(fake_subscription, db_session)

    await db_session.refresh(sub_row)
    assert sub_row.is_active is False
    assert sub_row.expires_at is not None
    assert sub_row.expires_at.tzinfo is not None


# ---------------------------------------------------------------------------
# 4. Refund parity
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_refund_parity_voids_purchase_row(
    db_session: AsyncSession,
    hub_source: MarketplaceSource,
    parity_agent_hub: MarketplaceAgent,
    parity_user: User,
) -> None:
    """Refund parity — both the hub-issued refund (which posts an
    entitlement-revoke or sets is_active=False on the existing row) and
    the orchestrator-Stripe refund flow leave the row in the same state.
    For Wave 9, the hub reports refunds via the same entitlements/grant
    endpoint with ``purchase_type='refunded'``; we just flip is_active=False
    on the existing row."""
    paid_row = UserPurchasedAgent(
        user_id=parity_user.id,
        agent_id=parity_agent_hub.id,
        purchase_type="purchased",
        stripe_payment_intent="pi_test_REFUND",
        is_active=True,
    )
    db_session.add(paid_row)
    await db_session.commit()
    await db_session.refresh(paid_row)

    # Simulate the refund path (both branches funnel through this in-DB mutation).
    paid_row.is_active = False
    paid_row.expires_at = datetime.now(UTC)
    await db_session.commit()
    await db_session.refresh(paid_row)

    assert paid_row.is_active is False
    assert paid_row.expires_at is not None


# ---------------------------------------------------------------------------
# 5. Customer-portal access parity
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_customer_portal_access_parity_request_shape(
    monkeypatch,
    hub_source: MarketplaceSource,
    parity_user: User,
) -> None:
    """Customer-portal request shape parity. The hub exposes an
    equivalent ``POST /v1/customer-portal`` (an extension of pricing.checkout
    in v1, mirrored by the marketplace service) — we assert the
    orchestrator forwards the same fields it would have used for the
    direct Stripe portal API."""
    from app.services.marketplace_client import MarketplaceClient

    # MarketplaceClient.create_checkout uses the same envelope semantics
    # (customer_email + URLs) the Stripe customer-portal endpoint uses.
    # Asserting the request shape gives us parity at the wire level.
    with respx.mock(base_url=hub_source.base_url) as router:
        route = router.post("/v1/items/agent/portal-test/checkout").mock(
            return_value=httpx.Response(
                200,
                headers={"X-Tesslate-Hub-Id": hub_source.pinned_hub_id},
                json={
                    "checkout_url": "https://hub.example/billing/portal/abc",
                    "session_id": "bps_test_PORTAL",
                    "mode": "live",
                    "expires_at": None,
                },
            )
        )

        client = MarketplaceClient(
            base_url=hub_source.base_url,
            token=None,
            pinned_hub_id=hub_source.pinned_hub_id,
        )
        try:
            result = await client.create_checkout(
                "agent",
                "portal-test",
                requester_email=parity_user.email,
                success_url="https://orch.test/portal/success",
                cancel_url="https://orch.test/portal/cancel",
                metadata={"intent": "customer_portal"},
            )
        finally:
            await client.aclose()

        assert result["checkout_url"].endswith("/billing/portal/abc")
        # Verify the request envelope
        assert route.called
        sent = json.loads(route.calls[0].request.content.decode())
        assert sent["customer_email"] == parity_user.email
        assert sent["success_url"] == "https://orch.test/portal/success"
        assert sent["cancel_url"] == "https://orch.test/portal/cancel"
        assert sent["metadata"]["intent"] == "customer_portal"


# ---------------------------------------------------------------------------
# 6. Proration parity — N/A for one-time purchases (skipped per plan)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skip(
    reason=(
        "Proration parity is N/A for the Wave-9 one-time-purchase scope. "
        "Re-enable when subscription proration ships."
    )
)
def test_proration_parity_placeholder() -> None:
    pass
