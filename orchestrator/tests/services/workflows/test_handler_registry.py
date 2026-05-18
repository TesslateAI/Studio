"""Unit tests for the StepHandler registry (no DB required).

Verifies:

* Importing the handlers package registers the Phase A built-ins.
* :func:`get_handler` returns the right class for a known kind.
* :func:`get_handler` raises a useful KeyError for unknown kinds, and
  the message lists the known kinds (so debugging is fast).
* :func:`register_handler` rejects classes without a ``kind``.
"""

from __future__ import annotations

import pytest


def test_phase_a_handlers_register():
    # Importing the package side-effects in the three Phase A handlers.
    import app.services.workflows.handlers  # noqa: F401
    from app.services.workflows.handlers.base import known_kinds

    kinds = known_kinds()
    assert "agent.run" in kinds
    assert "app.invoke" in kinds
    assert "gateway.send" in kinds


def test_get_handler_returns_class_for_known_kind():
    import app.services.workflows.handlers  # noqa: F401
    from app.services.workflows.handlers.base import get_handler

    cls = get_handler("app.invoke")
    assert cls.kind == "app.invoke"


def test_get_handler_raises_for_unknown_kind():
    import app.services.workflows.handlers  # noqa: F401
    from app.services.workflows.handlers.base import get_handler

    with pytest.raises(KeyError) as exc_info:
        get_handler("does-not-exist")
    msg = str(exc_info.value)
    assert "does-not-exist" in msg
    # The error message mentions known kinds so debugging is one read.
    assert "agent.run" in msg


def test_register_handler_rejects_missing_kind():
    from app.services.workflows.handlers.base import register_handler

    class NoKind:
        async def execute(self, ctx):  # noqa: ARG002 - protocol shape
            return None

    with pytest.raises(ValueError) as exc_info:
        register_handler(NoKind)  # type: ignore[arg-type]
    assert "kind" in str(exc_info.value)
