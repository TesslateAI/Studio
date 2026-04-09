"""
MCP security utilities — environment filtering and credential stripping.

Shared by both the MCP client (subprocess env) and bridge (error sanitisation).
"""

from __future__ import annotations

import os
import re

# ---------------------------------------------------------------------------
# Environment variable filtering for stdio subprocesses
# ---------------------------------------------------------------------------

# Only these baseline vars are inherited by MCP stdio child processes.
# Everything else (API keys, tokens, database URLs, etc.) must be explicitly
# passed via the server's ``env`` config or injected from user credentials.
_SAFE_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "TERM",
        "SHELL",
        "TMPDIR",
    }
)


def build_safe_env(
    user_env: dict[str, str] | None = None,
    credentials: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a filtered environment dict for an MCP stdio subprocess.

    1. Copy only safe baseline vars from the current process environment.
    2. Include any ``XDG_*`` vars (freedesktop spec).
    3. Merge explicit ``user_env`` from the server config (e.g. custom PATH additions).
    4. Inject decrypted ``credentials`` as environment variables
       (e.g. ``GITHUB_TOKEN``, ``BRAVE_API_KEY``).

    Explicit values always override inherited ones.
    """
    base: dict[str, str] = {
        k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS or k.startswith("XDG_")
    }
    if user_env:
        base.update(user_env)
    if credentials:
        base.update(credentials)
    return base


# ---------------------------------------------------------------------------
# Credential stripping from error messages
# ---------------------------------------------------------------------------

# Patterns that look like secrets.  Matched case-insensitively so that
# ``Token=abc`` and ``TOKEN=abc`` are both caught.
_CRED_PATTERN = re.compile(
    r"ghp_[A-Za-z0-9_]{1,255}"  # GitHub personal access token
    r"|gho_[A-Za-z0-9_]{1,255}"  # GitHub OAuth token
    r"|ghs_[A-Za-z0-9_]{1,255}"  # GitHub app installation token
    r"|github_pat_[A-Za-z0-9_]{1,255}"  # GitHub fine-grained PAT
    r"|sk-[A-Za-z0-9_]{1,255}"  # OpenAI / Anthropic style key
    r"|xoxb-[A-Za-z0-9\-]{1,255}"  # Slack bot token
    r"|xoxp-[A-Za-z0-9\-]{1,255}"  # Slack user token
    r"|Bearer\s+\S+"  # Bearer token in headers
    r"|(?:token|key|api_key|apikey|password|secret|credential)"
    r"=[^\s&\"']{4,}",  # key=value style secrets
    re.IGNORECASE,
)


def sanitize_error(text: str) -> str:
    """Strip credential-like strings from ``text`` before the LLM sees it.

    This is a best-effort defence-in-depth measure — MCP tool errors may
    contain tokens or API keys (e.g. in HTTP headers or connection strings).
    """
    if not text:
        return text
    return _CRED_PATTERN.sub("[REDACTED]", text)
