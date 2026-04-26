"""Three-tier LiteLLM key orchestrator (session / invocation / nested).

Wires the pure state machine in `services/apps/key_lifecycle.py` to:
  - the `LiteLLMKeyLedger` table (state persistence + audit trail)
  - the `LiteLLMService` HTTP client (actual key mint / revoke at the proxy)

Wave 0 scope: mint / record_spend / begin_settlement / finalize_settlement /
cascade_revoke / reap_idle_session_keys / await_children_terminal. Wallet
reservation and revenue-split settlement are orchestrated from the billing
dispatcher in Wave 2; this module is billing-agnostic.

See docs/proposed/plans/tesslate-apps.md §6.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LiteLLMKeyLedger
from .apps.key_lifecycle import (
    KeyMintError,
    KeyState,
    KeyTier,
    KeyTransitionError,
    NestedMintRequest,
    assert_can_mint_nested,
    assert_legal_transition,
    assert_tier_for_mint,
    is_terminal,
)

logger = logging.getLogger(__name__)


# Env-overridable knobs. Promoted to config.py settings in Wave 2.
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


TTL_SESSION_IDLE_SECONDS = _env_int("TSL_LITELLM_TTL_SESSION_IDLE", 3600)
TTL_INVOCATION_MAX_SECONDS = _env_int("TSL_LITELLM_TTL_INVOCATION_MAX", 900)
NESTED_MAX_DEPTH = _env_int("TSL_LITELLM_NESTED_MAX_DEPTH", 3)


# ---------------------------------------------------------------------------
# LiteLLM HTTP delegate — abstracted to a callable so tests can inject a
# fake without touching aiohttp. Production wiring lives in
# services/litellm_service.py::LiteLLMService.create_scoped_key / revoke_key.
# ---------------------------------------------------------------------------


class LiteLLMDelegate:
    """Minimal interface this module needs from the LiteLLM proxy client."""

    async def create_scoped_key(
        self,
        *,
        tier: str,
        budget_usd: Decimal,
        ttl_seconds: int,
        metadata: dict[str, Any],
    ) -> dict[str, str]:
        """Returns {"key_id": <opaque-id>, "api_key": <secret>}."""
        raise NotImplementedError

    async def revoke_key(self, key_id: str) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Mint
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MintResult:
    """Return value of :func:`mint_with_secret`.

    Carries both the persisted ledger row (whose ``meta`` contains only
    the 8-char ``api_key_preview``, never the full secret) and the full
    ``api_key`` string returned by the LiteLLM proxy on mint.

    The full ``api_key`` is the caller's responsibility — it is NOT
    persisted anywhere in the orchestrator DB. Callers that need it for
    HTTP-header injection (e.g. ``services.automations.budget``) should
    plumb it through their in-memory payload (e.g. AgentTaskPayload via
    Redis, which is explicitly transient) and NEVER write it to a
    durable store.
    """

    ledger: LiteLLMKeyLedger
    api_key: str


async def _compute_ancestor_chain_len(db: AsyncSession, parent_key_id: str) -> int:
    """Walk the ancestor chain; returns 1 if parent has no parent, 2 if it does, etc."""
    depth = 0
    cursor = parent_key_id
    # Cap the walk well above any legal depth to catch cycles defensively.
    while cursor is not None and depth < 32:
        depth += 1
        row = (
            await db.execute(
                select(LiteLLMKeyLedger.parent_key_id).where(LiteLLMKeyLedger.key_id == cursor)
            )
        ).scalar_one_or_none()
        cursor = row
    return depth


async def mint_with_secret(
    db: AsyncSession,
    *,
    delegate: LiteLLMDelegate,
    tier: KeyTier | str,
    user_id: UUID | None,
    budget_usd: Decimal,
    session_id: UUID | None = None,
    app_instance_id: UUID | None = None,
    parent_key_id: str | None = None,
    ttl_seconds: int | None = None,
    meta: dict[str, Any] | None = None,
) -> MintResult:
    """Mint a new key and return both the ledger row and the full secret.

    Same validation + rollback semantics as :func:`mint`. The only
    difference is the return shape: this function returns a
    :class:`MintResult` so the caller can inject the full ``api_key``
    into outbound HTTP headers (e.g. agent worker ``Authorization``).

    The ledger row's ``meta`` keeps only the 8-char ``api_key_preview``,
    matching the existing security policy: the full secret is NEVER
    persisted in the DB. The caller owns the lifetime of the returned
    ``api_key`` string.

    Raises:
        KeyMintError: invariant violation (tier mismatch, depth exceeded,
            over-budget nested, non-active parent).
    """
    tier_enum = KeyTier(tier) if isinstance(tier, str) else tier
    assert_tier_for_mint(tier_enum, has_parent=parent_key_id is not None)

    if parent_key_id is not None:
        parent = (
            await db.execute(
                select(LiteLLMKeyLedger)
                .where(LiteLLMKeyLedger.key_id == parent_key_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if parent is None:
            raise KeyMintError(f"parent key_id {parent_key_id!r} not found")
        depth = await _compute_ancestor_chain_len(db, parent_key_id)
        assert_can_mint_nested(
            NestedMintRequest(
                parent=parent,
                requested_budget_usd=Decimal(budget_usd),
                ancestor_chain_len=depth,
            ),
            max_depth=NESTED_MAX_DEPTH,
        )

    if ttl_seconds is None:
        ttl_seconds = (
            TTL_SESSION_IDLE_SECONDS if tier_enum == KeyTier.SESSION else TTL_INVOCATION_MAX_SECONDS
        )
    ttl_at = datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)

    call_meta: dict[str, Any] = {
        "tier": tier_enum.value,
        "user_id": str(user_id) if user_id else None,
        "session_id": str(session_id) if session_id else None,
        "app_instance_id": str(app_instance_id) if app_instance_id else None,
        "parent_key_id": parent_key_id,
    }
    if meta:
        call_meta.update(meta)

    try:
        resp = await delegate.create_scoped_key(
            tier=tier_enum.value,
            budget_usd=Decimal(budget_usd),
            ttl_seconds=ttl_seconds,
            metadata=call_meta,
        )
    except Exception:
        logger.exception("litellm_keys.mint: LiteLLM create_scoped_key failed")
        raise

    key_id = resp["key_id"]
    api_key = resp.get("api_key") or ""

    row = LiteLLMKeyLedger(
        id=uuid.uuid4(),
        key_id=key_id,
        parent_key_id=parent_key_id,
        tier=tier_enum.value,
        user_id=user_id,
        app_instance_id=app_instance_id,
        session_id=session_id,
        budget_usd=Decimal(budget_usd),
        spent_usd=Decimal("0"),
        ttl_at=ttl_at,
        state=KeyState.ACTIVE.value,
        meta={**call_meta, "api_key_preview": api_key[:8]},
    )
    db.add(row)
    try:
        await db.flush()
    except Exception:
        logger.exception("litellm_keys.mint: DB insert failed; best-effort revoke")
        try:
            await delegate.revoke_key(key_id)
        except Exception:
            logger.exception("litellm_keys.mint: best-effort revoke also failed")
        raise

    return MintResult(ledger=row, api_key=api_key)


async def mint(
    db: AsyncSession,
    *,
    delegate: LiteLLMDelegate,
    tier: KeyTier | str,
    user_id: UUID | None,
    budget_usd: Decimal,
    session_id: UUID | None = None,
    app_instance_id: UUID | None = None,
    parent_key_id: str | None = None,
    ttl_seconds: int | None = None,
    meta: dict[str, Any] | None = None,
) -> LiteLLMKeyLedger:
    """Mint a new key. Validates tier/depth/budget, calls LiteLLM, inserts row.

    Returns the persisted :class:`LiteLLMKeyLedger` row only — the full
    ``api_key`` is dropped after the ledger is written. Callers that
    need the secret (e.g. for HTTP injection into the agent worker)
    should call :func:`mint_with_secret` instead.

    Rollback: if the DB insert fails after LiteLLM mint, we try best-effort
    revoke at the proxy and re-raise. If the LiteLLM call fails, no row is
    written.

    Raises:
        KeyMintError: invariant violation (tier mismatch, depth exceeded,
            over-budget nested, non-active parent).
    """
    result = await mint_with_secret(
        db,
        delegate=delegate,
        tier=tier,
        user_id=user_id,
        budget_usd=budget_usd,
        session_id=session_id,
        app_instance_id=app_instance_id,
        parent_key_id=parent_key_id,
        ttl_seconds=ttl_seconds,
        meta=meta,
    )
    return result.ledger


# ---------------------------------------------------------------------------
# Spend accounting
# ---------------------------------------------------------------------------


async def record_spend(
    db: AsyncSession,
    *,
    key_id: str,
    delta_usd: Decimal,
) -> LiteLLMKeyLedger:
    """Atomic spend accrual. Cascades the delta up the parent chain so parent
    remaining-budget checks stay accurate for subsequent nested mints.

    Returns the refreshed row. The caller is responsible for persisting a
    UsageLog / AppSpendLog entry — this function only updates the ledger.
    """
    if delta_usd < 0:
        raise ValueError("delta_usd must be non-negative")

    # Walk up the chain starting at this key. Each ancestor gets the same delta.
    cursor: str | None = key_id
    leaf: LiteLLMKeyLedger | None = None
    seen: set[str] = set()
    while cursor is not None and cursor not in seen and len(seen) < 32:
        seen.add(cursor)
        row = (
            await db.execute(
                select(LiteLLMKeyLedger).where(LiteLLMKeyLedger.key_id == cursor).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            if leaf is None:
                raise LookupError(f"key_id {cursor!r} not found")
            break
        row.spent_usd = Decimal(row.spent_usd) + Decimal(delta_usd)
        if leaf is None:
            leaf = row
        cursor = row.parent_key_id

    assert leaf is not None
    await db.flush()
    return leaf


# ---------------------------------------------------------------------------
# Settlement + revoke
# ---------------------------------------------------------------------------


async def begin_settlement(
    db: AsyncSession,
    *,
    delegate: LiteLLMDelegate,
    key_id: str,
    reason: str = "complete",
) -> LiteLLMKeyLedger:
    """active | reaped → settling. Revokes the key at LiteLLM."""
    row = await _lock_row(db, key_id)
    if row is None:
        raise LookupError(f"key_id {key_id!r} not found")
    if is_terminal(row.state):
        return row
    assert_legal_transition(row.state, KeyState.SETTLING)
    row.state = KeyState.SETTLING.value
    row.meta = {**(row.meta or {}), "settlement_reason": reason}
    try:
        await delegate.revoke_key(key_id)
    except Exception:
        # Best-effort revoke; finalize anyway — LiteLLM will stop honoring
        # the key at TTL even if revoke failed.
        logger.exception("begin_settlement: LiteLLM revoke failed for %s", key_id)
    await db.flush()
    return row


async def finalize_settlement(
    db: AsyncSession,
    *,
    key_id: str,
) -> LiteLLMKeyLedger:
    """settling → settled. Caller's billing dispatcher should have already
    resolved revenue split + idempotent ledger writes before calling this."""
    row = await _lock_row(db, key_id)
    if row is None:
        raise LookupError(f"key_id {key_id!r} not found")
    if KeyState(row.state) == KeyState.SETTLED:
        return row
    assert_legal_transition(row.state, KeyState.SETTLED)
    row.state = KeyState.SETTLED.value
    await db.flush()
    return row


async def mark_failed(db: AsyncSession, *, key_id: str, reason: str) -> LiteLLMKeyLedger:
    """Terminal failure. Only callers that know the key is unrecoverable
    should invoke this (mint errors, reconciliation-lost keys)."""
    row = await _lock_row(db, key_id)
    if row is None:
        raise LookupError(f"key_id {key_id!r} not found")
    if is_terminal(row.state):
        return row
    assert_legal_transition(row.state, KeyState.FAILED)
    row.state = KeyState.FAILED.value
    row.meta = {**(row.meta or {}), "failure_reason": reason}
    await db.flush()
    return row


async def cascade_revoke(
    db: AsyncSession,
    *,
    delegate: LiteLLMDelegate,
    parent_key_id: str,
) -> list[str]:
    """BFS revoke all active descendants. Safe on cycles and deep graphs.

    Does NOT revoke `parent_key_id` itself — callers who want the parent
    revoked should transition it separately.

    Returns the list of revoked key_ids.
    """
    revoked: list[str] = []
    frontier = [parent_key_id]
    visited: set[str] = set()
    while frontier:
        next_frontier: list[str] = []
        children = (
            (
                await db.execute(
                    select(LiteLLMKeyLedger)
                    .where(LiteLLMKeyLedger.parent_key_id.in_(frontier))
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for child in children:
            if child.key_id in visited:
                continue
            visited.add(child.key_id)
            if not is_terminal(child.state):
                try:
                    assert_legal_transition(child.state, KeyState.REVOKED)
                except KeyTransitionError:
                    continue
                child.state = KeyState.REVOKED.value
                try:
                    await delegate.revoke_key(child.key_id)
                except Exception:
                    logger.exception("cascade_revoke: revoke failed for %s", child.key_id)
                revoked.append(child.key_id)
            next_frontier.append(child.key_id)
        frontier = next_frontier
    await db.flush()
    return revoked


async def await_children_terminal(
    db: AsyncSession,
    *,
    parent_key_id: str,
) -> bool:
    """Return True iff every descendant is in a terminal state.

    Used as the parent-settle barrier. Callers should retry with backoff
    until this returns True before calling finalize_settlement on the parent.
    """
    result = await db.execute(
        select(LiteLLMKeyLedger.state).where(LiteLLMKeyLedger.parent_key_id == parent_key_id)
    )
    return all(is_terminal(state) for (state,) in result.all())


# ---------------------------------------------------------------------------
# Reaper
# ---------------------------------------------------------------------------


async def select_idle_session_keys(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 200,
) -> list[str]:
    """Select up to `limit` session-tier keys past their idle TTL. Caller
    enqueues begin_settlement for each."""
    now_ts = now or datetime.now(tz=UTC)
    rows = (
        (
            await db.execute(
                select(LiteLLMKeyLedger.key_id)
                .where(
                    LiteLLMKeyLedger.state == KeyState.ACTIVE.value,
                    LiteLLMKeyLedger.tier == KeyTier.SESSION.value,
                    LiteLLMKeyLedger.ttl_at.is_not(None),
                    LiteLLMKeyLedger.ttl_at <= now_ts,
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def bump_session_ttl(
    db: AsyncSession,
    *,
    key_id: str,
    extend_seconds: int | None = None,
) -> LiteLLMKeyLedger | None:
    """Called on activity to defer the idle reaper. Noop for terminal rows."""
    row = await _lock_row(db, key_id)
    if row is None or is_terminal(row.state):
        return row
    delta = extend_seconds if extend_seconds is not None else TTL_SESSION_IDLE_SECONDS
    row.ttl_at = datetime.now(tz=UTC) + timedelta(seconds=delta)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _lock_row(db: AsyncSession, key_id: str) -> LiteLLMKeyLedger | None:
    return (
        await db.execute(
            select(LiteLLMKeyLedger).where(LiteLLMKeyLedger.key_id == key_id).with_for_update()
        )
    ).scalar_one_or_none()
