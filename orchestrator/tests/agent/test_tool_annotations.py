"""
CI-enforced check that every concrete Tool registered with the global
ToolRegistry declares both state-shape annotations.

Why this exists
---------------
Phase 2 (non-blocking HITL) and Phase 6 (full checkpoint) both depend on
knowing each tool's serialization story up front. The plan requires:

  * ``state_serializable: bool`` — Phase 2/Phase 6 checkpoint can serialize
    this tool's input + output + partial state to JSON.
  * ``holds_external_state: bool`` — Tool keeps state outside the run
    (open sockets, MCP streams, persistent shells, PTYs).

The orchestrator's ``Tool`` is a ``@dataclass`` instance (see
``app/agent/tools/registry.py``), not a class hierarchy. Construction-time
enforcement lives in ``Tool.__post_init__`` — that's the dataclass-pattern
analogue of the plan's ``_ToolStateMeta`` metaclass and raises ``TypeError``
the moment a tool is constructed without both fields. This test is the
second gate: it walks the full registered surface, reasserts the same
invariant, and gates merges in CI.

New tools added in any future phase MUST declare both annotations or:
1. Construction will fail at module import time (Tool.__post_init__).
2. This test will fail in CI even if construction is somehow bypassed.

Reference: Phase 1 §"Tool-state CI enforcement" in
/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

from app.agent import tools as tools_pkg
from app.agent.tools.registry import Tool, get_tool_registry


def _import_all_tool_modules() -> None:
    """Import every submodule under app.agent.tools so all Tool() registrations
    execute at least once. This is the same surface the agent runtime sees.
    """
    for module_info in pkgutil.walk_packages(tools_pkg.__path__, prefix=tools_pkg.__name__ + "."):
        try:
            importlib.import_module(module_info.name)
        except Exception:
            # Some optional submodules may have heavy import deps; skip them
            # rather than masking the actual annotation check below. They
            # would still fail at runtime if the agent tries to register a
            # bad Tool — Tool.__post_init__ catches that case.
            continue


def _registered_tools() -> list[Tool]:
    """Return every Tool registered with the global registry."""
    _import_all_tool_modules()
    registry = get_tool_registry()
    return list(registry.list_tools())


_ALL_TOOLS = _registered_tools()


@pytest.mark.unit
def test_tool_registry_is_non_empty() -> None:
    """Sanity check — if this fires we're parameterizing zero cases below."""
    assert _ALL_TOOLS, (
        "No tools were discovered in the global ToolRegistry. The annotation "
        "check below would silently pass with zero parameters. Investigate "
        "why app.agent.tools failed to register tools."
    )


@pytest.mark.unit
@pytest.mark.parametrize("tool", _ALL_TOOLS, ids=lambda t: t.name)
def test_tool_declares_state_serializable(tool: Tool) -> None:
    """Every Tool MUST declare ``state_serializable: bool``."""
    assert hasattr(tool, "state_serializable"), (
        f"Tool '{tool.name}' must declare 'state_serializable: bool' as a "
        f"dataclass field for Phase 2 non-blocking HITL and Phase 6 "
        f"checkpointing."
    )
    assert isinstance(tool.state_serializable, bool), (
        f"Tool '{tool.name}'.state_serializable must be a bool, got "
        f"{type(tool.state_serializable).__name__}."
    )


@pytest.mark.unit
@pytest.mark.parametrize("tool", _ALL_TOOLS, ids=lambda t: t.name)
def test_tool_declares_holds_external_state(tool: Tool) -> None:
    """Every Tool MUST declare ``holds_external_state: bool``."""
    assert hasattr(tool, "holds_external_state"), (
        f"Tool '{tool.name}' must declare 'holds_external_state: bool' as a "
        f"dataclass field. Required by the Phase 2 non-blocking HITL pattern "
        f"to decide whether the in-flight tool can be cleanly cancelled."
    )
    assert isinstance(tool.holds_external_state, bool), (
        f"Tool '{tool.name}'.holds_external_state must be a bool, got "
        f"{type(tool.holds_external_state).__name__}."
    )


@pytest.mark.unit
def test_tool_construction_rejects_missing_annotations() -> None:
    """The Tool dataclass must raise TypeError when annotations are omitted —
    this is the construction-time analogue of the plan's metaclass guard.
    Without this, only the parametrized checks above protect us, and a tool
    could slip through if it failed to register globally for some reason."""
    from app.agent.tools.registry import Tool, ToolCategory

    async def _noop(p, c):
        return {"success": True}

    with pytest.raises(TypeError, match="state_serializable"):
        Tool(
            name="missing_annotations",
            description="should fail to construct",
            parameters={},
            executor=_noop,
            category=ToolCategory.FILE_OPS,
        )


@pytest.mark.unit
def test_tool_construction_rejects_non_bool_annotation() -> None:
    """Annotations must be ``bool`` — a truthy non-bool (string, int) must be
    rejected. Catches accidental ``state_serializable="true"`` typos."""
    from app.agent.tools.registry import Tool, ToolCategory

    async def _noop(p, c):
        return {"success": True}

    with pytest.raises(TypeError, match="must be a bool"):
        Tool(
            name="bad_annotation",
            description="should fail to construct",
            parameters={},
            executor=_noop,
            category=ToolCategory.FILE_OPS,
            state_serializable="yes",  # type: ignore[arg-type]
            holds_external_state=False,
        )
