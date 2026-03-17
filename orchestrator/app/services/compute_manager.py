"""
Compute Manager — compute lifecycle for Tier 1 (ephemeral) and Tier 2 (environment).

Tier 1: Short-lived pods in the tesslate namespace that mount a project's
btrfs subvolume via hostPath, run a single command, and self-destruct.

Tier 2: Full persistent environments (dev servers, service containers, ingress)
using CSI-backed PV+PVC in per-project namespaces. ~5-10s startup.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
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


class ComputeQuotaExceeded(Exception):
    """Raised when the concurrent compute pod limit is reached."""


class ComputeManager:
    """Manages ephemeral pods (Tier 1) and full environments (Tier 2)."""

    def __init__(self) -> None:
        self._v1: k8s_client.CoreV1Api | None = None
        self._k8s = None  # KubernetesClient wrapper for T2

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
            await asyncio.to_thread(v1.create_namespaced_pod, ns, manifest)

            logger.info(
                "[COMPUTE] Pod %s created for volume %s on node %s",
                pod_name,
                volume_id,
                node_name,
            )

            # Wait for completion
            output, exit_code = await self._wait_for_completion(pod_name, ns, timeout)
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

        pod_name = f"eph-{volume_id[:8]}-{uuid4().hex[:6]}"
        ns = self._namespace()
        devserver_image = image or settings.k8s_devserver_image

        manifest = self._build_pod_manifest(
            pod_name=pod_name,
            namespace=ns,
            volume_id=volume_id,
            node_name=node_name,
            command=["sleep", "infinity"],
            image=devserver_image,
            timeout=1800,
        )
        # Add ephemeral-specific labels
        manifest.metadata.labels["tesslate.io/component"] = "ephemeral-shell"
        manifest.metadata.labels["tesslate.io/project-id"] = project_id

        v1 = self._api()
        await asyncio.to_thread(v1.create_namespaced_pod, ns, manifest)

        logger.info(
            "[COMPUTE] Ephemeral pod %s created for volume %s on node %s",
            pod_name,
            volume_id,
            node_name,
        )
        return pod_name, ns

    async def delete_pod(self, pod_name: str, namespace: str | None = None) -> None:
        """Best-effort delete a pod by name. Swallows 404."""
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
                            requests={"cpu": "50m", "memory": "256Mi"},
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

        Returns: {container_directory: preview_url}
        """
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
        node_name = project.node_name
        volume_state = project.volume_state
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

        # 1. Ensure volume is locally accessible
        if volume_state in ("remote_only", "restoring", "provisioning"):
            if volume_state == "remote_only":
                await send_progress("restoring_volume", "Restoring project files...", 5)
                project.volume_state = "restoring"
                await db.commit()

                vm = get_volume_manager()
                node_name, _ = await vm.ensure_volume_local(volume_id, "remote_only", node_name)
                project.node_name = node_name
                project.volume_state = "local"
                await db.commit()
            else:
                # restoring or provisioning — poll until local (max 90s)
                await send_progress("restoring_volume", "Waiting for volume...", 5)
                for _ in range(45):
                    await asyncio.sleep(2)
                    await db.refresh(project)
                    if project.volume_state == "local":
                        node_name = project.node_name
                        break
                else:
                    raise RuntimeError(f"Volume {volume_id} stuck in state '{volume_state}'")

        # 2. Separate service and dev containers
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
                f"Project {project.id} has volume_state='{volume_state}' but node_name is not set. "
                "Cannot create node-affinity PV."
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
                svc_volume_id = await vm.create_service_volume(volume_id, svc_dir, node_name)

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

            protocol = "https" if settings.k8s_wildcard_tls_secret else "http"
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

        await send_progress("ready", "Environment is ready!", 100, container_status="ready")

        logger.info(
            "[COMPUTE-T2] Environment started for project %s (%d containers)",
            project.slug,
            len(containers),
        )
        return container_urls

    async def stop_environment(self, project, db: AsyncSession) -> None:
        """Delete namespace + PVs for a v2 project. btrfs subvolumes stay on node."""
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
