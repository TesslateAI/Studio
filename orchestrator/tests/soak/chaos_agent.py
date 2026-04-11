"""
Chaos agent — periodically disrupts cluster infrastructure.

Runs independently from user workers. Actions:
  - Cordon/uncordon a random worker node
  - Rollout restart the CSI DaemonSet
  - Rollout restart the Volume Hub
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time

from .event_log import EventLog
from .metrics import Metrics

logger = logging.getLogger("soak.chaos")


class ChaosAgent:
    """Periodically injects infrastructure chaos into the cluster."""

    def __init__(
        self,
        worker_nodes: list[str],
        metrics: Metrics,
        interval_seconds: int = 600,
        enabled: bool = True,
        event_log: EventLog | None = None,
    ):
        self.worker_nodes = worker_nodes
        self.metrics = metrics
        self.interval = interval_seconds
        self.enabled = enabled
        self.events = event_log
        self._cordoned: str | None = None

    async def run(self, deadline: float | None = None, max_cycles: int | None = None):
        """Run chaos actions on a timer until deadline or cancellation."""
        if not self.enabled:
            logger.info("[chaos] Disabled — skipping all disruptions")
            try:
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                return

        logger.info("[chaos] Enabled — interval=%ds", self.interval)
        cycle = 0
        try:
            while True:
                if deadline and time.monotonic() > deadline:
                    break
                await asyncio.sleep(self.interval + random.uniform(-10, 10))
                cycle += 1

                action = random.choice(
                    [
                        self._chaos_cordon_uncordon,
                        self._chaos_restart_csi,
                        self._chaos_restart_hub,
                    ]
                )
                action_name = action.__name__

                t0 = time.monotonic()
                try:
                    await action()
                    dur = time.monotonic() - t0
                    self.metrics.record("chaos", action_name, True, dur)
                    logger.info("[chaos] %s OK (%.1fs)", action_name, dur)
                    if self.events:
                        self.events.log(
                            "chaos",
                            action_name,
                            "complete",
                            "",
                            duration_s=dur,
                        )
                except Exception as e:
                    dur = time.monotonic() - t0
                    self.metrics.record("chaos", action_name, False, dur, str(e)[:120])
                    logger.warning("[chaos] %s FAIL: %s", action_name, e)
                    if self.events:
                        self.events.log(
                            "chaos",
                            action_name,
                            "fail",
                            "",
                            success=False,
                            duration_s=dur,
                            error=str(e)[:120],
                        )
        except asyncio.CancelledError:
            pass
        finally:
            # Always uncordon on shutdown
            if self._cordoned:
                with contextlib.suppress(Exception):
                    await self._uncordon(self._cordoned)

    # ── Chaos actions ────────────────────────────────────────────

    async def _chaos_cordon_uncordon(self):
        """Cordon a random node for 30s, then uncordon."""
        import kubernetes

        kubernetes.config.load_incluster_config()
        v1 = kubernetes.client.CoreV1Api()

        if self._cordoned:
            await self._uncordon(self._cordoned)
            logger.info("[chaos] Uncordoned %s", self._cordoned)
            if self.events:
                self.events.log(
                    "chaos",
                    "cordon_uncordon",
                    "uncordon",
                    "",
                    detail=f"node={self._cordoned}",
                )
            self._cordoned = None
            return

        victim = random.choice(self.worker_nodes)
        v1.patch_node(victim, {"spec": {"unschedulable": True}})
        self._cordoned = victim
        logger.info("[chaos] Cordoned %s — will uncordon in ~30s", victim)
        if self.events:
            self.events.log(
                "chaos",
                "cordon_uncordon",
                "cordon",
                "",
                detail=f"node={victim}",
            )

        await asyncio.sleep(30)

        await self._uncordon(victim)
        if self.events:
            self.events.log(
                "chaos",
                "cordon_uncordon",
                "uncordon",
                "",
                detail=f"node={victim}",
            )
        self._cordoned = None

    async def _chaos_restart_csi(self):
        """Rollout restart the CSI DaemonSet and wait for recovery."""
        if self.events:
            self.events.log("chaos", "restart_csi", "begin", "")
        await self._rollout_restart_daemonset("tesslate-btrfs-csi-node", "kube-system")
        await self._wait_daemonset_ready("tesslate-btrfs-csi-node", "kube-system")
        await asyncio.sleep(10)  # Let Hub rediscover nodes

    async def _chaos_restart_hub(self):
        """Rollout restart the Volume Hub and wait for recovery."""
        if self.events:
            self.events.log("chaos", "restart_hub", "begin", "")
        await self._rollout_restart_deployment("tesslate-volume-hub", "kube-system")
        await self._wait_deployment_ready("tesslate-volume-hub", "kube-system")

        # Reset VolumeManager singleton so it gets a fresh gRPC channel
        import app.services.volume_manager as vm_mod

        vm_mod._instance = None
        await asyncio.sleep(10)  # Let Hub rediscover nodes

    # ── K8s helpers ──────────────────────────────────────────────

    async def _uncordon(self, node: str):
        import kubernetes

        kubernetes.config.load_incluster_config()
        v1 = kubernetes.client.CoreV1Api()
        v1.patch_node(node, {"spec": {"unschedulable": False}})
        logger.info("[chaos] Uncordoned %s", node)

    async def _rollout_restart_daemonset(self, name: str, namespace: str):
        import kubernetes

        kubernetes.config.load_incluster_config()
        apps = kubernetes.client.AppsV1Api()
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "tesslate.io/restartedAt": str(time.time()),
                        }
                    }
                }
            }
        }
        apps.patch_namespaced_daemon_set(name, namespace, body)

    async def _rollout_restart_deployment(self, name: str, namespace: str):
        import kubernetes

        kubernetes.config.load_incluster_config()
        apps = kubernetes.client.AppsV1Api()
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "tesslate.io/restartedAt": str(time.time()),
                        }
                    }
                }
            }
        }
        apps.patch_namespaced_deployment(name, namespace, body)

    async def _wait_daemonset_ready(self, name: str, namespace: str, timeout: int = 180):
        import kubernetes

        kubernetes.config.load_incluster_config()
        apps = kubernetes.client.AppsV1Api()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ds = apps.read_namespaced_daemon_set(name, namespace)
            desired = ds.status.desired_number_scheduled or 0
            ready = ds.status.number_ready or 0
            if desired > 0 and ready == desired:
                return
            await asyncio.sleep(3)

    async def _wait_deployment_ready(self, name: str, namespace: str, timeout: int = 120):
        import kubernetes

        kubernetes.config.load_incluster_config()
        apps = kubernetes.client.AppsV1Api()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            dep = apps.read_namespaced_deployment(name, namespace)
            desired = dep.spec.replicas or 1
            ready = dep.status.ready_replicas or 0
            if ready >= desired:
                return
            await asyncio.sleep(3)
