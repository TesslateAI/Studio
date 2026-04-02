"""
Compute Manager — compute lifecycle for Tier 1 (ephemeral) and Tier 2 (environment).

Tier 1: Short-lived pods in the dedicated ``tesslate-compute-pool`` namespace
that mount a project's btrfs subvolume via CSI PV+PVC, run a single command,
and self-destruct.  PSA ``restricted`` is enforced on the namespace.

Tier 2: Full persistent environments (dev servers, service containers, ingress)
using CSI-backed PV+PVC in per-project namespaces. ~5-10s startup.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _sanitize_k8s_name(name: str) -> str:
    """Sanitize a name for K8s (DNS-1123 compliant).

    Mirrors KubernetesOrchestrator._sanitize_name(): lowercase, replace
    non-alphanumeric with hyphens, collapse double hyphens, strip, truncate
    to 59 chars (leaves room for 4-char prefixes like 'dev-' or 'svc-').
    """
    safe = name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
    safe = "".join(c for c in safe if c.isalnum() or c == "-")
    while "--" in safe:
        safe = safe.replace("--", "-")
    safe = safe.strip("-")
    return safe[:59]


def resolve_k8s_container_dir(container) -> str:
    """Resolve a container's K8s resource identifier from its directory.

    Uses container.directory directly. When directory is "." (root),
    uses a stable identifier derived from container.id.
    NEVER falls back to container.name — that pattern is banned.
    """
    sanitized = _sanitize_k8s_name(container.directory or ".")
    if not sanitized:
        # Root directory (".") → use container UUID prefix as stable identifier
        return _sanitize_k8s_name(str(container.id).replace("-", "")[:12])
    return sanitized


def _parse_cpu_millicores(cpu_str: str) -> int:
    """Parse K8s CPU string (e.g. '1930m', '2', '500m') to millicores."""
    cpu_str = str(cpu_str).strip()
    if not cpu_str or cpu_str == "0":
        return 0
    if cpu_str.endswith("m"):
        return int(float(cpu_str[:-1]))
    return int(float(cpu_str) * 1000)


def _parse_mem_mib(mem_str: str) -> int:
    """Parse K8s memory string (e.g. '512Mi', '2Gi', '1024') to MiB."""
    mem_str = str(mem_str).strip()
    if not mem_str or mem_str == "0":
        return 0
    if mem_str.endswith("Gi"):
        return int(float(mem_str[:-2]) * 1024)
    if mem_str.endswith("Mi"):
        return int(float(mem_str[:-2]))
    if mem_str.endswith("Ki"):
        return max(1, int(float(mem_str[:-2]) / 1024))
    return max(1, int(float(mem_str) / (1024 * 1024)))


# Default resource requests for dev (base) containers.
_DEV_CONTAINER_CPU_REQUEST = "50m"
_DEV_CONTAINER_MEM_REQUEST = "256Mi"

# Reserved headroom for ephemeral pods (terminal, one-shot commands).
_EPHEMERAL_HEADROOM_CPU = "100m"
_EPHEMERAL_HEADROOM_MEM = "512Mi"


@dataclass(frozen=True, slots=True)
class PlacementBudget:
    """Total resource budget for a placement unit."""

    cpu_millicores: int
    memory_mib: int


def placement_budget(containers: list) -> PlacementBudget:
    """Calculate total resource budget for a placement unit.

    Sums CPU/memory requests for all containers in the project:
    - Service containers use profiles from service_definitions.py.
    - Base (dev) containers use defaults (_DEV_CONTAINER_*).
    - Ephemeral headroom is always added.
    """
    from .service_definitions import get_service

    total_cpu = 0
    total_mem = 0

    for c in containers:
        if c.container_type == "service" and c.service_slug:
            svc_def = get_service(c.service_slug)
            if svc_def:
                total_cpu += _parse_cpu_millicores(svc_def.cpu_request)
                total_mem += _parse_mem_mib(svc_def.mem_request)
            else:
                total_cpu += _parse_cpu_millicores(_DEV_CONTAINER_CPU_REQUEST)
                total_mem += _parse_mem_mib(_DEV_CONTAINER_MEM_REQUEST)
        else:
            total_cpu += _parse_cpu_millicores(_DEV_CONTAINER_CPU_REQUEST)
            total_mem += _parse_mem_mib(_DEV_CONTAINER_MEM_REQUEST)

    # Always reserve ephemeral headroom
    total_cpu += _parse_cpu_millicores(_EPHEMERAL_HEADROOM_CPU)
    total_mem += _parse_mem_mib(_EPHEMERAL_HEADROOM_MEM)

    return PlacementBudget(cpu_millicores=total_cpu, memory_mib=total_mem)


class ComputeQuotaExceeded(Exception):
    """Raised when the concurrent compute pod limit is reached."""


class ComputeManager:
    """Manages ephemeral pods (Tier 1) and full environments (Tier 2)."""

    def __init__(self) -> None:
        self._v1: k8s_client.CoreV1Api | None = None
        self._k8s = None  # KubernetesClient wrapper for T2
        self._ns_ready = False  # Lazy-init flag for compute namespace

    # ------------------------------------------------------------------
    # K8s clients (lazy init)
    # ------------------------------------------------------------------

    def _k8s_client(self):
        """KubernetesClient wrapper for T2 (namespaces, deployments, services, ingress)."""
        if self._k8s is None:
            from .orchestration.kubernetes.client import get_k8s_client

            self._k8s = get_k8s_client()
        return self._k8s

    def _api(self) -> k8s_client.CoreV1Api:
        if self._v1 is None:
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config()
            self._v1 = k8s_client.CoreV1Api()
        return self._v1

    def _namespace(self) -> str:
        """Return the namespace for compute pods."""
        from ..config import get_settings

        return get_settings().compute_pool_namespace

    async def _get_schedulable_nodes(self) -> list[str]:
        """Return names of all K8s nodes that are Ready and not cordoned."""
        v1 = self._api()
        try:
            node_list = await asyncio.to_thread(v1.list_node)
        except Exception:
            logger.warning("[COMPUTE] Failed to list K8s nodes")
            return []
        result = []
        for node in node_list.items or []:
            if node.spec and node.spec.unschedulable:
                continue
            for cond in node.status.conditions or []:
                if cond.type == "Ready" and cond.status == "True":
                    result.append(node.metadata.name)
                    break
        return result

    # ------------------------------------------------------------------
    # Compute namespace lifecycle (lazy init)
    # ------------------------------------------------------------------

    async def _ensure_compute_namespace(self) -> None:
        """Ensure compute pool namespace exists with NetworkPolicy. Idempotent."""
        if self._ns_ready:
            return

        ns = self._namespace()
        v1 = self._api()

        try:
            await asyncio.to_thread(v1.read_namespace, ns)
        except ApiException as exc:
            if exc.status != 404:
                raise
            body = k8s_client.V1Namespace(
                metadata=k8s_client.V1ObjectMeta(
                    name=ns,
                    labels={
                        "app.kubernetes.io/name": "tesslate-studio",
                        "app.kubernetes.io/component": "compute-pool",
                        "pod-security.kubernetes.io/enforce": "restricted",
                    },
                ),
            )
            await asyncio.to_thread(v1.create_namespace, body)
            logger.info("[COMPUTE] Created namespace %s", ns)

        await self._apply_compute_network_policy(ns)
        await self._apply_compute_resource_quota(ns)
        self._ns_ready = True

    async def _apply_compute_network_policy(self, namespace: str) -> None:
        """Apply the compute-pool NetworkPolicy (deny ingress, allow DNS + HTTP/HTTPS egress)."""
        policy = k8s_client.V1NetworkPolicy(
            metadata=k8s_client.V1ObjectMeta(
                name="compute-pool-isolation",
                namespace=namespace,
            ),
            spec=k8s_client.V1NetworkPolicySpec(
                pod_selector=k8s_client.V1LabelSelector(),
                policy_types=["Ingress", "Egress"],
                ingress=[],
                egress=[
                    # DNS to kube-system
                    k8s_client.V1NetworkPolicyEgressRule(
                        to=[
                            k8s_client.V1NetworkPolicyPeer(
                                namespace_selector=k8s_client.V1LabelSelector(
                                    match_labels={"kubernetes.io/metadata.name": "kube-system"}
                                )
                            )
                        ],
                        ports=[
                            k8s_client.V1NetworkPolicyPort(protocol="UDP", port=53),
                            k8s_client.V1NetworkPolicyPort(protocol="TCP", port=53),
                        ],
                    ),
                    # HTTP/HTTPS to external
                    k8s_client.V1NetworkPolicyEgressRule(
                        ports=[
                            k8s_client.V1NetworkPolicyPort(protocol="TCP", port=443),
                            k8s_client.V1NetworkPolicyPort(protocol="TCP", port=80),
                        ],
                    ),
                ],
            ),
        )

        net_api = k8s_client.NetworkingV1Api(api_client=self._api().api_client)
        try:
            await asyncio.to_thread(net_api.create_namespaced_network_policy, namespace, policy)
        except ApiException as exc:
            if exc.status == 409:
                await asyncio.to_thread(
                    net_api.patch_namespaced_network_policy,
                    "compute-pool-isolation",
                    namespace,
                    policy,
                )
            else:
                raise

    async def _apply_compute_resource_quota(self, namespace: str) -> None:
        """Apply the compute-pool ResourceQuota. Idempotent (create or patch)."""
        quota = k8s_client.V1ResourceQuota(
            metadata=k8s_client.V1ObjectMeta(
                name="compute-pool-quota",
                namespace=namespace,
            ),
            spec=k8s_client.V1ResourceQuotaSpec(
                hard={
                    "pods": "10",
                    "requests.cpu": "500m",
                    "requests.memory": "2560Mi",
                    "limits.cpu": "20",
                    "limits.memory": "40Gi",
                    "persistentvolumeclaims": "10",
                }
            ),
        )

        v1 = self._api()
        try:
            await asyncio.to_thread(v1.create_namespaced_resource_quota, namespace, quota)
        except ApiException as exc:
            if exc.status == 409:
                await asyncio.to_thread(
                    v1.patch_namespaced_resource_quota,
                    "compute-pool-quota",
                    namespace,
                    quota,
                )
            else:
                raise

    # ------------------------------------------------------------------
    # Compute PV/PVC lifecycle (reusable per-volume)
    # ------------------------------------------------------------------

    async def _ensure_compute_pv_pvc(self, volume_id: str, node_name: str) -> str:
        """Ensure a reusable PV+PVC exists for a volume. Returns PVC name.

        PV/PVC are keyed by volume_id (not pod_name) so they can be reused
        across multiple ephemeral pods for the same project. Uses claimRef
        pre-binding for fast PVC bind (~1s instead of ~14s).
        """
        ns = self._namespace()
        v1 = self._api()
        pv_name = f"vol-pv-{volume_id}"
        pvc_name = f"vol-pvc-{volume_id}"

        # Check if PVC already exists and is bound
        try:
            existing_pvc = await asyncio.to_thread(
                v1.read_namespaced_persistent_volume_claim, pvc_name, ns
            )
            if existing_pvc.status.phase == "Bound":
                return pvc_name
        except ApiException as exc:
            if exc.status != 404:
                raise

        # Check if PV exists (might exist from a previous PVC that was deleted)
        pv_exists = False
        try:
            existing_pv = await asyncio.to_thread(v1.read_persistent_volume, pv_name)
            pv_exists = True
            pv_phase = (existing_pv.status.phase or "") if existing_pv.status else ""
            if pv_phase == "Released":
                await asyncio.to_thread(v1.delete_persistent_volume, pv_name)
                pv_exists = False
                logger.info("[COMPUTE] Recreating PV %s (phase=%s)", pv_name, pv_phase)
        except ApiException as exc:
            if exc.status != 404:
                raise

        if not pv_exists:
            pv = k8s_client.V1PersistentVolume(
                metadata=k8s_client.V1ObjectMeta(
                    name=pv_name,
                    labels={
                        "tesslate.io/tier": "1",
                        "tesslate.io/volume-id": volume_id,
                    },
                ),
                spec=k8s_client.V1PersistentVolumeSpec(
                    capacity={"storage": "10Gi"},
                    access_modes=["ReadWriteOnce"],
                    persistent_volume_reclaim_policy="Retain",
                    storage_class_name="",
                    csi=k8s_client.V1CSIPersistentVolumeSource(
                        driver="btrfs.csi.tesslate.io",
                        volume_handle=volume_id,
                    ),
                    claim_ref=k8s_client.V1ObjectReference(
                        name=pvc_name,
                        namespace=ns,
                    ),
                ),
            )
            await asyncio.to_thread(v1.create_persistent_volume, body=pv)

        # Create PVC
        pvc = k8s_client.V1PersistentVolumeClaim(
            metadata=k8s_client.V1ObjectMeta(name=pvc_name, namespace=ns),
            spec=k8s_client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                storage_class_name="",
                volume_name=pv_name,
                resources=k8s_client.V1ResourceRequirements(requests={"storage": "10Gi"}),
            ),
        )
        try:
            await asyncio.to_thread(v1.create_namespaced_persistent_volume_claim, ns, pvc)
        except ApiException as exc:
            if exc.status != 409:  # Already exists
                raise

        return pvc_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def _count_active_compute_pods(self) -> int:
        """Count running tier-1 compute pods."""
        v1 = self._api()
        ns = self._namespace()
        pod_list = await asyncio.to_thread(
            v1.list_namespaced_pod,
            ns,
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
            node_name: Target node (volume locality — PV node affinity drives scheduling).
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

        await self._ensure_compute_namespace()

        pod_name = f"t1-{volume_id[:8]}-{uuid4().hex[:6]}"
        ns = self._namespace()
        devserver_image = image or settings.k8s_devserver_image
        v1 = self._api()

        # Use reusable per-volume PV/PVC (not per-pod)
        pvc_name = await self._ensure_compute_pv_pvc(volume_id, node_name)

        manifest = self._build_pod_manifest(
            pod_name=pod_name,
            namespace=ns,
            command=command,
            image=devserver_image,
            timeout=timeout,
            pvc_name=pvc_name,
        )

        try:
            await asyncio.to_thread(v1.create_namespaced_pod, ns, manifest)

            logger.info(
                "[COMPUTE] Pod %s created (PVC %s) for volume %s on node %s",
                pod_name,
                pvc_name,
                volume_id,
                node_name,
            )

            # Wait for completion
            output, exit_code = await self._wait_for_completion(pod_name, ns, timeout)
            return output, exit_code, pod_name

        finally:
            # Clean up pod only — PV/PVC are reusable across pods
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

    async def create_ephemeral_pod(
        self,
        volume_id: str,
        node_name: str,
        project_id: str,
        image: str | None = None,
    ) -> tuple[str, str]:
        """Create a long-lived ephemeral pod for interactive use (e.g. terminal).

        Unlike run_command(), the pod stays alive until explicitly deleted.
        Caller is responsible for cleanup via delete_pod().

        Returns:
            (pod_name, namespace)
        """
        from ..config import get_settings

        settings = get_settings()

        count = await self._count_active_compute_pods()
        if count >= settings.compute_max_concurrent_pods:
            raise ComputeQuotaExceeded(
                f"Compute pod limit reached ({count}/{settings.compute_max_concurrent_pods})"
            )

        await self._ensure_compute_namespace()

        pod_name = f"eph-{volume_id[:8]}-{uuid4().hex[:6]}"
        ns = self._namespace()
        devserver_image = image or settings.k8s_devserver_image
        v1 = self._api()

        # Use reusable per-volume PV/PVC (not per-pod)
        pvc_name = await self._ensure_compute_pv_pvc(volume_id, node_name)

        manifest = self._build_pod_manifest(
            pod_name=pod_name,
            namespace=ns,
            command=["sleep", "infinity"],
            image=devserver_image,
            timeout=1800,
            pvc_name=pvc_name,
        )
        # Add ephemeral-specific labels
        manifest.metadata.labels["tesslate.io/component"] = "ephemeral-shell"
        manifest.metadata.labels["tesslate.io/project-id"] = project_id

        await asyncio.to_thread(v1.create_namespaced_pod, ns, manifest)

        logger.info(
            "[COMPUTE] Ephemeral pod %s created (PVC %s) on node %s",
            pod_name,
            pvc_name,
            node_name,
        )
        return pod_name, ns

    async def delete_pod(self, pod_name: str, namespace: str | None = None) -> None:
        """Best-effort delete a pod. Swallows 404. PV/PVC are reusable and not deleted."""
        ns = namespace or self._namespace()
        v1 = self._api()
        try:
            await asyncio.to_thread(
                v1.delete_namespaced_pod,
                pod_name,
                ns,
                grace_period_seconds=0,
            )
            logger.info("[COMPUTE] Deleted pod %s in %s", pod_name, ns)
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("[COMPUTE] Failed to delete pod %s: %s", pod_name, exc.reason)

    async def wait_for_pod_running(
        self,
        pod_name: str,
        namespace: str | None = None,
        timeout: int = 15,
    ) -> None:
        """Poll until pod reaches Running phase. Raises RuntimeError on failure/timeout."""
        ns = namespace or self._namespace()
        v1 = self._api()
        for _ in range(timeout):
            await asyncio.sleep(1)
            try:
                pod = await asyncio.to_thread(v1.read_namespaced_pod, pod_name, ns)
                phase = (pod.status.phase or "").lower()
                if phase == "running":
                    return
                if phase in ("failed", "unknown"):
                    raise RuntimeError(f"Pod {pod_name} failed: {phase}")
            except ApiException as exc:
                if exc.status == 404:
                    raise RuntimeError(f"Pod {pod_name} disappeared") from exc
                raise
        raise RuntimeError(f"Pod {pod_name} did not become Running within {timeout}s")

    async def reap_orphaned_pods(self, max_age_seconds: int = 900) -> int:
        """Delete pods older than max_age_seconds. Returns count deleted."""
        from datetime import datetime

        ns = self._namespace()
        v1 = self._api()
        now = datetime.now(UTC)
        reaped = 0  # noqa: F841

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
                # PV/PVC are reusable — do NOT delete them when reaping pods
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

        results = await asyncio.gather(*[_delete_pod(name, age) for name, age in to_reap])
        return sum(1 for r in results if r)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_pod_manifest(
        self,
        *,
        pod_name: str,
        namespace: str,
        command: list[str],
        image: str,
        timeout: int = 120,
        pvc_name: str | None = None,
    ) -> k8s_client.V1Pod:
        """Build the ephemeral pod manifest (CSI PVC volume, PSA restricted)."""
        pvc_name = pvc_name or f"compute-pvc-{pod_name}"
        return k8s_client.V1Pod(
            metadata=k8s_client.V1ObjectMeta(
                name=pod_name,
                namespace=namespace,
                labels={
                    "tesslate.io/tier": "1",
                    "app.kubernetes.io/part-of": "tesslate",
                },
            ),
            spec=k8s_client.V1PodSpec(
                priority_class_name="tesslate-ephemeral",
                restart_policy="Never",
                active_deadline_seconds=timeout + 30,  # K8s safety net slightly after app timeout
                termination_grace_period_seconds=5,
                automount_service_account_token=False,
                security_context=k8s_client.V1PodSecurityContext(
                    run_as_user=1000,
                    run_as_group=1000,
                    run_as_non_root=True,
                    fs_group=1000,
                    seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
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
                            requests={"cpu": "50m", "memory": "256Mi"},
                            limits={"cpu": "2000m", "memory": "4Gi"},
                        ),
                        security_context=k8s_client.V1SecurityContext(
                            run_as_user=1000,
                            run_as_group=1000,
                            allow_privilege_escalation=False,
                            capabilities=k8s_client.V1Capabilities(drop=["ALL"]),
                            seccomp_profile=k8s_client.V1SeccompProfile(type="RuntimeDefault"),
                        ),
                    ),
                ],
                volumes=[
                    k8s_client.V1Volume(
                        name="project-source",
                        persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=pvc_name,
                        ),
                    ),
                ],
            ),
        )

    def _pod_failure_reason(self, pod: k8s_client.V1Pod) -> str:
        """Extract a human-readable failure reason from pod status."""
        parts: list[str] = []

        # Check container statuses for waiting/terminated reasons
        for cs in pod.status.container_statuses or []:
            if cs.state:
                if cs.state.waiting and cs.state.waiting.reason:
                    parts.append(
                        f"{cs.name}: {cs.state.waiting.reason} — {cs.state.waiting.message or ''}"
                    )
                if cs.state.terminated and cs.state.terminated.reason:
                    parts.append(
                        f"{cs.name}: {cs.state.terminated.reason} — {cs.state.terminated.message or ''}"
                    )

        # Check pod-level conditions (e.g., Unschedulable, volume mount failures)
        for cond in pod.status.conditions or []:
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
                pod = await asyncio.to_thread(v1.read_namespaced_pod, pod_name, namespace)
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
                        "[COMPUTE] Pod %s failed: %s",
                        pod_name,
                        reason,
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
    # Tier 2: Full Environment Lifecycle
    # ------------------------------------------------------------------

    async def start_environment(
        self,
        project,
        containers: list,
        connections: list,
        user_id: UUID,
        db: AsyncSession,
        progress_queue: asyncio.Queue | None = None,
    ) -> dict[str, str]:
        """Create namespace + deployments + services + ingress for a v2 project.

        Acquires a per-project distributed lock to prevent concurrent
        start/stop races (e.g., two browser tabs clicking Start).

        Returns: {container_directory: preview_url}
        """
        from .distributed_lock import get_distributed_lock

        lock = get_distributed_lock()
        async with lock.hold(f"env:{project.id}", ttl_seconds=600):
            return await self._start_environment_inner(
                project, containers, connections, user_id, db, progress_queue
            )

    async def _start_environment_inner(
        self,
        project,
        containers: list,
        connections: list,
        user_id: UUID,
        db: AsyncSession,
        progress_queue: asyncio.Queue | None = None,
    ) -> dict[str, str]:
        """Inner start logic, called under the per-project lock."""
        if project.environment_status == "provisioning":
            raise RuntimeError("Cannot start environment: project is still being provisioned")

        from ..config import get_settings
        from .orchestration.kubernetes.helpers import (
            create_ingress_manifest,
            create_network_policy_manifest,
            create_service_manifest,
            create_v2_dev_deployment,
            create_v2_project_pv,
            create_v2_project_pvc,
            create_v2_service_deployment,
            create_v2_service_pv,
            create_v2_service_pvc,
        )
        from .secret_manager_env import build_env_overrides
        from .service_definitions import ServiceType, get_service
        from .volume_manager import get_volume_manager

        settings = get_settings()
        k8s = self._k8s_client()
        volume_id = project.volume_id
        namespace = f"proj-{project.id}"

        # WebSocket progress
        from ..routers.chat import get_chat_connection_manager

        ws_manager = get_chat_connection_manager()

        async def send_progress(phase: str, message: str, progress: int, **kwargs):
            try:
                status = {
                    "container_status": "starting",
                    "phase": phase,
                    "message": message,
                    "progress": progress,
                    **kwargs,
                }
                await ws_manager.send_status_update(user_id, project.id, status)
            except Exception:
                pass
            if progress_queue is not None:
                with contextlib.suppress(Exception):
                    await progress_queue.put(
                        {"phase": phase, "message": message, "progress": progress}
                    )

        # 1. Calculate placement budget for the entire placement unit.
        budget = placement_budget(containers)
        logger.info(
            "[COMPUTE-T2] Placement budget for project %s: %dm CPU, %d MiB mem",
            project.id,
            budget.cpu_millicores,
            budget.memory_mib,
        )

        # 2. Ensure volume is cached on a schedulable compute node with
        #    enough headroom for the placement unit. The Hub handles data
        #    transfer internally (peer-transfer or CAS restore) and
        #    prefers the node where the volume already lives (fast path).
        vm = get_volume_manager()
        candidate_nodes = await self._get_schedulable_nodes()
        if not candidate_nodes:
            raise RuntimeError("No schedulable compute nodes available")
        node_name = await vm.ensure_cached(
            volume_id,
            candidate_nodes=candidate_nodes,
            budget_cpu=budget.cpu_millicores,
            budget_mem=budget.memory_mib * 1024 * 1024,  # MiB → bytes for Hub
        )

        # 3. Idempotent start: clean up any existing namespace before
        #    creating fresh. This replaces the old _migrate_placement_unit
        #    flow — no separate migration code path. The Hub already moved
        #    the data in ensure_cached; we just manage K8s resources.
        if project.compute_tier == "environment":
            await send_progress("migrating", "Cleaning up old environment...", 5)
            await self._stop_environment_inner(project, db)

        # 3. Separate service and dev containers
        service_containers = [
            c for c in containers if getattr(c, "container_type", "base") == "service"
        ]
        dev_containers = [
            c for c in containers if getattr(c, "container_type", "base") != "service"
        ]

        await send_progress("creating_namespace", "Creating project namespace...", 10)

        # 3. Create namespace — "baseline" PSA is fine since we use CSI PVCs (not hostPath)
        await k8s.create_namespace_if_not_exists(
            namespace=namespace,
            project_id=str(project.id),
            user_id=user_id,
            extra_labels={"pod-security.kubernetes.io/enforce": "baseline"},
        )

        # 4. NetworkPolicy for isolation
        net_policy = create_network_policy_manifest(namespace=namespace, project_id=project.id)
        await k8s.apply_network_policy(net_policy, namespace)

        # 5. Copy TLS secret if configured
        if settings.k8s_wildcard_tls_secret:
            await k8s.copy_wildcard_tls_secret(namespace)

        # 5b. Create project PV + PVC (CSI-backed)
        if not node_name:
            raise RuntimeError(
                f"Project {project.id} has no cache_node after ensure_cached. "
                "Cannot create PV without a target node."
            )
        v1 = self._api()
        project_pv = create_v2_project_pv(volume_id, node_name, project.id)
        project_pvc = create_v2_project_pvc(namespace, volume_id, project.id, user_id)
        try:
            await asyncio.to_thread(v1.create_persistent_volume, body=project_pv)
            logger.info("[COMPUTE-T2] Created PV pv-%s", volume_id)
        except ApiException as e:
            if e.status != 409:  # Already exists — fine on restart
                raise
            logger.debug("[COMPUTE-T2] PV pv-%s already exists", volume_id)
        await k8s.create_pvc(project_pvc, namespace)

        container_urls: dict[str, str] = {}

        # 6. Deploy service containers first
        if service_containers:
            await send_progress("starting_services", "Starting service containers...", 20)

        for svc_container in service_containers:
            service_def = get_service(svc_container.service_slug)
            if not service_def:
                logger.warning(
                    "[COMPUTE-T2] No service definition for slug=%s, skipping",
                    svc_container.service_slug,
                )
                continue

            if service_def.service_type == ServiceType.EXTERNAL:
                continue
            if getattr(svc_container, "deployment_mode", "container") == "external":
                continue

            svc_dir = _sanitize_k8s_name(svc_container.service_slug or svc_container.name)

            # Create service subvolume + PV/PVC only if service needs persistent storage
            svc_pvc_name = None
            if service_def.volumes:
                vm = get_volume_manager()
                svc_volume_id = await vm.create_service_volume(volume_id, svc_dir)

                svc_pvc_name = f"svc-{svc_dir}-data"
                svc_pv = create_v2_service_pv(svc_volume_id, node_name, project.id, svc_dir)
                svc_pvc = create_v2_service_pvc(
                    namespace, svc_volume_id, project.id, user_id, svc_dir
                )
                try:
                    await asyncio.to_thread(v1.create_persistent_volume, body=svc_pv)
                    logger.info(
                        "[COMPUTE-T2] Created PV pv-%s for service %s", svc_volume_id, svc_dir
                    )
                except ApiException as e:
                    if e.status != 409:
                        raise
                    logger.debug("[COMPUTE-T2] PV pv-%s already exists", svc_volume_id)
                await k8s.create_pvc(svc_pvc, namespace)

            # Build env
            env_overrides = await build_env_overrides(db, project.id, [svc_container])
            extra_env = env_overrides.get(svc_container.id, {})
            merged_env = {**service_def.environment_vars, **extra_env}
            svc_port = service_def.internal_port or service_def.default_port or 5432

            deployment = create_v2_service_deployment(
                namespace=namespace,
                project_id=project.id,
                user_id=user_id,
                container_id=svc_container.id,
                container_directory=svc_dir,
                image=service_def.docker_image,
                port=svc_port,
                environment_vars=merged_env,
                volumes=service_def.volumes,
                service_pvc_name=svc_pvc_name,
                command=service_def.command,
                health_check=service_def.health_check,
                service_slug=svc_container.service_slug,
                preferred_node=node_name,
            )
            await k8s.create_deployment(deployment, namespace)

            # ClusterIP service for internal DNS
            svc_k8s_name = f"svc-{svc_dir}"
            svc = k8s_client.V1Service(
                metadata=k8s_client.V1ObjectMeta(
                    name=svc_k8s_name,
                    namespace=namespace,
                    labels={
                        "tesslate.io/project-id": str(project.id),
                        "tesslate.io/container-id": str(svc_container.id),
                        "tesslate.io/container-directory": svc_dir,
                        "tesslate.io/component": "service-container",
                    },
                ),
                spec=k8s_client.V1ServiceSpec(
                    selector={"tesslate.io/container-id": str(svc_container.id)},
                    ports=[
                        k8s_client.V1ServicePort(
                            port=svc_port, target_port=svc_port, protocol="TCP"
                        )
                    ],
                    type="ClusterIP",
                ),
            )
            await k8s.create_service(svc, namespace)
            logger.info("[COMPUTE-T2] Service %s deployed in %s", svc_dir, namespace)

        # 7. Deploy dev containers
        from .base_config_parser import get_node_modules_fix_prefix

        node_modules_prefix = get_node_modules_fix_prefix()

        if dev_containers:
            await send_progress("starting_dev_servers", "Starting development servers...", 50)

        for container in dev_containers:
            container_directory = resolve_k8s_container_dir(container)
            working_directory = container.directory or "."

            startup_command = container.startup_command or "sleep infinity"
            port = container.effective_port

            # Prepend node_modules/.bin permission fix
            startup_command = node_modules_prefix + startup_command

            # Build env overrides
            env_overrides = await build_env_overrides(db, project.id, [container])
            extra_env = env_overrides.get(container.id, {})

            # Inject sibling container URLs for service discovery
            for sibling in containers:
                if sibling.id == container.id:
                    continue
                if getattr(sibling, "container_type", "base") == "service":
                    continue
                sib_name = sibling.name.upper().replace("-", "_")
                sib_k8s_name = resolve_k8s_container_dir(sibling)
                sib_port = sibling.effective_port
                sib_url = f"http://dev-{sib_k8s_name}:{sib_port}"
                extra_env.setdefault(f"{sib_name}_URL", sib_url)
                extra_env.setdefault(f"VITE_{sib_name}_URL", sib_url)

            deployment = create_v2_dev_deployment(
                namespace=namespace,
                project_id=project.id,
                user_id=user_id,
                container_id=container.id,
                container_directory=container_directory,
                image=settings.k8s_devserver_image,
                port=port,
                startup_command=startup_command,
                pvc_name="project-source",
                working_directory=working_directory,
                image_pull_policy=settings.k8s_image_pull_policy,
                image_pull_secret=settings.k8s_image_pull_secret or None,
                extra_env=extra_env,
                preferred_node=node_name,
            )
            await k8s.create_deployment(deployment, namespace)

            # Service + Ingress
            service = create_service_manifest(
                namespace=namespace,
                project_id=project.id,
                container_id=container.id,
                container_directory=container_directory,
                port=port,
            )
            await k8s.create_service(service, namespace)

            ingress = create_ingress_manifest(
                namespace=namespace,
                project_id=project.id,
                container_id=container.id,
                container_directory=container_directory,
                project_slug=project.slug,
                port=port,
                domain=settings.app_domain,
                ingress_class=settings.k8s_ingress_class,
                tls_secret=settings.k8s_wildcard_tls_secret or None,
            )
            await k8s.create_ingress(ingress, namespace)

            protocol = settings.k8s_container_url_protocol
            hostname = f"{project.slug}-{container_directory}.{settings.app_domain}"
            preview_url = f"{protocol}://{hostname}"
            container_urls[container_directory] = preview_url

            logger.info("[COMPUTE-T2] Dev container %s → %s", container_directory, preview_url)

        # 8. Verify at least one dev pod is schedulable (catch PSA / image pull failures early)
        if dev_containers:
            await send_progress("verifying_pods", "Verifying pods are starting...", 80)
            v1 = self._api()
            for _attempt in range(15):
                await asyncio.sleep(2)
                pod_list = await asyncio.to_thread(
                    v1.list_namespaced_pod,
                    namespace,
                    label_selector="tesslate.io/tier=2,tesslate.io/component=dev-container",
                )
                pods = pod_list.items or []
                if any(
                    (p.status.phase or "").lower() in ("running", "pending")
                    and not any(
                        cs.state
                        and cs.state.waiting
                        and cs.state.waiting.reason
                        in ("ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff")
                        for cs in (p.status.container_statuses or [])
                    )
                    for p in pods
                ):
                    break

                # Check for ReplicaSet events that indicate permanent failures
                if pods:
                    # Pods exist but may be stuck — keep waiting
                    continue

                # No pods at all — check ReplicaSet for creation errors
                try:
                    apps_v1 = k8s_client.AppsV1Api(v1.api_client)
                    rs_list = await asyncio.to_thread(
                        apps_v1.list_namespaced_replica_set,
                        namespace,
                        label_selector="tesslate.io/tier=2,tesslate.io/component=dev-container",
                    )
                    for rs in rs_list.items or []:
                        for cond in rs.status.conditions or []:
                            if cond.type == "ReplicaFailure" and cond.status == "True":
                                raise RuntimeError(f"Pod creation failed: {cond.message}")
                except RuntimeError:
                    raise
                except Exception:
                    pass  # Non-fatal — keep polling
            else:
                logger.error("[COMPUTE-T2] No pods started in %s after 30s", namespace)
                raise RuntimeError(
                    f"No dev pods started in namespace {namespace} — "
                    f"check events: kubectl get events -n {namespace}"
                )

        # 9. Update project state
        project.compute_tier = "environment"
        project.environment_status = "active"
        project.hibernated_at = None
        project.last_activity = datetime.now(UTC)
        await db.commit()

        # 10. Transfer ownership to the node where pods are running.
        # Best-effort — if Hub is briefly unavailable, the next ensure_cached
        # will fix it. No stale cache_node in DB to worry about.
        try:
            await vm.transfer_ownership(volume_id, node_name)
        except Exception:
            logger.warning(
                "[COMPUTE-T2] Ownership transfer failed for project %s — "
                "pods are running, will fix on next ensure_cached",
                project.id,
                exc_info=True,
            )

        await send_progress("ready", "Environment is ready!", 100, container_status="ready")

        logger.info(
            "[COMPUTE-T2] Environment started for project %s (%d containers)",
            project.slug,
            len(containers),
        )
        return container_urls

    async def stop_environment(self, project, db: AsyncSession) -> None:
        """Delete namespace + PVs for a v2 project. btrfs subvolumes stay on node.

        Acquires the same per-project lock as start_environment to prevent
        stop racing with a concurrent start. Callers already under the lock
        (e.g., _migrate_placement_unit) should call _stop_environment_inner
        directly to avoid deadlock.
        """
        from .distributed_lock import get_distributed_lock

        lock = get_distributed_lock()
        async with lock.hold(f"env:{project.id}", ttl_seconds=600):
            await self._stop_environment_inner(project, db)

    async def _stop_environment_inner(self, project, db: AsyncSession) -> None:
        """Inner stop logic. Call directly when already holding the env lock."""
        namespace = f"proj-{project.id}"
        k8s = self._k8s_client()
        v1 = self._api()

        # Delete namespace — cascades all namespace-scoped resources (PVCs, deployments, etc.)
        try:
            await asyncio.to_thread(k8s.core_v1.delete_namespace, name=namespace)
            logger.info("[COMPUTE-T2] Namespace %s deleted", namespace)
        except ApiException as exc:
            if exc.status != 404:
                logger.error(
                    "[COMPUTE-T2] Failed to delete namespace %s: %s", namespace, exc.reason
                )
                raise
            logger.debug("[COMPUTE-T2] Namespace %s already gone", namespace)

        # Delete cluster-scoped PVs (Retain policy keeps btrfs subvolumes intact)
        try:
            pv_list = await asyncio.to_thread(
                v1.list_persistent_volume,
                label_selector=f"tesslate.io/project-id={project.id}",
            )
            for pv in pv_list.items or []:
                pv_name = pv.metadata.name
                try:
                    await asyncio.to_thread(v1.delete_persistent_volume, name=pv_name)
                    logger.info("[COMPUTE-T2] Deleted PV %s", pv_name)
                except ApiException as e:
                    if e.status != 404:
                        logger.warning("[COMPUTE-T2] Failed to delete PV %s: %s", pv_name, e.reason)
        except ApiException as e:
            logger.warning(
                "[COMPUTE-T2] Failed to list PVs for project %s: %s", project.id, e.reason
            )

        project.compute_tier = "none"
        await db.commit()


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
