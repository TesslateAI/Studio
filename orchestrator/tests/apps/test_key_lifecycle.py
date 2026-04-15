"""Pure state-machine tests for services/apps/key_lifecycle.

No DB, no network. Covers transition legality, tier rules, nested mint
invariants, and budget math. This file is the first-line safety net —
if a transition is missed here, the orchestrator tests stand no chance.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.apps.key_lifecycle import (
    DEFAULT_NESTED_MAX_DEPTH,
    TERMINAL_STATES,
    KeyMintError,
    KeyState,
    KeyTier,
    KeyTransitionError,
    NestedMintRequest,
    assert_can_mint_nested,
    assert_legal_transition,
    assert_tier_for_mint,
    is_terminal,
    remaining_budget,
)


def _active(budget: str = "1.0", spent: str = "0.0"):
    return SimpleNamespace(
        key_id="k",
        parent_key_id=None,
        tier=KeyTier.SESSION.value,
        state=KeyState.ACTIVE.value,
        budget_usd=Decimal(budget),
        spent_usd=Decimal(spent),
    )


# -- transition table -------------------------------------------------------


def test_legal_transitions_happy_path() -> None:
    assert_legal_transition(KeyState.PENDING, KeyState.ACTIVE)
    assert_legal_transition(KeyState.ACTIVE, KeyState.SETTLING)
    assert_legal_transition(KeyState.SETTLING, KeyState.SETTLED)
    assert_legal_transition(KeyState.ACTIVE, KeyState.REAPED)
    assert_legal_transition(KeyState.REAPED, KeyState.SETTLING)
    assert_legal_transition(KeyState.ACTIVE, KeyState.REVOKED)


def test_failure_transitions_allowed_from_all_non_terminal() -> None:
    for st in (KeyState.PENDING, KeyState.ACTIVE, KeyState.REAPED, KeyState.SETTLING):
        assert_legal_transition(st, KeyState.FAILED)


@pytest.mark.parametrize(
    "illegal",
    [
        (KeyState.SETTLED, KeyState.ACTIVE),
        (KeyState.REVOKED, KeyState.ACTIVE),
        (KeyState.FAILED, KeyState.ACTIVE),
        (KeyState.SETTLED, KeyState.SETTLING),
        (KeyState.ACTIVE, KeyState.PENDING),
        (KeyState.ACTIVE, KeyState.SETTLED),  # must go through settling
        (KeyState.PENDING, KeyState.SETTLING),
        (KeyState.REVOKED, KeyState.SETTLED),
    ],
)
def test_illegal_transitions_rejected(illegal) -> None:
    src, dst = illegal
    with pytest.raises(KeyTransitionError):
        assert_legal_transition(src, dst)


def test_transition_accepts_string_values() -> None:
    assert_legal_transition("active", "settling")
    with pytest.raises(KeyTransitionError):
        assert_legal_transition("settled", "active")


def test_terminal_state_set_is_exactly_settled_revoked_failed() -> None:
    assert TERMINAL_STATES == frozenset(
        {KeyState.SETTLED, KeyState.REVOKED, KeyState.FAILED}
    )
    for st in (KeyState.PENDING, KeyState.ACTIVE, KeyState.SETTLING, KeyState.REAPED):
        assert not is_terminal(st)
    for st in TERMINAL_STATES:
        assert is_terminal(st)


# -- tier/parent consistency ------------------------------------------------


def test_tier_session_top_level_ok() -> None:
    assert_tier_for_mint(KeyTier.SESSION, has_parent=False)


def test_tier_invocation_top_level_ok() -> None:
    assert_tier_for_mint(KeyTier.INVOCATION, has_parent=False)


def test_tier_nested_requires_parent() -> None:
    with pytest.raises(KeyMintError):
        assert_tier_for_mint(KeyTier.NESTED, has_parent=False)


def test_parent_without_nested_tier_rejected() -> None:
    with pytest.raises(KeyMintError):
        assert_tier_for_mint(KeyTier.SESSION, has_parent=True)
    with pytest.raises(KeyMintError):
        assert_tier_for_mint(KeyTier.INVOCATION, has_parent=True)


# -- nested mint invariants --------------------------------------------------


def test_nested_mint_ok_under_active_parent() -> None:
    parent = _active(budget="1.00", spent="0.20")
    assert_can_mint_nested(
        NestedMintRequest(parent=parent, requested_budget_usd=Decimal("0.50")),
    )


def test_nested_mint_rejects_non_active_parent() -> None:
    parent = _active()
    parent.state = KeyState.SETTLING.value
    with pytest.raises(KeyMintError, match="parent key must be active"):
        assert_can_mint_nested(
            NestedMintRequest(parent=parent, requested_budget_usd=Decimal("0.10"))
        )


def test_nested_mint_rejects_zero_or_negative_budget() -> None:
    parent = _active()
    with pytest.raises(KeyMintError):
        assert_can_mint_nested(
            NestedMintRequest(parent=parent, requested_budget_usd=Decimal("0"))
        )
    with pytest.raises(KeyMintError):
        assert_can_mint_nested(
            NestedMintRequest(parent=parent, requested_budget_usd=Decimal("-0.01"))
        )


def test_nested_mint_rejects_over_remaining_budget() -> None:
    parent = _active(budget="1.00", spent="0.80")
    # remaining = 0.20; request 0.25 → reject
    with pytest.raises(KeyMintError, match="exceeds parent remaining"):
        assert_can_mint_nested(
            NestedMintRequest(parent=parent, requested_budget_usd=Decimal("0.25"))
        )


def test_nested_mint_at_exactly_remaining_budget_ok() -> None:
    parent = _active(budget="1.00", spent="0.80")
    assert_can_mint_nested(
        NestedMintRequest(parent=parent, requested_budget_usd=Decimal("0.20"))
    )


def test_nested_depth_enforced_default() -> None:
    parent = _active()
    # chain len == max_depth + 1 → reject
    with pytest.raises(KeyMintError, match="exceeds max"):
        assert_can_mint_nested(
            NestedMintRequest(
                parent=parent,
                requested_budget_usd=Decimal("0.10"),
                ancestor_chain_len=DEFAULT_NESTED_MAX_DEPTH + 1,
            )
        )


def test_nested_depth_at_max_accepted() -> None:
    parent = _active()
    assert_can_mint_nested(
        NestedMintRequest(
            parent=parent,
            requested_budget_usd=Decimal("0.10"),
            ancestor_chain_len=DEFAULT_NESTED_MAX_DEPTH,
        )
    )


def test_nested_depth_custom_max_honored() -> None:
    parent = _active()
    with pytest.raises(KeyMintError):
        assert_can_mint_nested(
            NestedMintRequest(
                parent=parent,
                requested_budget_usd=Decimal("0.10"),
                ancestor_chain_len=2,
            ),
            max_depth=1,
        )


# -- budget math -------------------------------------------------------------


def test_remaining_budget_computes_from_budget_minus_spent() -> None:
    row = _active(budget="2.500000", spent="1.125000")
    assert remaining_budget(row) == Decimal("1.375000")


def test_remaining_budget_can_go_zero() -> None:
    row = _active(budget="1.0", spent="1.0")
    assert remaining_budget(row) == Decimal("0")


def test_remaining_budget_negative_is_surfaced() -> None:
    # Not a valid state but if we ever get there we should see it, not clamp.
    row = _active(budget="1.0", spent="1.5")
    assert remaining_budget(row) == Decimal("-0.5")
