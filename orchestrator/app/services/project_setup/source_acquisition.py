import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from uuid import UUID

logger = logging.getLogger(__name__)

SKIP_DIRS = frozenset({".git", "node_modules", ".next", "__pycache__", ".venv", "venv", "dist", "build"})


@dataclass
class SourceSpec:
    """Describes where to get source files."""
    kind: str  # "template_snapshot", "cache", "git_clone", "archive"

    # For template_snapshot
    template_slug: str | None = None

    # For cache
    cache_path: str | None = None

    # For git_clone
    git_url: str | None = None
    git_branch: str = "main"

    # For archive
    archive_path: str | None = None

    # Common
    base_slug: str | None = None
    base_id: UUID | None = None


@dataclass
class AcquiredSource:
    """Result of source acquisition."""
    local_path: str | None = None  # Temp dir path for git_clone/archive, cache path for cache
    volume_id: str | None = None   # For template_snapshot (v2)
    node_name: str | None = None   # For template_snapshot (v2)
    _temp_dirs: list[str] = field(default_factory=list)  # Dirs to cleanup

    async def cleanup(self):
        """Clean up temporary directories."""
        for d in self._temp_dirs:
            try:
                await asyncio.to_thread(shutil.rmtree, d, ignore_errors=True)
                logger.info(f"[SOURCE] Cleaned up temp dir: {d}")
            except Exception as e:
                logger.warning(f"[SOURCE] Failed to clean temp dir {d}: {e}")


async def acquire_source(spec: SourceSpec, task=None) -> AcquiredSource:
    """
    Acquire source files based on spec.kind.

    Returns AcquiredSource with either local_path or volume_id set.
    Caller MUST call source.cleanup() when done.
    """
    if spec.kind == "template_snapshot":
        return await _acquire_template_snapshot(spec, task)
    elif spec.kind == "cache":
        return await _acquire_from_cache(spec, task)
    elif spec.kind == "git_clone":
        return await _acquire_from_git(spec, task)
    elif spec.kind == "archive":
        return await _acquire_from_archive(spec, task)
    else:
        raise ValueError(f"Unknown source kind: {spec.kind}")


async def _acquire_template_snapshot(spec: SourceSpec, task) -> AcquiredSource:
    from ...services.volume_manager import get_volume_manager

    if task:
        task.update_progress(20, 100, "Creating project from template snapshot...")

    vm = get_volume_manager()
    volume_id, node_name = await vm.create_volume(template=spec.template_slug)  # type: ignore[arg-type]  # validated by caller
    logger.info(f"[SOURCE] Created volume {volume_id} from template {spec.template_slug}")

    return AcquiredSource(volume_id=volume_id, node_name=node_name)


async def _acquire_from_cache(spec: SourceSpec, task) -> AcquiredSource:
    if task:
        task.update_progress(20, 100, "Loading pre-installed base from cache...")

    if not spec.cache_path or not os.path.exists(spec.cache_path):
        raise FileNotFoundError(f"Cache path not found: {spec.cache_path}")

    logger.info(f"[SOURCE] Using cached base at {spec.cache_path}")
    return AcquiredSource(local_path=spec.cache_path)


async def _acquire_from_git(spec: SourceSpec, task) -> AcquiredSource:
    if not spec.git_url:
        raise ValueError("git_url is required for git_clone source")

    if task:
        task.update_progress(20, 100, "Cloning repository...")

    temp_dir = tempfile.mkdtemp(prefix="tesslate-clone-")

    try:
        clone_cmd = ["git", "clone", "--depth=1"]
        if spec.git_branch:
            clone_cmd.extend(["--branch", spec.git_branch])
        clone_cmd.extend([spec.git_url, temp_dir])

        logger.info(f"[SOURCE] Cloning {spec.git_url} to {temp_dir}")
        process = await asyncio.create_subprocess_exec(
            *clone_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=300)

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Git clone failed: {error_msg}")

        # Remove .git directory
        git_dir = os.path.join(temp_dir, ".git")
        if os.path.exists(git_dir):
            await asyncio.to_thread(shutil.rmtree, git_dir, ignore_errors=True)

        logger.info(f"[SOURCE] Successfully cloned to {temp_dir}")

        if task:
            task.update_progress(50, 100, "Repository cloned")

        return AcquiredSource(local_path=temp_dir, _temp_dirs=[temp_dir])
    except Exception:
        # Clean up on failure
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


async def _acquire_from_archive(spec: SourceSpec, task) -> AcquiredSource:
    from ...services.template_storage import get_template_storage
    from ...services.template_export import extract_archive_to_directory

    if not spec.archive_path:
        raise ValueError("archive_path is required for archive source")

    if task:
        task.update_progress(20, 100, "Retrieving template archive...")

    storage = get_template_storage()
    archive_bytes = await storage.retrieve_archive(spec.archive_path)

    if task:
        task.update_progress(40, 100, "Extracting template files...")

    temp_dir = tempfile.mkdtemp(prefix="tesslate-archive-")
    try:
        await extract_archive_to_directory(archive_bytes, temp_dir)
        logger.info(f"[SOURCE] Extracted archive to {temp_dir}")
        return AcquiredSource(local_path=temp_dir, _temp_dirs=[temp_dir])
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
