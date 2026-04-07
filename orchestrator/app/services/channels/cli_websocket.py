"""
CLI WebSocket channel for gateway-direct communication.

Provides a WebSocket endpoint that CLI clients can connect to for real-time
bidirectional communication with the agent, bypassing the standard HTTP API.
Authentication is via JWT token passed as a query parameter.

Credential shape: {} (no platform credentials needed — uses Tesslate JWT)
"""

import asyncio
import logging
from typing import Any

from .base import (
    GatewayAdapter,
    InboundMessage,
    MessageEvent,
    MessageType,
    SendResult,
    SessionSource,
    sanitize_inbound_text,
)

logger = logging.getLogger(__name__)


class CLIWebSocketChannel(GatewayAdapter):
    """WebSocket adapter for CLI clients connecting directly to the gateway."""

    channel_type = "cli"

    def __init__(self, credentials: dict[str, Any], config_id: str = ""):
        super().__init__(credentials, config_id)
        self._connections: dict[str, Any] = {}  # user_id -> websocket
        self._server_task: asyncio.Task | None = None

    @property
    def supports_gateway(self) -> bool:
        return True

    async def connect(self) -> bool:
        """Mark adapter as ready. Actual WebSocket connections arrive per-client."""
        self._connected = True
        logger.info("[CLI-GW] Ready for WebSocket connections (config=%s)", self.config_id)
        return True

    async def disconnect(self) -> None:
        """Close all active WebSocket connections."""
        import contextlib

        self._connected = False
        for ws in list(self._connections.values()):
            with contextlib.suppress(Exception):
                await ws.close()
        self._connections.clear()
        logger.info("[CLI-GW] Disconnected all clients (config=%s)", self.config_id)

    async def handle_ws_message(self, user_id: str, user_name: str, text: str, ws: Any) -> None:
        """Process an inbound WebSocket message from a CLI client."""
        self._connections[user_id] = ws

        source = SessionSource(
            platform="cli",
            chat_id=user_id,
            chat_type="dm",
            user_id=user_id,
            user_name=user_name,
        )

        event = MessageEvent(
            text=sanitize_inbound_text(text),
            message_type=MessageType.TEXT,
            source=source,
            message_id=f"cli-{user_id}-{asyncio.get_event_loop().time():.0f}",
        )

        if self._message_handler:
            await self._message_handler(event)

    async def send_message(
        self, jid: str, text: str, *, sender: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Send message to CLI client via WebSocket."""
        user_id = jid.split(":", 1)[-1] if ":" in jid else jid
        ws = self._connections.get(user_id)
        if not ws:
            return {"success": False, "error": "Client not connected"}

        try:
            import json

            await ws.send_text(json.dumps({"type": "message", "text": text}))
            return {"success": True, "platform_message_id": ""}
        except Exception as e:
            logger.warning("[CLI-GW] Send failed for user %s: %s", user_id, e)
            self._connections.pop(user_id, None)
            return {"success": False, "error": str(e)}

    async def send_gateway_response(self, chat_id: str, text: str) -> SendResult:
        result = await self.send_message(chat_id, text)
        return SendResult(
            success=result.get("success", False),
            message_id=result.get("platform_message_id"),
        )

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        return False  # CLI uses WebSocket, not webhooks

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        return None  # CLI uses WebSocket, not webhook payloads
