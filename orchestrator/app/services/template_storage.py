"""Template archive storage service.

Handles storing, retrieving, and deleting tar.gz template archives
on the local filesystem at the configured template_storage_path.
"""

import logging
import os
from asyncio import to_thread
from uuid import UUID

from ..config import get_settings

logger = logging.getLogger(__name__)


class TemplateStorageService:
    """Manages template archive files on the filesystem."""

    def __init__(self):
        self.settings = get_settings()

    @property
    def base_path(self) -> str:
        return self.settings.template_storage_path

    async def store_archive(self, user_id: UUID, template_id: UUID, archive_bytes: bytes) -> str:
        """Store a template archive and return its relative path.

        Args:
            user_id: The owner's user ID (used for directory partitioning).
            template_id: The MarketplaceBase ID for this template.
            archive_bytes: The raw tar.gz bytes.

        Returns:
            Relative path like "templates/{user_id}/{template_id}.tar.gz"
        """
        user_dir = os.path.join(self.base_path, str(user_id))
        await to_thread(os.makedirs, user_dir, exist_ok=True)

        filename = f"{template_id}.tar.gz"
        full_path = os.path.join(user_dir, filename)

        await to_thread(self._write_file, full_path, archive_bytes)

        relative_path = f"templates/{user_id}/{filename}"
        logger.info(f"[TEMPLATE] Stored archive ({len(archive_bytes)} bytes) at {relative_path}")
        return relative_path

    def _resolve_archive_path(self, archive_path: str) -> str:
        """Resolve an archive_path to a full filesystem path, with traversal validation."""
        # archive_path = "templates/{user_id}/{id}.tar.gz"
        # base_path = "/templates"
        # full = "/templates/{user_id}/{id}.tar.gz"
        parts = archive_path.split("/", 1)  # ["templates", "{user_id}/{id}.tar.gz"]
        if len(parts) == 2:
            full_path = os.path.join(self.base_path, parts[1])
        else:
            full_path = os.path.join(self.base_path, archive_path)

        # Validate resolved path stays within base_path
        real_path = os.path.realpath(full_path)
        real_base = os.path.realpath(self.base_path)
        if not real_path.startswith(real_base + os.sep) and real_path != real_base:
            raise ValueError(f"Invalid archive path: {archive_path}")

        return full_path

    async def retrieve_archive(self, archive_path: str) -> bytes:
        """Read an archive from the filesystem.

        Args:
            archive_path: Relative path like "templates/{user_id}/{id}.tar.gz"

        Returns:
            Raw bytes of the archive.

        Raises:
            FileNotFoundError: If the archive doesn't exist.
        """
        full_path = self._resolve_archive_path(archive_path)

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Template archive not found: {archive_path}")

        return await to_thread(self._read_file, full_path)

    async def delete_archive(self, archive_path: str) -> None:
        """Delete an archive file from the filesystem.

        Args:
            archive_path: Relative path like "templates/{user_id}/{id}.tar.gz"
        """
        full_path = self._resolve_archive_path(archive_path)

        if os.path.exists(full_path):
            await to_thread(os.remove, full_path)
            logger.info(f"[TEMPLATE] Deleted archive: {archive_path}")
        else:
            logger.warning(f"[TEMPLATE] Archive not found for deletion: {archive_path}")

    @staticmethod
    def _write_file(path: str, data: bytes) -> None:
        with open(path, "wb") as f:
            f.write(data)

    @staticmethod
    def _read_file(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()


def get_template_storage() -> TemplateStorageService:
    """Get a TemplateStorageService instance."""
    return TemplateStorageService()
