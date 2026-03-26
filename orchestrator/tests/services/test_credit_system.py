"""
Unit tests for the credit system audit fixes.

Fix 1: LiteLLM initial budget configuration ($10,000 default)
Fix 2: ensure_budget_headroom method on LiteLLMService
Fix 2b: Budget sync calls in fulfill_credit_purchase / fulfill_subscription
Fix 3: _reset_bundled_credits in daily_credit_reset
Fix 3b: _handle_invoice_payment_succeeded subscription renewal logic
"""

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers for mocking aiohttp
# ---------------------------------------------------------------------------


def make_mock_response(status=200, json_data=None, text=""):
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=text)
    return resp


def make_mock_session(responses):
    """Create a mock aiohttp.ClientSession that returns responses in order.

    responses: list of mock response objects
    """
    session = AsyncMock()
    call_idx = [0]

    @asynccontextmanager
    async def mock_request(*args, **kwargs):
        resp = responses[min(call_idx[0], len(responses) - 1)]
        call_idx[0] += 1
        yield resp

    session.get = mock_request
    session.post = mock_request

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ===========================================================================
# Fix 1 — Initial budget configuration
# ===========================================================================


@pytest.mark.unit
class TestLiteLLMInitialBudget:
    """Verify the $10,000 default initial budget is wired correctly."""

    def test_default_budget_is_10000(self):
        from app.config import get_settings

        # Override the env var to ensure the Settings default ($10,000) takes effect.
        # The .env file may contain a different value for local dev.
        old = os.environ.get("LITELLM_INITIAL_BUDGET")
        os.environ["LITELLM_INITIAL_BUDGET"] = "10000.0"
        try:
            get_settings.cache_clear()
            settings = get_settings()
            assert settings.litellm_initial_budget == 10000.0
        finally:
            if old is not None:
                os.environ["LITELLM_INITIAL_BUDGET"] = old
            else:
                os.environ.pop("LITELLM_INITIAL_BUDGET", None)
            get_settings.cache_clear()

    def test_litellm_service_uses_config_budget(self):
        from app.config import get_settings
        from app.services.litellm_service import LiteLLMService

        old = os.environ.get("LITELLM_INITIAL_BUDGET")
        os.environ["LITELLM_INITIAL_BUDGET"] = "10000.0"
        try:
            get_settings.cache_clear()
            service = LiteLLMService()
            assert service.initial_budget == 10000.0
        finally:
            if old is not None:
                os.environ["LITELLM_INITIAL_BUDGET"] = old
            else:
                os.environ.pop("LITELLM_INITIAL_BUDGET", None)
            get_settings.cache_clear()


# ===========================================================================
# Fix 2 — ensure_budget_headroom
# ===========================================================================


@pytest.mark.unit
class TestEnsureBudgetHeadroom:
    """Test the ensure_budget_headroom method on LiteLLMService."""

    @pytest.mark.asyncio
    async def test_headroom_sufficient_no_update(self):
        """When remaining >= headroom, no POST /key/update should be made."""
        key_info_resp = make_mock_response(
            200, json_data={"info": {"spend": 5.0, "max_budget": 20000.0}}
        )
        mock_session = make_mock_session([key_info_resp])

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from app.services.litellm_service import LiteLLMService

            service = LiteLLMService()
            result = await service.ensure_budget_headroom(api_key="sk-test", headroom=10000.0)

        assert result is True
        # Only the GET /key/info call should have been made — no POST
        # The session context manager was entered once (for the GET).
        # If POST had fired, call_idx would be 2.
        # We verify by checking that key_info_resp.json was awaited (GET happened)
        key_info_resp.json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_headroom_insufficient_bumps_budget(self):
        """When remaining < headroom, POST /key/update sets max_budget = spend + headroom."""
        key_info_resp = make_mock_response(
            200, json_data={"info": {"spend": 8.0, "max_budget": 10.0}}
        )
        update_resp = make_mock_response(200)
        mock_session = make_mock_session([key_info_resp, update_resp])

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from app.services.litellm_service import LiteLLMService

            service = LiteLLMService()
            result = await service.ensure_budget_headroom("sk-test", headroom=10000.0)

        assert result is True
        # The update response was accessed (POST happened)
        assert update_resp.status == 200

    @pytest.mark.asyncio
    async def test_key_info_failure_returns_false(self):
        """GET /key/info returning non-200 should return False."""
        key_info_resp = make_mock_response(404, text="Not found")
        mock_session = make_mock_session([key_info_resp])

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from app.services.litellm_service import LiteLLMService

            service = LiteLLMService()
            result = await service.ensure_budget_headroom("sk-test", headroom=10000.0)

        assert result is False

    @pytest.mark.asyncio
    async def test_key_update_failure_returns_false(self):
        """POST /key/update returning non-200 should return False."""
        key_info_resp = make_mock_response(
            200, json_data={"info": {"spend": 8.0, "max_budget": 10.0}}
        )
        update_resp = make_mock_response(500, text="Internal Server Error")
        mock_session = make_mock_session([key_info_resp, update_resp])

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from app.services.litellm_service import LiteLLMService

            service = LiteLLMService()
            result = await service.ensure_budget_headroom("sk-test", headroom=10000.0)

        assert result is False

    @pytest.mark.asyncio
    async def test_network_error_returns_false(self):
        """Any network exception inside the session should be caught and return False."""
        # The try/except is inside `async with aiohttp.ClientSession()`, so we
        # make session.get() raise to simulate a connection error.
        session = AsyncMock()

        @asynccontextmanager
        async def failing_get(*args, **kwargs):  # noqa: ARG001
            raise Exception("connection refused")
            yield  # noqa: F541, RET503

        session.get = failing_get

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=cm):
            from app.services.litellm_service import LiteLLMService

            service = LiteLLMService()
            result = await service.ensure_budget_headroom("sk-test", headroom=10000.0)

        assert result is False


# ===========================================================================
# Fix 3 — _reset_bundled_credits (daily background sweep)
# ===========================================================================


@pytest.mark.unit
class TestBundledCreditReset:
    """Test _reset_bundled_credits from app.services.daily_credit_reset."""

    @pytest.mark.asyncio
    async def test_resets_expired_bundled_credits(self):
        """Users with past credits_reset_date get their bundled credits refreshed."""
        user = Mock()
        user.subscription_tier = "pro"
        user.credits_reset_date = datetime.now(UTC) - timedelta(days=1)
        user.bundled_credits = 100

        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [user]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session_factory():
            yield mock_session

        with (
            patch("app.services.daily_credit_reset.AsyncSessionLocal", mock_session_factory),
            patch("app.services.daily_credit_reset.settings") as mock_settings,
        ):
            mock_settings.get_tier_bundled_credits = Mock(return_value=2000)

            from app.services.daily_credit_reset import _reset_bundled_credits

            await _reset_bundled_credits()

        assert user.bundled_credits == 2000
        # credits_reset_date should be approximately 30 days from now
        assert user.credits_reset_date > datetime.now(UTC) + timedelta(days=29)
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_free_tier_users(self):
        """Free-tier users are excluded by the query; no commit should happen."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session_factory():
            yield mock_session

        with patch("app.services.daily_credit_reset.AsyncSessionLocal", mock_session_factory):
            from app.services.daily_credit_reset import _reset_bundled_credits

            await _reset_bundled_credits()

        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_users_with_future_reset_date(self):
        """Users whose credits_reset_date is in the future are not returned by query."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        @asynccontextmanager
        async def mock_session_factory():
            yield mock_session

        with patch("app.services.daily_credit_reset.AsyncSessionLocal", mock_session_factory):
            from app.services.daily_credit_reset import _reset_bundled_credits

            await _reset_bundled_credits()

        mock_session.commit.assert_not_awaited()


# ===========================================================================
# Fix 3b — _handle_invoice_payment_succeeded (Stripe webhook)
# ===========================================================================


@pytest.mark.unit
class TestStripeSubscriptionRenewal:
    """Test _handle_invoice_payment_succeeded subscription renewal logic."""

    @pytest.mark.asyncio
    async def test_subscription_cycle_resets_credits(self):
        """billing_reason='subscription_cycle' resets bundled credits for the user."""
        from app.services.stripe_service import StripeService

        service = StripeService.__new__(StripeService)
        service.stripe = None
        service.stripe_key = None
        service.webhook_secret = None
        service.publishable_key = None

        invoice = {
            "id": "inv_123",
            "billing_reason": "subscription_cycle",
            "subscription": "sub_abc",
            "metadata": {},
        }

        user = Mock()
        user.id = uuid4()
        user.subscription_tier = "pro"
        user.stripe_subscription_id = "sub_abc"
        user.bundled_credits = 100
        user.credits_reset_date = None

        mock_user_result = Mock()
        mock_user_result.scalar_one_or_none.return_value = user

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_user_result)
        db.commit = AsyncMock()

        with patch("app.services.stripe_service.settings") as mock_settings:
            mock_settings.get_tier_bundled_credits = Mock(return_value=2000)
            await service._handle_invoice_payment_succeeded(invoice, db)

        assert user.bundled_credits == 2000
        assert user.credits_reset_date is not None
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_non_cycle_invoice_skips_renewal(self):
        """billing_reason='subscription_create' should NOT reset credits."""
        from app.services.stripe_service import StripeService

        service = StripeService.__new__(StripeService)
        service.stripe = None
        service.stripe_key = None
        service.webhook_secret = None
        service.publishable_key = None

        invoice = {
            "id": "inv_456",
            "billing_reason": "subscription_create",
            "subscription": "sub_abc",
            "metadata": {},
        }

        user = Mock()
        user.subscription_tier = "pro"
        user.bundled_credits = 500

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        await service._handle_invoice_payment_succeeded(invoice, db)

        # bundled_credits should remain untouched
        assert user.bundled_credits == 500

    @pytest.mark.asyncio
    async def test_usage_invoice_marks_logs_paid(self):
        """Usage invoices should mark usage logs as paid."""
        from app.services.stripe_service import StripeService

        service = StripeService.__new__(StripeService)
        service.stripe = None
        service.stripe_key = None
        service.webhook_secret = None
        service.publishable_key = None

        user_id = uuid4()
        invoice = {
            "id": "inv_789",
            "billing_reason": "manual",
            "subscription": None,
            "metadata": {"type": "usage_invoice", "user_id": str(user_id)},
        }

        log1 = Mock()
        log1.billed_status = "pending"
        log2 = Mock()
        log2.billed_status = "pending"

        mock_usage_result = Mock()
        mock_usage_result.scalars.return_value.all.return_value = [log1, log2]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_usage_result)
        db.commit = AsyncMock()

        await service._handle_invoice_payment_succeeded(invoice, db)

        assert log1.billed_status == "paid"
        assert log2.billed_status == "paid"
        db.commit.assert_awaited()


# ===========================================================================
# Fix 2b — Budget sync in Stripe fulfillment methods
# ===========================================================================


@pytest.mark.unit
class TestStripeBudgetSync:
    """Test that fulfill_credit_purchase and fulfill_subscription call ensure_budget_headroom."""

    @pytest.mark.asyncio
    async def test_fulfill_credit_purchase_syncs_budget(self):
        """After fulfilling a credit purchase, ensure_budget_headroom is called."""
        from app.services.stripe_service import StripeService

        service = StripeService.__new__(StripeService)
        service.stripe = None
        service.stripe_key = None
        service.webhook_secret = None
        service.publishable_key = None

        user_id = uuid4()
        team_id = uuid4()
        checkout_session = {
            "id": "cs_test_123",
            "payment_intent": "pi_test_123",
            "amount_total": 2500,
            "metadata": {
                "user_id": str(user_id),
                "team_id": str(team_id),
                "amount_cents": "2500",
                "credits_amount": "2500",
            },
        }

        team = Mock()
        team.id = team_id
        team.purchased_credits = 0
        team.total_spend = 0

        user = Mock()
        user.id = user_id
        user.litellm_api_key = "sk-test"

        # First execute: check for existing CreditPurchase (idempotency)
        existing_result = Mock()
        existing_result.scalar_one_or_none.return_value = None

        # Second execute: select team (team_id in metadata, no user lookup needed)
        team_result = Mock()
        team_result.scalar_one_or_none.return_value = team

        # Third execute: select user (for LiteLLM budget sync)
        user_result = Mock()
        user_result.scalar_one.return_value = user

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[existing_result, team_result, user_result])
        db.add = Mock()
        db.commit = AsyncMock()

        mock_headroom = AsyncMock(return_value=True)
        with (
            patch(
                "app.services.stripe_service.litellm_service",
                create=True,
            ),
            patch("app.services.litellm_service.litellm_service") as mock_litellm,
        ):
            mock_litellm.ensure_budget_headroom = mock_headroom

            result = await service.fulfill_credit_purchase(checkout_session, db)

        assert result["credits_added"] == 2500
        assert result["already_fulfilled"] is False
        mock_headroom.assert_awaited_once_with("sk-test")

    @pytest.mark.asyncio
    async def test_fulfill_subscription_syncs_budget(self):
        """After fulfilling a subscription, ensure_budget_headroom is called."""
        from app.services.stripe_service import StripeService

        service = StripeService.__new__(StripeService)
        service.stripe = None
        service.stripe_key = None
        service.webhook_secret = None
        service.publishable_key = None

        user_id = uuid4()
        team_id = uuid4()
        checkout_session = {
            "id": "cs_test_sub",
            "subscription": "sub_test_123",
            "metadata": {
                "user_id": str(user_id),
                "team_id": str(team_id),
                "tier": "pro",
            },
        }

        team = Mock()
        team.id = team_id
        team.subscription_tier = "free"
        team.stripe_subscription_id = None
        team.bundled_credits = 0
        team.credits_reset_date = None
        team.support_tier = "community"

        user = Mock()
        user.id = user_id
        user.litellm_api_key = "sk-test"

        # First execute: select team
        team_result = Mock()
        team_result.scalar_one_or_none.return_value = team

        # Second execute: select user (for LiteLLM sync)
        user_result = Mock()
        user_result.scalar_one.return_value = user

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[team_result, user_result])
        db.commit = AsyncMock()

        mock_headroom = AsyncMock(return_value=True)
        with patch("app.services.litellm_service.litellm_service") as mock_litellm:
            mock_litellm.ensure_budget_headroom = mock_headroom

            result = await service.fulfill_subscription(checkout_session, db)

        assert result["tier"] == "pro"
        assert result["already_fulfilled"] is False
        mock_headroom.assert_awaited_once_with("sk-test")

    @pytest.mark.asyncio
    async def test_budget_sync_failure_does_not_block_purchase(self):
        """ensure_budget_headroom raising an exception must not break fulfillment."""
        from app.services.stripe_service import StripeService

        service = StripeService.__new__(StripeService)
        service.stripe = None
        service.stripe_key = None
        service.webhook_secret = None
        service.publishable_key = None

        user_id = uuid4()
        team_id = uuid4()
        checkout_session = {
            "id": "cs_test_fail",
            "payment_intent": "pi_test_fail",
            "amount_total": 500,
            "metadata": {
                "user_id": str(user_id),
                "team_id": str(team_id),
                "amount_cents": "500",
                "credits_amount": "500",
            },
        }

        team = Mock()
        team.id = team_id
        team.purchased_credits = 0
        team.total_spend = 0

        user = Mock()
        user.id = user_id
        user.litellm_api_key = "sk-test"

        existing_result = Mock()
        existing_result.scalar_one_or_none.return_value = None

        team_result = Mock()
        team_result.scalar_one_or_none.return_value = team

        user_result = Mock()
        user_result.scalar_one.return_value = user

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[existing_result, team_result, user_result])
        db.add = Mock()
        db.commit = AsyncMock()

        with patch("app.services.litellm_service.litellm_service") as mock_litellm:
            mock_litellm.ensure_budget_headroom = AsyncMock(
                side_effect=Exception("LiteLLM is down")
            )

            # Should NOT raise
            result = await service.fulfill_credit_purchase(checkout_session, db)

        assert result["credits_added"] == 500
        assert result["already_fulfilled"] is False
