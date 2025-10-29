from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import User, PodAccessLog
from ..schemas import Token, User as UserSchema, UserCreate, RefreshTokenRequest
from ..auth import (
    authenticate_user, create_access_token, get_password_hash, get_current_active_user,
    create_refresh_token, validate_refresh_token, revoke_refresh_token
)
from ..config import get_settings
from ..services.litellm_service import litellm_service
from ..services.discord_service import discord_service
from ..utils.slug_generator import generate_username_slug
import logging

logger = logging.getLogger(__name__)

settings = get_settings()
router = APIRouter()

@router.post("/register", response_model=Token)
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Register a new user and automatically log them in.

    Returns access and refresh tokens so the user doesn't need to login separately.
    """
    # Check if user exists
    result = await db.execute(
        select(User).where((User.username == user.username) | (User.email == user.email))
    )
    db_user = result.scalar_one_or_none()
    if db_user:
        raise HTTPException(
            status_code=400,
            detail="Username or email already registered"
        )

    # Generate unique slug for the user
    user_slug = generate_username_slug(username=user.name, email=user.email)

    # Handle collision (retry with new slug)
    max_retries = 10
    for attempt in range(max_retries):
        try:
            # Create new user
            hashed_password = get_password_hash(user.password)
            db_user = User(
                name=user.name,
                username=user.username,
                slug=user_slug,
                email=user.email,
                hashed_password=hashed_password
            )
            db.add(db_user)
            await db.commit()
            await db.refresh(db_user)
            break
        except Exception as e:
            await db.rollback()
            if "unique" in str(e).lower() and "slug" in str(e).lower() and attempt < max_retries - 1:
                # Slug collision, generate a new one
                user_slug = generate_username_slug(username=user.name, email=user.email)
                logger.warning(f"[REGISTER] Slug collision, retrying with: {user_slug}")
            else:
                # Other error or max retries reached
                raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")

    # Create LiteLLM virtual key for the user
    try:
        litellm_result = await litellm_service.create_user_key(
            user_id=db_user.id,
            username=db_user.username
        )

        # Update user with LiteLLM details
        db_user.litellm_api_key = litellm_result["api_key"]
        db_user.litellm_user_id = litellm_result["litellm_user_id"]
        await db.commit()

        logger.info(f"Created LiteLLM key for user {db_user.username}")
    except Exception as e:
        logger.error(f"Failed to create LiteLLM key for user {db_user.username}: {e}")
        # Commit the user without LiteLLM key - they can get one added later via script
        await db.commit()
        logger.warning(f"User {db_user.username} registered WITHOUT LiteLLM key. Run fix_user_keys.py to add it later.")

    # Auto-add Stream Builder (Open Source) agent to new users
    try:
        from ..models import MarketplaceAgent, UserPurchasedAgent

        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == "stream-builder-open")
        )
        stream_agent = result.scalar_one_or_none()

        if stream_agent:
            purchase = UserPurchasedAgent(
                user_id=db_user.id,
                agent_id=stream_agent.id,
                purchase_type="free",
                is_active=True
            )
            db.add(purchase)
            await db.commit()
            logger.info(f"Auto-added Stream Builder (Open Source) to user {db_user.username}")
        else:
            logger.warning("Stream Builder (Open Source) not found - user registered without default agent")
    except Exception as e:
        logger.error(f"Failed to add Stream Builder to user {db_user.username}: {e}")
        # Don't fail registration if agent assignment fails

    # Auto-login: Create tokens for the new user
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": db_user.username, "is_admin": db_user.is_admin}, expires_delta=access_token_expires
    )

    # Create refresh token
    refresh_token = await create_refresh_token(db_user, db)

    logger.info(f"User {db_user.username} registered and auto-logged in")

    # Send Discord notification for signup
    try:
        await discord_service.send_signup_notification(
            username=db_user.username,
            email=db_user.email,
            name=db_user.name,
            user_id=str(db_user.id)
        )
    except Exception as e:
        logger.error(f"Failed to send Discord signup notification: {e}")

    # Check if this was a referral signup
    # Frontend should send referred_by in request body if it exists in sessionStorage
    referred_by = getattr(user, 'referred_by', None)
    if referred_by:
        try:
            from ..referral_db import save_conversion
            from ..services.ntfy_service import ntfy_service

            # Save conversion to database
            save_conversion(referred_by, str(db_user.id), db_user.username, db_user.email, db_user.name)

            # Send referral conversion notifications
            await discord_service.send_referral_conversion_notification(
                referred_by=referred_by,
                new_user_name=db_user.name,
                new_user_username=db_user.username,
                new_user_email=db_user.email,
                user_id=str(db_user.id)
            )

            await ntfy_service.send_referral_conversion(referred_by, db_user.username)

            logger.info(f"Tracked referral conversion: {referred_by} -> {db_user.username}")
        except Exception as e:
            logger.error(f"Failed to track referral conversion: {e}")

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token
    }

@router.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """
    Login endpoint that returns both access and refresh tokens.

    Note: OAuth2 requires the field to be called "username", but we accept username OR email.

    Best practice token lifecycle:
    - Access token: Short-lived (30 minutes) for API requests
    - Refresh token: Long-lived (14 days) for obtaining new access tokens
    """
    try:
        # OAuth2 spec requires field name "username", but we accept username or email
        username_or_email = form_data.username
        logger.info(f"Login attempt for: {username_or_email}")
        user = await authenticate_user(db, username_or_email, form_data.password)
        if not user:
            logger.warning(f"Authentication failed for: {username_or_email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username/email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Create access token (short-lived)
        access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
        access_token = create_access_token(
            data={"sub": user.username, "is_admin": user.is_admin}, expires_delta=access_token_expires
        )

        # Create refresh token (long-lived)
        refresh_token = await create_refresh_token(user, db)

        logger.info(f"Login successful for: {username_or_email}")

        # Send Discord notification for login
        try:
            await discord_service.send_login_notification(
                username=user.username,
                email=user.email,
                user_id=str(user.id)
            )
        except Exception as e:
            logger.error(f"Failed to send Discord login notification: {e}")

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "refresh_token": refresh_token
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during login"
        )


@router.get("/verify")
async def verify_dev_environment_access(
    request: Request,
    current_user: User = Depends(get_current_active_user),
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
        from .utils.resource_naming import parse_hostname
        _, project_id_str = parse_hostname(request_host)
        from uuid import UUID
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
                expected_user_id=0,  # Unknown
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


@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    refresh_request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh endpoint to obtain a new access token using a refresh token.

    Best practice: This implements token rotation - the old refresh token
    is revoked and a new one is issued along with the new access token.
    """
    try:
        logger.info("Token refresh attempt")

        # Validate the refresh token
        user = await validate_refresh_token(refresh_request.refresh_token, db)
        if not user:
            logger.warning("Invalid or expired refresh token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Revoke the old refresh token (token rotation for security)
        await revoke_refresh_token(refresh_request.refresh_token, db)

        # Create new access token
        access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
        access_token = create_access_token(
            data={"sub": user.username, "is_admin": user.is_admin}, expires_delta=access_token_expires
        )

        # Create new refresh token (rotation)
        new_refresh_token = await create_refresh_token(user, db)

        logger.info(f"Token refresh successful for user: {user.username}")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "refresh_token": new_refresh_token
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during token refresh"
        )