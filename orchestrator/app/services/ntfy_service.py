"""
ntfy.sh notification service for push notifications.
"""

import aiohttp
import logging

logger = logging.getLogger(__name__)

class NtfyService:
    """Service for sending push notifications via ntfy.sh."""

    def __init__(self, topic: str = "TesslateTracking"):
        self.topic = topic
        self.url = f"https://ntfy.sh/{topic}"

    async def send_referral_landing(self, referred_by: str):
        """Send notification when someone lands on site via referral."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    data=f"👀 Referral landing from: {referred_by}",
                    headers={
                        "Title": "Referral Landing",
                        "Priority": "default",
                        "Tags": "eyes,link"
                    }
                ) as resp:
                    if resp.status not in (200, 204):
                        error_text = await resp.text()
                        logger.error(f"ntfy notification failed: {resp.status} - {error_text}")
                    else:
                        logger.info("ntfy landing notification sent successfully")
        except Exception as e:
            logger.error(f"Failed to send ntfy notification: {e}")

    async def send_referral_conversion(self, referred_by: str, username: str):
        """Send notification when someone signs up via referral."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    data=f"🎁 Referral signup! {username} signed up via {referred_by}",
                    headers={
                        "Title": "Referral Signup",
                        "Priority": "high",
                        "Tags": "gift,tada"
                    }
                ) as resp:
                    if resp.status not in (200, 204):
                        error_text = await resp.text()
                        logger.error(f"ntfy notification failed: {resp.status} - {error_text}")
                    else:
                        logger.info("ntfy conversion notification sent successfully")
        except Exception as e:
            logger.error(f"Failed to send ntfy notification: {e}")

# Global instance
ntfy_service = NtfyService()
