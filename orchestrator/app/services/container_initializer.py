"""
Container Initializer Service

Handles async initialization of containers:
- Ensures project directory exists in shared volume
- Copies base files from cache
- Sets permissions
- Updates docker-compose configuration

Architecture:
- Uses shared tesslate-projects-data volume mounted at /projects
- Each project has files at /projects/{project-slug}/
- All containers in a project share the same volume with different working_dirs

This runs in background to avoid blocking the HTTP request.
"""

import os
import asyncio
import logging
from pathlib import Path
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..models import Container, Project, ProjectFile, MarketplaceBase
from ..services.base_cache_manager import get_base_cache_manager
from ..services.orchestration import get_orchestrator, is_docker_mode
from ..config import get_settings
from ..database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def initialize_container_async(
    container_id: UUID,
    project_id: UUID,
    user_id: UUID,
    base_slug: str,
    git_repo_url: str,
    task
) -> None:
    """
    Initialize a container asynchronously in the background.

    This function:
    1. Ensures project directory exists in shared volume
    2. Copies base files from cache (if first container)
    3. Sets permissions
    4. Updates docker-compose configuration

    Args:
        container_id: Container ID
        project_id: Project ID
        user_id: User ID
        base_slug: Base slug (for cache lookup)
        git_repo_url: Git repository URL (fallback if no cache)
        task: Task object for progress updates
    """
    # Get a new database session for this background task
    db = AsyncSessionLocal()

    try:
        settings = get_settings()
        orchestrator = get_orchestrator()

        # Get container and project
        container = await db.get(Container, container_id)
        project = await db.get(Project, project_id)

        if not container or not project:
            logger.error(f"[CONTAINER-INIT] Container or project not found")
            task.update_progress(0, 100, "Container or project not found")
            raise ValueError("Container or project not found")

        logger.info(f"[CONTAINER-INIT] Starting initialization for container {container_id}")
        task.update_progress(10, 100, "Initializing container...")

        # Step 1: Ensure project directory exists in shared volume
        task.update_progress(20, 100, "Ensuring project directory exists...")
        await orchestrator.ensure_project_directory(project.slug)
        logger.info(f"[CONTAINER-INIT] Project directory ready at /projects/{project.slug}")

        # Step 2: Copy base from cache (only for first container in project)
        base_cache_manager = get_base_cache_manager()
        cached_base_path = await base_cache_manager.get_base_path(base_slug)

        # Check if this is the first container by counting existing containers
        from sqlalchemy import func
        from ..models import Container as ContainerModel

        container_count = await db.scalar(
            select(func.count(ContainerModel.id))
            .where(ContainerModel.project_id == project_id)
        )

        is_first_container = container_count == 1  # Only this container exists

        # Determine target directory for this container's files
        # For multi-container projects, each container may have its own subdirectory
        container_dir = container.directory or '.'
        if container_dir == '.':
            # Root-level container - files go to project root
            target_subdir = None
            container_path = project.slug
        else:
            # Container has a subdirectory - files go there
            target_subdir = container_dir
            container_path = f"{project.slug}/{container_dir}"

        # Check if THIS container's directory has files (not just project root)
        # In K8s mode, we always initialize files via file-manager pod
        if not is_docker_mode():
            # KUBERNETES MODE: Initialize files via file-manager pod
            task.update_progress(40, 100, "Initializing container files (K8s mode)...")

            # Get git URL from base if available
            git_url = git_repo_url  # Use passed in URL as fallback

            # Try to get base from DB to get git_repo_url
            if container.base_id:
                base_query = await db.execute(
                    select(MarketplaceBase).where(MarketplaceBase.id == container.base_id)
                )
                base = base_query.scalar_one_or_none()
                if base and base.git_repo_url:
                    git_url = base.git_repo_url
                    logger.info(f"[CONTAINER-INIT] Using base git URL: {git_url}")

            # Initialize files via K8s orchestrator
            logger.info(f"[CONTAINER-INIT] K8s mode: Initializing files for {container_dir}")
            success = await orchestrator.initialize_container_files(
                project_id=project_id,
                user_id=user_id,
                container_id=container_id,
                container_directory=container_dir if container_dir != '.' else container.name.lower().replace(' ', '-'),
                git_url=git_url
            )

            if success:
                logger.info(f"[CONTAINER-INIT] ✅ K8s files initialized for {container.name}")
            else:
                logger.error(f"[CONTAINER-INIT] ❌ K8s file initialization failed for {container.name}")
        else:
            # DOCKER MODE: Copy from cache as before
            container_has_files = await orchestrator.project_has_files(project.slug, subdir=target_subdir)

            if not container_has_files:
                # This container's directory is empty - copy base files
                task.update_progress(40, 100, "Copying base files...")
                if cached_base_path and os.path.exists(cached_base_path):
                    logger.info(f"[CONTAINER-INIT] Copying base files from cache to /projects/{container_path}")
                    await orchestrator.copy_base_to_project(
                        base_slug,
                        project.slug,
                        exclude_patterns=['.git', '__pycache__', '*.pyc'],
                        target_subdir=target_subdir  # Copy to container's subdirectory
                    )
                    logger.info(f"[CONTAINER-INIT] Successfully copied from cache to {container_path}")
                else:
                    logger.warning(f"[CONTAINER-INIT] Base {base_slug} not in cache, skipping file copy")
                    # TODO: Fallback to git clone into volume
            else:
                # Container directory already has files
                task.update_progress(40, 100, "Using existing project files...")
                logger.info(f"[CONTAINER-INIT] Reusing existing files at /projects/{container_path}")

        # Step 3: Regenerate orchestrator configuration (docker-compose.yml in Docker mode)
        if is_docker_mode():
            task.update_progress(80, 100, "Updating Docker Compose configuration...")
            try:
                # Get all containers and connections
                containers_result = await db.execute(
                    select(Container)
                    .where(Container.project_id == project_id)
                    .options(selectinload(Container.base))  # Eagerly load base
                )
                all_containers = containers_result.scalars().all()

                from ..models import ContainerConnection
                connections_result = await db.execute(
                    select(ContainerConnection).where(ContainerConnection.project_id == project_id)
                )
                all_connections = connections_result.scalars().all()

                # Regenerate docker-compose.yml
                orchestrator = get_orchestrator()
                await orchestrator.write_compose_file(
                    project, all_containers, all_connections, user_id
                )

                logger.info(f"[CONTAINER-INIT] Updated docker-compose.yml")
            except Exception as e:
                logger.error(f"[CONTAINER-INIT] Failed to update docker-compose: {e}")
        else:
            task.update_progress(80, 100, "Skipping compose update (Kubernetes mode)")

        # Done!
        task.update_progress(100, 100, "Container initialized successfully")
        logger.info(f"[CONTAINER-INIT] ✅ Container {container_id} initialized successfully")

    except Exception as e:
        logger.error(f"[CONTAINER-INIT] ❌ Failed to initialize container: {e}", exc_info=True)
        task.update_progress(0, 100, f"Initialization failed: {str(e)}")
        raise  # Re-raise so task_manager marks it as failed

    finally:
        await db.close()
