"""
Volume Manager — thin client for the Volume Hub.

All intelligence lives in the Hub (storageless orchestrator that coordinates
nodes for volume lifecycle, cache placement, S3 sync).
The orchestrator only needs: create, delete, ensure_cached, trigger_sync.
No local state machine, no node selection, no S3 interaction.
"""

from __future__ import annotations

import logging

from ..config import get_settings
from .hub_client import HubClient

logger = logging.getLogger(__name__)


class VolumeManager:
    """Thin client — all volume intelligence is in the Hub."""

    def __init__(self) -> None:
        settings = get_settings()
        self._hub = HubClient(settings.volume_hub_address)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_volume(
        self, template: str | None = None, hint_node: str | None = None
    ) -> tuple[str, str]:
        """Create a volume on a node from template (or empty).

        If no hint_node is provided, the Hub picks the best available node.

        Returns:
            (volume_id, node_name)
        """
        volume_id, node_name = await self._hub.create_volume(template=template, hint_node=hint_node)
        logger.info(
            "[VOLUME] Created volume %s on node %s (template=%s)",
            volume_id,
            node_name,
            template,
        )
        return volume_id, node_name

    async def create_empty_volume(self, hint_node: str | None = None) -> tuple[str, str]:
        """Create an empty volume (no template).

        Convenience wrapper for callers that need a blank volume
        (e.g. file_placement.py).

        Returns:
            (volume_id, node_name)
        """
        return await self.create_volume(template=None, hint_node=hint_node)

    async def delete_volume(self, volume_id: str) -> None:
        """Delete from Hub + S3 + all node caches. Idempotent."""
        await self._hub.delete_volume(volume_id)
        logger.info("[VOLUME] Deleted volume %s", volume_id)

    async def ensure_cached(self, volume_id: str, hint_node: str | None = None) -> str:
        """Ensure volume is cached on a compute node. Returns node_name.

        Fast path: hint_node already has it (~0ms).
        Else: Hub coordinates peer transfer or S3 restore (~1-2s).
        """
        node_name = await self._hub.ensure_cached(volume_id, hint_node=hint_node)
        logger.info(
            "[VOLUME] Volume %s cached on node %s (hint=%s)",
            volume_id,
            node_name,
            hint_node,
        )
        return node_name

    async def trigger_sync(self, volume_id: str) -> None:
        """Trigger S3 sync on the node that owns the volume.

        The Hub looks up the owner node and tells it to sync.
        Non-blocking from the caller's perspective.
        """
        await self._hub.trigger_sync(volume_id)
        logger.info(
            "[VOLUME] Sync triggered: volume %s",
            volume_id,
        )

    async def create_service_volume(self, base_volume_id: str, service_name: str) -> str:
        """Create a service-specific subvolume on the Hub.

        Service volumes hold ephemeral service data (e.g. postgres data dir).
        Not tracked for S3 sync.

        Returns:
            service_volume_id (e.g. "vol-a1b2c3d4-postgres")
        """
        service_volume_id = await self._hub.create_service_volume(base_volume_id, service_name)
        logger.info(
            "[VOLUME] Created service volume %s for %s",
            service_volume_id,
            service_name,
        )
        return service_volume_id


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_instance: VolumeManager | None = None


def get_volume_manager() -> VolumeManager:
    """Get or create the global VolumeManager singleton."""
    global _instance
    if _instance is None:
        _instance = VolumeManager()
    return _instance
