"""
Structured Plan Tool

Provides the ``update_plan`` tool, which lets an agent record a structured,
ordered plan for the current run. The plan is kept in a per-process in-memory
store keyed by ``run_id`` and mirrored to ``<project_root>/.tesslate/plan.json``
so that other processes, UIs, and replays can read it.

This complements ``todo_read`` / ``todo_write`` (which are loose, replaceable
session todos) and ``save_plan`` / legacy ``update_plan`` (which persist
through PlanManager). The tool defined here is optimized for a fixed
``run_id`` scope and real-time event fan-out to any connected event sink —
for example, the streaming agent's SSE pipeline.

Design:
    - ``PlanStore``: thread-safe per-process store ``{run_id: PlanState}``
      with ``get`` / ``set`` / ``clear``, mirroring every set through the
      orchestrator's ``write_file`` so the path is handled uniformly across
      Docker, Kubernetes, and Local backends.
    - ``update_plan`` tool: validates the plan shape, persists it via
      ``PlanStore.set``, writes the JSON mirror, and emits a ``plan_update``
      event to ``context['event_sink']`` when present (async callable or
      queue-like object).

Run ID resolution order:
    1. ``context['run_id']`` if set
    2. ``context['task_id']`` if set
    3. Fallback string ``"default"``
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STATUSES: tuple[str, ...] = (
    "pending",
    "in_progress",
    "completed",
    "blocked",
)

#: Path (relative to project root) where the plan mirror is written.
PLAN_MIRROR_PATH: str = ".tesslate/plan.json"

#: Fallback run_id used when neither ``run_id`` nor ``task_id`` is present
#: in the tool execution context.
DEFAULT_RUN_ID: str = "default"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PlanStep:
    """A single step within a structured plan."""

    index: int
    step: str
    status: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "step": self.step,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class PlanState:
    """Snapshot of a plan for one run."""

    plan: list[PlanStep] = field(default_factory=list)
    reasoning: str = ""
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": [step.to_dict() for step in self.plan],
            "reasoning": self.reasoning,
            "updated_at": self.updated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Plan store
# ---------------------------------------------------------------------------


class PlanStore:
    """
    Per-process in-memory plan registry.

    Keyed by ``run_id``. Thread-safe via an ``asyncio.Lock``. Every ``set``
    optionally mirrors the current plan to ``<project_root>/.tesslate/plan.json``
    through the unified orchestrator, so storage backend differences (local
    filesystem, Docker shared volume, Kubernetes pod API) are handled for us.
    """

    def __init__(self) -> None:
        self._states: dict[str, PlanState] = {}
        self._lock = asyncio.Lock()

    async def get(self, run_id: str) -> PlanState | None:
        """Return the plan state for ``run_id`` or ``None`` if none set."""
        async with self._lock:
            return self._states.get(run_id)

    async def set(
        self,
        run_id: str,
        plan: list[PlanStep],
        reasoning: str,
        *,
        mirror_context: dict[str, Any] | None = None,
    ) -> tuple[PlanState, str | None]:
        """
        Store ``plan`` under ``run_id`` and mirror it to disk.

        Args:
            run_id: Caller-supplied run identifier.
            plan: Fully indexed list of :class:`PlanStep` entries — this
                call replaces any previously stored plan for ``run_id``.
            reasoning: Optional explanation attached to the update.
            mirror_context: Execution context dict forwarded to the
                orchestrator's ``write_file`` so the mirror lands in the
                right project root. When ``None`` (or missing required
                fields) the mirror step is skipped and the returned path
                is ``None``.

        Returns:
            Tuple of ``(state, mirror_path_or_None)``.
        """
        state = PlanState(
            plan=list(plan),
            reasoning=reasoning,
            updated_at=datetime.now(UTC),
        )

        async with self._lock:
            self._states[run_id] = state

        mirror_path = await self._mirror_to_disk(run_id, state, mirror_context)
        return state, mirror_path

    async def clear(self, run_id: str) -> None:
        """Drop any stored state for ``run_id``."""
        async with self._lock:
            self._states.pop(run_id, None)

    # ------------------------------------------------------------------
    # Mirror helpers
    # ------------------------------------------------------------------

    async def _mirror_to_disk(
        self,
        run_id: str,
        state: PlanState,
        context: dict[str, Any] | None,
    ) -> str | None:
        """
        Write the plan JSON to ``<project_root>/.tesslate/plan.json``.

        Uses the unified orchestrator ``write_file`` so it works across
        Docker, Kubernetes, and Local backends without special-casing.
        Returns the mirror path on success, or ``None`` if the mirror was
        skipped (no context, missing required fields, or a write error).
        """
        if context is None:
            return None

        user_id = context.get("user_id")
        project_id = context.get("project_id")
        if user_id is None or project_id is None:
            logger.debug(
                "[PLAN-STORE] Skipping mirror for run_id=%s: missing user_id/project_id",
                run_id,
            )
            return None

        payload = {
            "run_id": run_id,
            **state.to_dict(),
        }
        content = json.dumps(payload, indent=2, sort_keys=False)

        try:
            from ....services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()
            success = await orchestrator.write_file(
                user_id=user_id,
                project_id=str(project_id),
                container_name=context.get("container_name"),
                file_path=PLAN_MIRROR_PATH,
                content=content,
                project_slug=context.get("project_slug"),
                subdir=context.get("container_directory"),
                volume_id=context.get("volume_id"),
                cache_node=context.get("cache_node"),
            )
        except Exception as exc:
            logger.warning("[PLAN-STORE] Mirror write failed for run_id=%s: %s", run_id, exc)
            return None

        if not success:
            logger.warning("[PLAN-STORE] Mirror write reported failure for run_id=%s", run_id)
            return None

        return PLAN_MIRROR_PATH


#: Module-level singleton shared by all callers.
PLAN_STORE = PlanStore()


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def _resolve_run_id(context: dict[str, Any]) -> str:
    """
    Pick the run identifier from the tool execution context.

    Preference order: explicit ``run_id`` → ``task_id`` → default fallback.
    """
    run_id = context.get("run_id")
    if isinstance(run_id, str) and run_id:
        return run_id
    if run_id is not None:
        return str(run_id)

    task_id = context.get("task_id")
    if isinstance(task_id, str) and task_id:
        return task_id
    if task_id is not None:
        return str(task_id)

    return DEFAULT_RUN_ID


async def _emit_event(context: dict[str, Any], event: dict[str, Any]) -> None:
    """
    Fan out a ``plan_update`` event to the context's sink, if any.

    Supported sink shapes (in order):

    1. Async callable — ``await event_sink(event)``.
    2. Sync callable — ``event_sink(event)``.
    3. Object with ``put_nowait`` (e.g. ``asyncio.Queue``) —
       ``event_sink.put_nowait(event)``.
    4. Object with ``put`` returning an awaitable — ``await event_sink.put(event)``.

    Any exception during delivery is logged and swallowed so a faulty sink
    never breaks the plan update itself.
    """
    sink = context.get("event_sink")
    if sink is None:
        return

    try:
        if asyncio.iscoroutinefunction(sink):
            await sink(event)
            return

        put_nowait = getattr(sink, "put_nowait", None)
        if callable(put_nowait):
            put_nowait(event)
            return

        put = getattr(sink, "put", None)
        if callable(put):
            result = put(event)
            if asyncio.iscoroutine(result):
                await result
            return

        if callable(sink):
            result = sink(event)
            if asyncio.iscoroutine(result):
                await result
            return
    except Exception as exc:
        logger.warning("[PLAN-TOOL] event_sink delivery failed: %s", exc)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_plan_input(raw_plan: Any) -> tuple[list[PlanStep] | None, dict[str, Any] | None]:
    """
    Validate and normalize the ``plan`` argument.

    Returns:
        ``(steps, None)`` on success, or ``(None, error_dict)`` on failure.
        ``error_dict`` is a prepared :func:`error_output` ready to return.
    """
    if raw_plan is None:
        return None, error_output(
            message="Missing 'plan' parameter",
            suggestion='Provide a non-empty "plan" array of step objects',
        )

    if not isinstance(raw_plan, list):
        return None, error_output(
            message=(
                f"Invalid 'plan' parameter type: expected array, got {type(raw_plan).__name__}"
            ),
            suggestion=('Example: {"plan": [{"step": "Read config", "status": "pending"}]}'),
        )

    if len(raw_plan) == 0:
        return None, error_output(
            message="Empty 'plan' array",
            suggestion="Provide at least one step with 'step' and 'status' fields",
        )

    steps: list[PlanStep] = []
    for index, entry in enumerate(raw_plan):
        if not isinstance(entry, dict):
            return None, error_output(
                message=(f"Step at index {index} must be an object, got {type(entry).__name__}"),
                suggestion='Example: {"step": "Task description", "status": "pending"}',
            )

        step_text = entry.get("step")
        if not isinstance(step_text, str) or not step_text.strip():
            return None, error_output(
                message=f"Step at index {index} is missing a non-empty 'step' field",
                suggestion="Each step must have a 'step' string describing the work",
            )

        status = entry.get("status")
        if status not in VALID_STATUSES:
            return None, error_output(
                message=(
                    f"Step at index {index} has invalid status "
                    f"{status!r}; must be one of: {', '.join(VALID_STATUSES)}"
                ),
                suggestion=(
                    "Use 'pending' for not-started, 'in_progress' for the active "
                    "step, 'completed' when done, or 'blocked' when stuck"
                ),
            )

        notes_value = entry.get("notes", "")
        if notes_value is None:
            notes = ""
        elif isinstance(notes_value, str):
            notes = notes_value
        else:
            return None, error_output(
                message=(
                    f"Step at index {index} has non-string 'notes' field "
                    f"(got {type(notes_value).__name__})"
                ),
                suggestion="'notes' must be a string if provided",
            )

        steps.append(
            PlanStep(
                index=index,
                step=step_text.strip(),
                status=status,
                notes=notes,
            )
        )

    return steps, None


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------


async def update_plan_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Record a structured plan for the current run.

    Args:
        params: ``{"plan": [...], "reasoning": "optional string"}``.
        context: Tool execution context. Honored keys:
            ``run_id`` / ``task_id``    — run identifier for the plan store.
            ``user_id`` / ``project_id``/ ``project_slug`` / ``container_directory``
            ``volume_id`` / ``cache_node`` — forwarded to the orchestrator
                so the ``.tesslate/plan.json`` mirror lands in the right place.
            ``event_sink``              — optional async callable / queue /
                callable that receives ``plan_update`` events.

    Returns:
        Standardized success/error output. Success payload includes
        ``run_id``, ``plan``, ``reasoning``, ``mirror_path``, ``updated_at``.
    """
    steps, error = _validate_plan_input(params.get("plan"))
    if error is not None:
        return error

    reasoning_raw = params.get("reasoning", "")
    if reasoning_raw is None:
        reasoning = ""
    elif isinstance(reasoning_raw, str):
        reasoning = reasoning_raw
    else:
        return error_output(
            message=(
                f"Invalid 'reasoning' parameter type: expected string, got "
                f"{type(reasoning_raw).__name__}"
            ),
            suggestion='Example: {"reasoning": "Expanding step 3 into sub-tasks"}',
        )

    assert steps is not None  # _validate_plan_input guarantees this on success
    run_id = _resolve_run_id(context)

    state, mirror_path = await PLAN_STORE.set(
        run_id,
        steps,
        reasoning,
        mirror_context=context,
    )

    event_payload = {
        "plan": [step.to_dict() for step in state.plan],
        "reasoning": state.reasoning,
        "run_id": run_id,
        "updated_at": state.updated_at.isoformat(),
    }
    await _emit_event(context, {"type": "plan_update", "data": event_payload})

    counts = {
        status: sum(1 for step in state.plan if step.status == status) for status in VALID_STATUSES
    }

    logger.info(
        "[PLAN-TOOL] Updated plan run_id=%s steps=%d reasoning=%r mirror=%s",
        run_id,
        len(state.plan),
        reasoning[:80] if reasoning else "",
        mirror_path,
    )

    return success_output(
        message=f"Plan updated: {len(state.plan)} step(s) recorded for run '{run_id}'",
        run_id=run_id,
        plan=[step.to_dict() for step in state.plan],
        reasoning=reasoning,
        mirror_path=mirror_path,
        updated_at=state.updated_at.isoformat(),
        details={
            "step_count": len(state.plan),
            "status_counts": counts,
            "mirror_written": mirror_path is not None,
        },
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_update_plan_tool(registry) -> None:
    """
    Register the ``update_plan`` structured plan tool on ``registry``.

    Note: this replaces the legacy ``update_plan`` executor if one was
    previously registered by :func:`register_plan_tools`. Callers that want
    both must pick one — they share the same tool name by design.
    """
    registry.register(
        Tool(
            name="update_plan",
            description=(
                "Record a structured execution plan for the current run. "
                "Replaces any previous plan for this run. Use this to "
                "expose your step-by-step approach to the UI and any "
                "connected event consumers; each step has a status of "
                "pending, in_progress, completed, or blocked and an "
                "optional free-form notes string. At most one step "
                "should be in_progress at a time."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "array",
                        "description": "Ordered list of plan steps (replaces any existing plan).",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {
                                    "type": "string",
                                    "description": "Short description of the step (5-12 words).",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": list(VALID_STATUSES),
                                    "description": "Current status of the step.",
                                },
                                "notes": {
                                    "type": "string",
                                    "description": "Optional free-form notes for this step.",
                                },
                            },
                            "required": ["step", "status"],
                        },
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Optional explanation of why the plan was updated.",
                    },
                },
                "required": ["plan"],
            },
            executor=update_plan_tool,
            category=ToolCategory.PLANNING,
            examples=[
                (
                    '{"tool_name": "update_plan", "parameters": {"plan": ['
                    '{"step": "Inspect failing test", "status": "in_progress"},'
                    '{"step": "Patch regression", "status": "pending"},'
                    '{"step": "Re-run suite", "status": "pending"}'
                    '], "reasoning": "Breaking the fix into verifiable steps"}}'
                )
            ],
        )
    )

    logger.info("Registered structured update_plan tool")
