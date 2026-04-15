"""Wave-2 settlement worker.

Sweeps unsettled ``spend_records`` rows into ``wallet_ledger_entries`` by
debiting the declared payer, crediting the creator (net of platform markup),
and crediting the platform wallet for the markup portion.

Run as an ARQ task (``settle_spend_batch``) on a short interval (e.g. 15s).
Multiple workers are safe: the sweep uses
``SELECT ... FOR UPDATE SKIP LOCKED``.

Invariants:
  * Money movement is always a balanced ledger: sum(debits) == sum(credits).
  * Each spend record yields at most three ledger entries:
        - debit payer wallet (gross)
        - credit creator wallet (gross * (1 - markup_pct))
        - credit platform wallet (gross * markup_pct)
  * BYOK + ai_compute is a no-op: the key was funded outside our wallets,
    we mark the record settled with ``reason='byok_no_op'``.
  * Creator-paid dimensions skip the creator credit (they eat their own
    cost); platform still receives the markup portion if any.
  * Every settlement runs in its own transaction/savepoint so one bad row
    cannot poison a batch.

See docs/proposed/plans/tesslate-apps.md §5.3.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import AsyncSessionLocal
from ...models import (
    AppInstance,
    MarketplaceApp,
    SpendRecord,
    Wallet,
    WalletLedgerEntry,
)

logger = logging.getLogger(__name__)


__all__ = [
    "settle_spend_batch",
    "settle_one_spend",
    "find_or_create_wallet",
]


# Money is stored as Numeric(12, 6). Normalize everything to 6 dp to avoid
# drift between credits/debits in the wallet_ledger.
_QUANT = Decimal("0.000001")


def _q(x: Decimal | int | float | str) -> Decimal:
    return Decimal(x).quantize(_QUANT, rounding=ROUND_HALF_UP)


OwnerType = Literal["creator", "platform", "installer"]


# ---------------------------------------------------------------------------
# Wallet helpers
# ---------------------------------------------------------------------------


def _wallet_advisory_key(owner_type: str, owner_user_id: UUID | None) -> int:
    """Derive a stable 63-bit Postgres advisory lock key from owner identity."""
    material = f"wallet:{owner_type}:{owner_user_id or 'singleton'}".encode()
    digest = hashlib.sha256(material).digest()
    # Take the low 8 bytes, mask to 63 bits so it fits pg_advisory's bigint.
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


async def find_or_create_wallet(
    db: AsyncSession,
    *,
    owner_type: OwnerType,
    owner_user_id: UUID | None,
) -> Wallet:
    """Lookup-then-insert, race-safe via transaction-scoped advisory lock.

    The platform wallet uses ``owner_user_id IS NULL``; the service layer (not
    a DB unique index) enforces singleton-ness because Postgres's default
    NULL-distinct semantics make a partial unique index ineffective here.
    If multiple active platform rows somehow exist, we log and return the
    oldest.
    """
    if owner_type not in ("creator", "platform", "installer"):
        raise ValueError(f"invalid owner_type: {owner_type!r}")
    if owner_type == "platform" and owner_user_id is not None:
        raise ValueError("platform wallet must have owner_user_id=None")
    if owner_type != "platform" and owner_user_id is None:
        raise ValueError(f"owner_type={owner_type} requires owner_user_id")

    # Transaction-scoped advisory lock prevents racing inserts for the same
    # owner across multiple workers. Released on commit/rollback.
    lock_key = _wallet_advisory_key(owner_type, owner_user_id)
    await db.execute(select(_pg_advisory_xact_lock(lock_key)))

    if owner_user_id is None:
        where = and_(Wallet.owner_type == owner_type, Wallet.owner_user_id.is_(None))
    else:
        where = and_(
            Wallet.owner_type == owner_type, Wallet.owner_user_id == owner_user_id
        )

    rows = (
        await db.execute(select(Wallet).where(where).order_by(Wallet.created_at))
    ).scalars().all()

    if rows:
        if owner_type == "platform" and len(rows) > 1:
            logger.error(
                "find_or_create_wallet: platform singleton invariant violated "
                "(%d rows); returning oldest",
                len(rows),
            )
        return rows[0]

    wallet = Wallet(
        id=uuid.uuid4(),
        owner_type=owner_type,
        owner_user_id=owner_user_id,
        balance_usd=Decimal("0"),
        state="active",
    )
    db.add(wallet)
    await db.flush()
    return wallet


def _pg_advisory_xact_lock(key: int):
    """Wrap pg_advisory_xact_lock(:key) as a SQLAlchemy SELECT-able."""
    from sqlalchemy import func

    return func.pg_advisory_xact_lock(key)


async def _apply_ledger(
    db: AsyncSession,
    wallet: Wallet,
    delta: Decimal,
    *,
    kind: str,
    reference_id: UUID,
    meta: dict[str, Any],
) -> WalletLedgerEntry:
    """Lock wallet row, apply delta, insert ledger entry."""
    locked = (
        await db.execute(
            select(Wallet).where(Wallet.id == wallet.id).with_for_update()
        )
    ).scalar_one()
    locked.balance_usd = _q(Decimal(locked.balance_usd) + delta)
    entry = WalletLedgerEntry(
        id=uuid.uuid4(),
        wallet_id=locked.id,
        delta_usd=delta,
        kind=kind,
        reference_type="spend_record",
        reference_id=reference_id,
        meta=meta,
    )
    db.add(entry)
    await db.flush()
    return entry


# ---------------------------------------------------------------------------
# Per-row settlement
# ---------------------------------------------------------------------------


async def settle_one_spend(db: AsyncSession, spend: SpendRecord) -> dict:
    """Settle a single spend_records row. Caller owns the transaction.

    Returns a small dict for logging/telemetry.
    """
    from datetime import datetime, timezone

    gross = _q(Decimal(spend.amount_usd))
    markup_pct = Decimal("0")
    creator_user_id: UUID | None = None

    # Resolve creator + markup from the AppInstance + MarketplaceApp.
    if spend.app_instance_id is not None:
        inst = (
            await db.execute(
                select(AppInstance).where(AppInstance.id == spend.app_instance_id)
            )
        ).scalar_one_or_none()
        if inst is not None:
            creator_user_id = (
                await db.execute(
                    select(MarketplaceApp.creator_user_id).where(
                        MarketplaceApp.id == inst.app_id
                    )
                )
            ).scalar_one_or_none()
            entry = (inst.wallet_mix or {}).get(spend.dimension) or {}
            raw_pct = entry.get("markup_pct", 0)
            try:
                markup_pct = Decimal(str(raw_pct))
            except Exception:
                markup_pct = Decimal("0")

    # BYOK + ai_compute: no wallet movement, but still mark settled.
    if spend.payer == "byok" and spend.dimension == "ai_compute":
        spend.settled = True
        spend.settled_at = datetime.now(tz=timezone.utc)
        spend.meta = {**(spend.meta or {}), "settlement_reason": "byok_no_op"}
        await db.flush()
        logger.info(
            "settled spend=%s payer=byok amount=%s net_creator=0 markup=0 (no-op)",
            spend.id,
            gross,
        )
        return {"spend_id": str(spend.id), "noop": True}

    markup_amount = _q(gross * markup_pct)
    net_creator_amount = _q(gross - markup_amount)

    # 1. Debit payer wallet.
    if spend.payer == "installer":
        payer_wallet = await find_or_create_wallet(
            db, owner_type="installer", owner_user_id=spend.installer_user_id
        )
    elif spend.payer == "creator":
        if creator_user_id is None:
            raise RuntimeError(
                f"spend {spend.id}: creator payer but no creator_user_id"
            )
        payer_wallet = await find_or_create_wallet(
            db, owner_type="creator", owner_user_id=creator_user_id
        )
    elif spend.payer == "platform":
        payer_wallet = await find_or_create_wallet(
            db, owner_type="platform", owner_user_id=None
        )
    else:
        raise RuntimeError(
            f"spend {spend.id}: unexpected payer {spend.payer!r}"
        )

    await _apply_ledger(
        db,
        payer_wallet,
        -gross,
        kind="settlement",
        reference_id=spend.id,
        meta={
            "role": "debit_payer",
            "dimension": spend.dimension,
            "payer": spend.payer,
        },
    )

    # 2. Credit creator wallet net amount (skip if payer IS creator — they
    # eat their own declared cost; skip if no creator_user_id is knowable).
    if (
        spend.payer != "creator"
        and creator_user_id is not None
        and net_creator_amount > 0
    ):
        creator_wallet = await find_or_create_wallet(
            db, owner_type="creator", owner_user_id=creator_user_id
        )
        await _apply_ledger(
            db,
            creator_wallet,
            net_creator_amount,
            kind="settlement",
            reference_id=spend.id,
            meta={
                "role": "credit_creator",
                "dimension": spend.dimension,
                "markup_pct": str(markup_pct),
            },
        )

    # 3. Credit platform wallet for markup portion. If the payer is already
    # platform, the markup is a round-trip on its own wallet — skip to avoid
    # noisy zero-net entries.
    if spend.payer != "platform" and markup_amount > 0:
        platform_wallet = await find_or_create_wallet(
            db, owner_type="platform", owner_user_id=None
        )
        await _apply_ledger(
            db,
            platform_wallet,
            markup_amount,
            kind="settlement",
            reference_id=spend.id,
            meta={
                "role": "credit_platform_markup",
                "dimension": spend.dimension,
                "markup_pct": str(markup_pct),
            },
        )

    spend.settled = True
    spend.settled_at = datetime.now(tz=timezone.utc)
    await db.flush()

    logger.info(
        "settled spend=%s payer=%s amount=%s net_creator=%s markup=%s",
        spend.id,
        spend.payer,
        gross,
        net_creator_amount,
        markup_amount,
    )
    return {
        "spend_id": str(spend.id),
        "payer": spend.payer,
        "gross": str(gross),
        "net_creator": str(net_creator_amount),
        "markup": str(markup_amount),
    }


# ---------------------------------------------------------------------------
# Batch sweeper (ARQ entrypoint)
# ---------------------------------------------------------------------------


async def settle_spend_batch(ctx: dict, *, limit: int = 500) -> dict:
    """ARQ task: sweep up to ``limit`` unsettled spend rows FIFO.

    Each row settles in its own nested transaction (SAVEPOINT) so a single
    failing row does not roll back the rest of the batch.
    """
    t0 = time.monotonic()
    processed = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(SpendRecord)
                .where(SpendRecord.settled.is_(False))
                .order_by(SpendRecord.created_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        for spend in rows:
            try:
                async with db.begin_nested():
                    await settle_one_spend(db, spend)
                processed += 1
            except Exception:
                errors += 1
                logger.exception(
                    "settle_spend_batch: failed to settle spend=%s", spend.id
                )

        await db.commit()

    wall_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "settle_spend_batch: processed=%d errors=%d wall_ms=%d",
        processed,
        errors,
        wall_ms,
    )
    return {"processed": processed, "errors": errors, "wall_clock_ms": wall_ms}
