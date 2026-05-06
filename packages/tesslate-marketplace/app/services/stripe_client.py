"""
Stripe Connect compatible checkout adapter.

Live mode: when `STRIPE_API_KEY` is set, we use the official Stripe SDK to
create a Checkout Session targeting the configured `STRIPE_CONNECT_ACCOUNT_ID`
(if any).

Dev mode: returns a deterministic fake URL of the form
`http://localhost:8800/dev/checkout/<session_id>` along with `mode="dev_simulator"`.
This lets the orchestrator's federation client exercise the entire flow without
a Stripe account during local development. The dev simulator endpoint is wired
in `routers/pricing.py` so a `GET` on the URL returns a confirmation page.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckoutResult:
    checkout_url: str
    session_id: str
    mode: str
    payload: dict[str, Any]


class StripeClient:
    """Tiny wrapper that hides whether we're in live or dev mode."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stripe = None
        if settings.stripe_api_key:
            try:
                import stripe  # type: ignore[import-untyped]
            except ImportError:
                logger.warning("stripe SDK missing; falling back to dev simulator")
            else:
                stripe.api_key = settings.stripe_api_key
                self._stripe = stripe

    @property
    def is_live(self) -> bool:
        return self._stripe is not None

    def create_checkout(
        self,
        *,
        item_kind: str,
        item_slug: str,
        item_name: str,
        amount_cents: int,
        currency: str,
        customer_email: str | None,
        success_url: str | None = None,
        cancel_url: str | None = None,
        metadata: dict[str, str] | None = None,
        stripe_price_id: str | None = None,
    ) -> CheckoutResult:
        success_url = success_url or self._settings.stripe_success_url
        cancel_url = cancel_url or self._settings.stripe_cancel_url
        meta = {
            "item_kind": item_kind,
            "item_slug": item_slug,
            **(metadata or {}),
        }

        if self._stripe is None:
            return self._dev_checkout(
                item_kind=item_kind,
                item_slug=item_slug,
                item_name=item_name,
                amount_cents=amount_cents,
                currency=currency,
                customer_email=customer_email,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=meta,
                stripe_price_id=stripe_price_id,
            )

        stripe = self._stripe
        kwargs: dict[str, Any] = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": meta,
        }
        if customer_email:
            kwargs["customer_email"] = customer_email

        if stripe_price_id:
            kwargs["line_items"] = [{"price": stripe_price_id, "quantity": 1}]
        else:
            kwargs["line_items"] = [
                {
                    "price_data": {
                        "currency": currency,
                        "unit_amount": amount_cents,
                        "product_data": {"name": item_name},
                    },
                    "quantity": 1,
                }
            ]

        if self._settings.stripe_connect_account_id:
            session = stripe.checkout.Session.create(
                stripe_account=self._settings.stripe_connect_account_id,
                **kwargs,
            )
        else:
            session = stripe.checkout.Session.create(**kwargs)

        return CheckoutResult(
            checkout_url=session.url,
            session_id=session.id,
            mode="live",
            payload={"stripe_session_id": session.id},
        )

    # -----------------------------------------------------------------
    # Dev simulator
    # -----------------------------------------------------------------

    def _dev_checkout(
        self,
        *,
        item_kind: str,
        item_slug: str,
        item_name: str,
        amount_cents: int,
        currency: str,
        customer_email: str | None,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
        stripe_price_id: str | None,
    ) -> CheckoutResult:
        session_id = "dev_" + secrets.token_urlsafe(16)
        url = f"{self._settings.bundle_base_url.rstrip('/')}/dev/checkout/{session_id}"
        return CheckoutResult(
            checkout_url=url,
            session_id=session_id,
            mode="dev_simulator",
            payload={
                "item_kind": item_kind,
                "item_slug": item_slug,
                "item_name": item_name,
                "amount_cents": amount_cents,
                "currency": currency,
                "customer_email": customer_email,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata,
                "stripe_price_id": stripe_price_id,
            },
        )


def get_stripe_client(settings: Settings | None = None) -> StripeClient:
    settings = settings or get_settings()
    return StripeClient(settings)
