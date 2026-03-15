"""
Python gRPC client for the btrfs CSI driver's NodeOps service.

The CSI driver uses a custom JSON codec (not protobuf), so this client
sends JSON-encoded request/response bodies over gRPC.  Cluster-internal
traffic is protected by NetworkPolicy, so plaintext gRPC is fine.
"""

from __future__ import annotations

import json
import logging

import grpc
import grpc.aio

logger = logging.getLogger(__name__)


def _serialize(obj: dict) -> bytes:
    """Serialize a dict to JSON bytes for the gRPC wire format."""
    return json.dumps(obj).encode("utf-8")


def _deserialize(data: bytes) -> dict:
    """Deserialize a JSON response."""
    return json.loads(data) if data else {}


# The CSI driver uses a registered JSON codec (not protobuf).
# Go clients use grpc.ForceCodec(jsonCodec{}) which sets content-type
# to application/grpc+json. Python gRPC doesn't have ForceCodec, so
# we set the content-type via call metadata.
_JSON_METADATA = (("content-type", "application/grpc+json"),)


class NodeOpsClient:
    """Async client for the btrfs CSI NodeOps gRPC service.

    Usage::

        client = NodeOpsClient("csi-node-service:9741")
        await client.promote_to_template("vol-abc123", "nextjs")
        await client.close()
    """

    def __init__(self, address: str) -> None:
        self._address = address
        self._channel: grpc.aio.Channel | None = None

    async def _ensure_channel(self) -> grpc.aio.Channel:
        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._address)
        return self._channel

    async def _call(
        self, method: str, request: dict, *, timeout: float = 30.0
    ) -> dict:
        """Invoke a NodeOps RPC with JSON codec content-type."""
        channel = await self._ensure_channel()
        call = channel.unary_unary(
            f"/nodeops.NodeOps/{method}",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )
        return await call(request, timeout=timeout, metadata=_JSON_METADATA)

    async def promote_to_template(
        self,
        volume_id: str,
        template_name: str,
        *,
        timeout: float = 300.0,
    ) -> None:
        """Call PromoteToTemplate on the CSI node.

        Snapshots the build volume as a read-only template, uploads the
        snapshot to S3, and deletes the source volume.

        Args:
            volume_id: The CSI volume ID to promote.
            template_name: Human-readable template name (e.g. "nextjs").
            timeout: gRPC deadline in seconds (default 5 min, uploads can
                     be large).

        Raises:
            grpc.aio.AioRpcError: On any gRPC failure.
        """
        await self._call(
            "PromoteToTemplate",
            {"volume_id": volume_id, "template_name": template_name},
            timeout=timeout,
        )
        logger.info(
            "PromoteToTemplate succeeded: volume=%s template=%s",
            volume_id,
            template_name,
        )

    async def create_subvolume(self, name: str, *, uid: int = 1000, gid: int = 1000, timeout: float = 30.0) -> None:
        """Create a new btrfs subvolume."""
        await self._call("CreateSubvolume", {"name": name, "uid": uid, "gid": gid}, timeout=timeout)
        logger.info("CreateSubvolume succeeded: name=%s", name)

    async def set_ownership(self, name: str, uid: int = 1000, gid: int = 1000, *, timeout: float = 30.0) -> None:
        """Recursively chown a subvolume to the given uid:gid."""
        await self._call("SetOwnership", {"name": name, "uid": uid, "gid": gid}, timeout=timeout)
        logger.info("SetOwnership succeeded: name=%s uid=%d gid=%d", name, uid, gid)

    async def delete_subvolume(self, name: str, *, timeout: float = 30.0) -> None:
        """Delete a btrfs subvolume."""
        await self._call("DeleteSubvolume", {"name": name}, timeout=timeout)
        logger.info("DeleteSubvolume succeeded: name=%s", name)

    async def snapshot_subvolume(
        self,
        source: str,
        dest: str,
        *,
        read_only: bool = False,
        timeout: float = 30.0,
    ) -> None:
        """Snapshot a btrfs subvolume."""
        await self._call(
            "SnapshotSubvolume",
            {"source": source, "dest": dest, "read_only": read_only},
            timeout=timeout,
        )
        logger.info(
            "SnapshotSubvolume succeeded: source=%s dest=%s read_only=%s",
            source, dest, read_only,
        )

    async def subvolume_exists(self, name: str, *, timeout: float = 30.0) -> bool:
        """Check if a btrfs subvolume exists."""
        resp = await self._call("SubvolumeExists", {"name": name}, timeout=timeout)
        return resp.get("exists", False)

    async def get_capacity(self, *, timeout: float = 30.0) -> dict:
        """Get btrfs filesystem capacity info.

        Returns:
            dict with "total" and "available" (bytes).
        """
        return await self._call("GetCapacity", {}, timeout=timeout)

    async def list_subvolumes(
        self, prefix: str = "", *, timeout: float = 30.0
    ) -> list[dict]:
        """List btrfs subvolumes matching a prefix.

        Returns:
            List of dicts with "id", "name", "path", "read_only".
        """
        resp = await self._call("ListSubvolumes", {"prefix": prefix}, timeout=timeout)
        return resp.get("subvolumes", [])

    async def track_volume(self, volume_id: str, *, timeout: float = 30.0) -> None:
        """Register a volume for tracking by the CSI driver."""
        await self._call("TrackVolume", {"volume_id": volume_id}, timeout=timeout)
        logger.info("TrackVolume succeeded: volume_id=%s", volume_id)

    async def untrack_volume(self, volume_id: str, *, timeout: float = 30.0) -> None:
        """Unregister a volume from CSI driver tracking."""
        await self._call("UntrackVolume", {"volume_id": volume_id}, timeout=timeout)
        logger.info("UntrackVolume succeeded: volume_id=%s", volume_id)

    async def ensure_template(
        self, name: str, *, timeout: float = 300.0
    ) -> None:
        """Ensure a template subvolume exists (download from S3 if needed)."""
        await self._call("EnsureTemplate", {"name": name}, timeout=timeout)
        logger.info("EnsureTemplate succeeded: name=%s", name)

    async def restore_volume(
        self, volume_id: str, *, timeout: float = 300.0
    ) -> None:
        """Restore a volume from object storage."""
        await self._call("RestoreVolume", {"volume_id": volume_id}, timeout=timeout)
        logger.info("RestoreVolume succeeded: volume_id=%s", volume_id)

    async def sync_volume(
        self, volume_id: str, *, timeout: float = 300.0
    ) -> None:
        """Trigger an S3 sync for a volume."""
        await self._call("SyncVolume", {"volume_id": volume_id}, timeout=timeout)
        logger.info("SyncVolume succeeded: volume_id=%s", volume_id)

    async def close(self) -> None:
        """Gracefully close the underlying gRPC channel."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    async def __aenter__(self) -> NodeOpsClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
