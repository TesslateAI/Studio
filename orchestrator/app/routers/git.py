"""
Git operations router for project version control.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import logging

from ..database import get_db
from ..models import User, Project, GitRepository
from ..schemas import (
    GitCloneRequest,
    GitInitRequest,
    GitCommitRequest,
    GitPushRequest,
    GitPullRequest,
    GitBranchRequest,
    GitSwitchBranchRequest,
    GitStatusResponse,
    GitCommitResponse,
    GitPushResponse,
    GitPullResponse,
    GitHistoryResponse,
    GitBranchesResponse,
    GitRepositoryResponse,
    GitCommitInfo,
    GitBranchInfo
)
from ..services.git_manager import GitManager
from ..services.credential_manager import get_credential_manager
from ..services.github_client import GitHubClient
from ..users import current_active_user, current_superuser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/git", tags=["git"])


async def verify_project_access(
    project_id: UUID,
    current_user: User,
    db: AsyncSession
) -> Project:
    """Verify that the user has access to the project."""
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
            detail="Project not found"
        )

    return project


@router.post("/init")
async def initialize_repository(
    project_id: str,
    request: GitInitRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Initialize a Git repository in the project.
    """
    try:
        # Verify project access
        project = await verify_project_access(project_id, current_user, db)

        # Initialize Git repository
        git_manager = GitManager(current_user.id, str(project_id))
        await git_manager.initialize_repository(
            remote_url=request.remote_url,
            default_branch=request.default_branch
        )

        # Update project
        project.has_git_repo = True
        project.git_remote_url = request.remote_url

        # Create git_repository record if remote URL is provided
        if request.remote_url:
            # Parse repository info from URL
            repo_info = GitHubClient.parse_repo_url(request.remote_url)

            git_repo = GitRepository(
                project_id=project_id,
                user_id=current_user.id,
                repo_url=request.remote_url,
                repo_name=repo_info['repo'] if repo_info else None,
                repo_owner=repo_info['owner'] if repo_info else None,
                default_branch=request.default_branch,
                auth_method='oauth'
            )
            db.add(git_repo)

        await db.commit()

        logger.info(f"[GIT] Initialized repository for project {project_id}")
        return {"message": "Git repository initialized successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to initialize repository: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize repository: {str(e)}"
        )


@router.post("/clone")
async def clone_repository(
    project_id: str,
    request: GitCloneRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Clone a GitHub repository into the project.

    This will replace existing project files with the repository contents.
    """
    try:
        # Verify project access
        project = await verify_project_access(project_id, current_user, db)

        # Get GitHub access token
        credential_manager = get_credential_manager()
        access_token = await credential_manager.get_access_token(db, current_user.id)

        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="GitHub not connected. Please connect your GitHub account first."
            )

        # Parse repository info
        repo_info = GitHubClient.parse_repo_url(request.repo_url)
        if not repo_info:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid GitHub repository URL"
            )

        # Get default branch if not specified
        branch = request.branch
        if not branch:
            github_client = GitHubClient(access_token)
            try:
                branch = await github_client.get_default_branch(repo_info['owner'], repo_info['repo'])
            except:
                branch = "main"  # Fallback

        # Clone repository
        git_manager = GitManager(current_user.id, str(project_id))
        await git_manager.clone_repository(
            repo_url=request.repo_url,
            branch=branch,
            auth_token=access_token
        )

        # Update project
        project.has_git_repo = True
        project.git_remote_url = request.repo_url

        # Create or update git_repository record
        result = await db.execute(
            select(GitRepository).where(GitRepository.project_id == project_id)
        )
        git_repo = result.scalar_one_or_none()

        if git_repo:
            git_repo.repo_url = request.repo_url
            git_repo.repo_name = repo_info['repo']
            git_repo.repo_owner = repo_info['owner']
            git_repo.default_branch = branch
        else:
            git_repo = GitRepository(
                project_id=project_id,
                user_id=current_user.id,
                repo_url=request.repo_url,
                repo_name=repo_info['repo'],
                repo_owner=repo_info['owner'],
                default_branch=branch,
                auth_method='oauth'
            )
            db.add(git_repo)

        await db.commit()

        logger.info(f"[GIT] Cloned repository {request.repo_url} into project {project_id}")
        return {
            "message": "Repository cloned successfully",
            "branch": branch,
            "repo_name": repo_info['repo']
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to clone repository: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clone repository: {str(e)}"
        )


@router.get("/status", response_model=GitStatusResponse)
async def get_git_status(
    project_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the current Git status of the project.
    """
    try:
        # Verify project access
        await verify_project_access(project_id, current_user, db)

        # Check if repository exists
        result = await db.execute(
            select(GitRepository).where(GitRepository.project_id == project_id)
        )
        git_repo = result.scalar_one_or_none()

        if not git_repo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No Git repository connected to this project"
            )

        # Get Git status
        git_manager = GitManager(current_user.id, str(project_id))
        git_status = await git_manager.get_status()

        return GitStatusResponse(**git_status)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to get status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get Git status: {str(e)}"
        )


@router.post("/commit", response_model=GitCommitResponse)
async def create_commit(
    project_id: str,
    request: GitCommitRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new commit with the specified changes.
    """
    try:
        # Verify project access
        await verify_project_access(project_id, current_user, db)

        # Create commit
        git_manager = GitManager(current_user.id, str(project_id))
        commit_sha = await git_manager.commit(
            message=request.message,
            files=request.files
        )

        # Update git_repository record
        result = await db.execute(
            select(GitRepository).where(GitRepository.project_id == project_id)
        )
        git_repo = result.scalar_one_or_none()

        if git_repo:
            git_repo.last_commit_sha = commit_sha
            await db.commit()

        logger.info(f"[GIT] Created commit in project {project_id}: {commit_sha[:8]}")
        return GitCommitResponse(sha=commit_sha, message=request.message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to create commit: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create commit: {str(e)}"
        )


@router.post("/push", response_model=GitPushResponse)
async def push_commits(
    project_id: str,
    request: GitPushRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Push commits to the remote repository.
    """
    try:
        # Verify project access
        await verify_project_access(project_id, current_user, db)

        # Push commits
        git_manager = GitManager(current_user.id, str(project_id))
        success = await git_manager.push(
            branch=request.branch,
            remote=request.remote,
            force=request.force
        )

        # Update git_repository record
        result = await db.execute(
            select(GitRepository).where(GitRepository.project_id == project_id)
        )
        git_repo = result.scalar_one_or_none()

        if git_repo:
            from datetime import datetime
            git_repo.last_sync_at = datetime.utcnow()
            git_repo.sync_status = 'synced'
            await db.commit()

        logger.info(f"[GIT] Pushed commits from project {project_id}")
        return GitPushResponse(
            success=success,
            message="Commits pushed successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to push: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to push commits: {str(e)}"
        )


@router.post("/pull", response_model=GitPullResponse)
async def pull_changes(
    project_id: str,
    request: GitPullRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Pull changes from the remote repository.
    """
    try:
        # Verify project access
        await verify_project_access(project_id, current_user, db)

        # Pull changes
        git_manager = GitManager(current_user.id, str(project_id))
        result = await git_manager.pull(
            branch=request.branch,
            remote=request.remote
        )

        # Update git_repository record
        db_result = await db.execute(
            select(GitRepository).where(GitRepository.project_id == project_id)
        )
        git_repo = db_result.scalar_one_or_none()

        if git_repo:
            from datetime import datetime
            git_repo.last_sync_at = datetime.utcnow()
            git_repo.sync_status = 'synced' if result['success'] else 'conflict'
            await db.commit()

        logger.info(f"[GIT] Pulled changes into project {project_id}")
        return GitPullResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to pull: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pull changes: {str(e)}"
        )


@router.get("/commits", response_model=GitHistoryResponse)
async def get_commit_history(
    project_id: str,
    limit: int = 50,
    branch: Optional[str] = None,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get commit history for the project.
    """
    try:
        # Verify project access
        await verify_project_access(project_id, current_user, db)

        # Get commit history
        git_manager = GitManager(current_user.id, str(project_id))
        commits = await git_manager.get_commit_history(limit=limit, branch=branch)

        return GitHistoryResponse(
            commits=[GitCommitInfo(**commit) for commit in commits]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to get commit history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get commit history: {str(e)}"
        )


@router.get("/branches", response_model=GitBranchesResponse)
async def list_branches(
    project_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all branches in the project.
    """
    try:
        # Verify project access
        await verify_project_access(project_id, current_user, db)

        # List branches
        git_manager = GitManager(current_user.id, str(project_id))
        branches = await git_manager.list_branches()

        current_branch = next((b['name'] for b in branches if b['current']), None)

        return GitBranchesResponse(
            branches=[GitBranchInfo(**branch) for branch in branches],
            current_branch=current_branch
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to list branches: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list branches: {str(e)}"
        )


@router.post("/branches")
async def create_branch(
    project_id: str,
    request: GitBranchRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new branch in the project.
    """
    try:
        # Verify project access
        await verify_project_access(project_id, current_user, db)

        # Create branch
        git_manager = GitManager(current_user.id, str(project_id))
        success = await git_manager.create_branch(
            name=request.name,
            checkout=request.checkout
        )

        logger.info(f"[GIT] Created branch '{request.name}' in project {project_id}")
        return {
            "message": f"Branch '{request.name}' created successfully",
            "checked_out": request.checkout
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to create branch: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create branch: {str(e)}"
        )


@router.put("/branches/switch")
async def switch_branch(
    project_id: str,
    request: GitSwitchBranchRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Switch to a different branch.
    """
    try:
        # Verify project access
        await verify_project_access(project_id, current_user, db)

        # Switch branch
        git_manager = GitManager(current_user.id, str(project_id))
        success = await git_manager.switch_branch(name=request.name)

        logger.info(f"[GIT] Switched to branch '{request.name}' in project {project_id}")
        return {"message": f"Switched to branch '{request.name}' successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to switch branch: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to switch branch: {str(e)}"
        )


@router.get("/info", response_model=Optional[GitRepositoryResponse])
async def get_repository_info(
    project_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get Git repository information for the project.
    """
    try:
        # Verify project access
        await verify_project_access(project_id, current_user, db)

        # Get repository info
        result = await db.execute(
            select(GitRepository).where(GitRepository.project_id == project_id)
        )
        git_repo = result.scalar_one_or_none()

        if not git_repo:
            return None

        return GitRepositoryResponse.from_orm(git_repo)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to get repository info: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get repository info: {str(e)}"
        )


@router.delete("/disconnect")
async def disconnect_repository(
    project_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Disconnect the project from its Git repository.

    This removes the Git repository connection but preserves local Git history.
    """
    try:
        # Verify project access
        project = await verify_project_access(project_id, current_user, db)

        # Delete git_repository record
        result = await db.execute(
            select(GitRepository).where(GitRepository.project_id == project_id)
        )
        git_repo = result.scalar_one_or_none()

        if git_repo:
            await db.delete(git_repo)

        # Update project
        project.has_git_repo = False
        project.git_remote_url = None

        await db.commit()

        logger.info(f"[GIT] Disconnected repository from project {project_id}")
        return {"message": "Repository disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GIT] Failed to disconnect repository: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect repository: {str(e)}"
        )
