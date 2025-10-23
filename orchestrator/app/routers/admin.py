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
    MarketplaceAgent, UserPurchasedAgent, ProjectAgent,
    MarketplaceBase, UserPurchasedBase
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
    admin: User = Depends(admin_required),
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