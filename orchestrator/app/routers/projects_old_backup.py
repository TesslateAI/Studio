from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request, status, WebSocket
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from sqlalchemy.orm.attributes import flag_modified
from ..database import get_db
from ..models import Project, User, ProjectFile, Chat, Message, ProjectAsset
from ..schemas import Project as ProjectSchema, ProjectCreate, ProjectFile as ProjectFileSchema
from ..config import get_settings
from ..utils.slug_generator import generate_project_slug
from ..utils.resource_naming import get_project_path
from ..users import current_active_user, current_superuser
from ..services.task_manager import get_task_manager, Task
from ..utils.async_fileio import (
    walk_directory_async,
    read_file_async,
    makedirs_async,
    copy_file_async
)
import os
import shutil
import asyncio
import logging
import re
from pathlib import Path
import mimetypes

logger = logging.getLogger(__name__)

router = APIRouter()


async def get_project_by_slug(
    db: AsyncSession,
    project_slug: str,
    user_id: UUID
) -> Project:
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
        result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
    except ValueError:
        # Not a UUID, treat as slug (recommended for URLs)
        result = await db.execute(
            select(Project).where(Project.slug == project_slug)
        )
        project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this project")

    return project


@router.get("/", response_model=List[ProjectSchema])
async def get_projects(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Project).where(Project.owner_id == current_user.id)
    )
    projects = result.scalars().all()
    return projects

@router.post("/", response_model=ProjectSchema)
async def create_project(
    project: ProjectCreate,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new project from a template or GitHub repository.

    Supports two source types:
    - template: Initialize from built-in React/Vite template (default)
    - github: Import from a GitHub repository

    For GitHub import:
    - GitHub authentication is OPTIONAL for public repositories
    - GitHub authentication is REQUIRED for private repositories
    - Repository will be cloned into the project
    - Project files will be populated from the repository
    """
    try:
        logger.info(f"[CREATE] Creating project for user {current_user.id}: {project.name} (source: {project.source_type})")

        # Check project limits based on subscription tier
        from ..config import get_settings
        settings = get_settings()

        # Count current active projects (not including deployed-only)
        current_projects_result = await db.execute(
            select(func.count(Project.id)).where(
                Project.owner_id == current_user.id
            )
        )
        current_projects_count = current_projects_result.scalar()

        # Determine max projects based on tier
        if current_user.subscription_tier == "pro":
            max_projects = settings.premium_max_projects
        else:
            max_projects = settings.free_max_projects

        # Enforce limit
        if current_projects_count >= max_projects:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Project limit reached. Your {current_user.subscription_tier} tier allows {max_projects} project(s). Upgrade to create more projects."
            )

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
                    owner_id=current_user.id
                )
                db.add(db_project)
                await db.commit()
                await db.refresh(db_project)
                break
            except Exception as e:
                await db.rollback()
                if "unique" in str(e).lower() and "slug" in str(e).lower() and attempt < max_retries - 1:
                    # Slug collision, generate a new one
                    project_slug = generate_project_slug(project.name)
                    logger.warning(f"[CREATE] Slug collision, retrying with: {project_slug}")
                else:
                    # Other error or max retries reached
                    raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e)}")

        logger.info(f"[CREATE] Project {db_project.slug} (ID: {db_project.id}) created in database")

        # Start container first (so we have a container to clone into)
        project_path = os.path.abspath(get_project_path(current_user.id, db_project.id))

        # In Docker mode, create the directory
        settings = get_settings()
        if settings.deployment_mode == "docker":
            # Force create directories using Path (more reliable on Windows Docker volumes)
            from pathlib import Path
            try:
                Path(project_path).mkdir(parents=True, exist_ok=True)
                logger.info(f"[CREATE] Created project directory: {project_path}")
            except Exception as e:
                logger.warning(f"[CREATE] mkdir failed: {e}, trying subprocess")
                # Try alternative method
                import subprocess
                subprocess.run(['mkdir', '-p', project_path], check=False, capture_output=True)

            # Give filesystem a moment to sync (Windows Docker volume issue)
            import time
            time.sleep(0.1)

            logger.info(f"[CREATE] Project directory ready: {project_path}")

        # Handle source type: template or github
        if project.source_type == "github":
            logger.info(f"[CREATE] Importing from GitHub: {project.github_repo_url}")

            # Try to get GitHub credentials (optional for public repos)
            from ..services.credential_manager import get_credential_manager
            credential_manager = get_credential_manager()
            access_token = await credential_manager.get_access_token(db, current_user.id)

            if access_token:
                logger.info(f"[CREATE] Using GitHub authentication for {current_user.id}")
            else:
                logger.info(f"[CREATE] No GitHub authentication - attempting public repository clone")

            # Clone repository first (don't start container yet - no package.json exists!)
            # Container will be started later when user opens the project
            try:
                from ..services.git_manager import GitManager
                from ..services.github_client import GitHubClient
                from ..services.project_patcher import ProjectPatcher

                # Parse repository info
                repo_info = GitHubClient.parse_repo_url(project.github_repo_url)
                if not repo_info:
                    raise ValueError("Invalid GitHub repository URL")

                # Get default branch if not specified
                branch = project.github_branch
                if not branch or branch == "":
                    if access_token:
                        # Try to get default branch from GitHub API
                        github_client = GitHubClient(access_token)
                        try:
                            branch = await github_client.get_default_branch(repo_info['owner'], repo_info['repo'])
                            logger.info(f"[CREATE] Detected default branch: {branch}")
                        except Exception as e:
                            logger.warning(f"[CREATE] Could not detect default branch: {e}, defaulting to 'main'")
                            branch = "main"
                    else:
                        # No auth token - default to 'main'
                        branch = "main"
                        logger.info(f"[CREATE] No auth token, defaulting to branch: {branch}")

                # Clone repository
                git_manager = GitManager(current_user.id, str(db_project.id))
                await git_manager.clone_repository(
                    repo_url=project.github_repo_url,
                    branch=branch,
                    auth_token=access_token,
                    direct_to_filesystem=(settings.deployment_mode == "docker")  # Clone directly for Docker mode
                )

                logger.info(f"[CREATE] Repository cloned successfully")

                # Auto-patch the imported project to work with Tesslate Studio
                logger.info(f"[CREATE] Auto-patching imported project for Tesslate compatibility...")
                try:
                    if settings.deployment_mode == "kubernetes":
                        # For Kubernetes, read files from pod, patch them, and write back
                        from ..k8s_client import get_k8s_manager
                        from ..services.framework_detector import FrameworkDetector
                        k8s_manager = get_k8s_manager()

                        # Check if package.json exists
                        package_json_content = await k8s_manager.read_file_from_pod(
                            user_id=current_user.id,
                            project_id=str(db_project.id),
                            file_path="package.json"
                        )

                        if package_json_content:
                            # Detect framework
                            import json
                            try:
                                framework, config = FrameworkDetector.detect_from_package_json(package_json_content)
                                logger.info(f"[CREATE] Detected {framework} project")

                                if framework == "vite":
                                    logger.info(f"[CREATE] Applying Vite compatibility patches...")

                                    # Write Tesslate-compatible vite.config.js
                                    vite_config = ProjectPatcher.REQUIRED_VITE_CONFIG
                                    await k8s_manager.write_file_to_pod(
                                        user_id=current_user.id,
                                        project_id=str(db_project.id),
                                        file_path="vite.config.js",
                                        content=vite_config
                                    )
                                    logger.info(f"[CREATE] ✅ Wrote Tesslate-compatible vite.config.js")

                                    # Ensure index.html exists
                                    index_html = await k8s_manager.read_file_from_pod(
                                        user_id=current_user.id,
                                        project_id=str(db_project.id),
                                        file_path="index.html"
                                    )
                                    if not index_html:
                                        await k8s_manager.write_file_to_pod(
                                            user_id=current_user.id,
                                            project_id=str(db_project.id),
                                            file_path="index.html",
                                            content=ProjectPatcher.MINIMAL_INDEX_HTML
                                        )
                                        logger.info(f"[CREATE] ✅ Created missing index.html")

                                elif framework == "nextjs":
                                    logger.info(f"[CREATE] Applying Next.js compatibility patches...")

                                    # Write Tesslate-compatible next.config.js
                                    next_config = FrameworkDetector.get_required_config_content("nextjs")
                                    await k8s_manager.write_file_to_pod(
                                        user_id=current_user.id,
                                        project_id=str(db_project.id),
                                        file_path="next.config.js",
                                        content=next_config
                                    )
                                    logger.info(f"[CREATE] ✅ Wrote Tesslate-compatible next.config.js")
                                    logger.warning(f"[CREATE] ⚠️ Next.js support is experimental. Dev server will run on port 3000.")

                                else:
                                    compatibility = FrameworkDetector.get_compatibility_message(framework)
                                    logger.warning(f"[CREATE] ⚠️ {framework} project: {compatibility}")

                            except Exception as parse_error:
                                logger.warning(f"[CREATE] Could not parse package.json for patching: {parse_error}")
                        else:
                            logger.warning(f"[CREATE] ⚠️ No package.json found in imported project")

                    else:
                        # Docker mode - patch files on filesystem
                        patcher = ProjectPatcher(project_path)
                        patch_result = await patcher.auto_patch()

                        if patch_result["patches_applied"]:
                            logger.info(f"[CREATE] ✅ Applied patches: {', '.join(patch_result['patches_applied'])}")

                        if patch_result["issues_detected"]:
                            logger.warning(f"[CREATE] ⚠️ Issues detected: {', '.join(patch_result['issues_detected'])}")

                except Exception as patch_error:
                    logger.warning(f"[CREATE] Auto-patch encountered an error (project may still work): {patch_error}")
                    # Don't fail the import if patching fails

                # Save cloned files to database (for frontend display)
                logger.info(f"[CREATE] Saving cloned files to database...")
                files_saved = 0

                if settings.deployment_mode == "docker":
                    # Docker mode: Read files from filesystem
                    for root, dirs, files in os.walk(project_path):
                        # Skip node_modules, .git, dist, build directories
                        dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build', '.next']]

                        for file in files:
                            # Skip system files and binary files
                            if (file.startswith('.') or
                                file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico'))):
                                continue

                            file_full_path = os.path.join(root, file)
                            relative_path = os.path.relpath(file_full_path, project_path).replace('\\', '/')

                            try:
                                with open(file_full_path, 'r', encoding='utf-8', errors='replace') as f:
                                    content = f.read()

                                db_file = ProjectFile(
                                    project_id=db_project.id,
                                    file_path=relative_path,
                                    content=content
                                )
                                db.add(db_file)
                                files_saved += 1
                            except Exception as e:
                                logger.warning(f"[CREATE] Could not read file {relative_path}: {e}")
                                continue

                    logger.info(f"[CREATE] ✅ Saved {files_saved} files to database")

                # Note: For Kubernetes mode, files are already in the pod and will be read on-demand

                # Update project with Git info
                db_project.has_git_repo = True
                db_project.git_remote_url = project.github_repo_url

                # Create git_repository record
                from ..models import GitRepository
                git_repo = GitRepository(
                    project_id=db_project.id,
                    user_id=current_user.id,
                    repo_url=project.github_repo_url,
                    repo_name=repo_info['repo'],
                    repo_owner=repo_info['owner'],
                    default_branch=branch,
                    auth_method='pat' if access_token else 'none'
                )
                db.add(git_repo)
                await db.commit()
                await db.refresh(db_project)  # Refresh to get updated timestamps

                logger.info(f"[CREATE] Git repository linked to project {db_project.id}")

            except Exception as git_error:
                logger.error(f"[CREATE] Failed to clone repository: {git_error}", exc_info=True)
                # Clean up project (no need to stop container - it was never started)
                await db.delete(db_project)
                await db.commit()
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to import repository: {str(git_error)}"
                )

            logger.info(f"[CREATE] Project {db_project.id} created from GitHub repository successfully")

        elif project.source_type == "base":
            logger.info(f"[CREATE] Creating from marketplace base: {project.base_id}")

            if not project.base_id:
                raise HTTPException(status_code=400, detail="base_id is required for source_type 'base'")

            # Verify user has purchased this base
            from ..models import UserPurchasedBase, MarketplaceBase
            purchase = await db.scalar(
                select(UserPurchasedBase).where(
                    UserPurchasedBase.user_id == current_user.id,
                    UserPurchasedBase.base_id == project.base_id,
                    UserPurchasedBase.is_active == True
                )
            )
            if not purchase:
                raise HTTPException(status_code=403, detail="You have not acquired this project base.")

            # Get the base's repository URL
            base_repo = await db.get(MarketplaceBase, project.base_id)
            if not base_repo:
                raise HTTPException(status_code=404, detail="Project base not found.")

            logger.info(f"[CREATE] Cloning base repository: {base_repo.git_repo_url}")

            try:
                # Try to clone using the base's Git repository
                from ..services.git_manager import GitManager
                from ..services.credential_manager import get_credential_manager

                # Get GitHub credentials (optional for public repos)
                credential_manager = get_credential_manager()
                access_token = await credential_manager.get_access_token(db, current_user.id)

                git_manager = GitManager(current_user.id, str(db_project.id))
                await git_manager.clone_repository(
                    repo_url=base_repo.git_repo_url,
                    branch=base_repo.default_branch,
                    auth_token=access_token,
                    direct_to_filesystem=(settings.deployment_mode == "docker")
                )

                logger.info(f"[CREATE] Base cloned successfully from {base_repo.git_repo_url}")

                # Parse TESSLATE.md and generate startup script for dynamic startup
                try:
                    from ..services.tesslate_parser import TesslateParser
                    from ..services.startup_generator import StartupGenerator

                    tesslate_md_path = os.path.join(project_path, "TESSLATE.md")

                    if os.path.exists(tesslate_md_path):
                        logger.info(f"[CREATE] Found TESSLATE.md, parsing for dynamic startup...")

                        with open(tesslate_md_path, 'r', encoding='utf-8') as f:
                            tesslate_content = f.read()

                        # Parse configuration
                        config = TesslateParser.parse(tesslate_content)

                        # Generate startup script
                        script_path = StartupGenerator.write_script(config, project_path)

                        logger.info(f"[CREATE] Generated startup script for {config.framework} on port {config.port}")
                    else:
                        logger.info(f"[CREATE] No TESSLATE.md found, generating default Vite startup script")
                        StartupGenerator.generate_default_script(project_path, "vite")

                except Exception as parse_error:
                    logger.warning(f"[CREATE] Failed to parse TESSLATE.md: {parse_error}, using default startup")
                    # Generate default script as fallback
                    try:
                        from ..services.startup_generator import StartupGenerator
                        StartupGenerator.generate_default_script(project_path, "vite")
                    except Exception as fallback_error:
                        logger.error(f"[CREATE] Failed to generate default script: {fallback_error}")

                # Save cloned files to database (similar to GitHub import)
                if settings.deployment_mode == "docker":
                    files_saved = 0
                    for root, dirs, files in os.walk(project_path):
                        dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build', '.next']]

                        for file in files:
                            if (file.startswith('.') or
                                file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico'))):
                                continue

                            file_full_path = os.path.join(root, file)
                            relative_path = os.path.relpath(file_full_path, project_path).replace('\\', '/')

                            try:
                                with open(file_full_path, 'r', encoding='utf-8', errors='replace') as f:
                                    content = f.read()

                                db_file = ProjectFile(
                                    project_id=db_project.id,
                                    file_path=relative_path,
                                    content=content
                                )
                                db.add(db_file)
                                files_saved += 1
                            except Exception as e:
                                logger.warning(f"[CREATE] Could not read file {relative_path}: {e}")
                                continue

                    logger.info(f"[CREATE] Saved {files_saved} files to database")

                # Mark as having Git repo
                db_project.has_git_repo = True
                db_project.git_remote_url = base_repo.git_repo_url

                await db.commit()
                await db.refresh(db_project)

                logger.info(f"[CREATE] Project {db_project.id} created from base '{base_repo.name}' successfully")

            except Exception as git_error:
                logger.error(f"[CREATE] Failed to clone base repository: {git_error}", exc_info=True)

                # FALLBACK: Use hardcoded template as safety net
                logger.warning(f"[CREATE] Falling back to hardcoded template due to Git error")

                template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "template"))

                if not os.path.exists(template_dir):
                    logger.error(f"[CREATE] Template directory not found: {template_dir}")
                    await db.delete(db_project)
                    await db.commit()
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to clone base and fallback template not found"
                    )

                # Copy template files
                files_saved = 0
                for root, dirs, files in os.walk(template_dir):
                    dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build']]

                    for file in files:
                        if file.startswith('.') or file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico')):
                            continue

                        file_path = os.path.join(root, file)
                        relative_path = os.path.relpath(file_path, template_dir).replace('\\', '/')

                        try:
                            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                                content = f.read()

                            db_file = ProjectFile(
                                project_id=db_project.id,
                                file_path=relative_path,
                                content=content
                            )
                            db.add(db_file)
                            files_saved += 1
                        except Exception as e:
                            logger.warning(f"[CREATE] Could not read template file {relative_path}: {e}")

                # In Docker mode, also copy to filesystem
                if settings.deployment_mode == "docker":
                    try:
                        for root, dirs, files in os.walk(template_dir):
                            dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build']]

                            for file in files:
                                src_path = os.path.join(root, file)
                                rel_path = os.path.relpath(src_path, template_dir)
                                dst_path = os.path.join(project_path, rel_path)

                                parent_dir = os.path.dirname(dst_path)
                                if parent_dir:
                                    os.makedirs(parent_dir, exist_ok=True)

                                shutil.copy2(src_path, dst_path)
                    except Exception as copy_error:
                        logger.error(f"[CREATE] Failed to copy template files: {copy_error}")

                await db.commit()
                await db.refresh(db_project)

                logger.info(f"[CREATE] Project {db_project.id} created with fallback template after base clone failure")

        else:
            # Template mode (default behavior)
            logger.info(f"[CREATE] Initializing from template")

            # Get template directory to read files
            template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "template"))

            if not os.path.exists(template_dir):
                logger.error(f"[CREATE] Template directory not found: {template_dir}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Template directory not found. Server configuration error."
                )

            logger.info(f"[CREATE] Reading template files from: {template_dir}")

            # Save template files to database for frontend display and editing
            files_saved = 0
            for root, dirs, files in os.walk(template_dir):
                # Skip node_modules, .git, dist, build directories
                dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build', '.next']]

                for file in files:
                    # Skip system files and binary files
                    if (file.startswith('.') or
                        file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico'))):
                        continue

                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, template_dir).replace('\\', '/')

                    try:
                        # Read file content
                        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read()

                        # Save to database
                        db_file = ProjectFile(
                            project_id=db_project.id,
                            file_path=relative_path,
                            content=content
                        )
                        db.add(db_file)
                        files_saved += 1

                    except Exception as e:
                        logger.warning(f"[CREATE] Could not read template file {relative_path}: {e}")
                        continue

            # Commit database changes
            await db.commit()
            logger.info(f"[CREATE] Saved {files_saved} template files to database for project {db_project.id}")
            await db.refresh(db_project)  # Refresh to get updated timestamps

            # In Docker mode, also copy template files to filesystem immediately
            if settings.deployment_mode == "docker":
                try:
                    logger.info(f"[CREATE] Docker mode: Copying template files to filesystem")

                    # Copy all template files to project directory (excluding node_modules)
                    for root, dirs, files in os.walk(template_dir):
                        # Skip node_modules in source
                        dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build', '.next']]

                        for file in files:
                            src_path = os.path.join(root, file)
                            rel_path = os.path.relpath(src_path, template_dir)
                            dst_path = os.path.join(project_path, rel_path)

                            # Create directory if needed (with safety check for Windows Docker volumes)
                            parent_dir = os.path.dirname(dst_path)
                            if parent_dir:
                                try:
                                    os.makedirs(parent_dir, exist_ok=True)
                                except FileExistsError:
                                    # Handle race condition on Windows Docker volumes - verify it exists
                                    if not os.path.exists(parent_dir):
                                        # If it still doesn't exist, something is wrong
                                        raise

                            # Copy file
                            shutil.copy2(src_path, dst_path)

                    logger.info(f"[CREATE] ✅ Template files copied to {project_path}")
                except Exception as copy_error:
                    logger.error(f"[CREATE] Failed to copy template files: {copy_error}", exc_info=True)
                    # Don't fail project creation, files are in DB

            logger.info(f"[CREATE] Project {db_project.id} created successfully")

        return db_project

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"[CREATE] Critical error during project creation: {e}", exc_info=True)

        # Clean up failed project from database
        try:
            if 'db_project' in locals():
                await db.delete(db_project)
                await db.commit()
                logger.info(f"[CREATE] Cleaned up failed project from database")
        except Exception as cleanup_error:
            logger.error(f"[CREATE] Error during cleanup: {cleanup_error}", exc_info=True)

        raise HTTPException(
            status_code=500,
            detail=f"Failed to create project: {str(e)}"
        )

@router.get("/{project_slug}", response_model=ProjectSchema)
async def get_project(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a project by its slug."""
    project = await get_project_by_slug(db, project_slug, current_user.id)
    return project

@router.get("/{project_slug}/files", response_model=List[ProjectFileSchema])
async def get_project_files(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    from_pod: bool = False  # Optional query param to force reading from pod
):
    """
    Get project files from database (default) or from running pod (if from_pod=true).

    Strategy:
    - Default: Return files from database (fast, always available)
    - If from_pod=true: Try to read from pod, fall back to DB if pod unavailable
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    # If from_pod requested, try to read from running container (K8s only)
    settings = get_settings()
    if from_pod and settings.deployment_mode == "kubernetes":
        try:
            from ..k8s_client import get_k8s_manager
            k8s_manager = get_k8s_manager()

            # Check if pod is ready
            readiness = await k8s_manager.is_pod_ready(current_user.id, str(project_id))

            if readiness["ready"]:
                logger.info(f"[FILES] Reading files from pod for project {project_id}")

                # Get list of files from pod
                pod_files = await k8s_manager.list_files_in_pod(
                    current_user.id,
                    str(project_id),
                    directory="."
                )

                # Read content for each file
                files_with_content = []
                for pod_file in pod_files:
                    if pod_file["type"] == "file":
                        try:
                            content = await k8s_manager.read_file_from_pod(
                                current_user.id,
                                str(project_id),
                                pod_file["path"]
                            )

                            if content is not None:
                                files_with_content.append(ProjectFileSchema(
                                    id=0,  # Temporary ID
                                    project_id=project_id,
                                    file_path=pod_file["path"],
                                    content=content,
                                    created_at=None,
                                    updated_at=None
                                ))
                        except Exception as e:
                            logger.warning(f"[FILES] Failed to read {pod_file['path']}: {e}")
                            continue

                logger.info(f"[FILES] ✅ Read {len(files_with_content)} files from pod")
                return files_with_content

            else:
                logger.info(f"[FILES] Pod not ready, falling back to database")

        except Exception as e:
            logger.warning(f"[FILES] Failed to read from pod: {e}, falling back to database")

    # Default: Get files from database
    result = await db.execute(
        select(ProjectFile).where(ProjectFile.project_id == project_id)
    )
    files = result.scalars().all()
    logger.info(f"[FILES] Returning {len(files)} files from database")
    return files

@router.post("/{project_slug}/start-dev-container")
async def start_dev_container(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Start a development environment for the project."""
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    logger.info(f"[START-CONTAINER] Request to start dev container for project {project_slug} (ID: {project_id}), user {current_user.id}")

    # Start dev container (path is for metadata only in K8s mode)
    project_path = os.path.abspath(get_project_path(current_user.id, project_id))

    try:
        from ..dev_server_manager import get_container_manager
        container_manager = get_container_manager()
        logger.info(f"[START-CONTAINER] Starting container for project {project_id}...")
        url = await container_manager.start_container(project_path, str(project_id), current_user.id, project_slug=project.slug)
        logger.info(f"[START-CONTAINER] ✅ Container started successfully: {url}")
        return {"url": url, "hostname": url}
    except Exception as e:
        logger.error(f"[START-CONTAINER] ❌ Failed to start container: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start development environment: {str(e)}")

@router.post("/{project_slug}/restart-dev-container")
async def restart_dev_container(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    # Restart dev container
    project_path = os.path.abspath(get_project_path(current_user.id, project_id))
    try:
        from ..dev_server_manager import get_container_manager
        container_manager = get_container_manager()
        hostname = await container_manager.restart_container(project_path, str(project_id), current_user.id)
        return {"url": hostname, "hostname": hostname, "message": "Dev container restarted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart dev container: {str(e)}")

@router.post("/{project_slug}/stop-dev-container")
async def stop_dev_container(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    # Stop dev container
    try:
        from ..dev_server_manager import get_container_manager
        container_manager = get_container_manager()
        await container_manager.stop_container(str(project_id), current_user.id)
        return {"message": "Dev container stopped successfully", "project_id": project_id}
    except Exception as e:
        # Don't fail if container is already stopped
        return {"message": "Container stop attempted", "project_id": project_id}

@router.get("/{project_slug}/dev-server-url")
async def get_dev_server_url(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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

    logger.info(f"[DEV-URL] Checking dev environment for user {current_user.id}, project {project_id}")

    try:
        settings = get_settings()

        # Auto-restart container if it was stopped by cleanup task
        from ..dev_server_manager import get_container_manager
        container_manager = get_container_manager()
        await container_manager.ensure_container_running(str(project_id), current_user.id, project.slug)

        if settings.deployment_mode == "kubernetes":
            # Kubernetes mode - use K8s-specific health check
            from ..k8s_client import get_k8s_manager
            k8s_manager = get_k8s_manager()
            health = await k8s_manager.check_dev_environment_health(current_user.id, str(project_id))

            if health["exists"] and health["ready"]:
                logger.info(f"[DEV-URL] ✅ Environment exists and is ready: {health['url']}")
                k8s_manager.track_activity(current_user.id, str(project_id))
                return {
                    "url": health["url"],
                    "status": "ready",
                    "message": "Development environment is ready"
                }

            if health["exists"] and not health["ready"]:
                logger.info(f"[DEV-URL] ⏳ Environment exists but not ready yet")
                return {
                    "url": None,
                    "status": "starting",
                    "message": health["message"],
                    "replicas": health.get("replicas"),
                    "hint": "Please wait a moment and try again"
                }
        else:
            # Docker mode - use Docker-specific status check
            from ..dev_server_manager import get_container_manager
            docker_manager = get_container_manager()
            status = await docker_manager.get_container_status(str(project_id), current_user.id, project.slug)

            if status.get("running"):
                url = docker_manager.get_container_url(str(project_id), current_user.id)

                # Check Docker health status instead of making HTTP request
                # (HTTP requests fail from orchestrator container due to DNS resolution)
                health_status = status.get("health", "unknown")

                if health_status == "healthy":
                    logger.info(f"[DEV-URL] ✅ Container is running and healthy: {url}")
                    docker_manager.track_activity(current_user.id, str(project_id))
                    return {
                        "url": url,
                        "status": "ready",
                        "message": "Development environment is ready"
                    }
                else:
                    logger.info(f"[DEV-URL] ⏳ Container is running but health status is: {health_status}")
                    # Container exists but not healthy yet - return starting status
                    return {
                        "url": None,
                        "status": "starting",
                        "message": "Development server is starting, please wait...",
                        "hint": f"The container is running but health check is {health_status}. Try again in a few seconds."
                    }

        # Container doesn't exist - create it
        logger.info(f"[DEV-URL] Container does not exist, creating new environment...")
        # Use absolute path to ensure files are created in the correct location
        project_path = os.path.abspath(get_project_path(current_user.id, project_id))

        # In Docker mode, create project directory from database files if it doesn't exist
        if settings.deployment_mode == "docker" and not os.path.exists(project_path):
            logger.info(f"[DEV-URL] Creating project directory from database files: {project_path}")
            # Create parent directory first to avoid Windows bind mount issues
            user_dir = os.path.abspath(f"users/{current_user.id}")

            # Force create directories using Path (more reliable on Windows Docker volumes)
            from pathlib import Path
            try:
                Path(project_path).mkdir(parents=True, exist_ok=True)
                logger.info(f"[DEV-URL] Created project directory: {project_path}")
            except Exception as e:
                logger.error(f"[DEV-URL] Failed to create project directory: {e}")
                # Try alternative method
                import subprocess
                subprocess.run(['mkdir', '-p', project_path], check=False, capture_output=True)

            # Give filesystem a moment to sync (Windows Docker volume issue)
            import time
            time.sleep(0.1)

            # Verify directory was created
            if not os.path.exists(project_path):
                raise FileNotFoundError(f"Failed to create project directory: {project_path}")

            # Get all files from database
            files_result = await db.execute(
                select(ProjectFile).where(ProjectFile.project_id == project_id)
            )
            project_files = files_result.scalars().all()

            if not project_files:
                logger.error(f"[DEV-URL] No files found in database for project {project_id}")
                raise HTTPException(
                    status_code=500,
                    detail="Project has no files. Please recreate the project."
                )

            # Write each file to filesystem
            for db_file in project_files:
                file_full_path = os.path.join(project_path, db_file.file_path)

                # Create parent directory (with safety check for Windows Docker volumes)
                parent_dir = os.path.dirname(file_full_path)
                if parent_dir:
                    try:
                        os.makedirs(parent_dir, exist_ok=True)
                    except FileExistsError:
                        # Handle race condition on Windows Docker volumes - verify it exists
                        if not os.path.exists(parent_dir):
                            raise

                with open(file_full_path, 'w', encoding='utf-8') as f:
                    f.write(db_file.content)

                logger.debug(f"[DEV-URL] Created file: {db_file.file_path}")

            logger.info(f"[DEV-URL] Created {len(project_files)} files from database")

        from ..dev_server_manager import get_container_manager
        container_manager = get_container_manager()
        url = await container_manager.start_container(project_path, str(project_id), current_user.id, project_slug=project.slug)
        logger.info(f"[DEV-URL] ✅ Dev container started successfully: {url}")

        return {
            "url": url,
            "status": "ready",
            "message": "Development environment created successfully"
        }

    except Exception as e:
        logger.error(f"[DEV-URL] ❌ Failed to get/create dev environment", exc_info=True)

        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to start development environment",
                "message": str(e),
                "user_id": current_user.id,
                "project_id": project_id,
                "hint": f"Check Kubernetes pod logs: kubectl logs -l app=dev-environment,user-id={current_user.id},project-id={project_id} -n tesslate-user-environments"
            }
        )

@router.get("/{project_slug}/container-status")
async def get_container_status(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
        settings = get_settings()

        if settings.deployment_mode == "kubernetes":
            # Kubernetes mode
            from ..k8s_client import get_k8s_manager
            k8s_manager = get_k8s_manager()

            readiness = await k8s_manager.is_pod_ready(
                current_user.id,
                str(project_id),
                check_responsive=True
            )

            # Get full environment status
            env_status = await k8s_manager.get_dev_environment_status(
                current_user.id,
                str(project_id)
            )

            return {
                "status": "ready" if readiness["ready"] else "starting",
                "ready": readiness["ready"],
                "phase": readiness["phase"],
                "message": readiness["message"],
                "responsive": readiness.get("responsive"),
                "conditions": readiness.get("conditions", []),
                "pod_name": readiness.get("pod_name"),
                "url": env_status.get("url"),
                "deployment": env_status.get("deployment_ready"),
                "replicas": env_status.get("replicas"),
                "project_id": project_id,
                "user_id": current_user.id
            }
        else:
            # Docker mode
            from ..dev_server_manager import get_container_manager
            docker_manager = get_container_manager()
            status = await docker_manager.get_container_status(str(project_id), current_user.id)
            url = docker_manager.get_container_url(str(project_id), current_user.id)

            return {
                "status": "ready" if status.get("running") else "stopped",
                "ready": status.get("running", False),
                "phase": status.get("status", "Unknown"),
                "message": "Container is running" if status.get("running") else "Container is not running",
                "url": url,
                "project_id": project_id,
                "user_id": current_user.id
            }

    except Exception as e:
        logger.error(f"[STATUS] Failed to get container status: {e}", exc_info=True)
        return {
            "status": "error",
            "ready": False,
            "phase": "Unknown",
            "message": f"Failed to get status: {str(e)}",
            "project_id": project_id,
            "user_id": current_user.id
        }

@router.post("/{project_slug}/files/save")
async def save_project_file(
    project_slug: str,
    file_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Save a file to the user's dev container.

    Architecture: Backend is stateless and doesn't store files.
    Instead, it writes files directly to the dev container pod via K8s API.
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    file_path = file_data.get('file_path')
    content = file_data.get('content')

    if not file_path or content is None:
        raise HTTPException(status_code=400, detail="file_path and content are required")

    try:
        settings = get_settings()

        # 1. Write file to container/filesystem
        if settings.deployment_mode == "kubernetes":
            # K8s mode: Write directly to pod via K8s API
            try:
                from ..k8s_client import get_k8s_manager
                k8s_manager = get_k8s_manager()

                success = await k8s_manager.write_file_to_pod(
                    user_id=current_user.id,
                    project_id=str(project_id),
                    file_path=file_path,
                    content=content
                )

                if not success:
                    raise RuntimeError("Failed to write file to pod")

                logger.info(f"[FILE] ✅ Wrote {file_path} to pod for user {current_user.id}, project {project_id}")
                k8s_manager.track_activity(current_user.id, str(project_id))

            except Exception as k8s_error:
                logger.warning(f"[FILE] ⚠️ Failed to write to pod: {k8s_error}")
                # Continue to save in DB even if pod write fails
        else:
            # Docker mode: Write to filesystem (volume-mounted to container)
            try:
                project_path = os.path.abspath(get_project_path(current_user.id, project_id))
                os.makedirs(project_path, exist_ok=True)

                full_file_path = os.path.join(project_path, file_path)

                # Create parent directory (with safety check for Windows Docker volumes)
                parent_dir = os.path.dirname(full_file_path)
                if parent_dir:
                    try:
                        os.makedirs(parent_dir, exist_ok=True)
                    except FileExistsError:
                        # Handle race condition on Windows Docker volumes - verify it exists
                        if not os.path.exists(parent_dir):
                            raise

                with open(full_file_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                logger.info(f"[FILE] ✅ Wrote {file_path} to filesystem for user {current_user.id}, project {project_id}")

                # Track activity to keep container alive
                try:
                    from ..dev_server_manager import get_container_manager
                    container_manager = get_container_manager()
                    container_manager.track_activity(current_user.id, str(project_id))
                except Exception as e:
                    logger.debug(f"Could not track file save activity: {e}")

            except Exception as docker_error:
                logger.warning(f"[FILE] ⚠️ Failed to write to filesystem: {docker_error}")

        # 2. Update database record (for version history / backup)
        result = await db.execute(
            select(ProjectFile).where(
                ProjectFile.project_id == project_id,
                ProjectFile.file_path == file_path
            )
        )
        existing_file = result.scalar_one_or_none()

        if existing_file:
            existing_file.content = content
        else:
            new_file = ProjectFile(
                project_id=project_id,
                file_path=file_path,
                content=content
            )
            db.add(new_file)

        # Update project's updated_at timestamp
        from datetime import datetime
        project.updated_at = datetime.utcnow()

        await db.commit()

        logger.info(f"[FILE] Saved {file_path} to database as backup")

        return {
            "message": "File saved successfully",
            "file_path": file_path,
            "method": "kubernetes_api"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] Failed to save file {file_path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

@router.get("/{project_slug}/container-info")
async def get_container_info(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
            "git_command_example": f"kubectl exec -n {namespace} {pod_name} -- git status"
        }
    else:
        from ..utils.resource_naming import get_container_name
        container_name = get_container_name(current_user.id, project_id, mode="docker")
        return {
            "deployment_mode": "docker",
            "container_name": container_name,
            "command_prefix": f"docker exec {container_name}",
            "git_command_example": f"docker exec {container_name} git status"
        }

@router.get("/containers/all")
async def get_all_dev_containers(
    current_user: User = Depends(current_active_user)
):
    """Get all running development containers (for admin/debugging)."""
    try:
        from ..dev_server_manager import get_container_manager
        container_manager = get_container_manager()
        containers = await container_manager.get_all_containers()
        # Filter to show only containers for current user unless admin
        user_containers = [c for c in containers if c.get('user_id') == current_user.id]
        return {
            "containers": user_containers,
            "total": len(user_containers),
            "user_id": current_user.id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get containers: {str(e)}")

@router.delete("/{project_slug}")
async def delete_project(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a project and ALL associated data including chats, messages, files, and containers."""
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    try:
        logger.info(f"[DELETE] Starting deletion of project {project_id} for user {current_user.id}")

        # 1. Stop and remove any running containers/pods
        try:
            from ..dev_server_manager import get_container_manager
            container_manager = get_container_manager()
            await container_manager.stop_container(str(project_id), current_user.id)
            logger.info(f"[DELETE] Stopped containers for project {project_id}")
        except Exception as e:
            logger.warning(f"[DELETE] Error stopping containers: {e}")

        # 2. Delete all chats associated with this project (and their messages will cascade)
        chats_result = await db.execute(
            select(Chat).where(Chat.project_id == project_id)
        )
        project_chats = chats_result.scalars().all()

        for chat in project_chats:
            logger.info(f"[DELETE] Deleting chat {chat.id} with messages")
            await db.delete(chat)  # Use ORM delete to trigger cascades

        logger.info(f"[DELETE] Deleted {len(project_chats)} chats and their messages")

        # 3. Delete project from database (files will cascade automatically)
        await db.delete(project)  # Use ORM delete to trigger cascades
        await db.commit()
        logger.info(f"[DELETE] Deleted project from database")

        # 5. Delete filesystem directory (Docker mode only - K8s uses PVCs)
        settings = get_settings()
        if settings.deployment_mode == "docker":
            project_dir = os.path.abspath(get_project_path(current_user.id, project_id))
            if os.path.exists(project_dir):
                try:
                    shutil.rmtree(project_dir)
                    logger.info(f"[DELETE] Deleted filesystem directory: {project_dir}")
                except PermissionError:
                    # On Windows, wait a moment and try again
                    await asyncio.sleep(1)
                    try:
                        shutil.rmtree(project_dir)
                        logger.info(f"[DELETE] Deleted filesystem directory: {project_dir}")
                    except PermissionError as e:
                        logger.warning(f"[DELETE] Could not delete project directory: {e}")

        logger.info(f"[DELETE] Successfully deleted project {project_id}")
        return {"message": "Project deleted successfully", "project_id": project_id}

    except Exception as e:
        await db.rollback()
        logger.error(f"[DELETE] Error during project deletion: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete project: {str(e)}")


@router.post("/{project_slug}/generate-architecture-diagram")
async def generate_architecture_diagram(
    project_slug: str,
    diagram_type: str = "mermaid",  # "mermaid" or "c4_plantuml"
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate an architecture diagram for the project using the user's selected model.

    This endpoint analyzes the project files and generates either a Mermaid diagram
    or a C4 PlantUML diagram showing the architecture, component relationships, and data flow.

    Args:
        diagram_type: Type of diagram to generate ("mermaid" or "c4_plantuml")
    """
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id  # For internal operations

    # Check if user has selected a diagram model
    if not current_user.diagram_model:
        raise HTTPException(
            status_code=400,
            detail="No diagram generation model selected. Please select a model in your Library settings."
        )

    try:
        logger.info(f"[DIAGRAM] Generating {diagram_type} architecture diagram for project {project_id} using model {current_user.diagram_model}")

        # Get project files from database
        files_result = await db.execute(
            select(ProjectFile).where(ProjectFile.project_id == project_id)
        )
        project_files = files_result.scalars().all()

        if not project_files:
            raise HTTPException(status_code=400, detail="Project has no files to analyze")

        # Build a summary of the project structure
        file_structure = {}
        for file in project_files:
            # Skip large files and binary files
            if len(file.content) > 50000:
                continue
            if file.file_path.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf')):
                continue

            file_structure[file.file_path] = file.content[:5000]  # Limit content to first 5000 chars

        # Create prompt for diagram generation based on type
        if diagram_type == "c4_plantuml":
            prompt = f"""Analyze this project and generate a C4 PlantUML diagram showing the architecture.

Project Name: {project.name}
Project Description: {project.description or 'No description'}

Files in the project:
{chr(10).join(file_structure.keys())}

Key file contents (truncated):
{chr(10).join([f"--- {path} ---{chr(10)}{content[:500]}" for path, content in list(file_structure.items())[:10]])}

Please generate a C4 PlantUML diagram that shows:
1. System Context or Container level view (choose appropriately based on project size)
2. The main components/containers of the application
3. How they interact with each other
4. External dependencies or services if any

Use C4-PlantUML syntax with proper directives. Return ONLY the PlantUML code starting with '@startuml', no explanations or markdown code blocks.

Example format:
@startuml
!include https://raw.githubusercontent.com/plantuml-stdlib/C4-PlantUML/master/C4_Container.puml

Person(user, "User", "End user of the application")
System_Boundary(c1, "Application") {{
    Container(frontend, "Frontend", "React", "User interface")
    Container(backend, "Backend", "FastAPI", "Business logic and API")
    ContainerDb(database, "Database", "PostgreSQL", "Stores data")
}}

Rel(user, frontend, "Uses", "HTTPS")
Rel(frontend, backend, "Calls", "REST API")
Rel(backend, database, "Reads/Writes", "SQL")
@enduml"""
        else:  # mermaid (default)
            prompt = f"""Analyze this project and generate a Mermaid diagram showing the architecture.

Project Name: {project.name}
Project Description: {project.description or 'No description'}

Files in the project:
{chr(10).join(file_structure.keys())}

Key file contents (truncated):
{chr(10).join([f"--- {path} ---{chr(10)}{content[:500]}" for path, content in list(file_structure.items())[:10]])}

Please generate a Mermaid diagram that shows:
1. The main components/modules of the application
2. How they interact with each other
3. Data flow between components
4. External dependencies or services if any

Return ONLY the Mermaid diagram code starting with 'graph' or 'flowchart', no explanations or markdown code blocks."""

        # Call LiteLLM to generate the diagram
        import httpx
        from ..config import get_settings
        settings = get_settings()

        # Use the user's LiteLLM API key and selected model
        if not current_user.litellm_api_key:
            raise HTTPException(
                status_code=400,
                detail="LiteLLM API key not configured for your account"
            )

        # Use litellm_api_base from settings (same as all other LLM calls)
        litellm_url = settings.litellm_api_base

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{litellm_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {current_user.litellm_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": current_user.diagram_model,
                    "messages": [
                        {"role": "system", "content": f"You are an expert software architect. Generate clear, accurate {'C4 PlantUML' if diagram_type == 'c4_plantuml' else 'Mermaid'} diagrams."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 2000,
                    "temperature": 0.3
                }
            )

        if response.status_code != 200:
            logger.error(f"[DIAGRAM] LiteLLM API error: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate diagram: {response.text}"
            )

        result_data = response.json()
        diagram_code = result_data["choices"][0]["message"]["content"].strip()

        # Clean up the diagram code (remove markdown code blocks if present)
        if diagram_code.startswith("```plantuml") or diagram_code.startswith("```puml"):
            diagram_code = diagram_code.replace("```plantuml", "").replace("```puml", "").replace("```", "").strip()
        elif diagram_code.startswith("```mermaid"):
            diagram_code = diagram_code.replace("```mermaid", "").replace("```", "").strip()
        elif diagram_code.startswith("```"):
            diagram_code = diagram_code.replace("```", "").strip()

        # Sanitize based on diagram type
        import re

        if diagram_type == "c4_plantuml":
            # PlantUML sanitization is minimal - just ensure it has proper start/end tags
            if not diagram_code.startswith("@startuml"):
                diagram_code = "@startuml\n" + diagram_code
            if not diagram_code.endswith("@enduml"):
                diagram_code = diagram_code + "\n@enduml"
        else:
            # Sanitize Mermaid syntax to prevent parsing errors
            # Remove quotes from node labels and escape special characters

            # Fix: Remove double quotes around node labels that contain special chars
            # Match patterns like: A["@vitejs/plugin-react"] or B["some text"]
            diagram_code = re.sub(r'\["([^"]+)"\]', r'[\1]', diagram_code)
            diagram_code = re.sub(r'\("([^"]+)"\)', r'(\1)', diagram_code)
            diagram_code = re.sub(r'\{"([^"]+)"\}', r'{\1}', diagram_code)

            # Fix: Replace problematic characters in node labels
            # Replace @ symbol which can cause issues
            diagram_code = diagram_code.replace('@', 'at-')

            # Fix: Escape any remaining quotes in text
            lines = diagram_code.split('\n')
            sanitized_lines = []
            for line in lines:
                # Skip directive lines and graph declarations
                if line.strip().startswith(('graph', 'flowchart', '%%', 'classDef', 'class ', 'style ')):
                    sanitized_lines.append(line)
                else:
                    # For node and edge definitions, ensure labels don't have problematic chars
                    # Remove any stray quotes that might break parsing
                    line = line.replace('"', '')
                    sanitized_lines.append(line)

            diagram_code = '\n'.join(sanitized_lines)

        # Save diagram and diagram type to database
        project.architecture_diagram = diagram_code

        # Store diagram type in project settings
        if not project.settings:
            project.settings = {}
        project.settings['diagram_type'] = diagram_type
        flag_modified(project, 'settings')

        await db.commit()
        await db.refresh(project)

        logger.info(f"[DIAGRAM] Successfully generated and saved {diagram_type} diagram for project {project_id}")

        return {
            "diagram": diagram_code,
            "diagram_type": diagram_type,
            "model_used": current_user.diagram_model,
            "project_id": project_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DIAGRAM] Failed to generate diagram: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate diagram: {str(e)}")


@router.get("/{project_slug}/settings")
async def get_project_settings(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get project settings."""
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)

    settings = project.settings or {}
    return {
        "settings": settings,
        "architecture_diagram": project.architecture_diagram,
        "diagram_type": settings.get('diagram_type', 'mermaid')  # Default to mermaid for backwards compatibility
    }


@router.patch("/{project_slug}/settings")
async def update_project_settings(
    project_slug: str,
    settings_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Update project settings."""
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)

    try:
        # Merge new settings with existing
        current_settings = project.settings or {}
        new_settings = settings_data.get('settings', {})
        current_settings.update(new_settings)

        project.settings = current_settings
        flag_modified(project, 'settings')  # Mark JSON field as modified for SQLAlchemy
        await db.commit()
        await db.refresh(project)

        logger.info(f"[SETTINGS] Updated settings for project {project.id}: {new_settings}")

        return {
            "message": "Settings updated successfully",
            "settings": project.settings
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"[SETTINGS] Failed to update settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")


@router.post("/{project_id}/fork", response_model=ProjectSchema)
async def fork_project(
    project_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fork (duplicate) a project with all its files.
    Creates a new project with the same files as the original.
    """
    # Get source project
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == current_user.id
        )
    )
    source_project = result.scalar_one_or_none()
    if not source_project:
        raise HTTPException(status_code=404, detail="Project not found")

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
                    owner_id=current_user.id
                )
                db.add(forked_project)
                await db.commit()
                await db.refresh(forked_project)
                break
            except Exception as e:
                if "unique constraint" in str(e).lower() and "slug" in str(e).lower():
                    if attempt < max_retries - 1:
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
                content=source_file.content
            )
            db.add(forked_file)
            files_copied += 1

        await db.commit()
        await db.refresh(forked_project)

        logger.info(f"[FORK] Copied {files_copied} files to project {forked_project.id}")

        return forked_project

    except Exception as e:
        await db.rollback()
        logger.error(f"[FORK] Failed to fork project: {e}", exc_info=True)
        if 'forked_project' in locals():
            try:
                await db.delete(forked_project)
                await db.commit()
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to fork project: {str(e)}")


# ============================================================================
# Asset Management Endpoints
# ============================================================================

# Allowed file types for asset uploads
ALLOWED_MIME_TYPES = {
    # Images
    'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/svg+xml', 'image/webp', 'image/bmp', 'image/ico', 'image/x-icon',
    # Videos
    'video/mp4', 'video/webm', 'video/ogg', 'video/quicktime', 'video/x-msvideo',
    # Fonts
    'font/woff', 'font/woff2', 'font/ttf', 'font/otf', 'application/font-woff', 'application/font-woff2', 'application/x-font-ttf', 'application/x-font-otf',
    # Documents
    'application/pdf',
    # Audio
    'audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/webm',
}

# Maximum file size: 20MB
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB in bytes


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent security issues."""
    # Remove path components
    filename = os.path.basename(filename)
    # Replace spaces with hyphens
    filename = filename.replace(' ', '-')
    # Remove special characters except alphanumeric, dash, underscore, and dot
    filename = re.sub(r'[^\w\-.]', '_', filename)
    # Remove multiple dots (except before extension)
    name, ext = os.path.splitext(filename)
    name = name.replace('.', '_')
    return f"{name}{ext}"


def get_file_type(mime_type: str) -> str:
    """Determine file type category from MIME type."""
    if mime_type.startswith('image/'):
        return 'image'
    elif mime_type.startswith('video/'):
        return 'video'
    elif mime_type.startswith('font/') or 'font' in mime_type:
        return 'font'
    elif mime_type == 'application/pdf':
        return 'document'
    elif mime_type.startswith('audio/'):
        return 'audio'
    else:
        return 'other'


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
    db: AsyncSession = Depends(get_db)
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
                for root, dirs, files in os.walk(project_path):
                    for dir_name in dirs:
                        dir_full_path = os.path.join(root, dir_name)
                        # Get relative path from project root
                        rel_path = os.path.relpath(dir_full_path, project_path)
                        # Convert to forward slashes and add leading slash
                        rel_path = '/' + rel_path.replace('\\', '/')
                        # Skip hidden directories and common exclusions
                        if not any(part.startswith('.') for part in rel_path.split('/')):
                            directories_set.add(rel_path)
        else:
            # Kubernetes mode - directories are created via exec, so rely on DB + manual tracking
            # For K8s, we could use kubectl exec to list directories, but for now use DB
            pass

    except Exception as e:
        logger.warning(f"Failed to scan filesystem for directories: {e}")

    return {"directories": sorted(list(directories_set))}


@router.post("/{project_slug}/assets/directories")
async def create_asset_directory(
    project_slug: str,
    directory_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new directory for assets.
    This creates the physical directory in the project filesystem.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)
    project_id = project.id

    directory_path = directory_data.get('path', '').strip('/')
    if not directory_path:
        raise HTTPException(status_code=400, detail="Directory path is required")

    # Validate directory path (prevent path traversal)
    if '..' in directory_path or directory_path.startswith('/'):
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
            # Kubernetes mode - create directory in pod
            from ..k8s_client import get_k8s_manager
            k8s_manager = get_k8s_manager()

            # Use exec to create directory in pod
            command = f"mkdir -p /app/{directory_path}"
            await k8s_manager.exec_command_in_pod(
                current_user.id,
                str(project_id),
                command
            )
            logger.info(f"[ASSETS] Created directory in pod: {directory_path}")

        return {"message": "Directory created", "path": directory_path}

    except Exception as e:
        logger.error(f"[ASSETS] Failed to create directory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create directory: {str(e)}")


@router.post("/{project_slug}/assets/upload")
async def upload_asset(
    project_slug: str,
    file: UploadFile = File(...),
    directory: str = Form(...),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
    directory = directory.strip('/')
    if '..' in directory or directory.startswith('/'):
        raise HTTPException(status_code=400, detail="Invalid directory path")

    try:
        # Read file content
        content = await file.read()
        file_size = len(content)

        # Validate file size (20MB max)
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File size ({file_size / 1024 / 1024:.2f}MB) exceeds maximum allowed size (20MB)"
            )

        # Detect MIME type
        mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or 'application/octet-stream'

        # Validate file type
        if mime_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File type {mime_type} is not allowed. Only images, videos, fonts, and PDFs are supported."
            )

        # Sanitize filename
        safe_filename = sanitize_filename(file.filename)
        file_type = get_file_type(mime_type)

        # Get project path
        settings = get_settings()
        project_path = get_project_path(current_user.id, project_id)

        # Create assets directory path
        assets_dir = os.path.join(project_path, directory)
        file_path_relative = f"{directory}/{safe_filename}".lstrip('/')
        file_path_absolute = os.path.join(project_path, file_path_relative)

        # Check for duplicate filename
        existing_asset = await db.scalar(
            select(ProjectAsset).where(
                ProjectAsset.project_id == project_id,
                ProjectAsset.directory == f"/{directory}",
                ProjectAsset.filename == safe_filename
            )
        )

        if existing_asset:
            # Auto-increment filename
            name, ext = os.path.splitext(safe_filename)
            counter = 1
            while existing_asset:
                safe_filename = f"{name}-{counter}{ext}"
                file_path_relative = f"{directory}/{safe_filename}".lstrip('/')
                file_path_absolute = os.path.join(project_path, file_path_relative)
                existing_asset = await db.scalar(
                    select(ProjectAsset).where(
                        ProjectAsset.project_id == project_id,
                        ProjectAsset.directory == f"/{directory}",
                        ProjectAsset.filename == safe_filename
                    )
                )
                counter += 1

        # Write file to filesystem or pod
        if settings.deployment_mode == "docker":
            # Create directory if it doesn't exist
            os.makedirs(assets_dir, exist_ok=True)

            # Write file
            with open(file_path_absolute, 'wb') as f:
                f.write(content)

            logger.info(f"[ASSETS] Saved file to: {file_path_absolute}")
        else:
            # Kubernetes mode - write to pod
            from ..k8s_client import get_k8s_manager
            k8s_manager = get_k8s_manager()

            # Ensure directory exists
            await k8s_manager.exec_command_in_pod(
                current_user.id,
                str(project_id),
                f"mkdir -p /app/{directory}"
            )

            # Write file to pod
            success = await k8s_manager.write_file_to_pod(
                user_id=current_user.id,
                project_id=str(project_id),
                file_path=file_path_relative,
                content=content.decode('latin-1')  # Binary content
            )

            if not success:
                raise RuntimeError("Failed to write file to pod")

            logger.info(f"[ASSETS] Saved file to pod: {file_path_relative}")

        # Get image dimensions if it's an image
        width, height = None, None
        if file_type == 'image' and settings.deployment_mode == "docker":
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
            height=height
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
            "url": f"/api/projects/{project_slug}/assets/{db_asset.id}/file"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[ASSETS] Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload asset: {str(e)}")


@router.get("/{project_slug}/assets")
async def list_assets(
    project_slug: str,
    directory: Optional[str] = Query(None),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
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
                "url": f"/api/projects/{project_slug}/assets/{asset.id}/file"
            }
            for asset in assets
        ]
    }


@router.get("/{project_slug}/assets/{asset_id}/file")
async def get_asset_file(
    project_slug: str,
    asset_id: UUID,
    auth_token: Optional[str] = Query(None),
    current_user: Optional[User] = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Serve the actual asset file.
    Supports both Bearer token and query parameter token for image loading.
    """
    # If no current_user from Bearer, try auth_token query parameter
    if not current_user and auth_token:
        from ..users import fastapi_users
        from ..database import User as DBUser
        try:
            user_payload = await fastapi_users.authenticator.decode_token(auth_token)
            if user_payload:
                user_id = user_payload.get("sub")
                current_user = await db.get(DBUser, UUID(user_id))
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

        return FileResponse(
            file_path,
            media_type=asset.mime_type,
            filename=asset.filename
        )
    else:
        # Kubernetes mode - read from pod and return
        from ..k8s_client import get_k8s_manager
        k8s_manager = get_k8s_manager()

        content = await k8s_manager.read_file_from_pod(
            current_user.id,
            str(project.id),
            asset.file_path
        )

        if not content:
            raise HTTPException(status_code=404, detail="Asset file not found in pod")

        from fastapi.responses import Response
        return Response(content=content.encode('latin-1'), media_type=asset.mime_type)


@router.delete("/{project_slug}/assets/{asset_id}")
async def delete_asset(
    project_slug: str,
    asset_id: UUID,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete an asset and its file from the filesystem.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Asset not found")

    try:
        settings = get_settings()
        project_path = get_project_path(current_user.id, project.id)
        file_path = os.path.join(project_path, asset.file_path)

        # Delete file from filesystem or pod
        if settings.deployment_mode == "docker":
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"[ASSETS] Deleted file: {file_path}")
        else:
            # Kubernetes mode - delete from pod
            from ..k8s_client import get_k8s_manager
            k8s_manager = get_k8s_manager()

            await k8s_manager.exec_command_in_pod(
                current_user.id,
                str(project.id),
                f"rm -f /app/{asset.file_path}"
            )
            logger.info(f"[ASSETS] Deleted file from pod: {asset.file_path}")

        # Delete database record
        await db.delete(asset)
        await db.commit()

        return {"message": "Asset deleted successfully"}

    except Exception as e:
        await db.rollback()
        logger.error(f"[ASSETS] Delete failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete asset: {str(e)}")


@router.patch("/{project_slug}/assets/{asset_id}/rename")
async def rename_asset(
    project_slug: str,
    asset_id: UUID,
    rename_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Rename an asset file.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Asset not found")

    new_filename = rename_data.get('new_filename', '').strip()
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
            ProjectAsset.id != asset_id
        )
    )

    if existing_asset:
        raise HTTPException(status_code=400, detail="An asset with this name already exists in this directory")

    try:
        settings = get_settings()
        project_path = get_project_path(current_user.id, project.id)

        old_file_path = os.path.join(project_path, asset.file_path)
        new_file_path_relative = f"{asset.directory.strip('/')}/{new_filename}".lstrip('/')
        new_file_path_absolute = os.path.join(project_path, new_file_path_relative)

        # Rename file in filesystem or pod
        if settings.deployment_mode == "docker":
            if os.path.exists(old_file_path):
                os.rename(old_file_path, new_file_path_absolute)
                logger.info(f"[ASSETS] Renamed file: {old_file_path} -> {new_file_path_absolute}")
        else:
            # Kubernetes mode
            from ..k8s_client import get_k8s_manager
            k8s_manager = get_k8s_manager()

            await k8s_manager.exec_command_in_pod(
                current_user.id,
                str(project.id),
                f"mv /app/{asset.file_path} /app/{new_file_path_relative}"
            )
            logger.info(f"[ASSETS] Renamed file in pod: {asset.file_path} -> {new_file_path_relative}")

        # Update database record
        asset.filename = new_filename
        asset.file_path = new_file_path_relative
        await db.commit()
        await db.refresh(asset)

        return {
            "id": str(asset.id),
            "filename": asset.filename,
            "file_path": asset.file_path,
            "message": "Asset renamed successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[ASSETS] Rename failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to rename asset: {str(e)}")


@router.patch("/{project_slug}/assets/{asset_id}/move")
async def move_asset(
    project_slug: str,
    asset_id: UUID,
    move_data: dict,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Move an asset to a different directory.
    """
    project = await get_project_by_slug(db, project_slug, current_user.id)

    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project.id:
        raise HTTPException(status_code=404, detail="Asset not found")

    new_directory = move_data.get('directory', '').strip('/')
    if not new_directory:
        raise HTTPException(status_code=400, detail="New directory is required")

    # Validate directory path
    if '..' in new_directory:
        raise HTTPException(status_code=400, detail="Invalid directory path")

    new_directory = f"/{new_directory}"

    # Check if moving to same directory
    if new_directory == asset.directory:
        return {"message": "Asset is already in this directory"}

    try:
        settings = get_settings()
        project_path = get_project_path(current_user.id, project.id)

        old_file_path = os.path.join(project_path, asset.file_path)
        new_file_path_relative = f"{new_directory.strip('/')}/{asset.filename}".lstrip('/')
        new_file_path_absolute = os.path.join(project_path, new_file_path_relative)

        # Move file in filesystem or pod
        if settings.deployment_mode == "docker":
            # Ensure new directory exists
            new_dir_absolute = os.path.dirname(new_file_path_absolute)
            os.makedirs(new_dir_absolute, exist_ok=True)

            if os.path.exists(old_file_path):
                shutil.move(old_file_path, new_file_path_absolute)
                logger.info(f"[ASSETS] Moved file: {old_file_path} -> {new_file_path_absolute}")
        else:
            # Kubernetes mode
            from ..k8s_client import get_k8s_manager
            k8s_manager = get_k8s_manager()

            # Ensure directory exists
            await k8s_manager.exec_command_in_pod(
                current_user.id,
                str(project.id),
                f"mkdir -p /app/{new_directory.strip('/')}"
            )

            # Move file
            await k8s_manager.exec_command_in_pod(
                current_user.id,
                str(project.id),
                f"mv /app/{asset.file_path} /app/{new_file_path_relative}"
            )
            logger.info(f"[ASSETS] Moved file in pod: {asset.file_path} -> {new_file_path_relative}")

        # Update database record
        asset.directory = new_directory
        asset.file_path = new_file_path_relative
        await db.commit()
        await db.refresh(asset)

        return {
            "id": str(asset.id),
            "directory": asset.directory,
            "file_path": asset.file_path,
            "message": "Asset moved successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"[ASSETS] Move failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to move asset: {str(e)}")


# ============================================================================
# Deployment Management (for billing/premium features)
# ============================================================================

@router.post("/{project_slug}/deploy")
async def deploy_project(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a project as deployed (keeps container running permanently).
    This is a premium feature with tier-based limits.
    """
    # Get project
    project = await get_project_by_slug(db, project_slug, current_user.id)

    # Check if already deployed
    if project.is_deployed:
        return {
            "message": "Project is already deployed",
            "project_id": str(project.id)
        }

    # Check deployment limits
    from ..config import get_settings
    settings = get_settings()

    # Count current deployed projects
    deployed_count_result = await db.execute(
        select(func.count(Project.id)).where(
            and_(
                Project.owner_id == current_user.id,
                Project.is_deployed == True
            )
        )
    )
    deployed_count = deployed_count_result.scalar()

    # Determine max deploys based on tier
    if current_user.subscription_tier == "pro":
        max_deploys = settings.premium_max_deploys
    else:
        max_deploys = settings.free_max_deploys

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
                    "purchase_additional_url": "/api/billing/deploy/purchase"
                }
            )

    # Mark as deployed
    project.is_deployed = True
    project.deploy_type = "deployed"
    project.deployed_at = datetime.now(timezone.utc)
    current_user.deployed_projects_count += 1

    await db.commit()

    logger.info(f"[DEPLOY] Project {project_slug} deployed for user {current_user.id}")

    return {
        "message": "Project deployed successfully",
        "project_id": str(project.id),
        "deployed_at": project.deployed_at.isoformat()
    }


@router.delete("/{project_slug}/deploy")
async def undeploy_project(
    project_slug: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Remove deployment status from a project (allows container to be stopped when idle).
    """
    # Get project
    project = await get_project_by_slug(db, project_slug, current_user.id)

    if not project.is_deployed:
        return {
            "message": "Project is not deployed",
            "project_id": str(project.id)
        }

    # Undeploy
    project.is_deployed = False
    project.deploy_type = "development"
    project.deployed_at = None
    current_user.deployed_projects_count = max(0, current_user.deployed_projects_count - 1)

    await db.commit()

    logger.info(f"[DEPLOY] Project {project_slug} undeployed for user {current_user.id}")

    return {
        "message": "Project undeployed successfully",
        "project_id": str(project.id)
    }


@router.get("/deployment/limits")
async def get_deployment_limits(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current deployment limits and usage for the user.
    """
    from ..config import get_settings
    settings = get_settings()

    # Count deployed projects
    deployed_count_result = await db.execute(
        select(func.count(Project.id)).where(
            and_(
                Project.owner_id == current_user.id,
                Project.is_deployed == True
            )
        )
    )
    deployed_count = deployed_count_result.scalar()

    # Determine limits
    if current_user.subscription_tier == "pro":
        base_max_deploys = settings.premium_max_deploys
        base_max_projects = settings.premium_max_projects
    else:
        base_max_deploys = settings.free_max_deploys
        base_max_projects = settings.free_max_projects

    # Calculate additional slots from purchases
    additional_slots = current_user.total_spend // settings.additional_deploy_price
    effective_max_deploys = base_max_deploys + additional_slots

    # Count total projects
    total_projects_result = await db.execute(
        select(func.count(Project.id)).where(
            Project.owner_id == current_user.id
        )
    )
    total_projects = total_projects_result.scalar()

    return {
        "tier": current_user.subscription_tier,
        "projects": {
            "current": total_projects,
            "max": base_max_projects
        },
        "deploys": {
            "current": deployed_count,
            "base_max": base_max_deploys,
            "additional_purchased": additional_slots,
            "effective_max": effective_max_deploys
        },
        "can_deploy_more": deployed_count < effective_max_deploys,
        "can_create_more_projects": total_projects < base_max_projects
    }


@router.post("/deployment/purchase-slot")
async def purchase_additional_deploy_slot(
    request: Request,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a checkout session for purchasing an additional deploy slot.
    """
    from ..services.stripe_service import stripe_service
    from ..config import get_settings
    settings = get_settings()

    # Use origin-based URLs to preserve user's domain
    origin = request.headers.get('origin') or request.headers.get('referer', '').rstrip('/').split('?')[0].rsplit('/', 1)[0] or settings.get_app_base_url
    success_url = f"{origin}/billing/deploy/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/projects"

    session = await stripe_service.create_deploy_purchase_checkout(
        user=current_user,
        success_url=success_url,
        cancel_url=cancel_url,
        db=db
    )

    if not session:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session"
        )

    return {
        "checkout_url": session['url'],
        "session_id": session['id']
    }

# WebSocket endpoint for streaming container logs
@router.websocket("/{project_slug}/logs/stream")
async def stream_container_logs(
    websocket: WebSocket,
    project_slug: str,
    db: AsyncSession = Depends(get_db)
):
    """
    WebSocket endpoint to stream container logs in real-time.
    Streams stdout/stderr from the project's dev container.
    """
    from fastapi import WebSocket, WebSocketDisconnect
    import docker
    import asyncio
    
    await websocket.accept()
    
    try:
        # Get project
        result = await db.execute(
            select(Project).where(Project.slug == project_slug)
        )
        project = result.scalar_one_or_none()
        
        if not project:
            await websocket.send_json({"type": "error", "message": "Project not found"})
            await websocket.close()
            return
        
        # Get container name
        from ..utils.resource_naming import get_container_name
        container_name = get_container_name(str(project.user_id), str(project.id))
        
        await websocket.send_json({"type": "status", "message": f"Connecting to container: {container_name}"})
        
        # Connect to Docker
        docker_client = docker.from_env()
        
        try:
            container = docker_client.containers.get(container_name)
            
            await websocket.send_json({"type": "status", "message": "Container found. Streaming logs..."})
            
            # Stream logs (follow=True for real-time)
            log_stream = container.logs(stream=True, follow=True, stdout=True, stderr=True, tail=100)
            
            # Stream logs to WebSocket
            for log_line in log_stream:
                try:
                    # Decode and send log line
                    log_text = log_line.decode('utf-8', errors='replace')
                    await websocket.send_json({"type": "log", "data": log_text})
                    
                    # Check for disconnect
                    try:
                        message = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                        if message == "ping":
                            await websocket.send_text("pong")
                    except asyncio.TimeoutError:
                        pass  # No message, continue streaming
                        
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error streaming log line: {e}")
                    break
                    
        except docker.errors.NotFound:
            await websocket.send_json({"type": "error", "message": "Container not found. Start the dev server first."})
        except Exception as e:
            logger.error(f"Error accessing container: {e}")
            await websocket.send_json({"type": "error", "message": f"Container error: {str(e)}"})
        finally:
            docker_client.close()
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for project {project_slug}")
    except Exception as e:
        logger.error(f"WebSocket error for project {project_slug}: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass


@router.websocket("/{project_slug}/terminal")
async def interactive_terminal(
    websocket: WebSocket,
    project_slug: str,
    db: AsyncSession = Depends(get_db)
):
    """
    WebSocket endpoint for interactive terminal with PTY support.
    Provides full bidirectional shell access to the project's dev container.

    Message format:
    - Client -> Server: {"type": "input", "data": "command text"} or {"type": "resize", "cols": 80, "rows": 24}
    - Server -> Client: {"type": "output", "data": "terminal output"} or {"type": "error", "message": "error text"}
    """
    from fastapi import WebSocket, WebSocketDisconnect
    from ..services.shell_session_manager import ShellSessionManager
    from ..services.pty_broker import get_pty_broker
    import json

    await websocket.accept()
    session_id = None
    shell_manager = ShellSessionManager()
    output_task = None

    try:
        # Get project and verify ownership
        result = await db.execute(
            select(Project).where(Project.slug == project_slug)
        )
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
            session_info = await shell_manager.create_session(
                user_id=user_id,
                project_id=str(project.id),
                db=db,
                command="/bin/sh"
            )
            session_id = session_info["session_id"]

            await websocket.send_json({"type": "status", "message": f"Shell session created: {session_id}"})

        except HTTPException as e:
            await websocket.send_json({"type": "error", "message": e.detail})
            await websocket.close()
            return
        except Exception as e:
            logger.error(f"Failed to create shell session: {e}")
            await websocket.send_json({"type": "error", "message": f"Failed to create shell: {str(e)}"})
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
        await websocket.send_json({"type": "output", "data": "\r\n\x1b[38;5;208m╔═══════════════════════════════════════╗\x1b[0m\r\n"})
        await websocket.send_json({"type": "output", "data": "\x1b[38;5;208m║   Tesslate Studio - Interactive Shell ║\x1b[0m\r\n"})
        await websocket.send_json({"type": "output", "data": "\x1b[38;5;208m╚═══════════════════════════════════════╝\x1b[0m\r\n\r\n"})

        # Start background task to stream PTY output to WebSocket
        async def stream_output():
            """Stream PTY output to WebSocket"""
            try:
                while True:
                    # Read new output from PTY session
                    new_data, is_eof = await pty_session.read_new_output()

                    if new_data:
                        # Send raw output to client
                        await websocket.send_json({
                            "type": "output",
                            "data": new_data.decode('utf-8', errors='replace')
                        })

                    if is_eof:
                        await websocket.send_json({"type": "status", "message": "Shell session ended"})
                        break

                    # Small delay to prevent tight loop
                    await asyncio.sleep(0.05)

            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected during output streaming")
            except Exception as e:
                logger.error(f"Error streaming output: {e}")
                try:
                    await websocket.send_json({"type": "error", "message": f"Stream error: {str(e)}"})
                except:
                    pass

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
                        data=input_data.encode('utf-8'),
                        db=db,
                        user_id=user_id
                    )

                elif data.get("type") == "resize":
                    # Terminal resize event
                    cols = data.get("cols", 80)
                    rows = data.get("rows", 24)

                    # Resize PTY
                    if pty_session and hasattr(pty_session, 'resize'):
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
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        # Clean up output streaming task
        if output_task:
            output_task.cancel()
            try:
                await output_task
            except asyncio.CancelledError:
                pass

        # Close shell session
        if session_id:
            try:
                await shell_manager.close_session(
                    session_id=session_id,
                    db=db
                )
                logger.info(f"Closed shell session {session_id}")
            except Exception as e:
                logger.error(f"Error closing session {session_id}: {e}")

        try:
            await websocket.close()
        except:
            pass
