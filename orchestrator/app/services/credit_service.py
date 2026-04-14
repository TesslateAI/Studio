"""
Credit deduction service for real-time AI usage billing.

Handles pre-request credit checks, post-request deduction with
priority ordering (daily → bundled → bonus → purchased), and
UsageLog creation.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from .model_pricing import calculate_cost_cents

logger = logging.getLogger(__name__)


def _get_byok_prefixes() -> tuple[str, ...]:
    """Get BYOK provider prefixes from the canonical provider registry.

    Derives prefixes from BUILTIN_PROVIDERS in agent/models.py — the single
    source of truth for all supported providers. Adding a new provider there
    automatically makes it recognized as BYOK here.
    """
    try:
        from ..agent.models import get_byok_provider_prefixes

        return get_byok_provider_prefixes()
    except Exception:
        # Fallback only during early startup or import errors
        logger.debug("Could not load provider registry, using fallback BYOK prefixes")
        return (
            "openrouter/",
            "openai/",
            "groq/",
            "anthropic/",
            "together/",
            "deepseek/",
            "fireworks/",
            "nano-gpt/",
        )


def is_byok_model(model_name: str) -> bool:
    """Return True if the model uses the user's own API key (no credit charge)."""
    return any(model_name.startswith(p) for p in _get_byok_prefixes())


async def check_credits(user, model_name: str, team=None) -> tuple[bool, str]:
    """
    Pre-request guard: verify credits before making an LLM call.

    Checks team credits first (if team provided), falls back to user credits
    for backward compatibility during migration.

    Returns:
        (True, "") if user can proceed.
        (False, error_message) if insufficient credits.
    """
    if is_byok_model(model_name):
        return True, ""

    # Check team credits if available, otherwise fall back to user
    credit_source = team if team is not None else user
    if credit_source.total_credits <= 0:
        return False, (
            "You have no credits remaining. "
            "Please purchase credits or upgrade your plan to continue using AI features."
        )

    return True, ""


async def deduct_credits(
    db: AsyncSession,
    user_id: UUID,
    model_name: str,
    tokens_in: int,
    tokens_out: int,
    agent_id: UUID | None = None,
    project_id: UUID | None = None,
    team_id: UUID | None = None,
) -> dict:
    """
    Deduct credits from team (or user) balance and create a UsageLog entry.

    When team_id is provided, locks and deducts from the Team row.
    Falls back to user-level deduction for backward compatibility.

    Uses SELECT FOR UPDATE to prevent race conditions on concurrent requests.
    Deduction priority: daily → bundled → signup_bonus → purchased.

    Returns dict with cost_total, credits_deducted, new_balance, usage_log_id.
    """
    from ..models import UsageLog, User
    from ..models_team import Team

    byok = is_byok_model(model_name)

    # Calculate cost (0 for BYOK)
    if byok:
        cost_input, cost_output, cost_total = 0, 0, 0
    else:
        cost_input, cost_output, cost_total = await calculate_cost_cents(
            model_name, tokens_in, tokens_out
        )

    # Resolve team_id from project or user if not explicitly provided
    resolved_team_id = team_id
    if not resolved_team_id and project_id:
        from ..models import Project

        proj_result = await db.execute(select(Project.team_id).where(Project.id == project_id))
        resolved_team_id = proj_result.scalar_one_or_none()
    if not resolved_team_id:
        user_result = await db.execute(select(User.default_team_id).where(User.id == user_id))
        resolved_team_id = user_result.scalar_one_or_none()

    max_retries = 3
    for attempt in range(max_retries):
        try:
            credits_deducted = 0

            # Deduct from team if we have one, otherwise fall back to user
            if resolved_team_id:
                result = await db.execute(
                    select(Team).where(Team.id == resolved_team_id).with_for_update()
                )
                credit_source = result.scalar_one()
            else:
                result = await db.execute(select(User).where(User.id == user_id).with_for_update())
                credit_source = result.scalar_one()

            if not byok and cost_total > 0:
                remaining = cost_total

                # 1. Daily credits first
                daily = credit_source.daily_credits or 0
                if daily > 0 and remaining > 0:
                    take = min(daily, remaining)
                    credit_source.daily_credits = daily - take
                    remaining -= take
                    credits_deducted += take

                # 2. Bundled credits (monthly allowance)
                bundled = credit_source.bundled_credits or 0
                if bundled > 0 and remaining > 0:
                    take = min(bundled, remaining)
                    credit_source.bundled_credits = bundled - take
                    remaining -= take
                    credits_deducted += take

                # 3. Signup bonus credits (if not expired)
                bonus = credit_source.signup_bonus_credits or 0
                if bonus > 0 and remaining > 0:
                    from ..database import ensure_aware

                    _expires = ensure_aware(credit_source.signup_bonus_expires_at)
                    expired = bool(_expires and datetime.now(UTC) > _expires)
                    if not expired:
                        take = min(bonus, remaining)
                        credit_source.signup_bonus_credits = bonus - take
                        remaining -= take
                        credits_deducted += take

                # 4. Purchased credits (permanent, last resort)
                purchased = credit_source.purchased_credits or 0
                if purchased > 0 and remaining > 0:
                    take = min(purchased, remaining)
                    credit_source.purchased_credits = purchased - take
                    remaining -= take
                    credits_deducted += take

            # Create UsageLog entry with both user_id (attribution) and team_id (billing)
            usage_log = UsageLog(
                user_id=user_id,
                team_id=resolved_team_id,
                agent_id=agent_id,
                project_id=project_id,
                model=model_name,
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                cost_input=cost_input,
                cost_output=cost_output,
                cost_total=cost_total,
                is_byok=byok,
                billed_status="credited"
                if credits_deducted > 0
                else ("exempt" if byok else "pending"),
            )
            db.add(usage_log)

            await db.commit()
            await db.refresh(usage_log)
            break  # Success, exit retry loop
        except OperationalError as e:
            await db.rollback()
            if attempt < max_retries - 1:
                logger.warning(
                    f"Credit deduction retry {attempt + 1}/{max_retries} for user={user_id}: {e}"
                )
                continue
            logger.error(f"Credit deduction failed after {max_retries} retries for user={user_id}")
            raise

    new_balance = credit_source.total_credits

    logger.info(
        f"Credit deduction: user={user_id} team={resolved_team_id} model={model_name} "
        f"tokens_in={tokens_in} tokens_out={tokens_out} "
        f"cost={cost_total}¢ deducted={credits_deducted}¢ "
        f"balance={new_balance} byok={byok}"
    )

    return {
        "cost_total": cost_total,
        "credits_deducted": credits_deducted,
        "new_balance": new_balance,
        "usage_log_id": str(usage_log.id),
        "is_byok": byok,
    }
