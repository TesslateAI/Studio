"""
Tool output formatting utilities.

Provides standardized, user-friendly output formatting for agent tools.
"""

from __future__ import annotations

import re
from typing import Any


def success_output(
    message: str,
    details: dict[str, Any] | None = None,
    **extra_fields: Any,
) -> dict[str, Any]:
    """
    Build a standardized tool success payload.

    Args:
        message: User-friendly success message.
        details: Optional technical details shown to advanced callers.
        **extra_fields: Additional top-level fields to include
            (e.g. ``file_path``, ``session_id``).

    Returns:
        A dict with ``success=True``, ``message``, optional ``details``, and
        any extra fields merged in at the top level.
    """
    output: dict[str, Any] = {
        "success": True,
        "message": message,
    }

    if extra_fields:
        output.update(extra_fields)

    if details:
        output["details"] = details

    return output


def error_output(
    message: str,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
    **extra_fields: Any,
) -> dict[str, Any]:
    """
    Build a standardized tool error payload.

    Args:
        message: User-friendly error message.
        suggestion: Optional actionable suggestion for the user.
        details: Optional technical error details.
        **extra_fields: Additional top-level fields to include.

    Returns:
        A dict with ``success=False``, ``message``, optional ``suggestion``,
        optional ``details``, and any extra fields merged in.
    """
    output: dict[str, Any] = {
        "success": False,
        "message": message,
    }

    if suggestion:
        output["suggestion"] = suggestion

    if details:
        output["details"] = details

    if extra_fields:
        output.update(extra_fields)

    return output


def format_file_size(size_bytes: int) -> str:
    """
    Format a byte count in a human-readable way (e.g. ``"1.5 KB"``).

    Args:
        size_bytes: Size in bytes.

    Returns:
        A compact string representation using the largest fitting unit.
    """
    if size_bytes == 1:
        return "1 byte"
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def truncate_session_id(session_id: str, length: int = 8) -> str:
    """
    Return the first ``length`` characters of ``session_id`` for display.
    """
    return session_id[:length]


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    """
    Format ``count`` with ``singular`` or ``plural`` based on magnitude.

    Args:
        count: Numeric count to format.
        singular: Singular form of the word.
        plural: Plural form; defaults to ``singular + "s"``.

    Returns:
        A string like ``"1 file"`` or ``"5 files"``.
    """
    if count == 1:
        return f"{count} {singular}"
    plural_form = plural if plural else f"{singular}s"
    return f"{count} {plural_form}"


def strip_ansi_codes(text: str) -> str:
    """
    Remove ANSI escape sequences and unprintable control characters.

    Keeps newlines and tabs intact; strips cursor movements, color codes,
    and any other common terminal control bytes so the output is safe to
    display in plain text UIs.
    """
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    text = ansi_pattern.sub("", text)

    control_pattern = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")
    text = control_pattern.sub("", text)

    return text
