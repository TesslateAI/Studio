"""
Admin API endpoints for platform metrics and management.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime, timedelta, date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, distinct
from sqlalchemy.orm import selectinload
import logging

from ..database import get_db
from ..models import (
    User, Project, Chat, Message, AgentCommandLog,
    MarketplaceAgent, UserPurchasedAgent, ProjectAgent,
    MarketplaceBase, UserPurchasedBase
)
from ..services.litellm_service import litellm_service
from ..users import current_active_user, current_superuser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================================================
# User Metrics
# ============================================================================

@router.get("/metrics/users")
async def get_user_metrics(
    days: int = 30,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
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
        recent_set = set([u[0] for u in recent_users])

        # Get users active in previous week
        prev_active = select(distinct(Chat.user_id)).where(
            and_(Chat.created_at >= two_weeks_ago, Chat.created_at < week_ago)
        )
        prev_users = await db.execute(prev_active)
        prev_set = set([u[0] for u in prev_users])

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

            daily_new_users.append({
                "date": day_start.isoformat(),
                "count": count
            })

        daily_new_users.reverse()

        return {
            "total_users": total_users,
            "new_users": new_users,
            "dau": dau,
            "mau": mau,
            "growth_rate": round(growth_rate, 2),
            "retention_rate": round(retention_rate, 2),
            "daily_new_users": daily_new_users,
            "period_days": days
        }

    except Exception as e:
        logger.error(f"Error getting user metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user metrics")


# ============================================================================
# Project Metrics
# ============================================================================

@router.get("/metrics/projects")
async def get_project_metrics(
    days: int = 30,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
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
            func.count(Project.id).label('count'),
            Project.owner_id
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

            daily_projects.append({
                "date": day_start.isoformat(),
                "count": count
            })

        daily_projects.reverse()

        # Project categories (with/without git)
        git_projects_query = select(func.count(Project.id)).where(Project.has_git_repo == True)
        git_projects = await db.scalar(git_projects_query)

        return {
            "total_projects": total_projects,
            "new_projects": new_projects,
            "avg_projects_per_user": round(avg_projects_per_user, 2),
            "git_enabled_projects": git_projects,
            "daily_projects": daily_projects,
            "period_days": days
        }

    except Exception as e:
        logger.error(f"Error getting project metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get project metrics")


# ============================================================================
# Session Metrics
# ============================================================================

@router.get("/metrics/sessions")
async def get_session_metrics(
    days: int = 30,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
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
                "period_days": days
            }

        # Unique users with sessions
        unique_users = len(set(s.user_id for s in sessions))

        # Sessions per user
        avg_sessions_per_user = len(sessions) / unique_users if unique_users > 0 else 0

        # Calculate session durations and messages
        session_durations = []
        total_messages = 0

        for session in sessions:
            # Get messages for this session
            messages_query = select(Message).where(Message.chat_id == session.id).order_by(Message.created_at)
            result = await db.execute(messages_query)
            messages = result.scalars().all()

            if messages and len(messages) > 1:
                # Duration from first to last message
                duration = (messages[-1].created_at - messages[0].created_at).total_seconds() / 60  # in minutes
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

            daily_sessions.append({
                "date": day_start.isoformat(),
                "count": count
            })

        daily_sessions.reverse()

        return {
            "total_sessions": len(sessions),
            "unique_users": unique_users,
            "avg_sessions_per_user": round(avg_sessions_per_user, 2),
            "avg_session_duration": round(avg_duration, 2),  # in minutes
            "avg_messages_per_session": round(avg_messages, 2),
            "daily_sessions": daily_sessions,
            "period_days": days
        }

    except Exception as e:
        logger.error(f"Error getting session metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get session metrics")


# ============================================================================
# Token Usage Metrics (from LiteLLM)
# ============================================================================

@router.get("/metrics/tokens")
async def get_token_metrics(
    days: int = 30,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
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
            "max_budget": global_stats_raw.get("max_budget", 0)
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
            user_cost = user_usage.get('spend', 0) or 0
            total_cost += user_cost

            # Calculate tokens from model_spend if available
            user_tokens = 0
            if 'model_spend' in user_usage and user_usage['model_spend']:
                for model, spend_data in user_usage['model_spend'].items():
                    # model_spend contains cost data, estimate tokens if not available
                    # For now, we'll track cost instead of tokens
                    pass

            # Track per-user data
            user_token_data.append({
                "user_id": user_usage.get('user_id', 'unknown'),
                "total_tokens": user_tokens,
                "total_cost": user_cost,
                "last_used": user_usage.get('updated_at', None)
            })

            # Aggregate by model from model_spend
            if 'model_spend' in user_usage and user_usage['model_spend']:
                for model, spend_amount in user_usage['model_spend'].items():
                    if model not in tokens_by_model:
                        tokens_by_model[model] = {
                            "tokens": 0,
                            "cost": 0,
                            "requests": 0
                        }
                    # LiteLLM model_spend is just a dict of model: cost
                    tokens_by_model[model]['cost'] += spend_amount
                    tokens_by_model[model]['requests'] += 1  # Estimate

        # Sort users by cost (since we don't have token counts from LiteLLM)
        user_token_data.sort(key=lambda x: x['total_cost'], reverse=True)
        top_users = user_token_data[:10]  # Top 10 users

        # Calculate averages
        active_users = len([u for u in user_token_data if u['total_cost'] > 0])
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
            "period_days": days
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
            "error": "LiteLLM metrics unavailable"
        }


# ============================================================================
# Marketplace Metrics
# ============================================================================

@router.get("/metrics/marketplace")
async def get_marketplace_metrics(
    days: int = 30,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get marketplace performance metrics including agents and bases.
    """
    try:
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)

        # ===== AGENTS METRICS =====
        # Total agents (official + published community agents)
        total_agents_query = select(func.count(MarketplaceAgent.id)).where(
            MarketplaceAgent.is_active == True,
            (MarketplaceAgent.forked_by_user_id == None) | (MarketplaceAgent.is_published == True)
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
        agent_revenue_query = select(UserPurchasedAgent, MarketplaceAgent).join(
            MarketplaceAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id
        ).where(UserPurchasedAgent.purchase_date >= start_date)

        result = await db.execute(agent_revenue_query)
        agent_purchases = result.all()

        agent_revenue = 0
        revenue_by_type = {
            "monthly": 0,
            "one_time": 0,
            "usage": 0
        }

        for purchase, agent in agent_purchases:
            if agent.pricing_type == "monthly":
                agent_revenue += agent.price / 100  # Convert from cents
                revenue_by_type["monthly"] += agent.price / 100
            elif agent.pricing_type in ["one_time", "usage"]:
                agent_revenue += agent.price / 100
                revenue_by_type["one_time"] += agent.price / 100

        # Popular agents by purchases
        popular_agents_query = select(
            MarketplaceAgent.name,
            MarketplaceAgent.slug,
            MarketplaceAgent.usage_count,
            func.count(UserPurchasedAgent.id).label('purchase_count')
        ).join(
            UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id, isouter=True
        ).where(
            MarketplaceAgent.is_active == True
        ).group_by(MarketplaceAgent.id).order_by(func.count(UserPurchasedAgent.id).desc()).limit(5)

        result = await db.execute(popular_agents_query)
        popular_agents = [
            {
                "name": r.name,
                "slug": r.slug,
                "purchases": r.purchase_count,
                "usage_count": r.usage_count or 0
            }
            for r in result
        ]

        # Most used agents (by usage_count - messages sent to agent)
        most_used_query = select(
            MarketplaceAgent.name,
            MarketplaceAgent.slug,
            MarketplaceAgent.usage_count
        ).where(
            MarketplaceAgent.is_active == True,
            MarketplaceAgent.usage_count > 0
        ).order_by(MarketplaceAgent.usage_count.desc()).limit(5)

        result = await db.execute(most_used_query)
        most_used_agents = [
            {
                "name": r.name,
                "slug": r.slug,
                "usage_count": r.usage_count
            }
            for r in result
        ]

        # Agent adoption rate (agents applied to projects)
        applied_agents_query = select(func.count(distinct(ProjectAgent.agent_id)))
        applied_agents = await db.scalar(applied_agents_query)

        agent_adoption_rate = (applied_agents / total_agents * 100) if total_agents > 0 else 0

        # ===== BASES METRICS =====
        # Total bases
        total_bases_query = select(func.count(MarketplaceBase.id)).where(MarketplaceBase.is_active == True)
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
        popular_bases_query = select(
            MarketplaceBase.name,
            MarketplaceBase.slug,
            MarketplaceBase.downloads,
            func.count(UserPurchasedBase.id).label('purchase_count')
        ).join(
            UserPurchasedBase, UserPurchasedBase.base_id == MarketplaceBase.id, isouter=True
        ).where(
            MarketplaceBase.is_active == True
        ).group_by(MarketplaceBase.id).order_by(func.count(UserPurchasedBase.id).desc()).limit(5)

        result = await db.execute(popular_bases_query)
        popular_bases = [
            {
                "name": r.name,
                "slug": r.slug,
                "purchases": r.purchase_count,
                "downloads": r.downloads
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
                "most_used": most_used_agents
            },

            # Base-specific metrics
            "bases": {
                "total": total_bases,
                "total_purchases": total_base_purchases,
                "recent_purchases": recent_base_purchases,
                "popular": popular_bases
            },

            "period_days": days
        }

    except Exception as e:
        logger.error(f"Error getting marketplace metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get marketplace metrics")


# ============================================================================
# Summary Dashboard
# ============================================================================

@router.get("/metrics/summary")
async def get_metrics_summary(
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
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
                "growth_rate": user_metrics["growth_rate"]
            },
            "projects": {
                "total": project_metrics["total_projects"],
                "new_this_week": project_metrics["new_projects"],
                "avg_per_user": project_metrics["avg_projects_per_user"]
            },
            "sessions": {
                "total_this_week": session_metrics["total_sessions"],
                "avg_per_user": session_metrics["avg_sessions_per_user"],
                "avg_duration": session_metrics["avg_session_duration"]
            },
            "tokens": {
                "total_this_week": token_metrics["total_tokens"],
                "total_cost": token_metrics["total_cost"],
                "avg_per_user": token_metrics["avg_tokens_per_user"]
            },
            "marketplace": {
                "total_items": marketplace_metrics["total_items"],
                "total_agents": marketplace_metrics["agents"]["total"],
                "total_bases": marketplace_metrics["bases"]["total"],
                "total_revenue": marketplace_metrics["total_revenue"],
                "recent_purchases": marketplace_metrics["recent_purchases"]
            }
        }

    except Exception as e:
        logger.error(f"Error getting metrics summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to get metrics summary")


# ============================================================================
# Agent Management
# ============================================================================

from pydantic import BaseModel, Field
from typing import List as TypeList
import re
import os


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
    features: TypeList[str] = Field(default_factory=list)
    required_models: TypeList[str] = Field(default_factory=list)
    tags: TypeList[str] = Field(default_factory=list)
    is_featured: bool = Field(default=False)
    is_active: bool = Field(default=True)


class AgentUpdate(BaseModel):
    """Schema for updating an existing agent."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    long_description: Optional[str] = None
    category: Optional[str] = None
    system_prompt: Optional[str] = None
    mode: Optional[str] = Field(None, pattern="^(stream|agent)$")
    agent_type: Optional[str] = None
    model: Optional[str] = None
    icon: Optional[str] = None
    pricing_type: Optional[str] = Field(None, pattern="^(free|monthly|api|one_time)$")
    price: Optional[int] = Field(None, ge=0)
    api_pricing_input: Optional[float] = Field(None, ge=0)
    api_pricing_output: Optional[float] = Field(None, ge=0)
    source_type: Optional[str] = Field(None, pattern="^(open|closed)$")
    is_forkable: Optional[bool] = None
    requires_user_keys: Optional[bool] = None
    features: Optional[TypeList[str]] = None
    required_models: Optional[TypeList[str]] = None
    tags: Optional[TypeList[str]] = None
    is_featured: Optional[bool] = None
    is_active: Optional[bool] = None


def can_edit_agent(agent: MarketplaceAgent) -> bool:
    """Check if admin can edit this agent (only Tesslate-created agents)."""
    return agent.created_by_user_id is None and agent.forked_by_user_id is None


def generate_slug(name: str, db_session: AsyncSession = None) -> str:
    """Generate a unique slug from agent name."""
    # Convert to lowercase and replace spaces with hyphens
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return slug


@router.get("/agents")
async def list_agents(
    source_type: Optional[str] = None,
    pricing_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    List all agents with optional filters.
    Admins can see all agents including user-created ones.
    """
    try:
        query = select(MarketplaceAgent).options(
            selectinload(MarketplaceAgent.created_by_user),
            selectinload(MarketplaceAgent.forked_by_user)
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
                    "created_by_tesslate": agent.created_by_user_id is None and agent.forked_by_user_id is None,
                    "created_by_username": agent.created_by_user.username if agent.created_by_user else None,
                    "forked_by_username": agent.forked_by_user.username if agent.forked_by_user else None,
                    "can_edit": can_edit_agent(agent)
                }
                for agent in agents
            ],
            "total": len(agents)
        }

    except Exception as e:
        logger.error(f"Error listing agents: {e}")
        raise HTTPException(status_code=500, detail="Failed to list agents")


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """Get detailed information about a specific agent."""
    try:
        result = await db.execute(
            select(MarketplaceAgent)
            .options(
                selectinload(MarketplaceAgent.created_by_user),
                selectinload(MarketplaceAgent.forked_by_user)
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
            "created_by_tesslate": agent.created_by_user_id is None and agent.forked_by_user_id is None,
            "created_by_username": agent.created_by_user.username if agent.created_by_user else None,
            "forked_by_username": agent.forked_by_user.username if agent.forked_by_user else None,
            "can_edit": can_edit_agent(agent)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get agent")


@router.post("/agents")
async def create_agent(
    agent_data: AgentCreate,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Create a new agent.
    All agents created via admin panel are marked as Tesslate-created (created_by_user_id = NULL).
    """
    try:
        # Generate slug from name
        slug = generate_slug(agent_data.name)

        # Check if slug already exists
        existing = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == slug)
        )
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
            forked_by_user_id=None
        )

        db.add(agent)
        await db.commit()
        await db.refresh(agent)

        logger.info(f"Admin {admin.username} created agent: {agent.name} (ID: {agent.id})")

        return {
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "message": "Agent created successfully"
        }

    except Exception as e:
        logger.error(f"Error creating agent: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create agent")


@router.put("/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    agent_data: AgentUpdate,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Update an existing agent.
    Only Tesslate-created agents can be edited. User-forked or custom agents cannot be edited.
    """
    try:
        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Check if admin can edit this agent
        if not can_edit_agent(agent):
            raise HTTPException(
                status_code=403,
                detail="Cannot edit user-created or forked agents. Only Tesslate-created agents can be edited."
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
            "message": "Agent updated successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating agent {agent_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update agent")


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Delete an agent.
    Only Tesslate-created agents can be deleted. User-created agents can only be removed from marketplace.
    """
    try:
        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Check if admin can delete this agent
        if not can_edit_agent(agent):
            raise HTTPException(
                status_code=403,
                detail="Cannot delete user-created or forked agents. Use remove-from-marketplace instead."
            )

        agent_name = agent.name
        await db.delete(agent)
        await db.commit()

        logger.info(f"Admin {admin.username} deleted agent: {agent_name} (ID: {agent_id})")

        return {
            "message": f"Agent '{agent_name}' deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting agent {agent_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete agent")


@router.patch("/agents/{agent_id}/remove-from-marketplace")
async def remove_from_marketplace(
    agent_id: str,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Remove an agent from the public marketplace (set is_active = false).
    This can be used on ANY agent, including user-created ones.
    """
    try:
        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
        )
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        agent.is_active = False
        agent.updated_at = datetime.utcnow()

        await db.commit()

        logger.info(f"Admin {admin.username} removed agent from marketplace: {agent.name} (ID: {agent_id})")

        return {
            "id": agent.id,
            "name": agent.name,
            "message": "Agent removed from marketplace successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing agent {agent_id} from marketplace: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to remove agent from marketplace")


@router.patch("/agents/{agent_id}/feature")
async def toggle_featured(
    agent_id: str,
    is_featured: bool,
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Toggle the featured status of an agent.
    """
    try:
        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id)
        )
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
            "message": f"Agent {status} successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling featured status for agent {agent_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to toggle featured status")


@router.get("/models")
async def get_available_models(
    admin: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get list of available models from LiteLLM.
    Returns model names from your LiteLLM instance.
    """
    try:
        from ..services.litellm_service import litellm_service

        # Get all available models from LiteLLM
        litellm_models = await litellm_service.get_available_models()

        # Extract model IDs
        models = [model.get('id') for model in litellm_models if model.get('id')]

        # If no models from LiteLLM, fallback to environment variable
        if not models:
            from ..config import get_settings
            settings = get_settings()
            models_str = settings.litellm_default_models
            models = [m.strip() for m in models_str.split(",") if m.strip()]

        if not models:
            models = ["qwen-3-235b-a22b-thinking-2507"]  # Final fallback

        return {
            "models": models
        }

    except Exception as e:
        logger.error(f"Error getting available models: {e}")
        # Fallback to environment variable on error
        from ..config import get_settings
        settings = get_settings()
        models_str = settings.litellm_default_models
        models = [m.strip() for m in models_str.split(",") if m.strip()]
        return {
            "models": models if models else ["qwen-3-235b-a22b-thinking-2507"]
        }