"""
Volume Manager — thin client for the Volume Hub.

All intelligence lives in the Hub (storageless orchestrator that coordinates
nodes for volume lifecycle, cache placement, S3 sync).
The orchestrator only needs: create, delete, ensure_cached, trigger_sync,
resolve_volume, get_fileops_client.
No local state machine, no node selection, no S3 interaction.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..config import get_settings
from .hub_client import HubClient

if TYPE_CHECKING:
    from .fileops_client import FileOpsClient

logger = logging.getLogger(__name__)


class VolumeRestoringError(Exception):
    """Volume is being restored from S3 — retry shortly."""

    pass


class VolumeUnavailableError(Exception):
    """Volume restore failed or no CAS data exists."""

    pass


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

    async def fork_volume(self, source_volume_id: str) -> tuple[str, str]:
        """Fork a volume by snapshotting it on the same node (btrfs CoW clone).

        Returns: (new_volume_id, node_name)
        """
        volume_id, node_name = await self._hub.fork_volume(source_volume_id)
        logger.info("[VOLUME] Forked %s → %s on %s", source_volume_id, volume_id, node_name)
        return volume_id, node_name

    async def delete_volume(self, volume_id: str) -> None:
        """Delete from Hub + S3 + all node caches. Idempotent."""
        await self._hub.delete_volume(volume_id)
        logger.info("[VOLUME] Deleted volume %s", volume_id)

    async def ensure_cached(
        self,
        volume_id: str,
        candidate_nodes: list[str] | None = None,
        budget_cpu: int = 0,
        budget_mem: int = 0,
    ) -> str:
        """Ensure volume is cached on a live, schedulable compute node.

        The Hub validates candidates against its live node set, filters by
        resource headroom if budget is provided, and picks the best one.
        """
        node_name = await self._hub.ensure_cached(
            volume_id,
            candidate_nodes=candidate_nodes,
            budget_cpu=budget_cpu,
            budget_mem=budget_mem,
        )
        logger.info(
            "[VOLUME] Volume %s cached on node %s (candidates=%s)",
            volume_id,
            node_name,
            candidate_nodes,
        )
        return node_name

    async def transfer_ownership(self, volume_id: str, new_node: str) -> None:
        """Transfer volume ownership to a new node.

        Call after pods are healthy on the new node. Hub validates the
        volume is cached there before transferring.
        """
        await self._hub.transfer_ownership(volume_id, new_node)
        logger.info("[VOLUME] Ownership transferred: volume %s → node %s", volume_id, new_node)

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
    # Volume routing (Hub as single source of truth)
    # ------------------------------------------------------------------

    async def resolve_volume(self, volume_id: str) -> dict:
        """Non-blocking volume resolution via Hub.

        Returns dict with ``node_name``, ``fileops_address``,
        ``nodeops_address``, ``state`` (cached/restoring/unavailable).

        Raises:
            VolumeRestoringError: If volume is being restored from S3.
            VolumeUnavailableError: If restore failed or no CAS data.
        """
        resp = await self._hub.resolve_volume(volume_id)
        state = resp.get("state", "unavailable")

        if state == "cached":
            return resp

        if state == "restoring":
            raise VolumeRestoringError(volume_id)

        raise VolumeUnavailableError(volume_id)

    async def get_fileops_client(self, volume_id: str) -> FileOpsClient:
        """Get a ready-to-use FileOps client routed via the Hub.

        Raises:
            VolumeRestoringError: If volume is being restored from S3.
            VolumeUnavailableError: If restore failed or no CAS data.
        """
        from .fileops_client import FileOpsClient

        resp = await self.resolve_volume(volume_id)
        address = resp.get("fileops_address", "")
        if not address:
            raise VolumeUnavailableError(f"No fileops address for {volume_id}")
        return FileOpsClient(address)

    async def get_volume_node(self, volume_id: str) -> str:
        """Get the live node where a volume is cached.

        Quick Hub round-trip (~5ms). Used by T1 pods and builds to set
        node affinity so the pod lands on the volume's node.

        Raises:
            VolumeRestoringError: If volume is being restored from S3.
            VolumeUnavailableError: If restore failed or no CAS data.
        """
        resp = await self.resolve_volume(volume_id)
        return resp.get("node_name", "")


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
