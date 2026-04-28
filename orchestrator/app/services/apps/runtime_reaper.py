"""Idle reaper for ``app_runtime_deployments`` (legacy Phase 4 path).

.. note::

   **Superseded by :mod:`app.services.apps.idle_reaper`.** The new
   reaper produces ``controller_intents(kind='scale_to_zero')`` rows
   instead of patching K8s directly, so the controller plane owns
   every mutation under one TOCTOU-safe contract.

   This module is kept intact for backwards compatibility with the
   gateway runner's reaper loop (``services/gateway/runner.py``) until
   the dedicated ``automations-controller`` Deployment is wired in. New
   call sites should use :func:`app.services.apps.idle_reaper.reap_idle_runtimes`.

The reaper acts on :class:`AppRuntimeDeployment` rows — NOT on
:class:`AppInstance` — so a shared-singleton runtime backing N installs is
reaped exactly once per pass instead of N times. PVCs, namespaces and
Secrets are preserved; only the pod ``replicas`` count drops to zero.

Active-run check
----------------
There is no direct FK from :class:`AutomationRun` to
:class:`AppInstance`. The supported join goes through
:class:`InvocationSubject` (Phase 2), which carries both
``automation_run_id`` and ``app_instance_id``. For Phase 4 we treat any
non-terminal :class:`AutomationRun` whose subject points at an
:class:`AppInstance` backed by the deployment as "active" — the reaper
skips that deployment entirely.

Mode neutrality
---------------
Scale-to-zero is K8s-specific in Phase 4. Docker mode is a no-op (the
``docker-compose`` model has no "scale to 0 with state preservation"
verb that would round-trip cleanly through this path); the deployment
is examined but skipped. Desktop is identical to docker.
"""

from __future__ import annotations

import asyncio
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

logger = logging.getLogger(__name__)


# Run statuses that mean "the runtime might still be doing work for this
# row." See plan §"Reaper logic" for the canonical list. ``paused`` and
# ``failed_preflight`` are intentionally treated as terminal-ish for
# reaping purposes — they don't represent live pod work.
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
_GRACE_POLL_INTERVAL_SECONDS = 5
_GRACE_DEADLINE_SECONDS = 60


@dataclass(frozen=True)
class ReapResult:
    """Counters returned by one reap pass.

    Attributes
    ----------
    examined:
        Number of eligible candidate deployments inspected.
    skipped_active:
        Deployments left alone because at least one non-terminal
        :class:`AutomationRun` references one of their installs.
    reaped:
        Deployments scaled to zero gracefully (SIGTERM only).
    timeout_killed:
        Deployments where the post-scale grace window expired and at
        least one run remained non-terminal — pods were force-deleted
        and the offending runs were marked
        ``paused_reason='reaped_after_timeout'``.
    """

    examined: int
    skipped_active: int
    reaped: int
    timeout_killed: int


# ---------------------------------------------------------------------------
# Internal helpers — kept as small, individually testable units.
# ---------------------------------------------------------------------------


async def _select_candidates(db: AsyncSession) -> list[AppRuntimeDeployment]:
    """Return deployments eligible to scale to zero.

    A deployment is eligible iff it is currently running pods
    (``desired_replicas > 0``) AND its scaling policy permits zero
    (``min_replicas == 0``). ``per_invocation`` rows have
    ``min_replicas=max_replicas=0`` so they're naturally excluded.
    """
    stmt = select(AppRuntimeDeployment).where(
        AppRuntimeDeployment.min_replicas == 0,
        AppRuntimeDeployment.desired_replicas > 0,
    )
    return list((await db.execute(stmt)).scalars().all())


async def _active_runs_for_deployment(
    db: AsyncSession, deployment_id: UUID
) -> list[AutomationRun]:
    """Find non-terminal AutomationRun rows that reference this deployment.

    The join goes through :class:`InvocationSubject`:

        AppRuntimeDeployment ⟵ AppInstance.runtime_deployment_id ⟵
        InvocationSubject.app_instance_id → InvocationSubject.automation_run_id
        → AutomationRun

    Both joins must use ``app_instance_id`` because :class:`AutomationRun`
    has no direct FK to :class:`AppInstance` (or to the runtime row).
    """
    stmt = (
        select(AutomationRun)
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
    )
    return list((await db.execute(stmt)).scalars().all())


def _compute_last_activity(
    deployment: AppRuntimeDeployment,
    candidate_runs: list[AutomationRun],
) -> datetime | None:
    """Pick the freshest activity timestamp across deployment + active runs.

    ``candidate_runs`` here is the *broader* set used for liveness — even
    terminal runs contribute their ``heartbeat_at`` to "we did something
    recently". The caller filters separately for the skip-when-active
    check.
    """
    candidates: list[datetime] = []
    if deployment.last_activity_at is not None:
        candidates.append(deployment.last_activity_at)
    for run in candidate_runs:
        if run.heartbeat_at is not None:
            candidates.append(run.heartbeat_at)
    if not candidates:
        return None
    return max(candidates)


def _idle_timeout_for(
    deployment: AppRuntimeDeployment, default_seconds: int
) -> int:
    """Per-deployment idle timeout with a sane fallback."""
    if deployment.idle_timeout_seconds and deployment.idle_timeout_seconds > 0:
        return int(deployment.idle_timeout_seconds)
    return default_seconds


async def _scale_deployment_to_zero(
    *,
    namespace: str,
    deployment_name: str,
    k8s_client: Any,
) -> None:
    """Patch the K8s Deployment's ``spec.replicas`` to 0 (sends SIGTERM).

    Uses ``apps_v1.patch_namespaced_deployment_scale`` directly so we
    don't depend on :class:`KubernetesClient`'s naming generators —
    the AppRuntimeDeployment row already carries the resolved namespace
    and deployment name.
    """
    body = {"spec": {"replicas": 0}}
    await asyncio.to_thread(
        k8s_client.apps_v1.patch_namespaced_deployment_scale,
        name=deployment_name,
        namespace=namespace,
        body=body,
    )


async def _force_delete_deployment_pods(
    *,
    namespace: str,
    deployment_name: str,
    k8s_client: Any,
) -> None:
    """SIGKILL any pods still backing the deployment after the grace window.

    Listed by the conventional ``app=<deployment_name>`` label selector
    used by :class:`KubernetesClient`. Best-effort: 404s are swallowed
    (the pod may have terminated between list and delete).
    """
    try:
        pods = await asyncio.to_thread(
            k8s_client.core_v1.list_namespaced_pod,
            namespace=namespace,
            label_selector=f"app={deployment_name}",
        )
    except Exception:
        logger.exception(
            "runtime_reaper: failed to list pods for force-delete ns=%s deploy=%s",
            namespace,
            deployment_name,
        )
        return

    for pod in getattr(pods, "items", []) or []:
        pod_name = pod.metadata.name
        try:
            await asyncio.to_thread(
                k8s_client.core_v1.delete_namespaced_pod,
                name=pod_name,
                namespace=namespace,
                grace_period_seconds=0,
            )
        except Exception:
            logger.warning(
                "runtime_reaper: force-delete pod failed ns=%s pod=%s",
                namespace,
                pod_name,
                exc_info=True,
            )


async def _wait_for_runs_terminal(
    db: AsyncSession,
    deployment_id: UUID,
    *,
    poll_interval_seconds: int = _GRACE_POLL_INTERVAL_SECONDS,
    deadline_seconds: int = _GRACE_DEADLINE_SECONDS,
) -> list[AutomationRun]:
    """Poll for non-terminal runs flipping to a terminal status.

    Returns the list of runs that were STILL non-terminal when the
    deadline expired. An empty list means graceful termination
    completed.
    """
    deadline = asyncio.get_event_loop().time() + deadline_seconds
    while True:
        # Refresh from the DB so worker-side commits become visible.
        await db.commit()
        active = await _active_runs_for_deployment(db, deployment_id)
        if not active:
            return []
        if asyncio.get_event_loop().time() >= deadline:
            return active
        await asyncio.sleep(poll_interval_seconds)


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


async def reap_idle_runtimes(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    default_idle_timeout_seconds: int = _DEFAULT_IDLE_TIMEOUT_SECONDS,
    k8s_client: Any | None = None,
    deployment_mode: str | None = None,
) -> ReapResult:
    """One reap pass over :class:`AppRuntimeDeployment` rows.

    Parameters
    ----------
    db:
        Session to use for all reads and writes. The caller is
        responsible for the surrounding transaction lifetime.
    now:
        Optional override for the current time, used by tests so the
        idle-timeout math is deterministic.
    default_idle_timeout_seconds:
        Fallback when an :class:`AppRuntimeDeployment` row carries
        ``idle_timeout_seconds = 0`` (defensive — the column has a
        non-zero server default).
    k8s_client:
        Optional pre-resolved K8s client (mainly for tests).
        Production callers leave this as ``None`` and the reaper
        resolves the singleton via
        :func:`get_k8s_client` only when running in K8s mode AND
        there is at least one row to act on.
    deployment_mode:
        Optional override for the active deployment mode. ``None``
        reads from :func:`get_settings`. When the mode is anything
        other than ``"kubernetes"``, the reaper logs a debug
        message and returns without scaling — Phase 4 only ships
        K8s reconciliation.
    """
    if now is None:
        now = datetime.now(UTC)

    # Lazy-import config so the module is import-safe without env vars.
    if deployment_mode is None:
        from ...config import get_settings

        deployment_mode = get_settings().deployment_mode

    candidates = await _select_candidates(db)
    examined = len(candidates)

    if examined == 0:
        return ReapResult(examined=0, skipped_active=0, reaped=0, timeout_killed=0)

    if deployment_mode.lower() != "kubernetes":
        # Phase 4 simplification: docker / desktop scale-to-zero is a no-op.
        # Surface it loudly enough to debug, quietly enough not to spam.
        logger.debug(
            "runtime_reaper: skipping reap (deployment_mode=%s, examined=%d)",
            deployment_mode,
            examined,
        )
        return ReapResult(
            examined=examined,
            skipped_active=0,
            reaped=0,
            timeout_killed=0,
        )

    # Resolve the K8s client lazily — only after we know we have work AND
    # we're in K8s mode. Keeps tests on docker mode from importing the
    # K8s SDK.
    if k8s_client is None:
        from ..orchestration.kubernetes.client import get_k8s_client

        k8s_client = get_k8s_client()

    skipped_active = 0
    reaped = 0
    timeout_killed = 0

    for deployment in candidates:
        active_runs = await _active_runs_for_deployment(db, deployment.id)
        if active_runs:
            skipped_active += 1
            logger.debug(
                "runtime_reaper: skip active deployment=%s active_runs=%d",
                deployment.id,
                len(active_runs),
            )
            continue

        last_activity = _compute_last_activity(deployment, active_runs)
        idle_timeout = _idle_timeout_for(deployment, default_idle_timeout_seconds)

        # No recorded activity at all → safe to reap (the deployment has
        # been sitting at desired_replicas>0 with nothing happening).
        if last_activity is not None and (now - last_activity) <= timedelta(
            seconds=idle_timeout
        ):
            continue

        namespace = deployment.namespace
        deployment_name = deployment.primary_container_id
        if not namespace or not deployment_name:
            # Can't drive K8s without both. Skip rather than crash so a
            # partially-installed row doesn't poison the whole pass.
            logger.warning(
                "runtime_reaper: missing namespace/name on deployment=%s "
                "(ns=%r, name=%r); skipping",
                deployment.id,
                namespace,
                deployment_name,
            )
            continue

        # 1. Scale to zero (graceful — sends SIGTERM).
        try:
            await _scale_deployment_to_zero(
                namespace=namespace,
                deployment_name=deployment_name,
                k8s_client=k8s_client,
            )
        except Exception:
            logger.exception(
                "runtime_reaper: scale-to-zero failed deployment=%s ns=%s name=%s",
                deployment.id,
                namespace,
                deployment_name,
            )
            continue

        # 2. Wait for any straggling runs to flip terminal.
        still_active = await _wait_for_runs_terminal(db, deployment.id)

        # 3. SIGKILL fallback if the grace window expired.
        if still_active:
            logger.warning(
                "runtime_reaper: grace window expired deployment=%s "
                "active_runs=%d — force-deleting pods",
                deployment.id,
                len(still_active),
            )
            await _force_delete_deployment_pods(
                namespace=namespace,
                deployment_name=deployment_name,
                k8s_client=k8s_client,
            )
            for run in still_active:
                run.paused_reason = "reaped_after_timeout"
            timeout_killed += 1
        else:
            reaped += 1

        # 4. Mark the deployment row.
        deployment.scaled_to_zero_at = now
        deployment.desired_replicas = 0

    try:
        await db.commit()
    except Exception:
        logger.exception("runtime_reaper: failed to commit reap pass")
        await db.rollback()

    return ReapResult(
        examined=examined,
        skipped_active=skipped_active,
        reaped=reaped,
        timeout_killed=timeout_killed,
    )
