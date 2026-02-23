"""
TesslateAgent

Native function-calling agent that uses the OpenAI tools API for structured
tool invocation. This replaces the text-based JSON parsing of IterativeAgent
with reliable, API-level tool calls.

Key features:
- Native OpenAI function calling (tools=[...], tool_choice="auto")
- RwLock-style parallel tool execution (reads concurrent, writes exclusive)
- Context compaction at 80% of context window
- Subagent support (general-purpose, Plan, Explore)
- Plan mode integration with existing ToolRegistry blocking
- Exponential backoff retry for transient API errors

The system_prompt comes from the MarketplaceAgent DB model (users can customize
via fork/edit in the Library). The prompt_templates/ .md files are seed defaults
and internal subagent prompts - NOT loaded at runtime for the main agent.
"""

import asyncio
import contextlib
import json
import logging
import random
import uuid as uuid_mod
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from .base import AbstractAgent
from .compaction import compact_conversation
from .features import Feature, Features
from .models import ModelAdapter
from .plan_manager import PlanManager
from .prompt_templates import load_prompt as load_prompt_template
from .resource_limits import ResourceLimitExceeded, get_resource_limits
from .tool_converter import is_parallel_tool, registry_to_openai_tools
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Retry constants (matching Codex's backoff pattern)
INITIAL_DELAY_MS = 200
MAX_RETRIES = 5
RETRYABLE_KEYWORDS = frozenset(
    {
        "timeout",
        "connection",
        "temporary",
        "transient",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "rate limit",
        "stream",
        "502",
        "503",
        "504",
        "429",
    }
)

# Context window defaults
DEFAULT_CONTEXT_WINDOW = 128_000
COMPACTION_THRESHOLD = 0.8

# Tool output truncation
MAX_TOOL_OUTPUT = 10_000


# =============================================================================
# Utility Functions
# =============================================================================


def _backoff(attempt: int) -> float:
    """Exponential backoff with jitter. Returns delay in seconds."""
    exp = 2.0 ** max(0, attempt)
    base_ms = INITIAL_DELAY_MS * exp
    jitter = random.uniform(0.9, 1.1)
    return (base_ms * jitter) / 1000.0


def _is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable based on keywords."""
    error_str = str(error).lower()
    return any(kw in error_str for kw in RETRYABLE_KEYWORDS)


def _safe_json_loads(s: str) -> dict[str, Any]:
    """Safely parse JSON string, returning empty dict on failure."""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


def _convert_uuids(obj: Any) -> Any:
    """Recursively convert UUID objects to strings for JSON serialization."""
    if isinstance(obj, UUID):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: _convert_uuids(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_uuids(item) for item in obj]
    return obj


# =============================================================================
# Message Serialization
# =============================================================================


def serialize_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Serialize an assistant message for the conversation history.

    Follows the exact OpenAI format:
    - content is None (not omitted) when tool_calls are present
    - Each tool_call has explicit "type": "function"
    - Arguments remain as JSON strings
    """
    if not tool_calls:
        return {"role": "assistant", "content": content or ""}

    serialized = []
    for tc in tool_calls:
        serialized.append(
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": tc.get("function", {}).get("arguments", "{}"),
                },
            }
        )

    return {
        "role": "assistant",
        "content": None,
        "tool_calls": serialized,
    }


def format_tool_result(result: dict[str, Any]) -> str:
    """
    Format a tool execution result as a string for role:"tool" messages.
    Applies intelligent truncation for large outputs.
    """
    if result.get("approval_required"):
        return f"Awaiting approval for {result.get('tool', 'unknown')}"

    if result.get("success"):
        tool_result = result.get("result", {})
        if isinstance(tool_result, dict):
            parts = []
            if "message" in tool_result:
                parts.append(tool_result["message"])

            for field_name in ("content", "stdout", "output", "preview"):
                if field_name in tool_result:
                    output = str(tool_result[field_name])
                    if len(output) > MAX_TOOL_OUTPUT:
                        half = MAX_TOOL_OUTPUT // 2
                        elided = len(output) - MAX_TOOL_OUTPUT
                        output = (
                            f"{output[:half]}\n... ({elided} chars truncated) ...\n{output[-half:]}"
                        )
                    parts.append(output)

            if "files" in tool_result and isinstance(tool_result["files"], list):
                parts.append(
                    f"Files ({len(tool_result['files'])} items): {tool_result['files'][:20]}"
                )

            if tool_result.get("stderr"):
                parts.append(f"stderr: {tool_result['stderr']}")

            return "\n".join(parts) if parts else json.dumps(tool_result)
        return str(tool_result)

    error = result.get("error", "Unknown error")
    suggestion = ""
    if isinstance(result.get("result"), dict):
        suggestion = result["result"].get("suggestion", "")
    return f"Error: {error}" + (f"\nSuggestion: {suggestion}" if suggestion else "")


# =============================================================================
# TesslateAgent Class
# =============================================================================


class TesslateAgent(AbstractAgent):
    """
    Agent using native OpenAI function calling for reliable tool invocation.

    The agent loop:
    1. Build system prompt with marker substitution (from DB, user-customizable)
    2. Convert ToolRegistry to OpenAI tools format
    3. Call LLM with tools (streaming)
    4. If tool_calls returned: execute, feed results back, continue
    5. If no tool_calls: task complete, return
    6. Compact context if approaching window limit
    """

    def __init__(
        self,
        system_prompt: str,
        tools: ToolRegistry | None = None,
        model: ModelAdapter | None = None,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        enable_subagents: bool = True,
        features: Features | None = None,
    ):
        super().__init__(system_prompt, tools)
        self.model = model
        self.context_window = context_window
        self.features = features or Features()
        # enable_subagents kept for backward compat; features takes precedence
        self.enable_subagents = enable_subagents and self.features.enabled(Feature.SUBAGENTS)

        logger.info(
            f"TesslateAgent initialized - "
            f"tools: {len(self.tools._tools) if self.tools else 0}, "
            f"context_window: {context_window}, subagents: {self.enable_subagents}, "
            f"features: {self.features}"
        )

    def set_model(self, model: ModelAdapter):
        """Set the model adapter (for lazy initialization)."""
        self.model = model

    # -------------------------------------------------------------------------
    # Main Agent Loop
    # -------------------------------------------------------------------------

    async def run(
        self,
        user_request: str,
        context: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Run the agent to complete a user request.

        Yields events: text_chunk, agent_step, approval_required, complete, error
        """
        if not self.model:
            yield {"type": "error", "content": "Model adapter not set."}
            return

        logger.info(f"[TesslateAgent] Starting - request: {user_request[:100]}...")

        # Per-run state
        limits = get_resource_limits()
        run_id = (
            f"user-{context.get('user_id')}-"
            f"project-{context.get('project_id')}-"
            f"{datetime.now(UTC).timestamp()}"
        )
        tool_calls_count = 0
        iteration = 0

        # Trajectory recording
        from .trajectory import TrajectoryRecorder
        from .trajectory_writer import TrajectoryWriter

        session_id = str(uuid_mod.uuid4())
        recorder = TrajectoryRecorder(
            session_id=session_id,
            model_name=getattr(self.model, "model_name", "unknown"),
        )
        writer = TrajectoryWriter(context=context, session_id=session_id)
        subagent_counter = 0

        # Build messages
        messages = await self._build_initial_messages(user_request, context)

        # Record initial messages for trajectory
        if messages:
            recorder.record_system(messages[0].get("content", ""))
        recorder.record_user(user_request)
        await writer.flush(recorder)

        # Initialize subagent manager with custom subagent loading
        subagent_manager = None
        if self.enable_subagents and self.tools:
            from .subagent_manager import SubagentManager

            subagent_manager = SubagentManager(
                model_adapter=self.model,
                base_tool_registry=self.tools,
                context=context,
            )
            # Load custom subagents from container and DB (non-blocking)
            try:
                await subagent_manager.load_custom_subagents()
                await subagent_manager.load_user_subagents()
            except Exception as e:
                logger.warning(f"[TesslateAgent] Custom subagent loading failed: {e}")

        # Convert tools to OpenAI format (after subagent_manager so it can populate the tool description)
        openai_tools = self._get_openai_tools(context, subagent_manager)

        try:
            while True:
                iteration += 1
                logger.info(f"[TesslateAgent] Iteration {iteration}")

                # Resource limits check
                try:
                    limits.add_iteration(run_id)
                except ResourceLimitExceeded as e:
                    logger.warning(f"[TesslateAgent] Resource limit: {e}")
                    yield {"type": "error", "content": f"Resource limit exceeded: {e}"}
                    yield self._complete_event(
                        False,
                        iteration,
                        "",
                        str(e),
                        tool_calls_count,
                        "resource_limit_exceeded",
                        limits.get_stats(run_id),
                        session_id=session_id,
                    )
                    return

                # Context compaction
                compacted = await compact_conversation(
                    messages, self.model, self.context_window, COMPACTION_THRESHOLD
                )
                if compacted is not None:
                    messages = compacted

                # Call LLM
                try:
                    content, tool_calls, usage = await self._call_llm_with_retry(
                        messages, openai_tools
                    )
                except Exception as e:
                    logger.error(f"[TesslateAgent] LLM call failed: {e}")
                    yield {"type": "error", "content": f"Agent error: {str(e)}"}
                    yield self._complete_event(
                        False,
                        iteration,
                        "",
                        str(e),
                        tool_calls_count,
                        "error",
                        limits.get_stats(run_id),
                        session_id=session_id,
                    )
                    return

                # Record assistant response
                recorder.record_assistant(content, tool_calls, usage)
                await writer.flush(recorder)

                # --- Credit deduction (non-blocking) ---
                try:
                    from ..database import AsyncSessionLocal
                    from ..services.credit_service import deduct_credits

                    model_name = context.get("model_name", "")
                    agent_id = context.get("agent_id")
                    project_id = context.get("project_id")
                    user_id = context.get("user_id")

                    if user_id and model_name:
                        tokens_in = usage.get("prompt_tokens", 0) if usage else 0
                        tokens_out = usage.get("completion_tokens", 0) if usage else 0

                        # Estimate tokens if provider didn't return usage
                        if not tokens_in and not tokens_out:
                            msg_text = " ".join(
                                m.get("content", "")
                                for m in messages
                                if isinstance(m.get("content"), str)
                            )
                            tokens_in = max(1, len(msg_text) // 4)
                            tokens_out = max(1, len(content or "") // 4)

                        async with AsyncSessionLocal() as credit_db:
                            credit_result = await deduct_credits(
                                db=credit_db,
                                user_id=user_id,
                                model_name=model_name,
                                tokens_in=tokens_in,
                                tokens_out=tokens_out,
                                agent_id=agent_id,
                                project_id=project_id,
                            )
                            yield {"type": "credits_used", "data": credit_result}

                            if (
                                not credit_result.get("is_byok")
                                and credit_result.get("new_balance", 1) <= 0
                            ):
                                yield {
                                    "type": "error",
                                    "content": "You have run out of credits. Please purchase more to continue.",
                                }
                                yield self._complete_event(
                                    False,
                                    iteration,
                                    content or "",
                                    "credits_exhausted",
                                    tool_calls_count,
                                    "credits_exhausted",
                                    limits.get_stats(run_id),
                                    session_id=session_id,
                                )
                                return
                except Exception as e:
                    logger.warning(f"[TesslateAgent] Credit deduction failed (non-blocking): {e}")

                # No tool calls = done
                if not tool_calls:
                    logger.info(f"[TesslateAgent] Complete in {iteration} iterations")
                    yield self._complete_event(
                        True,
                        iteration,
                        content or "Task completed.",
                        None,
                        tool_calls_count,
                        "no_more_actions",
                        limits.get_stats(run_id),
                        session_id=session_id,
                    )
                    return

                # Add assistant message to history
                messages.append(serialize_assistant_message(content, tool_calls))

                # Emit tool_started so the frontend updates immediately
                yield {
                    "type": "tool_started",
                    "data": {
                        "iteration": iteration,
                        "tools": [
                            {
                                "name": tc.get("function", {}).get("name", ""),
                                "parameters": _convert_uuids(
                                    _safe_json_loads(tc.get("function", {}).get("arguments", "{}"))
                                ),
                            }
                            for tc in tool_calls
                        ],
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                }

                # Execute tool calls
                tool_results = await self._execute_tool_calls(tool_calls, context, subagent_manager)
                tool_calls_count += len(tool_calls)

                # Handle approval requests
                for idx, result in enumerate(tool_results):
                    if result.get("approval_required"):
                        # Phase 1: Create approval request and yield event to SSE
                        approval_id, request, event_data = await self._create_approval_request(
                            result, tool_calls[idx]
                        )
                        yield event_data  # Frontend sees approval_required NOW

                        # Phase 2: Wait for user response (with timeout)
                        approval_result = await self._wait_for_approval(
                            approval_id, request, tool_calls[idx], context
                        )
                        if approval_result.get("type") == "complete":
                            yield approval_result
                            return
                        elif "result" in approval_result:
                            tool_results[idx] = approval_result["result"]

                # Add tool results to history and record for trajectory
                for idx, tc in enumerate(tool_calls):
                    tc_id = tc.get("id", f"call_{idx}")
                    result_text = format_tool_result(tool_results[idx])
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": result_text,
                        }
                    )
                    recorder.record_tool_result(tc_id, result_text)

                # Save subagent trajectories and mirror plans
                for idx, tc in enumerate(tool_calls):
                    fn = tc.get("function", {})
                    tool_name = fn.get("name", "")

                    # Subagent trajectory
                    if tool_name == "invoke_subagent" and subagent_manager:
                        result_data = tool_results[idx].get("result", {})
                        agent_id = (
                            result_data.get("agent_id") if isinstance(result_data, dict) else None
                        )
                        if agent_id:
                            session = subagent_manager.get_session(agent_id)
                            if session:
                                subagent_counter += 1
                                await writer.save_subagent_trajectory(
                                    subagent_type=session.name,
                                    index=subagent_counter,
                                    agent_id=agent_id,
                                    messages=session.messages,
                                    model_name=getattr(self.model, "model_name", "unknown"),
                                )

                    # Plan mirroring
                    if tool_name in ("save_plan", "update_plan"):
                        plan = PlanManager.get_plan_sync(context)
                        if plan:
                            await writer.mirror_plan(plan.to_markdown(), plan.name)

                await writer.flush(recorder)

                # Yield agent_step
                yield {
                    "type": "agent_step",
                    "data": {
                        "iteration": iteration,
                        "thought": None,
                        "tool_calls": [
                            {
                                "name": tc.get("function", {}).get("name", ""),
                                "parameters": _convert_uuids(
                                    _safe_json_loads(tc.get("function", {}).get("arguments", "{}"))
                                ),
                            }
                            for tc in tool_calls
                        ],
                        "tool_results": _convert_uuids(tool_results),
                        "response_text": content or "",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "is_complete": False,
                    },
                }

        finally:
            # Final trajectory flush (best-effort)
            with contextlib.suppress(Exception):
                await writer.flush(recorder)
            limits.cleanup_run(run_id)

    # -------------------------------------------------------------------------
    # Message Building
    # -------------------------------------------------------------------------

    async def _build_initial_messages(
        self,
        user_request: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build the initial message list with system prompt, history, and user request."""
        # System prompt from DB (user-customizable) + marker substitution
        system_prompt = self._build_system_prompt(context)

        # User message with context wrapper
        from .prompts import get_user_message_wrapper

        project_context = context.get("project_context") or {}
        project_context["user_id"] = context.get("user_id")
        project_context["project_id"] = context.get("project_id")
        user_message = await get_user_message_wrapper(user_request, project_context)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Chat history for conversation continuity
        chat_history = context.get("chat_history", [])
        if chat_history:
            logger.info(f"[TesslateAgent] Including {len(chat_history)} history messages")
            messages.extend(chat_history)

        messages.append({"role": "user", "content": user_message})
        return messages

    def _build_system_prompt(self, context: dict[str, Any]) -> str:
        """
        Build system prompt with marker substitution.

        The base prompt comes from the MarketplaceAgent DB model (user-customizable
        via Library fork/edit). We add plan mode guidance and active plan context.
        Unlike IterativeAgent, tool info is NOT in the system prompt (it's in the API).
        """
        processed = self.get_processed_system_prompt(context)

        if context.get("edit_mode") == "plan":
            plan_guidance = load_prompt_template("plan_mode_main")
            if plan_guidance:
                processed += f"\n\n{plan_guidance}"

        # Inject active plan context if one exists (1:1 codex pattern)
        # Uses sync variant — dict.get() is atomic in CPython, and we only
        # need a consistent snapshot for the system prompt.
        if self.features.enabled(Feature.PLAN_MODE):
            plan = PlanManager.get_plan_sync(context)
            if plan:
                plan_context = plan.to_markdown()
                processed += (
                    f"\n\n=== ACTIVE PLAN ===\n{plan_context}\n=== END PLAN ===\n\n"
                    f"Continue executing from the current in_progress step. "
                    f"Mark steps completed as you finish them using update_plan."
                )

        return processed

    def _get_openai_tools(
        self,
        context: dict[str, Any],
        subagent_manager=None,
    ) -> list[dict[str, Any]]:
        """Get OpenAI-format tools, filtered by features, with invoke_subagent if enabled."""
        if not self.tools:
            return []

        tools = registry_to_openai_tools(self.tools)

        # Filter tools by feature flags
        filtered = []
        for tool in tools:
            name = tool.get("function", {}).get("name", "")
            # apply_patch requires APPLY_PATCH feature
            if name == "apply_patch" and not self.features.enabled(Feature.APPLY_PATCH):
                continue
            # save_plan/update_plan require PLAN_MODE feature
            if name in ("save_plan", "update_plan") and not self.features.enabled(
                Feature.PLAN_MODE
            ):
                continue
            # web_fetch requires WEB_SEARCH feature
            if name == "web_fetch" and not self.features.enabled(Feature.WEB_SEARCH):
                continue
            filtered.append(tool)
        tools = filtered

        if self.enable_subagents and subagent_manager:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "invoke_subagent",
                        "description": subagent_manager.get_invoke_tool_description(),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Name of the subagent to invoke",
                                },
                                "task": {
                                    "type": "string",
                                    "description": "Specific task for the subagent",
                                },
                                "context": {
                                    "type": "string",
                                    "description": "Optional context from prior exploration",
                                },
                                "resume_id": {
                                    "type": "string",
                                    "description": "Optional agent_id to resume a previous session",
                                },
                            },
                            "required": ["name", "task"],
                        },
                    },
                }
            )

        return tools

    # -------------------------------------------------------------------------
    # LLM Calling with Retry
    # -------------------------------------------------------------------------

    async def _call_llm_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> tuple:
        """Call LLM with exponential backoff. Returns (content, tool_calls, usage)."""
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                return await self._call_llm_streaming(messages, tools)
            except Exception as e:
                last_error = e
                if not _is_retryable_error(e) or attempt == MAX_RETRIES - 1:
                    raise

                delay = _backoff(attempt)
                logger.warning(
                    f"[TesslateAgent] Retry {attempt + 1}/{MAX_RETRIES} after {delay:.1f}s: {e}"
                )
                await asyncio.sleep(delay)

        raise last_error

    async def _call_llm_streaming(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> tuple:
        """Call LLM and accumulate response. Returns (content, tool_calls, usage)."""
        content = ""
        tool_calls = []
        usage = None

        async for event in self.model.chat_with_tools(
            messages=messages,
            tools=tools,
            tool_choice="auto",
        ):
            t = event.get("type", "")
            if t == "text_delta":
                content += event.get("content", "")
            elif t == "tool_calls_complete":
                tool_calls = event.get("tool_calls", [])
            elif t == "done":
                usage = event.get("usage")

        return content, tool_calls, usage

    # -------------------------------------------------------------------------
    # Tool Execution (Parallel Reads, Sequential Writes)
    # -------------------------------------------------------------------------

    async def _execute_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        context: dict[str, Any],
        subagent_manager=None,
    ) -> list[dict[str, Any]]:
        """Execute tool calls with RwLock-style parallelism."""
        if not self.tools:
            return [{"success": False, "error": "No tool registry"}] * len(tool_calls)

        parallel_tasks = []
        sequential_tasks = []

        for idx, tc in enumerate(tool_calls):
            fn = tc.get("function", {})
            name = fn.get("name", "")
            params = _safe_json_loads(fn.get("arguments", "{}"))
            info = (idx, name, params, tc)

            if name == "invoke_subagent":
                sequential_tasks.append(info)
            elif is_parallel_tool(name):
                parallel_tasks.append(info)
            else:
                sequential_tasks.append(info)

        results: list[dict | None] = [None] * len(tool_calls)

        # Parallel read tools
        if parallel_tasks:

            async def _run(info):
                idx, name, params, _ = info
                return idx, await self.tools.execute(name, params, context)

            outcomes = await asyncio.gather(
                *[_run(i) for i in parallel_tasks],
                return_exceptions=True,
            )
            for outcome in outcomes:
                if isinstance(outcome, Exception):
                    logger.error(f"[TesslateAgent] Parallel tool error: {outcome}")
                else:
                    idx, result = outcome
                    results[idx] = result

        # Sequential write/mutating tools
        for idx, name, params, _tc in sequential_tasks:
            if name == "invoke_subagent" and subagent_manager:
                results[idx] = await self._invoke_subagent(params, subagent_manager)
            else:
                results[idx] = await self.tools.execute(name, params, context)

        # Fill None results
        for i in range(len(results)):
            if results[i] is None:
                results[i] = {"success": False, "error": "Tool execution failed"}

        return results

    async def _invoke_subagent(
        self,
        parameters: dict[str, Any],
        subagent_manager,
    ) -> dict[str, Any]:
        """Handle invoke_subagent tool call with resume support."""
        name = parameters.get("name", "")
        task = parameters.get("task", "")
        context_str = parameters.get("context")
        resume_id = parameters.get("resume_id")

        try:
            result_text, agent_id = await subagent_manager.invoke(
                name=name,
                task=task,
                context_str=context_str,
                resume_id=resume_id,
            )
            return {
                "success": True,
                "tool": "invoke_subagent",
                "result": {
                    "message": f"Subagent '{name}' completed (agent_id: {agent_id})",
                    "content": result_text,
                    "agent_id": agent_id,
                },
            }
        except ValueError as e:
            return {"success": False, "tool": "invoke_subagent", "error": str(e)}
        except Exception as e:
            logger.error(f"[TesslateAgent] Subagent error: {e}", exc_info=True)
            return {
                "success": False,
                "tool": "invoke_subagent",
                "error": f"Subagent failed: {str(e)}",
            }

    # -------------------------------------------------------------------------
    # Approval Handling
    # -------------------------------------------------------------------------

    async def _create_approval_request(
        self,
        result: dict[str, Any],
        tool_call: dict[str, Any],
    ) -> tuple:
        """
        Phase 1: Create approval request and build SSE event.

        Returns (approval_id, request, event_data) — the event_data must be
        yielded to the SSE stream BEFORE calling _wait_for_approval so the
        frontend can render the approval buttons.
        """
        from .tools.approval_manager import get_approval_manager

        approval_mgr = get_approval_manager()
        fn = tool_call.get("function", {})
        tool_name = fn.get("name", "")
        parameters = _safe_json_loads(fn.get("arguments", "{}"))

        approval_id, request = await approval_mgr.request_approval(
            tool_name=result["tool"],
            parameters=result["parameters"],
            session_id=result["session_id"],
        )

        # Build the SSE event for the frontend
        tool_obj = self.tools.get(tool_name) if self.tools else None
        event_data = {
            "type": "approval_required",
            "data": {
                "approval_id": approval_id,
                "tool_name": tool_name,
                "tool_parameters": _convert_uuids(parameters),
                "tool_description": tool_obj.description if tool_obj else tool_name,
            },
        }

        logger.info(f"[TesslateAgent] Emitting approval_required {approval_id} for {tool_name}")
        return approval_id, request, event_data

    async def _wait_for_approval(
        self,
        approval_id: str,
        request,
        tool_call: dict[str, Any],
        context: dict[str, Any],
        timeout_seconds: float = 300.0,
    ) -> dict[str, Any]:
        """
        Phase 2: Wait for user approval response (with timeout).

        Must be called AFTER the approval_required event has been yielded
        to the SSE stream.
        """
        fn = tool_call.get("function", {})
        tool_name = fn.get("name", "")
        parameters = _safe_json_loads(fn.get("arguments", "{}"))

        logger.info(f"[TesslateAgent] Waiting for approval {approval_id}")
        try:
            await asyncio.wait_for(request.event.wait(), timeout=timeout_seconds)
        except TimeoutError:
            logger.warning(f"[TesslateAgent] Approval timeout for {approval_id}")
            return {
                "type": "complete",
                "data": {
                    "final_response": "Request timed out waiting for approval. Please try again.",
                    "iterations": 0,
                    "tool_calls_made": 0,
                    "completion_reason": "approval_timeout",
                },
            }

        logger.info(f"[TesslateAgent] Response: {request.response}")

        if request.response == "stop":
            return {
                "type": "complete",
                "data": {
                    "final_response": "Execution stopped by user.",
                    "iterations": 0,
                    "tool_calls_made": 0,
                    "completion_reason": "user_stopped",
                },
            }

        # Retry with approval granted
        approved_context = {**context, "skip_approval_check": True}
        retried = await self.tools.execute(
            tool_name=tool_name,
            parameters=parameters,
            context=approved_context,
        )
        return {"result": retried}

    # -------------------------------------------------------------------------
    # Event Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _complete_event(
        success: bool,
        iterations: int,
        final_response: str,
        error: str | None,
        tool_calls_made: int,
        reason: str,
        resource_stats: dict | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Build a complete event dict."""
        data = {
            "success": success,
            "iterations": iterations,
            "final_response": final_response,
            "tool_calls_made": tool_calls_made,
            "completion_reason": reason,
        }
        if error:
            data["error"] = error
        if resource_stats:
            data["resource_stats"] = resource_stats
        if session_id:
            data["session_id"] = session_id
        return {"type": "complete", "data": data}
