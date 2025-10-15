"""
GitHub integration router for authentication and repository management.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import httpx
import logging

from ..database import get_db
from ..models import User, Project, GitRepository
from ..schemas import (
    GitHubConnectRequest,
    GitHubCredentialResponse,
    GitRepositoryResponse,
    CreateGitHubRepoRequest
)
from ..services.credential_manager import get_credential_manager
from ..services.github_client import GitHubClient
from ..auth import get_current_active_user as get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github", tags=["github"])


@router.post("/connect", response_model=GitHubCredentialResponse)
async def connect_github_pat(
    request: GitHubConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Connect GitHub account using a Personal Access Token.

    This endpoint allows users to authenticate with GitHub using a PAT.
    The token will be securely encrypted and stored.
    """
    try:
        # Validate token by attempting to get user info
        github_client = GitHubClient(request.pat_token)

        try:
            user_info = await github_client.get_user_info()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid GitHub token. Please check your PAT and try again."
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to validate GitHub token: {str(e)}"
            )

        # Get user email
        github_email = user_info.get('email')
        if not github_email:
            try:
                emails = await github_client.get_user_emails()
                primary_email = next((e['email'] for e in emails if e.get('primary')), None)
                github_email = primary_email or (emails[0]['email'] if emails else None)
                logger.info(f"[GITHUB] Retrieved {len(emails)} email addresses for user {user_info.get('login')}")
            except httpx.HTTPStatusError as e:
                logger.warning(f"[GITHUB] Could not fetch user emails (status {e.response.status_code}): Token may lack 'user:email' scope")
            except Exception as e:
                logger.warning(f"[GITHUB] Failed to fetch user emails: {e}")

        # Store credentials
        credential_manager = get_credential_manager()
        await credential_manager.store_pat(
            db=db,
            user_id=current_user.id,
            pat_token=request.pat_token,
            github_username=user_info.get('login'),
            github_email=github_email
        )

        logger.info(f"[GITHUB] User {current_user.id} connected GitHub account: {user_info.get('login')}")

        return GitHubCredentialResponse(
            connected=True,
            github_username=user_info.get('login'),
            github_email=github_email,
            auth_method="pat"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GITHUB] Failed to connect GitHub: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect GitHub account: {str(e)}"
        )


@router.get("/status", response_model=GitHubCredentialResponse)
async def get_github_status(
    current_user: User = Depends(get_current_user),
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
            github_username=credentials.get('github_username'),
            github_email=credentials.get('github_email'),
            auth_method='oauth' if credentials.get('access_token') else 'pat'
        )

    except Exception as e:
        logger.error(f"[GITHUB] Failed to get status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get GitHub status: {str(e)}"
        )


@router.delete("/disconnect")
async def disconnect_github(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Disconnect GitHub account and remove stored credentials.
    """
    try:
        credential_manager = get_credential_manager()
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
    current_user: User = Depends(get_current_user),
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
                    "name": repo['name'],
                    "full_name": repo['full_name'],
                    "description": repo.get('description'),
                    "url": repo['html_url'],
                    "clone_url": repo['clone_url'],
                    "default_branch": repo.get('default_branch', 'main'),
                    "private": repo.get('private', False),
                    "updated_at": repo.get('updated_at')
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
    current_user: User = Depends(get_current_user),
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
                "name": repo['name'],
                "full_name": repo['full_name'],
                "url": repo['html_url'],
                "clone_url": repo['clone_url'],
                "default_branch": repo.get('default_branch', 'main')
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
    current_user: User = Depends(get_current_user),
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
                    "name": branch['name'],
                    "protected": branch.get('protected', False)
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
