"""
Node discovery for btrfs CSI DaemonSet pods.

Discovers CSI node pods to resolve per-node gRPC addresses for
FileOps and NodeOps services.  Uses the synchronous kubernetes
client with asyncio.to_thread (same pattern as snapshot_manager.py).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


def _parse_cpu_millicores(cpu_str: str) -> int:
    """Parse K8s CPU string (e.g. '1930m', '2', '500m') to millicores."""
    cpu_str = str(cpu_str).strip()
    if not cpu_str or cpu_str == "0":
        return 0
    if cpu_str.endswith("m"):
        return int(float(cpu_str[:-1]))
    return int(float(cpu_str) * 1000)


_CACHE_TTL_SECONDS = 60
_CSI_LABEL = "app=tesslate-btrfs-csi-node"
_CSI_NAMESPACE = "kube-system"
_NODEOPS_PORT = 9741
_FILEOPS_PORT = 9742


@dataclass(frozen=True, slots=True)
class CSINodeInfo:
    """Metadata for a single CSI DaemonSet pod."""

    node_name: str
    pod_ip: str
    pod_name: str
    ready: bool


class NodeDiscovery:
    """Discovers btrfs CSI node pods and caches their addresses.

    Usage::

        discovery = NodeDiscovery()
        addr = await discovery.get_fileops_address("node-1")
        # => "10.0.1.5:9742"
    """

    def __init__(self) -> None:
        self._core_v1: client.CoreV1Api | None = None
        self._cache: dict[str, tuple[CSINodeInfo, float]] = {}
        self._refresh_lock = asyncio.Lock()

    def _init_client(self) -> client.CoreV1Api:
        """Lazy-init the Kubernetes client (try in-cluster, fallback kubeconfig)."""
        if self._core_v1 is not None:
            return self._core_v1

        try:
            config.load_incluster_config()
            logger.info("NodeDiscovery: Loaded in-cluster Kubernetes configuration")
        except config.ConfigException:
            try:
                config.load_kube_config()
                logger.info("NodeDiscovery: Loaded kubeconfig for development")
            except config.ConfigException as e:
                logger.error("NodeDiscovery: Failed to load Kubernetes config: %s", e)
                raise RuntimeError("Cannot load Kubernetes configuration") from e

        self._core_v1 = client.CoreV1Api()
        return self._core_v1

    def _list_csi_pods_sync(self) -> list[CSINodeInfo]:
        """List CSI DaemonSet pods (synchronous — run via to_thread)."""
        api = self._init_client()
        try:
            pods = api.list_namespaced_pod(
                namespace=_CSI_NAMESPACE,
                label_selector=_CSI_LABEL,
            )
        except ApiException as e:
            logger.error("NodeDiscovery: Failed to list CSI pods: %s", e)
            raise

        nodes: list[CSINodeInfo] = []
        for pod in pods.items:
            node_name = pod.spec.node_name or ""
            pod_ip = pod.status.pod_ip or ""
            pod_name = pod.metadata.name or ""

            # Check readiness from container statuses
            ready = False
            if pod.status.container_statuses:
                ready = all(cs.ready for cs in pod.status.container_statuses)

            nodes.append(
                CSINodeInfo(
                    node_name=node_name,
                    pod_ip=pod_ip,
                    pod_name=pod_name,
                    ready=ready,
                )
            )

        return nodes

    async def _refresh_cache(self) -> None:
        """Refresh the full node cache from the Kubernetes API."""
        async with self._refresh_lock:
            # Double-check after acquiring lock — another coroutine may have refreshed
            now = time.monotonic()
            if self._cache and all(now < exp for _, exp in self._cache.values()):
                return

            nodes = await asyncio.to_thread(self._list_csi_pods_sync)
            now = time.monotonic()
            expires_at = now + _CACHE_TTL_SECONDS

            self._cache.clear()
            for info in nodes:
                if info.node_name:
                    self._cache[info.node_name] = (info, expires_at)

            logger.info(
                "NodeDiscovery: Refreshed cache — %d CSI nodes found", len(nodes)
            )

    async def _get_node(self, node_name: str) -> CSINodeInfo:
        """Get CSINodeInfo for a node, refreshing cache if needed."""
        now = time.monotonic()
        entry = self._cache.get(node_name)

        if entry is not None:
            info, expires_at = entry
            if now < expires_at:
                return info

        # Cache miss or expired — refresh
        await self._refresh_cache()

        entry = self._cache.get(node_name)
        if entry is None:
            raise ValueError(
                f"CSI node pod not found for node '{node_name}'"
            )
        return entry[0]

    async def get_fileops_address(self, node_name: str) -> str:
        """Get the FileOps gRPC address for a node.

        Returns:
            Address string like "10.0.1.5:9742".

        Raises:
            ValueError: If node not found or pod not ready.
        """
        info = await self._get_node(node_name)
        if not info.ready:
            raise ValueError(
                f"CSI node pod on '{node_name}' is not ready"
            )
        return f"{info.pod_ip}:{_FILEOPS_PORT}"

    async def get_nodeops_address(self, node_name: str) -> str:
        """Get the NodeOps gRPC address for a node.

        Returns:
            Address string like "10.0.1.5:9741".

        Raises:
            ValueError: If node not found or pod not ready.
        """
        info = await self._get_node(node_name)
        if not info.ready:
            raise ValueError(
                f"CSI node pod on '{node_name}' is not ready"
            )
        return f"{info.pod_ip}:{_NODEOPS_PORT}"

    def _get_node_cpu_headroom_sync(self, node_name: str) -> int:
        """Return available CPU headroom in millicores for a K8s node.

        Calculates: allocatable_cpu - sum(pod_cpu_requests) for all
        non-terminated pods on the node.
        """
        api = self._init_client()

        node = api.read_node(node_name)
        alloc_cpu = _parse_cpu_millicores(node.status.allocatable.get("cpu", "0"))

        pods = api.list_pod_for_all_namespaces(
            field_selector=f"spec.nodeName={node_name},status.phase!=Succeeded,status.phase!=Failed"
        )
        total_requested = 0
        for pod in pods.items:
            # Regular containers: sum of requests
            regular_cpu = 0
            for container in pod.spec.containers or []:
                requests = (container.resources.requests or {}) if container.resources else {}
                regular_cpu += _parse_cpu_millicores(requests.get("cpu", "0"))

            # Init containers: max of requests (run sequentially, not concurrently)
            init_cpu = 0
            for container in pod.spec.init_containers or []:
                requests = (container.resources.requests or {}) if container.resources else {}
                init_cpu = max(init_cpu, _parse_cpu_millicores(requests.get("cpu", "0")))

            total_requested += max(regular_cpu, init_cpu)

        return max(0, alloc_cpu - total_requested)

    async def get_node_cpu_headroom(self, node_name: str) -> int:
        """Async wrapper for CPU headroom query. Returns millicores available."""
        return await asyncio.to_thread(self._get_node_cpu_headroom_sync, node_name)

    async def get_all_csi_nodes(self) -> list[CSINodeInfo]:
        """Get all known CSI nodes, refreshing cache if empty or all expired."""
        now = time.monotonic()
        # Check if any entries are still valid
        valid = [
            info for info, exp in self._cache.values() if now < exp
        ]
        if not valid:
            await self._refresh_cache()
            valid = [info for info, _ in self._cache.values()]
        return valid
