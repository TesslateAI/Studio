"""
Natural language → cron expression parser.

Rule-based, no LLM call. Handles common scheduling patterns and passes
through valid 5-field cron expressions unchanged.
"""

import re


def parse_schedule(expression: str) -> str:
    """
    Parse a natural language schedule or cron expression into a normalized
    5-field cron expression.

    Examples:
        "every 30m"         → "*/30 * * * *"
        "every 2h"          → "0 */2 * * *"
        "daily at 9am"      → "0 9 * * *"
        "daily at 9:30am"   → "30 9 * * *"
        "weekdays at 9am"   → "0 9 * * 1-5"
        "every monday at 6am" → "0 6 * * 1"
        "nightly at 2am"    → "0 2 * * *"
        "0 9 * * *"         → "0 9 * * *"  (passthrough)

    Raises:
        ValueError: If the expression cannot be parsed.
    """
    expr = expression.strip().lower()

    # Passthrough: already a valid 5-field cron
    if _is_cron(expr):
        return expr

    # "every Nm" or "every N minutes"
    m = re.match(r"every\s+(\d+)\s*m(?:in(?:ute)?s?)?$", expr)
    if m:
        mins = int(m.group(1))
        if mins < 1 or mins > 59:
            raise ValueError(f"Invalid minute interval: {mins}")
        return f"*/{mins} * * * *"

    # "every Nh" or "every N hours"
    m = re.match(r"every\s+(\d+)\s*h(?:ours?)?$", expr)
    if m:
        hours = int(m.group(1))
        if hours < 1 or hours > 23:
            raise ValueError(f"Invalid hour interval: {hours}")
        return f"0 */{hours} * * *"

    # "daily at H:MMam/pm" or "daily at Ham/pm"
    m = re.match(r"(?:daily|every\s*day)\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", expr)
    if m:
        hour, minute, ampm = _parse_time(m.group(1), m.group(2), m.group(3))
        return f"{minute} {hour} * * *"

    # "nightly at ..."
    m = re.match(r"nightly\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", expr)
    if m:
        hour, minute, ampm = _parse_time(m.group(1), m.group(2), m.group(3))
        return f"{minute} {hour} * * *"

    # "weekdays at H:MMam/pm"
    m = re.match(r"weekdays?\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", expr)
    if m:
        hour, minute, _ = _parse_time(m.group(1), m.group(2), m.group(3))
        return f"{minute} {hour} * * 1-5"

    # "weekends at H:MMam/pm"
    m = re.match(r"weekends?\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", expr)
    if m:
        hour, minute, _ = _parse_time(m.group(1), m.group(2), m.group(3))
        return f"{minute} {hour} * * 0,6"

    # "every <weekday> at H:MMam/pm"
    m = re.match(
        r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$",
        expr,
    )
    if m:
        day = _weekday_to_cron(m.group(1))
        hour, minute, _ = _parse_time(m.group(2), m.group(3), m.group(4))
        return f"{minute} {hour} * * {day}"

    # "hourly" / "every hour"
    if expr in ("hourly", "every hour"):
        return "0 * * * *"

    raise ValueError(
        f"Cannot parse schedule: '{expression}'. "
        "Use patterns like 'every 30m', 'daily at 9am', 'weekdays at 9:30am', "
        "or a 5-field cron expression."
    )


def _is_cron(expr: str) -> bool:
    """Check if expression looks like a 5-field cron."""
    parts = expr.split()
    if len(parts) != 5:
        return False
    # Each field should contain only cron-valid characters
    cron_chars = set("0123456789*,/-")
    return all(set(p).issubset(cron_chars) for p in parts)


def _parse_time(
    hour_str: str, minute_str: str | None, ampm: str | None
) -> tuple[int, int, str | None]:
    """Parse time components into 24-hour format."""
    hour = int(hour_str)
    minute = int(minute_str) if minute_str else 0

    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    if hour < 0 or hour > 23:
        raise ValueError(f"Invalid hour: {hour}")
    if minute < 0 or minute > 59:
        raise ValueError(f"Invalid minute: {minute}")

    return hour, minute, ampm


_WEEKDAYS = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}


def _weekday_to_cron(day: str) -> int:
    """Convert weekday name to cron number (0=Sunday)."""
    return _WEEKDAYS[day.lower()]
