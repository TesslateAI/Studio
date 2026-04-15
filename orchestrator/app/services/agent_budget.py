"""Budget interceptor for multi-agent orchestration.

Per-agent monthly USD caps enforced from the ``agent_budgets`` table.

Lookup precedence for ``check_budget``:

1. (agent_id, project_id) — project-scoped override.
2. (agent_id, NULL) — agent-wide fallback.
3. No row — unlimited (``ok=True``).

The module is defensive: malformed rows, unexpected dialect errors, or
missing sessions must never raise out of ``check_budget`` — logging at
``debug`` level and returning ``ok=True`` is preferred so the budget can
never become a correctness-critical dependency.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentBudget

logger = logging.getLogger(__name__)

RESET_WINDOW_DAYS = 30


@dataclass(frozen=True)
class BudgetStatus:
    ok: bool
    remaining_usd: Decimal
    reason: str | None = None


_UNLIMITED = BudgetStatus(ok=True, remaining_usd=Decimal("Infinity"), reason=None)


async def _find_row(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> AgentBudget | None:
    if project_id is not None:
        stmt = select(AgentBudget).where(
            and_(
                AgentBudget.agent_id == agent_id,
                AgentBudget.project_id == project_id,
            )
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            return row
    stmt = select(AgentBudget).where(
        and_(AgentBudget.agent_id == agent_id, AgentBudget.project_id.is_(None))
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def check_budget(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    pending_usd: Decimal | float | int = 0,
) -> BudgetStatus:
    """Decide whether a pending spend is within the agent's monthly cap."""
    try:
        row = await _find_row(session, agent_id=agent_id, project_id=project_id)
        if row is None:
            return _UNLIMITED
        limit = Decimal(row.monthly_limit_usd)
        spent = Decimal(row.spent_usd)
        pending = Decimal(pending_usd)
        remaining = limit - spent
        if spent + pending > limit:
            return BudgetStatus(
                ok=False,
                remaining_usd=remaining if remaining > 0 else Decimal(0),
                reason="monthly budget exhausted",
            )
        return BudgetStatus(ok=True, remaining_usd=remaining, reason=None)
    except Exception as exc:  # pragma: no cover - defense-in-depth
        logger.debug("check_budget degraded to unlimited: %s", exc)
        return _UNLIMITED


async def record_spend(
    session: AsyncSession,
    *,
    agent_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    amount_usd: Decimal | float | int,
) -> None:
    """Increment ``spent_usd`` on the most specific matching row.

    Does not create rows — callers are responsible for provisioning budgets
    before recording spend against them.
    """
    try:
        amount = Decimal(amount_usd)
        row = await _find_row(session, agent_id=agent_id, project_id=project_id)
        if row is None:
            return
        stmt = (
            update(AgentBudget)
            .where(AgentBudget.id == row.id)
            .values(spent_usd=AgentBudget.spent_usd + amount)
            .execution_options(synchronize_session=False)
        )
        await session.execute(stmt)
        await session.commit()
    except Exception as exc:  # pragma: no cover - defense-in-depth
        logger.debug("record_spend swallowed unexpected error: %s", exc)


async def reset_if_due(session: AsyncSession) -> int:
    """Zero out ``spent_usd`` on any row whose window has elapsed.

    Returns the number of rows reset.
    """
    try:
        now = datetime.now(UTC)
        next_reset = now + timedelta(days=RESET_WINDOW_DAYS)
        stmt = (
            update(AgentBudget)
            .where(AgentBudget.reset_at <= now)
            .values(spent_usd=Decimal(0), reset_at=next_reset)
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount or 0
    except Exception as exc:  # pragma: no cover - defense-in-depth
        logger.debug("reset_if_due swallowed unexpected error: %s", exc)
        return 0


async def _litellm_budget_success_handler(
    kwargs: dict, completion_response: object, start_time: object, end_time: object
) -> None:  # noqa: ARG001
    """LiteLLM async success callback that records spend against agent budgets.

    Activated by ``register_litellm_budget_callback()``.  Callers must pass
    ``metadata={"agent_id": "<uuid>", "project_id": "<uuid>"}`` in the
    LiteLLM completion kwargs for spend to be attributed correctly.  Calls
    without metadata are silently skipped.
    """
    try:
        import litellm

        metadata: dict = (kwargs.get("litellm_params") or {}).get("metadata") or {}
        raw_agent_id = metadata.get("agent_id")
        raw_project_id = metadata.get("project_id")
        if not raw_agent_id:
            return

        import uuid as _uuid

        agent_id = _uuid.UUID(raw_agent_id)
        project_id = _uuid.UUID(raw_project_id) if raw_project_id else None

        try:
            cost = Decimal(str(litellm.completion_cost(completion_response=completion_response)))
        except Exception:
            cost = Decimal(0)

        from ..database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await record_spend(session, agent_id=agent_id, project_id=project_id, amount_usd=cost)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("_litellm_budget_success_handler: %s", exc)


def register_litellm_budget_callback() -> None:
    """Register the budget success handler with LiteLLM (idempotent).

    Call once at application startup (e.g. from ``main.py`` lifespan).
    Safe to call multiple times — duplicate registrations are filtered out.
    """
    try:
        import litellm

        if _litellm_budget_success_handler not in litellm.success_callback:
            litellm.success_callback.append(_litellm_budget_success_handler)
            logger.debug("agent_budget: LiteLLM success_callback registered")
    except Exception as exc:  # pragma: no cover - litellm may not be installed in all envs
        logger.debug("agent_budget: failed to register LiteLLM callback: %s", exc)


__all__ = [
    "BudgetStatus",
    "check_budget",
    "record_spend",
    "reset_if_due",
    "register_litellm_budget_callback",
]
