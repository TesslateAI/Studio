from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import Agent as AgentModel, User
from ..schemas import Agent, AgentCreate, AgentUpdate
from ..auth import get_current_active_user

router = APIRouter()

@router.get("/", response_model=List[Agent])
async def get_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get all active agents."""
    result = await db.execute(
        select(AgentModel).where(AgentModel.is_active == True).order_by(AgentModel.created_at.asc())
    )
    agents = result.scalars().all()
    return agents


@router.get("/{agent_id}", response_model=Agent)
async def get_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Get a specific agent by ID."""
    result = await db.execute(
        select(AgentModel).where(AgentModel.id == agent_id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return agent


@router.post("/", response_model=Agent)
async def create_agent(
    agent_data: AgentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Create a new agent (admin only for now)."""
    # Check if agent with same name or slug exists
    result = await db.execute(
        select(AgentModel).where(
            (AgentModel.name == agent_data.name) | (AgentModel.slug == agent_data.slug)
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Agent with this name or slug already exists"
        )

    db_agent = AgentModel(**agent_data.model_dump())
    db.add(db_agent)
    await db.commit()
    await db.refresh(db_agent)
    return db_agent


@router.put("/{agent_id}", response_model=Agent)
async def update_agent(
    agent_id: int,
    agent_data: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Update an existing agent."""
    result = await db.execute(
        select(AgentModel).where(AgentModel.id == agent_id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Update only provided fields
    update_data = agent_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Soft delete an agent by setting is_active to False."""
    result = await db.execute(
        select(AgentModel).where(AgentModel.id == agent_id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.is_active = False
    await db.commit()

    return {"message": "Agent deleted successfully"}
