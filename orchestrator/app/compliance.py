"""
Email compliance guard.

Two config-driven filters on the domain part (after @), evaluated in order:

1. ALLOWED_EMAIL_DOMAINS (allowlist, exact match)
   When non-empty, ONLY emails whose domain exactly matches an entry are
   permitted. All others get 503. Empty = no restriction (default).

2. BLOCKED_EMAIL_DOMAINS (blocklist, suffix match)
   Blocks emails whose domain matches a suffix pattern.
   Supports TLD suffixes (.xx), exact domains (blocked.example), etc.
   Empty = no blocking (default).

Both empty = fully open (default for open-source).
"""

import logging

from fastapi import HTTPException

from .config import get_settings

logger = logging.getLogger(__name__)


def _extract_domain(email: str) -> str | None:
    """Return the lowercase domain part of an email, or None if invalid."""
    at_idx = email.rfind("@")
    if at_idx == -1:
        return None
    return email[at_idx + 1 :].lower()


def _parse_csv(value: str) -> list[str]:
    """Split a comma-separated string into a lowercased, trimmed list."""
    return [d.strip().lower() for d in value.split(",") if d.strip()]


# ---------------------------------------------------------------------------
# Allowlist — exact domain match
# ---------------------------------------------------------------------------


def is_email_allowed(email: str) -> bool:
    """Return True if the email passes the allowlist (or if allowlist is empty)."""
    settings = get_settings()
    if not settings.allowed_email_domains:
        return True  # no allowlist = everything allowed
    allowed = _parse_csv(settings.allowed_email_domains)
    domain = _extract_domain(email)
    if domain is None:
        return False
    return domain in allowed


# ---------------------------------------------------------------------------
# Blocklist — suffix match
# ---------------------------------------------------------------------------


def is_email_blocked(email: str) -> bool:
    """Check if an email's domain matches any blocked pattern."""
    settings = get_settings()
    if not settings.blocked_email_domains:
        return False
    blocked = _parse_csv(settings.blocked_email_domains)
    domain = _extract_domain(email)
    if domain is None:
        return False

    for pattern in blocked:
        if domain == pattern:
            # Exact domain match: "blocked.example" blocks "blocked.example"
            return True
        if domain.endswith("." + pattern):
            # Subdomain match: "blocked.example" blocks "sub.blocked.example"
            return True
        if pattern.startswith(".") and (domain.endswith(pattern) or domain == pattern[1:]):
            # TLD suffix: ".xx" blocks "mail.xx" and "provider.xx"
            return True

    return False


# ---------------------------------------------------------------------------
# Combined enforcement — allowlist first, then blocklist
# ---------------------------------------------------------------------------


def enforce_email_compliance(email: str) -> None:
    """Raise 503 if the email fails allowlist or matches blocklist."""
    if not is_email_allowed(email):
        logger.info("Blocked email outside allowed domains")
        raise HTTPException(
            status_code=403, detail="Registration is restricted to authorized domains"
        )
    if is_email_blocked(email):
        logger.info("Blocked compliance-restricted email attempt")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
