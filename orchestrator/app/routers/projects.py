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

import httpx
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
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from ..auth_unified import get_authenticated_user
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
    ShellSession,
    User,
    UserPurchasedBase,
)
from ..permissions import Permission
from ..schemas import (
    BatchContentRequest,
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
    SetupConfigSyncResponse,
    TemplateExportRequest,
    TesslateConfigCreate,
    TesslateConfigResponse,
)
from ..schemas import BrowserPreview as BrowserPreviewSchema
from ..schemas import Container as ContainerSchema
from ..schemas import ContainerConnection as ContainerConnectionSchema
from ..schemas import Project as ProjectSchema
from ..schemas import ProjectFile as ProjectFileSchema
from ..services.secret_manager_env import build_env_overrides, get_injected_env_vars_for_container
from ..services.service_definitions import get_service
from ..services.task_manager import Task, get_task_manager
from ..users import current_optional_user
from ..utils.async_fileio import makedirs_async, read_file_async, walk_directory_async
from ..utils.resource_naming import get_project_path
from ..utils.slug_generator import generate_project_slug

logger = logging.getLogger(__name__)

router = APIRouter()


async def _resolve_container_url(
    db: AsyncSession,
    project: Project,
    container: Container | None,
    *,
    fallback_dir: str,
    protocol: str,
    app_domain: str,
) -> str:
    """Compute a public URL for a container, branching on app_role.

    Installed AppInstance projects render as
    ``{dir}-{app_handle}-{creator_handle}.{domain}`` (or
    ``{app_handle}-{creator_handle}.{domain}`` for single-container apps).
    Non-app user projects keep the legacy ``{project_slug}-{dir}.{domain}``.
    """
    from ..services.apps.runtime_urls import (
        container_url as _legacy_url,
    )
    from ..services.apps.runtime_urls import (
        resolve_app_url_for_container,
    )

    if container is not None and getattr(project, "app_role", "none") == "app_instance":
        url = await resolve_app_url_for_container(db, container, protocol=protocol)
        if url:
            return url
    return _legacy_url(
        project_slug=project.slug,
        container_dir_or_name=fallback_dir,
        app_domain=app_domain,
        protocol=protocol,
    )


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


async def get_project_by_slug(
    db: AsyncSession,
    project_slug: str,
    user_id_or_user: UUID | User,
    permission: Permission = Permission.PROJECT_VIEW,
) -> Project:
    """
    Fetch project and verify access via RBAC. Raises 403/404.

    Args:
        db: Database session
        project_slug: Project slug (e.g., "my-awesome-app-k3x8n2") or UUID string
        user_id_or_user: User ID (UUID) or User object to verify access
        permission: The permission required for this operation. Defaults to
            ``PROJECT_VIEW`` for read endpoints — **mutation endpoints MUST
            pass the permission appropriate to the operation** (e.g.
            ``FILE_WRITE`` for file saves, ``PROJECT_DELETE`` for deletion,
            ``CONTAINER_START_STOP`` for start/stop, ``PROJECT_SETTINGS``
            for settings changes). Passing the default on a mutation
            endpoint is a security bug: any team member who can see the
            project would be able to mutate it.

    Returns:
        Project object if found and user has access

    Raises:
        HTTPException 404 if project not found
        HTTPException 403 if user lacks permission
    """
    from ..auth_unified import enforce_permission_scope, enforce_project_scope
    from ..permissions import get_project_with_access

    user = user_id_or_user if isinstance(user_id_or_user, User) else None
    user_id = user_id_or_user.id if isinstance(user_id_or_user, User) else user_id_or_user

    # API key scope enforcement: check permission scopes before RBAC
    if user is not None:
        enforce_permission_scope(user, permission)

    project, _role = await get_project_with_access(db, project_slug, user_id, permission)

    # API key project scope enforcement: check project_ids restriction
    if user is not None:
        enforce_project_scope(user, project.id)

    return project


async def track_project_activity(project_id: UUID, db: AsyncSession) -> None:
    """Update last_activity timestamp on a project.

    Lightweight helper called from key project-scoped endpoints
    to track when a project was last accessed. Used by hibernation
    and scale-to-zero policies.
    """
    from sqlalchemy import update as sa_update

    await db.execute(
        sa_update(Project).where(Project.id == project_id).values(last_activity=func.now())
    )
    await db.commit()


@router.get("/", response_model=list[ProjectSchema])
async def get_projects(
    team: str | None = Query(None),
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    from ..models_team import ProjectMembership, Team, TeamMembership

    # Resolve active team
    if team:
        team_result = await db.execute(select(Team).where(Team.slug == team))
        active_team = team_result.scalar_one_or_none()
        if not active_team:
            raise HTTPException(status_code=404, detail="Team not found")
        team_id = active_team.id
    else:
        team_id = current_user.default_team_id

    if not team_id:
        return []

    # Check team membership
    membership_result = await db.execute(
        select(TeamMembership).where(
            and_(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == current_user.id,
                TeamMembership.is_active.is_(True),
            )
        )
    )
    member = membership_result.scalar_one_or_none()
    if not member and not getattr(current_user, "is_superuser", False):
        return []

    # Hide installed-app instance projects from the normal Projects list —
    # those are rendered in Library > Apps instead. Forks (app_source) remain.
    from ..services.apps.project_scopes import exclude_app_instances_clause

    app_role_filter = exclude_app_instances_clause()

    # Admins / superusers see all projects in the team
    if (member and member.role == "admin") or getattr(current_user, "is_superuser", False):
        result = await db.execute(
            select(Project).where(and_(Project.team_id == team_id, app_role_filter))
        )
    else:
        # Non-admin: team-visible projects + projects with explicit membership
        result = await db.execute(
            select(Project).where(
                and_(
                    Project.team_id == team_id,
                    app_role_filter,
                    or_(
                        Project.visibility == "team",
                        Project.id.in_(
                            select(ProjectMembership.project_id).where(
                                and_(
                                    ProjectMembership.user_id == current_user.id,
                                    ProjectMembership.is_active.is_(True),
                                )
                            )
                        ),
                    ),
                )
            )
        )

    projects = result.scalars().all()
    return projects


async def enforce_project_limit(user: User, db: AsyncSession) -> None:
    """Raise 403 if user has reached their tier's project limit."""
    from ..models_team import Team, TeamMembership

    settings = get_settings()
    team_id = user.default_team_id

    # Resolve the tier from the active team (billing lives on teams since RBAC)
    tier = "free"
    if team_id:
        team_result = await db.execute(select(Team).where(Team.id == team_id))
        team = team_result.scalar_one_or_none()
        if team:
            tier = team.subscription_tier or "free"

    if team_id:
        result = await db.execute(select(func.count(Project.id)).where(Project.team_id == team_id))
    else:
        # Fallback: count projects across all teams the user belongs to
        user_team_ids = select(TeamMembership.team_id).where(
            and_(TeamMembership.user_id == user.id, TeamMembership.is_active.is_(True))
        )
        result = await db.execute(
            select(func.count(Project.id)).where(Project.team_id.in_(user_team_ids))
        )
    current_count = result.scalar()
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
    """Background worker function that performs project setup operations."""
    from ..database import AsyncSessionLocal
    from ..services.project_setup import setup_project

    async with AsyncSessionLocal() as db:
        try:
            from sqlalchemy import select

            result = await db.execute(select(Project).where(Project.id == db_project_id))
            db_project = result.scalar_one()

            project_path = os.path.abspath(get_project_path(user_id, db_project.id))

            # Docker mode: ensure project directory exists
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

            # Run the unified pipeline
            await setup_project(
                project_data=project_data,
                db_project=db_project,
                user_id=user_id,
                settings=settings,
                db=db,
                task=task,
            )

            db_project.environment_status = "active"
            await db.commit()

            task.update_progress(100, 100, "Project setup complete")
            logger.info(f"[CREATE] Project {db_project.id} setup completed successfully")

            # Always send to setup screen so user can review detected apps
            # and optionally add infrastructure services (postgres, redis, etc.)
            return {"slug": db_project_slug, "container_id": "needs_setup"}

        except Exception as e:
            logger.error(f"[CREATE] Background task error: {e}", exc_info=True)
            # Mark the project as setup_failed so the UI shows an error
            # with retry/delete options instead of a broken project.
            try:
                db_project.environment_status = "setup_failed"
                await db.commit()
            except Exception:
                logger.warning("[CREATE] Failed to mark project %s as setup_failed", db_project_id)
            raise


def _resolve_default_runtime(settings) -> str:
    """Map deployment_mode → per-project runtime default.

    Desktop shells default new projects to the local runtime; cloud / server
    deployments keep the historical docker default so existing callers that
    omit ``runtime`` are unaffected.
    """
    mode = (settings.deployment_mode or "").lower()
    if mode == "desktop":
        return "local"
    if mode == "kubernetes":
        return "k8s"
    return "docker"


def _materialize_imported_root(source_path: str, project_root: str) -> None:
    """Point ``project_root`` at an existing ``source_path``.

    POSIX: create a symlink ``project_root → source_path``.
    Windows: create ``project_root`` as a plain directory containing a
    ``.tesslate-source`` marker file with the canonical source path — symlink
    creation on Windows typically requires elevation and is therefore
    unreliable for a desktop shell.
    """
    parent = os.path.dirname(project_root)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.lexists(project_root):
        return
    if os.name == "nt":
        os.makedirs(project_root, exist_ok=True)
        marker = os.path.join(project_root, ".tesslate-source")
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(source_path)
        return
    os.symlink(source_path, project_root)


async def create_project_from_payload(
    payload: ProjectCreate,
    *,
    current_user: User,
    db: AsyncSession,
) -> dict:
    """Shared core for ``POST /api/projects`` and ``POST /api/desktop/import``.

    Encapsulates permission + quota checks, slug collision handling, and the
    import-path vs. template branch. Returns the same shape both callers
    expose to clients: ``{"project", "task_id", "status_endpoint"}`` for the
    template flow, or ``{"project", "task_id": None, "status_endpoint": None}``
    for imports (no background setup required).
    """
    # Validate base_id is provided for base source type (skipped for imports).
    if not payload.import_path and payload.source_type == "base" and not payload.base_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A template must be selected to create a project. Please select a template and try again.",
        )

    # Team permission check (create).
    from ..permissions import check_team_permission

    if current_user.default_team_id:
        await check_team_permission(
            db, current_user.default_team_id, current_user.id, Permission.PROJECT_CREATE
        )

    await enforce_project_limit(current_user, db)

    settings = get_settings()
    resolved_runtime = payload.runtime or _resolve_default_runtime(settings)

    # Import branch: resolve + dedupe the source_path up-front.
    canonical_source: str | None = None
    if payload.import_path:
        expanded = os.path.expanduser(payload.import_path)
        if not os.path.isdir(expanded):
            raise HTTPException(
                status_code=400,
                detail=f"import_path is not a directory: {payload.import_path}",
            )
        canonical_source = os.path.realpath(expanded)

        dup = await db.execute(
            select(Project).where(
                Project.owner_id == current_user.id,
                Project.source_path == canonical_source,
            )
        )
        if dup.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A project already exists for this path: {canonical_source}",
            )

    project_slug = generate_project_slug(payload.name)
    max_retries = 10
    db_project: Project | None = None
    for attempt in range(max_retries):
        try:
            db_project = Project(
                name=payload.name,
                slug=project_slug,
                description=payload.description,
                owner_id=current_user.id,
                team_id=current_user.default_team_id,
                runtime=resolved_runtime,
                source_path=canonical_source,
            )
            db.add(db_project)
            await db.flush()

            from ..models_team import ProjectMembership

            creator_membership = ProjectMembership(
                project_id=db_project.id,
                user_id=current_user.id,
                role="admin",
                granted_by_id=current_user.id,
            )
            db.add(creator_membership)
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
                project_slug = generate_project_slug(payload.name)
                logger.warning(f"[CREATE] Slug collision, retrying with: {project_slug}")
            else:
                raise HTTPException(
                    status_code=500, detail=f"Failed to create project: {str(e)}"
                ) from e

    assert db_project is not None
    logger.info(f"[CREATE] Project {db_project.slug} (ID: {db_project.id}) created in database")

    # Import flow: materialize project root pointing at source and short-circuit.
    if canonical_source is not None:
        try:
            from ..services.orchestration.local import _get_project_root

            project_root = str(_get_project_root(db_project))
            _materialize_imported_root(canonical_source, project_root)
            db_project.environment_status = "active"
            await db.commit()
            await db.refresh(db_project)
        except Exception as exc:
            logger.warning(
                "[CREATE] import_path materialization failed for %s: %s",
                db_project.id,
                exc,
            )
        return {"project": db_project, "task_id": None, "status_endpoint": None}

    # Template flow: hand off to the existing background setup pipeline.
    task_manager = get_task_manager()
    task = task_manager.create_task(
        user_id=current_user.id,
        task_type="project_creation",
        metadata={
            "project_id": str(db_project.id),
            "project_slug": db_project.slug,
            "project_name": db_project.name,
            "source_type": payload.source_type,
        },
    )

    task_manager.start_background_task(
        task_id=task.id,
        coro=_perform_project_setup,
        project_data=payload,
        db_project_id=db_project.id,
        db_project_slug=db_project.slug,
        user_id=current_user.id,
        settings=settings,
    )

    logger.info(f"[CREATE] Background task {task.id} started for project {db_project.id}")

    return {
        "project": db_project,
        "task_id": task.id,
        "status_endpoint": f"/api/tasks/{task.id}",
    }


@router.post("/")
async def create_project(
    project: ProjectCreate,
    current_user: User = Depends(get_authenticated_user),
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
    logger.info(
        f"[CREATE] Creating project for user {current_user.id}: {project.name} "
        f"(source: {project.source_type}, base_id: {project.base_id}, "
        f"runtime={project.runtime}, import_path={project.import_path})"
    )
    try:
        return await create_project_from_payload(project, current_user=current_user, db=db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CREATE] Critical error during project creation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e)}") from e


@router.get("/{project_slug}/my-role")
async def get_my_project_role(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's effective role on a project (team role + project override)."""
    from ..permissions import get_effective_project_role

    project = await get_project_by_slug(db, project_slug, current_user.id)
    role = await get_effective_project_role(db, project, current_user.id)
    return {"role": role}


@router.get("/{project_slug}", response_model=ProjectSchema)
async def get_project(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a project by its slug."""
    project = await get_project_by_slug(db, project_slug, current_user)
    return project


@router.get("/{project_slug}/files/tree")
async def get_file_tree(
    project_slug: str,
    container_dir: str | None = None,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recursive filtered file tree (metadata only, no content)."""
    from ..services.volume_manager import VolumeRestoringError, VolumeUnavailableError

    project = await get_project_by_slug(db, project_slug, current_user)

    from ..services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()

    try:
        entries = await orchestrator.list_tree(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            subdir=container_dir,
        )
        return {"status": "ready", "files": entries}
    except VolumeRestoringError:
        return JSONResponse(
            status_code=202,
            content={
                "status": "restoring",
                "files": [],
                "message": "Project storage is being restored",
            },
        )
    except VolumeUnavailableError:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "files": [],
                "message": "Project storage is unavailable",
            },
        )


@router.get("/{project_slug}/git/tree")
async def get_git_tree(
    project_slug: str,
    branch: str | None = None,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Repository tree for the Repository panel.

    If the project has a GitHub remote, fetch the recursive tree from GitHub
    (using the user's OAuth token if connected, falling back to an
    unauthenticated request for public repos). If there's no GitHub remote or
    the GitHub API call fails, fall back to the local project file tree so the
    panel always has something useful to show.
    """
    from ..services.github_client import GitHubClient
    from ..services.volume_manager import VolumeRestoringError, VolumeUnavailableError

    project = await get_project_by_slug(db, project_slug, current_user)

    remote_url = getattr(project, "git_remote_url", None)
    parsed = GitHubClient.parse_repo_url(remote_url) if remote_url else None

    if parsed:
        access_token: str | None = None
        try:
            from ..services.credential_manager import get_credential_manager

            credential_manager = get_credential_manager()
            access_token = await credential_manager.get_access_token(db, current_user.id)
        except Exception as exc:
            logger.debug(f"[GIT_TREE] Could not retrieve GitHub token: {exc}")

        client = GitHubClient(access_token or "")
        try:
            result = await client.get_repository_tree(parsed["owner"], parsed["repo"], branch)

            files: list[dict[str, object]] = []
            for entry in result.get("tree", []):
                if not isinstance(entry, dict):
                    continue
                path = entry.get("path")
                if not isinstance(path, str) or not path:
                    continue
                is_dir = entry.get("type") == "tree"
                size_val = entry.get("size")
                files.append(
                    {
                        "path": path,
                        "name": path.rsplit("/", 1)[-1],
                        "is_dir": is_dir,
                        "size": int(size_val) if isinstance(size_val, int | float) else 0,
                        "mod_time": 0,
                        "sha": entry.get("sha"),
                    }
                )

            return {
                "status": "ready",
                "source": "github",
                "owner": parsed["owner"],
                "repo": parsed["repo"],
                "branch": result.get("branch"),
                "sha": result.get("sha"),
                "truncated": result.get("truncated", False),
                "html_url": f"https://github.com/{parsed['owner']}/{parsed['repo']}",
                "files": files,
            }
        except httpx.HTTPStatusError as exc:
            # 401 without token for a private repo, 404, rate-limit, etc.
            # Fall through to local tree below so the panel still works.
            logger.info(
                f"[GIT_TREE] GitHub fetch failed for {project_slug} "
                f"({parsed['owner']}/{parsed['repo']}): {exc.response.status_code}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[GIT_TREE] Unexpected GitHub error for {project_slug}: {exc}")

    # Fallback — local project file tree (same shape as /files/tree)
    from ..services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()
    try:
        entries = await orchestrator.list_tree(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            subdir=None,
        )
        return {
            "status": "ready",
            "source": "local",
            "owner": None,
            "repo": None,
            "branch": None,
            "sha": None,
            "truncated": False,
            "html_url": remote_url,
            "files": entries,
        }
    except VolumeRestoringError:
        return JSONResponse(
            status_code=202,
            content={
                "status": "restoring",
                "source": "local",
                "files": [],
                "message": "Project storage is being restored",
            },
        )
    except VolumeUnavailableError:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "source": "local",
                "files": [],
                "message": "Project storage is unavailable",
            },
        )


async def _resolve_github_client(
    db: AsyncSession,
    project: Project,
    user: User,
) -> tuple[str, str, object] | None:
    """Resolve (owner, repo, client) for a project's GitHub remote.

    Returns ``None`` when the project has no GitHub remote or the URL is not
    parseable. The returned client is authenticated when the user has a
    GitHub OAuth token available; otherwise falls back to unauthenticated
    requests (public repos only).
    """
    from ..services.github_client import GitHubClient

    remote_url = getattr(project, "git_remote_url", None)
    parsed = GitHubClient.parse_repo_url(remote_url) if remote_url else None
    if not parsed:
        return None

    access_token: str | None = None
    try:
        from ..services.credential_manager import get_credential_manager

        credential_manager = get_credential_manager()
        access_token = await credential_manager.get_access_token(db, user.id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[GIT] Could not retrieve GitHub token: {exc}")

    return parsed["owner"], parsed["repo"], GitHubClient(access_token or "")


def _no_remote_payload(kind: str) -> dict[str, object]:
    """Return a friendly 'connect GitHub to see X' envelope."""
    return {
        "status": "no_remote",
        "message": f"Connect a GitHub remote to see {kind}.",
    }


def _error_payload(kind: str, exc: Exception) -> dict[str, object]:
    """Return a safe error envelope for GitHub failures.

    We intentionally surface errors as HTTP 200 bodies so the read-only
    Repository panel can render a friendly empty state without triggering
    axios error handlers or retry storms. The panel is non-critical — "no
    data" is always an acceptable outcome.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return {
            "status": "error",
            "message": f"GitHub returned {exc.response.status_code}",
            "http_status": exc.response.status_code,
        }
    return {
        "status": "error",
        "message": f"Could not load {kind} from GitHub",
    }


@router.get("/{project_slug}/git/commits")
async def get_git_commits(
    project_slug: str,
    branch: str | None = None,
    limit: int = 30,
    include_stats: bool = False,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent commits for the Repository panel (Overview + Graph tabs).

    Returns up to ``limit`` commits (capped at 100) from the given branch (or
    default branch if not specified). When ``include_stats=true`` each commit
    is enriched with a ``files_changed`` count via the per-commit GitHub
    endpoint — this costs one extra request per commit so it is bounded to
    the first 30 commits and only used when explicitly requested.

    Shape (per commit):
        sha: str
        short_sha: str (first 7)
        message: str
        title: str (first line only)
        author: {login, avatar_url, name, email, date}
        committer: {...}
        parents: [sha]
        html_url: str
        files_changed: int | None (only when include_stats=true)
    """
    project = await get_project_by_slug(db, project_slug, current_user)
    resolved = await _resolve_github_client(db, project, current_user)
    if resolved is None:
        return _no_remote_payload("commit history")

    owner, repo, client = resolved
    capped = max(1, min(limit, 100))

    try:
        raw_commits = await client.list_commits(owner, repo, sha=branch, per_page=capped)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"[GIT_COMMITS] Failed for {project_slug}: {exc}")
        return _error_payload("commit history", exc)

    def _normalize(commit: dict[str, object]) -> dict[str, object]:
        sha = str(commit.get("sha") or "")
        commit_body = commit.get("commit") or {}
        if not isinstance(commit_body, dict):
            commit_body = {}
        author_meta = commit_body.get("author") or {}
        if not isinstance(author_meta, dict):
            author_meta = {}
        author_user = commit.get("author") or {}
        if not isinstance(author_user, dict):
            author_user = {}
        committer_meta = commit_body.get("committer") or {}
        if not isinstance(committer_meta, dict):
            committer_meta = {}
        committer_user = commit.get("committer") or {}
        if not isinstance(committer_user, dict):
            committer_user = {}
        parents_raw = commit.get("parents") or []
        parents: list[str] = []
        if isinstance(parents_raw, list):
            for p in parents_raw:
                if isinstance(p, dict) and isinstance(p.get("sha"), str):
                    parents.append(p["sha"])
        message = str(commit_body.get("message") or "")
        title = message.split("\n", 1)[0] if message else ""
        return {
            "sha": sha,
            "short_sha": sha[:7] if sha else "",
            "message": message,
            "title": title,
            "html_url": commit.get("html_url"),
            "parents": parents,
            "author": {
                "login": author_user.get("login"),
                "avatar_url": author_user.get("avatar_url"),
                "name": author_meta.get("name"),
                "email": author_meta.get("email"),
                "date": author_meta.get("date"),
            },
            "committer": {
                "login": committer_user.get("login"),
                "avatar_url": committer_user.get("avatar_url"),
                "name": committer_meta.get("name"),
                "email": committer_meta.get("email"),
                "date": committer_meta.get("date"),
            },
            "files_changed": None,
        }

    commits = [_normalize(c) for c in raw_commits if isinstance(c, dict)]

    if include_stats and commits:
        # Bounded enrichment — cap at 30 parallel requests to stay polite
        # against GitHub rate limits and keep the response non-blocking.
        stats_cap = min(len(commits), 30)

        async def _enrich(commit: dict[str, object]) -> None:
            sha = commit.get("sha")
            if not isinstance(sha, str) or not sha:
                return
            try:
                detail = await client.get_commit(owner, repo, sha)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[GIT_COMMITS] stats fetch failed for {sha}: {exc}")
                return
            files = detail.get("files") if isinstance(detail, dict) else None
            if isinstance(files, list):
                commit["files_changed"] = len(files)

        await asyncio.gather(*[_enrich(c) for c in commits[:stats_cap]])

    return {
        "status": "ready",
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "html_url": f"https://github.com/{owner}/{repo}",
        "commits": commits,
    }


@router.get("/{project_slug}/git/branches")
async def get_git_branches(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """List branches with ahead/behind-default counts.

    For each non-default branch we call ``GET /compare/{default}...{branch}``
    to get ``ahead_by`` / ``behind_by``. Comparisons run concurrently; if
    any individual compare fails (e.g. on orphaned branches) we fall back to
    ``None`` for that branch's counts rather than failing the whole request.
    """
    project = await get_project_by_slug(db, project_slug, current_user)
    resolved = await _resolve_github_client(db, project, current_user)
    if resolved is None:
        return _no_remote_payload("branches")

    owner, repo, client = resolved

    try:
        repo_info = await client.get_repository_info(owner, repo)
        default_branch = str(repo_info.get("default_branch") or "main")
        raw_branches = await client.list_branches(owner, repo, per_page=100)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"[GIT_BRANCHES] Failed for {project_slug}: {exc}")
        return _error_payload("branches", exc)

    async def _compare(name: str) -> dict[str, object] | None:
        if name == default_branch:
            return {"ahead_by": 0, "behind_by": 0}
        try:
            cmp_result = await client.compare_commits(owner, repo, default_branch, name)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[GIT_BRANCHES] compare {name} failed: {exc}")
            return None
        return {
            "ahead_by": cmp_result.get("ahead_by"),
            "behind_by": cmp_result.get("behind_by"),
        }

    names = [
        str(b.get("name"))
        for b in raw_branches
        if isinstance(b, dict) and isinstance(b.get("name"), str)
    ]
    compares = await asyncio.gather(*[_compare(n) for n in names])

    branches: list[dict[str, object]] = []
    for b, cmp in zip(raw_branches, compares, strict=False):
        if not isinstance(b, dict):
            continue
        name = b.get("name")
        if not isinstance(name, str):
            continue
        commit = b.get("commit") if isinstance(b.get("commit"), dict) else {}
        sha = commit.get("sha") if isinstance(commit, dict) else None
        branches.append(
            {
                "name": name,
                "is_default": name == default_branch,
                "protected": bool(b.get("protected")),
                "sha": sha,
                "html_url": (f"https://github.com/{owner}/{repo}/tree/{name}" if name else None),
                "ahead_by": (cmp or {}).get("ahead_by"),
                "behind_by": (cmp or {}).get("behind_by"),
            }
        )

    # Default branch first, then alphabetical for predictability.
    branches.sort(key=lambda b: (not b["is_default"], b["name"]))

    return {
        "status": "ready",
        "owner": owner,
        "repo": repo,
        "default_branch": default_branch,
        "html_url": f"https://github.com/{owner}/{repo}",
        "branches": branches,
    }


@router.get("/{project_slug}/git/repo-info")
async def get_git_repo_info(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate stats for the Overview tab.

    Runs repo info, contributors list and open-PR list concurrently so the
    panel gets everything in one round-trip. Any sub-call that fails returns
    a safe default so the Overview tab degrades gracefully.
    """
    project = await get_project_by_slug(db, project_slug, current_user)
    resolved = await _resolve_github_client(db, project, current_user)
    if resolved is None:
        return _no_remote_payload("repository info")

    owner, repo, client = resolved

    async def _info() -> dict[str, object] | None:
        try:
            return await client.get_repository_info(owner, repo)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"[GIT_REPO_INFO] info failed: {exc}")
            return None

    async def _contributors() -> list[dict[str, object]]:
        try:
            result = await client.list_contributors(owner, repo, per_page=30)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"[GIT_REPO_INFO] contributors failed: {exc}")
            return []
        return result if isinstance(result, list) else []

    async def _pulls() -> list[dict[str, object]]:
        try:
            result = await client.list_pulls(owner, repo, state="open", per_page=30)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"[GIT_REPO_INFO] pulls failed: {exc}")
            return []
        return result if isinstance(result, list) else []

    info, contributors_raw, pulls_raw = await asyncio.gather(_info(), _contributors(), _pulls())

    if info is None:
        return _error_payload("repository info", Exception("info fetch failed"))

    contributors = [
        {
            "login": c.get("login"),
            "avatar_url": c.get("avatar_url"),
            "contributions": c.get("contributions"),
            "html_url": c.get("html_url"),
        }
        for c in contributors_raw
        if isinstance(c, dict)
    ]

    open_prs = [
        {
            "number": p.get("number"),
            "title": p.get("title"),
            "html_url": p.get("html_url"),
            "user": (
                {
                    "login": p["user"].get("login"),
                    "avatar_url": p["user"].get("avatar_url"),
                }
                if isinstance(p.get("user"), dict)
                else None
            ),
            "created_at": p.get("created_at"),
            "draft": p.get("draft"),
        }
        for p in pulls_raw
        if isinstance(p, dict)
    ]

    topics = info.get("topics")
    if not isinstance(topics, list):
        topics = []

    return {
        "status": "ready",
        "owner": owner,
        "repo": repo,
        "html_url": info.get("html_url") or f"https://github.com/{owner}/{repo}",
        "description": info.get("description"),
        "default_branch": info.get("default_branch") or "main",
        "stars": info.get("stargazers_count"),
        "watchers": info.get("watchers_count"),
        "forks": info.get("forks_count"),
        "open_issues": info.get("open_issues_count"),
        "pushed_at": info.get("pushed_at"),
        "updated_at": info.get("updated_at"),
        "created_at": info.get("created_at"),
        "is_private": info.get("private"),
        "topics": topics,
        "contributors": contributors,
        "open_pulls": open_prs,
        "open_pulls_count": len(open_prs),
    }


@router.get("/{project_slug}/files/content")
async def get_file_content(
    project_slug: str,
    path: str,
    container_dir: str | None = None,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Get content of a single file."""
    from ..services.volume_manager import VolumeRestoringError, VolumeUnavailableError

    project = await get_project_by_slug(db, project_slug, current_user)

    from ..services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()

    try:
        result = await orchestrator.read_file_content(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            file_path=path,
            subdir=container_dir,
        )
        if result is None:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")
        return (
            {"status": "ready", **result}
            if isinstance(result, dict)
            else {"status": "ready", "content": result}
        )
    except VolumeRestoringError:
        return JSONResponse(
            status_code=202,
            content={
                "status": "restoring",
                "message": "Project storage is being restored",
            },
        )
    except VolumeUnavailableError:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "message": "Project storage is unavailable",
            },
        )


@router.post("/{project_slug}/files/content/batch")
async def get_files_content_batch(
    project_slug: str,
    body: BatchContentRequest,
    container_dir: str | None = None,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Batch-read multiple files in one request."""
    from ..services.volume_manager import VolumeRestoringError, VolumeUnavailableError

    project = await get_project_by_slug(db, project_slug, current_user)

    from ..services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()

    try:
        files, errors = await orchestrator.read_files_batch(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            paths=body.paths,
            subdir=container_dir,
        )
        return {"status": "ready", "files": files, "errors": errors}
    except VolumeRestoringError:
        return JSONResponse(
            status_code=202,
            content={
                "status": "restoring",
                "files": [],
                "errors": [],
                "message": "Project storage is being restored",
            },
        )
    except VolumeUnavailableError:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "files": [],
                "errors": [],
                "message": "Project storage is unavailable",
            },
        )


@router.get("/{project_slug}/files", response_model=list[ProjectFileSchema])
async def get_project_files(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
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
    project = await get_project_by_slug(db, project_slug, current_user)
    project_id = project.id  # For internal operations

    get_settings()

    # Check if this project has a host-reachable filesystem path (docker shared
    # volume, or desktop $OPENSAIL_HOME). K8s projects go through
    # orchestrator FileOps in the next branch.
    from ..services.project_fs import get_project_fs_path, read_all_files

    fs_path = get_project_fs_path(project) if from_volume else None
    if fs_path is not None:
        try:
            subdir_log = f"/{container_dir}" if container_dir else ""
            logger.info(f"[FILES] Reading files from project filesystem: {fs_path}{subdir_log}")

            volume_files = await read_all_files(
                fs_path,
                max_files=200,
                max_file_size=100_000,
                subdir=container_dir,
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
    current_user: User = Depends(get_authenticated_user),
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
    project = await get_project_by_slug(db, project_slug, current_user)
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


# =============================================================================
# Volume Health & Recovery
# =============================================================================


@router.get("/{project_slug}/volume/status")
async def get_volume_status(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Check current volume health — cached, restoring, unavailable, unreachable.

    Used by the frontend to show recovery options when a project's
    storage is in an error state.
    """
    from ..services.volume_manager import (
        VolumeOwnerUnreachableError,
        VolumeRestoringError,
        VolumeUnavailableError,
        get_volume_manager,
    )

    project = await get_project_by_slug(db, project_slug, current_user)

    if not project.volume_id:
        return {"status": "no_volume", "message": "Project has no volume"}

    vm = get_volume_manager()
    try:
        resp = await vm.resolve_volume(project.volume_id)
        return {
            "status": "healthy",
            "node": resp.get("node_name", ""),
            "volume_id": project.volume_id,
        }
    except VolumeRestoringError:
        return JSONResponse(
            status_code=202,
            content={
                "status": "restoring",
                "volume_id": project.volume_id,
                "message": "Volume is being restored from backup",
                "recoverable": True,
            },
        )
    except VolumeOwnerUnreachableError:
        return {
            "status": "unreachable",
            "volume_id": project.volume_id,
            "message": "Volume node is temporarily unreachable",
            "recoverable": True,
        }
    except VolumeUnavailableError:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "volume_id": project.volume_id,
                "message": "Volume is unavailable",
                "recoverable": True,
            },
        )


@router.post("/{project_slug}/volume/recover")
async def recover_volume(
    project_slug: str,
    request: Request,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Recover a project volume to a live node.

    Optionally restore to a specific CAS snapshot (target_hash).
    Without target_hash, recovers to the latest synced state (HEAD).

    This endpoint is used by:
    - "Recover Now" button (no target_hash)
    - "Restore to Snapshot" button (with target_hash from Timeline)
    """
    from ..services.hub_client import NodeResourcesExhausted
    from ..services.volume_manager import get_volume_manager

    project = await get_project_by_slug(db, project_slug, current_user)

    if not project.volume_id:
        raise HTTPException(status_code=404, detail="Project has no volume")

    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    target_hash = body.get("target_hash")

    vm = get_volume_manager()
    try:
        result = await vm.recover_volume(
            project.volume_id,
            target_hash=target_hash,
        )
    except NodeResourcesExhausted as exc:
        raise HTTPException(
            status_code=503,
            detail="No nodes available with enough resources for recovery",
        ) from exc
    except Exception as e:
        logger.error("[VOLUME] Recovery failed for %s: %s", project.volume_id, e)
        raise HTTPException(status_code=503, detail=f"Recovery failed: {e}") from e

    # Update project's cache_node
    project.cache_node = result["node_name"]
    await db.commit()

    return {
        "status": "recovered",
        "node": result["node_name"],
        "action": result["action"],
        "restored_hash": result.get("restored_hash"),
    }


@router.get("/{project_slug}/container-status")
async def get_container_status(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed status of the development container/pod.

    Returns readiness, phase, and detailed status information.
    Frontend should poll this endpoint to know when pod is ready.
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user)
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
                protocol = settings.k8s_container_url_protocol
                container_url = await _resolve_container_url(
                    db,
                    project,
                    first_container,
                    fallback_dir=container_dir,
                    protocol=protocol,
                    app_domain=settings.app_domain,
                )

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Save a file to the user's dev container.

    Architecture: Backend is stateless and doesn't store files.
    Instead, it writes files directly to the dev container pod via K8s API.
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file or directory from the user's dev container."""
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_DELETE)
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename / move a file or directory inside the user's dev container."""
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a directory in the project volume via FileOps.

    Works without a running compute pod — writes directly to the btrfs
    volume through the CSI driver's FileOps gRPC service.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)
    dir_path = _validate_file_path(body.dir_path)

    try:
        from ..services.orchestration import is_kubernetes_mode

        if is_kubernetes_mode() and project.volume_id:
            from ..services.volume_manager import get_volume_manager

            vm = get_volume_manager()
            client = await vm.get_fileops_client(project.volume_id)
            async with client:
                await client.mkdir_all(project.volume_id, f"/{dir_path}")
        else:
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
    current_user: User = Depends(get_authenticated_user),
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
    project = await get_project_by_slug(db, project_slug, current_user)
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
            # Capture volume_id now — project row is deleted later in step 3
            volume_id: str | None = getattr(project, "volume_id", None) if project else None

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

        # Clean up btrfs volume and CAS data via Hub (fire-and-forget).
        # If Hub is unreachable, the GC collector will clean up eventually.
        if project and project.volume_id:
            try:
                from ..services.volume_manager import VolumeManager

                vm = VolumeManager()
                await vm.delete_volume(project.volume_id)
            except Exception:
                logger.warning(
                    "Failed to delete volume %s for project %s (GC will clean up)",
                    project.volume_id,
                    project.slug,
                )

        task.update_progress(30, 100, "Deleting chats and messages...")

        # 2. Delete all chats associated with this project (and their messages will cascade)
        chats_result = await db.execute(select(Chat).where(Chat.project_id == project_id))
        project_chats = chats_result.scalars().all()

        for chat in project_chats:
            logger.info(f"[DELETE] Deleting chat {chat.id} with messages")
            await db.delete(chat)  # Use ORM delete to trigger cascades

        logger.info(f"[DELETE] Deleted {len(project_chats)} chats and their messages")

        task.update_progress(45, 100, "Closing shell sessions...")

        # 2b. Close any active shell sessions before deletion
        await db.execute(
            sql_update(ShellSession)
            .where(ShellSession.project_id == project_id, ShellSession.status == "active")
            .values(status="closed", closed_at=func.now())
        )
        await db.commit()

        settings = get_settings()

        # 2c. K8s mode only: soft-delete snapshots BEFORE the project row is
        #     deleted. The snapshots relationship uses passive_deletes=True, so
        #     db.delete(project) will NOT cascade-delete snapshot rows — the DB's
        #     ondelete="SET NULL" only nullifies project_id. Soft-deleting here
        #     ensures the 30-day retention CronJob can still find these rows and
        #     clean up K8s VolumeSnapshots after expiry.
        if settings.deployment_mode == "kubernetes":
            try:
                from ..services.snapshot_manager import get_snapshot_manager

                snapshot_manager = get_snapshot_manager()
                deleted_count = await snapshot_manager.soft_delete_project_snapshots(project_id, db)
                if deleted_count > 0:
                    logger.info(
                        f"[DELETE] Soft-deleted {deleted_count} snapshots for project {project_id} (30-day retention)"
                    )
            except Exception as e:
                logger.warning(f"[DELETE] Error soft-deleting snapshots (continuing): {e}")

        task.update_progress(50, 100, "Removing project from database...")

        # 3. Delete project from database. Snapshot rows are NOT cascaded (passive_deletes=True
        #    on the relationship) — the DB-level ondelete="SET NULL" nullifies their project_id.
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()
        if project:
            await db.delete(project)
            await db.commit()
            logger.info("[DELETE] Deleted project from database")

        task.update_progress(70, 100, "Deleting project files...")

        # 4. Delete project files — shared volume (docker) or on-disk project
        # directory (desktop). K8s owns files in per-project PVCs so cleanup
        # happens in the namespace-delete branch below.
        from ..services.project_fs import get_project_fs_path

        fs_path = get_project_fs_path(project) if project else None
        if settings.deployment_mode == "docker" and project:
            try:
                await orchestrator.delete_project_directory(project.slug)
                logger.info(f"[DELETE] Deleted project directory: /projects/{project.slug}")
            except Exception as e:
                logger.warning(f"[DELETE] Failed to delete project directory: {e}")

        elif fs_path is not None and fs_path.exists():
            # Desktop: direct filesystem cleanup.
            import shutil

            try:
                await asyncio.to_thread(shutil.rmtree, fs_path)
                logger.info(f"[DELETE] Deleted desktop project directory: {fs_path}")
            except Exception as e:
                logger.warning(f"[DELETE] Failed to delete desktop project dir {fs_path}: {e}")
            # Drop the cached per-project root so a future project reusing the
            # id (unlikely) or slug doesn't hit a stale mapping.
            try:
                from ..services.orchestration.local import _invalidate_project_root_cache

                _invalidate_project_root_cache(project.id if project else None)
            except Exception:
                pass

        else:
            # Kubernetes mode: Delete K8s resources. Snapshot soft-delete already
            # happened in step 2c above, before the project row was removed.
            logger.info("[DELETE] Kubernetes mode: Cleaning up K8s resources...")

            # 4a. Delete Kubernetes namespace and all resources
            try:
                # Delete entire namespace (cascades to all pods, services, ingresses, PVCs)
                await orchestrator.delete_project_namespace(project_id=project_id, user_id=user_id)
                logger.info(
                    f"[DELETE] Deleted K8s namespace and resources for project {project_slug}"
                )
            except Exception as e:
                logger.warning(f"[DELETE] Error deleting K8s resources: {e}")

            # 4b. Delete compute-pool PVC/PV for this volume (prevents quota exhaustion)
            if volume_id:
                try:
                    from ..services.compute_manager import get_compute_manager

                    await get_compute_manager().delete_compute_pool_pvc(volume_id)
                except Exception as e:
                    logger.warning(
                        f"[DELETE] Error deleting compute-pool PVC for volume {volume_id}: {e}"
                    )

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a project and ALL associated data including chats, messages, files, and containers.

    This is a non-blocking operation. The deletion happens in the background and you can
    track its progress using the returned task_id.
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user, Permission.PROJECT_DELETE)
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Read .tesslate/config.json from the project filesystem/PVC.
    """
    project = await get_project_by_slug(db, project_slug, current_user)
    await track_project_activity(project.id, db)
    get_settings()

    from ..services.base_config_parser import read_tesslate_config

    config_data = None

    from ..services.project_fs import get_project_fs_path

    fs_path = get_project_fs_path(project)
    if fs_path is not None:
        # Host-reachable filesystem (docker volume mount or desktop home).
        config_data = read_tesslate_config(str(fs_path))
    else:
        # K8s: read from PVC via orchestrator
        from ..services.orchestration import get_orchestrator

        orchestrator = get_orchestrator()

        # Volume routing hints for FileOps
        volume_hints = {
            "volume_id": project.volume_id,
            "cache_node": project.cache_node,
        }

        try:
            config_json = await orchestrator.read_file(
                user_id=current_user.id,
                project_id=project.id,
                container_name=None,
                file_path=".tesslate/config.json",
                project_slug=project.slug,
                **volume_hints,
            )
            if config_json:
                from ..services.base_config_parser import parse_tesslate_config

                config_data = parse_tesslate_config(config_json)
        except Exception as e:
            logger.debug(f"[SETUP-CONFIG] Could not read config from K8s: {e}")

    if config_data:
        response: dict = {
            "exists": True,
            "apps": {
                name: {
                    "directory": app.directory,
                    "port": app.port,
                    "start": app.start,
                    **({"build": app.build} if app.build else {}),
                    **({"output": app.output} if app.output else {}),
                    **({"framework": app.framework} if app.framework else {}),
                    "env": app.env,
                    **({"exports": app.exports} if app.exports else {}),
                    "x": app.x,
                    "y": app.y,
                }
                for name, app in config_data.apps.items()
            },
            "infrastructure": {
                name: {
                    **({"image": infra.image} if infra.image else {}),
                    **({"port": infra.port} if infra.port else {}),
                    **({"env": infra.env} if infra.env else {}),
                    **({"exports": infra.exports} if infra.exports else {}),
                    **({"type": infra.infra_type} if infra.infra_type != "container" else {}),
                    **({"provider": infra.provider} if infra.provider else {}),
                    **({"endpoint": infra.endpoint} if infra.endpoint else {}),
                    "x": infra.x,
                    "y": infra.y,
                }
                for name, infra in config_data.infrastructure.items()
            },
            "primaryApp": config_data.primaryApp,
        }
        if config_data.connections:
            response["connections"] = [
                {"from": c.from_node, "to": c.to_node} for c in config_data.connections
            ]
        if config_data.deployments:
            response["deployments"] = {
                name: {
                    "provider": dep.provider,
                    "targets": dep.targets,
                    **({"env": dep.env} if dep.env else {}),
                    "x": dep.x,
                    "y": dep.y,
                }
                for name, dep in config_data.deployments.items()
            }
        if config_data.previews:
            response["previews"] = {
                name: {"target": prev.target, "x": prev.x, "y": prev.y}
                for name, prev in config_data.previews.items()
            }
        return response

    # Nothing found
    return {
        "exists": False,
        "apps": {},
        "infrastructure": {},
        "primaryApp": "",
    }


async def _auto_start_project(project_id: UUID, project_slug: str, user_id: UUID) -> None:
    """Background task: start all containers for a freshly configured project.

    Opens its own DB session because the caller's session ends with the
    response. Never raises — a failed auto-start logs a warning but doesn't
    leave the user stuck with no response.
    """
    from ..database import AsyncSessionLocal
    from ..services.orchestration import get_orchestrator

    try:
        async with AsyncSessionLocal() as bg_db:
            proj_result = await bg_db.execute(select(Project).where(Project.id == project_id))
            bg_project = proj_result.scalar_one_or_none()
            if bg_project is None:
                return

            containers_result = await bg_db.execute(
                select(Container)
                .where(Container.project_id == project_id)
                .options(selectinload(Container.base))
            )
            containers = list(containers_result.scalars().all())
            if not containers:
                return

            conns_result = await bg_db.execute(
                select(ContainerConnection).where(ContainerConnection.project_id == project_id)
            )
            connections = list(conns_result.scalars().all())

            orchestrator = get_orchestrator()
            await orchestrator.start_project(bg_project, containers, connections, user_id, bg_db)
            logger.info(f"[AUTO_START] Started containers for new project {project_slug}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[AUTO_START] Failed to auto-start project {project_slug}: {exc}")


@router.post("/{project_slug}/setup-config", response_model=SetupConfigSyncResponse)
async def save_setup_config(
    project_slug: str,
    config_data: TesslateConfigCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Save .tesslate/config.json and replace the project's container graph.

    When this is the first config sync (no existing containers), auto-start
    the newly created containers so the user lands on a running environment
    rather than having to click 'Start Environment'. Subsequent syncs (canvas
    edits on an already-configured project) do not auto-start — that would
    interrupt a user editing their running project.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)
    await track_project_activity(project.id, db)

    from ..services.config_sync import ConfigSyncError, sync_project_config

    # Detect first-sync before running the sync (afterwards, containers exist)
    pre_count_result = await db.execute(
        select(func.count(Container.id)).where(Container.project_id == project.id)
    )
    is_first_sync = (pre_count_result.scalar() or 0) == 0

    try:
        result = await sync_project_config(db, project, config_data, current_user.id)
    except ConfigSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if is_first_sync and result.container_ids and can_auto_start(project):
        background_tasks.add_task(_auto_start_project, project.id, project.slug, current_user.id)

    return result


def can_auto_start(project: Project) -> bool:
    """Gate auto-start to healthy environment states.

    Don't auto-start if the environment is mid-transition (provisioning,
    starting, stopping) or in an error state — a background start there
    would race with the active workflow.
    """
    status_value = getattr(project, "environment_status", None)
    return status_value in {None, "active", "stopped"}


@router.post("/{project_slug}/sync-config")
async def sync_config_to_file(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Save current canvas state (DB) to .tesslate/config.json.

    Reads all Container, ContainerConnection, DeploymentTarget, and BrowserPreview
    records for the project and writes a complete config.json.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)
    await track_project_activity(project.id, db)
    get_settings()

    from ..services.base_config_parser import (
        serialize_config_to_json,
        write_tesslate_config,
    )
    from ..services.config_sync import build_config_from_db

    config = await build_config_from_db(db, project.id)

    # Write to filesystem (host-reachable) or FileOps (K8s)
    from ..services.project_fs import get_project_fs_path

    fs_path = get_project_fs_path(project)
    if fs_path is not None:
        write_tesslate_config(str(fs_path), config)
    else:
        from ..services.orchestration import get_orchestrator

        orchestrator = get_orchestrator()
        volume_hints = {
            "volume_id": project.volume_id,
            "cache_node": project.cache_node,
        }
        config_json = serialize_config_to_json(config)
        await orchestrator.write_file(
            user_id=current_user.id,
            project_id=project.id,
            container_name=None,
            file_path=".tesslate/config.json",
            content=config_json,
            project_slug=project.slug,
            **volume_hints,
        )

    return {
        "status": "saved",
        "sections": {
            "apps": len(config.apps),
            "infrastructure": len(config.infrastructure),
            "connections": len(config.connections),
            "deployments": len(config.deployments),
            "previews": len(config.previews),
        },
    }


@router.post("/{project_slug}/analyze", response_model=TesslateConfigResponse)
async def analyze_project(
    project_slug: str,
    model: str | None = None,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze project files and generate .tesslate/config.json using LLM.
    Returns a TesslateConfigResponse with the generated configuration.
    """

    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)
    get_settings()

    # Read file tree from filesystem/PVC
    file_tree = []
    config_files_content = {}

    CONFIG_FILENAMES = {
        "package.json",
        "requirements.txt",
        "go.mod",
        "Cargo.toml",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "Makefile",
        "pyproject.toml",
        "pubspec.yaml",
        "Gemfile",
        "composer.json",
        "pom.xml",
        "build.gradle",
        "mix.exs",
        ".tesslate/config.json",
    }
    SKIP_DIRS = {
        "node_modules",
        ".git",
        "dist",
        "build",
        ".next",
        "__pycache__",
        ".venv",
        "vendor",
        "target",
    }
    COMMON_SUBDIRS = ["", "frontend", "backend", "client", "server", "api", "web", "app", "src"]

    from ..services.project_fs import get_project_fs_path

    fs_path = get_project_fs_path(project)
    if fs_path is not None:
        project_path = str(fs_path)
        try:
            walk_results = await walk_directory_async(project_path, exclude_dirs=list(SKIP_DIRS))
            for root, _dirs, files in walk_results:
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
                file_tree = [
                    f.get("path", f.get("name", "")) for f in files_list if isinstance(f, dict)
                ]
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

            db_files_result = await db.execute(select(PF).where(PF.project_id == project.id))
            for pf in db_files_result.scalars().all():
                fp = pf.file_path
                # Skip dirs we don't care about
                if any(skip in fp for skip in SKIP_DIRS):
                    continue
                file_tree.append(fp)
                basename = os.path.basename(fp)
                if (
                    (basename in CONFIG_FILENAMES or fp in CONFIG_FILENAMES)
                    and pf.content
                    and len(pf.content) < 20000
                ):
                    config_files_content[fp] = pf.content

    if not file_tree:
        raise HTTPException(status_code=400, detail="No files found in project to analyze")

    # Call shared config resolver LLM function
    try:
        from ..services.project_setup.config_resolver import generate_config_via_llm

        try:
            config = await generate_config_via_llm(
                file_tree=sorted(file_tree)[:500],
                config_files_content=dict(list(config_files_content.items())[:15]),
                user_id=current_user.id,
                db=db,
                model=model,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

        if not config:
            raise HTTPException(
                status_code=422,
                detail="AI could not parse the project structure. Try a different model or use manual setup.",
            )

        # Convert to response format
        return {
            "exists": False,
            "apps": {
                name: {
                    "directory": app.directory,
                    "port": app.port,
                    "start": app.start,
                    **({"build": app.build} if app.build else {}),
                    **({"output": app.output} if app.output else {}),
                    **({"framework": app.framework} if app.framework else {}),
                    "env": app.env,
                }
                for name, app in config.apps.items()
            },
            "infrastructure": {
                name: {
                    "image": infra.image,
                    "port": infra.port,
                }
                for name, infra in config.infrastructure.items()
            },
            "primaryApp": config.primaryApp,
        }

    except HTTPException:
        raise
    except Exception as e:
        error_str = str(e).lower()
        if (
            "429" in str(e)
            or "rate" in error_str
            or "resource_exhausted" in error_str
            or "throttl" in error_str
        ):
            logger.warning(f"[ANALYZE] Rate limited by LLM provider: {e}")
            raise HTTPException(
                status_code=429,
                detail="AI model is temporarily rate-limited. Please try again in a moment.",
            ) from e
        if "400" in str(e) or "invalid model" in error_str:
            logger.warning(f"[ANALYZE] Invalid model: {e}")
            raise HTTPException(
                status_code=400, detail="Invalid model. Please select a different model."
            ) from e
        logger.error(f"[ANALYZE] Failed to analyze project: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to analyze project: {str(e)}") from e


@router.get("/{project_slug}/settings")
async def get_project_settings(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Get project settings."""
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Update project settings."""
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user, Permission.PROJECT_SETTINGS)

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


@router.patch("/{project_slug}/app-role", response_model=ProjectSchema)
async def set_project_app_role(
    project_slug: str,
    payload: dict,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Flip a project between `null` (regular) and `app_source` (publishable).

    Transitions allowed: ``None ↔ 'app_source'``. An ``app_instance`` project
    is an installed app — not a creator surface — and may NOT be re-roled.
    """
    from ..permissions import get_project_with_access

    # Accept {"app_role": "app_source" | null} from the request body.
    if not isinstance(payload, dict) or "app_role" not in payload:
        raise HTTPException(status_code=400, detail="missing 'app_role' field")
    requested = payload["app_role"]
    if requested not in (None, "app_source"):
        raise HTTPException(
            status_code=400,
            detail="app_role must be null or 'app_source'",
        )

    project, _role = await get_project_with_access(
        db, project_slug, current_user.id, Permission.PROJECT_EDIT
    )

    current = project.app_role
    if current == "app_instance":
        raise HTTPException(
            status_code=409,
            detail="installed app_instance projects cannot change app_role",
        )
    if current == requested:
        # No-op; return current.
        return ProjectSchema.model_validate(project)

    project.app_role = requested
    await db.commit()
    await db.refresh(project)
    logger.info(
        "project %s app_role: %s -> %s (user=%s)",
        project.id,
        current,
        requested,
        current_user.id,
    )
    return ProjectSchema.model_validate(project)


@router.post("/{project_slug}/export-template")
async def export_project_as_template(
    project_slug: str,
    export_data: TemplateExportRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Export a project as a reusable template archive.

    Creates a MarketplaceBase record with source_type='archive' and starts
    a background task to package the project files into a tar.gz archive.
    """
    settings = get_settings()
    project = await get_project_by_slug(db, project_slug, current_user, Permission.PROJECT_SETTINGS)

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
        team_id=current_user.default_team_id,
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

            # Determine the project path.
            # docker/desktop: use the on-disk project root via get_project_fs_path.
            # K8s: no host-accessible volume — reconstruct from DB file rows.
            from ..models import Project as _ProjectModel
            from ..services.project_fs import get_project_fs_path as _get_fs_path

            async with AsyncSessionLocal() as _path_db:
                _proj_for_path = await _path_db.get(_ProjectModel, proj_id)
                _fs_path = _get_fs_path(_proj_for_path) if _proj_for_path else None

            if _fs_path is not None:
                project_path = str(_fs_path)
            elif settings.deployment_mode == "kubernetes":
                # K8s: reconstruct from DB files into a temp directory
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
    current_user: User = Depends(get_authenticated_user),
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

    project = await get_project_by_slug(db, project_slug, current_user)
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Fork (duplicate) a project with all its files.
    Creates a new project with the same files as the original.
    """
    # Get source project (RBAC check)
    from ..permissions import Permission, get_project_with_access

    source_project, _role = await get_project_with_access(
        db, project_id, current_user.id, Permission.PROJECT_VIEW
    )

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
                    team_id=current_user.default_team_id,
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

        # Fork the btrfs volume (CoW snapshot on same node — instant).
        # This gives the forked project its own writable copy of the data.
        if source_project.volume_id:
            try:
                from ..services.volume_manager import get_volume_manager

                vm = get_volume_manager()
                new_vol_id, _ = await vm.fork_volume(source_project.volume_id)
                forked_project.volume_id = new_vol_id
            except Exception:
                logger.warning(
                    "[FORK] Failed to fork volume %s — project will have no volume",
                    source_project.volume_id,
                    exc_info=True,
                )

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

# Docker project root — must match DockerComposeOrchestrator.projects_path
_DOCKER_PROJECTS_ROOT = "/projects"


def _get_docker_asset_path(project_slug: str) -> str:
    """Return the Docker-mode project root for asset file operations.

    The Docker orchestrator stores project files at /projects/{slug}.
    Asset endpoints must use the same root so uploads, deletes, renames,
    and directory listings are visible in the file tree.
    """
    # Prevent path traversal — slug must be a simple name
    safe_slug = os.path.basename(project_slug)
    resolved = os.path.realpath(os.path.join(_DOCKER_PROJECTS_ROOT, safe_slug))
    if not resolved.startswith(os.path.realpath(_DOCKER_PROJECTS_ROOT) + os.sep):
        raise ValueError(f"Invalid project slug: {project_slug}")
    return resolved


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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all asset directories for this project.
    Scans the filesystem for directories and merges with database records.
    """
    project = await get_project_by_slug(db, project_slug, current_user)
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

        if settings.deployment_mode == "docker":
            project_path = _get_docker_asset_path(project_slug)
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new directory for assets.
    This creates the physical directory in the project filesystem.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)
    project_id = project.id

    directory_path = directory_data.get("path", "").strip("/")
    if not directory_path:
        raise HTTPException(status_code=400, detail="Directory path is required")

    # Validate directory path (prevent path traversal)
    if ".." in directory_path or directory_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid directory path")

    try:
        settings = get_settings()

        if settings.deployment_mode == "docker":
            project_path = _get_docker_asset_path(project_slug)
            full_dir_path = os.path.join(project_path, directory_path)
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
    current_user: User = Depends(get_authenticated_user),
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
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)
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

        # Get project path — works for docker and desktop; None on K8s.
        from ..services.project_fs import get_project_fs_path

        project_path_obj = get_project_fs_path(project)
        project_path = str(project_path_obj) if project_path_obj is not None else None

        # Create assets directory path
        assets_dir = os.path.join(project_path, directory) if project_path else None
        file_path_relative = f"{directory}/{safe_filename}".lstrip("/")
        file_path_absolute = (
            os.path.join(project_path, file_path_relative) if project_path else None
        )

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

        # Write file to filesystem (docker/desktop) or container (K8s)
        if project_path_obj is not None:
            os.makedirs(assets_dir, exist_ok=True)
            with open(file_path_absolute, "wb") as f:
                f.write(content)
            logger.info(f"[ASSETS] Saved file to: {file_path_absolute}")
        else:
            # Kubernetes mode — write to container via orchestrator
            from ..services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()
            await orchestrator.write_binary_to_container(
                project_id=project_id,
                file_path=file_path_relative,
                data=content,
            )
            logger.info(f"[ASSETS] Saved file to container: {file_path_relative}")

        # Get image dimensions if it's an image (filesystem path available)
        width, height = None, None
        if file_type == "image" and file_path_absolute is not None:
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all assets for a project, optionally filtered by directory.
    """
    project = await get_project_by_slug(db, project_slug, current_user)

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

    project = await get_project_by_slug(db, project_slug, current_user)

    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Asset not found")

    settings = get_settings()

    if settings.deployment_mode == "docker":
        project_path = _get_docker_asset_path(project_slug)
        file_path = os.path.join(project_path, asset.file_path)
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete an asset and its file from the filesystem.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_DELETE)

    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Asset not found")

    try:
        # Delete file from filesystem (docker/desktop) or container (K8s)
        from ..services.project_fs import get_project_fs_path

        project_path_obj = get_project_fs_path(project)
        if project_path_obj is not None:
            file_path = os.path.join(str(project_path_obj), asset.file_path)
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"[ASSETS] Deleted file: {file_path}")
        else:
            # Kubernetes mode — delete from container
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Rename an asset file.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)

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
        # Rename file in filesystem (docker/desktop) or container (K8s)
        from ..services.project_fs import get_project_fs_path

        new_file_path_relative = f"{asset.directory.strip('/')}/{new_filename}".lstrip("/")
        project_path_obj = get_project_fs_path(project)

        if project_path_obj is not None:
            project_path = str(project_path_obj)
            old_file_path = os.path.join(project_path, asset.file_path)
            new_file_path_absolute = os.path.join(project_path, new_file_path_relative)
            if os.path.exists(old_file_path):
                os.rename(old_file_path, new_file_path_absolute)
                logger.info(f"[ASSETS] Renamed file: {old_file_path} -> {new_file_path_absolute}")
        else:
            # Kubernetes mode — rename inside container
            from ..services.orchestration import get_orchestrator

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Move an asset to a different directory.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)

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
        # Move file in filesystem (docker/desktop) or container (K8s)
        from ..services.project_fs import get_project_fs_path

        new_file_path_relative = f"{new_directory.strip('/')}/{asset.filename}".lstrip("/")
        project_path_obj = get_project_fs_path(project)

        if project_path_obj is not None:
            project_path = str(project_path_obj)
            old_file_path = os.path.join(project_path, asset.file_path)
            new_file_path_absolute = os.path.join(project_path, new_file_path_relative)

            new_dir_absolute = os.path.dirname(new_file_path_absolute)
            await asyncio.to_thread(os.makedirs, new_dir_absolute, exist_ok=True)

            if os.path.exists(old_file_path):
                await asyncio.to_thread(shutil.move, old_file_path, new_file_path_absolute)
                logger.info(f"[ASSETS] Moved file: {old_file_path} -> {new_file_path_absolute}")
        else:
            # Kubernetes mode — move inside container
            from ..services.orchestration import get_orchestrator

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a project as deployed (keeps container running permanently).
    This is a premium feature with tier-based limits.
    """
    # Get project
    project = await get_project_by_slug(
        db, project_slug, current_user, Permission.DEPLOYMENT_CREATE
    )

    # Check if already deployed
    if project.is_deployed:
        return {"message": "Project is already deployed", "project_id": str(project.id)}

    # Check deployment limits
    from ..config import get_settings

    settings = get_settings()

    # Count current deployed projects (team-scoped)
    from ..models_team import Team, TeamMembership

    _team_id = current_user.default_team_id

    # Resolve tier and total_spend from the active team
    _tier = "free"
    _total_spend = 0
    if _team_id:
        _team_result = await db.execute(select(Team).where(Team.id == _team_id))
        _team = _team_result.scalar_one_or_none()
        if _team:
            _tier = _team.subscription_tier or "free"
            _total_spend = _team.total_spend or 0

    if _team_id:
        deployed_count_result = await db.execute(
            select(func.count(Project.id)).where(
                and_(Project.team_id == _team_id, Project.is_deployed)
            )
        )
    else:
        _user_team_ids = select(TeamMembership.team_id).where(
            and_(TeamMembership.user_id == current_user.id, TeamMembership.is_active.is_(True))
        )
        deployed_count_result = await db.execute(
            select(func.count(Project.id)).where(
                and_(Project.team_id.in_(_user_team_ids), Project.is_deployed)
            )
        )
    deployed_count = deployed_count_result.scalar()

    # Determine max deploys based on team tier
    max_deploys = settings.get_tier_max_deploys(_tier)

    # Check if limit exceeded
    if deployed_count >= max_deploys:
        additional_slots_purchased = _total_spend // settings.additional_deploy_price
        effective_max_deploys = max_deploys + additional_slots_purchased

        if deployed_count >= effective_max_deploys:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "message": f"Deploy limit reached. Your {_tier} tier allows {max_deploys} deployed project(s).",
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove deployment status from a project (allows container to be stopped when idle).
    """
    # Get project
    project = await get_project_by_slug(
        db, project_slug, current_user, Permission.DEPLOYMENT_DELETE
    )

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
    current_user: User = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)
):
    """
    Get current deployment limits and usage for the user.
    """
    from ..config import get_settings

    settings = get_settings()

    # Count deployed projects (team-scoped)
    from ..models_team import Team as _Team
    from ..models_team import TeamMembership as _TM

    _team_id = current_user.default_team_id

    # Resolve tier and total_spend from the active team
    _tier = "free"
    _total_spend = 0
    if _team_id:
        _team_result = await db.execute(select(_Team).where(_Team.id == _team_id))
        _team_obj = _team_result.scalar_one_or_none()
        if _team_obj:
            _tier = _team_obj.subscription_tier or "free"
            _total_spend = _team_obj.total_spend or 0

    if _team_id:
        deployed_count_result = await db.execute(
            select(func.count(Project.id)).where(
                and_(Project.team_id == _team_id, Project.is_deployed)
            )
        )
    else:
        _user_team_ids = select(_TM.team_id).where(
            and_(_TM.user_id == current_user.id, _TM.is_active.is_(True))
        )
        deployed_count_result = await db.execute(
            select(func.count(Project.id)).where(
                and_(Project.team_id.in_(_user_team_ids), Project.is_deployed)
            )
        )
    deployed_count = deployed_count_result.scalar()

    # Determine limits based on team tier
    base_max_deploys = settings.get_tier_max_deploys(_tier)
    base_max_projects = settings.get_tier_max_projects(_tier)

    # Calculate additional slots from purchases
    additional_slots = _total_spend // settings.additional_deploy_price
    effective_max_deploys = base_max_deploys + additional_slots

    # Count total projects (team-scoped)
    if _team_id:
        total_projects_result = await db.execute(
            select(func.count(Project.id)).where(Project.team_id == _team_id)
        )
    else:
        total_projects_result = await db.execute(
            select(func.count(Project.id)).where(Project.team_id.in_(_user_team_ids))
        )
    total_projects = total_projects_result.scalar()

    return {
        "tier": _tier,
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
    current_user: User = Depends(get_authenticated_user),
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


# ============================================================================
# Container Management Endpoints (Node Graph / Monorepo)
# ============================================================================


@router.get("/{project_slug}/containers", response_model=list[ContainerSchema])
async def get_project_containers(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all containers for a project (for the React Flow node graph).
    Returns containers with their positions and base information.
    """
    project = await get_project_by_slug(db, project_slug, current_user)

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
    current_user: User = Depends(get_authenticated_user),
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
    project = await get_project_by_slug(db, project_slug, current_user, Permission.CONTAINER_CREATE)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all connections between containers in the project.
    """
    project = await get_project_by_slug(db, project_slug, current_user)

    result = await db.execute(
        select(ContainerConnection).where(ContainerConnection.project_id == project.id)
    )
    connections = result.scalars().all()

    return connections


@router.post("/{project_slug}/containers/connections", response_model=ContainerConnectionSchema)
async def create_container_connection(
    project_slug: str,
    connection_data: ContainerConnectionCreate,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a connection between two containers (React Flow edge).
    This represents a dependency or network connection.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.CONTAINER_CREATE)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a connection between containers.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.CONTAINER_DELETE)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all browser preview nodes for a project.
    """
    project = await get_project_by_slug(db, project_slug, current_user)

    result = await db.execute(select(BrowserPreview).where(BrowserPreview.project_id == project.id))
    previews = result.scalars().all()

    return previews


@router.post("/{project_slug}/browser-previews", response_model=BrowserPreviewSchema)
async def create_browser_preview(
    project_slug: str,
    preview_data: BrowserPreviewCreate,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new browser preview node on the canvas.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a browser preview node (position, connected container, current path).
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a browser preview node.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_DELETE)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Connect a browser preview to a container for preview.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Disconnect a browser preview from its container.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.FILE_WRITE)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the runtime status of all containers in the project.

    Returns Docker status for each container (running, stopped, etc.)
    The response keys status entries by both the K8s directory name and the
    sanitized container display name so the frontend graph canvas polling
    can always find the correct entry.
    """
    project = await get_project_by_slug(db, project_slug, current_user)

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
                # Find the K8s key by matching container_id from pod labels
                cid = str(c.id)
                k8s_key = None
                for key, info in containers_map.items():
                    if info.get("container_id") == cid:
                        k8s_key = key
                        break
                if not k8s_key and c.container_type == "service":
                    # Fallback for service containers keyed by service_slug
                    k8s_key = _sanitize_status_key(c.service_slug or c.name)
                # Add alias if the keys differ and the K8s entry exists
                if k8s_key and frontend_key != k8s_key and k8s_key in containers_map:
                    containers_map[frontend_key] = containers_map[k8s_key]

        # Derive live compute state so the frontend doesn't rely on stale DB.
        # Desktop (local runtime) never uses the K8s compute-tier system — the
        # orchestrator reports "running" because the app is up, but that does
        # not mean environment-level compute is provisioned. Always return "none"
        # so the project page doesn't auto-trigger a container start loop.
        settings_obj = get_settings()
        if settings_obj.deployment_mode == "desktop":
            status["compute_state"] = "none"
        else:
            live_status = status.get("status")
            if live_status in ("running", "partial"):
                status["compute_state"] = "environment"
            elif live_status == "stopped":
                status["compute_state"] = "ephemeral"
            else:
                status["compute_state"] = "none"

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a single container's details including environment variables.
    """
    project = await get_project_by_slug(db, project_slug, current_user)

    result = await db.execute(
        select(Container).where(Container.id == container_id).options(selectinload(Container.base))
    )
    container = result.scalar_one_or_none()
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    injected = await get_injected_env_vars_for_container(db, container.id, project.id)
    return _container_response(container, injected_env_vars=injected)


@router.patch("/{project_slug}/containers/{container_id}", response_model=ContainerSchema)
async def update_container(
    project_slug: str,
    container_id: UUID,
    container_data: ContainerUpdate,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update container settings (mainly position for React Flow).
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.CONTAINER_EDIT)

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
            existing = dict(container.environment_vars or {})
            existing.update(container_data.env_vars_to_set)
            container.environment_vars = existing
            flag_modified(container, "environment_vars")
        if container_data.env_vars_to_delete:
            existing = dict(container.environment_vars or {})
            for key in container_data.env_vars_to_delete:
                existing.pop(key, None)
            container.environment_vars = existing
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Update credentials for an external service container."""
    project = await get_project_by_slug(db, project_slug, current_user, Permission.CONTAINER_EDIT)

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

        # Re-fetch with eagerly loaded base to avoid MissingGreenlet in _container_response
        refreshed = await db.execute(
            select(Container)
            .where(Container.id == container.id)
            .options(selectinload(Container.base))
        )
        container = refreshed.scalar_one()

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
    current_user: User = Depends(get_authenticated_user),
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

    project = await get_project_by_slug(db, project_slug, current_user, Permission.CONTAINER_EDIT)

    result = await db.execute(
        select(Container).where(Container.id == container_id).options(selectinload(Container.base))
    )
    container = result.scalar_one_or_none()
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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Assign or remove a deployment target from a container.

    Validates that the container type and framework are compatible with the
    deployment provider before assignment.
    """
    from ..services.service_definitions import DEPLOYMENT_COMPATIBILITY, is_deployment_compatible

    project = await get_project_by_slug(db, project_slug, current_user, Permission.CONTAINER_EDIT)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a container from the project.
    Deletes the container record and its directory from the monorepo.
    """
    project = await get_project_by_slug(db, project_slug, current_user, Permission.CONTAINER_DELETE)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start all containers in a project.

    In Docker mode: Uses docker-compose up to start containers.
    In Kubernetes mode: Creates namespace, deployments, and services.
    """
    project = await get_project_by_slug(
        db, project_slug, current_user, Permission.CONTAINER_START_STOP
    )

    if project.environment_status == "provisioning":
        raise HTTPException(
            status_code=409,
            detail="Project is still being provisioned. Please wait for setup to complete.",
        )

    await track_project_activity(project.id, db)

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stop all containers in a project.

    In Docker mode: Uses docker-compose down.
    In Kubernetes mode: Deletes the project namespace.
    """
    project = await get_project_by_slug(
        db, project_slug, current_user, Permission.CONTAINER_START_STOP
    )

    try:
        # Use unified orchestration (handles both Docker and Kubernetes)
        from ..services.orchestration import get_deployment_mode, get_orchestrator

        orchestrator = get_orchestrator()
        deployment_mode = get_deployment_mode()

        # Close any active shell sessions before tearing down pods
        await db.execute(
            sql_update(ShellSession)
            .where(ShellSession.project_id == project.id, ShellSession.status == "active")
            .values(status="closed", closed_at=func.now())
        )
        await db.commit()

        await orchestrator.stop_project(project.slug, project.id, current_user.id)

        project.environment_status = "stopped"
        await db.commit()

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

        project = await get_project_by_slug(
            db, project_slug, user_id, Permission.CONTAINER_START_STOP
        )
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

        # Find this container's status by matching container_id from pod labels
        container_info = None
        cid = str(container.id)
        for _dir, info in status.get("containers", {}).items():
            if info.get("container_id") == cid:
                container_info = info
                break
        if container_info and container_info.get("running"):
            # Container is already running - return immediately!
            task.update_progress(100, 100, "Container already running")
            # Use URL from orchestrator status if available, otherwise build it
            container_url = container_info.get("url")
            if not container_url:
                settings = get_settings()
                svc = container.container_directory or container.name
                protocol = (
                    "http"
                    if settings.deployment_mode == "docker"
                    else settings.k8s_container_url_protocol
                )
                container_url = await _resolve_container_url(
                    db,
                    project,
                    container,
                    fallback_dir=svc,
                    protocol=protocol,
                    app_domain=settings.app_domain,
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

            container_url = result.get("url")
            if not container_url:
                fallback_dir = (
                    container.container_directory or container.directory or container.name
                )
                container_url = await _resolve_container_url(
                    db,
                    project,
                    container,
                    fallback_dir=fallback_dir,
                    protocol=settings.k8s_container_url_protocol,
                    app_domain=settings.app_domain,
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
                if settings.deployment_mode == "desktop":
                    port = getattr(container, "effective_port", None)
                    container_url = f"http://localhost:{port}" if port else "http://localhost"
                else:
                    protocol = (
                        "http"
                        if settings.deployment_mode == "docker"
                        else settings.k8s_container_url_protocol
                    )
                    container_url = await _resolve_container_url(
                        db,
                        project,
                        container,
                        fallback_dir=sanitized_name,
                        protocol=protocol,
                        app_domain=settings.app_domain,
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
    current_user: User = Depends(get_authenticated_user),
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
    project = await get_project_by_slug(
        db, project_slug, current_user, Permission.CONTAINER_START_STOP
    )

    if project.environment_status == "provisioning":
        raise HTTPException(
            status_code=409,
            detail="Project is still being provisioned. Please wait for setup to complete.",
        )

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stop a specific container in the project.
    """
    project = await get_project_by_slug(
        db, project_slug, current_user, Permission.CONTAINER_START_STOP
    )

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
    current_user: User = Depends(get_authenticated_user),
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

    project = await get_project_by_slug(db, project_slug, current_user)

    container = await db.get(Container, container_id)
    if not container or container.project_id != project.id:
        raise HTTPException(status_code=404, detail="Container not found")

    settings = get_settings()

    # Get container directory (sanitized for K8s naming)
    from ..services.compute_manager import resolve_k8s_container_dir

    container_dir = resolve_k8s_container_dir(container)

    # Build container URL based on deployment mode
    if settings.deployment_mode == "desktop":
        # Desktop/local mode: containers are processes managed by LocalOrchestrator.
        # There is no Traefik or in-cluster DNS — just report healthy immediately
        # so the frontend iframe can proceed.  LocalOrchestrator.start_container()
        # is a no-op that returns "running" only after the process is up.
        local_port = container.effective_port
        external_url = f"http://localhost:{local_port}" if local_port else "http://localhost"
        return {"healthy": True, "url": external_url, "mode": "local"}
    elif settings.deployment_mode == "kubernetes":
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

            # For K8s: verify external path through NGINX Ingress is also routable.
            # The Ingress Controller may take 1-5s to sync after Service endpoints update.
            if is_healthy and settings.deployment_mode == "kubernetes":
                ingress_host = f"{project.slug}-{container_dir}.{settings.app_domain}"
                ingress_svc = "http://ingress-nginx-controller.ingress-nginx.svc.cluster.local"
                try:
                    ingress_resp = await client.get(
                        ingress_svc,
                        headers={"Host": ingress_host},
                        follow_redirects=True,
                        timeout=3.0,
                    )
                    if ingress_resp.status_code >= 500:
                        return {
                            "healthy": False,
                            "url": external_url,
                            "error": "Ingress routing not ready yet",
                        }
                except (httpx.TimeoutException, httpx.ConnectError):
                    # Ingress controller not reachable (minikube / local dev) — skip
                    pass

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
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Restart a specific container in the project (stop + start).

    This endpoint returns immediately with a task ID. The client should poll
    for status updates.
    """
    project = await get_project_by_slug(
        db, project_slug, current_user, Permission.CONTAINER_START_STOP
    )

    if project.environment_status == "provisioning":
        raise HTTPException(
            status_code=409,
            detail="Project is still being provisioned. Please wait for setup to complete.",
        )

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

        project = await get_project_by_slug(
            db, project_slug, user_id, Permission.CONTAINER_START_STOP
        )
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
                protocol = settings.k8s_container_url_protocol
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
# Lifecycle: Activity Touch & Hibernate
# =============================================================================


@router.post("/{project_slug}/activity", status_code=204)
async def touch_project_activity(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Lightweight endpoint to reset the idle timer.

    Called by the frontend "Keep Active" button in the idle warning banner.
    Returns 204 No Content on success.
    """
    from ..services.activity_tracker import track_project_activity as _track

    project = await get_project_by_slug(db, project_slug, current_user)
    await _track(db, project.id, "keep_active")


@router.post("/{project_slug}/hibernate", status_code=202)
async def hibernate_project(
    project_slug: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Hibernate a project — stops compute, volume stays local.

    Returns 202 immediately; background task handles K8s cleanup.
    Volume is NOT evicted — it stays on node for instant wake.
    Disk eviction happens separately after a configurable dormancy period.
    """
    settings = get_settings()

    if settings.deployment_mode != "kubernetes":
        raise HTTPException(
            status_code=400, detail="Hibernation is only available in Kubernetes mode"
        )

    project = await get_project_by_slug(
        db, project_slug, current_user, Permission.CONTAINER_START_STOP
    )

    if project.environment_status in ("hibernated", "stopping"):
        raise HTTPException(status_code=400, detail="Already hibernated or stopping")

    if project.environment_status not in ("active", "stopped"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot hibernate from state: {project.environment_status}",
        )

    project.environment_status = "stopping"
    project.hibernated_at = func.now()
    await db.commit()

    from ..services.hibernate import hibernate_project_bg

    asyncio.create_task(hibernate_project_bg(project.id, current_user.id))

    return {"status": "stopping", "message": "Hibernation started"}
