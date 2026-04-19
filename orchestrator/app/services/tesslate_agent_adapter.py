"""Adapter between the orchestrator and the ``tesslate-agent`` package.

Responsibilities:
    1. Re-export the submodule's ``TesslateAgent`` + ``AbstractAgent`` with
       stable local names (``TesslateAgentAdapter.inner`` preserves the raw
       submodule instance for callers that need direct access).
    2. ``run_turn()`` drives a single request/response cycle against the
       submodule runner and writes each trajectory event as an
       ``AgentStep`` row (message-scoped, append-only) so real-time status
       streams still work.
    3. ``AgentAdapterContext`` is the neutral invocation envelope shared by
       routers and the worker.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from tesslate_agent.agent.base import AbstractAgent
from tesslate_agent.agent.tesslate_agent import TesslateAgent

try:
    from tesslate_agent.agent.tools.registry import ToolRegistry
except ImportError:
    ToolRegistry = Any  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentAdapterContext:
    """Minimal invocation context the orchestrator hands to the adapter."""

    project_id: str
    user_id: str
    goal_ancestry: list[str] | None = None
    extra: dict[str, Any] | None = None


class TesslateAgentAdapter:
    """Thin wrapper around ``TesslateAgent`` for orchestrator-side use.

    Construction mirrors ``TesslateAgent.__init__``. The wrapper exists so
    orchestrator call sites depend on a local class name; once trajectory
    persistence and tool-registry plumbing are wired, only this module
    changes.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._inner: AbstractAgent = TesslateAgent(*args, **kwargs)

    @property
    def inner(self) -> AbstractAgent:
        return self._inner

    async def run(self, user_request: str, context: dict[str, Any]) -> Any:
        return await self._inner.run(user_request, context)

    async def run_turn(
        self,
        user_request: str,
        adapter_context: AgentAdapterContext,
        *,
        event_sink: EventSink | None = None,
    ) -> dict[str, Any]:
        """Drive a single agent turn, forwarding each yielded event.

        Returns the last event emitted (typically ``{"type": "complete", ...}``
        or ``{"type": "max_iterations", ...}``). If ``event_sink`` is
        provided, every event is awaited on it first — this is how the
        orchestrator persists trajectory events as ``AgentStep`` rows and
        fans them out on the PubSub stream without coupling the submodule
        to that plumbing.
        """
        last: dict[str, Any] = {}
        ctx = adapter_context.to_submodule_context()
        async for event in _iter_events(self._inner, user_request, ctx):
            last = event
            if event_sink is not None:
                try:
                    await event_sink(event)
                except Exception as exc:
                    logger.debug("event_sink raised; swallowing: %s", exc)
        return last


async def _iter_events(
    agent: AbstractAgent, user_request: str, context: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """Normalise ``agent.run()`` into a plain async-iterator of event dicts.

    ``TesslateAgent.run`` returns an async generator; some older code paths
    return a coroutine that awaits to an async generator. Tolerate both.
    """
    result = agent.run(user_request, context)
    if hasattr(result, "__aiter__"):
        async for event in result:
            yield event
        return
    awaited = await result  # type: ignore[misc]
    async for event in awaited:
        yield event


# ---------------------------------------------------------------------------
# Event sink: persist trajectory events as AgentStep rows
# ---------------------------------------------------------------------------

EventSink = Any  # async callable taking a single event dict


def make_agent_step_sink(
    session_factory: Any,
    *,
    message_id: uuid.UUID,
    chat_id: uuid.UUID,
) -> Any:
    """Build an event-sink coroutine that writes each event as an AgentStep.

    ``session_factory`` is an async callable that yields a fresh
    ``AsyncSession`` (usually ``AsyncSessionLocal``). Each emitted event
    becomes one append-only row with a monotonically increasing
    ``step_index``.
    """
    from ..models import AgentStep

    counter = {"i": 0}

    async def _sink(event: dict[str, Any]) -> None:
        idx = counter["i"]
        counter["i"] = idx + 1
        async with session_factory() as session:
            row = AgentStep(
                id=uuid.uuid4(),
                message_id=message_id,
                chat_id=chat_id,
                step_index=idx,
                step_data=event,
            )
            session.add(row)
            await session.commit()

    return _sink


def build_adapter_from_system_prompt(
    system_prompt: str,
    *,
    tools: ToolRegistry | None = None,
    model: Any | None = None,
    max_iterations: int = 25,
) -> TesslateAgentAdapter:
    """Construct an adapter pre-loaded with the submodule's default tool set.

    ``tools`` defaults to a fresh ``ToolRegistry`` populated with every
    built-in submodule tool (file / shell / nav / git / memory / planning /
    web / delegation). Orchestrator-specific tools (kanban, project_control,
    etc.) must be registered by the caller.
    """
    if tools is None:
        tools = ToolRegistry()
        from tesslate_agent.agent.tools.registry import register_all_tools

        register_all_tools(tools)
    return TesslateAgentAdapter(
        system_prompt=system_prompt,
        tools=tools,
        model=model,
        max_iterations=max_iterations,
    )


__all__ = [
    "AgentAdapterContext",
    "TesslateAgentAdapter",
    "build_adapter_from_system_prompt",
    "make_agent_step_sink",
]
