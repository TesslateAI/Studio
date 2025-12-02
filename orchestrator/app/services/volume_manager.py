"""
Volume Manager Service - Shared Projects Architecture

Manages project files in the shared tesslate-projects-data volume.
The orchestrator has this volume mounted at /projects, enabling direct
filesystem access to all project files without temp containers.

Architecture:
- Shared volume: tesslate-projects-data mounted at /projects
- Each project: /projects/{project-slug}/
- Orchestrator: Direct read/write access
- Project containers: Mount same volume, workdir=/projects/{slug}
- Database: Source of truth for file metadata
- Base cache: /app/base-cache/{base-slug}/ (pre-installed marketplace bases)
"""

import os
import asyncio
import logging
import shutil
import aiofiles
import aiofiles.os
from pathlib import Path
from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)

# Shared projects volume mount point inside orchestrator
PROJECTS_BASE_PATH = Path("/projects")

# Binary file extensions to skip when reading content
BINARY_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'ico', 'svg', 'webp', 'bmp',
    'woff', 'woff2', 'ttf', 'eot', 'otf',
    'mp3', 'mp4', 'wav', 'ogg', 'webm', 'avi', 'mov',
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'zip', 'tar', 'gz', 'rar', '7z',
    'bin', 'exe', 'dll', 'so', 'dylib',
    'class', 'jar', 'pyc', 'pyo',
    'lock', 'map'
}

# Directories to exclude from file listings
EXCLUDED_DIRS = {
    'node_modules', '.git', '__pycache__', '.next', 'dist', 'build',
    '.venv', 'venv', '.cache', '.turbo', 'coverage', '.nyc_output'
}

# Files to exclude from listings
EXCLUDED_FILES = {'.DS_Store', 'Thumbs.db', '.env.local'}


class VolumeManager:
    """
    Manages project files in the shared projects volume.

    With the new architecture, all file operations use direct filesystem
    access at /projects/{project-slug}/ - no temp containers needed.
    """

    def __init__(self):
        self.projects_path = PROJECTS_BASE_PATH
        # Ensure projects directory exists
        self.projects_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[VOLUME] Volume manager initialized with shared projects at {self.projects_path}")

    def get_project_path(self, project_slug: str) -> Path:
        """Get the filesystem path for a project."""
        return self.projects_path / project_slug

    async def ensure_project_directory(self, project_slug: str) -> Path:
        """
        Ensure the project directory exists.

        Args:
            project_slug: Project slug

        Returns:
            Path to the project directory
        """
        project_path = self.get_project_path(project_slug)
        await aiofiles.os.makedirs(project_path, exist_ok=True)
        logger.debug(f"[VOLUME] Ensured project directory: {project_path}")
        return project_path

    async def delete_project_directory(self, project_slug: str) -> bool:
        """
        Delete a project's directory and all its contents.

        Args:
            project_slug: Project slug

        Returns:
            True if deleted, False if not found
        """
        project_path = self.get_project_path(project_slug)

        if not project_path.exists():
            logger.warning(f"[VOLUME] Project directory not found: {project_slug}")
            return False

        try:
            # Use shutil.rmtree in thread pool (blocking operation)
            await asyncio.to_thread(shutil.rmtree, project_path)
            logger.info(f"[VOLUME] ✅ Deleted project directory: {project_slug}")
            return True
        except Exception as e:
            logger.error(f"[VOLUME] ❌ Failed to delete project directory {project_slug}: {e}")
            raise

    async def rename_directory(
        self,
        project_slug: str,
        old_name: str,
        new_name: str
    ) -> bool:
        """
        Rename a subdirectory within a project.

        Args:
            project_slug: Project slug
            old_name: Current directory name
            new_name: New directory name

        Returns:
            True if renamed successfully
        """
        project_path = self.get_project_path(project_slug)
        old_path = project_path / old_name
        new_path = project_path / new_name

        if not old_path.exists():
            logger.warning(f"[VOLUME] Source directory not found: {old_path}")
            raise FileNotFoundError(f"Directory '{old_name}' not found in project")

        if new_path.exists():
            logger.warning(f"[VOLUME] Target directory already exists: {new_path}")
            raise FileExistsError(f"Directory '{new_name}' already exists in project")

        try:
            # Use shutil.move in thread pool (blocking operation)
            await asyncio.to_thread(shutil.move, str(old_path), str(new_path))
            logger.info(f"[VOLUME] ✅ Renamed directory: {old_name} -> {new_name}")
            return True
        except Exception as e:
            logger.error(f"[VOLUME] ❌ Failed to rename directory {old_name} -> {new_name}: {e}")
            raise

    async def copy_base_to_project(
        self,
        base_slug: str,
        project_slug: str,
        exclude_patterns: Optional[List[str]] = None,
        target_subdir: Optional[str] = None
    ) -> None:
        """
        Copy a base from cache to a project directory.

        Args:
            base_slug: Slug of the marketplace base
            project_slug: Target project slug
            exclude_patterns: Patterns to exclude (e.g., '.git', '__pycache__')
            target_subdir: Optional subdirectory within project to copy to
                          (for multi-container projects with separate dirs)
        """
        if exclude_patterns is None:
            # Don't exclude node_modules - we want pre-installed deps!
            exclude_patterns = ['.git', '__pycache__', '*.pyc', '.DS_Store']

        target_display = f"{project_slug}/{target_subdir}" if target_subdir else project_slug
        logger.info(f"[VOLUME] Copying base {base_slug} to project {target_display}")

        # Validate base cache exists and has some content
        cache_path = Path(f"/app/base-cache/{base_slug}")
        if not cache_path.exists():
            raise RuntimeError(f"Base cache not found: {cache_path}. Run base cache initialization first.")

        # Just check directory isn't empty - don't validate specific files
        # This supports any framework/language without hardcoding file patterns
        has_content = any(cache_path.iterdir())
        if not has_content:
            raise RuntimeError(f"Base cache {base_slug} is empty.")

        # Ensure project directory exists
        project_path = await self.ensure_project_directory(project_slug)

        # Determine actual destination path
        # If target_subdir is specified, copy to that subdirectory within the project
        if target_subdir:
            destination_path = project_path / target_subdir
            await aiofiles.os.makedirs(destination_path, exist_ok=True)
        else:
            destination_path = project_path

        try:
            # Define ignore function for shutil.copytree
            def ignore_patterns(directory, files):
                ignored = []
                for f in files:
                    for pattern in exclude_patterns:
                        if pattern.startswith('*.'):
                            # Extension pattern (e.g., *.pyc)
                            if f.endswith(pattern[1:]):
                                ignored.append(f)
                                break
                        elif f == pattern:
                            # Exact match
                            ignored.append(f)
                            break
                return ignored

            # Copy using shutil.copytree (in thread pool)
            # dirs_exist_ok=True allows overwriting existing files
            await asyncio.to_thread(
                shutil.copytree,
                cache_path,
                destination_path,
                ignore=ignore_patterns,
                dirs_exist_ok=True
            )

            # Fix permissions so container user (1000:1000) can write
            # This runs chown recursively in a thread
            await asyncio.to_thread(self._fix_permissions, destination_path)

            logger.info(f"[VOLUME] ✅ Copied base {base_slug} to {target_display}")

        except Exception as e:
            logger.error(f"[VOLUME] ❌ Failed to copy base {base_slug}: {e}", exc_info=True)
            raise

    def _fix_permissions(self, path: Path) -> None:
        """Fix permissions for container user (uid 1000, gid 1000)."""
        try:
            import pwd
            import grp
            # Try to chown to uid 1000, gid 1000
            for root, dirs, files in os.walk(path):
                os.chown(root, 1000, 1000)
                for d in dirs:
                    os.chown(os.path.join(root, d), 1000, 1000)
                for f in files:
                    os.chown(os.path.join(root, f), 1000, 1000)
        except (ImportError, PermissionError, KeyError):
            # On Windows or if permissions fail, skip
            pass

    async def write_file(
        self,
        project_slug: str,
        file_path: str,
        content: str,
        subdir: Optional[str] = None
    ) -> bool:
        """
        Write a file to a project directory.

        Args:
            project_slug: Project slug
            file_path: Relative file path (e.g., "src/App.tsx")
            content: File content
            subdir: Optional subdirectory (e.g., "frontend") - file_path is relative to this

        Returns:
            True if successful
        """
        try:
            project_path = self.get_project_path(project_slug)
            if subdir and subdir != '.':
                project_path = project_path / subdir
            full_path = project_path / file_path

            # Create parent directories
            await aiofiles.os.makedirs(full_path.parent, exist_ok=True)

            # Write file
            async with aiofiles.open(full_path, 'w', encoding='utf-8') as f:
                await f.write(content)

            logger.debug(f"[VOLUME] Wrote file {file_path} to project {project_slug}")
            return True

        except Exception as e:
            logger.error(f"[VOLUME] Failed to write file {file_path} to {project_slug}: {e}")
            return False

    async def read_file(
        self,
        project_slug: str,
        file_path: str,
        subdir: Optional[str] = None
    ) -> Optional[str]:
        """
        Read a file from a project directory.

        Args:
            project_slug: Project slug
            file_path: Relative file path
            subdir: Optional subdirectory (e.g., "frontend") - file_path is relative to this

        Returns:
            File content or None if not found
        """
        try:
            project_path = self.get_project_path(project_slug)
            if subdir and subdir != '.':
                project_path = project_path / subdir
            full_path = project_path / file_path

            if not full_path.exists():
                return None

            async with aiofiles.open(full_path, 'r', encoding='utf-8') as f:
                content = await f.read()

            return content

        except Exception as e:
            logger.error(f"[VOLUME] Failed to read file {file_path} from {project_slug}: {e}")
            return None

    async def delete_file(
        self,
        project_slug: str,
        file_path: str,
        subdir: Optional[str] = None
    ) -> bool:
        """
        Delete a file from a project directory.

        Args:
            project_slug: Project slug
            file_path: Relative file path
            subdir: Optional subdirectory (e.g., "frontend") - file_path is relative to this

        Returns:
            True if deleted, False if not found
        """
        try:
            project_path = self.get_project_path(project_slug)
            if subdir and subdir != '.':
                project_path = project_path / subdir
            full_path = project_path / file_path

            if not full_path.exists():
                return False

            await aiofiles.os.remove(full_path)
            logger.debug(f"[VOLUME] Deleted file {file_path} from project {project_slug}")
            return True

        except Exception as e:
            logger.error(f"[VOLUME] Failed to delete file {file_path} from {project_slug}: {e}")
            return False

    async def list_files(
        self,
        project_slug: str,
        max_files: int = 500
    ) -> List[Dict[str, Any]]:
        """
        List all files in a project (excluding node_modules, .git, etc.).

        Args:
            project_slug: Project slug
            max_files: Maximum number of files to return

        Returns:
            List of file info dicts with 'path' and 'type' keys
        """
        project_path = self.get_project_path(project_slug)

        if not project_path.exists():
            logger.warning(f"[VOLUME] Project directory not found: {project_slug}")
            return []

        files = []
        count = 0

        try:
            for root, dirs, filenames in os.walk(project_path):
                # Modify dirs in-place to skip excluded directories
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

                for filename in filenames:
                    if count >= max_files:
                        break

                    if filename in EXCLUDED_FILES:
                        continue

                    full_path = Path(root) / filename
                    rel_path = full_path.relative_to(project_path)

                    files.append({
                        'path': str(rel_path),
                        'type': 'file'
                    })
                    count += 1

                if count >= max_files:
                    break

            logger.info(f"[VOLUME] Found {len(files)} files in project {project_slug}")
            return files

        except Exception as e:
            logger.error(f"[VOLUME] Failed to list files in {project_slug}: {e}")
            return []

    async def get_files_with_content(
        self,
        project_slug: str,
        max_files: int = 200,
        max_file_size: int = 100000,  # 100KB per file
        subdir: Optional[str] = None  # Container subdirectory (e.g., "frontend")
    ) -> List[Dict[str, Any]]:
        """
        Get all files in a project with their content.

        This is used by the Monaco editor to display the file tree with content.
        Uses direct filesystem access - no temp containers needed.

        Args:
            project_slug: Project slug
            max_files: Maximum number of files to return
            max_file_size: Maximum size per file (bytes)
            subdir: Optional subdirectory to read from (files appear as root-level)

        Returns:
            List of dicts with 'file_path' and 'content' keys
        """
        project_path = self.get_project_path(project_slug)

        # If subdir specified, use that as the root for file listing
        if subdir and subdir != '.':
            project_path = project_path / subdir

        if not project_path.exists():
            logger.warning(f"[VOLUME] Project directory not found: {project_slug}/{subdir or ''}")
            return []

        files_with_content = []
        count = 0

        try:
            for root, dirs, filenames in os.walk(project_path):
                # Modify dirs in-place to skip excluded directories
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

                for filename in filenames:
                    if count >= max_files:
                        break

                    if filename in EXCLUDED_FILES:
                        continue

                    # Skip binary files
                    ext = filename.split('.')[-1].lower() if '.' in filename else ''
                    if ext in BINARY_EXTENSIONS:
                        continue

                    full_path = Path(root) / filename
                    rel_path = full_path.relative_to(project_path)

                    # Check file size
                    try:
                        file_size = full_path.stat().st_size
                        if file_size > max_file_size:
                            continue
                    except OSError:
                        continue

                    # Read content
                    try:
                        async with aiofiles.open(full_path, 'r', encoding='utf-8') as f:
                            content = await f.read()

                        files_with_content.append({
                            'file_path': str(rel_path),
                            'content': content
                        })
                        count += 1

                    except (UnicodeDecodeError, IOError):
                        # Skip files that can't be read as text
                        continue

                if count >= max_files:
                    break

            logger.info(f"[VOLUME] Loaded {len(files_with_content)} files with content from project {project_slug}")
            return files_with_content

        except Exception as e:
            logger.error(f"[VOLUME] Failed to get files with content from {project_slug}: {e}")
            return []

    async def sync_db_to_project(
        self,
        project_id: UUID,
        project_slug: str,
        db: AsyncSession
    ) -> int:
        """
        Sync project files from database to project directory.

        Args:
            project_id: Project ID
            project_slug: Project slug
            db: Database session

        Returns:
            Number of files synced
        """
        from ..models import ProjectFile

        logger.info(f"[VOLUME] Syncing database files to project {project_slug}")

        try:
            # Get all files for project from database
            result = await db.execute(
                select(ProjectFile).where(ProjectFile.project_id == project_id)
            )
            files = result.scalars().all()

            if not files:
                logger.warning(f"[VOLUME] No files found in database for project {project_id}")
                return 0

            # Ensure project directory exists
            await self.ensure_project_directory(project_slug)

            files_synced = 0
            for file in files:
                try:
                    success = await self.write_file(project_slug, file.file_path, file.content)
                    if success:
                        files_synced += 1
                except Exception as e:
                    logger.warning(f"[VOLUME] Failed to sync file {file.file_path}: {e}")

            logger.info(f"[VOLUME] ✅ Synced {files_synced}/{len(files)} files to project {project_slug}")
            return files_synced

        except Exception as e:
            logger.error(f"[VOLUME] ❌ Failed to sync database to project: {e}", exc_info=True)
            raise

    async def project_exists(self, project_slug: str) -> bool:
        """Check if a project directory exists."""
        project_path = self.get_project_path(project_slug)
        return project_path.exists() and project_path.is_dir()

    async def project_has_files(self, project_slug: str, subdir: Optional[str] = None) -> bool:
        """
        Check if a project (or subdirectory) has any files.

        Args:
            project_slug: Project slug
            subdir: Optional subdirectory within the project to check

        Returns:
            True if the directory has files
        """
        project_path = self.get_project_path(project_slug)
        if subdir:
            project_path = project_path / subdir

        if not project_path.exists():
            return False

        # Check for any files (excluding hidden and excluded dirs)
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            if any(f for f in files if not f.startswith('.')):
                return True

        return False

    # =========================================================================
    # Legacy compatibility methods (for gradual migration)
    # These wrap the new methods with the old interface
    # =========================================================================

    async def create_project_volume(
        self,
        volume_name: str,
        labels: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Legacy compatibility: Create project directory.
        Volume name is treated as project slug.
        """
        # Extract project slug from volume name (e.g., "my-project-abc123")
        project_slug = volume_name
        await self.ensure_project_directory(project_slug)
        logger.info(f"[VOLUME] Created project directory for: {project_slug}")
        return project_slug

    async def delete_volume(self, volume_name: str, force: bool = False) -> bool:
        """Legacy compatibility: Delete project directory."""
        return await self.delete_project_directory(volume_name)

    async def volume_exists(self, volume_name: str) -> bool:
        """Legacy compatibility: Check if project directory exists."""
        return await self.project_exists(volume_name)

    async def copy_base_to_volume(
        self,
        base_slug: str,
        volume_name: str,
        exclude_patterns: Optional[List[str]] = None
    ) -> None:
        """Legacy compatibility: Copy base to project directory."""
        await self.copy_base_to_project(base_slug, volume_name, exclude_patterns)

    async def write_file_to_volume(
        self,
        volume_name: str,
        file_path: str,
        content: str
    ) -> bool:
        """Legacy compatibility: Write file to project directory."""
        return await self.write_file(volume_name, file_path, content)

    async def read_file_from_volume(
        self,
        volume_name: str,
        file_path: str
    ) -> Optional[str]:
        """Legacy compatibility: Read file from project directory."""
        return await self.read_file(volume_name, file_path)

    async def list_files_in_volume(
        self,
        volume_name: str,
        max_files: int = 500
    ) -> List[Dict[str, Any]]:
        """Legacy compatibility: List files in project directory."""
        return await self.list_files(volume_name, max_files)

    async def sync_db_to_volume(
        self,
        project_id: UUID,
        volume_name: str,
        db: AsyncSession
    ) -> int:
        """Legacy compatibility: Sync DB to project directory."""
        return await self.sync_db_to_project(project_id, volume_name, db)


# Singleton instance
_volume_manager: Optional[VolumeManager] = None


def get_volume_manager() -> VolumeManager:
    """Get the global VolumeManager instance."""
    global _volume_manager
    if _volume_manager is None:
        _volume_manager = VolumeManager()
    return _volume_manager
