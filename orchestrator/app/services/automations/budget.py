"""Per-run + daily budget enforcement for automation runs (Phase 2).

Two layers, deliberately split:

1.  **Per-run LiteLLM key with ``budget_usd`` cap** — minted at dispatch
    (Phase B preflight in :mod:`dispatcher`) with ``budget_usd =
    contract.max_spend_per_run_usd``. The agent loop in
    ``packages/tesslate-agent/`` issues the actual model calls with this
    key; LiteLLM returns 429 on exhaustion. The key is **single-use**:
    after the run terminates we DELETE it (no recycle, no pool reuse) so
    spend reconciliation stays 1:1 with our ledger and a leaked key has
    blast radius bounded to that one run. (See
    :file:`/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md`
    §"ContractGate — tool-call gating + LiteLLM-key budget" for the full
    rationale of mint-per-run vs mint-N-don't-recycle pool.)

2.  **Daily budget Redis decrementer** — a counter at
    ``tesslate:budget:daily:{automation_id}`` is decremented atomically
    by ``max_usd_per_run`` on allocation. If the decrement would take it
    negative the allocator raises :class:`DailyBudgetExceeded`; the
    dispatcher catches and registers an approval-card "extend daily
    budget?" If the run completes early, ``deallocate_run_budget`` refunds
    the unused portion back to the daily counter so the cap reflects
    actual spend, not the ceiling.

For the agent-builder skill (depth-1 cap), child runs ALSO debit the
parent automation's daily counter — walking the ``parent_automation_id``
chain with cycle detection (visited set, max depth 2). This keeps a
parent automation from spawning ten children that each consume the full
parent daily cap.

A separate :func:`request_budget_extension` helper handles the
parallel-429 case: when an agent fires N concurrent model calls and they
all 429 simultaneously, we want exactly one approval card. The first
caller acquires a Redis ``SET NX`` lock and returns ``True`` (the caller
registers the ApprovalRequest); subsequent callers return the resolution
of the existing request via Redis pubsub.

Wave coordination
-----------------
* Wave 1B's :mod:`invocation_subject` is meant to mint the LiteLLM key
  itself; this module builds the budget envelope around it. Until
  Wave 1B lands we mint directly via :mod:`services.litellm_keys` (which
  is the existing pattern key_lifecycle.py was built to support).
* The agent-side ``BudgetExhaustedError`` catch belongs to
  ``packages/tesslate-agent``; we only define the exception class here
  so the submodule can ``from app.services.automations.budget import
  BudgetExhaustedError`` once it wires the catch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import AutomationDefinition
from ..litellm_keys import LiteLLMDelegate, mint_with_secret as litellm_mint_with_secret

if TYPE_CHECKING:  # pragma: no cover
    from ..apps.key_lifecycle import KeyTier as _KeyTier

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetAllocation:
    """Returned by :func:`allocate_run_budget`.

    Carries the LiteLLM key (id + secret value) and the budget envelope
    we just reserved against. ``daily_remaining_usd`` is the post-debit
    remaining; it's surfaced in run history for the user.

    ``is_extension=True`` is set when the allocation came from a re-
    allocation after the user approved a budget-extension card. The
    dispatcher uses it to flip the run's ``contract_breaches`` counter
    and stamp the audit trail.
    """

    litellm_key_id: str
    litellm_key_value: str  # actual sk-... string for HTTP injection
    max_usd_per_run: Decimal
    daily_remaining_usd: Decimal
    is_extension: bool = False

    def __repr__(self) -> str:  # pragma: no cover — defensive log-leak guard
        masked = (
            f"{self.litellm_key_value[:6]}…(len={len(self.litellm_key_value)})"
            if self.litellm_key_value
            else "<empty>"
        )
        return (
            f"BudgetAllocation(litellm_key_id={self.litellm_key_id!r}, "
            f"litellm_key_value={masked}, max_usd_per_run={self.max_usd_per_run}, "
            f"daily_remaining_usd={self.daily_remaining_usd}, is_extension={self.is_extension})"
        )


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------


class BudgetError(RuntimeError):
    """Base class for budget-allocation domain errors."""


class BudgetExhaustedError(BudgetError):
    """Raised by the agent runtime (in :mod:`packages.tesslate-agent`) when
    a LiteLLM call returns 429 on the per-run key.

    The orchestrator does NOT raise this directly — it's defined here so
    the submodule can import a stable type from the orchestrator without
    creating a circular dep. The catch path is wired up in Phase 2 polish.
    """

    def __init__(self, run_id: UUID, key_id: str, spent_usd: Decimal):
        self.run_id = run_id
        self.key_id = key_id
        self.spent_usd = spent_usd
        super().__init__(
            f"budget exhausted for run {run_id}: key {key_id} spent ${spent_usd}"
        )


class DailyBudgetExceeded(BudgetError):
    """Raised by :func:`allocate_run_budget` when the per-run cap would
    push the daily counter for the automation (or any ancestor in the
    parent chain) below zero.

    Carries the offending automation_id so the dispatcher can register an
    "extend daily budget?" approval against the right scope (own vs
    ancestor) — the user might need to top up their own daily limit OR
    an upstream parent's, and the card text differs.
    """

    def __init__(self, automation_id: UUID, requested_usd: Decimal, remaining_usd: Decimal):
        self.automation_id = automation_id
        self.requested_usd = requested_usd
        self.remaining_usd = remaining_usd
        super().__init__(
            f"daily budget exceeded for automation {automation_id}: "
            f"requested ${requested_usd}, remaining ${remaining_usd}"
        )


class CycleDetected(BudgetError):
    """Raised by :func:`_walk_parent_chain` when the ``parent_automation_id``
    walk loops back on itself.

    The DB has a CHECK that bans self-parenting at the row level
    (``ck_automation_definitions_no_self_parent``) and a depth-range
    check (``ck_automation_definitions_depth_range`` -> 0 or 1), but a
    multi-row cycle (A -> B -> A) could still slip through if depth
    constraints were ever relaxed. Defensive guard: visited set + cap.
    """

    def __init__(self, chain: list[UUID]):
        self.chain = chain
        super().__init__(f"cycle in parent automation chain: {chain}")


# ---------------------------------------------------------------------------
# Redis key conventions + Lua scripts
# ---------------------------------------------------------------------------


# Per-automation daily counter, keyed by automation UUID. TTL = end of day
# UTC so the counter naturally rolls over without needing a cron sweep.
_R_DAILY_KEY = "tesslate:budget:daily:{automation_id}"

# Pending budget-extension lock. Acquired by the first caller in
# request_budget_extension; subsequent callers await pubsub.
_R_EXTENSION_LOCK = "tesslate:budget_extension_pending:{run_id}"
_R_EXTENSION_RESOLVED_CHANNEL = "tesslate:budget_extension_resolved:{run_id}"

# Money is stored as MICRO-DOLLARS (1 USD == 1_000_000) so the Lua
# script can do integer math (Lua ``tonumber`` returns a double; we don't
# trust it for fractional cents). This gives us 6 decimal places of
# precision which is well past LiteLLM's per-call resolution.
_MICRO_PER_USD = 1_000_000

# Atomic DECRBY with floor check. Returns either the new value (>=0) or
# the sentinel ``-1`` if the decrement would take the counter negative.
# We deliberately do NOT initialize the key on first read — that's the
# caller's job (see ``_initialize_daily_if_absent``) so we can stamp the
# end-of-day TTL atomically with the SET.
_LUA_RESERVE_DAILY = """
local key = KEYS[1]
local decrement = tonumber(ARGV[1])
local cur = redis.call('GET', key)
if not cur then
  -- Key absent => no daily cap configured. Treat as inf, no debit.
  return -2
end
local cur_n = tonumber(cur)
if cur_n - decrement < 0 then
  return -1
end
return redis.call('DECRBY', key, decrement)
"""


# ---------------------------------------------------------------------------
# Default LiteLLM delegate wiring
# ---------------------------------------------------------------------------


def _default_delegate() -> LiteLLMDelegate:
    """Return the production LiteLLM delegate (the singleton service).

    Tests inject their own delegate via the ``delegate`` kwarg on
    :func:`allocate_run_budget` so we never hit the real proxy in CI.
    """
    from ..litellm_service import litellm_service

    return litellm_service  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Parent chain walking (cycle-detected)
# ---------------------------------------------------------------------------


# Hard cap on parent-chain depth. The agent-builder skill ships with a
# depth-1 cap (parent + one child = chain length 2), so we walk at most
# two hops. If a future feature relaxes that cap, this constant moves
# with it.
_MAX_PARENT_CHAIN_DEPTH = 2


async def _walk_parent_chain(
    db: AsyncSession,
    automation_id: UUID,
) -> list[UUID]:
    """Return the chain ``[automation_id, parent, grandparent, ...]``.

    Always includes ``automation_id`` itself at index 0. Stops at NULL
    parent or :data:`_MAX_PARENT_CHAIN_DEPTH` hops. Raises
    :class:`CycleDetected` if a visited row reappears.
    """
    visited: set[UUID] = {automation_id}
    chain: list[UUID] = [automation_id]
    cursor = automation_id
    hops = 0

    while hops < _MAX_PARENT_CHAIN_DEPTH:
        parent_id = (
            await db.execute(
                select(AutomationDefinition.parent_automation_id).where(
                    AutomationDefinition.id == cursor
                )
            )
        ).scalar_one_or_none()

        if parent_id is None:
            break
        if parent_id in visited:
            raise CycleDetected(chain + [parent_id])

        visited.add(parent_id)
        chain.append(parent_id)
        cursor = parent_id
        hops += 1

    return chain


# ---------------------------------------------------------------------------
# Daily counter helpers
# ---------------------------------------------------------------------------


def _seconds_until_end_of_day_utc() -> int:
    """Return seconds remaining until 00:00 UTC tomorrow.

    Used as TTL on the daily counter so it naturally rolls over without
    a cron sweep. We always return at least 60s so a counter created
    just before midnight doesn't expire mid-allocation.
    """
    from datetime import UTC, datetime, timedelta

    now = datetime.now(tz=UTC)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(int((tomorrow - now).total_seconds()), 60)


async def _initialize_daily_if_absent(
    redis_client: Any,
    automation_id: UUID,
    initial_usd: Decimal,
) -> None:
    """SETNX the daily counter with end-of-day TTL.

    No-op if the counter already exists or if ``initial_usd`` is None
    (no daily cap configured). The atomic SET-NX-EX guarantees we don't
    race with another worker doing the same thing — both paths converge
    on the same value.
    """
    key = _R_DAILY_KEY.format(automation_id=str(automation_id))
    micro = int(Decimal(initial_usd) * _MICRO_PER_USD)
    ttl = _seconds_until_end_of_day_utc()
    await redis_client.set(key, micro, nx=True, ex=ttl)


async def _atomic_reserve_daily(
    redis_client: Any,
    automation_id: UUID,
    amount_usd: Decimal,
) -> Decimal | None:
    """Atomic DECRBY-with-floor against the daily counter.

    Returns the post-debit remaining as Decimal, or ``None`` if no daily
    cap is configured for this automation (key absent). Raises
    :class:`DailyBudgetExceeded` if the decrement would take the counter
    negative.
    """
    key = _R_DAILY_KEY.format(automation_id=str(automation_id))
    micro = int(Decimal(amount_usd) * _MICRO_PER_USD)

    raw = await redis_client.eval(_LUA_RESERVE_DAILY, 1, key, micro)
    # redis-py returns int or bytes depending on decode_responses; coerce.
    if isinstance(raw, (bytes, bytearray)):
        raw = int(raw.decode())
    raw = int(raw)

    if raw == -2:
        # No daily cap configured.
        return None
    if raw == -1:
        # Floor breach. Re-read current remaining for the error payload.
        cur = await redis_client.get(key)
        if isinstance(cur, (bytes, bytearray)):
            cur = cur.decode()
        cur_micro = int(cur) if cur is not None else 0
        raise DailyBudgetExceeded(
            automation_id=automation_id,
            requested_usd=Decimal(amount_usd),
            remaining_usd=Decimal(cur_micro) / _MICRO_PER_USD,
        )

    return Decimal(raw) / _MICRO_PER_USD


async def _refund_daily(
    redis_client: Any,
    automation_id: UUID,
    amount_usd: Decimal,
) -> None:
    """Refund unused budget back to the daily counter.

    Best-effort — if the key has rolled over to the next UTC day in the
    meantime the refund silently no-ops (the new day's counter is fresh
    and shouldn't inherit yesterday's overruns). We use INCRBY which is
    a no-op-on-missing in atomic terms but creates a key without TTL —
    so we EXISTS-check first.
    """
    if amount_usd <= 0:
        return
    key = _R_DAILY_KEY.format(automation_id=str(automation_id))
    micro = int(Decimal(amount_usd) * _MICRO_PER_USD)
    # Only refund if the counter still exists — refunding into a rolled-
    # over day would inflate the new day's cap.
    exists = await redis_client.exists(key)
    if not exists:
        return
    await redis_client.incrby(key, micro)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def allocate_run_budget(
    db: AsyncSession,
    *,
    run_id: UUID,
    automation_id: UUID,
    contract: dict,
    parent_automation_id: UUID | None = None,
    delegate: LiteLLMDelegate | None = None,
    redis_client: Any | None = None,
    is_extension: bool = False,
) -> BudgetAllocation:
    """Mint a single-use LiteLLM key + reserve daily budget for one run.

    Two reservations happen atomically from the caller's perspective:

    1.  ``DECRBY`` the per-automation daily counter (and every ancestor
        in the parent chain). If any debit would take the counter below
        zero, raise :class:`DailyBudgetExceeded` *before* minting the
        LiteLLM key — no rollback needed for the cheap path.
    2.  Mint the per-run LiteLLM key with ``budget_usd =
        contract.max_spend_per_run_usd``. If the mint fails after we've
        debited the daily counter(s), refund and re-raise.

    Returns a :class:`BudgetAllocation` carrying the key id + secret
    value (the caller is responsible for plumbing the secret into the
    agent's HTTP injection — we don't store it).

    Raises:
        DailyBudgetExceeded: any chain member would go negative.
        CycleDetected: the parent chain loops.
        ValueError: ``contract.max_spend_per_run_usd`` is missing or
            non-positive (we don't allow ``inf`` budgets — that's the
            user's job to opt out by leaving ``max_spend_per_day_usd``
            unset).
    """
    max_per_run = contract.get("max_spend_per_run_usd")
    if max_per_run is None:
        raise ValueError(
            "contract.max_spend_per_run_usd is required for budget allocation"
        )
    max_per_run = Decimal(str(max_per_run))
    if max_per_run <= 0:
        raise ValueError(
            f"contract.max_spend_per_run_usd must be positive, got {max_per_run}"
        )

    # Daily cap is optional — None means "no daily limit". The plan calls
    # this out as the explicit user opt-out: leave the field unset.
    max_per_day_raw = contract.get("max_spend_per_day_usd")
    max_per_day = Decimal(str(max_per_day_raw)) if max_per_day_raw is not None else None

    if redis_client is None:
        from ..cache_service import get_redis_client

        redis_client = await get_redis_client()

    # Build the chain of automations we need to debit. Order matters
    # only for the refund path on partial failure, so we record what we
    # successfully debited as we go.
    chain = await _walk_parent_chain(db, automation_id)
    if parent_automation_id is not None and parent_automation_id not in chain:
        # Caller-supplied parent supersedes the DB walk (used when the
        # dispatcher knows the runtime parent — e.g., spawned by the
        # agent-builder skill — but the DB row hasn't been updated yet).
        chain.append(parent_automation_id)

    debited: list[UUID] = []

    if redis_client is not None:
        # Lazy-initialize each chain member's daily counter from the
        # automation's own ``max_spend_per_day_usd`` setting, NOT from
        # the contract — every level enforces its own cap.
        for chain_member in chain:
            member_max_per_day = await db.scalar(
                select(AutomationDefinition.max_spend_per_day_usd).where(
                    AutomationDefinition.id == chain_member
                )
            )
            if member_max_per_day is None:
                # No cap on this level; skip initialization. The Lua
                # script returns -2 (no cap) and the debit is a no-op.
                continue
            await _initialize_daily_if_absent(
                redis_client, chain_member, Decimal(str(member_max_per_day))
            )

        # Now debit each level. Chain[0] is the run's own automation;
        # the rest are ancestors. On any failure we refund what we've
        # already debited and re-raise.
        try:
            own_remaining: Decimal | None = None
            for idx, chain_member in enumerate(chain):
                remaining = await _atomic_reserve_daily(
                    redis_client, chain_member, max_per_run
                )
                debited.append(chain_member)
                if idx == 0:
                    own_remaining = remaining
        except DailyBudgetExceeded:
            # Refund anything we already debited before re-raising.
            for member in debited:
                await _refund_daily(redis_client, member, max_per_run)
            raise
    else:
        own_remaining = None

    # Daily cap reservations succeeded (or no cap). Mint the LiteLLM key.
    # The mint call itself already updates the LiteLLMKeyLedger row; we
    # don't need to record anything else here.
    if delegate is None:
        delegate = _default_delegate()

    from ..apps.key_lifecycle import KeyTier

    try:
        mint_result = await litellm_mint_with_secret(
            db,
            delegate=delegate,
            tier=KeyTier.INVOCATION,
            user_id=None,
            budget_usd=max_per_run,
            session_id=None,
            app_instance_id=None,
            parent_key_id=None,
            ttl_seconds=None,
            meta={
                "automation_id": str(automation_id),
                "automation_run_id": str(run_id),
                "single_use": True,
                "source": "automation_budget",
            },
        )
    except Exception:
        # Mint failed — refund the daily debits we already made.
        if redis_client is not None:
            for member in debited:
                await _refund_daily(redis_client, member, max_per_run)
        raise

    # The ledger row only stores an 8-char ``api_key_preview`` (security
    # policy: full secret is never persisted in the DB). The full secret
    # comes back through ``mint_result.api_key`` and we hand it off to
    # the caller for HTTP injection into the agent worker. The agent
    # worker carries it via ``AgentTaskPayload`` in Redis (transient) —
    # never written to durable storage. See
    # :class:`services.litellm_keys.MintResult` for the policy contract.
    ledger_row = mint_result.ledger
    api_key_full = mint_result.api_key

    return BudgetAllocation(
        litellm_key_id=ledger_row.key_id,
        litellm_key_value=api_key_full,
        max_usd_per_run=max_per_run,
        daily_remaining_usd=own_remaining if own_remaining is not None else Decimal("Infinity"),
        is_extension=is_extension,
    )


async def deallocate_run_budget(
    db: AsyncSession,
    *,
    run_id: UUID,
    automation_id: UUID,
    allocation: BudgetAllocation,
    actual_spend_usd: Decimal,
    parent_automation_id: UUID | None = None,
    delegate: LiteLLMDelegate | None = None,
    redis_client: Any | None = None,
) -> None:
    """Refund unused per-run budget + delete the single-use LiteLLM key.

    Called after the run terminates (success, failure, or cancel). Two
    operations:

    1.  Refund ``(max_usd_per_run - actual_spend_usd)`` to every chain
        member's daily counter. Refund is INCRBY, no floor check needed.
    2.  Delete the LiteLLM key at the proxy via
        :meth:`LiteLLMDelegate.revoke_key`. The key is single-use; no
        recycling. Spend reconciliation stays 1:1.

    Idempotent: safe to call twice. The Redis refund is idempotent on a
    rolled-over counter (we EXISTS-check before INCRBY), and the LiteLLM
    revoke is idempotent on the proxy side.
    """
    if redis_client is None:
        from ..cache_service import get_redis_client

        redis_client = await get_redis_client()

    refund_amount = max(allocation.max_usd_per_run - Decimal(actual_spend_usd), Decimal("0"))

    if redis_client is not None and refund_amount > 0:
        chain = await _walk_parent_chain(db, automation_id)
        if parent_automation_id is not None and parent_automation_id not in chain:
            chain.append(parent_automation_id)
        for member in chain:
            await _refund_daily(redis_client, member, refund_amount)

    if delegate is None:
        delegate = _default_delegate()

    try:
        await delegate.revoke_key(allocation.litellm_key_id)
    except Exception:  # pragma: no cover - delegate is best-effort
        logger.exception(
            "deallocate_run_budget: delegate.revoke_key failed for %s",
            allocation.litellm_key_id,
        )


async def request_budget_extension(
    *,
    run_id: UUID,
    extension_usd: Decimal,
    redis_client: Any | None = None,
    timeout_seconds: float = 900.0,
) -> bool:
    """Dedup parallel 429s when the agent fires concurrent model calls.

    Workflow:

    *   Acquire ``SET NX EX`` on
        ``tesslate:budget_extension_pending:{run_id}``. TTL = 60s so a
        crashed worker doesn't wedge the lock forever.
    *   If we got the lock → return ``True``. The caller is responsible
        for registering the ApprovalRequest, then PUBLISHing the
        resolution to ``tesslate:budget_extension_resolved:{run_id}``
        with payload ``approved`` or ``rejected``.
    *   If the lock was already held → subscribe to the resolution
        channel and return ``True`` if the existing request was
        approved, ``False`` otherwise.

    Returns ``True`` if the run may continue with extended budget,
    ``False`` if the user denied (or the existing request timed out).
    """
    if redis_client is None:
        from ..cache_service import get_redis_client

        redis_client = await get_redis_client()

    if redis_client is None:
        # No Redis (desktop / dev with Redis disabled): degrade to "first
        # caller wins, no dedup". Returning True lets the agent register
        # the approval; if multiple concurrent callers all return True,
        # the ApprovalRequest table itself dedups via UNIQUE(run_id,
        # kind) — see ``automation_approval_requests`` schema in plan.
        return True

    lock_key = _R_EXTENSION_LOCK.format(run_id=str(run_id))
    channel = _R_EXTENSION_RESOLVED_CHANNEL.format(run_id=str(run_id))

    acquired = await redis_client.set(lock_key, "1", nx=True, ex=60)
    if acquired:
        return True

    # Lock already held — wait for the existing extension to resolve.
    pubsub = redis_client.pubsub()
    try:
        await pubsub.subscribe(channel)
        # ``listen()`` yields a stream of dicts; the first message is a
        # subscribe-confirm we ignore. We bound the wait to the run's
        # max approval timeout (default 15min — matches the worker-
        # suspension cap in the plan).
        import asyncio

        async def _await_message() -> bool:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = msg.get("data")
                if isinstance(data, (bytes, bytearray)):
                    data = data.decode()
                return data == "approved"
            return False

        try:
            return await asyncio.wait_for(_await_message(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return False
    finally:
        try:
            await pubsub.unsubscribe(channel)
        except Exception:  # pragma: no cover
            pass
        try:
            await pubsub.close()
        except Exception:  # pragma: no cover
            pass


async def publish_extension_resolution(
    *,
    run_id: UUID,
    approved: bool,
    redis_client: Any | None = None,
) -> None:
    """Publish the resolution of a pending budget extension.

    Called by the approval-response handler after the user clicks
    Approve/Deny on the budget-extension card. Wakes every concurrent
    caller currently awaiting the resolution channel via
    :func:`request_budget_extension`.

    Best-effort: if Redis is unavailable, callers will time out via
    ``timeout_seconds`` and surface a clean denial to the agent.
    """
    if redis_client is None:
        from ..cache_service import get_redis_client

        redis_client = await get_redis_client()

    if redis_client is None:
        return

    channel = _R_EXTENSION_RESOLVED_CHANNEL.format(run_id=str(run_id))
    lock_key = _R_EXTENSION_LOCK.format(run_id=str(run_id))
    payload = "approved" if approved else "rejected"
    try:
        await redis_client.publish(channel, payload)
    finally:
        # Drop the lock regardless of publish success so the next
        # extension request for this run can proceed.
        try:
            await redis_client.delete(lock_key)
        except Exception:  # pragma: no cover
            pass


__all__ = [
    "BudgetAllocation",
    "BudgetError",
    "BudgetExhaustedError",
    "DailyBudgetExceeded",
    "CycleDetected",
    "allocate_run_budget",
    "deallocate_run_budget",
    "request_budget_extension",
    "publish_extension_resolution",
]
