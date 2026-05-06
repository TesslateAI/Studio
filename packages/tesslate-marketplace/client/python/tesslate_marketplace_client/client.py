"""
Async client for the Tesslate federated marketplace `/v1` protocol.

```python
async with AsyncTesslateMarketplaceClient(
    base_url="https://marketplace.tesslate.com",
    token="..."  # optional bearer
) as client:
    manifest = await client.get_manifest()
    items = await client.list_items(kind="agent")
```

Verifies the `X-Tesslate-Hub-Id` header against `pinned_hub_id` if supplied
(orchestrator-side anti-hijack guarantee).
"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import HubIdMismatch, MarketplaceClientError, UnsupportedCapability
from .models import (
    BundleEnvelope,
    CategoryList,
    ChangesFeed,
    CheckoutResponse,
    FeaturedList,
    HubManifest,
    ItemDetail,
    ItemList,
    ItemVersion,
    Review,
    ReviewAggregate,
    ReviewList,
    Submission,
    Yank,
)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class AsyncTesslateMarketplaceClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        pinned_hub_id: str | None = None,
        timeout: httpx.Timeout | float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )
        self._pinned_hub_id = pinned_hub_id

    async def __aenter__(self) -> "AsyncTesslateMarketplaceClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _check_hub_id(self, response: httpx.Response) -> str:
        actual = response.headers.get("X-Tesslate-Hub-Id")
        if not actual:
            raise MarketplaceClientError("missing X-Tesslate-Hub-Id header on response")
        if self._pinned_hub_id and actual != self._pinned_hub_id:
            raise HubIdMismatch(self._pinned_hub_id, actual)
        return actual

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._http.request(method, path, **kwargs)
        self._check_hub_id(response)
        if response.status_code == 501:
            payload = response.json()
            raise UnsupportedCapability(
                capability=payload.get("capability", "unknown"),
                hub_id=payload.get("hub_id", "unknown"),
                details=payload.get("details"),
            )
        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = {"raw": response.text}
            raise MarketplaceClientError(f"{method} {path} failed: {response.status_code} {detail!r}")
        return response

    # -----------------------------------------------------------------
    # Manifest
    # -----------------------------------------------------------------

    async def get_manifest(self) -> HubManifest:
        r = await self._request("GET", "/v1/manifest")
        return HubManifest.model_validate(r.json())

    # -----------------------------------------------------------------
    # Items
    # -----------------------------------------------------------------

    async def list_items(
        self,
        *,
        kind: str | None = None,
        category: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        sort: str | None = None,
    ) -> ItemList:
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
        r = await self._request("GET", "/v1/items", params=params)
        return ItemList.model_validate(r.json())

    async def get_item(self, kind: str, slug: str) -> ItemDetail:
        r = await self._request("GET", f"/v1/items/{kind}/{slug}")
        return ItemDetail.model_validate(r.json())

    async def list_versions(self, kind: str, slug: str) -> list[ItemVersion]:
        r = await self._request("GET", f"/v1/items/{kind}/{slug}/versions")
        return [ItemVersion.model_validate(v) for v in r.json()]

    async def get_version(self, kind: str, slug: str, version: str) -> ItemVersion:
        r = await self._request("GET", f"/v1/items/{kind}/{slug}/versions/{version}")
        return ItemVersion.model_validate(r.json())

    async def get_bundle(self, kind: str, slug: str, version: str) -> BundleEnvelope:
        r = await self._request("GET", f"/v1/items/{kind}/{slug}/versions/{version}/bundle")
        return BundleEnvelope.model_validate(r.json())

    async def download_bundle(self, kind: str, slug: str, version: str) -> bytes:
        envelope = await self.get_bundle(kind, slug, version)
        # The signed URL may point back at us OR at a remote backend.
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as raw:
            response = await raw.get(envelope.url)
            response.raise_for_status()
            return response.content

    # -----------------------------------------------------------------
    # Categories + featured
    # -----------------------------------------------------------------

    async def list_categories(self, kind: str | None = None) -> CategoryList:
        params = {"kind": kind} if kind else {}
        r = await self._request("GET", "/v1/categories", params=params)
        return CategoryList.model_validate(r.json())

    async def list_featured(self, kind: str | None = None) -> FeaturedList:
        params = {"kind": kind} if kind else {}
        r = await self._request("GET", "/v1/featured", params=params)
        return FeaturedList.model_validate(r.json())

    # -----------------------------------------------------------------
    # Changes / yanks feed
    # -----------------------------------------------------------------

    async def get_changes(self, since: str | None = None, limit: int | None = None) -> ChangesFeed:
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if limit is not None:
            params["limit"] = limit
        r = await self._request("GET", "/v1/changes", params=params)
        return ChangesFeed.model_validate(r.json())

    async def get_yanks_feed(self, since: str | None = None, limit: int | None = None) -> ChangesFeed:
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if limit is not None:
            params["limit"] = limit
        r = await self._request("GET", "/v1/yanks", params=params)
        return ChangesFeed.model_validate(r.json())

    # -----------------------------------------------------------------
    # Reviews
    # -----------------------------------------------------------------

    async def list_reviews(self, kind: str, slug: str) -> ReviewList:
        r = await self._request("GET", f"/v1/items/{kind}/{slug}/reviews")
        return ReviewList.model_validate(r.json())

    async def get_review_aggregate(self, kind: str, slug: str) -> ReviewAggregate:
        r = await self._request("GET", f"/v1/items/{kind}/{slug}/reviews/aggregate")
        return ReviewAggregate.model_validate(r.json())

    async def write_review(self, kind: str, slug: str, payload: dict[str, Any]) -> Review:
        r = await self._request("POST", f"/v1/items/{kind}/{slug}/reviews", json=payload)
        return Review.model_validate(r.json())

    # -----------------------------------------------------------------
    # Pricing
    # -----------------------------------------------------------------

    async def get_pricing(self, kind: str, slug: str) -> dict[str, Any]:
        r = await self._request("GET", f"/v1/items/{kind}/{slug}/pricing")
        return r.json()

    async def create_checkout(self, kind: str, slug: str, payload: dict[str, Any] | None = None) -> CheckoutResponse:
        r = await self._request("POST", f"/v1/items/{kind}/{slug}/checkout", json=payload or {})
        return CheckoutResponse.model_validate(r.json())

    # -----------------------------------------------------------------
    # Publish
    # -----------------------------------------------------------------

    async def publish(self, kind: str, payload: dict[str, Any]) -> Submission:
        r = await self._request("POST", f"/v1/publish/{kind}", json=payload)
        return Submission.model_validate(r.json())

    async def get_submission(self, submission_id: str) -> Submission:
        r = await self._request("GET", f"/v1/submissions/{submission_id}")
        return Submission.model_validate(r.json())

    async def withdraw_submission(self, submission_id: str) -> Submission:
        r = await self._request("POST", f"/v1/submissions/{submission_id}/withdraw")
        return Submission.model_validate(r.json())

    # -----------------------------------------------------------------
    # Yanks
    # -----------------------------------------------------------------

    async def create_yank(self, payload: dict[str, Any]) -> Yank:
        r = await self._request("POST", "/v1/yanks", json=payload)
        return Yank.model_validate(r.json())

    async def get_yank(self, yank_id: str) -> Yank:
        r = await self._request("GET", f"/v1/yanks/{yank_id}")
        return Yank.model_validate(r.json())

    async def appeal_yank(self, yank_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self._request("POST", f"/v1/yanks/{yank_id}/appeal", json=payload)
        return r.json()

    # -----------------------------------------------------------------
    # Telemetry
    # -----------------------------------------------------------------

    async def post_install_telemetry(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self._request("POST", "/v1/telemetry/install", json=payload)
        return r.json()

    async def post_usage_telemetry(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = await self._request("POST", "/v1/telemetry/usage", json=payload)
        return r.json()
