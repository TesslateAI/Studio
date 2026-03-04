"""
Deployment OAuth Flow Router.

This module provides OAuth 2.0 authentication endpoints for deployment providers
(Vercel, Netlify) that support OAuth instead of manual API tokens.
"""

import base64
import hashlib
import html as html_mod
import logging
import secrets
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
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
# Shared HTML response helpers
# ============================================================================


def _success_html(provider_name: str) -> HTMLResponse:
    """Return HTML page that shows success and closes the popup window."""
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>{provider_name} Connected</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            background: #1a1a1a;
            color: #fff;
        }}
        .checkmark {{ font-size: 64px; margin-bottom: 16px; }}
        h1 {{ font-size: 24px; margin: 0 0 8px 0; }}
        p {{ color: #888; margin: 0; }}
    </style>
</head>
<body>
    <div class="checkmark">&#10003;</div>
    <h1>{provider_name} Connected!</h1>
    <p>This window will close automatically...</p>
    <script>
        setTimeout(function() {{ window.close(); }}, 1500);
    </script>
</body>
</html>
    """, status_code=200)


def _error_html(title: str, message: str) -> HTMLResponse:
    """Return HTML error page that shows the error and closes the popup window."""
    # Escape HTML entities in user-facing strings
    safe_title = html_mod.escape(title)
    safe_message = html_mod.escape(message)
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <title>Connection Failed</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            background: #1a1a1a;
            color: #fff;
        }}
        .error {{ font-size: 64px; margin-bottom: 16px; }}
        h1 {{ font-size: 24px; margin: 0 0 8px 0; color: #f87171; }}
        p {{ color: #888; margin: 0; max-width: 400px; text-align: center; }}
    </style>
</head>
<body>
    <div class="error">&#10007;</div>
    <h1>{safe_title}</h1>
    <p>{safe_message}</p>
    <script>
        setTimeout(function() {{ window.close(); }}, 3000);
    </script>
</body>
</html>
    """, status_code=200)


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

    # PKCE: generate code_verifier and code_challenge (required by Vercel)
    code_verifier = secrets.token_hex(43)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    # Generate signed JWT state token (stateless, survives restarts)
    # Store code_verifier in JWT so we can use it in the callback
    extra = {"code_verifier": code_verifier}
    if project_id:
        extra["project_id"] = str(project_id)
    state = generate_oauth_state(
        user_id=str(current_user.id),
        flow="vercel",
        audience=DEPLOYMENT_OAUTH_AUDIENCE,
        extra=extra,
    )

    # Build Vercel OAuth URL (redirect_uri must be URL-encoded per OAuth 2.0 spec)
    encoded_redirect = quote(settings.vercel_oauth_redirect_uri, safe="")
    oauth_url = (
        f"https://vercel.com/oauth/authorize"
        f"?client_id={settings.vercel_client_id}"
        f"&redirect_uri={encoded_redirect}"
        f"&state={state}"
        f"&response_type=code"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )

    logger.info(f"Generated Vercel OAuth URL for user {current_user.id}")
    return {"auth_url": oauth_url}


@router.get("/vercel/callback")
async def vercel_callback(
    code: str | None = Query(None, description="Authorization code from Vercel"),
    state: str | None = Query(None, description="State token for CSRF protection"),
    error: str | None = Query(None, description="OAuth error code"),
    error_description: str | None = Query(None, description="OAuth error description"),
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
        code: Authorization code from Vercel (missing if user denied or error occurred)
        state: State token for CSRF verification (optional for marketplace flow)
        error: OAuth error code (e.g., "access_denied")
        error_description: Human-readable error description
        configurationId: Vercel configuration ID (for marketplace installations)
        teamId: Vercel team ID (optional)
        db: Database session
        current_user: Current authenticated user (optional)

    Returns:
        HTML page that closes the popup window
    """
    settings = get_settings()

    # Handle OAuth errors (user denied, provider error, etc.)
    if error:
        desc = error_description or error
        logger.warning(f"Vercel OAuth error: {error} - {error_description}")
        return _error_html("Authorization Denied", f"Vercel returned: {desc}")

    # code is required for the token exchange
    if not code:
        logger.warning("Vercel OAuth callback received without authorization code")
        return _error_html(
            "Connection Failed",
            "No authorization code received from Vercel. Please try again.",
        )

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
            # Extract extra data from JWT (project_id, code_verifier)
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
            extra_data = {}
            logger.info(f"Vercel marketplace installation for user {user_id}")
        else:
            # No state and no current user - can't proceed
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing authentication: no state token or current user",
            )

        # Exchange code for access token using Vercel's current OAuth endpoint
        # PKCE code_verifier is stored in the JWT state token
        code_verifier = extra_data.get("code_verifier", "")
        token_params = {
            "grant_type": "authorization_code",
            "client_id": settings.vercel_client_id,
            "client_secret": settings.vercel_client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": settings.vercel_oauth_redirect_uri,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.vercel.com/login/oauth/token",
                data=token_params,
            )
            if response.status_code != 200:
                error_body = response.text
                logger.error(
                    f"Vercel token exchange failed ({response.status_code}): {error_body}"
                )
                return _error_html(
                    "Connection Failed",
                    "Vercel rejected the token exchange. Please try again.",
                )
            token_data = response.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to obtain access token from Vercel",
            )

        # Fetch team information and store configuration ID
        team_id = token_data.get("team_id") or teamId
        metadata = {}
        if configurationId:
            metadata["configuration_id"] = configurationId

        # If no team_id from token response or callback, proactively fetch
        # the user's teams. Without a team_id, Vercel API calls go to the
        # personal/Hobby scope which may not have project creation permissions.
        if not team_id:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    teams_response = await client.get(
                        "https://api.vercel.com/v2/teams",
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    if teams_response.status_code == 200:
                        teams_data = teams_response.json()
                        teams = teams_data.get("teams", [])
                        if teams:
                            # Use the first team (primary team)
                            team_id = teams[0].get("id")
                            metadata["account_name"] = teams[0].get("name", teams[0].get("slug"))
                            logger.info(f"Auto-detected Vercel team: {team_id}")
            except Exception as e:
                logger.warning(f"Failed to fetch Vercel teams: {e}")

        if team_id:
            metadata["team_id"] = team_id
            # Fetch team name if not already set
            if "account_name" not in metadata:
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        team_response = await client.get(
                            f"https://api.vercel.com/v2/teams/{team_id}",
                            headers={"Authorization": f"Bearer {access_token}"},
                        )
                        if team_response.status_code == 200:
                            team_data = team_response.json()
                            metadata["account_name"] = team_data.get("name", team_data.get("slug"))
                except Exception as e:
                    logger.warning(f"Failed to fetch Vercel team info: {e}")
        else:
            # Personal account — fetch user info for account_name
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    user_response = await client.get(
                        "https://api.vercel.com/v2/user",
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                    if user_response.status_code == 200:
                        user_data = user_response.json().get("user", {})
                        metadata["account_name"] = user_data.get("name") or user_data.get("username")
            except Exception as e:
                logger.warning(f"Failed to fetch Vercel user info: {e}")

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
            existing.provider_metadata = metadata
            await db.commit()
            logger.info(f"Updated Vercel credential for user {user_id}")
        else:
            credential = DeploymentCredential(
                user_id=user_id,
                project_id=project_id,
                provider="vercel",
                access_token_encrypted=encrypted_token,
                provider_metadata=metadata,
            )
            db.add(credential)
            await db.commit()
            logger.info(f"Created Vercel credential for user {user_id}")

        return _success_html("Vercel")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Vercel OAuth callback failed: {e}", exc_info=True)
        return _error_html("Connection Failed", "Please close this window and try again.")


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

    # Build Netlify OAuth URL (redirect_uri must be URL-encoded per OAuth 2.0 spec)
    encoded_redirect = quote(settings.netlify_oauth_redirect_uri, safe="")
    oauth_url = (
        f"https://app.netlify.com/authorize"
        f"?client_id={settings.netlify_client_id}"
        f"&redirect_uri={encoded_redirect}"
        f"&state={state}"
        f"&response_type=code"
    )

    logger.info(f"Generated Netlify OAuth URL for user {current_user.id}")
    return {"auth_url": oauth_url}


@router.get("/netlify/callback")
async def netlify_callback(
    code: str | None = Query(None, description="Authorization code from Netlify"),
    state: str | None = Query(None, description="State token for CSRF protection"),
    error: str | None = Query(None, description="OAuth error code"),
    error_description: str | None = Query(None, description="OAuth error description"),
    db: AsyncSession = Depends(get_db),
):
    """
    Netlify OAuth callback endpoint.

    This endpoint is called by Netlify after the user authorizes the application.
    It exchanges the authorization code for an access token and stores it securely.

    Args:
        code: Authorization code from Netlify (missing if user denied or error occurred)
        state: State token for CSRF verification
        error: OAuth error code (e.g., "access_denied")
        error_description: Human-readable error description
        db: Database session

    Returns:
        HTML page that closes the popup window
    """
    settings = get_settings()

    # Handle OAuth errors (user denied, provider error, etc.)
    if error:
        desc = error_description or error
        logger.warning(f"Netlify OAuth error: {error} - {error_description}")
        return _error_html("Authorization Denied", f"Netlify returned: {desc}")

    # code and state are required for the token exchange
    if not code:
        logger.warning("Netlify OAuth callback received without authorization code")
        return _error_html(
            "Connection Failed",
            "No authorization code received from Netlify. Please try again.",
        )

    if not state:
        logger.warning("Netlify OAuth callback received without state token")
        return _error_html(
            "Connection Failed",
            "Missing state token. Please try again.",
        )

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
            if response.status_code != 200:
                error_body = response.text
                logger.error(
                    f"Netlify token exchange failed ({response.status_code}): {error_body}"
                )
                return _error_html(
                    "Connection Failed",
                    "Netlify rejected the token exchange. Please try again.",
                )
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
            existing.provider_metadata = metadata
            await db.commit()
            logger.info(f"Updated Netlify credential for user {user_id}")
        else:
            credential = DeploymentCredential(
                user_id=user_id,
                project_id=project_id,
                provider="netlify",
                access_token_encrypted=encrypted_token,
                provider_metadata=metadata,
            )
            db.add(credential)
            await db.commit()
            logger.info(f"Created Netlify credential for user {user_id}")

        return _success_html("Netlify")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Netlify OAuth callback failed: {e}", exc_info=True)
        return _error_html("Connection Failed", "Please close this window and try again.")
