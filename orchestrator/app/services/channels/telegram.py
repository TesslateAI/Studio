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
                    {
                        "offset": self._offset,
                        "timeout": 30,
                        # Phase 4: also receive callback_query so approval
                        # button clicks (and bot mentions) flow back here.
                        "allowed_updates": ["message", "callback_query"],
                    },
                    timeout=35.0,
                )
                updates = result.get("result", [])
                for update in updates:
                    self._offset = update["update_id"] + 1

                    # ---- Phase 4 inbound discriminator ----
                    # callback_query button clicks NEVER enter the chat
                    # session ordering layer. Branch BEFORE _update_to_event.
                    if self.is_approval_callback_payload(update):
                        await self._handle_callback_query(update)
                        continue

                    event = self._update_to_event(update)
                    if event and self._message_handler:
                        # Slash commands are routed to the gateway-trigger
                        # path (NOT the chat handler) so the agent never
                        # sees them. Bot mentions are also classified.
                        msg = update.get("message") or {}
                        text = (msg.get("text") or "").strip()
                        if text.startswith("/") or self._looks_like_bot_mention(text):
                            await self._handle_command_message(msg)
                            continue
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

    @staticmethod
    def _looks_like_bot_mention(text: str) -> bool:
        """Heuristic — message starts with ``@<botname>`` token."""
        return bool(text) and text.startswith("@") and len(text) < 4096

    async def _handle_callback_query(self, update: dict[str, Any]) -> None:
        """Route an approval-card button click directly to the
        ``PendingUserInputManager``. Never enters ``_pending_messages``.

        Also acknowledges the callback to remove the loading spinner on
        the user's button.
        """
        input_id, choice, tg_user_id = self.parse_approval_callback(update)
        if not input_id or not choice:
            return

        from ._inbound_dispatch import post_approval_response_locally

        await post_approval_response_locally(
            input_id=input_id,
            choice=choice,
            platform="telegram",
            platform_user_id=tg_user_id,
        )

        # Best-effort: ack the callback so Telegram dismisses the spinner.
        cb_id = update.get("callback_query", {}).get("id")
        if cb_id:
            try:
                await self._api_call(
                    "answerCallbackQuery",
                    {"callback_query_id": cb_id, "text": f"Recorded: {choice}"},
                )
            except Exception:
                logger.warning(
                    "[TG-GW] answerCallbackQuery failed cb_id=%s", cb_id
                )

    async def _handle_command_message(self, message: dict[str, Any]) -> None:
        """Route a Telegram slash command / bot mention to the gateway-trigger
        path. NEVER enters ``_pending_messages``.
        """
        if not self.config_id:
            logger.warning("[TG-GW] command on adapter with no config_id")
            return

        from ._inbound_dispatch import dispatch_gateway_command
        from ..gateway.triggers.telegram_command import handle_telegram_command

        await dispatch_gateway_command(
            payload=message,
            channel_config_id=self.config_id,
            handler=handle_telegram_command,
        )

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

    # ------------------------------------------------------------------
    # Approval cards (Phase 4) — outbound inline_keyboard buttons
    # ------------------------------------------------------------------

    # ---- Phase 4 file upload (approval-card artifacts) -----------------

    # Telegram's documented sendDocument upload limit (50 MiB), but we
    # cap at 25 MiB for parity with Slack so the runner has one cross-
    # platform threshold to enforce. Larger payloads need the local-bot
    # API server which we can't assume in production.
    TELEGRAM_FILE_UPLOAD_MAX_BYTES: int = 25 * 1024 * 1024

    async def send_document(
        self,
        *,
        chat_id: str,
        filename: str,
        content: bytes,
        caption: str | None = None,
        mime_type: str | None = None,
        message_thread_id: int | str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Upload a binary blob to ``chat_id`` via Telegram ``sendDocument``.

        Uses ``multipart/form-data`` because the Bot API only accepts
        binary payloads when the request body is multipart — the JSON
        form expects a ``file_id`` or URL string.

        Returns ``{"ok": ..., "message_id": ..., "error": ...}`` so the
        caller can audit the post.
        """
        if len(content) > self.TELEGRAM_FILE_UPLOAD_MAX_BYTES:
            return {
                "ok": False,
                "error": "file_too_large",
                "message_id": None,
            }

        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=60.0)
        try:
            url = f"{TELEGRAM_API}/bot{self.bot_token}/sendDocument"
            data: dict[str, Any] = {"chat_id": str(chat_id)}
            if caption:
                # Telegram caption max is 1024 chars; truncate so the
                # API doesn't 400 us.
                data["caption"] = caption[:1024]
                data["parse_mode"] = "HTML"
            if message_thread_id is not None:
                data["message_thread_id"] = str(int(message_thread_id))

            files = {
                "document": (
                    filename,
                    content,
                    mime_type or "application/octet-stream",
                ),
            }
            resp = await client.post(url, data=data, files=files)
            result = resp.json()
            if not result.get("ok"):
                logger.warning(
                    "[TG] sendDocument failed chat=%s file=%s: %s",
                    chat_id,
                    filename,
                    result.get("description"),
                )
                return {
                    "ok": False,
                    "error": result.get("description") or "send_document_failed",
                    "message_id": None,
                }
            msg_id = None
            if result.get("result"):
                msg_id = str(result["result"].get("message_id", ""))
            return {"ok": True, "message_id": msg_id, "error": None}
        except Exception as exc:
            logger.exception(
                "[TG] send_document raised chat=%s file=%s",
                chat_id,
                filename,
            )
            return {"ok": False, "error": str(exc), "message_id": None}
        finally:
            if owns_client:
                await client.aclose()

    async def send_approval_card(
        self,
        chat_id: str,
        input_id: str,
        automation_id: str,
        tool_name: str,
        summary: str,
        actions: list[str] | None = None,
        message_thread_id: int | str | None = None,
        *,
        api_call=None,
    ) -> dict[str, Any]:
        """Post an interactive approval card to ``chat_id``.

        ``message_thread_id`` is supported for Telegram supergroup
        topics. ``api_call`` is injectable so unit tests can drop in a
        fake without monkey-patching the adapter.

        Returns ``{"ok": ..., "message_id": ..., "chat_id": ...,
        "error": ...}`` so callers can audit where it landed.
        """
        from .approval_cards import build_telegram_inline_keyboard

        keyboard = build_telegram_inline_keyboard(
            input_id=input_id, actions=actions
        )
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": (
                f"<b>Approval needed</b>\n"
                f"<i>tool</i>: <code>{tool_name}</code>\n\n"
                f"{(summary or '').strip()[:3500]}\n\n"
                f"<i>automation</i>: <code>{automation_id}</code>\n"
                f"<i>input</i>: <code>{input_id}</code>"
            ),
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": keyboard},
            "disable_web_page_preview": True,
        }
        if message_thread_id is not None:
            body["message_thread_id"] = int(message_thread_id)

        try:
            if api_call is not None:
                result = await api_call("sendMessage", body)
            else:
                result = await self._api_call("sendMessage", body)
        except Exception as exc:
            logger.exception(
                "[TG] send_approval_card failed chat=%s input=%s",
                chat_id,
                input_id,
            )
            return {"ok": False, "error": str(exc), "message_id": None, "chat_id": chat_id}

        msg_id = None
        if result.get("ok") and result.get("result"):
            msg_id = result["result"].get("message_id")
        return {
            "ok": bool(result.get("ok")),
            "message_id": msg_id,
            "chat_id": chat_id,
            "error": result.get("description"),
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
    ) -> bool:
        """Send the approval card directly to ``user_id`` (a Telegram
        user id). For private chats the chat_id IS the user_id, so no
        ``conversations.open``-equivalent dance is required.
        """
        if not user_id:
            return False
        result = await self.send_approval_card(
            chat_id=str(user_id),
            input_id=input_id,
            automation_id=automation_id,
            tool_name=tool_name,
            summary=summary,
            actions=actions,
        )
        return bool(result.get("ok"))

    # ------------------------------------------------------------------
    # Inbound discriminator — callback_query never enters the chat queue
    # ------------------------------------------------------------------

    @staticmethod
    def is_approval_callback_payload(update: dict[str, Any]) -> bool:
        """Return True iff ``update`` is a Telegram ``callback_query``
        from an approval-card button (callback_data starts with ``approve:``).
        """
        if not isinstance(update, dict):
            return False
        cb = update.get("callback_query")
        if not isinstance(cb, dict):
            return False
        data = cb.get("data") or ""
        return isinstance(data, str) and data.startswith("approve:")

    @staticmethod
    def parse_approval_callback(
        update: dict[str, Any],
    ) -> tuple[str | None, str | None, str | None]:
        """Extract ``(input_id, choice, telegram_user_id)`` from a
        Telegram callback_query. Returns ``(None, None, None)`` if the
        update doesn't match the approval shape.
        """
        from .approval_cards import parse_action_id

        if not TelegramChannel.is_approval_callback_payload(update):
            return None, None, None
        cb = update["callback_query"]
        input_id, choice = parse_action_id(cb.get("data") or "")
        sender = cb.get("from") or {}
        return input_id, choice, str(sender.get("id") or "") or None
