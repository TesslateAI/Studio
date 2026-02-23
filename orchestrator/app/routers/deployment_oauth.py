"""
Deployment OAuth Flow Router.

This module provides OAuth 2.0 authentication endpoints for deployment providers
(Vercel, Netlify) that support OAuth instead of manual API tokens.
"""

import logging
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import DeploymentCredential, User
from ..services.deployment_encryption import (
    get_deployment_encryption_service,
)
from ..services.oauth_state import (
    DEPLOYMENT_OAUTH_AUDIENCE,
    decode_oauth_state,
    generate_oauth_state,
)
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deployment-oauth", tags=["deployment-oauth"])


# ============================================================================
# Vercel OAuth Endpoints
# ============================================================================


@router.get("/vercel/authorize")
async def vercel_authorize(
    project_id: UUID | None = Query(
        None, description="Optional project ID for project-specific credential"
    ),
    current_user: User = Depends(current_active_user),
):
    """
    Initiate Vercel OAuth flow.

    Returns the OAuth authorization URL for the frontend to redirect to.
    After authorization, Vercel will redirect back to /vercel/callback.

    Args:
        project_id: Optional project ID for project-specific credential override
        current_user: Current authenticated user

    Returns:
        JSON with auth_url to redirect to
    """
    settings = get_settings()

    # Check if Vercel OAuth is configured
    if not settings.vercel_client_id or not settings.vercel_oauth_redirect_uri:
        logger.error("Vercel OAuth not configured")
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Vercel OAuth is not configured on this server",
        )

    # Generate signed JWT state token (stateless, survives restarts)
    extra = {}
    if project_id:
        extra["project_id"] = str(project_id)
    state = generate_oauth_state(
        user_id=str(current_user.id),
        flow="vercel",
        audience=DEPLOYMENT_OAUTH_AUDIENCE,
        extra=extra,
    )

    # Build Vercel OAuth URL
    oauth_url = (
        f"https://vercel.com/oauth/authorize"
        f"?client_id={settings.vercel_client_id}"
        f"&redirect_uri={settings.vercel_oauth_redirect_uri}"
        f"&state={state}"
        f"&scope=deployments"  # Request deployment permissions
    )

    logger.info(f"Generated Vercel OAuth URL for user {current_user.id}")
    return {"auth_url": oauth_url}


@router.get("/vercel/callback")
async def vercel_callback(
    code: str = Query(..., description="Authorization code from Vercel"),
    state: str | None = Query(None, description="State token for CSRF protection"),
    configurationId: str | None = Query(None, description="Vercel configuration ID"),
    teamId: str | None = Query(None, description="Vercel team ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_active_user),
):
    """
    Vercel OAuth callback endpoint.

    This endpoint is called by Vercel after the user authorizes the application.
    It exchanges the authorization code for an access token and stores it securely.

    Supports two flows:
    1. Direct OAuth flow (with state token)
    2. Marketplace installation flow (with configurationId, no state)

    Args:
        code: Authorization code from Vercel
        state: State token for CSRF verification (optional for marketplace flow)
        configurationId: Vercel configuration ID (for marketplace installations)
        teamId: Vercel team ID (optional)
        db: Database session
        current_user: Current authenticated user (optional)

    Returns:
        Redirect to frontend settings page
    """
    settings = get_settings()

    try:
        # Determine which flow we're using
        project_id = None
        user_id = None

        if state:
            # Standard OAuth flow with JWT state token
            state_payload = decode_oauth_state(state, DEPLOYMENT_OAUTH_AUDIENCE)
            if not state_payload:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired state token",
                )
            user_id = UUID(state_payload["sub"])
            # Extract project_id from JWT extra data
            extra_data = state_payload.get("data", {})
            project_id_str = extra_data.get("project_id")
            if project_id_str:
                try:
                    project_id = UUID(project_id_str)
                except ValueError:
                    logger.warning(f"Invalid project_id in state: {project_id_str}")
        elif current_user:
            # Marketplace installation flow - user is already authenticated
            user_id = current_user.id
            logger.info(f"Vercel marketplace installation for user {user_id}")
        else:
            # No state and no current user - can't proceed
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing authentication: no state token or current user",
            )

        # Exchange code for access token
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.vercel.com/v2/oauth/access_token",
                data={
                    "client_id": settings.vercel_client_id,
                    "client_secret": settings.vercel_client_secret,
                    "code": code,
                    "redirect_uri": settings.vercel_oauth_redirect_uri,
                },
            )
            response.raise_for_status()
            token_data = response.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to obtain access token from Vercel",
            )

        # Optionally fetch team information and store configuration ID
        team_id = token_data.get("team_id") or teamId
        metadata = {}
        if team_id:
            metadata["team_id"] = team_id
        if configurationId:
            metadata["configuration_id"] = configurationId

            # Fetch team name
            try:
                async with httpx.AsyncClient() as client:
                    team_response = await client.get(
                        f"https://api.vercel.com/v2/teams/{team_id}",
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    if team_response.status_code == 200:
                        team_data = team_response.json()
                        metadata["account_name"] = team_data.get("name", team_data.get("slug"))
            except Exception as e:
                logger.warning(f"Failed to fetch Vercel team info: {e}")

        # Encrypt and store credential
        encryption_service = get_deployment_encryption_service()
        encrypted_token = encryption_service.encrypt(access_token)

        # Check for existing credential (upsert)
        from sqlalchemy import and_

        existing_result = await db.execute(
            select(DeploymentCredential).where(
                and_(
                    DeploymentCredential.user_id == user_id,
                    DeploymentCredential.provider == "vercel",
                    DeploymentCredential.project_id == project_id,
                )
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.access_token_encrypted = encrypted_token
            existing.metadata = metadata
            await db.commit()
            logger.info(f"Updated Vercel credential for user {user_id}")
        else:
            credential = DeploymentCredential(
                user_id=user_id,
                project_id=project_id,
                provider="vercel",
                access_token_encrypted=encrypted_token,
                metadata=metadata,
            )
            db.add(credential)
            await db.commit()
            logger.info(f"Created Vercel credential for user {user_id}")

        # Redirect to frontend settings page with success message
        frontend_url = (
            settings.cors_origins.split(",")[0]
            if settings.cors_origins
            else "http://localhost:5173"
        )
        redirect_url = f"{frontend_url}/settings?tab=deployments&success=vercel"

        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Vercel OAuth callback failed: {e}", exc_info=True)

        # Redirect to frontend with error
        frontend_url = (
            settings.cors_origins.split(",")[0]
            if settings.cors_origins
            else "http://localhost:5173"
        )
        redirect_url = f"{frontend_url}/settings?tab=deployments&error=vercel"

        return RedirectResponse(url=redirect_url)


# ============================================================================
# Netlify OAuth Endpoints
# ============================================================================


@router.get("/netlify/authorize")
async def netlify_authorize(
    project_id: UUID | None = Query(
        None, description="Optional project ID for project-specific credential"
    ),
    current_user: User = Depends(current_active_user),
):
    """
    Initiate Netlify OAuth flow.

    Returns the OAuth authorization URL for the frontend to redirect to.
    After authorization, Netlify will redirect back to /netlify/callback.

    Args:
        project_id: Optional project ID for project-specific credential override
        current_user: Current authenticated user

    Returns:
        JSON with auth_url to redirect to
    """
    settings = get_settings()

    # Check if Netlify OAuth is configured
    if not settings.netlify_client_id or not settings.netlify_oauth_redirect_uri:
        logger.error("Netlify OAuth not configured")
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Netlify OAuth is not configured on this server",
        )

    # Generate signed JWT state token (stateless, survives restarts)
    extra = {}
    if project_id:
        extra["project_id"] = str(project_id)
    state = generate_oauth_state(
        user_id=str(current_user.id),
        flow="netlify",
        audience=DEPLOYMENT_OAUTH_AUDIENCE,
        extra=extra,
    )

    # Build Netlify OAuth URL
    oauth_url = (
        f"https://app.netlify.com/authorize"
        f"?client_id={settings.netlify_client_id}"
        f"&redirect_uri={settings.netlify_oauth_redirect_uri}"
        f"&state={state}"
        f"&response_type=code"
    )

    logger.info(f"Generated Netlify OAuth URL for user {current_user.id}")
    return {"auth_url": oauth_url}


@router.get("/netlify/callback")
async def netlify_callback(
    code: str = Query(..., description="Authorization code from Netlify"),
    state: str = Query(..., description="State token for CSRF protection"),
    db: AsyncSession = Depends(get_db),
):
    """
    Netlify OAuth callback endpoint.

    This endpoint is called by Netlify after the user authorizes the application.
    It exchanges the authorization code for an access token and stores it securely.

    Args:
        code: Authorization code from Netlify
        state: State token for CSRF verification
        db: Database session

    Returns:
        Redirect to frontend settings page
    """
    settings = get_settings()

    try:
        # Validate JWT state token
        state_payload = decode_oauth_state(state, DEPLOYMENT_OAUTH_AUDIENCE)
        if not state_payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state token",
            )

        user_id = UUID(state_payload["sub"])

        # Extract project_id from JWT extra data
        project_id = None
        extra_data = state_payload.get("data", {})
        project_id_str = extra_data.get("project_id")
        if project_id_str:
            try:
                project_id = UUID(project_id_str)
            except ValueError:
                logger.warning(f"Invalid project_id in state: {project_id_str}")

        # Exchange code for access token
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.netlify.com/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": settings.netlify_client_id,
                    "client_secret": settings.netlify_client_secret,
                    "redirect_uri": settings.netlify_oauth_redirect_uri,
                },
            )
            response.raise_for_status()
            token_data = response.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to obtain access token from Netlify",
            )

        # Optionally fetch account information
        metadata = {}
        try:
            async with httpx.AsyncClient() as client:
                user_response = await client.get(
                    "https://api.netlify.com/api/v1/user",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if user_response.status_code == 200:
                    user_data = user_response.json()
                    metadata["account_name"] = user_data.get("full_name") or user_data.get("email")
        except Exception as e:
            logger.warning(f"Failed to fetch Netlify account info: {e}")

        # Encrypt and store credential
        encryption_service = get_deployment_encryption_service()
        encrypted_token = encryption_service.encrypt(access_token)

        # Check for existing credential (upsert)
        from sqlalchemy import and_

        existing_result = await db.execute(
            select(DeploymentCredential).where(
                and_(
                    DeploymentCredential.user_id == user_id,
                    DeploymentCredential.provider == "netlify",
                    DeploymentCredential.project_id == project_id,
                )
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.access_token_encrypted = encrypted_token
            existing.metadata = metadata
            await db.commit()
            logger.info(f"Updated Netlify credential for user {user_id}")
        else:
            credential = DeploymentCredential(
                user_id=user_id,
                project_id=project_id,
                provider="netlify",
                access_token_encrypted=encrypted_token,
                metadata=metadata,
            )
            db.add(credential)
            await db.commit()
            logger.info(f"Created Netlify credential for user {user_id}")

        # Redirect to frontend settings page with success message
        frontend_url = (
            settings.cors_origins.split(",")[0]
            if settings.cors_origins
            else "http://localhost:5173"
        )
        redirect_url = f"{frontend_url}/settings?tab=deployments&success=netlify"

        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Netlify OAuth callback failed: {e}", exc_info=True)

        # Redirect to frontend with error
        frontend_url = (
            settings.cors_origins.split(",")[0]
            if settings.cors_origins
            else "http://localhost:5173"
        )
        redirect_url = f"{frontend_url}/settings?tab=deployments&error=netlify"

        return RedirectResponse(url=redirect_url)
