"""
Base Cache Manager

Pre-installs marketplace bases with dependencies on startup.
Solves WSL slowness by installing in Linux, then copying to user projects.
"""

import os
import asyncio
import logging
import shutil
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import MarketplaceBase
from ..database import AsyncSessionLocal
from ..config import get_settings

if TYPE_CHECKING:
    import docker

logger = logging.getLogger(__name__)


class BaseCacheManager:
    """Manages pre-installed marketplace base cache (Docker mode only)."""

    def __init__(self, cache_dir: str = "/app/base-cache"):
        self.cache_dir = Path(cache_dir)
        # Use Docker volume name for mounting to dev containers
        self.cache_volume_name = "tesslate-base-cache"
        self._initialized = False
        self._docker_client: Optional["docker.DockerClient"] = None
        self.dev_server_image = "tesslate-devserver:latest"

    @property
    def docker_client(self) -> "docker.DockerClient":
        """Lazy-initialize Docker client only when needed (Docker mode only)."""
        if self._docker_client is None:
            import docker
            self._docker_client = docker.from_env()
        return self._docker_client

    def _is_docker_mode(self) -> bool:
        """Check if running in Docker mode."""
        settings = get_settings()
        return settings.deployment_mode == "docker"

    async def initialize_cache(self) -> None:
        """
        Initialize base cache on startup.
        Clones and installs all marketplace bases if not already cached.

        Only runs in Docker mode - K8s mode uses S3 for file storage.
        """
        if self._initialized:
            logger.info("[BASE-CACHE] Already initialized, skipping")
            return

        # Skip cache initialization in K8s mode - no Docker socket available
        if not self._is_docker_mode():
            logger.info("[BASE-CACHE] Skipping cache initialization (Kubernetes mode)")
            self._initialized = True
            return

        logger.info("[BASE-CACHE] Initializing marketplace base cache...")

        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        async with AsyncSessionLocal() as db:
            # Get all active marketplace bases
            result = await db.execute(
                select(MarketplaceBase).where(MarketplaceBase.is_active == True)
            )
            bases = result.scalars().all()

            if not bases:
                logger.warning("[BASE-CACHE] No marketplace bases found in database")
                self._initialized = True
                return

            logger.info(f"[BASE-CACHE] Found {len(bases)} marketplace bases")

            # Process each base
            for base in bases:
                await self._process_base(base)

        self._initialized = True
        logger.info("[BASE-CACHE] ✅ Base cache initialization complete!")

    async def _process_base(self, base: MarketplaceBase) -> None:
        """
        Process a single marketplace base: clone and install dependencies.

        Args:
            base: MarketplaceBase model instance
        """
        base_path = self.cache_dir / base.slug

        # Check if already cached with valid content
        # A valid cache must have at least package.json or requirements.txt
        if base_path.exists():
            has_package_json = (base_path / "package.json").exists()
            has_requirements = (base_path / "requirements.txt").exists()
            has_go_mod = (base_path / "go.mod").exists()

            if has_package_json or has_requirements or has_go_mod:
                logger.info(f"[BASE-CACHE] ✓ {base.name} already cached at {base_path}")
                return
            else:
                # Directory exists but is invalid/empty - remove and re-clone
                logger.warning(f"[BASE-CACHE] ⚠ {base.name} cache is invalid/empty, re-cloning...")
                shutil.rmtree(base_path, ignore_errors=True)

        logger.info(f"[BASE-CACHE] 📦 Caching {base.name}...")

        try:
            # Clone repository
            await self._clone_repository(
                base.git_repo_url,
                base.default_branch,
                base_path
            )

            # Install dependencies
            await self._install_dependencies(base_path, base.name)

            logger.info(f"[BASE-CACHE] ✅ {base.name} cached successfully!")

        except Exception as e:
            logger.error(f"[BASE-CACHE] ❌ Failed to cache {base.name}: {e}", exc_info=True)
            # Clean up partial download
            if base_path.exists():
                shutil.rmtree(base_path, ignore_errors=True)

    async def _clone_repository(
        self,
        repo_url: str,
        branch: str,
        destination: Path
    ) -> None:
        """
        Clone a git repository.

        Args:
            repo_url: Git repository URL
            branch: Branch to clone
            destination: Destination path
        """
        logger.info(f"[BASE-CACHE]   Cloning {repo_url} (branch: {branch})...")

        # Use git clone with depth=1 for faster cloning
        process = await asyncio.create_subprocess_exec(
            'git', 'clone',
            '--depth', '1',
            '--branch', branch,
            '--single-branch',
            repo_url,
            str(destination),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Git clone failed: {error_msg}")

        logger.info(f"[BASE-CACHE]   ✓ Clone complete")

    async def _install_dependencies(self, base_path: Path, base_name: str) -> None:
        """
        Install dependencies for all languages found in the base.

        Args:
            base_path: Path to the cloned base
            base_name: Name of the base (for logging)
        """
        logger.info(f"[BASE-CACHE]   Installing dependencies for {base_name}...")

        # Check for multi-container structure (frontend/backend)
        has_frontend = (base_path / 'frontend').exists()
        has_backend = (base_path / 'backend').exists()

        if has_frontend or has_backend:
            # Multi-container base
            if has_frontend:
                await self._install_in_directory(base_path / 'frontend', 'Frontend')
            if has_backend:
                await self._install_in_directory(base_path / 'backend', 'Backend')
        else:
            # Single-container base
            await self._install_in_directory(base_path, base_name)

    async def _install_in_directory(self, directory: Path, label: str) -> None:
        """
        Install dependencies in a specific directory using a dev server container.

        Args:
            directory: Directory to install in
            label: Label for logging
        """
        # Detect which package managers are needed
        has_nodejs = (directory / 'package.json').exists()
        has_python = (directory / 'requirements.txt').exists()
        has_go = (directory / 'go.mod').exists()

        if not (has_nodejs or has_python or has_go):
            logger.info(f"[BASE-CACHE]     No dependencies to install ({label})")
            return

        # Build install command
        commands = []

        if has_nodejs:
            logger.info(f"[BASE-CACHE]     Installing Node.js deps ({label})...")
            commands.append("npm install --unsafe-perm")

        if has_python:
            logger.info(f"[BASE-CACHE]     Installing Python deps ({label})...")
            commands.extend([
                "python3 -m venv .venv",
                ".venv/bin/pip install --upgrade pip",
                ".venv/bin/pip install -r requirements.txt"
            ])

        if has_go:
            logger.info(f"[BASE-CACHE]     Downloading Go modules ({label})...")
            commands.append("go mod download")

        # Run installs in a temporary dev server container
        await self._run_in_container(directory, commands, label)

    async def _run_in_container(
        self,
        directory: Path,
        commands: List[str],
        label: str
    ) -> None:
        """
        Run commands in a temporary dev server container.

        Args:
            directory: Directory to mount
            commands: List of commands to run
            label: Label for logging
        """
        try:
            # Get the path inside the volume to mount
            # directory is like /app/base-cache/nextjs-15
            # We want to mount just that subdirectory from the volume
            relative_path = directory.relative_to(self.cache_dir)
            volume_subpath = f"{self.cache_volume_name}:/{relative_path}"

            logger.info(f"[BASE-CACHE]     Mounting volume: {self.cache_volume_name}/{relative_path}")

            # Run container and wait for completion
            # Note: Must override USER directive in devserver image (USER 1000) to run as root
            # User projects will copy these files and run as user 1000:1000
            result = await asyncio.to_thread(
                self.docker_client.containers.run,
                image=self.dev_server_image,
                command=["sh", "-c", " && ".join(commands)],
                volumes={
                    self.cache_volume_name: {
                        'bind': '/cache',
                        'mode': 'rw'
                    }
                },
                working_dir=f'/cache/{relative_path}',
                user='root',  # Override USER 1000 from Dockerfile
                detach=False,  # Wait for completion
                remove=True,   # Auto-cleanup after completion
                stdout=True,
                stderr=True
            )

            # Result contains combined stdout/stderr
            logs_str = result.decode('utf-8', errors='replace')
            logger.info(f"[BASE-CACHE]     ✓ Install complete ({label})")
            logger.debug(f"[BASE-CACHE]     Logs:\n{logs_str}")

        except docker.errors.ContainerError as e:
            error_msg = e.stderr.decode('utf-8', errors='replace') if e.stderr else str(e)
            logger.warning(f"[BASE-CACHE]     ⚠ Install failed ({label}): {error_msg[:500]}")

        except Exception as e:
            logger.error(f"[BASE-CACHE]     ❌ Container execution failed ({label}): {e}")

    async def get_base_path(self, base_slug: str) -> Optional[Path]:
        """
        Get the cached path for a marketplace base.

        Args:
            base_slug: Slug of the marketplace base

        Returns:
            Path to cached base, or None if not found (always None in K8s mode)
        """
        # In K8s mode, cache is not used - files come from S3
        if not self._is_docker_mode():
            return None

        base_path = self.cache_dir / base_slug
        if base_path.exists():
            return base_path
        return None

    def is_base_cached(self, base_slug: str) -> bool:
        """
        Check if a base is already cached.

        Args:
            base_slug: Slug of the marketplace base

        Returns:
            True if cached, False otherwise (always False in K8s mode)
        """
        # In K8s mode, cache is not used - files come from S3
        if not self._is_docker_mode():
            return False

        base_path = self.cache_dir / base_slug
        return base_path.exists()


# Singleton instance
_base_cache_manager: Optional[BaseCacheManager] = None


def get_base_cache_manager() -> BaseCacheManager:
    """Get the singleton base cache manager instance."""
    global _base_cache_manager

    if _base_cache_manager is None:
        _base_cache_manager = BaseCacheManager()

    return _base_cache_manager
