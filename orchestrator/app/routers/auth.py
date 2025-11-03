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


@router.get("/verify")
async def verify_dev_environment_access(
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify user access to development environment.
    Called by NGINX Ingress Controller for each request to dev environments.

    Headers expected from NGINX:
    - X-Original-URI: The original request URI
    - X-Expected-User-ID: The user ID that should match the token
    - X-Forwarded-For: Client IP address
    - X-Forwarded-Host: Request hostname
    - User-Agent: Client user agent

    Returns:
    - 200 OK: User is authorized to access the environment
    - 401 Unauthorized: User is not authorized

    Audit Logging:
    - All access attempts are logged to database for compliance
    - Failed attempts trigger security monitoring alerts
    """
    # Extract request metadata for audit logging
    original_uri = request.headers.get("X-Original-URI", "")
    expected_user_id_str = request.headers.get("X-Expected-User-ID", "")
    request_host = request.headers.get("X-Forwarded-Host", request.headers.get("Host", ""))
    ip_address = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    user_agent = request.headers.get("User-Agent", "")

    # Extract project_id from hostname if available
    # Hostname format: {user_uuid}-{project_uuid}.domain.com
    project_id = None
    try:
        from ..utils.resource_naming import parse_hostname
        from uuid import UUID
        _, project_id_str = parse_hostname(request_host)
        project_id = UUID(project_id_str)
    except (ValueError, IndexError, Exception):
        pass  # Could not extract project ID, log without it

    success = False
    failure_reason = None

    try:
        # Validate expected user ID header
        if not expected_user_id_str:
            failure_reason = "Missing X-Expected-User-ID header"
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

            # Log unauthorized access attempt to database
            access_log = PodAccessLog(
                user_id=current_user.id,
                expected_user_id=expected_user_id,
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
                detail="Access denied - user mismatch"
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
