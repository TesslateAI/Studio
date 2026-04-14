"""
Fuzzy Editor

Multi-strategy search/replace engine shared by ``patch_file``,
``multi_edit``, and ``apply_patch``. Ports the three-strategy pipeline
(exact → flexible whitespace → Levenshtein fuzzy) with an optional LLM
repair pass for cases where every strategy fails.

Strategies (in order):
    1. **Exact**       — literal ``old_str`` occurrences. Honors
       ``expected_occurrence`` / ``allow_multiple``.
    2. **Flexible**    — line-by-line whitespace-normalized sliding
       window. Replaces the ORIGINAL slice so indentation is preserved
       on the replacement lines.
    3. **Fuzzy (Levenshtein)** — slides a window of length
       ``len(old_str)`` (character-based) across the file, computes
       Levenshtein distance on each window, and replaces when the best
       window has ``distance / len(old_str) <= 0.10`` AND is uniquely
       best (no tie). Minimum needle length for fuzzy: 10 characters.

If all three strategies fail, :func:`apply_edit` optionally invokes an
LLM repair pass (see :func:`llm_repair`). The repair model is asked to
return a corrected ``old_str`` / ``new_str`` pair; strategies 1–3 are
then retried once with the corrected values. Repair is capped at a
single retry.

Callers are also protected against placeholder-style omissions in
``new_str``: lines that are exactly ``...``, ``// ...``, or ``# ...``
(optionally surrounded by whitespace) are rejected before any strategy
runs.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

FUZZY_MATCH_THRESHOLD = 0.10
FUZZY_MIN_NEEDLE_LEN = 10

# Placeholder regexes: one per supported line shape.
_PLACEHOLDER_PATTERNS = (
    re.compile(r"^\s*\.\.\.\s*$"),
    re.compile(r"^\s*//\s*\.\.\.\s*$"),
    re.compile(r"^\s*#\s*\.\.\.\s*$"),
)


class EditError(Exception):
    """
    Raised by :func:`apply_edit` when no strategy (and no repair pass)
    produced a valid replacement.

    The ``attempted`` attribute names the strategies that were tried so
    callers can surface a targeted suggestion to the user.
    """

    def __init__(
        self,
        message: str,
        attempted: list[str],
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        self.attempted = attempted
        self.suggestion = suggestion


@dataclass
class EditResult:
    """Outcome of a successful :func:`apply_edit` call."""

    content: str
    strategy: str
    occurrences: int
    final_old_str: str
    final_new_str: str
    repair_applied: bool = False


# =============================================================================
# Placeholder detection
# =============================================================================


def contains_omission_placeholder(text: str) -> bool:
    """
    Return True if ``text`` has a line that is exactly the ``...`` /
    ``// ...`` / ``# ...`` omission marker.
    """
    for line in text.splitlines():
        for pat in _PLACEHOLDER_PATTERNS:
            if pat.match(line):
                return True
    return False


# =============================================================================
# Strategy 1 — exact match
# =============================================================================


def _strategy_exact(
    content: str,
    old_str: str,
    new_str: str,
    *,
    expected_occurrence: int,
    allow_multiple: bool,
) -> tuple[str | None, int]:
    """
    Literal match. Honors ``expected_occurrence`` / ``allow_multiple``.

    Returns:
        ``(new_content, count)`` when the strategy made (or would make)
        a decision, or ``(None, count)`` when it should fall through to
        the next strategy. A count of 0 always falls through.
    """
    count = content.count(old_str) if old_str else 0
    if count == 0:
        return None, 0

    if allow_multiple:
        return content.replace(old_str, new_str), count

    if count != expected_occurrence:
        # Signal mismatch by returning the count and None — callers
        # decide whether to fall through or error out.
        return None, count

    # Replace exactly ``expected_occurrence`` occurrences from left to right.
    result = content.replace(old_str, new_str, expected_occurrence)
    return result, count


# =============================================================================
# Strategy 2 — flexible whitespace match
# =============================================================================


def _normalize_whitespace(s: str) -> str:
    """Collapse any run of whitespace in ``s`` into a single space."""
    return re.sub(r"\s+", " ", s).strip()


def _strategy_flexible(
    content: str,
    old_str: str,
    new_str: str,
    *,
    expected_occurrence: int,
    allow_multiple: bool,
) -> tuple[str | None, int]:
    """
    Line-by-line whitespace-insensitive sliding window match.

    The needle is split into lines; each line is whitespace-normalized.
    We then slide a window of the same line count across the source and
    compare whitespace-normalized line arrays. When a match is found we
    replace the original slice (preserving indentation of the first line
    of the match) with the replacement text.
    """
    if not old_str:
        return None, 0

    source_lines = content.splitlines(keepends=True)
    # Drop purely-whitespace lines from the needle so agents that inject
    # extra blank lines can still match the underlying content.
    search_significant = [
        re.sub(r"\s+", " ", ln).strip() for ln in old_str.splitlines() if ln.strip()
    ]
    if not search_significant:
        return None, 0

    replace_lines = new_str.splitlines()
    needed = len(search_significant)

    match_runs: list[tuple[int, int]] = []  # (start, end-exclusive)

    i = 0
    while i < len(source_lines):
        # Grow the window until we've collected `needed` non-blank lines,
        # allowing arbitrary blank lines between them.
        j = i
        significant_matched = 0
        window_end = i
        matched = True
        while significant_matched < needed and j < len(source_lines):
            source_line = source_lines[j]
            stripped = source_line.strip()
            if not stripped:
                j += 1
                continue
            normalized = re.sub(r"\s+", " ", stripped)
            if normalized != search_significant[significant_matched]:
                matched = False
                break
            significant_matched += 1
            j += 1
            window_end = j
        if matched and significant_matched == needed:
            match_runs.append((i, window_end))
            i = window_end
            continue
        i += 1

    count = len(match_runs)
    if count == 0:
        return None, 0

    if not allow_multiple and count != expected_occurrence:
        return None, count

    targets = match_runs if allow_multiple else match_runs[:expected_occurrence]

    # Apply from bottom to top so earlier indices stay valid.
    modified = list(source_lines)
    for start, end in reversed(targets):
        first_line = modified[start]
        indent_match = re.match(r"^([ \t]*)", first_line)
        indent = indent_match.group(1) if indent_match else ""
        had_trailing_newline = modified[end - 1].endswith("\n")

        indented_replacement = _apply_indentation(replace_lines, indent)
        replacement_text = "\n".join(indented_replacement)
        if had_trailing_newline and not replacement_text.endswith("\n"):
            replacement_text += "\n"

        modified[start:end] = [replacement_text]

    return "".join(modified), count


def _apply_indentation(lines: list[str], target_indent: str) -> list[str]:
    """
    Indent ``lines`` by ``target_indent`` while preserving their relative
    indentation against the first non-empty line's own indent.
    """
    if not lines:
        return []
    reference = lines[0]
    ref_indent_match = re.match(r"^([ \t]*)", reference)
    ref_indent = ref_indent_match.group(1) if ref_indent_match else ""

    out: list[str] = []
    for line in lines:
        if not line.strip():
            out.append("")
            continue
        if line.startswith(ref_indent):
            out.append(target_indent + line[len(ref_indent) :])
        else:
            out.append(target_indent + line.lstrip())
    return out


# =============================================================================
# Strategy 3 — Levenshtein fuzzy
# =============================================================================


def _levenshtein(a: str, b: str) -> int:
    """
    Compute the Levenshtein distance between ``a`` and ``b``.

    Uses the standard two-row dynamic programming formulation — adequate
    for the window sizes fuzzy match targets (bounded by the complexity
    guard below).
    """
    if a == b:
        return 0
    if len(a) == 0:
        return len(b)
    if len(b) == 0:
        return len(a)

    if len(a) < len(b):
        a, b = b, a

    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)
    for i, ca in enumerate(a, 1):
        curr[0] = i
        for j, cb in enumerate(b, 1):
            insert = curr[j - 1] + 1
            delete = prev[j] + 1
            substitute = prev[j - 1] + (0 if ca == cb else 1)
            curr[j] = min(insert, delete, substitute)
        prev, curr = curr, prev
    return prev[len(b)]


def _strategy_fuzzy(
    content: str,
    old_str: str,
    new_str: str,
) -> tuple[str | None, int]:
    """
    Character-window Levenshtein fuzzy match.

    Slides a window of exactly ``len(old_str)`` characters across
    ``content``, scores each window by distance / needle length, and
    only applies a replacement when:

        * there is at least one candidate under the 10% threshold, AND
        * the lowest-scoring candidate is strictly better than every
          other candidate (i.e., no ties at the best score).

    Returns ``(None, 0)`` when the strategy doesn't apply (needle too
    short, no candidates, ambiguous best).
    """
    needle_len = len(old_str)
    if needle_len < FUZZY_MIN_NEEDLE_LEN:
        return None, 0

    # Soft complexity guard so a huge file doesn't freeze the worker.
    # O(N * M^2) ballpark, capped at 4e8 basic ops.
    if len(content) * (needle_len**2) > 400_000_000:
        return None, 0

    best_score = float("inf")
    best_idx = -1
    ties = 0

    span = len(content) - needle_len
    for i in range(span + 1):
        window = content[i : i + needle_len]
        # Fast length-diff guard (identical lengths since we slice needle_len).
        dist = _levenshtein(window, old_str)
        score = dist / needle_len
        if score < best_score:
            best_score = score
            best_idx = i
            ties = 1
        elif score == best_score:
            ties += 1

    if best_idx < 0 or best_score > FUZZY_MATCH_THRESHOLD:
        return None, 0
    if ties > 1:
        # Ambiguous best: refuse rather than guess.
        return None, ties

    new_content = content[:best_idx] + new_str + content[best_idx + needle_len :]
    return new_content, 1


# =============================================================================
# Top-level entry point
# =============================================================================


RepairFn = Callable[[str, str, str, str], "RepairSuggestion | None"]


@dataclass
class RepairSuggestion:
    """Structured payload returned by an LLM repair callback."""

    old_str: str
    new_str: str


async def apply_edit(
    *,
    content: str,
    old_str: str,
    new_str: str,
    expected_occurrence: int = 1,
    allow_multiple: bool = False,
    file_path: str | None = None,
    repair_fn: RepairAsyncFn | None = None,
) -> EditResult:
    """
    Run the full strategy pipeline against ``content`` and return a
    successful :class:`EditResult`, or raise :class:`EditError`.

    Args:
        content: Current file content.
        old_str: Text to search for.
        new_str: Replacement text.
        expected_occurrence: Expected count for exact / flexible
            strategies when ``allow_multiple`` is False.
        allow_multiple: When True, replace every match regardless of
            count.
        file_path: Optional file path — used in error messages and
            forwarded to the repair callback for context.
        repair_fn: Optional async callable
            ``async (file_path, content, old_str, new_str) -> RepairSuggestion | None``.
            When provided and the primary pipeline fails, it is invoked
            exactly once; the returned suggestion is then fed back
            through strategies 1–3.

    Returns:
        :class:`EditResult` describing the modification.

    Raises:
        EditError: If the pipeline (and optional repair) fails.
    """
    if contains_omission_placeholder(new_str):
        raise EditError(
            message="new_str contains an omission placeholder — provide the full replacement",
            attempted=["placeholder_check"],
            suggestion=(
                "Replace any `...`, `// ...`, or `# ...` lines in new_str with the "
                "exact literal code you want in the file."
            ),
        )

    try:
        return _run_pipeline(
            content=content,
            old_str=old_str,
            new_str=new_str,
            expected_occurrence=expected_occurrence,
            allow_multiple=allow_multiple,
            file_path=file_path,
        )
    except EditError as initial_error:
        if repair_fn is None:
            raise

        suggestion = None
        try:
            suggestion = await repair_fn(
                file_path or "<unknown>",
                content,
                old_str,
                new_str,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[FUZZY-EDIT] repair_fn raised: %s", exc)
            suggestion = None

        if suggestion is None:
            raise initial_error

        if contains_omission_placeholder(suggestion.new_str):
            raise EditError(
                message="Repaired new_str still contains an omission placeholder",
                attempted=initial_error.attempted + ["llm_repair"],
                suggestion=(
                    "Ask the repair model to emit literal replacement text — no `...` shorthand."
                ),
            ) from initial_error

        try:
            result = _run_pipeline(
                content=content,
                old_str=suggestion.old_str,
                new_str=suggestion.new_str,
                expected_occurrence=expected_occurrence,
                allow_multiple=allow_multiple,
                file_path=file_path,
            )
        except EditError as repair_error:
            raise EditError(
                message=(
                    f"{initial_error.args[0]}; repair pass also failed: {repair_error.args[0]}"
                ),
                attempted=initial_error.attempted + ["llm_repair"] + repair_error.attempted,
                suggestion=repair_error.suggestion or initial_error.suggestion,
            ) from repair_error

        result.repair_applied = True
        return result


def _run_pipeline(
    *,
    content: str,
    old_str: str,
    new_str: str,
    expected_occurrence: int,
    allow_multiple: bool,
    file_path: str | None,
) -> EditResult:
    """Run strategies 1→3. Raise EditError on exhaustion."""
    if not old_str:
        raise EditError(
            message="old_str is empty",
            attempted=[],
            suggestion="Provide the exact text to search for.",
        )

    attempted: list[str] = []

    # Strategy 1: exact
    attempted.append("exact")
    exact_result, exact_count = _strategy_exact(
        content,
        old_str,
        new_str,
        expected_occurrence=expected_occurrence,
        allow_multiple=allow_multiple,
    )
    if exact_result is not None:
        occurrences = exact_count if allow_multiple else min(exact_count, expected_occurrence)
        return EditResult(
            content=exact_result,
            strategy="exact",
            occurrences=occurrences,
            final_old_str=old_str,
            final_new_str=new_str,
        )
    if exact_count > 0 and not allow_multiple and exact_count != expected_occurrence:
        raise EditError(
            message=(
                f"Expected {expected_occurrence} occurrence(s) but found "
                f"{exact_count} in {file_path or 'file'}"
            ),
            attempted=attempted,
            suggestion=(
                "Set allow_multiple=true to replace every match, or add more "
                "surrounding context to make old_str unique."
            ),
        )

    # Strategy 2: flexible whitespace
    attempted.append("flexible")
    flex_result, flex_count = _strategy_flexible(
        content,
        old_str,
        new_str,
        expected_occurrence=expected_occurrence,
        allow_multiple=allow_multiple,
    )
    if flex_result is not None:
        occurrences = flex_count if allow_multiple else min(flex_count, expected_occurrence)
        return EditResult(
            content=flex_result,
            strategy="flexible",
            occurrences=occurrences,
            final_old_str=old_str,
            final_new_str=new_str,
        )
    if flex_count > 0 and not allow_multiple and flex_count != expected_occurrence:
        raise EditError(
            message=(
                f"Whitespace-flexible match found {flex_count} occurrence(s) but "
                f"expected {expected_occurrence}"
            ),
            attempted=attempted,
            suggestion=("Set allow_multiple=true or provide extra context to pin the match."),
        )

    # Strategy 3: fuzzy
    attempted.append("fuzzy")
    fuzzy_result, fuzzy_count = _strategy_fuzzy(content, old_str, new_str)
    if fuzzy_result is not None:
        return EditResult(
            content=fuzzy_result,
            strategy="fuzzy",
            occurrences=1,
            final_old_str=old_str,
            final_new_str=new_str,
        )
    if fuzzy_count > 1:
        raise EditError(
            message=(
                f"Fuzzy match was ambiguous ({fuzzy_count} equally-scored "
                f"windows) in {file_path or 'file'}"
            ),
            attempted=attempted,
            suggestion=(
                "Include more surrounding context in old_str so one window "
                "scores strictly better than the others."
            ),
        )

    raise EditError(
        message=f"Could not locate old_str in {file_path or 'file'}",
        attempted=attempted,
        suggestion=(
            "Verify the exact text exists, or include more surrounding context. "
            "If the file has changed, re-read it before editing."
        ),
    )


# =============================================================================
# LLM repair
# =============================================================================


RepairAsyncFn = Callable[
    [str, str, str, str], "Any"  # Coroutine returning RepairSuggestion | None
]


async def llm_repair(
    file_path: str,
    content: str,
    old_str: str,
    new_str: str,
) -> RepairSuggestion | None:
    """
    Default LLM repair callback.

    Calls :func:`create_model_adapter` with the cheap repair model from
    settings (``compaction_summary_model`` or the ``openai/gpt-4o-mini``
    fallback), asks it to return corrected ``old_str`` / ``new_str``
    values as strict JSON, and parses the response.

    Returns:
        :class:`RepairSuggestion` when the model produced a valid
        structured reply, or ``None`` if anything went wrong.
    """
    try:
        from ....config import get_settings
        from ...models import create_model_adapter
    except ImportError as exc:  # pragma: no cover - defensive
        logger.warning("[FUZZY-EDIT] llm_repair imports failed: %s", exc)
        return None

    settings = get_settings()
    model_name = getattr(settings, "compaction_summary_model", "") or "openai/gpt-4o-mini"

    # Truncate very long files so we stay under the repair model's budget.
    excerpt = content
    lines = content.splitlines()
    if len(lines) > 2000:
        excerpt = "\n".join(lines[-2000:])
        excerpt = "[...earlier lines omitted...]\n" + excerpt

    prompt = (
        "You are repairing a failed search/replace edit. The search text "
        "did not match the file exactly. Return corrected old_str / new_str "
        "values that will match uniquely when re-applied. Do not invent "
        "code that isn't in the file.\n\n"
        f"File: {file_path}\n\n"
        f"Attempted old_str:\n<<<OLD>>>\n{old_str}\n<<<END_OLD>>>\n\n"
        f"Attempted new_str:\n<<<NEW>>>\n{new_str}\n<<<END_NEW>>>\n\n"
        f"File content:\n<<<FILE>>>\n{excerpt}\n<<<END_FILE>>>\n\n"
        'Respond with ONLY a JSON object: {"old_str": "...", "new_str": "..."} '
        "and nothing else."
    )

    try:
        adapter = await create_model_adapter(model_name, user_id=None, db=None)
    except Exception as exc:
        logger.warning("[FUZZY-EDIT] create_model_adapter failed: %s", exc)
        return None

    text_chunks: list[str] = []
    try:
        async for chunk in adapter.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You correct failing search/replace edits. You always "
                        "reply with a single JSON object of the form "
                        '{"old_str": "...", "new_str": "..."} — no prose, '
                        "no markdown fences."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        ):
            if isinstance(chunk, str):
                text_chunks.append(chunk)
    except Exception as exc:
        logger.warning("[FUZZY-EDIT] repair model stream failed: %s", exc)
        return None

    raw = "".join(text_chunks).strip()
    if not raw:
        return None

    # Strip common markdown fencing.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Be lenient: pick the first {...} span.
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        return None
    candidate = raw[first_brace : last_brace + 1]

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    fixed_old = data.get("old_str")
    fixed_new = data.get("new_str")
    if not isinstance(fixed_old, str) or not isinstance(fixed_new, str):
        return None

    return RepairSuggestion(old_str=fixed_old, new_str=fixed_new)


__all__ = [
    "EditError",
    "EditResult",
    "RepairSuggestion",
    "apply_edit",
    "contains_omission_placeholder",
    "llm_repair",
    "FUZZY_MATCH_THRESHOLD",
    "FUZZY_MIN_NEEDLE_LEN",
]
