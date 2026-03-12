import asyncio
import builtins
import contextlib
import json
import logging
import mimetypes
import os
import re
import shlex
import shutil
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from ..config import get_settings
from ..database import get_db
from ..models import (
    BrowserPreview,
    Chat,
    Container,
    ContainerConnection,
    DeploymentCredential,
    MarketplaceBase,
    Project,
    ProjectAsset,
    ProjectAssetDirectory,
    ProjectFile,
    User,
    UserPurchasedBase,
)
from ..schemas import BrowserPreview as BrowserPreviewSchema
from ..schemas import (
    BrowserPreviewCreate,
    BrowserPreviewUpdate,
    ContainerConnectionCreate,
    ContainerCreate,
    ContainerCredentialUpdate,
    ContainerRename,
    ContainerUpdate,
    DeploymentTargetAssignment,
    DirectoryCreateRequest,
    FileDeleteRequest,
    FileRenameRequest,
    ProjectCreate,
    TemplateExportRequest,
    TesslateConfigCreate,
    TesslateConfigResponse,
    SetupConfigSyncResponse,
    AppConfigSchema,
    InfraConfigSchema,
)
from ..schemas import Container as ContainerSchema
from ..schemas import ContainerConnection as ContainerConnectionSchema
from ..schemas import Project as ProjectSchema
from ..schemas import ProjectFile as ProjectFileSchema
from ..services.secret_codec import decode_secret_map, encode_secret_map
from ..services.secret_manager_env import build_env_overrides, get_injected_env_vars_for_container
from ..services.service_definitions import get_service
from ..services.task_manager import Task, get_task_manager
from ..users import current_active_user, current_optional_user, current_superuser
from ..utils.async_fileio import makedirs_async, read_file_async, walk_directory_async
from ..utils.resource_naming import get_project_path
from ..utils.slug_generator import generate_project_slug
from .chat import manager as ws_manager

logger = logging.getLogger(__name__)

router = APIRouter()


async def _validate_git_repo_accessible(
    repo_url: str,
    *,
    timeout: int = 15,
    auth_token: str | None = None,
) -> None:
    """
    Validate that a git repository URL is reachable before cloning.

    Uses ``git ls-remote`` with a short timeout.  Raises ``RuntimeError``
    with a user-friendly message when the repo cannot be reached.

    Args:
        repo_url: The HTTPS clone URL to check.
        timeout: Seconds before giving up.
        auth_token: Optional token injected into the URL for private repos.
    """
    check_url = repo_url
    if auth_token and check_url.startswith("https://"):
        # Inject token for authenticated ls-remote (same pattern git clone uses)
        check_url = check_url.replace("https://", f"https://x-access-token:{auth_token}@", 1)

    cmd = ["git", "ls-remote", "--exit-code", "--heads", check_url]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

        if process.returncode != 0:
            err_text = stderr.decode(errors="replace").strip() if stderr else ""
            # Sanitise the error — never leak tokens into user-facing messages
            if auth_token and auth_token in err_text:
                err_text = err_text.replace(auth_token, "***")
            raise RuntimeError(
                f"Repository is not accessible: {repo_url}. "
                f"Please check that the URL is correct and the repository is public "
                f"(or that you have connected the right account for private repos). "
                f"Git error: {err_text}"
            )
    except TimeoutError:
        raise RuntimeError(
            f"Repository check timed out after {timeout}s for {repo_url}. "
            f"The remote server may be unreachable."
        ) from None


async def _check_repo_size_limit(
    *,
    provider_type,
    provider_class,
    owner: str,
    repo: str,
    access_token: str | None,
    max_size_kb: int,
) -> None:
    """
    Best-effort check that a repository does not exceed the size limit before cloning.

    Uses the git provider API to query the repository size.  If the provider
    doesn't report size reliably (e.g. GitLab returns 0) or the API call fails,
    the check is silently skipped so the clone can proceed normally.

    Args:
        provider_type: GitProviderType enum value.
        provider_class: The provider class (e.g. GitHubProvider).
        owner: Repository owner / namespace.
        repo: Repository name.
        access_token: OAuth token (may be None for public repos).
        max_size_kb: Maximum allowed size in kilobytes.

    Raises:
        HTTPException (400): If the repo size exceeds the limit.
    """
    from ..services.git_providers.base import GitProviderType

    try:
        repo_size_kb = 0

        if access_token:
            # Use the existing provider infrastructure for authenticated requests
            provider_instance = provider_class(access_token)
            repo_data = await provider_instance.get_repository(owner, repo)
            repo_size_kb = repo_data.size
        else:
            # Unauthenticated fallback for public repos (GitHub only)
            if provider_type == GitProviderType.GITHUB:
                import httpx

                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"https://api.github.com/repos/{owner}/{repo}",
                        headers={"Accept": "application/vnd.github.v3+json"},
                    )
                    if resp.status_code == 200:
                        repo_size_kb = resp.json().get("size", 0)

        # Skip enforcement when the provider doesn't report size (e.g. GitLab returns 0)
        if repo_size_kb <= 0:
            return

        max_size_mb = max_size_kb / 1024
        repo_size_mb = repo_size_kb / 1024

        if repo_size_kb > max_size_kb:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Repository exceeds {max_size_mb / 1024:.0f} GB size limit. "
                    f"The repository is approximately {repo_size_mb:.0f} MB. "
                    f"Please use a smaller repository or remove large files with git history rewriting."
                ),
            )

        logger.info(
            f"[CREATE] Repository size check passed: {owner}/{repo} is ~{repo_size_mb:.0f} MB "
            f"(limit: {max_size_mb:.0f} MB)"
        )

    except HTTPException:
        # Re-raise size limit errors
        raise
    except Exception as e:
        # Best-effort: log and continue if the size check fails for any reason
        logger.warning(f"[CREATE] Could not check repository size for {owner}/{repo}: {e}")


async def get_project_by_slug(db: AsyncSession, project_slug: str, user_id: UUID) -> Project:
    """
    Get a project by its slug or numeric ID and verify ownership.

    Args:
        db: Database session
        project_slug: Project slug (e.g., "my-awesome-app-k3x8n2") or numeric ID as string (e.g., "4")
        user_id: User ID to verify ownership

    Returns:
        Project object if found and owned by user

    Raises:
        HTTPException 404 if project not found
        HTTPException 403 if user doesn't own the project
    """
    # Try to parse as UUID first (for direct ID access)
    try:
        from uuid import UUID

        project_id = UUID(project_slug)
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
    except ValueError:
        # Not a UUID, treat as slug (recommended for URLs)
        result = await db.execute(select(Project).where(Project.slug == project_slug))
        project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this project")

    return project


@router.get("/", response_model=list[ProjectSchema])
async def get_projects(
    current_user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Project).where(Project.owner_id == current_user.id))
    projects = result.scalars().all()
    return projects


async def enforce_project_limit(user: User, db: AsyncSession) -> None:
    """Raise 403 if user has reached their tier's project limit."""
    settings = get_settings()
    result = await db.execute(select(func.count(Project.id)).where(Project.owner_id == user.id))
    current_count = result.scalar()
    tier = user.subscription_tier or "free"
    max_projects = settings.get_tier_max_projects(tier)
    if current_count >= max_projects:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Project limit reached. Your {tier} tier allows {max_projects} project(s). Upgrade to create more projects.",
        )


async def _perform_project_setup(
    project_data: ProjectCreate,
    db_project_id: UUID,
    db_project_slug: str,
    user_id: UUID,
    settings,
    task: Task,
) -> None:
    """
    Background worker function that performs project setup operations.

    Args:
        project_data: Original project creation request
        db_project_id: Database project ID (already created)
        db_project_slug: Database project slug
        user_id: User ID
        settings: Application settings
        task: Task object for progress tracking
    """
    from ..database import AsyncSessionLocal

    # Create a new database session for this background task
    async with AsyncSessionLocal() as db:
        try:
            # Fetch the project from DB
            from sqlalchemy import select

            result = await db.execute(select(Project).where(Project.id == db_project_id))
            db_project = result.scalar_one()

            project_path = os.path.abspath(get_project_path(user_id, db_project.id))

            # Docker volume mode setting (currently unused)
            # use_docker_volumes = os.getenv('USE_DOCKER_VOLUMES', 'true').lower() == 'true'

            # Step 1: Create directory (5%)
            task.update_progress(5, 100, "Creating project directory")
            if settings.deployment_mode == "docker":
                try:
                    await makedirs_async(project_path)
                    logger.info(f"[CREATE] Created project directory: {project_path}")
                except Exception as e:
                    logger.warning(f"[CREATE] mkdir failed: {e}, trying subprocess")
                    import subprocess

                    await asyncio.to_thread(
                        subprocess.run,
                        ["mkdir", "-p", project_path],
                        check=False,
                        capture_output=True,
                    )
                await asyncio.sleep(0.1)

            # Handle different source types
            container_id = None
            if project_data.source_type in ("github", "gitlab", "bitbucket"):
                container_id = await _setup_git_provider_project(
                    project_data, db_project, user_id, settings, db, task, project_path
                )
            elif project_data.source_type == "base":
                container_id = await _setup_base_project(
                    project_data, db_project, user_id, settings, db, task, project_path
                )
            else:
                raise ValueError(
                    f"Invalid source_type: {project_data.source_type}. Must be 'base', 'github', 'gitlab', or 'bitbucket'."
                )

            # Final step: Complete
            task.update_progress(100, 100, "Project setup complete")
            logger.info(f"[CREATE] Project {db_project.id} setup completed successfully")

            # Return result with container_id for navigation
            return {"slug": db_project_slug, "container_id": container_id}

        except Exception as e:
            logger.error(f"[CREATE] Background task error: {e}", exc_info=True)
            raise


async def _setup_git_provider_project(
    project_data: ProjectCreate,
    db_project: Project,
    user_id: UUID,
    settings,
    db: AsyncSession,
    task: Task,
    project_path: str,
) -> str | None:
    """
    Unified setup for projects imported from GitHub, GitLab, or Bitbucket.

    Uses the git_providers infrastructure for a consistent experience across all providers.

    In K8s mode: Creates project environment (namespace + PVC + file-manager pod) and
    clones directly into the PVC. Files are never stored in the database.

    In Docker mode: Clones directly to the project filesystem path.

    Returns:
        Container ID string if container was created, None otherwise.
    """
    from ..services.git_providers import (
        GitProviderType,
        get_git_provider_manager,
    )
    from ..services.git_providers.credential_service import get_git_provider_credential_service

    # Determine provider and repo URL
    provider_name = project_data.source_type  # 'github', 'gitlab', 'bitbucket'

    # Support both new unified fields and legacy github-specific fields
    repo_url = project_data.git_repo_url or project_data.github_repo_url
    branch = project_data.git_branch or project_data.github_branch or "main"

    if not repo_url:
        raise ValueError(f"No repository URL provided for {provider_name} import")

    provider_type = GitProviderType(provider_name)
    provider_manager = get_git_provider_manager()

    # Step 1: Get credentials and parse URL
    task.update_progress(10, 100, f"Preparing to import from {provider_name.title()}")
    logger.info(f"[CREATE] Importing from {provider_name}: {repo_url}")

    # Get credentials for this provider
    credential_service = get_git_provider_credential_service()
    access_token = await credential_service.get_access_token(db, user_id, provider_type)

    # Parse repository URL to extract owner/repo info (use class, not instance)
    provider_class = provider_manager.get_provider_class(provider_type)
    repo_info = provider_class.parse_repo_url(repo_url)
    if not repo_info:
        raise ValueError(f"Invalid {provider_name} repository URL: {repo_url}")

    # Get default branch if not specified and we have credentials
    if not project_data.git_branch and not project_data.github_branch and access_token:
        try:
            provider_instance = provider_class(access_token)
            branch = await provider_instance.get_default_branch(
                repo_info["owner"], repo_info["repo"]
            )
            logger.info(f"[CREATE] Using default branch: {branch}")
        except Exception as e:
            logger.warning(f"[CREATE] Could not fetch default branch, using 'main': {e}")

    # Format clone URL with authentication if available
    authenticated_url = provider_class.format_clone_url(
        repo_info["owner"], repo_info["repo"], access_token
    )

    # Validate that the repository is accessible before allocating resources
    task.update_progress(15, 100, "Validating repository access...")
    await _validate_git_repo_accessible(authenticated_url, auth_token=access_token)
    logger.info(f"[CREATE] Repository validated: {repo_url}")

    # Check repository size before cloning (best-effort, non-blocking on failure)
    MAX_REPO_SIZE_KB = 1_000_000  # 1 GB in KB
    await _check_repo_size_limit(
        provider_type=provider_type,
        provider_class=provider_class,
        owner=repo_info["owner"],
        repo=repo_info["repo"],
        access_token=access_token,
        max_size_kb=MAX_REPO_SIZE_KB,
    )

    # Framework detection defaults (updated after clone based on package.json)
    framework_name = "unknown"
    framework_port = 5173  # default fallback

    # ==========================================================================
    # K8s Mode: Create environment and clone directly to PVC
    # ==========================================================================
    if settings.deployment_mode != "docker":
        from ..services.orchestration import get_orchestrator
        from ..services.orchestration.kubernetes.helpers import generate_git_clone_script

        orchestrator = get_orchestrator()

        # Step 2: Create K8s environment (namespace + PVC + file-manager pod)
        task.update_progress(20, 100, "Creating project environment...")
        logger.info(f"[CREATE] K8s mode: Creating environment for project {db_project.id}")

        namespace = await orchestrator.ensure_project_environment(
            project_id=db_project.id, user_id=user_id
        )
        logger.info(f"[CREATE] K8s environment created: {namespace}")

        # Step 3: Wait for file-manager pod to be ready
        task.update_progress(30, 100, "Waiting for project environment...")
        pod_name = None
        for attempt in range(20):  # Up to 60 seconds
            pod_name = await orchestrator.k8s_client.get_file_manager_pod(namespace)
            if pod_name:
                break
            logger.info(f"[CREATE] Waiting for file-manager pod... (attempt {attempt + 1}/20)")
            await asyncio.sleep(3)

        if not pod_name:
            raise RuntimeError("File manager pod not ready after 60 seconds")

        logger.info(f"[CREATE] File-manager pod ready: {pod_name}")

        # Step 4: Clone directly into PVC via file-manager pod
        task.update_progress(40, 100, f"Cloning repository from {provider_name.title()}...")

        # Generate clone script - clone to /app (root of PVC)
        clone_script = generate_git_clone_script(
            git_url=authenticated_url,
            branch=branch,
            target_dir="/app",
            install_deps=False,  # Don't install deps during import - user can do this when they start container
        )

        logger.info("[CREATE] Executing git clone in file-manager pod...")
        result = await asyncio.to_thread(
            orchestrator.k8s_client._exec_in_pod,
            pod_name,
            namespace,
            "file-manager",
            ["/bin/sh", "-c", clone_script],
            timeout=300,  # 5 minutes for large repos
        )

        logger.info("[CREATE] Git clone completed in PVC")
        logger.debug(f"[CREATE] Clone output: {result[:500] if result else 'None'}...")
        task.update_progress(70, 100, "Repository cloned to project storage")

        # Step 5: Auto-patch project (run patch script in pod)
        task.update_progress(80, 100, "Patching project for Tesslate compatibility...")
        # TODO: Run patcher inside pod if needed - for now skip since basic Next.js should work
        logger.info("[CREATE] Skipping auto-patch in K8s mode (TODO: implement in-pod patching)")

        task.update_progress(90, 100, "Project files ready")

    # ==========================================================================
    # Docker Mode: Clone directly to filesystem
    # ==========================================================================
    else:
        from ..services.project_patcher import ProjectPatcher

        # Step 2: Clone repository
        task.update_progress(20, 100, f"Cloning repository from {provider_name.title()}...")

        git_cmd = ["git", "clone"]
        if branch:
            git_cmd.extend(["--branch", branch])
        git_cmd.extend([authenticated_url, project_path])

        logger.info(f"[CREATE] Executing git clone to: {project_path}")
        process = await asyncio.create_subprocess_exec(
            *git_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Git clone failed: {error_msg}")

        logger.info(f"[CREATE] Repository cloned successfully to {project_path}")
        task.update_progress(60, 100, "Repository cloned successfully")

        # Step 3: Auto-patch project
        task.update_progress(70, 100, "Patching project for Tesslate compatibility")
        try:
            patcher = ProjectPatcher(project_path)
            await patcher.auto_patch()
        except Exception as patch_error:
            logger.warning(f"[CREATE] Auto-patch error: {patch_error}")

        task.update_progress(90, 100, "Project setup complete")

    # Update project with Git info
    db_project.has_git_repo = True
    db_project.git_remote_url = repo_url

    from ..models import GitRepository

    git_repo = GitRepository(
        project_id=db_project.id,
        user_id=user_id,
        repo_url=repo_url,
        repo_name=repo_info["repo"],
        repo_owner=repo_info["owner"],
        default_branch=branch,
        auth_method="pat" if access_token else "none",
    )
    db.add(git_repo)
    await db.commit()

    # Check for .tesslate/config.json in the cloned repo
    task.update_progress(90, 100, "Checking for project configuration...")

    from ..services.base_config_parser import read_tesslate_config

    config = None
    if settings.deployment_mode == "docker":
        config = read_tesslate_config(project_path)
    else:
        # K8s: try reading from PVC
        try:
            from ..services.orchestration import get_orchestrator as _get_orch
            orch = _get_orch()
            config_content = await orch.read_file(
                user_id=user_id,
                project_id=db_project.id,
                container_name=None,
                file_path=".tesslate/config.json",
                project_slug=db_project.slug,
            )
            if config_content:
                from ..services.base_config_parser import parse_tesslate_config
                config = parse_tesslate_config(config_content)
        except Exception as e:
            logger.debug(f"[CREATE] Could not read .tesslate/config.json from PVC: {e}")

    if config and config.apps:
        # Config exists - create containers from it
        task.update_progress(95, 100, "Creating containers from config")
        primary_container_id = None

        for app_name, app_config in config.apps.items():
            container = Container(
                project_id=db_project.id,
                base_id=None,
                name=app_name,
                directory=app_config.directory,
                container_name=f"{db_project.slug}-{app_name}",
                internal_port=app_config.port or 3000,
                environment_vars=app_config.env or {},
                container_type="base",
                status="stopped",
                position_x=app_config.x or 200,
                position_y=app_config.y or 200,
            )
            db.add(container)
            await db.flush()
            await db.refresh(container)
            logger.info(f"[CREATE] Created container {container.id} for app '{app_name}'")
            if app_name == config.primaryApp:
                primary_container_id = str(container.id)

        for infra_name, infra_config in config.infrastructure.items():
            container = Container(
                project_id=db_project.id,
                name=infra_name,
                directory=".",
                container_name=f"{db_project.slug}-{infra_name}",
                internal_port=infra_config.port,
                container_type="service",
                service_slug=infra_name,
                status="stopped",
                position_x=infra_config.x or 400,
                position_y=infra_config.y or 400,
            )
            db.add(container)

        await db.commit()
        return primary_container_id or str(container.id)
    else:
        # No config found - mark as needs_setup, DON'T create container
        task.update_progress(95, 100, "Project imported - setup needed")
        logger.info(f"[CREATE] No .tesslate/config.json found, project needs setup")
        return "needs_setup"


async def _setup_github_project(
    project_data: ProjectCreate,
    db_project: Project,
    user_id: UUID,
    settings,
    db: AsyncSession,
    task: Task,
    project_path: str,
) -> None:
    """
    Setup project from GitHub repository.

    DEPRECATED: This function is kept for backward compatibility.
    New code should use _setup_git_provider_project which handles all providers.
    """
    import shutil
    import tempfile

    # Step 2: Clone repository (10-40%)
    task.update_progress(10, 100, f"Cloning repository from GitHub: {project_data.github_repo_url}")
    logger.info(f"[CREATE] Importing from GitHub: {project_data.github_repo_url}")

    # Get GitHub credentials
    from ..services.credential_manager import get_credential_manager

    credential_manager = get_credential_manager()
    access_token = await credential_manager.get_access_token(db, user_id)

    # Clone repository
    from ..services.github_client import GitHubClient
    from ..services.project_patcher import ProjectPatcher

    repo_info = GitHubClient.parse_repo_url(project_data.github_repo_url)
    if not repo_info:
        raise ValueError("Invalid GitHub repository URL")

    # Get default branch
    branch = project_data.github_branch or "main"
    if not project_data.github_branch and access_token:
        try:
            github_client = GitHubClient(access_token)
            branch = await github_client.get_default_branch(repo_info["owner"], repo_info["repo"])
        except Exception:
            pass

    # For both Docker and K8s mode, clone to filesystem first
    # Docker mode: clone to final project_path
    # K8s mode: clone to temp directory, then save to database
    if settings.deployment_mode == "docker":
        clone_path = project_path
    else:
        # K8s mode: use temp directory
        clone_path = tempfile.mkdtemp(prefix=f"tesslate-github-{db_project.id}-")
        logger.info(f"[CREATE] K8s mode: cloning to temp directory: {clone_path}")

    try:
        # Clone directly to filesystem
        repo_url = project_data.github_repo_url
        if access_token and "github.com" in repo_url:
            if repo_url.startswith("git@github.com:"):
                repo_url = repo_url.replace("git@github.com:", "https://github.com/")
            repo_url = repo_url.replace(
                "https://github.com/", f"https://{access_token}@github.com/"
            )

        # Build git clone command
        git_cmd = ["git", "clone"]
        if branch:
            git_cmd.extend(["--branch", branch])
        git_cmd.extend([repo_url, clone_path])

        logger.info(f"[CREATE] Executing git clone to: {clone_path}")
        process = await asyncio.create_subprocess_exec(
            *git_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Git clone failed: {error_msg}")

        logger.info(f"[CREATE] Repository cloned successfully to {clone_path}")
        task.update_progress(40, 100, "Repository cloned successfully")

        # Step 3: Auto-patch project (40-60%)
        task.update_progress(50, 100, "Patching project for Tesslate compatibility")
        try:
            patcher = ProjectPatcher(clone_path)
            await patcher.auto_patch()
        except Exception as patch_error:
            logger.warning(f"[CREATE] Auto-patch error: {patch_error}")

        task.update_progress(60, 100, "Patching complete")

        # Step 4: Save files to database (60-90%)
        task.update_progress(65, 100, "Saving cloned files to database")
        files_saved = 0
        walk_results = await walk_directory_async(
            clone_path, exclude_dirs=["node_modules", ".git", "dist", "build", ".next"]
        )

        for root, _dirs, files in walk_results:
            for file in files:
                if file.startswith(".") or file.endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico")
                ):
                    continue

                file_full_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_full_path, clone_path).replace("\\", "/")

                try:
                    content = await read_file_async(file_full_path)
                    db_file = ProjectFile(
                        project_id=db_project.id, file_path=relative_path, content=content
                    )
                    db.add(db_file)
                    files_saved += 1
                except Exception as e:
                    logger.warning(f"[CREATE] Could not read file {relative_path}: {e}")

        await db.commit()
        task.update_progress(90, 100, f"Saved {files_saved} files to database")

    finally:
        # Clean up temp directory for K8s mode
        if settings.deployment_mode != "docker" and clone_path != project_path:
            try:
                await asyncio.to_thread(shutil.rmtree, clone_path, ignore_errors=True)
                logger.info(f"[CREATE] Cleaned up temp directory: {clone_path}")
            except Exception as cleanup_error:
                logger.warning(f"[CREATE] Failed to cleanup temp directory: {cleanup_error}")

    # Update project with Git info
    db_project.has_git_repo = True
    db_project.git_remote_url = project_data.github_repo_url

    from ..models import GitRepository

    git_repo = GitRepository(
        project_id=db_project.id,
        user_id=user_id,
        repo_url=project_data.github_repo_url,
        repo_name=repo_info["repo"],
        repo_owner=repo_info["owner"],
        default_branch=branch,
        auth_method="pat" if access_token else "none",
    )
    db.add(git_repo)
    await db.commit()


async def _setup_archive_base_project(
    base_repo: MarketplaceBase,
    db_project: Project,
    user_id: UUID,
    settings,
    db: AsyncSession,
    task: Task,
    project_path: str,
) -> str:
    """Setup project from an archive-based marketplace base (exported template)."""
    import subprocess

    from ..services.template_export import extract_archive_to_directory
    from ..services.template_storage import get_template_storage

    use_volumes = os.getenv("USE_DOCKER_VOLUMES", "true").lower() == "true"

    if not base_repo.archive_path:
        raise ValueError("Archive template has no archive file. Export may still be in progress.")

    task.update_progress(20, 100, "Retrieving template archive...")

    storage = get_template_storage()
    archive_bytes = await storage.retrieve_archive(base_repo.archive_path)

    task.update_progress(40, 100, "Extracting template files...")

    if settings.deployment_mode == "docker" and use_volumes:
        volume_project_path = f"/projects/{db_project.slug}"
        os.makedirs(volume_project_path, exist_ok=True)
        files_extracted = await extract_archive_to_directory(archive_bytes, volume_project_path)

        # Fix permissions for devserver (runs as user 1000:1000)
        subprocess.run(["chown", "-R", "1000:1000", volume_project_path], check=True)
        logger.info(f"[CREATE] Extracted {files_extracted} files to volume: {volume_project_path}")
        task.update_progress(80, 100, f"Extracted {files_extracted} files")

    elif settings.deployment_mode == "kubernetes":
        # K8s: Extract to temp directory and save to DB
        import tempfile

        temp_dir = tempfile.mkdtemp(prefix=f"archive-extract-{db_project.slug}-")
        try:
            files_extracted = await extract_archive_to_directory(archive_bytes, temp_dir)
            task.update_progress(60, 100, "Saving files to database...")

            files_saved = 0
            walk_results = await walk_directory_async(
                temp_dir,
                exclude_dirs=[
                    "node_modules",
                    ".git",
                    "dist",
                    "build",
                    ".next",
                    "__pycache__",
                    "venv",
                ],
            )
            for root, _dirs, files in walk_results:
                for file in files:
                    if file.startswith(".") or file.endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico")
                    ):
                        continue
                    file_full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_full_path, temp_dir).replace("\\", "/")
                    try:
                        content = await read_file_async(file_full_path)
                        db_file = ProjectFile(
                            project_id=db_project.id, file_path=relative_path, content=content
                        )
                        db.add(db_file)
                        files_saved += 1
                    except Exception as e:
                        logger.warning(
                            f"[CREATE] Could not read extracted file {relative_path}: {e}"
                        )

            await db.commit()
            task.update_progress(80, 100, f"Saved {files_saved} files to database")
            logger.info(f"[CREATE] Saved {files_saved} extracted files for K8s mode")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    else:
        # Bind mount mode
        os.makedirs(project_path, exist_ok=True)
        files_extracted = await extract_archive_to_directory(archive_bytes, project_path)
        task.update_progress(80, 100, f"Extracted {files_extracted} files")

    await db.commit()

    # Create container linked to the base
    task.update_progress(90, 100, "Creating container from template")

    # Check for TESSLATE.md in the archive for port config
    from ..services.base_config_parser import parse_tesslate_md

    internal_port = 3000  # Default fallback
    if settings.deployment_mode == "docker" and use_volumes:
        tesslate_path = os.path.join(f"/projects/{db_project.slug}", "TESSLATE.md")
    else:
        tesslate_path = os.path.join(project_path, "TESSLATE.md")

    if os.path.exists(tesslate_path):
        try:
            tesslate_content = await read_file_async(tesslate_path)
            base_config = parse_tesslate_md(tesslate_content)
            internal_port = base_config.port
            logger.info(f"[CREATE] Parsed port {internal_port} from template TESSLATE.md")
        except Exception as e:
            logger.warning(f"[CREATE] Could not parse TESSLATE.md: {e}, using default port 3000")

    base_display = re.sub(r"[^a-z0-9]+", "-", base_repo.name.lower()).strip("-")

    container = Container(
        project_id=db_project.id,
        base_id=base_repo.id,
        name=base_display,
        directory=".",
        container_name=f"{db_project.slug}-{base_display}",
        internal_port=internal_port,
        container_type="base",
        status="stopped",
        position_x=200,
        position_y=200,
    )
    db.add(container)
    await db.commit()
    await db.refresh(container)
    logger.info(f"[CREATE] Created container {container.id} from archive template {base_repo.slug}")

    return str(container.id)


async def _setup_base_project(
    project_data: ProjectCreate,
    db_project: Project,
    user_id: UUID,
    settings,
    db: AsyncSession,
    task: Task,
    project_path: str,
) -> None:
    """Setup project from marketplace base"""
    # Docker volume mode setting
    use_volumes = os.getenv("USE_DOCKER_VOLUMES", "true").lower() == "true"

    if not project_data.base_id:
        raise ValueError("base_id is required for source_type 'base'")

    task.update_progress(10, 100, f"Loading marketplace base: {project_data.base_id}")

    # Get base info first
    from sqlalchemy import select

    from ..models import MarketplaceBase, UserPurchasedBase

    base_repo = await db.get(MarketplaceBase, project_data.base_id)
    if not base_repo:
        raise ValueError("Project base not found.")

    # Check if user has this base in their library
    purchase = await db.scalar(
        select(UserPurchasedBase).where(
            UserPurchasedBase.user_id == user_id,
            UserPurchasedBase.base_id == project_data.base_id,
        )
    )

    if purchase and not purchase.is_active:
        # Re-activate a previously deactivated purchase
        if base_repo.pricing_type != "free":
            raise ValueError(
                f"'{base_repo.name}' requires purchase. Please buy it from the marketplace first."
            )
        from datetime import UTC, datetime

        purchase.is_active = True
        purchase.purchase_date = datetime.now(UTC)
        base_repo.downloads += 1
        await db.flush()
        logger.info(f"[CREATE] Re-activated base '{base_repo.name}' for user {user_id}")
    elif not purchase:
        # Auto-add free bases to the user's library on project creation
        if base_repo.pricing_type != "free":
            raise ValueError(
                f"'{base_repo.name}' requires purchase. Please buy it from the marketplace first."
            )
        purchase = UserPurchasedBase(
            user_id=user_id,
            base_id=project_data.base_id,
            purchase_type="free",
            is_active=True,
        )
        db.add(purchase)
        base_repo.downloads += 1
        await db.flush()
        logger.info(f"[CREATE] Auto-added base '{base_repo.name}' to user {user_id} library")

    # Note: MarketplaceBase doesn't have a metadata column - framework detection
    # happens via TESSLATE.md parsing during container startup

    # Handle archive-based templates (exported from projects)
    if base_repo.source_type == "archive":
        return await _setup_archive_base_project(
            base_repo, db_project, user_id, settings, db, task, project_path
        )

    # Track if we're using a temp clone directory (for K8s mode without local cache)
    # Must be defined before try block so finally block can reference it
    temp_clone_dir = None

    try:
        import tempfile

        from ..services.base_cache_manager import get_base_cache_manager
        from ..services.orchestration import get_orchestrator

        task.update_progress(20, 100, "Copying pre-installed base from cache")

        # Get cached base path (returns None in K8s mode)
        base_cache_manager = get_base_cache_manager()
        cached_base_path = await base_cache_manager.get_base_path(base_repo.slug)
        get_orchestrator()

        if cached_base_path is None or not os.path.exists(cached_base_path):
            # Base not in local cache - need to git clone
            # Validate repository is accessible before allocating resources
            task.update_progress(22, 100, "Validating base repository...")
            await _validate_git_repo_accessible(base_repo.git_repo_url)
            logger.info(f"[CREATE] Base repo validated: {base_repo.git_repo_url}")

            logger.info(f"[CREATE] Base {base_repo.slug} not in cache, cloning from git")
            task.update_progress(25, 100, "Cloning base repository...")

            # Clone to temp directory (unified approach for both K8s and Docker)
            temp_clone_dir = tempfile.mkdtemp(prefix=f"base-clone-{base_repo.slug}-")
            logger.info(
                f"[CREATE] Cloning base {base_repo.slug} to temp directory: {temp_clone_dir}"
            )

            # Build clone command
            clone_url = base_repo.git_repo_url
            clone_cmd = ["git", "clone", "--depth=1"]
            branch_ref = project_data.base_version or base_repo.default_branch
            if branch_ref:
                clone_cmd.extend(["--branch", branch_ref])
            clone_cmd.extend([clone_url, temp_clone_dir])

            # Execute git clone
            process = await asyncio.create_subprocess_exec(
                *clone_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=120)

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise RuntimeError(f"Git clone failed: {error_msg}")

            logger.info(f"[CREATE] Successfully cloned base {base_repo.slug}")
            cached_base_path = temp_clone_dir

            # Docker mode: Copy files from temp to volume
            if settings.deployment_mode == "docker" and use_volumes:
                import subprocess

                volume_project_path = f"/projects/{db_project.slug}"
                os.makedirs(volume_project_path, exist_ok=True)

                # Copy source files to volume (skip generated/dependency dirs)
                # node_modules is NOT copied — the container installs deps on first boot
                # This avoids broken symlinks when copying between filesystems/platforms
                _SKIP_DIRS = {
                    ".git",
                    "node_modules",
                    ".next",
                    "__pycache__",
                    ".venv",
                    "dist",
                    "build",
                }
                for item in os.listdir(temp_clone_dir):
                    if item in _SKIP_DIRS:
                        continue
                    src = os.path.join(temp_clone_dir, item)
                    dst = os.path.join(volume_project_path, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)

                # Fix permissions for devserver (runs as user 1000:1000)
                subprocess.run(["chown", "-R", "1000:1000", volume_project_path], check=True)
                logger.info(f"[CREATE] Copied base files to volume: {volume_project_path}")

        # Docker mode with local cache: Copy files from cache to volume
        if (
            settings.deployment_mode == "docker"
            and use_volumes
            and os.path.exists(cached_base_path)
            and not temp_clone_dir
        ):
            import subprocess

            volume_project_path = f"/projects/{db_project.slug}"
            os.makedirs(volume_project_path, exist_ok=True)

            # Copy source files to volume (skip generated/dependency dirs)
            # node_modules is NOT copied — the container installs deps on first boot
            # This avoids broken symlinks when copying between filesystems/platforms
            _SKIP_DIRS = {".git", "node_modules", ".next", "__pycache__", ".venv", "dist", "build"}
            for item in os.listdir(cached_base_path):
                if item in _SKIP_DIRS:
                    continue
                src = os.path.join(cached_base_path, item)
                dst = os.path.join(volume_project_path, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)

            # Fix permissions for devserver (runs as user 1000:1000)
            subprocess.run(["chown", "-R", "1000:1000", volume_project_path], check=True)
            logger.info(
                f"[CREATE] Copied base {base_repo.slug} from cache to volume: {volume_project_path}"
            )

        task.update_progress(40, 100, "Base loaded successfully")

        # Save files to database (needed for K8s mode and as source of truth)
        if settings.deployment_mode == "kubernetes":
            # K8s mode: Save base files to database (will sync to PVC on container start)
            task.update_progress(50, 100, "Saving base files to database")
            files_saved = 0
            walk_results = await walk_directory_async(
                cached_base_path,
                exclude_dirs=[
                    "node_modules",
                    ".git",
                    "dist",
                    "build",
                    ".next",
                    "__pycache__",
                    "venv",
                ],
            )

            for root, _dirs, files in walk_results:
                for file in files:
                    if file.startswith(".") or file.endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico")
                    ):
                        continue

                    file_full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_full_path, cached_base_path).replace(
                        "\\", "/"
                    )

                    try:
                        content = await read_file_async(file_full_path)
                        db_file = ProjectFile(
                            project_id=db_project.id, file_path=relative_path, content=content
                        )
                        db.add(db_file)
                        files_saved += 1
                    except Exception as e:
                        logger.warning(f"[CREATE] Could not read base file {relative_path}: {e}")

            await db.commit()
            task.update_progress(90, 100, f"Saved {files_saved} base files to database")
            logger.info(f"[CREATE] Saved {files_saved} base files to database for K8s mode")

        elif settings.deployment_mode == "docker":
            if use_volumes:
                # Volume mode: Files are in volume, skip DB sync for now
                # TODO: Read files from volume and sync to database
                task.update_progress(90, 100, "Files ready in volume (DB sync skipped)")
                logger.info("[CREATE] Skipped DB sync for volume (files will sync on first edit)")
            else:
                # Bind mount mode: Sync files to database
                task.update_progress(65, 100, "Saving base files to database")
                files_saved = 0
                walk_results = await walk_directory_async(
                    project_path, exclude_dirs=["node_modules", ".git", "dist", "build", ".next"]
                )

                for root, _dirs, files in walk_results:
                    for file in files:
                        if file.startswith(".") or file.endswith(
                            (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico")
                        ):
                            continue

                        file_full_path = os.path.join(root, file)
                        relative_path = os.path.relpath(file_full_path, project_path).replace(
                            "\\", "/"
                        )

                        try:
                            content = await read_file_async(file_full_path)
                            db_file = ProjectFile(
                                project_id=db_project.id, file_path=relative_path, content=content
                            )
                            db.add(db_file)
                            files_saved += 1
                        except Exception as e:
                            logger.warning(f"[CREATE] Could not read file {relative_path}: {e}")

                await db.commit()
                task.update_progress(90, 100, f"Saved {files_saved} files to database")

        db_project.has_git_repo = True
        db_project.git_remote_url = base_repo.git_repo_url
        await db.commit()

        # Create container linked to the base
        task.update_progress(95, 100, "Creating container from base")

        # Priority 1: Check for .tesslate/config.json
        from ..services.base_config_parser import read_tesslate_config as _read_config

        tesslate_config = _read_config(cached_base_path)
        if tesslate_config and tesslate_config.apps:
            # Config-driven setup - create containers from config
            primary_container_id = None
            for app_name, app_config in tesslate_config.apps.items():
                container = Container(
                    project_id=db_project.id,
                    base_id=base_repo.id,
                    name=app_name,
                    directory=app_config.directory,
                    container_name=f"{db_project.slug}-{app_name}",
                    internal_port=app_config.port or 3000,
                    environment_vars=app_config.env or {},
                    container_type="base",
                    status="stopped",
                    position_x=app_config.x or 200,
                    position_y=app_config.y or 200,
                )
                db.add(container)
                await db.flush()
                await db.refresh(container)
                if app_name == tesslate_config.primaryApp:
                    primary_container_id = str(container.id)

            for infra_name, infra_config in tesslate_config.infrastructure.items():
                container = Container(
                    project_id=db_project.id,
                    name=infra_name,
                    directory=".",
                    container_name=f"{db_project.slug}-{infra_name}",
                    internal_port=infra_config.port,
                    container_type="service",
                    service_slug=infra_name,
                    status="stopped",
                    position_x=infra_config.x or 400,
                    position_y=infra_config.y or 400,
                )
                db.add(container)

            await db.commit()
            logger.info(f"[CREATE] Created {len(tesslate_config.apps)} containers from .tesslate/config.json")
            return primary_container_id or str(container.id)

        # No .tesslate/config.json — project needs setup
        task.update_progress(95, 100, "Project created - setup needed")
        logger.info(f"[CREATE] No .tesslate/config.json in base {base_repo.slug}, needs setup")
        return "needs_setup"

    except Exception as git_error:
        logger.error(f"[CREATE] Failed to setup base project: {git_error}", exc_info=True)
        # Re-raise the error - no fallback, let it fail properly
        raise

    finally:
        # Clean up temp clone directory if created
        if temp_clone_dir and os.path.exists(temp_clone_dir):
            try:
                shutil.rmtree(temp_clone_dir)
                logger.info(f"[K8S] Cleaned up temp clone directory: {temp_clone_dir}")
            except Exception as cleanup_error:
                logger.warning(f"[K8S] Failed to cleanup temp directory: {cleanup_error}")


@router.post("/")
async def create_project(
    project: ProjectCreate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new project from a marketplace base or GitHub repository.

    Supports source types:
    - base: Create from a marketplace base (NextJS, Vite, FastAPI, etc.)
    - github/gitlab/bitbucket: Import from a Git repository

    For GitHub import:
    - GitHub authentication is OPTIONAL for public repositories
    - GitHub authentication is REQUIRED for private repositories
    - Repository will be cloned into the project
    - Project files will be populated from the repository
    """
    try:
        # Validate base_id is provided for base source type
        if project.source_type == "base" and not project.base_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A template must be selected to create a project. Please select a template and try again.",
            )

        logger.info(
            f"[CREATE] Creating project for user {current_user.id}: {project.name} "
            f"(source: {project.source_type}, base_id: {project.base_id})"
        )

        # Check project limits based on subscription tier
        await enforce_project_limit(current_user, db)

        settings = get_settings()

        # Generate unique slug for the project
        project_slug = generate_project_slug(project.name)

        # Handle collision (retry with new slug)
        max_retries = 10
        for attempt in range(max_retries):
            try:
                # Create project database record
                db_project = Project(
                    name=project.name,
                    slug=project_slug,
                    description=project.description,
                    owner_id=current_user.id,
                )
                db.add(db_project)
                await db.commit()
                await db.refresh(db_project)
                break
            except Exception as e:
                await db.rollback()
                if (
                    "unique" in str(e).lower()
                    and "slug" in str(e).lower()
                    and attempt < max_retries - 1
                ):
                    # Slug collision, generate a new one
                    project_slug = generate_project_slug(project.name)
                    logger.warning(f"[CREATE] Slug collision, retrying with: {project_slug}")
                else:
                    # Other error or max retries reached
                    raise HTTPException(
                        status_code=500, detail=f"Failed to create project: {str(e)}"
                    ) from e

        logger.info(f"[CREATE] Project {db_project.slug} (ID: {db_project.id}) created in database")

        # Create background task for project setup
        task_manager = get_task_manager()
        task = task_manager.create_task(
            user_id=current_user.id,
            task_type="project_creation",
            metadata={
                "project_id": str(db_project.id),
                "project_slug": db_project.slug,
                "project_name": db_project.name,
                "source_type": project.source_type,
            },
        )

        # Start background task (non-blocking)
        task_manager.start_background_task(
            task_id=task.id,
            coro=_perform_project_setup,
            project_data=project,
            db_project_id=db_project.id,
            db_project_slug=db_project.slug,
            user_id=current_user.id,
            settings=settings,
        )

        logger.info(f"[CREATE] Background task {task.id} started for project {db_project.id}")

        # Return IMMEDIATELY with project and task info
        return {
            "project": db_project,
            "task_id": task.id,
            "status_endpoint": f"/api/tasks/{task.id}",
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"[CREATE] Critical error during project creation: {e}", exc_info=True)

        # Clean up failed project from database if it was created
        try:
            if "db_project" in locals():
                await db.delete(db_project)
                await db.commit()
                logger.info("[CREATE] Cleaned up failed project from database")
        except Exception as cleanup_error:
            logger.error(f"[CREATE] Error during cleanup: {cleanup_error}", exc_info=True)

        raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e)}") from e


@router.get("/{project_slug}", response_model=ProjectSchema)
async def get_project(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a project by its slug."""
    project = await get_project_by_slug(db, project_slug, current_user.id)
    return project


@router.get("/{project_slug}/files", response_model=list[ProjectFileSchema])
async def get_project_files(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    from_pod: bool = False,  # Optional query param to force reading from pod
    from_volume: bool = True,  # Default: Try reading from Docker volume for multi-container projects
    container_dir: str
    | None = None,  # Container subdirectory (e.g., "frontend") - files shown as root
):
    """
    Get project files from Docker volume, database, or running pod.

    Strategy:
    1. For multi-container projects (Docker): Read from Docker volume
    2. For K8s projects: If from_pod=true, read from pod
    3. Fallback: Return files from database

    If container_dir is specified, only files from that subdirectory are returned,
    with paths relative to that directory (appearing as root-level).
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    settings = get_settings()

    # Check if this is a Docker project - use shared projects volume
    if from_volume and settings.deployment_mode == "docker":
        try:
            from ..services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()

            subdir_log = f"/{container_dir}" if container_dir else ""
            logger.info(
                f"[FILES] Reading files from shared projects volume: /projects/{project.slug}{subdir_log}"
            )

            # Get files with content from shared volume (direct filesystem access)
            volume_files = await orchestrator.get_files_with_content(
                project.slug,  # Uses /projects/{slug}/ directory
                max_files=200,
                max_file_size=100000,  # 100KB per file
                subdir=container_dir,  # Container subdirectory (files appear as root)
            )

            if volume_files:
                # Convert to ProjectFileSchema format
                files_with_content = []
                now = datetime.now(UTC)
                for vf in volume_files:
                    files_with_content.append(
                        ProjectFileSchema(
                            id=uuid4(),  # Generate unique ID for each file
                            project_id=project_id,
                            file_path=vf["file_path"],
                            content=vf["content"],
                            created_at=now,
                            updated_at=now,
                        )
                    )

                logger.info(f"[FILES] ✅ Read {len(files_with_content)} files from shared volume")
                return files_with_content
            else:
                logger.info("[FILES] No files found in volume, falling back to database")

        except Exception as e:
            logger.warning(
                f"[FILES] Failed to read from shared volume: {e}, falling back to database"
            )

    # For K8s mode, automatically try reading from pod (like Docker reads from volume)
    from ..services.orchestration import get_orchestrator, is_kubernetes_mode

    if is_kubernetes_mode():
        try:
            orchestrator = get_orchestrator()

            # Determine directory to read from
            # If container_dir specified, read from that subdirectory
            # Otherwise, read from root /app (shows all container directories)
            directory = container_dir if container_dir else "."
            subdir_log = f"/{container_dir}" if container_dir else ""
            logger.info(f"[FILES] K8s: Reading files from file-manager pod: /app{subdir_log}")

            # Get list of files from file-manager pod
            pod_files = await orchestrator.list_files(
                user_id=current_user.id,
                project_id=project_id,
                container_name=None,
                directory=directory,
            )

            # Read content for each file (recursively for directories)
            files_with_content = []
            now = datetime.now(UTC)

            async def read_files_recursive(files, base_path=""):
                for pod_file in files:
                    file_name = pod_file.get("name", "")
                    if not file_name or file_name in [".", ".."]:
                        continue

                    rel_path = f"{base_path}/{file_name}" if base_path else file_name

                    if pod_file["type"] == "file":
                        try:
                            # Build the full path for reading
                            full_path = f"{directory}/{rel_path}" if directory != "." else rel_path
                            content = await orchestrator.read_file(
                                user_id=current_user.id,
                                project_id=project_id,
                                container_name=None,
                                file_path=full_path,
                            )

                            if content is not None:
                                files_with_content.append(
                                    ProjectFileSchema(
                                        id=uuid4(),
                                        project_id=project_id,
                                        file_path=rel_path,  # Relative to container_dir
                                        content=content,
                                        created_at=now,
                                        updated_at=now,
                                    )
                                )
                        except Exception as e:
                            logger.warning(f"[FILES] Failed to read {rel_path}: {e}")
                            continue
                    elif pod_file["type"] == "directory":
                        # Skip node_modules and other large directories
                        # Keep in sync with EXCLUDED_DIRS in docker.py
                        if file_name in [
                            "node_modules",
                            ".next",
                            ".git",
                            "__pycache__",
                            "dist",
                            "build",
                            ".venv",
                            "venv",
                            ".cache",
                            ".turbo",
                            "coverage",
                            ".nyc_output",
                            "lost+found",
                        ]:
                            continue
                        # Recursively read directory contents
                        try:
                            sub_dir = f"{directory}/{rel_path}" if directory != "." else rel_path
                            sub_files = await orchestrator.list_files(
                                user_id=current_user.id,
                                project_id=project_id,
                                container_name=None,
                                directory=sub_dir,
                            )
                            count_before = len(files_with_content)
                            await read_files_recursive(sub_files, rel_path)
                            # If no files were added, this directory is empty — emit placeholder
                            if len(files_with_content) == count_before:
                                files_with_content.append(
                                    ProjectFileSchema(
                                        id=uuid4(),
                                        project_id=project_id,
                                        file_path=rel_path + "/",
                                        content="",
                                        created_at=now,
                                        updated_at=now,
                                    )
                                )
                        except Exception as e:
                            logger.warning(f"[FILES] Failed to list {rel_path}: {e}")

            await read_files_recursive(pod_files)

            if files_with_content:
                logger.info(
                    f"[FILES] ✅ Read {len(files_with_content)} files from file-manager pod"
                )
                return files_with_content
            else:
                # No files in pod yet - return empty (pod environment starting or files being cloned)
                logger.info("[FILES] No files in pod - returning empty list (K8s mode)")
                return []

        except Exception as e:
            logger.warning(f"[FILES] Failed to read from pod: {e}")
            # In K8s mode, return empty list on error - files live on PVC only
            return []

    # Docker mode only: Get files from database
    result = await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id))
    files = result.scalars().all()
    logger.info(f"[FILES] Returning {len(files)} files from database")
    return files


@router.get("/{project_slug}/dev-server-url")
async def get_dev_server_url(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get or create the development server URL for a project.

    Best practice implementation:
    1. Check if container exists and is healthy
    2. If not, create it
    3. Wait for readiness before returning URL
    4. Return detailed status for better UX
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    logger.info(
        f"[DEV-URL] Checking dev environment for user {current_user.id}, project {project_id}"
    )

    try:
        get_settings()

        # Check if this is a multi-container project
        containers_result = await db.execute(
            select(Container).where(Container.project_id == project.id)
        )
        containers = containers_result.scalars().all()

        if containers:
            # Multi-container project - dev servers managed via docker-compose
            logger.info(
                f"[DEV-URL] Multi-container project detected ({len(containers)} containers)"
            )
            return {
                "url": None,
                "status": "multi_container",
                "message": "Multi-container project. Each container has its own dev server.",
            }

        # No containers found - this is an error as all projects should have containers
        logger.error(
            f"[DEV-URL] Project {project_slug} has no containers. All projects must use multi-container system."
        )
        raise HTTPException(
            status_code=400,
            detail="Project has no containers. Please add containers to your project using the graph canvas.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[DEV-URL] ❌ Failed to get dev environment", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get development environment: {str(e)}"
        ) from e


@router.get("/{project_slug}/container-status")
async def get_container_status(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed status of the development container/pod.

    Returns readiness, phase, and detailed status information.
    Frontend should poll this endpoint to know when pod is ready.
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    try:
        from ..services.orchestration import get_orchestrator, is_kubernetes_mode

        if is_kubernetes_mode():
            # Kubernetes mode
            orchestrator = get_orchestrator()

            readiness = await orchestrator.is_container_ready(
                user_id=current_user.id, project_id=project_id, container_name=None
            )

            # Get full environment status
            env_status = await orchestrator.get_container_status(
                project_slug=None,
                project_id=project_id,
                container_name=None,
                user_id=current_user.id,
            )

            # Build container URL from project's first container
            container_url = None
            containers_result = await db.execute(
                select(Container).where(Container.project_id == project_id)
            )
            containers = containers_result.scalars().all()
            if containers:
                settings = get_settings()
                first_container = containers[0]
                container_dir = (
                    (first_container.directory or first_container.name)
                    .lower()
                    .replace(" ", "-")
                    .replace("_", "-")
                    .replace(".", "-")
                )
                protocol = "https" if settings.k8s_wildcard_tls_secret else "http"
                container_url = f"{protocol}://{container_dir}.{project_slug}.{settings.app_domain}"

            return {
                "status": "ready" if readiness["ready"] else "starting",
                "ready": readiness["ready"],
                "phase": readiness.get("phase", "Unknown"),
                "message": readiness.get("message", ""),
                "responsive": readiness.get("responsive"),
                "conditions": readiness.get("conditions", []),
                "pod_name": readiness.get("pod_name"),
                "url": container_url,
                "deployment": env_status.get("deployment_ready"),
                "replicas": env_status.get("replicas"),
                "project_id": project_id,
                "user_id": current_user.id,
            }
        else:
            # Docker mode - multi-container projects only
            raise HTTPException(
                status_code=400,
                detail="This endpoint is only for Kubernetes deployments. For Docker, use the multi-container project status endpoints.",
            )

    except Exception as e:
        logger.error(f"[STATUS] Failed to get container status: {e}", exc_info=True)
        return {
            "status": "error",
            "ready": False,
            "phase": "Unknown",
            "message": f"Failed to get status: {str(e)}",
            "project_id": project_id,
            "user_id": current_user.id,
        }


@router.post("/{project_slug}/files/save")
async def save_project_file(
    project_slug: str,
    file_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Save a file to the user's dev container.

    Architecture: Backend is stateless and doesn't store files.
    Instead, it writes files directly to the dev container pod via K8s API.
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    file_path = file_data.get("file_path")
    content = file_data.get("content")

    if not file_path or content is None:
        raise HTTPException(status_code=400, detail="file_path and content are required")

    try:
        from ..services.orchestration import get_orchestrator, is_kubernetes_mode

        # 1. Write file to container/filesystem using unified orchestrator
        try:
            orchestrator = get_orchestrator()

            success = await orchestrator.write_file(
                user_id=current_user.id,
                project_id=project_id,
                container_name=None,
                file_path=file_path,
                content=content,
            )

            if success:
                logger.info(
                    f"[FILE] ✅ Wrote {file_path} to container for user {current_user.id}, project {project_id}"
                )
                # Track activity for idle cleanup (database-based)
                from ..services.activity_tracker import track_project_activity

                await track_project_activity(db, project_id, "file_save")
            else:
                logger.warning("[FILE] ⚠️ Failed to write to container")

        except Exception as write_error:
            logger.warning(f"[FILE] ⚠️ Failed to write via orchestrator: {write_error}")
            # Continue to save in DB even if container write fails

        # Fallback for Docker mode: Write to shared volume via orchestrator
        if not is_kubernetes_mode():
            # Docker mode: Write directly to shared projects volume
            try:
                from ..services.orchestration import get_orchestrator

                orch = get_orchestrator()

                # Write file to shared volume at /projects/{project.slug}/{file_path}
                success = await orch.write_file(
                    user_id=current_user.id,
                    project_id=project_id,
                    container_name=None,
                    file_path=file_path,
                    content=content,
                    project_slug=project.slug,
                )

                if success:
                    logger.info(
                        f"[FILE] ✅ Wrote {file_path} to shared volume for project {project.slug}"
                    )
                else:
                    logger.warning("[FILE] ⚠️ Failed to write to shared volume")

            except Exception as docker_error:
                logger.warning(f"[FILE] ⚠️ Failed to write to shared volume: {docker_error}")

        # 2. Update database record (for version history / backup)
        result = await db.execute(
            select(ProjectFile).where(
                ProjectFile.project_id == project_id, ProjectFile.file_path == file_path
            )
        )
        existing_file = result.scalar_one_or_none()

        if existing_file:
            existing_file.content = content
        else:
            new_file = ProjectFile(project_id=project_id, file_path=file_path, content=content)
            db.add(new_file)

        # Update project's updated_at timestamp
        from datetime import datetime

        project.updated_at = datetime.utcnow()

        await db.commit()

        logger.info(f"[FILE] Saved {file_path} to database as backup")

        return {
            "message": "File saved successfully",
            "file_path": file_path,
            "method": "shared_volume" if not is_kubernetes_mode() else "kubernetes_pod",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] Failed to save file {file_path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}") from e


def _validate_file_path(path: str) -> str:
    """Validate and sanitise a file path. Raises HTTPException on invalid input."""
    if not path or not path.strip():
        raise HTTPException(status_code=400, detail="Path cannot be empty")
    path = path.strip()
    if "\x00" in path:
        raise HTTPException(status_code=400, detail="Path contains invalid characters")
    for segment in path.replace("\\", "/").split("/"):
        if segment == "..":
            raise HTTPException(status_code=400, detail="Path traversal is not allowed")
    return path.lstrip("/")


@router.delete("/{project_slug}/files")
async def delete_project_file(
    project_slug: str,
    body: FileDeleteRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file or directory from the user's dev container."""
    project = await get_project_by_slug(db, project_slug, current_user.id)
    file_path = _validate_file_path(body.file_path)

    try:
        from ..services.orchestration import get_orchestrator

        orchestrator = get_orchestrator()

        if body.is_directory:
            await orchestrator.execute_command(
                user_id=current_user.id,
                project_id=project.id,
                container_name=None,
                command=["rm", "-rf", "--", f"/app/{file_path}"],
            )
        else:
            await orchestrator.execute_command(
                user_id=current_user.id,
                project_id=project.id,
                container_name=None,
                command=["rm", "-f", "--", f"/app/{file_path}"],
            )

        # Remove matching ProjectFile DB records
        if body.is_directory:
            result = await db.execute(
                select(ProjectFile).where(
                    ProjectFile.project_id == project.id,
                    or_(
                        ProjectFile.file_path == file_path,
                        ProjectFile.file_path.like(
                            file_path.replace("%", r"\%").replace("_", r"\_") + "/%",
                            escape="\\",
                        ),
                    ),
                )
            )
        else:
            result = await db.execute(
                select(ProjectFile).where(
                    ProjectFile.project_id == project.id,
                    ProjectFile.file_path == file_path,
                )
            )
        for pf in result.scalars().all():
            await db.delete(pf)

        await db.commit()

        logger.info(f"[FILE] Deleted {'directory' if body.is_directory else 'file'} {file_path}")
        return {"message": "Deleted successfully", "file_path": file_path}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] Failed to delete {file_path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete file") from e


@router.post("/{project_slug}/files/rename")
async def rename_project_file(
    project_slug: str,
    body: FileRenameRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename / move a file or directory inside the user's dev container."""
    project = await get_project_by_slug(db, project_slug, current_user.id)
    old_path = _validate_file_path(body.old_path)
    new_path = _validate_file_path(body.new_path)

    if old_path == new_path:
        raise HTTPException(status_code=400, detail="Old and new paths are the same")

    try:
        from ..services.orchestration import get_orchestrator

        orchestrator = get_orchestrator()

        new_parent = "/app/" + "/".join(new_path.split("/")[:-1]) if "/" in new_path else "/app"
        await orchestrator.execute_command(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            command=["mkdir", "-p", "--", new_parent],
        )

        await orchestrator.execute_command(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            command=["mv", "--", f"/app/{old_path}", f"/app/{new_path}"],
        )

        # Update matching ProjectFile DB records
        escaped_old = old_path.replace("%", r"\%").replace("_", r"\_")
        result = await db.execute(
            select(ProjectFile).where(
                ProjectFile.project_id == project.id,
                or_(
                    ProjectFile.file_path == old_path,
                    ProjectFile.file_path.like(escaped_old + "/%", escape="\\"),
                ),
            )
        )
        for pf in result.scalars().all():
            if pf.file_path == old_path:
                pf.file_path = new_path
            elif pf.file_path.startswith(old_path + "/"):
                pf.file_path = new_path + pf.file_path[len(old_path) :]

        await db.commit()

        logger.info(f"[FILE] Renamed {old_path} → {new_path}")
        return {"message": "Renamed successfully", "old_path": old_path, "new_path": new_path}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] Failed to rename {old_path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to rename file") from e


@router.post("/{project_slug}/files/mkdir")
async def create_project_directory(
    project_slug: str,
    body: DirectoryCreateRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a directory inside the user's dev container."""
    project = await get_project_by_slug(db, project_slug, current_user.id)
    dir_path = _validate_file_path(body.dir_path)

    try:
        from ..services.orchestration import get_orchestrator

        orchestrator = get_orchestrator()

        await orchestrator.execute_command(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            command=["mkdir", "-p", "--", f"/app/{dir_path}"],
        )

        logger.info(f"[FILE] Created directory {dir_path}")
        return {"message": "Directory created", "dir_path": dir_path}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] Failed to create directory {dir_path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create directory") from e


@router.get("/{project_slug}/container-info")
async def get_container_info(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get container/pod information for a project.

    This endpoint is useful for agents that need to execute commands (like Git operations)
    in the user's development environment. It returns the deployment mode and container/pod
    naming information.

    Returns:
        - deployment_mode: "kubernetes" or "docker"
        - For Kubernetes:
          - pod_name: Name of the pod (e.g., "dev-{user_uuid}-{project_uuid}")
          - namespace: Kubernetes namespace (e.g., "tesslate-user-environments")
          - command_prefix: kubectl exec command prefix
        - For Docker:
          - container_name: Name of the container (e.g., "tesslate-dev-{user_uuid}-{project_uuid}")
          - command_prefix: docker exec command prefix
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    settings = get_settings()

    if settings.deployment_mode == "kubernetes":
        from ..utils.resource_naming import get_container_name

        pod_name = get_container_name(current_user.id, project_id, mode="kubernetes")
        namespace = "tesslate-user-environments"
        return {
            "deployment_mode": "kubernetes",
            "pod_name": pod_name,
            "namespace": namespace,
            "command_prefix": f"kubectl exec -n {namespace} {pod_name} --",
            "git_command_example": f"kubectl exec -n {namespace} {pod_name} -- git status",
        }
    else:
        from ..utils.resource_naming import get_container_name

        container_name = get_container_name(current_user.id, project_id, mode="docker")
        return {
            "deployment_mode": "docker",
            "container_name": container_name,
            "command_prefix": f"docker exec {container_name}",
            "git_command_example": f"docker exec {container_name} git status",
        }


async def _perform_project_deletion(
    project_id: UUID, user_id: UUID, project_slug: str, task: Task
) -> None:
    """Background worker to delete a project"""
    from ..database import get_db
    from ..services.orchestration import get_orchestrator

    # Get a new database session for this background task
    db_gen = get_db()
    db = await db_gen.__anext__()

    try:
        logger.info(f"[DELETE] Starting deletion of project {project_id} for user {user_id}")
        task.update_progress(0, 100, "Stopping containers...")

        # 1. Stop and remove containers using unified orchestrator
        try:
            orchestrator = get_orchestrator()

            # Get project to access slug
            project_result = await db.execute(select(Project).where(Project.id == project_id))
            project = project_result.scalar_one_or_none()

            if project:
                try:
                    # Stop the entire project (all containers)
                    await orchestrator.stop_project(project.slug, project_id, user_id)
                    logger.info(f"[DELETE] Stopped all containers for project {project.slug}")
                except Exception as e:
                    logger.warning(f"[DELETE] Error stopping project containers: {e}")

                try:
                    # Disconnect main Traefik from project network and remove network
                    network_name = f"tesslate-{project.slug}"

                    logger.info(f"[DELETE] Disconnecting tesslate-traefik from {network_name}")
                    process = await asyncio.create_subprocess_exec(
                        "docker",
                        "network",
                        "disconnect",
                        network_name,
                        "tesslate-traefik",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await process.communicate()

                    # Remove project network
                    logger.info(f"[DELETE] Removing network {network_name}")
                    process = await asyncio.create_subprocess_exec(
                        "docker",
                        "network",
                        "rm",
                        network_name,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await process.communicate()

                    logger.info(f"[DELETE] Cleaned up networks for project {project.slug}")
                except Exception as e:
                    logger.warning(f"[DELETE] Error cleaning up networks: {e}")

        except Exception as e:
            logger.warning(f"[DELETE] Error stopping containers: {e}")

        task.update_progress(30, 100, "Deleting chats and messages...")

        # 2. Delete all chats associated with this project (and their messages will cascade)
        chats_result = await db.execute(select(Chat).where(Chat.project_id == project_id))
        project_chats = chats_result.scalars().all()

        for chat in project_chats:
            logger.info(f"[DELETE] Deleting chat {chat.id} with messages")
            await db.delete(chat)  # Use ORM delete to trigger cascades

        logger.info(f"[DELETE] Deleted {len(project_chats)} chats and their messages")

        task.update_progress(50, 100, "Removing project from database...")

        # 3. Delete project from database (files will cascade automatically)
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()
        if project:
            await db.delete(project)  # Use ORM delete to trigger cascades
            await db.commit()
            logger.info("[DELETE] Deleted project from database")

        task.update_progress(70, 100, "Deleting project files...")

        # 4. Delete project files from shared volume (Docker mode only - K8s uses PVCs)
        settings = get_settings()
        if settings.deployment_mode == "docker" and project:
            # Delete project directory from shared volume via orchestrator
            try:
                await orchestrator.delete_project_directory(project.slug)
                logger.info(f"[DELETE] Deleted project directory: /projects/{project.slug}")
            except Exception as e:
                logger.warning(f"[DELETE] Failed to delete project directory: {e}")

        else:
            # Kubernetes mode: Delete K8s resources and soft-delete snapshots
            logger.info("[DELETE] Kubernetes mode: Cleaning up K8s resources...")

            # 4a. Soft-delete snapshots (marks for 30-day retention)
            try:
                from ..services.snapshot_manager import get_snapshot_manager

                snapshot_manager = get_snapshot_manager()

                deleted_count = await snapshot_manager.soft_delete_project_snapshots(project_id, db)
                if deleted_count > 0:
                    logger.info(
                        f"[DELETE] Soft-deleted {deleted_count} snapshots for project {project_id} (30-day retention)"
                    )
            except Exception as e:
                logger.warning(f"[DELETE] Error soft-deleting snapshots: {e}")
                # Continue with deletion even if soft delete fails

            # 4b. Delete Kubernetes namespace and all resources
            try:
                # Delete entire namespace (cascades to all pods, services, ingresses, PVCs)
                await orchestrator.delete_project_namespace(project_id=project_id, user_id=user_id)
                logger.info(
                    f"[DELETE] Deleted K8s namespace and resources for project {project_slug}"
                )
            except Exception as e:
                logger.warning(f"[DELETE] Error deleting K8s resources: {e}")

        task.update_progress(100, 100, "Project deleted successfully")
        logger.info(f"[DELETE] Successfully deleted project {project_id}")

    except Exception as e:
        await db.rollback()
        logger.error(f"[DELETE] Error during project deletion: {e}", exc_info=True)
        raise
    finally:
        await db_gen.aclose()


@router.delete("/{project_slug}")
async def delete_project(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a project and ALL associated data including chats, messages, files, and containers.

    This is a non-blocking operation. The deletion happens in the background and you can
    track its progress using the returned task_id.
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    # Create a background task for deletion
    from ..services.task_manager import get_task_manager

    task_manager = get_task_manager()

    task = task_manager.create_task(
        user_id=current_user.id,
        task_type="project_deletion",
        metadata={
            "project_id": str(project_id),
            "project_slug": project_slug,
            "project_name": project.name,
        },
    )

    # Start the background task
    task_manager.start_background_task(
        task_id=task.id,
        coro=_perform_project_deletion,
        project_id=project_id,
        user_id=UUID(str(current_user.id)),
        project_slug=project_slug,
    )

    logger.info(f"[DELETE] Started background deletion for project {project_id}, task_id={task.id}")

    return {
        "message": "Project deletion started",
        "task_id": task.id,
        "project_id": str(project_id),
        "project_slug": project_slug,
        "status_endpoint": f"/api/tasks/{task.id}/status",
    }


@router.get("/{project_slug}/setup-config", response_model=TesslateConfigResponse)
async def get_setup_config(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Read .tesslate/config.json from the project filesystem/PVC.
    Falls back to parsing TESSLATE.md if config.json doesn't exist.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)
    settings = get_settings()

    from ..services.base_config_parser import (
        read_tesslate_config,
        parse_tesslate_md,
    )

    config_data = None

    if settings.deployment_mode == "docker":
        # Docker: read from filesystem
        project_path = f"/projects/{project.slug}"
        config_data = read_tesslate_config(project_path)

        if not config_data:
            # Try TESSLATE.md fallback
            tesslate_path = os.path.join(project_path, "TESSLATE.md")
            if os.path.exists(tesslate_path):
                try:
                    content = await read_file_async(tesslate_path)
                    base_config = parse_tesslate_md(content)
                    if base_config and base_config.start_command:
                        return {
                            "exists": False,
                            "apps": {
                                "app": {
                                    "directory": ".",
                                    "port": base_config.port or 3000,
                                    "start": base_config.start_command,
                                    "env": {},
                                }
                            },
                            "infrastructure": {},
                            "primaryApp": "app",
                        }
                except Exception as e:
                    logger.warning(f"[SETUP-CONFIG] Could not parse TESSLATE.md: {e}")
    else:
        # K8s: read from PVC via file-manager pod
        from ..services.orchestration import get_orchestrator
        orchestrator = get_orchestrator()
        try:
            config_json = await orchestrator.read_file(
                user_id=current_user.id,
                project_id=project.id,
                container_name=None,
                file_path=".tesslate/config.json",
                project_slug=project.slug,
            )
            if config_json:
                from ..services.base_config_parser import parse_tesslate_config
                config_data = parse_tesslate_config(config_json)
        except Exception as e:
            logger.debug(f"[SETUP-CONFIG] Could not read config from K8s: {e}")

        if not config_data:
            # Try TESSLATE.md fallback (same as Docker path)
            try:
                tesslate_content = await orchestrator.read_file(
                    user_id=current_user.id,
                    project_id=project.id,
                    container_name=None,
                    file_path="TESSLATE.md",
                    project_slug=project.slug,
                )
                if tesslate_content:
                    base_config = parse_tesslate_md(tesslate_content)
                    if base_config and base_config.start_command:
                        return {
                            "exists": False,
                            "apps": {
                                "app": {
                                    "directory": ".",
                                    "port": base_config.port or 3000,
                                    "start": base_config.start_command,
                                    "env": {},
                                }
                            },
                            "infrastructure": {},
                            "primaryApp": "app",
                        }
            except Exception as e:
                logger.warning(f"[SETUP-CONFIG] Could not parse TESSLATE.md from K8s: {e}")

    if config_data:
        return {
            "exists": True,
            "apps": {
                name: {
                    "directory": app.directory,
                    "port": app.port,
                    "start": app.start,
                    "env": app.env,
                    "x": app.x,
                    "y": app.y,
                }
                for name, app in config_data.apps.items()
            },
            "infrastructure": {
                name: {
                    "image": infra.image,
                    "port": infra.port,
                    "x": infra.x,
                    "y": infra.y,
                }
                for name, infra in config_data.infrastructure.items()
            },
            "primaryApp": config_data.primaryApp,
        }

    # Nothing found
    return {
        "exists": False,
        "apps": {},
        "infrastructure": {},
        "primaryApp": "",
    }


@router.post("/{project_slug}/setup-config", response_model=SetupConfigSyncResponse)
async def save_setup_config(
    project_slug: str,
    config_data: TesslateConfigCreate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Save .tesslate/config.json and sync Container records.
    Creates/updates/deletes containers to match the config.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)
    settings = get_settings()

    from ..services.base_config_parser import (
        TesslateProjectConfig,
        AppConfig,
        InfraConfig,
        write_tesslate_config,
        validate_startup_command,
    )

    # Validate all start commands
    for app_name, app_data in config_data.apps.items():
        if app_data.start:
            is_valid, error = validate_startup_command(app_data.start)
            if not is_valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"App '{app_name}' has invalid start command: {error}",
                )

    # Build internal config object
    config = TesslateProjectConfig(
        apps={
            name: AppConfig(
                directory=app.directory,
                port=app.port,
                start=app.start,
                env=app.env,
                x=app.x,
                y=app.y,
            )
            for name, app in config_data.apps.items()
        },
        infrastructure={
            name: InfraConfig(
                image=infra.image,
                port=infra.port,
                x=infra.x,
                y=infra.y,
            )
            for name, infra in config_data.infrastructure.items()
        },
        primaryApp=config_data.primaryApp,
    )

    # Write config file to filesystem/PVC
    if settings.deployment_mode == "docker":
        project_path = f"/projects/{project.slug}"
        write_tesslate_config(project_path, config)
    else:
        # K8s: write via orchestrator
        import json as json_mod

        config_json = json_mod.dumps({
            "apps": {
                name: {"directory": a.directory, "port": a.port, "start": a.start, "env": a.env, "x": a.x, "y": a.y}
                for name, a in config.apps.items()
            },
            "infrastructure": {
                name: {"image": i.image, "port": i.port, "x": i.x, "y": i.y}
                for name, i in config.infrastructure.items()
            },
            "primaryApp": config.primaryApp,
        }, indent=2)

        from ..services.orchestration import get_orchestrator
        orchestrator = get_orchestrator()
        await orchestrator.write_file(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            file_path=".tesslate/config.json",
            content=config_json,
            project_slug=project.slug,
        )

    # Sync Container records
    container_ids = []
    primary_container_id = None

    # Get existing containers for this project
    existing_result = await db.execute(
        select(Container).where(Container.project_id == project.id)
    )
    existing_containers = {c.name: c for c in existing_result.scalars().all()}

    # Create/update app containers
    for app_name, app_config in config.apps.items():
        if app_name in existing_containers:
            # Update existing container
            container = existing_containers[app_name]
            container.directory = app_config.directory
            container.internal_port = app_config.port or 3000
            container.environment_vars = app_config.env or {}
            if app_config.x is not None:
                container.position_x = app_config.x
            if app_config.y is not None:
                container.position_y = app_config.y
            del existing_containers[app_name]
        else:
            # Create new container
            container = Container(
                project_id=project.id,
                name=app_name,
                directory=app_config.directory,
                container_name=f"{project.slug}-{app_name}",
                internal_port=app_config.port or 3000,
                environment_vars=app_config.env or {},
                container_type="base",
                status="stopped",
                position_x=app_config.x or 200,
                position_y=app_config.y or 200,
            )
            db.add(container)

        await db.flush()
        await db.refresh(container)
        container_ids.append(str(container.id))
        if app_name == config.primaryApp:
            primary_container_id = str(container.id)

    # Create/update infrastructure containers
    for infra_name, infra_config in config.infrastructure.items():
        if infra_name in existing_containers:
            container = existing_containers[infra_name]
            container.internal_port = infra_config.port
            if infra_config.x is not None:
                container.position_x = infra_config.x
            if infra_config.y is not None:
                container.position_y = infra_config.y
            del existing_containers[infra_name]
        else:
            container = Container(
                project_id=project.id,
                name=infra_name,
                directory=".",
                container_name=f"{project.slug}-{infra_name}",
                internal_port=infra_config.port,
                container_type="service",
                service_slug=infra_name,
                status="stopped",
                position_x=infra_config.x or 400,
                position_y=infra_config.y or 400,
            )
            db.add(container)

        await db.flush()
        await db.refresh(container)
        container_ids.append(str(container.id))

    # Delete orphaned containers (those no longer in config)
    for orphan_name, orphan_container in existing_containers.items():
        logger.info(f"[SETUP-CONFIG] Deleting orphaned container: {orphan_name}")
        await db.delete(orphan_container)

    await db.commit()

    return SetupConfigSyncResponse(
        container_ids=container_ids,
        primary_container_id=primary_container_id,
    )


@router.post("/{project_slug}/analyze", response_model=TesslateConfigResponse)
async def analyze_project(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze project files and generate .tesslate/config.json using LLM.
    Returns a TesslateConfigResponse with the generated configuration.
    """
    from fastapi.responses import JSONResponse

    project = await get_project_by_slug(db, project_slug, current_user.id)
    settings = get_settings()

    # Read file tree from filesystem/PVC
    file_tree = []
    config_files_content = {}

    CONFIG_FILENAMES = {
        "package.json", "requirements.txt", "go.mod", "Cargo.toml",
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "Makefile", "pyproject.toml", "pubspec.yaml", "Gemfile",
        "composer.json", "pom.xml", "build.gradle", "mix.exs",
        "TESSLATE.md", ".tesslate/config.json",
    }
    SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "__pycache__", ".venv", "vendor", "target"}
    COMMON_SUBDIRS = ["", "frontend", "backend", "client", "server", "api", "web", "app", "src"]

    if settings.deployment_mode == "docker":
        project_path = f"/projects/{project.slug}"
        # Walk directory for file tree
        try:
            walk_results = await walk_directory_async(
                project_path, exclude_dirs=list(SKIP_DIRS)
            )
            for root, dirs, files in walk_results:
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), project_path).replace("\\", "/")
                    file_tree.append(rel)
                    # Read config files
                    basename = os.path.basename(rel)
                    if basename in CONFIG_FILENAMES or rel in CONFIG_FILENAMES:
                        try:
                            content = await read_file_async(os.path.join(root, f))
                            if len(content) < 20000:
                                config_files_content[rel] = content
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"[ANALYZE] Could not walk project directory: {e}")
    else:
        # K8s: try reading from PVC first, fall back to DB (ProjectFile records)
        from ..services.orchestration import get_orchestrator
        orchestrator = get_orchestrator()
        k8s_success = False
        try:
            files_list = await orchestrator.list_files(
                user_id=current_user.id,
                project_id=project.id,
                container_name=".",
            )
            if files_list:
                file_tree = [f.get("path", f.get("name", "")) for f in files_list if isinstance(f, dict)]
                k8s_success = True

            # Read config files from PVC
            for subdir in COMMON_SUBDIRS:
                for config_name in CONFIG_FILENAMES:
                    file_path = f"{subdir}/{config_name}".lstrip("/") if subdir else config_name
                    try:
                        content = await orchestrator.read_file(
                            user_id=current_user.id,
                            project_id=project.id,
                            container_name=".",
                            file_path=file_path,
                        )
                        if content and len(content) < 20000:
                            config_files_content[file_path] = content
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"[ANALYZE] Could not read files from K8s: {e}")

        # Fallback: read from DB (ProjectFile records) — handles projects at setup stage
        # where no K8s namespace/PVC exists yet
        if not k8s_success:
            logger.info("[ANALYZE] Falling back to ProjectFile records from DB")
            from ..models import ProjectFile as PF
            db_files_result = await db.execute(
                select(PF).where(PF.project_id == project.id)
            )
            for pf in db_files_result.scalars().all():
                fp = pf.file_path
                # Skip dirs we don't care about
                if any(skip in fp for skip in SKIP_DIRS):
                    continue
                file_tree.append(fp)
                basename = os.path.basename(fp)
                if basename in CONFIG_FILENAMES or fp in CONFIG_FILENAMES:
                    if pf.content and len(pf.content) < 20000:
                        config_files_content[fp] = pf.content

    if not file_tree:
        raise HTTPException(status_code=400, detail="No files found in project to analyze")

    # Build LLM prompt
    file_tree_str = "\n".join(sorted(file_tree)[:500])
    config_contents_str = "\n".join([
        f"--- {path} ---\n{content[:3000]}"
        for path, content in list(config_files_content.items())[:15]
    ])

    prompt = f"""Analyze this project and generate a .tesslate/config.json file.

The config defines how to run this project in containerized dev environments.

## File tree:
{file_tree_str}

## Config file contents:
{config_contents_str}

## Config format:
The config has this structure:
{{
  "apps": {{
    "<app-name>": {{
      "directory": "<relative-dir or . for root>",
      "port": <port-number or null for no-server>,
      "start": "<shell command to install deps and start dev server>",
      "env": {{"KEY": "value"}}
    }}
  }},
  "infrastructure": {{
    "<service-name>": {{
      "image": "<docker-image:tag>",
      "port": <internal-port>
    }}
  }},
  "primaryApp": "<name of the main app to show in preview>"
}}

## Rules:
1. Every start command MUST bind to 0.0.0.0 (not localhost) for container networking
2. For Node.js: use `npm install && npm run dev -- --host 0.0.0.0` or equivalent
3. For Python: use `pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port 8001 --reload`
4. For Go: use `go mod tidy && go run .` or `air` if .air.toml exists
5. If the project has frontend + backend in separate dirs, create separate apps
6. If it's a monorepo with one entry point, use directory "." and one app
7. For projects with no server (CLI tools, libraries), set port to null and start to "sleep infinity"
8. Use common port conventions: Next.js=3000, Vite=5173, FastAPI=8001, Go=8080, Rails=3000, Django=8000
9. primaryApp should be the frontend or the main user-facing app
10. Only add infrastructure (postgres, redis, etc.) if the project clearly uses them

Return ONLY valid JSON, no markdown code blocks, no explanation."""

    # Call LLM via OpenAI client pointed at LiteLLM proxy
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.litellm_master_key,
            base_url=settings.litellm_api_base,
        )

        response = await client.chat.completions.create(
            model="glm-5",
            messages=[
                {"role": "system", "content": "You are a project analyzer. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
        )

        response_text = response.choices[0].message.content.strip()

        # Clean up response - strip markdown code blocks if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # Parse and validate
        import json as json_mod
        parsed = json_mod.loads(response_text)

        # Validate structure
        apps = parsed.get("apps", {})
        if not apps:
            raise ValueError("No apps found in generated config")

        primary = parsed.get("primaryApp", "")
        if not primary or primary not in apps:
            primary = next(iter(apps))
            parsed["primaryApp"] = primary

        return {
            "exists": False,
            **parsed,
        }

    except json.JSONDecodeError as e:
        logger.error(f"[ANALYZE] LLM returned invalid JSON: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse generated config. Please try again.")
    except Exception as e:
        logger.error(f"[ANALYZE] Failed to analyze project: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to analyze project: {str(e)}")


@router.get("/{project_slug}/settings")
async def get_project_settings(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get project settings."""
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)

    settings = project.settings or {}
    return {
        "settings": settings,
        "architecture_diagram": project.architecture_diagram,
        "diagram_type": settings.get(
            "diagram_type", "mermaid"
        ),  # Default to mermaid for backwards compatibility
    }


@router.patch("/{project_slug}/settings")
async def update_project_settings(
    project_slug: str,
    settings_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update project settings."""
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)

    try:
        # Merge new settings with existing
        current_settings = project.settings or {}
        new_settings = settings_data.get("settings", {})
        current_settings.update(new_settings)

        project.settings = current_settings
        flag_modified(project, "settings")  # Mark JSON field as modified for SQLAlchemy
        await db.commit()
        await db.refresh(project)

        logger.info(f"[SETTINGS] Updated settings for project {project.id}: {new_settings}")

        return {"message": "Settings updated successfully", "settings": project.settings}
    except Exception as e:
        await db.rollback()
        logger.error(f"[SETTINGS] Failed to update settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}") from e


@router.post("/{project_slug}/export-template")
async def export_project_as_template(
    project_slug: str,
    export_data: TemplateExportRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Export a project as a reusable template archive.

    Creates a MarketplaceBase record with source_type='archive' and starts
    a background task to package the project files into a tar.gz archive.
    """
    settings = get_settings()
    project = await get_project_by_slug(db, project_slug, current_user.id)

    # Create the marketplace base record
    template_slug = generate_project_slug(export_data.name)

    marketplace_base = MarketplaceBase(
        name=export_data.name,
        slug=template_slug,
        description=export_data.description,
        long_description=export_data.long_description,
        category=export_data.category,
        icon=export_data.icon or "\U0001f4e6",
        tags=export_data.tags,
        features=export_data.features,
        tech_stack=export_data.tech_stack,
        visibility=export_data.visibility,
        pricing_type="free",
        price=0,
        source_type="archive",
        git_repo_url=None,
        source_project_id=project.id,
        created_by_user_id=current_user.id,
    )
    db.add(marketplace_base)
    await db.flush()

    # Auto-add to user's library
    user_purchase = UserPurchasedBase(
        user_id=current_user.id,
        base_id=marketplace_base.id,
        purchase_type="free",
        is_active=True,
    )
    db.add(user_purchase)
    await db.commit()
    await db.refresh(marketplace_base)

    base_id = marketplace_base.id

    # Capture ORM values before request session closes
    proj_slug = project.slug
    proj_id = project.id
    user_id = current_user.id

    # Start background export task
    task_manager = get_task_manager()
    task = task_manager.create_task(
        user_id=current_user.id,
        task_type="template_export",
        metadata={
            "template_id": str(base_id),
            "template_name": export_data.name,
            "project_slug": project_slug,
        },
    )

    async def _run_export():
        from ..database import AsyncSessionLocal
        from ..services.template_export import export_project_to_archive
        from ..services.template_storage import get_template_storage

        try:
            task.update_progress(5, 100, "Preparing export...")

            # Determine the project path
            use_volumes = os.getenv("USE_DOCKER_VOLUMES", "true").lower() == "true"
            if settings.deployment_mode == "docker" and use_volumes:
                project_path = f"/projects/{proj_slug}"
            elif settings.deployment_mode == "kubernetes":
                # K8s: We need to reconstruct from DB files
                import tempfile

                project_path = tempfile.mkdtemp(prefix=f"export-{proj_slug}-")
                async with AsyncSessionLocal() as export_db:
                    result = await export_db.execute(
                        select(ProjectFile).where(ProjectFile.project_id == proj_id)
                    )
                    db_files = result.scalars().all()

                    for db_file in db_files:
                        file_full_path = os.path.join(project_path, db_file.file_path)
                        os.makedirs(os.path.dirname(file_full_path), exist_ok=True)
                        with open(file_full_path, "w") as f:
                            f.write(db_file.content or "")

                    logger.info(f"[TEMPLATE] Reconstructed {len(db_files)} files for K8s export")
            else:
                project_path = os.path.join("/app/projects", proj_slug)

            if not os.path.exists(project_path):
                raise FileNotFoundError(
                    f"Project directory not found: {project_path}. "
                    "Make sure the project containers are running."
                )

            # Create archive
            archive_bytes = await export_project_to_archive(
                project_path,
                task=task,
                max_size_mb=settings.template_max_size_mb,
            )

            # Store archive
            storage = get_template_storage()
            archive_path = await storage.store_archive(user_id, base_id, archive_bytes)

            # Update the marketplace base record
            async with AsyncSessionLocal() as update_db:
                result = await update_db.execute(
                    select(MarketplaceBase).where(MarketplaceBase.id == base_id)
                )
                base = result.scalar_one()
                base.archive_path = archive_path
                base.archive_size_bytes = len(archive_bytes)
                await update_db.commit()

            task.update_progress(100, 100, "Template exported successfully!")
            task.result = {"template_id": str(base_id), "slug": template_slug}

            # Cleanup temp dir for K8s
            if settings.deployment_mode == "kubernetes" and project_path.startswith("/tmp"):
                shutil.rmtree(project_path, ignore_errors=True)

        except Exception as e:
            logger.error(f"[TEMPLATE] Export failed: {e}", exc_info=True)
            task.error = str(e)

    background_tasks.add_task(_run_export)

    return {
        "id": str(base_id),
        "slug": template_slug,
        "task_id": task.id,
    }


@router.get("/{project_slug}/download-tesslate")
async def download_tesslate_folder(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Download the .tesslate/ folder as a ZIP archive.

    Contains trajectory logs, subagent trajectories, and mirrored plans.
    Uses the orchestrator abstraction for platform-agnostic file access.
    """
    import io
    import zipfile

    from fastapi.responses import StreamingResponse

    from ..services.orchestration import get_orchestrator

    project = await get_project_by_slug(db, project_slug, current_user.id)
    orchestrator = get_orchestrator()

    # Get the first container for file access
    container_result = await db.execute(
        select(Container).where(Container.project_id == project.id).limit(1)
    )
    container = container_result.scalar_one_or_none()
    container_name = None
    container_directory = None
    if container:
        container_name = (
            container.directory if container.directory and container.directory != "." else None
        )
        if container.directory and container.directory != ".":
            container_directory = container.directory

    # List .tesslate directory contents via execute_command (recursive find)
    try:
        result = await orchestrator.execute_command(
            user_id=current_user.id,
            project_id=project.id,
            container_name=container_name,
            command="find .tesslate -type f 2>/dev/null || true",
            project_slug=project.slug,
        )
        stdout = ""
        if isinstance(result, dict):
            stdout = result.get("stdout", "") or result.get("output", "")
        elif isinstance(result, str):
            stdout = result

        file_paths = [p.strip() for p in stdout.strip().split("\n") if p.strip()]
    except Exception as e:
        logger.warning(f"[DOWNLOAD-TESSLATE] Failed to list .tesslate: {e}")
        file_paths = []

    if not file_paths:
        raise HTTPException(status_code=404, detail="No .tesslate/ data found for this project")

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in file_paths:
            try:
                content = await orchestrator.read_file(
                    user_id=current_user.id,
                    project_id=project.id,
                    container_name=container_name,
                    file_path=fp,
                    project_slug=project.slug,
                    subdir=container_directory,
                )
                if content is not None:
                    zf.writestr(fp, content)
            except Exception as e:
                logger.debug(f"[DOWNLOAD-TESSLATE] Skipping {fp}: {e}")

    buf.seek(0)
    filename = f"{project.slug}-tesslate.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{project_id}/fork", response_model=ProjectSchema)
async def fork_project(
    project_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fork (duplicate) a project with all its files.
    Creates a new project with the same files as the original.
    """
    # Get source project
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    source_project = result.scalar_one_or_none()
    if not source_project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Enforce project limit (same check as create_project)
    await enforce_project_limit(current_user, db)

    try:
        logger.info(f"[FORK] Forking project {project_id} for user {current_user.id}")

        # Generate unique slug for the forked project
        forked_name = f"{source_project.name} (Fork)"
        project_slug = generate_project_slug(forked_name)

        # Handle collision (retry with new slug)
        max_retries = 10
        for attempt in range(max_retries):
            try:
                # Create new project
                forked_project = Project(
                    name=forked_name,
                    slug=project_slug,
                    description=f"Forked from: {source_project.description or source_project.name}",
                    owner_id=current_user.id,
                )
                db.add(forked_project)
                await db.flush()
                break
            except Exception as e:
                if (
                    "unique constraint" in str(e).lower()
                    and "slug" in str(e).lower()
                    and attempt < max_retries - 1
                ):
                    # Generate new slug and retry
                    project_slug = generate_project_slug(forked_name)
                    await db.rollback()
                    continue
                raise

        logger.info(f"[FORK] Created new project {forked_project.id}")

        # Copy all files from source project
        files_result = await db.execute(
            select(ProjectFile).where(ProjectFile.project_id == project_id)
        )
        source_files = files_result.scalars().all()

        files_copied = 0
        for source_file in source_files:
            forked_file = ProjectFile(
                project_id=forked_project.id,
                file_path=source_file.file_path,
                content=source_file.content,
            )
            db.add(forked_file)
            files_copied += 1

        # Copy containers and build old_id → new_id map
        container_id_map = {}
        containers_result = await db.execute(
            select(Container).where(Container.project_id == project_id)
        )
        source_containers = containers_result.scalars().all()

        for src_container in source_containers:
            new_container = Container(
                project_id=forked_project.id,
                base_id=src_container.base_id,
                name=src_container.name,
                directory=src_container.directory,
                container_name=f"{forked_project.slug}-{src_container.name}",
                port=src_container.port,
                internal_port=src_container.internal_port,
                environment_vars=src_container.environment_vars,
                dockerfile_path=src_container.dockerfile_path,
                volume_name=None,
                container_type=src_container.container_type,
                service_slug=src_container.service_slug,
                deployment_mode=src_container.deployment_mode,
                external_endpoint=src_container.external_endpoint,
                credentials_id=None,
                position_x=src_container.position_x,
                position_y=src_container.position_y,
                status="stopped",
            )
            db.add(new_container)
            await db.flush()
            container_id_map[src_container.id] = new_container.id

        # Copy container connections (remap IDs)
        connections_copied = 0
        connections_result = await db.execute(
            select(ContainerConnection).where(ContainerConnection.project_id == project_id)
        )
        source_connections = connections_result.scalars().all()

        for src_conn in source_connections:
            new_source_id = container_id_map.get(src_conn.source_container_id)
            new_target_id = container_id_map.get(src_conn.target_container_id)
            if new_source_id is None or new_target_id is None:
                continue
            new_conn = ContainerConnection(
                project_id=forked_project.id,
                source_container_id=new_source_id,
                target_container_id=new_target_id,
                connection_type=src_conn.connection_type,
                connector_type=src_conn.connector_type,
                config=src_conn.config,
                label=src_conn.label,
            )
            db.add(new_conn)
            connections_copied += 1

        # Copy browser previews (remap container ID)
        previews_result = await db.execute(
            select(BrowserPreview).where(BrowserPreview.project_id == project_id)
        )
        source_previews = previews_result.scalars().all()

        for src_preview in source_previews:
            if src_preview.connected_container_id is not None:
                new_container_id = container_id_map.get(src_preview.connected_container_id)
                if new_container_id is None:
                    continue  # source container wasn't copied (shouldn't happen)
            else:
                new_container_id = None  # preserve unconnected preview
            new_preview = BrowserPreview(
                project_id=forked_project.id,
                connected_container_id=new_container_id,
                position_x=src_preview.position_x,
                position_y=src_preview.position_y,
                current_path=src_preview.current_path,
            )
            db.add(new_preview)

        # Single atomic commit — all or nothing
        await db.commit()
        await db.refresh(forked_project)

        logger.info(
            f"[FORK] Copied {files_copied} files, {len(container_id_map)} containers, "
            f"{connections_copied} connections to project {forked_project.id}"
        )

        return forked_project

    except Exception as e:
        await db.rollback()
        logger.error(f"[FORK] Failed to fork project: {e}", exc_info=True)
        if "forked_project" in locals():
            try:
                await db.delete(forked_project)
                await db.commit()
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to fork project: {str(e)}") from e


# ============================================================================
# Asset Management Endpoints
# ============================================================================

# Allowed file types for asset uploads
ALLOWED_MIME_TYPES = {
    # Images
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/svg+xml",
    "image/webp",
    "image/bmp",
    "image/ico",
    "image/x-icon",
    # Videos
    "video/mp4",
    "video/webm",
    "video/ogg",
    "video/quicktime",
    "video/x-msvideo",
    # Fonts
    "font/woff",
    "font/woff2",
    "font/ttf",
    "font/otf",
    "application/font-woff",
    "application/font-woff2",
    "application/x-font-ttf",
    "application/x-font-otf",
    # Documents
    "application/pdf",
    # Audio
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
    "audio/webm",
}

# Maximum file size: 20MB
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB in bytes


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent security issues."""
    # Remove path components
    filename = os.path.basename(filename)
    # Replace spaces with hyphens
    filename = filename.replace(" ", "-")
    # Remove special characters except alphanumeric, dash, underscore, and dot
    filename = re.sub(r"[^\w\-.]", "_", filename)
    # Remove multiple dots (except before extension)
    name, ext = os.path.splitext(filename)
    name = name.replace(".", "_")
    return f"{name}{ext}"


def get_file_type(mime_type: str) -> str:
    """Determine file type category from MIME type."""
    if mime_type.startswith("image/"):
        return "image"
    elif mime_type.startswith("video/"):
        return "video"
    elif mime_type.startswith("font/") or "font" in mime_type:
        return "font"
    elif mime_type == "application/pdf":
        return "document"
    elif mime_type.startswith("audio/"):
        return "audio"
    else:
        return "other"


async def get_image_dimensions(file_path: str) -> tuple:
    """Get image dimensions using PIL."""
    try:
        from PIL import Image

        with Image.open(file_path) as img:
            return img.size  # Returns (width, height)
    except Exception as e:
        logger.warning(f"Could not get image dimensions for {file_path}: {e}")
        return (None, None)


@router.get("/{project_slug}/assets/directories")
async def list_asset_directories(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all asset directories for this project.
    Scans the filesystem for directories and merges with database records.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id

    directories_set = set()

    # Get directories from database (directories with assets)
    result = await db.execute(
        select(ProjectAsset.directory).where(ProjectAsset.project_id == project_id).distinct()
    )
    db_directories = [row[0] for row in result.all()]
    directories_set.update(db_directories)

    # Also scan filesystem for empty directories
    try:
        settings = get_settings()
        project_path = get_project_path(current_user.id, project_id)

        if settings.deployment_mode == "docker":
            # Scan filesystem for directories
            if os.path.exists(project_path):
                from ..utils.async_fileio import walk_directory_async

                # Use async walk to avoid blocking
                walk_results = await walk_directory_async(
                    project_path, exclude_dirs=["node_modules", ".git", "dist", "build", ".next"]
                )
                for root, dirs, _files in walk_results:
                    for dir_name in dirs:
                        dir_full_path = os.path.join(root, dir_name)
                        # Get relative path from project root
                        rel_path = os.path.relpath(dir_full_path, project_path)
                        # Convert to forward slashes and add leading slash
                        rel_path = "/" + rel_path.replace("\\", "/")
                        # Skip hidden directories
                        if not any(part.startswith(".") for part in rel_path.split("/")):
                            directories_set.add(rel_path)
        else:
            # Kubernetes mode - no local filesystem to scan
            pass

    except Exception as e:
        logger.warning(f"Failed to scan filesystem for directories: {e}")

    # Include persisted directory records from DB (works for both modes)
    try:
        dir_result = await db.execute(
            select(ProjectAssetDirectory.path).where(ProjectAssetDirectory.project_id == project_id)
        )
        persisted_dirs = [row[0] for row in dir_result.all()]
        directories_set.update(persisted_dirs)
    except Exception:
        pass  # Table may not exist yet during migration

    return {"directories": sorted(directories_set)}


@router.post("/{project_slug}/assets/directories")
async def create_asset_directory(
    project_slug: str,
    directory_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new directory for assets.
    This creates the physical directory in the project filesystem.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id

    directory_path = directory_data.get("path", "").strip("/")
    if not directory_path:
        raise HTTPException(status_code=400, detail="Directory path is required")

    # Validate directory path (prevent path traversal)
    if ".." in directory_path or directory_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid directory path")

    try:
        settings = get_settings()
        project_path = get_project_path(current_user.id, project_id)
        full_dir_path = os.path.join(project_path, directory_path)

        if settings.deployment_mode == "docker":
            # Create directory on filesystem
            os.makedirs(full_dir_path, exist_ok=True)
            logger.info(f"[ASSETS] Created directory: {full_dir_path}")
        else:
            # Kubernetes mode - create directory in container
            from ..services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()

            # Use exec to create directory in container
            command = ["/bin/sh", "-c", f"mkdir -p {shlex.quote(f'/app/{directory_path}')}"]
            await orchestrator.execute_command(
                user_id=current_user.id,
                project_id=project_id,
                container_name=None,
                command=command,
                timeout=30,
            )
            logger.info(f"[ASSETS] Created directory in container: {directory_path}")

        # Persist directory record to DB (idempotent)
        normalized_path = f"/{directory_path}"
        existing_dir = await db.scalar(
            select(ProjectAssetDirectory).where(
                ProjectAssetDirectory.project_id == project_id,
                ProjectAssetDirectory.path == normalized_path,
            )
        )
        if not existing_dir:
            db_dir = ProjectAssetDirectory(project_id=project_id, path=normalized_path)
            db.add(db_dir)
            await db.commit()
            logger.info(f"[ASSETS] Persisted directory record: {normalized_path}")

        return {"message": "Directory created", "path": directory_path}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[ASSETS] Failed to create directory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create directory: {str(e)}") from e


@router.post("/{project_slug}/assets/upload")
async def upload_asset(
    project_slug: str,
    file: UploadFile = File(...),
    directory: str = Form(...),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload an asset file to a specified directory.

    Validates:
    - File size (20MB max)
    - File type (images, videos, fonts, PDFs only)
    - Filename (sanitized)

    Stores the file in the project's filesystem and records metadata in the database.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id

    # Validate directory path
    directory = directory.strip("/")
    if ".." in directory or directory.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid directory path")

    try:
        # Read file content
        content = await file.read()
        file_size = len(content)

        # Validate file size (20MB max)
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File size ({file_size / 1024 / 1024:.2f}MB) exceeds maximum allowed size (20MB)",
            )

        # Detect MIME type
        mime_type = (
            file.content_type
            or mimetypes.guess_type(file.filename)[0]
            or "application/octet-stream"
        )

        # Validate file type
        if mime_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File type {mime_type} is not allowed. Only images, videos, fonts, and PDFs are supported.",
            )

        # Sanitize filename
        safe_filename = sanitize_filename(file.filename)
        file_type = get_file_type(mime_type)

        # Get project path
        settings = get_settings()
        project_path = get_project_path(current_user.id, project_id)

        # Create assets directory path
        assets_dir = os.path.join(project_path, directory)
        file_path_relative = f"{directory}/{safe_filename}".lstrip("/")
        file_path_absolute = os.path.join(project_path, file_path_relative)

        # Check for duplicate filename
        existing_asset = await db.scalar(
            select(ProjectAsset).where(
                ProjectAsset.project_id == project_id,
                ProjectAsset.directory == f"/{directory}",
                ProjectAsset.filename == safe_filename,
            )
        )

        if existing_asset:
            # Auto-increment filename
            name, ext = os.path.splitext(safe_filename)
            counter = 1
            while existing_asset:
                safe_filename = f"{name}-{counter}{ext}"
                file_path_relative = f"{directory}/{safe_filename}".lstrip("/")
                file_path_absolute = os.path.join(project_path, file_path_relative)
                existing_asset = await db.scalar(
                    select(ProjectAsset).where(
                        ProjectAsset.project_id == project_id,
                        ProjectAsset.directory == f"/{directory}",
                        ProjectAsset.filename == safe_filename,
                    )
                )
                counter += 1

        # Write file to filesystem or pod
        if settings.deployment_mode == "docker":
            # Create directory if it doesn't exist
            os.makedirs(assets_dir, exist_ok=True)

            # Write file
            with open(file_path_absolute, "wb") as f:
                f.write(content)

            logger.info(f"[ASSETS] Saved file to: {file_path_absolute}")
        else:
            # Kubernetes mode - write to container
            from ..services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()

            # Write binary file to container using tar streaming
            # (echo|base64 approach breaks for files >100KB due to ARG_MAX)
            await orchestrator.write_binary_to_container(
                project_id=project_id,
                file_path=file_path_relative,
                data=content,
            )

            logger.info(f"[ASSETS] Saved file to container: {file_path_relative}")

        # Get image dimensions if it's an image
        width, height = None, None
        if file_type == "image" and settings.deployment_mode == "docker":
            width, height = await get_image_dimensions(file_path_absolute)

        # Create database record
        db_asset = ProjectAsset(
            project_id=project_id,
            filename=safe_filename,
            directory=f"/{directory}",
            file_path=file_path_relative,
            file_type=file_type,
            file_size=file_size,
            mime_type=mime_type,
            width=width,
            height=height,
        )
        db.add(db_asset)
        await db.commit()
        await db.refresh(db_asset)

        logger.info(f"[ASSETS] Asset uploaded successfully: {safe_filename}")

        return {
            "id": str(db_asset.id),
            "filename": db_asset.filename,
            "directory": db_asset.directory,
            "file_path": db_asset.file_path,
            "file_type": db_asset.file_type,
            "file_size": db_asset.file_size,
            "mime_type": db_asset.mime_type,
            "width": db_asset.width,
            "height": db_asset.height,
            "created_at": db_asset.created_at.isoformat(),
            "url": f"/api/projects/{project_slug}/assets/{db_asset.id}/file",
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[ASSETS] Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload asset: {str(e)}") from e


@router.get("/{project_slug}/assets")
async def list_assets(
    project_slug: str,
    directory: str | None = Query(None),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all assets for a project, optionally filtered by directory.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    query = select(ProjectAsset).where(ProjectAsset.project_id == project.id)

    if directory:
        directory = f"/{directory.strip('/')}"
        query = query.where(ProjectAsset.directory == directory)

    query = query.order_by(ProjectAsset.created_at.desc())

    result = await db.execute(query)
    assets = result.scalars().all()

    return {
        "assets": [
            {
                "id": str(asset.id),
                "filename": asset.filename,
                "directory": asset.directory,
                "file_path": asset.file_path,
                "file_type": asset.file_type,
                "file_size": asset.file_size,
                "mime_type": asset.mime_type,
                "width": asset.width,
                "height": asset.height,
                "created_at": asset.created_at.isoformat(),
                "url": f"/api/projects/{project_slug}/assets/{asset.id}/file",
            }
            for asset in assets
        ]
    }


@router.get("/{project_slug}/assets/{asset_id}/file")
async def get_asset_file(
    project_slug: str,
    asset_id: UUID,
    auth_token: str | None = Query(None),
    current_user: User | None = Depends(current_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Serve the actual asset file.
    Supports both cookie/Bearer token and query parameter token for image loading.
    """
    # If no current_user from cookie/Bearer, try auth_token query parameter
    if not current_user and auth_token:
        try:
            from jose import jwt as jose_jwt

            auth_settings = get_settings()
            payload = jose_jwt.decode(
                auth_token,
                auth_settings.secret_key,
                algorithms=[auth_settings.algorithm],
                audience="fastapi-users:auth",
            )
            user_id = payload.get("sub")
            if user_id:
                token_user = await db.get(User, UUID(user_id))
                if token_user and token_user.is_active:
                    current_user = token_user
        except Exception:
            pass

    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    project = await get_project_by_slug(db, project_slug, current_user.id)

    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Asset not found")

    settings = get_settings()
    project_path = get_project_path(current_user.id, project.id)
    file_path = os.path.join(project_path, asset.file_path)

    if settings.deployment_mode == "docker":
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Asset file not found on disk")

        return FileResponse(file_path, media_type=asset.mime_type, filename=asset.filename)
    else:
        # Kubernetes mode - read binary file from container using base64
        from ..services.orchestration import get_orchestrator

        orchestrator = get_orchestrator()

        try:
            import base64 as b64module

            result = await orchestrator.execute_command(
                user_id=current_user.id,
                project_id=project.id,
                container_name=None,
                command=["/bin/sh", "-c", f"base64 {shlex.quote(f'/app/{asset.file_path}')}"],
                timeout=30,
            )

            if not result or not result.strip():
                raise HTTPException(status_code=404, detail="Asset file not found in container")

            # Remove all whitespace (base64 command outputs 76-char lines with newlines)
            clean_b64 = "".join(result.split())
            binary_content = b64module.b64decode(clean_b64)

            from fastapi.responses import Response

            return Response(content=binary_content, media_type=asset.mime_type)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[ASSETS] Failed to read asset from container: {e}")
            raise HTTPException(
                status_code=404, detail="Asset file not found in container"
            ) from None


@router.delete("/{project_slug}/assets/{asset_id}")
async def delete_asset(
    project_slug: str,
    asset_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete an asset and its file from the filesystem.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Asset not found")

    try:
        project_path = get_project_path(current_user.id, project.id)
        file_path = os.path.join(project_path, asset.file_path)

        # Delete file from filesystem or container
        from ..services.orchestration import is_docker_mode

        if is_docker_mode():
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"[ASSETS] Deleted file: {file_path}")
        else:
            # Kubernetes mode - delete from container
            from ..services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()

            await orchestrator.execute_command(
                user_id=current_user.id,
                project_id=project.id,
                container_name=None,
                command=["/bin/sh", "-c", f"rm -f /app/{asset.file_path}"],
                timeout=30,
            )
            logger.info(f"[ASSETS] Deleted file from container: {asset.file_path}")

        # Delete database record
        await db.delete(asset)
        await db.commit()

        return {"message": "Asset deleted successfully"}

    except Exception as e:
        await db.rollback()
        logger.error(f"[ASSETS] Delete failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete asset: {str(e)}") from e


@router.patch("/{project_slug}/assets/{asset_id}/rename")
async def rename_asset(
    project_slug: str,
    asset_id: UUID,
    rename_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Rename an asset file.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Asset not found")

    new_filename = rename_data.get("new_filename", "").strip()
    if not new_filename:
        raise HTTPException(status_code=400, detail="New filename is required")

    # Sanitize new filename
    new_filename = sanitize_filename(new_filename)

    # Check for duplicates
    existing_asset = await db.scalar(
        select(ProjectAsset).where(
            ProjectAsset.project_id == project.id,
            ProjectAsset.directory == asset.directory,
            ProjectAsset.filename == new_filename,
            ProjectAsset.id != asset_id,
        )
    )

    if existing_asset:
        raise HTTPException(
            status_code=400, detail="An asset with this name already exists in this directory"
        )

    try:
        project_path = get_project_path(current_user.id, project.id)

        old_file_path = os.path.join(project_path, asset.file_path)
        new_file_path_relative = f"{asset.directory.strip('/')}/{new_filename}".lstrip("/")
        new_file_path_absolute = os.path.join(project_path, new_file_path_relative)

        # Rename file in filesystem or container
        from ..services.orchestration import get_orchestrator, is_docker_mode

        if is_docker_mode():
            if os.path.exists(old_file_path):
                os.rename(old_file_path, new_file_path_absolute)
                logger.info(f"[ASSETS] Renamed file: {old_file_path} -> {new_file_path_absolute}")
        else:
            # Kubernetes mode
            orchestrator = get_orchestrator()

            await orchestrator.execute_command(
                user_id=current_user.id,
                project_id=project.id,
                container_name=None,
                command=[
                    "/bin/sh",
                    "-c",
                    f"mv /app/{asset.file_path} /app/{new_file_path_relative}",
                ],
                timeout=30,
            )
            logger.info(
                f"[ASSETS] Renamed file in container: {asset.file_path} -> {new_file_path_relative}"
            )

        # Update database record
        asset.filename = new_filename
        asset.file_path = new_file_path_relative
        await db.commit()
        await db.refresh(asset)

        return {
            "id": str(asset.id),
            "filename": asset.filename,
            "file_path": asset.file_path,
            "message": "Asset renamed successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[ASSETS] Rename failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to rename asset: {str(e)}") from e


@router.patch("/{project_slug}/assets/{asset_id}/move")
async def move_asset(
    project_slug: str,
    asset_id: UUID,
    move_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Move an asset to a different directory.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Asset not found")

    new_directory = move_data.get("directory", "").strip("/")
    if not new_directory:
        raise HTTPException(status_code=400, detail="New directory is required")

    # Validate directory path
    if ".." in new_directory:
        raise HTTPException(status_code=400, detail="Invalid directory path")

    new_directory = f"/{new_directory}"

    # Check if moving to same directory
    if new_directory == asset.directory:
        return {"message": "Asset is already in this directory"}

    try:
        project_path = get_project_path(current_user.id, project.id)

        old_file_path = os.path.join(project_path, asset.file_path)
        new_file_path_relative = f"{new_directory.strip('/')}/{asset.filename}".lstrip("/")
        new_file_path_absolute = os.path.join(project_path, new_file_path_relative)

        # Move file in filesystem or container
        from ..services.orchestration import get_orchestrator, is_docker_mode

        if is_docker_mode():
            # Ensure new directory exists (async to avoid blocking)
            new_dir_absolute = os.path.dirname(new_file_path_absolute)
            await asyncio.to_thread(os.makedirs, new_dir_absolute, exist_ok=True)

            if os.path.exists(old_file_path):
                # Use async to avoid blocking on large files
                await asyncio.to_thread(shutil.move, old_file_path, new_file_path_absolute)
                logger.info(f"[ASSETS] Moved file: {old_file_path} -> {new_file_path_absolute}")
        else:
            # Kubernetes mode
            orchestrator = get_orchestrator()

            # Ensure directory exists and move file
            await orchestrator.execute_command(
                user_id=current_user.id,
                project_id=project.id,
                container_name=None,
                command=[
                    "/bin/sh",
                    "-c",
                    f"mkdir -p /app/{new_directory.strip('/')} && mv /app/{asset.file_path} /app/{new_file_path_relative}",
                ],
                timeout=30,
            )
            logger.info(
                f"[ASSETS] Moved file in container: {asset.file_path} -> {new_file_path_relative}"
            )

        # Update database record
        asset.directory = new_directory
        asset.file_path = new_file_path_relative
        await db.commit()
        await db.refresh(asset)

        return {
            "id": str(asset.id),
            "directory": asset.directory,
            "file_path": asset.file_path,
            "message": "Asset moved successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[ASSETS] Move failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to move asset: {str(e)}") from e


# ============================================================================
# Deployment Management (for billing/premium features)
# ============================================================================


@router.post("/{project_slug}/deploy")
async def deploy_project(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a project as deployed (keeps container running permanently).
    This is a premium feature with tier-based limits.
    """
    # Get project
    project = await get_project_by_slug(db, project_slug, current_user.id)

    # Check if already deployed
    if project.is_deployed:
        return {"message": "Project is already deployed", "project_id": str(project.id)}

    # Check deployment limits
    from ..config import get_settings

    settings = get_settings()

    # Count current deployed projects
    deployed_count_result = await db.execute(
        select(func.count(Project.id)).where(
            and_(Project.owner_id == current_user.id, Project.is_deployed)
        )
    )
    deployed_count = deployed_count_result.scalar()

    # Determine max deploys based on tier
    max_deploys = settings.get_tier_max_deploys(current_user.subscription_tier or "free")

    # Check if limit exceeded
    if deployed_count >= max_deploys:
        # Check if user has purchased additional deploy slots
        # For now, we'll use total_spend to track additional purchases
        # In a real system, you'd have a separate table for tracking this
        additional_slots_purchased = current_user.total_spend // settings.additional_deploy_price
        effective_max_deploys = max_deploys + additional_slots_purchased

        if deployed_count >= effective_max_deploys:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "message": f"Deploy limit reached. Your {current_user.subscription_tier} tier allows {max_deploys} deployed project(s).",
                    "current_deployed": deployed_count,
                    "max_deploys": effective_max_deploys,
                    "upgrade_required": True,
                    "purchase_additional_url": "/api/billing/deploy/purchase",
                },
            )

    # Mark as deployed
    project.is_deployed = True
    project.deploy_type = "deployed"
    project.deployed_at = datetime.now(UTC)
    current_user.deployed_projects_count += 1

    await db.commit()

    logger.info(f"[DEPLOY] Project {project_slug} deployed for user {current_user.id}")

    return {
        "message": "Project deployed successfully",
        "project_id": str(project.id),
        "deployed_at": project.deployed_at.isoformat(),
    }


@router.delete("/{project_slug}/deploy")
async def undeploy_project(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove deployment status from a project (allows container to be stopped when idle).
    """
    # Get project
    project = await get_project_by_slug(db, project_slug, current_user.id)

    if not project.is_deployed:
        return {"message": "Project is not deployed", "project_id": str(project.id)}

    # Undeploy
    project.is_deployed = False
    project.deploy_type = "development"
    project.deployed_at = None
    current_user.deployed_projects_count = max(0, current_user.deployed_projects_count - 1)

    await db.commit()

    logger.info(f"[DEPLOY] Project {project_slug} undeployed for user {current_user.id}")

    return {"message": "Project undeployed successfully", "project_id": str(project.id)}


@router.get("/deployment/limits")
async def get_deployment_limits(
    current_user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    """
    Get current deployment limits and usage for the user.
    """
    from ..config import get_settings

    settings = get_settings()

    # Count deployed projects
    deployed_count_result = await db.execute(
        select(func.count(Project.id)).where(
            and_(Project.owner_id == current_user.id, Project.is_deployed)
        )
    )
    deployed_count = deployed_count_result.scalar()

    # Determine limits based on tier
    tier = current_user.subscription_tier or "free"
    base_max_deploys = settings.get_tier_max_deploys(tier)
    base_max_projects = settings.get_tier_max_projects(tier)

    # Calculate additional slots from purchases
    additional_slots = current_user.total_spend // settings.additional_deploy_price
    effective_max_deploys = base_max_deploys + additional_slots

    # Count total projects
    total_projects_result = await db.execute(
        select(func.count(Project.id)).where(Project.owner_id == current_user.id)
    )
    total_projects = total_projects_result.scalar()

    return {
        "tier": current_user.subscription_tier,
        "projects": {"current": total_projects, "max": base_max_projects},
        "deploys": {
            "current": deployed_count,
            "base_max": base_max_deploys,
            "additional_purchased": additional_slots,
            "effective_max": effective_max_deploys,
        },
        "can_deploy_more": deployed_count < effective_max_deploys,
        "can_create_more_projects": total_projects < base_max_projects,
    }


@router.post("/deployment/purchase-slot")
async def purchase_additional_deploy_slot(
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a checkout session for purchasing an additional deploy slot.
    """
    from ..config import get_settings
    from ..services.stripe_service import stripe_service

    settings = get_settings()

    # Use origin-based URLs to preserve user's domain
    origin = (
        request.headers.get("origin")
        or request.headers.get("referer", "").rstrip("/").split("?")[0].rsplit("/", 1)[0]
        or settings.get_app_base_url
    )
    success_url = f"{origin}/billing/deploy/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/projects"

    session = await stripe_service.create_deploy_purchase_checkout(
        user=current_user, success_url=success_url, cancel_url=cancel_url, db=db
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session",
        )

    return {"checkout_url": session["url"], "session_id": session["id"]}


# WebSocket endpoint for streaming container logs
@router.websocket("/{project_slug}/logs/stream")
async def stream_container_logs(
    websocket: WebSocket, project_slug: str, db: AsyncSession = Depends(get_db)
):
    """
    WebSocket endpoint to stream container logs in real-time.

    Protocol:
        Server -> Client: {"type": "containers", "data": [{id, name, status, type}]}
        Server -> Client: {"type": "log", "data": "<line>", "container_id": "<uuid>"}
        Server -> Client: {"type": "error", "message": "<msg>"}
        Server -> Client: {"type": "pong"}
        Client -> Server: {"type": "switch_container", "container_id": "<uuid>"}
        Client -> Server: {"type": "ping"}
    """
    from fastapi import WebSocketDisconnect

    from ..services.orchestration import get_orchestrator

    await websocket.accept()

    try:
        # Get project with containers
        result = await db.execute(
            select(Project)
            .options(selectinload(Project.containers))
            .where(Project.slug == project_slug)
        )
        project = result.scalar_one_or_none()

        if not project:
            await websocket.send_json({"type": "error", "message": "Project not found"})
            await websocket.close()
            return

        # Send container list to client
        containers_data = [
            {
                "id": str(c.id),
                "name": c.name,
                "status": c.status or "unknown",
                "type": c.container_type or "dev",
            }
            for c in project.containers
        ]
        await websocket.send_json({"type": "containers", "data": containers_data})

        # Streaming with cancel support — wait for client to pick container
        cancel_event = asyncio.Event()
        stream_task = None

        async def _stream_logs(container_id: UUID, cancel_ev: asyncio.Event):
            try:
                orchestrator = get_orchestrator()
                async for line in orchestrator.stream_logs(
                    project.id, project.owner_id, container_id
                ):
                    if cancel_ev.is_set():
                        break
                    await websocket.send_json(
                        {"type": "log", "data": line, "container_id": str(container_id)}
                    )
            except Exception as e:
                logger.error(f"Error in log stream for container {container_id}: {e}")
                with contextlib.suppress(builtins.BaseException):
                    await websocket.send_json(
                        {"type": "error", "message": f"Log stream error: {str(e)}"}
                    )

        # Message receive loop — stream starts when client sends switch_container
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg_type == "switch_container":
                    # Cancel current stream before starting new one
                    cancel_event.set()
                    if stream_task and not stream_task.done():
                        stream_task.cancel()
                        with contextlib.suppress(Exception, asyncio.CancelledError):
                            await stream_task

                    # Start new stream for requested container
                    cancel_event = asyncio.Event()
                    new_container_id = UUID(data["container_id"])
                    stream_task = asyncio.create_task(_stream_logs(new_container_id, cancel_event))
        except WebSocketDisconnect:
            cancel_event.set()

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for project {project_slug}")
    except Exception as e:
        logger.error(f"WebSocket error for project {project_slug}: {e}")
        with contextlib.suppress(builtins.BaseException):
            await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        if "cancel_event" in locals():
            cancel_event.set()
        if "stream_task" in locals() and stream_task:
            stream_task.cancel()
        with contextlib.suppress(builtins.BaseException):
            await websocket.close()


@router.websocket("/{project_slug}/terminal")
async def interactive_terminal(
    websocket: WebSocket, project_slug: str, db: AsyncSession = Depends(get_db)
):
    """
    WebSocket endpoint for interactive terminal with PTY support.
    Provides full bidirectional shell access to the project's dev container.

    Message format:
    - Client -> Server: {"type": "input", "data": "command text"} or {"type": "resize", "cols": 80, "rows": 24}
    - Server -> Client: {"type": "output", "data": "terminal output"} or {"type": "error", "message": "error text"}
    """
    import json

    from fastapi import WebSocketDisconnect

    from ..services.pty_broker import get_pty_broker
    from ..services.shell_session_manager import ShellSessionManager

    await websocket.accept()
    session_id = None
    shell_manager = ShellSessionManager()
    output_task = None

    try:
        # Get project and verify ownership
        result = await db.execute(select(Project).where(Project.slug == project_slug))
        project = result.scalar_one_or_none()

        if not project:
            await websocket.send_json({"type": "error", "message": "Project not found"})
            await websocket.close()
            return

        # For now, we'll get user from project owner (in production, extract from JWT token)
        user_id = project.owner_id

        # Create shell session
        await websocket.send_json({"type": "status", "message": "Starting shell session..."})

        try:
            # Start a regular shell
            # Tmux runs the dev server in the background, but we don't attach to it
            # This avoids tmux's display layer conflicting with xterm.js
            # Users can run "tmux attach -t main" manually if they want full tmux features
            # Use 'exec' to replace the wrapper shell with an interactive shell
            session_info = await shell_manager.create_session(
                user_id=user_id, project_id=str(project.id), db=db, command="exec /bin/sh"
            )
            session_id = session_info["session_id"]

            # Track activity for idle cleanup (database-based)
            from ..services.activity_tracker import track_project_activity

            await track_project_activity(db, project.id, "terminal")

            await websocket.send_json(
                {"type": "status", "message": f"Shell session created: {session_id}"}
            )

        except HTTPException as e:
            await websocket.send_json({"type": "error", "message": e.detail})
            await websocket.close()
            return
        except Exception as e:
            logger.error(f"Failed to create shell session: {e}")
            await websocket.send_json(
                {"type": "error", "message": f"Failed to create shell: {str(e)}"}
            )
            await websocket.close()
            return

        # Get PTY session for direct access
        pty_broker = get_pty_broker()
        pty_session = pty_broker.sessions.get(session_id)

        if not pty_session:
            await websocket.send_json({"type": "error", "message": "PTY session not found"})
            await websocket.close()
            return

        # Send initial prompt
        await websocket.send_json(
            {
                "type": "output",
                "data": "\r\n\x1b[38;5;208m╔═══════════════════════════════════════╗\x1b[0m\r\n",
            }
        )
        await websocket.send_json(
            {
                "type": "output",
                "data": "\x1b[38;5;208m║   Tesslate Studio - Interactive Shell ║\x1b[0m\r\n",
            }
        )
        await websocket.send_json(
            {
                "type": "output",
                "data": "\x1b[38;5;208m╚═══════════════════════════════════════╝\x1b[0m\r\n\r\n",
            }
        )

        # Send any existing output history (scrollback) from the PTY buffer
        # This ensures clients see the full history, not just new output
        try:
            if pty_session and hasattr(pty_session, "output_buffer"):
                async with pty_session.buffer_lock:
                    if len(pty_session.output_buffer) > 0:
                        # Send existing buffer contents
                        existing_output = bytes(pty_session.output_buffer)
                        if existing_output:
                            await websocket.send_json(
                                {
                                    "type": "output",
                                    "data": existing_output.decode("utf-8", errors="replace"),
                                }
                            )
                            logger.info(
                                f"Sent {len(existing_output)} bytes of scrollback history to client"
                            )
        except Exception as e:
            logger.warning(f"Failed to send scrollback history: {e}")

        # Start background task to stream PTY output to WebSocket
        async def stream_output():
            """Stream PTY output to WebSocket"""
            try:
                while True:
                    # Read new output from PTY session
                    new_data, is_eof = await pty_session.read_new_output()

                    if new_data:
                        # Send raw output to client
                        await websocket.send_json(
                            {"type": "output", "data": new_data.decode("utf-8", errors="replace")}
                        )

                    if is_eof:
                        await websocket.send_json(
                            {"type": "status", "message": "Shell session ended"}
                        )
                        break

                    # Increased delay from 50ms to 100ms to reduce CPU usage
                    # This reduces polling from 20x/sec to 10x/sec per terminal
                    # while still maintaining responsive terminal feel
                    await asyncio.sleep(0.1)

            except WebSocketDisconnect:
                logger.info("WebSocket disconnected during output streaming")
            except Exception as e:
                logger.error(f"Error streaming output: {e}")
                with contextlib.suppress(builtins.BaseException):
                    await websocket.send_json(
                        {"type": "error", "message": f"Stream error: {str(e)}"}
                    )

        # Start output streaming task
        output_task = asyncio.create_task(stream_output())

        # Handle incoming messages from client
        while True:
            try:
                message = await websocket.receive_text()
                data = json.loads(message)

                if data.get("type") == "input":
                    # User input - send to PTY stdin
                    input_data = data.get("data", "")
                    await shell_manager.write_to_session(
                        session_id=session_id,
                        data=input_data.encode("utf-8"),
                        db=db,
                        user_id=user_id,
                    )

                elif data.get("type") == "resize":
                    # Terminal resize event
                    cols = data.get("cols", 80)
                    rows = data.get("rows", 24)

                    # Resize PTY
                    if pty_session and hasattr(pty_session, "resize"):
                        try:
                            await pty_session.resize(cols, rows)
                        except Exception as e:
                            logger.error(f"Failed to resize terminal: {e}")

            except WebSocketDisconnect:
                logger.info(f"Client disconnected from terminal {session_id}")
                break
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
            except Exception as e:
                logger.error(f"Error handling client message: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for project {project_slug}")
    except Exception as e:
        logger.error(f"Terminal WebSocket error for project {project_slug}: {e}")
        with contextlib.suppress(builtins.BaseException):
            await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        # Clean up output streaming task
        if output_task:
            output_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await output_task

        # Close shell session
        if session_id:
            try:
                await shell_manager.close_session(session_id=session_id, db=db)
                logger.info(f"Closed shell session {session_id}")
            except Exception as e:
                logger.error(f"Error closing session {session_id}: {e}")

        with contextlib.suppress(builtins.BaseException):
            await websocket.close()


# ============================================================================
# Container Management Endpoints (Node Graph / Monorepo)
# ============================================================================


@router.get("/{project_slug}/containers", response_model=list[ContainerSchema])
async def get_project_containers(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all containers for a project (for the React Flow node graph).
    Returns containers with their positions and base information.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    result = await db.execute(
        select(Container)
        .where(Container.project_id == project.id)
        .options(selectinload(Container.base))
    )
    containers = result.scalars().all()

    return [_container_response(c) for c in containers]


@router.post("/{project_slug}/containers")
async def add_container_to_project(
    project_slug: str,
    container_data: ContainerCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a base as a container to the project.

    This is a **NON-BLOCKING** operation. The container record is created immediately,
    but file copying happens in the background.

    Flow:
    1. User drags base from sidebar onto canvas
    2. Backend creates Container record immediately
    3. Backend starts background task to copy base files
    4. Frontend receives container data + task_id
    5. Frontend polls task status and shows progress
    6. Background task copies files, syncs to DB, updates docker-compose

    Returns:
        {
            "container": Container object,
            "task_id": UUID for tracking background initialization
        }
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    try:
        # Handle service containers differently from base containers
        if container_data.container_type == "service":
            # Service container (Postgres, Redis, etc.) or External service (Supabase, OpenAI, etc.)
            from ..services.deployment_encryption import get_deployment_encryption_service
            from ..services.service_definitions import ServiceType, get_service

            if not container_data.service_slug:
                raise HTTPException(
                    status_code=400, detail="service_slug required for service containers"
                )

            service_def = get_service(container_data.service_slug)
            if not service_def:
                raise HTTPException(
                    status_code=404, detail=f"Service '{container_data.service_slug}' not found"
                )

            # Use service definition for container config
            container_name = container_data.name or service_def.name
            container_directory = (
                f"services/{container_data.service_slug}"  # Services don't need a real directory
            )
            service_name = container_data.service_slug  # Use slug directly for service containers
            docker_container_name = f"{project.slug}-{service_name}"
            internal_port = service_def.internal_port
            base_name = None  # Services don't have bases
            git_repo_url = None
            resolved_base_id = None  # Services don't have a base

            # Handle external services
            deployment_mode = container_data.deployment_mode or "container"
            external_endpoint = container_data.external_endpoint
            credentials_id = None

            # Check if this is an external service that needs credentials stored
            is_external = (
                service_def.service_type in (ServiceType.EXTERNAL, ServiceType.HYBRID)
                and deployment_mode == "external"
            )

            if is_external and container_data.credentials:
                # Store credentials using DeploymentCredential model
                encryption_service = get_deployment_encryption_service()
                credential = DeploymentCredential(
                    user_id=current_user.id,
                    project_id=project.id,
                    provider=container_data.service_slug,
                    access_token_encrypted=encryption_service.encrypt(
                        # Store all credentials as JSON for flexibility
                        json.dumps(container_data.credentials)
                    ),
                    provider_metadata={
                        "service_type": service_def.service_type.value,
                        "external_endpoint": external_endpoint,
                    },
                )
                db.add(credential)
                await db.flush()  # Get the ID without committing
                credentials_id = credential.id
                logger.info(
                    f"[CONTAINER] Stored credentials for external service {container_data.service_slug}"
                )

        else:
            # Base container (marketplace base or builtin)
            resolved_base_id = None  # Will hold the actual UUID for the base

            if container_data.base_id == "builtin":
                base_name = "main"
                git_repo_url = None  # Built-in template, already in project
                resolved_base_id = None  # Built-in has no base_id
            else:
                # Try to find base by ID first, then by slug (for workflow templates)
                base = None
                base_id_str = str(container_data.base_id) if container_data.base_id else None

                # Check if it looks like a UUID
                is_uuid = False
                if base_id_str:
                    try:
                        import uuid as uuid_module

                        uuid_module.UUID(base_id_str)
                        is_uuid = True
                    except (ValueError, AttributeError):
                        is_uuid = False

                if is_uuid:
                    # Look up by ID
                    base_result = await db.execute(
                        select(MarketplaceBase).where(MarketplaceBase.id == container_data.base_id)
                    )
                    base = base_result.scalar_one_or_none()
                else:
                    # Look up by slug (for workflow templates that use base_slug)
                    base_result = await db.execute(
                        select(MarketplaceBase).where(MarketplaceBase.slug == base_id_str)
                    )
                    base = base_result.scalar_one_or_none()

                if not base:
                    raise HTTPException(
                        status_code=404, detail=f"Base not found: {container_data.base_id}"
                    )

                # Use display name (not slug) — user-submitted base slugs
                # include UUID+timestamp for uniqueness, which is too long for K8s names
                base_name = re.sub(r"[^a-z0-9]+", "-", base.name.lower()).strip("-")
                git_repo_url = base.git_repo_url
                resolved_base_id = base.id  # Use the actual UUID from the database

            # Determine container directory and name for base containers
            container_name = container_data.name or base_name

            # Sanitize the container name for Docker and directory naming
            # Docker normalizes names: lowercase, replace spaces/underscores/dots with hyphens, alphanumeric only
            service_name = (
                container_name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
            )
            service_name = "".join(c for c in service_name if c.isalnum() or c == "-")
            service_name = service_name.strip("-")  # Remove leading/trailing hyphens
            docker_container_name = f"{project.slug}-{service_name}"

            # Each container gets its own directory using the sanitized name
            # This creates a clean structure: project-abc123/next-js-15/, project-abc123/vite-react-fastapi/
            container_directory = service_name

            # Check for duplicate directory names - if exists, append a number suffix
            existing_containers = await db.execute(
                select(Container).where(Container.project_id == project.id)
            )
            existing_dirs = set()
            for existing in existing_containers.scalars().all():
                if existing.directory:
                    existing_dirs.add(existing.directory.lower())

            # If directory already exists, find a unique name by appending -2, -3, etc.
            if container_directory.lower() in existing_dirs:
                base_dir = container_directory
                counter = 2
                while f"{base_dir}-{counter}".lower() in existing_dirs:
                    counter += 1
                container_directory = f"{base_dir}-{counter}"
                container_name = f"{container_name} ({counter})"
                docker_container_name = f"{project.slug}-{container_directory}"
                logger.info(
                    f"[CONTAINER] Duplicate detected, using unique name: {container_name} -> {container_directory}"
                )

            # Auto-detect internal port based on framework
            internal_port = 5173  # Default to Vite
            if base_name:
                base_lower = base_name.lower()
                if "next" in base_lower:
                    internal_port = 3000  # Next.js
                elif "fastapi" in base_lower or "python" in base_lower:
                    internal_port = 8000  # FastAPI/Python
                elif "go" in base_lower:
                    internal_port = 8080  # Go
                elif "vite" in base_lower or "react" in base_lower:
                    internal_port = 5173  # Vite/React

            logger.info(f"[CONTAINER] Auto-detected port {internal_port} for base {base_name}")

            # Base containers don't have external service fields
            deployment_mode = "container"
            external_endpoint = None
            credentials_id = None

        # Create Container record
        # For external services, set status to 'connected' since they don't run as containers
        initial_status = "connected" if deployment_mode == "external" else "stopped"

        new_container = Container(
            project_id=project.id,
            base_id=resolved_base_id,
            name=container_name,
            directory=container_directory,
            container_name=docker_container_name,
            position_x=container_data.position_x,
            position_y=container_data.position_y,
            port=None,  # Will be auto-assigned
            internal_port=internal_port,  # Set framework-specific port
            container_type=container_data.container_type,
            service_slug=container_data.service_slug,
            status=initial_status,
            # External service fields
            deployment_mode=deployment_mode,
            external_endpoint=external_endpoint,
            credentials_id=credentials_id,
        )

        db.add(new_container)
        await db.commit()
        await db.refresh(new_container)
        hydrated_container_result = await db.execute(
            select(Container)
            .where(Container.id == new_container.id)
            .options(selectinload(Container.base))
        )
        new_container = hydrated_container_result.scalar_one()

        logger.info(
            f"[CONTAINER] Created {container_data.container_type} container {new_container.id} for project {project.id}"
        )

        # Only run initialization for base containers (not services)
        if container_data.container_type == "base":
            # Create background task for container initialization
            logger.info(
                f"[CONTAINER] About to create background task for container {new_container.id}"
            )
            task_manager = get_task_manager()
            logger.info(f"[CONTAINER] Got task_manager: {task_manager}")

            task = task_manager.create_task(
                user_id=current_user.id,
                task_type="container_initialization",
                metadata={
                    "container_id": str(new_container.id),
                    "project_id": str(project.id),
                    "container_name": container_name,
                    "base_name": base_name,
                },
            )

            # Start background task (non-blocking!) using FastAPI's BackgroundTasks
            # This ensures the task executes even after the response is sent
            from ..services.container_initializer import initialize_container_async

            logger.info("[CONTAINER] Adding task to FastAPI background_tasks")

            background_tasks.add_task(
                task_manager.run_task,
                task_id=task.id,
                coro=initialize_container_async,
                container_id=new_container.id,
                project_id=project.id,
                user_id=current_user.id,
                base_slug=base_name,
                git_repo_url=git_repo_url or "",
            )

            logger.info(
                f"[CONTAINER] Started background initialization task {task.id} for container {new_container.id}"
            )

            # Return immediately with container + task ID (non-blocking!)
            return {
                "container": new_container,
                "task_id": task.id,
                "status_endpoint": f"/api/tasks/{task.id}/status",
            }
        else:
            # Service containers don't need file initialization
            from ..services.orchestration import get_orchestrator, is_kubernetes_mode

            if not is_kubernetes_mode():
                # Docker mode: regenerate docker-compose.yml to include the new service
                logger.info("[CONTAINER] Service container created, regenerating docker-compose")

                containers_result = await db.execute(
                    select(Container)
                    .where(Container.project_id == project.id)
                    .options(selectinload(Container.base))
                )
                all_containers = containers_result.scalars().all()

                from ..models import ContainerConnection

                connections_result = await db.execute(
                    select(ContainerConnection).where(ContainerConnection.project_id == project.id)
                )
                all_connections = connections_result.scalars().all()

                orchestrator = get_orchestrator()
                env_overrides = await build_env_overrides(db, project.id, all_containers)
                await orchestrator.write_compose_file(
                    project,
                    all_containers,
                    all_connections,
                    current_user.id,
                    env_overrides,
                )
            else:
                # Kubernetes mode: service container will be started via
                # start_single_container endpoint (no compose file needed)
                logger.info(
                    "[CONTAINER] Service container created in K8s mode "
                    "(will be started via start_container)"
                )

            return {
                "container": new_container,
                "task_id": None,  # No task for service containers
                "status_endpoint": None,
            }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[CONTAINER] Failed to add container: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add container: {str(e)}") from e


# Container Connection Endpoints (must come before {container_id} routes!)


@router.get(
    "/{project_slug}/containers/connections", response_model=list[ContainerConnectionSchema]
)
async def get_container_connections(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all connections between containers in the project.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    result = await db.execute(
        select(ContainerConnection).where(ContainerConnection.project_id == project.id)
    )
    connections = result.scalars().all()

    return connections


@router.post("/{project_slug}/containers/connections", response_model=ContainerConnectionSchema)
async def create_container_connection(
    project_slug: str,
    connection_data: ContainerConnectionCreate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a connection between two containers (React Flow edge).
    This represents a dependency or network connection.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    try:
        # Verify both containers exist and belong to this project
        source = await db.get(Container, connection_data.source_container_id)
        target = await db.get(Container, connection_data.target_container_id)

        if not source or source.project_id != project.id:
            raise HTTPException(status_code=404, detail="Source container not found")
        if not target or target.project_id != project.id:
            raise HTTPException(status_code=404, detail="Target container not found")

        # Prevent duplicate connections between the same two containers
        existing = await db.execute(
            select(ContainerConnection).where(
                ContainerConnection.project_id == project.id,
                ContainerConnection.source_container_id == connection_data.source_container_id,
                ContainerConnection.target_container_id == connection_data.target_container_id,
            )
        )
        if existing.scalars().first():
            raise HTTPException(
                status_code=409, detail="Connection already exists between these containers"
            )

        # Auto-detect env vars to inject based on target type
        # One edge type: "connects to" — env vars are auto-injected into source
        connector_type = "env_injection"
        config = connection_data.config or {}
        env_mapping = {}
        label = connection_data.label

        if target.container_type == "service" and target.service_slug:
            # Target is infrastructure (postgres, redis, etc.)
            from ..services.secret_manager_env import resolve_connection_env_vars
            from ..services.service_definitions import get_service

            svc_def = get_service(target.service_slug)
            resolved = resolve_connection_env_vars(target, svc_def)
            if resolved:
                env_mapping = {k: k for k in resolved}
                # Set label to the primary env var
                if not label:
                    label = next(iter(resolved.keys()), None)
        elif target.container_type == "base":
            # Target is an app — inject URL env var into source
            target_name_upper = target.name.upper().replace("-", "_")
            target_port = target.internal_port or target.port or 3000
            env_key = f"{target_name_upper}_URL"
            env_value = f"http://{target.name}:{target_port}"
            env_mapping = {env_key: env_value}
            if not label:
                label = env_key

        if env_mapping:
            config["env_mapping"] = env_mapping

        # Create connection
        new_connection = ContainerConnection(
            project_id=project.id,
            source_container_id=connection_data.source_container_id,
            target_container_id=connection_data.target_container_id,
            connection_type="depends_on",
            connector_type=connector_type,
            config=config,
            label=label,
        )

        db.add(new_connection)
        await db.commit()
        await db.refresh(new_connection)

        logger.info(f"[CONTAINER] Created connection {new_connection.id} in project {project.id}")

        # Regenerate docker-compose.yml with updated depends_on
        try:
            from ..services.orchestration import get_orchestrator

            # Use selectinload to eagerly load the base relationship
            containers_result = await db.execute(
                select(Container)
                .where(Container.project_id == project.id)
                .options(selectinload(Container.base))  # Eagerly load base
            )
            all_containers = containers_result.scalars().all()

            connections_result = await db.execute(
                select(ContainerConnection).where(ContainerConnection.project_id == project.id)
            )
            all_connections = connections_result.scalars().all()

            orchestrator = get_orchestrator()
            env_overrides = await build_env_overrides(db, project.id, all_containers)
            await orchestrator.write_compose_file(
                project, all_containers, all_connections, current_user.id, env_overrides
            )

            logger.info("[CONTAINER] Updated docker-compose.yml with new connection")
        except Exception as e:
            logger.warning(f"[CONTAINER] Failed to update docker-compose.yml: {e}")

        return new_connection

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[CONTAINER] Failed to create connection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create connection: {str(e)}") from e


@router.delete("/{project_slug}/containers/connections/{connection_id}")
async def delete_container_connection(
    project_slug: str,
    connection_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a connection between containers.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    connection = await db.get(ContainerConnection, connection_id)
    if not connection or connection.project_id != project.id:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        await db.delete(connection)
        await db.commit()

        logger.info(f"[CONTAINER] Deleted connection {connection_id} from project {project.id}")

        # TODO: Update docker-compose.yml

        return {"message": "Connection deleted successfully"}

    except Exception as e:
        await db.rollback()
        logger.error(f"[CONTAINER] Failed to delete connection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete connection: {str(e)}") from e


# ============================================================================
# Browser Preview Endpoints
# ============================================================================


@router.get("/{project_slug}/browser-previews", response_model=list[BrowserPreviewSchema])
async def get_browser_previews(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all browser preview nodes for a project.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    result = await db.execute(select(BrowserPreview).where(BrowserPreview.project_id == project.id))
    previews = result.scalars().all()

    return previews


@router.post("/{project_slug}/browser-previews", response_model=BrowserPreviewSchema)
async def create_browser_preview(
    project_slug: str,
    preview_data: BrowserPreviewCreate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new browser preview node on the canvas.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    try:
        # If a container ID is provided, verify it exists in this project
        if preview_data.connected_container_id:
            container = await db.get(Container, preview_data.connected_container_id)
            if not container or container.project_id != project.id:
                raise HTTPException(status_code=404, detail="Connected container not found")

        preview = BrowserPreview(
            project_id=project.id,
            position_x=preview_data.position_x,
            position_y=preview_data.position_y,
            connected_container_id=preview_data.connected_container_id,
        )

        db.add(preview)
        await db.commit()
        await db.refresh(preview)

        logger.info(f"[BROWSER] Created browser preview {preview.id} for project {project.id}")

        return preview

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[BROWSER] Failed to create browser preview: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to create browser preview: {str(e)}"
        ) from e


@router.patch("/{project_slug}/browser-previews/{preview_id}", response_model=BrowserPreviewSchema)
async def update_browser_preview(
    project_slug: str,
    preview_id: UUID,
    preview_data: BrowserPreviewUpdate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a browser preview node (position, connected container, current path).
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    preview = await db.get(BrowserPreview, preview_id)
    if not preview or preview.project_id != project.id:
        raise HTTPException(status_code=404, detail="Browser preview not found")

    try:
        # Update fields if provided
        if preview_data.position_x is not None:
            preview.position_x = preview_data.position_x
        if preview_data.position_y is not None:
            preview.position_y = preview_data.position_y
        if preview_data.connected_container_id is not None:
            # Verify container exists
            if preview_data.connected_container_id:
                container = await db.get(Container, preview_data.connected_container_id)
                if not container or container.project_id != project.id:
                    raise HTTPException(status_code=404, detail="Connected container not found")
            preview.connected_container_id = preview_data.connected_container_id
        if preview_data.current_path is not None:
            preview.current_path = preview_data.current_path

        await db.commit()
        await db.refresh(preview)

        return preview

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[BROWSER] Failed to update browser preview: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to update browser preview: {str(e)}"
        ) from e


@router.delete("/{project_slug}/browser-previews/{preview_id}")
async def delete_browser_preview(
    project_slug: str,
    preview_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a browser preview node.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    preview = await db.get(BrowserPreview, preview_id)
    if not preview or preview.project_id != project.id:
        raise HTTPException(status_code=404, detail="Browser preview not found")

    try:
        await db.delete(preview)
        await db.commit()

        logger.info(f"[BROWSER] Deleted browser preview {preview_id} from project {project.id}")

        return {"message": "Browser preview deleted successfully"}

    except Exception as e:
        await db.rollback()
        logger.error(f"[BROWSER] Failed to delete browser preview: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to delete browser preview: {str(e)}"
        ) from e


@router.post(
    "/{project_slug}/browser-previews/{preview_id}/connect/{container_id}",
    response_model=BrowserPreviewSchema,
)
async def connect_browser_to_container(
    project_slug: str,
    preview_id: UUID,
    container_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Connect a browser preview to a container for preview.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    preview = await db.get(BrowserPreview, preview_id)
    if not preview or preview.project_id != project.id:
        raise HTTPException(status_code=404, detail="Browser preview not found")

    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    try:
        preview.connected_container_id = container_id
        await db.commit()
        await db.refresh(preview)

        logger.info(f"[BROWSER] Connected browser {preview_id} to container {container_id}")

        return preview

    except Exception as e:
        await db.rollback()
        logger.error(f"[BROWSER] Failed to connect browser to container: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to connect browser: {str(e)}") from e


@router.post(
    "/{project_slug}/browser-previews/{preview_id}/disconnect", response_model=BrowserPreviewSchema
)
async def disconnect_browser_from_container(
    project_slug: str,
    preview_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Disconnect a browser preview from its container.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    preview = await db.get(BrowserPreview, preview_id)
    if not preview or preview.project_id != project.id:
        raise HTTPException(status_code=404, detail="Browser preview not found")

    try:
        preview.connected_container_id = None
        await db.commit()
        await db.refresh(preview)

        logger.info(f"[BROWSER] Disconnected browser {preview_id} from container")

        return preview

    except Exception as e:
        await db.rollback()
        logger.error(f"[BROWSER] Failed to disconnect browser: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to disconnect browser: {str(e)}"
        ) from e


# Container-specific endpoints (parameterized routes come after specific ones)


@router.get("/{project_slug}/containers/status")
async def get_containers_status(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the runtime status of all containers in the project.

    Returns Docker status for each container (running, stopped, etc.)
    The response keys status entries by both the K8s directory name and the
    sanitized container display name so the frontend graph canvas polling
    can always find the correct entry.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    try:
        from ..services.orchestration import get_orchestrator

        orchestrator = get_orchestrator()
        status = await orchestrator.get_project_status(project.slug, project.id)

        # Add display-name aliases so the frontend can look up status by
        # sanitized container.name (which may differ from the K8s directory key,
        # e.g. "PostgreSQL" → "postgresql" vs service_slug "postgres").
        containers_map = status.get("containers")
        if containers_map:
            containers_result = await db.execute(
                select(Container).where(Container.project_id == project.id)
            )
            for c in containers_result.scalars().all():
                # Frontend sanitises: name.lower(), keep [a-z0-9-], collapse dashes
                frontend_key = _sanitize_status_key(c.name)
                # K8s key depends on container type
                if c.container_type == "service":
                    k8s_key = _sanitize_status_key(c.service_slug or c.name)
                else:
                    dir_for_k8s = c.name if c.directory in (".", "", None) else c.directory
                    k8s_key = _sanitize_status_key(dir_for_k8s)
                # Add alias if the keys differ and the K8s entry exists
                if frontend_key != k8s_key and k8s_key in containers_map:
                    containers_map[frontend_key] = containers_map[k8s_key]

        return status

    except Exception as e:
        logger.error(f"[ORCHESTRATION] Failed to get container status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}") from e


def _sanitize_status_key(name: str) -> str:
    """Sanitize a name into a DNS-1123 style key (matches frontend sanitization)."""
    s = re.sub(r"[^a-z0-9-]", "-", name.lower())
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _container_response(container, injected_env_vars: list | None = None) -> dict:
    """Serialize container with write-only env vars (hide values, expose keys only)."""
    data = ContainerSchema.model_validate(container).model_dump()
    data["environment_vars"] = None
    data["env_var_keys"] = container.env_var_keys
    data["env_vars_count"] = container.env_vars_count
    data["injected_env_vars"] = injected_env_vars
    service_def = get_service(container.service_slug) if container.service_slug else None
    data["service_outputs"] = service_def.outputs if service_def and service_def.outputs else None
    data["service_type"] = service_def.service_type.value if service_def else None
    data["icon"] = service_def.icon if service_def else getattr(container.base, "icon", None)
    data["tech_stack"] = (
        [service_def.docker_image] if service_def and service_def.docker_image else None
    ) or getattr(container.base, "tech_stack", None)
    data["base_name"] = getattr(container.base, "name", None)
    return data


@router.get("/{project_slug}/containers/{container_id}", response_model=ContainerSchema)
async def get_container(
    project_slug: str,
    container_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a single container's details including environment variables.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    injected = await get_injected_env_vars_for_container(db, container.id, project.id)
    return _container_response(container, injected_env_vars=injected)


@router.patch("/{project_slug}/containers/{container_id}", response_model=ContainerSchema)
async def update_container(
    project_slug: str,
    container_id: UUID,
    container_data: ContainerUpdate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update container settings (mainly position for React Flow).
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    try:
        # Update fields
        if container_data.name is not None:
            container.name = container_data.name
        if container_data.position_x is not None:
            container.position_x = container_data.position_x
        if container_data.position_y is not None:
            container.position_y = container_data.position_y
        if container_data.port is not None:
            container.port = container_data.port
        if container_data.env_vars_to_set:
            existing = decode_secret_map(container.environment_vars or {})
            existing.update(container_data.env_vars_to_set)
            container.environment_vars = encode_secret_map(existing)
            flag_modified(container, "environment_vars")
        if container_data.env_vars_to_delete:
            existing = decode_secret_map(container.environment_vars or {})
            for key in container_data.env_vars_to_delete:
                existing.pop(key, None)
            container.environment_vars = encode_secret_map(existing)
            flag_modified(container, "environment_vars")

        await db.commit()
        refreshed_container = await db.execute(
            select(Container)
            .where(Container.id == container.id)
            .options(selectinload(Container.base))
        )
        container = refreshed_container.scalar_one()

        return _container_response(container)

    except Exception as e:
        await db.rollback()
        logger.error(f"[CONTAINER] Failed to update container: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update container: {str(e)}") from e


@router.put("/{project_slug}/containers/{container_id}/credentials", response_model=ContainerSchema)
async def update_container_credentials(
    project_slug: str,
    container_id: UUID,
    body: ContainerCredentialUpdate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update credentials for an external service container."""
    project = await get_project_by_slug(db, project_slug, current_user.id)

    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    if container.deployment_mode != "external":
        raise HTTPException(status_code=400, detail="Container is not an external service")

    try:
        from ..services.deployment_encryption import get_deployment_encryption_service

        encryption_service = get_deployment_encryption_service()
        encrypted = encryption_service.encrypt(json.dumps(body.credentials))

        # Update existing credential or create a new one
        credential = None
        if container.credentials_id:
            credential = await db.get(DeploymentCredential, container.credentials_id)

        if credential:
            credential.access_token_encrypted = encrypted
            if body.external_endpoint is not None:
                credential.provider_metadata = {
                    **(credential.provider_metadata or {}),
                    "external_endpoint": body.external_endpoint,
                }
                flag_modified(credential, "provider_metadata")
        else:
            credential = DeploymentCredential(
                user_id=current_user.id,
                project_id=project.id,
                provider=container.service_slug or "external",
                access_token_encrypted=encrypted,
                provider_metadata={
                    "service_type": "external",
                    "external_endpoint": body.external_endpoint,
                },
            )
            db.add(credential)
            await db.flush()
            container.credentials_id = credential.id

        if body.external_endpoint is not None:
            container.external_endpoint = body.external_endpoint

        await db.commit()
        await db.refresh(container)

        logger.info(f"[CONTAINER] Updated credentials for container {container_id}")

        injected = await get_injected_env_vars_for_container(db, container.id, project.id)
        return _container_response(container, injected_env_vars=injected)

    except Exception as e:
        await db.rollback()
        logger.error(f"[CONTAINER] Failed to update credentials: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to update credentials: {str(e)}"
        ) from e


@router.post("/{project_slug}/containers/{container_id}/rename", response_model=ContainerSchema)
async def rename_container(
    project_slug: str,
    container_id: UUID,
    rename_data: ContainerRename,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Rename a container and its associated folder.

    This operation:
    1. Validates the new name doesn't conflict with existing containers
    2. Renames the folder in the shared volume
    3. Updates the container record (name, directory, container_name)
    4. Regenerates docker-compose.yml
    """
    import re

    project = await get_project_by_slug(db, project_slug, current_user.id)

    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    new_name = rename_data.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Container name cannot be empty")

    # If name hasn't changed, return early
    if new_name == container.name:
        return _container_response(container)

    try:
        # Sanitize the new name for Docker and directory naming
        new_service_name = new_name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
        new_service_name = "".join(c for c in new_service_name if c.isalnum() or c == "-")
        new_service_name = re.sub(r"-+", "-", new_service_name).strip("-")

        if not new_service_name:
            raise HTTPException(
                status_code=400, detail="Container name must contain alphanumeric characters"
            )

        # Check for duplicate directory names in this project
        existing_containers = await db.execute(
            select(Container).where(
                Container.project_id == project.id, Container.id != container_id
            )
        )
        for existing in existing_containers.scalars().all():
            existing_service = (
                existing.name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
            )
            existing_service = "".join(c for c in existing_service if c.isalnum() or c == "-")
            existing_service = re.sub(r"-+", "-", existing_service).strip("-")

            if existing_service == new_service_name:
                raise HTTPException(
                    status_code=400,
                    detail=f"A container with folder name '{new_service_name}' already exists in this project",
                )

        old_directory = container.directory
        new_directory = new_service_name
        new_docker_container_name = f"{project.slug}-{new_service_name}"

        # Only rename folder for base containers (not service containers)
        if container.container_type == "base" and old_directory and old_directory != new_directory:
            # Stop the container if running
            try:
                import docker as docker_lib

                docker_client = docker_lib.from_env()
                old_docker_name = container.container_name
                try:
                    docker_container = docker_client.containers.get(old_docker_name)
                    logger.info(f"[CONTAINER] Stopping container {old_docker_name} before rename")
                    docker_container.stop(timeout=5)
                    docker_container.remove(force=True)
                except docker_lib.errors.NotFound:
                    pass  # Container not running
            except Exception as e:
                logger.warning(f"[CONTAINER] Could not stop container before rename: {e}")

            # Rename folder in shared volume via orchestrator
            from ..services.orchestration import get_orchestrator

            orch = get_orchestrator()

            try:
                await orch.rename_directory(project.slug, old_directory, new_directory)
                logger.info(f"[CONTAINER] Renamed folder from {old_directory} to {new_directory}")
            except Exception as e:
                logger.error(f"[CONTAINER] Failed to rename folder: {e}")
                raise HTTPException(
                    status_code=500, detail=f"Failed to rename folder: {str(e)}"
                ) from e

        # Update container record
        container.name = new_name
        container.directory = new_directory
        container.container_name = new_docker_container_name

        await db.commit()
        await db.refresh(container)

        # Regenerate docker-compose.yml
        try:
            containers_result = await db.execute(
                select(Container)
                .where(Container.project_id == project.id)
                .options(selectinload(Container.base))
            )
            all_containers = containers_result.scalars().all()

            connections_result = await db.execute(
                select(ContainerConnection).where(ContainerConnection.project_id == project.id)
            )
            all_connections = connections_result.scalars().all()

            from ..services.orchestration import get_orchestrator, is_docker_mode

            if is_docker_mode():
                orchestrator = get_orchestrator()
                env_overrides = await build_env_overrides(db, project.id, all_containers)
                await orchestrator.write_compose_file(
                    project, all_containers, all_connections, current_user.id, env_overrides
                )
                logger.info("[CONTAINER] Regenerated docker-compose.yml after rename")
        except Exception as e:
            logger.error(f"[CONTAINER] Failed to regenerate docker-compose: {e}")

        logger.info(
            f"[CONTAINER] ✅ Renamed container {container_id} from '{container.name}' to '{new_name}'"
        )
        return _container_response(container)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[CONTAINER] Failed to rename container: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to rename container: {str(e)}") from e


@router.patch(
    "/{project_slug}/containers/{container_id}/deployment-target", response_model=ContainerSchema
)
async def assign_deployment_target(
    project_slug: str,
    container_id: UUID,
    assignment: DeploymentTargetAssignment,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Assign or remove a deployment target from a container.

    Validates that the container type and framework are compatible with the
    deployment provider before assignment.
    """
    from ..services.service_definitions import DEPLOYMENT_COMPATIBILITY, is_deployment_compatible

    project = await get_project_by_slug(db, project_slug, current_user.id)

    # Get container with base relationship for tech stack info
    result = await db.execute(
        select(Container).where(Container.id == container_id).options(selectinload(Container.base))
    )
    container = result.scalar_one_or_none()

    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    provider = assignment.provider

    # If removing deployment target (provider is None), just clear it
    if provider is None:
        container.deployment_provider = None
        await db.commit()
        await db.refresh(container)
        logger.info(f"[CONTAINER] Removed deployment target from container {container_id}")
        return container

    # Normalize provider name
    provider = provider.lower().strip()

    # Validate provider exists
    if provider not in DEPLOYMENT_COMPATIBILITY:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid deployment provider. Must be one of: {', '.join(DEPLOYMENT_COMPATIBILITY.keys())}",
        )

    # Get tech stack from base if available
    tech_stack = []
    if container.base and container.base.tech_stack:
        tech_stack = (
            container.base.tech_stack if isinstance(container.base.tech_stack, list) else []
        )

    # Validate compatibility
    is_compatible, reason = is_deployment_compatible(
        container_type=container.container_type,
        service_slug=container.service_slug,
        tech_stack=tech_stack,
        provider=provider,
    )

    if not is_compatible:
        raise HTTPException(status_code=400, detail=reason)

    # Assign deployment target
    container.deployment_provider = provider
    await db.commit()
    await db.refresh(container)

    logger.info(f"[CONTAINER] Assigned deployment target '{provider}' to container {container_id}")
    return container


@router.delete("/{project_slug}/containers/{container_id}")
async def delete_container(
    project_slug: str,
    container_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a container from the project.
    Deletes the container record and its directory from the monorepo.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    try:
        # Step 1: Stop and remove Docker container (if running)
        import docker as docker_lib

        try:
            docker_client = docker_lib.from_env()

            # Get container name (same sanitization as in docker_compose_orchestrator)
            service_name = (
                container.name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
            )
            service_name = "".join(c for c in service_name if c.isalnum() or c == "-")
            container_name = f"{project.slug}-{service_name}"

            # Stop and remove container
            try:
                docker_container = docker_client.containers.get(container_name)
                logger.info(f"[CONTAINER] Stopping container {container_name}")
                docker_container.stop(timeout=5)
                docker_container.remove(force=True)
                logger.info(f"[CONTAINER] ✅ Removed Docker container {container_name}")
            except docker_lib.errors.NotFound:
                logger.info(
                    f"[CONTAINER] Docker container {container_name} not found (already deleted)"
                )
            except Exception as e:
                logger.warning(f"[CONTAINER] Failed to remove Docker container: {e}")
        except Exception as e:
            logger.warning(f"[CONTAINER] Failed to connect to Docker: {e}")

        # Step 2: Delete container from database (connections will cascade)
        # Note: With shared volume architecture, there's no per-container volume to delete
        # Project files stay in /projects/{project-slug}/ and are only deleted with the project
        await db.delete(container)
        await db.commit()

        logger.info(f"[CONTAINER] ✅ Deleted container {container_id} from project {project.id}")

        # Regenerate docker-compose.yml (Docker mode only)
        try:
            from ..services.orchestration import get_orchestrator, is_docker_mode

            if is_docker_mode():
                # Get remaining containers and connections
                # Use selectinload to eagerly load the base relationship
                containers_result = await db.execute(
                    select(Container)
                    .where(Container.project_id == project.id)
                    .options(selectinload(Container.base))  # Eagerly load base
                )
                remaining_containers = containers_result.scalars().all()

                connections_result = await db.execute(
                    select(ContainerConnection).where(ContainerConnection.project_id == project.id)
                )
                remaining_connections = connections_result.scalars().all()

                # Update docker-compose.yml
                orchestrator = get_orchestrator()
                env_overrides = await build_env_overrides(db, project.id, remaining_containers)
                await orchestrator.write_compose_file(
                    project,
                    remaining_containers,
                    remaining_connections,
                    current_user.id,
                    env_overrides,
                )

                logger.info("[CONTAINER] Updated docker-compose.yml after deletion")
        except Exception as e:
            logger.warning(f"[CONTAINER] Failed to update docker-compose.yml: {e}")

        return {"message": "Container deleted successfully"}

    except Exception as e:
        await db.rollback()
        logger.error(f"[CONTAINER] Failed to delete container: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete container: {str(e)}") from e


# ============================================================================
# Multi-Container Orchestration Endpoints (Start/Stop)
# ============================================================================


@router.post("/{project_slug}/containers/start-all")
async def start_all_containers(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start all containers in a project.

    In Docker mode: Uses docker-compose up to start containers.
    In Kubernetes mode: Creates namespace, deployments, and services.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    try:
        # Get all containers and connections
        # Use selectinload to eagerly load the base relationship to avoid lazy loading errors
        containers_result = await db.execute(
            select(Container)
            .where(Container.project_id == project.id)
            .options(selectinload(Container.base))  # Eagerly load base
        )
        containers = containers_result.scalars().all()

        if not containers:
            raise HTTPException(status_code=400, detail="No containers to start")

        connections_result = await db.execute(
            select(ContainerConnection).where(ContainerConnection.project_id == project.id)
        )
        connections = connections_result.scalars().all()

        # Use unified orchestration (handles both Docker and Kubernetes)
        from ..services.orchestration import get_deployment_mode, get_orchestrator

        orchestrator = get_orchestrator()
        deployment_mode = get_deployment_mode()

        result = await orchestrator.start_project(
            project, containers, connections, current_user.id, db
        )

        logger.info(
            f"[{deployment_mode.value.upper()}] Started all containers for project {project.slug}"
        )

        return {
            "message": "All containers started successfully",
            "project_slug": project.slug,
            "containers": result.get("containers", {}),
            "network": result.get("network"),
            "namespace": result.get("namespace"),
            "deployment_mode": deployment_mode.value,
        }

    except Exception as e:
        logger.error(f"[ORCHESTRATOR] Failed to start containers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start containers: {str(e)}") from e


@router.post("/{project_slug}/containers/stop-all")
async def stop_all_containers(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stop all containers in a project.

    In Docker mode: Uses docker-compose down.
    In Kubernetes mode: Deletes the project namespace.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    try:
        # Use unified orchestration (handles both Docker and Kubernetes)
        from ..services.orchestration import get_deployment_mode, get_orchestrator

        orchestrator = get_orchestrator()
        deployment_mode = get_deployment_mode()

        await orchestrator.stop_project(project.slug, project.id, current_user.id)

        logger.info(
            f"[{deployment_mode.value.upper()}] Stopped all containers for project {project.slug}"
        )

        return {
            "message": "All containers stopped successfully",
            "deployment_mode": deployment_mode.value,
        }

    except Exception as e:
        logger.error(f"[ORCHESTRATOR] Failed to stop containers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to stop containers: {str(e)}") from e


async def _start_container_background_task(
    project_slug: str, container_id: UUID, user_id: UUID, task: "Task"
) -> dict:
    """
    Background task worker for starting a container with progress tracking.

    This function runs asynchronously and updates task progress throughout
    the container startup process. It automatically detects the deployment
    mode (Docker or Kubernetes) and uses the appropriate orchestrator.

    Security:
    - User authorization verified before task creation
    - All operations scoped to user's project
    - Timeout enforced at task manager level

    Progress Stages:
    - 10%: Validating project and container
    - 25%: Loading project configuration
    - 40%: Generating configuration
    - 55%: Starting container
    - 70%: Configuring network routing
    - 85%: Waiting for container health check
    - 100%: Container ready

    Args:
        project_slug: Project identifier
        container_id: Container UUID to start
        user_id: User UUID (for authorization)
        task: Task object for progress updates

    Returns:
        dict with container_id, container_name, and url

    Raises:
        RuntimeError: If container start fails at any stage
    """
    from ..database import get_db
    from ..services.orchestration import get_orchestrator, is_kubernetes_mode

    db_gen = get_db()
    db = await db_gen.__anext__()

    try:
        # Stage 1: Validate project and container (10%)
        task.update_progress(10, 100, "Validating project and container")

        project = await get_project_by_slug(db, project_slug, user_id)
        if not project:
            raise RuntimeError(f"Project '{project_slug}' not found")

        container = await db.get(Container, container_id)
        if not container or container.project_id != project.id:
            raise RuntimeError(f"Container not found in project '{project_slug}'")

        # Check if container is already running - skip full startup if so
        orchestrator = get_orchestrator()
        try:
            status = await asyncio.wait_for(
                orchestrator.get_project_status(project.slug, project.id),
                timeout=15,
            )
        except Exception as e:
            # If status check fails/times out, proceed with startup
            task.add_log(f"Status check skipped ({type(e).__name__}), proceeding with startup")
            logger.warning(f"[ORCHESTRATOR] get_project_status timed out or failed: {e}")
            status = {"status": "unknown", "containers": {}}

        # Build the lookup key matching what K8s uses for the pod label:
        # service containers key by service_slug, base containers by directory
        if getattr(container, "container_type", "base") == "service":
            service_name = _sanitize_status_key(container.service_slug or container.name)
        else:
            dir_for_k8s = (
                container.name if container.directory in (".", "", None) else container.directory
            )
            service_name = _sanitize_status_key(dir_for_k8s)

        container_info = status.get("containers", {}).get(service_name)
        if container_info and container_info.get("running"):
            # Container is already running - return immediately!
            task.update_progress(100, 100, "Container already running")
            # Use URL from orchestrator status if available, otherwise build it
            container_url = container_info.get("url")
            if not container_url:
                settings = get_settings()
                if settings.deployment_mode == "docker":
                    # Docker mode always uses HTTP on localhost
                    container_url = f"http://{project.slug}-{service_name}.{settings.app_domain}"
                else:
                    protocol = "https" if settings.k8s_wildcard_tls_secret else "http"
                    container_url = (
                        f"{protocol}://{project.slug}-{service_name}.{settings.app_domain}"
                    )
            task.add_log(f"Container '{container.name}' is already running at {container_url}")
            logger.info(f"[COMPOSE] Container {container.name} already running, skipping startup")

            return {
                "container_id": str(container.id),
                "container_name": container.name,
                "url": container_url,
                "status": "running",
            }

        task.add_log(f"Starting container '{container.name}' in project '{project.slug}'")
        deployment_mode = "kubernetes" if is_kubernetes_mode() else "docker"
        task.add_log(f"Deployment mode: {deployment_mode}")

        # Stage 2: Fetch all containers and connections (25%)
        task.update_progress(25, 100, "Loading project configuration")

        # Use selectinload to eagerly load the base relationship
        containers_result = await db.execute(
            select(Container)
            .where(Container.project_id == project.id)
            .options(
                selectinload(Container.base)
            )  # Eagerly load base to avoid lazy loading in async context
        )
        all_containers = containers_result.scalars().all()
        task.add_log(f"Found {len(all_containers)} containers in project")

        # CRITICAL: Use the container from all_containers which has base eagerly loaded
        # The original container from db.get() doesn't have the base relationship loaded
        container = next((c for c in all_containers if c.id == container_id), container)
        if container.base:
            task.add_log(
                f"Container base: {container.base.name} (git: {container.base.git_repo_url})"
            )
        else:
            task.add_log(f"WARNING: Container has no base - base_id={container.base_id}")

        connections_result = await db.execute(
            select(ContainerConnection).where(ContainerConnection.project_id == project.id)
        )
        all_connections = connections_result.scalars().all()
        task.add_log(f"Found {len(all_connections)} container connections")

        # Choose orchestrator based on deployment mode (orchestrator already obtained above)
        if is_kubernetes_mode():
            # Kubernetes mode
            settings = get_settings()
            task.update_progress(40, 100, "Preparing Kubernetes deployment")
            task.add_log("Using Kubernetes orchestrator")

            # Stage 4: Start container in K8s (55%)
            task.update_progress(55, 100, f"Creating Kubernetes resources for '{container.name}'")

            result = await asyncio.wait_for(
                orchestrator.start_container(
                    project=project,
                    container=container,
                    all_containers=all_containers,
                    connections=all_connections,
                    user_id=user_id,
                    db=db,
                ),
                timeout=300,  # 5 min timeout for K8s container startup
            )

            task.add_log(f"Container '{container.name}' deployed to Kubernetes")

            # Stage 5: Network routing (70%)
            task.update_progress(70, 100, "Configuring ingress routing")
            task.add_log("Kubernetes ingress configured")

            # Stage 6: Wait for readiness (85%)
            task.update_progress(85, 100, "Waiting for pod to be ready")
            task.add_log("Pod readiness check completed")

            container_url = result.get(
                "url",
                f"{settings.k8s_container_url_protocol}://{result.get('hostname', 'unknown')}",
            )

        else:
            # Docker mode: Use Docker Compose orchestrator

            # Stage 3-4: Start container (includes compose file generation)
            task.update_progress(40, 100, f"Starting container '{container.name}'")

            result = await orchestrator.start_container(
                project=project,
                container=container,
                all_containers=all_containers,
                connections=all_connections,
                user_id=user_id,
                db=db,
            )
            task.add_log(f"Container '{container.name}' started via docker compose")

            # Stage 5: Regional Traefik routing (70%)
            task.update_progress(70, 100, "Configuring network routing")
            task.add_log("Regional Traefik routing configured")

            # Stage 6: Wait for container health (85%)
            task.update_progress(85, 100, "Waiting for container to be ready")

            # Get container URL from result (orchestrator returns correct URL)
            container_url = result.get("url")
            if not container_url:
                settings = get_settings()
                sanitized_name = (
                    container.name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
                )
                sanitized_name = "".join(
                    c for c in sanitized_name if c.isalnum() or c == "-"
                ).strip("-")
                if settings.deployment_mode == "docker":
                    # Docker mode always uses HTTP on localhost
                    container_url = f"http://{project.slug}-{sanitized_name}.{settings.app_domain}"
                else:
                    protocol = "https" if settings.k8s_wildcard_tls_secret else "http"
                    container_url = (
                        f"{protocol}://{project.slug}-{sanitized_name}.{settings.app_domain}"
                    )

            # Give container a moment to fully initialize
            await asyncio.sleep(2)
            task.add_log("Container health check passed")

        # Stage 7: Complete (100%)
        task.update_progress(100, 100, "Container ready")
        task.add_log(f"Container accessible at {container_url}")

        logger.info(
            f"[ORCHESTRATOR] Successfully started container {container.name} in project {project.slug} ({deployment_mode} mode)"
        )

        return {
            "container_id": str(container.id),
            "container_name": container.name,
            "url": container_url,
            "status": "running",
        }

    except Exception as e:
        error_msg = f"Failed to start container: {str(e)}"
        task.add_log(f"ERROR: {error_msg}")
        logger.error(f"[ORCHESTRATOR] Container start failed: {e}", exc_info=True)
        raise RuntimeError(error_msg) from e
    finally:
        await db_gen.aclose()


@router.post("/{project_slug}/containers/{container_id}/start", status_code=202)
async def start_single_container(
    project_slug: str,
    container_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start a specific container in the project (asynchronous).

    This is used when opening a container's builder - it starts just that
    container without starting the entire project.

    This endpoint returns immediately with a task ID. The client should poll
    GET /api/tasks/{task_id}/status or use WebSocket /api/tasks/ws for real-time
    progress updates.

    Security:
    - Verifies user owns the project before creating task
    - Prevents concurrent container starts for same container
    - Task results only accessible by task owner

    Returns:
        202 Accepted with task_id for progress tracking

    Example Response:
        {
            "task_id": "550e8400-e29b-41d4-a716-446655440000",
            "message": "Container start initiated",
            "container_name": "frontend",
            "status_url": "/api/tasks/{task_id}/status"
        }
    """
    # Verify project ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)

    # Verify container exists and belongs to project
    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    # FAST PATH: Check if container is already running (Docker mode only)
    # This avoids creating a background task for already-running containers
    settings = get_settings()
    if settings.deployment_mode == "docker":
        from ..services.orchestration import get_orchestrator

        orchestrator = get_orchestrator()
        is_running = await orchestrator.is_container_running(project.slug, container.name)
        if is_running:
            # Container already running - return immediately without creating task
            # Sanitize the name the same way docker.py does
            sanitized_name = (
                container.name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
            )
            sanitized_name = "".join(c for c in sanitized_name if c.isalnum() or c == "-")
            sanitized_name = re.sub(r"-+", "-", sanitized_name).strip("-")
            container_url = f"http://{project.slug}-{sanitized_name}.{settings.app_domain}"

            logger.info(
                f"[COMPOSE] Container {container.name} already running, returning fast path"
            )
            return {
                "task_id": None,
                "message": "Container already running",
                "container_name": container.name,
                "already_running": True,
                "url": container_url,
                "completed": True,
            }

    # Rate limiting: Check for existing active container start tasks
    from ..services.task_manager import TaskStatus, get_task_manager

    task_manager = get_task_manager()
    active_tasks = await task_manager.get_user_tasks_async(current_user.id, active_only=True)

    # Check if there's already a running task for this container
    for existing_task in active_tasks:
        if (
            existing_task.type == "container_start"
            and existing_task.metadata.get("container_id") == str(container_id)
            and existing_task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING)
        ):
            # Return existing task instead of creating duplicate
            return {
                "task_id": existing_task.id,
                "message": "Container start already in progress",
                "container_name": container.name,
                "status_url": f"/api/tasks/{existing_task.id}/status",
                "already_started": True,
            }

    # Create background task
    task = task_manager.create_task(
        user_id=current_user.id,
        task_type="container_start",
        metadata={
            "project_slug": project_slug,
            "project_id": str(project.id),
            "container_id": str(container_id),
            "container_name": container.name,
        },
    )

    # Start task in background with timeout protection
    task_manager.start_background_task(
        task_id=task.id,
        coro=_start_container_background_task,
        project_slug=project_slug,
        container_id=container_id,
        user_id=current_user.id,
    )

    logger.info(
        f"[COMPOSE] Container start task {task.id} created for "
        f"container {container.name} in project {project.slug}"
    )

    return {
        "task_id": task.id,
        "message": f"Container start initiated for '{container.name}'",
        "container_name": container.name,
        "status_url": f"/api/tasks/{task.id}/status",
    }


@router.post("/{project_slug}/containers/{container_id}/stop")
async def stop_single_container(
    project_slug: str,
    container_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stop a specific container in the project.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    # Get the container
    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    try:
        from ..services.orchestration import get_orchestrator, is_kubernetes_mode

        orchestrator = get_orchestrator()
        if (
            is_kubernetes_mode()
            and hasattr(container, "container_type")
            and container.container_type == "service"
        ):
            await orchestrator.stop_container(
                project_slug=project.slug,
                project_id=project.id,
                container_name=container.name,
                user_id=current_user.id,
                container_type="service",
                service_slug=container.service_slug,
            )
        else:
            await orchestrator.stop_container(
                project_slug=project.slug,
                project_id=project.id,
                container_name=container.name,
                user_id=current_user.id,
            )

        logger.info(f"[ORCHESTRATION] Stopped container {container.name} in project {project.slug}")

        return {
            "message": f"Container {container.name} stopped successfully",
            "container_id": str(container.id),
            "container_name": container.name,
        }

    except Exception as e:
        logger.error(f"[COMPOSE] Failed to stop container {container.name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to stop container: {str(e)}") from e


@router.get("/{project_slug}/containers/{container_id}/health")
async def check_container_health(
    project_slug: str,
    container_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if a container's web server is responding to HTTP requests.

    This endpoint is used by the frontend to determine when a container is ready
    to display in the preview iframe, avoiding 404/503 errors during startup.

    Returns:
        healthy: True if the container responds with 2xx/3xx status
        status_code: HTTP status code from the container
        url: The URL that was checked
        error: Error message if check failed
    """
    import httpx

    project = await get_project_by_slug(db, project_slug, current_user.id)

    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    settings = get_settings()

    # Get container directory (sanitized for K8s naming)
    container_dir = container.directory or container.name
    if container_dir in (".", "", None):
        container_dir = container.name
    # Sanitize for DNS compliance
    container_dir = container_dir.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
    container_dir = "".join(c for c in container_dir if c.isalnum() or c == "-")
    while "--" in container_dir:
        container_dir = container_dir.replace("--", "-")
    container_dir = container_dir.strip("-")[:63]

    # Build container URL based on deployment mode
    if settings.deployment_mode == "kubernetes":
        # External URL for frontend display (what users access via browser)
        external_url = f"{settings.k8s_container_url_protocol}://{project.slug}-{container_dir}.{settings.app_domain}"
        # Internal URL for health check (always reachable from within cluster)
        # Service naming: dev-{container_dir} in namespace proj-{project.id}
        service_port = container.effective_port
        health_check_url = (
            f"http://dev-{container_dir}.proj-{project.id}.svc.cluster.local:{service_port}"
        )
    else:
        # Docker URL pattern: {project_slug}-{container}.localhost
        external_url = f"http://{project.slug}-{container_dir}.{settings.app_domain}"
        # Health check through Traefik (orchestrator can't reach container directly)
        health_check_url = "http://traefik"
        health_check_headers = {"Host": f"{project.slug}-{container_dir}.{settings.app_domain}"}

    try:
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            if settings.deployment_mode == "docker":
                response = await client.get(
                    health_check_url, headers=health_check_headers, follow_redirects=True
                )
            else:
                response = await client.get(health_check_url, follow_redirects=True)
            is_healthy = response.status_code < 400

            return {
                "healthy": is_healthy,
                "status_code": response.status_code,
                "url": external_url,  # Return external URL for frontend
            }
    except httpx.TimeoutException:
        return {
            "healthy": False,
            "url": external_url,
            "error": "Connection timeout - server not responding",
        }
    except httpx.ConnectError:
        return {
            "healthy": False,
            "url": external_url,
            "error": "Connection refused - server not started",
        }
    except Exception as e:
        logger.debug(f"[HEALTH CHECK] Error checking {health_check_url}: {e}")
        return {"healthy": False, "url": external_url, "error": str(e)}


@router.post("/{project_slug}/containers/{container_id}/restart", status_code=202)
async def restart_single_container(
    project_slug: str,
    container_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Restart a specific container in the project (stop + start).

    This endpoint returns immediately with a task ID. The client should poll
    for status updates.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    from ..services.task_manager import get_task_manager

    task_manager = get_task_manager()

    # Create background task
    task = task_manager.create_task(
        user_id=current_user.id,
        task_type="container_restart",
        metadata={
            "project_slug": project_slug,
            "project_id": str(project.id),
            "container_id": str(container_id),
            "container_name": container.name,
        },
    )

    # Start task in background
    task_manager.start_background_task(
        task_id=task.id,
        coro=_restart_container_background_task,
        project_slug=project_slug,
        container_id=container_id,
        user_id=current_user.id,
    )

    logger.info(
        f"[COMPOSE] Container restart task {task.id} created for container {container.name}"
    )

    return {
        "task_id": task.id,
        "message": f"Container restart initiated for '{container.name}'",
        "container_name": container.name,
        "status_url": f"/api/tasks/{task.id}/status",
    }


async def _restart_container_background_task(
    project_slug: str, container_id: UUID, user_id: UUID, task: "Task"
) -> dict:
    """Background task worker for restarting a container."""
    from ..database import get_db
    from ..services.orchestration import get_orchestrator, is_kubernetes_mode

    db_gen = get_db()
    db = await db_gen.__anext__()

    try:
        task.update_progress(10, 100, "Validating container")

        project = await get_project_by_slug(db, project_slug, user_id)
        container = await db.get(Container, container_id)

        if not container or container.project_id != project.id:
            raise RuntimeError("Container not found")

        orchestrator = get_orchestrator()

        # Stop the container
        task.update_progress(30, 100, f"Stopping container '{container.name}'")
        try:
            if (
                is_kubernetes_mode()
                and hasattr(container, "container_type")
                and container.container_type == "service"
            ):
                await orchestrator.stop_container(
                    project_slug=project.slug,
                    project_id=project.id,
                    container_name=container.name,
                    user_id=user_id,
                    container_type="service",
                    service_slug=container.service_slug,
                )
            else:
                await orchestrator.stop_container(
                    project_slug=project.slug,
                    project_id=project.id,
                    container_name=container.name,
                    user_id=user_id,
                )
            task.add_log(f"Container '{container.name}' stopped")
        except Exception as e:
            task.add_log(f"Note: Container may not have been running: {e}")

        # Load containers and connections for restart
        task.update_progress(50, 100, "Regenerating configuration")
        containers_result = await db.execute(
            select(Container)
            .where(Container.project_id == project.id)
            .options(selectinload(Container.base))
        )
        all_containers = containers_result.scalars().all()

        connections_result = await db.execute(
            select(ContainerConnection).where(ContainerConnection.project_id == project.id)
        )
        all_connections = connections_result.scalars().all()

        # Start the container (includes compose file generation)
        task.update_progress(70, 100, f"Starting container '{container.name}'")
        result = await orchestrator.start_container(
            project=project,
            container=container,
            all_containers=all_containers,
            connections=all_connections,
            user_id=user_id,
            db=db,
        )
        task.add_log(f"Container '{container.name}' started")

        # Wait for container to be ready
        task.update_progress(90, 100, "Waiting for container to be ready")
        import asyncio

        await asyncio.sleep(2)

        # Get container URL from result (orchestrator returns correct URL)
        container_url = result.get("url")
        if not container_url:
            settings = get_settings()
            sanitized_name = (
                container.name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
            )
            sanitized_name = "".join(c for c in sanitized_name if c.isalnum() or c == "-").strip(
                "-"
            )
            if settings.deployment_mode == "docker":
                # Docker mode always uses HTTP on localhost
                container_url = f"http://{project.slug}-{sanitized_name}.{settings.app_domain}"
            else:
                protocol = "https" if settings.k8s_wildcard_tls_secret else "http"
                container_url = (
                    f"{protocol}://{project.slug}-{sanitized_name}.{settings.app_domain}"
                )

        task.update_progress(100, 100, "Container restarted successfully")
        logger.info(f"[COMPOSE] Successfully restarted container {container.name}")

        return {
            "container_id": str(container.id),
            "container_name": container.name,
            "url": container_url,
            "status": "running",
        }

    except Exception as e:
        error_msg = f"Failed to restart container: {str(e)}"
        task.add_log(f"ERROR: {error_msg}")
        logger.error(f"[COMPOSE] Container restart failed: {e}", exc_info=True)
        raise RuntimeError(error_msg) from e

    finally:
        with contextlib.suppress(Exception):
            await db_gen.aclose()


# =============================================================================
# Admin Endpoints for Testing
# =============================================================================


@router.post("/{project_slug}/admin/hibernate")
async def admin_force_hibernate(
    project_slug: str,
    current_user: User = Depends(current_superuser),  # Requires admin/superuser
    db: AsyncSession = Depends(get_db),
):
    """
    [ADMIN ONLY] Force hibernate a project for testing.

    This endpoint allows admins to immediately hibernate a project without
    waiting for the idle timeout. Useful for testing hibernation/restore flow.

    The project will be:
    1. Marked as 'hibernating'
    2. Saved to S3 (full zip including node_modules)
    3. K8s namespace deleted
    4. Marked as 'hibernated'

    Returns the hibernation result including archive size.
    """
    settings = get_settings()

    if settings.deployment_mode != "kubernetes":
        raise HTTPException(
            status_code=400, detail="Hibernation is only available in Kubernetes mode"
        )

    # Get project (admin can access any project)
    result = await db.execute(select(Project).where(Project.slug == project_slug))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.environment_status == "hibernated":
        raise HTTPException(
            status_code=400,
            detail=f"Project is already hibernated (hibernated_at: {project.hibernated_at})",
        )

    if project.environment_status == "hibernating":
        raise HTTPException(status_code=400, detail="Project is currently being hibernated")

    try:
        from datetime import datetime

        from ..services.orchestration.kubernetes_orchestrator import get_kubernetes_orchestrator

        orchestrator = get_kubernetes_orchestrator()

        logger.info(
            f"[ADMIN:HIBERNATE] Force hibernating project {project.slug} by admin {current_user.email}"
        )

        # Mark as hibernating
        project.environment_status = "hibernating"
        await db.commit()

        # Send WebSocket notification to redirect user (same as cleanup task)
        try:
            await ws_manager.send_status_update(
                user_id=project.owner_id,
                project_id=project.id,
                status={
                    "environment_status": "hibernating",
                    "message": "Saving project files...",
                    "action": "redirect_to_projects",
                },
            )
        except Exception as ws_err:
            logger.debug(f"[ADMIN:HIBERNATE] Could not send WebSocket notification: {ws_err}")

        # Perform hibernation
        success = await orchestrator.hibernate_project(project.id, project.owner_id, db=db)

        if not success:
            project.environment_status = "active"
            project.hibernated_at = None
            await db.commit()
            raise HTTPException(
                status_code=500,
                detail="Hibernation failed - snapshot save returned false. Check logs for details.",
            )

        # Mark as hibernated
        project.environment_status = "hibernated"
        project.hibernated_at = datetime.now(UTC)
        await db.commit()

        # Send completion notification
        try:
            await ws_manager.send_status_update(
                user_id=project.owner_id,
                project_id=project.id,
                status={
                    "environment_status": "hibernated",
                    "message": "Project saved successfully",
                },
            )
        except Exception as ws_err:
            logger.debug(f"[ADMIN:HIBERNATE] Could not send completion notification: {ws_err}")

        logger.info(f"[ADMIN:HIBERNATE] ✅ Successfully hibernated project {project.slug}")

        return {
            "message": f"Project '{project.slug}' hibernated successfully",
            "project_id": str(project.id),
            "project_slug": project.slug,
            "environment_status": project.environment_status,
            "hibernated_at": project.hibernated_at.isoformat(),
            "owner_id": str(project.owner_id),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ADMIN:HIBERNATE] Failed to hibernate project: {e}", exc_info=True)
        project.environment_status = "active"
        project.hibernated_at = None
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Hibernation failed: {str(e)}") from e


@router.get("/{project_slug}/admin/status")
async def admin_get_project_status(
    project_slug: str,
    current_user: User = Depends(current_superuser),
    db: AsyncSession = Depends(get_db),
):
    """
    [ADMIN ONLY] Get detailed project environment status.

    Returns environment status, hibernation timestamp, namespace info, etc.
    """
    settings = get_settings()

    # Get project (admin can access any project)
    result = await db.execute(select(Project).where(Project.slug == project_slug))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    response = {
        "project_id": str(project.id),
        "project_slug": project.slug,
        "project_name": project.name,
        "owner_id": str(project.owner_id),
        "environment_status": project.environment_status,
        "hibernated_at": project.hibernated_at.isoformat() if project.hibernated_at else None,
        "last_activity": project.last_activity.isoformat() if project.last_activity else None,
        "deployment_mode": settings.deployment_mode,
        "idle_timeout_minutes": settings.k8s_hibernation_idle_minutes
        if settings.deployment_mode == "kubernetes"
        else None,
    }

    # Check K8s namespace if in kubernetes mode
    if settings.deployment_mode == "kubernetes":
        try:
            from ..services.orchestration.kubernetes_orchestrator import get_kubernetes_orchestrator

            orchestrator = get_kubernetes_orchestrator()
            namespace = orchestrator._get_namespace(str(project.id))
            namespace_exists = await orchestrator.k8s_client.namespace_exists(namespace)
            response["k8s_namespace"] = namespace
            response["k8s_namespace_exists"] = namespace_exists
        except Exception as e:
            response["k8s_namespace_error"] = str(e)

    # Check snapshots if hibernated
    if project.environment_status == "hibernated":
        try:
            from ..services.snapshot_manager import get_snapshot_manager

            snapshot_manager = get_snapshot_manager()
            snapshots = await snapshot_manager.get_project_snapshots(project.id, db)

            response["snapshot_count"] = len(snapshots)
            if snapshots:
                latest = snapshots[0]
                response["latest_snapshot"] = {
                    "name": latest.snapshot_name,
                    "status": latest.status,
                    "type": latest.snapshot_type,
                    "created_at": latest.created_at.isoformat() if latest.created_at else None,
                    "size_bytes": latest.volume_size_bytes,
                }
        except Exception as e:
            response["snapshot_error"] = str(e)

    return response
