"""
Abstract base class for messaging channels.

All channel implementations must inherit from AbstractChannel and implement
the required methods for sending messages, verifying webhooks, and parsing
inbound payloads.
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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

    async def set_typing(self, jid: str, on: bool = True) -> None:
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
        return {"registered": False, "message": "Webhook registration not required for this platform"}

    async def deregister_webhook(self) -> dict[str, Any]:
        """
        Deregister/remove the webhook from the platform.
        Default no-op. Override for platforms that support deregistration.
        """
        return {"deregistered": False, "message": "Webhook deregistration not supported for this platform"}
