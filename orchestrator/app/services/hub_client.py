"""
gRPC client for the Volume Hub service.

The Hub is the cluster brain -- storageless orchestrator that coordinates
nodes for volume lifecycle, cache placement, and S3 sync.  Same JSON codec
as NodeOps/FileOps: requests are JSON-encoded over gRPC with
``content-type: application/grpc+json``.

Hub endpoint:
  - Port 9750: VolumeHub gRPC (volume management, cache orchestration)
"""

from __future__ import annotations

import json
import logging

import grpc
import grpc.aio

logger = logging.getLogger(__name__)


class NodeResourcesExhausted(Exception):
    """Raised when no node has enough resources for a placement unit."""


_MAX_MESSAGE_SIZE = 64 * 1024 * 1024  # 64 MiB


def _serialize(obj: dict) -> bytes:
    """Serialize a dict to JSON bytes for the gRPC wire format."""
    return json.dumps(obj).encode("utf-8")


def _deserialize(data: bytes) -> dict:
    """Deserialize a JSON response."""
    return json.loads(data) if data else {}


# The Hub uses the same registered JSON codec as the CSI driver.
# Python gRPC doesn't have ForceCodec, so we set the content-type
# via call metadata.
_JSON_METADATA = (("content-type", "application/grpc+json"),)


class HubClient:
    """Async client for the Volume Hub gRPC service.

    Usage::

        async with HubClient("tesslate-volume-hub.kube-system.svc:9750") as client:
            vol_id = await client.create_volume(template="nextjs")
            node = await client.ensure_cached(vol_id, candidate_nodes=["node-1"])
    """

    def __init__(self, address: str) -> None:
        self._address = address
        self._channel: grpc.aio.Channel | None = None

    async def _ensure_channel(self) -> grpc.aio.Channel:
        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(
                self._address,
                options=[
                    ("grpc.max_send_message_length", _MAX_MESSAGE_SIZE),
                    ("grpc.max_receive_message_length", _MAX_MESSAGE_SIZE),
                    # Keepalive: detect dead connections and trigger reconnect.
                    ("grpc.keepalive_time_ms", 30_000),
                    ("grpc.keepalive_timeout_ms", 10_000),
                    ("grpc.keepalive_permit_without_calls", 1),
                ],
            )
        return self._channel

    async def _call(self, method: str, request: dict, *, timeout: float = 30.0) -> dict:
        """Invoke a VolumeHub RPC with JSON codec content-type."""
        channel = await self._ensure_channel()
        call = channel.unary_unary(
            f"/volumehub.VolumeHub/{method}",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )
        # wait_for_ready: if channel is reconnecting after a transient failure,
        # wait up to `timeout` instead of failing immediately.
        return await call(request, timeout=timeout, metadata=_JSON_METADATA, wait_for_ready=True)

    # ------------------------------------------------------------------
    # Volume lifecycle
    # ------------------------------------------------------------------

    async def create_volume(
        self,
        template: str | None = None,
        hint_node: str | None = None,
        *,
        timeout: float = 30.0,
    ) -> tuple[str, str]:
        """Create a volume on a node from template (or empty).

        Args:
            template: Template name to clone from (e.g. ``"nextjs"``).
                      Pass ``None`` for an empty volume.
            hint_node: Preferred node for volume placement.
            timeout: gRPC deadline in seconds.

        Returns:
            Tuple of ``(volume_id, node_name)`` — the volume ID and the
            node where the volume was created.
        """
        request: dict = {}
        if template is not None:
            request["template"] = template
        if hint_node is not None:
            request["hint_node"] = hint_node
        resp = await self._call("CreateVolume", request, timeout=timeout)
        volume_id = resp["volume_id"]
        node_name = resp["node_name"]
        logger.info(
            "CreateVolume succeeded: volume_id=%s node=%s template=%s",
            volume_id,
            node_name,
            template,
        )
        return volume_id, node_name

    async def delete_volume(self, volume_id: str, *, timeout: float = 30.0) -> None:
        """Delete from Hub + S3 + all node caches.  Idempotent.

        Args:
            volume_id: Volume to delete.
            timeout: gRPC deadline in seconds.
        """
        await self._call("DeleteVolume", {"volume_id": volume_id}, timeout=timeout)
        logger.info("DeleteVolume succeeded: volume_id=%s", volume_id)

    # ------------------------------------------------------------------
    # Cache orchestration
    # ------------------------------------------------------------------

    async def ensure_cached(
        self,
        volume_id: str,
        candidate_nodes: list[str] | None = None,
        *,
        budget_cpu: int = 0,
        budget_mem: int = 0,
        timeout: float = 120.0,
    ) -> str:
        """Ensure volume is cached on a live, schedulable compute node.

        The Hub validates candidates against its live node set, optionally
        filters by resource headroom, and never returns a dead node. If the
        volume is already cached on a qualifying candidate, it returns
        immediately (fast path). Otherwise it peer-transfers or restores
        from CAS onto the best candidate.

        Args:
            volume_id: Volume to cache.
            candidate_nodes: K8s nodes the caller considers schedulable.
                The Hub intersects this with its own live set and picks
                the best one. Pass ``None`` to let the Hub choose from
                all live nodes.
            budget_cpu: CPU millicores needed for the placement unit (0 = skip check).
            budget_mem: Memory bytes needed for the placement unit (0 = skip check).
            timeout: gRPC deadline in seconds (default 120 s to cover
                     network transfers).

        Returns:
            The node name where the volume is now cached.
        """
        request: dict = {"volume_id": volume_id}
        if candidate_nodes is not None:
            request["candidate_nodes"] = candidate_nodes
        if budget_cpu > 0:
            request["budget_cpu"] = budget_cpu
        if budget_mem > 0:
            request["budget_mem"] = budget_mem
        try:
            resp = await self._call("EnsureCached", request, timeout=timeout)
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
                raise NodeResourcesExhausted(
                    f"No node has enough resources for volume {volume_id}: {e.details()}"
                ) from e
            raise
        node_name = resp["node_name"]
        logger.info(
            "EnsureCached succeeded: volume_id=%s node=%s (candidates=%s)",
            volume_id,
            node_name,
            candidate_nodes,
        )
        return node_name

    async def transfer_ownership(
        self,
        volume_id: str,
        new_node: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        """Transfer volume ownership to a new node.

        The Hub validates the volume is cached on the new node before
        transferring. Orchestrator should call this after pods are
        healthy on the new node.

        Args:
            volume_id: Volume to transfer.
            new_node: Node to become the new owner.
            timeout: gRPC deadline in seconds.
        """
        await self._call(
            "TransferOwnership",
            {"volume_id": volume_id, "new_node": new_node},
            timeout=timeout,
        )
        logger.info(
            "TransferOwnership succeeded: volume_id=%s new_node=%s",
            volume_id,
            new_node,
        )

    async def trigger_sync(
        self,
        volume_id: str,
        *,
        timeout: float = 120.0,
    ) -> None:
        """Trigger S3 sync on the node that owns the volume.

        The Hub looks up the owner node and tells it to sync to S3.
        No node_name needed — the Hub tracks ownership.

        Args:
            volume_id: Volume whose data to sync.
            timeout: gRPC deadline in seconds (default 120 s for large
                     syncs).
        """
        await self._call(
            "TriggerSync",
            {"volume_id": volume_id},
            timeout=timeout,
        )
        logger.info(
            "TriggerSync succeeded: volume_id=%s",
            volume_id,
        )

    # ------------------------------------------------------------------
    # Status / introspection
    # ------------------------------------------------------------------

    async def volume_status(self, volume_id: str, *, timeout: float = 30.0) -> dict:
        """Get volume status from Hub registry.

        Args:
            volume_id: Volume to query.
            timeout: gRPC deadline in seconds.

        Returns:
            Dict with keys ``volume_id``, ``owner_node``,
            ``cached_nodes`` (list[str]), ``last_sync`` (ISO timestamp
            or ``None``).
        """
        resp = await self._call("VolumeStatus", {"volume_id": volume_id}, timeout=timeout)
        return resp

    # ------------------------------------------------------------------
    # Volume routing
    # ------------------------------------------------------------------

    async def resolve_volume(self, volume_id: str, *, timeout: float = 20.0) -> dict:
        """Non-blocking volume resolution via Hub.

        Returns the volume's current state and routing addresses.

        Args:
            volume_id: Volume to resolve.
            timeout: gRPC deadline in seconds.

        Returns:
            Dict with ``node_name``, ``fileops_address``,
            ``nodeops_address``, ``state`` (cached/restoring/unavailable).
        """
        resp = await self._call("ResolveVolume", {"volume_id": volume_id}, timeout=timeout)
        logger.info(
            "ResolveVolume: volume_id=%s state=%s node=%s",
            volume_id,
            resp.get("state"),
            resp.get("node_name", ""),
        )
        return resp

    # ------------------------------------------------------------------
    # Service volumes
    # ------------------------------------------------------------------

    async def create_service_volume(
        self,
        base_volume_id: str,
        service_name: str,
        *,
        timeout: float = 30.0,
    ) -> str:
        """Create a service-specific subvolume on the Hub.

        Service volumes hold ephemeral service data (e.g. Postgres data
        dir) and are tied to a base project volume.

        Args:
            base_volume_id: Parent project volume ID.
            service_name: Service identifier (e.g. ``"postgres"``).
            timeout: gRPC deadline in seconds.

        Returns:
            The service volume ID (e.g. ``"vol-abc123-postgres"``).
        """
        resp = await self._call(
            "CreateServiceVolume",
            {"base_volume_id": base_volume_id, "service_name": service_name},
            timeout=timeout,
        )
        volume_id = resp["volume_id"]
        logger.info(
            "CreateServiceVolume succeeded: base=%s service=%s -> %s",
            base_volume_id,
            service_name,
            volume_id,
        )
        return volume_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Gracefully close the underlying gRPC channel."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    async def __aenter__(self) -> HubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
