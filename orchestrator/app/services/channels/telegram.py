"""
Telegram Bot API channel implementation.

Auth: User creates bot via @BotFather -> gets bot token -> stored in ChannelConfig.
Inbound: Webhook-based (setWebhook called on config create).
Outbound: POST to Bot API sendMessage.

Credential shape: {"bot_token": "...", "pool_tokens": ["...", "..."]}  (pool_tokens optional for swarm)
"""

import asyncio
import hashlib
import logging
from typing import Any

import httpx

from .base import AbstractChannel, InboundMessage, sanitize_inbound_text
from .formatting import format_for_telegram, split_message

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramChannel(AbstractChannel):
    channel_type = "telegram"

    def __init__(self, credentials: dict[str, Any]):
        super().__init__(credentials)
        self.bot_token = credentials["bot_token"]
        self.pool_tokens: list[str] = credentials.get("pool_tokens", [])
        # Stable mapping of sender->pool bot index
        self._pool_assignments: dict[str, int] = {}

    async def _api_call(self, method: str, data: dict, token: str | None = None) -> dict:
        """Make a Telegram Bot API call."""
        token = token or self.bot_token
        url = f"{TELEGRAM_API}/bot{token}/{method}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=data)
            result = resp.json()
            if not result.get("ok"):
                logger.error(f"Telegram API error: {method} -> {result}")
            return result

    async def send_message(
        self, jid: str, text: str, *, sender: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Send message via Telegram Bot API. Splits at 4096 chars."""
        # Extract chat_id from jid format "telegram:123456"
        chat_id = jid.split(":", 1)[-1] if ":" in jid else jid

        formatted = format_for_telegram(text)
        chunks = split_message(formatted, max_length=4096)

        last_result = {}
        for chunk in chunks:
            last_result = await self._api_call("sendMessage", {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
            })

        msg_id = None
        if last_result.get("ok") and last_result.get("result"):
            msg_id = str(last_result["result"].get("message_id", ""))

        return {
            "success": last_result.get("ok", False),
            "platform_message_id": msg_id,
            "chunks_sent": len(chunks),
        }

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify Telegram webhook via secret token header."""
        # Telegram sends the secret in X-Telegram-Bot-Api-Secret-Token
        secret = headers.get("x-telegram-bot-api-secret-token", "")
        # The webhook_secret is passed via the channel config, stored on the instance
        expected = self.credentials.get("_webhook_secret", "")
        if not expected:
            # If no secret stored, accept (legacy configs)
            return True
        return secret == expected

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        """Parse Telegram Update JSON into InboundMessage."""
        message = payload.get("message") or payload.get("edited_message")
        if not message:
            return None

        text = message.get("text", "")
        if not text:
            # Ignore non-text messages (photos, stickers, etc.) for now
            return None

        chat = message.get("chat", {})
        sender = message.get("from", {})
        chat_id = str(chat.get("id", ""))

        # Skip bot's own messages
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
        await self._api_call("sendChatAction", {
            "chat_id": chat_id,
            "action": "typing",
        })

    async def send_pool_message(
        self, jid: str, text: str, sender: str, group_id: str
    ) -> dict[str, Any]:
        """Send via a pool bot with a specific identity (agent swarm)."""
        if not self.pool_tokens:
            return await self.send_message(jid, text, sender=sender)

        # Stable sender->bot mapping using hash
        mapping_key = f"{group_id}:{sender}"
        if mapping_key not in self._pool_assignments:
            idx = int(hashlib.md5(mapping_key.encode()).hexdigest(), 16) % len(self.pool_tokens)
            self._pool_assignments[mapping_key] = idx

            # Rename pool bot to sender's identity
            pool_token = self.pool_tokens[self._pool_assignments[mapping_key]]
            await self._api_call("setMyName", {"name": sender[:64]}, token=pool_token)
            # Brief delay for Telegram propagation
            await asyncio.sleep(2)

        pool_token = self.pool_tokens[self._pool_assignments[mapping_key]]
        chat_id = jid.split(":", 1)[-1] if ":" in jid else jid

        formatted = format_for_telegram(text)
        chunks = split_message(formatted, max_length=4096)

        last_result = {}
        for chunk in chunks:
            last_result = await self._api_call("sendMessage", {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
            }, token=pool_token)

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
        result = await self._api_call("setWebhook", {
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": ["message", "edited_message"],
        })
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
