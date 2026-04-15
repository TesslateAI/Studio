"""
Context Compaction — 5-phase ContextCompressor

Handles conversation context compaction when approaching context window limits.
Ported from Hermes-style structured compression to Tesslate's async ModelAdapter
interface.

Algorithm:
  1. Prune old tool results (cheap pre-pass, no LLM call)
  2. Protect head messages (system prompt + first exchange)
  3. Protect tail messages by token budget (most recent context)
  4. Summarize middle turns with structured LLM prompt
  5. Sanitize orphaned tool_call / tool_result pairs

On subsequent compactions the previous summary is iteratively updated rather
than re-summarized from scratch, preserving accumulated context across
multiple compressions.
"""

from __future__ import annotations

import logging
from typing import Any

from .model_adapters import ModelAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APPROX_BYTES_PER_TOKEN = 4

SUMMARY_PREFIX = (
    "[CONTEXT COMPACTION] Earlier turns in this conversation were compacted "
    "to save context space. The summary below describes work that was "
    "already completed, and the current session state may still reflect "
    "that work (for example, files may already be changed). Use the summary "
    "and the current state to continue from where things left off, and "
    "avoid repeating work:"
)

_PRUNED_TOOL_PLACEHOLDER = "[Old tool output cleared to save context space]"
_MIN_SUMMARY_TOKENS = 2000
_SUMMARY_RATIO = 0.20
_SUMMARY_TOKENS_CEILING = 12_000
_CHARS_PER_TOKEN = 4


def approx_token_count(text: str) -> int:
    """Approximate token count from text length (~4 bytes per token)."""
    return len(text.encode("utf-8", errors="replace")) // APPROX_BYTES_PER_TOKEN


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total token count across all messages."""
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        if isinstance(content, str):
            total += approx_token_count(content)
        for tc in msg.get("tool_calls", []):
            if isinstance(tc, dict):
                fn = tc.get("function", {})
                total += approx_token_count(fn.get("name", ""))
                total += approx_token_count(fn.get("arguments", ""))
    return total


# ---------------------------------------------------------------------------
# ContextCompressor
# ---------------------------------------------------------------------------


class ContextCompressor:
    """Compresses conversation context when approaching the model's limit.

    Algorithm (5 phases):
      1. Prune old tool results (cheap, no LLM call)
      2. Protect head messages (system prompt + first exchange)
      3. Token-budget tail protection (recent context preserved)
      4. Summarize middle turns with structured LLM prompt
      5. Sanitize orphaned tool_call / tool_result pairs

    Iterative: on re-compression the previous summary is updated, not
    re-generated from scratch.
    """

    def __init__(
        self,
        model_adapter: ModelAdapter,
        compaction_adapter: ModelAdapter | None = None,
        context_window: int = 128_000,
        threshold: float = 0.80,
        protect_first_n: int = 3,
        protect_last_n: int = 20,
        summary_target_ratio: float = 0.20,
    ):
        self.model_adapter = model_adapter
        self.compaction_adapter = compaction_adapter
        self.context_window = context_window
        self.threshold = threshold
        self.protect_first_n = protect_first_n
        self.protect_last_n = protect_last_n
        self.summary_target_ratio = max(0.10, min(summary_target_ratio, 0.80))

        # Derived budgets
        self.threshold_tokens = int(context_window * threshold)
        self.tail_token_budget = int(self.threshold_tokens * self.summary_target_ratio)
        self.max_summary_tokens = max(
            _MIN_SUMMARY_TOKENS,
            min(int(context_window * 0.05), _SUMMARY_TOKENS_CEILING),
        )

        # Mutable state
        self._previous_summary: str | None = None
        self.compression_count: int = 0
        self.last_prompt_tokens: int = 0

        logger.info(
            "ContextCompressor initialized: context_window=%d threshold=%d "
            "(%.0f%%) tail_budget=%d max_summary=%d",
            context_window,
            self.threshold_tokens,
            threshold * 100,
            self.tail_token_budget,
            self.max_summary_tokens,
        )

    # ------------------------------------------------------------------
    # Public query helpers
    # ------------------------------------------------------------------

    def should_compress_preflight(self, messages: list[dict[str, Any]]) -> bool:
        """Quick rough-estimate check (before an API call)."""
        return estimate_messages_tokens(messages) >= self.threshold_tokens

    def should_compress(self, prompt_tokens: int | None = None) -> bool:
        """Check using API-reported or cached prompt token count."""
        tokens = prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens
        return tokens >= self.threshold_tokens

    def update_from_usage(self, usage: dict[str, Any]) -> None:
        """Update last_prompt_tokens from an API response usage dict."""
        self.last_prompt_tokens = usage.get("prompt_tokens", 0)

    def get_status(self) -> dict[str, Any]:
        """Return current compression state for logging / display."""
        return {
            "last_prompt_tokens": self.last_prompt_tokens,
            "threshold_tokens": self.threshold_tokens,
            "context_window": self.context_window,
            "usage_percent": (
                min(100.0, self.last_prompt_tokens / self.context_window * 100)
                if self.context_window
                else 0.0
            ),
            "compression_count": self.compression_count,
        }

    # ------------------------------------------------------------------
    # Phase 1: Prune old tool results
    # ------------------------------------------------------------------

    @staticmethod
    def _prune_old_tool_results(
        messages: list[dict[str, Any]],
        protect_tail_count: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Replace old tool result contents (>200 chars) with a placeholder.

        Walks messages, protecting the last ``protect_tail_count`` messages.
        Returns (pruned_messages, count_of_pruned).
        """
        if not messages:
            return messages, 0

        result = [m.copy() for m in messages]
        pruned = 0
        boundary = len(result) - protect_tail_count

        for i in range(max(boundary, 0)):
            msg = result[i]
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if not content or content == _PRUNED_TOOL_PLACEHOLDER:
                continue
            if len(content) > 200:
                result[i] = {**msg, "content": _PRUNED_TOOL_PLACEHOLDER}
                pruned += 1

        return result, pruned

    # ------------------------------------------------------------------
    # Boundary alignment helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _align_boundary_forward(messages: list[dict[str, Any]], idx: int) -> int:
        """Push boundary forward past orphaned tool results."""
        while idx < len(messages) and messages[idx].get("role") == "tool":
            idx += 1
        return idx

    @staticmethod
    def _align_boundary_backward(messages: list[dict[str, Any]], idx: int) -> int:
        """Pull boundary back to avoid splitting tool_call/result groups.

        If the boundary falls in the middle of a tool-result group, walk
        backward past consecutive tool messages to find the parent assistant
        message and move the boundary before it.
        """
        if idx <= 0 or idx >= len(messages):
            return idx
        check = idx - 1
        while check >= 0 and messages[check].get("role") == "tool":
            check -= 1
        if (
            check >= 0
            and messages[check].get("role") == "assistant"
            and messages[check].get("tool_calls")
        ):
            idx = check
        return idx

    # ------------------------------------------------------------------
    # Tail protection by token budget
    # ------------------------------------------------------------------

    def _find_tail_cut_by_tokens(
        self,
        messages: list[dict[str, Any]],
        head_end: int,
        token_budget: int | None = None,
    ) -> int:
        """Walk backward from end accumulating tokens until budget exhausted.

        Returns the index where the protected tail starts. Never cuts
        inside a tool_call/result group. Falls back to ``protect_last_n``
        if the budget would protect fewer messages.
        """
        if token_budget is None:
            token_budget = self.tail_token_budget

        n = len(messages)
        min_tail = self.protect_last_n
        accumulated = 0
        cut_idx = n

        for i in range(n - 1, head_end - 1, -1):
            msg = messages[i]
            content = msg.get("content") or ""
            msg_tokens = len(content) // _CHARS_PER_TOKEN + 10
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict):
                    args = tc.get("function", {}).get("arguments", "")
                    msg_tokens += len(args) // _CHARS_PER_TOKEN
            if accumulated + msg_tokens > token_budget and (n - i) >= min_tail:
                break
            accumulated += msg_tokens
            cut_idx = i

        # Ensure at least protect_last_n
        fallback_cut = n - min_tail
        if cut_idx > fallback_cut:
            cut_idx = fallback_cut

        # If budget would protect everything, fall back to fixed count
        if cut_idx <= head_end:
            cut_idx = fallback_cut

        cut_idx = self._align_boundary_backward(messages, cut_idx)
        return max(cut_idx, head_end + 1)

    # ------------------------------------------------------------------
    # Serialization for summarizer
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_for_summary(turns: list[dict[str, Any]]) -> str:
        """Convert turns to labeled text for the summarizer LLM.

        Format:
          [USER]: content
          [ASSISTANT]: content + [Tool calls: name(args)]
          [TOOL RESULT call_id]: content

        Individual messages truncated to 3000 chars, tool args to 500 chars.
        """
        parts: list[str] = []
        for msg in turns:
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""

            if role == "tool":
                tool_id = msg.get("tool_call_id", "")
                if len(content) > 3000:
                    content = content[:2000] + "\n...[truncated]...\n" + content[-800:]
                parts.append(f"[TOOL RESULT {tool_id}]: {content}")
                continue

            if role == "assistant":
                if len(content) > 3000:
                    content = content[:2000] + "\n...[truncated]...\n" + content[-800:]
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    tc_parts: list[str] = []
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            name = fn.get("name", "?")
                            args = fn.get("arguments", "")
                            if len(args) > 500:
                                args = args[:400] + "..."
                            tc_parts.append(f"  {name}({args})")
                        else:
                            fn = getattr(tc, "function", None)
                            name = getattr(fn, "name", "?") if fn else "?"
                            tc_parts.append(f"  {name}(...)")
                    content += "\n[Tool calls:\n" + "\n".join(tc_parts) + "\n]"
                parts.append(f"[ASSISTANT]: {content}")
                continue

            # User and other roles
            if len(content) > 3000:
                content = content[:2000] + "\n...[truncated]...\n" + content[-800:]
            parts.append(f"[{role.upper()}]: {content}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Summary budget
    # ------------------------------------------------------------------

    def _compute_summary_budget(self, turns: list[dict[str, Any]]) -> int:
        """Scale summary token budget proportional to compressed content."""
        content_tokens = estimate_messages_tokens(turns)
        budget = int(content_tokens * _SUMMARY_RATIO)
        return max(_MIN_SUMMARY_TOKENS, min(budget, self.max_summary_tokens))

    # ------------------------------------------------------------------
    # Summary generation (async)
    # ------------------------------------------------------------------

    def _get_summary_adapter(self) -> ModelAdapter:
        """Return the adapter to use for summary generation."""
        return self.compaction_adapter if self.compaction_adapter else self.model_adapter

    async def _generate_summary(self, turns: list[dict[str, Any]]) -> str | None:
        """Generate a structured summary of conversation turns.

        First compaction: structured template from scratch.
        Subsequent: iteratively update the previous summary with new turns.

        Returns None on failure (caller drops middle turns without summary).
        """
        summary_budget = self._compute_summary_budget(turns)
        content_to_summarize = self._serialize_for_summary(turns)

        if self._previous_summary:
            prompt = f"""You are updating a context compaction summary. A previous compaction produced the summary below. New conversation turns have occurred since then and need to be incorporated.

PREVIOUS SUMMARY:
{self._previous_summary}

NEW TURNS TO INCORPORATE:
{content_to_summarize}

Update the summary using this exact structure. PRESERVE all existing information that is still relevant. ADD new progress. Move items from "In Progress" to "Done" when completed. Remove information only if it is clearly obsolete.

## Goal
[What the user is trying to accomplish — preserve from previous summary, update if goal evolved]

## Constraints & Preferences
[User preferences, coding style, constraints, important decisions — accumulate across compactions]

## Progress
### Done
[Completed work — include specific file paths, commands run, results obtained]
### In Progress
[Work currently underway]
### Blocked
[Any blockers or issues encountered]

## Key Decisions
[Important technical decisions and why they were made]

## Relevant Files
[Files read, modified, or created — with brief note on each. Accumulate across compactions.]

## Next Steps
[What needs to happen next to continue the work]

## Critical Context
[Any specific values, error messages, configuration details, or data that would be lost without explicit preservation]

Target ~{summary_budget} tokens. Be specific — include file paths, command outputs, error messages, and concrete values rather than vague descriptions.

Write only the summary body. Do not include any preamble or prefix."""
        else:
            prompt = f"""Create a structured handoff summary for a later assistant that will continue this conversation after earlier turns are compacted.

TURNS TO SUMMARIZE:
{content_to_summarize}

Use this exact structure:

## Goal
[What the user is trying to accomplish]

## Constraints & Preferences
[User preferences, coding style, constraints, important decisions]

## Progress
### Done
[Completed work — include specific file paths, commands run, results obtained]
### In Progress
[Work currently underway]
### Blocked
[Any blockers or issues encountered]

## Key Decisions
[Important technical decisions and why they were made]

## Relevant Files
[Files read, modified, or created — with brief note on each]

## Next Steps
[What needs to happen next to continue the work]

## Critical Context
[Any specific values, error messages, configuration details, or data that would be lost without explicit preservation]

Target ~{summary_budget} tokens. Be specific — include file paths, command outputs, error messages, and concrete values rather than vague descriptions. The goal is to prevent the next assistant from repeating work or losing important details.

Write only the summary body. Do not include any preamble or prefix."""

        adapter = self._get_summary_adapter()
        summary_messages = [{"role": "user", "content": prompt}]

        try:
            summary = ""
            async for chunk in adapter.chat(
                summary_messages,
                temperature=0.3,
                max_tokens=summary_budget * 2,
            ):
                summary += chunk

            summary = summary.strip()
            if not summary:
                logger.warning("[Compaction] Empty summary generated")
                return None

            # Store raw summary (without prefix) for iterative updates
            self._previous_summary = summary
            return f"{SUMMARY_PREFIX}\n{summary}"

        except Exception as e:
            logger.warning("[Compaction] Failed to generate summary: %s", e)
            return None

    # ------------------------------------------------------------------
    # Tool pair sanitization
    # ------------------------------------------------------------------

    @staticmethod
    def _get_tool_call_id(tc: Any) -> str:
        """Extract call ID from a tool_call entry (dict or object)."""
        if isinstance(tc, dict):
            return tc.get("id", "")
        return getattr(tc, "id", "") or ""

    def _sanitize_tool_pairs(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fix orphaned tool_call / tool_result pairs after compression.

        1. Remove tool results whose call_id has no matching assistant tool_call.
        2. Insert stub results for assistant tool_calls whose results were dropped.
        """
        surviving_call_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    cid = self._get_tool_call_id(tc)
                    if cid:
                        surviving_call_ids.add(cid)

        result_call_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "tool":
                cid = msg.get("tool_call_id")
                if cid:
                    result_call_ids.add(cid)

        # Remove orphaned tool results
        orphaned_results = result_call_ids - surviving_call_ids
        if orphaned_results:
            messages = [
                m
                for m in messages
                if not (m.get("role") == "tool" and m.get("tool_call_id") in orphaned_results)
            ]
            logger.info(
                "Compression sanitizer: removed %d orphaned tool result(s)",
                len(orphaned_results),
            )

        # Insert stub results for orphaned tool calls
        missing_results = surviving_call_ids - result_call_ids
        if missing_results:
            patched: list[dict[str, Any]] = []
            for msg in messages:
                patched.append(msg)
                if msg.get("role") == "assistant":
                    for tc in msg.get("tool_calls") or []:
                        cid = self._get_tool_call_id(tc)
                        if cid in missing_results:
                            patched.append(
                                {
                                    "role": "tool",
                                    "content": "[Result from earlier -- see context summary above]",
                                    "tool_call_id": cid,
                                }
                            )
            messages = patched
            logger.info(
                "Compression sanitizer: added %d stub tool result(s)",
                len(missing_results),
            )

        return messages

    # ------------------------------------------------------------------
    # Main compression entry point (async)
    # ------------------------------------------------------------------

    async def compress(
        self,
        messages: list[dict[str, Any]],
        current_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        """Compress conversation messages via 5-phase algorithm.

        1. Prune old tool results (cheap pre-pass)
        2. Protect head (first ``protect_first_n`` messages)
        3. Token-budget tail boundary
        4. Summarize middle turns
        5. Sanitize tool pairs

        Returns the compressed message list.
        """
        n_messages = len(messages)
        if n_messages <= self.protect_first_n + self.protect_last_n + 1:
            logger.warning(
                "Cannot compress: only %d messages (need > %d)",
                n_messages,
                self.protect_first_n + self.protect_last_n + 1,
            )
            return messages

        display_tokens = (
            current_tokens or self.last_prompt_tokens or estimate_messages_tokens(messages)
        )

        # Phase 1: Prune old tool results
        messages, pruned_count = self._prune_old_tool_results(
            messages, protect_tail_count=self.protect_last_n * 3
        )
        if pruned_count:
            logger.info("Phase 1: pruned %d old tool result(s)", pruned_count)

        # Phase 2: Head protection
        compress_start = self._align_boundary_forward(messages, self.protect_first_n)

        # Phase 3: Tail boundary by token budget
        compress_end = self._find_tail_cut_by_tokens(messages, compress_start)

        if compress_start >= compress_end:
            return messages

        turns_to_summarize = messages[compress_start:compress_end]

        logger.info(
            "Context compression triggered (%d tokens >= %d threshold). "
            "Summarizing turns %d-%d (%d turns), protecting %d head + %d tail.",
            display_tokens,
            self.threshold_tokens,
            compress_start + 1,
            compress_end,
            len(turns_to_summarize),
            compress_start,
            n_messages - compress_end,
        )

        # Phase 4: Generate summary
        summary = await self._generate_summary(turns_to_summarize)

        # Assemble compressed list: head + summary + tail
        compressed: list[dict[str, Any]] = []

        # Head messages
        for i in range(compress_start):
            msg = messages[i].copy()
            if i == 0 and msg.get("role") == "system" and self.compression_count == 0:
                msg["content"] = (
                    (msg.get("content") or "")
                    + "\n\n[Note: Some earlier conversation turns have been "
                    "compacted into a handoff summary to preserve context "
                    "space. The current session state may still reflect "
                    "earlier work, so build on that summary and state rather "
                    "than re-doing work.]"
                )
            compressed.append(msg)

        # Role-aware summary injection
        _merge_into_tail = False
        if summary:
            last_head_role = (
                messages[compress_start - 1].get("role", "user") if compress_start > 0 else "user"
            )
            first_tail_role = (
                messages[compress_end].get("role", "user") if compress_end < n_messages else "user"
            )

            # Pick role that avoids consecutive same-role with both neighbors
            summary_role = "user" if last_head_role in ("assistant", "tool") else "assistant"

            if summary_role == first_tail_role:
                flipped = "assistant" if summary_role == "user" else "user"
                if flipped != last_head_role:
                    summary_role = flipped
                else:
                    # Both roles would collide — merge into first tail message
                    _merge_into_tail = True

            if not _merge_into_tail:
                compressed.append({"role": summary_role, "content": summary})
        else:
            logger.warning("No summary generated — middle turns dropped without summary")

        # Tail messages
        for i in range(compress_end, n_messages):
            msg = messages[i].copy()
            if _merge_into_tail and i == compress_end:
                original = msg.get("content") or ""
                msg["content"] = summary + "\n\n" + original
                _merge_into_tail = False
            compressed.append(msg)

        self.compression_count += 1

        # Phase 5: Sanitize tool pairs
        compressed = self._sanitize_tool_pairs(compressed)

        new_estimate = estimate_messages_tokens(compressed)
        logger.info(
            "Compressed: %d -> %d messages (~%d tokens saved). Compression #%d complete.",
            n_messages,
            len(compressed),
            display_tokens - new_estimate,
            self.compression_count,
        )

        return compressed
