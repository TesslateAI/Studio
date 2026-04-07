"""
Slack channel implementation.

Auth: User creates Slack app -> enables Events API -> gets Bot Token + Signing Secret.
Inbound: Events API webhook OR gateway Socket Mode.
Outbound: POST to chat.postMessage.

Credential shape: {"bot_token": "xoxb-...", "signing_secret": "...", "app_token": "xapp-..."}
"""

import asyncio
import contextlib
import hashlib
import hmac
import logging
import time
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
from .formatting import format_for_slack, split_message

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"


class SlackChannel(GatewayAdapter):
    channel_type = "slack"

    def __init__(self, credentials: dict[str, Any], config_id: str = ""):
        super().__init__(credentials, config_id)
        self.bot_token = credentials["bot_token"]
        self.signing_secret = credentials.get("signing_secret", "")
        self.app_token = credentials.get("app_token", "")  # xapp-* for Socket Mode
        self._socket_client: Any = None
        self._socket_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Gateway lifecycle (Socket Mode)
    # ------------------------------------------------------------------

    @property
    def supports_gateway(self) -> bool:
        return bool(self.app_token)

    async def connect(self) -> bool:
        """Start Slack Socket Mode client."""
        if not self.app_token:
            self.mark_fatal_error("No app_token for Socket Mode", retryable=False)
            return False

        try:
            from slack_sdk.socket_mode.aiohttp import SocketModeClient
            from slack_sdk.socket_mode.response import SocketModeResponse
            from slack_sdk.web.async_client import AsyncWebClient

            web_client = AsyncWebClient(token=self.bot_token)
            self._socket_client = SocketModeClient(
                app_token=self.app_token,
                web_client=web_client,
            )

            adapter = self

            async def _handle_event(client, req):
                """Process Socket Mode events."""
                # Acknowledge immediately
                response = SocketModeResponse(envelope_id=req.envelope_id)
                await client.send_socket_mode_response(response)

                if req.type != "events_api":
                    return

                event = req.payload.get("event", {})
                if event.get("type") != "message":
                    return
                if event.get("subtype") or event.get("bot_id"):
                    return

                text = event.get("text", "")
                if not text:
                    return

                if not adapter._message_handler:
                    return

                channel_id = event.get("channel", "")
                user_id = event.get("user", "")
                channel_type_raw = event.get("channel_type", "")
                chat_type = "dm" if channel_type_raw == "im" else "group"
                thread_id = event.get("thread_ts", "")

                source = SessionSource(
                    platform="slack",
                    chat_id=channel_id,
                    chat_type=chat_type,
                    user_id=user_id,
                    user_name=user_id,
                    thread_id=thread_id,
                )

                msg_type = MessageType.TEXT
                media_urls: list[str] = []
                media_types: list[str] = []

                if event.get("files"):
                    for f in event["files"]:
                        url = f.get("url_private_download") or f.get("url_private", "")
                        if url:
                            media_urls.append(url)
                            media_types.append(f.get("mimetype", "application/octet-stream"))
                            if f.get("mimetype", "").startswith("image/"):
                                msg_type = MessageType.IMAGE
                            elif f.get("mimetype", "").startswith("audio/"):
                                msg_type = MessageType.VOICE

                msg_event = MessageEvent(
                    text=sanitize_inbound_text(text),
                    message_type=msg_type,
                    source=source,
                    message_id=event.get("ts", ""),
                    media_urls=media_urls,
                    media_types=media_types,
                )

                try:
                    await adapter._message_handler(msg_event)
                except Exception:
                    logger.exception("[SLACK-GW] Handler error for event ts=%s", event.get("ts"))

            self._socket_client.socket_mode_request_listeners.append(_handle_event)
            self._socket_task = asyncio.create_task(self._run_socket())

            # Wait for connection
            for _ in range(15):
                if self._socket_client.is_connected():
                    self._connected = True
                    logger.info("[SLACK-GW] Connected via Socket Mode (config=%s)", self.config_id)
                    return True
                await asyncio.sleep(1)

            self.mark_fatal_error("Timed out waiting for Slack Socket Mode connection")
            return False

        except ImportError:
            self.mark_fatal_error("slack-sdk[socket-mode] not installed", retryable=False)
            return False
        except Exception as e:
            self.mark_fatal_error(str(e))
            logger.error("[SLACK-GW] Connect failed: %s", e)
            return False

    async def _run_socket(self) -> None:
        """Run the Socket Mode client."""
        try:
            await self._socket_client.connect()
            # Keep alive until disconnected
            while self._connected:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.mark_fatal_error(str(e))
            logger.error("[SLACK-GW] Socket error: %s", e)

    async def disconnect(self) -> None:
        """Stop Socket Mode client."""
        self._connected = False
        if self._socket_client:
            await self._socket_client.disconnect()
        if self._socket_task and not self._socket_task.done():
            self._socket_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._socket_task
        self._socket_client = None
        self._socket_task = None
        logger.info("[SLACK-GW] Disconnected (config=%s)", self.config_id)

    # ------------------------------------------------------------------
    # Send (shared by webhook and gateway modes)
    # ------------------------------------------------------------------

    async def send_message(
        self, jid: str, text: str, *, sender: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Send message via Slack Web API."""
        channel_id = jid.split(":", 1)[-1] if ":" in jid else jid

        formatted = format_for_slack(text)
        chunks = split_message(formatted, max_length=4000)

        last_result = {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                resp = await client.post(
                    f"{SLACK_API}/chat.postMessage",
                    headers={"Authorization": f"Bearer {self.bot_token}"},
                    json={
                        "channel": channel_id,
                        "text": chunk,
                        "unfurl_links": False,
                    },
                )
                last_result = resp.json()

        return {
            "success": last_result.get("ok", False),
            "platform_message_id": last_result.get("ts", ""),
            "chunks_sent": len(chunks),
            "error": last_result.get("error"),
        }

    async def send_gateway_response(self, chat_id: str, text: str) -> SendResult:
        """Send a response via gateway."""
        result = await self.send_message(chat_id, text)
        return SendResult(
            success=result.get("success", False),
            message_id=result.get("platform_message_id"),
        )

    async def send_media(
        self, chat_id: str, media_url: str, media_type: str, caption: str = ""
    ) -> SendResult:
        """Send media as a message with URL."""
        content = f"{caption}\n{media_url}" if caption else media_url
        result = await self.send_message(chat_id, content)
        return SendResult(
            success=result.get("success", False),
            message_id=result.get("platform_message_id"),
        )

    async def send_status(
        self, chat_id: str, text: str, message_id: str | None = None
    ) -> str | None:
        """Send or update an in-place status message."""
        if message_id:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{SLACK_API}/chat.update",
                    headers={"Authorization": f"Bearer {self.bot_token}"},
                    json={"channel": chat_id, "ts": message_id, "text": text},
                )
                result = resp.json()
                return message_id if result.get("ok") else None
        result = await self.send_message(chat_id, text)
        return result.get("platform_message_id")

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        """Delete a message via Slack API."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{SLACK_API}/chat.delete",
                headers={"Authorization": f"Bearer {self.bot_token}"},
                json={"channel": chat_id, "ts": message_id},
            )
            return resp.json().get("ok", False)

    # ------------------------------------------------------------------
    # Webhook mode
    # ------------------------------------------------------------------

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify Slack request signature (HMAC-SHA256)."""
        if not self.signing_secret:
            return True

        timestamp = headers.get("x-slack-request-timestamp", "")
        signature = headers.get("x-slack-signature", "")

        if not timestamp or not signature:
            return False

        try:
            if abs(time.time() - float(timestamp)) > 300:
                logger.warning("Slack webhook timestamp too old")
                return False
        except (ValueError, TypeError):
            return False

        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
        expected = (
            "v0="
            + hmac.new(
                self.signing_secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        )

        return hmac.compare_digest(expected, signature)

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        """Parse Slack Events API payload."""
        if payload.get("type") == "url_verification":
            return None

        event = payload.get("event", {})
        if event.get("type") != "message":
            return None

        if event.get("subtype") or event.get("bot_id"):
            return None

        text = event.get("text", "")
        if not text:
            return None

        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        ts = event.get("ts", "")
        channel_type = event.get("channel_type", "")
        is_group = channel_type in ("channel", "group")

        return InboundMessage(
            jid=f"slack:{channel_id}",
            sender_id=user_id,
            sender_name=user_id,
            text=sanitize_inbound_text(text),
            platform_message_id=ts,
            is_group=is_group,
            metadata={
                "channel_type": channel_type,
                "team_id": payload.get("team_id"),
                "event_id": payload.get("event_id"),
            },
        )

    async def register_webhook(self, webhook_url: str, secret: str) -> dict[str, Any]:
        """Slack doesn't support programmatic webhook registration."""
        return {
            "registered": False,
            "message": f"Configure this URL in your Slack app's Event Subscriptions: {webhook_url}",
            "webhook_url": webhook_url,
        }
