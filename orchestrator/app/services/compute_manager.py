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
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Per-request app_instance_id, set by callers (e.g. app_runtime_status.start)
# so compute lifecycle events can be fanned out to the SSE stream for the
# corresponding AppInstance. None for non-app-backed projects.
current_app_instance_id: ContextVar[UUID | None] = ContextVar(
    "current_app_instance_id", default=None
)


async def _persist_failed_state(project_id: UUID, container_ids: list[UUID]) -> None:
    """Best-effort persist of failed compute state in a fresh DB session.

    Used from ``start_environment``'s exception handler where the caller's
    session may be mid-rollback. Independent session avoids piggybacking
    on a poisoned transaction.
    """
    try:
        from sqlalchemy import update

        from ..database import AsyncSessionLocal
        from ..models import Container, Project

        async with AsyncSessionLocal() as db:
            proj = await db.get(Project, project_id)
            if proj is not None:
                proj.environment_status = "error"
                proj.active_compute_pod = None
            if container_ids:
                await db.execute(
                    update(Container).where(Container.id.in_(container_ids)).values(status="failed")
                )
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.debug("persist_failed_state ignored error", exc_info=True)


async def _emit_app_runtime(
    app_instance_id: UUID | None,
    state: str,
    *,
    containers: list | None = None,
    message: str | None = None,
) -> None:
    """Best-effort emit of an app-runtime lifecycle event."""
    if app_instance_id is None:
        return
    try:
        from .pubsub import publish_app_runtime_event

        payload = {
            "state": state,
            "ts": datetime.now(UTC).isoformat(),
        }
        if message is not None:
            payload["message"] = message
        if containers is not None:
            payload["containers"] = [
                {
                    "id": str(getattr(c, "id", "")),
                    "name": getattr(c, "name", None),
                    "status": getattr(c, "status", None) or "stopped",
                }
                for c in containers
            ]
        await publish_app_runtime_event(app_instance_id, payload)
    except Exception as e:  # noqa: BLE001
        logger.debug("emit_app_runtime ignored error: %s", e)


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

# Annotation that warm-start drift detection compares against the live Deployment
# to decide whether a re-render is needed.
SPEC_HASH_ANNOTATION = "tesslate.io/spec-hash"


_POD_TEMPLATE_REVISION = "v4"
"""Bump when the rendered Deployment pod template gains structural elements
(initContainers, volumes, additional containers) that the per-field inputs
below don't already capture. Acts as a dimension in the spec hash so
existing warm-startable Deployments cold-redeploy on the next bring-up.

History:
  v1 — original spec
  v2 — added install-tsinit initContainer + tsinit-bin emptyDir
  v3 — branched mounts on source_strategy (image vs bundle)
  v4 — empty tsinit --dir for image strategy (inherit image WORKDIR)
"""


def compute_dev_container_spec_hash(
    *,
    startup_command: str,
    image: str,
    port: int,
    working_directory: str,
    extra_env: dict[str, str] | None,
) -> str:
    """Deterministic short hash of the runtime-affecting Container spec.

    Stamped on the Deployment so warm-start can detect drift and fall through
    to a cold render. Inputs are exactly the fields that flow into the dev
    container's args/env — change the inputs and you change the rendered pod.
    """
    import hashlib
    import json

    payload = {
        "startup_command": startup_command or "",
        "image": image or "",
        "port": int(port) if port is not None else 0,
        "working_directory": working_directory or "",
        "env": sorted((extra_env or {}).items()),
        # Pod-template version: bump to invalidate cached Deployments when
        # the helper structurally changes (e.g. tsinit sideloader added).
        "pod_template_revision": _POD_TEMPLATE_REVISION,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


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


_TIER1_LABEL_SELECTOR = "tesslate.io/tier=1"
_TIER2_DEV_LABEL_SELECTOR = "tesslate.io/tier=2,tesslate.io/component=dev-container"
_COMPUTE_PRIORITY_CLASS = "tesslate-ephemeral"
_COMPUTE_RUN_AS_UID = 1000  # user, group, and fs_group for all compute pods
_COMPUTE_POD_CPU_LIMIT = "2000m"
_COMPUTE_POD_MEM_LIMIT = "4Gi"


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
                    # HTTP/HTTPS to external — IMDS (169.254.169.254) is explicitly
                    # blocked so user code running in compute pods cannot steal node
                    # IAM credentials via the AWS metadata service.
                    k8s_client.V1NetworkPolicyEgressRule(
                        to=[
                            k8s_client.V1NetworkPolicyPeer(
                                ip_block=k8s_client.V1IPBlock(
                                    cidr="0.0.0.0/0",
                                    _except=["169.254.169.254/32"],  # Block AWS IMDS
                                )
                            )
                        ],
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
        from ..config import get_settings

        s = get_settings()
        quota = k8s_client.V1ResourceQuota(
            metadata=k8s_client.V1ObjectMeta(
                name="compute-pool-quota",
                namespace=namespace,
            ),
            spec=k8s_client.V1ResourceQuotaSpec(
                hard={
                    "pods": str(s.compute_pool_max_pods),
                    "requests.cpu": s.compute_pool_cpu_request,
                    "requests.memory": s.compute_pool_memory_request,
                    "limits.cpu": s.compute_pool_cpu_limit,
                    "limits.memory": s.compute_pool_memory_limit,
                    "persistentvolumeclaims": str(s.compute_pool_max_pvcs),
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

        from ..config import get_settings

        pvc_size = get_settings().compute_pool_pvc_size

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
                    capacity={"storage": pvc_size},
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
                resources=k8s_client.V1ResourceRequirements(requests={"storage": pvc_size}),
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
            label_selector=_TIER1_LABEL_SELECTOR,
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
                label_selector=_TIER1_LABEL_SELECTOR,
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

    async def reap_orphaned_pvcs(self, grace_seconds: int = 900) -> int:
        """Delete PVCs in compute-pool that have no active pod referencing them.

        Run after reap_orphaned_pods() in the reaper loop. Deletes PVCs (and
        their backing PVs) that are older than grace_seconds and have no
        Running or Pending pod using them. Returns count of PVCs deleted.
        """
        from datetime import datetime

        ns = self._namespace()
        v1 = self._api()
        now = datetime.now(UTC)

        try:
            pvc_list = await asyncio.to_thread(v1.list_namespaced_persistent_volume_claim, ns)
        except ApiException as exc:
            if exc.status == 404:
                return 0
            raise

        if not pvc_list.items:
            return 0

        try:
            pod_list = await asyncio.to_thread(
                v1.list_namespaced_pod,
                ns,
                label_selector=_TIER1_LABEL_SELECTOR,
            )
        except ApiException as exc:
            if exc.status == 404:
                return 0
            raise

        # Build set of PVC names held by Running or Pending pods
        active_pvc_names: set[str] = set()
        for pod in pod_list.items:
            pod_phase = (pod.status.phase or "") if pod.status else ""
            if pod_phase in ("Running", "Pending"):
                for volume in pod.spec.volumes or []:
                    if volume.persistent_volume_claim:
                        active_pvc_names.add(volume.persistent_volume_claim.claim_name)

        reaped = 0
        for pvc in pvc_list.items:
            pvc_name = pvc.metadata.name
            if pvc_name in active_pvc_names:
                continue

            creation = pvc.metadata.creation_timestamp
            if creation is None:
                continue
            age = (now - creation).total_seconds()
            if age < grace_seconds:
                continue

            pv_name = (pvc.spec.volume_name or "") if pvc.spec else ""

            try:
                await asyncio.to_thread(v1.delete_namespaced_persistent_volume_claim, pvc_name, ns)
                logger.warning("[COMPUTE] Reaped orphaned PVC %s (age: %.0fs)", pvc_name, age)
                reaped += 1
            except ApiException as exc:
                if exc.status != 404:
                    logger.warning("[COMPUTE] Failed to reap PVC %s: %s", pvc_name, exc.reason)
                continue

            if pv_name:
                try:
                    await asyncio.to_thread(v1.delete_persistent_volume, pv_name)
                    logger.warning("[COMPUTE] Deleted orphaned PV %s", pv_name)
                except ApiException as exc:
                    if exc.status != 404:
                        logger.warning("[COMPUTE] Failed to delete PV %s: %s", pv_name, exc.reason)

        return reaped

    async def delete_compute_pool_pvc(self, volume_id: str) -> None:
        """Delete the compute-pool PVC and PV for a project volume on deletion.

        Called from the project deletion flow to prevent quota exhaustion.
        Swallows 404 — safe to call even if no compute pod was ever run.
        """
        ns = self._namespace()
        v1 = self._api()
        pvc_name = f"vol-pvc-{volume_id}"
        pv_name = f"vol-pv-{volume_id}"

        try:
            await asyncio.to_thread(v1.delete_namespaced_persistent_volume_claim, pvc_name, ns)
            logger.info("[COMPUTE] Deleted compute-pool PVC %s for volume %s", pvc_name, volume_id)
        except ApiException as exc:
            if exc.status != 404:
                logger.warning(
                    "[COMPUTE] Failed to delete compute-pool PVC %s: %s", pvc_name, exc.reason
                )

        try:
            await asyncio.to_thread(v1.delete_persistent_volume, pv_name)
            logger.info("[COMPUTE] Deleted compute-pool PV %s for volume %s", pv_name, volume_id)
        except ApiException as exc:
            if exc.status != 404:
                logger.warning(
                    "[COMPUTE] Failed to delete compute-pool PV %s: %s", pv_name, exc.reason
                )

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
        state_model: str = "per_install_volume",
    ) -> k8s_client.V1Pod:
        """Build the ephemeral pod manifest (CSI PVC volume, PSA restricted).

        Tier-1 hardening (Phase 4 bridge):

        * **tmpfs at ``/tmp``** (``emptyDir{medium: Memory, sizeLimit: 256Mi}``)
          is always mounted. Tools that scribble to ``/tmp`` (the universal
          escape valve) land in memory and vanish on pod terminate. Bounded
          to 256Mi so a misbehaving tool can't pin all of node RAM.
        * **``readOnlyRootFilesystem: true``** is set ONLY when the manifest's
          ``runtime.state_model='stateless'``. Apps with declared write
          scopes (per_install_volume, service_pvc, shared_volume, external)
          legitimately write outside ``/tmp`` to mounted volumes — RO root
          would break them. Stateless apps have no such write contract, so
          RO root catches the silent-write class loudly.
        """
        pvc_name = pvc_name or f"compute-pvc-{pod_name}"
        # See state_model gating above. We only flip readOnlyRootFilesystem
        # for stateless contracts — anything else has a declared write
        # surface that RO root would break.
        read_only_root = state_model == "stateless"

        return k8s_client.V1Pod(
            metadata=k8s_client.V1ObjectMeta(
                name=pod_name,
                namespace=namespace,
                labels={
                    "tesslate.io/tier": "1",
                    "tesslate.io/state-model": state_model,
                    "app.kubernetes.io/part-of": "tesslate",
                },
            ),
            spec=k8s_client.V1PodSpec(
                priority_class_name=_COMPUTE_PRIORITY_CLASS,
                restart_policy="Never",
                active_deadline_seconds=timeout + 30,  # K8s safety net slightly after app timeout
                termination_grace_period_seconds=5,
                automount_service_account_token=False,
                security_context=k8s_client.V1PodSecurityContext(
                    run_as_user=_COMPUTE_RUN_AS_UID,
                    run_as_group=_COMPUTE_RUN_AS_UID,
                    run_as_non_root=True,
                    fs_group=_COMPUTE_RUN_AS_UID,
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
                            # tmpfs scratch for /tmp writes. Always mounted
                            # so tools have a known-safe write target even
                            # when readOnlyRootFilesystem is on.
                            k8s_client.V1VolumeMount(
                                name="tmp",
                                mount_path="/tmp",
                            ),
                        ],
                        resources=k8s_client.V1ResourceRequirements(
                            requests={
                                "cpu": _DEV_CONTAINER_CPU_REQUEST,
                                "memory": _DEV_CONTAINER_MEM_REQUEST,
                            },
                            limits={
                                "cpu": _COMPUTE_POD_CPU_LIMIT,
                                "memory": _COMPUTE_POD_MEM_LIMIT,
                            },
                        ),
                        security_context=k8s_client.V1SecurityContext(
                            run_as_user=_COMPUTE_RUN_AS_UID,
                            run_as_group=_COMPUTE_RUN_AS_UID,
                            allow_privilege_escalation=False,
                            read_only_root_filesystem=read_only_root,
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
                    k8s_client.V1Volume(
                        name="tmp",
                        empty_dir=k8s_client.V1EmptyDirVolumeSource(
                            medium="Memory",
                            size_limit="256Mi",
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
        *,
        app_instance_id: UUID | None = None,
    ) -> dict[str, str]:
        """Create namespace + deployments + services + ingress for a v2 project.

        Acquires a per-project distributed lock to prevent concurrent
        start/stop races (e.g., two browser tabs clicking Start).

        Returns: {container_directory: preview_url}
        """
        from .distributed_lock import get_distributed_lock

        # Fall back to the contextvar if no explicit kwarg given, so callers
        # that go through orchestrator.start_project (which can't pass kwargs)
        # still get app-runtime fanout.
        effective_app_instance = app_instance_id or current_app_instance_id.get()

        lock = get_distributed_lock()
        async with lock.hold(f"env:{project.id}", ttl_seconds=600):
            try:
                return await self._start_environment_inner(
                    project,
                    containers,
                    connections,
                    user_id,
                    db,
                    progress_queue,
                    app_instance_id=effective_app_instance,
                )
            except Exception as exc:
                await _emit_app_runtime(
                    effective_app_instance,
                    "error",
                    containers=containers,
                    message=str(exc),
                )
                # Persist failed state in a fresh session so /runtime polls
                # converge with the SSE emit instead of advertising stale
                # "running" state.
                await _persist_failed_state(project.id, [c.id for c in containers])
                raise

    async def _compute_expected_spec_hashes(
        self, project, containers: list, db: AsyncSession
    ) -> dict[str, str]:
        """Mirror the deploy-loop's input shaping to predict each dev
        container's ``tesslate.io/spec-hash``. Used by warm-start drift
        detection to decide whether the live Deployment is still in sync
        with the Container model.

        Keys are ``container_directory`` (matches the
        ``tesslate.io/container-directory`` label on Deployments). Service
        containers are excluded — they get a different deployment helper.
        """
        from ..config import get_settings
        from .base_config_parser import get_node_modules_fix_prefix
        from .secret_manager_env import build_env_overrides

        settings = get_settings()
        node_modules_prefix = get_node_modules_fix_prefix()

        dev_containers = [
            c for c in containers if getattr(c, "container_type", "base") != "service"
        ]
        env_overrides = await build_env_overrides(db, project.id, dev_containers)

        out: dict[str, str] = {}
        for container in dev_containers:
            cdir = resolve_k8s_container_dir(container)
            startup = container.startup_command or "sleep infinity"
            startup = node_modules_prefix + startup
            port = container.effective_port
            working_dir = container.directory or "."

            extra_env = dict(env_overrides.get(container.id, {}))
            for sibling in dev_containers:
                if sibling.id == container.id:
                    continue
                sib_name = sibling.name.upper().replace("-", "_")
                sib_k8s = resolve_k8s_container_dir(sibling)
                sib_port = sibling.effective_port
                sib_url = f"http://dev-{sib_k8s}:{sib_port}"
                extra_env.setdefault(f"{sib_name}_URL", sib_url)
                extra_env.setdefault(f"VITE_{sib_name}_URL", sib_url)

            container_env_dict = container.environment_vars or {}
            legacy_env_image = container_env_dict.get("TSL_CONTAINER_IMAGE")
            effective_image = container.image or legacy_env_image or settings.k8s_devserver_image
            prefix = (settings.app_image_registry_prefix or "").strip()
            if prefix and effective_image and "/" not in effective_image:
                effective_image = f"{prefix.rstrip('/')}/{effective_image}"

            out[cdir] = compute_dev_container_spec_hash(
                startup_command=startup,
                image=effective_image,
                port=port,
                working_directory=working_dir,
                extra_env=extra_env,
            )
        return out

    async def _detect_spec_drift(
        self, project, containers: list, namespace: str, db: AsyncSession
    ) -> bool:
        """Return True if any live dev Deployment's ``tesslate.io/spec-hash``
        annotation differs from what the Container model would now render.

        On any error during the comparison (API failure, label miss, etc.)
        return True — the safe fallback is to cold-render so the manifest
        re-applies. Legacy Deployments without the annotation always count
        as drift, which forces a one-time re-apply across upgraded clusters.
        """
        try:
            v1 = self._api()
            apps_v1 = k8s_client.AppsV1Api(v1.api_client)
            live = await asyncio.to_thread(
                apps_v1.list_namespaced_deployment,
                namespace,
                label_selector=_TIER2_DEV_LABEL_SELECTOR,
            )
            live_hashes: dict[str, str | None] = {}
            for dep in live.items or []:
                cdir = (dep.metadata.labels or {}).get("tesslate.io/container-directory")
                if not cdir:
                    continue
                live_hashes[cdir] = (dep.metadata.annotations or {}).get(SPEC_HASH_ANNOTATION)

            expected = await self._compute_expected_spec_hashes(project, containers, db)
            for cdir, exp_hash in expected.items():
                if live_hashes.get(cdir) != exp_hash:
                    logger.info(
                        "[COMPUTE-T2] Spec drift in %s for %s (live=%s expected=%s) — cold render",
                        namespace,
                        cdir,
                        live_hashes.get(cdir),
                        exp_hash,
                    )
                    return True
            return False
        except Exception as e:
            logger.warning(
                "[COMPUTE-T2] Drift check failed in %s (%s) — cold render to be safe",
                namespace,
                e,
            )
            return True

    async def _start_environment_inner(
        self,
        project,
        containers: list,
        connections: list,
        user_id: UUID,
        db: AsyncSession,
        progress_queue: asyncio.Queue | None = None,
        *,
        app_instance_id: UUID | None = None,
    ) -> dict[str, str]:
        """Inner start logic, called under the per-project lock."""
        await _emit_app_runtime(
            app_instance_id, "pending", containers=containers, message="Acquired lock"
        )
        if project.environment_status == "provisioning":
            raise RuntimeError("Cannot start environment: project is still being provisioned")

        # Skip job-only containers — they're invoked as K8s Jobs by schedules,
        # never as long-running Deployments. Filter early so downstream sizing,
        # placement, and deployment loops never see them.
        containers = [c for c in containers if (getattr(c, "status", None) != "job_only")]

        # Persist "starting" so late-joining SSE snapshots (which read
        # Container.status via _build_runtime_payload) see the transition
        # instead of a stale "stopped" that racing auto-start logic could
        # re-trigger.
        for c in containers:
            c.status = "starting"
        await db.commit()
        if not containers:
            logger.info(
                "[COMPUTE-T2] start_environment: project %s has only job-only containers — no Deployments to create",
                project.id,
            )
            return {}

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

        # Map internal phases to coarse app-runtime states for SSE consumers.
        _phase_to_state = {
            "migrating": "starting",
            "creating_namespace": "starting",
            "starting_services": "pulling",
            "starting_dev_servers": "pulling",
            "verifying_pods": "starting",
            "ready": "running",
        }

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
            # App-runtime SSE fanout (best-effort, never blocks).
            mapped = _phase_to_state.get(phase)
            if mapped is not None:
                await _emit_app_runtime(
                    app_instance_id,
                    mapped,
                    containers=containers,
                    message=message,
                )

        # 0. Warm-start fast path (HF-Spaces-style wake):
        #    If the namespace is already Active with Deployments, just
        #    scale replicas back to 1 and wait for Ready. This avoids the
        #    60-120s namespace-terminate race and keeps the ingress URL
        #    stable across Stop→Start cycles.
        v1 = self._api()
        ns_phase: str | None = None
        try:
            ns_obj = await asyncio.to_thread(v1.read_namespace, name=namespace)
            ns_phase = ((ns_obj.status.phase or "").lower()) if ns_obj.status else None
        except ApiException as exc:
            if exc.status != 404:
                raise

        if ns_phase == "terminating":
            # Previous teardown still in progress (e.g., hand-deleted
            # namespace, reaper). Wait briefly for GC to finish, then fall
            # through to cold bootstrap on the next iteration.
            logger.info("[COMPUTE-T2] Namespace %s is Terminating — waiting up to 30s", namespace)
            for _ in range(15):
                await asyncio.sleep(2)
                try:
                    await asyncio.to_thread(v1.read_namespace, name=namespace)
                except ApiException as exc:
                    if exc.status == 404:
                        ns_phase = None
                        break
                    raise
            else:
                raise RuntimeError(f"Namespace {namespace} stuck Terminating — retry shortly")

        if ns_phase == "active":
            # Drift check: if the live Deployment's spec annotation no longer
            # matches the Container model (config.json edits, image swap, env
            # changes), skip warm-start and fall through to cold-render so
            # the manifest is re-applied with the new spec.
            drift = await self._detect_spec_drift(project, containers, namespace, db)
            if drift:
                ns_phase = None
                logger.info(
                    "[COMPUTE-T2] Skipping warm-start for %s — drift detected, cold-rendering",
                    namespace,
                )

        if ns_phase == "active":
            await send_progress("creating_namespace", "Waking environment...", 20)
            patched = await self._scale_project_deployments(namespace, project.id, replicas=1)
            if patched > 0:
                logger.info(
                    "[COMPUTE-T2] Warm-start: scaled %d deployments in %s to 1",
                    patched,
                    namespace,
                )
                await send_progress("verifying_pods", "Waking container...", 60)

                # Wait for at least one dev pod to reach Running (same
                # polling loop as cold bootstrap). Up to 60s.
                for _attempt in range(30):
                    await asyncio.sleep(2)
                    pod_list = await asyncio.to_thread(
                        v1.list_namespaced_pod,
                        namespace,
                        label_selector=_TIER2_DEV_LABEL_SELECTOR,
                    )
                    pods = pod_list.items or []
                    if any(
                        (p.status.phase or "").lower() == "running"
                        and not any(
                            cs.state
                            and cs.state.waiting
                            and cs.state.waiting.reason
                            in (
                                "ImagePullBackOff",
                                "ErrImagePull",
                                "CrashLoopBackOff",
                            )
                            for cs in (p.status.container_statuses or [])
                        )
                        for p in pods
                    ):
                        break
                else:
                    raise RuntimeError(
                        f"Warm-start: pods in {namespace} did not reach Running in 60s"
                    )

                # Re-derive container URLs deterministically (same logic
                # as cold bootstrap — the ingress host is an immutable
                # function of project.slug + container directory, or the
                # creator-branded app handle for AppInstance projects).
                from ..config import get_settings
                from .apps.runtime_urls import (
                    container_url as _container_url,
                )
                from .apps.runtime_urls import (
                    resolve_app_url_for_container,
                )

                _settings = get_settings()
                container_urls: dict[str, str] = {}
                dev_containers_for_urls = [
                    c for c in containers if getattr(c, "container_type", "base") != "service"
                ]
                from ..models import PROJECT_KIND_APP_RUNTIME

                for c in dev_containers_for_urls:
                    cdir = resolve_k8s_container_dir(c)
                    preview: str | None = None
                    if getattr(project, "project_kind", None) == PROJECT_KIND_APP_RUNTIME:
                        preview = await resolve_app_url_for_container(
                            db,
                            c,
                            protocol=_settings.k8s_container_url_protocol,
                        )
                    if preview is None:
                        preview = _container_url(
                            project_slug=project.slug,
                            container_dir_or_name=cdir,
                            app_domain=_settings.app_domain,
                            protocol=_settings.k8s_container_url_protocol,
                        )
                    container_urls[cdir] = preview

                project.compute_tier = "environment"
                project.environment_status = "active"
                project.hibernated_at = None
                project.last_activity = datetime.now(UTC)
                for c in containers:
                    c.status = "running"
                await db.commit()

                await send_progress("ready", "Environment is ready!", 100, container_status="ready")
                logger.info(
                    "[COMPUTE-T2] Warm-start complete for project %s (%d deployments)",
                    project.slug,
                    patched,
                )
                return container_urls
            # Namespace exists but has no Deployments (drift) — fall through
            # to cold bootstrap below to recreate from manifests.
            logger.info(
                "[COMPUTE-T2] Namespace %s exists but has no deployments — cold bootstrap",
                namespace,
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
            # Retain-policy PVs from a previous namespace linger in
            # Released state with a stale claimRef. A new PVC can't bind
            # until we clear it. Safe to clear: volume data is intact and
            # we're about to bind a new PVC that matches the same volume.
            try:
                await self._clear_released_pv_claimref(f"pv-{volume_id}")
            except Exception:
                logger.debug(
                    "[COMPUTE-T2] Unable to clear claimRef on pv-%s (non-fatal)",
                    volume_id,
                    exc_info=True,
                )
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

            # Apps-installed service containers may override the catalog image
            # via manifest compute.containers[].image → Container.image.
            effective_svc_image = svc_container.image or service_def.docker_image
            # Same registry-prefix rule as primary containers below: short
            # manifest names resolve via ECR on AWS, pass-through on minikube.
            svc_prefix = (settings.app_image_registry_prefix or "").strip()
            if svc_prefix and effective_svc_image and "/" not in effective_svc_image:
                effective_svc_image = f"{svc_prefix.rstrip('/')}/{effective_svc_image}"
            deployment = create_v2_service_deployment(
                namespace=namespace,
                project_id=project.id,
                user_id=user_id,
                container_id=svc_container.id,
                container_directory=svc_dir,
                image=effective_svc_image,
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

            # Prefer the explicit Container.image column; fall back to the
            # legacy TSL_CONTAINER_IMAGE env-smuggle for any install that
            # pre-dates the 0060 migration backfill.
            container_env = container.environment_vars or {}
            legacy_env_image = container_env.get("TSL_CONTAINER_IMAGE")
            effective_image = container.image or legacy_env_image or settings.k8s_devserver_image
            # Defensive strip: never let the legacy sentinel reach the pod.
            if legacy_env_image:
                container_env = {
                    k: v for k, v in container_env.items() if k != "TSL_CONTAINER_IMAGE"
                }
                extra_env = {k: v for k, v in extra_env.items() if k != "TSL_CONTAINER_IMAGE"}

            # App manifests ship short image names (e.g. "tesslate-markitdown:latest")
            # that minikube resolves from the node's docker daemon. On AWS the node
            # can't pull a short name, so prepend the ECR registry prefix when
            # configured. Images that already include a registry path ("/") are
            # left alone (ghcr.io/*, public/*, full ECR refs, etc.).
            prefix = (settings.app_image_registry_prefix or "").strip()
            if prefix and effective_image and "/" not in effective_image:
                effective_image = f"{prefix.rstrip('/')}/{effective_image}"

            # Propagate any ${secret:name/key} refs from the platform ns into
            # this project's ns (secretKeyRef is namespace-local). Idempotent.
            try:
                from .apps.env_resolver import extract_secret_refs
                from .apps.secret_propagator import propagate_secrets

                combined = {**(container_env or {}), **(extra_env or {})}
                refs = extract_secret_refs(combined)
                if refs:
                    await asyncio.to_thread(
                        propagate_secrets,
                        k8s.core_v1,
                        refs,
                        settings.k8s_default_namespace,
                        namespace,
                    )
            except Exception as e:
                logger.warning("secret propagation failed for project %s: %s", project.id, e)

            spec_hash = compute_dev_container_spec_hash(
                startup_command=startup_command,
                image=effective_image,
                port=port,
                working_directory=working_directory,
                extra_env=extra_env,
            )

            # App runtimes have no live agent to fix a crashed dev server, so
            # tsinit must self-heal. User workspaces keep "never" so their
            # agent can attach and diagnose the failure in place.
            from ..models import PROJECT_KIND_APP_RUNTIME

            tsinit_restart_policy = (
                "always" if project.project_kind == PROJECT_KIND_APP_RUNTIME else "never"
            )

            deployment = create_v2_dev_deployment(
                namespace=namespace,
                project_id=project.id,
                user_id=user_id,
                container_id=container.id,
                container_directory=container_directory,
                image=effective_image,
                port=port,
                startup_command=startup_command,
                # Source for the sideloaded tsinit binary. The dev container
                # may be ANY image (devserver OR an app's manifest-declared
                # image like ghcr.io/owner/app:tag), so tsinit is mounted in
                # via initContainer rather than expected on PATH.
                tsinit_source_image=settings.k8s_devserver_image,
                pvc_name="project-source",
                working_directory=working_directory,
                image_pull_policy=settings.k8s_image_pull_policy,
                image_pull_secret=settings.k8s_image_pull_secret or None,
                extra_env=extra_env,
                preferred_node=node_name,
                spec_hash=spec_hash,
                tsinit_restart_policy=tsinit_restart_policy,
                # 2026-05 App Runtime Contract: declare which mount strategy
                # the renderer should use. NULL/'bundle' = legacy behaviour
                # (bundle PVC at /app, source comes from bundle). 'image' =
                # image is self-contained; per-install PVC mounts at
                # ``state_mount_path`` and image's WORKDIR remains
                # authoritative. Set by install_compute_materializer from
                # the app manifest's compute.containers[].source_strategy.
                source_strategy=container.source_strategy,
                state_mount_path=container.state_mount_path,
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

            # Installed AppInstance projects use creator-branded hostnames
            # (``{dir}-{app}-{creator}.{domain}`` or ``{app}-{creator}.{domain}``
            # for single-container apps). Non-app projects and apps without
            # handles fall back to the legacy slug-based shape.
            from ..models import PROJECT_KIND_APP_RUNTIME
            from .apps.runtime_urls import (
                container_url as _container_url,
            )
            from .apps.runtime_urls import (
                resolve_app_url_for_container,
            )

            preview_url: str | None = None
            ingress_hostname: str | None = None
            if getattr(project, "project_kind", None) == PROJECT_KIND_APP_RUNTIME:
                preview_url = await resolve_app_url_for_container(
                    db, container, protocol=settings.k8s_container_url_protocol
                )
                if preview_url:
                    # Strip ``{protocol}://`` to get just the hostname for the ingress rule.
                    ingress_hostname = preview_url.split("://", 1)[-1]

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
                hostname=ingress_hostname,
            )
            await k8s.create_ingress(ingress, namespace)

            if preview_url is None:
                preview_url = _container_url(
                    project_slug=project.slug,
                    container_dir_or_name=container_directory,
                    app_domain=settings.app_domain,
                    protocol=settings.k8s_container_url_protocol,
                )
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
                    label_selector=_TIER2_DEV_LABEL_SELECTOR,
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
                        label_selector=_TIER2_DEV_LABEL_SELECTOR,
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

        # 9. Update project + container state. Persisted alongside the
        # SSE "running" emit below so late-joining clients and
        # polling-fallback GET /runtime agree with the live pods.
        project.compute_tier = "environment"
        project.environment_status = "active"
        project.hibernated_at = None
        project.last_activity = datetime.now(UTC)
        for c in containers:
            c.status = "running"
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

    async def _clear_released_pv_claimref(self, pv_name: str) -> None:
        """If the named PV is in ``Released`` state, clear its ``claimRef``
        so a new PVC can bind. No-op if the PV is Available/Bound/absent.

        Needed on cold bootstrap after an out-of-band namespace delete
        (reaper, operator, uninstall). The btrfs subvolume behind the PV
        is intact (Retain policy); we just need the PV to be bindable.
        """
        v1 = self._api()
        try:
            pv = await asyncio.to_thread(v1.read_persistent_volume, name=pv_name)
        except ApiException as exc:
            if exc.status == 404:
                return
            raise
        phase = (pv.status.phase or "") if pv.status else ""
        if phase != "Released":
            return
        # Clear claimRef via JSON patch (strategic merge doesn't remove
        # the field; JSON Merge Patch with null removes it).
        await asyncio.to_thread(
            v1.patch_persistent_volume,
            name=pv_name,
            body={"spec": {"claimRef": None}},
        )
        logger.info("[COMPUTE-T2] Cleared stale claimRef on Released PV %s", pv_name)

    async def _scale_project_deployments(
        self, namespace: str, project_id: UUID, replicas: int
    ) -> int:
        """Patch all project Deployments' ``spec.replicas`` via the scale
        subresource. Returns the count actually patched.

        Targets only Deployments labelled ``tesslate.io/project-id=<id>``
        so sibling namespaces (should there ever be any) stay untouched.
        Idempotent: 404s on individual Deployments are swallowed.
        """
        from kubernetes import client as _k8s

        v1 = self._api()
        apps_v1 = _k8s.AppsV1Api(v1.api_client)

        try:
            dep_list = await asyncio.to_thread(
                apps_v1.list_namespaced_deployment,
                namespace,
                label_selector=f"tesslate.io/project-id={project_id}",
            )
        except ApiException as exc:
            if exc.status == 404:
                return 0
            raise

        patched = 0
        body = {"spec": {"replicas": replicas}}
        for dep in dep_list.items or []:
            name = dep.metadata.name
            try:
                await asyncio.to_thread(
                    apps_v1.patch_namespaced_deployment_scale,
                    name=name,
                    namespace=namespace,
                    body=body,
                )
                patched += 1
            except ApiException as exc:
                if exc.status == 404:
                    continue
                logger.warning(
                    "[COMPUTE-T2] Failed to scale %s/%s → %d: %s",
                    namespace,
                    name,
                    replicas,
                    exc.reason,
                )
        return patched

    async def _stop_environment_inner(self, project, db: AsyncSession) -> None:
        """Scale project Deployments to zero. Namespace, PVC, PV, Service,
        Ingress, and NetworkPolicy all stay in place so a subsequent Start
        can warm-resume in ~5s (HF-Spaces-style sleep).

        Call directly when already holding the env lock. Full teardown
        (namespace delete) belongs to ``delete_project_namespace`` on
        uninstall, not here.
        """
        # Sync volume to CAS before scaling down (non-blocking on failure).
        # Useful even with scale-to-zero: if the cache node dies before the
        # next start, the next ensure_cached() can restore from CAS.
        if getattr(project, "volume_id", None):
            try:
                from .volume_manager import get_volume_manager

                vm = get_volume_manager()
                await vm.trigger_sync(project.volume_id)
                logger.info("[COMPUTE-T2] Volume %s synced before sleep", project.volume_id)
            except Exception as e:
                logger.warning("[COMPUTE-T2] Volume sync before sleep failed (non-fatal): %s", e)

        namespace = f"proj-{project.id}"

        # Confirm the namespace still exists before trying to scale. If it
        # was already hand-deleted (reaper, operator), stop is a no-op for
        # K8s state and we just converge the DB below.
        v1 = self._api()
        ns_exists = True
        try:
            await asyncio.to_thread(v1.read_namespace, name=namespace)
        except ApiException as exc:
            if exc.status == 404:
                ns_exists = False
            else:
                raise

        if ns_exists:
            patched = await self._scale_project_deployments(namespace, project.id, replicas=0)
            logger.info(
                "[COMPUTE-T2] Scaled %d deployments to 0 in namespace %s", patched, namespace
            )
        else:
            logger.debug("[COMPUTE-T2] Namespace %s already gone — stop is DB-only", namespace)

        project.compute_tier = "none"
        project.environment_status = "stopped"
        project.active_compute_pod = None

        # Reset container rows so the UI rollup converges on "stopped"
        # without a subsequent compute_manager invocation. Skip job-only
        # containers: they're headless and carry their own status enum.
        from sqlalchemy import update

        from ..models import Container

        await db.execute(
            update(Container)
            .where(
                Container.project_id == project.id,
                Container.status != "job_only",
            )
            .values(status="stopped")
        )
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
