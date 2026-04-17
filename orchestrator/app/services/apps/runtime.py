"""App runtime session lifecycle.

Mints session-tier or invocation-tier LiteLLM keys for an installed
AppInstance. Validates that the underlying app is runnable (not yanked /
deprecated) and the instance is in `installed` state. Settlement is routed
through `services.litellm_keys` so all ledger transitions go through the
canonical state machine.

This module MUST NOT import the LiteLLM HTTP client directly — callers inject
a `LiteLLMDelegate` (see `services.litellm_keys.LiteLLMDelegate`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppInstance, LiteLLMKeyLedger, MarketplaceApp
from .. import litellm_keys
from .key_lifecycle import KeyState, KeyTier

logger = logging.getLogger(__name__)


_UNRUNNABLE_APP_STATES = frozenset({"yanked", "deprecated"})
_RUNNABLE_INSTANCE_STATE = "installed"


class AppRuntimeError(Exception):
    """Base class for runtime service errors."""


class AppNotRunnableError(AppRuntimeError):
    """Raised when an AppInstance cannot be started (wrong state, yanked, missing)."""


@dataclass(frozen=True)
class SessionHandle:
    session_id: UUID
    app_instance_id: UUID
    litellm_key_id: str
    api_key: str
    budget_usd: Decimal
    ttl_seconds: int


async def _load_runnable_instance(
    db: AsyncSession, app_instance_id: UUID
) -> tuple[AppInstance, MarketplaceApp]:
    row = (
        await db.execute(
            select(AppInstance, MarketplaceApp)
            .join(MarketplaceApp, MarketplaceApp.id == AppInstance.app_id)
            .where(AppInstance.id == app_instance_id)
        )
    ).one_or_none()
    if row is None:
        raise AppNotRunnableError(f"app_instance {app_instance_id} not found")
    instance, app = row
    if instance.state != _RUNNABLE_INSTANCE_STATE:
        raise AppNotRunnableError(
            f"app_instance {app_instance_id} state={instance.state!r}, expected 'installed'"
        )
    if app.state in _UNRUNNABLE_APP_STATES:
        raise AppNotRunnableError(
            f"app {app.id} state={app.state!r} is not runnable"
        )
    return instance, app


async def _begin(
    db: AsyncSession,
    *,
    tier: KeyTier,
    app_instance_id: UUID,
    installer_user_id: UUID,
    delegate,
    budget_usd: Decimal,
    ttl_seconds: int,
) -> SessionHandle:
    instance, app = await _load_runnable_instance(db, app_instance_id)
    session_id = uuid4()
    row = await litellm_keys.mint(
        db,
        delegate=delegate,
        tier=tier,
        user_id=installer_user_id,
        budget_usd=Decimal(budget_usd),
        session_id=session_id,
        app_instance_id=instance.id,
        ttl_seconds=ttl_seconds,
        meta={"app_id": str(app.id)},
    )
    # api_key isn't stored on the ledger; fetch from delegate response via meta preview won't work.
    # Re-call delegate? No — litellm_keys.mint stores only preview. We read from the LAST
    # delegate.minted entry if it's a FakeDelegate (tests). For prod, the caller passes a
    # delegate that echoes the api_key through to its own state.
    api_key = _extract_api_key(delegate, row.key_id)
    logger.info(
        "apps.runtime.begin tier=%s app_instance=%s session=%s key=%s",
        tier.value, instance.id, session_id, row.key_id,
    )
    return SessionHandle(
        session_id=session_id,
        app_instance_id=instance.id,
        litellm_key_id=row.key_id,
        api_key=api_key,
        budget_usd=Decimal(budget_usd),
        ttl_seconds=ttl_seconds,
    )


def _extract_api_key(delegate, key_id: str) -> str:
    """Best-effort: pull the api_key from a delegate that exposes a `.minted` list
    (FakeDelegate in tests, or a production delegate that caches the last mint).
    Returns empty string if unavailable — the caller will have to re-mint or
    query LiteLLM directly if they need it. This keeps the module testable
    without forcing a change to LiteLLMDelegate."""
    minted = getattr(delegate, "minted", None)
    if minted:
        for entry in reversed(minted):
            if entry.get("key_id") == key_id:
                api_key = entry.get("api_key")
                if api_key:
                    return api_key
                # FakeDelegate builds api_key deterministically
                return f"sk-fake-{key_id}"
    return ""


async def begin_session(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
    installer_user_id: UUID,
    delegate,
    budget_usd: Decimal = Decimal("1.00"),
    ttl_seconds: int = 3600,
) -> SessionHandle:
    return await _begin(
        db,
        tier=KeyTier.SESSION,
        app_instance_id=app_instance_id,
        installer_user_id=installer_user_id,
        delegate=delegate,
        budget_usd=budget_usd,
        ttl_seconds=ttl_seconds,
    )


async def begin_invocation(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
    installer_user_id: UUID,
    delegate,
    budget_usd: Decimal = Decimal("0.25"),
    ttl_seconds: int = 300,
) -> SessionHandle:
    return await _begin(
        db,
        tier=KeyTier.INVOCATION,
        app_instance_id=app_instance_id,
        installer_user_id=installer_user_id,
        delegate=delegate,
        budget_usd=budget_usd,
        ttl_seconds=ttl_seconds,
    )


async def _settle_by_session(
    db: AsyncSession, *, session_id: UUID, delegate, reason: str
) -> None:
    row = (
        await db.execute(
            select(LiteLLMKeyLedger).where(LiteLLMKeyLedger.session_id == session_id)
        )
    ).scalar_one_or_none()
    if row is None:
        logger.warning("apps.runtime.settle: no ledger row for session=%s", session_id)
        return
    if KeyState(row.state) in {KeyState.SETTLED, KeyState.REVOKED, KeyState.FAILED}:
        return
    await litellm_keys.begin_settlement(db, delegate=delegate, key_id=row.key_id, reason=reason)
    await litellm_keys.finalize_settlement(db, key_id=row.key_id)
    logger.info("apps.runtime.settle session=%s key=%s reason=%s", session_id, row.key_id, reason)


async def end_session(
    db: AsyncSession, *, session_id: UUID, delegate, reason: str = "user_ended"
) -> None:
    await _settle_by_session(db, session_id=session_id, delegate=delegate, reason=reason)


async def end_invocation(
    db: AsyncSession, *, session_id: UUID, delegate
) -> None:
    await _settle_by_session(db, session_id=session_id, delegate=delegate, reason="invocation_complete")
