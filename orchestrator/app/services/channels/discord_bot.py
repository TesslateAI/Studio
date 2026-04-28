"""
Discord Bot channel implementation.

Auth: User creates Discord app -> gets Bot Token + Application ID + Public Key.
Inbound: Interactions endpoint (webhook) OR gateway WebSocket via discord.py.
Outbound: POST to Discord REST API.

Credential shape: {"bot_token": "...", "application_id": "...", "public_key": "..."}
"""

import asyncio
import contextlib
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
from .formatting import format_for_discord, split_message

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


class DiscordBotChannel(GatewayAdapter):
    channel_type = "discord"

    def __init__(self, credentials: dict[str, Any], config_id: str = ""):
        super().__init__(credentials, config_id)
        self.bot_token = credentials["bot_token"]
        self.application_id = credentials.get("application_id", "")
        self.public_key = credentials.get("public_key", "")
        self._client: Any = None  # discord.Client instance (lazy)
        self._client_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Gateway lifecycle
    # ------------------------------------------------------------------

    @property
    def supports_gateway(self) -> bool:
        return True

    async def connect(self) -> bool:
        """Start discord.py WebSocket client."""
        try:
            import discord

            intents = discord.Intents.default()
            intents.message_content = True
            self._client = discord.Client(intents=intents)

            adapter = self  # capture for closure

            @self._client.event
            async def on_ready():
                logger.info(
                    "[DISCORD-GW] Connected as %s (config=%s)",
                    self._client.user,
                    adapter.config_id,
                )
                adapter._connected = True

            @self._client.event
            async def on_message(message):
                if message.author.bot:
                    return
                if not adapter._message_handler:
                    return

                chat_type = "dm" if message.guild is None else "group"
                thread_id = ""
                if hasattr(message.channel, "parent_id") and message.channel.parent_id:
                    thread_id = str(message.channel.id)

                source = SessionSource(
                    platform="discord",
                    chat_id=str(message.channel.id),
                    chat_type=chat_type,
                    user_id=str(message.author.id),
                    user_name=str(message.author),
                    thread_id=thread_id,
                    chat_name=getattr(message.channel, "name", ""),
                )

                # Determine message type
                msg_type = MessageType.TEXT
                media_urls: list[str] = []
                media_types: list[str] = []
                text = message.content or ""

                if message.attachments:
                    for att in message.attachments:
                        media_urls.append(att.url)
                        ct = att.content_type or "application/octet-stream"
                        media_types.append(ct)
                        if ct.startswith("image/"):
                            msg_type = MessageType.IMAGE
                        elif ct.startswith("audio/"):
                            msg_type = MessageType.VOICE

                reply_to_id = ""
                reply_to_text = ""
                if message.reference and message.reference.resolved:
                    ref = message.reference.resolved
                    reply_to_id = str(ref.id)
                    reply_to_text = (ref.content or "")[:200]

                event = MessageEvent(
                    text=sanitize_inbound_text(text),
                    message_type=msg_type,
                    source=source,
                    message_id=str(message.id),
                    media_urls=media_urls,
                    media_types=media_types,
                    reply_to_message_id=reply_to_id,
                    reply_to_text=reply_to_text,
                    timestamp=message.created_at,
                    raw=message,
                )

                try:
                    await adapter._message_handler(event)
                except Exception:
                    logger.exception("[DISCORD-GW] Handler error for message %s", message.id)

            @self._client.event
            async def on_disconnect():
                adapter._connected = False
                logger.warning("[DISCORD-GW] Disconnected (config=%s)", adapter.config_id)

            self._client_task = asyncio.create_task(self._run_client())
            # Wait briefly for connection
            for _ in range(30):
                if self._connected:
                    return True
                await asyncio.sleep(1)

            if not self._connected:
                self.mark_fatal_error("Timed out waiting for Discord connection")
                return False
            return True

        except ImportError:
            self.mark_fatal_error("discord.py not installed", retryable=False)
            return False
        except Exception as e:
            self.mark_fatal_error(str(e))
            logger.error("[DISCORD-GW] Connect failed: %s", e)
            return False

    async def _run_client(self) -> None:
        """Run the discord.py client (blocking coroutine)."""
        try:
            await self._client.start(self.bot_token)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.mark_fatal_error(str(e))
            logger.error("[DISCORD-GW] Client error: %s", e)

    async def disconnect(self) -> None:
        """Stop discord.py client."""
        self._connected = False
        if self._client:
            await self._client.close()
        if self._client_task and not self._client_task.done():
            self._client_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._client_task
        self._client = None
        self._client_task = None
        logger.info("[DISCORD-GW] Disconnected (config=%s)", self.config_id)

    # ------------------------------------------------------------------
    # Send (shared by webhook and gateway modes)
    # ------------------------------------------------------------------

    async def send_message(
        self, jid: str, text: str, *, sender: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Send message via Discord REST API."""
        channel_id = jid.split(":", 1)[-1] if ":" in jid else jid

        formatted = format_for_discord(text)
        chunks = split_message(formatted, max_length=2000)

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
                    logger.error("Discord API error: %s %s", resp.status_code, resp.text)
                    last_result = {"error": resp.text}

        return {
            "success": "id" in last_result,
            "platform_message_id": last_result.get("id", ""),
            "chunks_sent": len(chunks),
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
        """Send media as an embed or attachment link."""
        content = f"{caption}\n{media_url}" if caption else media_url
        result = await self.send_message(chat_id, content)
        return SendResult(
            success=result.get("success", False),
            message_id=result.get("platform_message_id"),
        )

    # ------------------------------------------------------------------
    # Webhook mode
    # ------------------------------------------------------------------

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify Discord interaction signature using Ed25519."""
        if not self.public_key:
            return True

        signature = headers.get("x-signature-ed25519", "")
        timestamp = headers.get("x-signature-timestamp", "")

        if not signature or not timestamp:
            return False

        try:
            from nacl.exceptions import BadSignatureError
            from nacl.signing import VerifyKey

            verify_key = VerifyKey(bytes.fromhex(self.public_key))
            message = timestamp.encode() + body
            verify_key.verify(message, bytes.fromhex(signature))
            return True
        except (BadSignatureError, Exception) as e:
            logger.warning("Discord signature verification failed: %s", e)
            return False

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        """Parse Discord interaction payload."""
        interaction_type = payload.get("type")

        if interaction_type == 1:
            return None

        if interaction_type not in (2, 3):
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
                    metadata={"guild_id": payload.get("guild_id")},
                )
            return None

        data = payload.get("data", {})
        user = payload.get("member", {}).get("user") or payload.get("user", {})

        text = ""
        if data.get("options"):
            text = " ".join(str(opt.get("value", "")) for opt in data["options"])
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

    async def send_status(
        self, chat_id: str, text: str, message_id: str | None = None
    ) -> str | None:
        """Send or update an in-place status message."""
        if message_id:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.patch(
                    f"{DISCORD_API}/channels/{chat_id}/messages/{message_id}",
                    headers={
                        "Authorization": f"Bot {self.bot_token}",
                        "Content-Type": "application/json",
                    },
                    json={"content": text},
                )
            return message_id
        result = await self.send_message(chat_id, text)
        return result.get("platform_message_id")

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        """Delete a message via Discord API."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                f"{DISCORD_API}/channels/{chat_id}/messages/{message_id}",
                headers={"Authorization": f"Bot {self.bot_token}"},
            )
            return resp.status_code == 204

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
        """Discord doesn't support programmatic interactions URL registration."""
        return {
            "registered": False,
            "message": f"Configure this as your Interactions Endpoint URL in Discord Developer Portal: {webhook_url}",
            "webhook_url": webhook_url,
        }

    # ------------------------------------------------------------------
    # Approval cards (Phase 4) — outbound buttons via REST components
    # ------------------------------------------------------------------

    async def _open_dm_channel(
        self, user_id: str, *, http_client: httpx.AsyncClient | None = None
    ) -> str | None:
        """Resolve a Discord user id to its DM channel id via
        ``POST /users/@me/channels``. Returns ``None`` on failure."""
        if not user_id:
            return None
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=10.0)
        try:
            resp = await client.post(
                f"{DISCORD_API}/users/@me/channels",
                headers={
                    "Authorization": f"Bot {self.bot_token}",
                    "Content-Type": "application/json",
                },
                json={"recipient_id": str(user_id)},
            )
            if resp.status_code not in (200, 201):
                logger.warning(
                    "[DISCORD] open DM failed user=%s: %s %s",
                    user_id,
                    resp.status_code,
                    resp.text[:200],
                )
                return None
            data = resp.json()
            return str(data.get("id") or "") or None
        except Exception:
            logger.exception("[DISCORD] open DM raised user=%s", user_id)
            return None
        finally:
            if owns_client:
                await client.aclose()

    async def send_approval_card(
        self,
        channel_id: str,
        input_id: str,
        automation_id: str,
        tool_name: str,
        summary: str,
        actions: list[str] | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Post an interactive approval card to a Discord channel id.

        Discord supports a ``components`` field with action-row buttons
        whose ``custom_id`` (``approve:<input_id>:<choice>``) is echoed
        back when clicked. We use the REST API here (not discord.py)
        because (a) the runner already has an authenticated httpx
        client, and (b) the approval-card path doesn't need WebSocket
        events. ``http_client`` is injectable for unit tests.
        """
        from .approval_cards import build_discord_components

        components = build_discord_components(
            input_id=input_id, actions=actions
        )
        body = {
            "content": (
                f"**Approval needed**\n"
                f"_tool_: `{tool_name}`\n\n"
                f"{(summary or '').strip()[:1700]}\n\n"
                f"_automation_: `{automation_id}` · _input_: `{input_id}`"
            ),
            "components": components,
            "allowed_mentions": {"parse": []},
        }

        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await client.post(
                f"{DISCORD_API}/channels/{channel_id}/messages",
                headers={
                    "Authorization": f"Bot {self.bot_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except Exception as exc:
            logger.exception(
                "[DISCORD] send_approval_card failed channel=%s input=%s",
                channel_id,
                input_id,
            )
            return {"ok": False, "error": str(exc), "message_id": None}
        finally:
            if owns_client:
                await client.aclose()

        if resp.status_code in (200, 201):
            data = resp.json()
            return {
                "ok": True,
                "message_id": data.get("id"),
                "channel_id": channel_id,
            }
        return {
            "ok": False,
            "error": resp.text[:500],
            "status": resp.status_code,
        }

    async def send_approval_card_to_dm(
        self,
        *,
        user_id: str,
        input_id: str,
        automation_id: str,
        tool_name: str,
        summary: str,
        actions: list[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> bool:
        """Open a DM with ``user_id`` and post the approval card."""
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=15.0)
        try:
            channel_id = await self._open_dm_channel(
                user_id, http_client=client
            )
            if not channel_id:
                return False
            result = await self.send_approval_card(
                channel_id,
                input_id,
                automation_id,
                tool_name,
                summary,
                actions=actions,
                http_client=client,
            )
            return bool(result.get("ok"))
        finally:
            if owns_client:
                await client.aclose()

    # ------------------------------------------------------------------
    # Inbound discriminator — message_component never enters chat queue
    # ------------------------------------------------------------------

    @staticmethod
    def is_approval_interaction_payload(payload: dict[str, Any]) -> bool:
        """Return True iff ``payload`` is a Discord ``message_component``
        interaction (type=3) from an approval-card button (custom_id
        starts with ``approve:``).
        """
        if not isinstance(payload, dict):
            return False
        if payload.get("type") != 3:  # MESSAGE_COMPONENT
            return False
        data = payload.get("data") or {}
        custom_id = data.get("custom_id") if isinstance(data, dict) else None
        return isinstance(custom_id, str) and custom_id.startswith("approve:")

    @staticmethod
    def parse_approval_interaction(
        payload: dict[str, Any],
    ) -> tuple[str | None, str | None, str | None]:
        """Extract ``(input_id, choice, discord_user_id)`` from a
        message_component interaction. Returns ``(None, None, None)`` if
        the payload doesn't match.
        """
        from .approval_cards import parse_action_id

        if not DiscordBotChannel.is_approval_interaction_payload(payload):
            return None, None, None
        data = payload.get("data") or {}
        input_id, choice = parse_action_id(data.get("custom_id") or "")
        # User is on ``member.user`` for guild interactions, on ``user``
        # for DM interactions.
        user = (payload.get("member") or {}).get("user") or payload.get("user") or {}
        return input_id, choice, str(user.get("id") or "") or None
