"""Gmail provider sugar.

Mirrors the curated allowlist in
``orchestrator/app/services/apps/connector_proxy/provider_adapters/gmail.py``.
Endpoints carry the ``gmail/v1/users/{userId}`` prefix; ``user_id``
defaults to ``"me"`` (Google's well-known alias for the authorized user).

``messages.send`` accepts either a pre-encoded ``raw`` (base64url RFC822)
or the friendlier ``to=/from_=/subject=/body_text=`` shorthand which the
SDK encodes for you.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..client import ConnectorProxy


_CONNECTOR_ID = "gmail"


def _build_raw_message(
    *,
    to: str | list[str],
    from_: str | None,
    subject: str | None,
    body_text: str | None,
    body_html: str | None,
    cc: str | list[str] | None,
    bcc: str | list[str] | None,
) -> str:
    """Return base64url-encoded RFC 822 bytes ready for Gmail's ``raw`` field."""
    msg = EmailMessage()
    if isinstance(to, list):
        msg["To"] = ", ".join(to)
    else:
        msg["To"] = to
    if from_ is not None:
        msg["From"] = from_
    if subject is not None:
        msg["Subject"] = subject
    if cc is not None:
        msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc
    if bcc is not None:
        msg["Bcc"] = ", ".join(bcc) if isinstance(bcc, list) else bcc

    if body_html is not None and body_text is not None:
        msg.set_content(body_text)
        msg.add_alternative(body_html, subtype="html")
    elif body_html is not None:
        msg.set_content(body_html, subtype="html")
    elif body_text is not None:
        msg.set_content(body_text)
    else:
        msg.set_content("")

    raw_bytes = msg.as_bytes()
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii")


class _GmailMessages:
    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy

    async def list(
        self,
        *,
        user_id: str = "me",
        q: str | None = None,
        max_results: int | None = None,
        page_token: str | None = None,
        label_ids: list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if q is not None:
            params["q"] = q
        if max_results is not None:
            params["maxResults"] = max_results
        if page_token is not None:
            params["pageToken"] = page_token
        if label_ids is not None:
            params["labelIds"] = label_ids
        params.update(extra)
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path=f"gmail/v1/users/{user_id}/messages",
            params=params,
        )

    async def get(
        self,
        *,
        id: str,
        user_id: str = "me",
        format: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if format is not None:
            params["format"] = format
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path=f"gmail/v1/users/{user_id}/messages/{id}",
            params=params,
        )

    async def send(
        self,
        *,
        user_id: str = "me",
        raw: str | None = None,
        to: str | list[str] | None = None,
        from_: str | None = None,
        subject: str | None = None,
        body_text: str | None = None,
        body_html: str | None = None,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST gmail/v1/users/{userId}/messages/send``.

        Pass either ``raw`` (already base64url-encoded RFC 822) OR the
        ``to=/subject=/body_text=`` shorthand. Mixing the two raises.
        """
        if raw is None and to is None:
            raise ValueError(
                "Gmail.messages.send requires either 'raw' or at minimum 'to'"
            )
        if raw is not None and to is not None:
            raise ValueError(
                "Gmail.messages.send: pass 'raw' OR shorthand fields, not both"
            )
        if raw is None:
            assert to is not None  # for type narrowing
            raw = _build_raw_message(
                to=to,
                from_=from_,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                cc=cc,
                bcc=bcc,
            )
        body: dict[str, Any] = {"raw": raw}
        if thread_id is not None:
            body["threadId"] = thread_id
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="POST",
            endpoint_path=f"gmail/v1/users/{user_id}/messages/send",
            json=body,
        )


class _GmailLabels:
    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy

    async def list(self, *, user_id: str = "me") -> dict[str, Any]:
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path=f"gmail/v1/users/{user_id}/labels",
        )


class Gmail:
    """Top-level ``proxy.gmail`` namespace."""

    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy
        self.messages = _GmailMessages(proxy)
        self.labels = _GmailLabels(proxy)


__all__ = ["Gmail"]
