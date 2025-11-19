"""
Volume Manager Service

Manages Docker volumes for user projects.
Replaces bind mounts with named volumes for:
- Faster I/O (no cross-filesystem overhead)
- Better isolation (per-project volumes)
- Easier cleanup (volumes deleted with projects)
- Non-blocking operations (async copy from base cache)

Architecture:
- Database (PostgreSQL) = source of truth for source files
- Volumes = runtime storage (node_modules, build artifacts, synced files)
- Base cache (volume) = pre-installed marketplace bases
"""

import os
import asyncio
import logging
import docker
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)


class VolumeManager:
    """
    Manages Docker volumes for user projects.

    Each project gets its own named volume: {project-slug}-project
    Multi-container projects get additional volumes per container if needed.
    """

    def __init__(self):
        self.docker_client = docker.from_env()
        self.dev_server_image = "tesslate-devserver:latest"

    async def create_project_volume(
        self,
        volume_name: str,
        labels: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Create a Docker volume for a project.

        Args:
            volume_name: Name of the volume (e.g., "my-project-abc123")
            labels: Optional labels for volume metadata

        Returns:
            Volume name

        Raises:
            docker.errors.APIError: If volume creation fails
        """
        try:
            default_labels = {
                'com.tesslate.type': 'project',
                'com.tesslate.managed': 'true'
            }
            if labels:
                default_labels.update(labels)

            # Create volume in thread pool to avoid blocking
            await asyncio.to_thread(
                self.docker_client.volumes.create,
                name=volume_name,
                driver='local',
                labels=default_labels
            )

            logger.info(f"[VOLUME] ✅ Created volume: {volume_name}")
            return volume_name

        except docker.errors.APIError as e:
            if 'already exists' in str(e).lower():
                logger.warning(f"[VOLUME] Volume {volume_name} already exists")
                return volume_name
            logger.error(f"[VOLUME] ❌ Failed to create volume {volume_name}: {e}")
            raise

    async def delete_volume(self, volume_name: str, force: bool = False) -> bool:
        """
        Delete a Docker volume.

        Args:
            volume_name: Name of the volume
            force: Force deletion even if in use

        Returns:
            True if deleted, False if not found
        """
        try:
            volume = await asyncio.to_thread(
                self.docker_client.volumes.get,
                volume_name
            )

            await asyncio.to_thread(volume.remove, force=force)
            logger.info(f"[VOLUME] ✅ Deleted volume: {volume_name}")
            return True

        except docker.errors.NotFound:
            logger.warning(f"[VOLUME] Volume {volume_name} not found")
            return False
        except docker.errors.APIError as e:
            logger.error(f"[VOLUME] ❌ Failed to delete volume {volume_name}: {e}")
            raise

    async def volume_exists(self, volume_name: str) -> bool:
        """Check if a volume exists."""
        try:
            await asyncio.to_thread(
                self.docker_client.volumes.get,
                volume_name
            )
            return True
        except docker.errors.NotFound:
            return False

    async def get_project_volumes(self, project_slug: str) -> List[str]:
        """
        Get all volumes for a project.

        Args:
            project_slug: Project slug

        Returns:
            List of volume names
        """
        try:
            volumes = await asyncio.to_thread(
                self.docker_client.volumes.list,
                filters={'label': f'com.tesslate.project={project_slug}'}
            )
            return [v.name for v in volumes]
        except Exception as e:
            logger.error(f"[VOLUME] Error listing volumes for {project_slug}: {e}")
            return []

    async def copy_base_to_volume(
        self,
        base_slug: str,
        volume_name: str,
        exclude_patterns: Optional[List[str]] = None
    ) -> None:
        """
        Copy a base from cache to a project volume.

        This runs in a temporary container with both volumes mounted:
        - Base cache volume (read-only): /cache
        - Project volume (read-write): /project

        Args:
            base_slug: Slug of the marketplace base
            volume_name: Target project volume name
            exclude_patterns: Patterns to exclude (e.g., '.git', '__pycache__')
        """
        if exclude_patterns is None:
            # Don't exclude node_modules - we want pre-installed deps!
            exclude_patterns = ['.git', '__pycache__', '*.pyc', '.DS_Store']

        logger.info(f"[VOLUME] Copying base {base_slug} to volume {volume_name}")

        try:
            # Build exclude patterns for tar (simpler and more robust than find)
            # tar can handle files, directories, and symlinks correctly
            exclude_args = []
            for pattern in exclude_patterns:
                exclude_args.append(f"--exclude='{pattern}'")

            exclude_str = ' '.join(exclude_args) if exclude_args else ''

            # Use tar to copy everything (preserves symlinks, permissions, etc.)
            # tar is available in Alpine images and handles all file types correctly
            # Then fix permissions so the non-root user (1000:1000) can write
            command = f"tar -C /cache/{base_slug} {exclude_str} -cf - . | tar -C /project -xf - && chown -R 1000:1000 /project"

            # Run in temporary container with both volumes mounted
            result = await asyncio.to_thread(
                self.docker_client.containers.run,
                image=self.dev_server_image,
                command=["sh", "-c", command],
                volumes={
                    'tesslate-base-cache': {
                        'bind': '/cache',
                        'mode': 'ro'  # Read-only
                    },
                    volume_name: {
                        'bind': '/project',
                        'mode': 'rw'
                    }
                },
                user='root',  # Need root for tar and chown operations
                detach=False,  # Wait for completion
                remove=True,   # Auto-cleanup
                stdout=True,
                stderr=True
            )

            logs = result.decode('utf-8', errors='replace')
            logger.info(f"[VOLUME] ✅ Copied base {base_slug} to {volume_name}")
            logger.debug(f"[VOLUME] Copy logs:\n{logs[:1000]}")  # First 1000 chars

        except docker.errors.ContainerError as e:
            error_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else str(e)
            logger.error(f"[VOLUME] ❌ Failed to copy base {base_slug}: {error_msg}")
            raise
        except Exception as e:
            logger.error(f"[VOLUME] ❌ Unexpected error copying base: {e}", exc_info=True)
            raise

    async def sync_db_to_volume(
        self,
        project_id: UUID,
        volume_name: str,
        db: AsyncSession
    ) -> int:
        """
        Sync project files from database to volume.

        This is for ensuring volume has latest code when database is source of truth.

        Args:
            project_id: Project ID
            volume_name: Target volume name
            db: Database session

        Returns:
            Number of files synced
        """
        from ..models import ProjectFile

        logger.info(f"[VOLUME] Syncing database files to volume {volume_name}")

        try:
            # Get all files for project from database
            result = await db.execute(
                select(ProjectFile).where(ProjectFile.project_id == project_id)
            )
            files = result.scalars().all()

            if not files:
                logger.warning(f"[VOLUME] No files found in database for project {project_id}")
                return 0

            # Write files to volume using temporary container
            files_synced = 0

            for file in files:
                # Create a temp script that writes the file
                # Escape content for shell
                content_escaped = file.content.replace("'", "'\\''")
                file_path_escaped = file.file_path.replace("'", "'\\''")

                # Create parent directory and write file
                command = f"""
                mkdir -p "$(dirname '/project/{file_path_escaped}')" && \
                cat > '/project/{file_path_escaped}' << 'EOF'
{file.content}
EOF
                """

                try:
                    await asyncio.to_thread(
                        self.docker_client.containers.run,
                        image=self.dev_server_image,
                        command=["sh", "-c", command],
                        volumes={
                            volume_name: {
                                'bind': '/project',
                                'mode': 'rw'
                            }
                        },
                        user='1000:1000',  # Run as project user
                        detach=False,
                        remove=True,
                        stdout=False,
                        stderr=True
                    )
                    files_synced += 1

                except Exception as e:
                    logger.warning(f"[VOLUME] Failed to sync file {file.file_path}: {e}")

            logger.info(f"[VOLUME] ✅ Synced {files_synced}/{len(files)} files to {volume_name}")
            return files_synced

        except Exception as e:
            logger.error(f"[VOLUME] ❌ Failed to sync database to volume: {e}", exc_info=True)
            raise

    async def write_file_to_volume(
        self,
        volume_name: str,
        file_path: str,
        content: str
    ) -> bool:
        """
        Write a single file to a volume.

        Args:
            volume_name: Volume name
            file_path: Relative file path (e.g., "src/App.tsx")
            content: File content

        Returns:
            True if successful
        """
        try:
            # Escape for shell
            content_escaped = content.replace("'", "'\\''")
            file_path_escaped = file_path.replace("'", "'\\''")

            command = f"""
            mkdir -p "$(dirname '/project/{file_path_escaped}')" && \
            cat > '/project/{file_path_escaped}' << 'EOF'
{content}
EOF
            """

            await asyncio.to_thread(
                self.docker_client.containers.run,
                image=self.dev_server_image,
                command=["sh", "-c", command],
                volumes={
                    volume_name: {
                        'bind': '/project',
                        'mode': 'rw'
                    }
                },
                user='1000:1000',
                detach=False,
                remove=True,
                stdout=False,
                stderr=True
            )

            logger.debug(f"[VOLUME] Wrote file {file_path} to {volume_name}")
            return True

        except Exception as e:
            logger.error(f"[VOLUME] Failed to write file {file_path} to {volume_name}: {e}")
            return False

    async def read_file_from_volume(
        self,
        volume_name: str,
        file_path: str
    ) -> Optional[str]:
        """
        Read a file from a volume.

        Args:
            volume_name: Volume name
            file_path: Relative file path

        Returns:
            File content or None if not found
        """
        try:
            file_path_escaped = file_path.replace("'", "'\\''")
            command = f"cat '/project/{file_path_escaped}'"

            result = await asyncio.to_thread(
                self.docker_client.containers.run,
                image=self.dev_server_image,
                command=["sh", "-c", command],
                volumes={
                    volume_name: {
                        'bind': '/project',
                        'mode': 'ro'
                    }
                },
                user='1000:1000',
                detach=False,
                remove=True,
                stdout=True,
                stderr=False
            )

            content = result.decode('utf-8', errors='replace')
            return content

        except docker.errors.ContainerError:
            # File not found
            return None
        except Exception as e:
            logger.error(f"[VOLUME] Failed to read file {file_path} from {volume_name}: {e}")
            return None

    async def cleanup_orphaned_volumes(self) -> int:
        """
        Clean up volumes that are not associated with any project.

        Returns:
            Number of volumes cleaned up
        """
        logger.info("[VOLUME] Scanning for orphaned volumes...")

        try:
            # Get all Tesslate volumes
            volumes = await asyncio.to_thread(
                self.docker_client.volumes.list,
                filters={'label': 'com.tesslate.managed=true'}
            )

            cleaned = 0
            for volume in volumes:
                # Check if volume is in use
                try:
                    # Attempt to remove - will fail if in use
                    await asyncio.to_thread(volume.remove, force=False)
                    logger.info(f"[VOLUME] Cleaned up orphaned volume: {volume.name}")
                    cleaned += 1
                except docker.errors.APIError:
                    # Volume is in use, skip
                    continue

            logger.info(f"[VOLUME] ✅ Cleaned up {cleaned} orphaned volumes")
            return cleaned

        except Exception as e:
            logger.error(f"[VOLUME] Error during cleanup: {e}")
            return 0


# Singleton instance
_volume_manager: Optional[VolumeManager] = None


def get_volume_manager() -> VolumeManager:
    """Get the global VolumeManager instance."""
    global _volume_manager
    if _volume_manager is None:
        _volume_manager = VolumeManager()
    return _volume_manager
