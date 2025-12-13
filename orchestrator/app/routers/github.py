"""
GitHub integration router for OAuth authentication and repository management.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status, Response, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
import httpx
import logging
from datetime import datetime

from ..database import get_db
from ..models import User, Project, GitRepository, GitHubCredential
from ..schemas import (
    GitHubCredentialResponse,
    GitRepositoryResponse,
    CreateGitHubRepoRequest,
    GitHubOAuthCallbackRequest
)
from ..services.credential_manager import get_credential_manager
from ..services.github_client import GitHubClient
from ..services.github_oauth import get_github_oauth_service
from ..users import current_active_user, current_superuser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])


# Store OAuth states temporarily (in production, use Redis or database)
# Key: state, Value: {"user_id": int, "timestamp": datetime}
oauth_states = {}


@router.get("/oauth/authorize")
async def github_oauth_authorize(
    current_user: User = Depends(current_active_user),
    scope: str = Query(default="repo user:email", description="OAuth scopes to request")
):
    """
    Initiate GitHub OAuth authorization flow.

    Returns a redirect URL for the frontend to navigate to GitHub's authorization page.
    """
    try:
        oauth_service = get_github_oauth_service()

        # Generate state for CSRF protection
        state = oauth_service.generate_state()

        # Store state with user info (expires in 10 minutes)
        oauth_states[state] = {
            "user_id": current_user.id,
            "timestamp": datetime.utcnow(),
            "scope": scope
        }

        # Clean up old states (older than 10 minutes)
        cutoff = datetime.utcnow()
        expired_states = [
            s for s, data in oauth_states.items()
            if (cutoff - data["timestamp"]).seconds > 600
        ]
        for s in expired_states:
            del oauth_states[s]

        # Generate authorization URL
        auth_url = oauth_service.get_authorization_url(state, scope)

        logger.info(f"[GITHUB] User {current_user.id} initiating OAuth flow")

        return {
            "authorization_url": auth_url,
            "state": state
        }

    except Exception as e:
        logger.error(f"[GITHUB] Failed to initiate OAuth: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate GitHub OAuth: {str(e)}"
        )


@router.get("/oauth/callback")
async def github_oauth_callback(
    code: str = Query(..., description="Authorization code from GitHub"),
    state: str = Query(..., description="State parameter for CSRF protection"),
    db: AsyncSession = Depends(get_db)
):
    """
    Handle GitHub OAuth callback.

    This endpoint is called by GitHub after user authorizes the application.
    It exchanges the authorization code for an access token and stores it.
    """
    try:
        # Validate state
        if state not in oauth_states:
            logger.error(f"[GITHUB] Invalid OAuth state: {state}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OAuth state. Please try connecting again."
            )

        state_data = oauth_states[state]
        user_id = state_data["user_id"]

        # Clean up used state
        del oauth_states[state]

        # Exchange code for token
        oauth_service = get_github_oauth_service()
        token_data = await oauth_service.exchange_code_for_token(code, state)

        if "access_token" not in token_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to obtain access token from GitHub"
            )

        access_token = token_data["access_token"]
        scope = token_data.get("scope", "")

        # Get user info from GitHub
        user_info = await oauth_service.get_user_info(access_token)

        # Get user email if not in profile
        github_email = user_info.get("email")
        if not github_email:
            try:
                emails = await oauth_service.get_user_emails(access_token)
                primary_email = next((e["email"] for e in emails if e.get("primary")), None)
                github_email = primary_email or (emails[0]["email"] if emails else None)
            except Exception as e:
                logger.warning(f"[GITHUB] Could not fetch user emails: {e}")

        # Store credentials
        credential_manager = get_credential_manager()
        await credential_manager.store_oauth_token(
            db=db,
            user_id=user_id,
            access_token=access_token,
            refresh_token=None,  # GitHub doesn't provide refresh tokens for OAuth Apps
            expires_at=token_data.get("expires_at"),
            github_username=user_info.get("login"),
            github_email=github_email,
            github_user_id=str(user_info.get("id"))
        )

        # Also store scope in credentials
        result = await db.execute(
            select(GitHubCredential).where(GitHubCredential.user_id == user_id)
        )
        credential = result.scalar_one_or_none()
        if credential:
            credential.scope = scope
            credential.state = None  # Clear state after successful auth
            await db.commit()

        logger.info(f"[GITHUB] User {user_id} successfully connected GitHub account: {user_info.get('login')}")

        # Return success response that frontend can handle
        return {
            "success": True,
            "github_username": user_info.get("login"),
            "github_email": github_email,
            "message": "GitHub account connected successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GITHUB] OAuth callback failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete GitHub OAuth: {str(e)}"
        )


@router.post("/oauth/refresh")
async def refresh_github_token(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh GitHub OAuth token.

    Note: GitHub doesn't support refresh tokens for OAuth Apps,
    so this will return an error instructing user to re-authenticate.
    """
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="GitHub OAuth doesn't support token refresh. Please reconnect your GitHub account."
    )


@router.get("/status", response_model=GitHubCredentialResponse)
async def get_github_status(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the current GitHub connection status for the user.
    """
    try:
        credential_manager = get_credential_manager()
        has_creds = await credential_manager.has_credentials(db, current_user.id)

        if not has_creds:
            return GitHubCredentialResponse(connected=False)

        credentials = await credential_manager.get_credentials(db, current_user.id)

        return GitHubCredentialResponse(
            connected=True,
            github_username=credentials.get("github_username"),
            github_email=credentials.get("github_email"),
            auth_method="oauth",
            scope=credentials.get("scope")
        )

    except Exception as e:
        logger.error(f"[GITHUB] Failed to get status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get GitHub status: {str(e)}"
        )


@router.delete("/disconnect")
async def disconnect_github(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Disconnect GitHub account and revoke access token.
    """
    try:
        credential_manager = get_credential_manager()

        # Get access token before deletion
        access_token = await credential_manager.get_access_token(db, current_user.id)

        if access_token:
            # Try to revoke token on GitHub's side
            oauth_service = get_github_oauth_service()
            try:
                await oauth_service.revoke_token(access_token)
                logger.info(f"[GITHUB] Revoked access token for user {current_user.id}")
            except Exception as e:
                logger.warning(f"[GITHUB] Failed to revoke token on GitHub: {e}")

        # Delete credentials from database
        deleted = await credential_manager.delete_credentials(db, current_user.id)

        if deleted:
            logger.info(f"[GITHUB] User {current_user.id} disconnected GitHub account")
            return {"message": "GitHub account disconnected successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No GitHub connection found"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GITHUB] Failed to disconnect: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect GitHub: {str(e)}"
        )


@router.get("/repositories")
async def list_github_repositories(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all repositories accessible by the authenticated GitHub account.
    """
    try:
        # Get GitHub credentials
        credential_manager = get_credential_manager()
        access_token = await credential_manager.get_access_token(db, current_user.id)

        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="GitHub not connected. Please connect your GitHub account first."
            )

        # Create GitHub client
        github_client = GitHubClient(access_token)

        # List repositories
        try:
            repos = await github_client.list_user_repositories()

            # Format response
            formatted_repos = [
                {
                    "id": repo["id"],
                    "name": repo["name"],
                    "full_name": repo["full_name"],
                    "description": repo.get("description"),
                    "url": repo["html_url"],
                    "clone_url": repo["clone_url"],
                    "default_branch": repo.get("default_branch", "main"),
                    "private": repo.get("private", False),
                    "updated_at": repo.get("updated_at"),
                    "language": repo.get("language"),
                    "size": repo.get("size", 0),
                    "stargazers_count": repo.get("stargazers_count", 0),
                    "forks_count": repo.get("forks_count", 0)
                }
                for repo in repos
            ]

            return {"repositories": formatted_repos}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="GitHub token expired or invalid. Please reconnect your GitHub account."
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch repositories from GitHub: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GITHUB] Failed to list repositories: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list repositories: {str(e)}"
        )


@router.post("/repositories", status_code=status.HTTP_201_CREATED)
async def create_github_repository(
    request: CreateGitHubRepoRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new GitHub repository.
    """
    try:
        # Get GitHub credentials
        credential_manager = get_credential_manager()
        access_token = await credential_manager.get_access_token(db, current_user.id)

        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="GitHub not connected. Please connect your GitHub account first."
            )

        # Create GitHub client
        github_client = GitHubClient(access_token)

        # Create repository
        try:
            repo = await github_client.create_repository(
                name=request.name,
                description=request.description,
                private=request.private,
                auto_init=request.auto_init
            )

            logger.info(f"[GITHUB] User {current_user.id} created repository: {repo['full_name']}")

            return {
                "id": repo["id"],
                "name": repo["name"],
                "full_name": repo["full_name"],
                "url": repo["html_url"],
                "clone_url": repo["clone_url"],
                "default_branch": repo.get("default_branch", "main")
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="GitHub token expired or invalid. Please reconnect your GitHub account."
                )
            elif e.response.status_code == 422:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Repository name already exists or is invalid"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create repository on GitHub: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GITHUB] Failed to create repository: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create repository: {str(e)}"
        )


@router.get("/repositories/{owner}/{repo}/branches")
async def list_repository_branches(
    owner: str,
    repo: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all branches for a specific GitHub repository.
    """
    try:
        # Get GitHub credentials
        credential_manager = get_credential_manager()
        access_token = await credential_manager.get_access_token(db, current_user.id)

        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="GitHub not connected. Please connect your GitHub account first."
            )

        # Create GitHub client
        github_client = GitHubClient(access_token)

        # List branches
        try:
            branches = await github_client.list_branches(owner, repo)

            formatted_branches = [
                {
                    "name": branch["name"],
                    "protected": branch.get("protected", False),
                    "commit": {
                        "sha": branch["commit"]["sha"],
                        "url": branch["commit"]["url"]
                    }
                }
                for branch in branches
            ]

            return {"branches": formatted_branches}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Repository {owner}/{repo} not found"
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch branches from GitHub: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GITHUB] Failed to list branches: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list branches: {str(e)}"
        )