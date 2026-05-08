"""``branch`` step handler (Phase F, issue #475).

Evaluates a small expression against the run context and decides
which subsequent step to execute next. The engine reads
``StepResult.next_ordinal`` (when set) to skip ahead.

Action config shape::

    {
        "condition": {            # required: simple equality or "exists" check
            "kind": "equals",
            "left": "{step.body}",   # template against prior_step_outputs
            "right": "OK"
        },
        "then_ordinal": 2,        # ordinal to jump to when true
        "else_ordinal": 5         # ordinal to jump to when false
    }

The condition vocabulary is intentionally small in this slice. A
follow-up adds JSONLogic for richer predicates (and / or / not /
contains / numeric comparison). Today's slice covers the most common
"if last step said OK, do X, else do Y" pattern and ships the
engine wiring so the richer predicate set is purely additive.
"""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar

from .base import StepContext, StepHandler, StepResult, register_handler

logger = logging.getLogger(__name__)


@register_handler
class BranchHandler(StepHandler):
    kind: ClassVar[str] = "branch"

    async def execute(self, ctx: StepContext) -> StepResult:
        cfg = ctx.action.config or {}
        condition = cfg.get("condition") or {}
        result = _evaluate(condition, ctx)

        next_ordinal: int | None = None
        if result is True:
            next_ordinal = cfg.get("then_ordinal")
        elif result is False:
            next_ordinal = cfg.get("else_ordinal")

        # Coerce to int when present; ignore invalid values rather than
        # blowing up the run (engine treats "no jump" as "advance by 1").
        try:
            next_ordinal = int(next_ordinal) if next_ordinal is not None else None
        except (TypeError, ValueError):
            next_ordinal = None

        return StepResult(
            output={
                "action_type": "branch",
                "condition_result": bool(result),
                "next_ordinal": next_ordinal,
            },
            async_handoff=False,
            next_ordinal=next_ordinal,
        )


def _evaluate(condition: dict[str, Any], ctx: StepContext) -> bool:
    """Evaluate a small predicate. Returns False on unknown kind so the
    engine takes the else_ordinal path."""
    kind = condition.get("kind")
    left = _render(condition.get("left"), ctx)

    if kind == "equals":
        right = _render(condition.get("right"), ctx)
        return str(left) == str(right)

    if kind == "exists":
        return left is not None and left != ""

    if kind == "regex":
        pattern = condition.get("right") or condition.get("pattern") or ""
        if not isinstance(left, str) or not pattern:
            return False
        try:
            return re.search(pattern, left, flags=re.IGNORECASE) is not None
        except re.error:
            logger.warning("branch.bad_regex pattern=%r", pattern)
            return False

    logger.warning("branch.unknown_condition_kind kind=%r", kind)
    return False


def _render(value: Any, ctx: StepContext) -> Any:
    """Resolve ``{step.key}`` placeholders against ``prior_step_outputs[-1]``
    and ``{run_id}`` / ``{automation_name}`` against the run context.

    Non-string values pass through unchanged (so a numeric literal in
    the condition stays numeric).
    """
    if not isinstance(value, str):
        return value
    if "{" not in value:
        return value

    flat: dict[str, Any] = {}
    if isinstance(ctx.event_payload, dict):
        flat.update(ctx.event_payload)
    if ctx.prior_step_outputs:
        last = ctx.prior_step_outputs[-1]
        if isinstance(last, dict):
            flat.update({f"step.{k}": v for k, v in last.items()})
            flat["last_output"] = last
    flat["automation_name"] = ctx.automation.name
    flat["run_id"] = str(ctx.run.id)
    try:
        return value.format_map(_DefaultDict(flat))
    except (ValueError, IndexError, KeyError):
        return value


class _DefaultDict(dict):
    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return "{" + key + "}"
