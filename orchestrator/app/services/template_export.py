"""Template export service.

Packages project files into a tar.gz archive for sharing as a template.
Handles both Docker (filesystem) and Kubernetes (file-manager pod) modes.
"""

import io
import logging
import os
import tarfile
from asyncio import to_thread

from ..services.task_manager import Task

logger = logging.getLogger(__name__)

# Directories to exclude from template archives
EXCLUDE_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".next",
    "dist",
    "build",
    ".venv",
    ".cache",
    ".turbo",
    "venv",
    ".tsbuildinfo",
}

# File patterns to exclude
EXCLUDE_EXTENSIONS = {".pyc", ".pyo", ".so", ".dylib"}


def _should_exclude(path: str) -> bool:
    """Check if a path should be excluded from the archive."""
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part in EXCLUDE_DIRS:
            return True
    _, ext = os.path.splitext(path)
    return ext in EXCLUDE_EXTENSIONS


def _validate_tar_entry(member: tarfile.TarInfo) -> bool:
    """Validate a tar entry for path traversal and symlink attacks."""
    # Reject absolute paths and path traversal
    if member.name.startswith("/") or ".." in member.name.split("/"):
        return False
    # Reject symlinks and hardlinks (could point outside target)
    if member.issym() or member.islnk():
        return False
    # Reject device files and other special entries
    return member.isfile() or member.isdir()


async def export_project_to_archive(
    project_path: str,
    task: Task | None = None,
    max_size_mb: int = 100,
) -> bytes:
    """Package project files into a tar.gz archive.

    Args:
        project_path: Absolute path to the project directory.
        task: Optional Task for progress updates.
        max_size_mb: Maximum allowed uncompressed size in MB.

    Returns:
        Raw bytes of the tar.gz archive.

    Raises:
        ValueError: If the project exceeds the size limit.
        FileNotFoundError: If the project path doesn't exist.
    """
    if not os.path.exists(project_path):
        raise FileNotFoundError(f"Project path not found: {project_path}")

    if task:
        task.update_progress(10, 100, "Scanning project files...")

    # Calculate total size first
    total_size = 0
    file_count = 0
    max_size_bytes = max_size_mb * 1024 * 1024

    for root, dirs, files in os.walk(project_path):
        # Prune excluded directories in-place
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        rel_root = os.path.relpath(root, project_path)
        for file in files:
            rel_path = os.path.join(rel_root, file).replace("\\", "/")
            if rel_path.startswith("./"):
                rel_path = rel_path[2:]
            if _should_exclude(rel_path):
                continue

            full_path = os.path.join(root, file)
            try:
                file_size = os.path.getsize(full_path)
                total_size += file_size
                file_count += 1
            except OSError:
                continue

    if total_size > max_size_bytes:
        raise ValueError(
            f"Project size ({total_size / 1024 / 1024:.1f} MB) exceeds "
            f"the {max_size_mb} MB limit. Remove large files or directories first."
        )

    if task:
        task.update_progress(
            30, 100, f"Archiving {file_count} files ({total_size / 1024 / 1024:.1f} MB)..."
        )

    # Create the tar.gz archive in memory
    archive_bytes = await to_thread(_create_tar_archive, project_path, file_count, task)

    if task:
        task.update_progress(
            90, 100, f"Archive created ({len(archive_bytes) / 1024 / 1024:.1f} MB compressed)"
        )

    logger.info(
        f"[TEMPLATE] Exported {file_count} files, "
        f"{total_size / 1024:.0f} KB uncompressed -> "
        f"{len(archive_bytes) / 1024:.0f} KB compressed"
    )
    return archive_bytes


def _create_tar_archive(
    project_path: str,
    total_files: int,
    task: Task | None,
) -> bytes:
    """Create a tar.gz archive from the project directory (runs in thread)."""
    buf = io.BytesIO()
    files_processed = 0

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for root, dirs, files in os.walk(project_path):
            # Prune excluded directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            rel_root = os.path.relpath(root, project_path)
            for file in files:
                rel_path = os.path.join(rel_root, file).replace("\\", "/")
                if rel_path.startswith("./"):
                    rel_path = rel_path[2:]
                if _should_exclude(rel_path):
                    continue

                full_path = os.path.join(root, file)
                try:
                    tar.add(full_path, arcname=rel_path)
                    files_processed += 1

                    if task and files_processed % 50 == 0:
                        progress = 30 + int(60 * files_processed / max(total_files, 1))
                        task.update_progress(
                            min(progress, 89),
                            100,
                            f"Archiving files... ({files_processed}/{total_files})",
                        )
                except (OSError, PermissionError) as e:
                    logger.warning(f"[TEMPLATE] Skipping file {rel_path}: {e}")

    return buf.getvalue()


async def extract_archive_to_directory(
    archive_bytes: bytes,
    target_path: str,
) -> int:
    """Extract a template archive to a target directory.

    Args:
        archive_bytes: Raw tar.gz bytes.
        target_path: Directory to extract files into.

    Returns:
        Number of files extracted.

    Raises:
        ValueError: If the archive contains unsafe paths.
    """
    return await to_thread(_extract_tar_archive, archive_bytes, target_path)


def _extract_tar_archive(archive_bytes: bytes, target_path: str) -> int:
    """Extract tar.gz archive (runs in thread)."""
    os.makedirs(target_path, exist_ok=True)
    buf = io.BytesIO(archive_bytes)
    files_extracted = 0

    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        for member in tar.getmembers():
            if not _validate_tar_entry(member):
                logger.warning(f"[TEMPLATE] Skipping unsafe tar entry: {member.name}")
                continue
            tar.extract(member, path=target_path)
            files_extracted += 1

    logger.info(f"[TEMPLATE] Extracted {files_extracted} files to {target_path}")
    return files_extracted
