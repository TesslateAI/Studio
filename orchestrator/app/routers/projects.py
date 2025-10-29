from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm.attributes import flag_modified
from ..database import get_db
from ..models import Project, User, ProjectFile, Chat, Message
from ..schemas import Project as ProjectSchema, ProjectCreate, ProjectFile as ProjectFileSchema
from ..auth import get_current_active_user
from ..config import get_settings
from ..utils.slug_generator import generate_project_slug
from ..utils.resource_naming import get_project_path
import os
import shutil
import asyncio
import logging

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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a project by its slug."""
    project = await get_project_by_slug(db, project_slug, current_user.id)
    return project

@router.get("/{project_slug}/files", response_model=List[ProjectFileSchema])
async def get_project_files(
    project_slug: str,
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user)
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
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate a Mermaid architecture diagram for the project using the user's selected model.

    This endpoint analyzes the project files and generates a Mermaid diagram
    showing the architecture, component relationships, and data flow.
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
        logger.info(f"[DIAGRAM] Generating architecture diagram for project {project_id} using model {current_user.diagram_model}")

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

        # Create prompt for diagram generation
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
                        {"role": "system", "content": "You are an expert software architect. Generate clear, accurate Mermaid diagrams."},
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
        if diagram_code.startswith("```mermaid"):
            diagram_code = diagram_code.replace("```mermaid", "").replace("```", "").strip()
        elif diagram_code.startswith("```"):
            diagram_code = diagram_code.replace("```", "").strip()

        # Save diagram to database
        project.architecture_diagram = diagram_code
        await db.commit()
        await db.refresh(project)

        logger.info(f"[DIAGRAM] Successfully generated and saved diagram for project {project_id}")

        return {
            "diagram": diagram_code,
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
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get project settings."""
    # Get project and verify ownership
    project = await get_project_by_slug(db, project_slug, current_user.id)

    return {
        "settings": project.settings or {},
        "architecture_diagram": project.architecture_diagram
    }


@router.patch("/{project_slug}/settings")
async def update_project_settings(
    project_slug: str,
    settings_data: dict,
    current_user: User = Depends(get_current_active_user),
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
    current_user: User = Depends(get_current_active_user),
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