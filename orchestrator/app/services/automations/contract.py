"""Contract inheritance validator for parent → child automations.

The agent-builder skill (Phase 5) lets one automation create child
automations attached to draft agents. The child's contract MUST be a
valid restriction of the parent's: it can only carry scopes from the
positive-list, and its per-run / per-day spend caps cannot exceed the
parent's caps and remaining daily budget respectively.

This module is the single entry point for that validation. Callers:

- ``agent.tools.marketplace_ops.attach_schedule.py`` — runs the check at
  attach time so the user sees errors before the row exists.
- ``services.automations.dispatcher`` — re-runs the check at dispatch
  time as defense-in-depth, in case a bypass slipped past the tool layer
  (e.g. a backfill or admin edit).

See ``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
sections "Agent-builder skill — depth-1 cap, positive-list inheritance,
cycle-safe budgets".
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .scopes import (
    filter_to_inheritable,
    reject_non_inheritable,
)


__all__ = [
    "ContractInheritanceError",
    "validate_child_contract",
]


class ContractInheritanceError(ValueError):
    """A child contract violates the inheritance rules.

    Carries a structured ``code`` so callers can branch on the failure
    type without parsing the message:

    - ``"scope_not_inheritable"``: child contains a non-positive-list scope.
    - ``"per_run_cap_exceeded"``: child's per-run cap > parent's per-run cap.
    - ``"daily_cap_exceeded"``: child's daily cap > parent's remaining daily.
    - ``"missing_required_field"``: child is missing a key the validator needs.
    """

    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None):
        self.code = code
        self.detail = detail or {}
        super().__init__(message)


def _coerce_decimal(value: Any) -> Decimal | None:
    """Best-effort Decimal coercion. ``None`` passes through.

    Strings, ints, floats all coerce; anything else raises so we surface
    contract authoring errors loudly rather than silently converting to
    zero.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        return Decimal(str(value))
    raise ContractInheritanceError(
        code="missing_required_field",
        message=f"unexpected USD value type {type(value).__name__!r}",
    )


def _scopes_from_contract(contract: dict[str, Any]) -> set[str]:
    """Return the union of every scope-bearing list on the contract.

    The contract uses several keys to describe what the run may do:
    ``allowed_scopes``, ``allowed_tools``, ``allowed_mcp_scopes``,
    ``allowed_capabilities``. We treat each as a set of dotted scope
    strings for inheritance purposes — everything is checked against the
    positive list uniformly.
    """
    scopes: set[str] = set()
    for key in ("allowed_scopes", "allowed_tools", "allowed_mcp_scopes", "allowed_capabilities"):
        value = contract.get(key)
        if value is None:
            continue
        if not isinstance(value, (list, set, tuple)):
            continue
        for item in value:
            if isinstance(item, str) and item:
                scopes.add(item)
    return scopes


def validate_child_contract(
    parent_contract: dict[str, Any],
    child_contract: dict[str, Any],
    *,
    parent_remaining_daily_usd: Decimal | None = None,
) -> None:
    """Validate ``child_contract`` is a legal restriction of ``parent_contract``.

    Raises :class:`ContractInheritanceError` on the FIRST violation
    found. Returns ``None`` on success.

    Checks performed:

    1.  **Positive-list scopes.** Every scope on the child contract must
        be inheritable per :mod:`app.services.automations.scopes`. The check is strict: a
        single non-inheritable scope on the child is a hard reject (no
        silent stripping at validation time).
    2.  **Per-run spend cap.** ``child.max_spend_per_run_usd`` must be
        ``<=`` ``parent.max_spend_per_run_usd``. A child without a cap
        is invalid when the parent has one (would let the child outrun
        the parent's budget).
    3.  **Daily spend cap.** ``child.max_spend_per_day_usd`` must be
        ``<=`` ``parent_remaining_daily_usd`` when supplied. If the caller
        does not pass ``parent_remaining_daily_usd`` the daily check is
        skipped (used by attach-time validation where the runtime daily
        counter isn't available; the dispatcher re-checks at run time).
    """
    if not isinstance(parent_contract, dict):
        raise ContractInheritanceError(
            code="missing_required_field",
            message="parent_contract must be a dict",
        )
    if not isinstance(child_contract, dict):
        raise ContractInheritanceError(
            code="missing_required_field",
            message="child_contract must be a dict",
        )

    # --- (a) Positive-list scope check -----------------------------------
    child_scopes = _scopes_from_contract(child_contract)
    bad = reject_non_inheritable(child_scopes)
    if bad:
        raise ContractInheritanceError(
            code="scope_not_inheritable",
            message=(
                f"child contract carries non-inheritable scopes: {sorted(bad)}"
            ),
            detail={"offending_scopes": sorted(bad)},
        )

    # Defense in depth: also drop child scopes that fall outside the
    # parent's allow-set even if they're technically inheritable. The
    # child can only restrict, never widen.
    parent_scopes = _scopes_from_contract(parent_contract)
    if parent_scopes:
        parent_inheritable = filter_to_inheritable(parent_scopes)
        widened = child_scopes - parent_inheritable
        if widened:
            raise ContractInheritanceError(
                code="scope_not_inheritable",
                message=(
                    f"child contract widens parent scope set: {sorted(widened)}"
                ),
                detail={"offending_scopes": sorted(widened)},
            )

    # --- (b) Per-run spend cap -------------------------------------------
    parent_per_run = _coerce_decimal(parent_contract.get("max_spend_per_run_usd"))
    child_per_run = _coerce_decimal(child_contract.get("max_spend_per_run_usd"))
    if parent_per_run is not None:
        if child_per_run is None:
            raise ContractInheritanceError(
                code="per_run_cap_exceeded",
                message=(
                    "child contract must set max_spend_per_run_usd when parent has one"
                ),
                detail={"parent_per_run_usd": str(parent_per_run)},
            )
        if child_per_run > parent_per_run:
            raise ContractInheritanceError(
                code="per_run_cap_exceeded",
                message=(
                    f"child max_spend_per_run_usd={child_per_run} exceeds "
                    f"parent {parent_per_run}"
                ),
                detail={
                    "parent_per_run_usd": str(parent_per_run),
                    "child_per_run_usd": str(child_per_run),
                },
            )

    # --- (c) Daily spend cap ---------------------------------------------
    if parent_remaining_daily_usd is not None:
        child_daily = _coerce_decimal(child_contract.get("max_spend_per_day_usd"))
        if child_daily is not None and child_daily > parent_remaining_daily_usd:
            raise ContractInheritanceError(
                code="daily_cap_exceeded",
                message=(
                    f"child max_spend_per_day_usd={child_daily} exceeds parent "
                    f"remaining daily {parent_remaining_daily_usd}"
                ),
                detail={
                    "parent_remaining_daily_usd": str(parent_remaining_daily_usd),
                    "child_daily_usd": str(child_daily),
                },
            )
