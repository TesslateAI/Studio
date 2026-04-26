"""Transactional email rendering for approval cards (Phase 4 fallback).

Email is rung #3 in the delivery fallback chain (after Slack DM and
Telegram DM). The body is intentionally simple:

  * HTML body with the summary, the four buttons rendered as styled
    anchors pointing at the web approval drawer, and a plaintext
    fallback.
  * Plaintext body with the same content, line-broken for clients that
    can't (or won't) render HTML.

Buttons in the HTML are *deeplinks*, not mailto: actions — clicking
"Allow Once" opens the web approval drawer pre-loaded with the
``input_id`` and the chosen response. SMTP doesn't natively support
"reply with a button click"; the deeplink approach gives a single
clickable surface that works in every email client.

We reuse the existing :class:`EmailService` SMTP transport so we get the
same retry/backoff behavior the rest of the platform's transactional
email already gets — no SMTP code duplicated here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape as html_escape
from typing import Any

from ....config import get_settings

logger = logging.getLogger(__name__)


__all__ = [
    "ApprovalEmailContent",
    "build_approval_email",
    "send_approval_email",
    "DEFAULT_ACTIONS",
    "ACTION_LABELS",
]


# Re-exported for callers that want a single import surface.
DEFAULT_ACTIONS: tuple[str, ...] = (
    "allow_once",
    "allow_for_run",
    "allow_permanently",
    "deny",
)

ACTION_LABELS: dict[str, str] = {
    "allow_once": "Allow Once",
    "allow_for_run": "Allow For Run",
    "allow_permanently": "Allow Permanently",
    "deny": "Deny",
}

# Button colours — kept inline so the email is self-contained (some
# clients strip <style> blocks).
_ACTION_COLOR: dict[str, str] = {
    "allow_once": "#16a34a",
    "allow_for_run": "#2563eb",
    "allow_permanently": "#7c3aed",
    "deny": "#dc2626",
}


@dataclass(frozen=True)
class ApprovalEmailContent:
    """Rendered email payload — handed to the SMTP transport as-is."""

    subject: str
    plaintext: str
    html: str


def _deeplink(input_id: str, choice: str | None = None) -> str:
    """Build a web deeplink for the approval drawer.

    The frontend route is ``/approvals/{input_id}?choice=<choice>``.
    Settings ``public_app_url`` is the canonical base URL; we fall back
    to ``http://localhost:5173`` for dev so the link is always present
    (clicking it in dev still opens the local frontend).
    """
    settings = get_settings()
    base = (
        getattr(settings, "public_app_url", None)
        or getattr(settings, "frontend_origin", None)
        or "http://localhost:5173"
    ).rstrip("/")
    suffix = f"?choice={choice}" if choice else ""
    return f"{base}/approvals/{input_id}{suffix}"


def _build_button_html(input_id: str, choice: str) -> str:
    label = ACTION_LABELS.get(choice, choice.replace("_", " ").title())
    color = _ACTION_COLOR.get(choice, "#111827")
    href = html_escape(_deeplink(input_id, choice), quote=True)
    return (
        f'<a href="{href}" '
        f'style="display:inline-block;background:{color};color:#fff;'
        'padding:12px 20px;border-radius:8px;text-decoration:none;'
        'font-weight:600;font-size:14px;margin:4px 4px 4px 0;">'
        f"{html_escape(label)}</a>"
    )


def build_approval_email(
    *,
    input_id: str,
    automation_id: str,
    tool_name: str,
    summary: str,
    actions: list[str] | tuple[str, ...] | None = None,
    automation_name: str | None = None,
) -> ApprovalEmailContent:
    """Render the HTML + plaintext body for an approval-card email.

    Pure function — no I/O. The caller (delivery_fallback) handles the
    actual SMTP send so this module stays unit-testable in isolation.
    """
    actions_list = list(actions) if actions else list(DEFAULT_ACTIONS)
    safe_summary = html_escape((summary or "").strip())
    safe_tool = html_escape(tool_name or "")
    safe_name = html_escape(
        automation_name or f"automation {automation_id[:8]}"
    )

    subject = f"Approval needed: {tool_name or 'Tesslate automation'}"

    buttons_html = "".join(_build_button_html(input_id, c) for c in actions_list)
    deeplink = _deeplink(input_id)
    safe_deeplink = html_escape(deeplink, quote=True)

    html = (
        '<div style="font-family: -apple-system, BlinkMacSystemFont,'
        " 'Segoe UI', Roboto, sans-serif; max-width: 540px;"
        ' margin: 0 auto; padding: 32px 20px;">'
        f'<h2 style="color:#111;margin-bottom:6px;">Approval needed</h2>'
        f'<p style="color:#666;font-size:14px;margin-bottom:20px;">'
        f"<strong>{safe_name}</strong> wants to run "
        f"<code>{safe_tool}</code>.</p>"
        '<div style="background:#f5f5f5;border-radius:10px;padding:16px;'
        'margin-bottom:20px;color:#333;font-size:14px;white-space:pre-wrap;'
        'word-break:break-word;">'
        f"{safe_summary or '(no summary provided)'}"
        "</div>"
        '<div style="margin-bottom:20px;">'
        f"{buttons_html}"
        "</div>"
        '<p style="color:#999;font-size:12px;margin-bottom:6px;">'
        "If the buttons don&#39;t work, open the approval drawer here:</p>"
        f'<p style="color:#666;font-size:12px;word-break:break-all;">'
        f"{safe_deeplink}</p>"
        '<p style="color:#bbb;font-size:11px;margin-top:24px;">'
        f"automation {html_escape(automation_id)} · "
        f"input {html_escape(input_id)}"
        "</p>"
        "</div>"
    )

    plain_lines = [
        "Approval needed",
        "",
        f"{automation_name or 'A Tesslate automation'} wants to run "
        f"{tool_name or 'a tool'}.",
        "",
        (summary or "").strip() or "(no summary provided)",
        "",
        "Choose a response by clicking one of the links below:",
    ]
    for choice in actions_list:
        label = ACTION_LABELS.get(choice, choice)
        plain_lines.append(f"  {label}: {_deeplink(input_id, choice)}")
    plain_lines.append("")
    plain_lines.append(f"Open the approval drawer: {deeplink}")
    plain_lines.append("")
    plain_lines.append(f"automation: {automation_id}")
    plain_lines.append(f"input: {input_id}")

    return ApprovalEmailContent(
        subject=subject,
        plaintext="\n".join(plain_lines),
        html=html,
    )


async def send_approval_email(
    *,
    to_email: str,
    input_id: str,
    automation_id: str,
    tool_name: str,
    summary: str,
    actions: list[str] | tuple[str, ...] | None = None,
    automation_name: str | None = None,
    email_service: Any = None,
) -> bool:
    """Render + send an approval email. Returns ``True`` on success.

    ``email_service`` lets unit tests inject a stub (mirrors the
    dependency-injection pattern the build directive calls out for the
    Slack / Telegram adapters). When omitted, the module-level singleton
    from :func:`get_email_service` is used.
    """
    content = build_approval_email(
        input_id=input_id,
        automation_id=automation_id,
        tool_name=tool_name,
        summary=summary,
        actions=actions,
        automation_name=automation_name,
    )

    if email_service is None:
        try:
            from ...email_service import get_email_service

            email_service = get_email_service()
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "[APPROVAL-EMAIL] failed to import EmailService — skipping"
            )
            return False

    if not getattr(email_service, "is_configured", False):
        # Mirror EmailService dev-mode: log the body so devs can pick a
        # response without an SMTP server in the loop.
        logger.info(
            "[APPROVAL-EMAIL] [dev mode] subject=%r to=%s body=%s",
            content.subject,
            to_email,
            content.plaintext,
        )
        return False

    try:
        await email_service._send(  # type: ignore[attr-defined]
            to_email,
            content.subject,
            content.plaintext,
            content.html,
        )
    except Exception:
        logger.exception(
            "[APPROVAL-EMAIL] SMTP send failed to=%s input_id=%s",
            to_email,
            input_id,
        )
        return False

    logger.info(
        "[APPROVAL-EMAIL] sent to=%s input_id=%s automation=%s",
        to_email,
        input_id,
        automation_id,
    )
    return True
