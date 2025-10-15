"""
Admin API endpoints for platform metrics and management.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, date
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, distinct
from sqlalchemy.orm import selectinload
import logging

from ..database import get_db
from ..auth import get_current_active_user
from ..models import (
    User, Project, Chat, Message, AgentCommandLog,
    MarketplaceAgent, UserPurchasedAgent, ProjectAgent
)
from ..services.litellm_service import litellm_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def admin_required(current_user: User = Depends(get_current_active_user)) -> User:
    """Dependency to ensure user is an admin."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


# ============================================================================
# User Metrics
# ============================================================================

@router.get("/metrics/users")
async def get_user_metrics(
    days: int = 30,
    admin: User = Depends(admin_required),
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
    admin: User = Depends(admin_required),
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
    admin: User = Depends(admin_required),
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
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get token usage metrics from LiteLLM.
    """
    try:
        start_date = datetime.utcnow() - timedelta(days=days)

        # Get global statistics from LiteLLM
        global_stats = await litellm_service.get_global_stats()

        # Get all users' usage from LiteLLM
        all_users_usage = await litellm_service.get_all_users_usage(start_date)

        # Aggregate metrics
        total_tokens = 0
        total_cost = 0
        tokens_by_model = {}
        user_token_data = []

        for user_usage in all_users_usage:
            if 'total_tokens' in user_usage:
                total_tokens += user_usage['total_tokens']

            if 'total_cost' in user_usage:
                total_cost += user_usage['total_cost']

            # Track per-user data
            user_token_data.append({
                "user_id": user_usage.get('user_id', 'unknown'),
                "total_tokens": user_usage.get('total_tokens', 0),
                "total_cost": user_usage.get('total_cost', 0),
                "last_used": user_usage.get('last_used', None)
            })

            # Aggregate by model
            if 'model_usage' in user_usage:
                for model, usage in user_usage['model_usage'].items():
                    if model not in tokens_by_model:
                        tokens_by_model[model] = {
                            "tokens": 0,
                            "cost": 0,
                            "requests": 0
                        }
                    tokens_by_model[model]['tokens'] += usage.get('tokens', 0)
                    tokens_by_model[model]['cost'] += usage.get('cost', 0)
                    tokens_by_model[model]['requests'] += usage.get('requests', 0)

        # Sort users by token usage
        user_token_data.sort(key=lambda x: x['total_tokens'], reverse=True)
        top_users = user_token_data[:10]  # Top 10 users

        # Calculate averages
        active_users = len([u for u in user_token_data if u['total_tokens'] > 0])
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
    admin: User = Depends(admin_required),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get marketplace performance metrics.
    """
    try:
        now = datetime.utcnow()
        start_date = now - timedelta(days=days)

        # Total agents
        total_agents_query = select(func.count(MarketplaceAgent.id)).where(MarketplaceAgent.is_active == True)
        total_agents = await db.scalar(total_agents_query)

        # Total purchases
        total_purchases_query = select(func.count(UserPurchasedAgent.id))
        total_purchases = await db.scalar(total_purchases_query)

        # Recent purchases
        recent_purchases_query = select(func.count(UserPurchasedAgent.id)).where(
            UserPurchasedAgent.purchase_date >= start_date
        )
        recent_purchases = await db.scalar(recent_purchases_query)

        # Revenue calculations
        # Get all purchased agents with their prices
        revenue_query = select(UserPurchasedAgent, MarketplaceAgent).join(
            MarketplaceAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id
        ).where(UserPurchasedAgent.purchase_date >= start_date)

        result = await db.execute(revenue_query)
        purchases = result.all()

        total_revenue = 0
        revenue_by_type = {
            "monthly": 0,
            "one_time": 0,
            "usage": 0
        }

        for purchase, agent in purchases:
            if agent.pricing_type == "monthly":
                # Monthly subscriptions (count as monthly revenue)
                total_revenue += agent.price / 100  # Convert from cents
                revenue_by_type["monthly"] += agent.price / 100
            elif agent.pricing_type in ["one_time", "usage"]:
                total_revenue += agent.price / 100
                revenue_by_type["one_time"] += agent.price / 100

        # Popular agents
        popular_query = select(
            MarketplaceAgent.name,
            MarketplaceAgent.slug,
            func.count(UserPurchasedAgent.id).label('purchase_count')
        ).join(
            UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id
        ).group_by(MarketplaceAgent.id).order_by(func.count(UserPurchasedAgent.id).desc()).limit(5)

        result = await db.execute(popular_query)
        popular_agents = [
            {
                "name": r.name,
                "slug": r.slug,
                "purchases": r.purchase_count
            }
            for r in result
        ]

        # Agent adoption rate (agents applied to projects)
        applied_agents_query = select(func.count(distinct(ProjectAgent.agent_id)))
        applied_agents = await db.scalar(applied_agents_query)

        adoption_rate = (applied_agents / total_agents * 100) if total_agents > 0 else 0

        return {
            "total_agents": total_agents,
            "total_purchases": total_purchases,
            "recent_purchases": recent_purchases,
            "total_revenue": round(total_revenue, 2),
            "revenue_by_type": revenue_by_type,
            "popular_agents": popular_agents,
            "adoption_rate": round(adoption_rate, 2),
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
    admin: User = Depends(admin_required),
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
                "total_agents": marketplace_metrics["total_agents"],
                "total_revenue": marketplace_metrics["total_revenue"],
                "recent_purchases": marketplace_metrics["recent_purchases"]
            }
        }

    except Exception as e:
        logger.error(f"Error getting metrics summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to get metrics summary")