"""
Deployment OAuth Flow Router.

This module provides OAuth 2.0 authentication endpoints for deployment providers
(Vercel, Netlify) that support OAuth instead of manual API tokens.
"""

import logging
import secrets
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from ..database import get_db
from ..models import DeploymentCredential, User
from ..auth import get_current_user
from ..services.deployment_encryption import get_deployment_encryption_service, DeploymentEncryptionError
from ..config import get_settings
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deployment-oauth", tags=["deployment-oauth"])

# In-memory store for OAuth state tokens (in production, use Redis or database)
# Maps state token -> user_id
_oauth_states = {}


# ============================================================================
# Helper Functions
# ============================================================================

def generate_state_token(user_id: UUID) -> str:
    """Generate a secure random state token for CSRF protection."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = str(user_id)
    logger.debug(f"Generated OAuth state token for user {user_id}")
    return state


def verify_state_token(state: str) -> Optional[str]:
    """Verify and consume a state token, returning the user_id if valid."""
    user_id = _oauth_states.pop(state, None)
    if user_id:
        logger.debug(f"Verified OAuth state token for user {user_id}")
    else:
        logger.warning(f"Invalid or expired OAuth state token: {state}")
    return user_id


# ============================================================================
# Vercel OAuth Endpoints
# ============================================================================

@router.get("/vercel/authorize")
async def vercel_authorize(
    project_id: Optional[UUID] = Query(None, description="Optional project ID for project-specific credential"),
    current_user: User = Depends(current_active_user)
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
            detail="Vercel OAuth is not configured on this server"
        )

    # Generate state token for CSRF protection
    state = generate_state_token(current_user.id)

    # Add project_id to state if provided (encode it)
    if project_id:
        state = f"{state}:{project_id}"

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
    state: Optional[str] = Query(None, description="State token for CSRF protection"),
    configurationId: Optional[str] = Query(None, description="Vercel configuration ID"),
    teamId: Optional[str] = Query(None, description="Vercel team ID"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(current_active_user)
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
            # Standard OAuth flow with state token
            # Parse state (may contain project_id)
            if ":" in state:
                state, project_id_str = state.split(":", 1)
                try:
                    project_id = UUID(project_id_str)
                except ValueError:
                    logger.warning(f"Invalid project_id in state: {project_id_str}")

            # Verify state token
            user_id_str = verify_state_token(state)
            if not user_id_str:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired state token"
                )
            user_id = UUID(user_id_str)
        elif current_user:
            # Marketplace installation flow - user is already authenticated
            user_id = current_user.id
            logger.info(f"Vercel marketplace installation for user {user_id}")
        else:
            # No state and no current user - can't proceed
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing authentication: no state token or current user"
            )

        # Exchange code for access token
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.vercel.com/v2/oauth/access_token",
                data={
                    "client_id": settings.vercel_client_id,
                    "client_secret": settings.vercel_client_secret,
                    "code": code,
                    "redirect_uri": settings.vercel_oauth_redirect_uri
                }
            )
            response.raise_for_status()
            token_data = response.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to obtain access token from Vercel"
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
                        headers={"Authorization": f"Bearer {access_token}"}
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
                    DeploymentCredential.project_id == project_id
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
                metadata=metadata
            )
            db.add(credential)
            await db.commit()
            logger.info(f"Created Vercel credential for user {user_id}")

        # Redirect to frontend settings page with success message
        frontend_url = settings.cors_origins.split(",")[0] if settings.cors_origins else "http://localhost:5173"
        redirect_url = f"{frontend_url}/settings?tab=deployments&success=vercel"

        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Vercel OAuth callback failed: {e}", exc_info=True)

        # Redirect to frontend with error
        frontend_url = settings.cors_origins.split(",")[0] if settings.cors_origins else "http://localhost:5173"
        redirect_url = f"{frontend_url}/settings?tab=deployments&error=vercel"

        return RedirectResponse(url=redirect_url)


# ============================================================================
# Netlify OAuth Endpoints
# ============================================================================

@router.get("/netlify/authorize")
async def netlify_authorize(
    project_id: Optional[UUID] = Query(None, description="Optional project ID for project-specific credential"),
    current_user: User = Depends(current_active_user)
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
            detail="Netlify OAuth is not configured on this server"
        )

    # Generate state token for CSRF protection
    state = generate_state_token(current_user.id)

    # Add project_id to state if provided
    if project_id:
        state = f"{state}:{project_id}"

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
    db: AsyncSession = Depends(get_db)
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
        # Parse state (may contain project_id)
        project_id = None
        if ":" in state:
            state, project_id_str = state.split(":", 1)
            try:
                project_id = UUID(project_id_str)
            except ValueError:
                logger.warning(f"Invalid project_id in state: {project_id_str}")

        # Verify state token
        user_id_str = verify_state_token(state)
        if not user_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state token"
            )

        user_id = UUID(user_id_str)

        # Exchange code for access token
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.netlify.com/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": settings.netlify_client_id,
                    "client_secret": settings.netlify_client_secret,
                    "redirect_uri": settings.netlify_oauth_redirect_uri
                }
            )
            response.raise_for_status()
            token_data = response.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to obtain access token from Netlify"
            )

        # Optionally fetch account information
        metadata = {}
        try:
            async with httpx.AsyncClient() as client:
                user_response = await client.get(
                    "https://api.netlify.com/api/v1/user",
                    headers={"Authorization": f"Bearer {access_token}"}
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
                    DeploymentCredential.project_id == project_id
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
                metadata=metadata
            )
            db.add(credential)
            await db.commit()
            logger.info(f"Created Netlify credential for user {user_id}")

        # Redirect to frontend settings page with success message
        frontend_url = settings.cors_origins.split(",")[0] if settings.cors_origins else "http://localhost:5173"
        redirect_url = f"{frontend_url}/settings?tab=deployments&success=netlify"

        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Netlify OAuth callback failed: {e}", exc_info=True)

        # Redirect to frontend with error
        frontend_url = settings.cors_origins.split(",")[0] if settings.cors_origins else "http://localhost:5173"
        redirect_url = f"{frontend_url}/settings?tab=deployments&error=netlify"

        return RedirectResponse(url=redirect_url)
