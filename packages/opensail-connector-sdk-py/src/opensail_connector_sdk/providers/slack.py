"""Slack provider sugar.

Mirrors the curated allowlist in
``orchestrator/app/services/apps/connector_proxy/provider_adapters/slack.py``.
Only the most-used endpoints are exposed as typed methods; for any
other allowlisted endpoint, fall through to ``ConnectorProxy._request``
directly with ``connector_id="slack"``.

Slack's REST surface uses dotted method names (``chat.postMessage``,
``conversations.list``). We mirror the dotted shape with nested
namespaces so call sites read the same way as the upstream docs::

    await proxy.slack.chat.postMessage(channel="C123", text="hi")
    await proxy.slack.conversations.list(limit=10)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..client import ConnectorProxy


_CONNECTOR_ID = "slack"


class _SlackChat:
    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy

    async def postMessage(
        self,
        *,
        channel: str,
        text: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """``POST chat.postMessage``. Returns the parsed Slack JSON."""
        body: dict[str, Any] = {"channel": channel}
        if text is not None:
            body["text"] = text
        if blocks is not None:
            body["blocks"] = blocks
        if thread_ts is not None:
            body["thread_ts"] = thread_ts
        if attachments is not None:
            body["attachments"] = attachments
        body.update(extra)
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="POST",
            endpoint_path="chat.postMessage",
            json=body,
        )

    async def update(
        self,
        *,
        channel: str,
        ts: str,
        text: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"channel": channel, "ts": ts}
        if text is not None:
            body["text"] = text
        if blocks is not None:
            body["blocks"] = blocks
        body.update(extra)
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="POST",
            endpoint_path="chat.update",
            json=body,
        )

    async def delete(
        self, *, channel: str, ts: str, **extra: Any
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"channel": channel, "ts": ts, **extra}
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="POST",
            endpoint_path="chat.delete",
            json=body,
        )


class _SlackConversations:
    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy

    async def list(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        types: str | None = None,
        exclude_archived: bool | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        if types is not None:
            params["types"] = types
        if exclude_archived is not None:
            params["exclude_archived"] = (
                "true" if exclude_archived else "false"
            )
        params.update(extra)
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path="conversations.list",
            params=params,
        )

    async def history(
        self,
        *,
        channel: str,
        limit: int | None = None,
        cursor: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"channel": channel}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        params.update(extra)
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path="conversations.history",
            params=params,
        )


class _SlackUsers:
    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy

    async def list(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        params.update(extra)
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path="users.list",
            params=params,
        )

    async def lookupByEmail(self, *, email: str) -> dict[str, Any]:
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path="users.lookupByEmail",
            params={"email": email},
        )


class Slack:
    """Top-level ``proxy.slack`` namespace."""

    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy
        self.chat = _SlackChat(proxy)
        self.conversations = _SlackConversations(proxy)
        self.users = _SlackUsers(proxy)


__all__ = ["Slack"]
