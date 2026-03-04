"""
Username validation — single source of truth.

Used by registration, profile update, and availability check endpoints.
"""

import re

USERNAME_REGEX = re.compile(r"^[a-z0-9][a-z0-9_-]{1,48}[a-z0-9]$")

RESERVED_USERNAMES: frozenset[str] = frozenset(
    {
        "admin",
        "api",
        "auth",
        "dashboard",
        "login",
        "logout",
        "marketplace",
        "oauth",
        "register",
        "settings",
        "billing",
        "project",
        "library",
        "feedback",
        "referral",
        "referrals",
        "tesslate",
        "support",
        "help",
        "about",
        "terms",
        "privacy",
        "blog",
        "docs",
        "status",
        "www",
        "mail",
        "root",
        "null",
        "undefined",
        "system",
    }
)

# Consecutive special characters look ugly and cause confusion
_CONSECUTIVE_SPECIAL = re.compile(r"[-_]{2}")


def resolve_display_name(name: str | None, username: str | None, email: str | None = None) -> str:
    """Pick the best display name: name > username > email prefix > 'Unknown'."""
    return name or username or (email.split("@")[0] if email else None) or "Unknown"


def normalize_username(username: str) -> str:
    """Lowercase and strip whitespace."""
    return username.lower().strip()


def validate_username(username: str) -> tuple[bool, str | None]:
    """
    Validate a username string.

    Returns (True, None) on success, or (False, "error message") on failure.
    Reserved-word rejections return a generic message to avoid leaking the blocklist.
    """
    if not isinstance(username, str):
        return False, "Username must be a string"

    if not USERNAME_REGEX.match(username):
        length = len(username)
        if length < 3:
            return False, "Username must be at least 3 characters"
        if length > 50:
            return False, "Username must be at most 50 characters"
        return (
            False,
            "Username can only contain lowercase letters, numbers, hyphens, and underscores, and must start and end with a letter or number",
        )

    if _CONSECUTIVE_SPECIAL.search(username):
        return False, "Username cannot contain consecutive hyphens or underscores"

    if username in RESERVED_USERNAMES:
        # Generic message — never reveal that the word is reserved
        return False, "Username is not available"

    return True, None
