"""
Signal channel implementation via signal-cli REST API.

Auth: Self-hosted signal-cli REST API with registered phone number.
Inbound: SSE stream from signal-cli /v1/receive endpoint.
Outbound: POST to signal-cli /v2/send endpoint.

Credential shape: {"signal_cli_url": "http://...", "phone_number": "+1234567890"}
"""

import asyncio
import contextlib
import json
import logging
from typing import Any

import httpx

from .base import (
    GatewayAdapter,
    InboundMessage,
    MessageEvent,
    MessageType,
    SendResult,
    SessionSource,
    sanitize_inbound_text,
)
from .formatting import split_message

logger = logging.getLogger(__name__)


class SignalChannel(GatewayAdapter):
    channel_type = "signal"

    def __init__(self, credentials: dict[str, Any], config_id: str = ""):
        super().__init__(credentials, config_id)
        self.signal_cli_url = credentials["signal_cli_url"].rstrip("/")
        self.phone_number = credentials["phone_number"]
        self._sse_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Gateway lifecycle
    # ------------------------------------------------------------------

    @property
    def supports_gateway(self) -> bool:
        return True

    async def connect(self) -> bool:
        """Start SSE stream from signal-cli REST API."""
        try:
            # Verify signal-cli is reachable
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.signal_cli_url}/v1/about")
                if resp.status_code != 200:
                    self.mark_fatal_error(f"signal-cli API returned {resp.status_code}")
                    return False

            self._connected = True
            self._sse_task = asyncio.create_task(self._sse_loop())
            logger.info("[SIGNAL-GW] Connected (config=%s)", self.config_id)
            return True

        except Exception as e:
            self.mark_fatal_error(str(e))
            logger.error("[SIGNAL-GW] Connect failed: %s", e)
            return False

    async def disconnect(self) -> None:
        """Stop SSE stream."""
        self._connected = False
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sse_task
        self._sse_task = None
        logger.info("[SIGNAL-GW] Disconnected (config=%s)", self.config_id)

    async def _sse_loop(self) -> None:
        """Stream messages from signal-cli SSE endpoint."""
        url = f"{self.signal_cli_url}/v1/receive/{self.phone_number}"
        while self._connected:
            try:
                async with (
                    httpx.AsyncClient(timeout=None) as client,
                    client.stream("GET", url) as response,
                ):
                    async for line in response.aiter_lines():
                        if not self._connected:
                            break
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            data = json.loads(data_str)
                            event = self._parse_sse_event(data)
                            if event and self._message_handler:
                                await self._message_handler(event)
                        except json.JSONDecodeError:
                            continue
                        except Exception:
                            logger.exception("[SIGNAL-GW] Handler error")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[SIGNAL-GW] SSE stream error: %s", e)
                await asyncio.sleep(5)

    def _parse_sse_event(self, data: dict) -> MessageEvent | None:
        """Convert signal-cli message to MessageEvent."""
        envelope = data.get("envelope", {})
        if not envelope:
            return None

        data_msg = envelope.get("dataMessage")
        if not data_msg:
            return None

        text = data_msg.get("message", "")
        sender = envelope.get("source", "")
        timestamp = envelope.get("timestamp")

        if not sender:
            return None

        # Determine chat context
        group_info = data_msg.get("groupInfo", {})
        if group_info:
            chat_id = group_info.get("groupId", "")
            chat_type = "group"
        else:
            chat_id = sender
            chat_type = "dm"

        source = SessionSource(
            platform="signal",
            chat_id=chat_id,
            chat_type=chat_type,
            user_id=sender,
            user_name=envelope.get("sourceName", sender),
        )

        # Media attachments
        msg_type = MessageType.TEXT
        media_urls: list[str] = []
        media_types: list[str] = []

        for att in data_msg.get("attachments", []):
            att_id = att.get("id", "")
            if att_id:
                media_urls.append(f"{self.signal_cli_url}/v1/attachments/{att_id}")
                ct = att.get("contentType", "application/octet-stream")
                media_types.append(ct)
                if ct.startswith("image/"):
                    msg_type = MessageType.IMAGE
                elif ct.startswith("audio/"):
                    msg_type = MessageType.VOICE

        if not text and not media_urls:
            return None

        return MessageEvent(
            text=sanitize_inbound_text(text or ""),
            message_type=msg_type,
            source=source,
            message_id=str(timestamp or ""),
            media_urls=media_urls,
            media_types=media_types,
        )

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send_message(
        self, jid: str, text: str, *, sender: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Send message via signal-cli REST API."""
        recipient = jid.split(":", 1)[-1] if ":" in jid else jid
        chunks = split_message(text, max_length=4096)

        last_result: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                payload: dict[str, Any] = {
                    "message": chunk,
                    "number": self.phone_number,
                }
                # Determine if group or individual
                if recipient.startswith("+"):
                    payload["recipients"] = [recipient]
                else:
                    payload["recipients"] = [recipient]

                resp = await client.post(
                    f"{self.signal_cli_url}/v2/send",
                    json=payload,
                )
                last_result = resp.json() if resp.status_code == 200 else {"error": resp.text}

        return {
            "success": "error" not in last_result,
            "platform_message_id": str(last_result.get("timestamp", "")),
            "chunks_sent": len(chunks),
        }

    async def send_gateway_response(self, chat_id: str, text: str) -> SendResult:
        result = await self.send_message(chat_id, text)
        return SendResult(
            success=result.get("success", False),
            message_id=result.get("platform_message_id"),
        )

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        return True  # Signal uses SSE, not webhooks

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        return None  # Signal uses SSE, not webhook payloads

    async def register_webhook(self, webhook_url: str, secret: str) -> dict[str, Any]:
        return {
            "registered": False,
            "message": "Signal uses SSE streaming, no webhook registration needed",
        }
