"""
Platform-native message formatting.

Converts markdown-style text to platform-specific formatting:
- Telegram: HTML mode
- Slack: mrkdwn
- Discord: Markdown (native)
- WhatsApp: Bold/italic markers
"""

import html
import re
import logging

logger = logging.getLogger(__name__)


def format_for_telegram(text: str) -> str:
    """Convert markdown to Telegram HTML."""
    # Escape HTML entities FIRST to prevent XSS, then apply markdown formatting.
    text = html.escape(text)
    # Bold: **text** or __text__ → <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Italic: *text* or _text_ → <i>text</i>
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", text)
    # Code: `text` → <code>text</code>
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Code blocks: ```text``` → <pre>text</pre>
    text = re.sub(r"```(?:\w+)?\n?(.*?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)
    return text


def format_for_slack(text: str) -> str:
    """Convert markdown to Slack mrkdwn."""
    # Bold: **text** → *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # Italic: *text* stays as _text_ in Slack
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"_\1_", text)
    # Code blocks: ```lang\n...\n``` → ```\n...\n```
    text = re.sub(r"```\w+\n", "```\n", text)
    return text


def format_for_discord(text: str) -> str:
    """Discord uses standard markdown natively. Minimal conversion needed."""
    return text


def format_for_whatsapp(text: str) -> str:
    """Convert markdown to WhatsApp formatting."""
    # Bold: **text** → *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # Italic: *text* → _text_
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"_\1_", text)
    # Code: `text` → ```text```
    text = re.sub(r"(?<!`)`([^`]+)`(?!`)", r"```\1```", text)
    return text


FORMATTERS = {
    "telegram": format_for_telegram,
    "slack": format_for_slack,
    "discord": format_for_discord,
    "whatsapp": format_for_whatsapp,
}


def format_message(text: str, channel_type: str) -> str:
    """Format a message for the specified channel type."""
    formatter = FORMATTERS.get(channel_type)
    if formatter:
        return formatter(text)
    return text


def split_message(text: str, max_length: int = 4096) -> list[str]:
    """
    Split a long message into chunks respecting the platform's max length.

    Tries to split at paragraph boundaries, then sentence boundaries,
    then word boundaries, falling back to hard split.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to find a good split point
        chunk = remaining[:max_length]

        # Try paragraph break
        split_at = chunk.rfind("\n\n")
        if split_at < max_length // 2:
            # Try newline
            split_at = chunk.rfind("\n")
        if split_at < max_length // 2:
            # Try sentence end
            split_at = chunk.rfind(". ")
            if split_at > 0:
                split_at += 1  # Include the period
        if split_at < max_length // 4:
            # Try space
            split_at = chunk.rfind(" ")
        if split_at < 1:
            # Hard split
            split_at = max_length

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return chunks
