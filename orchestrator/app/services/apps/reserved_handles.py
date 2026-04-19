"""Reserved handles for users and apps.

These names cannot be claimed as ``users.handle`` or
``marketplace_apps.handle`` because they collide with platform/system
subdomains, infra terms, or generic words we want to keep for ourselves
on ``*.{app_domain}``.
"""

from __future__ import annotations

import re

__all__ = [
    "RESERVED_HANDLES",
    "HANDLE_REGEX",
    "is_reserved",
    "is_valid_handle_format",
]


RESERVED_HANDLES: frozenset[str] = frozenset(
    {
        "admin",
        "api",
        "app",
        "apps",
        "marketplace",
        "studio",
        "www",
        "docs",
        "status",
        "health",
        "blog",
        "support",
        "help",
        "about",
        "login",
        "logout",
        "signup",
        "signin",
        "settings",
        "account",
        "user",
        "users",
        "team",
        "teams",
        "billing",
        "pricing",
        "security",
        "privacy",
        "terms",
        "tesslate",
        "mail",
        "smtp",
        "pop",
        "imap",
        "ftp",
        "ssh",
        "git",
        "vpn",
        "cdn",
        "s3",
        "staging",
        "prod",
        "production",
        "dev",
        "test",
        "localhost",
    }
)


# Single-segment DNS label: lowercase alphanumeric + hyphen, must start
# and end alphanumeric, length 3..32 by default. App handles are allowed
# slightly longer (the regex enforces the inner shape; callers cap length
# at 48 for apps, 32 for users).
HANDLE_REGEX = re.compile(r"^[a-z0-9][a-z0-9-]{1,46}[a-z0-9]$")


def is_reserved(handle: str) -> bool:
    return handle.lower() in RESERVED_HANDLES


def is_valid_handle_format(handle: str, *, max_length: int = 32) -> bool:
    if not isinstance(handle, str):
        return False
    if len(handle) < 3 or len(handle) > max_length:
        return False
    if not HANDLE_REGEX.match(handle):
        return False
    return "--" not in handle
