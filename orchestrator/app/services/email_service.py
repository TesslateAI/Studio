"""
Email service for sending transactional emails.

Supports SMTP for production and logs to console as fallback
when SMTP is not configured (local development).
"""

import logging
from email.message import EmailMessage
from functools import lru_cache
from html import escape as html_escape

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

    async def send_password_reset(self, to_email: str, reset_url: str) -> None:
        """
        Send a password reset link via email.

        If SMTP is not configured, logs the reset URL to the console instead.
        This is non-blocking and safe to fire-and-forget via asyncio.create_task.
        """
        subject = "Reset your Tesslate password"

        if not self.is_configured:
            logger.info(
                f"[EMAIL-DEV] Password reset for {to_email}: {reset_url} "
                "(SMTP not configured, printing to console)"
            )
            return

        try:
            html = _build_password_reset_html(reset_url)
            plain = (
                f"You requested a password reset for your Tesslate account.\n\n"
                f"Click the link below to reset your password:\n{reset_url}\n\n"
                "This link expires in 1 hour.\n"
                "If you did not request a password reset, you can safely ignore this email."
            )
            await self._send(to_email, subject, plain, html)
            logger.info(f"Password reset email sent to {to_email}")
        except Exception as e:
            logger.error(f"Failed to send password reset email to {to_email}: {e}")

    async def send_magic_link(self, to_email: str, link_url: str, code: str) -> None:
        """
        Send a passwordless login email containing both a clickable link and a
        6-digit fallback code.

        If SMTP is not configured, logs the link + code to the console instead.
        If test helpers are enabled (TEST_HELPERS_ENABLED=1), also captures
        the entry in an in-memory inbox that Playwright E2E tests can poll.
        This is non-blocking and safe to fire-and-forget via asyncio.create_task.
        """
        subject = "Your Tesslate sign-in link"

        if not self.is_configured:
            logger.info(
                f"[EMAIL-DEV] Magic link for {to_email}: {link_url} "
                f"(code: {code}) (SMTP not configured, printing to console)"
            )
            # E2E test hook — no-op unless TEST_HELPERS_ENABLED is set
            try:
                from ..routers.test_helpers import capture

                capture(to_email, link_url, code)
            except Exception:  # noqa: BLE001 — never let test hook break real sends
                pass
            return

        try:
            html = _build_magic_link_html(link_url, code)
            plain = (
                "Sign in to your Tesslate account.\n\n"
                f"Click the link to sign in:\n{link_url}\n\n"
                f"Or enter this 6-digit code: {code}\n\n"
                "This link and code expire in 10 minutes.\n"
                "If you did not request this, you can safely ignore this email."
            )
            await self._send(to_email, subject, plain, html)
            logger.info(f"Magic-link email sent to {to_email}")
        except Exception as e:
            logger.error(f"Failed to send magic-link email to {to_email}: {e}")

    async def send_team_invite(
        self, to_email: str, invite_url: str, team_name: str, inviter_name: str, role: str
    ) -> None:
        """
        Send a team invitation email.

        If SMTP is not configured, logs the invite URL to the console instead.
        This is non-blocking and safe to fire-and-forget via asyncio.create_task.
        """
        subject = f"You've been invited to {team_name} on Tesslate"

        if not self.is_configured:
            logger.info(
                f"[EMAIL-DEV] Team invite for {to_email}: {invite_url} "
                f"(team={team_name}, role={role}, invited_by={inviter_name}) "
                "(SMTP not configured, printing to console)"
            )
            return

        try:
            html = _build_team_invite_html(invite_url, team_name, inviter_name, role)
            plain = (
                f"{inviter_name} invited you to join {team_name} on Tesslate as {role}.\n\n"
                f"Accept the invitation:\n{invite_url}\n\n"
                "This invitation expires in 7 days.\n"
                "If you weren't expecting this, you can safely ignore this email."
            )
            await self._send(to_email, subject, plain, html)
            logger.info(f"Team invite email sent to {to_email} for team {team_name}")
        except Exception as e:
            logger.error(f"Failed to send team invite email to {to_email}: {e}")

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


def _build_password_reset_html(reset_url: str) -> str:
    """Build a styled HTML email for password reset."""
    safe_url = html_escape(reset_url, quote=True)
    return (
        '<div style="font-family: -apple-system, BlinkMacSystemFont,'
        " 'Segoe UI', Roboto, sans-serif; max-width: 480px;"
        ' margin: 0 auto; padding: 40px 20px;">'
        '<h2 style="color: #111; margin-bottom: 8px;">Reset your password</h2>'
        '<p style="color: #666; font-size: 14px; margin-bottom: 24px;">'
        "Click the button below to reset your password. This link expires in 1 hour."
        "</p>"
        '<div style="text-align: center; margin-bottom: 24px;">'
        f'<a href="{safe_url}" style="display: inline-block; background: #111;'
        " color: #fff; padding: 14px 32px; border-radius: 12px; text-decoration: none;"
        ' font-weight: 600; font-size: 14px;">Reset Password</a>'
        "</div>"
        '<p style="color: #999; font-size: 12px; margin-bottom: 16px;">'
        "If the button doesn&#39;t work, copy and paste this link into your browser:"
        "</p>"
        f'<p style="color: #666; font-size: 12px; word-break: break-all;">{safe_url}</p>'
        '<p style="color: #999; font-size: 12px; margin-top: 24px;">'
        "If you didn&#39;t request this, you can safely ignore this email."
        "</p>"
        "</div>"
    )


def _build_magic_link_html(link_url: str, code: str) -> str:
    """Build a styled HTML email for magic-link login (link + OTP fallback)."""
    safe_url = html_escape(link_url, quote=True)
    safe_code = html_escape(code)
    return (
        '<div style="font-family: -apple-system, BlinkMacSystemFont,'
        " 'Segoe UI', Roboto, sans-serif; max-width: 480px;"
        ' margin: 0 auto; padding: 40px 20px;">'
        '<h2 style="color: #111; margin-bottom: 8px;">Sign in to Tesslate</h2>'
        '<p style="color: #666; font-size: 14px; margin-bottom: 24px;">'
        "Click the button below to sign in. This link expires in 10 minutes."
        "</p>"
        '<div style="text-align: center; margin-bottom: 24px;">'
        f'<a href="{safe_url}" style="display: inline-block; background: #111;'
        " color: #fff; padding: 14px 32px; border-radius: 12px; text-decoration: none;"
        ' font-weight: 600; font-size: 14px;">Sign in</a>'
        "</div>"
        '<p style="color: #999; font-size: 12px; margin-bottom: 8px;">'
        "Or enter this 6-digit code on the sign-in page:"
        "</p>"
        '<div style="background: #f5f5f5; border-radius: 12px; padding: 20px;'
        ' text-align: center; margin-bottom: 24px;">'
        '<span style="font-size: 28px; font-weight: 700; letter-spacing: 6px;'
        f' color: #111;">{safe_code}</span>'
        "</div>"
        '<p style="color: #999; font-size: 12px; margin-bottom: 8px;">'
        "If the button doesn&#39;t work, copy and paste this link:"
        "</p>"
        f'<p style="color: #666; font-size: 12px; word-break: break-all;">{safe_url}</p>'
        '<p style="color: #999; font-size: 12px; margin-top: 24px;">'
        "If you didn&#39;t request this, you can safely ignore this email."
        "</p>"
        "</div>"
    )


def _build_team_invite_html(invite_url: str, team_name: str, inviter_name: str, role: str) -> str:
    """Build a styled HTML email for team invitations."""
    safe_url = html_escape(invite_url, quote=True)
    safe_team = html_escape(team_name)
    safe_inviter = html_escape(inviter_name)
    safe_role = html_escape(role)
    return (
        '<div style="font-family: -apple-system, BlinkMacSystemFont,'
        " 'Segoe UI', Roboto, sans-serif; max-width: 480px;"
        ' margin: 0 auto; padding: 40px 20px;">'
        f'<h2 style="color: #111; margin-bottom: 8px;">Join {safe_team}</h2>'
        f'<p style="color: #666; font-size: 14px; margin-bottom: 24px;">'
        f"{safe_inviter} invited you to join <strong>{safe_team}</strong>"
        f" as <strong>{safe_role}</strong>."
        "</p>"
        '<div style="text-align: center; margin-bottom: 24px;">'
        f'<a href="{safe_url}" style="display: inline-block; background: #111;'
        " color: #fff; padding: 14px 32px; border-radius: 12px; text-decoration: none;"
        ' font-weight: 600; font-size: 14px;">Accept Invitation</a>'
        "</div>"
        '<p style="color: #999; font-size: 12px; margin-bottom: 16px;">'
        "If the button doesn&#39;t work, copy and paste this link into your browser:"
        "</p>"
        f'<p style="color: #666; font-size: 12px; word-break: break-all;">{safe_url}</p>'
        '<p style="color: #999; font-size: 12px; margin-top: 24px;">'
        "This invitation expires in 7 days. "
        "If you weren&#39;t expecting this, you can safely ignore this email."
        "</p>"
        "</div>"
    )


@lru_cache
def get_email_service() -> EmailService:
    """Get the singleton EmailService instance."""
    return EmailService()
