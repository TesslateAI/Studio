"""
Custom authentication routes for Tesslate Studio.

Note: Register, login, and token management are handled by fastapi-users in main.py
This file only contains custom endpoints like pod access verification.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from ..database import get_db
from ..models import User, PodAccessLog
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/verify-access")
async def verify_dev_environment_access(
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify user access to development environment.

    Supports two authentication modes:
    1. NGINX Ingress (Kubernetes): Uses X-Expected-User-ID header
    2. Traefik forwardAuth (Docker): Extracts user from project slug in hostname

    Headers expected:
    - X-Original-URI: The original request URI (NGINX)
    - X-Expected-User-ID: The user ID that should match the token (NGINX only)
    - X-Forwarded-Host or Host: Request hostname (Traefik & NGINX)
    - X-Forwarded-For: Client IP address
    - User-Agent: Client user agent

    Returns:
    - 200 OK: User is authorized to access the environment
    - 401 Unauthorized: User is not authorized

    Audit Logging:
    - All access attempts are logged to database for compliance
    - Failed attempts trigger security monitoring alerts
    """
    # Extract request metadata for audit logging
    original_uri = request.headers.get("X-Original-URI", request.url.path)
    expected_user_id_str = request.headers.get("X-Expected-User-ID", "")
    request_host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", ""))
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    user_agent = request.headers.get("User-Agent", "")

    # Extract project_id from hostname if available
    # Hostname format: {project-slug}.domain.com (Docker/Traefik)
    # or {user_uuid}-{project_uuid}.domain.com (K8s/NGINX)
    project_id = None
    project_slug = None

    try:
        # Extract subdomain from hostname
        # e.g., "ff-9en0cx.localhost" -> "ff-9en0cx"
        subdomain = request_host.split('.')[0] if '.' in request_host else request_host

        # Try parsing as K8s format first
        try:
            from ..utils.resource_naming import parse_hostname
            from uuid import UUID
            _, project_id_str = parse_hostname(request_host)
            project_id = UUID(project_id_str)
        except (ValueError, IndexError, Exception):
            # Not K8s format, treat as project slug (Docker/Traefik)
            project_slug = subdomain
    except Exception as e:
        logger.debug(f"Could not extract project info from hostname: {e}")

    success = False
    failure_reason = None
    expected_user_id = None

    try:
        # MODE 1: NGINX Ingress (Kubernetes) - X-Expected-User-ID header present
        if expected_user_id_str:
            from uuid import UUID
            expected_user_id = UUID(expected_user_id_str)

            # Verify user matches expected user
            if current_user.id != expected_user_id:
                failure_reason = f"User mismatch: user {current_user.id} attempted to access user {expected_user_id}'s environment"
                logger.warning(
                    f"[SECURITY] User {current_user.id} ({current_user.username}) attempted to access "
                    f"environment for user {expected_user_id}. "
                    f"URI: {original_uri}, Host: {request_host}, IP: {ip_address}"
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Access denied - user mismatch"
                )

        # MODE 2: Traefik forwardAuth (Docker) - Look up project by slug
        elif project_slug:
            from sqlalchemy import select
            from ..models import Project

            # Look up project by slug
            result = await db.execute(
                select(Project).where(Project.slug == project_slug)
            )
            project = result.scalar_one_or_none()

            if not project:
                failure_reason = f"Project not found: {project_slug}"
                logger.warning(
                    f"[SECURITY] User {current_user.id} ({current_user.username}) attempted to access "
                    f"non-existent project {project_slug}. "
                    f"Host: {request_host}, IP: {ip_address}"
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Project not found"
                )

            # Verify current user owns this project
            if current_user.id != project.owner_id:
                failure_reason = f"User {current_user.id} attempted to access project {project_slug} owned by {project.owner_id}"
                logger.warning(
                    f"[SECURITY] User {current_user.id} ({current_user.username}) attempted to access "
                    f"project {project_slug} owned by user {project.owner_id}. "
                    f"Host: {request_host}, IP: {ip_address}"
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Access denied - you do not own this project"
                )

            # Set expected_user_id for audit logging
            expected_user_id = project.owner_id
            project_id = project.id

        # Neither mode available
        else:
            failure_reason = "Missing X-Expected-User-ID header and could not extract project from hostname"
            logger.warning(f"[SECURITY] {failure_reason}. URI: {original_uri}, IP: {ip_address}")

            # Log failed attempt to database
            access_log = PodAccessLog(
                user_id=current_user.id,
                expected_user_id=None,
                project_id=project_id,
                success=False,
                request_uri=original_uri,
                request_host=request_host,
                ip_address=ip_address,
                user_agent=user_agent,
                failure_reason=failure_reason
            )
            db.add(access_log)
            await db.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid request - missing user verification data"
            )

        # Access granted - log successful verification
        success = True

        logger.info(
            f"[AUDIT] Verified access for user {current_user.id} ({current_user.username}) "
            f"to project {project_id} environment. URI: {original_uri}, IP: {ip_address}"
        )

        # Log successful access to database for audit trail
        access_log = PodAccessLog(
            user_id=current_user.id,
            expected_user_id=expected_user_id,
            project_id=project_id,
            success=True,
            request_uri=original_uri,
            request_host=request_host,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason=None
        )
        db.add(access_log)
        await db.commit()

        # Return success response
        return Response(status_code=status.HTTP_200_OK)

    except HTTPException:
        # Re-raise HTTP exceptions (already logged and saved to DB above)
        raise

    except Exception as e:
        # Log unexpected errors and deny access
        failure_reason = f"Unexpected error: {str(e)}"
        logger.error(f"[ERROR] Unexpected error in auth verification: {e}", exc_info=True)

        # Log error to database
        try:
            from uuid import UUID
            access_log = PodAccessLog(
                user_id=current_user.id,
                expected_user_id=UUID(expected_user_id_str) if expected_user_id_str else None,
                project_id=project_id,
                success=False,
                request_uri=original_uri,
                request_host=request_host,
                ip_address=ip_address,
                user_agent=user_agent,
                failure_reason=failure_reason
            )
            db.add(access_log)
            await db.commit()
        except Exception as db_error:
            logger.error(f"[ERROR] Failed to log access attempt to database: {db_error}")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication verification failed"
        )
