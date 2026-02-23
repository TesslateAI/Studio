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


async def check_credits(user, model_name: str) -> tuple[bool, str]:
    """
    Pre-request guard: verify user has credits before making an LLM call.

    Returns:
        (True, "") if user can proceed.
        (False, error_message) if insufficient credits.
    """
    if is_byok_model(model_name):
        return True, ""

    if user.total_credits <= 0:
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
) -> dict:
    """
    Deduct credits from user balance and create a UsageLog entry.

    Uses SELECT FOR UPDATE to prevent race conditions on concurrent requests.
    Deduction priority: daily → bundled → signup_bonus → purchased.

    Returns dict with cost_total, credits_deducted, new_balance, usage_log_id.
    """
    from ..models import UsageLog, User

    byok = is_byok_model(model_name)

    # Calculate cost (0 for BYOK)
    if byok:
        cost_input, cost_output, cost_total = 0, 0, 0
    else:
        cost_input, cost_output, cost_total = await calculate_cost_cents(
            model_name, tokens_in, tokens_out
        )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Lock the user row to prevent concurrent deduction races
            result = await db.execute(select(User).where(User.id == user_id).with_for_update())
            user = result.scalar_one()

            credits_deducted = 0

            if not byok and cost_total > 0:
                remaining = cost_total

                # 1. Daily credits first
                daily = user.daily_credits or 0
                if daily > 0 and remaining > 0:
                    take = min(daily, remaining)
                    user.daily_credits = daily - take
                    remaining -= take
                    credits_deducted += take

                # 2. Bundled credits (monthly allowance)
                bundled = user.bundled_credits or 0
                if bundled > 0 and remaining > 0:
                    take = min(bundled, remaining)
                    user.bundled_credits = bundled - take
                    remaining -= take
                    credits_deducted += take

                # 3. Signup bonus credits (if not expired)
                bonus = user.signup_bonus_credits or 0
                if bonus > 0 and remaining > 0:
                    expired = (
                        user.signup_bonus_expires_at
                        and datetime.now(UTC) > user.signup_bonus_expires_at
                    )
                    if not expired:
                        take = min(bonus, remaining)
                        user.signup_bonus_credits = bonus - take
                        remaining -= take
                        credits_deducted += take

                # 4. Purchased credits (permanent, last resort)
                purchased = user.purchased_credits or 0
                if purchased > 0 and remaining > 0:
                    take = min(purchased, remaining)
                    user.purchased_credits = purchased - take
                    remaining -= take
                    credits_deducted += take

            # Create UsageLog entry (always, even for BYOK and 0-cost)
            usage_log = UsageLog(
                user_id=user_id,
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

    new_balance = user.total_credits

    logger.info(
        f"Credit deduction: user={user_id} model={model_name} "
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
