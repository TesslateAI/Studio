"""
Volume Manager — high-level lifecycle management for btrfs subvolumes.

Composes NodeOpsClient and NodeDiscovery to handle volume creation (from
template or empty), service volume creation, deletion, restore from S3,
and sync triggers.  No database access — callers update Project model fields.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

import grpc
import grpc.aio

from .node_discovery import NodeDiscovery
from .nodeops_client import NodeOpsClient

logger = logging.getLogger(__name__)


def _generate_volume_id() -> str:
    return f"vol-{uuid4().hex[:12]}"


class VolumeManager:
    """Manages the full lifecycle of btrfs volumes via the CSI NodeOps gRPC service."""

    def __init__(self) -> None:
        self._discovery = NodeDiscovery()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_volume(self, template: str) -> tuple[str, str]:
        """Create a volume from a template snapshot.

        Selects the best node, ensures the template exists (downloading from
        S3 if necessary), then creates an instant btrfs reflink snapshot.

        Returns:
            (volume_id, node_name)
        """
        volume_id = _generate_volume_id()
        tried_nodes: set[str] = set()

        while True:
            node_name = await self._select_target_node(exclude=tried_nodes)
            address = await self._discovery.get_nodeops_address(node_name)

            try:
                await self._retry_on_node(
                    lambda: self._do_create_from_template(
                        address, volume_id, template
                    ),
                    node_name,
                )
                logger.info(
                    "[VOLUME] Created volume %s from template '%s' on node %s",
                    volume_id,
                    template,
                    node_name,
                )
                return volume_id, node_name

            except _AllRetriesExhausted:
                tried_nodes.add(node_name)
                logger.warning(
                    "[VOLUME] All retries exhausted on node %s for create_volume, trying another node",
                    node_name,
                )
                continue

    async def create_empty_volume(
        self, node_name: str | None = None
    ) -> tuple[str, str]:
        """Create an empty btrfs subvolume.

        Args:
            node_name: Pin to a specific node, or None to auto-select.

        Returns:
            (volume_id, node_name)
        """
        volume_id = _generate_volume_id()

        if node_name is None:
            node_name = await self._select_target_node()

        address = await self._discovery.get_nodeops_address(node_name)
        async with NodeOpsClient(address) as client:
            await client.create_subvolume(f"volumes/{volume_id}")
            await client.track_volume(volume_id)

        logger.info(
            "[VOLUME] Created empty volume %s on node %s", volume_id, node_name
        )
        return volume_id, node_name

    async def create_service_volume(
        self, base_volume_id: str, service_name: str, node_name: str
    ) -> str:
        """Create a service-specific subvolume (e.g. postgres data dir).

        Service volumes are *not* tracked for S3 sync — they hold
        ephemeral service data that doesn't need persistence.

        Returns:
            service_volume_id (e.g. "vol-a1b2c3d4-postgres")
        """
        service_volume_id = f"{base_volume_id}-{service_name}"

        address = await self._discovery.get_nodeops_address(node_name)
        async with NodeOpsClient(address) as client:
            await client.create_subvolume(f"volumes/{service_volume_id}")

        logger.info(
            "[VOLUME] Created service volume %s for %s on node %s",
            service_volume_id,
            service_name,
            node_name,
        )
        return service_volume_id

    async def delete_volume(self, volume_id: str, node_name: str) -> None:
        """Delete a volume and stop S3 sync tracking.

        Idempotent — silently succeeds if the volume is already gone.
        """
        address = await self._discovery.get_nodeops_address(node_name)
        async with NodeOpsClient(address) as client:
            try:
                await client.untrack_volume(volume_id)
            except grpc.aio.AioRpcError as e:
                if e.code() != grpc.StatusCode.NOT_FOUND:
                    raise
                logger.warning(
                    "[VOLUME] Volume %s already untracked (NOT_FOUND), continuing delete",
                    volume_id,
                )

            try:
                await client.delete_subvolume(f"volumes/{volume_id}")
            except grpc.aio.AioRpcError as e:
                if e.code() != grpc.StatusCode.NOT_FOUND:
                    raise
                logger.warning(
                    "[VOLUME] Volume %s already deleted (NOT_FOUND)", volume_id
                )
                return

        logger.info(
            "[VOLUME] Deleted volume %s from node %s", volume_id, node_name
        )

    async def restore_volume(self, volume_id: str) -> str:
        """Restore a volume from S3 onto the best available node.

        Returns:
            node_name where the volume was restored.
        """
        tried_nodes: set[str] = set()

        while True:
            node_name = await self._select_target_node(exclude=tried_nodes)
            address = await self._discovery.get_nodeops_address(node_name)

            try:
                await self._retry_on_node(
                    lambda: self._do_restore(address, volume_id),
                    node_name,
                )
                logger.info(
                    "[VOLUME] Restored volume %s on node %s",
                    volume_id,
                    node_name,
                )
                return node_name

            except _AllRetriesExhausted:
                tried_nodes.add(node_name)
                logger.warning(
                    "[VOLUME] All retries exhausted on node %s for restore_volume, trying another node",
                    node_name,
                )
                continue

    async def trigger_sync(self, volume_id: str, node_name: str) -> None:
        """Trigger an S3 sync for a volume before eviction or scale-to-zero.

        Calls SyncVolume RPC if the CSI driver supports it; otherwise logs a
        warning and returns (the background sync daemon will handle it).
        """
        address = await self._discovery.get_nodeops_address(node_name)
        try:
            async with NodeOpsClient(address) as client:
                await client.sync_volume(volume_id)

            logger.info(
                "[VOLUME] Triggered sync for volume %s on node %s",
                volume_id,
                node_name,
            )
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.UNIMPLEMENTED:
                logger.warning(
                    "[VOLUME] SyncVolume RPC not implemented on node %s — "
                    "relying on background sync daemon for volume %s",
                    node_name,
                    volume_id,
                )
            else:
                raise

    async def fix_ownership(self, volume_id: str, node_name: str, uid: int = 1000, gid: int = 1000) -> None:
        """Fix ownership of an existing volume (migration for pre-fix volumes)."""
        address = await self._discovery.get_nodeops_address(node_name)
        async with NodeOpsClient(address) as client:
            await client.set_ownership(f"volumes/{volume_id}", uid=uid, gid=gid)

        logger.info(
            "[VOLUME] Fixed ownership for volume %s on node %s (uid=%d, gid=%d)",
            volume_id,
            node_name,
            uid,
            gid,
        )

    # ------------------------------------------------------------------
    # Node selection
    # ------------------------------------------------------------------

    async def _select_target_node(
        self, *, exclude: set[str] | None = None
    ) -> str:
        """Pick the best node considering both btrfs capacity and CPU headroom.

        Prefers nodes with enough CPU headroom to actually schedule a pod.
        Among schedulable nodes, picks the one with the most disk space.

        Args:
            exclude: Node names to skip (e.g. nodes that already failed).

        Raises:
            RuntimeError: If no ready CSI nodes are available.
        """
        all_nodes = await self._discovery.get_all_csi_nodes()
        ready = [
            n for n in all_nodes
            if n.ready and (exclude is None or n.node_name not in exclude)
        ]

        if not ready:
            raise RuntimeError("No ready CSI nodes available")

        # Query disk capacity and CPU headroom concurrently
        async def _score_node(node):
            try:
                addr = await self._discovery.get_nodeops_address(node.node_name)
                async with NodeOpsClient(addr) as client:
                    cap = await client.get_capacity()
                disk_avail = cap.get("available", 0)
            except Exception:
                logger.warning("[VOLUME] Failed to get capacity for node %s", node.node_name)
                disk_avail = 0

            try:
                cpu_headroom = await self._discovery.get_node_cpu_headroom(node.node_name)
            except Exception:
                logger.warning("[VOLUME] Failed to get CPU headroom for node %s", node.node_name)
                cpu_headroom = 0

            return node.node_name, disk_avail, cpu_headroom

        results = await asyncio.gather(*[_score_node(n) for n in ready])

        # Minimum CPU headroom to schedule a project pod (50m request + margin)
        MIN_CPU_HEADROOM_M = 100

        schedulable = [(name, disk, cpu) for name, disk, cpu in results if cpu >= MIN_CPU_HEADROOM_M]

        if schedulable:
            best = max(schedulable, key=lambda r: r[1])
        else:
            logger.warning(
                "[VOLUME] No nodes have >= %dm CPU headroom, falling back to most disk",
                MIN_CPU_HEADROOM_M,
            )
            best = max(results, key=lambda r: r[1])

        best_node, best_disk, best_cpu = best
        logger.info(
            "[VOLUME] Selected node %s (disk: %d bytes, cpu headroom: %dm)",
            best_node,
            best_disk,
            best_cpu,
        )
        return best_node

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    async def _retry_on_node(
        self,
        coro_factory,
        node_name: str,
        max_retries: int = 3,
    ) -> None:
        """Execute an async callable with exponential backoff.

        Retries on UNAVAILABLE and DEADLINE_EXCEEDED gRPC errors.
        Raises _AllRetriesExhausted after exhausting all attempts.
        """
        backoff = 1.0
        for attempt in range(1, max_retries + 1):
            try:
                await coro_factory()
                return
            except grpc.aio.AioRpcError as e:
                if e.code() in (
                    grpc.StatusCode.UNAVAILABLE,
                    grpc.StatusCode.DEADLINE_EXCEEDED,
                ):
                    if attempt == max_retries:
                        logger.error(
                            "[VOLUME] gRPC %s on node %s after %d attempts",
                            e.code().name,
                            node_name,
                            max_retries,
                        )
                        raise _AllRetriesExhausted(node_name) from e

                    logger.warning(
                        "[VOLUME] gRPC %s on node %s (attempt %d/%d), retrying in %.0fs",
                        e.code().name,
                        node_name,
                        attempt,
                        max_retries,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    raise

    # ------------------------------------------------------------------
    # Private operation helpers
    # ------------------------------------------------------------------

    async def _do_create_from_template(
        self, address: str, volume_id: str, template: str
    ) -> None:
        async with NodeOpsClient(address) as client:
            await client.ensure_template(template, timeout=300.0)
            await client.snapshot_subvolume(
                f"templates/{template}", f"volumes/{volume_id}"
            )
            await client.track_volume(volume_id)

    async def _do_restore(self, address: str, volume_id: str) -> None:
        async with NodeOpsClient(address) as client:
            await client.restore_volume(volume_id, timeout=300.0)
            await client.track_volume(volume_id)


class _AllRetriesExhausted(Exception):
    """Internal signal: all retry attempts on a single node failed."""

    def __init__(self, node_name: str) -> None:
        self.node_name = node_name
        super().__init__(f"All retries exhausted on node {node_name}")


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
