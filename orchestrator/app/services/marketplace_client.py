"""
Federated marketplace HTTP client (orchestrator → marketplace hub).

Wraps :class:`httpx.AsyncClient` with the federation-specific behaviors
called out in the Wave-3 plan:

  - **Bearer injection**: per-instance bearer token (already decrypted by the
    caller via ``services/credential_manager.py``). Never stored in the DB
    by this class.
  - **Hub-id pinning**: every response carries ``X-Tesslate-Hub-Id``. If the
    instance was constructed with a non-null ``pinned_hub_id`` and the value
    diverges, the request fails fast with :class:`HubIdMismatchError`. The
    first request after construction (with no pin) records the value via
    :pyattr:`MarketplaceClient.last_seen_hub_id` so the caller can persist it.
  - **ETag conditional GETs**: list / changes / categories / featured calls
    accept ``if_none_match=`` and short-circuit on ``304 Not Modified`` to
    :data:`NOT_MODIFIED`, so the sync worker can skip the upsert pass.
  - **Bounded retries with jitter**: 429 and 5xx responses retry up to
    3 attempts with exponential back-off + jitter. 401/403/404 do NOT retry.
  - **Circuit breaker**: per-base-url consecutive-failure counter; 5 failures
    inside 60s opens the breaker for 30s; further calls fail fast with
    :class:`CircuitOpenError`. In-memory only — does not survive process
    restart, which is acceptable for a cron-style sync worker that re-tests
    on the next tick.
  - **``local://`` short-circuit**: instances constructed against a sentinel
    ``local://...`` base URL never make HTTP calls; ``is_local_source`` is
    ``True`` and any verb raises :class:`NotImplementedError`. The federation
    facade routes ``local`` sources to ``marketplace_local.py`` instead
    (Wave 6).

Mirror the patterns in ``services/cloud_client.py`` for consistency.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final, Literal, cast

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Retry budget (initial attempt + 2 retries = 3 total).
_MAX_RETRIES: Final[int] = 2
_BACKOFF_BASE_SECONDS: Final[float] = 0.5
_BACKOFF_MAX_SECONDS: Final[float] = 5.0
_BACKOFF_JITTER_FRACTION: Final[float] = 0.25

# Circuit breaker: consecutive failures inside the window opens the breaker.
_CB_FAILURE_THRESHOLD: Final[int] = 5
_CB_FAILURE_WINDOW_S: Final[float] = 60.0
_CB_OPEN_DURATION_S: Final[float] = 30.0

# Pool / timeouts (matches cloud_client values).
_POOL_LIMITS: Final[httpx.Limits] = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=5,
)

# HTTP status codes that should retry vs hard-fail.
_RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({408, 425, 429, 500, 502, 503, 504})
_TERMINAL_NON_RETRY_STATUSES: Final[frozenset[int]] = frozenset({401, 403, 404, 410, 451})

# Header / sentinel constants.
HUB_ID_HEADER: Final[str] = "X-Tesslate-Hub-Id"
HUB_API_VERSION_HEADER: Final[str] = "X-Tesslate-Hub-Api-Version"
ETAG_HEADER: Final[str] = "ETag"
LOCAL_URL_PREFIX: Final[str] = "local://"


class _NotModifiedSentinel:
    """Singleton sentinel returned by ETag-aware GETs on 304."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "<NOT_MODIFIED>"

    def __bool__(self) -> bool:
        return False


NOT_MODIFIED: Final[_NotModifiedSentinel] = _NotModifiedSentinel()


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class MarketplaceClientError(Exception):
    """Base for every error raised by :class:`MarketplaceClient`."""

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        status_code: int | None = None,
        hub_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.hub_id = hub_id


class HubIdMismatchError(MarketplaceClientError):
    """The hub returned a ``X-Tesslate-Hub-Id`` that differs from the pin."""

    def __init__(self, expected: str, actual: str, *, url: str | None = None) -> None:
        super().__init__(
            f"hub_id mismatch: expected={expected!r} actual={actual!r} url={url!r}",
            url=url,
            hub_id=actual,
        )
        self.expected = expected
        self.actual = actual


class UnsupportedCapabilityError(MarketplaceClientError):
    """The hub returned a typed ``unsupported_capability`` envelope (HTTP 501)."""

    def __init__(
        self,
        capability: str,
        *,
        hub_id: str | None,
        details: str | None,
        url: str | None = None,
    ) -> None:
        super().__init__(
            f"capability {capability!r} not implemented by hub {hub_id!r}",
            url=url,
            status_code=501,
            hub_id=hub_id,
        )
        self.capability = capability
        self.details = details


class BundleSizeExceededError(MarketplaceClientError):
    """A bundle envelope advertised a size larger than the hub's policy max."""

    def __init__(self, kind: str, slug: str, version: str, size_bytes: int, max_bytes: int) -> None:
        super().__init__(
            f"bundle {kind}/{slug}@{version} size={size_bytes} exceeds policy max={max_bytes}",
        )
        self.kind = kind
        self.slug = slug
        self.version = version
        self.size_bytes = size_bytes
        self.max_bytes = max_bytes


class MarketplaceAuthError(MarketplaceClientError):
    """The hub rejected the bearer token (401 or 403)."""


class MarketplaceNotFoundError(MarketplaceClientError):
    """The hub returned 404 for the requested item / version / submission."""


class MarketplaceServerError(MarketplaceClientError):
    """The hub returned a 5xx (after exhausting retries) or terminal upstream error."""


class CircuitOpenError(MarketplaceClientError):
    """Circuit breaker is open; the hub is being given time to recover."""


class MalformedResponseError(MarketplaceClientError):
    """Response could not be parsed (bad JSON, missing required header, etc.)."""


class LocalSourceNotSupportedError(MarketplaceClientError):
    """A network verb was called on a ``local://`` short-circuited client."""


# ---------------------------------------------------------------------------
# Circuit breaker (per-base-url, in-memory).
# ---------------------------------------------------------------------------


class _CircuitBreaker:
    """Sliding-window consecutive-failure breaker; asyncio-safe (single-threaded)."""

    __slots__ = ("_failures", "_opened_at")

    def __init__(self) -> None:
        self._failures: list[float] = []
        self._opened_at: float | None = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if time.monotonic() - self._opened_at >= _CB_OPEN_DURATION_S:
            # Half-open: let one request through. record_success closes,
            # record_failure re-opens.
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
                "marketplace_client: circuit opened after %d failures in %.0fs",
                len(self._failures),
                _CB_FAILURE_WINDOW_S,
            )


# Process-wide circuit breakers keyed on normalized base_url. Tests can clear
# this to reset state between cases.
_BREAKERS: dict[str, _CircuitBreaker] = {}


def _get_breaker(base_url: str) -> _CircuitBreaker:
    breaker = _BREAKERS.get(base_url)
    if breaker is None:
        breaker = _CircuitBreaker()
        _BREAKERS[base_url] = breaker
    return breaker


def reset_circuit_breakers_for_tests() -> None:
    """Drop every cached circuit breaker. Call from test teardown."""
    _BREAKERS.clear()


# ---------------------------------------------------------------------------
# Result type aliases
# ---------------------------------------------------------------------------


JsonObject = dict[str, Any]
ConditionalResult = JsonObject | _NotModifiedSentinel


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


class MarketplaceClient:
    """Async wrapper over the federated-marketplace ``/v1`` protocol.

    Construct one instance per :class:`MarketplaceSource` (the sync worker
    re-creates instances per tick — it's cheap and avoids token reuse across
    sources). Use as an async context manager so the underlying
    :class:`httpx.AsyncClient` is closed cleanly::

        async with MarketplaceClient(source.base_url, token=plain_token,
                                     pinned_hub_id=source.pinned_hub_id) as cli:
            manifest = await cli.get_manifest()
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        pinned_hub_id: str | None = None,
        timeout_seconds: int = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._pinned_hub_id = pinned_hub_id
        self._last_seen_hub_id: str | None = None
        self._is_local = self._base_url.startswith(LOCAL_URL_PREFIX)
        self._closed = False

        if self._is_local:
            # No HTTP machinery for local sources — keep the attribute so tests
            # can still inspect ``base_url`` / ``token`` without surprise.
            self._http: httpx.AsyncClient | None = None
            self._breaker = _CircuitBreaker()  # unused, for shape-consistency
            return

        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        timeout = httpx.Timeout(float(timeout_seconds), connect=min(10.0, float(timeout_seconds)))

        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
            limits=_POOL_LIMITS,
            transport=transport,
        )
        self._breaker = _get_breaker(self._base_url)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def is_local_source(self) -> bool:
        return self._is_local

    @property
    def pinned_hub_id(self) -> str | None:
        return self._pinned_hub_id

    @property
    def last_seen_hub_id(self) -> str | None:
        """The most recent ``X-Tesslate-Hub-Id`` returned, for first-pin
        persistence by the caller."""
        return self._last_seen_hub_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> MarketplaceClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._http is not None:
            await self._http.aclose()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _refuse_local(self, verb: str) -> None:
        if self._is_local:
            raise LocalSourceNotSupportedError(
                f"local:// source ({self._base_url!r}) cannot perform HTTP verb {verb!r}; "
                "route via marketplace_local.py instead",
                url=self._base_url,
            )

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        # Exponential with capped + jittered output.
        raw = min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * (2**attempt))
        jitter = raw * _BACKOFF_JITTER_FRACTION * (2 * random.random() - 1)
        return max(0.0, raw + jitter)

    @staticmethod
    async def _sleep(seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            raise

    def _check_hub_id(self, response: httpx.Response, *, url: str) -> str:
        actual = response.headers.get(HUB_ID_HEADER)
        if not actual:
            raise MalformedResponseError(
                f"missing {HUB_ID_HEADER} header on response",
                url=url,
                status_code=response.status_code,
            )
        if self._pinned_hub_id and actual != self._pinned_hub_id:
            raise HubIdMismatchError(self._pinned_hub_id, actual, url=url)
        # Always record what we saw so the first call can prime the pin.
        self._last_seen_hub_id = actual
        return actual

    @staticmethod
    def _safe_json(response: httpx.Response, url: str) -> JsonObject:
        try:
            payload = response.json()
        except Exception as exc:
            raise MalformedResponseError(
                f"response JSON decode failed: {exc}",
                url=url,
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise MalformedResponseError(
                f"response JSON is not an object (got {type(payload).__name__})",
                url=url,
                status_code=response.status_code,
            )
        return cast(JsonObject, payload)

    def _raise_for_unsupported_capability(
        self, response: httpx.Response, *, url: str, hub_id: str | None
    ) -> None:
        # 501 envelope shape: {"error": "unsupported_capability", "capability": "...", "hub_id": "...", "details": "..."}
        try:
            payload = response.json()
        except Exception:
            payload = {}
        capability = payload.get("capability") if isinstance(payload, dict) else None
        details = payload.get("details") if isinstance(payload, dict) else None
        raise UnsupportedCapabilityError(
            capability or "unknown",
            hub_id=hub_id,
            details=details,
            url=url,
        )

    def _classify_status_error(
        self, response: httpx.Response, *, url: str, hub_id: str | None
    ) -> MarketplaceClientError:
        code = response.status_code
        # Pull error body for context but tolerate non-JSON bodies.
        try:
            body = response.json()
        except Exception:
            body = {"raw": (response.text or "")[:500]}
        message = f"{response.request.method} {url} -> {code}: {body!r}"
        if code in (401, 403):
            return MarketplaceAuthError(message, url=url, status_code=code, hub_id=hub_id)
        if code == 404:
            return MarketplaceNotFoundError(message, url=url, status_code=code, hub_id=hub_id)
        if code >= 500:
            return MarketplaceServerError(message, url=url, status_code=code, hub_id=hub_id)
        return MarketplaceClientError(message, url=url, status_code=code, hub_id=hub_id)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        allow_304: bool = False,
    ) -> httpx.Response:
        """Issue one logical request with retry + breaker + hub-id verification."""
        self._refuse_local(method)
        assert self._http is not None  # narrowing — _is_local guards above

        if not self._breaker.allow():
            raise CircuitOpenError(
                f"marketplace circuit open for {self._base_url!r}",
                url=self._base_url,
            )

        attempt = 0
        last_exc: Exception | None = None
        full_url = f"{self._base_url}{path}"

        while True:
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
            except asyncio.CancelledError:
                raise
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                self._breaker.record_failure()
                if attempt >= _MAX_RETRIES:
                    raise MarketplaceServerError(
                        f"transport error contacting {full_url}: {exc}",
                        url=full_url,
                    ) from exc
                await self._sleep(self._backoff_seconds(attempt))
                attempt += 1
                continue

            # Hub-id verification fires on every response (including 5xx), so
            # an attacker swapping the hub mid-flight cannot evade detection
            # by serving an error code. The marketplace service includes the
            # header on errors too (see app/main.py middleware).
            try:
                hub_id = self._check_hub_id(response, url=full_url)
            except (HubIdMismatchError, MalformedResponseError):
                # Hub-id problems do not retry — they're either a config /
                # hijack issue (mismatch) or a misbehaving hub (missing
                # header). Re-raise so the sync worker logs and disables.
                self._breaker.record_failure()
                raise

            status = response.status_code

            # Success path
            if 200 <= status < 300:
                self._breaker.record_success()
                return response

            if status == 304 and allow_304:
                self._breaker.record_success()
                return response

            if status == 501:
                # Unsupported capability is structured + non-retryable.
                self._breaker.record_success()  # the hub is responsive
                self._raise_for_unsupported_capability(response, url=full_url, hub_id=hub_id)

            if status in _TERMINAL_NON_RETRY_STATUSES:
                # 4xx that we surface verbatim — record as a "soft" success
                # for the breaker (the hub answered) but raise a typed error.
                self._breaker.record_success()
                raise self._classify_status_error(response, url=full_url, hub_id=hub_id)

            if status in _RETRYABLE_STATUSES:
                self._breaker.record_failure()
                if attempt >= _MAX_RETRIES:
                    raise self._classify_status_error(response, url=full_url, hub_id=hub_id)
                # Honor Retry-After when present; otherwise jittered backoff.
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = self._backoff_seconds(attempt)
                else:
                    delay = self._backoff_seconds(attempt)
                await self._sleep(delay)
                attempt += 1
                continue

            # Any other 4xx that wasn't called out — surface verbatim.
            self._breaker.record_success()
            raise self._classify_status_error(response, url=full_url, hub_id=hub_id)

        # Unreachable in practice; satisfies type-checker.
        if last_exc:  # pragma: no cover
            raise last_exc
        raise MarketplaceServerError("retry loop exited without response", url=full_url)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> JsonObject:
        response = await self._request(
            method, path, params=params, json_body=json_body, headers=headers
        )
        return self._safe_json(response, f"{self._base_url}{path}")

    async def _request_conditional(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        if_none_match: str | None = None,
    ) -> ConditionalResult:
        headers: dict[str, str] = {}
        if if_none_match:
            headers["If-None-Match"] = if_none_match
        response = await self._request(
            method,
            path,
            params=params,
            headers=headers or None,
            allow_304=True,
        )
        if response.status_code == 304:
            return NOT_MODIFIED
        return self._safe_json(response, f"{self._base_url}{path}")

    # ==================================================================
    # Public verbs — every /v1 endpoint of the protocol.
    # ==================================================================

    # ---------- Manifest ----------

    async def get_manifest(self) -> JsonObject:
        return await self._request_json("GET", "/v1/manifest")

    # ---------- Catalog (list / detail / versions) ----------

    async def list_items(
        self,
        *,
        kind: str | None = None,
        category: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        sort: str | None = None,
        if_none_match: str | None = None,
    ) -> ConditionalResult:
        params: dict[str, Any] = {}
        if kind:
            params["kind"] = kind
        if category:
            params["category"] = category
        if q:
            params["q"] = q
        if cursor:
            params["cursor"] = cursor
        if limit is not None:
            params["limit"] = limit
        if sort:
            params["sort"] = sort
        return await self._request_conditional(
            "GET", "/v1/items", params=params or None, if_none_match=if_none_match
        )

    async def get_item(self, kind: str, slug: str) -> JsonObject:
        return await self._request_json("GET", f"/v1/items/{kind}/{slug}")

    async def list_versions(self, kind: str, slug: str) -> list[JsonObject]:
        # The /versions endpoint returns a JSON array (not an object), so we
        # cannot reuse _request_json. Re-validate type explicitly.
        url = f"/v1/items/{kind}/{slug}/versions"
        response = await self._request("GET", url)
        try:
            payload = response.json()
        except Exception as exc:
            raise MalformedResponseError(
                f"response JSON decode failed: {exc}",
                url=f"{self._base_url}{url}",
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, list):
            raise MalformedResponseError(
                f"expected JSON array; got {type(payload).__name__}",
                url=f"{self._base_url}{url}",
                status_code=response.status_code,
            )
        return [v for v in payload if isinstance(v, dict)]

    async def get_version(self, kind: str, slug: str, version: str) -> JsonObject:
        return await self._request_json("GET", f"/v1/items/{kind}/{slug}/versions/{version}")

    async def get_bundle(self, kind: str, slug: str, version: str) -> JsonObject:
        return await self._request_json("GET", f"/v1/items/{kind}/{slug}/versions/{version}/bundle")

    async def get_attestation(self, kind: str, slug: str, version: str) -> JsonObject:
        return await self._request_json(
            "GET", f"/v1/items/{kind}/{slug}/versions/{version}/attestation"
        )

    # ---------- Categories + featured ----------

    async def list_categories(
        self, *, kind: str | None = None, if_none_match: str | None = None
    ) -> ConditionalResult:
        params = {"kind": kind} if kind else None
        return await self._request_conditional(
            "GET", "/v1/categories", params=params, if_none_match=if_none_match
        )

    async def list_featured(
        self, *, kind: str | None = None, if_none_match: str | None = None
    ) -> ConditionalResult:
        params = {"kind": kind} if kind else None
        return await self._request_conditional(
            "GET", "/v1/featured", params=params, if_none_match=if_none_match
        )

    # ---------- Changes / yanks feeds ----------

    async def get_changes(
        self,
        *,
        since: str | None = None,
        limit: int | None = None,
        if_none_match: str | None = None,
    ) -> ConditionalResult:
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if limit is not None:
            params["limit"] = limit
        return await self._request_conditional(
            "GET", "/v1/changes", params=params or None, if_none_match=if_none_match
        )

    async def get_yanks(self, *, since: str | None = None, limit: int | None = None) -> JsonObject:
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if limit is not None:
            params["limit"] = limit
        return await self._request_json("GET", "/v1/yanks", params=params or None)

    # ---------- Reviews ----------

    async def list_reviews(self, kind: str, slug: str) -> JsonObject:
        return await self._request_json("GET", f"/v1/items/{kind}/{slug}/reviews")

    async def get_review_aggregate(self, kind: str, slug: str) -> JsonObject:
        return await self._request_json("GET", f"/v1/items/{kind}/{slug}/reviews/aggregate")

    async def post_review(self, kind: str, slug: str, payload: JsonObject) -> JsonObject:
        return await self._request_json(
            "POST", f"/v1/items/{kind}/{slug}/reviews", json_body=payload
        )

    # ---------- Pricing + checkout ----------

    async def get_pricing(self, kind: str, slug: str) -> JsonObject:
        return await self._request_json("GET", f"/v1/items/{kind}/{slug}/pricing")

    async def post_checkout(
        self, kind: str, slug: str, *, payload: JsonObject | None = None
    ) -> JsonObject:
        return await self._request_json(
            "POST",
            f"/v1/items/{kind}/{slug}/checkout",
            json_body=payload or {},
        )

    async def create_checkout(
        self,
        kind: str,
        slug: str,
        *,
        version: str | None = None,
        requester_email: str | None = None,
        success_url: str | None = None,
        cancel_url: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> JsonObject:
        """Convenience wrapper for the Wave-9 hub-checkout dispatch path.

        Mirrors the marketplace service's
        ``packages/tesslate-marketplace/app/routers/pricing.py::create_checkout``
        request envelope (see ``CheckoutRequest`` in the marketplace
        package's ``schemas.py``):

            {
              "customer_email": "<requester_email>",
              "success_url":   "<orchestrator success URL>",
              "cancel_url":    "<orchestrator cancel URL>",
              "metadata":      { ... }
            }

        And returns the hub's response envelope verbatim
        (``CheckoutResponse``):

            {
              "checkout_url": "https://...",
              "session_id":   "cs_test_...",
              "mode":         "live" | "dev_simulator",
              "expires_at":   "..." | null
            }

        ``version`` is forwarded as metadata so the hub can pin the
        purchase to a specific catalog version (some hubs price per
        version — the Tesslate marketplace doesn't currently, but the
        protocol allows it). Failures bubble up as the same typed
        :class:`MarketplaceClientError` subclasses every other verb
        raises (``MarketplaceAuthError``, ``MarketplaceNotFoundError``,
        ``UnsupportedCapabilityError``, ``HubIdMismatchError``, etc).
        """
        payload: dict[str, Any] = {}
        if requester_email:
            payload["customer_email"] = requester_email
        if success_url:
            payload["success_url"] = success_url
        if cancel_url:
            payload["cancel_url"] = cancel_url
        meta = dict(metadata or {})
        if version is not None:
            meta.setdefault("version", version)
        if meta:
            payload["metadata"] = meta
        return await self.post_checkout(kind, slug, payload=payload)

    # ---------- Publish / submissions ----------

    async def publish(self, kind: str, payload: JsonObject) -> JsonObject:
        return await self._request_json("POST", f"/v1/publish/{kind}", json_body=payload)

    async def publish_version(
        self, kind: str, slug: str, version: str, payload: JsonObject
    ) -> JsonObject:
        return await self._request_json(
            "POST",
            f"/v1/publish/{kind}/{slug}/versions/{version}",
            json_body=payload,
        )

    async def create_submission(
        self,
        *,
        kind: str,
        payload: JsonObject,
    ) -> JsonObject:
        """Wave 8: orchestrator-side wrapper for ``POST /v1/publish/{kind}``.

        Named ``create_submission`` to match the orchestrator's
        proxy-router vocabulary (``app_submissions.py`` calls
        ``create_submission`` to mean "open a new submission row in the
        marketplace's authoritative DB"). The hub treats this as the
        same publish endpoint — the verb name is local to the
        orchestrator.
        """
        return await self.publish(kind=kind, payload=payload)

    async def get_submission(self, submission_id: str) -> JsonObject:
        return await self._request_json("GET", f"/v1/submissions/{submission_id}")

    async def advance_submission(self, submission_id: str) -> JsonObject:
        """Wave 8: drive a submission through the next stage.

        Maps to ``POST /v1/submissions/{id}/advance`` — the marketplace
        runs the appropriate scanner (stage1 / stage2) for the row's
        current stage, records every check, and updates the stage
        column. Idempotent on terminal rows.
        """
        return await self._request_json("POST", f"/v1/submissions/{submission_id}/advance")

    async def finalize_submission(
        self,
        submission_id: str,
        *,
        decision: str,
        decision_reason: str | None = None,
    ) -> JsonObject:
        """Wave 8: terminal-decision write for a submission.

        Maps to ``POST /v1/submissions/{id}/finalize``. Approval requires
        the row to be at ``stage3``; rejection is allowed from any
        non-terminal stage. The marketplace enforces both rules
        server-side; the orchestrator just forwards.
        """
        body: JsonObject = {"decision": decision}
        if decision_reason is not None:
            body["decision_reason"] = decision_reason
        return await self._request_json(
            "POST", f"/v1/submissions/{submission_id}/finalize", json_body=body
        )

    async def withdraw_submission(self, submission_id: str) -> JsonObject:
        return await self._request_json("POST", f"/v1/submissions/{submission_id}/withdraw")

    # ---------- Admin overrides (Wave 8, requires admin.write scope) ----------

    async def admin_force_approve_submission(
        self,
        submission_id: str,
        *,
        decision_reason: str | None = None,
        skip_remaining_stages: bool = True,
    ) -> JsonObject:
        body: JsonObject = {"skip_remaining_stages": skip_remaining_stages}
        if decision_reason is not None:
            body["decision_reason"] = decision_reason
        return await self._request_json(
            "POST",
            f"/v1/admin/submissions/{submission_id}/force-approve",
            json_body=body,
        )

    async def admin_force_reject_submission(
        self,
        submission_id: str,
        *,
        decision_reason: str,
    ) -> JsonObject:
        return await self._request_json(
            "POST",
            f"/v1/admin/submissions/{submission_id}/force-reject",
            json_body={"decision_reason": decision_reason},
        )

    async def admin_override_yank(
        self,
        yank_id: str,
        *,
        new_state: str,
        resolution: str | None = None,
        note: str | None = None,
    ) -> JsonObject:
        body: JsonObject = {"new_state": new_state}
        if resolution is not None:
            body["resolution"] = resolution
        if note is not None:
            body["note"] = note
        return await self._request_json(
            "POST", f"/v1/admin/yanks/{yank_id}/override", json_body=body
        )

    # ---------- Yanks + appeals ----------

    async def request_yank(self, payload: JsonObject) -> JsonObject:
        return await self._request_json("POST", "/v1/yanks", json_body=payload)

    async def publish_yank(
        self,
        *,
        kind: str,
        slug: str,
        version: str | None,
        reason: str,
        severity: str,
        requested_by: str | None = None,
    ) -> JsonObject:
        """Publish an orchestrator-side yank decision back to the hub.

        Wave 7: when the orchestrator approves a :class:`YankRequest` for a
        federated app version (via ``services/apps/yanks.py``), it must
        propagate the decision to the source hub so other orchestrators
        consuming the same hub's ``/v1/yanks`` feed pick up the yank on
        their next sync tick.

        The hub's ``POST /v1/yanks`` endpoint requires the ``yanks.write``
        scope on the bearer token used by this client. The caller is
        responsible for ensuring the source row's stored token carries that
        scope; tokens that don't will surface as :class:`MarketplaceAuthError`
        (401/403) which the caller should log and surface to the operator
        without aborting the local yank — the local catalog already
        reflects the yank, and a missing upstream propagation is a
        recoverable condition the operator can retry.
        """
        payload: JsonObject = {
            "kind": kind,
            "slug": slug,
            "severity": severity,
            "reason": reason,
        }
        if version is not None:
            payload["version"] = version
        if requested_by is not None:
            payload["requested_by"] = requested_by
        return await self._request_json("POST", "/v1/yanks", json_body=payload)

    async def appeal_yank(self, yank_id: str, payload: JsonObject) -> JsonObject:
        return await self._request_json("POST", f"/v1/yanks/{yank_id}/appeal", json_body=payload)

    async def get_yank(self, yank_id: str) -> JsonObject:
        return await self._request_json("GET", f"/v1/yanks/{yank_id}")

    # ---------- Telemetry ----------

    async def post_telemetry_install(self, payload: JsonObject) -> JsonObject:
        return await self._request_json("POST", "/v1/telemetry/install", json_body=payload)

    async def post_telemetry_usage(self, payload: JsonObject) -> JsonObject:
        return await self._request_json("POST", "/v1/telemetry/usage", json_body=payload)

    # ------------------------------------------------------------------
    # Streaming helper for bundle downloads (used by Wave 4 installer).
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def stream_bundle(self, signed_url: str) -> AsyncIterator[httpx.Response]:
        """Stream a signed bundle URL.

        The signed URL may point at the hub itself OR at an external CDN
        (S3, R2, Volume Hub). Either way we MUST NOT include our bearer
        token — the URL carries its own signature.
        """
        self._refuse_local("stream_bundle")
        # Bare client (no auth header, no breaker — the URL is one-shot).
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                limits=_POOL_LIMITS,
            ) as raw,
            raw.stream("GET", signed_url) as response,
        ):
            response.raise_for_status()
            yield response


# ---------------------------------------------------------------------------
# Convenience factory used by the sync worker
# ---------------------------------------------------------------------------


def make_client_from_source(
    source: Any | None = None,
    *,
    decrypted_token: str | None = None,
    base_url: str | None = None,
    pinned_hub_id: str | None = None,
    timeout_seconds: int = 10,
    transport: httpx.AsyncBaseTransport | None = None,
) -> MarketplaceClient:
    """Construct a :class:`MarketplaceClient` from a :class:`MarketplaceSource` row.

    The token MUST already be decrypted by the caller (e.g. via
    ``credential_manager.safe_decrypt_token``) — this function never touches
    the DB or crypto. ``source`` is duck-typed (anything exposing ``base_url``
    and ``pinned_hub_id``) so callers can pass a row, a mock, or omit it and
    use the explicit ``base_url`` / ``pinned_hub_id`` kwargs.
    """
    if source is not None:
        if base_url is None:
            base_url = source.base_url
        if pinned_hub_id is None:
            pinned_hub_id = getattr(source, "pinned_hub_id", None)
    if base_url is None:
        raise TypeError("make_client_from_source requires source or base_url")
    return MarketplaceClient(
        base_url=base_url,
        token=decrypted_token,
        pinned_hub_id=pinned_hub_id,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )


# Backwards-compat aliases used by the federation facade naming.
TrustLevel = Literal["official", "admin_trusted", "local", "private", "untrusted"]


__all__ = [
    "BundleSizeExceededError",
    "CircuitOpenError",
    "ConditionalResult",
    "ETAG_HEADER",
    "HUB_API_VERSION_HEADER",
    "HUB_ID_HEADER",
    "HubIdMismatchError",
    "JsonObject",
    "LOCAL_URL_PREFIX",
    "LocalSourceNotSupportedError",
    "MalformedResponseError",
    "MarketplaceAuthError",
    "MarketplaceClient",
    "MarketplaceClientError",
    "MarketplaceNotFoundError",
    "MarketplaceServerError",
    "NOT_MODIFIED",
    "TrustLevel",
    "UnsupportedCapabilityError",
    "make_client_from_source",
    "reset_circuit_breakers_for_tests",
]
