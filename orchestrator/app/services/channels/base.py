"""
Abstract base class for messaging channels.

All channel implementations must inherit from AbstractChannel and implement
the required methods for sending messages, verifying webhooks, and parsing
inbound payloads.
"""

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

# Max message length before sanitization truncation
MAX_INBOUND_MESSAGE_LENGTH = 8000


@dataclass
class InboundMessage:
    """Parsed inbound message from a messaging platform."""

    jid: str  # Canonical address: "telegram:123456", "slack:C012345", etc.
    sender_id: str
    sender_name: str
    text: str
    platform_message_id: str
    is_group: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def sanitize_inbound_text(text: str) -> str:
    """Strip platform control characters and enforce max length."""
    if not text:
        return ""
    # Strip null bytes and other non-printable control chars (keep newlines/tabs)
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", text)
    # Enforce max length
    if len(text) > MAX_INBOUND_MESSAGE_LENGTH:
        text = text[:MAX_INBOUND_MESSAGE_LENGTH] + "... (truncated)"
    return text.strip()


class AbstractChannel(ABC):
    """
    Abstract base for messaging channel implementations.

    Each channel handles a specific platform (Telegram, Slack, Discord, WhatsApp)
    and provides methods for sending messages, verifying inbound webhooks,
    and parsing inbound payloads into a unified InboundMessage format.
    """

    channel_type: str = ""

    def __init__(self, credentials: dict[str, Any]):
        self.credentials = credentials

    @abstractmethod
    async def send_message(
        self, jid: str, text: str, *, sender: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """
        Send a message to the specified address.

        Args:
            jid: Target address (platform-specific ID)
            text: Message text
            sender: Optional sender identity name (for swarm mode)

        Returns:
            Dict with delivery status and platform_message_id
        """
        ...

    @abstractmethod
    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """
        Verify that an inbound webhook request is authentic.

        Args:
            headers: HTTP request headers
            body: Raw request body bytes

        Returns:
            True if the webhook signature is valid
        """
        ...

    @abstractmethod
    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        """
        Parse an inbound webhook payload into an InboundMessage.

        Returns None if the payload should be ignored (e.g., bot's own messages,
        non-message events).

        Args:
            payload: Parsed JSON webhook payload

        Returns:
            InboundMessage or None
        """
        ...

    async def set_typing(self, jid: str, on: bool = True) -> None:  # noqa: B027
        """Send typing indicator. Default no-op; override per platform."""
        pass

    async def send_pool_message(
        self, jid: str, text: str, sender: str, group_id: str
    ) -> dict[str, Any]:
        """
        Send a message via a pool bot with a specific identity (agent swarm).

        Default: falls back to send_message with sender param.
        Override in channels that support multiple bot identities (e.g., Telegram).
        """
        return await self.send_message(jid, text, sender=sender)

    async def register_webhook(self, webhook_url: str, secret: str) -> dict[str, Any]:
        """
        Register the webhook URL with the platform (e.g., Telegram setWebhook).

        Default no-op. Override for platforms that require explicit registration.
        Returns dict with registration status.
        """
        return {
            "registered": False,
            "message": "Webhook registration not required for this platform",
        }

    async def deregister_webhook(self) -> dict[str, Any]:
        """
        Deregister/remove the webhook from the platform.
        Default no-op. Override for platforms that support deregistration.
        """
        return {
            "deregistered": False,
            "message": "Webhook deregistration not supported for this platform",
        }


# ==========================================================================
# Gateway Protocol v2 — Platform-agnostic message types & adapter base
# ==========================================================================


class MessageType(StrEnum):
    """Inbound message content type."""

    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    DOCUMENT = "document"
    COMMAND = "command"


@dataclass
class SessionSource:
    """Origin metadata for routing and session keying."""

    platform: str
    chat_id: str
    chat_type: str  # "dm", "group", "channel", "thread"
    user_id: str
    user_name: str = ""
    thread_id: str = ""
    chat_name: str = ""

    def session_key(self) -> str:
        """Deterministic, human-readable, survives restarts."""
        parts = [self.platform, self.chat_type, self.chat_id]
        if self.thread_id:
            parts.append(self.thread_id)
        return ":".join(parts)


@dataclass
class MessageEvent:
    """Platform-agnostic inbound message envelope."""

    text: str
    message_type: MessageType
    source: SessionSource
    message_id: str
    media_urls: list[str] = field(default_factory=list)
    media_types: list[str] = field(default_factory=list)
    reply_to_message_id: str = ""
    reply_to_text: str = ""
    timestamp: datetime | None = None
    raw: Any = None


@dataclass
class SendResult:
    """Standardized outbound delivery result."""

    success: bool
    message_id: str | None = None
    error: str | None = None
    retryable: bool = False


class GatewayAdapter(AbstractChannel):
    """Base for adapters supporting persistent gateway connections.

    Extends AbstractChannel with connect/disconnect lifecycle for long-lived
    platform connections (WebSocket, polling, Socket Mode). Adapters that only
    support webhook inbound should leave ``supports_gateway`` as False.
    """

    channel_type: str = ""

    def __init__(self, credentials: dict[str, Any], config_id: str = ""):
        super().__init__(credentials)
        self.config_id = config_id
        self._message_handler: Callable[[MessageEvent], Awaitable[None]] | None = None
        self._connected = False
        self._fatal_error: str | None = None
        self._fatal_retryable: bool = True

    async def connect(self) -> bool:
        """Start persistent connection. Return True on success."""
        return False

    async def disconnect(self) -> None:
        """Gracefully stop persistent connection."""
        pass

    @property
    def supports_gateway(self) -> bool:
        """Whether this adapter supports persistent gateway connections."""
        return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_message_handler(self, handler: Callable[[MessageEvent], Awaitable[None]]) -> None:
        """Register the callback the gateway invokes for each inbound message."""
        self._message_handler = handler

    def mark_fatal_error(self, error: str, *, retryable: bool = True) -> None:
        """Record a fatal adapter error. The reconnect watcher reads this."""
        self._fatal_error = error
        self._fatal_retryable = retryable
        self._connected = False

    async def send_media(
        self,
        chat_id: str,
        media_url: str,
        media_type: str,
        caption: str = "",
    ) -> SendResult:
        """Send a media attachment. Override per platform."""
        return SendResult(success=False, error="Media not supported by this platform")
