"""
Delegation Operations: subagent orchestration tools.

Exposes five function tools for the parent agent:

- ``task``                    — spawn a specialist subagent with a scoped
                                 tool registry and run its generator in a
                                 background asyncio task. Supports both
                                 ``wait=True`` (blocking) and ``wait=False``
                                 (fire-and-forget) delivery modes.
- ``wait_agent``              — await completion of a previously spawned
                                 subagent, bounded by ``timeout_ms``.
- ``send_message_to_agent``   — enqueue a message that will be delivered to
                                 the running subagent at its next event
                                 boundary via the ``injected_messages`` key
                                 on its run-context dict.
- ``close_agent``              — cancel a running subagent and mark its
                                 record ``cancelled``.
- ``list_agents``              — return serializable snapshots of every
                                 tracked subagent, optionally filtered by
                                 parent_agent_id or status.

Message delivery limitation
---------------------------

Mid-run message injection relies on the child agent re-reading the
``injected_messages`` list from the run context between iterations.
The canonical :class:`TesslateAgent` does not currently poll this key
natively, so queued messages are surfaced via the registry snapshot and
inspectable by the parent via ``list_agents`` / ``wait_agent``. When the
child agent class gains native support for ``injected_messages``, the
runner loop here will deliver them transparently with no call-site
changes. Until then, the runner logs a warning the first time it
encounters undeliverable messages for a given subagent so operators
know the enqueue succeeded but the child did not consume them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Any

from ..output_formatter import error_output, success_output
from ..registry import (
    Tool,
    ToolCategory,
    ToolRegistry,
    create_scoped_tool_registry,
    get_tool_registry,
)
from .agent_registry import (
    MAX_SUBAGENT_DEPTH,
    STATUS_PENDING,
    STATUS_RUNNING,
    SUBAGENT_REGISTRY,
    TERMINAL_STATUSES,
    SubagentRecord,
)

logger = logging.getLogger(__name__)

# Default and maximum wall-clock limits for subagent execution.
DEFAULT_TIMEOUT_MS = 600_000
MAX_TIMEOUT_MS = 3_600_000

# Tools that must never be available inside a subagent by default, to
# prevent runaway recursion even under the depth cap.
RECURSION_GUARD_TOOLS: frozenset[str] = frozenset(
    {
        "task",
        "wait_agent",
        "send_message_to_agent",
        "close_agent",
        "list_agents",
    }
)

# Child subagents get sensible iteration and text generation budgets.
DEFAULT_MAX_ITERATIONS = 15

_DEFAULT_SYSTEM_PROMPT = (
    "You are a specialist subagent delegated a focused task by a parent "
    "coordinator agent. Complete the task diligently using the tools made "
    "available to you. When finished, produce a concise natural-language "
    "summary of what you did and any key findings so the parent can "
    "integrate your work."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp_timeout(value: Any) -> int:
    try:
        ms = int(value) if value is not None else DEFAULT_TIMEOUT_MS
    except (TypeError, ValueError):
        ms = DEFAULT_TIMEOUT_MS
    if ms <= 0:
        ms = DEFAULT_TIMEOUT_MS
    return min(ms, MAX_TIMEOUT_MS)


def _resolve_tool_registry(
    requested_names: list[str] | None,
) -> ToolRegistry:
    """Build a scoped registry for the child subagent.

    If ``requested_names`` is ``None``, the child inherits every tool the
    parent knows about *except* the delegation tools themselves. If the
    caller passed an explicit list, the delegation tools are stripped from
    it as a defence-in-depth measure.
    """
    global_registry = get_tool_registry()
    all_names = list(global_registry._tools.keys())

    if requested_names is None:
        child_names = [n for n in all_names if n not in RECURSION_GUARD_TOOLS]
    else:
        child_names = [n for n in requested_names if n not in RECURSION_GUARD_TOOLS]

    return create_scoped_tool_registry(child_names)


async def _resolve_model_adapter(
    parent_context: dict[str, Any],
    model_name: str | None,
) -> Any:
    """Return an adapter for the child subagent.

    Reuses the parent adapter when the child has no explicit model
    override; otherwise builds a fresh adapter via the factory.
    """
    parent_adapter = parent_context.get("model_adapter")
    if model_name is None and parent_adapter is not None:
        return parent_adapter

    from ...models import create_model_adapter

    effective_name = model_name or getattr(parent_adapter, "model_name", None)
    if not effective_name:
        raise ValueError(
            "cannot resolve a model for the subagent: no model_name provided "
            "and parent context has no model_adapter"
        )
    return await create_model_adapter(
        effective_name,
        user_id=parent_context.get("user_id"),
        db=parent_context.get("db"),
    )


def _build_child_context(
    parent_context: dict[str, Any],
    agent_id: str,
    child_adapter: Any,
) -> dict[str, Any]:
    """Derive the child agent's run-context from the parent's context."""
    child_context = dict(parent_context)
    child_context["agent_id"] = agent_id
    child_context["parent_agent_id"] = parent_context.get("agent_id")
    child_context["subagent_depth"] = int(parent_context.get("subagent_depth", 0)) + 1
    child_context["model_adapter"] = child_adapter
    # Clear chat history so the subagent starts with a clean conversation
    # independent of the parent's scrollback, but keep project-scoped data.
    child_context["chat_history"] = []
    # Fresh mutable container for mid-run message injection.
    child_context["injected_messages"] = []
    # Avoid propagating approval prompts: subagents run in the same trust
    # domain as the parent for the duration of this delegation.
    child_context["skip_approval_check"] = True
    return child_context


def _record_event_for_trajectory(recorder, event: dict[str, Any]) -> None:
    """Feed a child-agent event into the trajectory recorder."""
    etype = event.get("type", "")
    data = event.get("data") or {}

    if etype == "agent_step":
        tool_calls = [
            {
                "id": f"call_{data.get('iteration', 0)}_{i}",
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": json.dumps(tc.get("parameters") or {}),
                },
            }
            for i, tc in enumerate(data.get("tool_calls") or [])
        ]
        recorder.record_assistant(
            content=data.get("response_text") or "",
            tool_calls=tool_calls or None,
        )

    elif etype == "tool_call":
        # Per-tool event also carries the result — record the tool result.
        tc_id = f"call_{data.get('iteration', 0)}_{data.get('index', 0)}"
        result_payload = data.get("result")
        if isinstance(result_payload, dict):
            result_text = json.dumps(result_payload)
        else:
            result_text = str(result_payload or "")
        recorder.record_tool_result(tc_id, result_text)

    elif etype == "complete":
        final = (data or {}).get("final_response") or ""
        if final:
            recorder.record_assistant(content=final)


async def _deliver_pending_messages(agent_id: str, child_context: dict[str, Any]) -> None:
    """Drain the pending queue into the child's run context."""
    pending = await SUBAGENT_REGISTRY.drain_messages(agent_id)
    if not pending:
        return

    injected = child_context.setdefault("injected_messages", [])
    before = len(injected)
    injected.extend(pending)

    # Warn if the child agent never consumes the queue. We consider messages
    # "undelivered" when the list grows beyond a reasonable buffer without
    # the child resetting it.
    if len(injected) > before and len(injected) > 16:
        logger.warning(
            "[delegation] subagent %s has %d buffered injected_messages "
            "but the child agent may not be polling them; messages will "
            "remain visible via list_agents snapshot",
            agent_id,
            len(injected),
        )


# ---------------------------------------------------------------------------
# Runner: drives the child agent's generator
# ---------------------------------------------------------------------------


async def _run_subagent(
    *,
    agent_id: str,
    prompt: str,
    child_agent_cls: Any,
    system_prompt: str,
    scoped_registry: ToolRegistry,
    adapter: Any,
    max_iterations: int,
    child_context: dict[str, Any],
    timeout_s: float,
) -> None:
    """Background task entry point — drives one subagent to completion.

    The task owns the child-agent instance and trajectory recorder for
    the lifetime of the run. On exit (success, failure, cancel, timeout)
    it updates the registry record exactly once.
    """

    from ...trajectory import TrajectoryRecorder

    recorder = TrajectoryRecorder(
        session_id=agent_id,
        model_name=getattr(adapter, "model_name", "unknown"),
    )
    recorder.record_system(system_prompt)
    recorder.record_user(prompt)

    await SUBAGENT_REGISTRY.mark_running(agent_id)

    try:
        child_agent = child_agent_cls(
            system_prompt=system_prompt,
            tools=scoped_registry,
            model=adapter,
        )
    except Exception as exc:
        logger.exception("[delegation] failed to instantiate subagent %s", agent_id)
        await SUBAGENT_REGISTRY.fail(agent_id, f"instantiation error: {exc}")
        return

    final_response: str | None = None
    events_seen = 0

    async def _drive() -> None:
        nonlocal final_response, events_seen
        async for event in child_agent.run(prompt, child_context):
            events_seen += 1
            await SUBAGENT_REGISTRY.append_event(agent_id, event)
            _record_event_for_trajectory(recorder, event)

            etype = event.get("type")
            if etype == "complete":
                data = event.get("data") or {}
                final_response = data.get("final_response")
            elif etype == "error":
                # Surface the error as the final trajectory assistant note
                # so the parent can see what broke.
                note = event.get("content") or "subagent reported error"
                recorder.record_assistant(content=str(note))

            # Drain any messages the parent queued since the last tick.
            await _deliver_pending_messages(agent_id, child_context)

            # Honour the max_iterations budget at the event boundary.
            data = event.get("data") or {}
            iteration = data.get("iteration")
            if (
                isinstance(iteration, int)
                and iteration >= max_iterations
                and etype in ("agent_step", "complete")
            ) and etype != "complete":
                break

    try:
        await asyncio.wait_for(_drive(), timeout=timeout_s)
        trajectory = recorder.to_atif()
        await SUBAGENT_REGISTRY.complete(
            agent_id, final_response=final_response, trajectory=trajectory
        )
    except asyncio.CancelledError:
        # Ensure the current status reflects cancellation. If a concurrent
        # ``close_agent`` already marked it, this is a no-op.
        record = SUBAGENT_REGISTRY.get(agent_id)
        if record is not None and record.status not in TERMINAL_STATUSES:
            record.trajectory = recorder.to_atif()
            record.final_response = final_response
            record.completed_at = datetime.now(UTC)
            # Preserve any status that cancel() set; otherwise mark cancelled.
            from .agent_registry import STATUS_CANCELLED

            record.status = STATUS_CANCELLED
        raise
    except TimeoutError:
        record = SUBAGENT_REGISTRY.get(agent_id)
        if record is not None:
            record.trajectory = recorder.to_atif()
            record.final_response = final_response
        await SUBAGENT_REGISTRY.mark_timed_out(agent_id)
    except Exception as exc:
        logger.exception("[delegation] subagent %s failed", agent_id)
        record = SUBAGENT_REGISTRY.get(agent_id)
        if record is not None:
            record.trajectory = recorder.to_atif()
            record.final_response = final_response
        await SUBAGENT_REGISTRY.fail(agent_id, str(exc))


# ---------------------------------------------------------------------------
# Tool executor: task
# ---------------------------------------------------------------------------


async def task_executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    role = str(params.get("role") or "").strip()
    prompt = params.get("prompt")
    if not role:
        return error_output(
            message="role is required",
            suggestion="Pass a short label like 'explore-codebase' or 'refactor-tests'",
        )
    if not isinstance(prompt, str) or not prompt.strip():
        return error_output(
            message="prompt is required",
            suggestion="Describe the task the subagent should complete",
        )

    parent_depth = int(context.get("subagent_depth", 0))
    if parent_depth >= MAX_SUBAGENT_DEPTH:
        return error_output(
            message="maximum subagent depth reached",
            suggestion=(
                f"Parent is already at depth {parent_depth}; "
                f"limit is {MAX_SUBAGENT_DEPTH}. Complete this task directly."
            ),
            details={"parent_depth": parent_depth, "max_depth": MAX_SUBAGENT_DEPTH},
        )

    tool_names = params.get("tool_names")
    if tool_names is not None and not isinstance(tool_names, list):
        return error_output(
            message="tool_names must be a list of strings when provided",
        )

    system_prompt_override = params.get("system_prompt_override")
    model_name = params.get("model_name")
    max_iterations = params.get("max_iterations") or DEFAULT_MAX_ITERATIONS
    try:
        max_iterations = int(max_iterations)
    except (TypeError, ValueError):
        max_iterations = DEFAULT_MAX_ITERATIONS
    max_iterations = max(1, max_iterations)

    reasoning_effort = params.get("reasoning_effort")
    wait_flag = bool(params.get("wait", False))
    timeout_ms = _clamp_timeout(params.get("timeout_ms"))

    scoped_registry = _resolve_tool_registry(tool_names)

    try:
        adapter = await _resolve_model_adapter(context, model_name)
    except Exception as exc:
        logger.exception("[delegation] adapter resolution failed")
        return error_output(
            message=f"failed to resolve model adapter: {exc}",
            suggestion="Verify the model_name is configured and API keys are set",
        )

    if reasoning_effort and hasattr(adapter, "thinking_effort"):
        try:
            adapter.thinking_effort = reasoning_effort
        except Exception:
            logger.debug(
                "[delegation] adapter %s ignored reasoning_effort override",
                getattr(adapter, "model_name", "?"),
            )

    # Late import to avoid a circular import at module load time.
    from ...tesslate_agent import TesslateAgent

    agent_id = uuid_mod.uuid4().hex
    child_context = _build_child_context(context, agent_id, adapter)
    system_prompt = (
        system_prompt_override
        if isinstance(system_prompt_override, str) and system_prompt_override.strip()
        else f"{_DEFAULT_SYSTEM_PROMPT}\n\nAssigned task:\n{prompt}"
    )

    record = SubagentRecord(
        agent_id=agent_id,
        role=role,
        status=STATUS_PENDING,
        spawned_at=datetime.now(UTC),
        task_text=prompt,
        model_name=getattr(adapter, "model_name", model_name or "unknown"),
        depth=parent_depth + 1,
        parent_agent_id=context.get("agent_id"),
    )
    await SUBAGENT_REGISTRY.register(record)

    task = asyncio.create_task(
        _run_subagent(
            agent_id=agent_id,
            prompt=prompt,
            child_agent_cls=TesslateAgent,
            system_prompt=system_prompt,
            scoped_registry=scoped_registry,
            adapter=adapter,
            max_iterations=max_iterations,
            child_context=child_context,
            timeout_s=timeout_ms / 1000.0,
        ),
        name=f"subagent-{agent_id}",
    )
    SUBAGENT_REGISTRY.attach_task(agent_id, task)

    if not wait_flag:
        return success_output(
            message=f"Subagent {role} spawned",
            agent_id=agent_id,
            role=role,
            status=STATUS_RUNNING,
            spawned_at=record.spawned_at.isoformat(),
            depth=record.depth,
        )

    # Blocking mode — await the task with a shared deadline.
    start_ms = datetime.now(UTC).timestamp() * 1000
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout_ms / 1000.0)
    except TimeoutError:
        return error_output(
            message=f"Subagent {role} did not complete within timeout",
            agent_id=agent_id,
            status=STATUS_RUNNING,
            suggestion="Use wait_agent to keep waiting, or close_agent to cancel",
        )
    except Exception as exc:
        # Task crashed or was cancelled — the record has authoritative state.
        logger.debug("[delegation] wait=True raised: %s", exc)

    record = SUBAGENT_REGISTRY.get(agent_id)
    if record is None:  # pragma: no cover - defensive
        return error_output(message="subagent record disappeared")

    elapsed_ms = int(datetime.now(UTC).timestamp() * 1000 - start_ms)
    return success_output(
        message=f"Subagent {role} finished with status {record.status}",
        agent_id=agent_id,
        role=role,
        status=record.status,
        final_response=record.final_response,
        trajectory=record.trajectory,
        error=record.error,
        duration_ms=elapsed_ms,
        depth=record.depth,
    )


# ---------------------------------------------------------------------------
# Tool executor: wait_agent
# ---------------------------------------------------------------------------


async def wait_agent_executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    agent_id = params.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return error_output(message="agent_id is required")

    record = SUBAGENT_REGISTRY.get(agent_id)
    if record is None:
        return error_output(
            message=f"unknown subagent agent_id={agent_id}",
            suggestion="Use list_agents to see currently tracked subagents",
        )

    timeout_ms = _clamp_timeout(params.get("timeout_ms"))
    start_ms = datetime.now(UTC).timestamp() * 1000

    task = record.task
    if task is not None and not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout_ms / 1000.0)
        except TimeoutError:
            return success_output(
                message=f"Subagent {agent_id} still running",
                agent_id=agent_id,
                status="still_running",
            )
        except Exception as exc:
            logger.debug("[delegation] wait_agent shielded await raised: %s", exc)

    duration_ms = int(datetime.now(UTC).timestamp() * 1000 - start_ms)
    record = SUBAGENT_REGISTRY.get(agent_id)
    if record is None:  # pragma: no cover - defensive
        return error_output(message="subagent record disappeared")

    return success_output(
        message=f"Subagent {agent_id} status={record.status}",
        agent_id=agent_id,
        status=record.status,
        final_response=record.final_response,
        trajectory=record.trajectory,
        error=record.error,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Tool executor: send_message_to_agent
# ---------------------------------------------------------------------------


async def send_message_to_agent_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    agent_id = params.get("agent_id")
    message = params.get("message")
    if not isinstance(agent_id, str) or not agent_id:
        return error_output(message="agent_id is required")
    if not isinstance(message, str) or not message:
        return error_output(message="message is required")

    try:
        queue_depth = await SUBAGENT_REGISTRY.enqueue_message(agent_id, message)
    except ValueError as exc:
        return error_output(message=str(exc))

    return success_output(
        message=f"Message queued for {agent_id}",
        agent_id=agent_id,
        queued=True,
        queue_depth=queue_depth,
    )


# ---------------------------------------------------------------------------
# Tool executor: close_agent
# ---------------------------------------------------------------------------


async def close_agent_executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    agent_id = params.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id:
        return error_output(message="agent_id is required")

    record = SUBAGENT_REGISTRY.get(agent_id)
    if record is None:
        return error_output(
            message=f"unknown subagent agent_id={agent_id}",
            suggestion="Use list_agents to see currently tracked subagents",
        )

    was_terminal = record.status in TERMINAL_STATUSES
    cancelled = await SUBAGENT_REGISTRY.cancel(agent_id)
    if not cancelled:  # pragma: no cover - defensive
        return error_output(message=f"failed to cancel subagent {agent_id}")

    # Give the task a chance to observe the cancel so tests and callers
    # see the final status without a race.
    task = record.task
    if task is not None and not task.done():
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, Exception):
            await asyncio.wait_for(task, timeout=1.0)

    fresh = SUBAGENT_REGISTRY.get(agent_id)
    status = fresh.status if fresh is not None else "unknown"
    return success_output(
        message=(
            f"Subagent {agent_id} already terminal"
            if was_terminal
            else f"Subagent {agent_id} cancelled"
        ),
        agent_id=agent_id,
        status=status,
    )


# ---------------------------------------------------------------------------
# Tool executor: list_agents
# ---------------------------------------------------------------------------


async def list_agents_executor(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    parent_agent_id = params.get("parent_agent_id")
    status_filter = params.get("status")
    if parent_agent_id is not None and not isinstance(parent_agent_id, str):
        return error_output(message="parent_agent_id must be a string")
    if status_filter is not None and not isinstance(status_filter, str):
        return error_output(message="status must be a string")

    snapshots = SUBAGENT_REGISTRY.snapshot_for_listing(
        parent_agent_id=parent_agent_id,
        status=status_filter,
    )
    return success_output(
        message=f"Found {len(snapshots)} subagents",
        agents=snapshots,
        details={"count": len(snapshots)},
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_delegation_ops_tools(registry: ToolRegistry) -> None:
    """Register all delegation tools on the given registry."""

    registry.register(
        Tool(
            name="task",
            description=(
                "Spawn a specialist subagent to handle a focused subtask "
                "with its own tool-scoped workspace. Use this when a task "
                "benefits from a dedicated agent thread (e.g. deep code "
                "exploration, a self-contained refactor, long-running "
                "analysis). Set wait=true to block until the subagent "
                "finishes, or wait=false to get an agent_id back immediately "
                "and poll with wait_agent."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "Short descriptor of the subagent's purpose (e.g. 'explore-codebase').",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The task the subagent should complete.",
                    },
                    "tool_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional allowlist of tool names to expose to the subagent. Defaults to the parent's full set minus delegation tools.",
                    },
                    "system_prompt_override": {
                        "type": "string",
                        "description": "Optional full system prompt for the subagent.",
                    },
                    "model_name": {
                        "type": "string",
                        "description": "Optional model name override. Defaults to the parent's model.",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Optional cap on child agent iterations. Default 15.",
                    },
                    "reasoning_effort": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                        "description": "Optional reasoning effort override for supported models.",
                    },
                    "wait": {
                        "type": "boolean",
                        "description": "If true, block until the subagent finishes (bounded by timeout_ms). Default false.",
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Wall-clock timeout in milliseconds. Default 600000, max 3600000.",
                    },
                },
                "required": ["role", "prompt"],
            },
            executor=task_executor,
            category=ToolCategory.DELEGATION_OPS,
            examples=[
                '{"role": "explore-codebase", "prompt": "Map every caller of foo()", "wait": false}',
                '{"role": "refactor-tests", "prompt": "Port tests to pytest-asyncio", "wait": true, "timeout_ms": 300000}',
            ],
        )
    )

    registry.register(
        Tool(
            name="wait_agent",
            description=(
                "Wait for a previously spawned subagent to finish. Returns "
                "the final response, trajectory, and status. If the subagent "
                "is still running past timeout_ms, returns a still_running "
                "status without cancelling it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The agent_id returned by task.",
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Wall-clock timeout in milliseconds. Default 600000, max 3600000.",
                    },
                },
                "required": ["agent_id"],
            },
            executor=wait_agent_executor,
            category=ToolCategory.DELEGATION_OPS,
        )
    )

    registry.register(
        Tool(
            name="send_message_to_agent",
            description=(
                "Queue a message to be delivered to a running subagent at "
                "its next event boundary. The subagent will see the message "
                "in its run-context's injected_messages list."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The agent_id returned by task.",
                    },
                    "message": {
                        "type": "string",
                        "description": "Message contents to inject into the running subagent.",
                    },
                },
                "required": ["agent_id", "message"],
            },
            executor=send_message_to_agent_executor,
            category=ToolCategory.DELEGATION_OPS,
        )
    )

    registry.register(
        Tool(
            name="close_agent",
            description=(
                "Cancel a running subagent. Idempotent — calling on an "
                "already-terminal agent is a no-op."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "The agent_id returned by task.",
                    },
                },
                "required": ["agent_id"],
            },
            executor=close_agent_executor,
            category=ToolCategory.DELEGATION_OPS,
        )
    )

    registry.register(
        Tool(
            name="list_agents",
            description=(
                "List all subagents spawned during this agent run, with "
                "optional filtering by parent_agent_id or status."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "parent_agent_id": {
                        "type": "string",
                        "description": "Optional: only return children of this agent_id.",
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional: filter by status (pending, running, completed, failed, cancelled, timed_out).",
                    },
                },
                "required": [],
            },
            executor=list_agents_executor,
            category=ToolCategory.DELEGATION_OPS,
        )
    )

    logger.info("Registered 5 delegation_ops tools")
