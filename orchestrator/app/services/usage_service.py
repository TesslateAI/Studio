"""
Usage tracking service for syncing LiteLLM usage data and calculating costs.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from ..models import (
    User,
    UsageLog,
    MarketplaceAgent,
    UserPurchasedAgent
)
from ..config import get_settings
from .litellm_service import LiteLLMService
from .stripe_service import stripe_service

logger = logging.getLogger(__name__)
settings = get_settings()


class UsageService:
    """
    Service for tracking and syncing usage data from LiteLLM.
    """

    def __init__(self):
        """Initialize usage service."""
        self.litellm = LiteLLMService()

    async def sync_user_usage(
        self,
        user: User,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        db: AsyncSession = None
    ) -> List[UsageLog]:
        """
        Sync usage data from LiteLLM for a specific user.

        Args:
            user: User to sync usage for
            start_date: Start date for usage sync
            end_date: End date for usage sync (defaults to now)
            db: Database session

        Returns:
            List of created usage log entries
        """
        if not user.litellm_api_key:
            logger.warning(f"User {user.id} has no LiteLLM API key")
            return []

        if end_date is None:
            end_date = datetime.now(timezone.utc)

        try:
            # Get usage data from LiteLLM
            usage_data = await self.litellm.get_user_usage(
                api_key=user.litellm_api_key,
                start_date=start_date
            )

            if not usage_data or "data" not in usage_data:
                logger.info(f"No usage data for user {user.id}")
                return []

            usage_logs = []

            for entry in usage_data["data"]:
                # Extract usage details
                model = entry.get("model", "unknown")
                tokens_input = entry.get("total_prompt_tokens", 0)
                tokens_output = entry.get("total_completion_tokens", 0)
                request_id = entry.get("request_id")

                # Check if already logged (idempotency)
                if request_id and db:
                    existing = await db.execute(
                        select(UsageLog).where(UsageLog.request_id == request_id)
                    )
                    if existing.scalar_one_or_none():
                        continue

                # Calculate costs based on agent pricing
                agent_id = entry.get("metadata", {}).get("agent_id")
                project_id = entry.get("metadata", {}).get("project_id")

                cost_input, cost_output, creator_id = await self._calculate_costs(
                    model=model,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    agent_id=UUID(agent_id) if agent_id else None,
                    user_id=user.id,
                    db=db
                )

                cost_total = cost_input + cost_output

                # Calculate revenue sharing if agent has a creator
                creator_revenue = 0
                platform_revenue = 0
                if creator_id:
                    creator_revenue = int(cost_total * settings.creator_revenue_share)
                    platform_revenue = cost_total - creator_revenue

                # Create usage log
                usage_log = UsageLog(
                    user_id=user.id,
                    agent_id=UUID(agent_id) if agent_id else None,
                    project_id=UUID(project_id) if project_id else None,
                    model=model,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    cost_input=cost_input,
                    cost_output=cost_output,
                    cost_total=cost_total,
                    creator_id=creator_id,
                    creator_revenue=creator_revenue,
                    platform_revenue=platform_revenue,
                    request_id=request_id,
                    billed_status="pending"
                )

                if db:
                    db.add(usage_log)
                    usage_logs.append(usage_log)

            if db and usage_logs:
                await db.commit()
                logger.info(f"Synced {len(usage_logs)} usage entries for user {user.id}")

            return usage_logs

        except Exception as e:
            logger.error(f"Failed to sync usage for user {user.id}: {e}")
            return []

    async def _calculate_costs(
        self,
        model: str,
        tokens_input: int,
        tokens_output: int,
        agent_id: Optional[UUID],
        user_id: UUID,
        db: Optional[AsyncSession]
    ) -> tuple[int, int, Optional[UUID]]:
        """
        Calculate costs for usage based on agent pricing or default LiteLLM pricing.

        Args:
            model: Model used
            tokens_input: Input tokens
            tokens_output: Output tokens
            agent_id: Agent ID (if using paid agent)
            user_id: User ID
            db: Database session

        Returns:
            Tuple of (cost_input_cents, cost_output_cents, creator_id)
        """
        creator_id = None

        # Check if user is using a paid API-based agent
        if agent_id and db:
            agent_result = await db.execute(
                select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
            )
            agent = agent_result.scalar_one_or_none()

            if agent and agent.pricing_type == "api":
                # Use agent's custom pricing
                cost_input_per_million = agent.api_pricing_input  # $ per million tokens
                cost_output_per_million = agent.api_pricing_output

                cost_input = int((tokens_input / 1_000_000) * cost_input_per_million * 100)  # Convert to cents
                cost_output = int((tokens_output / 1_000_000) * cost_output_per_million * 100)

                creator_id = agent.created_by_user_id
                return cost_input, cost_output, creator_id

        # Default pricing from LiteLLM (using approximate values)
        # This should ideally come from LiteLLM's model pricing data
        default_pricing = self._get_default_model_pricing(model)
        cost_input = int((tokens_input / 1_000_000) * default_pricing["input"] * 100)
        cost_output = int((tokens_output / 1_000_000) * default_pricing["output"] * 100)

        return cost_input, cost_output, None

    def _get_default_model_pricing(self, model: str) -> Dict[str, float]:
        """
        Get default pricing for a model.

        Args:
            model: Model name

        Returns:
            Dict with 'input' and 'output' prices per million tokens in USD
        """
        # Default pricing map (approximate values, should be updated from LiteLLM)
        pricing_map = {
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4-turbo": {"input": 10.00, "output": 30.00},
            "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
            "claude-3-opus": {"input": 15.00, "output": 75.00},
            "claude-3-sonnet": {"input": 3.00, "output": 15.00},
            "claude-3-haiku": {"input": 0.25, "output": 1.25},
            "gemini-pro": {"input": 0.50, "output": 1.50},
        }

        # Try exact match first
        if model in pricing_map:
            return pricing_map[model]

        # Try partial match
        for key in pricing_map:
            if key in model.lower():
                return pricing_map[key]

        # Default fallback pricing
        logger.warning(f"Unknown model pricing for {model}, using default")
        return {"input": 1.00, "output": 3.00}

    async def sync_all_users_usage(
        self,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        db: AsyncSession = None
    ) -> int:
        """
        Sync usage data for all users with LiteLLM API keys.

        Args:
            start_date: Start date for usage sync
            end_date: End date for usage sync
            db: Database session

        Returns:
            Number of users synced
        """
        if not db:
            logger.error("Database session required for syncing all users")
            return 0

        try:
            # Get all users with LiteLLM API keys
            result = await db.execute(
                select(User).where(User.litellm_api_key.isnot(None))
            )
            users = result.scalars().all()

            synced_count = 0
            for user in users:
                usage_logs = await self.sync_user_usage(user, start_date, end_date, db)
                if usage_logs:
                    synced_count += 1

            logger.info(f"Synced usage for {synced_count}/{len(users)} users")
            return synced_count

        except Exception as e:
            logger.error(f"Failed to sync all users usage: {e}")
            return 0

    async def get_user_usage_summary(
        self,
        user_id: UUID,
        start_date: datetime,
        end_date: datetime,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Get usage summary for a user within a date range.

        Args:
            user_id: User ID
            start_date: Start date
            end_date: End date
            db: Database session

        Returns:
            Usage summary with totals
        """
        try:
            # Get usage logs
            result = await db.execute(
                select(UsageLog).where(
                    and_(
                        UsageLog.user_id == user_id,
                        UsageLog.created_at >= start_date,
                        UsageLog.created_at <= end_date
                    )
                )
            )
            usage_logs = result.scalars().all()

            # Calculate totals
            total_cost = sum(log.cost_total for log in usage_logs)
            total_tokens_input = sum(log.tokens_input for log in usage_logs)
            total_tokens_output = sum(log.tokens_output for log in usage_logs)
            total_requests = len(usage_logs)

            # Group by model
            by_model = {}
            for log in usage_logs:
                if log.model not in by_model:
                    by_model[log.model] = {
                        "requests": 0,
                        "tokens_input": 0,
                        "tokens_output": 0,
                        "cost_total": 0
                    }
                by_model[log.model]["requests"] += 1
                by_model[log.model]["tokens_input"] += log.tokens_input
                by_model[log.model]["tokens_output"] += log.tokens_output
                by_model[log.model]["cost_total"] += log.cost_total

            # Group by agent
            by_agent = {}
            for log in usage_logs:
                if log.agent_id:
                    agent_id_str = str(log.agent_id)
                    if agent_id_str not in by_agent:
                        by_agent[agent_id_str] = {
                            "requests": 0,
                            "tokens_input": 0,
                            "tokens_output": 0,
                            "cost_total": 0
                        }
                    by_agent[agent_id_str]["requests"] += 1
                    by_agent[agent_id_str]["tokens_input"] += log.tokens_input
                    by_agent[agent_id_str]["tokens_output"] += log.tokens_output
                    by_agent[agent_id_str]["cost_total"] += log.cost_total

            return {
                "total_cost_cents": total_cost,
                "total_cost_usd": total_cost / 100,
                "total_tokens_input": total_tokens_input,
                "total_tokens_output": total_tokens_output,
                "total_requests": total_requests,
                "by_model": by_model,
                "by_agent": by_agent,
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to get usage summary for user {user_id}: {e}")
            return {}

    async def generate_monthly_invoices(
        self,
        month: int,
        year: int,
        db: AsyncSession
    ) -> int:
        """
        Generate monthly invoices for all users with unpaid usage.

        Args:
            month: Month number (1-12)
            year: Year
            db: Database session

        Returns:
            Number of invoices created
        """
        try:
            # Calculate date range for the month
            start_date = datetime(year, month, 1, tzinfo=timezone.utc)
            if month == 12:
                end_date = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                end_date = datetime(year, month + 1, 1, tzinfo=timezone.utc)

            # Get all users with unpaid usage logs
            result = await db.execute(
                select(User).join(UsageLog).where(
                    and_(
                        UsageLog.billed_status == "pending",
                        UsageLog.created_at >= start_date,
                        UsageLog.created_at < end_date
                    )
                ).distinct()
            )
            users = result.scalars().all()

            invoices_created = 0
            for user in users:
                # Get unpaid usage logs for this user
                logs_result = await db.execute(
                    select(UsageLog).where(
                        and_(
                            UsageLog.user_id == user.id,
                            UsageLog.billed_status == "pending",
                            UsageLog.created_at >= start_date,
                            UsageLog.created_at < end_date
                        )
                    )
                )
                usage_logs = list(logs_result.scalars().all())

                if usage_logs:
                    # Create invoice
                    invoice_id = await stripe_service.create_usage_invoice(
                        user=user,
                        usage_logs=usage_logs,
                        db=db
                    )

                    if invoice_id:
                        invoices_created += 1

            logger.info(f"Generated {invoices_created} invoices for {month}/{year}")
            return invoices_created

        except Exception as e:
            logger.error(f"Failed to generate monthly invoices: {e}")
            return 0

    async def get_creator_earnings(
        self,
        creator_id: UUID,
        start_date: datetime,
        end_date: datetime,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Get earnings summary for an agent creator.

        Args:
            creator_id: Creator user ID
            start_date: Start date
            end_date: End date
            db: Database session

        Returns:
            Earnings summary
        """
        try:
            # Get usage logs where creator earned revenue
            result = await db.execute(
                select(UsageLog).where(
                    and_(
                        UsageLog.creator_id == creator_id,
                        UsageLog.created_at >= start_date,
                        UsageLog.created_at <= end_date
                    )
                )
            )
            usage_logs = result.scalars().all()

            # Calculate totals
            total_revenue = sum(log.creator_revenue for log in usage_logs)
            total_requests = len(usage_logs)

            # Group by agent
            by_agent = {}
            for log in usage_logs:
                if log.agent_id:
                    agent_id_str = str(log.agent_id)
                    if agent_id_str not in by_agent:
                        by_agent[agent_id_str] = {
                            "requests": 0,
                            "revenue": 0
                        }
                    by_agent[agent_id_str]["requests"] += 1
                    by_agent[agent_id_str]["revenue"] += log.creator_revenue

            # Group by billing status
            pending_revenue = sum(log.creator_revenue for log in usage_logs if log.billed_status == "pending")
            paid_revenue = sum(log.creator_revenue for log in usage_logs if log.billed_status == "paid")

            return {
                "total_revenue_cents": total_revenue,
                "total_revenue_usd": total_revenue / 100,
                "pending_revenue_cents": pending_revenue,
                "pending_revenue_usd": pending_revenue / 100,
                "paid_revenue_cents": paid_revenue,
                "paid_revenue_usd": paid_revenue / 100,
                "total_requests": total_requests,
                "by_agent": by_agent,
                "period_start": start_date.isoformat(),
                "period_end": end_date.isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to get creator earnings for {creator_id}: {e}")
            return {}


# Singleton instance
usage_service = UsageService()
