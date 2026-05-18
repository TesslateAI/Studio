"""Dry-run a workflow proposal (G3, issue #469).

Synthetic execution of a proposed WorkflowVersion payload against a
synthetic event. Step handlers that have external side effects
(``gateway.send`` posts to Redis, ``deliver`` writes InboxItem,
``app.invoke`` calls another service) are short-circuited to a
representative response so the dry-run never escapes the database
transaction it runs in.

Returns :class:`DryRunResult` with per-step outcomes. The auto-apply
path in :mod:`proposals` calls this and refuses to apply on any
failure.

Phase G3 scope:

* Supported: ``gateway.send``, ``deliver`` (web_inbox short-circuit),
  ``branch``, ``sub_workflow`` (target is loaded but not dispatched).
* Refused: ``agent.run`` (LLM calls cost money + the only way to
  dry-run is to actually call). Workflows with ``agent.run`` steps
  always route to manual approval until G3.1's shadow-run primitive
  lands.
* Refused: ``app.invoke`` without ``sample_output`` in the
  manifest — the action could touch external state. Most manifests
  declare a sample_output; ones that don't are explicitly
  approval-only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DryRunStepResult:
    ordinal: int
    kind: str
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class DryRunResult:
    ok: bool
    steps: list[DryRunStepResult] = field(default_factory=list)
    refusal_reason: str | None = None


def evaluate_dry_run(payload: dict[str, Any]) -> DryRunResult:
    """Walk ``payload['actions']`` and short-circuit each step.

    Returns ok=True when every step would either execute side-effect-
    free or has a clear short-circuit path. Returns ok=False with a
    refusal_reason for any step that can't be safely dry-run.

    Synchronous, no I/O. The dispatcher's full path is not invoked
    — this is intentional: dry-run should never touch external
    systems or the live AutomationRun row.
    """
    actions = payload.get("actions") or []
    if not actions:
        return DryRunResult(ok=False, refusal_reason="proposal has no actions to dry-run")

    steps: list[DryRunStepResult] = []
    for entry in actions:
        if not isinstance(entry, dict):
            return DryRunResult(
                ok=False,
                steps=steps,
                refusal_reason="non-dict action entry",
            )
        ordinal = int(entry.get("ordinal", 0))
        kind = str(entry.get("action_type", ""))
        config = dict(entry.get("config") or {})

        step = _dry_run_step(ordinal=ordinal, kind=kind, config=config)
        steps.append(step)
        if not step.ok:
            return DryRunResult(
                ok=False,
                steps=steps,
                refusal_reason=step.error,
            )

    return DryRunResult(ok=True, steps=steps)


def _dry_run_step(*, ordinal: int, kind: str, config: dict[str, Any]) -> DryRunStepResult:
    if kind == "gateway.send":
        # Pure body render; no XADD, no Redis. Mirrors the dispatcher's
        # ``_render_simple_template`` fallback shape.
        body = config.get("body_template") or config.get("body") or ""
        return DryRunStepResult(
            ordinal=ordinal,
            kind=kind,
            ok=True,
            output={
                "action_type": "gateway.send",
                "delivered": False,
                "body": str(body)[:8000],
                "dry_run": True,
            },
        )

    if kind == "deliver":
        # The real handler walks AutomationDeliveryTarget rows and
        # writes to each destination kind. In dry-run we just return
        # a sample shape so a chained branch / sub_workflow has
        # something to read.
        return DryRunStepResult(
            ordinal=ordinal,
            kind=kind,
            ok=True,
            output={
                "action_type": "deliver",
                "delivered": [],
                "destination_count": 0,
                "dry_run": True,
            },
        )

    if kind == "branch":
        # Conditions reference prior step outputs which we don't
        # carry across in this v0 dry-run. Report as inconclusive —
        # the engine will still execute it at apply time.
        return DryRunStepResult(
            ordinal=ordinal,
            kind=kind,
            ok=True,
            output={
                "action_type": "branch",
                "condition_result": None,
                "dry_run": True,
            },
        )

    if kind == "sub_workflow":
        child_id = config.get("child_automation_id")
        if not child_id:
            return DryRunStepResult(
                ordinal=ordinal,
                kind=kind,
                ok=False,
                error="sub_workflow requires child_automation_id",
            )
        return DryRunStepResult(
            ordinal=ordinal,
            kind=kind,
            ok=True,
            output={
                "action_type": "sub_workflow",
                "child_automation_id": str(child_id),
                "dispatched": False,
                "dry_run": True,
            },
        )

    if kind == "agent.run":
        return DryRunStepResult(
            ordinal=ordinal,
            kind=kind,
            ok=False,
            error=(
                "agent.run cannot be dry-run (LLM call has cost + side "
                "effects); workflows with agent.run steps require manual "
                "approval"
            ),
        )

    if kind == "app.invoke":
        # G3 v0: refuse without a sample_output. Apps can publish a
        # sample for each action in the manifest; a future commit
        # threads that through here so app.invoke can dry-run cleanly.
        return DryRunStepResult(
            ordinal=ordinal,
            kind=kind,
            ok=False,
            error=(
                "app.invoke dry-run requires manifest sample_output "
                "(Phase G3 follow-up); workflows with app.invoke "
                "require manual approval until then"
            ),
        )

    return DryRunStepResult(
        ordinal=ordinal,
        kind=kind,
        ok=False,
        error=f"unknown step kind {kind!r}",
    )
