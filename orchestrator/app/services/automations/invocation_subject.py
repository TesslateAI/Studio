"""InvocationSubject resolver — unified billing + token identity (Phase 2).

Today three separate code paths handle billing routing:

* ``services/apps/billing_dispatcher.py`` settles ``wallet_mix`` for apps.
* ``services/credit_service.py`` debits user OpenSail credits.
* ``services/apps/key_lifecycle.py`` mints LiteLLM virtual keys with budgets.

Each path writes its own attribution columns onto ``spend_records``.
``InvocationSubject`` collapses all three into a *single* resolved
decision per :class:`AutomationRun` so every spend row, every minted key,
and every audit event joins back to the same identity row by a single
``invocation_subject_id`` column. After this lands the manager-dashboard
query "spend by app per user in March" is one ``GROUP BY``.

Decision order (deterministic — same automation always picks the same
source so the audit trail is reproducible):

1. **Parent run wins.** If a ``parent_run`` is supplied the child inherits
   its parent's billing — ``payer_policy='parent_run'``,
   ``credit_source='parent_run'``. The child still gets its own
   ``InvocationSubject`` row (so the spend rollup graph is a tree); the
   row points at the parent via ``parent_run_id``.
2. **Contract override.** ``automation.contract['payer_policy']`` (and the
   optional ``contract['credit_source']``) win over the manifest default.
3. **App manifest default.** When the action targets an ``AppAction``,
   ``app_action.billing.{ai_compute|general_compute}.payer_default`` is
   used. The orchestrator picks ``ai_compute`` first, then
   ``general_compute``, since the dominant cost on every hosted-agent
   action is the LLM call.
4. **Default: installer pays.** The user who created the automation
   (resolved via ``automation.attribution_user_id`` for shared-singleton
   billing, falling back to ``automation.owner_user_id``).

Once ``payer_policy`` is decided, ``credit_source`` is derived from a
fixed bridge table — see :data:`_PAYER_TO_CREDIT_SOURCE` below. The bridge
keeps the wiring honest: every supported payer policy has exactly one
credit_source, and the mapping is the only place we couple the
``InvocationSubject`` to the underlying services.

This module is INTENTIONALLY a wrapper. It does not rewrite
``billing_dispatcher`` / ``credit_service`` / ``key_lifecycle`` — it just
calls them with consistent attribution. Phase 2C will fill in the actual
``key_lifecycle.mint_with_budget`` invocation; until then ``litellm_key_id``
is left ``None`` for ``scoped_litellm_key`` subjects so the dispatcher
preflight can enforce policy without a live LiteLLM upstream.

See ``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
section "InvocationSubject — unified billing and token identity".
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SpendRecord
from ...models_automations import (
    AppAction,
    AppInstance,
    AutomationDefinition,
    AutomationRun,
    InvocationSubject,
)

logger = logging.getLogger(__name__)


__all__ = [
    "PayerPolicy",
    "CreditSource",
    "BudgetEnvelope",
    "ResolvedSubject",
    "InvocationSubjectError",
    "ParentRunCycleError",
    "ParentRunBudgetExhausted",
    "resolve_invocation_subject",
    "settle_subject_spend",
]


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class PayerPolicy(StrEnum):
    """Who owes the money for this run."""

    INSTALLER = "installer"
    CREATOR = "creator"
    TEAM = "team"
    PLATFORM = "platform"
    BYOK = "byok"
    PARENT_RUN = "parent_run"


class CreditSource(StrEnum):
    """Which underlying ledger the dispatcher debits."""

    OPENSAIL_CREDITS = "opensail_credits"
    SCOPED_LITELLM_KEY = "scoped_litellm_key"
    BYOK_LITELLM_KEY = "byok_litellm_key"
    CREATOR_WALLET = "creator_wallet"
    TEAM_CREDITS = "team_credits"
    PLATFORM_BUDGET = "platform_budget"
    PARENT_RUN = "parent_run"


@dataclass(frozen=True)
class BudgetEnvelope:
    """Computed spend caps for a single resolved subject."""

    max_usd_per_run: Decimal | None
    max_usd_per_day: Decimal | None

    def to_dict(self) -> dict[str, str | None]:
        """JSON-safe representation for the ``budget_envelope`` JSONB column."""
        return {
            "max_usd_per_run": (
                None if self.max_usd_per_run is None else str(self.max_usd_per_run)
            ),
            "max_usd_per_day": (
                None if self.max_usd_per_day is None else str(self.max_usd_per_day)
            ),
        }


@dataclass(frozen=True)
class ResolvedSubject:
    """Snapshot of a freshly-inserted ``InvocationSubject`` row.

    Returned by :func:`resolve_invocation_subject` so callers don't need
    to re-fetch the row to know the resolved decision. The id matches the
    persisted row's primary key.
    """

    id: UUID
    payer_policy: PayerPolicy
    credit_source: CreditSource
    credit_source_ref: str | None
    litellm_key_id: str | None
    budget_envelope: BudgetEnvelope
    parent_run_id: UUID | None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvocationSubjectError(Exception):
    """Base class for resolver errors."""


class ParentRunCycleError(InvocationSubjectError):
    """Raised when ``payer_policy='parent_run'`` resolution detects a cycle.

    Should never happen in practice (``automation_definitions`` enforces
    ``depth IN (0, 1)`` and the dispatcher refuses to enqueue a run whose
    parent points at itself), but the resolver belt-and-braces against
    a misconfigured row corrupting the chain.
    """


class ParentRunBudgetExhausted(InvocationSubjectError):
    """Parent's ``budget_envelope.max_usd_per_run`` is already spent."""


# ---------------------------------------------------------------------------
# Bridge: payer_policy → credit_source (single source of truth)
# ---------------------------------------------------------------------------

# Default mapping. The contract MAY override the credit_source explicitly
# (e.g. an installer paying via ``scoped_litellm_key`` rather than raw
# ``opensail_credits``); when it does, we accept any credit_source whose
# membership in the resolved payer_policy's "compatible set" is sane.
_PAYER_TO_CREDIT_SOURCE: dict[PayerPolicy, CreditSource] = {
    PayerPolicy.INSTALLER: CreditSource.OPENSAIL_CREDITS,
    PayerPolicy.CREATOR: CreditSource.CREATOR_WALLET,
    PayerPolicy.TEAM: CreditSource.TEAM_CREDITS,
    PayerPolicy.PLATFORM: CreditSource.PLATFORM_BUDGET,
    PayerPolicy.BYOK: CreditSource.BYOK_LITELLM_KEY,
    PayerPolicy.PARENT_RUN: CreditSource.PARENT_RUN,
}


# Cycle-detection limit. We walk the parent chain at most this deep before
# bailing — ``automation_definitions.depth`` is capped at 1 today, so a
# chain longer than 4 means something has gone catastrophically wrong.
_MAX_PARENT_CHAIN_DEPTH = 8


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


async def resolve_invocation_subject(
    db: AsyncSession,
    *,
    automation_run: AutomationRun,
    automation: AutomationDefinition,
    parent_run: AutomationRun | None = None,
) -> ResolvedSubject:
    """Resolve and persist an :class:`InvocationSubject` for ``automation_run``.

    The resolver is deterministic — the same ``(automation, parent_run)``
    pair always picks the same ``payer_policy`` and ``credit_source``.
    The decision is recorded on the persisted row so the audit trail can
    explain after the fact why this particular run drew from this
    particular wallet.

    Concurrency: the caller is expected to call this exactly once per
    ``AutomationRun.id`` from inside the dispatcher's preflight phase.
    The row carries no unique constraint on ``automation_run_id`` because
    ``InvocationSubject`` rows MAY exist without a run anchor (direct
    manual invocations) — duplicates would only land here if the
    dispatcher re-entered preflight for an already-resolved run, which is
    a bug the dispatcher already prevents via its idempotency upsert.

    Args:
        db: Async session — the caller owns commit semantics.
        automation_run: The freshly-upserted ``automation_runs`` row.
        automation: The owning ``automation_definitions`` row.
        parent_run: When set, the new subject inherits this run's billing.
            The contract / manifest decision tree is short-circuited.

    Returns:
        :class:`ResolvedSubject` snapshot of the persisted row.

    Raises:
        ParentRunCycleError: ``parent_run`` chain is malformed.
        ParentRunBudgetExhausted: parent's per-run cap is already spent.
    """
    contract = automation.contract or {}

    # ---- 1. payer_policy ------------------------------------------------
    if parent_run is not None:
        await _validate_parent_chain(db, parent_run)
        payer_policy = PayerPolicy.PARENT_RUN
    else:
        payer_policy = await _decide_payer_policy(
            db, automation=automation, contract=contract
        )

    # ---- 2. credit_source -----------------------------------------------
    credit_source = _decide_credit_source(payer_policy, contract=contract)

    # ---- 3. credit_source_ref + invoking_user_id ------------------------
    invoking_user_id = automation.attribution_user_id or automation.owner_user_id
    credit_source_ref = await _resolve_credit_source_ref(
        db,
        payer_policy=payer_policy,
        credit_source=credit_source,
        automation=automation,
        invoking_user_id=invoking_user_id,
        parent_run=parent_run,
    )

    # ---- 4. budget_envelope ---------------------------------------------
    budget = await _compute_budget_envelope(
        db, contract=contract, parent_run=parent_run
    )

    # ---- 5. (Phase 2C) optional scoped key mint -------------------------
    # ``key_lifecycle.mint_with_budget`` lands in Phase 2C. When it does,
    # this is the single place that calls it. Until then we leave
    # ``litellm_key_id`` NULL; the dispatcher preflight still has all the
    # routing information it needs from ``credit_source``.
    litellm_key_id: str | None = None
    if credit_source == CreditSource.SCOPED_LITELLM_KEY:
        logger.debug(
            "invocation_subject.resolve: scoped_litellm_key requested; "
            "mint deferred to Phase 2C — leaving litellm_key_id=NULL run=%s",
            automation_run.id,
        )

    # ---- 6. Persist + return snapshot -----------------------------------
    parent_run_id = parent_run.id if parent_run is not None else None
    app_instance_id, app_action_id = await _resolve_app_anchors(
        db, automation_run=automation_run, automation=automation
    )

    subject = InvocationSubject(
        id=uuid.uuid4(),
        automation_run_id=automation_run.id,
        invoking_user_id=invoking_user_id,
        team_id=automation.team_id,
        app_instance_id=app_instance_id,
        app_action_id=app_action_id,
        agent_id=None,  # Filled by the agent.run executor when it loads the agent row.
        payer_policy=payer_policy.value,
        parent_run_id=parent_run_id,
        credit_source=credit_source.value,
        credit_source_ref=credit_source_ref,
        budget_envelope=budget.to_dict(),
        spent_so_far_usd=Decimal("0"),
        litellm_key_id=litellm_key_id,
    )
    db.add(subject)
    await db.flush()

    logger.info(
        "invocation_subject.resolve: subject=%s run=%s payer=%s "
        "credit_source=%s ref=%s budget_per_run=%s parent=%s",
        subject.id,
        automation_run.id,
        payer_policy.value,
        credit_source.value,
        credit_source_ref,
        budget.max_usd_per_run,
        parent_run_id,
    )

    return ResolvedSubject(
        id=subject.id,
        payer_policy=payer_policy,
        credit_source=credit_source,
        credit_source_ref=credit_source_ref,
        litellm_key_id=litellm_key_id,
        budget_envelope=budget,
        parent_run_id=parent_run_id,
    )


# ---------------------------------------------------------------------------
# Decision helpers
# ---------------------------------------------------------------------------


async def _decide_payer_policy(
    db: AsyncSession,
    *,
    automation: AutomationDefinition,
    contract: dict[str, Any],
) -> PayerPolicy:
    """Order: contract.payer_policy → app manifest default → installer."""
    raw = contract.get("payer_policy")
    if raw is not None:
        return _coerce_payer_policy(raw, source="contract.payer_policy")

    # App manifest default — only applies when the automation's first
    # action is an ``app.invoke`` and the targeted ``AppAction`` declares
    # a ``billing.{ai_compute|general_compute}.payer_default``.
    manifest_default = await _app_manifest_payer_default(db, automation=automation)
    if manifest_default is not None:
        return manifest_default

    return PayerPolicy.INSTALLER


def _coerce_payer_policy(raw: Any, *, source: str) -> PayerPolicy:
    try:
        return PayerPolicy(raw)
    except (ValueError, TypeError) as exc:
        raise InvocationSubjectError(
            f"{source}={raw!r} is not a valid payer_policy"
        ) from exc


def _coerce_credit_source(raw: Any, *, source: str) -> CreditSource:
    try:
        return CreditSource(raw)
    except (ValueError, TypeError) as exc:
        raise InvocationSubjectError(
            f"{source}={raw!r} is not a valid credit_source"
        ) from exc


def _decide_credit_source(
    payer_policy: PayerPolicy, *, contract: dict[str, Any]
) -> CreditSource:
    """Bridge ``payer_policy`` → ``credit_source`` with optional override.

    The default is :data:`_PAYER_TO_CREDIT_SOURCE`. The contract may
    override (e.g. ``payer_policy='installer'`` paying via
    ``scoped_litellm_key`` instead of raw ``opensail_credits``) but only
    within the allowed set per payer.
    """
    default = _PAYER_TO_CREDIT_SOURCE[payer_policy]
    override = contract.get("credit_source")
    if override is None:
        return default
    coerced = _coerce_credit_source(override, source="contract.credit_source")
    if coerced not in _allowed_credit_sources_for(payer_policy):
        raise InvocationSubjectError(
            f"contract.credit_source={coerced.value!r} not allowed for "
            f"payer_policy={payer_policy.value!r}"
        )
    return coerced


def _allowed_credit_sources_for(payer_policy: PayerPolicy) -> set[CreditSource]:
    """Whitelist of credit sources compatible with each payer policy.

    Kept narrow: every entry must be reachable through an existing
    service. Adding e.g. ``CREATOR_WALLET`` to the installer set would
    require a settlement path that doesn't exist today, so it stays out.
    """
    if payer_policy == PayerPolicy.INSTALLER:
        return {
            CreditSource.OPENSAIL_CREDITS,
            CreditSource.SCOPED_LITELLM_KEY,
            CreditSource.BYOK_LITELLM_KEY,
        }
    if payer_policy == PayerPolicy.CREATOR:
        return {CreditSource.CREATOR_WALLET}
    if payer_policy == PayerPolicy.TEAM:
        return {CreditSource.TEAM_CREDITS, CreditSource.SCOPED_LITELLM_KEY}
    if payer_policy == PayerPolicy.PLATFORM:
        return {CreditSource.PLATFORM_BUDGET}
    if payer_policy == PayerPolicy.BYOK:
        return {CreditSource.BYOK_LITELLM_KEY}
    if payer_policy == PayerPolicy.PARENT_RUN:
        return {CreditSource.PARENT_RUN}
    raise InvocationSubjectError(f"unknown payer_policy {payer_policy!r}")


async def _app_manifest_payer_default(
    db: AsyncSession, *, automation: AutomationDefinition
) -> PayerPolicy | None:
    """Lookup the app's manifest default for the automation's first action.

    Returns ``None`` when:
    * The automation has no action rows.
    * The first action is not ``action_type='app.invoke'``.
    * The targeted ``AppAction`` row is gone.
    * The action's billing block declares no ``payer_default``.

    All four cases fall through to the installer default upstream.
    """
    from ...models_automations import AutomationAction

    first_action = (
        await db.execute(
            select(AutomationAction)
            .where(AutomationAction.automation_id == automation.id)
            .order_by(AutomationAction.ordinal.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if first_action is None or first_action.action_type != "app.invoke":
        return None
    if first_action.app_action_id is None:
        return None

    app_action = (
        await db.execute(
            select(AppAction).where(AppAction.id == first_action.app_action_id)
        )
    ).scalar_one_or_none()
    if app_action is None or not app_action.billing:
        return None

    billing = app_action.billing
    # ai_compute is the dominant cost on every hosted-agent action; only
    # fall back to general_compute when ai_compute declares no default.
    for dim_key in ("ai_compute", "general_compute"):
        dim = (billing or {}).get(dim_key) or {}
        raw = dim.get("payer_default")
        if raw is not None:
            return _coerce_payer_policy(
                raw, source=f"app_action.billing.{dim_key}.payer_default"
            )
    return None


async def _resolve_credit_source_ref(
    db: AsyncSession,
    *,
    payer_policy: PayerPolicy,
    credit_source: CreditSource,
    automation: AutomationDefinition,
    invoking_user_id: UUID | None,
    parent_run: AutomationRun | None,
) -> str | None:
    """Stamp a stable pointer into the underlying ledger.

    The returned string is opaque from this module's perspective — the
    settle helper and downstream services know how to interpret it
    based on ``credit_source``. The shape per source:

    * ``opensail_credits`` → ``str(invoking_user_id)``.
    * ``team_credits`` → ``str(automation.team_id)``.
    * ``creator_wallet`` → wallet routing happens inside
      ``billing_dispatcher.record_spend`` — the ref is the creator's
      ``users.id`` once the app instance is known. We persist NULL here
      and let the dispatcher resolve it per-spend (so a later
      app_instance.update of wallet_mix doesn't strand the subject).
    * ``parent_run`` → ``str(parent_run.id)``.
    * ``platform_budget`` → ``None`` — the platform isn't a wallet, just
      a sentinel that no debit takes place.
    * ``scoped_litellm_key`` → NULL until Phase 2C mints the key.
    * ``byok_litellm_key`` → NULL — the actual key is fetched
      Fernet-decrypted at request time from ``UserMcpConfig``.
    """
    if credit_source == CreditSource.OPENSAIL_CREDITS:
        return str(invoking_user_id) if invoking_user_id is not None else None
    if credit_source == CreditSource.TEAM_CREDITS:
        return str(automation.team_id) if automation.team_id is not None else None
    if credit_source == CreditSource.PARENT_RUN:
        return str(parent_run.id) if parent_run is not None else None
    return None


async def _compute_budget_envelope(
    db: AsyncSession,
    *,
    contract: dict[str, Any],
    parent_run: AutomationRun | None,
) -> BudgetEnvelope:
    """Derive the envelope from contract caps, intersected with parent's remaining.

    Per-run cap precedence: contract → parent_run remaining → uncapped.
    Per-day cap precedence: contract → uncapped (parent's per-day cap is
    handled at parent settlement time, not duplicated onto the child).

    The parent's effective per-run cap is the parent's
    ``InvocationSubject.budget_envelope.max_usd_per_run`` minus
    ``InvocationSubject.spent_so_far_usd``. We refetch the parent subject
    here rather than relying on the (denormalized) ``automation_runs``
    columns so we never bill the child against a stale rollup.
    """
    per_run = _decimal_or_none(contract.get("max_spend_per_run_usd"))
    per_day = _decimal_or_none(contract.get("max_spend_per_day_usd"))

    if parent_run is None:
        return BudgetEnvelope(max_usd_per_run=per_run, max_usd_per_day=per_day)

    parent_subject = (
        await db.execute(
            select(InvocationSubject)
            .where(InvocationSubject.automation_run_id == parent_run.id)
            .order_by(InvocationSubject.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if parent_subject is None:
        return BudgetEnvelope(max_usd_per_run=per_run, max_usd_per_day=per_day)

    parent_per_run = _decimal_or_none(
        (parent_subject.budget_envelope or {}).get("max_usd_per_run")
    )
    if parent_per_run is None:
        return BudgetEnvelope(max_usd_per_run=per_run, max_usd_per_day=per_day)

    spent = Decimal(parent_subject.spent_so_far_usd or 0)
    remaining = parent_per_run - spent
    if remaining <= 0:
        raise ParentRunBudgetExhausted(
            f"parent run {parent_run.id} per-run cap "
            f"{parent_per_run} already spent ({spent})"
        )
    capped = remaining if per_run is None else min(per_run, remaining)
    return BudgetEnvelope(max_usd_per_run=capped, max_usd_per_day=per_day)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise InvocationSubjectError(
            f"cannot coerce {value!r} to Decimal for budget envelope"
        ) from exc


async def _resolve_app_anchors(
    db: AsyncSession,
    *,
    automation_run: AutomationRun,
    automation: AutomationDefinition,
) -> tuple[UUID | None, UUID | None]:
    """Best-effort lookup of (app_instance_id, app_action_id) for the run.

    These columns are denormalized so the manager dashboard query can
    GROUP BY app without joining through ``automation_actions``. We tolerate
    NULL on both — agent.run and gateway.send actions have no app_action,
    and an app.invoke action whose row was reaped by mid-flight cleanup
    just records the missing anchors.
    """
    from ...models_automations import AutomationAction

    first_action = (
        await db.execute(
            select(AutomationAction)
            .where(AutomationAction.automation_id == automation.id)
            .order_by(AutomationAction.ordinal.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if first_action is None:
        return None, None

    app_action_id = first_action.app_action_id
    app_instance_id: UUID | None = None
    config = first_action.config or {}
    raw_instance = config.get("app_instance_id")
    if isinstance(raw_instance, str):
        try:
            app_instance_id = UUID(raw_instance)
        except ValueError:
            app_instance_id = None
    elif isinstance(raw_instance, UUID):
        app_instance_id = raw_instance

    # Defensive: confirm the row still exists; if it was uninstalled mid-flight
    # we'd rather record NULL than dangle an FK to a gone row.
    if app_instance_id is not None:
        exists = (
            await db.execute(
                select(AppInstance.id).where(AppInstance.id == app_instance_id)
            )
        ).scalar_one_or_none()
        if exists is None:
            app_instance_id = None

    return app_instance_id, app_action_id


# ---------------------------------------------------------------------------
# Parent chain validation
# ---------------------------------------------------------------------------


async def _validate_parent_chain(db: AsyncSession, parent_run: AutomationRun) -> None:
    """Walk the parent chain, raising on cycles or runaway depth.

    Cycle detection is by id-set membership. Each subject row's
    ``parent_run_id`` points at an ``automation_runs.id``; we walk via the
    most-recent ``InvocationSubject`` row for each run. A cycle would be
    an automation builder bug; a depth blow-up would be a configuration
    mistake — both surface as :class:`ParentRunCycleError`.
    """
    seen: set[UUID] = set()
    cursor: UUID | None = parent_run.id
    depth = 0
    while cursor is not None:
        if cursor in seen:
            raise ParentRunCycleError(
                f"parent run chain cycles back to {cursor}"
            )
        seen.add(cursor)
        depth += 1
        if depth > _MAX_PARENT_CHAIN_DEPTH:
            raise ParentRunCycleError(
                f"parent run chain exceeds depth {_MAX_PARENT_CHAIN_DEPTH}"
            )

        # Find the InvocationSubject for this run (most recent row).
        next_subject = (
            await db.execute(
                select(InvocationSubject.parent_run_id)
                .where(InvocationSubject.automation_run_id == cursor)
                .order_by(InvocationSubject.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        cursor = next_subject


# ---------------------------------------------------------------------------
# Spend settlement helper
# ---------------------------------------------------------------------------


async def settle_subject_spend(
    db: AsyncSession,
    *,
    subject_id: UUID,
    spend_usd: Decimal,
    dimension: str,
    record_kwargs: dict[str, Any] | None = None,
) -> SpendRecord:
    """Append a ``SpendRecord`` keyed to ``subject_id`` and update its rolling total.

    This is a thin wrapper over the existing
    ``services/apps/billing_dispatcher.record_spend`` for ``app.invoke``
    spend, plus a direct ``SpendRecord`` insert for the non-app paths
    (``opensail_credits``, ``platform_budget``, etc.) that
    ``billing_dispatcher`` doesn't cover.

    What this guarantees:

    * Every emitted ``SpendRecord`` row has ``invocation_subject_id``
      stamped — that's the load-bearing column for the manager dashboard.
    * ``InvocationSubject.spent_so_far_usd`` is bumped atomically with
      the insert (single ``flush``).
    * If the subject's ``payer_policy='parent_run'``, the parent's
      ``spend_so_far_usd`` is debited too — so a child run's spend rolls
      up the chain naturally.

    Idempotency lives upstream: callers are expected to dedupe on
    ``record_kwargs['meta']['request_id']`` before calling this. We
    intentionally don't reach into ``billing_dispatcher`` to share the
    request_id fast path because that path only activates when an
    ``app_instance_id`` is in play.

    Caller owns commit semantics — we ``flush`` so the row is visible to
    subsequent SELECTs in the same transaction but do NOT commit.

    Args:
        db: Async session.
        subject_id: ``invocation_subjects.id`` to attribute against.
        spend_usd: Non-negative amount in USD.
        dimension: One of the six SpendRecord dimensions
            (ai_compute / general_compute / storage / egress /
            mcp_tool_call / platform_fee).
        record_kwargs: Extra fields to persist on the SpendRecord row
            (litellm_key_id, usage_log_id, session_id, meta, etc.).

    Returns:
        The freshly-inserted ``SpendRecord`` row.

    Raises:
        InvocationSubjectError: subject not found or spend negative.
    """
    if spend_usd < 0:
        raise InvocationSubjectError(
            f"spend_usd must be non-negative, got {spend_usd!r}"
        )

    subject = (
        await db.execute(
            select(InvocationSubject).where(InvocationSubject.id == subject_id)
        )
    ).scalar_one_or_none()
    if subject is None:
        raise InvocationSubjectError(
            f"invocation_subject {subject_id} not found"
        )

    record_kwargs = dict(record_kwargs or {})
    payer_str = _payer_str_for_spend_record(subject.payer_policy)

    spend = SpendRecord(
        id=uuid.uuid4(),
        app_instance_id=subject.app_instance_id,
        session_id=record_kwargs.get("session_id"),
        installer_user_id=subject.invoking_user_id,
        dimension=dimension,
        payer=payer_str,
        payer_user_id=record_kwargs.get("payer_user_id"),
        amount_usd=Decimal(spend_usd),
        litellm_key_id=record_kwargs.get("litellm_key_id")
        or subject.litellm_key_id,
        usage_log_id=record_kwargs.get("usage_log_id"),
        settled=False,
        automation_run_id=subject.automation_run_id,
        invocation_subject_id=subject.id,
        agent_id=subject.agent_id,
        meta=record_kwargs.get("meta") or {},
    )
    db.add(spend)

    # Atomic rollup: bump the subject's running total in the same flush.
    subject.spent_so_far_usd = Decimal(subject.spent_so_far_usd or 0) + Decimal(
        spend_usd
    )

    # Walk the parent chain and roll the child's spend up to each ancestor's
    # InvocationSubject row + its automation_runs row. This is the
    # "parent_run debits parent's spent_so_far_usd" guarantee from the plan.
    if subject.parent_run_id is not None:
        await _rollup_to_parent_chain(
            db,
            from_subject=subject,
            spend_usd=Decimal(spend_usd),
        )

    await db.flush()

    logger.info(
        "invocation_subject.settle: subject=%s spend=%s dim=%s payer=%s "
        "running_total=%s",
        subject.id,
        spend_usd,
        dimension,
        payer_str,
        subject.spent_so_far_usd,
    )
    return spend


async def _rollup_to_parent_chain(
    db: AsyncSession,
    *,
    from_subject: InvocationSubject,
    spend_usd: Decimal,
) -> None:
    """Bump ``spent_so_far_usd`` on every ancestor InvocationSubject + run.

    The walk uses ``parent_run_id`` on each subject. We bound the walk by
    :data:`_MAX_PARENT_CHAIN_DEPTH` for the same reason
    :func:`_validate_parent_chain` does.
    """
    cursor_run_id: UUID | None = from_subject.parent_run_id
    seen: set[UUID] = set()
    depth = 0
    while cursor_run_id is not None:
        if cursor_run_id in seen:
            logger.warning(
                "invocation_subject.rollup: cycle detected at run=%s; halting",
                cursor_run_id,
            )
            return
        seen.add(cursor_run_id)
        depth += 1
        if depth > _MAX_PARENT_CHAIN_DEPTH:
            logger.warning(
                "invocation_subject.rollup: depth %s exceeds max; halting",
                depth,
            )
            return

        ancestor = (
            await db.execute(
                select(InvocationSubject)
                .where(InvocationSubject.automation_run_id == cursor_run_id)
                .order_by(InvocationSubject.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if ancestor is None:
            cursor_run_id = None
            continue

        ancestor.spent_so_far_usd = Decimal(
            ancestor.spent_so_far_usd or 0
        ) + spend_usd

        # Bump AutomationRun.spend_usd in lockstep so per-run dashboard
        # rollups don't need to JOIN through invocation_subjects.
        run_row = (
            await db.execute(
                select(AutomationRun).where(
                    AutomationRun.id == ancestor.automation_run_id
                )
            )
        ).scalar_one_or_none()
        if run_row is not None:
            run_row.spend_usd = Decimal(run_row.spend_usd or 0) + spend_usd

        cursor_run_id = ancestor.parent_run_id


def _payer_str_for_spend_record(payer_policy: str) -> str:
    """Map our :class:`PayerPolicy` onto :class:`SpendRecord.payer`'s legal set.

    ``SpendRecord.payer`` only accepts ``creator | platform | installer | byok``
    today (constraint pre-dates ``InvocationSubject``). We collapse the new
    policies onto the closest legacy bucket so the SpendRecord CHECK
    constraint stays satisfied. The full payer_policy is always
    recoverable via ``InvocationSubject.payer_policy``, so no information
    is lost.
    """
    mapping = {
        PayerPolicy.INSTALLER.value: "installer",
        PayerPolicy.CREATOR.value: "creator",
        PayerPolicy.TEAM.value: "installer",  # team rolls up to the human invoker
        PayerPolicy.PLATFORM.value: "platform",
        PayerPolicy.BYOK.value: "byok",
        PayerPolicy.PARENT_RUN.value: "installer",  # parent's installer is the human payer
    }
    return mapping.get(payer_policy, "installer")
