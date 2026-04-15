"""
Cloud companion HTTP client (desktop sidecar → cloud).

Wraps ``httpx.AsyncClient`` with three desktop-specific behaviors:

  - **Bearer injection**: every request reads ``token_store.get_cloud_token()``
    at call time. Missing token → :class:`NotPairedError` (never a network call).
  - **Bounded retries**: 5xx responses retry on ``0.5s, 1s, 2s`` then give up.
    4xx responses never retry. ``asyncio.CancelledError`` propagates cleanly.
  - **Circuit breaker**: 5 consecutive failures inside a 60s window opens the
    breaker for 30s; further calls fail fast with :class:`CircuitOpenError`.
    Any successful response resets the counter.

The client is a lazy process-wide singleton via :func:`get_cloud_client` so
the connection pool (``max_connections=20``, ``max_keepalive_connections=5``)
is shared across routers/workers. All public methods are non-blocking on
failure: callers should ``try/except`` and fall back to cached/empty data.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from ..config import get_settings
from . import token_store

logger = logging.getLogger(__name__)

# Retry policy (seconds)
_RETRY_DELAYS: tuple[float, ...] = (0.5, 1.0, 2.0)

# Circuit breaker tunables
_CB_FAILURE_THRESHOLD = 5
_CB_FAILURE_WINDOW_S = 60.0
_CB_OPEN_DURATION_S = 30.0

# Pool / timeout
_POOL_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=5)
_DEFAULT_TIMEOUT = httpx.Timeout(30.0)


class CloudClientError(Exception):
    """Base error raised by :class:`CloudClient`."""


class NotPairedError(CloudClientError):
    """No cloud bearer token is available — pair via the desktop UI first."""


class CircuitOpenError(CloudClientError):
    """The circuit breaker is open; the cloud is being given time to recover."""


class _CircuitBreaker:
    """Tiny consecutive-failure breaker. Not thread-safe; asyncio-safe."""

    def __init__(self) -> None:
        self._failures: list[float] = []
        self._opened_at: float | None = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if time.monotonic() - self._opened_at >= _CB_OPEN_DURATION_S:
            # Half-open: let one request through; success will close, failure re-opens.
            self._opened_at = None
            self._failures.clear()
            return True
        return False

    def record_success(self) -> None:
        self._failures.clear()
        self._opened_at = None

    def record_failure(self) -> None:
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t <= _CB_FAILURE_WINDOW_S]
        self._failures.append(now)
        if len(self._failures) >= _CB_FAILURE_THRESHOLD:
            self._opened_at = now
            logger.warning(
                "cloud_client: circuit opened after %d failures in %.0fs",
                len(self._failures),
                _CB_FAILURE_WINDOW_S,
            )


class CloudClient:
    """Async HTTP client for the cloud companion endpoint.

    Construct directly in tests (with a custom ``base_url`` / ``transport``)
    or use :func:`get_cloud_client` for the process singleton.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.tesslate_cloud_url).rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=_DEFAULT_TIMEOUT,
            limits=_POOL_LIMITS,
            transport=transport,
        )
        self._breaker = _CircuitBreaker()

    @property
    def base_url(self) -> str:
        return self._base_url

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Public verbs
    # ------------------------------------------------------------------

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, *, json: Any = None) -> httpx.Response:
        return await self._request("POST", path, json=json)

    async def post_multipart(
        self,
        path: str,
        *,
        files: dict[str, Any],
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Multipart POST for file uploads.

        Bearer + circuit breaker are enforced, retry-on-5xx is NOT applied
        because the file body would be partially consumed on replay.
        """
        if not self._breaker.allow():
            raise CircuitOpenError("cloud circuit open")
        headers = self._build_headers()
        headers.pop("Accept", None)
        try:
            resp = await self._client.post(path, files=files, data=data, headers=headers)
            if resp.status_code >= 500:
                self._breaker.record_failure()
            else:
                self._breaker.record_success()
            return resp
        except asyncio.CancelledError:
            raise
        except (httpx.TransportError, httpx.TimeoutException):
            self._breaker.record_failure()
            raise

    @asynccontextmanager
    async def stream(self, path: str, *, method: str = "GET") -> AsyncIterator[httpx.Response]:
        """Streaming variant. Bearer + breaker enforced; retries are NOT applied
        to streaming requests (the body would be partially consumed).
        """
        if not self._breaker.allow():
            raise CircuitOpenError("cloud circuit open")
        headers = self._build_headers()
        try:
            async with self._client.stream(method, path, headers=headers) as resp:
                if resp.status_code >= 500:
                    self._breaker.record_failure()
                else:
                    self._breaker.record_success()
                yield resp
        except asyncio.CancelledError:
            raise
        except (httpx.TransportError, httpx.TimeoutException):
            self._breaker.record_failure()
            raise

    @asynccontextmanager
    async def stream_post(self, path: str, *, json: Any = None) -> AsyncIterator[httpx.Response]:
        """Streaming POST variant. Passes a JSON body with bearer + breaker
        enforced. Retries are NOT applied (body would be partially consumed).
        """
        if not self._breaker.allow():
            raise CircuitOpenError("cloud circuit open")
        headers = self._build_headers()
        headers["Content-Type"] = "application/json"
        try:
            async with self._client.stream("POST", path, json=json, headers=headers) as resp:
                if resp.status_code >= 500:
                    self._breaker.record_failure()
                else:
                    self._breaker.record_success()
                yield resp
        except asyncio.CancelledError:
            raise
        except (httpx.TransportError, httpx.TimeoutException):
            self._breaker.record_failure()
            raise

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        token = token_store.get_cloud_token()
        if not token:
            raise NotPairedError("no cloud token; pair the desktop first")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        if not self._breaker.allow():
            raise CircuitOpenError("cloud circuit open")

        headers = self._build_headers()
        last_exc: Exception | None = None

        # First attempt + len(_RETRY_DELAYS) retries
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                resp = await self._client.request(
                    method, path, params=params, json=json, headers=headers
                )
            except asyncio.CancelledError:
                raise
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                self._breaker.record_failure()
                if attempt >= len(_RETRY_DELAYS):
                    raise
                await self._sleep(_RETRY_DELAYS[attempt])
                continue

            if resp.status_code < 500:
                # 2xx/3xx/4xx — no retry, breaker registers success for non-5xx.
                self._breaker.record_success()
                return resp

            # 5xx: retry with backoff
            self._breaker.record_failure()
            if attempt >= len(_RETRY_DELAYS):
                return resp  # exhausted; hand back the 5xx for caller to inspect
            await self._sleep(_RETRY_DELAYS[attempt])

        # Unreachable in practice; satisfies type-checker.
        if last_exc:
            raise last_exc
        raise CloudClientError("retry loop exited without response")

    @staticmethod
    async def _sleep(seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            raise


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_singleton: CloudClient | None = None
_singleton_lock = asyncio.Lock()


async def get_cloud_client() -> CloudClient:
    """Return the process-wide :class:`CloudClient` singleton (async-safe)."""
    global _singleton
    if _singleton is not None:
        return _singleton
    async with _singleton_lock:
        if _singleton is None:
            _singleton = CloudClient()
        return _singleton


def reset_cloud_client_for_tests() -> None:
    """Drop the singleton so the next ``get_cloud_client()`` rebuilds it.

    Tests that monkeypatch ``settings.tesslate_cloud_url`` or inject a custom
    transport should call this in teardown.
    """
    global _singleton
    if _singleton is not None:
        # Best-effort sync close; tests typically own their own client anyway.
        import contextlib

        with contextlib.suppress(RuntimeError):
            asyncio.get_event_loop().create_task(_singleton.aclose())
    _singleton = None
