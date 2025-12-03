"""
Agent API router for secure command execution in user development pods.

This module provides a RESTful API for AI agents to execute shell commands
in user development environments with comprehensive security controls.
"""

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging
import time
from typing import List

from ..database import get_db
from ..models import User, Project
from ..schemas import (
    AgentCommandRequest,
    AgentCommandResponse,
    AgentCommandLogSchema,
    AgentCommandStatsResponse
)
from ..services.command_validator import get_command_validator, CommandRisk
from ..services.agent_audit import get_audit_service
from ..users import current_active_user, current_superuser

logger = logging.getLogger(__name__)
router = APIRouter()


# Rate limiting: Track command executions per user
_user_command_counts = {}
_user_last_reset = {}
RATE_LIMIT_COMMANDS = 30  # commands per minute
RATE_LIMIT_WINDOW = 60  # seconds


def check_rate_limit(user_id: UUID) -> bool:
    """
    Check if user has exceeded rate limit.

    Returns:
        True if within limits, False if exceeded
    """
    current_time = time.time()

    # Reset counter if window has passed
    if user_id in _user_last_reset:
        if current_time - _user_last_reset[user_id] > RATE_LIMIT_WINDOW:
            _user_command_counts[user_id] = 0
            _user_last_reset[user_id] = current_time
    else:
        _user_last_reset[user_id] = current_time
        _user_command_counts[user_id] = 0

    # Check limit
    count = _user_command_counts.get(user_id, 0)
    if count >= RATE_LIMIT_COMMANDS:
        return False

    # Increment counter
    _user_command_counts[user_id] = count + 1
    return True


@router.post("/execute", response_model=AgentCommandResponse)
async def execute_command(
    request: AgentCommandRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Execute a shell command in a user's development pod.

    Security features:
    - JWT authentication required
    - User ownership verification
    - Command validation (allowlist/blocklist)
    - Rate limiting (30 commands/minute)
    - Audit logging
    - Dry-run mode for testing

    Args:
        request: Command execution request
        current_user: Authenticated user from JWT token
        db: Database session

    Returns:
        AgentCommandResponse with execution results

    Raises:
        HTTPException: On authentication, authorization, or execution errors
    """
    try:
        # 1. Rate limiting check
        if not check_rate_limit(current_user.id):
            logger.warning(
                f"Rate limit exceeded for user {current_user.id} ({current_user.username})"
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {RATE_LIMIT_COMMANDS} commands per minute."
            )

        # 2. Verify project ownership
        result = await db.execute(
            select(Project).where(
                Project.id == request.project_id,
                Project.owner_id == current_user.id
            )
        )
        project = result.scalar_one_or_none()

        if not project:
            logger.warning(
                f"User {current_user.id} attempted to access project {request.project_id} "
                f"(not found or access denied)"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found or access denied"
            )

        # 3. Validate command
        validator = get_command_validator(allow_network=False)
        validation = validator.validate(request.command, request.working_dir)

        if not validation.is_valid:
            logger.warning(
                f"Command validation failed for user {current_user.id}: "
                f"{request.command[:50]}... Reason: {validation.reason}"
            )

            # Log failed validation attempt
            audit_service = get_audit_service(db)
            await audit_service.log_command(
                user_id=current_user.id,
                project_id=request.project_id,
                command=request.command,
                working_dir=request.working_dir,
                success=False,
                exit_code=-1,
                stderr=f"Command validation failed: {validation.reason}",
                risk_level=validation.risk_level.value,
                dry_run=request.dry_run
            )

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Command validation failed: {validation.reason}"
            )

        # 4. Check if container/pod is ready
        from ..services.orchestration import get_orchestrator, is_kubernetes_mode

        if is_kubernetes_mode():
            orchestrator = get_orchestrator()
            container_status = await orchestrator.is_container_ready(
                user_id=current_user.id,
                project_id=request.project_id,
                container_name=None  # Use default container
            )

            if not container_status["ready"] or not container_status.get("responsive", False):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Development environment not ready: {container_status['message']}"
                )
        else:
            # Docker mode - not supported for agent commands
            # All projects should use multi-container system
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent commands are only supported in Kubernetes mode."
            )

        # 5. Execute command (or simulate if dry_run)
        start_time = time.time()
        success = False
        stdout = ""
        stderr = ""
        exit_code = 0

        if request.dry_run:
            # Dry run - simulate execution
            stdout = "[DRY RUN] Command would be executed (not actually run)"
            success = True
            duration_ms = 0
            logger.info(
                f"Dry run command for user {current_user.id}, project {request.project_id}: "
                f"{request.command}"
            )
        else:
            # Real execution
            try:
                logger.info(
                    f"Executing command for user {current_user.id}, project {request.project_id}: "
                    f"{request.command[:100]}..."
                )

                # Kubernetes mode - execute command in pod
                output = await orchestrator.execute_command(
                    user_id=current_user.id,
                    project_id=request.project_id,
                    container_name=request.container_name if hasattr(request, 'container_name') else None,
                    command=validation.sanitized_command if isinstance(validation.sanitized_command, list) else ["/bin/sh", "-c", validation.sanitized_command],
                    timeout=request.timeout
                )
                stdout = output
                success = True
                exit_code = 0

                logger.info(
                    f"Command executed successfully for user {current_user.id}, "
                    f"project {request.project_id}"
                )

            except Exception as e:
                success = False
                stderr = str(e)
                exit_code = 1
                logger.error(
                    f"Command execution failed for user {current_user.id}, "
                    f"project {request.project_id}: {e}"
                )

        duration_ms = int((time.time() - start_time) * 1000)

        # 6. Audit log the command
        audit_service = get_audit_service(db)
        log_entry = await audit_service.log_command(
            user_id=current_user.id,
            project_id=request.project_id,
            command=request.command,
            working_dir=request.working_dir,
            success=success,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            risk_level=validation.risk_level.value,
            dry_run=request.dry_run
        )

        # 7. Check for suspicious activity
        suspicious_check = await audit_service.detect_suspicious_activity(
            user_id=current_user.id,
            time_window_minutes=5
        )

        if suspicious_check["is_suspicious"]:
            logger.warning(
                f"Suspicious activity detected for user {current_user.id}: "
                f"{len(suspicious_check['alerts'])} alerts"
            )
            # Could implement additional actions here (notify admins, throttle, etc.)

        # 8. Return response
        return AgentCommandResponse(
            success=success,
            command=request.command,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=duration_ms,
            risk_level=validation.risk_level.value,
            dry_run=request.dry_run,
            command_id=log_entry.id,
            message="Command executed successfully" if success else "Command execution failed"
        )

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error in agent execute endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/history/{project_id}", response_model=List[AgentCommandLogSchema])
async def get_command_history(
    project_id: str,
    limit: int = 50,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get command execution history for a project.

    Args:
        project_id: Project ID to query
        limit: Maximum number of entries to return (default 50, max 200)
        current_user: Authenticated user
        db: Database session

    Returns:
        List of command log entries
    """
    # Verify project ownership
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or access denied"
        )

    # Enforce limit cap
    limit = min(limit, 200)

    # Get history
    audit_service = get_audit_service(db)
    history = await audit_service.get_user_command_history(
        user_id=current_user.id,
        project_id=project_id,
        limit=limit,
        include_dry_run=False
    )

    return history


@router.get("/stats", response_model=AgentCommandStatsResponse)
async def get_command_stats(
    days: int = 7,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get command execution statistics for the current user.

    Args:
        days: Number of days to look back (default 7, max 30)
        current_user: Authenticated user
        db: Database session

    Returns:
        Command statistics
    """
    # Enforce days cap
    days = min(days, 30)

    audit_service = get_audit_service(db)
    stats = await audit_service.get_command_stats(
        user_id=current_user.id,
        days=days
    )

    return AgentCommandStatsResponse(**stats)


@router.get("/health")
async def health_check():
    """Health check endpoint for agent service."""
    return {
        "status": "healthy",
        "service": "agent-api",
        "features": {
            "command_execution": True,
            "audit_logging": True,
            "rate_limiting": True,
            "command_validation": True
        }
    }
