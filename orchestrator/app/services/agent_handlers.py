"""
Shared handler registry for background tasks.

Both ARQ (via `app.worker.WorkerSettings.functions`) and `LocalTaskQueue`
resolve handlers by name through this registry. The actual handler bodies
live in `app.worker` — we only re-export the references so we don't fork
implementations.

Agent execution is routed by ``settings.agent_runner``:
  - ``"bridge"`` (default): submodule runner via
    ``services/tesslate_agent_bridge.TesslateAgentBridge``.
  - ``"inline"``: in-tree ``app/agent/`` runner.
Both paths are called from ``worker.execute_agent_task`` via
``_create_agent_runner()``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..worker import execute_agent_task, refresh_templates, send_webhook_callback

TASK_HANDLERS: dict[str, Callable[..., Any]] = {
    "execute_agent_task": execute_agent_task,
    "send_webhook_callback": send_webhook_callback,
    "refresh_templates": refresh_templates,
}


__all__ = ["TASK_HANDLERS"]
