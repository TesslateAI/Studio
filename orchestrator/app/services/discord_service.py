"""
Discord webhook service for sending notifications.
"""

import aiohttp
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class DiscordWebhookService:
    """Service for sending notifications to Discord via webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_signup_notification(
        self,
        username: str,
        email: str,
        name: str,
        user_id: str
    ):
        """Send notification when a new user signs up."""
        embed = {
            "title": "🎉 New User Signup",
            "color": 0x00ff00,  # Green
            "fields": [
                {"name": "Name", "value": name, "inline": True},
                {"name": "Username", "value": username, "inline": True},
                {"name": "Email", "value": email, "inline": False},
                {"name": "User ID", "value": str(user_id), "inline": False},
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Tesslate Studio"}
        }

        await self._send_webhook(embeds=[embed])

    async def send_login_notification(
        self,
        username: str,
        email: Optional[str] = None,
        user_id: Optional[str] = None
    ):
        """Send notification when a user logs in."""
        fields = [
            {"name": "Username", "value": username, "inline": True},
        ]

        if email:
            fields.append({"name": "Email", "value": email, "inline": True})

        if user_id:
            fields.append({"name": "User ID", "value": str(user_id), "inline": False})

        embed = {
            "title": "🔐 User Login",
            "color": 0x0099ff,  # Blue
            "fields": fields,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Tesslate Studio"}
        }

        await self._send_webhook(embeds=[embed])

    async def send_referral_landing_notification(
        self,
        referred_by: str,
        ip_address: str = None
    ):
        """Send notification when someone lands on site via referral link."""
        fields = [
            {"name": "Referred By", "value": referred_by, "inline": True},
        ]

        if ip_address:
            fields.append({"name": "IP Address", "value": ip_address, "inline": True})

        embed = {
            "title": "👀 Referral Landing",
            "color": 0x00ff00,  # Green
            "fields": fields,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Tesslate Studio"}
        }

        await self._send_webhook(embeds=[embed])

    async def send_referral_conversion_notification(
        self,
        referred_by: str,
        new_user_name: str,
        new_user_username: str,
        new_user_email: str,
        user_id: str
    ):
        """Send notification when a user signs up via referral."""
        embed = {
            "title": "🎁 Referral Signup",
            "color": 0x00ff00,  # Green
            "fields": [
                {"name": "Referred By", "value": referred_by, "inline": True},
                {"name": "New User", "value": new_user_name, "inline": True},
                {"name": "Username", "value": new_user_username, "inline": True},
                {"name": "Email", "value": new_user_email, "inline": False},
                {"name": "User ID", "value": str(user_id), "inline": False},
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Tesslate Studio"}
        }

        await self._send_webhook(embeds=[embed])

    async def _send_webhook(self, embeds: list):
        """Send webhook to Discord."""
        if not self.webhook_url:
            logger.warning("Discord webhook URL not configured")
            return

        payload = {"embeds": embeds}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    if resp.status not in (200, 204):
                        error_text = await resp.text()
                        logger.error(f"Discord webhook failed: {resp.status} - {error_text}")
                    else:
                        logger.info("Discord notification sent successfully")
        except Exception as e:
            logger.error(f"Failed to send Discord webhook: {e}")


# Global instance with the webhook URL
discord_service = DiscordWebhookService(
    webhook_url=""
)
