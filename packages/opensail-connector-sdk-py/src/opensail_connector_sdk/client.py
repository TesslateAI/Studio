"""Async :class:`ConnectorProxy` client.

The client is a thin transport: it manages an :class:`httpx.AsyncClient`,
attaches the ``X-OpenSail-AppInstance`` header on every request, and
exposes one property per provider. Each provider object owns its own
typed sugar (:class:`opensail_connector_sdk.providers.slack.Slack`, etc.)
and dispatches back into ``ConnectorProxy._request`` so all I/O flows
through a single connection pool.

Defaults are read from the environment so an app pod can do
``ConnectorProxy()`` with no arguments — the OpenSail installer injects
both env vars at pod start. Tests pass an explicit ``transport=`` (e.g.
``httpx.MockTransport`` or ``respx``) to mock the network.
"""

from __future__ import annotations

import os
from types import TracebackType
from typing import Any, Mapping

import httpx

# Header the Connector Proxy uses to authenticate the calling AppInstance.
# Mirrored from
# ``orchestrator/app/services/apps/connector_proxy/auth.py::APP_INSTANCE_HEADER``.
_APP_INSTANCE_HEADER = "X-OpenSail-AppInstance"

_RUNTIME_URL_ENV = "OPENSAIL_RUNTIME_URL"
_TOKEN_ENV = "OPENSAIL_APPINSTANCE_TOKEN"


class ConnectorProxyError(Exception):
    """Base class for SDK-raised errors."""


class ConnectorProxyHttpError(ConnectorProxyError):
    """Raised when the upstream proxy (or its target) returns a non-2xx.

    ``status`` is the HTTP status code from the proxy. ``body`` is the
    parsed JSON response if the response body was JSON-decodable, else
    the raw text. ``response`` is the underlying httpx.Response so callers
    that need raw access don't have to refire the request.
    """

    def __init__(
        self,
        status: int,
        message: str,
        body: Any,
        response: httpx.Response,
    ) -> None:
        super().__init__(f"{status} {message}")
        self.status = status
        self.body = body
        self.response = response


class ConnectorProxy:
    """Async client for the OpenSail Connector Proxy.

    Parameters
    ----------
    base_url:
        Base URL of the proxy. Defaults to ``$OPENSAIL_RUNTIME_URL``.
    token:
        Per-pod app-instance token. Defaults to
        ``$OPENSAIL_APPINSTANCE_TOKEN``.
    timeout:
        Per-request timeout in seconds. Defaults to 30s.
    transport:
        Optional ``httpx.AsyncBaseTransport`` for tests.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        resolved_base = base_url if base_url is not None else os.environ.get(
            _RUNTIME_URL_ENV
        )
        resolved_token = token if token is not None else os.environ.get(
            _TOKEN_ENV
        )

        if not resolved_base:
            raise ConnectorProxyError(
                f"ConnectorProxy: base_url not provided and ${_RUNTIME_URL_ENV} "
                "is not set in the environment"
            )
        if not resolved_token:
            raise ConnectorProxyError(
                f"ConnectorProxy: token not provided and ${_TOKEN_ENV} is not "
                "set in the environment"
            )

        self._base_url = resolved_base.rstrip("/")
        self._token = resolved_token
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                _APP_INSTANCE_HEADER: resolved_token,
                "Accept": "application/json",
            },
            transport=transport,
        )

        # Lazy-instantiated provider sugar. Importing inside __init__ keeps
        # the providers package free to import this module without a cycle.
        from .providers.slack import Slack
        from .providers.github import GitHub
        from .providers.linear import Linear
        from .providers.gmail import Gmail

        self.slack = Slack(self)
        self.github = GitHub(self)
        self.linear = Linear(self)
        self.gmail = Gmail(self)

    # ---- context manager ---------------------------------------------------

    async def __aenter__(self) -> "ConnectorProxy":
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

    # ---- low-level dispatch ------------------------------------------------

    def _build_url(self, connector_id: str, endpoint_path: str) -> str:
        return (
            f"{self._base_url}/connectors/{connector_id}/"
            f"{endpoint_path.lstrip('/')}"
        )

    async def _request(
        self,
        *,
        connector_id: str,
        method: str,
        endpoint_path: str,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Send one request to the proxy and return the parsed response.

        Returns ``None`` for 204. Raises :class:`ConnectorProxyHttpError`
        on non-2xx so the caller can branch on ``.status`` / ``.body``.
        """
        url = self._build_url(connector_id, endpoint_path)
        merged_headers = dict(headers) if headers else None
        resp = await self._client.request(
            method,
            url,
            json=json,
            params=dict(params) if params else None,
            data=data,
            headers=merged_headers,
        )
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
                else (resp.reason_phrase or "request failed")
            )
            raise ConnectorProxyHttpError(
                resp.status_code, str(detail), parsed, resp
            )
        return parsed


__all__ = [
    "ConnectorProxy",
    "ConnectorProxyError",
    "ConnectorProxyHttpError",
]
