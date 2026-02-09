"""
Email service for sending transactional emails.

Supports SMTP for production and logs to console as fallback
when SMTP is not configured (local development).
"""

import logging
from email.message import EmailMessage
from functools import lru_cache

import aiosmtplib

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EmailService:
    """
    Async email service using aiosmtplib.

    Falls back to logging the email content when SMTP is not configured,
    so local development works without an email provider.
    """

    def __init__(self):
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.use_tls = settings.smtp_use_tls
        self.sender = settings.smtp_sender_email

    @property
    def is_configured(self) -> bool:
        """Check if SMTP is configured (host and sender are required)."""
        return bool(self.host and self.sender)

    async def send_2fa_code(self, to_email: str, code: str) -> None:
        """
        Send a 2FA verification code via email.

        If SMTP is not configured, logs the code to the console instead.
        This is non-blocking and safe to fire-and-forget via asyncio.create_task.
        """
        subject = "Your Tesslate verification code"

        if not self.is_configured:
            logger.info(
                f"[EMAIL-DEV] 2FA code for {to_email}: {code} "
                "(SMTP not configured, printing to console)"
            )
            return

        try:
            digits = list(code)
            html = _build_2fa_html(digits)
            plain = (
                f"Your verification code is: {code}\n\n"
                "This code expires in 10 minutes.\n"
                "If you did not request this code, you can safely ignore this email."
            )
            await self._send(to_email, subject, plain, html)
            logger.info(f"2FA code sent to {to_email}")
        except Exception as e:
            logger.error(f"Failed to send 2FA email to {to_email}: {e}")

    async def _send(self, to_email: str, subject: str, plain: str, html: str | None = None) -> None:
        """Send an email via SMTP with optional HTML body."""
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(plain)
        if html:
            msg.add_alternative(html, subtype="html")

        await aiosmtplib.send(
            msg,
            hostname=self.host,
            port=self.port,
            username=self.username or None,
            password=self.password or None,
            start_tls=self.use_tls,
        )


def _build_2fa_html(digits: list[str]) -> str:
    """Build a styled HTML email for 2FA verification codes."""
    code = "".join(digits)

    return (
        '<div style="font-family: -apple-system, BlinkMacSystemFont,'
        " 'Segoe UI', Roboto, sans-serif; max-width: 480px;"
        ' margin: 0 auto; padding: 40px 20px;">'
        '<h2 style="color: #111; margin-bottom: 8px;">Verification code</h2>'
        '<p style="color: #666; font-size: 14px; margin-bottom: 24px;">'
        "Enter this code to verify your identity. It expires in 10 minutes."
        "</p>"
        '<div style="background: #f5f5f5; border-radius: 12px; padding: 24px;'
        ' text-align: center; margin-bottom: 24px;">'
        '<span style="font-size: 32px; font-weight: 700; letter-spacing: 8px;'
        f' color: #111;">{code}</span>'
        "</div>"
        '<p style="color: #999; font-size: 12px;">'
        "If you didn&#39;t request this code, you can safely ignore this email."
        "</p>"
        "</div>"
    )


@lru_cache
def get_email_service() -> EmailService:
    """Get the singleton EmailService instance."""
    return EmailService()
