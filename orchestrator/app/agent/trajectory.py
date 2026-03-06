"""
ATIF v1.4 Trajectory Recording.

Records agent execution as timestamped entries and converts to the
Agent Trajectory Interchange Format (ATIF) v1.4 for observability.

Adapted for Tesslate's async agent infrastructure.

Output: timestamped JSON files in .tesslate/trajectories/ inside the
project volume, written via the orchestrator abstraction layer.
"""

from datetime import UTC, datetime
from typing import Any

AGENT_NAME = "tesslate-agent"
AGENT_VERSION = "1.0.0"
SCHEMA_VERSION = "ATIF-v1.4"


class TrajectoryRecorder:
    """Records agent messages for ATIF conversion.

    Each record_* method appends a timestamped entry. After the run
    completes, call to_atif() to get the full ATIF v1.4 dict.
    """

    def __init__(self, session_id: str, model_name: str):
        self.session_id = session_id
        self.model_name = model_name
        self.entries: list[dict[str, Any]] = []

    def record_system(self, content: str) -> None:
        self.entries.append(
            {
                "role": "system",
                "content": content,
                "timestamp": _now(),
            }
        )

    def record_user(self, content: str) -> None:
        self.entries.append(
            {
                "role": "user",
                "content": content,
                "timestamp": _now(),
            }
        )

    def record_assistant(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "role": "assistant",
            "content": content or "",
            "timestamp": _now(),
        }
        if tool_calls:
            entry["tool_calls"] = tool_calls
        if usage:
            entry["usage"] = usage
        self.entries.append(entry)

    def record_tool_result(self, tool_call_id: str, content: str) -> None:
        self.entries.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
                "timestamp": _now(),
            }
        )

    def to_atif(self) -> dict[str, Any]:
        """Convert recorded entries to ATIF v1.4 dict."""
        return convert_to_atif(
            trajectory=self.entries,
            session_id=self.session_id,
            model_name=self.model_name,
            agent_name=AGENT_NAME,
        )


def convert_to_atif(
    trajectory: list[dict[str, Any]],
    session_id: str,
    model_name: str,
    agent_name: str = AGENT_NAME,
    agent_version: str = AGENT_VERSION,
    extra_agent_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a raw trajectory list to ATIF v1.4 format.

    Tool results are attached as observation.results on the preceding
    agent step (matched by tool_call_id), NOT as separate steps.
    Tool results are matched by tool_call_id to the preceding agent step.
    """
    steps: list[dict[str, Any]] = []
    step_id = 0

    # Collect totals for final_metrics
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cached_tokens = 0
    agent_step_count = 0

    # First pass: build steps for system, user, and assistant entries.
    # Tool results are deferred and attached to the prior agent step.
    pending_tool_results: list[dict[str, Any]] = []

    for entry in trajectory:
        role = entry.get("role", "")

        if role == "tool":
            # Defer — will be attached to the last agent step
            pending_tool_results.append(entry)
            continue

        # Flush any pending tool results onto the last agent step
        if pending_tool_results and steps:
            _attach_tool_results(steps[-1], pending_tool_results)
            pending_tool_results = []

        step_id += 1

        if role == "system":
            steps.append(
                {
                    "step_id": step_id,
                    "timestamp": entry.get("timestamp", ""),
                    "source": "system",
                    "message": entry.get("content", ""),
                }
            )

        elif role == "user":
            steps.append(
                {
                    "step_id": step_id,
                    "timestamp": entry.get("timestamp", ""),
                    "source": "user",
                    "message": entry.get("content", ""),
                }
            )

        elif role == "assistant":
            agent_step_count += 1
            step: dict[str, Any] = {
                "step_id": step_id,
                "timestamp": entry.get("timestamp", ""),
                "source": "agent",
                "model_name": model_name,
                "message": entry.get("content", ""),
            }

            # Tool calls
            tool_calls = entry.get("tool_calls")
            if tool_calls:
                step["tool_calls"] = [
                    {
                        "tool_call_id": tc.get("id", ""),
                        "function_name": tc.get("function", {}).get("name", ""),
                        "arguments": _safe_parse_arguments(
                            tc.get("function", {}).get("arguments", "{}")
                        ),
                    }
                    for tc in tool_calls
                ]

            # Per-step metrics from usage
            usage = entry.get("usage") or {}
            prompt = usage.get("prompt_tokens", 0)
            completion = usage.get("completion_tokens", 0)
            cached = usage.get("cached_tokens", 0)
            if prompt or completion:
                metrics: dict[str, int] = {
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                }
                if cached:
                    metrics["cached_tokens"] = cached
                step["metrics"] = metrics

            total_prompt_tokens += prompt
            total_completion_tokens += completion
            total_cached_tokens += cached

            steps.append(step)

    # Flush remaining tool results
    if pending_tool_results and steps:
        _attach_tool_results(steps[-1], pending_tool_results)

    # Build agent info
    agent_info: dict[str, Any] = {
        "name": agent_name,
        "version": agent_version,
        "model_name": model_name,
    }
    if extra_agent_fields:
        agent_info["extra"] = extra_agent_fields

    # Final metrics
    final_metrics: dict[str, Any] = {
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_steps": agent_step_count,
    }
    if total_cached_tokens:
        final_metrics["total_cached_tokens"] = total_cached_tokens

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "agent": agent_info,
        "steps": steps,
        "final_metrics": final_metrics,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_parse_arguments(args: Any) -> Any:
    """Return parsed JSON if string, otherwise return as-is."""
    if isinstance(args, str):
        import json

        try:
            return json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return args
    return args


def _attach_tool_results(
    step: dict[str, Any],
    tool_results: list[dict[str, Any]],
) -> None:
    """Attach tool results as observation.results on an agent step."""
    results = []
    for tr in tool_results:
        results.append(
            {
                "source_call_id": tr.get("tool_call_id", ""),
                "content": tr.get("content", ""),
            }
        )
    if results:
        step.setdefault("observation", {})["results"] = results
