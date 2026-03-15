"""
Compute Manager — ephemeral pod lifecycle for Tier 1 one-off commands.

Creates short-lived pods in the tesslate namespace that mount a project's
btrfs subvolume via hostPath, run a single command, and self-destruct.
No database access — callers manage Project model state.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


class ComputeQuotaExceeded(Exception):
    """Raised when the concurrent compute pod limit is reached."""


class ComputeManager:
    """Manages ephemeral pods for one-off command execution (Tier 1 compute)."""

    def __init__(self) -> None:
        self._v1: k8s_client.CoreV1Api | None = None

    # ------------------------------------------------------------------
    # K8s client (lazy init, matches kubernetes/client.py pattern)
    # ------------------------------------------------------------------

    def _api(self) -> k8s_client.CoreV1Api:
        if self._v1 is None:
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()
            self._v1 = k8s_client.CoreV1Api()
        return self._v1

    def _namespace(self) -> str:
        """Return the namespace for compute pods (always tesslate)."""
        from ..config import get_settings
        return get_settings().k8s_default_namespace

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def _count_active_compute_pods(self) -> int:
        """Count running tier-1 compute pods."""
        v1 = self._api()
        ns = self._namespace()
        pod_list = await asyncio.to_thread(
            v1.list_namespaced_pod, ns,
            label_selector="tesslate.io/tier=1",
            field_selector="status.phase!=Succeeded,status.phase!=Failed",
        )
        return len(pod_list.items or [])

    async def run_command(
        self,
        volume_id: str,
        node_name: str,
        command: list[str],
        timeout: int = 120,
        image: str | None = None,
    ) -> tuple[str, int, str]:
        """Run a one-off command in an ephemeral pod.

        Args:
            volume_id: btrfs subvolume ID for the project.
            node_name: Target node (volume locality — bypasses scheduler).
            command: Command to execute (e.g. ["/bin/sh", "-c", "npm install"]).
            timeout: Maximum seconds to wait for completion.
            image: Container image override (defaults to k8s_devserver_image).

        Returns:
            (output, exit_code, pod_name)

        Raises:
            ComputeQuotaExceeded: When the concurrent pod limit is reached.
        """
        from ..config import get_settings

        settings = get_settings()

        # Enforce concurrent pod cap
        count = await self._count_active_compute_pods()
        if count >= settings.compute_max_concurrent_pods:
            raise ComputeQuotaExceeded(
                f"Compute pod limit reached ({count}/{settings.compute_max_concurrent_pods})"
            )

        pod_name = f"t1-{volume_id[:8]}-{uuid4().hex[:6]}"
        ns = self._namespace()
        devserver_image = image or settings.k8s_devserver_image

        manifest = self._build_pod_manifest(
            pod_name=pod_name,
            namespace=ns,
            volume_id=volume_id,
            node_name=node_name,
            command=command,
            image=devserver_image,
            timeout=timeout,
        )

        v1 = self._api()

        try:
            await asyncio.to_thread(
                v1.create_namespaced_pod, ns, manifest
            )

            logger.info(
                "[COMPUTE] Pod %s created for volume %s on node %s",
                pod_name,
                volume_id,
                node_name,
            )

            # Wait for completion
            output, exit_code = await self._wait_for_completion(
                pod_name, ns, timeout
            )
            return output, exit_code, pod_name

        finally:
            # Always clean up — fire-and-forget, swallow 404
            try:
                await asyncio.to_thread(
                    v1.delete_namespaced_pod,
                    pod_name,
                    ns,
                    grace_period_seconds=0,
                )
                logger.debug("[COMPUTE] Pod %s deleted", pod_name)
            except ApiException as exc:
                if exc.status != 404:
                    logger.warning(
                        "[COMPUTE] Failed to delete pod %s: %s",
                        pod_name,
                        exc.reason,
                    )

    async def reap_orphaned_pods(self, max_age_seconds: int = 900) -> int:
        """Delete pods older than max_age_seconds. Returns count deleted."""
        from datetime import datetime, timezone

        ns = self._namespace()
        v1 = self._api()
        now = datetime.now(timezone.utc)
        reaped = 0

        def _list_pods() -> k8s_client.V1PodList:
            return v1.list_namespaced_pod(
                ns,
                label_selector="tesslate.io/tier=1",
            )

        try:
            pod_list = await asyncio.to_thread(_list_pods)
        except ApiException as exc:
            if exc.status == 404:
                return 0  # Namespace doesn't exist yet
            raise

        # Collect pods that exceed max age
        to_reap: list[tuple[str, float]] = []
        for pod in pod_list.items:
            creation = pod.metadata.creation_timestamp
            if creation is None:
                continue
            age = (now - creation).total_seconds()
            if age > max_age_seconds:
                to_reap.append((pod.metadata.name, age))

        if not to_reap:
            return 0

        # Delete concurrently
        async def _delete_pod(pod_name: str, age: float) -> bool:
            try:
                await asyncio.to_thread(
                    v1.delete_namespaced_pod,
                    pod_name,
                    ns,
                    grace_period_seconds=0,
                )
                logger.warning(
                    "[COMPUTE] Reaped orphaned pod %s (age: %.0fs)",
                    pod_name,
                    age,
                )
                return True
            except ApiException as exc:
                if exc.status != 404:
                    logger.warning(
                        "[COMPUTE] Failed to reap pod %s: %s",
                        pod_name,
                        exc.reason,
                    )
                return False

        results = await asyncio.gather(
            *[_delete_pod(name, age) for name, age in to_reap]
        )
        return sum(1 for r in results if r)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_pod_manifest(
        self,
        *,
        pod_name: str,
        namespace: str,
        volume_id: str,
        node_name: str,
        command: list[str],
        image: str,
        timeout: int = 120,
    ) -> k8s_client.V1Pod:
        """Build the ephemeral pod manifest."""
        return k8s_client.V1Pod(
            metadata=k8s_client.V1ObjectMeta(
                name=pod_name,
                namespace=namespace,
                labels={
                    "tesslate.io/tier": "1",
                    "tesslate.io/volume-id": volume_id[:63],
                    "app.kubernetes.io/part-of": "tesslate",
                },
            ),
            spec=k8s_client.V1PodSpec(
                restart_policy="Never",
                active_deadline_seconds=timeout + 30,  # K8s safety net slightly after app timeout
                termination_grace_period_seconds=5,
                node_name=node_name,
                automount_service_account_token=False,
                security_context=k8s_client.V1PodSecurityContext(
                    run_as_user=1000,
                    run_as_group=1000,
                    run_as_non_root=True,
                ),
                containers=[
                    k8s_client.V1Container(
                        name="cmd",
                        image=image,
                        image_pull_policy="IfNotPresent",
                        command=command,
                        working_dir="/app",
                        volume_mounts=[
                            k8s_client.V1VolumeMount(
                                name="project-source",
                                mount_path="/app",
                            ),
                        ],
                        resources=k8s_client.V1ResourceRequirements(
                            requests={"cpu": "100m", "memory": "256Mi"},
                            limits={"cpu": "2000m", "memory": "4Gi"},
                        ),
                        security_context=k8s_client.V1SecurityContext(
                            run_as_user=1000,
                            run_as_group=1000,
                            allow_privilege_escalation=False,
                        ),
                    ),
                ],
                volumes=[
                    k8s_client.V1Volume(
                        name="project-source",
                        host_path=k8s_client.V1HostPathVolumeSource(
                            path=f"/mnt/tesslate-pool/volumes/{volume_id}",
                            type="Directory",
                        ),
                    ),
                ],
            ),
        )

    def _pod_failure_reason(self, pod: k8s_client.V1Pod) -> str:
        """Extract a human-readable failure reason from pod status."""
        parts: list[str] = []

        # Check container statuses for waiting/terminated reasons
        for cs in (pod.status.container_statuses or []):
            if cs.state:
                if cs.state.waiting and cs.state.waiting.reason:
                    parts.append(f"{cs.name}: {cs.state.waiting.reason} — {cs.state.waiting.message or ''}")
                if cs.state.terminated and cs.state.terminated.reason:
                    parts.append(f"{cs.name}: {cs.state.terminated.reason} — {cs.state.terminated.message or ''}")

        # Check pod-level conditions (e.g., Unschedulable, volume mount failures)
        for cond in (pod.status.conditions or []):
            if cond.status == "False" and cond.message:
                parts.append(f"{cond.type}: {cond.message}")

        return "; ".join(parts) if parts else "unknown reason"

    async def _safe_read_logs(self, pod_name: str, namespace: str) -> str:
        """Read pod logs, returning empty string if container never started."""
        v1 = self._api()
        try:
            return await asyncio.to_thread(
                v1.read_namespaced_pod_log,
                pod_name,
                namespace,
                container="cmd",
                limit_bytes=1_048_576,  # 1 MB cap
            )
        except ApiException as exc:
            # 400 = container not available (never started); 404 = pod gone
            if exc.status in (400, 404):
                logger.debug(
                    "[COMPUTE] Could not read logs for %s: %s",
                    pod_name,
                    exc.reason,
                )
                return ""
            raise

    async def _wait_for_completion(
        self,
        pod_name: str,
        namespace: str,
        timeout: int,
    ) -> tuple[str, int]:
        """Poll pod status until Succeeded/Failed/timeout."""
        v1 = self._api()
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            try:
                pod = await asyncio.to_thread(
                    v1.read_namespaced_pod, pod_name, namespace
                )
                phase = pod.status.phase if pod.status else "Unknown"

                if phase == "Succeeded":
                    logs = await self._safe_read_logs(pod_name, namespace)
                    return logs, 0

                if phase == "Failed":
                    logs = await self._safe_read_logs(pod_name, namespace)
                    reason = self._pod_failure_reason(pod)
                    if not logs and reason:
                        logs = f"Pod failed before container started: {reason}"
                    logger.warning(
                        "[COMPUTE] Pod %s failed: %s", pod_name, reason,
                    )
                    exit_code = 1
                    if pod.status and pod.status.container_statuses:
                        for cs in pod.status.container_statuses:
                            if cs.state and cs.state.terminated:
                                exit_code = cs.state.terminated.exit_code
                    return logs, exit_code

            except ApiException as exc:
                if exc.status == 404:
                    return "", 1  # Pod disappeared
                raise

            await asyncio.sleep(1)

        # Timeout — return 124 (Unix `timeout` convention)
        return "", 124


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_instance: ComputeManager | None = None


def get_compute_manager() -> ComputeManager:
    """Get or create the global ComputeManager singleton."""
    global _instance
    if _instance is None:
        _instance = ComputeManager()
    return _instance
