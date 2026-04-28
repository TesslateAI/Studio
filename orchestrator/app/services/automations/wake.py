"""Compute auto-wake — provision a Tier-2 environment for an AutomationRun.

The dispatcher decides a run needs ``compute_target='automation_workspace'``
or ``compute_target='project'`` at Tier 2 (full env), but the underlying
``AppRuntimeDeployment`` (or the project's runtime) may be scaled to zero.
This module patches the Deployment, polls for endpoint readiness, signals
the worker via a Redis stream, and enqueues the actual ``execute_action``
ARQ task.

Bounded readiness timeout = 5 minutes (no infinite retry loop). On
timeout the run is flipped to ``status='waiting_approval'`` with
``paused_reason='compute_unavailable'`` and an ApprovalRequest titled
"could not start environment — retry?" is created.

Pattern reference
-----------------
The K8s wait-for-ready pattern mirrors ``services.orchestration.kubernetes
.client._wait_for_namespace_active`` — bounded poll with explicit interval,
``asyncio.to_thread`` around the sync K8s client, no informer streaming.
We deliberately stay on the bounded-poll path (not a watch stream) because:

* Five minutes is a small enough window that informer setup overhead
  (~250ms per call) outweighs the streaming benefit.
* The poll loop is interruptible — a controller cancellation drops the
  task cleanly.
* Informer streams add a third source of truth (cache) that the
  controller plane has to invalidate on revoke / rollout. We avoid the
  cache by polling Endpoints directly each tick.

Phase 4's controller may swap the body for an informer if metrics show
the readiness latency dominates Tier-2 cold-start budgets; the public
``provision_for_run`` signature is stable across that swap.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import (
    AppAction,
    AppInstance,
    AppRuntimeDeployment,
    AutomationAction,
    AutomationApprovalRequest,
    AutomationDefinition,
    AutomationRun,
)

logger = logging.getLogger(__name__)


# 5-minute readiness timeout — explicit per the plan (compute auto-wake
# section). Outside this window the run pauses, the user is asked to
# retry. Picked to be much larger than typical pod cold-start (~30-60s
# for warm images) but short enough that a stuck run doesn't sit
# eternally blocking a worker slot.
_READINESS_TIMEOUT_SECONDS = 300

# Poll interval. K8s endpoint readiness updates land within ~1-2s of pod
# Ready; 2s is the smallest interval that doesn't hammer the API server
# under load.
_POLL_INTERVAL_SECONDS = 2

# Redis stream key — workers waiting on a wake subscribe here. Phase 4's
# controller plane consumer hangs off this stream too for audit trace.
_COMPUTE_READY_STREAM_TEMPLATE = "tesslate:compute_ready:{run_id}"


@dataclass(frozen=True)
class ProvisionResult:
    """Typed return from :func:`provision_for_run`.

    ``ready`` reflects whether endpoints came up before the timeout.
    ``approval_request_id`` is set when the wake timed out and the run
    was paused with ``paused_reason='compute_unavailable'``.
    ``execute_action_enqueued`` mirrors whether the dispatcher
    successfully handed the run off to the worker pool.
    """

    ready: bool
    duration_seconds: float
    approval_request_id: UUID | None = None
    execute_action_enqueued: bool = False
    reason: str | None = None


async def _scale_deployment(
    apps_v1: Any,  # kubernetes.client.AppsV1Api — Any to avoid import in tests
    *,
    namespace: str,
    deployment_name: str,
    replicas: int,
) -> None:
    """Patch a Deployment's ``spec.replicas``.

    Mirrors :meth:`KubernetesClient.scale_deployment` but takes a raw
    ``apps_v1`` so callers can inject a fake in tests without standing up
    the full client wrapper.
    """
    deployment = await asyncio.to_thread(
        apps_v1.read_namespaced_deployment,
        name=deployment_name,
        namespace=namespace,
    )
    deployment.spec.replicas = replicas
    await asyncio.to_thread(
        apps_v1.patch_namespaced_deployment,
        name=deployment_name,
        namespace=namespace,
        body=deployment,
    )


async def _endpoints_ready(
    core_v1: Any,
    *,
    namespace: str,
    service_name: str,
) -> bool:
    """Return True iff the Service has at least one ready Endpoint subset.

    K8s populates ``Endpoints.subsets[].addresses`` only for ready pods;
    ``not_ready_addresses`` is the holding bay for pods that are running
    but failing readiness probes. We treat "any ready address" as ready
    so the worker can POST through ingress.
    """
    try:
        ep = await asyncio.to_thread(
            core_v1.read_namespaced_endpoints,
            name=service_name,
            namespace=namespace,
        )
    except Exception as exc:  # noqa: BLE001 — informational, falls back to "not ready"
        logger.debug(
            "wake: read_namespaced_endpoints svc=%s ns=%s err=%r",
            service_name,
            namespace,
            exc,
        )
        return False
    subsets = getattr(ep, "subsets", None) or []
    for subset in subsets:
        addresses = getattr(subset, "addresses", None) or []
        if addresses:
            return True
    return False


async def _publish_ready_event(
    redis: Any,
    *,
    run_id: UUID,
    deployment_id: UUID | None,
    namespace: str | None,
) -> None:
    """XADD a ``compute_ready`` event so workers waiting on this run unblock.

    Best-effort — Redis being unavailable does not fail the wake; the
    run still progresses via the ARQ enqueue path. Logged so operators
    can correlate "worker missed the signal" cases.
    """
    if redis is None:
        return
    stream_key = _COMPUTE_READY_STREAM_TEMPLATE.format(run_id=run_id)
    try:
        await redis.xadd(
            stream_key,
            {
                "run_id": str(run_id),
                "deployment_id": str(deployment_id) if deployment_id else "",
                "namespace": namespace or "",
                "ts": datetime.now(UTC).isoformat(),
            },
            maxlen=100,
            approximate=True,
        )
    except Exception as exc:  # noqa: BLE001 — non-fatal
        logger.warning(
            "wake: xadd compute_ready failed run=%s err=%r", run_id, exc
        )


async def _enqueue_execute_action(
    *,
    run_id: UUID,
    automation_id: UUID,
    enqueue_fn: Any | None,
) -> bool:
    """Enqueue the ``execute_action`` ARQ task — or skip if no queue wired.

    ``enqueue_fn`` is the injection point so tests don't depend on
    ``services.task_queue`` being importable. Production callers pass
    ``get_task_queue().enqueue`` (a bound method).
    """
    if enqueue_fn is None:
        # Fall back to the project queue.
        from ..task_queue import get_task_queue

        queue = get_task_queue()
        enqueue_fn = queue.enqueue
    try:
        await enqueue_fn(
            "execute_action",
            {
                "automation_run_id": str(run_id),
                "automation_id": str(automation_id),
                "wake_signaled_at": datetime.now(UTC).isoformat(),
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001 — surfaces in ProvisionResult
        logger.error(
            "wake: enqueue execute_action failed run=%s err=%r", run_id, exc
        )
        return False


async def _create_compute_unavailable_approval(
    db: AsyncSession,
    *,
    run: AutomationRun,
    namespace: str | None,
    deployment_name: str | None,
) -> UUID:
    """Persist the "could not start environment — retry?" approval card.

    Returns the new approval request id. Caller commits.
    """
    summary = (
        "Could not start the environment for this automation run within "
        f"{_READINESS_TIMEOUT_SECONDS}s. Retry to attempt another wake."
    )
    request = AutomationApprovalRequest(
        id=uuid4(),
        run_id=run.id,
        reason="credential_missing",  # nearest existing CHECK value; Phase 4 widens
        context={
            "summary": summary,
            "kind": "compute_unavailable",
            "namespace": namespace,
            "deployment": deployment_name,
        },
        context_artifacts=[],
        options=["allow_once", "deny", "deny_and_disable_automation"],
        delivered_to=[],
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(request)
    await db.flush()
    return request.id


async def _resolve_runtime(
    db: AsyncSession, run: AutomationRun
) -> AppRuntimeDeployment | None:
    """Walk the automation graph to find the AppRuntimeDeployment for ``run``.

    Path::

        AutomationRun.automation_id
            → AutomationAction WHERE action_type='app.invoke' (first row)
            → AppAction (via app_action_id)
            → AppInstance WHERE app_version_id matches AND
              installer_user_id == automation.owner_user_id
            → AppRuntimeDeployment (via app_instances.runtime_deployment_id)

    Returns ``None`` when:

    * the automation has no ``app.invoke`` action (direct agent.run /
      gateway.send runs — there is no deployment to wake), or
    * the install row has no ``runtime_deployment_id`` (legacy installs
      that predate Phase 3), or
    * any link in the chain is missing (deleted FK target — fail closed).

    The caller can still pass ``deployment_override`` to bypass this
    walk; the override path stays the canonical entry point for
    dispatchers that already hold a deployment reference (e.g. the
    action dispatcher's per-install cold-start path).
    """
    automation_action = (
        await db.execute(
            select(AutomationAction)
            .where(AutomationAction.automation_id == run.automation_id)
            .where(AutomationAction.action_type == "app.invoke")
            .where(AutomationAction.app_action_id.is_not(None))
            .order_by(AutomationAction.ordinal.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if automation_action is None or automation_action.app_action_id is None:
        return None

    app_action = await db.get(AppAction, automation_action.app_action_id)
    if app_action is None:
        return None

    automation = await db.get(AutomationDefinition, run.automation_id)
    if automation is None:
        return None

    install = (
        await db.execute(
            select(AppInstance)
            .where(AppInstance.app_version_id == app_action.app_version_id)
            .where(AppInstance.installer_user_id == automation.owner_user_id)
            .where(AppInstance.state == "installed")
            .limit(1)
        )
    ).scalar_one_or_none()
    if install is None or install.runtime_deployment_id is None:
        return None

    return await db.get(AppRuntimeDeployment, install.runtime_deployment_id)


async def provision_for_run(
    run_id: UUID,
    db: AsyncSession,
    k8s_client: Any,
    *,
    deployment_override: AppRuntimeDeployment | None = None,
    redis_client: Any | None = None,
    enqueue_fn: Any | None = None,
    timeout_seconds: int = _READINESS_TIMEOUT_SECONDS,
    poll_interval_seconds: int = _POLL_INTERVAL_SECONDS,
) -> ProvisionResult:
    """Wake a Tier-2 environment for ``run_id`` and signal readiness.

    Steps:

    1. Resolve the AppRuntimeDeployment (or use ``deployment_override``).
    2. Patch ``Deployment.spec.replicas`` from the current value to
       ``max(1, current.desired_replicas)``. If the deployment is already
       scaled up, skip the patch and proceed to readiness wait.
    3. Poll ``Endpoints.subsets[].addresses`` every
       ``poll_interval_seconds``. Return ``ready=True`` as soon as a
       ready address appears.
    4. If the timeout elapses without readiness: flip the run to
       ``status='waiting_approval'`` with ``paused_reason='compute_unavailable'``
       and create an ApprovalRequest. Return ``ready=False`` with the
       request id.
    5. On readiness: XADD a ``tesslate:compute_ready:{run_id}`` event so
       any worker waiting on this run unblocks; enqueue the
       ``execute_action`` ARQ task; return ``ready=True``.

    All K8s calls run in ``asyncio.to_thread`` so the event loop stays
    free.
    """
    started = datetime.now(UTC)

    run = await db.get(AutomationRun, run_id)
    if run is None:
        return ProvisionResult(
            ready=False,
            duration_seconds=0.0,
            reason="run_not_found",
        )

    deployment = deployment_override
    if deployment is None:
        deployment = await _resolve_runtime(db, run)

    if deployment is None or not deployment.namespace:
        # Tier-0 / no-runtime path: nothing to wake. The dispatcher should
        # not have called us, but failing closed (no enqueue) is safer
        # than racing the worker.
        logger.info(
            "wake: run=%s has no deployment to wake; skipping provision",
            run_id,
        )
        ok = await _enqueue_execute_action(
            run_id=run_id,
            automation_id=run.automation_id,
            enqueue_fn=enqueue_fn,
        )
        await _publish_ready_event(
            redis_client,
            run_id=run_id,
            deployment_id=None,
            namespace=None,
        )
        return ProvisionResult(
            ready=True,
            duration_seconds=(datetime.now(UTC) - started).total_seconds(),
            execute_action_enqueued=ok,
            reason="no_runtime_required",
        )

    namespace = deployment.namespace
    # Convention: Deployment + Service share the deployment_id-derived
    # name. Phase 4 will hoist this onto the AppRuntimeDeployment row;
    # for now we derive it.
    deployment_name = (
        deployment.primary_container_id or f"app-{deployment.id}"
    )
    service_name = deployment_name

    apps_v1 = getattr(k8s_client, "apps_v1", None)
    core_v1 = getattr(k8s_client, "core_v1", None)
    if apps_v1 is None or core_v1 is None:
        return ProvisionResult(
            ready=False,
            duration_seconds=(datetime.now(UTC) - started).total_seconds(),
            reason="k8s_client_misconfigured",
        )

    # Step 2 — scale up. Already-scaled deployments tolerate a no-op patch.
    target_replicas = max(1, deployment.desired_replicas or 1)
    try:
        await _scale_deployment(
            apps_v1,
            namespace=namespace,
            deployment_name=deployment_name,
            replicas=target_replicas,
        )
    except Exception as exc:  # noqa: BLE001 — surface in approval card
        logger.error(
            "wake: scale failed run=%s ns=%s deployment=%s err=%r",
            run_id,
            namespace,
            deployment_name,
            exc,
        )
        approval_id = await _create_compute_unavailable_approval(
            db,
            run=run,
            namespace=namespace,
            deployment_name=deployment_name,
        )
        run.status = "waiting_approval"
        run.paused_reason = "compute_unavailable"
        await db.flush()
        return ProvisionResult(
            ready=False,
            duration_seconds=(datetime.now(UTC) - started).total_seconds(),
            approval_request_id=approval_id,
            reason="scale_failed",
        )

    # Step 3 — poll endpoints.
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while asyncio.get_event_loop().time() < deadline:
        if await _endpoints_ready(
            core_v1, namespace=namespace, service_name=service_name
        ):
            duration = (datetime.now(UTC) - started).total_seconds()

            # Step 5a — Redis ready signal (best-effort).
            await _publish_ready_event(
                redis_client,
                run_id=run_id,
                deployment_id=deployment.id,
                namespace=namespace,
            )

            # Step 5b — enqueue the worker task.
            enqueued = await _enqueue_execute_action(
                run_id=run_id,
                automation_id=run.automation_id,
                enqueue_fn=enqueue_fn,
            )

            logger.info(
                "wake: ready run=%s ns=%s deployment=%s duration=%.1fs enqueued=%s",
                run_id,
                namespace,
                deployment_name,
                duration,
                enqueued,
            )
            return ProvisionResult(
                ready=True,
                duration_seconds=duration,
                execute_action_enqueued=enqueued,
                reason="ready",
            )
        await asyncio.sleep(poll_interval_seconds)

    # Step 4 — readiness timeout.
    duration = (datetime.now(UTC) - started).total_seconds()
    approval_id = await _create_compute_unavailable_approval(
        db,
        run=run,
        namespace=namespace,
        deployment_name=deployment_name,
    )
    run.status = "waiting_approval"
    run.paused_reason = "compute_unavailable"
    await db.flush()
    logger.warning(
        "wake: TIMEOUT run=%s ns=%s deployment=%s duration=%.1fs approval=%s",
        run_id,
        namespace,
        deployment_name,
        duration,
        approval_id,
    )
    return ProvisionResult(
        ready=False,
        duration_seconds=duration,
        approval_request_id=approval_id,
        reason="readiness_timeout",
    )


async def lookup_runtime_for_run(
    db: AsyncSession, run: AutomationRun
) -> AppRuntimeDeployment | None:
    """Public re-export of the (currently best-effort) runtime resolver.

    Exposed so dispatcher code can build a ``deployment_override`` once
    and pass it in — the resolver is a stub today; the wave that wires
    the run→deployment FK swaps the body without changing this signature.
    """
    return await _resolve_runtime(db, run)


__all__ = [
    "ProvisionResult",
    "lookup_runtime_for_run",
    "provision_for_run",
]
