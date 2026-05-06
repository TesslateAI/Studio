"""Hosted-agent runtime: mint LiteLLM keys for invocations of
manifest-declared hosted agents (`compute.hosted_agents[*]`).

Pure key-minting + manifest-resolution layer. Uses INVOCATION tier (or
NESTED if `parent_session_id` points at an active session key). Actual
agent execution happens elsewhere (stream_agent) using the returned
api_key as its LLM credential.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppInstance, AppVersion, LiteLLMKeyLedger, MarketplaceApp
from .. import litellm_keys
from .key_lifecycle import KeyState, KeyTier
from .runtime import ApiKeyExtractionError, _extract_api_key  # noqa: F401  (re-export for callers)

logger = logging.getLogger(__name__)

_UNRUNNABLE_APP_STATES = frozenset({"yanked", "deprecated"})
_RUNNABLE_INSTANCE_STATE = "installed"
_DEFAULT_HOSTED_BUDGET_USD = Decimal("0.25")


class HostedAgentError(Exception):
    """Base class for hosted-agent runtime errors."""


class AgentNotDeclaredError(HostedAgentError):
    """Raised when the manifest does not declare the requested agent id."""


class AppInstanceNotRunnableError(HostedAgentError):
    """Raised when the AppInstance / MarketplaceApp is not in a runnable state."""


@dataclass(frozen=True)
class HostedAgentInvocationHandle:
    invocation_id: UUID
    app_instance_id: UUID
    agent_id: str
    litellm_key_id: str
    api_key: str
    model: str | None
    system_prompt_ref: str
    tools_ref: list[str]
    mcps_ref: list[str]
    budget_usd: Decimal
    ttl_seconds: int


async def _load_instance_with_version(
    db: AsyncSession, app_instance_id: UUID
) -> tuple[AppInstance, MarketplaceApp, AppVersion]:
    row = (
        await db.execute(
            select(AppInstance, MarketplaceApp, AppVersion)
            .join(MarketplaceApp, MarketplaceApp.id == AppInstance.app_id)
            .join(AppVersion, AppVersion.id == AppInstance.app_version_id)
            .where(AppInstance.id == app_instance_id)
        )
    ).one_or_none()
    if row is None:
        raise AppInstanceNotRunnableError(f"app_instance {app_instance_id} not found")
    instance, app, version = row
    if instance.state != _RUNNABLE_INSTANCE_STATE:
        raise AppInstanceNotRunnableError(
            f"app_instance {app_instance_id} state={instance.state!r}"
        )
    if app.state in _UNRUNNABLE_APP_STATES:
        raise AppInstanceNotRunnableError(f"app {app.id} state={app.state!r} not runnable")
    return instance, app, version


def _find_hosted_agent_spec(manifest_json: dict[str, Any] | None, agent_id: str) -> dict[str, Any]:
    manifest = manifest_json or {}
    compute = manifest.get("compute") or {}
    for spec in compute.get("hosted_agents") or []:
        if isinstance(spec, dict) and spec.get("id") == agent_id:
            return spec
    raise AgentNotDeclaredError(f"hosted agent {agent_id!r} not declared in manifest")


def _resolve_budget(caller_budget: Decimal | None, spec: dict[str, Any]) -> Decimal:
    if caller_budget is not None:
        return Decimal(caller_budget)
    # Spec-derived default: scale off max_tokens if present (rough heuristic).
    max_tokens = spec.get("max_tokens")
    if isinstance(max_tokens, int) and max_tokens > 0:
        # 4 USD per 1M tokens as a conservative ceiling.
        derived = Decimal(max_tokens) * Decimal("0.000004")
        if derived > 0:
            return derived
    return _DEFAULT_HOSTED_BUDGET_USD


async def _find_parent_session_key(db: AsyncSession, session_id: UUID) -> LiteLLMKeyLedger:
    row = (
        await db.execute(
            select(LiteLLMKeyLedger).where(
                LiteLLMKeyLedger.session_id == session_id,
                LiteLLMKeyLedger.tier == KeyTier.SESSION.value,
                LiteLLMKeyLedger.state == KeyState.ACTIVE.value,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppInstanceNotRunnableError(
            f"no active session key for parent_session_id={session_id}"
        )
    return row


async def begin_hosted_invocation(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
    agent_id: str,
    installer_user_id: UUID,
    delegate,
    parent_session_id: UUID | None = None,
    budget_usd: Decimal | None = None,
    ttl_seconds: int = 300,
) -> HostedAgentInvocationHandle:
    """Mint a key for a hosted-agent invocation.

    Uses NESTED tier when `parent_session_id` is provided (and an active
    session key exists for it), otherwise INVOCATION tier.
    """
    instance, app, version = await _load_instance_with_version(db, app_instance_id)
    spec = _find_hosted_agent_spec(version.manifest_json, agent_id)
    effective_budget = _resolve_budget(budget_usd, spec)

    invocation_id = uuid4()
    parent_key_id: str | None = None
    tier = KeyTier.INVOCATION
    if parent_session_id is not None:
        parent = await _find_parent_session_key(db, parent_session_id)
        parent_key_id = parent.key_id
        tier = KeyTier.NESTED

    result = await litellm_keys.mint_with_secret(
        db,
        delegate=delegate,
        tier=tier,
        user_id=installer_user_id,
        budget_usd=effective_budget,
        session_id=invocation_id,
        app_instance_id=instance.id,
        parent_key_id=parent_key_id,
        ttl_seconds=ttl_seconds,
        meta={
            "app_id": str(app.id),
            "hosted_agent_id": agent_id,
            "invocation_id": str(invocation_id),
        },
    )
    if not result.api_key:
        raise ApiKeyExtractionError(
            f"LiteLLM mint returned empty api_key for key_id={result.ledger.key_id!r}"
        )
    logger.info(
        "hosted_agent.begin app_instance=%s agent=%s tier=%s key=%s budget=%s",
        instance.id,
        agent_id,
        tier.value,
        result.ledger.key_id,
        effective_budget,
    )
    return HostedAgentInvocationHandle(
        invocation_id=invocation_id,
        app_instance_id=instance.id,
        agent_id=agent_id,
        litellm_key_id=result.ledger.key_id,
        api_key=result.api_key,
        model=spec.get("model_pref"),
        system_prompt_ref=spec.get("system_prompt_ref", ""),
        tools_ref=list(spec.get("tools_ref") or []),
        mcps_ref=list(spec.get("mcps_ref") or []),
        budget_usd=effective_budget,
        ttl_seconds=ttl_seconds,
    )


async def end_hosted_invocation(
    db: AsyncSession,
    *,
    invocation_id: UUID,
    litellm_key_id: str,
    delegate,
    outcome: Literal["complete", "cancelled", "errored"] = "complete",
) -> None:
    """Settle the invocation key (begin+finalize). Idempotent."""
    row = (
        await db.execute(select(LiteLLMKeyLedger).where(LiteLLMKeyLedger.key_id == litellm_key_id))
    ).scalar_one_or_none()
    if row is None:
        logger.warning("hosted_agent.end: key not found key=%s", litellm_key_id)
        return
    if KeyState(row.state) in {KeyState.SETTLED, KeyState.REVOKED, KeyState.FAILED}:
        return
    reason = f"hosted_invocation_{outcome}"
    await litellm_keys.begin_settlement(db, delegate=delegate, key_id=litellm_key_id, reason=reason)
    await litellm_keys.finalize_settlement(db, key_id=litellm_key_id)
    logger.info(
        "hosted_agent.end invocation=%s key=%s outcome=%s",
        invocation_id,
        litellm_key_id,
        outcome,
    )


async def list_declared_agents(
    db: AsyncSession,
    *,
    app_instance_id: UUID,
) -> list[dict]:
    """Return the flat list of hosted_agents declared in the manifest.

    Returns an empty list if the instance does not exist, the manifest is
    missing, or no hosted_agents are declared.
    """
    row = (
        await db.execute(
            select(AppVersion)
            .join(AppInstance, AppInstance.app_version_id == AppVersion.id)
            .where(AppInstance.id == app_instance_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return []
    manifest = row.manifest_json or {}
    compute = manifest.get("compute") or {}
    agents = compute.get("hosted_agents") or []
    return [dict(a) for a in agents if isinstance(a, dict)]
