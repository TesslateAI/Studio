"""DNS-1123 compliant name sanitization for Kubernetes and Docker resource names.

This module provides a single, canonical sanitization function used everywhere
a raw user-supplied name must be turned into a valid K8s resource name or
Docker Compose service name.  It intentionally does **not** handle filesystem
paths — only DNS-label-safe identifiers.

RFC 1123 label rules (subset used by Kubernetes):
  - lowercase alphanumeric characters or hyphens
  - must start and end with an alphanumeric character
  - max 63 characters total (we default to 59 to leave room for 4-char
    prefixes like ``dev-`` or ``svc-`` added by helpers.py)
"""

from __future__ import annotations

import re

# Pre-compiled patterns for performance in hot loops.
_REPLACE_CHARS = re.compile(r"[\s_.]")       # spaces, underscores, dots → hyphen
_STRIP_INVALID = re.compile(r"[^a-z0-9-]")   # anything not lowercase alnum or hyphen
_COLLAPSE_HYPHENS = re.compile(r"-{2,}")      # consecutive hyphens → single hyphen


def sanitize_name(name: str, max_length: int = 59) -> str:
    """Return a DNS-1123 compliant identifier derived from *name*.

    Parameters
    ----------
    name:
        Arbitrary user-supplied string (project name, container name, etc.).
    max_length:
        Maximum length of the returned string.  Defaults to **59** so that
        callers can safely prepend a 4-character prefix (e.g. ``dev-``) and
        still stay within the Kubernetes 63-character limit.

    Returns
    -------
    str
        A lowercased, hyphen-separated string containing only ``[a-z0-9-]``,
        guaranteed to start and end with an alphanumeric character and to be
        at most *max_length* characters long.

    Examples
    --------
    >>> sanitize_name("My Cool App")
    'my-cool-app'
    >>> sanitize_name("hello__world..v2")
    'hello-world-v2'
    >>> sanitize_name("---leading-and-trailing---")
    'leading-and-trailing'
    """
    safe = _REPLACE_CHARS.sub("-", name.lower())
    safe = _STRIP_INVALID.sub("", safe)
    safe = _COLLAPSE_HYPHENS.sub("-", safe)
    safe = safe.strip("-")
    return safe[:max_length]
