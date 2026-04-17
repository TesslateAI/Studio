"""Hosted-agent warm pool.

DB-backed set of pre-minted invocation-tier LiteLLM keys per
`(app_instance_id, agent_id)` pair, sized by
`HostedAgentSpec.warm_pool_size`. Callers fast-path via `claim_warm_key`
and fall back to `begin_hosted_invocation` on miss. Warm keys live as
rows in `litellm_key_ledger` (state='active') with meta
`{"warm_pool": true, "app_instance_id", "agent_id", "claimed": bool}`.
No in-memory state — worker pods are ephemeral.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppInstance, AppVersion, LiteLLMKeyLedger, MarketplaceApp
from .. import litellm_keys
from .key_lifecycle import KeyState, KeyTier

logger = logging.getLogger(__name__)

_WARM_BUDGET_USD = Decimal("0.25")
_WARM_TTL_SECONDS = 900


def _warm_meta_match(app_instance_id: UUID, agent_id: str, claimed: bool):
    """Build a JSONB @> filter for warm-pool rows."""
    payload = {
        "warm_pool": True,
        "app_instance_id": str(app_instance_id),
        "agent_id": agent_id,
        "claimed": claimed,
    }
    return LiteLLMKeyLedger.meta.cast(JSONB).op("@>")(payload)


async def _load_manifest_hosted_agents(
    db: AsyncSession, app_instance_id: UUID
) -> tuple[UUID | None, UUID | None, list[dict[str, Any]]]:
    """Return (installer_user_id, app_id, hosted_agents list) for an instance."""
    row = (
        await db.execute(
            select(AppInstance, AppVersion, MarketplaceApp)
            .join(AppVersion, AppVersion.id == AppInstance.app_version_id)
            .join(MarketplaceApp, MarketplaceApp.id == AppInstance.app_id)
            .where(AppInstance.id == app_instance_id)
        )
    ).one_or_none()
    if row is None:
        return None, None, []
    instance, version, app = row
    manifest = version.manifest_json or {}
    compute = manifest.get("compute") or {}
    agents = [a for a in (compute.get("hosted_agents") or []) if isinstance(a, dict)]
    return instance.installer_user_id, app.id, agents


async def _count_unclaimed(
    db: AsyncSession, app_instance_id: UUID, agent_id: str
) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(LiteLLMKeyLedger).where(
                and_(
                    LiteLLMKeyLedger.state == KeyState.ACTIVE.value,
                    LiteLLMKeyLedger.app_instance_id == app_instance_id,
                    _warm_meta_match(app_instance_id, agent_id, claimed=False),
                )
            )
        )
    ).scalar_one()


async def _mint_one_warm(
    db: AsyncSession,
    *,
    delegate,
    app_instance_id: UUID,
    installer_user_id: UUID | None,
    app_id: UUID | None,
    agent_id: str,
) -> str:
    invocation_id = uuid4()
    row = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=KeyTier.INVOCATION,
        user_id=installer_user_id,
        budget_usd=_WARM_BUDGET_USD,
        session_id=invocation_id,
        app_instance_id=app_instance_id,
        ttl_seconds=_WARM_TTL_SECONDS,
        meta={
            "warm_pool": True,
            "app_instance_id": str(app_instance_id),
            "agent_id": agent_id,
            "claimed": False,
            "app_id": str(app_id) if app_id else None,
        },
    )
    return row.key_id


async def refill_warm_pool(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
    delegate,
    target_size: int | None = None,
) -> dict:
    """Ensure N unclaimed warm keys exist per declared hosted agent.

    Reads each `HostedAgentSpec.warm_pool_size` from the manifest when
    `target_size` is not provided. Returns {'minted': N, 'existing': M}
    summed across all hosted agents.
    """
    installer_user_id, app_id, agents = await _load_manifest_hosted_agents(
        db, app_instance_id
    )
    total_minted = 0
    total_existing = 0
    for spec in agents:
        agent_id = spec.get("id")
        if not agent_id:
            continue
        want = target_size if target_size is not None else int(spec.get("warm_pool_size") or 0)
        if want <= 0:
            continue
        have = await _count_unclaimed(db, app_instance_id, agent_id)
        total_existing += have
        shortfall = max(0, want - have)
        for _ in range(shortfall):
            try:
                await _mint_one_warm(
                    db,
                    delegate=delegate,
                    app_instance_id=app_instance_id,
                    installer_user_id=installer_user_id,
                    app_id=app_id,
                    agent_id=agent_id,
                )
                total_minted += 1
            except Exception:
                logger.exception(
                    "warm_pool.refill mint failed app_instance=%s agent=%s",
                    app_instance_id, agent_id,
                )
                break
    logger.info(
        "warm_pool.refill app_instance=%s minted=%s existing=%s",
        app_instance_id, total_minted, total_existing,
    )
    return {"minted": total_minted, "existing": total_existing}


async def claim_warm_key(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
    agent_id: str,
) -> str | None:
    """Atomically claim an unclaimed warm key. Returns key_id or None."""
    row = (
        await db.execute(
            select(LiteLLMKeyLedger)
            .where(
                and_(
                    LiteLLMKeyLedger.state == KeyState.ACTIVE.value,
                    LiteLLMKeyLedger.app_instance_id == app_instance_id,
                    _warm_meta_match(app_instance_id, agent_id, claimed=False),
                )
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.meta = {**(row.meta or {}), "claimed": True}
    await db.flush()
    logger.info(
        "warm_pool.claim app_instance=%s agent=%s key=%s",
        app_instance_id, agent_id, row.key_id,
    )
    return row.key_id


async def drain_warm_pool(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
    delegate,
) -> int:
    """Revoke all warm keys (claimed or not) for an instance. Returns count."""
    rows = (
        await db.execute(
            select(LiteLLMKeyLedger).where(
                and_(
                    LiteLLMKeyLedger.app_instance_id == app_instance_id,
                    LiteLLMKeyLedger.state == KeyState.ACTIVE.value,
                    LiteLLMKeyLedger.meta.cast(JSONB).op("@>")({"warm_pool": True}),
                )
            )
        )
    ).scalars().all()
    count = 0
    for row in rows:
        try:
            await litellm_keys.begin_settlement(
                db, delegate=delegate, key_id=row.key_id, reason="warm_pool_drain"
            )
            await litellm_keys.finalize_settlement(db, key_id=row.key_id)
            count += 1
        except Exception:
            logger.exception(
                "warm_pool.drain settle failed key=%s", row.key_id
            )
    logger.info(
        "warm_pool.drain app_instance=%s drained=%s", app_instance_id, count
    )
    return count
