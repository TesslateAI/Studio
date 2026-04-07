"""
WhatsApp channel implementation (Meta Cloud API).

Auth: Meta Cloud API -- user creates WhatsApp Business App -> gets access token + phone number ID.
Inbound: Webhook-based (Meta POSTs message payloads).
Outbound: POST to Graph API.

Credential shape: {"access_token": "...", "phone_number_id": "...", "verify_token": "...", "app_secret": "..."}
"""

import hashlib
import hmac
import logging
from typing import Any

import httpx

from .base import GatewayAdapter, InboundMessage, sanitize_inbound_text
from .formatting import format_for_whatsapp, split_message

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v21.0"


class WhatsAppChannel(GatewayAdapter):
    channel_type = "whatsapp"

    def __init__(self, credentials: dict[str, Any], config_id: str = ""):
        super().__init__(credentials, config_id)
        self.access_token = credentials["access_token"]
        self.phone_number_id = credentials["phone_number_id"]
        self.verify_token = credentials.get("verify_token", "")
        self.app_secret = credentials.get("app_secret", "")

    @property
    def supports_gateway(self) -> bool:
        return False  # WhatsApp uses webhook-only; no persistent connection

    async def send_message(
        self, jid: str, text: str, *, sender: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Send message via Meta Cloud API."""
        phone = jid.split(":", 1)[-1] if ":" in jid else jid

        formatted = format_for_whatsapp(text)
        chunks = split_message(formatted, max_length=4096)

        last_result = {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                resp = await client.post(
                    f"{GRAPH_API}/{self.phone_number_id}/messages",
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "messaging_product": "whatsapp",
                        "to": phone,
                        "type": "text",
                        "text": {"body": chunk},
                    },
                )
                last_result = resp.json()

        msg_id = ""
        messages = last_result.get("messages", [])
        if messages:
            msg_id = messages[0].get("id", "")

        return {
            "success": bool(messages),
            "platform_message_id": msg_id,
            "chunks_sent": len(chunks),
            "error": last_result.get("error", {}).get("message"),
        }

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify WhatsApp webhook signature (X-Hub-Signature-256)."""
        if not self.app_secret:
            return True

        signature = headers.get("x-hub-signature-256", "")
        if not signature:
            return False

        # Signature format: "sha256=hex_digest"
        if not signature.startswith("sha256="):
            return False

        expected = (
            "sha256="
            + hmac.new(
                self.app_secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()
        )

        return hmac.compare_digest(expected, signature)

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        """Parse Meta Cloud API webhook payload."""
        # Navigate to the message
        try:
            entry = payload.get("entry", [])
            if not entry:
                return None

            changes = entry[0].get("changes", [])
            if not changes:
                return None

            value = changes[0].get("value", {})

            # Check for status updates (delivery/read receipts) -- not messages
            if "statuses" in value:
                return None

            messages = value.get("messages", [])
            if not messages:
                return None

            msg = messages[0]

            # Only handle text messages for now
            if msg.get("type") != "text":
                return None

            text = msg.get("text", {}).get("body", "")
            if not text:
                return None

            phone = msg.get("from", "")
            msg_id = msg.get("id", "")

            # Get sender name from contacts if available
            contacts = value.get("contacts", [])
            sender_name = ""
            if contacts:
                profile = contacts[0].get("profile", {})
                sender_name = profile.get("name", "")

            return InboundMessage(
                jid=f"whatsapp:{phone}",
                sender_id=phone,
                sender_name=sender_name or phone,
                text=sanitize_inbound_text(text),
                platform_message_id=msg_id,
                is_group=False,  # Cloud API doesn't support groups in the same way
                metadata={
                    "phone_number_id": value.get("metadata", {}).get("phone_number_id"),
                },
            )
        except (IndexError, KeyError) as e:
            logger.warning(f"Failed to parse WhatsApp payload: {e}")
            return None

    async def register_webhook(self, webhook_url: str, secret: str) -> dict[str, Any]:
        """WhatsApp webhook must be configured in Meta App Dashboard."""
        return {
            "registered": False,
            "message": f"Configure this URL in your Meta App Dashboard webhook settings: {webhook_url}",
            "webhook_url": webhook_url,
            "verify_token": self.verify_token,
        }
