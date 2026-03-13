"""
Discord Bot channel implementation.

Auth: User creates Discord app -> gets Bot Token + Application ID + Public Key.
Inbound: Interactions endpoint (Discord POSTs interaction payloads).
Outbound: POST to Discord REST API.

Credential shape: {"bot_token": "...", "application_id": "...", "public_key": "..."}
"""

import logging
from typing import Any

import httpx

from .base import AbstractChannel, InboundMessage, sanitize_inbound_text
from .formatting import format_for_discord, split_message

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


class DiscordBotChannel(AbstractChannel):
    channel_type = "discord"

    def __init__(self, credentials: dict[str, Any]):
        super().__init__(credentials)
        self.bot_token = credentials["bot_token"]
        self.application_id = credentials.get("application_id", "")
        self.public_key = credentials.get("public_key", "")

    async def send_message(
        self, jid: str, text: str, *, sender: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Send message via Discord REST API."""
        channel_id = jid.split(":", 1)[-1] if ":" in jid else jid

        formatted = format_for_discord(text)
        chunks = split_message(formatted, max_length=2000)  # Discord limit

        last_result = {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                resp = await client.post(
                    f"{DISCORD_API}/channels/{channel_id}/messages",
                    headers={
                        "Authorization": f"Bot {self.bot_token}",
                        "Content-Type": "application/json",
                    },
                    json={"content": chunk},
                )
                if resp.status_code in (200, 201):
                    last_result = resp.json()
                else:
                    logger.error(f"Discord API error: {resp.status_code} {resp.text}")
                    last_result = {"error": resp.text}

        return {
            "success": "id" in last_result,
            "platform_message_id": last_result.get("id", ""),
            "chunks_sent": len(chunks),
        }

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify Discord interaction signature using Ed25519."""
        if not self.public_key:
            return True

        signature = headers.get("x-signature-ed25519", "")
        timestamp = headers.get("x-signature-timestamp", "")

        if not signature or not timestamp:
            return False

        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError

            verify_key = VerifyKey(bytes.fromhex(self.public_key))
            message = timestamp.encode() + body
            verify_key.verify(message, bytes.fromhex(signature))
            return True
        except (BadSignatureError, Exception) as e:
            logger.warning(f"Discord signature verification failed: {e}")
            return False

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        """Parse Discord interaction payload."""
        interaction_type = payload.get("type")

        # Type 1 = PING (handled separately in router, not a message)
        if interaction_type == 1:
            return None

        # Type 2 = APPLICATION_COMMAND
        # Type 3 = MESSAGE_COMPONENT
        # For now, handle message-based interactions
        if interaction_type not in (2, 3):
            # Try parsing as a Gateway message event (if using gateway)
            if "content" in payload and "author" in payload:
                author = payload["author"]
                if author.get("bot", False):
                    return None
                return InboundMessage(
                    jid=f"discord:{payload.get('channel_id', '')}",
                    sender_id=author.get("id", ""),
                    sender_name=author.get("username", "unknown"),
                    text=sanitize_inbound_text(payload.get("content", "")),
                    platform_message_id=payload.get("id", ""),
                    is_group=payload.get("guild_id") is not None,
                    metadata={
                        "guild_id": payload.get("guild_id"),
                    },
                )
            return None

        # Application command interaction
        data = payload.get("data", {})
        user = payload.get("member", {}).get("user") or payload.get("user", {})

        # Extract text from options or resolved messages
        text = ""
        if data.get("options"):
            # Slash command with options
            text = " ".join(
                str(opt.get("value", "")) for opt in data["options"]
            )
        elif data.get("name"):
            text = f"/{data['name']}"

        if not text:
            return None

        return InboundMessage(
            jid=f"discord:{payload.get('channel_id', '')}",
            sender_id=user.get("id", ""),
            sender_name=user.get("username", "unknown"),
            text=sanitize_inbound_text(text),
            platform_message_id=payload.get("id", ""),
            is_group=payload.get("guild_id") is not None,
            metadata={
                "interaction_type": interaction_type,
                "guild_id": payload.get("guild_id"),
                "command_name": data.get("name"),
            },
        )

    async def set_typing(self, jid: str, on: bool = True) -> None:
        """Send typing indicator via Discord API."""
        if not on:
            return
        channel_id = jid.split(":", 1)[-1] if ":" in jid else jid
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{DISCORD_API}/channels/{channel_id}/typing",
                headers={"Authorization": f"Bot {self.bot_token}"},
            )

    async def register_webhook(self, webhook_url: str, secret: str) -> dict[str, Any]:
        """Discord doesn't support programmatic interactions URL registration.
        User must set it in Discord Developer Portal."""
        return {
            "registered": False,
            "message": f"Configure this as your Interactions Endpoint URL in Discord Developer Portal: {webhook_url}",
            "webhook_url": webhook_url,
        }
