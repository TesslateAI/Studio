"""App runtime session lifecycle.

Mints session-tier or invocation-tier LiteLLM keys for an installed
AppInstance. Validates that the underlying app is runnable (not yanked /
deprecated) and the instance is in `installed` state. Settlement is routed
through `services.litellm_keys` so all ledger transitions go through the
canonical state machine.

This module MUST NOT import the LiteLLM HTTP client directly — callers inject
a `LiteLLMDelegate` (see `services.litellm_keys.LiteLLMDelegate`).

Phase 4 note (idle reaper): the Phase 4 controller's idle reaper will
sweep ``app_runtime_deployments`` (not ``app_instances``) so reaping
shared-singleton apps scales every install's view simultaneously. This
module's session-mint path stays installer-scoped — the reaper acts on
the shared deployment row above it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppInstance, AppVersion, LiteLLMKeyLedger, MarketplaceApp
from .. import litellm_keys
from .key_lifecycle import KeyState, KeyTier

logger = logging.getLogger(__name__)


_UNRUNNABLE_APP_STATES = frozenset({"yanked", "deprecated"})
# Wave 7: AppVersion.approval_state values that mean the version itself
# is yanked even when the parent MarketplaceApp.state is still ``approved``.
# Federated yanks land on the per-version row first (the parent app keeps
# other versions live); the runtime gate must refuse to start an installed
# instance whose pinned version is in any of these states.
_UNRUNNABLE_VERSION_STATES = frozenset({"yanked", "rejected"})
_RUNNABLE_INSTANCE_STATE = "installed"


class AppRuntimeError(Exception):
    """Base class for runtime service errors."""


class AppNotRunnableError(AppRuntimeError):
    """Raised when an AppInstance cannot be started (wrong state, yanked, missing)."""


class ApiKeyExtractionError(AppRuntimeError):
    """Raised when the api_key for a freshly minted LiteLLM key cannot be
    extracted from the delegate.

    The mint itself succeeded (the ledger row was written) but the delegate
    did not surface the api_key value back to us — without it, downstream
    callers cannot authenticate to LiteLLM. Loud-fail is mandatory: a silent
    empty string would propagate into invocation handles and only manifest
    as opaque 401s at request time.
    """


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
            select(AppInstance, MarketplaceApp, AppVersion)
            .join(MarketplaceApp, MarketplaceApp.id == AppInstance.app_id)
            .join(AppVersion, AppVersion.id == AppInstance.app_version_id)
            .where(AppInstance.id == app_instance_id)
        )
    ).one_or_none()
    if row is None:
        raise AppNotRunnableError(f"app_instance {app_instance_id} not found")
    instance, app, version = row
    if instance.state != _RUNNABLE_INSTANCE_STATE:
        raise AppNotRunnableError(
            f"app_instance {app_instance_id} state={instance.state!r}, expected 'installed'"
        )
    if app.state in _UNRUNNABLE_APP_STATES:
        raise AppNotRunnableError(
            f"app {app.id} state={app.state!r} is not runnable"
        )
    # Wave 7: a federated yank lands on the AppVersion row even when the
    # parent app state stays 'approved' (the hub can yank one version
    # while other versions remain live). The runtime gate refuses to
    # mint a session for an instance pinned at a yanked version so a
    # stale-but-installed AppInstance cannot side-step the propagation.
    if version.approval_state in _UNRUNNABLE_VERSION_STATES:
        raise AppNotRunnableError(
            f"app_version {version.id} approval_state="
            f"{version.approval_state!r} is not runnable"
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
    result = await litellm_keys.mint_with_secret(
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
    if not result.api_key:
        raise ApiKeyExtractionError(
            f"LiteLLM mint returned empty api_key for key_id={result.ledger.key_id!r}"
        )
    logger.info(
        "apps.runtime.begin tier=%s app_instance=%s session=%s key=%s",
        tier.value,
        instance.id,
        session_id,
        result.ledger.key_id,
    )
    return SessionHandle(
        session_id=session_id,
        app_instance_id=instance.id,
        litellm_key_id=result.ledger.key_id,
        api_key=result.api_key,
        budget_usd=Decimal(budget_usd),
        ttl_seconds=ttl_seconds,
    )


def _extract_api_key(delegate, key_id: str) -> str:
    """Pull the api_key for a freshly minted LiteLLM key from the delegate.

    Inspects the delegate's `.minted` audit list (FakeDelegate in tests, or a
    production delegate that caches the last mint) for an entry matching
    `key_id` and returns its `api_key` field.

    Raises:
        ApiKeyExtractionError: when the delegate exposes no `.minted` list,
            when no entry matches `key_id`, or when the matched entry's
            `api_key` is empty/None. Callers MUST NOT swallow this — a missing
            api_key means the resulting handle would be unusable, and the
            failure must surface as a typed invocation error rather than a
            silent empty string.
    """
    delegate_name = type(delegate).__name__
    minted = getattr(delegate, "minted", None)
    if minted is None:
        raise ApiKeyExtractionError(
            f"delegate {delegate_name!r} does not expose a `.minted` audit list; "
            f"cannot recover api_key for key_id={key_id!r}"
        )
    for entry in reversed(minted):
        if entry.get("key_id") == key_id:
            api_key = entry.get("api_key")
            if api_key:
                return api_key
            raise ApiKeyExtractionError(
                f"delegate {delegate_name!r} minted entry for key_id={key_id!r} "
                f"has empty/missing api_key field"
            )
    raise ApiKeyExtractionError(
        f"delegate {delegate_name!r} has no minted entry matching "
        f"key_id={key_id!r} (mint succeeded but delegate audit log lost it)"
    )


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


async def _settle_by_session(db: AsyncSession, *, session_id: UUID, delegate, reason: str) -> None:
    row = (
        await db.execute(select(LiteLLMKeyLedger).where(LiteLLMKeyLedger.session_id == session_id))
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


async def end_invocation(db: AsyncSession, *, session_id: UUID, delegate) -> None:
    await _settle_by_session(
        db, session_id=session_id, delegate=delegate, reason="invocation_complete"
    )
