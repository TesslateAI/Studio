"""Adapter surface between the orchestrator and the ``tesslate-agent`` package.

The orchestrator owns a legacy in-tree runner under ``app/agent/``; the
``tesslate-agent`` submodule at ``packages/tesslate-agent`` is the future
target. This module is the single seam we will swap behind — routers and
services should import ``TesslateAgentBridge`` from here rather than the
submodule directly, so the cutover later is a one-file change.

Nothing here replaces the in-tree runner today. The bridge currently just
imports the submodule's public entry points and re-exports them with a
stable local name. Trajectory persistence, tool registration, and the
enqueue-site cutover land in a later sweep.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tesslate_agent.agent.base import AbstractAgent
from tesslate_agent.agent.tesslate_agent import TesslateAgent


@dataclass(frozen=True)
class BridgeContext:
    """Minimal invocation context the orchestrator hands to the bridge."""

    project_id: str
    user_id: str
    goal_ancestry: list[str] | None = None
    extra: dict[str, Any] | None = None


class TesslateAgentBridge:
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
        bridge_context: BridgeContext,
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
        ctx = bridge_context.to_submodule_context()
        async for event in _iter_events(self._inner, user_request, ctx):
            last = event
            if event_sink is not None:
                try:
                    await event_sink(event)
                except Exception as exc:
                    logger.debug("event_sink raised; swallowing: %s", exc)
        return last

__all__ = ["BridgeContext", "TesslateAgentBridge"]
