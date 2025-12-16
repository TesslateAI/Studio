"""
Unified Git Providers Router.

Provides OAuth authentication and repository management for GitHub, GitLab, and Bitbucket.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import datetime
import logging

from ..database import get_db
from ..models import User
from ..users import current_active_user
from ..services.git_providers import (
    GitProviderManager,
    GitProviderType,
    get_git_provider_credential_service,
)
from ..services.git_providers.oauth import (
    get_github_oauth_service,
    get_gitlab_oauth_service,
    get_bitbucket_oauth_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/git-providers", tags=["git-providers"])

# Store OAuth states temporarily (in production, use Redis or database)
# Key: state, Value: {"user_id": UUID, "provider": str, "timestamp": datetime}
oauth_states = {}


def get_oauth_service(provider: str):
    """Get the OAuth service for a provider."""
    if provider == "github":
        return get_github_oauth_service()
    elif provider == "gitlab":
        return get_gitlab_oauth_service()
    elif provider == "bitbucket":
        return get_bitbucket_oauth_service()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid provider: {provider}. Valid providers: github, gitlab, bitbucket"
        )


def validate_provider(provider: str) -> GitProviderType:
    """Validate and convert provider string to GitProviderType."""
    try:
        return GitProviderType(provider.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid provider: {provider}. Valid providers: github, gitlab, bitbucket"
        )


@router.get("/")
async def list_providers():
    """
    List all available Git providers and their configuration status.
    """
    return {
        "providers": GitProviderManager.list_available_providers()
    }


@router.get("/status")
async def get_all_provider_status(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get connection status for all Git providers.
    """
    credential_service = get_git_provider_credential_service()
    all_credentials = await credential_service.get_all_credentials(db, current_user.id)

    status_response = {}
    for provider in ["github", "gitlab", "bitbucket"]:
        if provider in all_credentials:
            status_response[provider] = {
                "connected": True,
                "provider_username": all_credentials[provider].get("provider_username"),
                "provider_email": all_credentials[provider].get("provider_email"),
                "scope": all_credentials[provider].get("scope")
            }
        else:
            status_response[provider] = {"connected": False}

    return status_response


@router.get("/{provider}/status")
async def get_provider_status(
    provider: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get connection status for a specific Git provider.
    """
    provider_type = validate_provider(provider)
    credential_service = get_git_provider_credential_service()

    has_creds = await credential_service.has_credential(db, current_user.id, provider_type)

    if not has_creds:
        return {"connected": False}

    credentials = await credential_service.get_credential(db, current_user.id, provider_type)

    return {
        "connected": True,
        "provider_username": credentials.get("provider_username"),
        "provider_email": credentials.get("provider_email"),
        "scope": credentials.get("scope")
    }


@router.get("/{provider}/oauth/authorize")
async def initiate_oauth(
    provider: str,
    scope: Optional[str] = None,
    current_user: User = Depends(current_active_user)
):
    """
    Initiate OAuth authorization flow for a Git provider.

    Returns a redirect URL for the frontend to navigate to the provider's authorization page.
    """
    provider_type = validate_provider(provider)
    oauth_service = get_oauth_service(provider)

    if not oauth_service.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider.title()} OAuth is not configured. Please contact support."
        )

    # Generate state for CSRF protection
    state = oauth_service.generate_state()

    # Store state with user info
    oauth_states[state] = {
        "user_id": current_user.id,
        "provider": provider,
        "timestamp": datetime.utcnow()
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

    logger.info(f"[GIT PROVIDERS] User {current_user.id} initiating {provider} OAuth flow")

    return {
        "authorization_url": auth_url,
        "state": state,
        "provider": provider
    }


@router.get("/{provider}/oauth/callback")
async def oauth_callback(
    provider: str,
    code: str = Query(..., description="Authorization code from provider"),
    state: str = Query(..., description="State parameter for CSRF protection"),
    db: AsyncSession = Depends(get_db)
):
    """
    Handle OAuth callback from Git provider.

    This endpoint is called by the provider after user authorizes the application.
    """
    provider_type = validate_provider(provider)

    # Validate state
    if state not in oauth_states:
        logger.error(f"[GIT PROVIDERS] Invalid OAuth state for {provider}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state. Please try connecting again."
        )

    state_data = oauth_states[state]

    # Verify provider matches
    if state_data["provider"] != provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider mismatch in OAuth callback"
        )

    user_id = state_data["user_id"]

    # Clean up used state
    del oauth_states[state]

    # Get OAuth service and exchange code for token
    oauth_service = get_oauth_service(provider)

    try:
        token_data = await oauth_service.exchange_code_for_token(code)
    except Exception as e:
        logger.error(f"[GIT PROVIDERS] Token exchange failed for {provider}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to obtain access token from {provider.title()}"
        )

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to obtain access token from {provider.title()}"
        )

    # Get user info from provider
    try:
        user_info = await oauth_service.get_user_info(access_token)
    except Exception as e:
        logger.error(f"[GIT PROVIDERS] Failed to get user info for {provider}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get user information from {provider.title()}"
        )

    # Get user email
    provider_email = None
    try:
        if provider == "github":
            provider_email = user_info.get("email")
            if not provider_email:
                emails = await oauth_service.get_user_emails(access_token)
                primary_email = next((e["email"] for e in emails if e.get("primary")), None)
                provider_email = primary_email or (emails[0]["email"] if emails else None)
        elif provider == "gitlab":
            provider_email = user_info.get("email")
        elif provider == "bitbucket":
            emails = await oauth_service.get_user_emails(access_token)
            primary_email = next((e["email"] for e in emails if e.get("is_primary")), None)
            provider_email = primary_email or (emails[0]["email"] if emails else None)
    except Exception as e:
        logger.warning(f"[GIT PROVIDERS] Could not fetch user emails for {provider}: {e}")

    # Extract username based on provider
    if provider == "github":
        provider_username = user_info.get("login")
        provider_user_id = str(user_info.get("id"))
    elif provider == "gitlab":
        provider_username = user_info.get("username")
        provider_user_id = str(user_info.get("id"))
    elif provider == "bitbucket":
        provider_username = user_info.get("username")
        provider_user_id = user_info.get("uuid")

    # Store credentials
    credential_service = get_git_provider_credential_service()
    await credential_service.store_credential(
        db=db,
        user_id=user_id,
        provider=provider_type,
        access_token=access_token,
        refresh_token=token_data.get("refresh_token"),
        expires_at=token_data.get("expires_at"),
        provider_username=provider_username,
        provider_email=provider_email,
        provider_user_id=provider_user_id,
        scope=token_data.get("scope", "")
    )

    logger.info(f"[GIT PROVIDERS] User {user_id} connected {provider} account: {provider_username}")

    return {
        "success": True,
        "provider": provider,
        "provider_username": provider_username,
        "provider_email": provider_email,
        "message": f"{provider.title()} account connected successfully"
    }


@router.delete("/{provider}/disconnect")
async def disconnect_provider(
    provider: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Disconnect a Git provider and revoke access token.
    """
    provider_type = validate_provider(provider)
    credential_service = get_git_provider_credential_service()

    # Get access token before deletion
    access_token = await credential_service.get_access_token(db, current_user.id, provider_type)

    if access_token:
        # Try to revoke token on provider's side
        oauth_service = get_oauth_service(provider)
        try:
            await oauth_service.revoke_token(access_token)
            logger.info(f"[GIT PROVIDERS] Revoked {provider} token for user {current_user.id}")
        except Exception as e:
            logger.warning(f"[GIT PROVIDERS] Failed to revoke {provider} token: {e}")

    # Delete credentials from database
    deleted = await credential_service.delete_credential(db, current_user.id, provider_type)

    if deleted:
        logger.info(f"[GIT PROVIDERS] User {current_user.id} disconnected {provider}")
        return {"message": f"{provider.title()} account disconnected successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {provider.title()} connection found"
        )


@router.get("/{provider}/repositories")
async def list_repositories(
    provider: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List repositories from a Git provider.
    """
    provider_type = validate_provider(provider)
    credential_service = get_git_provider_credential_service()

    # Get access token
    access_token = await credential_service.get_access_token(db, current_user.id, provider_type)

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{provider.title()} not connected. Please connect your {provider.title()} account first."
        )

    # Get provider client
    try:
        git_provider = GitProviderManager.get_provider(provider_type, access_token)
    except Exception as e:
        logger.error(f"[GIT PROVIDERS] Failed to create {provider} client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize {provider.title()} client"
        )

    # List repositories
    try:
        repos = await git_provider.list_repositories()

        # Convert to dict format for JSON response
        formatted_repos = [
            {
                "id": repo.id,
                "name": repo.name,
                "full_name": repo.full_name,
                "description": repo.description,
                "clone_url": repo.clone_url,
                "web_url": repo.web_url,
                "default_branch": repo.default_branch,
                "private": repo.private,
                "updated_at": repo.updated_at.isoformat() if repo.updated_at else None,
                "owner": repo.owner,
                "provider": repo.provider.value,
                "language": repo.language,
                "stars_count": repo.stars_count,
                "forks_count": repo.forks_count
            }
            for repo in repos
        ]

        return {"repositories": formatted_repos}

    except Exception as e:
        logger.error(f"[GIT PROVIDERS] Failed to list {provider} repositories: {e}")

        # Check if it's an auth error
        if "401" in str(e) or "unauthorized" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"{provider.title()} token expired or invalid. Please reconnect your account."
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch repositories from {provider.title()}"
        )


@router.get("/{provider}/repositories/{owner}/{repo}/branches")
async def list_repository_branches(
    provider: str,
    owner: str,
    repo: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List branches for a specific repository.
    """
    provider_type = validate_provider(provider)
    credential_service = get_git_provider_credential_service()

    # Get access token
    access_token = await credential_service.get_access_token(db, current_user.id, provider_type)

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{provider.title()} not connected. Please connect your {provider.title()} account first."
        )

    # Get provider client
    try:
        git_provider = GitProviderManager.get_provider(provider_type, access_token)
    except Exception as e:
        logger.error(f"[GIT PROVIDERS] Failed to create {provider} client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize {provider.title()} client"
        )

    # List branches
    try:
        branches = await git_provider.list_branches(owner, repo)

        formatted_branches = [
            {
                "name": branch.name,
                "is_default": branch.is_default,
                "commit_sha": branch.commit_sha,
                "protected": branch.protected
            }
            for branch in branches
        ]

        return {"branches": formatted_branches}

    except Exception as e:
        logger.error(f"[GIT PROVIDERS] Failed to list branches for {owner}/{repo}: {e}")

        if "404" in str(e) or "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository {owner}/{repo} not found"
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch branches from {provider.title()}"
        )


@router.get("/{provider}/repositories/{owner}/{repo}")
async def get_repository_info(
    provider: str,
    owner: str,
    repo: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get information about a specific repository.
    """
    provider_type = validate_provider(provider)
    credential_service = get_git_provider_credential_service()

    # Get access token
    access_token = await credential_service.get_access_token(db, current_user.id, provider_type)

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{provider.title()} not connected. Please connect your {provider.title()} account first."
        )

    # Get provider client
    try:
        git_provider = GitProviderManager.get_provider(provider_type, access_token)
    except Exception as e:
        logger.error(f"[GIT PROVIDERS] Failed to create {provider} client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize {provider.title()} client"
        )

    # Get repository info
    try:
        repo_info = await git_provider.get_repository(owner, repo)

        return {
            "id": repo_info.id,
            "name": repo_info.name,
            "full_name": repo_info.full_name,
            "description": repo_info.description,
            "clone_url": repo_info.clone_url,
            "web_url": repo_info.web_url,
            "default_branch": repo_info.default_branch,
            "private": repo_info.private,
            "updated_at": repo_info.updated_at.isoformat() if repo_info.updated_at else None,
            "owner": repo_info.owner,
            "provider": repo_info.provider.value
        }

    except Exception as e:
        logger.error(f"[GIT PROVIDERS] Failed to get repo info for {owner}/{repo}: {e}")

        if "404" in str(e) or "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository {owner}/{repo} not found"
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch repository information from {provider.title()}"
        )
