"""Idempotent intent reconciler (Phase 4).

The reconciler is the only place K8s / Docker mutations happen for the
controller plane. Every 5 seconds it:

1. Reads up to 50 ``controller_intents`` rows with ``status='pending'``,
   oldest first.
2. For each row, if ``intent.lease_term != current_term`` → mark
   ``superseded`` (this row was written by a deposed leader).
3. Else dispatch to the appropriate :class:`Reconciler` (selected once
   at startup based on ``settings.deployment_mode``):

   * :class:`K8sReconciler` — patches Deployments, deletes Pods.
     Treats 409 (resourceVersion conflict) as "retry next tick".
   * :class:`DockerReconciler` — runs ``docker stop`` /
     ``docker compose scale`` analogues.
   * :class:`NoopReconciler` — desktop mode; just logs and marks
     ``applied`` (there's no compute orchestration to reconcile).

4. On success: :func:`mark_applied`. On retryable failure: increment
   ``attempts`` and continue. On terminal failure (>=5 attempts):
   :func:`mark_failed`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from sqlalchemy import select

from . import LeaseLost, mark_applied, mark_failed, mark_superseded

logger = logging.getLogger(__name__)


_TICK_INTERVAL_SECONDS = 5
_MAX_BATCH = 50
_MAX_ATTEMPTS = 5


# ---------------------------------------------------------------------------
# Reconciler implementations.
# ---------------------------------------------------------------------------


class K8sConflictError(RuntimeError):
    """Resource version conflict — retry on the next tick."""


class _BaseReconciler:
    async def apply(self, kind: str, target_ref: dict[str, Any]) -> None:
        raise NotImplementedError


class NoopReconciler(_BaseReconciler):
    """Desktop / no-compute mode — log only.

    Intents accumulate as ``applied`` rows so the audit trail is intact
    while no actual mutation happens; a future migration to a stronger
    backend can replay the trail.
    """

    async def apply(self, kind: str, target_ref: dict[str, Any]) -> None:
        logger.info(
            "[RECONCILER:noop] would apply kind=%s target=%s",
            kind,
            target_ref,
        )


class K8sReconciler(_BaseReconciler):
    """K8s-native mutation reconciler.

    Each ``kind`` maps to a single idempotent K8s call. Uses the
    existing :class:`KubernetesClient` singleton so credentials and
    apiClient settings are shared with the rest of the orchestrator.
    """

    def __init__(self) -> None:
        self._client = None

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        from ...orchestration.kubernetes.client import get_k8s_client

        self._client = get_k8s_client()
        return self._client

    async def apply(self, kind: str, target_ref: dict[str, Any]) -> None:
        client = self._resolve_client()
        if kind == "scale_to_zero":
            await self._scale_to_zero(client, target_ref)
        elif kind == "scale_up":
            await self._scale_up(client, target_ref)
        elif kind == "delete_pod":
            await self._delete_pod(client, target_ref)
        else:
            raise NotImplementedError(f"K8sReconciler: unsupported kind {kind!r}")

    async def _scale_to_zero(self, client: Any, ref: dict[str, Any]) -> None:
        ns = ref.get("namespace")
        name = ref.get("deployment") or ref.get("name")
        if not ns or not name:
            raise ValueError(f"scale_to_zero needs namespace+deployment, got {ref}")
        try:
            await asyncio.to_thread(
                client.apps_v1.patch_namespaced_deployment_scale,
                name=name,
                namespace=ns,
                body={"spec": {"replicas": 0}},
            )
        except Exception as exc:
            status = getattr(exc, "status", None)
            if status == 409:
                raise K8sConflictError(str(exc)) from exc
            raise

    async def _scale_up(self, client: Any, ref: dict[str, Any]) -> None:
        ns = ref.get("namespace")
        name = ref.get("deployment") or ref.get("name")
        replicas = int(ref.get("replicas", 1))
        if not ns or not name:
            raise ValueError(f"scale_up needs namespace+deployment, got {ref}")
        try:
            await asyncio.to_thread(
                client.apps_v1.patch_namespaced_deployment_scale,
                name=name,
                namespace=ns,
                body={"spec": {"replicas": replicas}},
            )
        except Exception as exc:
            status = getattr(exc, "status", None)
            if status == 409:
                raise K8sConflictError(str(exc)) from exc
            raise

    async def _delete_pod(self, client: Any, ref: dict[str, Any]) -> None:
        ns = ref.get("namespace")
        name = ref.get("pod") or ref.get("name")
        if not ns or not name:
            raise ValueError(f"delete_pod needs namespace+pod, got {ref}")
        grace = int(ref.get("grace_period_seconds", 0))
        try:
            await asyncio.to_thread(
                client.core_v1.delete_namespaced_pod,
                name=name,
                namespace=ns,
                grace_period_seconds=grace,
            )
        except Exception as exc:
            status = getattr(exc, "status", None)
            if status == 404:
                # Already gone — idempotency win.
                return
            if status == 409:
                raise K8sConflictError(str(exc)) from exc
            raise


class DockerReconciler(_BaseReconciler):
    """Docker-API mutation reconciler.

    ``scale_to_zero`` translates to ``container.stop()`` (graceful
    SIGTERM with the container's own configured timeout). ``scale_up``
    is ``container.start()``. ``delete_pod`` maps to ``container.kill()
    + container.remove()`` since docker has no pod abstraction; the
    intent's ``target_ref['container_id']`` carries the docker container
    id.
    """

    def __init__(self) -> None:
        self._client = None

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import docker  # type: ignore
        except ImportError as exc:
            raise RuntimeError("docker python client not installed") from exc
        self._client = docker.from_env()
        return self._client

    async def apply(self, kind: str, target_ref: dict[str, Any]) -> None:
        client = self._resolve_client()
        cid = target_ref.get("container_id") or target_ref.get("name")
        if not cid:
            raise ValueError(
                f"DockerReconciler: target_ref needs container_id/name, got {target_ref}"
            )

        def _do() -> None:
            try:
                container = client.containers.get(cid)
            except Exception as exc:
                # 404 — already gone. Idempotent win.
                if "Not Found" in str(exc) or "not found" in str(exc).lower():
                    return
                raise

            if kind == "scale_to_zero":
                container.stop()
            elif kind == "scale_up":
                container.start()
            elif kind == "delete_pod":
                try:
                    container.kill()
                except Exception:
                    pass
                container.remove(force=True)
            else:
                raise NotImplementedError(
                    f"DockerReconciler: unsupported kind {kind!r}"
                )

        await asyncio.to_thread(_do)


# ---------------------------------------------------------------------------
# Factory & loop.
# ---------------------------------------------------------------------------


def _build_reconciler(deployment_mode: str | None = None) -> _BaseReconciler:
    if deployment_mode is None:
        try:
            from ...config import get_settings

            deployment_mode = get_settings().deployment_mode
        except Exception:
            deployment_mode = "desktop"

    mode = (deployment_mode or "").lower()
    if mode == "kubernetes":
        return K8sReconciler()
    if mode == "docker":
        try:
            return DockerReconciler()
        except Exception:
            logger.warning(
                "[RECONCILER] docker backend unavailable; falling back to noop",
                exc_info=True,
            )
            return NoopReconciler()
    return NoopReconciler()


async def run_loop(
    *,
    db_factory: Callable[[], Any],
    token_provider: Callable[[], Any],
    shutdown_event: asyncio.Event,
    interval_seconds: int = _TICK_INTERVAL_SECONDS,
    reconciler: _BaseReconciler | None = None,
) -> None:
    """Reconcile pending intents until shutdown."""
    if reconciler is None:
        reconciler = _build_reconciler()

    logger.info(
        "[RECONCILER] starting (backend=%s interval=%ds)",
        type(reconciler).__name__,
        interval_seconds,
    )

    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                shutdown_event.wait(), timeout=interval_seconds
            )
            return
        except TimeoutError:
            pass

        try:
            current_term = int(token_provider().term)
            await tick(
                db_factory=db_factory,
                current_term=current_term,
                reconciler=reconciler,
            )
        except LeaseLost:
            logger.warning("[RECONCILER] lease lost; standing down")
            return
        except Exception:
            logger.exception("[RECONCILER] tick failed")


async def tick(
    *,
    db_factory: Callable[[], Any],
    current_term: int,
    reconciler: _BaseReconciler,
    max_batch: int = _MAX_BATCH,
) -> dict[str, int]:
    """One reconcile pass. Returns counts for observability."""
    from ....models_automations import ControllerIntent

    counts = {"applied": 0, "superseded": 0, "retried": 0, "failed": 0}

    async with db_factory() as db:
        stmt = (
            select(ControllerIntent)
            .where(ControllerIntent.status == "pending")
            .order_by(ControllerIntent.created_at.asc())
            .limit(max_batch)
        )
        intents = list((await db.execute(stmt)).scalars().all())

        for intent in intents:
            if int(intent.lease_term or 0) != current_term:
                await mark_superseded(db, intent.id)
                counts["superseded"] += 1
                continue

            try:
                await reconciler.apply(intent.kind, intent.target_ref or {})
            except K8sConflictError as exc:
                logger.info(
                    "[RECONCILER] conflict on intent=%s kind=%s — retry next tick: %s",
                    intent.id,
                    intent.kind,
                    exc,
                )
                counts["retried"] += 1
                continue
            except Exception as exc:
                attempts = int(intent.attempts or 0) + 1
                if attempts >= _MAX_ATTEMPTS:
                    logger.error(
                        "[RECONCILER] intent=%s kind=%s exhausted after %d attempts: %s",
                        intent.id,
                        intent.kind,
                        attempts,
                        exc,
                    )
                    await mark_failed(db, intent.id, repr(exc), attempts)
                    counts["failed"] += 1
                else:
                    logger.warning(
                        "[RECONCILER] intent=%s kind=%s attempt %d failed: %s",
                        intent.id,
                        intent.kind,
                        attempts,
                        exc,
                    )
                    intent.attempts = attempts
                    intent.last_error = repr(exc)[:1000]
                    await db.commit()
                    counts["retried"] += 1
                continue

            await mark_applied(db, intent.id, current_term)
            counts["applied"] += 1

    return counts


__all__ = [
    "K8sConflictError",
    "K8sReconciler",
    "DockerReconciler",
    "NoopReconciler",
    "run_loop",
    "tick",
]
