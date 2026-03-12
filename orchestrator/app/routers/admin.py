"""
Admin API endpoints for platform metrics and management.
Includes:
- Platform metrics (users, projects, sessions, tokens, marketplace)
- User management (search, view, suspend, delete, credits)
- System health monitoring
- Agent management
- Base management
"""

import asyncio
import contextlib
import csv
import io
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, asc, cast, desc, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import get_db
from ..models import (
    AdminAction,
    AgentStep,
    Chat,
    CreditPurchase,
    Deployment,
    HealthCheck,
    MarketplaceAgent,
    MarketplaceBase,
    Message,
    Project,
    ProjectAgent,
    UsageLog,
    User,
    UserPurchasedAgent,
    UserPurchasedBase,
)
from ..services.litellm_service import litellm_service
from ..users import current_superuser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================================================
# User Metrics
# ============================================================================


@router.get("/metrics/users")
async def get_user_metrics(
    days: int = 30, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Get comprehensive user metrics including DAU, MAU, growth rate.
    """
    try:
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)

        # Total users
        total_users_query = select(func.count(User.id))
        total_users = await db.scalar(total_users_query)

        # New users in period
        new_users_query = select(func.count(User.id)).where(User.created_at >= start_date)
        new_users = await db.scalar(new_users_query)

        # Active users (users who created projects or sent messages)
        # Daily Active Users (last 24 hours)
        day_ago = now - timedelta(days=1)
        dau_projects = select(distinct(Project.owner_id)).where(Project.created_at >= day_ago)
        dau_chats = select(distinct(Chat.user_id)).where(Chat.created_at >= day_ago)

        dau_project_users = await db.execute(dau_projects)
        dau_chat_users = await db.execute(dau_chats)

        dau_set = set()
        dau_set.update([u[0] for u in dau_project_users])
        dau_set.update([u[0] for u in dau_chat_users])
        dau = len(dau_set)

        # Monthly Active Users (last 30 days)
        month_ago = now - timedelta(days=30)
        mau_projects = select(distinct(Project.owner_id)).where(Project.created_at >= month_ago)
        mau_chats = select(distinct(Chat.user_id)).where(Chat.created_at >= month_ago)

        mau_project_users = await db.execute(mau_projects)
        mau_chat_users = await db.execute(mau_chats)

        mau_set = set()
        mau_set.update([u[0] for u in mau_project_users])
        mau_set.update([u[0] for u in mau_chat_users])
        mau = len(mau_set)

        # User growth rate (compare to previous period)
        previous_period_start = start_date - timedelta(days=days)
        previous_users_query = select(func.count(User.id)).where(
            and_(User.created_at >= previous_period_start, User.created_at < start_date)
        )
        previous_users = await db.scalar(previous_users_query)

        growth_rate = 0
        if previous_users > 0:
            growth_rate = ((new_users - previous_users) / previous_users) * 100

        # User retention (users active in both current and previous period)
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        # Get users active in last week (through chats)
        recent_active = select(distinct(Chat.user_id)).where(Chat.created_at >= week_ago)
        recent_users = await db.execute(recent_active)
        recent_set = {u[0] for u in recent_users}

        # Get users active in previous week
        prev_active = select(distinct(Chat.user_id)).where(
            and_(Chat.created_at >= two_weeks_ago, Chat.created_at < week_ago)
        )
        prev_users = await db.execute(prev_active)
        prev_set = {u[0] for u in prev_users}

        retained_users = len(recent_set.intersection(prev_set))
        retention_rate = (retained_users / len(prev_set) * 100) if prev_set else 0

        # Daily new users for chart
        daily_new_users = []
        for i in range(days):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            count_query = select(func.count(User.id)).where(
                and_(User.created_at >= day_start, User.created_at < day_end)
            )
            count = await db.scalar(count_query)

            daily_new_users.append({"date": day_start.isoformat(), "count": count})

        daily_new_users.reverse()

        return {
            "total_users": total_users,
            "new_users": new_users,
            "dau": dau,
            "mau": mau,
            "growth_rate": round(growth_rate, 2),
            "retention_rate": round(retention_rate, 2),
            "daily_new_users": daily_new_users,
            "period_days": days,
        }

    except Exception as e:
        logger.error(f"Error getting user metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user metrics") from e


# ============================================================================
# Project Metrics
# ============================================================================


@router.get("/metrics/projects")
async def get_project_metrics(
    days: int = 30, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Get project creation and usage metrics.
    """
    try:
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)

        # Total projects
        total_projects_query = select(func.count(Project.id))
        total_projects = await db.scalar(total_projects_query)

        # New projects in period
        new_projects_query = select(func.count(Project.id)).where(Project.created_at >= start_date)
        new_projects = await db.scalar(new_projects_query)

        # Projects per user
        projects_per_user_query = select(
            func.count(Project.id).label("count"), Project.owner_id
        ).group_by(Project.owner_id)

        result = await db.execute(projects_per_user_query)
        project_counts = [r.count for r in result]

        avg_projects_per_user = sum(project_counts) / len(project_counts) if project_counts else 0

        # Daily project creation for chart
        daily_projects = []
        for i in range(days):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            count_query = select(func.count(Project.id)).where(
                and_(Project.created_at >= day_start, Project.created_at < day_end)
            )
            count = await db.scalar(count_query)

            daily_projects.append({"date": day_start.isoformat(), "count": count})

        daily_projects.reverse()

        # Project categories (with/without git)
        git_projects_query = select(func.count(Project.id)).where(Project.has_git_repo)
        git_projects = await db.scalar(git_projects_query)

        return {
            "total_projects": total_projects,
            "new_projects": new_projects,
            "avg_projects_per_user": round(avg_projects_per_user, 2),
            "git_enabled_projects": git_projects,
            "daily_projects": daily_projects,
            "period_days": days,
        }

    except Exception as e:
        logger.error(f"Error getting project metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get project metrics") from e


# ============================================================================
# Session Metrics
# ============================================================================


@router.get("/metrics/sessions")
async def get_session_metrics(
    days: int = 30, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Get user session and engagement metrics.
    """
    try:
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)

        # Get all chats (sessions) in period
        sessions_query = select(Chat).where(Chat.created_at >= start_date)
        result = await db.execute(sessions_query)
        sessions = result.scalars().all()

        if not sessions:
            return {
                "total_sessions": 0,
                "unique_users": 0,
                "avg_sessions_per_user": 0,
                "avg_session_duration": 0,
                "avg_messages_per_session": 0,
                "period_days": days,
            }

        # Unique users with sessions
        unique_users = len({s.user_id for s in sessions})

        # Sessions per user
        avg_sessions_per_user = len(sessions) / unique_users if unique_users > 0 else 0

        # Calculate session durations and messages
        session_durations = []
        total_messages = 0

        for session in sessions:
            # Get messages for this session
            messages_query = (
                select(Message).where(Message.chat_id == session.id).order_by(Message.created_at)
            )
            result = await db.execute(messages_query)
            messages = result.scalars().all()

            if messages and len(messages) > 1:
                # Duration from first to last message
                duration = (
                    messages[-1].created_at - messages[0].created_at
                ).total_seconds() / 60  # in minutes
                session_durations.append(duration)
                total_messages += len(messages)

        avg_duration = sum(session_durations) / len(session_durations) if session_durations else 0
        avg_messages = total_messages / len(sessions) if sessions else 0

        # Daily active sessions
        daily_sessions = []
        for i in range(days):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            count_query = select(func.count(Chat.id)).where(
                and_(Chat.created_at >= day_start, Chat.created_at < day_end)
            )
            count = await db.scalar(count_query)

            daily_sessions.append({"date": day_start.isoformat(), "count": count})

        daily_sessions.reverse()

        return {
            "total_sessions": len(sessions),
            "unique_users": unique_users,
            "avg_sessions_per_user": round(avg_sessions_per_user, 2),
            "avg_session_duration": round(avg_duration, 2),  # in minutes
            "avg_messages_per_session": round(avg_messages, 2),
            "daily_sessions": daily_sessions,
            "period_days": days,
        }

    except Exception as e:
        logger.error(f"Error getting session metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get session metrics") from e


# ============================================================================
# Token Usage Metrics (from LiteLLM)
# ============================================================================


@router.get("/metrics/tokens")
async def get_token_metrics(
    days: int = 30, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Get token usage metrics from LiteLLM.
    """
    try:
        start_date = datetime.utcnow() - timedelta(days=days)

        # Get global statistics from LiteLLM
        global_stats_raw = await litellm_service.get_global_stats()

        # Transform global stats to expected format
        global_stats = {
            "spend": global_stats_raw.get("spend", 0),
            "max_budget": global_stats_raw.get("max_budget", 0),
        }

        # Get all users' usage from LiteLLM
        all_users_usage = await litellm_service.get_all_users_usage(start_date)

        # Aggregate metrics
        total_tokens = 0
        total_cost = 0
        tokens_by_model = {}
        user_token_data = []

        for user_usage in all_users_usage:
            # LiteLLM returns 'spend' instead of 'total_cost'
            user_cost = user_usage.get("spend", 0) or 0
            total_cost += user_cost

            # Calculate tokens from model_spend if available
            user_tokens = 0
            if "model_spend" in user_usage and user_usage["model_spend"]:
                for _model, _spend_data in user_usage["model_spend"].items():
                    # model_spend contains cost data, estimate tokens if not available
                    # For now, we'll track cost instead of tokens
                    pass

            # Track per-user data
            user_token_data.append(
                {
                    "user_id": user_usage.get("user_id", "unknown"),
                    "total_tokens": user_tokens,
                    "total_cost": user_cost,
                    "last_used": user_usage.get("updated_at", None),
                }
            )

            # Aggregate by model from model_spend
            if "model_spend" in user_usage and user_usage["model_spend"]:
                for model, spend_amount in user_usage["model_spend"].items():
                    if model not in tokens_by_model:
                        tokens_by_model[model] = {"tokens": 0, "cost": 0, "requests": 0}
                    # LiteLLM model_spend is just a dict of model: cost
                    tokens_by_model[model]["cost"] += spend_amount
                    tokens_by_model[model]["requests"] += 1  # Estimate

        # Sort users by cost (since we don't have token counts from LiteLLM)
        user_token_data.sort(key=lambda x: x["total_cost"], reverse=True)
        top_users = user_token_data[:10]  # Top 10 users

        # Calculate averages
        active_users = len([u for u in user_token_data if u["total_cost"] > 0])
        avg_tokens_per_user = total_tokens / active_users if active_users > 0 else 0
        avg_cost_per_user = total_cost / active_users if active_users > 0 else 0

        # Daily token usage (if available from LiteLLM)
        # This would require LiteLLM to provide daily breakdowns
        # For now, we'll estimate based on total usage
        daily_avg = total_tokens / days if days > 0 else 0

        return {
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 4),
            "active_users": active_users,
            "avg_tokens_per_user": round(avg_tokens_per_user, 0),
            "avg_cost_per_user": round(avg_cost_per_user, 4),
            "daily_avg_tokens": round(daily_avg, 0),
            "tokens_by_model": tokens_by_model,
            "top_users": top_users,
            "global_stats": global_stats,
            "period_days": days,
        }

    except Exception as e:
        logger.error(f"Error getting token metrics: {e}")
        # Return empty metrics if LiteLLM is unavailable
        return {
            "total_tokens": 0,
            "total_cost": 0,
            "active_users": 0,
            "avg_tokens_per_user": 0,
            "avg_cost_per_user": 0,
            "daily_avg_tokens": 0,
            "tokens_by_model": {},
            "top_users": [],
            "global_stats": {},
            "period_days": days,
            "error": "LiteLLM metrics unavailable",
        }


# ============================================================================
# Marketplace Metrics
# ============================================================================


@router.get("/metrics/marketplace")
async def get_marketplace_metrics(
    days: int = 30, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Get marketplace performance metrics including agents and bases.
    """
    try:
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)

        # ===== AGENTS METRICS =====
        # Total agents (official + published community agents)
        total_agents_query = select(func.count(MarketplaceAgent.id)).where(
            MarketplaceAgent.is_active.is_(True),
            (MarketplaceAgent.forked_by_user_id.is_(None))
            | (MarketplaceAgent.is_published.is_(True)),
        )
        total_agents = await db.scalar(total_agents_query)

        # Total agent purchases
        total_agent_purchases_query = select(func.count(UserPurchasedAgent.id))
        total_agent_purchases = await db.scalar(total_agent_purchases_query)

        # Recent agent purchases
        recent_agent_purchases_query = select(func.count(UserPurchasedAgent.id)).where(
            UserPurchasedAgent.purchase_date >= start_date
        )
        recent_agent_purchases = await db.scalar(recent_agent_purchases_query)

        # Agent revenue calculations
        agent_revenue_query = (
            select(UserPurchasedAgent, MarketplaceAgent)
            .join(MarketplaceAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
            .where(UserPurchasedAgent.purchase_date >= start_date)
        )

        result = await db.execute(agent_revenue_query)
        agent_purchases = result.all()

        agent_revenue = 0
        revenue_by_type = {"monthly": 0, "one_time": 0, "usage": 0}

        for _purchase, agent in agent_purchases:
            if agent.pricing_type == "monthly":
                agent_revenue += agent.price / 100  # Convert from cents
                revenue_by_type["monthly"] += agent.price / 100
            elif agent.pricing_type in ["one_time", "usage"]:
                agent_revenue += agent.price / 100
                revenue_by_type["one_time"] += agent.price / 100

        # Popular agents by purchases
        popular_agents_query = (
            select(
                MarketplaceAgent.name,
                MarketplaceAgent.slug,
                MarketplaceAgent.usage_count,
                func.count(UserPurchasedAgent.id).label("purchase_count"),
            )
            .join(
                UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id, isouter=True
            )
            .where(MarketplaceAgent.is_active)
            .group_by(MarketplaceAgent.id)
            .order_by(func.count(UserPurchasedAgent.id).desc())
            .limit(5)
        )

        result = await db.execute(popular_agents_query)
        popular_agents = [
            {
                "name": r.name,
                "slug": r.slug,
                "purchases": r.purchase_count,
                "usage_count": r.usage_count or 0,
            }
            for r in result
        ]

        # Most used agents (by usage_count - messages sent to agent)
        most_used_query = (
            select(MarketplaceAgent.name, MarketplaceAgent.slug, MarketplaceAgent.usage_count)
            .where(MarketplaceAgent.is_active, MarketplaceAgent.usage_count > 0)
            .order_by(MarketplaceAgent.usage_count.desc())
            .limit(5)
        )

        result = await db.execute(most_used_query)
        most_used_agents = [
            {"name": r.name, "slug": r.slug, "usage_count": r.usage_count} for r in result
        ]

        # Agent adoption rate (agents applied to projects)
        applied_agents_query = select(func.count(distinct(ProjectAgent.agent_id)))
        applied_agents = await db.scalar(applied_agents_query)

        agent_adoption_rate = (applied_agents / total_agents * 100) if total_agents > 0 else 0

        # ===== BASES METRICS =====
        # Total bases
        total_bases_query = select(func.count(MarketplaceBase.id)).where(MarketplaceBase.is_active)
        total_bases = await db.scalar(total_bases_query)

        # Total base purchases
        total_base_purchases_query = select(func.count(UserPurchasedBase.id))
        total_base_purchases = await db.scalar(total_base_purchases_query)

        # Recent base purchases
        recent_base_purchases_query = select(func.count(UserPurchasedBase.id)).where(
            UserPurchasedBase.purchase_date >= start_date
        )
        recent_base_purchases = await db.scalar(recent_base_purchases_query)

        # Popular bases
        popular_bases_query = (
            select(
                MarketplaceBase.name,
                MarketplaceBase.slug,
                MarketplaceBase.downloads,
                func.count(UserPurchasedBase.id).label("purchase_count"),
            )
            .join(UserPurchasedBase, UserPurchasedBase.base_id == MarketplaceBase.id, isouter=True)
            .where(MarketplaceBase.is_active)
            .group_by(MarketplaceBase.id)
            .order_by(func.count(UserPurchasedBase.id).desc())
            .limit(5)
        )

        result = await db.execute(popular_bases_query)
        popular_bases = [
            {
                "name": r.name,
                "slug": r.slug,
                "purchases": r.purchase_count,
                "downloads": r.downloads,
            }
            for r in result
        ]

        # ===== COMBINED METRICS =====
        total_revenue = agent_revenue  # Add base revenue when bases have pricing
        total_purchases = total_agent_purchases + total_base_purchases
        recent_purchases = recent_agent_purchases + recent_base_purchases

        return {
            # Overall metrics
            "total_items": total_agents + total_bases,
            "total_purchases": total_purchases,
            "recent_purchases": recent_purchases,
            "total_revenue": round(total_revenue, 2),
            "revenue_by_type": revenue_by_type,
            # Agent-specific metrics
            "agents": {
                "total": total_agents,
                "total_purchases": total_agent_purchases,
                "recent_purchases": recent_agent_purchases,
                "adoption_rate": round(agent_adoption_rate, 2),
                "popular": popular_agents,
                "most_used": most_used_agents,
            },
            # Base-specific metrics
            "bases": {
                "total": total_bases,
                "total_purchases": total_base_purchases,
                "recent_purchases": recent_base_purchases,
                "popular": popular_bases,
            },
            "period_days": days,
        }

    except Exception as e:
        logger.error(f"Error getting marketplace metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get marketplace metrics") from e


# ============================================================================
# Summary Dashboard
# ============================================================================


@router.get("/metrics/summary")
async def get_metrics_summary(
    admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Get a summary of all key metrics for the admin dashboard.
    """
    try:
        # Get metrics from each category (7 days for summary)
        user_metrics = await get_user_metrics(7, admin, db)
        project_metrics = await get_project_metrics(7, admin, db)
        session_metrics = await get_session_metrics(7, admin, db)
        token_metrics = await get_token_metrics(7, admin, db)
        marketplace_metrics = await get_marketplace_metrics(7, admin, db)

        return {
            "users": {
                "total": user_metrics["total_users"],
                "dau": user_metrics["dau"],
                "mau": user_metrics["mau"],
                "growth_rate": user_metrics["growth_rate"],
            },
            "projects": {
                "total": project_metrics["total_projects"],
                "new_this_week": project_metrics["new_projects"],
                "avg_per_user": project_metrics["avg_projects_per_user"],
            },
            "sessions": {
                "total_this_week": session_metrics["total_sessions"],
                "avg_per_user": session_metrics["avg_sessions_per_user"],
                "avg_duration": session_metrics["avg_session_duration"],
            },
            "tokens": {
                "total_this_week": token_metrics["total_tokens"],
                "total_cost": token_metrics["total_cost"],
                "avg_per_user": token_metrics["avg_tokens_per_user"],
            },
            "marketplace": {
                "total_items": marketplace_metrics["total_items"],
                "total_agents": marketplace_metrics["agents"]["total"],
                "total_bases": marketplace_metrics["bases"]["total"],
                "total_revenue": marketplace_metrics["total_revenue"],
                "recent_purchases": marketplace_metrics["recent_purchases"],
            },
        }

    except Exception as e:
        logger.error(f"Error getting metrics summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to get metrics summary") from e


# ============================================================================
# Agent Management
# ============================================================================


class AgentCreate(BaseModel):
    """Schema for creating a new agent."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    long_description: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    system_prompt: str = Field(..., min_length=1)
    mode: str = Field(..., pattern="^(stream|agent)$")
    agent_type: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    icon: str = Field(default="🤖")
    pricing_type: str = Field(..., pattern="^(free|monthly|api|one_time)$")
    price: int = Field(default=0, ge=0)  # In cents
    api_pricing_input: float = Field(default=0.0, ge=0)  # $ per million input tokens
    api_pricing_output: float = Field(default=0.0, ge=0)  # $ per million output tokens
    source_type: str = Field(..., pattern="^(open|closed)$")
    is_forkable: bool = Field(default=False)
    requires_user_keys: bool = Field(default=False)
    features: list[str] = Field(default_factory=list)
    required_models: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    is_featured: bool = Field(default=False)
    is_active: bool = Field(default=True)


class AgentUpdate(BaseModel):
    """Schema for updating an existing agent."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, min_length=1, max_length=500)
    long_description: str | None = None
    category: str | None = None
    system_prompt: str | None = None
    mode: str | None = Field(None, pattern="^(stream|agent)$")
    agent_type: str | None = None
    model: str | None = None
    icon: str | None = None
    pricing_type: str | None = Field(None, pattern="^(free|monthly|api|one_time)$")
    price: int | None = Field(None, ge=0)
    api_pricing_input: float | None = Field(None, ge=0)
    api_pricing_output: float | None = Field(None, ge=0)
    source_type: str | None = Field(None, pattern="^(open|closed)$")
    is_forkable: bool | None = None
    requires_user_keys: bool | None = None
    features: list[str] | None = None
    required_models: list[str] | None = None
    tags: list[str] | None = None
    is_featured: bool | None = None
    is_active: bool | None = None


def can_edit_agent(agent: MarketplaceAgent) -> bool:
    """Check if admin can edit this agent (only Tesslate-created agents)."""
    return agent.created_by_user_id is None and agent.forked_by_user_id is None


def generate_slug(name: str, db_session: AsyncSession = None) -> str:
    """Generate a unique slug from agent name."""
    # Convert to lowercase and replace spaces with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


@router.get("/agents")
async def list_agents(
    source_type: str | None = None,
    pricing_type: str | None = None,
    is_active: bool | None = None,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    List all agents with optional filters.
    Admins can see all agents including user-created ones.
    """
    try:
        query = select(MarketplaceAgent).options(
            selectinload(MarketplaceAgent.created_by_user),
            selectinload(MarketplaceAgent.forked_by_user),
        )

        # Apply filters
        if source_type:
            query = query.where(MarketplaceAgent.source_type == source_type)
        if pricing_type:
            query = query.where(MarketplaceAgent.pricing_type == pricing_type)
        if is_active is not None:
            query = query.where(MarketplaceAgent.is_active == is_active)

        # Order by creation date (newest first)
        query = query.order_by(MarketplaceAgent.created_at.desc())

        result = await db.execute(query)
        agents = result.scalars().all()

        return {
            "agents": [
                {
                    "id": agent.id,
                    "name": agent.name,
                    "slug": agent.slug,
                    "description": agent.description,
                    "category": agent.category,
                    "mode": agent.mode,
                    "agent_type": agent.agent_type,
                    "model": agent.model,
                    "icon": agent.icon,
                    "pricing_type": agent.pricing_type,
                    "price": agent.price,
                    "api_pricing_input": agent.api_pricing_input,
                    "api_pricing_output": agent.api_pricing_output,
                    "source_type": agent.source_type,
                    "is_forkable": agent.is_forkable,
                    "requires_user_keys": agent.requires_user_keys,
                    "is_featured": agent.is_featured,
                    "is_active": agent.is_active,
                    "usage_count": agent.usage_count,
                    "created_at": agent.created_at.isoformat(),
                    "created_by_tesslate": agent.created_by_user_id is None
                    and agent.forked_by_user_id is None,
                    "created_by_username": agent.created_by_user.username
                    if agent.created_by_user
                    else None,
                    "forked_by_username": agent.forked_by_user.username
                    if agent.forked_by_user
                    else None,
                    "can_edit": can_edit_agent(agent),
                }
                for agent in agents
            ],
            "total": len(agents),
        }

    except Exception as e:
        logger.error(f"Error listing agents: {e}")
        raise HTTPException(status_code=500, detail="Failed to list agents") from e


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Get detailed information about a specific agent."""
    try:
        result = await db.execute(
            select(MarketplaceAgent)
            .options(
                selectinload(MarketplaceAgent.created_by_user),
                selectinload(MarketplaceAgent.forked_by_user),
            )
            .where(MarketplaceAgent.id == agent_id)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        return {
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "description": agent.description,
            "long_description": agent.long_description,
            "category": agent.category,
            "system_prompt": agent.system_prompt,
            "mode": agent.mode,
            "agent_type": agent.agent_type,
            "model": agent.model,
            "icon": agent.icon,
            "pricing_type": agent.pricing_type,
            "price": agent.price,
            "api_pricing_input": agent.api_pricing_input,
            "api_pricing_output": agent.api_pricing_output,
            "source_type": agent.source_type,
            "is_forkable": agent.is_forkable,
            "requires_user_keys": agent.requires_user_keys,
            "features": agent.features,
            "required_models": agent.required_models,
            "tags": agent.tags,
            "is_featured": agent.is_featured,
            "is_active": agent.is_active,
            "is_published": agent.is_published,
            "usage_count": agent.usage_count,
            "created_at": agent.created_at.isoformat(),
            "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
            "created_by_tesslate": agent.created_by_user_id is None
            and agent.forked_by_user_id is None,
            "created_by_username": agent.created_by_user.username
            if agent.created_by_user
            else None,
            "forked_by_username": agent.forked_by_user.username if agent.forked_by_user else None,
            "can_edit": can_edit_agent(agent),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get agent") from e


@router.post("/agents")
async def create_agent(
    agent_data: AgentCreate,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Create a new agent.
    All agents created via admin panel are marked as Tesslate-created (created_by_user_id = NULL).
    """
    try:
        # Generate slug from name
        slug = generate_slug(agent_data.name)

        # Check if slug already exists
        existing = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.slug == slug))
        if existing.scalar_one_or_none():
            # Add a number suffix if slug exists
            counter = 1
            while True:
                new_slug = f"{slug}-{counter}"
                existing = await db.execute(
                    select(MarketplaceAgent).where(MarketplaceAgent.slug == new_slug)
                )
                if not existing.scalar_one_or_none():
                    slug = new_slug
                    break
                counter += 1

        # Create agent (created_by_user_id = NULL means Tesslate-created)
        agent = MarketplaceAgent(
            name=agent_data.name,
            slug=slug,
            description=agent_data.description,
            long_description=agent_data.long_description,
            category=agent_data.category,
            system_prompt=agent_data.system_prompt,
            mode=agent_data.mode,
            agent_type=agent_data.agent_type,
            model=agent_data.model,
            icon=agent_data.icon,
            pricing_type=agent_data.pricing_type,
            price=agent_data.price,
            api_pricing_input=agent_data.api_pricing_input,
            api_pricing_output=agent_data.api_pricing_output,
            source_type=agent_data.source_type,
            is_forkable=agent_data.is_forkable,
            requires_user_keys=agent_data.requires_user_keys,
            features=agent_data.features,
            required_models=agent_data.required_models,
            tags=agent_data.tags,
            is_featured=agent_data.is_featured,
            is_active=agent_data.is_active,
            created_by_user_id=None,  # NULL = Tesslate-created
            forked_by_user_id=None,
        )

        db.add(agent)
        await db.commit()
        await db.refresh(agent)

        logger.info(f"Admin {admin.username} created agent: {agent.name} (ID: {agent.id})")

        return {
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "message": "Agent created successfully",
        }

    except Exception as e:
        logger.error(f"Error creating agent: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create agent") from e


@router.put("/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    agent_data: AgentUpdate,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Update an existing agent.
    Only Tesslate-created agents can be edited. User-forked or custom agents cannot be edited.
    """
    try:
        result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Check if admin can edit this agent
        if not can_edit_agent(agent):
            raise HTTPException(
                status_code=403,
                detail="Cannot edit user-created or forked agents. Only Tesslate-created agents can be edited.",
            )

        # Update fields that were provided
        update_data = agent_data.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(agent, field, value)

        agent.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(agent)

        logger.info(f"Admin {admin.username} updated agent: {agent.name} (ID: {agent.id})")

        return {
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "message": "Agent updated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating agent {agent_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update agent") from e


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Delete an agent.
    Only Tesslate-created agents can be deleted. User-created agents can only be removed from marketplace.
    """
    try:
        result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Check if admin can delete this agent
        if not can_edit_agent(agent):
            raise HTTPException(
                status_code=403,
                detail="Cannot delete user-created or forked agents. Use remove-from-marketplace instead.",
            )

        agent_name = agent.name
        await db.delete(agent)
        await db.commit()

        logger.info(f"Admin {admin.username} deleted agent: {agent_name} (ID: {agent_id})")

        return {"message": f"Agent '{agent_name}' deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting agent {agent_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete agent") from e


@router.patch("/agents/{agent_id}/remove-from-marketplace")
async def remove_from_marketplace(
    agent_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Remove an agent from the public marketplace (set is_active = false).
    This can be used on ANY agent, including user-created ones.
    """
    try:
        result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        agent.is_active = False
        agent.updated_at = datetime.utcnow()

        await db.commit()

        logger.info(
            f"Admin {admin.username} removed agent from marketplace: {agent.name} (ID: {agent_id})"
        )

        return {
            "id": agent.id,
            "name": agent.name,
            "message": "Agent removed from marketplace successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing agent {agent_id} from marketplace: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=500, detail="Failed to remove agent from marketplace"
        ) from e


@router.patch("/agents/{agent_id}/restore-to-marketplace")
async def restore_to_marketplace(
    agent_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Restore an agent to the public marketplace (set is_active = true).
    This can be used on ANY agent, including user-created ones.
    """
    try:
        result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        agent.is_active = True
        agent.updated_at = datetime.utcnow()

        await db.commit()

        logger.info(
            f"Admin {admin.username} restored agent to marketplace: {agent.name} (ID: {agent_id})"
        )

        return {
            "id": agent.id,
            "name": agent.name,
            "message": "Agent restored to marketplace successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restoring agent {agent_id} to marketplace: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to restore agent to marketplace") from e


@router.patch("/agents/{agent_id}/feature")
async def toggle_featured(
    agent_id: str,
    is_featured: bool,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Toggle the featured status of an agent.
    """
    try:
        result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        agent.is_featured = is_featured
        agent.updated_at = datetime.utcnow()

        await db.commit()

        status = "featured" if is_featured else "unfeatured"
        logger.info(f"Admin {admin.username} {status} agent: {agent.name} (ID: {agent_id})")

        return {
            "id": agent.id,
            "name": agent.name,
            "is_featured": agent.is_featured,
            "message": f"Agent {status} successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling featured status for agent {agent_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to toggle featured status") from e


# ============================================================================
# Base Management
# ============================================================================


class BaseCreate(BaseModel):
    """Schema for creating a new base."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    long_description: str | None = None
    git_repo_url: str | None = None
    default_branch: str = Field(default="main")
    source_type: str = Field(default="git", pattern="^(git|archive)$")
    category: str = Field(..., min_length=1)
    icon: str = Field(default="📦")
    preview_image: str | None = None
    tags: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    pricing_type: str = Field(..., pattern="^(free|one_time|monthly)$")
    price: int = Field(default=0, ge=0)  # In cents
    visibility: str = Field(default="public", pattern="^(public|private)$")
    is_featured: bool = Field(default=False)
    is_active: bool = Field(default=True)


class BaseUpdate(BaseModel):
    """Schema for updating an existing base."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, min_length=1, max_length=500)
    long_description: str | None = None
    git_repo_url: str | None = None
    default_branch: str | None = None
    source_type: str | None = Field(None, pattern="^(git|archive)$")
    category: str | None = None
    icon: str | None = None
    preview_image: str | None = None
    tags: list[str] | None = None
    features: list[str] | None = None
    tech_stack: list[str] | None = None
    pricing_type: str | None = Field(None, pattern="^(free|one_time|monthly)$")
    price: int | None = Field(None, ge=0)
    visibility: str | None = Field(None, pattern="^(public|private)$")
    is_featured: bool | None = None
    is_active: bool | None = None


def can_edit_base(base: MarketplaceBase) -> bool:
    """Check if admin can edit this base (only Tesslate-created bases)."""
    return base.created_by_user_id is None


@router.get("/bases")
async def list_bases(
    category: str | None = None,
    pricing_type: str | None = None,
    is_active: bool | None = None,
    source_type: str | None = None,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    List all bases with optional filters.
    Admins can see all bases including user-created ones.
    """
    try:
        query = select(MarketplaceBase).options(
            selectinload(MarketplaceBase.created_by_user),
        )

        # Apply filters
        if category:
            query = query.where(MarketplaceBase.category == category)
        if pricing_type:
            query = query.where(MarketplaceBase.pricing_type == pricing_type)
        if is_active is not None:
            query = query.where(MarketplaceBase.is_active == is_active)
        if source_type:
            query = query.where(MarketplaceBase.source_type == source_type)

        # Order by creation date (newest first)
        query = query.order_by(MarketplaceBase.created_at.desc())

        result = await db.execute(query)
        bases = result.scalars().all()

        return {
            "bases": [
                {
                    "id": base.id,
                    "name": base.name,
                    "slug": base.slug,
                    "description": base.description,
                    "category": base.category,
                    "icon": base.icon,
                    "source_type": base.source_type,
                    "pricing_type": base.pricing_type,
                    "price": base.price,
                    "downloads": base.downloads,
                    "is_featured": base.is_featured,
                    "is_active": base.is_active,
                    "created_at": base.created_at.isoformat(),
                    "created_by_tesslate": base.created_by_user_id is None,
                    "created_by_username": base.created_by_user.username
                    if base.created_by_user
                    else None,
                    "can_edit": can_edit_base(base),
                }
                for base in bases
            ],
            "total": len(bases),
        }

    except Exception as e:
        logger.error(f"Error listing bases: {e}")
        raise HTTPException(status_code=500, detail="Failed to list bases") from e


@router.get("/bases/{base_id}")
async def get_base(
    base_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Get detailed information about a specific base."""
    try:
        result = await db.execute(
            select(MarketplaceBase)
            .options(
                selectinload(MarketplaceBase.created_by_user),
            )
            .where(MarketplaceBase.id == base_id)
        )
        base = result.scalar_one_or_none()

        if not base:
            raise HTTPException(status_code=404, detail="Base not found")

        return {
            "id": base.id,
            "name": base.name,
            "slug": base.slug,
            "description": base.description,
            "long_description": base.long_description,
            "git_repo_url": base.git_repo_url,
            "default_branch": base.default_branch,
            "source_type": base.source_type,
            "category": base.category,
            "icon": base.icon,
            "preview_image": base.preview_image,
            "tags": base.tags,
            "features": base.features,
            "tech_stack": base.tech_stack,
            "pricing_type": base.pricing_type,
            "price": base.price,
            "downloads": base.downloads,
            "rating": base.rating,
            "reviews_count": base.reviews_count,
            "visibility": base.visibility,
            "is_featured": base.is_featured,
            "is_active": base.is_active,
            "created_at": base.created_at.isoformat(),
            "updated_at": base.updated_at.isoformat() if base.updated_at else None,
            "created_by_tesslate": base.created_by_user_id is None,
            "created_by_username": base.created_by_user.username if base.created_by_user else None,
            "can_edit": can_edit_base(base),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting base {base_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get base") from e


@router.post("/bases")
async def create_base(
    base_data: BaseCreate,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Create a new base.
    All bases created via admin panel are marked as Tesslate-created (created_by_user_id = NULL).
    """
    try:
        # Generate slug from name
        slug = generate_slug(base_data.name)

        # Check if slug already exists
        existing = await db.execute(select(MarketplaceBase).where(MarketplaceBase.slug == slug))
        if existing.scalar_one_or_none():
            # Add a number suffix if slug exists
            counter = 1
            while True:
                new_slug = f"{slug}-{counter}"
                existing = await db.execute(
                    select(MarketplaceBase).where(MarketplaceBase.slug == new_slug)
                )
                if not existing.scalar_one_or_none():
                    slug = new_slug
                    break
                counter += 1

        # Create base (created_by_user_id = NULL means Tesslate-created)
        base = MarketplaceBase(
            name=base_data.name,
            slug=slug,
            description=base_data.description,
            long_description=base_data.long_description,
            git_repo_url=base_data.git_repo_url,
            default_branch=base_data.default_branch,
            source_type=base_data.source_type,
            category=base_data.category,
            icon=base_data.icon,
            preview_image=base_data.preview_image,
            tags=base_data.tags,
            features=base_data.features,
            tech_stack=base_data.tech_stack,
            pricing_type=base_data.pricing_type,
            price=base_data.price,
            visibility=base_data.visibility,
            is_featured=base_data.is_featured,
            is_active=base_data.is_active,
            created_by_user_id=None,  # NULL = Tesslate-created
        )

        db.add(base)
        await db.commit()
        await db.refresh(base)

        logger.info(f"Admin {admin.username} created base: {base.name} (ID: {base.id})")

        return {
            "id": base.id,
            "name": base.name,
            "slug": base.slug,
            "message": "Base created successfully",
        }

    except Exception as e:
        logger.error(f"Error creating base: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create base") from e


@router.put("/bases/{base_id}")
async def update_base(
    base_id: str,
    base_data: BaseUpdate,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Update an existing base.
    Only Tesslate-created bases can be edited. User-created bases cannot be edited.
    """
    try:
        result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
        base = result.scalar_one_or_none()

        if not base:
            raise HTTPException(status_code=404, detail="Base not found")

        # Check if admin can edit this base
        if not can_edit_base(base):
            raise HTTPException(
                status_code=403,
                detail="Cannot edit user-created bases. Only Tesslate-created bases can be edited.",
            )

        # Update fields that were provided
        update_data = base_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(base, field, value)

        base.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(base)

        logger.info(f"Admin {admin.username} updated base: {base.name} (ID: {base.id})")

        return {
            "id": base.id,
            "name": base.name,
            "slug": base.slug,
            "message": "Base updated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating base {base_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update base") from e


@router.delete("/bases/{base_id}")
async def delete_base(
    base_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Delete a base.
    Only Tesslate-created bases can be deleted. User-created bases can only be removed from marketplace.
    """
    try:
        result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
        base = result.scalar_one_or_none()

        if not base:
            raise HTTPException(status_code=404, detail="Base not found")

        # Check if admin can delete this base
        if not can_edit_base(base):
            raise HTTPException(
                status_code=403,
                detail="Cannot delete user-created bases. Use remove-from-marketplace instead.",
            )

        base_name = base.name
        await db.delete(base)
        await db.commit()

        logger.info(f"Admin {admin.username} deleted base: {base_name} (ID: {base_id})")

        return {"message": f"Base '{base_name}' deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting base {base_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete base") from e


@router.patch("/bases/{base_id}/remove-from-marketplace")
async def remove_base_from_marketplace(
    base_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Remove a base from the public marketplace (set is_active = false).
    This can be used on ANY base, including user-created ones.
    """
    try:
        result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
        base = result.scalar_one_or_none()

        if not base:
            raise HTTPException(status_code=404, detail="Base not found")

        base.is_active = False
        base.updated_at = datetime.utcnow()

        await db.commit()

        logger.info(
            f"Admin {admin.username} removed base from marketplace: {base.name} (ID: {base_id})"
        )

        return {
            "id": base.id,
            "name": base.name,
            "message": "Base removed from marketplace successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing base {base_id} from marketplace: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to remove base from marketplace") from e


@router.patch("/bases/{base_id}/restore-to-marketplace")
async def restore_base_to_marketplace(
    base_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Restore a base to the public marketplace (set is_active = true).
    This can be used on ANY base, including user-created ones.
    """
    try:
        result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
        base = result.scalar_one_or_none()

        if not base:
            raise HTTPException(status_code=404, detail="Base not found")

        base.is_active = True
        base.updated_at = datetime.utcnow()

        await db.commit()

        logger.info(
            f"Admin {admin.username} restored base to marketplace: {base.name} (ID: {base_id})"
        )

        return {
            "id": base.id,
            "name": base.name,
            "message": "Base restored to marketplace successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restoring base {base_id} to marketplace: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to restore base to marketplace") from e


@router.patch("/bases/{base_id}/feature")
async def toggle_base_featured(
    base_id: str,
    is_featured: bool,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Toggle the featured status of a base.
    """
    try:
        result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
        base = result.scalar_one_or_none()

        if not base:
            raise HTTPException(status_code=404, detail="Base not found")

        base.is_featured = is_featured
        base.updated_at = datetime.utcnow()

        await db.commit()

        status = "featured" if is_featured else "unfeatured"
        logger.info(f"Admin {admin.username} {status} base: {base.name} (ID: {base_id})")

        return {
            "id": base.id,
            "name": base.name,
            "is_featured": base.is_featured,
            "message": f"Base {status} successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling featured status for base {base_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to toggle featured status") from e


@router.get("/models")
async def get_available_models(
    admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Get list of available models from LiteLLM.
    Returns model names from your LiteLLM instance.
    """
    try:
        from ..services.litellm_service import litellm_service

        # Get all available models from LiteLLM
        litellm_models = await litellm_service.get_available_models()

        # Extract model IDs
        models = [model.get("id") for model in litellm_models if model.get("id")]

        # If no models from LiteLLM, fallback to environment variable
        if not models:
            from ..config import get_settings

            settings = get_settings()
            models_str = settings.litellm_default_models
            models = [m.strip() for m in models_str.split(",") if m.strip()]

        if not models:
            models = [settings.default_model]

        return {"models": models}

    except Exception as e:
        logger.error(f"Error getting available models: {e}")
        # Fallback to environment variable on error
        from ..config import get_settings

        settings = get_settings()
        models_str = settings.litellm_default_models
        models = [m.strip() for m in models_str.split(",") if m.strip()]
        return {"models": models if models else [settings.default_model]}


# ============================================================================
# User Management
# ============================================================================


async def log_admin_action(
    db: AsyncSession,
    admin: User,
    action_type: str,
    target_type: str,
    target_id: UUID,
    reason: str | None = None,
    extra_data: dict | None = None,
    request: Request | None = None,
):
    """Log an admin action to the audit log."""
    try:
        action = AdminAction(
            admin_id=admin.id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            extra_data=extra_data or {},
            ip_address=request.client.host if request else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
        db.add(action)
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to log admin action: {e}")


@router.get("/users")
async def list_users(
    search: str | None = None,
    tier: str | None = None,
    status: str | None = None,  # active, suspended, deleted
    verified: bool | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    last_active_after: datetime | None = None,
    last_active_before: datetime | None = None,
    has_projects: bool | None = None,
    is_creator: bool | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    List users with search, filters, and pagination.
    """
    try:
        # Correlated subqueries for project_count and creator_agent_count
        # These are computed in the DB, eliminating N+1 queries
        project_count_subq = (
            select(func.count(Project.id))
            .where(Project.owner_id == User.id)
            .correlate(User)
            .scalar_subquery()
            .label("project_count")
        )

        creator_count_subq = (
            select(func.count(MarketplaceAgent.id))
            .where(
                or_(
                    MarketplaceAgent.created_by_user_id == User.id,
                    MarketplaceAgent.forked_by_user_id == User.id,
                )
            )
            .correlate(User)
            .scalar_subquery()
            .label("creator_agent_count")
        )

        # Base query with computed columns
        query = select(User, project_count_subq, creator_count_subq)
        count_query = select(func.count()).select_from(User)

        # Apply filters
        filters = []

        # Search by email, username, or name
        if search:
            search_pattern = f"%{search}%"
            filters.append(
                or_(
                    User.email.ilike(search_pattern),
                    User.username.ilike(search_pattern),
                    User.name.ilike(search_pattern),
                )
            )

        # Subscription tier filter
        if tier:
            filters.append(User.subscription_tier == tier)

        # Account status filter
        if status:
            if status == "active":
                filters.append(
                    and_(
                        User.is_suspended.is_(False),
                        User.is_deleted.is_(False),
                        User.is_active.is_(True),
                    )
                )
            elif status == "suspended":
                filters.append(User.is_suspended.is_(True))
            elif status == "deleted":
                filters.append(User.is_deleted.is_(True))
            elif status == "inactive":
                filters.append(User.is_active.is_(False))

        # Email verification filter
        if verified is not None:
            filters.append(User.is_verified == verified)

        # Date range filters
        if created_after:
            filters.append(User.created_at >= created_after)
        if created_before:
            filters.append(User.created_at <= created_before)
        if last_active_after:
            filters.append(User.last_active_at >= last_active_after)
        if last_active_before:
            filters.append(User.last_active_at <= last_active_before)

        # has_projects / is_creator filters applied BEFORE pagination
        # Use EXISTS subqueries so they work as WHERE clauses on the User row
        if has_projects is not None:
            project_exists = (
                select(Project.id).where(Project.owner_id == User.id).correlate(User).exists()
            )
            if has_projects:
                filters.append(project_exists)
            else:
                filters.append(~project_exists)

        if is_creator is not None:
            creator_exists = (
                select(MarketplaceAgent.id)
                .where(
                    or_(
                        MarketplaceAgent.created_by_user_id == User.id,
                        MarketplaceAgent.forked_by_user_id == User.id,
                    )
                )
                .correlate(User)
                .exists()
            )
            if is_creator:
                filters.append(creator_exists)
            else:
                filters.append(~creator_exists)

        # Apply all filters
        if filters:
            query = query.where(and_(*filters))
            count_query = count_query.where(and_(*filters))

        # Get total count
        total = await db.scalar(count_query)

        # Apply sorting
        sort_column = getattr(User, sort_by, User.created_at)
        if sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        # Execute query - single round-trip, no N+1
        result = await db.execute(query)
        rows = result.all()

        # Format response
        users_data = []
        for user, project_count, creator_agent_count in rows:
            users_data.append(
                {
                    "id": str(user.id),
                    "email": user.email,
                    "username": user.username,
                    "name": user.name,
                    "avatar_url": user.avatar_url,
                    "subscription_tier": user.subscription_tier,
                    "is_active": user.is_active,
                    "is_suspended": user.is_suspended,
                    "is_deleted": user.is_deleted,
                    "is_verified": user.is_verified,
                    "is_superuser": user.is_superuser,
                    "total_credits": user.total_credits,
                    "bundled_credits": user.bundled_credits,
                    "purchased_credits": user.purchased_credits,
                    "total_spend": user.total_spend,
                    "project_count": project_count or 0,
                    "is_creator": (creator_agent_count or 0) > 0,
                    "last_active_at": user.last_active_at.isoformat()
                    if user.last_active_at
                    else None,
                    "created_at": user.created_at.isoformat() if user.created_at else None,
                }
            )

        return {
            "users": users_data,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    except Exception as e:
        logger.error(f"Error listing users: {e}")
        raise HTTPException(status_code=500, detail="Failed to list users") from e


@router.get("/users/export")
async def export_users(
    search: str | None = None,
    tier: str | None = None,
    status: str | None = None,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
):
    """Export users to CSV."""
    try:
        # Build query (similar to list_users but without pagination)
        query = select(User)
        filters = []

        if search:
            search_pattern = f"%{search}%"
            filters.append(
                or_(
                    User.email.ilike(search_pattern),
                    User.username.ilike(search_pattern),
                    User.name.ilike(search_pattern),
                )
            )
        if tier:
            filters.append(User.subscription_tier == tier)
        if status == "active":
            filters.append(and_(User.is_suspended.is_(False), User.is_deleted.is_(False)))
        elif status == "suspended":
            filters.append(User.is_suspended.is_(True))
        elif status == "deleted":
            filters.append(User.is_deleted.is_(True))

        if filters:
            query = query.where(and_(*filters))

        result = await db.execute(query.order_by(User.created_at.desc()))
        users = result.scalars().all()

        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "ID",
                "Email",
                "Username",
                "Name",
                "Tier",
                "Status",
                "Total Credits",
                "Total Spend",
                "Created At",
                "Last Active",
            ]
        )

        for user in users:
            status_str = "active"
            if user.is_deleted:
                status_str = "deleted"
            elif user.is_suspended:
                status_str = "suspended"
            elif not user.is_active:
                status_str = "inactive"

            writer.writerow(
                [
                    str(user.id),
                    user.email,
                    user.username,
                    user.name,
                    user.subscription_tier,
                    status_str,
                    user.total_credits,
                    user.total_spend / 100 if user.total_spend else 0,
                    user.created_at.isoformat() if user.created_at else "",
                    user.last_active_at.isoformat() if user.last_active_at else "",
                ]
            )

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=users_export.csv"},
        )

    except Exception as e:
        logger.error(f"Error exporting users: {e}")
        raise HTTPException(status_code=500, detail="Failed to export users") from e


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Get detailed information about a specific user."""
    try:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get project count
        project_count = await db.scalar(
            select(func.count(Project.id)).where(Project.owner_id == user.id)
        )

        # Get deployed projects count
        deployed_count = await db.scalar(
            select(func.count(Project.id)).where(
                and_(Project.owner_id == user.id, Project.is_deployed.is_(True))
            )
        )

        # Get total usage from UsageLog
        usage_query = select(
            func.sum(UsageLog.tokens_input).label("total_input"),
            func.sum(UsageLog.tokens_output).label("total_output"),
            func.sum(UsageLog.cost_total).label("total_cost"),
        ).where(UsageLog.user_id == user.id)
        usage_result = await db.execute(usage_query)
        usage = usage_result.one()

        # Get recent activity
        recent_projects = await db.execute(
            select(Project.name, Project.created_at)
            .where(Project.owner_id == user.id)
            .order_by(Project.created_at.desc())
            .limit(5)
        )

        return {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "name": user.name,
            "slug": user.slug,
            "avatar_url": user.avatar_url,
            "bio": user.bio,
            "twitter_handle": user.twitter_handle,
            "github_username": user.github_username,
            "website_url": user.website_url,
            "subscription_tier": user.subscription_tier,
            "stripe_customer_id": user.stripe_customer_id,
            "stripe_subscription_id": user.stripe_subscription_id,
            "is_active": user.is_active,
            "is_suspended": user.is_suspended,
            "suspended_at": user.suspended_at.isoformat() if user.suspended_at else None,
            "suspended_reason": user.suspended_reason,
            "is_deleted": user.is_deleted,
            "deleted_at": user.deleted_at.isoformat() if user.deleted_at else None,
            "deleted_reason": user.deleted_reason,
            "is_verified": user.is_verified,
            "is_superuser": user.is_superuser,
            "bundled_credits": user.bundled_credits,
            "purchased_credits": user.purchased_credits,
            "total_credits": user.total_credits,
            "credits_reset_date": user.credits_reset_date.isoformat()
            if user.credits_reset_date
            else None,
            "total_spend": user.total_spend,
            "referral_code": user.referral_code,
            "referred_by": user.referred_by,
            "project_count": project_count,
            "deployed_projects_count": deployed_count,
            "usage_stats": {
                "total_tokens_input": usage.total_input or 0,
                "total_tokens_output": usage.total_output or 0,
                "total_cost_cents": usage.total_cost or 0,
            },
            "recent_projects": [
                {"name": p.name, "created_at": p.created_at.isoformat()} for p in recent_projects
            ],
            "last_active_at": user.last_active_at.isoformat() if user.last_active_at else None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user details") from e


@router.get("/users/{user_id}/projects")
async def get_user_projects(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get projects owned by a specific user."""
    try:
        # Verify user exists
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get total count
        total = await db.scalar(select(func.count(Project.id)).where(Project.owner_id == user_id))

        # Get projects with pagination
        offset = (page - 1) * page_size
        result = await db.execute(
            select(Project)
            .where(Project.owner_id == user_id)
            .order_by(Project.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        projects = result.scalars().all()

        return {
            "projects": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "slug": p.slug,
                    "is_deployed": p.is_deployed,
                    "environment_status": p.environment_status,
                    "has_git_repo": p.has_git_repo,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "last_activity": p.last_activity.isoformat() if p.last_activity else None,
                }
                for p in projects
            ],
            "total": total,
            "page": page,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting projects for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user projects") from e


@router.get("/users/{user_id}/billing")
async def get_user_billing(
    user_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Get billing information for a specific user."""
    try:
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get credit purchases
        purchases_result = await db.execute(
            select(CreditPurchase)
            .where(CreditPurchase.user_id == user_id)
            .order_by(CreditPurchase.created_at.desc())
            .limit(10)
        )
        purchases = purchases_result.scalars().all()

        # Get recent usage logs
        usage_result = await db.execute(
            select(UsageLog)
            .where(UsageLog.user_id == user_id)
            .order_by(UsageLog.created_at.desc())
            .limit(20)
        )
        usage_logs = usage_result.scalars().all()

        # Calculate monthly spend
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_spend = (
            await db.scalar(
                select(func.sum(UsageLog.cost_total)).where(
                    and_(UsageLog.user_id == user_id, UsageLog.created_at >= month_start)
                )
            )
            or 0
        )

        return {
            "subscription": {
                "tier": user.subscription_tier,
                "stripe_customer_id": user.stripe_customer_id,
                "stripe_subscription_id": user.stripe_subscription_id,
            },
            "credits": {
                "bundled": user.bundled_credits,
                "purchased": user.purchased_credits,
                "total": user.total_credits,
                "reset_date": user.credits_reset_date.isoformat()
                if user.credits_reset_date
                else None,
            },
            "spend": {"total_lifetime_cents": user.total_spend, "monthly_cents": monthly_spend},
            "purchases": [
                {
                    "id": str(p.id),
                    "amount_cents": p.amount_cents,
                    "credits_amount": p.credits_amount,
                    "status": p.status,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in purchases
            ],
            "recent_usage": [
                {
                    "model": u.model,
                    "tokens_input": u.tokens_input,
                    "tokens_output": u.tokens_output,
                    "cost_cents": u.cost_total,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in usage_logs
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting billing for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user billing") from e


class SuspendUserRequest(BaseModel):
    """Request body for suspending a user."""

    reason: str = Field(..., min_length=1, max_length=1000)
    notify_user: bool = False


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: str,
    request_data: SuspendUserRequest,
    request: Request,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Suspend a user account."""
    try:
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if user.is_superuser:
            raise HTTPException(status_code=403, detail="Cannot suspend a superuser account")

        if user.is_suspended:
            raise HTTPException(status_code=400, detail="User is already suspended")

        # Suspend the user
        user.is_suspended = True
        user.suspended_at = datetime.utcnow()
        user.suspended_reason = request_data.reason
        user.suspended_by_id = admin.id
        user.is_active = False  # Also deactivate the account

        await db.commit()

        # Log admin action
        await log_admin_action(
            db,
            admin,
            "user.suspend",
            "user",
            UUID(user_id),
            reason=request_data.reason,
            extra_data={"notify_user": request_data.notify_user},
            request=request,
        )

        logger.info(f"Admin {admin.username} suspended user {user.username}")

        # TODO: Send email notification if notify_user is True

        return {"success": True, "message": f"User {user.username} has been suspended"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error suspending user {user_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to suspend user") from e


@router.post("/users/{user_id}/unsuspend")
async def unsuspend_user(
    user_id: str,
    request: Request,
    reason: str | None = None,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Remove suspension from a user account."""
    try:
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not user.is_suspended:
            raise HTTPException(status_code=400, detail="User is not suspended")

        # Unsuspend the user
        user.is_suspended = False
        user.suspended_at = None
        user.suspended_reason = None
        user.suspended_by_id = None
        user.is_active = True

        await db.commit()

        # Log admin action
        await log_admin_action(
            db, admin, "user.unsuspend", "user", UUID(user_id), reason=reason, request=request
        )

        logger.info(f"Admin {admin.username} unsuspended user {user.username}")

        return {"success": True, "message": f"User {user.username} has been unsuspended"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unsuspending user {user_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to unsuspend user") from e


class DeleteUserRequest(BaseModel):
    """Request body for deleting a user."""

    confirmation_email: str
    reason: str = Field(..., min_length=1, max_length=1000)
    notify_user: bool = False


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    request_data: DeleteUserRequest,
    request: Request,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Soft delete a user account."""
    try:
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if user.is_superuser:
            raise HTTPException(status_code=403, detail="Cannot delete a superuser account")

        # Verify confirmation email matches
        if request_data.confirmation_email.lower() != user.email.lower():
            raise HTTPException(status_code=400, detail="Confirmation email does not match")

        if user.is_deleted:
            raise HTTPException(status_code=400, detail="User is already deleted")

        # Soft delete the user
        user.is_deleted = True
        user.deleted_at = datetime.utcnow()
        user.deleted_reason = request_data.reason
        user.deleted_by_id = admin.id
        user.is_active = False
        user.scheduled_hard_delete_at = datetime.utcnow() + timedelta(days=30)

        await db.commit()

        # Log admin action
        await log_admin_action(
            db,
            admin,
            "user.delete",
            "user",
            UUID(user_id),
            reason=request_data.reason,
            extra_data={"notify_user": request_data.notify_user},
            request=request,
        )

        logger.info(f"Admin {admin.username} soft-deleted user {user.username}")

        # TODO: Send email notification if notify_user is True

        return {
            "success": True,
            "message": f"User {user.username} has been deleted. Data will be permanently removed after 30 days.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete user") from e


class AdjustCreditsRequest(BaseModel):
    """Request body for adjusting user credits."""

    amount: int = Field(..., description="Positive to add, negative to remove")
    reason: str = Field(..., min_length=1, max_length=500)


@router.post("/users/{user_id}/credits/adjust")
async def adjust_user_credits(
    user_id: str,
    request_data: AdjustCreditsRequest,
    request: Request,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Adjust a user's credit balance."""
    try:
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        old_balance = user.purchased_credits

        # Adjust purchased_credits (not bundled, as those reset monthly)
        new_balance = user.purchased_credits + request_data.amount
        if new_balance < 0:
            raise HTTPException(status_code=400, detail="Cannot reduce credits below zero")

        user.purchased_credits = new_balance

        await db.commit()

        # Log admin action
        await log_admin_action(
            db,
            admin,
            "user.credits_adjusted",
            "user",
            UUID(user_id),
            reason=request_data.reason,
            extra_data={
                "old_balance": old_balance,
                "adjustment": request_data.amount,
                "new_balance": new_balance,
            },
            request=request,
        )

        logger.info(
            f"Admin {admin.username} adjusted credits for {user.username}: {request_data.amount}"
        )

        return {
            "success": True,
            "old_balance": old_balance,
            "adjustment": request_data.amount,
            "new_balance": new_balance,
            "message": f"Credits adjusted by {request_data.amount}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adjusting credits for user {user_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to adjust credits") from e


# ============================================================================
# System Health Monitoring
# ============================================================================


async def check_service_health(service_name: str, check_func) -> dict[str, Any]:
    """Check health of a single service."""
    start_time = datetime.utcnow()
    try:
        await asyncio.wait_for(check_func(), timeout=10.0)
        response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
        return {
            "service": service_name,
            "status": "up",
            "response_time_ms": int(response_time),
            "error": None,
        }
    except TimeoutError:
        return {
            "service": service_name,
            "status": "down",
            "response_time_ms": 10000,
            "error": "Timeout after 10 seconds",
        }
    except Exception as e:
        response_time = (datetime.utcnow() - start_time).total_seconds() * 1000
        return {
            "service": service_name,
            "status": "down",
            "response_time_ms": int(response_time),
            "error": str(e),
        }


@router.get("/health")
async def get_system_health(
    admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Get current health status of all platform services."""
    try:
        services = []

        # Check Database
        async def check_db():
            await db.execute(select(func.now()))

        db_health = await check_service_health("database", check_db)
        services.append(db_health)

        # Check LiteLLM
        async def check_litellm():
            await litellm_service.get_available_models()

        litellm_health = await check_service_health("litellm", check_litellm)
        services.append(litellm_health)

        # Check Kubernetes (if in k8s mode)
        settings = get_settings()
        if settings.deployment_mode == "kubernetes":
            try:
                from ..services.orchestration.kubernetes.client import (
                    get_k8s_client as get_kubernetes_client,
                )

                k8s_client = get_kubernetes_client()

                async def check_k8s():
                    # Simple API check
                    await asyncio.get_running_loop().run_in_executor(
                        None, lambda: k8s_client.core_v1.list_namespace(limit=1)
                    )

                k8s_health = await check_service_health("kubernetes", check_k8s)
                services.append(k8s_health)
            except Exception as e:
                services.append(
                    {
                        "service": "kubernetes",
                        "status": "down",
                        "response_time_ms": 0,
                        "error": str(e),
                    }
                )

        # Determine overall status
        down_services = [s for s in services if s["status"] == "down"]
        degraded_services = [s for s in services if s.get("response_time_ms", 0) > 5000]

        if down_services:
            overall_status = "outage"
        elif degraded_services:
            overall_status = "degraded"
        else:
            overall_status = "operational"

        # Store health check results
        for service in services:
            health_record = HealthCheck(
                service_name=service["service"],
                status=service["status"],
                response_time_ms=service.get("response_time_ms"),
                error_message=service.get("error"),
            )
            db.add(health_record)

        await db.commit()

        # Get recent incidents (health checks that failed in last 24 hours)
        day_ago = datetime.utcnow() - timedelta(hours=24)
        incidents_query = (
            select(HealthCheck)
            .where(and_(HealthCheck.status != "up", HealthCheck.checked_at >= day_ago))
            .order_by(HealthCheck.checked_at.desc())
            .limit(10)
        )

        incidents_result = await db.execute(incidents_query)
        incidents = incidents_result.scalars().all()

        return {
            "overall_status": overall_status,
            "services": services,
            "incidents": [
                {
                    "service": i.service_name,
                    "status": i.status,
                    "error": i.error_message,
                    "time": i.checked_at.isoformat(),
                }
                for i in incidents
            ],
            "checked_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Error checking system health: {e}")
        raise HTTPException(status_code=500, detail="Failed to check system health") from e


@router.get("/health/{service}")
async def get_service_health_history(
    service: str,
    period: str = "24h",  # 1h, 24h, 7d
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get health check history for a specific service."""
    try:
        # Parse period
        if period == "1h":
            start_time = datetime.utcnow() - timedelta(hours=1)
        elif period == "7d":
            start_time = datetime.utcnow() - timedelta(days=7)
        else:
            start_time = datetime.utcnow() - timedelta(hours=24)

        # Get health history
        result = await db.execute(
            select(HealthCheck)
            .where(and_(HealthCheck.service_name == service, HealthCheck.checked_at >= start_time))
            .order_by(HealthCheck.checked_at.desc())
        )
        checks = result.scalars().all()

        if not checks:
            return {
                "service": service,
                "status": "unknown",
                "uptime_percent": 0,
                "avg_response_time_ms": 0,
                "history": [],
            }

        # Calculate statistics
        up_checks = [c for c in checks if c.status == "up"]
        uptime_percent = (len(up_checks) / len(checks)) * 100 if checks else 0

        response_times = [c.response_time_ms for c in checks if c.response_time_ms]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0

        # Current status is the most recent check
        current_status = checks[0].status if checks else "unknown"

        return {
            "service": service,
            "status": current_status,
            "uptime_percent": round(uptime_percent, 2),
            "avg_response_time_ms": int(avg_response_time),
            "checks_count": len(checks),
            "history": [
                {
                    "status": c.status,
                    "response_time_ms": c.response_time_ms,
                    "error": c.error_message,
                    "checked_at": c.checked_at.isoformat(),
                }
                for c in checks[:100]  # Limit to 100 entries
            ],
        }

    except Exception as e:
        logger.error(f"Error getting health history for {service}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get service health history") from e


@router.get("/k8s/namespaces")
async def list_kubernetes_namespaces(
    search: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all Kubernetes namespaces for user projects."""
    settings = get_settings()
    if settings.deployment_mode != "kubernetes":
        return {"namespaces": [], "total": 0, "message": "Kubernetes mode not enabled"}

    try:
        from ..services.orchestration.kubernetes.client import (
            get_k8s_client as get_kubernetes_client,
        )

        k8s_client = get_kubernetes_client()

        # Get all namespaces with proj- prefix
        all_namespaces = k8s_client.core_v1.list_namespace(
            label_selector="app.kubernetes.io/managed-by=tesslate"
        )

        namespaces_data = []
        for ns in all_namespaces.items:
            ns_name = ns.metadata.name
            if not ns_name.startswith("proj-"):
                continue

            # Apply search filter
            if search and search.lower() not in ns_name.lower():
                continue

            # Get project info from database
            project_id = ns_name.replace("proj-", "")
            project = await db.scalar(select(Project).where(cast(Project.id, String) == project_id))

            owner = None
            if project:
                owner = await db.scalar(select(User).where(User.id == project.owner_id))

            # Get pods in namespace
            try:
                pods = k8s_client.core_v1.list_namespaced_pod(ns_name)
                running_pods = len([p for p in pods.items if p.status.phase == "Running"])
                total_pods = len(pods.items)
            except Exception:
                running_pods = 0
                total_pods = 0

            # Get PVCs
            try:
                pvcs = k8s_client.core_v1.list_namespaced_persistent_volume_claim(ns_name)
                total_storage = sum(
                    int(pvc.spec.resources.requests.get("storage", "0").replace("Gi", ""))
                    for pvc in pvcs.items
                    if pvc.spec.resources.requests.get("storage")
                )
            except Exception:
                total_storage = 0

            ns_status = ns.status.phase if ns.status else "Unknown"
            if status and status.lower() != ns_status.lower():
                continue

            namespaces_data.append(
                {
                    "namespace": ns_name,
                    "project_id": project_id,
                    "project_name": project.name if project else "Unknown",
                    "owner_username": owner.username if owner else "Unknown",
                    "owner_email": owner.email if owner else None,
                    "status": ns_status,
                    "pods": f"{running_pods}/{total_pods}",
                    "storage_gb": total_storage,
                    "created_at": ns.metadata.creation_timestamp.isoformat()
                    if ns.metadata.creation_timestamp
                    else None,
                }
            )

        # Pagination
        total = len(namespaces_data)
        start = (page - 1) * page_size
        end = start + page_size
        paginated = namespaces_data[start:end]

        return {
            "namespaces": paginated,
            "total": total,
            "page": page,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    except Exception as e:
        logger.error(f"Error listing k8s namespaces: {e}")
        raise HTTPException(status_code=500, detail="Failed to list Kubernetes namespaces") from e


@router.get("/k8s/namespaces/{namespace}")
async def get_namespace_details(
    namespace: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Get detailed information about a Kubernetes namespace."""
    settings = get_settings()
    if settings.deployment_mode != "kubernetes":
        raise HTTPException(status_code=400, detail="Kubernetes mode not enabled")

    try:
        from ..services.orchestration.kubernetes.client import (
            get_k8s_client as get_kubernetes_client,
        )

        k8s_client = get_kubernetes_client()

        # Get namespace
        try:
            ns = k8s_client.core_v1.read_namespace(namespace)
        except Exception as e:
            raise HTTPException(status_code=404, detail="Namespace not found") from e

        # Get project info
        project_id = namespace.replace("proj-", "")
        project = await db.scalar(select(Project).where(cast(Project.id, String) == project_id))
        owner = None
        if project:
            owner = await db.scalar(select(User).where(User.id == project.owner_id))

        # Get pods
        pods = k8s_client.core_v1.list_namespaced_pod(namespace)
        pods_data = []
        for pod in pods.items:
            pods_data.append(
                {
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "ready": all(c.ready for c in pod.status.container_statuses or []),
                    "restarts": sum(c.restart_count for c in pod.status.container_statuses or []),
                    "created_at": pod.metadata.creation_timestamp.isoformat()
                    if pod.metadata.creation_timestamp
                    else None,
                }
            )

        # Get PVCs
        pvcs = k8s_client.core_v1.list_namespaced_persistent_volume_claim(namespace)
        pvcs_data = [
            {
                "name": pvc.metadata.name,
                "status": pvc.status.phase,
                "storage": pvc.spec.resources.requests.get("storage", "Unknown"),
                "storage_class": pvc.spec.storage_class_name,
            }
            for pvc in pvcs.items
        ]

        # Get ingresses
        ingresses = k8s_client.networking_v1.list_namespaced_ingress(namespace)
        ingresses_data = []
        for ing in ingresses.items:
            for rule in ing.spec.rules or []:
                ingresses_data.append({"host": rule.host, "tls": bool(ing.spec.tls)})

        return {
            "namespace": namespace,
            "status": ns.status.phase,
            "project": {
                "id": project_id,
                "name": project.name if project else None,
                "slug": project.slug if project else None,
            },
            "owner": {
                "id": str(owner.id) if owner else None,
                "username": owner.username if owner else None,
                "email": owner.email if owner else None,
            },
            "pods": pods_data,
            "pvcs": pvcs_data,
            "ingresses": ingresses_data,
            "created_at": ns.metadata.creation_timestamp.isoformat()
            if ns.metadata.creation_timestamp
            else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting namespace {namespace} details: {e}")
        raise HTTPException(status_code=500, detail="Failed to get namespace details") from e


@router.get("/k8s/namespaces/{namespace}/logs/{pod}")
async def get_pod_logs(
    namespace: str,
    pod: str,
    container: str | None = None,
    tail_lines: int = Query(100, ge=1, le=1000),
    admin: User = Depends(current_superuser),
) -> dict[str, Any]:
    """Get logs from a pod in a namespace."""
    settings = get_settings()
    if settings.deployment_mode != "kubernetes":
        raise HTTPException(status_code=400, detail="Kubernetes mode not enabled")

    try:
        from ..services.orchestration.kubernetes.client import (
            get_k8s_client as get_kubernetes_client,
        )

        k8s_client = get_kubernetes_client()

        logs = k8s_client.core_v1.read_namespaced_pod_log(
            name=pod, namespace=namespace, container=container, tail_lines=tail_lines
        )

        return {"namespace": namespace, "pod": pod, "container": container, "logs": logs}

    except Exception as e:
        logger.error(f"Error getting logs for {namespace}/{pod}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get pod logs") from e


@router.post("/k8s/namespaces/{namespace}/pods/{pod}/restart")
async def restart_pod(
    namespace: str,
    pod: str,
    request: Request,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Restart a pod by deleting it (Kubernetes will recreate it)."""
    settings = get_settings()
    if settings.deployment_mode != "kubernetes":
        raise HTTPException(status_code=400, detail="Kubernetes mode not enabled")

    try:
        from ..services.orchestration.kubernetes.client import (
            get_k8s_client as get_kubernetes_client,
        )

        k8s_client = get_kubernetes_client()

        # Delete pod (controller will recreate it)
        k8s_client.core_v1.delete_namespaced_pod(name=pod, namespace=namespace)

        # Log admin action
        project_id = namespace.replace("proj-", "")
        with contextlib.suppress(Exception):
            await log_admin_action(
                db,
                admin,
                "k8s.pod.restart",
                "pod",
                UUID(project_id),
                extra_data={"namespace": namespace, "pod": pod},
                request=request,
            )

        logger.info(f"Admin {admin.username} restarted pod {pod} in {namespace}")

        return {"success": True, "message": f"Pod {pod} restart initiated"}

    except Exception as e:
        logger.error(f"Error restarting pod {namespace}/{pod}: {e}")
        raise HTTPException(status_code=500, detail="Failed to restart pod") from e


@router.delete("/k8s/namespaces/{namespace}")
async def delete_namespace(
    namespace: str,
    reason: str,
    request: Request,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a Kubernetes namespace (cascades to all resources)."""
    settings = get_settings()
    if settings.deployment_mode != "kubernetes":
        raise HTTPException(status_code=400, detail="Kubernetes mode not enabled")

    try:
        from ..services.orchestration.kubernetes.client import (
            get_k8s_client as get_kubernetes_client,
        )

        k8s_client = get_kubernetes_client()

        # Safety check - don't delete system namespaces
        if not namespace.startswith("proj-"):
            raise HTTPException(status_code=400, detail="Can only delete project namespaces")

        # Delete the namespace
        k8s_client.core_v1.delete_namespace(name=namespace)

        # Log admin action
        project_id = namespace.replace("proj-", "")
        with contextlib.suppress(Exception):
            await log_admin_action(
                db,
                admin,
                "k8s.namespace.delete",
                "namespace",
                UUID(project_id),
                reason=reason,
                extra_data={"namespace": namespace},
                request=request,
            )

        logger.info(f"Admin {admin.username} deleted namespace {namespace}")

        return {"success": True, "message": f"Namespace {namespace} deletion initiated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting namespace {namespace}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete namespace") from e


# ============================================================================
# Enhanced Token Analytics
# ============================================================================


@router.get("/analytics/tokens")
async def get_enhanced_token_analytics(
    period: str = "30d",  # 1h, 24h, 7d, 30d, 90d
    group_by: str | None = None,  # model, user, agent, tier
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get enhanced token usage analytics with multiple breakdowns."""
    try:
        # Parse period
        if period == "1h":
            start_time = datetime.utcnow() - timedelta(hours=1)
        elif period == "24h":
            start_time = datetime.utcnow() - timedelta(hours=24)
        elif period == "7d":
            start_time = datetime.utcnow() - timedelta(days=7)
        elif period == "90d":
            start_time = datetime.utcnow() - timedelta(days=90)
        else:
            start_time = datetime.utcnow() - timedelta(days=30)

        # Get summary metrics
        summary_query = select(
            func.sum(UsageLog.tokens_input).label("tokens_in"),
            func.sum(UsageLog.tokens_output).label("tokens_out"),
            func.sum(UsageLog.cost_total).label("cost_total"),
            func.count(distinct(UsageLog.user_id)).label("active_users"),
        ).where(UsageLog.created_at >= start_time)

        summary_result = await db.execute(summary_query)
        summary = summary_result.one()

        tokens_in = summary.tokens_in or 0
        tokens_out = summary.tokens_out or 0
        cost_total = summary.cost_total or 0
        active_users = summary.active_users or 0

        # Breakdown by model
        by_model_query = (
            select(
                UsageLog.model,
                func.sum(UsageLog.tokens_input).label("tokens_in"),
                func.sum(UsageLog.tokens_output).label("tokens_out"),
                func.sum(UsageLog.cost_total).label("cost"),
                func.count().label("requests"),
            )
            .where(UsageLog.created_at >= start_time)
            .group_by(UsageLog.model)
        )

        by_model_result = await db.execute(by_model_query)
        by_model = [
            {
                "model": r.model,
                "tokens_in": r.tokens_in or 0,
                "tokens_out": r.tokens_out or 0,
                "cost_cents": r.cost or 0,
                "requests": r.requests,
            }
            for r in by_model_result
        ]

        # Breakdown by user (top 20)
        by_user_query = (
            select(
                UsageLog.user_id,
                func.sum(UsageLog.tokens_input).label("tokens_in"),
                func.sum(UsageLog.tokens_output).label("tokens_out"),
                func.sum(UsageLog.cost_total).label("cost"),
            )
            .where(UsageLog.created_at >= start_time)
            .group_by(UsageLog.user_id)
            .order_by(desc(func.sum(UsageLog.cost_total)))
            .limit(20)
        )

        by_user_result = await db.execute(by_user_query)
        by_user_raw = by_user_result.all()

        by_user = []
        for r in by_user_raw:
            user = await db.scalar(select(User).where(User.id == r.user_id))
            by_user.append(
                {
                    "user_id": str(r.user_id),
                    "username": user.username if user else "Unknown",
                    "email": user.email if user else None,
                    "tokens_in": r.tokens_in or 0,
                    "tokens_out": r.tokens_out or 0,
                    "cost_cents": r.cost or 0,
                }
            )

        # Breakdown by subscription tier
        by_tier_query = """
            SELECT u.subscription_tier as tier,
                   SUM(ul.tokens_input) as tokens_in,
                   SUM(ul.tokens_output) as tokens_out,
                   SUM(ul.cost_total) as cost,
                   COUNT(DISTINCT ul.user_id) as users
            FROM usage_logs ul
            JOIN users u ON ul.user_id = u.id
            WHERE ul.created_at >= :start_time
            GROUP BY u.subscription_tier
        """
        # Using raw SQL for the join query
        from sqlalchemy import text

        by_tier_result = await db.execute(text(by_tier_query), {"start_time": start_time})
        by_tier = [
            {
                "tier": r.tier,
                "tokens_in": r.tokens_in or 0,
                "tokens_out": r.tokens_out or 0,
                "cost_cents": r.cost or 0,
                "users": r.users,
            }
            for r in by_tier_result
        ]

        # Daily timeline - use text() to avoid parameterization issues with date_trunc
        from sqlalchemy import literal_column, text

        date_trunc_expr = func.date_trunc(literal_column("'day'"), UsageLog.created_at)
        timeline_query = (
            select(
                date_trunc_expr.label("date"),
                func.sum(UsageLog.tokens_input).label("tokens_in"),
                func.sum(UsageLog.tokens_output).label("tokens_out"),
                func.sum(UsageLog.cost_total).label("cost"),
            )
            .where(UsageLog.created_at >= start_time)
            .group_by(date_trunc_expr)
            .order_by(date_trunc_expr)
        )

        timeline_result = await db.execute(timeline_query)
        timeline = [
            {
                "date": r.date.isoformat() if r.date else None,
                "tokens_in": r.tokens_in or 0,
                "tokens_out": r.tokens_out or 0,
                "cost_cents": r.cost or 0,
            }
            for r in timeline_result
        ]

        # Calculate projected monthly cost
        days_in_period = {"1h": 1 / 24, "24h": 1, "7d": 7, "30d": 30, "90d": 90}.get(period, 30)

        daily_avg_cost = cost_total / days_in_period if days_in_period > 0 else 0
        projected_monthly = daily_avg_cost * 30

        return {
            "summary": {
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tokens_total": tokens_in + tokens_out,
                "cost_cents": cost_total,
                "cost_dollars": cost_total / 100,
                "active_users": active_users,
                "projected_monthly_cents": int(projected_monthly),
                "projected_monthly_dollars": projected_monthly / 100,
            },
            "by_model": by_model,
            "by_user": by_user,
            "by_tier": by_tier,
            "timeline": timeline,
            "period": period,
        }

    except Exception as e:
        logger.error(f"Error getting token analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get token analytics") from e


@router.get("/analytics/tokens/anomalies")
async def get_usage_anomalies(
    period: str = "24h",
    threshold: float = 3.0,  # Standard deviations
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Detect anomalous usage patterns."""
    try:
        # Parse period
        if period == "7d":
            start_time = datetime.utcnow() - timedelta(days=7)
        elif period == "30d":
            start_time = datetime.utcnow() - timedelta(days=30)
        else:
            start_time = datetime.utcnow() - timedelta(hours=24)

        # Get user usage statistics
        user_stats_query = (
            select(
                UsageLog.user_id,
                func.sum(UsageLog.cost_total).label("total_cost"),
                func.count().label("request_count"),
            )
            .where(UsageLog.created_at >= start_time)
            .group_by(UsageLog.user_id)
        )

        user_stats_result = await db.execute(user_stats_query)
        user_stats = user_stats_result.all()

        if not user_stats:
            return {"anomalies": [], "threshold": threshold}

        # Calculate mean and std for cost
        costs = [u.total_cost or 0 for u in user_stats]
        mean_cost = sum(costs) / len(costs) if costs else 0
        variance = sum((c - mean_cost) ** 2 for c in costs) / len(costs) if costs else 0
        std_cost = variance**0.5

        # Find anomalies
        anomalies = []
        for u in user_stats:
            cost = u.total_cost or 0
            if std_cost > 0 and (cost - mean_cost) / std_cost > threshold:
                user = await db.scalar(select(User).where(User.id == u.user_id))
                anomalies.append(
                    {
                        "user_id": str(u.user_id),
                        "username": user.username if user else "Unknown",
                        "email": user.email if user else None,
                        "cost_cents": cost,
                        "request_count": u.request_count,
                        "deviation": round((cost - mean_cost) / std_cost, 2) if std_cost > 0 else 0,
                        "severity": "high"
                        if (cost - mean_cost) / std_cost > threshold * 2
                        else "medium",
                    }
                )

        # Sort by deviation
        anomalies.sort(key=lambda x: x["deviation"], reverse=True)

        return {
            "anomalies": anomalies[:20],  # Top 20
            "threshold": threshold,
            "mean_cost_cents": int(mean_cost),
            "std_cost_cents": int(std_cost),
            "period": period,
        }

    except Exception as e:
        logger.error(f"Error detecting anomalies: {e}")
        raise HTTPException(status_code=500, detail="Failed to detect anomalies") from e


@router.get("/audit-logs")
async def get_audit_logs(
    search: str | None = None,
    action_type: str | None = None,
    admin_id: str | None = None,
    target_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get admin action audit logs."""
    try:
        query = select(AdminAction)
        count_query = select(func.count(AdminAction.id))

        filters = []

        if action_type:
            filters.append(AdminAction.action_type == action_type)
        if admin_id:
            filters.append(AdminAction.admin_id == admin_id)
        if target_type:
            filters.append(AdminAction.target_type == target_type)
        if date_from:
            filters.append(AdminAction.created_at >= date_from)
        if date_to:
            filters.append(AdminAction.created_at <= date_to)

        if filters:
            query = query.where(and_(*filters))
            count_query = count_query.where(and_(*filters))

        total = await db.scalar(count_query)

        # Pagination
        offset = (page - 1) * page_size
        query = query.order_by(AdminAction.created_at.desc()).offset(offset).limit(page_size)

        result = await db.execute(query)
        logs = result.scalars().all()

        # Format response
        logs_data = []
        for log in logs:
            admin_user = (
                await db.scalar(select(User).where(User.id == log.admin_id))
                if log.admin_id
                else None
            )
            logs_data.append(
                {
                    "id": str(log.id),
                    "admin_id": str(log.admin_id) if log.admin_id else None,
                    "admin_username": admin_user.username if admin_user else None,
                    "action_type": log.action_type,
                    "target_type": log.target_type,
                    "target_id": str(log.target_id),
                    "reason": log.reason,
                    "extra_data": log.extra_data,
                    "ip_address": log.ip_address,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
            )

        return {
            "logs": logs_data,
            "total": total,
            "page": page,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    except Exception as e:
        logger.error(f"Error getting audit logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to get audit logs") from e


# ============================================================================
# Project Administration
# ============================================================================


@router.get("/projects")
async def list_admin_projects(
    search: str | None = None,
    owner_id: str | None = None,
    status: str | None = None,  # active, hibernated
    deployment_status: str | None = None,  # development, deployed
    has_containers: bool | None = None,
    has_git: bool | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all projects with admin filters."""
    try:
        query = select(Project).options(selectinload(Project.owner))
        count_query = select(func.count(Project.id))

        filters = []

        # Search by name or slug
        if search:
            search_pattern = f"%{search}%"
            filters.append(
                or_(Project.name.ilike(search_pattern), Project.slug.ilike(search_pattern))
            )

        if owner_id:
            filters.append(Project.owner_id == owner_id)

        if status:
            if status == "active":
                filters.append(Project.environment_status == "active")
            elif status == "hibernated":
                filters.append(Project.environment_status == "hibernated")

        if deployment_status:
            if deployment_status == "deployed":
                filters.append(Project.is_deployed.is_(True))
            elif deployment_status == "development":
                filters.append(Project.is_deployed.is_(False))

        if has_git is not None:
            filters.append(Project.has_git_repo == has_git)

        if created_after:
            filters.append(Project.created_at >= created_after)
        if created_before:
            filters.append(Project.created_at <= created_before)

        if filters:
            query = query.where(and_(*filters))
            count_query = count_query.where(and_(*filters))

        total = await db.scalar(count_query)

        # Apply sorting
        sort_column = getattr(Project, sort_by, Project.created_at)
        if sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))

        # Pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await db.execute(query)
        projects = result.scalars().all()

        # Format response
        projects_data = []
        for p in projects:
            # Get deployment count
            deployment_count = await db.scalar(
                select(func.count(Deployment.id)).where(Deployment.project_id == p.id)
            )

            projects_data.append(
                {
                    "id": str(p.id),
                    "name": p.name,
                    "slug": p.slug,
                    "description": p.description,
                    "owner_id": str(p.owner_id),
                    "owner_username": p.owner.username if p.owner else None,
                    "owner_email": p.owner.email if p.owner else None,
                    "environment_status": p.environment_status,
                    "is_deployed": p.is_deployed,
                    "deploy_type": p.deploy_type,
                    "has_git_repo": p.has_git_repo,
                    "deployment_count": deployment_count or 0,
                    "last_activity": p.last_activity.isoformat() if p.last_activity else None,
                    "hibernated_at": p.hibernated_at.isoformat() if p.hibernated_at else None,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
            )

        # Filter by has_containers after getting data
        if has_containers is not None:
            # Get container counts for all projects
            for proj_data in projects_data:
                count = await db.scalar(
                    select(func.count()).select_from(
                        select(Project).where(Project.id == proj_data["id"])
                    )
                )
                proj_data["_has_containers"] = count > 0

            if has_containers:
                projects_data = [p for p in projects_data if p.get("_has_containers", False)]
            else:
                projects_data = [p for p in projects_data if not p.get("_has_containers", False)]

            # Clean up temp field
            for p in projects_data:
                p.pop("_has_containers", None)

        return {
            "projects": projects_data,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    except Exception as e:
        logger.error(f"Error listing projects: {e}")
        raise HTTPException(status_code=500, detail="Failed to list projects") from e


@router.get("/projects/{project_id}")
async def get_admin_project_detail(
    project_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Get detailed information about a specific project."""
    try:
        result = await db.execute(
            select(Project)
            .options(
                selectinload(Project.owner),
                selectinload(Project.containers),
                selectinload(Project.deployments),
            )
            .where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Get file count
        from ..models import ProjectFile

        file_count = await db.scalar(
            select(func.count(ProjectFile.id)).where(ProjectFile.project_id == project.id)
        )

        # Get recent deployments
        recent_deployments = sorted(
            project.deployments, key=lambda d: d.created_at or datetime.min, reverse=True
        )[:5]

        return {
            "id": str(project.id),
            "name": project.name,
            "slug": project.slug,
            "description": project.description,
            "owner": {
                "id": str(project.owner.id) if project.owner else None,
                "username": project.owner.username if project.owner else None,
                "email": project.owner.email if project.owner else None,
            },
            "environment_status": project.environment_status,
            "is_deployed": project.is_deployed,
            "deploy_type": project.deploy_type,
            "deployed_at": project.deployed_at.isoformat() if project.deployed_at else None,
            "has_git_repo": project.has_git_repo,
            "git_remote_url": project.git_remote_url,
            "network_name": project.network_name,
            "volume_name": project.volume_name,
            "file_count": file_count or 0,
            "containers": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "container_type": c.container_type,
                    "status": c.status,
                    "port": c.port,
                }
                for c in project.containers
            ],
            "recent_deployments": [
                {
                    "id": str(d.id),
                    "provider": d.provider,
                    "status": d.status,
                    "deployment_url": d.deployment_url,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in recent_deployments
            ],
            "last_activity": project.last_activity.isoformat() if project.last_activity else None,
            "hibernated_at": project.hibernated_at.isoformat() if project.hibernated_at else None,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project {project_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get project details") from e


class HibernateProjectRequest(BaseModel):
    """Request body for hibernating a project."""

    reason: str = Field(..., min_length=1, max_length=500)


@router.post("/projects/{project_id}/hibernate")
async def force_hibernate_project(
    project_id: str,
    request_data: HibernateProjectRequest,
    request: Request,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Force hibernate a project."""
    try:
        project = await db.scalar(select(Project).where(Project.id == project_id))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        if project.environment_status == "hibernated":
            raise HTTPException(status_code=400, detail="Project is already hibernated")

        # Update project status
        project.environment_status = "hibernated"
        project.hibernated_at = datetime.utcnow()

        await db.commit()

        # Log admin action
        await log_admin_action(
            db,
            admin,
            "project.hibernate",
            "project",
            UUID(project_id),
            reason=request_data.reason,
            request=request,
        )

        logger.info(f"Admin {admin.username} force-hibernated project {project.name}")

        return {"success": True, "message": f"Project {project.name} has been hibernated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error hibernating project {project_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to hibernate project") from e


class TransferProjectRequest(BaseModel):
    """Request body for transferring project ownership."""

    new_owner_id: str
    reason: str = Field(..., min_length=1, max_length=500)


@router.post("/projects/{project_id}/transfer")
async def transfer_project_ownership(
    project_id: str,
    request_data: TransferProjectRequest,
    request: Request,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Transfer project ownership to another user."""
    try:
        project = await db.scalar(select(Project).where(Project.id == project_id))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Verify new owner exists
        new_owner = await db.scalar(select(User).where(User.id == request_data.new_owner_id))
        if not new_owner:
            raise HTTPException(status_code=404, detail="New owner not found")

        old_owner_id = project.owner_id

        # Transfer ownership
        project.owner_id = UUID(request_data.new_owner_id)

        await db.commit()

        # Log admin action
        await log_admin_action(
            db,
            admin,
            "project.transfer",
            "project",
            UUID(project_id),
            reason=request_data.reason,
            extra_data={
                "old_owner_id": str(old_owner_id),
                "new_owner_id": request_data.new_owner_id,
            },
            request=request,
        )

        logger.info(
            f"Admin {admin.username} transferred project {project.name} to {new_owner.username}"
        )

        return {
            "success": True,
            "message": f"Project {project.name} transferred to {new_owner.username}",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error transferring project {project_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to transfer project") from e


class DeleteProjectRequest(BaseModel):
    """Request body for deleting a project."""

    reason: str = Field(..., min_length=1, max_length=500)


@router.delete("/projects/{project_id}")
async def force_delete_project(
    project_id: str,
    request_data: DeleteProjectRequest,
    request: Request,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Force delete a project (hard delete)."""
    try:
        project = await db.scalar(select(Project).where(Project.id == project_id))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        project_name = project.name

        # Delete the project (cascades to related records)
        await db.delete(project)
        await db.commit()

        # Log admin action
        await log_admin_action(
            db,
            admin,
            "project.delete",
            "project",
            UUID(project_id),
            reason=request_data.reason,
            extra_data={"project_name": project_name},
            request=request,
        )

        logger.info(f"Admin {admin.username} deleted project {project_name}")

        return {"success": True, "message": f"Project {project_name} has been deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting project {project_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete project") from e


# ============================================================================
# Billing Administration
# ============================================================================


@router.get("/billing/overview")
async def get_billing_overview(
    period: str = "30d",  # 7d, 30d, 90d
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get billing overview with revenue metrics."""
    try:
        # Parse period
        if period == "7d":
            start_time = datetime.utcnow() - timedelta(days=7)
            days = 7
        elif period == "90d":
            start_time = datetime.utcnow() - timedelta(days=90)
            days = 90
        else:
            start_time = datetime.utcnow() - timedelta(days=30)
            days = 30

        # Get subscription revenue by tier
        tier_counts = {}
        tier_revenue = {}
        tier_prices = {"free": 0, "basic": 900, "pro": 2900, "ultra": 9900}  # cents/month

        tier_query = (
            select(User.subscription_tier, func.count(User.id).label("count"))
            .where(User.is_deleted.is_(False))
            .group_by(User.subscription_tier)
        )

        tier_result = await db.execute(tier_query)
        for r in tier_result:
            tier_counts[r.subscription_tier or "free"] = r.count
            tier_revenue[r.subscription_tier or "free"] = r.count * tier_prices.get(
                r.subscription_tier or "free", 0
            )

        subscription_mrr = sum(tier_revenue.values())

        # Get credit purchase revenue in period
        credit_revenue_query = select(func.sum(CreditPurchase.amount_cents)).where(
            and_(CreditPurchase.created_at >= start_time, CreditPurchase.status == "completed")
        )
        credit_revenue = await db.scalar(credit_revenue_query) or 0

        # Get total credit purchases
        total_credit_purchases = (
            await db.scalar(
                select(func.count(CreditPurchase.id)).where(
                    and_(
                        CreditPurchase.created_at >= start_time,
                        CreditPurchase.status == "completed",
                    )
                )
            )
            or 0
        )

        # Get marketplace revenue (agent purchases)
        marketplace_revenue_query = (
            select(func.sum(MarketplaceAgent.price))
            .join(UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
            .where(UserPurchasedAgent.purchase_date >= start_time)
        )

        marketplace_revenue = await db.scalar(marketplace_revenue_query) or 0

        # Daily revenue timeline
        daily_revenue = []
        for i in range(days):
            day = datetime.utcnow() - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            day_credits = (
                await db.scalar(
                    select(func.sum(CreditPurchase.amount_cents)).where(
                        and_(
                            CreditPurchase.created_at >= day_start,
                            CreditPurchase.created_at < day_end,
                            CreditPurchase.status == "completed",
                        )
                    )
                )
                or 0
            )

            daily_revenue.append(
                {
                    "date": day_start.isoformat(),
                    "credits": day_credits,
                    "total": day_credits,  # Add marketplace when available
                }
            )

        daily_revenue.reverse()

        total_revenue = subscription_mrr + credit_revenue + marketplace_revenue

        return {
            "summary": {
                "subscription_mrr_cents": subscription_mrr,
                "credit_revenue_cents": credit_revenue,
                "marketplace_revenue_cents": marketplace_revenue,
                "total_revenue_cents": total_revenue,
                "total_revenue_dollars": total_revenue / 100,
            },
            "subscriptions": {
                "by_tier": tier_counts,
                "revenue_by_tier": tier_revenue,
                "total_subscribers": sum(v for k, v in tier_counts.items() if k != "free"),
            },
            "credits": {"total_purchases": total_credit_purchases, "revenue_cents": credit_revenue},
            "marketplace": {"revenue_cents": marketplace_revenue},
            "timeline": daily_revenue,
            "period": period,
        }

    except Exception as e:
        logger.error(f"Error getting billing overview: {e}")
        raise HTTPException(status_code=500, detail="Failed to get billing overview") from e


@router.get("/billing/credit-purchases")
async def list_credit_purchases(
    user_id: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List credit purchases with filters."""
    try:
        query = select(CreditPurchase)
        count_query = select(func.count(CreditPurchase.id))

        filters = []

        if user_id:
            filters.append(CreditPurchase.user_id == user_id)
        if status:
            filters.append(CreditPurchase.status == status)
        if date_from:
            filters.append(CreditPurchase.created_at >= date_from)
        if date_to:
            filters.append(CreditPurchase.created_at <= date_to)

        if filters:
            query = query.where(and_(*filters))
            count_query = count_query.where(and_(*filters))

        total = await db.scalar(count_query)

        # Pagination
        offset = (page - 1) * page_size
        query = query.order_by(CreditPurchase.created_at.desc()).offset(offset).limit(page_size)

        result = await db.execute(query)
        purchases = result.scalars().all()

        purchases_data = []
        for p in purchases:
            user = await db.scalar(select(User).where(User.id == p.user_id)) if p.user_id else None
            purchases_data.append(
                {
                    "id": str(p.id),
                    "user_id": str(p.user_id) if p.user_id else None,
                    "user_email": user.email if user else None,
                    "user_username": user.username if user else None,
                    "amount_cents": p.amount_cents,
                    "credits_amount": p.credits_amount,
                    "status": p.status,
                    "stripe_payment_intent": p.stripe_payment_intent,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    "completed_at": p.completed_at.isoformat() if p.completed_at else None,
                }
            )

        return {
            "purchases": purchases_data,
            "total": total,
            "page": page,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    except Exception as e:
        logger.error(f"Error listing credit purchases: {e}")
        raise HTTPException(status_code=500, detail="Failed to list credit purchases") from e


@router.get("/billing/creator-payouts")
async def list_creator_payouts(
    creator_id: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List creator payout information."""
    try:
        # Get all users with creator accounts
        query = select(User).where(User.creator_stripe_account_id.is_not(None))

        if creator_id:
            query = query.where(User.id == creator_id)

        result = await db.execute(query.order_by(User.created_at.desc()))
        creators = result.scalars().all()

        creators_data = []
        for creator in creators:
            # Calculate total earnings from agent sales
            earnings_query = (
                select(func.sum(MarketplaceAgent.price))
                .join(UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
                .where(
                    or_(
                        MarketplaceAgent.created_by_user_id == creator.id,
                        MarketplaceAgent.forked_by_user_id == creator.id,
                    )
                )
            )
            total_earnings = await db.scalar(earnings_query) or 0

            # Count agents
            agent_count = (
                await db.scalar(
                    select(func.count(MarketplaceAgent.id)).where(
                        or_(
                            MarketplaceAgent.created_by_user_id == creator.id,
                            MarketplaceAgent.forked_by_user_id == creator.id,
                        )
                    )
                )
                or 0
            )

            creators_data.append(
                {
                    "id": str(creator.id),
                    "username": creator.username,
                    "email": creator.email,
                    "stripe_account_id": creator.creator_stripe_account_id,
                    "agent_count": agent_count,
                    "total_earnings_cents": total_earnings,
                    "created_at": creator.created_at.isoformat() if creator.created_at else None,
                }
            )

        return {"creators": creators_data, "total": len(creators_data), "page": page, "pages": 1}

    except Exception as e:
        logger.error(f"Error listing creator payouts: {e}")
        raise HTTPException(status_code=500, detail="Failed to list creator payouts") from e


# ============================================================================
# Deployment Monitoring
# ============================================================================


@router.get("/deployments")
async def list_admin_deployments(
    provider: str | None = None,
    status: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all deployments with filters."""
    try:
        query = select(Deployment)
        count_query = select(func.count(Deployment.id))

        filters = []

        if provider:
            filters.append(Deployment.provider == provider)
        if status:
            filters.append(Deployment.status == status)
        if user_id:
            filters.append(Deployment.user_id == user_id)
        if project_id:
            filters.append(Deployment.project_id == project_id)
        if date_from:
            filters.append(Deployment.created_at >= date_from)
        if date_to:
            filters.append(Deployment.created_at <= date_to)

        if filters:
            query = query.where(and_(*filters))
            count_query = count_query.where(and_(*filters))

        total = await db.scalar(count_query)

        # Pagination
        offset = (page - 1) * page_size
        query = query.order_by(Deployment.created_at.desc()).offset(offset).limit(page_size)

        result = await db.execute(query)
        deployments = result.scalars().all()

        deployments_data = []
        for d in deployments:
            user = await db.scalar(select(User).where(User.id == d.user_id)) if d.user_id else None
            project = (
                await db.scalar(select(Project).where(Project.id == d.project_id))
                if d.project_id
                else None
            )

            deployments_data.append(
                {
                    "id": str(d.id),
                    "project_id": str(d.project_id),
                    "project_name": project.name if project else None,
                    "user_id": str(d.user_id),
                    "user_username": user.username if user else None,
                    "provider": d.provider,
                    "deployment_id": d.deployment_id,
                    "deployment_url": d.deployment_url,
                    "version": d.version,
                    "status": d.status,
                    "error": d.error,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "completed_at": d.completed_at.isoformat() if d.completed_at else None,
                }
            )

        return {
            "deployments": deployments_data,
            "total": total,
            "page": page,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    except Exception as e:
        logger.error(f"Error listing deployments: {e}")
        raise HTTPException(status_code=500, detail="Failed to list deployments") from e


@router.get("/deployments/stats")
async def get_deployment_stats(
    period: str = "30d",
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get deployment statistics."""
    try:
        # Parse period
        if period == "7d":
            start_time = datetime.utcnow() - timedelta(days=7)
        elif period == "90d":
            start_time = datetime.utcnow() - timedelta(days=90)
        else:
            start_time = datetime.utcnow() - timedelta(days=30)

        # Get counts by provider
        by_provider_query = (
            select(
                Deployment.provider,
                func.count(Deployment.id).label("total"),
                func.count(Deployment.id).filter(Deployment.status == "success").label("success"),
                func.count(Deployment.id).filter(Deployment.status == "failed").label("failed"),
            )
            .where(Deployment.created_at >= start_time)
            .group_by(Deployment.provider)
        )

        by_provider_result = await db.execute(by_provider_query)
        by_provider = [
            {
                "provider": r.provider,
                "total": r.total,
                "success": r.success,
                "failed": r.failed,
                "success_rate": round((r.success / r.total * 100) if r.total > 0 else 0, 1),
            }
            for r in by_provider_result
        ]

        # Get counts by status
        by_status_query = (
            select(Deployment.status, func.count(Deployment.id).label("count"))
            .where(Deployment.created_at >= start_time)
            .group_by(Deployment.status)
        )

        by_status_result = await db.execute(by_status_query)
        by_status = {r.status: r.count for r in by_status_result}

        # Get total deployments
        total = (
            await db.scalar(
                select(func.count(Deployment.id)).where(Deployment.created_at >= start_time)
            )
            or 0
        )

        success = by_status.get("success", 0)
        failed = by_status.get("failed", 0)
        overall_success_rate = round((success / total * 100) if total > 0 else 0, 1)

        # Daily deployment counts
        days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
        daily_deployments = []
        for i in range(days):
            day = datetime.utcnow() - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            day_count = (
                await db.scalar(
                    select(func.count(Deployment.id)).where(
                        and_(Deployment.created_at >= day_start, Deployment.created_at < day_end)
                    )
                )
                or 0
            )

            day_success = (
                await db.scalar(
                    select(func.count(Deployment.id)).where(
                        and_(
                            Deployment.created_at >= day_start,
                            Deployment.created_at < day_end,
                            Deployment.status == "success",
                        )
                    )
                )
                or 0
            )

            daily_deployments.append(
                {"date": day_start.isoformat(), "total": day_count, "success": day_success}
            )

        daily_deployments.reverse()

        return {
            "summary": {
                "total_deployments": total,
                "successful": success,
                "failed": failed,
                "pending": by_status.get("pending", 0) + by_status.get("building", 0),
                "success_rate": overall_success_rate,
            },
            "by_provider": by_provider,
            "by_status": by_status,
            "timeline": daily_deployments,
            "period": period,
        }

    except Exception as e:
        logger.error(f"Error getting deployment stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get deployment stats") from e


@router.get("/deployments/{deployment_id}")
async def get_admin_deployment_detail(
    deployment_id: str, admin: User = Depends(current_superuser), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Get detailed information about a specific deployment."""
    try:
        result = await db.execute(select(Deployment).where(Deployment.id == deployment_id))
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")

        user = (
            await db.scalar(select(User).where(User.id == deployment.user_id))
            if deployment.user_id
            else None
        )
        project = (
            await db.scalar(select(Project).where(Project.id == deployment.project_id))
            if deployment.project_id
            else None
        )

        return {
            "id": str(deployment.id),
            "project": {
                "id": str(deployment.project_id),
                "name": project.name if project else None,
                "slug": project.slug if project else None,
            },
            "user": {
                "id": str(deployment.user_id),
                "username": user.username if user else None,
                "email": user.email if user else None,
            },
            "provider": deployment.provider,
            "deployment_id": deployment.deployment_id,
            "deployment_url": deployment.deployment_url,
            "version": deployment.version,
            "status": deployment.status,
            "error": deployment.error,
            "logs": deployment.logs,
            "metadata": deployment.deployment_metadata,
            "created_at": deployment.created_at.isoformat() if deployment.created_at else None,
            "updated_at": deployment.updated_at.isoformat() if deployment.updated_at else None,
            "completed_at": deployment.completed_at.isoformat()
            if deployment.completed_at
            else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting deployment {deployment_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get deployment details") from e


@router.get("/audit-logs/export")
async def export_audit_logs(
    action_type: str | None = None,
    target_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
):
    """Export audit logs to CSV."""
    try:
        query = select(AdminAction)
        filters = []

        if action_type:
            filters.append(AdminAction.action_type == action_type)
        if target_type:
            filters.append(AdminAction.target_type == target_type)
        if date_from:
            filters.append(AdminAction.created_at >= date_from)
        if date_to:
            filters.append(AdminAction.created_at <= date_to)

        if filters:
            query = query.where(and_(*filters))

        result = await db.execute(query.order_by(AdminAction.created_at.desc()))
        logs = result.scalars().all()

        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "ID",
                "Admin ID",
                "Action Type",
                "Target Type",
                "Target ID",
                "Reason",
                "IP Address",
                "Created At",
            ]
        )

        for log in logs:
            writer.writerow(
                [
                    str(log.id),
                    str(log.admin_id) if log.admin_id else "",
                    log.action_type,
                    log.target_type,
                    str(log.target_id),
                    log.reason or "",
                    log.ip_address or "",
                    log.created_at.isoformat() if log.created_at else "",
                ]
            )

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_logs_export.csv"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting audit logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to export audit logs") from e


# ---------------------------------------------------------------------------
# Agent run inspection helpers
# ---------------------------------------------------------------------------


def _truncate_tool_results(results: list, max_len: int = 2000) -> list:
    """Truncate tool result strings to *max_len* characters."""
    truncated: list = []
    for r in results:
        if isinstance(r, str) and len(r) > max_len:
            truncated.append(r[:max_len] + "... [truncated]")
        elif isinstance(r, dict):
            tr = dict(r)
            for key in ("output", "result", "content"):
                if key in tr and isinstance(tr[key], str) and len(tr[key]) > max_len:
                    tr[key] = tr[key][:max_len] + "... [truncated]"
            truncated.append(tr)
        else:
            truncated.append(r)
    return truncated


# ---------------------------------------------------------------------------
# 1. GET /admin/users/{user_id}/agent-runs
# ---------------------------------------------------------------------------


@router.get("/users/{user_id}/agent-runs")
async def get_user_agent_runs(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    completion_reason: str | None = Query(None),
    project_id: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Paginated list of agent runs (assistant messages with metadata) for a user."""
    try:
        user = await db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        query = (
            select(
                Message,
                Chat.project_id,
                Project.name.label("project_name"),
                Project.slug.label("project_slug"),
            )
            .join(Chat, Message.chat_id == Chat.id)
            .outerjoin(Project, Chat.project_id == Project.id)
            .where(
                Chat.user_id == user_id,
                Message.role == "assistant",
                Message.message_metadata.isnot(None),
            )
        )

        if completion_reason:
            query = query.where(
                Message.message_metadata["completion_reason"].as_string() == completion_reason
            )
        if project_id:
            query = query.where(Chat.project_id == project_id)
        if date_from:
            query = query.where(Message.created_at >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.where(Message.created_at <= datetime.fromisoformat(date_to))

        # Total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await db.scalar(count_query) or 0

        # Paginate
        offset = (page - 1) * page_size
        result = await db.execute(
            query.order_by(Message.created_at.desc()).offset(offset).limit(page_size)
        )
        rows = result.all()

        items = []
        for row in rows:
            msg = row[0]
            meta = msg.message_metadata or {}
            items.append(
                {
                    "message_id": str(msg.id),
                    "chat_id": str(msg.chat_id),
                    "project_name": row.project_name,
                    "project_slug": row.project_slug,
                    "created_at": msg.created_at.isoformat(),
                    "completion_reason": meta.get("completion_reason"),
                    "error": meta.get("error"),  # TODO: fix worker.py to persist error from complete_data into message_metadata
                    "iterations": meta.get("iterations", 0),
                    "tool_calls_made": meta.get("tool_calls_made", 0),
                    "agent_type": meta.get("agent_type"),
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent runs for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get agent runs") from e


# ---------------------------------------------------------------------------
# 2. GET /admin/agent-runs/errors  (MUST be before the {message_id} route)
# ---------------------------------------------------------------------------


@router.get("/agent-runs/errors")
async def get_agent_run_errors(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    completion_reason: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Platform-wide error feed for agent runs."""
    try:
        error_reasons = ["error", "resource_limit_exceeded", "credit_deduction_failed"]

        query = (
            select(
                Message,
                User.email.label("user_email"),
                User.id.label("uid"),
                Project.name.label("project_name"),
                Project.slug.label("project_slug"),
            )
            .join(Chat, Message.chat_id == Chat.id)
            .join(User, Chat.user_id == User.id)
            .outerjoin(Project, Chat.project_id == Project.id)
            .where(
                Message.role == "assistant",
                Message.message_metadata.isnot(None),
            )
        )

        if completion_reason:
            query = query.where(
                Message.message_metadata["completion_reason"].as_string() == completion_reason
            )
        else:
            query = query.where(
                or_(
                    *[
                        Message.message_metadata["completion_reason"].as_string() == r
                        for r in error_reasons
                    ]
                )
            )

        if date_from:
            query = query.where(Message.created_at >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.where(Message.created_at <= datetime.fromisoformat(date_to))

        # Total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await db.scalar(count_query) or 0

        # Paginate
        offset = (page - 1) * page_size
        result = await db.execute(
            query.order_by(Message.created_at.desc()).offset(offset).limit(page_size)
        )
        rows = result.all()

        items = []
        for row in rows:
            msg = row[0]
            meta = msg.message_metadata or {}
            items.append(
                {
                    "message_id": str(msg.id),
                    "user_email": row.user_email,
                    "user_id": str(row.uid),
                    "project_name": row.project_name,
                    "project_slug": row.project_slug,
                    "error": meta.get("error"),  # TODO: fix worker.py to persist error from complete_data into message_metadata
                    "completion_reason": meta.get("completion_reason"),
                    "created_at": msg.created_at.isoformat(),
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent run errors: {e}")
        raise HTTPException(status_code=500, detail="Failed to get agent run errors") from e


# ---------------------------------------------------------------------------
# 3. GET /admin/agent-runs/{message_id}/steps
# ---------------------------------------------------------------------------


@router.get("/agent-runs/{message_id}/steps")
async def get_agent_run_steps(
    message_id: str,
    include_debug: bool = Query(False),
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Full step-by-step trace for a single agent run."""
    try:
        result = await db.execute(
            select(
                Message,
                Project.id.label("proj_id"),
                Project.name.label("proj_name"),
                Project.slug.label("proj_slug"),
            )
            .join(Chat, Message.chat_id == Chat.id)
            .outerjoin(Project, Chat.project_id == Project.id)
            .where(Message.id == message_id)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Agent run not found")

        message = row[0]

        # Build project dict
        project_info = None
        if row.proj_id:
            project_info = {
                "id": str(row.proj_id),
                "name": row.proj_name,
                "slug": row.proj_slug,
            }

        # Fetch all steps ordered by step_index
        steps_result = await db.execute(
            select(AgentStep)
            .where(AgentStep.message_id == message_id)
            .order_by(AgentStep.step_index)
        )
        steps = steps_result.scalars().all()

        meta = message.message_metadata or {}

        step_items = []
        for step in steps:
            sd = step.step_data or {}
            item: dict[str, Any] = {
                "step_index": step.step_index,
                "iteration": sd.get("iteration"),
                "thought": sd.get("thought"),
                "tool_calls": sd.get("tool_calls", []),
                "tool_results": _truncate_tool_results(sd.get("tool_results", []), 2000),
                "response_text": sd.get("response_text"),
                "timestamp": sd.get("timestamp"),
            }
            if include_debug:
                item["_debug"] = sd.get("_debug")
            step_items.append(item)

        return {
            "message": {
                "id": str(message.id),
                "chat_id": str(message.chat_id),
                "created_at": message.created_at.isoformat(),
                "completion_reason": meta.get("completion_reason"),
                "error": meta.get("error"),  # TODO: fix worker.py to persist error from complete_data into message_metadata
                "iterations": meta.get("iterations", 0),
                "tool_calls_made": meta.get("tool_calls_made", 0),
                "agent_type": meta.get("agent_type"),
                "task_id": meta.get("task_id"),
            },
            "project": project_info,
            "steps": step_items,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting steps for agent run {message_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get agent run steps") from e
