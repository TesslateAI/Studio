"""Wave-2 billing dispatcher.

Resolves *who pays* for each spend dimension declared in an AppInstance's
``wallet_mix``, then appends an unsettled ``spend_records`` row. Wallet
balance mutation is intentionally deferred to the settlement worker
(``settlement_worker.settle_spend_batch``) so this module stays a pure,
append-only attribution writer.

The dimensions are fixed by the manifest spec:

    ai_compute | general_compute | storage | egress | mcp_tool_call | platform_fee

A wallet_mix entry looks like::

    {
      "payer": "creator" | "platform" | "installer" | "byok",
      "markup_pct": 0.10,                    # optional, default 0
      "cap_usd_per_session": 1.00            # optional, informational
    }

Fail-closed: a dimension not declared in wallet_mix raises
``UnknownDimensionError``. The creator must have explicitly consented to
every dimension their app can spend on.

BYOK only overrides ``ai_compute``. Every other dimension still bills
whatever payer the creator declared, regardless of BYOK status.

See docs/proposed/plans/tesslate-apps.md §5.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppInstance, MarketplaceApp, SpendRecord

logger = logging.getLogger(__name__)


__all__ = [
    "BillingError",
    "UnknownDimensionError",
    "MissingWalletMixError",
    "Dimension",
    "Payer",
    "SpendOutcome",
    "VALID_DIMENSIONS",
    "VALID_PAYERS",
    "resolve_payer",
    "record_spend",
]


Dimension = Literal[
    "ai_compute",
    "general_compute",
    "storage",
    "egress",
    "mcp_tool_call",
    "platform_fee",
]
Payer = Literal["creator", "platform", "installer", "byok"]

VALID_DIMENSIONS: frozenset[str] = frozenset(
    {
        "ai_compute",
        "general_compute",
        "storage",
        "egress",
        "mcp_tool_call",
        "platform_fee",
    }
)
VALID_PAYERS: frozenset[str] = frozenset({"creator", "platform", "installer", "byok"})


class BillingError(Exception):
    """Base class for dispatcher errors."""


class UnknownDimensionError(BillingError):
    """Raised when a dimension is not declared in the instance's wallet_mix."""


class MissingWalletMixError(BillingError):
    """Raised when the AppInstance is missing or has no wallet_mix entries."""


@dataclass(frozen=True)
class SpendOutcome:
    spend_record_id: UUID
    payer: Payer
    amount_usd: Decimal  # gross
    dimension: Dimension


async def resolve_payer(
    wallet_mix: dict,
    dimension: Dimension,
    *,
    is_byok: bool = False,
) -> Payer:
    """Return the payer for ``dimension`` from ``wallet_mix``.

    BYOK short-circuits ``ai_compute`` to the ``"byok"`` pseudo-payer so the
    settlement worker knows not to move money through our wallets for that
    spend. All other dimensions honor the declared payer regardless of BYOK.

    Raises:
        UnknownDimensionError: if the dimension is not declared in
            ``wallet_mix``. Fail-closed — we never silently default to the
            platform bearing the cost.
    """
    if dimension not in VALID_DIMENSIONS:
        raise UnknownDimensionError(f"invalid dimension: {dimension!r}")

    if is_byok and dimension == "ai_compute":
        return "byok"

    entry = (wallet_mix or {}).get(dimension)
    if not entry or "payer" not in entry:
        raise UnknownDimensionError(
            f"dimension {dimension!r} not declared in wallet_mix"
        )

    payer = entry["payer"]
    if payer not in VALID_PAYERS:
        raise UnknownDimensionError(
            f"dimension {dimension!r} declares invalid payer {payer!r}"
        )
    return payer  # type: ignore[return-value]


async def _load_instance(
    db: AsyncSession, app_instance_id: UUID
) -> AppInstance:
    row = (
        await db.execute(
            select(AppInstance).where(AppInstance.id == app_instance_id).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise MissingWalletMixError(
            f"app_instance {app_instance_id} not found"
        )
    if not row.wallet_mix:
        raise MissingWalletMixError(
            f"app_instance {app_instance_id} has empty wallet_mix"
        )
    return row


async def _creator_user_id(db: AsyncSession, app_id: UUID) -> UUID | None:
    return (
        await db.execute(
            select(MarketplaceApp.creator_user_id).where(MarketplaceApp.id == app_id)
        )
    ).scalar_one_or_none()


async def record_spend(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
    installer_user_id: UUID,
    dimension: Dimension,
    amount_usd: Decimal,
    session_id: UUID | None = None,
    litellm_key_id: str | None = None,
    usage_log_id: UUID | None = None,
    is_byok: bool = False,
    meta: dict[str, Any] | None = None,
    automation_run_id: UUID | None = None,
    invocation_subject_id: UUID | None = None,
    agent_id: UUID | None = None,
) -> SpendOutcome:
    """Resolve the payer from the instance's wallet_mix and append a
    ``spend_records`` row with ``settled=False``.

    Idempotency: if ``meta["request_id"]`` is provided and a spend_records row
    already exists with the same request_id, the existing row is returned
    without inserting a duplicate.

    Phase 3 widens the signature to accept the three Automation Runtime
    attribution columns as first-class kwargs:

    * ``automation_run_id`` — FK-less today (target table FK lands in
      Phase 1's alembic 0074); the column ships now so spend rows
      between phases never lose attribution.
    * ``invocation_subject_id`` — Phase 2 column; same FK-less behavior.
    * ``agent_id`` — Phase 2 column; FK to ``marketplace_agents``.

    Before this widen, callers patched the row in a follow-up UPDATE
    after the dispatcher returned. That race window is closed: every
    write now carries attribution from the start.

    Does NOT mutate any wallet — that's the settlement worker's job.
    """
    if dimension not in VALID_DIMENSIONS:
        raise UnknownDimensionError(f"invalid dimension: {dimension!r}")
    amount = Decimal(amount_usd)
    if amount < 0:
        raise ValueError("amount_usd must be non-negative")

    meta = dict(meta or {})
    request_id = meta.get("request_id")

    # Idempotency fast-path on request_id.
    if request_id is not None:
        existing = (
            await db.execute(
                select(SpendRecord).where(
                    SpendRecord.meta["request_id"].astext == str(request_id)
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "billing_dispatcher.record_spend: idempotent hit request_id=%s "
                "spend=%s",
                request_id,
                existing.id,
            )
            return SpendOutcome(
                spend_record_id=existing.id,
                payer=existing.payer,  # type: ignore[arg-type]
                amount_usd=Decimal(existing.amount_usd),
                dimension=existing.dimension,  # type: ignore[arg-type]
            )

    instance = await _load_instance(db, app_instance_id)
    payer = await resolve_payer(instance.wallet_mix, dimension, is_byok=is_byok)

    payer_user_id: UUID | None
    if payer == "creator":
        payer_user_id = await _creator_user_id(db, instance.app_id)
    elif payer == "installer":
        payer_user_id = installer_user_id
    else:  # "platform" | "byok"
        payer_user_id = None

    row = SpendRecord(
        id=uuid.uuid4(),
        app_instance_id=app_instance_id,
        session_id=session_id,
        installer_user_id=installer_user_id,
        dimension=dimension,
        payer=payer,
        payer_user_id=payer_user_id,
        amount_usd=amount,
        litellm_key_id=litellm_key_id,
        usage_log_id=usage_log_id,
        settled=False,
        meta=meta,
        automation_run_id=automation_run_id,
        invocation_subject_id=invocation_subject_id,
        agent_id=agent_id,
    )
    db.add(row)
    await db.flush()

    logger.info(
        "billing_dispatcher.record_spend: spend=%s dim=%s payer=%s amount=%s "
        "app_instance=%s is_byok=%s",
        row.id,
        dimension,
        payer,
        amount,
        app_instance_id,
        is_byok,
    )
    return SpendOutcome(
        spend_record_id=row.id,
        payer=payer,
        amount_usd=amount,
        dimension=dimension,
    )
