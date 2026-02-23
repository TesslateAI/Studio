"""
Context Compaction

Handles conversation context compaction when approaching context window limits.
Adapted for Tesslate's async infrastructure and ModelAdapter interface.

When the agent's conversation grows large enough to risk exceeding the context window,
this module summarizes older messages and rebuilds a compact conversation history.
"""

import logging
from typing import Any

from .models import ModelAdapter

logger = logging.getLogger(__name__)

# Constants
APPROX_BYTES_PER_TOKEN = 4
COMPACT_USER_MESSAGE_MAX_BYTES = 80_000

# Prefix used to identify summary messages (prevents summary-of-summary bloat)
SUMMARY_PREFIX = "[Previous conversation summary]"

COMPACT_PROMPT = """You are a conversation summarizer. Summarize the key points of the conversation so far, focusing on:
1. What the user asked for
2. What actions were taken (files read, written, commands executed)
3. Important results and discoveries
4. What still needs to be done

Be concise but preserve all important technical details (file paths, error messages, code patterns).
Keep your summary under 2000 tokens."""


def approx_token_count(text: str) -> int:
    """
    Approximate token count from text length.

    Uses the heuristic of ~4 bytes per token.

    Args:
        text: Input text

    Returns:
        Approximate number of tokens
    """
    return len(text.encode("utf-8", errors="replace")) // APPROX_BYTES_PER_TOKEN


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """
    Estimate total token count across all messages.

    Args:
        messages: List of message dicts

    Returns:
        Approximate total tokens
    """
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        if isinstance(content, str):
            total += approx_token_count(content)
        # Account for tool_calls in assistant messages
        tool_calls = msg.get("tool_calls", [])
        for tc in tool_calls:
            if isinstance(tc, dict):
                fn = tc.get("function", {})
                total += approx_token_count(fn.get("name", ""))
                total += approx_token_count(fn.get("arguments", ""))
    return total


def _is_summary_message(msg: dict[str, Any]) -> bool:
    """Check if a message is a previous compaction summary."""
    content = msg.get("content", "")
    return isinstance(content, str) and content.startswith(SUMMARY_PREFIX)


def collect_user_messages(
    messages: list[dict[str, Any]],
    max_bytes: int = COMPACT_USER_MESSAGE_MAX_BYTES,
) -> str:
    """
    Collect user messages for summarization, newest first.

    Filters out system messages and previous summaries to prevent
    summary-of-summary bloat.

    Args:
        messages: Full conversation messages
        max_bytes: Maximum bytes of user content to collect

    Returns:
        Concatenated user message content
    """
    collected = []
    total_bytes = 0

    # Process newest to oldest (reverse order) to prioritize recent context
    for msg in reversed(messages):
        role = msg.get("role", "")

        # Skip system messages and previous summaries
        if role == "system":
            continue
        if _is_summary_message(msg):
            continue

        content = msg.get("content") or ""
        if not isinstance(content, str):
            continue

        content_bytes = len(content.encode("utf-8", errors="replace"))
        if total_bytes + content_bytes > max_bytes:
            # Truncate this message to fit
            remaining = max_bytes - total_bytes
            if remaining > 0:
                collected.append(f"[{role}]: {content[:remaining]}...")
            break

        collected.append(f"[{role}]: {content}")
        total_bytes += content_bytes

    # Reverse back to chronological order
    collected.reverse()
    return "\n\n".join(collected)


def build_compacted_history(
    original_messages: list[dict[str, Any]],
    summary: str,
) -> list[dict[str, Any]]:
    """
    Build a new message list with the summary replacing old messages.

    Preserves:
    - System message (always first)
    - The summary as a prefixed user message
    - Recent messages (last few exchanges)

    Args:
        original_messages: Original full message list
        summary: LLM-generated summary of conversation

    Returns:
        Compacted message list
    """
    new_messages = []

    # Always preserve system messages
    for msg in original_messages:
        if msg.get("role") == "system":
            new_messages.append(msg)
            break

    # Add the summary as a user message with prefix
    new_messages.append(
        {
            "role": "user",
            "content": f"{SUMMARY_PREFIX}\n\n{summary}",
        }
    )

    # Preserve recent messages (last 4 messages, or fewer if conversation is short)
    # This keeps the most recent exchange intact for continuity
    non_system = [m for m in original_messages if m.get("role") != "system"]
    recent_count = min(4, len(non_system))
    if recent_count > 0:
        recent = non_system[-recent_count:]
        # Skip if the first recent message is a tool result without context
        new_messages.extend(recent)

    return new_messages


async def compact_conversation(
    messages: list[dict[str, Any]],
    model_adapter: ModelAdapter,
    context_window: int,
    threshold: float = 0.8,
) -> list[dict[str, Any]] | None:
    """
    Compact conversation if it exceeds the context window threshold.

    This calls the LLM to generate a summary of the conversation, then
    rebuilds the message history with the summary replacing older messages.

    Args:
        messages: Current conversation messages
        model_adapter: Model adapter for generating summary
        context_window: Maximum context window size in tokens
        threshold: Fraction of context window that triggers compaction (0.0-1.0)

    Returns:
        Compacted messages if compaction was performed, None otherwise
    """
    current_tokens = estimate_messages_tokens(messages)
    threshold_tokens = int(context_window * threshold)

    if current_tokens <= threshold_tokens:
        return None

    logger.info(
        f"[Compaction] Triggering: {current_tokens} tokens > {threshold_tokens} threshold "
        f"({threshold:.0%} of {context_window})"
    )

    # Collect user messages for summary
    user_content = collect_user_messages(messages)

    if not user_content.strip():
        logger.warning("[Compaction] No user content to summarize, skipping")
        return None

    # Ask the LLM to summarize
    summary_messages = [
        {"role": "system", "content": COMPACT_PROMPT},
        {"role": "user", "content": f"Summarize this conversation:\n\n{user_content}"},
    ]

    summary = ""
    try:
        async for chunk in model_adapter.chat(summary_messages):
            summary += chunk
    except Exception as e:
        logger.error(f"[Compaction] Failed to generate summary: {e}")
        return None

    if not summary.strip():
        logger.warning("[Compaction] Empty summary generated, skipping")
        return None

    # Build compacted history
    compacted = build_compacted_history(messages, summary)

    compacted_tokens = estimate_messages_tokens(compacted)
    logger.info(
        f"[Compaction] Complete: {current_tokens} -> {compacted_tokens} tokens "
        f"(saved {current_tokens - compacted_tokens} tokens)"
    )

    return compacted
