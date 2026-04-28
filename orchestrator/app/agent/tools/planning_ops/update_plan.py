"""
Structured Plan Tool

Provides the ``update_plan`` tool, which lets an agent record a structured,
ordered plan for the current run. Plans are kept in a per-process in-memory
store keyed by ``run_id`` AND mirrored to disk as human-readable markdown at
``<project_root>/.tesslate/plans/{timestamp}-{slug}.md``. An ``_active``
pointer file at ``<project_root>/.tesslate/plans/_active`` records the
filename of the currently active plan so the compactor and any external
tooling can resolve "the current plan" without scanning the directory.

The agent names each plan. The first ``update_plan`` call for a run must use
``action: "create"`` and supply both ``name`` (slug) and ``task`` (one-line
goal). Subsequent calls use ``action: "update"`` to modify step statuses and
``action: "complete"`` to mark the plan done — completion leaves the
markdown on disk (plan history) but clears the ``_active`` pointer.

All disk writes go through the unified orchestrator ``write_file`` so Docker,
Kubernetes, and Local backends behave identically.
"""

from __future__ import annotations

import asyncio
import logging
import re
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

VALID_ACTIONS: tuple[str, ...] = ("create", "update", "complete")

#: Directory (relative to project root) where plan markdown files live.
PLANS_DIR: str = ".tesslate/plans"

#: Pointer file (relative to project root) that names the currently active
#: plan file. Contents are a single line: the basename of the active plan
#: markdown file, e.g. ``2026-04-20_143022-add-oauth-login.md``.
#: Kept for backwards-compat with legacy tooling — written by every plan
#: mutation as a best-effort "latest overall" hint. Two concurrent agents on
#: the same project will race here; the per-run pointer below is the truth.
ACTIVE_POINTER_PATH: str = f"{PLANS_DIR}/_active"

#: Directory of per-run pointer files. Each agent run writes its own pointer
#: under ``<project>/.tesslate/plans/_active_runs/{run_id}.txt`` so parallel
#: agents on the same project can't clobber each other's "active plan" state.
#: External tooling can list this directory to see all active plans.
ACTIVE_POINTERS_DIR: str = f"{PLANS_DIR}/_active_runs"

#: Maximum characters in a sanitised slug.
MAX_SLUG_LENGTH: int = 40

#: Fallback run_id used when neither ``run_id`` nor ``task_id`` is present
#: in the tool execution context.
DEFAULT_RUN_ID: str = "default"


def _per_run_pointer_path(run_id: str) -> str:
    """Return the per-run active-plan pointer path for ``run_id``."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", run_id or DEFAULT_RUN_ID)[:64]
    return f"{ACTIVE_POINTERS_DIR}/{safe}.txt"


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

    name: str = ""
    task: str = ""
    filename: str = ""  # e.g. "2026-04-20_143022-add-oauth-login.md"
    plan: list[PlanStep] = field(default_factory=list)
    reasoning: str = ""
    status: str = "active"  # "active" | "completed"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "task": self.task,
            "filename": self.filename,
            "plan": [step.to_dict() for step in self.plan],
            "reasoning": self.reasoning,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Slug + filename helpers
# ---------------------------------------------------------------------------


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _sanitise_slug(raw: str | None) -> str:
    """Reduce an agent-supplied name to a filesystem-safe slug.

    Lowercases, replaces runs of non-alphanumerics with hyphens, trims leading
    and trailing hyphens, caps at :data:`MAX_SLUG_LENGTH`. Returns ``""`` if
    nothing meaningful survives — callers fall back to a generated slug.
    """
    if not raw or not isinstance(raw, str):
        return ""
    lowered = raw.strip().lower()
    cleaned = _SLUG_STRIP.sub("-", lowered).strip("-")
    if not cleaned:
        return ""
    return cleaned[:MAX_SLUG_LENGTH].rstrip("-") or ""


def _fallback_slug(task: str | None, run_id: str) -> str:
    """Generate a slug when the agent omits a good ``name``.

    Preference: derive from the task's first meaningful words; if the task is
    empty or non-alphanumeric, fall back to ``plan-{run_id_tail}``.
    """
    derived = _sanitise_slug((task or "").split("\n", 1)[0])
    if derived:
        # Keep only the first 6 hyphen-joined segments to avoid very long names.
        return "-".join(derived.split("-")[:6])
    tail = run_id.replace("-", "")[-8:] or "x"
    return f"plan-{tail}"


def _timestamp_prefix(now: datetime) -> str:
    return now.strftime("%Y-%m-%d_%H%M%S")


def _build_plan_filename(slug: str, now: datetime) -> str:
    return f"{_timestamp_prefix(now)}-{slug}.md"


def _build_plan_path(filename: str) -> str:
    return f"{PLANS_DIR}/{filename}"


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


_STATUS_SYMBOLS = {
    "pending": " ",
    "in_progress": "~",
    "completed": "x",
    "blocked": "!",
}


def _render_plan_markdown(state: PlanState) -> str:
    """Serialise a :class:`PlanState` as a human-readable markdown document.

    The format is intentionally close to GitHub task lists so the file
    renders cleanly in any markdown viewer. Status markers mirror Forgecode's
    ``[ ] / [~] / [x] / [!]`` convention.
    """
    header_title = state.name.replace("-", " ").title() if state.name else "Plan"
    lines: list[str] = [f"# Plan: {header_title}", ""]
    if state.task:
        lines.append("## Task")
        lines.append(state.task.strip())
        lines.append("")

    lines.append("## Meta")
    lines.append(f"- **Name:** `{state.name}`")
    lines.append(f"- **Status:** {state.status}")
    lines.append(f"- **Created:** {state.created_at.isoformat()}")
    lines.append(f"- **Updated:** {state.updated_at.isoformat()}")
    lines.append("")

    lines.append("## Steps")
    if state.plan:
        for step in state.plan:
            marker = _STATUS_SYMBOLS.get(step.status, " ")
            line = f"{step.index + 1}. [{marker}] {step.step}"
            if step.notes:
                line += f"  \n    _{step.notes}_"
            lines.append(line)
    else:
        lines.append("_(no steps)_")
    lines.append("")

    if state.reasoning:
        lines.append("## Reasoning")
        lines.append(state.reasoning.strip())
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plan store
# ---------------------------------------------------------------------------


class PlanStore:
    """Per-process in-memory plan registry.

    Keyed by ``run_id``. Thread-safe via an ``asyncio.Lock``. Every ``set``
    optionally mirrors the current plan to
    ``<project_root>/.tesslate/plans/{filename}`` through the unified
    orchestrator and updates the ``_active`` pointer file.
    """

    def __init__(self) -> None:
        self._states: dict[str, PlanState] = {}
        self._lock = asyncio.Lock()

    async def get(self, run_id: str) -> PlanState | None:
        async with self._lock:
            return self._states.get(run_id)

    async def set(
        self,
        run_id: str,
        state: PlanState,
        *,
        mirror_context: dict[str, Any] | None = None,
        update_active_pointer: bool = True,
    ) -> tuple[PlanState, str | None]:
        """Store ``state`` under ``run_id`` and mirror it to disk.

        Returns ``(state, mirror_path_or_None)``. ``update_active_pointer``
        controls whether the ``_active`` file is rewritten — ``complete``
        clears the pointer instead of pointing at the new state.
        """
        async with self._lock:
            self._states[run_id] = state

        mirror_path = await self._mirror_to_disk(
            run_id, state, mirror_context, update_active_pointer=update_active_pointer
        )
        return state, mirror_path

    async def clear(self, run_id: str) -> None:
        async with self._lock:
            self._states.pop(run_id, None)

    async def _mirror_to_disk(
        self,
        run_id: str,
        state: PlanState,
        context: dict[str, Any] | None,
        *,
        update_active_pointer: bool,
    ) -> str | None:
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

        plan_path = _build_plan_path(state.filename)
        markdown = _render_plan_markdown(state)

        try:
            from ....services.orchestration import get_orchestrator

            orchestrator = get_orchestrator()
            success = await orchestrator.write_file(
                user_id=user_id,
                project_id=str(project_id),
                container_name=context.get("container_name"),
                file_path=plan_path,
                content=markdown,
                project_slug=context.get("project_slug"),
                subdir=context.get("container_directory"),
                volume_id=context.get("volume_id"),
                cache_node=context.get("cache_node"),
            )
        except Exception as exc:
            logger.warning(
                "[PLAN-STORE] Mirror write failed for run_id=%s path=%s: %s",
                run_id,
                plan_path,
                exc,
            )
            return None

        if not success:
            logger.warning(
                "[PLAN-STORE] Mirror write reported failure for run_id=%s path=%s",
                run_id,
                plan_path,
            )
            return None

        # Update pointers. Parallel agents on the same project MUST NOT fight
        # over a shared pointer — write the per-run pointer as the source of
        # truth, and the legacy project-wide pointer as a best-effort hint.
        pointer_body = state.filename if update_active_pointer else ""
        per_run_pointer = _per_run_pointer_path(run_id)
        try:
            await orchestrator.write_file(
                user_id=user_id,
                project_id=str(project_id),
                container_name=context.get("container_name"),
                file_path=per_run_pointer,
                content=pointer_body,
                project_slug=context.get("project_slug"),
                subdir=context.get("container_directory"),
                volume_id=context.get("volume_id"),
                cache_node=context.get("cache_node"),
            )
        except Exception as exc:
            logger.warning(
                "[PLAN-STORE] Per-run pointer write failed for run_id=%s: %s",
                run_id,
                exc,
            )

        try:
            await orchestrator.write_file(
                user_id=user_id,
                project_id=str(project_id),
                container_name=context.get("container_name"),
                file_path=ACTIVE_POINTER_PATH,
                content=pointer_body,
                project_slug=context.get("project_slug"),
                subdir=context.get("container_directory"),
                volume_id=context.get("volume_id"),
                cache_node=context.get("cache_node"),
            )
        except Exception as exc:
            logger.warning(
                "[PLAN-STORE] Active pointer write failed for run_id=%s: %s",
                run_id,
                exc,
            )

        return plan_path


#: Module-level singleton shared by all callers.
PLAN_STORE = PlanStore()


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def _resolve_run_id(context: dict[str, Any]) -> str:
    """Pick the run identifier from the tool execution context.

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
    """Fan out a ``plan_update`` event to the context's sink, if any.

    Supported sink shapes:

    1. Async callable — ``await event_sink(event)``.
    2. Object with ``put_nowait`` (e.g. ``asyncio.Queue``).
    3. Object with ``put`` returning an awaitable.
    4. Sync callable — ``event_sink(event)``.
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


def _validate_plan_steps(
    raw_plan: Any,
) -> tuple[list[PlanStep] | None, dict[str, Any] | None]:
    """Validate and normalise a ``plan`` array argument."""
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
            suggestion='Example: {"plan": [{"step": "Read config", "status": "pending"}]}',
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


def _coerce_string_param(
    name: str, value: Any, *, required: bool
) -> tuple[str | None, dict[str, Any] | None]:
    """Return ``(clean_string, error)``. ``clean_string`` is ``None`` iff an
    error dict is returned."""
    if value is None:
        if required:
            return None, error_output(
                message=f"Missing '{name}' parameter",
                suggestion=f"Provide a non-empty string for '{name}'",
            )
        return "", None
    if not isinstance(value, str):
        return None, error_output(
            message=(
                f"Invalid '{name}' parameter type: expected string, got {type(value).__name__}"
            ),
            suggestion=f"'{name}' must be a string",
        )
    stripped = value.strip()
    if required and not stripped:
        return None, error_output(
            message=f"Empty '{name}' parameter",
            suggestion=f"Provide a non-empty value for '{name}'",
        )
    return stripped, None


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------


async def update_plan_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Create, update, or complete the named plan for the current run.

    Required ``params``:
        ``action``: ``"create"`` | ``"update"`` | ``"complete"``.

    Additional params per action:
        ``create``: ``name`` (agent-chosen slug, required), ``task`` (one-line
            goal, required), ``plan`` (step list, required),
            ``reasoning`` (optional).
        ``update``: ``plan`` (step list, required), ``reasoning`` (optional).
            Operates on the active plan for this run.
        ``complete``: ``reasoning`` (optional). Marks the active plan done
            and clears the ``_active`` pointer. The markdown file stays on
            disk as plan history.
    """
    action_raw = params.get("action")
    if action_raw not in VALID_ACTIONS:
        return error_output(
            message=(
                f"Invalid or missing 'action': expected one of "
                f"{', '.join(VALID_ACTIONS)}, got {action_raw!r}"
            ),
            suggestion="Use 'create' for the first call, then 'update' or 'complete'",
        )
    action = action_raw

    run_id = _resolve_run_id(context)
    existing = await PLAN_STORE.get(run_id)

    reasoning, err = _coerce_string_param("reasoning", params.get("reasoning"), required=False)
    if err is not None:
        return err

    now = datetime.now(UTC)

    if action == "create":
        name_raw, err = _coerce_string_param("name", params.get("name"), required=True)
        if err is not None:
            return err
        task_text, err = _coerce_string_param("task", params.get("task"), required=True)
        if err is not None:
            return err
        steps, err = _validate_plan_steps(params.get("plan"))
        if err is not None:
            return err
        assert steps is not None

        slug = _sanitise_slug(name_raw) or _fallback_slug(task_text, run_id)
        filename = _build_plan_filename(slug, now)
        state = PlanState(
            name=slug,
            task=task_text,
            filename=filename,
            plan=steps,
            reasoning=reasoning,
            status="active",
            created_at=now,
            updated_at=now,
        )

    elif action == "update":
        if existing is None or existing.status != "active":
            return error_output(
                message=(
                    "No active plan for this run — cannot 'update'. Use "
                    "'action': 'create' to start a new plan."
                ),
                suggestion="Call update_plan with action='create' and a name/task first",
            )
        steps, err = _validate_plan_steps(params.get("plan"))
        if err is not None:
            return err
        assert steps is not None

        # Preserve identity (name, task, filename, created_at) across updates.
        state = PlanState(
            name=existing.name,
            task=existing.task,
            filename=existing.filename,
            plan=steps,
            reasoning=reasoning or existing.reasoning,
            status="active",
            created_at=existing.created_at,
            updated_at=now,
        )

    else:  # action == "complete"
        if existing is None:
            return error_output(
                message="No plan to complete for this run.",
                suggestion="Create a plan with action='create' before calling complete",
            )
        state = PlanState(
            name=existing.name,
            task=existing.task,
            filename=existing.filename,
            plan=existing.plan,
            reasoning=reasoning or existing.reasoning,
            status="completed",
            created_at=existing.created_at,
            updated_at=now,
        )

    state, mirror_path = await PLAN_STORE.set(
        run_id,
        state,
        mirror_context=context,
        update_active_pointer=(action != "complete"),
    )

    event_payload = {
        "action": action,
        "run_id": run_id,
        "name": state.name,
        "task": state.task,
        "filename": state.filename,
        "status": state.status,
        "plan": [step.to_dict() for step in state.plan],
        "reasoning": state.reasoning,
        "updated_at": state.updated_at.isoformat(),
    }
    await _emit_event(context, {"type": "plan_update", "data": event_payload})

    counts = {
        status: sum(1 for step in state.plan if step.status == status) for status in VALID_STATUSES
    }

    logger.info(
        "[PLAN-TOOL] %s plan run_id=%s name=%s steps=%d mirror=%s",
        action,
        run_id,
        state.name,
        len(state.plan),
        mirror_path,
    )

    verb = {"create": "created", "update": "updated", "complete": "completed"}[action]
    return success_output(
        message=(f"Plan '{state.name}' {verb}: {len(state.plan)} step(s) for run '{run_id}'"),
        action=action,
        run_id=run_id,
        name=state.name,
        task=state.task,
        filename=state.filename,
        plan=[step.to_dict() for step in state.plan],
        reasoning=state.reasoning,
        mirror_path=mirror_path,
        status=state.status,
        created_at=state.created_at.isoformat(),
        updated_at=state.updated_at.isoformat(),
        details={
            "step_count": len(state.plan),
            "status_counts": counts,
            "mirror_written": mirror_path is not None,
            "active": state.status == "active",
        },
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_update_plan_tool(registry) -> None:
    """Register the ``update_plan`` structured plan tool on ``registry``."""
    registry.register(
        Tool(
            name="update_plan",
            description=(
                "Create, update, or complete the named plan for the current "
                "run. Plans are persisted as markdown at "
                "`.tesslate/plans/<timestamp>-<slug>.md` with an `_active` "
                "pointer recording the current plan. First call must use "
                "`action: 'create'` with a `name` (short kebab-case slug you "
                "choose, e.g. `add-oauth-login`) and a `task` (one-line goal). "
                "Subsequent calls use `action: 'update'` to change step "
                "statuses or `action: 'complete'` to mark the plan done "
                "(the file stays on disk as plan history). At most one step "
                "should be in_progress at a time."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(VALID_ACTIONS),
                        "description": (
                            "'create' starts a new plan (requires name + task + plan), "
                            "'update' replaces the steps on the active plan, "
                            "'complete' marks the active plan done."
                        ),
                    },
                    "name": {
                        "type": "string",
                        "description": (
                            "Short kebab-case slug identifying the plan "
                            "(e.g. 'add-oauth-login'). Required when "
                            "action='create'. Server sanitises and caps length."
                        ),
                    },
                    "task": {
                        "type": "string",
                        "description": (
                            "One-line description of the overall goal. "
                            "Required when action='create'."
                        ),
                    },
                    "plan": {
                        "type": "array",
                        "description": (
                            "Ordered list of plan steps. Required for "
                            "action='create' and action='update'. Replaces "
                            "any existing steps."
                        ),
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
                        "description": "Optional explanation of why the plan changed.",
                    },
                },
                "required": ["action"],
            },
            executor=update_plan_tool,
            category=ToolCategory.PLANNING,
            # Action + plan in, success dict out — JSON-clean.
            state_serializable=True,
            # Plan persisted as markdown on disk + DB pointer; no in-tool state.
            holds_external_state=False,
            examples=[
                (
                    '{"tool_name": "update_plan", "parameters": {"action": "create", '
                    '"name": "add-oauth-login", "task": "Add Google OAuth login flow", '
                    '"plan": ['
                    '{"step": "Inspect auth middleware", "status": "in_progress"},'
                    '{"step": "Wire OAuth redirect handler", "status": "pending"},'
                    '{"step": "Add integration test", "status": "pending"}'
                    '], "reasoning": "Breaking the feature into verifiable steps"}}'
                ),
                (
                    '{"tool_name": "update_plan", "parameters": {"action": "update", '
                    '"plan": ['
                    '{"step": "Inspect auth middleware", "status": "completed"},'
                    '{"step": "Wire OAuth redirect handler", "status": "in_progress"},'
                    '{"step": "Add integration test", "status": "pending"}'
                    "]}}"
                ),
                ('{"tool_name": "update_plan", "parameters": {"action": "complete"}}'),
            ],
        )
    )

    logger.info("Registered structured update_plan tool (named markdown plans)")
