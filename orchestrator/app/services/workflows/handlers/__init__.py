"""Step handler registry.

A :class:`StepHandler` is the polymorphic execution unit for one
step kind. The engine looks up a handler by ``action.action_type`` and
delegates execution to it. Adding a new step kind is a one-file change:
write a class, register it, and the engine picks it up.

Phase A registers the four kinds the existing dispatcher already
supports (``agent.run``, ``app.invoke``, ``gateway.send``) plus stubs
for ``approval.gate`` and ``deliver`` which Phase D fills in. Phase F
adds ``branch``, ``parallel``, and ``sub_workflow``.
"""

from __future__ import annotations

# Eagerly import handlers so importing this package registers them.
from . import (
    agent_turn,  # noqa: F401
    app_action,  # noqa: F401
    gateway_send,  # noqa: F401
)
from .base import StepContext, StepHandler, StepResult, registry

__all__ = ["StepContext", "StepHandler", "StepResult", "registry"]
