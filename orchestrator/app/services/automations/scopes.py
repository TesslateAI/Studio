"""Capability scopes used by automations + the agent-builder skill.

The Phase 5 agent-builder lets one automation create child agents +
attach schedules to them (depth-1 cap). Two safety rules apply:

1.  **Author-grade scopes are NOT inheritable.** A parent run with
    ``marketplace.author`` may create a draft child agent, but the child
    automation it attaches must NOT inherit ``marketplace.author`` —
    otherwise the child could publish itself or spawn yet more agents
    out of band.
2.  **Child contracts may only carry scopes from a positive-list.** The
    parent's allowed_scopes is filtered through
    :func:`filter_to_inheritable` before being applied to the child;
    any scope outside the list is silently dropped on inheritance and
    actively rejected if the parent tries to put it on the child
    contract directly.

The list is intentionally short and conservative. New scopes default
to NON-INHERITABLE; we add them to the positive list explicitly with a
comment pinning the design rationale.

See ``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
sections "Agent-builder skill — depth-1 cap, positive-list inheritance,
cycle-safe budgets" and "UX Surfaces — five surfaces".
"""

from __future__ import annotations

from typing import Final


# ---------------------------------------------------------------------------
# Scope name constants
# ---------------------------------------------------------------------------

# Marketplace authoring — drafts agents/skills/MCP rows; flips
# ``is_published`` is gated separately (UI-only). NON-INHERITABLE: child
# automations must not be able to publish or spawn further agents.
MARKETPLACE_AUTHOR: Final[str] = "marketplace.author"

# Automation authoring — creates AutomationDefinition + triggers + actions.
# NON-INHERITABLE: a child automation should not be able to mint
# grandchildren (depth-1 cap is enforced at the row level via the
# ``depth IN (0, 1)`` CHECK constraint, but defense in depth here too).
AUTOMATIONS_WRITE: Final[str] = "automations.write"


# Inheritable tool-execution scopes. These map to the agent-tools surface
# the child run actually needs to do useful work. Anything outside this
# set is dropped on inheritance and rejected at attach_schedule time.
TOOLS_EXECUTE: Final[str] = "tools.execute"
READ_FILE: Final[str] = "read_file"
WRITE_FILE: Final[str] = "write_file"
BASH_EXEC: Final[str] = "bash_exec"
WEB_FETCH: Final[str] = "web_fetch"
WEB_SEARCH: Final[str] = "web_search"
SEND_MESSAGE: Final[str] = "send_message"
APP_INVOKE: Final[str] = "app.invoke"


# ---------------------------------------------------------------------------
# Inheritance positive-list
# ---------------------------------------------------------------------------

# Concrete scopes a child automation may inherit from its parent.
# MCP scopes are matched separately by prefix (``mcp.*``) so per-server
# scopes like ``mcp.notion.read`` flow without each having to be enumerated.
INHERITABLE_SCOPES_POSITIVE_LIST: Final[frozenset[str]] = frozenset(
    {
        TOOLS_EXECUTE,
        READ_FILE,
        WRITE_FILE,
        BASH_EXEC,
        WEB_FETCH,
        WEB_SEARCH,
        SEND_MESSAGE,
        APP_INVOKE,
    }
)

# Prefix-match rule: any scope starting with one of these is also
# inheritable. Keeps per-MCP scope enumeration out of the static list.
_INHERITABLE_SCOPE_PREFIXES: Final[tuple[str, ...]] = ("mcp.",)


# Scopes explicitly marked NON-inheritable. Used for fast lookup +
# explicit error messages when ``attach_schedule`` is called with a
# child contract carrying one of these. Keeping the negative list
# explicit rather than implicit (everything-not-in-positive-list) lets
# us surface a precise reason in the rejection error.
NON_INHERITABLE_SCOPES: Final[frozenset[str]] = frozenset(
    {
        MARKETPLACE_AUTHOR,
        AUTOMATIONS_WRITE,
    }
)


def is_inheritable(scope: str) -> bool:
    """Return True iff ``scope`` is allowed on a child automation.

    Membership rules:
    - Explicit positive-list match wins.
    - ``mcp.*`` prefix is allowed.
    - Everything else is denied.
    """
    if scope in INHERITABLE_SCOPES_POSITIVE_LIST:
        return True
    return any(scope.startswith(prefix) for prefix in _INHERITABLE_SCOPE_PREFIXES)


def filter_to_inheritable(scopes: set[str]) -> set[str]:
    """Return only the scopes from ``scopes`` that may be passed to a child.

    Intentionally lossy: unknown / explicitly-non-inheritable scopes are
    dropped silently here (the caller is asking for the inheritable
    subset, not validating the full set). Use :func:`is_inheritable` for
    per-scope decisions and :func:`reject_non_inheritable` for the
    explicit "raise if any non-inheritable" check used by
    ``attach_schedule``.
    """
    return {s for s in scopes if is_inheritable(s)}


def reject_non_inheritable(scopes: set[str]) -> set[str]:
    """Return the set of scopes from ``scopes`` that are NOT inheritable.

    Caller raises if non-empty. Used by ``attach_schedule`` to give the
    user a precise list of offending scopes rather than a binary
    "rejected".
    """
    return {s for s in scopes if not is_inheritable(s)}


__all__ = [
    "APP_INVOKE",
    "AUTOMATIONS_WRITE",
    "BASH_EXEC",
    "INHERITABLE_SCOPES_POSITIVE_LIST",
    "MARKETPLACE_AUTHOR",
    "NON_INHERITABLE_SCOPES",
    "READ_FILE",
    "SEND_MESSAGE",
    "TOOLS_EXECUTE",
    "WEB_FETCH",
    "WEB_SEARCH",
    "WRITE_FILE",
    "filter_to_inheritable",
    "is_inheritable",
    "reject_non_inheritable",
]
