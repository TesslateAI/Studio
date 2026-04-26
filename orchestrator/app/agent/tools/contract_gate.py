"""
ContractGate — Phase 2 Wave-1 tool-call enforcement layer.

Wedged into ``ToolRegistry.execute`` between the API-key scope check and the
edit-mode (ask/plan) check. When an agent invocation belongs to an
:class:`AutomationRun` (the dispatcher plumbs ``contract`` into the worker
context), every tool call is gated against the :class:`AutomationDefinition`
contract before dispatch.

Three checks, in order:

1. **Allow-list** — ``contract.allowed_tools`` (and, when wired in by callers,
   ``allowed_mcps`` / ``allowed_skills``). A ``None`` value means "inherit
   project defaults" (no enforcement); an empty list means "deny all".
2. **Compute-tier** — a tool with ``Tool.compute_tier > contract.max_compute_tier``
   is rejected (escalate). Most tools are Tier 0; only tools that need
   per-project pods declare a higher tier.
3. **Tool-spend estimate** — :func:`billing_dispatcher.estimate` returns a
   per-call USD estimate for the tool. If it exceeds the remaining run budget
   (``max_spend_per_run_usd - current_spend_usd``) the call is rejected.
   Tools declaring ``delegates_to_model=True`` skip this check; their spend
   is already captured by the LiteLLM key (avoids the double-count).

The gate is **decision-only**. It returns a frozen ``ContractGateDecision``;
the caller (``ToolRegistry.execute``) decides what to do next:

* ``on_breach='pause_for_approval'`` (default, Phase 2 Wave-1): the registry
  raises :class:`ContractBreachException`; the dispatcher catches it and
  registers an approval card via the existing ``PendingUserInputManager``.
* ``on_breach='hard_stop'`` and ``on_breach='extend_once'`` are wired in a
  follow-up wave (Phase 2 Wave-1B).

Backward compatibility: chat-session invocations have no ``contract`` in
context. The registry skips the gate entirely in that case — existing chat
flows are unaffected.

Plan reference: ``§"ContractGate — tool-call gating + LiteLLM-key budget"``
and ``§"Permission contract"`` in
``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import Tool

logger = logging.getLogger(__name__)


__all__ = [
    "ContractGate",
    "ContractGateDecision",
    "ContractBreachException",
    "BreachKind",
]


# Decision-only sentinel strings — kept narrow so callers can branch with a
# string equality check and downstream telemetry stays cardinality-bounded.
class BreachKind:
    TOOL_DISALLOWED = "tool_disallowed"
    MCP_DISALLOWED = "mcp_disallowed"
    SKILL_DISALLOWED = "skill_disallowed"
    TIER_TOO_HIGH = "tier_too_high"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass(frozen=True)
class ContractGateDecision:
    """Verdict from a single ContractGate.check() call.

    Attributes:
        allowed: True iff the tool call may proceed.
        reason: Human-readable explanation when ``allowed=False``. Surfaced
            verbatim in the approval card and run history.
        estimate_usd: The per-call spend estimate computed during the check.
            Always non-negative; ``Decimal(0)`` when the gate skipped the
            estimate (delegates_to_model=True or no estimator available).
        breach_kind: One of :class:`BreachKind` when ``allowed=False``;
            ``None`` when the call is allowed. Used by the caller to drive
            the on_breach branch (escalate / hard_stop / extend_once).
    """

    allowed: bool
    reason: str | None = None
    estimate_usd: Decimal = field(default_factory=lambda: Decimal(0))
    breach_kind: str | None = None


class ContractBreachException(Exception):
    """Raised by ``ToolRegistry.execute`` when ContractGate denies a call.

    Carries the original :class:`ContractGateDecision` so the dispatcher /
    ``PendingUserInputManager`` can render an approval card without
    re-running the checks.
    """

    def __init__(self, decision: ContractGateDecision, *, tool_name: str):
        self.decision = decision
        self.tool_name = tool_name
        super().__init__(
            f"ContractGate denied tool '{tool_name}': "
            f"{decision.breach_kind} — {decision.reason}"
        )


class ContractGate:
    """Enforces an :class:`AutomationDefinition` contract against tool calls.

    One instance per agent run. Cheap to construct — the gate holds no
    persistent state and is safe to allocate inside the registry hot path.
    """

    def __init__(self, contract: dict[str, Any], run_context: dict[str, Any]):
        """
        Args:
            contract: The JSONB ``AutomationDefinition.contract`` value.
                Required keys (``allowed_tools``, ``max_compute_tier``) are
                expected to have been validated by ``dispatcher._validate_contract``
                before reaching here.
            run_context: Per-run state read by the gate. Honored keys:

                * ``automation_run_id``: AutomationRun UUID (for logging).
                * ``automation_id``: AutomationDefinition UUID (for logging).
                * ``current_spend_usd``: ``Decimal`` of cumulative run spend.
                  Defaults to ``Decimal(0)`` if absent.
        """
        self.contract = contract or {}
        self.run_context = run_context or {}
        self._automation_run_id = self.run_context.get("automation_run_id")
        self._automation_id = self.run_context.get("automation_id")

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def check(
        self,
        *,
        tool_name: str,
        tool_call_params: dict[str, Any],
        tool: "Tool",
    ) -> ContractGateDecision:
        """Evaluate the contract against a single tool call.

        Order is deterministic: allow-list → compute-tier → spend estimate.
        The first failing check short-circuits — we want the most specific
        reason in the approval card, not the most expensive one.
        """
        # 1. Allow-list check (tool, MCP, skill).
        denial = self._check_allow_lists(
            tool_name=tool_name, tool_call_params=tool_call_params, tool=tool
        )
        if denial is not None:
            return denial

        # 2. Compute-tier check.
        denial = self._check_compute_tier(tool_name=tool_name, tool=tool)
        if denial is not None:
            return denial

        # 3. Tool-spend estimate (skipped for tools that delegate to a model).
        denial = await self._check_spend_estimate(
            tool_name=tool_name,
            tool_call_params=tool_call_params,
            tool=tool,
        )
        if denial is not None:
            return denial

        return ContractGateDecision(allowed=True)

    # ------------------------------------------------------------------
    # Per-check helpers (kept private; one reason per method)
    # ------------------------------------------------------------------

    def _check_allow_lists(
        self,
        *,
        tool_name: str,
        tool_call_params: dict[str, Any],
        tool: "Tool",
    ) -> ContractGateDecision | None:
        """Allow-list checks for tool, MCP server, and skill bundle.

        ``None`` value on any list means "inherit project defaults" — no
        enforcement. An empty ``[]`` means "deny everything in this category"
        (explicitly different from absent). Any extra MCP / skill names
        passed as parameters by future tool wrappers are checked against
        ``allowed_mcps`` / ``allowed_skills`` respectively.
        """
        allowed_tools = self.contract.get("allowed_tools")
        if allowed_tools is not None and tool_name not in allowed_tools:
            return ContractGateDecision(
                allowed=False,
                reason=f"tool '{tool_name}' not in contract.allowed_tools",
                breach_kind=BreachKind.TOOL_DISALLOWED,
            )

        # MCP allow-list (for tools whose params name an MCP server).
        # ``mcp_name`` / ``server`` are the conventional param keys —
        # ``invoke_app_action`` and the future ``mcp_call`` tool both pass
        # one of them.
        allowed_mcps = self.contract.get("allowed_mcps")
        if allowed_mcps is not None:
            mcp_name = tool_call_params.get("mcp_name") or tool_call_params.get("server")
            if mcp_name is not None and mcp_name not in allowed_mcps:
                return ContractGateDecision(
                    allowed=False,
                    reason=(
                        f"MCP server '{mcp_name}' not in contract.allowed_mcps "
                        f"(via tool '{tool_name}')"
                    ),
                    breach_kind=BreachKind.MCP_DISALLOWED,
                )

        # Skill allow-list (for ``load_skill`` and similar wrappers).
        allowed_skills = self.contract.get("allowed_skills")
        if allowed_skills is not None:
            skill_name = tool_call_params.get("skill_name") or tool_call_params.get("skill")
            if skill_name is not None and skill_name not in allowed_skills:
                return ContractGateDecision(
                    allowed=False,
                    reason=(
                        f"skill '{skill_name}' not in contract.allowed_skills "
                        f"(via tool '{tool_name}')"
                    ),
                    breach_kind=BreachKind.SKILL_DISALLOWED,
                )

        return None

    def _check_compute_tier(
        self, *, tool_name: str, tool: "Tool"
    ) -> ContractGateDecision | None:
        """Reject tools that demand a higher compute tier than the contract allows.

        Most tools default to Tier 0 (control-plane only). Tools that need a
        per-project pod declare ``compute_tier=1`` or ``2`` on their
        :class:`Tool` definition. ``contract.max_compute_tier`` is the cap.
        """
        max_tier_raw = self.contract.get("max_compute_tier", 0)
        try:
            max_tier = int(max_tier_raw)
        except (TypeError, ValueError):
            # Defensive: dispatcher already validated the schema, but never
            # crash the agent if a bad contract slipped through.
            logger.warning(
                "[ContractGate] non-integer max_compute_tier=%r in contract; treating as 0",
                max_tier_raw,
            )
            max_tier = 0

        tool_required_tier = int(getattr(tool, "compute_tier", 0) or 0)
        if tool_required_tier > max_tier:
            return ContractGateDecision(
                allowed=False,
                reason=(
                    f"tool '{tool_name}' requires compute tier {tool_required_tier} "
                    f"but contract.max_compute_tier={max_tier}"
                ),
                breach_kind=BreachKind.TIER_TOO_HIGH,
            )
        return None

    async def _check_spend_estimate(
        self,
        *,
        tool_name: str,
        tool_call_params: dict[str, Any],
        tool: "Tool",
    ) -> ContractGateDecision | None:
        """Estimate the spend for this call and compare against remaining budget.

        Tools declaring ``delegates_to_model=True`` skip the estimate — their
        spend is captured by the LiteLLM key, and double-counting it here
        would inflate ``automation_runs.spend_usd`` for every model call.
        """
        if getattr(tool, "delegates_to_model", False):
            return None

        max_per_run = self.contract.get("max_spend_per_run_usd")
        if max_per_run is None:
            # No per-run cap — only the daily cap (enforced elsewhere) applies.
            return None

        try:
            max_per_run_d = Decimal(str(max_per_run))
        except (TypeError, ValueError):
            logger.warning(
                "[ContractGate] non-numeric max_spend_per_run_usd=%r; skipping estimate",
                max_per_run,
            )
            return None

        current = self.run_context.get("current_spend_usd", Decimal(0))
        if not isinstance(current, Decimal):
            try:
                current = Decimal(str(current))
            except (TypeError, ValueError):
                current = Decimal(0)

        remaining = max_per_run_d - current

        # Resolve the estimator lazily — keeps the gate importable in
        # contexts where billing_dispatcher's heavy deps aren't loaded.
        estimate = await self._estimate_tool_spend(tool_name, tool_call_params)

        if estimate > remaining:
            return ContractGateDecision(
                allowed=False,
                reason=(
                    f"tool '{tool_name}' spend estimate ${estimate} exceeds "
                    f"remaining run budget ${remaining}"
                ),
                estimate_usd=estimate,
                breach_kind=BreachKind.BUDGET_EXCEEDED,
            )
        return None

    async def _estimate_tool_spend(
        self, tool_name: str, tool_call_params: dict[str, Any]
    ) -> Decimal:
        """Call into the billing dispatcher's estimator with hard fallbacks.

        We never let an estimator failure take down the agent — a missing or
        broken estimator returns ``Decimal(0)`` (no spend assumed) rather
        than raising. The defaults table is the safety net for tools that
        the estimator doesn't know about yet.
        """
        try:
            from ...services.apps import billing_dispatcher

            estimator = getattr(billing_dispatcher, "estimate", None)
            if estimator is None:
                return _DEFAULT_TOOL_ESTIMATES.get(tool_name, Decimal(0))

            value = await estimator(tool_name, tool_call_params)
            if value is None:
                return Decimal(0)
            return Decimal(str(value))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "[ContractGate] estimator failure for %s (%s); falling back",
                tool_name,
                exc,
            )
            return _DEFAULT_TOOL_ESTIMATES.get(tool_name, Decimal(0))


# Per-tool fallback estimates used when ``billing_dispatcher.estimate`` is not
# available. Conservative, slightly above observed per-call costs so the gate
# escalates *before* the LiteLLM key 429s. Real estimators can supersede.
_DEFAULT_TOOL_ESTIMATES: dict[str, Decimal] = {
    "web_fetch": Decimal("0.001"),
    "web_search": Decimal("0.005"),
    "invoke_app_action": Decimal("0.01"),
    "mcp_call": Decimal("0.01"),
}
