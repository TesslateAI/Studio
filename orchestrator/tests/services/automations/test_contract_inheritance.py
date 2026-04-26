"""Phase 5 — unit tests for ``services.automations.contract``.

Pure functions; no DB / Redis required. Exercises the three rules the
agent-builder skill relies on:

1.  Positive-list scope filter (``app.auth.scopes`` integration).
2.  Per-run spend cap inheritance.
3.  Daily spend cap inheritance vs. parent's remaining daily.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.auth.scopes import (
    APP_INVOKE,
    AUTOMATIONS_WRITE,
    INHERITABLE_SCOPES_POSITIVE_LIST,
    MARKETPLACE_AUTHOR,
    READ_FILE,
    SEND_MESSAGE,
    WRITE_FILE,
    filter_to_inheritable,
    is_inheritable,
)
from app.services.automations.contract import (
    ContractInheritanceError,
    validate_child_contract,
)


# ---------------------------------------------------------------------------
# Positive-list filter
# ---------------------------------------------------------------------------


class TestPositiveListFilter:
    def test_positive_list_subset_returned_unchanged(self):
        """Pure positive-list inputs survive the filter intact."""
        scopes = {READ_FILE, WRITE_FILE, SEND_MESSAGE}
        assert filter_to_inheritable(scopes) == scopes

    def test_non_inheritable_scopes_are_dropped(self):
        scopes = {MARKETPLACE_AUTHOR, AUTOMATIONS_WRITE, READ_FILE}
        # Only READ_FILE survives.
        assert filter_to_inheritable(scopes) == {READ_FILE}

    def test_mcp_prefix_is_inheritable(self):
        assert is_inheritable("mcp.linear.read")
        assert is_inheritable("mcp.notion.write")
        assert "mcp.linear.read" in filter_to_inheritable(
            {"mcp.linear.read", MARKETPLACE_AUTHOR}
        )

    def test_unknown_scope_is_not_inheritable(self):
        assert not is_inheritable("billing.refund")
        assert filter_to_inheritable({"billing.refund"}) == set()

    def test_app_invoke_present_in_positive_list(self):
        assert APP_INVOKE in INHERITABLE_SCOPES_POSITIVE_LIST


# ---------------------------------------------------------------------------
# Child contract validation — scope inheritance
# ---------------------------------------------------------------------------


class TestScopeInheritance:
    def test_clean_child_passes(self):
        parent = {
            "allowed_scopes": [READ_FILE, WRITE_FILE, MARKETPLACE_AUTHOR],
            "max_spend_per_run_usd": "1.00",
        }
        child = {
            "allowed_scopes": [READ_FILE],
            "max_spend_per_run_usd": "0.50",
        }
        # No exception => pass.
        validate_child_contract(parent, child)

    def test_child_with_non_inheritable_scope_rejected(self):
        parent = {
            "allowed_scopes": [READ_FILE, MARKETPLACE_AUTHOR],
            "max_spend_per_run_usd": "1.00",
        }
        child = {
            "allowed_scopes": [READ_FILE, MARKETPLACE_AUTHOR],
            "max_spend_per_run_usd": "0.50",
        }
        with pytest.raises(ContractInheritanceError) as exc_info:
            validate_child_contract(parent, child)
        assert exc_info.value.code == "scope_not_inheritable"
        assert MARKETPLACE_AUTHOR in exc_info.value.detail["offending_scopes"]

    def test_child_widening_parent_scope_set_rejected(self):
        """A child cannot grant itself a scope the parent didn't have."""
        parent = {
            "allowed_scopes": [READ_FILE],
            "max_spend_per_run_usd": "1.00",
        }
        child = {
            # WRITE_FILE is in the positive list, but the parent never
            # had it — child can't widen.
            "allowed_scopes": [READ_FILE, WRITE_FILE],
            "max_spend_per_run_usd": "0.50",
        }
        with pytest.raises(ContractInheritanceError) as exc_info:
            validate_child_contract(parent, child)
        assert exc_info.value.code == "scope_not_inheritable"


# ---------------------------------------------------------------------------
# Budget cap inheritance
# ---------------------------------------------------------------------------


class TestBudgetCapInheritance:
    def test_per_run_cap_equal_to_parent_passes(self):
        parent = {"max_spend_per_run_usd": "1.00"}
        child = {"max_spend_per_run_usd": "1.00"}
        validate_child_contract(parent, child)

    def test_per_run_cap_above_parent_rejected(self):
        parent = {"max_spend_per_run_usd": "1.00"}
        child = {"max_spend_per_run_usd": "1.01"}
        with pytest.raises(ContractInheritanceError) as exc_info:
            validate_child_contract(parent, child)
        assert exc_info.value.code == "per_run_cap_exceeded"

    def test_child_missing_per_run_cap_when_parent_has_one_rejected(self):
        parent = {"max_spend_per_run_usd": "1.00"}
        child = {}
        with pytest.raises(ContractInheritanceError) as exc_info:
            validate_child_contract(parent, child)
        assert exc_info.value.code == "per_run_cap_exceeded"

    def test_no_parent_cap_no_check(self):
        """When parent has no cap, child can carry any cap (or none)."""
        parent = {}
        child = {"max_spend_per_run_usd": "100.00"}
        # Doesn't raise.
        validate_child_contract(parent, child)


class TestDailyBudgetInheritance:
    def test_child_daily_below_remaining_passes(self):
        parent = {"max_spend_per_run_usd": "1.00"}
        child = {
            "max_spend_per_run_usd": "0.50",
            "max_spend_per_day_usd": "5.00",
        }
        validate_child_contract(
            parent, child, parent_remaining_daily_usd=Decimal("10.00")
        )

    def test_child_daily_above_remaining_rejected(self):
        parent = {"max_spend_per_run_usd": "1.00"}
        child = {
            "max_spend_per_run_usd": "0.50",
            "max_spend_per_day_usd": "20.00",
        }
        with pytest.raises(ContractInheritanceError) as exc_info:
            validate_child_contract(
                parent, child, parent_remaining_daily_usd=Decimal("10.00")
            )
        assert exc_info.value.code == "daily_cap_exceeded"
        assert exc_info.value.detail["parent_remaining_daily_usd"] == "10.00"

    def test_remaining_not_supplied_skips_daily_check(self):
        parent = {"max_spend_per_run_usd": "1.00"}
        child = {
            "max_spend_per_run_usd": "0.50",
            "max_spend_per_day_usd": "999999.00",
        }
        # No parent_remaining_daily_usd passed -> daily check skipped.
        validate_child_contract(parent, child)

    def test_child_with_no_daily_cap_passes(self):
        parent = {"max_spend_per_run_usd": "1.00"}
        child = {"max_spend_per_run_usd": "0.50"}
        validate_child_contract(
            parent, child, parent_remaining_daily_usd=Decimal("0.01")
        )
