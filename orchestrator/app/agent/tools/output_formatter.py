"""
Tool Output Formatting Utilities

Provides standardized, user-friendly output formatting for all agent tools.
"""

import re
from typing import Dict, Any, Optional


def success_output(
    message: str,
    details: Optional[Dict[str, Any]] = None,
    **extra_fields
) -> Dict[str, Any]:
    """
    Create a standardized success output.

    Args:
        message: User-friendly success message (REQUIRED)
        details: Technical details for advanced users (optional)
        **extra_fields: Additional fields to include at top level (e.g., file_path, session_id)

    Returns:
        Standardized success output dict
    """
    output = {
        "success": True,
        "message": message,
    }

    # Add extra fields at top level (for agent/backend use)
    if extra_fields:
        output.update(extra_fields)

    # Add details section if provided
    if details:
        output["details"] = details

    return output


def error_output(
    message: str,
    suggestion: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    **extra_fields
) -> Dict[str, Any]:
    """
    Create a standardized error output.

    Args:
        message: User-friendly error message (REQUIRED)
        suggestion: Actionable suggestion for the user (optional but recommended)
        details: Technical error details (optional)
        **extra_fields: Additional fields to include at top level

    Returns:
        Standardized error output dict
    """
    output = {
        "success": False,
        "message": message,
    }

    if suggestion:
        output["suggestion"] = suggestion

    if details:
        output["details"] = details

    # Add extra fields at top level
    if extra_fields:
        output.update(extra_fields)

    return output


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 KB", "2.3 MB")
    """
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def truncate_session_id(session_id: str, length: int = 8) -> str:
    """
    Truncate a session ID for display.

    Args:
        session_id: Full session ID (UUID)
        length: Number of characters to show (default: 8)

    Returns:
        Truncated ID (e.g., "abc12345")
    """
    return session_id[:length]


def pluralize(count: int, singular: str, plural: Optional[str] = None) -> str:
    """
    Pluralize a word based on count.

    Args:
        count: The count
        singular: Singular form (e.g., "file")
        plural: Plural form (optional, defaults to singular + "s")

    Returns:
        Formatted string (e.g., "1 file", "5 files")
    """
    if count == 1:
        return f"{count} {singular}"
    else:
        plural_form = plural if plural else f"{singular}s"
        return f"{count} {plural_form}"


def strip_ansi_codes(text: str) -> str:
    """
    Strip ANSI escape codes and control characters from text.

    This is useful for cleaning shell output that may contain
    terminal control sequences, color codes, cursor movements, etc.

    Args:
        text: Raw text with potential ANSI codes

    Returns:
        Clean text without ANSI codes
    """
    # ANSI escape code pattern (ESC followed by various characters)
    ansi_pattern = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
    text = ansi_pattern.sub('', text)

    # Remove other common control characters (but keep newlines and tabs)
    control_pattern = re.compile(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]')
    text = control_pattern.sub('', text)

    return text
