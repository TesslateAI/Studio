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
import uuid
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

                # ---- Phase 4 inbound discriminator ----
                # Approval-card button clicks arrive as ``interactive``
                # block_actions. We branch BEFORE reading the message
                # payload so they NEVER touch ``_pending_messages``.
                if req.type == "interactive":
                    await adapter._handle_interactive_payload(req.payload or {})
                    return

                # Slash commands arrive as ``slash_commands`` Socket
                # Mode requests. The body is form-shaped + flat.
                if req.type == "slash_commands":
                    await adapter._handle_slash_command_payload(req.payload or {})
                    return

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

    # ------------------------------------------------------------------
    # Approval cards (Phase 4) — outbound block_actions buttons
    # ------------------------------------------------------------------

    async def _resolve_dm_channel(
        self, user_id: str, *, http_client: httpx.AsyncClient | None = None
    ) -> str | None:
        """Open (or get) the IM channel for ``user_id`` via ``conversations.open``.

        Returns the channel id (e.g. ``"D0123ABCD"``) on success, ``None``
        on failure. ``http_client`` is injectable so unit tests can drop
        in a respx mock without touching the real Slack API.
        """
        if not user_id:
            return None
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=10.0)
        try:
            resp = await client.post(
                f"{SLACK_API}/conversations.open",
                headers={"Authorization": f"Bearer {self.bot_token}"},
                json={"users": user_id},
            )
            data = resp.json()
            if not data.get("ok"):
                logger.warning(
                    "[SLACK] conversations.open failed for user=%s: %s",
                    user_id,
                    data.get("error"),
                )
                return None
            return (data.get("channel") or {}).get("id")
        except Exception:
            logger.exception(
                "[SLACK] conversations.open raised for user=%s", user_id
            )
            return None
        finally:
            if owns_client:
                await client.aclose()

    # ---- Phase 4 file upload (approval-card artifacts) -----------------

    # Slack's documented file-upload size limit. Larger payloads need
    # the chunked external upload flow which we don't currently use;
    # the runner skips artifacts above this cap and surfaces the skip
    # in the card body.
    SLACK_FILE_UPLOAD_MAX_BYTES: int = 25 * 1024 * 1024  # 25 MiB

    async def upload_file(
        self,
        *,
        channel_id: str,
        filename: str,
        content: bytes,
        title: str | None = None,
        initial_comment: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Upload a binary blob to ``channel_id`` via Slack's
        ``files.getUploadURLExternal`` / ``files.completeUploadExternal``
        flow (the v2 file API, since ``files.upload`` was deprecated).

        Three-step flow:

        1. ``files.getUploadURLExternal`` returns a one-shot upload URL
           and a ``file_id`` we'll need at completion time.
        2. ``POST <upload_url>`` with the raw bytes uploads them.
        3. ``files.completeUploadExternal`` materialises the file and
           shares it into ``channel_id``.

        Returns ``{"ok": ..., "file_id": ..., "permalink": ..., "error": ...}``
        so the caller can attach a file reference to a follow-up post.

        Size policy: caller MUST pre-check ``len(content) <=
        SLACK_FILE_UPLOAD_MAX_BYTES``. We fail closed on oversize so a
        bug doesn't burn a Slack tier-3 quota call only to be rejected.
        """
        if len(content) > self.SLACK_FILE_UPLOAD_MAX_BYTES:
            return {
                "ok": False,
                "error": "file_too_large",
                "file_id": None,
                "permalink": None,
            }

        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=30.0)
        try:
            # Step 1 — request an upload URL.
            getu = await client.get(
                f"{SLACK_API}/files.getUploadURLExternal",
                headers={"Authorization": f"Bearer {self.bot_token}"},
                params={"filename": filename, "length": str(len(content))},
            )
            getu_data = getu.json()
            if not getu_data.get("ok"):
                logger.warning(
                    "[SLACK] files.getUploadURLExternal failed file=%s: %s",
                    filename,
                    getu_data.get("error"),
                )
                return {
                    "ok": False,
                    "error": getu_data.get("error") or "get_url_failed",
                    "file_id": None,
                    "permalink": None,
                }
            upload_url = getu_data.get("upload_url")
            file_id = getu_data.get("file_id")
            if not upload_url or not file_id:
                return {
                    "ok": False,
                    "error": "missing_upload_url",
                    "file_id": None,
                    "permalink": None,
                }

            # Step 2 — upload the bytes. The signed URL doesn't accept
            # the bot bearer; passing it here would trigger a 401.
            up = await client.post(
                upload_url,
                content=content,
            )
            if up.status_code >= 400:
                logger.warning(
                    "[SLACK] file upload POST failed file=%s status=%s",
                    filename,
                    up.status_code,
                )
                return {
                    "ok": False,
                    "error": f"upload_status_{up.status_code}",
                    "file_id": file_id,
                    "permalink": None,
                }

            # Step 3 — complete the upload + share to channel.
            complete_body: dict[str, Any] = {
                "files": [{"id": file_id, "title": title or filename}],
                "channel_id": channel_id,
            }
            if initial_comment:
                complete_body["initial_comment"] = initial_comment

            complete = await client.post(
                f"{SLACK_API}/files.completeUploadExternal",
                headers={"Authorization": f"Bearer {self.bot_token}"},
                json=complete_body,
            )
            complete_data = complete.json()
            if not complete_data.get("ok"):
                logger.warning(
                    "[SLACK] files.completeUploadExternal failed file=%s: %s",
                    filename,
                    complete_data.get("error"),
                )
                return {
                    "ok": False,
                    "error": complete_data.get("error") or "complete_failed",
                    "file_id": file_id,
                    "permalink": None,
                }

            # ``files`` array carries the materialised file objects.
            files_arr = complete_data.get("files") or []
            permalink = (files_arr[0] or {}).get("permalink") if files_arr else None
            return {
                "ok": True,
                "file_id": file_id,
                "permalink": permalink,
                "error": None,
            }
        except Exception as exc:
            logger.exception(
                "[SLACK] upload_file raised file=%s channel=%s",
                filename,
                channel_id,
            )
            return {
                "ok": False,
                "error": str(exc),
                "file_id": None,
                "permalink": None,
            }
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
        thread_ts: str | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Post an interactive approval card to ``channel_id``.

        ``thread_ts`` makes the call ``chat.update`` (edit-in-place) when
        present so we can refresh a previously-posted card. ``http_client``
        is injectable for unit tests.

        Returns ``{"ts": ..., "channel": ..., "ok": ...}`` mirroring the
        Slack API shape so the caller can record where it landed.
        """
        from .approval_cards import build_slack_blocks

        blocks = build_slack_blocks(
            input_id=input_id,
            automation_id=automation_id,
            tool_name=tool_name,
            summary=summary,
            actions=actions,
        )
        text_fallback = f"Approval needed for {tool_name}"

        endpoint = "chat.update" if thread_ts else "chat.postMessage"
        body: dict[str, Any] = {
            "channel": channel_id,
            "blocks": blocks,
            "text": text_fallback,
            "unfurl_links": False,
        }
        if thread_ts:
            body["ts"] = thread_ts

        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=15.0)
        try:
            resp = await client.post(
                f"{SLACK_API}/{endpoint}",
                headers={"Authorization": f"Bearer {self.bot_token}"},
                json=body,
            )
            data = resp.json()
        except Exception as exc:
            logger.exception(
                "[SLACK] send_approval_card failed channel=%s input=%s",
                channel_id,
                input_id,
            )
            return {"ok": False, "error": str(exc), "ts": None, "channel": channel_id}
        finally:
            if owns_client:
                await client.aclose()

        return {
            "ok": bool(data.get("ok")),
            "ts": data.get("ts"),
            "channel": data.get("channel") or channel_id,
            "error": data.get("error"),
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
        """Open a DM with ``user_id`` and post the approval card.

        Convenience wrapper used by ``services.automations.delivery_fallback``.
        Returns ``True`` on success.
        """
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=15.0)
        try:
            channel_id = await self._resolve_dm_channel(
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

    async def send_approval_card_dual(
        self,
        *,
        owner_user_id: str | None,
        channel_id: str | None,
        input_id: str,
        automation_id: str,
        tool_name: str,
        summary: str,
        actions: list[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Channel mode — post BOTH (a) DM to contract owner AND
        (b) thread root in the channel.

        Slack collapses bot-posted messages in busy channels so the DM
        is what actually notifies the owner; the channel post is the
        audit trail. Either click resolves the same ``input_id``.

        Returns ``{"dm": <result>, "channel": <result>}`` so the caller
        can audit both deliveries.
        """
        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=15.0)
        try:
            dm_result: dict[str, Any] = {"ok": False, "skipped": True}
            channel_result: dict[str, Any] = {"ok": False, "skipped": True}

            if owner_user_id:
                dm_channel_id = await self._resolve_dm_channel(
                    owner_user_id, http_client=client
                )
                if dm_channel_id:
                    dm_result = await self.send_approval_card(
                        dm_channel_id,
                        input_id,
                        automation_id,
                        tool_name,
                        summary,
                        actions=actions,
                        http_client=client,
                    )

            if channel_id:
                channel_result = await self.send_approval_card(
                    channel_id,
                    input_id,
                    automation_id,
                    tool_name,
                    summary,
                    actions=actions,
                    http_client=client,
                )

            return {"dm": dm_result, "channel": channel_result}
        finally:
            if owns_client:
                await client.aclose()

    # ------------------------------------------------------------------
    # Inbound discriminator — block_actions never enter the chat queue
    # ------------------------------------------------------------------

    @staticmethod
    def is_approval_action_payload(payload: dict[str, Any]) -> bool:
        """Return True iff ``payload`` is a Slack ``block_actions`` from
        an approval-card button (action_id starts with ``automation_approve:``).

        The runner / webhook router branches on this BEFORE entering the
        chat-session ordering layer (``_handle_message`` /
        ``_pending_messages``). Approval clicks NEVER queue behind chat
        traffic — that's the load-bearing guarantee from the plan.
        """
        if not isinstance(payload, dict):
            return False
        if payload.get("type") != "block_actions":
            return False
        actions = payload.get("actions") or []
        if not isinstance(actions, list):
            return False
        for action in actions:
            action_id = action.get("action_id") if isinstance(action, dict) else None
            if isinstance(action_id, str) and action_id.startswith(
                "automation_approve:"
            ):
                return True
        return False

    async def _handle_interactive_payload(self, payload: dict[str, Any]) -> None:
        """Inbound discriminator for Slack ``interactive`` payloads.

        Approval-card button clicks (``action_id`` starts with
        ``automation_approve:``) route directly to the
        ``PendingUserInputManager`` (the same code path that
        ``POST /api/chat/approval/{input_id}/respond`` uses). They NEVER
        enter the chat-session queue (``_pending_messages``).

        Anything else (other interactive flavours we don't handle yet) is
        silently dropped — the Socket Mode ack already happened in the
        caller, so Slack stops re-delivering.
        """
        if not self.is_approval_action_payload(payload):
            return

        input_id, choice, slack_user_id = self.parse_approval_action(payload)
        if not input_id or not choice:
            return

        from ._inbound_dispatch import post_approval_response_locally

        await post_approval_response_locally(
            input_id=input_id,
            choice=choice,
            platform="slack",
            platform_user_id=slack_user_id,
        )

    async def _handle_slash_command_payload(self, payload: dict[str, Any]) -> None:
        """Inbound dispatcher for Slack slash commands (Phase 4).

        Routes ``/automation run <name>`` style commands through
        ``services/gateway/triggers/slack_slash.handle_slash_command``.
        Like the interactive path, this NEVER enters the chat-session
        queue — slash commands are first-class triggers.
        """
        config_id = self.config_id
        if not config_id:
            logger.warning("[SLACK] slash command on adapter with no config_id")
            return

        from ._inbound_dispatch import dispatch_gateway_command
        from ..gateway.triggers.slack_slash import handle_slash_command

        await dispatch_gateway_command(
            payload=payload,
            channel_config_id=config_id,
            handler=handle_slash_command,
        )

    @staticmethod
    def parse_approval_action(
        payload: dict[str, Any],
    ) -> tuple[str | None, str | None, str | None]:
        """Extract ``(input_id, choice, slack_user_id)`` from a Slack
        ``block_actions`` payload. Returns ``(None, None, None)`` if the
        payload doesn't match the approval shape."""
        from .approval_cards import parse_action_id

        if not SlackChannel.is_approval_action_payload(payload):
            return None, None, None
        actions = payload.get("actions") or []
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_id = action.get("action_id") or ""
            input_id, choice = parse_action_id(action_id)
            if input_id and choice:
                user = payload.get("user") or {}
                return input_id, choice, str(user.get("id") or "") or None
        return None, None, None
