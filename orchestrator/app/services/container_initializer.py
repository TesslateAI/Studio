"""
Container Initializer Service

Handles async initialization of containers:
- Creates volumes
- Copies base files from cache
- Syncs files to database
- Sets permissions

This runs in background to avoid blocking the HTTP request.
"""

import os
import asyncio
import logging
import subprocess
from pathlib import Path
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..models import Container, Project, ProjectFile, MarketplaceBase
from ..services.volume_manager import get_volume_manager
from ..services.base_cache_manager import get_base_cache_manager
from ..services.docker_compose_orchestrator import get_compose_orchestrator
from ..utils.async_fileio import walk_directory_async, read_file_async
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
    1. Creates a Docker volume (if using volumes)
    2. Copies base files from cache to volume
    3. Syncs files to database
    4. Sets permissions
    5. Updates docker-compose with volume name

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
        use_volumes = os.getenv('USE_DOCKER_VOLUMES', 'true').lower() == 'true'

        # Get container and project
        container = await db.get(Container, container_id)
        project = await db.get(Project, project_id)

        if not container or not project:
            logger.error(f"[CONTAINER-INIT] Container or project not found")
            task.update_progress(0, 100, "Container or project not found")
            raise ValueError("Container or project not found")

        logger.info(f"[CONTAINER-INIT] Starting initialization for container {container_id}")
        task.update_progress(10, 100, "Initializing container...")

        # Step 1: Create or reuse project volume
        if use_volumes:
            task.update_progress(20, 100, "Setting up project volume...")
            volume_manager = get_volume_manager()

            # Use project-level volume (shared by all containers in the project)
            if not project.volume_name:
                # First container in project - create the volume
                volume_name = f"{project.slug}"

                await volume_manager.create_project_volume(
                    volume_name,
                    labels={
                        'com.tesslate.project': project.slug,
                        'com.tesslate.user': str(user_id)
                    }
                )

                # Store volume name on project
                project.volume_name = volume_name
                await db.commit()

                logger.info(f"[CONTAINER-INIT] Created project volume {volume_name}")
            else:
                # Reuse existing project volume
                volume_name = project.volume_name
                logger.info(f"[CONTAINER-INIT] Reusing existing project volume {volume_name}")

            # Store volume reference on container for backwards compatibility
            container.volume_name = volume_name
            await db.commit()
        else:
            # Legacy: Create bind mount directory
            task.update_progress(20, 100, "Creating directory...")
            project_dir = os.path.join("/app/users", str(user_id), str(project_id))
            container_path = os.path.join(project_dir, container.directory)
            os.makedirs(container_path, exist_ok=True)
            logger.info(f"[CONTAINER-INIT] Created directory {container_path}")

        # Step 2: Copy base from cache (only for first container in project)
        base_cache_manager = get_base_cache_manager()
        cached_base_path = await base_cache_manager.get_base_path(base_slug)

        if use_volumes:
            # Check if this is the first container (volume was just created)
            # We check this by counting containers in the project
            from sqlalchemy import select, func
            from ..models import Container as ContainerModel

            container_count = await db.scalar(
                select(func.count(ContainerModel.id))
                .where(ContainerModel.project_id == project_id)
            )

            is_first_container = container_count == 1  # Only this container exists

            if is_first_container:
                # First container - copy base files to volume
                task.update_progress(40, 100, "Copying base files...")
                if cached_base_path and os.path.exists(cached_base_path):
                    logger.info(f"[CONTAINER-INIT] First container - copying from cache to volume {volume_name}")
                    await volume_manager.copy_base_to_volume(
                        base_slug,
                        volume_name,
                        exclude_patterns=['.git', '__pycache__', '*.pyc']
                    )
                    logger.info(f"[CONTAINER-INIT] Successfully copied from cache")
                else:
                    logger.warning(f"[CONTAINER-INIT] Base {base_slug} not in cache, skipping file copy")
                    # TODO: Fallback to git clone into volume
            else:
                # Subsequent container - volume already has files
                task.update_progress(40, 100, "Using existing project volume...")
                logger.info(f"[CONTAINER-INIT] Subsequent container - reusing existing volume files")
        else:
            # Legacy: Copy to bind mount
            if cached_base_path and os.path.exists(cached_base_path):
                logger.info(f"[CONTAINER-INIT] Copying from cache to {container_path}")
                import shutil
                shutil.copytree(
                    cached_base_path,
                    container_path,
                    ignore=shutil.ignore_patterns('.git'),
                    dirs_exist_ok=True
                )

                # Set permissions
                chown_result = subprocess.run(
                    ["chown", "-R", "1000:1000", container_path],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if chown_result.returncode == 0:
                    logger.info(f"[CONTAINER-INIT] Permissions set successfully")
            else:
                logger.warning(f"[CONTAINER-INIT] Base {base_slug} not in cache")

        # Step 3: Sync files to database
        if settings.deployment_mode == "docker":
            task.update_progress(60, 100, "Syncing files to database...")

            if use_volumes:
                # TODO: Read files from volume and save to database
                # For now, we'll sync later when files are edited
                logger.info(f"[CONTAINER-INIT] Skipping DB sync for volume (will sync on edit)")
            else:
                # Legacy: Read from bind mount and save to DB
                files_saved = 0
                walk_results = await walk_directory_async(
                    container_path,
                    exclude_dirs=['node_modules', '.git', 'dist', 'build', '.next', '__pycache__', 'venv']
                )

                for root, dirs, files in walk_results:
                    for file in files:
                        if file.startswith('.') or file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico')):
                            continue

                        file_full_path = os.path.join(root, file)
                        relative_to_project = os.path.relpath(file_full_path, os.path.join("/app/users", str(user_id), str(project_id))).replace('\\', '/')

                        try:
                            content = await read_file_async(file_full_path)

                            # Check if file already exists
                            existing_file_result = await db.execute(
                                select(ProjectFile).where(
                                    ProjectFile.project_id == project_id,
                                    ProjectFile.file_path == relative_to_project
                                )
                            )
                            existing_file = existing_file_result.scalar_one_or_none()

                            if existing_file:
                                existing_file.content = content
                            else:
                                db_file = ProjectFile(
                                    project_id=project_id,
                                    file_path=relative_to_project,
                                    content=content
                                )
                                db.add(db_file)

                            files_saved += 1
                        except Exception as e:
                            logger.warning(f"[CONTAINER-INIT] Could not read file {relative_to_project}: {e}")

                await db.commit()
                logger.info(f"[CONTAINER-INIT] Saved {files_saved} files to database")

        # Step 4: Regenerate docker-compose
        task.update_progress(90, 100, "Updating Docker Compose configuration...")
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
            orchestrator = get_compose_orchestrator()
            await orchestrator.write_compose_file(
                project, all_containers, all_connections, user_id
            )

            logger.info(f"[CONTAINER-INIT] Updated docker-compose.yml")
        except Exception as e:
            logger.error(f"[CONTAINER-INIT] Failed to update docker-compose: {e}")

        # Done!
        task.update_progress(100, 100, "Container initialized successfully")
        logger.info(f"[CONTAINER-INIT] ✅ Container {container_id} initialized successfully")

    except Exception as e:
        logger.error(f"[CONTAINER-INIT] ❌ Failed to initialize container: {e}", exc_info=True)
        task.update_progress(0, 100, f"Initialization failed: {str(e)}")
        raise  # Re-raise so task_manager marks it as failed

    finally:
        await db.close()
