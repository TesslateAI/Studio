"""LiteLLM key lifecycle: pure state machine.

No DB, no network, no asyncio. Operates on the in-memory ledger row shape.
Keeps transition legality, tier rules, budget invariants, and nesting depth
as pure functions so they can be unit-tested exhaustively.

The orchestrator module (services/litellm_keys.py) wires these primitives
to the database and the LiteLLM HTTP client.

See docs/proposed/plans/tesslate-apps.md §6 for the full state machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final, Protocol


class KeyTier(StrEnum):
    SESSION = "session"
    INVOCATION = "invocation"
    NESTED = "nested"


class KeyState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SETTLING = "settling"
    SETTLED = "settled"
    REAPED = "reaped"
    REVOKED = "revoked"
    FAILED = "failed"


TERMINAL_STATES: Final[frozenset[KeyState]] = frozenset(
    {KeyState.SETTLED, KeyState.REVOKED, KeyState.FAILED}
)


# Every transition is explicit. `failed` is reachable from every non-terminal
# state (mint failures, LiteLLM upstream loss, etc.). Unlisted transitions are
# illegal and raise KeyTransitionError.
LEGAL_TRANSITIONS: Final[dict[KeyState, frozenset[KeyState]]] = {
    KeyState.PENDING: frozenset({KeyState.ACTIVE, KeyState.FAILED}),
    KeyState.ACTIVE: frozenset(
        {KeyState.SETTLING, KeyState.REAPED, KeyState.REVOKED, KeyState.FAILED}
    ),
    KeyState.REAPED: frozenset({KeyState.SETTLING, KeyState.FAILED}),
    KeyState.SETTLING: frozenset({KeyState.SETTLED, KeyState.FAILED}),
    KeyState.SETTLED: frozenset(),
    KeyState.REVOKED: frozenset(),
    KeyState.FAILED: frozenset(),
}


class KeyTransitionError(ValueError):
    """Raised when a requested state transition is illegal."""


class KeyMintError(ValueError):
    """Raised when a mint request violates tier, depth, or budget invariants."""


class LedgerLike(Protocol):
    """Structural type of rows we operate on — avoids importing SQLAlchemy here."""

    key_id: str
    parent_key_id: str | None
    tier: str
    state: str
    budget_usd: Decimal
    spent_usd: Decimal


DEFAULT_NESTED_MAX_DEPTH: Final[int] = 3


def assert_legal_transition(from_state: str | KeyState, to_state: str | KeyState) -> None:
    src = KeyState(from_state) if isinstance(from_state, str) else from_state
    dst = KeyState(to_state) if isinstance(to_state, str) else to_state
    allowed = LEGAL_TRANSITIONS.get(src, frozenset())
    if dst not in allowed:
        raise KeyTransitionError(
            f"illegal transition {src.value} -> {dst.value}; "
            f"allowed from {src.value}: {sorted(s.value for s in allowed)}"
        )


def is_terminal(state: str | KeyState) -> bool:
    return (KeyState(state) if isinstance(state, str) else state) in TERMINAL_STATES


def remaining_budget(row: LedgerLike) -> Decimal:
    return Decimal(row.budget_usd) - Decimal(row.spent_usd)


@dataclass(frozen=True)
class NestedMintRequest:
    parent: LedgerLike
    requested_budget_usd: Decimal
    ancestor_chain_len: int = 1  # 1 = immediate parent; increases as we walk up


def assert_can_mint_nested(
    req: NestedMintRequest,
    *,
    max_depth: int = DEFAULT_NESTED_MAX_DEPTH,
) -> None:
    """Validate a nested key mint against parent state + depth + budget.

    Depth starts at 1 for an immediate child and increases as we walk up the
    parent chain. `max_depth` is the deepest nested key we permit (not counting
    the root session/invocation).
    """
    if req.ancestor_chain_len > max_depth:
        raise KeyMintError(f"nested depth {req.ancestor_chain_len} exceeds max {max_depth}")

    parent_state = KeyState(req.parent.state)
    if parent_state != KeyState.ACTIVE:
        raise KeyMintError(f"parent key must be active, is {parent_state.value}")

    if req.requested_budget_usd <= Decimal("0"):
        raise KeyMintError(f"requested budget must be positive, got {req.requested_budget_usd}")

    available = remaining_budget(req.parent)
    if req.requested_budget_usd > available:
        raise KeyMintError(
            f"requested nested budget {req.requested_budget_usd} exceeds "
            f"parent remaining {available}"
        )


def assert_tier_for_mint(tier: str | KeyTier, *, has_parent: bool) -> None:
    """Tier/parent consistency check. Top-level mints must be session or
    invocation; nested mints must have a parent."""
    t = KeyTier(tier) if isinstance(tier, str) else tier
    if has_parent and t != KeyTier.NESTED:
        raise KeyMintError(
            f"parent provided but tier is {t.value}; nested keys require tier='nested'"
        )
    if (not has_parent) and t == KeyTier.NESTED:
        raise KeyMintError("tier='nested' requires parent_key_id")
