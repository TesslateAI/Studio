"""Intent-producing idle reaper for ``app_runtime_deployments`` (Phase 4).

Replaces the direct-K8s call path in :mod:`runtime_reaper` with the
controller intent pattern: the reaper scans deployments and, for each
that's been idle past its threshold AND has no active runs, opens a
short TXN that verifies the controller lease and INSERTs a
``controller_intents(kind='scale_to_zero')`` row. The reconciler picks
it up on its next tick.

The legacy module :mod:`runtime_reaper` remains a thin compat shim that
delegates here so existing call sites (gateway runner loop, tests)
continue to function during the gateway → controller migration.

Active-run check
----------------
Same join as :mod:`runtime_reaper`:

    AppRuntimeDeployment ⟵ AppInstance.runtime_deployment_id ⟵
    InvocationSubject.app_instance_id → InvocationSubject.automation_run_id
    → AutomationRun

Any non-terminal :class:`AutomationRun` referencing one of the
deployment's installs blocks reaping.

Mode neutrality
---------------
The reaper itself produces intents in any mode — only the reconciler
behaviour differs (K8s patches scale, Docker stops the container,
desktop logs only). This satisfies the CLAUDE.md "don't fork Docker
and K8s logic" rule by routing both through the same intent contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import (
    AppInstance,
    AppRuntimeDeployment,
    AutomationRun,
    InvocationSubject,
)
from ..automations.intents import LeaseLost, record_intent_with_lease

logger = logging.getLogger(__name__)


_NON_TERMINAL_RUN_STATUSES = frozenset(
    {
        "queued",
        "preflight",
        "running",
        "waiting_approval",
        "waiting_credentials",
        "waiting_credits",
    }
)

_DEFAULT_IDLE_TIMEOUT_SECONDS = 600
_DEFAULT_LEASE_NAME = "controller"


@dataclass(frozen=True)
class ReapIntentResult:
    """Counts returned from one reap-intent pass."""

    examined: int
    skipped_active: int
    intents_recorded: int
    intents_failed: int
    not_idle: int


async def _select_candidates(db: AsyncSession) -> list[AppRuntimeDeployment]:
    stmt = select(AppRuntimeDeployment).where(
        AppRuntimeDeployment.min_replicas == 0,
        AppRuntimeDeployment.desired_replicas > 0,
        AppRuntimeDeployment.scaled_to_zero_at.is_(None),
    )
    return list((await db.execute(stmt)).scalars().all())


async def _has_active_run(db: AsyncSession, deployment_id: UUID) -> bool:
    stmt = (
        select(AutomationRun.id)
        .join(
            InvocationSubject,
            InvocationSubject.automation_run_id == AutomationRun.id,
        )
        .join(
            AppInstance,
            AppInstance.id == InvocationSubject.app_instance_id,
        )
        .where(
            AppInstance.runtime_deployment_id == deployment_id,
            AutomationRun.status.in_(_NON_TERMINAL_RUN_STATUSES),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).first() is not None


def _idle_timeout_for(
    deployment: AppRuntimeDeployment, default_seconds: int
) -> int:
    if deployment.idle_timeout_seconds and deployment.idle_timeout_seconds > 0:
        return int(deployment.idle_timeout_seconds)
    return default_seconds


def _is_idle(
    deployment: AppRuntimeDeployment,
    *,
    now: datetime,
    default_idle_seconds: int,
) -> bool:
    last = deployment.last_activity_at
    timeout = _idle_timeout_for(deployment, default_idle_seconds)
    if last is None:
        # No activity ever recorded → treat as idle past timeout.
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (now - last) > timedelta(seconds=timeout)


async def reap_idle_runtimes(
    db: AsyncSession,
    *,
    our_term: int,
    lease_name: str = _DEFAULT_LEASE_NAME,
    now: datetime | None = None,
    default_idle_timeout_seconds: int = _DEFAULT_IDLE_TIMEOUT_SECONDS,
) -> ReapIntentResult:
    """One pass: produce ``scale_to_zero`` intents for idle deployments.

    The session ``db`` MUST be on the same connection as the caller's
    lease-verifying TXN — :func:`record_intent_with_lease` opens the
    verify INSIDE the call, so each intent gets its own TXN that locks
    the lease row.
    """
    if now is None:
        now = datetime.now(UTC)

    candidates = await _select_candidates(db)
    examined = len(candidates)

    if examined == 0:
        return ReapIntentResult(
            examined=0,
            skipped_active=0,
            intents_recorded=0,
            intents_failed=0,
            not_idle=0,
        )

    skipped_active = 0
    intents_recorded = 0
    intents_failed = 0
    not_idle = 0

    for deployment in candidates:
        if await _has_active_run(db, deployment.id):
            skipped_active += 1
            continue

        if not _is_idle(
            deployment,
            now=now,
            default_idle_seconds=default_idle_timeout_seconds,
        ):
            not_idle += 1
            continue

        target_ref: dict[str, Any] = {
            "runtime_deployment_id": str(deployment.id),
            "namespace": deployment.namespace,
            "deployment": deployment.primary_container_id,
            # docker mode uses container_id from the same field; reconciler
            # picks based on its mode.
            "container_id": deployment.primary_container_id,
        }

        try:
            await record_intent_with_lease(
                db,
                name=lease_name,
                our_term=our_term,
                kind="scale_to_zero",
                target_ref=target_ref,
            )
            await db.commit()
            intents_recorded += 1
        except LeaseLost:
            # No write committed in record_intent_with_lease before the
            # term check fails, so no rollback is required (and calling
            # rollback on a session whose only activity was a read can
            # raise MissingGreenlet on async SQLite). Let the exception
            # propagate to the supervisor cleanly.
            logger.warning(
                "[REAPER] lease lost mid-pass; aborting at deployment=%s",
                deployment.id,
            )
            raise
        except Exception:
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                logger.debug(
                    "[REAPER] rollback after intent-record failure also failed",
                    exc_info=True,
                )
            logger.exception(
                "[REAPER] failed to record intent for deployment=%s",
                deployment.id,
            )
            intents_failed += 1

    if intents_recorded:
        logger.info(
            "[REAPER] examined=%d skipped_active=%d intents=%d failed=%d not_idle=%d",
            examined,
            skipped_active,
            intents_recorded,
            intents_failed,
            not_idle,
        )

    return ReapIntentResult(
        examined=examined,
        skipped_active=skipped_active,
        intents_recorded=intents_recorded,
        intents_failed=intents_failed,
        not_idle=not_idle,
    )


__all__ = ["ReapIntentResult", "reap_idle_runtimes"]
