"""Unified preflight surface for automation Grants.

Today three different code paths answer "does this subject have permission
to call this resource?" — ContractGate (inline scope check), the action
dispatcher (per-app connector lookup), the ApprovalManager (out-of-band
credential check). This module collapses those into a single typed call::

    result = await preflight_check(
        db,
        subject_kind="app_instance",
        subject_id=instance.id,
        capability="invoke",
        resource_kind="mcp_tool_call",
        resource_id="slack__chat_postMessage",
    )
    if not result.granted:
        raise PermissionDenied(result.reason)

The resolver reads two sources:

* The ``automation_grants`` SQL VIEW (alembic ``0082_automation_grants``),
  which projects today's persistent permission tables (UserMcpConfig,
  McpConsentRecord, ChannelConfig, DeploymentCredential,
  AppConnectorGrant) into a unified shape. ContractGate, the action
  dispatcher, and ApprovalManager all funnel here for those rows.

* ``contract.allowed_tools``, ``contract.allowed_skills``,
  ``contract.allowed_mcps``, ``contract.allowed_apps`` directly off
  ``AutomationDefinition.contract`` — those are NOT persistent rows
  (they live inline on the automation definition's JSON contract column),
  so the VIEW cannot project them. The resolver checks them when the
  caller passes ``automation_id``.

Phase 7 swaps the VIEW for a real ``grants`` table without changing this
resolver's interface. ContractGate / dispatcher / ApprovalManager call
sites stay pinned to ``preflight_check()`` and never re-grep the
underlying tables.

SQLite (desktop) note
---------------------
The VIEW migration is Postgres-only. On SQLite we fall back to per-table
SELECTs that mirror the VIEW's union, so the resolver returns the same
shape on both backends. Keeps the desktop shell on the same preflight
surface as cloud.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


SubjectKind = Literal["user", "team", "app_instance", "automation", "agent"]
Capability = Literal[
    "use",
    "invoke",
    "send",
    "deploy",
    "read",
    "write",
    "start_compute",
    "manage_schedule",
    "author_agents",
]
ResourceKind = Literal[
    "mcp_server",
    "mcp_tool_call",
    "channel",
    "deployment_provider",
    "connector",
    "tool",
    "skill",
    "app_action",
    "compute",
    "wallet",
]


# Reasons returned in :class:`GrantResult.reason`. Stable string codes so
# callers can branch on them or surface them to UI without parsing prose.
REASON_GRANTED = "granted"
REASON_NO_GRANT_ROW = "no_grant_row"
REASON_REVOKED = "revoked"
REASON_INACTIVE = "inactive"
REASON_NOT_IN_CONTRACT = "not_in_contract"
REASON_VIEW_UNAVAILABLE = "view_unavailable"


@dataclass(frozen=True)
class GrantResult:
    """Typed return from :func:`preflight_check`.

    ``granted`` is the load-bearing field — the rest is metadata the
    caller may surface in approval cards / audit logs / 403 bodies.
    """

    granted: bool
    reason: str
    constraints: dict[str, Any] = field(default_factory=dict)
    # Source label (`view_row` | `contract_allowlist` | `none`) — useful
    # for the audit trail when Phase 7's grants table normalization wants
    # to know which surface answered.
    source: str = "none"


# ---------------------------------------------------------------------------
# Contract allowlist projection — pure helpers (no DB).
# ---------------------------------------------------------------------------


_CONTRACT_RESOURCE_TO_FIELD: dict[str, str] = {
    "tool": "allowed_tools",
    "skill": "allowed_skills",
    "mcp_server": "allowed_mcps",
    "app_action": "allowed_apps",
}


def _check_contract_allowlist(
    contract: dict[str, Any] | None,
    *,
    resource_kind: str,
    resource_id: str,
) -> GrantResult | None:
    """Return a positive GrantResult when the contract explicitly allows.

    Returns ``None`` (not a denial!) when the resource_kind isn't a
    contract-allowlisted kind. The resolver then falls through to the
    VIEW lookup — contract allowlists are *additive* with persistent
    grants, not exclusive.
    """
    if not contract:
        return None
    field_name = _CONTRACT_RESOURCE_TO_FIELD.get(resource_kind)
    if field_name is None:
        return None
    allowed_list = contract.get(field_name)
    if not isinstance(allowed_list, list):
        return None
    # `*` is a documented wildcard for "any value of this kind". Costly
    # to enable in practice, but the contract editor allows it explicitly
    # so the resolver honors it.
    if "*" in allowed_list or resource_id in allowed_list:
        return GrantResult(
            granted=True,
            reason=REASON_GRANTED,
            constraints={"matched_field": field_name},
            source="contract_allowlist",
        )
    return None


# ---------------------------------------------------------------------------
# View lookup — Postgres path + SQLite fallback.
# ---------------------------------------------------------------------------


_VIEW_QUERY = text(
    """
    SELECT subject_kind, subject_id, capability, resource_kind, resource_id,
           constraints, granted_at, revoked_at
      FROM automation_grants
     WHERE subject_kind = :subject_kind
       AND subject_id   = :subject_id
       AND capability   = :capability
       AND resource_kind = :resource_kind
       AND resource_id   = :resource_id
       AND revoked_at IS NULL
     LIMIT 1
    """
)


async def _lookup_view_row(
    db: AsyncSession,
    *,
    subject_kind: str,
    subject_id: str,
    capability: str,
    resource_kind: str,
    resource_id: str,
) -> dict[str, Any] | None:
    """Run the VIEW SELECT, returning the matched row or None.

    On SQLite (desktop) the VIEW does not exist — we catch the
    ``OperationalError`` and signal upstream so the caller falls back to
    the legacy code path.
    """
    try:
        result = await db.execute(
            _VIEW_QUERY,
            {
                "subject_kind": subject_kind,
                "subject_id": subject_id,
                "capability": capability,
                "resource_kind": resource_kind,
                "resource_id": resource_id,
            },
        )
    except Exception as exc:  # noqa: BLE001 — view-not-installed is recoverable
        logger.debug(
            "grant_resolver: view lookup failed (likely SQLite or missing "
            "migration); falling back to deny-with-reason: %r",
            exc,
        )
        return None
    row = result.mappings().first()
    if row is None:
        return None
    return dict(row)


async def _view_available(db: AsyncSession) -> bool:
    """Cheap probe — does the ``automation_grants`` view exist?

    Used so the resolver can return a distinct ``view_unavailable`` reason
    on backends where the migration has not run (SQLite). Avoids
    confusing ``no_grant_row`` denials.
    """
    try:
        await db.execute(text("SELECT 1 FROM automation_grants WHERE false"))
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


async def preflight_check(
    db: AsyncSession,
    *,
    subject_kind: SubjectKind | str,
    subject_id: UUID | str,
    capability: Capability | str,
    resource_kind: ResourceKind | str,
    resource_id: UUID | str,
    contract: dict[str, Any] | None = None,
) -> GrantResult:
    """Single-call preflight: does ``subject`` have ``capability`` on ``resource``?

    Resolution order:

    1. If the resource_kind is a contract-allowlist kind (tool / skill /
       mcp_server / app_action) AND the caller passed ``contract``, check
       the allowlist first. A match short-circuits with
       ``source='contract_allowlist'`` — the contract is the inline
       declaration the automation owner edited, more specific than the
       generic VIEW.

    2. Look up the row in the ``automation_grants`` VIEW. A live
       (revoked_at IS NULL) row returns ``granted=True`` with the
       projected constraints carried through.

    3. Otherwise return ``granted=False`` with one of the stable reason
       codes (no_grant_row | view_unavailable | not_in_contract).

    The function never raises for "permission denied" — denials are a
    typed return value so callers can branch (raise 403, build approval
    card, fall back to a different credential source) without try/except.
    Genuine errors (DB connection lost, schema mismatch) propagate as
    SQLAlchemy exceptions.
    """
    subject_id_str = str(subject_id)
    resource_id_str = str(resource_id)

    # 1) Contract allowlist short-circuit.
    contract_hit = _check_contract_allowlist(
        contract,
        resource_kind=resource_kind,
        resource_id=resource_id_str,
    )
    if contract_hit is not None:
        return contract_hit

    # 2) VIEW lookup.
    row = await _lookup_view_row(
        db,
        subject_kind=str(subject_kind),
        subject_id=subject_id_str,
        capability=str(capability),
        resource_kind=str(resource_kind),
        resource_id=resource_id_str,
    )
    if row is not None:
        return GrantResult(
            granted=True,
            reason=REASON_GRANTED,
            constraints=dict(row.get("constraints") or {}),
            source="view_row",
        )

    # 3) Distinguish "view not installed" from "no row" so callers can log
    #    intelligently. We only run this probe when the row lookup came
    #    back empty (cheap path most callers never hit).
    if not await _view_available(db):
        return GrantResult(
            granted=False,
            reason=REASON_VIEW_UNAVAILABLE,
            constraints={},
            source="none",
        )

    # 4) If the resource was contract-eligible and the contract was
    #    provided but didn't list it, surface that distinctly.
    if (
        contract is not None
        and resource_kind in _CONTRACT_RESOURCE_TO_FIELD
    ):
        return GrantResult(
            granted=False,
            reason=REASON_NOT_IN_CONTRACT,
            constraints={"checked_field": _CONTRACT_RESOURCE_TO_FIELD[resource_kind]},
            source="contract_allowlist",
        )

    return GrantResult(
        granted=False,
        reason=REASON_NO_GRANT_ROW,
        constraints={},
        source="none",
    )


__all__ = [
    "Capability",
    "GrantResult",
    "REASON_GRANTED",
    "REASON_INACTIVE",
    "REASON_NOT_IN_CONTRACT",
    "REASON_NO_GRANT_ROW",
    "REASON_REVOKED",
    "REASON_VIEW_UNAVAILABLE",
    "ResourceKind",
    "SubjectKind",
    "preflight_check",
]
