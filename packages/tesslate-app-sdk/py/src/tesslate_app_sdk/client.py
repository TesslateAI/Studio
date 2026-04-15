"""Async Tesslate Apps SDK client.

All network I/O runs over httpx. The client is context-manager friendly so
callers can share a single TCP pool:

    async with AppClient(options) as client:
        version = await client.get_version_info()

Authentication: ``Authorization: Bearer <api_key>`` where ``api_key`` is a
Tesslate external API key (``tsk_...``). Because every request is
Bearer-authenticated, the server's CSRF middleware does not engage — this
SDK never needs a CSRF cookie/header.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx

from .manifest import AppManifest_2025_01

__all__ = ["AppClient", "AppSdkOptions", "AppSdkHttpError"]


@dataclass
class AppSdkOptions:
    base_url: str
    api_key: str
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if not self.api_key or not self.api_key.startswith("tsk_"):
            raise ValueError(
                "AppSdkOptions.api_key must be a Tesslate external API key (starts with 'tsk_')"
            )
        if not self.base_url:
            raise ValueError("AppSdkOptions.base_url is required")
        self.base_url = self.base_url.rstrip("/")


class AppSdkHttpError(Exception):
    def __init__(self, status: int, message: str, body: Any) -> None:
        super().__init__(f"{status} {message}")
        self.status = status
        self.body = body


class AppClient:
    """Async client for the Tesslate Apps REST surface."""

    def __init__(
        self,
        options: AppSdkOptions,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._options = options
        self._client = httpx.AsyncClient(
            base_url=options.base_url,
            timeout=options.timeout,
            headers={
                "Authorization": f"Bearer {options.api_key}",
                "Accept": "application/json",
            },
            transport=transport,
        )

    # ---- context manager -----------------------------------------------------

    async def __aenter__(self) -> AppClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- Version lifecycle ---------------------------------------------------

    async def publish_version(
        self,
        *,
        project_id: str,
        manifest: AppManifest_2025_01 | dict[str, Any],
        app_id: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(manifest, AppManifest_2025_01):
            manifest_payload: Any = manifest.to_dict()
        else:
            manifest_payload = manifest
        body = {
            "project_id": project_id,
            "manifest": manifest_payload,
            "app_id": app_id,
        }
        return await self._request("POST", "/api/app-versions/publish", json=body)

    # ---- Install -------------------------------------------------------------

    async def install_app(
        self,
        *,
        app_version_id: str,
        team_id: str,
        wallet_mix_consent: dict[str, Any],
        mcp_consents: list[dict[str, Any]],
        update_policy: str = "manual",
    ) -> dict[str, Any]:
        body = {
            "app_version_id": app_version_id,
            "team_id": team_id,
            "wallet_mix_consent": wallet_mix_consent,
            "mcp_consents": mcp_consents,
            "update_policy": update_policy,
        }
        return await self._request("POST", "/api/app-installs/install", json=body)

    # ---- Runtime -------------------------------------------------------------

    async def begin_session(
        self,
        *,
        app_instance_id: str,
        budget_usd: float | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"app_instance_id": app_instance_id}
        if budget_usd is not None:
            body["budget_usd"] = budget_usd
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        return await self._request("POST", "/api/apps/runtime/sessions", json=body)

    async def end_session(self, session_id: str) -> None:
        await self._request("DELETE", f"/api/apps/runtime/sessions/{session_id}", expect_json=False)

    async def begin_invocation(
        self,
        *,
        app_instance_id: str,
        budget_usd: float | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"app_instance_id": app_instance_id}
        if budget_usd is not None:
            body["budget_usd"] = budget_usd
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        return await self._request("POST", "/api/apps/runtime/invocations", json=body)

    async def end_invocation(self, session_id: str) -> None:
        await self._request(
            "DELETE", f"/api/apps/runtime/invocations/{session_id}", expect_json=False
        )

    # ---- Version info --------------------------------------------------------

    async def get_version_info(self) -> dict[str, Any]:
        return await self._request("GET", "/api/version")

    async def check_compat(
        self, *, required_features: list[str], manifest_schema: str
    ) -> dict[str, Any]:
        body = {"required_features": required_features, "manifest_schema": manifest_schema}
        return await self._request("POST", "/api/version/check-compat", json=body)

    # ---- internals -----------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        expect_json: bool = True,
    ) -> Any:
        resp = await self._client.request(method, path, json=json)
        if resp.status_code == 204:
            return None
        text = resp.text
        parsed: Any = None
        if text:
            try:
                parsed = resp.json()
            except ValueError:
                parsed = text
        if resp.is_error:
            detail = (
                parsed.get("detail")
                if isinstance(parsed, dict) and "detail" in parsed
                else resp.reason_phrase
            )
            raise AppSdkHttpError(resp.status_code, str(detail or "request failed"), parsed)
        if not expect_json:
            return None
        return parsed
