"""Python async gRPC client for the standalone tesslate-ast service.

Uses JSON codec (not protobuf) to match the in-cluster convention used
by fileops_client.py and hub_client.py. Cluster-internal traffic is
protected by NetworkPolicy, so plaintext gRPC is fine.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import grpc
import grpc.aio

from ...config import get_settings
from .circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)

_MAX_MESSAGE_SIZE = 64 * 1024 * 1024  # 64 MB, matches fileops
_SERVICE_NAME = "tesslateast.AstService"
_JSON_METADATA = (("content-type", "application/grpc+json"),)

# Loopback-only. The AST service is a sidecar in the backend pod; the
# gRPC channel is plaintext (insecure_channel). Allowing a non-local
# address would silently route TSX source over the cluster network
# without TLS. If we ever want a cross-pod deployment, add TLS and
# remove this guard.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _assert_loopback_address(address: str) -> None:
    """Raise at construction time if the configured address isn't loopback.

    Prevents a misconfigured env var from silently leaking user source
    over a plaintext cross-pod gRPC connection.
    """
    host = address.rsplit(":", 1)[0]
    # Strip IPv6 brackets, e.g. "[::1]:9000"
    host = host.strip("[]")
    if host not in _LOOPBACK_HOSTS:
        raise ValueError(
            f"ast_service_address must be loopback (one of {sorted(_LOOPBACK_HOSTS)}); "
            f"got {address!r}. Plaintext gRPC is only safe in-pod. "
            "If you intend to split AST into its own pod, add TLS support first."
        )


def _serialize(obj: dict) -> bytes:
    return json.dumps(obj or {}).encode("utf-8")


def _deserialize(data: bytes) -> dict:
    return json.loads(data) if data else {}


class AstClientError(RuntimeError):
    """Raised for any AST client failure — network, deadline, or server-side."""


class AstClientBudgetError(AstClientError):
    """Raised when a request is rejected locally by client-side budgets."""


class AstClient:
    """Async client for the tesslate-ast gRPC service.

    Usage::

        client = get_ast_client()  # module-level singleton, auto-created
        result = await client.index(files)
        ...
        await client.close()       # registered on FastAPI lifespan shutdown
    """

    def __init__(
        self,
        address: str,
        *,
        timeout: float,
        max_request_files: int,
        max_request_bytes: int,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        _assert_loopback_address(address)
        self._address = address
        self._timeout = timeout
        self._max_files = max_request_files
        self._max_bytes = max_request_bytes
        self._breaker = circuit_breaker
        self._channel: grpc.aio.Channel | None = None

    # ------------------------------------------------------------------
    # Channel lifecycle
    # ------------------------------------------------------------------
    async def _ensure_channel(self) -> grpc.aio.Channel:
        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(
                self._address,
                options=[
                    ("grpc.max_send_message_length", _MAX_MESSAGE_SIZE),
                    ("grpc.max_receive_message_length", _MAX_MESSAGE_SIZE),
                    ("grpc.keepalive_time_ms", 30_000),
                    ("grpc.keepalive_timeout_ms", 10_000),
                    ("grpc.keepalive_permit_without_calls", 1),
                    ("grpc.http2.max_pings_without_data", 0),
                ],
            )
        return self._channel

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    # ------------------------------------------------------------------
    # Budget enforcement — mirror server budgets locally
    # ------------------------------------------------------------------
    def _check_files_budget(self, files: list[dict]) -> None:
        if len(files) > self._max_files:
            raise AstClientBudgetError(
                f"request has {len(files)} files, budget is {self._max_files}"
            )
        total = 0
        for f in files:
            path = f.get("path")
            content = f.get("content")
            if not isinstance(path, str) or not isinstance(content, str):
                raise AstClientBudgetError("each file must have {path: str, content: str}")
            total += len(content.encode("utf-8"))
            if total > self._max_bytes:
                raise AstClientBudgetError(f"request content exceeds {self._max_bytes} bytes")

    # ------------------------------------------------------------------
    # RPC invocation
    # ------------------------------------------------------------------
    async def _call(self, method: str, request: dict, *, timeout: float | None = None) -> dict:
        await self._breaker.allow()
        channel = await self._ensure_channel()
        unary = channel.unary_unary(
            f"/{_SERVICE_NAME}/{method}",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )
        try:
            result = await unary(
                request,
                timeout=timeout or self._timeout,
                metadata=_JSON_METADATA,
            )
        except grpc.aio.AioRpcError as exc:
            await self._breaker.record_failure()
            raise AstClientError(
                f"ast.{method} failed ({exc.code().name}): {exc.details()}"
            ) from exc
        except Exception as exc:
            await self._breaker.record_failure()
            raise AstClientError(f"ast.{method} failed: {exc}") from exc
        await self._breaker.record_success()
        return result

    # ------------------------------------------------------------------
    # Public API (contract: bytes in, bytes out — no project/user fields)
    # ------------------------------------------------------------------
    async def ping(self, *, timeout: float = 5.0) -> dict[str, Any]:
        return await self._call("Ping", {}, timeout=timeout)

    async def index(self, files: list[dict[str, str]]) -> dict[str, Any]:
        """files: [{path, content}] → {files, index}"""
        self._check_files_budget(files)
        return await self._call("Index", {"files": files})

    async def apply_diff(
        self,
        files: list[dict[str, str]],
        requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """files + requests → {files}"""
        self._check_files_budget(files)
        return await self._call("ApplyDiff", {"files": files, "requests": requests})


# ──────────────────────────────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────────────────────────────
_CLIENT: AstClient | None = None


def get_ast_client() -> AstClient:
    """Return the shared AstClient, creating it on first access."""
    global _CLIENT
    if _CLIENT is None:
        settings = get_settings()
        breaker = CircuitBreaker(
            failure_threshold=settings.ast_service_circuit_breaker_failures,
            reset_seconds=settings.ast_service_circuit_breaker_reset_seconds,
            name="ast_service",
        )
        _CLIENT = AstClient(
            address=settings.ast_service_address,
            timeout=float(settings.ast_service_timeout_seconds),
            max_request_files=settings.ast_service_max_request_files,
            max_request_bytes=settings.ast_service_max_request_bytes,
            circuit_breaker=breaker,
        )
    return _CLIENT


async def shutdown_ast_client() -> None:
    """Close the shared channel on app shutdown."""
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.close()
        _CLIENT = None


__all__ = [
    "AstClient",
    "AstClientError",
    "AstClientBudgetError",
    "CircuitOpenError",
    "get_ast_client",
    "shutdown_ast_client",
]
