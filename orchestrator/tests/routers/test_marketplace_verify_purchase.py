"""
Wave 4 — install_guard re-check on the Stripe verify-purchase redirect.

``POST /api/marketplace/verify-purchase`` finalizes a paid agent install
after Stripe's redirect. Between checkout creation and this call the
source's trust state can drift (admin marks the source ``is_active=False``,
trust_level drops, hub_id changes). The endpoint MUST re-run
``install_guard`` and, on a deny, void the purchase row, log an audit
entry, and return 200 with a structured failure body so Stripe doesn't
retry the redirect.

These tests stub Stripe and the ``current_active_user`` dependency so we
can exercise the gate in isolation; the focus is the void/return shape.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5433/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DEPLOYMENT_MODE", "docker")
os.environ.setdefault("LITELLM_API_BASE", "http://localhost:4000/v1")
os.environ.setdefault("LITELLM_MASTER_KEY", "test-key")

pytestmark = pytest.mark.asyncio


def _user(default_team_id: uuid.UUID | None = None) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_active = True
    u.is_superuser = False
    u.is_verified = True
    u.default_team_id = default_team_id
    u.stripe_customer_id = "cus_test_wave4"
    return u


def _agent(*, source_id: uuid.UUID | None = None, slug: str = "wave4-paid") -> MagicMock:
    a = MagicMock()
    a.id = uuid.uuid4()
    a.slug = slug
    a.name = "Wave4 Paid Agent"
    a.item_type = "agent"
    a.pricing_type = "paid"
    a.is_active = True
    a.source_id = source_id
    a.model = "gpt-4"
    a.downloads = 0
    return a


def _source_inactive() -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.handle = "drifted-test-hub"
    s.trust_level = "official"  # was trusted at checkout time...
    s.scope = "system"
    s.is_active = False  # ...but admin disabled it before fulfillment
    s.user_id = None
    s.team_id = None
    s.display_name = "Drifted Test Hub"
    return s


def _scalar(value: Any) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalar_one(value: Any) -> MagicMock:
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _stripe_session(*, customer: str, agent_id: uuid.UUID) -> MagicMock:
    s = MagicMock()
    s.payment_status = "paid"
    s.customer = customer
    s.subscription = None
    s.payment_intent = "pi_test_wave4"
    s.metadata = {"agent_id": str(agent_id)}
    return s


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
async def client_factory(mock_db):
    from app.database import get_db
    from app.main import app
    from app.users import current_active_user

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    async def _make(user):
        app.dependency_overrides[current_active_user] = lambda: user
        # Bearer header bypasses the CSRF middleware (stateless auth path);
        # the dependency override above wins for actual authentication.
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-bypass"},
        )

    yield _make
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------


class TestVerifyPurchaseTrustReCheck:
    async def test_inactive_source_voids_purchase_and_returns_trust_failure(
        self, client_factory, mock_db
    ):
        """
        A source flipped to ``is_active=False`` between checkout creation and
        Stripe's redirect MUST cause the verify call to:

        * skip creating a new ``UserPurchasedAgent`` row,
        * deactivate any pre-existing row (``is_active=False`` + ``expires_at``),
        * return 200 with ``install_blocked.reason='source_inactive'`` so the
          client surfaces the trust failure and Stripe stops retrying.
        """
        from app.routers import marketplace as marketplace_router

        # Wipe the in-memory source cache so our fresh "inactive" row wins
        # over anything a sibling test may have populated.
        marketplace_router._SOURCE_ID_CACHE.clear()
        marketplace_router._SOURCE_HANDLE_CACHE.clear()

        user = _user()
        source = _source_inactive()
        agent = _agent(source_id=source.id)

        # Pre-existing active purchase row (e.g. carried over from a prior
        # checkout). The void path should flip is_active to False.
        existing_purchase = MagicMock()
        existing_purchase.id = uuid.uuid4()
        existing_purchase.user_id = user.id
        existing_purchase.agent_id = agent.id
        existing_purchase.is_active = True
        existing_purchase.expires_at = None

        # db.execute call order in verify_agent_purchase:
        # 1. select(User).where(User.id == current_user.id)        -> scalar_one(user)
        # 2. select(MarketplaceAgent).where(...)                   -> scalar(agent)
        # 3. _load_source -> select(MarketplaceSource)             -> scalar(source)
        # 4. _void helper -> select(UserPurchasedAgent).where(...) -> scalar(existing)
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one(user),
                _scalar(agent),
                _scalar(source),
                _scalar(existing_purchase),
            ]
        )

        stripe_session = _stripe_session(
            customer=user.stripe_customer_id, agent_id=agent.id
        )

        # Patch Stripe SDK + service singleton so we don't hit the network.
        stripe_service_mock = MagicMock()
        stripe_service_mock.stripe = MagicMock()  # truthy → "configured"

        with (
            patch(
                "app.services.stripe_service.stripe_service",
                stripe_service_mock,
            ),
            patch("stripe.checkout.Session.retrieve", return_value=stripe_session),
        ):
            client = await client_factory(user)
            async with client as ac:
                resp = await ac.post(
                    "/api/marketplace/verify-purchase",
                    json={
                        "session_id": "cs_test_wave4_drift",
                        "agent_slug": agent.slug,
                    },
                )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is False
        assert body["agent_id"] == str(agent.id)
        assert body["refund_status"] == "pending"
        # The void path MUST surface the trust failure shape so the client UI
        # can render "your source dropped trust, refund coming" without
        # treating this as a generic 500.
        blocked = body.get("install_blocked")
        assert isinstance(blocked, dict), body
        assert blocked.get("error") == "install_blocked"
        assert blocked.get("reason") == "source_inactive"
        assert blocked.get("kind") == "agent"

        # Existing purchase row was voided in place.
        assert existing_purchase.is_active is False
        assert isinstance(existing_purchase.expires_at, datetime)
        assert existing_purchase.expires_at.tzinfo is not None
        # And NO new purchase row was inserted.
        mock_db.add.assert_not_called()
        # Cleanup the source cache so we don't pollute later tests.
        marketplace_router._SOURCE_ID_CACHE.clear()
        marketplace_router._SOURCE_HANDLE_CACHE.clear()
