"""StepHandler protocol + registry.

A handler is registered by importing its module: each handler module
calls :func:`register_handler` at import time. The engine asks
:func:`get_handler` for the right class given an
``AutomationAction.action_type`` value.

The registry is a process-global dict because handler classes are
stateless. Tests can use :func:`reset_registry` to wipe it between
cases when needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ....models_automations import (
    AutomationAction,
    AutomationDefinition,
    AutomationRun,
)


@dataclass
class StepResult:
    """Outcome of one step's execution.

    ``output`` is the dict the legacy dispatcher passes to
    ``_deliver_and_finalize``. The engine returns the FINAL step's
    output to the dispatcher so delivery and run-finalization stay
    unchanged for multi-step workflows.

    ``async_handoff`` is true when the underlying executor enqueued an
    ARQ task and the actual completion lands later via the worker
    (e.g. tier-0 ``agent.run``). Phase A refuses async handoffs in
    multi-step workflows and surfaces a typed error; Phase B wires the
    worker callback so async steps can advance the engine.

    ``next_ordinal`` is set by control-flow steps (Phase F ``branch``)
    to redirect the engine. When None, the engine advances to the
    next ordinal in the linear sweep.
    """

    output: dict[str, Any]
    async_handoff: bool = False
    spend_usd: Decimal | None = None
    artifact_ids: list[str] = field(default_factory=list)
    next_ordinal: int | None = None


@dataclass
class StepContext:
    """Inputs the engine hands to a handler for one step.

    ``prior_step_outputs`` lets a step read what earlier steps produced
    without each handler re-querying the database. Phase A keeps this a
    plain list of dicts (the engine appends each step's output as it
    completes); Phase F may expand to named references.
    """

    db: AsyncSession
    run: AutomationRun
    automation: AutomationDefinition
    action: AutomationAction
    event_payload: dict[str, Any]
    budget_allocation: Any | None
    prior_step_outputs: list[dict[str, Any]] = field(default_factory=list)


class StepHandler(Protocol):
    """One step kind's executor.

    ``kind`` is the ``AutomationAction.action_type`` value this handler
    serves (e.g. ``"agent.run"``, ``"app.invoke"``). Concrete classes
    declare it as a ``ClassVar`` so the registry can map it without
    instantiating.
    """

    kind: ClassVar[str]

    async def execute(self, ctx: StepContext) -> StepResult: ...


_REGISTRY: dict[str, type[StepHandler]] = {}


def register_handler(handler_cls: type[StepHandler]) -> type[StepHandler]:
    """Decorator: register a handler class by its ``kind`` attribute."""
    kind = getattr(handler_cls, "kind", None)
    if not kind:
        raise ValueError(f"{handler_cls.__name__} must declare a non-empty 'kind' ClassVar")
    _REGISTRY[kind] = handler_cls
    return handler_cls


def get_handler(kind: str) -> type[StepHandler]:
    """Look up a registered handler. Raises :class:`KeyError` if missing."""
    try:
        return _REGISTRY[kind]
    except KeyError as exc:
        known = sorted(_REGISTRY.keys())
        raise KeyError(f"no handler registered for step kind {kind!r}; known: {known}") from exc


def known_kinds() -> list[str]:
    """Snapshot of registered kinds — useful for error messages and tests."""
    return sorted(_REGISTRY.keys())


def reset_registry() -> None:
    """Test hook: wipe the registry. Production code never calls this."""
    _REGISTRY.clear()


# A read-only view used by callers who want to introspect.
class _RegistryView:
    def __contains__(self, kind: str) -> bool:
        return kind in _REGISTRY

    def __iter__(self):
        return iter(_REGISTRY)

    def __len__(self) -> int:
        return len(_REGISTRY)

    def get(self, kind: str) -> type[StepHandler] | None:
        return _REGISTRY.get(kind)


registry = _RegistryView()
