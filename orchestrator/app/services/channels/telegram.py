"""
Telegram Bot API channel implementation.

Auth: User creates bot via @BotFather -> gets bot token -> stored in ChannelConfig.
Inbound: Webhook-based (setWebhook called on config create) OR gateway long-polling.
Outbound: POST to Bot API sendMessage.

Credential shape: {"bot_token": "...", "pool_tokens": ["...", "..."]}  (pool_tokens optional for swarm)
"""

import asyncio
import contextlib
import hashlib
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
from .formatting import format_for_telegram, split_message

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramChannel(GatewayAdapter):
    channel_type = "telegram"

    def __init__(self, credentials: dict[str, Any], config_id: str = ""):
        super().__init__(credentials, config_id)
        self.bot_token = credentials["bot_token"]
        self.pool_tokens: list[str] = credentials.get("pool_tokens", [])
        self._pool_assignments: dict[str, int] = {}
        self._polling_task: asyncio.Task | None = None
        self._offset: int = 0

    # ------------------------------------------------------------------
    # Gateway lifecycle
    # ------------------------------------------------------------------

    @property
    def supports_gateway(self) -> bool:
        return True

    async def connect(self) -> bool:
        """Start getUpdates long-polling loop."""
        try:
            # Disable webhook so we can use getUpdates
            await self._api_call("deleteWebhook", {"drop_pending_updates": False})
            self._connected = True
            self._polling_task = asyncio.create_task(self._poll_loop())
            logger.info("[TG-GW] Connected via long-polling (config=%s)", self.config_id)
            return True
        except Exception as e:
            self.mark_fatal_error(str(e))
            logger.error("[TG-GW] Connect failed: %s", e)
            return False

    async def disconnect(self) -> None:
        """Stop polling loop."""
        self._connected = False
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._polling_task
        self._polling_task = None
        logger.info("[TG-GW] Disconnected (config=%s)", self.config_id)

    async def _poll_loop(self) -> None:
        """Long-poll getUpdates in a loop, dispatching to message handler."""
        while self._connected:
            try:
                result = await self._api_call(
                    "getUpdates",
                    {"offset": self._offset, "timeout": 30, "allowed_updates": ["message"]},
                    timeout=35.0,
                )
                updates = result.get("result", [])
                for update in updates:
                    self._offset = update["update_id"] + 1
                    event = self._update_to_event(update)
                    if event and self._message_handler:
                        try:
                            await self._message_handler(event)
                        except Exception:
                            logger.exception(
                                "[TG-GW] Handler error for update %s", update.get("update_id")
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[TG-GW] Poll error: %s", e)
                await asyncio.sleep(2)

    def _update_to_event(self, update: dict) -> MessageEvent | None:
        """Convert a Telegram Update to a MessageEvent."""
        message = update.get("message")
        if not message:
            return None

        chat = message.get("chat", {})
        sender = message.get("from", {})

        # Skip bot messages
        if sender.get("is_bot", False):
            return None

        chat_id = str(chat.get("id", ""))
        chat_type_raw = chat.get("type", "private")
        chat_type = "dm" if chat_type_raw == "private" else "group"

        sender_name = sender.get("first_name", "")
        if sender.get("last_name"):
            sender_name += f" {sender['last_name']}"

        source = SessionSource(
            platform="telegram",
            chat_id=chat_id,
            chat_type=chat_type,
            user_id=str(sender.get("id", "")),
            user_name=sender.get("username", sender_name),
            chat_name=chat.get("title", ""),
        )

        # Determine message type and text
        if message.get("voice") or message.get("audio"):
            voice = message.get("voice") or message.get("audio", {})
            file_id = voice.get("file_id", "")
            return MessageEvent(
                text="",
                message_type=MessageType.VOICE,
                source=source,
                message_id=str(message.get("message_id", "")),
                media_urls=[file_id],  # Telegram file_id, resolved by media pipeline
                media_types=["audio"],
            )

        if message.get("photo"):
            # Use largest photo size
            photo = message["photo"][-1]
            file_id = photo.get("file_id", "")
            caption = message.get("caption", "")
            return MessageEvent(
                text=sanitize_inbound_text(caption),
                message_type=MessageType.IMAGE,
                source=source,
                message_id=str(message.get("message_id", "")),
                media_urls=[file_id],
                media_types=["image"],
            )

        if message.get("document"):
            doc = message["document"]
            file_id = doc.get("file_id", "")
            caption = message.get("caption", "")
            return MessageEvent(
                text=sanitize_inbound_text(caption),
                message_type=MessageType.DOCUMENT,
                source=source,
                message_id=str(message.get("message_id", "")),
                media_urls=[file_id],
                media_types=[doc.get("mime_type", "application/octet-stream")],
            )

        text = message.get("text", "")
        if not text:
            return None

        msg_type = MessageType.COMMAND if text.startswith("/") else MessageType.TEXT

        reply_to_id = ""
        reply_to_text = ""
        if message.get("reply_to_message"):
            reply_msg = message["reply_to_message"]
            reply_to_id = str(reply_msg.get("message_id", ""))
            reply_to_text = reply_msg.get("text", "")[:200]

        return MessageEvent(
            text=sanitize_inbound_text(text),
            message_type=msg_type,
            source=source,
            message_id=str(message.get("message_id", "")),
            reply_to_message_id=reply_to_id,
            reply_to_text=reply_to_text,
        )

    # ------------------------------------------------------------------
    # Send (shared by webhook and gateway modes)
    # ------------------------------------------------------------------

    async def _api_call(
        self, method: str, data: dict, token: str | None = None, timeout: float = 15.0
    ) -> dict:
        """Make a Telegram Bot API call."""
        token = token or self.bot_token
        url = f"{TELEGRAM_API}/bot{token}/{method}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=data)
            result = resp.json()
            if not result.get("ok"):
                logger.error("Telegram API error: %s -> %s", method, result)
            return result

    async def send_message(
        self, jid: str, text: str, *, sender: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Send message via Telegram Bot API. Splits at 4096 chars."""
        chat_id = jid.split(":", 1)[-1] if ":" in jid else jid

        formatted = format_for_telegram(text)
        chunks = split_message(formatted, max_length=4096)

        last_result = {}
        for chunk in chunks:
            last_result = await self._api_call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                },
            )

        msg_id = None
        if last_result.get("ok") and last_result.get("result"):
            msg_id = str(last_result["result"].get("message_id", ""))

        return {
            "success": last_result.get("ok", False),
            "platform_message_id": msg_id,
            "chunks_sent": len(chunks),
        }

    async def send_gateway_response(self, chat_id: str, text: str) -> SendResult:
        """Send a response via gateway (used by delivery consumer)."""
        result = await self.send_message(chat_id, text)
        return SendResult(
            success=result.get("success", False),
            message_id=result.get("platform_message_id"),
        )

    async def send_media(
        self, chat_id: str, media_url: str, media_type: str, caption: str = ""
    ) -> SendResult:
        """Send media via Telegram."""
        method_map = {
            "image": "sendPhoto",
            "audio": "sendAudio",
            "video": "sendVideo",
        }
        method = method_map.get(media_type, "sendDocument")
        param_map = {
            "sendPhoto": "photo",
            "sendAudio": "audio",
            "sendVideo": "video",
            "sendDocument": "document",
        }
        param = param_map[method]

        result = await self._api_call(
            method,
            {
                "chat_id": chat_id,
                param: media_url,
                "caption": caption[:1024] if caption else "",
            },
        )
        msg_id = None
        if result.get("ok") and result.get("result"):
            msg_id = str(result["result"].get("message_id", ""))
        return SendResult(success=result.get("ok", False), message_id=msg_id)

    async def get_file_url(self, file_id: str) -> str | None:
        """Resolve a Telegram file_id to a download URL."""
        result = await self._api_call("getFile", {"file_id": file_id})
        if result.get("ok") and result.get("result"):
            file_path = result["result"].get("file_path")
            if file_path:
                return f"{TELEGRAM_API}/file/bot{self.bot_token}/{file_path}"
        return None

    # ------------------------------------------------------------------
    # Webhook mode (unchanged from v1)
    # ------------------------------------------------------------------

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify Telegram webhook via secret token header."""
        secret = headers.get("x-telegram-bot-api-secret-token", "")
        expected = self.credentials.get("_webhook_secret", "")
        if not expected:
            return True
        return secret == expected

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        """Parse Telegram Update JSON into InboundMessage."""
        message = payload.get("message") or payload.get("edited_message")
        if not message:
            return None

        text = message.get("text", "")
        if not text:
            return None

        chat = message.get("chat", {})
        sender = message.get("from", {})
        chat_id = str(chat.get("id", ""))

        if sender.get("is_bot", False):
            return None

        sender_name = sender.get("first_name", "")
        if sender.get("last_name"):
            sender_name += f" {sender['last_name']}"

        return InboundMessage(
            jid=f"telegram:{chat_id}",
            sender_id=str(sender.get("id", "")),
            sender_name=sender_name or sender.get("username", "unknown"),
            text=sanitize_inbound_text(text),
            platform_message_id=str(message.get("message_id", "")),
            is_group=chat.get("type") in ("group", "supergroup"),
            metadata={
                "chat_type": chat.get("type"),
                "chat_title": chat.get("title"),
                "username": sender.get("username"),
            },
        )

    async def set_typing(self, jid: str, on: bool = True) -> None:
        """Send typing indicator."""
        if not on:
            return
        chat_id = jid.split(":", 1)[-1] if ":" in jid else jid
        await self._api_call(
            "sendChatAction",
            {
                "chat_id": chat_id,
                "action": "typing",
            },
        )

    async def send_status(
        self, chat_id: str, text: str, message_id: str | None = None
    ) -> str | None:
        """Send or update an in-place status message."""
        if message_id:
            result = await self._api_call(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": int(message_id),
                    "text": text,
                    "parse_mode": "HTML",
                },
            )
            return message_id
        result = await self._api_call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_notification": True,
            },
        )
        if result.get("ok") and result.get("result"):
            return str(result["result"]["message_id"])
        return None

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        """Delete a message via Telegram Bot API."""
        result = await self._api_call(
            "deleteMessage",
            {"chat_id": chat_id, "message_id": int(message_id)},
        )
        return result.get("ok", False)

    async def send_pool_message(
        self, jid: str, text: str, sender: str, group_id: str
    ) -> dict[str, Any]:
        """Send via a pool bot with a specific identity (agent swarm)."""
        if not self.pool_tokens:
            return await self.send_message(jid, text, sender=sender)

        mapping_key = f"{group_id}:{sender}"
        if mapping_key not in self._pool_assignments:
            idx = int(hashlib.md5(mapping_key.encode()).hexdigest(), 16) % len(self.pool_tokens)
            self._pool_assignments[mapping_key] = idx

            pool_token = self.pool_tokens[self._pool_assignments[mapping_key]]
            await self._api_call("setMyName", {"name": sender[:64]}, token=pool_token)
            await asyncio.sleep(2)

        pool_token = self.pool_tokens[self._pool_assignments[mapping_key]]
        chat_id = jid.split(":", 1)[-1] if ":" in jid else jid

        formatted = format_for_telegram(text)
        chunks = split_message(formatted, max_length=4096)

        last_result = {}
        for chunk in chunks:
            last_result = await self._api_call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                },
                token=pool_token,
            )

        msg_id = None
        if last_result.get("ok") and last_result.get("result"):
            msg_id = str(last_result["result"].get("message_id", ""))

        return {
            "success": last_result.get("ok", False),
            "platform_message_id": msg_id,
            "sender": sender,
            "pool_bot_index": self._pool_assignments[mapping_key],
        }

    async def register_webhook(self, webhook_url: str, secret: str) -> dict[str, Any]:
        """Register webhook with Telegram via setWebhook API."""
        result = await self._api_call(
            "setWebhook",
            {
                "url": webhook_url,
                "secret_token": secret,
                "allowed_updates": ["message", "edited_message"],
            },
        )
        return {
            "registered": result.get("ok", False),
            "message": result.get("description", ""),
        }

    async def deregister_webhook(self) -> dict[str, Any]:
        """Remove webhook from Telegram."""
        result = await self._api_call("deleteWebhook", {})
        return {
            "deregistered": result.get("ok", False),
            "message": result.get("description", ""),
        }
