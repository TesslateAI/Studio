"""Wave-2 billing dispatcher + settlement worker tests.

Unit tests cover ``resolve_payer`` (pure function, no DB). Integration tests
exercise ``record_spend``, ``settle_spend_batch``, and
``find_or_create_wallet`` against the live Postgres container spun up by
``tests/integration/conftest.py``.

Run non-integration only::

    pytest tests/apps/test_billing_dispatcher.py -q -m "not integration"
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.services.apps.billing_dispatcher import (
    MissingWalletMixError,
    UnknownDimensionError,
    record_spend,
    resolve_payer,
)
from app.services.apps.settlement_worker import (
    find_or_create_wallet,
    settle_spend_batch,
)


# ---------------------------------------------------------------------------
# Unit: resolve_payer (pure)
# ---------------------------------------------------------------------------


DEFAULT_MIX = {
    "ai_compute": {"payer": "installer", "markup_pct": 0},
    "general_compute": {"payer": "platform", "markup_pct": 0},
    "storage": {"payer": "creator", "markup_pct": "0.10"},
    "platform_fee": {"payer": "installer", "markup_pct": 0},
}


@pytest.mark.asyncio
async def test_resolve_payer_honors_byok_for_ai_compute() -> None:
    # BYOK overrides ai_compute.
    assert (
        await resolve_payer(DEFAULT_MIX, "ai_compute", is_byok=True) == "byok"
    )
    # BYOK does NOT override general_compute — declared payer still pays.
    assert (
        await resolve_payer(DEFAULT_MIX, "general_compute", is_byok=True)
        == "platform"
    )
    # Non-BYOK goes to declared payer.
    assert (
        await resolve_payer(DEFAULT_MIX, "ai_compute", is_byok=False)
        == "installer"
    )


@pytest.mark.asyncio
async def test_resolve_payer_missing_dimension_raises() -> None:
    mix = {"ai_compute": {"payer": "installer"}}
    with pytest.raises(UnknownDimensionError):
        await resolve_payer(mix, "storage")
    # Also raises for dimensions outside the allowed set.
    with pytest.raises(UnknownDimensionError):
        await resolve_payer(mix, "not_a_dimension")  # type: ignore[arg-type]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payer", ["creator", "platform", "installer", "byok"]
)
async def test_resolve_payer_all_four_payers(payer: str) -> None:
    mix = {"ai_compute": {"payer": payer, "markup_pct": 0}}
    # Non-BYOK path returns the declared payer verbatim (including the
    # literal "byok" string if the creator declared it — unusual but legal).
    assert await resolve_payer(mix, "ai_compute", is_byok=False) == payer


@pytest.mark.asyncio
async def test_resolve_payer_rejects_invalid_declared_payer() -> None:
    mix = {"ai_compute": {"payer": "nonsense"}}
    with pytest.raises(UnknownDimensionError):
        await resolve_payer(mix, "ai_compute")


# ---------------------------------------------------------------------------
# Integration: record_spend + settlement_worker
# ---------------------------------------------------------------------------


pytestmark_integration = pytest.mark.integration


@pytest_asyncio.fixture
async def db():
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


async def _make_user(db, *, email_tag: str):
    from app import models

    u = models.User(
        id=uuid.uuid4(),
        email=f"{email_tag}-{uuid.uuid4().hex[:8]}@test.local",
        hashed_password="x",
        is_active=True,
        is_verified=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _make_app_instance(db, *, installer_id, creator_id, wallet_mix):
    from app import models

    app = models.MarketplaceApp(
        id=uuid.uuid4(),
        slug=f"test/app-{uuid.uuid4().hex[:8]}",
        name="Billing Dispatcher Test App",
        creator_user_id=creator_id,
    )
    db.add(app)
    await db.flush()

    version = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app.id,
        version="0.0.1",
        manifest_schema_version="2025-01",
        manifest_json={},
        manifest_hash="sha256:" + ("a" * 64),
        feature_set_hash="sha256:" + ("b" * 64),
    )
    db.add(version)
    await db.flush()

    inst = models.AppInstance(
        id=uuid.uuid4(),
        app_id=app.id,
        app_version_id=version.id,
        installer_user_id=installer_id,
        wallet_mix=wallet_mix,
    )
    db.add(inst)
    await db.flush()
    return app, inst


@pytest.mark.integration
async def test_record_spend_writes_row(db) -> None:
    installer = await _make_user(db, email_tag="installer")
    creator = await _make_user(db, email_tag="creator")
    _, inst = await _make_app_instance(
        db,
        installer_id=installer.id,
        creator_id=creator.id,
        wallet_mix=DEFAULT_MIX,
    )

    outcome = await record_spend(
        db,
        app_instance_id=inst.id,
        installer_user_id=installer.id,
        dimension="ai_compute",
        amount_usd=Decimal("0.25"),
    )

    from app import models
    from sqlalchemy import select

    row = (
        await db.execute(
            select(models.SpendRecord).where(
                models.SpendRecord.id == outcome.spend_record_id
            )
        )
    ).scalar_one()
    assert row.settled is False
    assert row.payer == "installer"
    assert Decimal(row.amount_usd) == Decimal("0.25")
    assert row.dimension == "ai_compute"
    assert row.payer_user_id == installer.id


@pytest.mark.integration
async def test_record_spend_idempotent_on_request_id(db) -> None:
    installer = await _make_user(db, email_tag="installer")
    creator = await _make_user(db, email_tag="creator")
    _, inst = await _make_app_instance(
        db,
        installer_id=installer.id,
        creator_id=creator.id,
        wallet_mix=DEFAULT_MIX,
    )
    req_id = f"req-{uuid.uuid4().hex}"

    first = await record_spend(
        db,
        app_instance_id=inst.id,
        installer_user_id=installer.id,
        dimension="ai_compute",
        amount_usd=Decimal("0.10"),
        meta={"request_id": req_id},
    )
    second = await record_spend(
        db,
        app_instance_id=inst.id,
        installer_user_id=installer.id,
        dimension="ai_compute",
        amount_usd=Decimal("0.10"),
        meta={"request_id": req_id},
    )
    assert first.spend_record_id == second.spend_record_id


@pytest.mark.integration
async def test_record_spend_missing_wallet_mix_raises(db) -> None:
    installer = await _make_user(db, email_tag="installer")
    creator = await _make_user(db, email_tag="creator")
    _, inst = await _make_app_instance(
        db,
        installer_id=installer.id,
        creator_id=creator.id,
        wallet_mix={},
    )
    with pytest.raises(MissingWalletMixError):
        await record_spend(
            db,
            app_instance_id=inst.id,
            installer_user_id=installer.id,
            dimension="ai_compute",
            amount_usd=Decimal("0.05"),
        )


@pytest.mark.integration
async def test_settle_spend_batch_happy_path(db) -> None:
    """Installer pays gross; creator gets net; platform gets markup."""
    from app import models
    from sqlalchemy import select

    installer = await _make_user(db, email_tag="installer")
    creator = await _make_user(db, email_tag="creator")
    mix = {
        "storage": {"payer": "installer", "markup_pct": "0.20"},
    }
    _, inst = await _make_app_instance(
        db,
        installer_id=installer.id,
        creator_id=creator.id,
        wallet_mix=mix,
    )

    await record_spend(
        db,
        app_instance_id=inst.id,
        installer_user_id=installer.id,
        dimension="storage",
        amount_usd=Decimal("1.00"),
    )
    await db.commit()

    result = await settle_spend_batch({}, limit=50)
    assert result["errors"] == 0
    assert result["processed"] >= 1

    # Re-open a session for assertions (settle_spend_batch committed).
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as check:
        rows = (
            await check.execute(
                select(models.SpendRecord).where(
                    models.SpendRecord.app_instance_id == inst.id
                )
            )
        ).scalars().all()
        assert all(r.settled for r in rows)

        # Installer wallet debited -1.00.
        installer_wallet = (
            await check.execute(
                select(models.Wallet).where(
                    models.Wallet.owner_type == "installer",
                    models.Wallet.owner_user_id == installer.id,
                )
            )
        ).scalar_one()
        assert Decimal(installer_wallet.balance_usd) == Decimal("-1.000000")

        # Creator wallet credited 0.80 (net of 20% markup).
        creator_wallet = (
            await check.execute(
                select(models.Wallet).where(
                    models.Wallet.owner_type == "creator",
                    models.Wallet.owner_user_id == creator.id,
                )
            )
        ).scalar_one()
        assert Decimal(creator_wallet.balance_usd) == Decimal("0.800000")

        # Platform wallet credited 0.20.
        platform_wallet = (
            await check.execute(
                select(models.Wallet).where(
                    models.Wallet.owner_type == "platform",
                    models.Wallet.owner_user_id.is_(None),
                )
            )
        ).scalar_one()
        assert Decimal(platform_wallet.balance_usd) == Decimal("0.200000")

        # Three ledger entries for this spend record.
        spend_id = rows[0].id
        entries = (
            await check.execute(
                select(models.WalletLedgerEntry).where(
                    models.WalletLedgerEntry.reference_id == spend_id
                )
            )
        ).scalars().all()
        assert len(entries) == 3
        assert sum(Decimal(e.delta_usd) for e in entries) == Decimal("0")


@pytest.mark.integration
async def test_settle_spend_batch_byok_ai_compute_skipped(db) -> None:
    from app import models
    from sqlalchemy import select

    installer = await _make_user(db, email_tag="installer")
    creator = await _make_user(db, email_tag="creator")
    _, inst = await _make_app_instance(
        db,
        installer_id=installer.id,
        creator_id=creator.id,
        wallet_mix=DEFAULT_MIX,
    )
    outcome = await record_spend(
        db,
        app_instance_id=inst.id,
        installer_user_id=installer.id,
        dimension="ai_compute",
        amount_usd=Decimal("0.50"),
        is_byok=True,
    )
    assert outcome.payer == "byok"
    await db.commit()

    result = await settle_spend_batch({}, limit=50)
    assert result["errors"] == 0

    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as check:
        row = (
            await check.execute(
                select(models.SpendRecord).where(
                    models.SpendRecord.id == outcome.spend_record_id
                )
            )
        ).scalar_one()
        assert row.settled is True
        assert (row.meta or {}).get("settlement_reason") == "byok_no_op"

        # No ledger entries.
        entries = (
            await check.execute(
                select(models.WalletLedgerEntry).where(
                    models.WalletLedgerEntry.reference_id == outcome.spend_record_id
                )
            )
        ).scalars().all()
        assert entries == []


@pytest.mark.integration
async def test_find_or_create_wallet_race_safe() -> None:
    """10 concurrent creators for the same user → exactly one wallet row."""
    from app import models
    from app.database import AsyncSessionLocal
    from sqlalchemy import select

    # Seed a user in its own session.
    async with AsyncSessionLocal() as seed:
        user = await _make_user(seed, email_tag="race")
        user_id = user.id
        await seed.commit()

    async def _one():
        async with AsyncSessionLocal() as s:
            w = await find_or_create_wallet(
                s, owner_type="installer", owner_user_id=user_id
            )
            await s.commit()
            return w.id

    ids = await asyncio.gather(*[_one() for _ in range(10)])
    assert len(set(ids)) == 1

    async with AsyncSessionLocal() as check:
        rows = (
            await check.execute(
                select(models.Wallet).where(
                    models.Wallet.owner_type == "installer",
                    models.Wallet.owner_user_id == user_id,
                )
            )
        ).scalars().all()
        assert len(rows) == 1
