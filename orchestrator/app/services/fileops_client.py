"""
Python gRPC client for the btrfs CSI driver's FileOps service.

The CSI driver uses a custom JSON codec (not protobuf), so this client
sends JSON-encoded request/response bodies over gRPC.  Cluster-internal
traffic is protected by NetworkPolicy, so plaintext gRPC is fine.

Bytes fields (file content, tar archives) are base64-encoded on the wire
because Go's json.Marshal encodes []byte as base64.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass

import grpc
import grpc.aio

logger = logging.getLogger(__name__)

_MAX_MESSAGE_SIZE = 64 * 1024 * 1024  # 64 MB


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


@dataclass(frozen=True, slots=True)
class FileInfo:
    """Metadata for a single file or directory, matching the Go FileInfo struct."""

    name: str
    path: str
    size: int
    is_dir: bool
    mod_time: int
    mode: int


@dataclass(frozen=True, slots=True)
class FileContent:
    """Content of a single file from batch read."""

    path: str
    data: str  # text content (decoded from base64 bytes)
    size: int


class FileOpsClient:
    """Async client for the btrfs CSI FileOps gRPC service.

    Usage::

        async with FileOpsClient("csi-node:9742") as client:
            data = await client.read_file("vol-abc", "/app/index.ts")
            text = await client.read_file_text("vol-abc", "/app/index.ts")
            await client.write_file_text("vol-abc", "/app/index.ts", "console.log('hi')")
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
                ],
            )
        return self._channel

    async def _call(self, method: str, request: dict, *, timeout: float = 30.0) -> dict:
        """Invoke a FileOps RPC with JSON codec content-type."""
        channel = await self._ensure_channel()
        call = channel.unary_unary(
            f"/fileops.FileOps/{method}",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )
        return await call(request, timeout=timeout, metadata=_JSON_METADATA)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    async def read_file(self, volume_id: str, path: str, *, timeout: float = 30.0) -> bytes:
        """Read a file from a volume. Returns raw bytes."""
        resp = await self._call("ReadFile", {"volume_id": volume_id, "path": path}, timeout=timeout)
        return base64.b64decode(resp.get("data", ""))

    async def write_file(
        self,
        volume_id: str,
        path: str,
        data: bytes,
        *,
        mode: int = 0o644,
        uid: int = 1000,
        gid: int = 1000,
        timeout: float = 30.0,
    ) -> None:
        """Write raw bytes to a file on a volume."""
        await self._call(
            "WriteFile",
            {
                "volume_id": volume_id,
                "path": path,
                "data": base64.b64encode(data).decode("ascii"),
                "mode": mode,
                "uid": uid,
                "gid": gid,
            },
            timeout=timeout,
        )
        logger.info("WriteFile succeeded: volume=%s path=%s", volume_id, path)

    async def list_dir(
        self,
        volume_id: str,
        path: str,
        *,
        recursive: bool = False,
        timeout: float = 30.0,
    ) -> list[FileInfo]:
        """List directory contents on a volume."""
        resp = await self._call(
            "ListDir",
            {"volume_id": volume_id, "path": path, "recursive": recursive},
            timeout=timeout,
        )
        return [
            FileInfo(
                name=e["name"],
                path=e["path"],
                size=e.get("size", 0),
                is_dir=e.get("is_dir", False),
                mod_time=e.get("mod_time", 0),
                mode=e.get("mode", 0),
            )
            for e in resp.get("entries", [])
        ]

    async def list_tree(
        self,
        volume_id: str,
        path: str = ".",
        *,
        exclude_dirs: list[str] | None = None,
        exclude_files: list[str] | None = None,
        exclude_extensions: list[str] | None = None,
        timeout: float = 30.0,
    ) -> list[FileInfo]:
        """Recursive filtered directory tree via ListTree RPC."""
        resp = await self._call(
            "ListTree",
            {
                "volume_id": volume_id,
                "path": path,
                "exclude_dirs": exclude_dirs or [],
                "exclude_files": exclude_files or [],
                "exclude_extensions": exclude_extensions or [],
            },
            timeout=timeout,
        )
        return [
            FileInfo(
                name=e["name"],
                path=e["path"],
                size=e.get("size", 0),
                is_dir=e.get("is_dir", False),
                mod_time=e.get("mod_time", 0),
                mode=e.get("mode", 0),
            )
            for e in resp.get("entries", [])
        ]

    async def read_files(
        self,
        volume_id: str,
        paths: list[str],
        *,
        max_file_size: int = 100_000,
        timeout: float = 30.0,
    ) -> tuple[list[FileContent], list[str]]:
        """Batch-read multiple files via ReadFiles RPC."""
        resp = await self._call(
            "ReadFiles",
            {
                "volume_id": volume_id,
                "paths": paths,
                "max_file_size": max_file_size,
            },
            timeout=timeout,
        )
        files = [
            FileContent(
                path=f["path"],
                data=base64.b64decode(f.get("data", "")).decode("utf-8", errors="replace"),
                size=f.get("size", 0),
            )
            for f in resp.get("files", [])
        ]
        errors = resp.get("errors", [])
        return files, errors

    async def stat_path(self, volume_id: str, path: str, *, timeout: float = 30.0) -> FileInfo:
        """Get file/directory metadata."""
        resp = await self._call("StatPath", {"volume_id": volume_id, "path": path}, timeout=timeout)
        info = resp.get("info", {})
        return FileInfo(
            name=info.get("name", ""),
            path=info.get("path", ""),
            size=info.get("size", 0),
            is_dir=info.get("is_dir", False),
            mod_time=info.get("mod_time", 0),
            mode=info.get("mode", 0),
        )

    async def delete_path(self, volume_id: str, path: str, *, timeout: float = 30.0) -> None:
        """Delete a file or directory on a volume."""
        await self._call("DeletePath", {"volume_id": volume_id, "path": path}, timeout=timeout)
        logger.info("DeletePath succeeded: volume=%s path=%s", volume_id, path)

    async def mkdir_all(
        self, volume_id: str, path: str, *, uid: int = 1000, gid: int = 1000, timeout: float = 30.0
    ) -> None:
        """Create a directory and all parents on a volume."""
        await self._call(
            "MkdirAll",
            {"volume_id": volume_id, "path": path, "uid": uid, "gid": gid},
            timeout=timeout,
        )
        logger.info("MkdirAll succeeded: volume=%s path=%s", volume_id, path)

    # ------------------------------------------------------------------
    # Tar operations
    # ------------------------------------------------------------------

    async def tar_create(self, volume_id: str, path: str, *, timeout: float = 60.0) -> bytes:
        """Create a tar archive of a path on a volume. Returns raw bytes."""
        resp = await self._call(
            "TarCreate", {"volume_id": volume_id, "path": path}, timeout=timeout
        )
        return base64.b64decode(resp.get("data", ""))

    async def tar_extract(
        self,
        volume_id: str,
        path: str,
        data: bytes,
        *,
        uid: int = 1000,
        gid: int = 1000,
        timeout: float = 60.0,
    ) -> None:
        """Extract a tar archive to a path on a volume."""
        await self._call(
            "TarExtract",
            {
                "volume_id": volume_id,
                "path": path,
                "data": base64.b64encode(data).decode("ascii"),
                "uid": uid,
                "gid": gid,
            },
            timeout=timeout,
        )
        logger.info("TarExtract succeeded: volume=%s path=%s", volume_id, path)

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    async def read_file_text(self, volume_id: str, path: str, *, timeout: float = 30.0) -> str:
        """Read a file as UTF-8 text."""
        data = await self.read_file(volume_id, path, timeout=timeout)
        return data.decode("utf-8")

    async def write_file_text(
        self,
        volume_id: str,
        path: str,
        text: str,
        *,
        mode: int = 0o644,
        uid: int = 1000,
        gid: int = 1000,
        timeout: float = 30.0,
    ) -> None:
        """Write UTF-8 text to a file."""
        await self.write_file(
            volume_id, path, text.encode("utf-8"), mode=mode, uid=uid, gid=gid, timeout=timeout
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Gracefully close the underlying gRPC channel."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    async def __aenter__(self) -> FileOpsClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
