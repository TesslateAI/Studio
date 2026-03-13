"""
Slack channel implementation.

Auth: User creates Slack app -> enables Events API -> gets Bot Token + Signing Secret.
Inbound: Events API webhook.
Outbound: POST to chat.postMessage.

Credential shape: {"bot_token": "xoxb-...", "signing_secret": "..."}
"""

import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

from .base import AbstractChannel, InboundMessage, sanitize_inbound_text
from .formatting import format_for_slack, split_message

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"


class SlackChannel(AbstractChannel):
    channel_type = "slack"

    def __init__(self, credentials: dict[str, Any]):
        super().__init__(credentials)
        self.bot_token = credentials["bot_token"]
        self.signing_secret = credentials.get("signing_secret", "")

    async def send_message(
        self, jid: str, text: str, *, sender: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Send message via Slack Web API."""
        channel_id = jid.split(":", 1)[-1] if ":" in jid else jid

        formatted = format_for_slack(text)
        chunks = split_message(formatted, max_length=4000)  # Slack limit ~4000 for text

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

    async def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify Slack request signature (HMAC-SHA256)."""
        if not self.signing_secret:
            return True

        timestamp = headers.get("x-slack-request-timestamp", "")
        signature = headers.get("x-slack-signature", "")

        if not timestamp or not signature:
            return False

        # Reject requests older than 5 minutes (replay protection)
        try:
            if abs(time.time() - float(timestamp)) > 300:
                logger.warning("Slack webhook timestamp too old")
                return False
        except (ValueError, TypeError):
            return False

        # Compute expected signature
        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
        expected = "v0=" + hmac.new(
            self.signing_secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    def parse_inbound(self, payload: dict[str, Any]) -> InboundMessage | None:
        """Parse Slack Events API payload."""
        # Handle URL verification challenge (not a real message)
        if payload.get("type") == "url_verification":
            return None

        event = payload.get("event", {})
        if event.get("type") != "message":
            return None

        # Skip bot messages, message_changed, etc.
        if event.get("subtype"):
            return None
        if event.get("bot_id"):
            return None

        text = event.get("text", "")
        if not text:
            return None

        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        ts = event.get("ts", "")

        # Determine if group
        channel_type = event.get("channel_type", "")
        is_group = channel_type in ("channel", "group")

        return InboundMessage(
            jid=f"slack:{channel_id}",
            sender_id=user_id,
            sender_name=user_id,  # Slack doesn't include name in event; would need users.info call
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
        """Slack doesn't support programmatic webhook registration.
        User must configure the Events API URL in their Slack app settings."""
        return {
            "registered": False,
            "message": f"Configure this URL in your Slack app's Event Subscriptions: {webhook_url}",
            "webhook_url": webhook_url,
        }
