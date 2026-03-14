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


def _deserialize_empty(data: bytes) -> dict:
    """Deserialize an (expected-empty) JSON response."""
    return json.loads(data) if data else {}


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
        channel = await self._ensure_channel()
        request = {"volume_id": volume_id, "template_name": template_name}

        call = channel.unary_unary(
            "/nodeops.NodeOps/PromoteToTemplate",
            request_serializer=_serialize,
            response_deserializer=_deserialize_empty,
        )
        await call(request, timeout=timeout)

        logger.info(
            "PromoteToTemplate succeeded: volume=%s template=%s",
            volume_id,
            template_name,
        )

    async def close(self) -> None:
        """Gracefully close the underlying gRPC channel."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    async def __aenter__(self) -> NodeOpsClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
