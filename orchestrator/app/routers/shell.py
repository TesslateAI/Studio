"""
Shell Router

REST API endpoints for agent programmatic shell access.
"""

import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from ..database import get_db
from ..models import User, ShellSession
from ..auth import get_current_active_user
from ..services.shell_session_manager import get_shell_session_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# Request/Response Models

class CreateSessionRequest(BaseModel):
    project_id: UUID
    command: str = "/bin/bash"
    cwd: str = "/app"


class CreateSessionResponse(BaseModel):
    session_id: str
    status: str
    created_at: str


class WriteRequest(BaseModel):
    data: str  # Will be encoded to bytes


class WriteResponse(BaseModel):
    success: bool
    bytes_written: int


class OutputResponse(BaseModel):
    output: str  # Base64 encoded
    bytes: int
    is_eof: bool


class SessionInfo(BaseModel):
    session_id: str
    project_id: UUID
    command: str
    working_dir: str
    status: str
    created_at: str
    last_activity_at: str
    bytes_read: int
    bytes_written: int
    total_reads: int


class SessionListResponse(BaseModel):
    sessions: list[dict]


# Endpoints

@router.post("/sessions", response_model=CreateSessionResponse)
async def create_shell_session(
    request: CreateSessionRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new shell session for agent use.

    Returns session_id for subsequent operations.
    """
    session_manager = get_shell_session_manager()

    session_info = await session_manager.create_session(
        user_id=current_user.id,
        project_id=request.project_id,
        db=db,
        command=request.command,
        cwd=request.cwd,
    )

    return session_info


@router.post("/sessions/{session_id}/write", response_model=WriteResponse)
async def write_to_session(
    session_id: str,
    request: WriteRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Write data to shell session stdin.

    Typically used to send commands (remember to include \\n).
    """
    session_manager = get_shell_session_manager()

    # Verify ownership
    result = await db.execute(
        select(ShellSession).where(
            ShellSession.session_id == session_id,
            ShellSession.user_id == current_user.id
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Write to PTY
    data_bytes = request.data.encode('utf-8')
    await session_manager.write_to_session(session_id, data_bytes, db)

    return WriteResponse(
        success=True,
        bytes_written=len(data_bytes)
    )


@router.get("/sessions/{session_id}/output", response_model=OutputResponse)
async def read_session_output(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Read new output from shell session since last read.

    Returns base64-encoded output and EOF flag.
    Agents should poll this endpoint or use after waiting for command completion.
    """
    session_manager = get_shell_session_manager()

    # Verify ownership
    result = await db.execute(
        select(ShellSession).where(
            ShellSession.session_id == session_id,
            ShellSession.user_id == current_user.id
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Read output
    output_data = await session_manager.read_output(session_id, db)

    return output_data


@router.get("/sessions", response_model=SessionListResponse)
async def list_shell_sessions(
    project_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all active shell sessions for the current user."""
    session_manager = get_shell_session_manager()

    sessions = await session_manager.list_sessions(
        user_id=current_user.id,
        project_id=project_id,
        db=db,
    )

    return {"sessions": sessions}


@router.delete("/sessions/{session_id}")
async def close_shell_session(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Close a shell session."""
    session_manager = get_shell_session_manager()

    # Verify ownership
    result = await db.execute(
        select(ShellSession).where(
            ShellSession.session_id == session_id,
            ShellSession.user_id == current_user.id
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    await session_manager.close_session(session_id, db)

    return {"message": "Session closed"}


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_shell_session(
    session_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get shell session details."""
    result = await db.execute(
        select(ShellSession).where(
            ShellSession.session_id == session_id,
            ShellSession.user_id == current_user.id
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    return {
        "session_id": session.session_id,
        "project_id": session.project_id,
        "command": session.command,
        "working_dir": session.working_dir,
        "status": session.status,
        "created_at": session.created_at.isoformat(),
        "last_activity_at": session.last_activity_at.isoformat(),
        "bytes_read": session.bytes_read,
        "bytes_written": session.bytes_written,
        "total_reads": session.total_reads,
    }
