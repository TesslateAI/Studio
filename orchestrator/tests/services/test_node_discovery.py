"""
Unit tests for NodeDiscovery service.

Tests cover:
- CSINodeInfo dataclass
- Lazy K8s client initialization (_init_client)
- Pod list parsing (_list_csi_pods_sync)
- Address resolution (get_fileops_address, get_nodeops_address)
- Node listing (get_all_csi_nodes)
- Cache behavior (TTL, expiry, refresh lock, empty node_name filtering)
"""

import asyncio
import time
from unittest.mock import Mock, patch

import pytest

from app.services.node_discovery import (
    _CACHE_TTL_SECONDS,
    _CSI_LABEL,
    _CSI_NAMESPACE,
    _FILEOPS_PORT,
    _NODEOPS_PORT,
    CSINodeInfo,
    NodeDiscovery,
)

# ---------------------------------------------------------------------------
# Helpers for building mock Kubernetes pod objects
# ---------------------------------------------------------------------------


def _make_container_status(ready: bool = True) -> Mock:
    cs = Mock()
    cs.ready = ready
    return cs


def _make_pod(
    node_name: str | None = "node-1",
    pod_ip: str | None = "10.0.1.5",
    pod_name: str | None = "csi-pod-abc",
    container_statuses: list[Mock] | None = None,
) -> Mock:
    """Build a mock V1Pod with the structure NodeDiscovery expects."""
    pod = Mock()
    pod.spec.node_name = node_name
    pod.status.pod_ip = pod_ip
    pod.metadata.name = pod_name
    pod.status.container_statuses = container_statuses
    return pod


def _make_pod_list(pods: list[Mock]) -> Mock:
    """Wrap a list of mock pods into a V1PodList-like object."""
    pod_list = Mock()
    pod_list.items = pods
    return pod_list


# ===========================================================================
# CSINodeInfo dataclass
# ===========================================================================


@pytest.mark.unit
class TestCSINodeInfo:
    """Verify CSINodeInfo dataclass fields and immutability."""

    def test_fields(self):
        info = CSINodeInfo(node_name="node-1", pod_ip="10.0.1.5", pod_name="csi-abc", ready=True)
        assert info.node_name == "node-1"
        assert info.pod_ip == "10.0.1.5"
        assert info.pod_name == "csi-abc"
        assert info.ready is True

    def test_frozen(self):
        info = CSINodeInfo(node_name="n", pod_ip="1.2.3.4", pod_name="p", ready=False)
        with pytest.raises(AttributeError):
            info.ready = True  # type: ignore[misc]

    def test_equality(self):
        a = CSINodeInfo("n", "1.2.3.4", "p", True)
        b = CSINodeInfo("n", "1.2.3.4", "p", True)
        assert a == b

    def test_inequality(self):
        a = CSINodeInfo("n", "1.2.3.4", "p", True)
        b = CSINodeInfo("n", "1.2.3.4", "p", False)
        assert a != b


# ===========================================================================
# _init_client
# ===========================================================================


@pytest.mark.unit
class TestInitClient:
    """Lazy K8s client initialization."""

    @patch("app.services.node_discovery.client.CoreV1Api")
    @patch("app.services.node_discovery.config.load_incluster_config")
    def test_loads_incluster_config(self, mock_incluster, mock_core_v1):
        discovery = NodeDiscovery()
        api = discovery._init_client()

        mock_incluster.assert_called_once()
        mock_core_v1.assert_called_once()
        assert api is mock_core_v1.return_value

    @patch("app.services.node_discovery.client.CoreV1Api")
    @patch("app.services.node_discovery.config.load_kube_config")
    @patch(
        "app.services.node_discovery.config.load_incluster_config",
        side_effect=Exception("not in cluster"),
    )
    def test_falls_back_to_kubeconfig(self, mock_incluster, mock_kubeconfig, mock_core_v1):
        # load_incluster_config raises a generic exception — the code catches
        # config.ConfigException specifically.  We need to raise the right type.
        from kubernetes.config import ConfigException

        mock_incluster.side_effect = ConfigException("not in cluster")

        discovery = NodeDiscovery()
        api = discovery._init_client()

        mock_incluster.assert_called_once()
        mock_kubeconfig.assert_called_once()
        mock_core_v1.assert_called_once()
        assert api is mock_core_v1.return_value

    @patch(
        "app.services.node_discovery.config.load_kube_config",
        side_effect=Exception("no kubeconfig"),
    )
    @patch(
        "app.services.node_discovery.config.load_incluster_config",
        side_effect=Exception("not in cluster"),
    )
    def test_raises_runtime_error_when_both_fail(self, mock_incluster, mock_kubeconfig):
        from kubernetes.config import ConfigException

        mock_incluster.side_effect = ConfigException("not in cluster")
        mock_kubeconfig.side_effect = ConfigException("no kubeconfig")

        discovery = NodeDiscovery()
        with pytest.raises(RuntimeError, match="Cannot load Kubernetes configuration"):
            discovery._init_client()

    @patch("app.services.node_discovery.client.CoreV1Api")
    @patch("app.services.node_discovery.config.load_incluster_config")
    def test_caches_client_after_first_init(self, mock_incluster, mock_core_v1):
        discovery = NodeDiscovery()
        api1 = discovery._init_client()
        api2 = discovery._init_client()

        # Should only create the client once
        assert api1 is api2
        mock_core_v1.assert_called_once()
        mock_incluster.assert_called_once()


# ===========================================================================
# _list_csi_pods_sync
# ===========================================================================


@pytest.mark.unit
class TestListCSIPodSync:
    """Parsing pod list into CSINodeInfo objects."""

    def _setup_discovery(self, pods: list[Mock]) -> NodeDiscovery:
        """Create a NodeDiscovery with a pre-configured mock client."""
        discovery = NodeDiscovery()
        mock_api = Mock()
        mock_api.list_namespaced_pod.return_value = _make_pod_list(pods)
        discovery._core_v1 = mock_api
        return discovery

    def test_parses_pods_correctly(self):
        pods = [
            _make_pod("node-1", "10.0.1.5", "csi-aaa", [_make_container_status(True)]),
            _make_pod("node-2", "10.0.2.6", "csi-bbb", [_make_container_status(True)]),
        ]
        discovery = self._setup_discovery(pods)
        result = discovery._list_csi_pods_sync()

        assert len(result) == 2
        assert result[0] == CSINodeInfo("node-1", "10.0.1.5", "csi-aaa", True)
        assert result[1] == CSINodeInfo("node-2", "10.0.2.6", "csi-bbb", True)

    def test_calls_api_with_correct_params(self):
        discovery = self._setup_discovery([])
        discovery._list_csi_pods_sync()

        discovery._core_v1.list_namespaced_pod.assert_called_once_with(
            namespace=_CSI_NAMESPACE,
            label_selector=_CSI_LABEL,
        )

    def test_ready_true_when_all_containers_ready(self):
        pods = [
            _make_pod(
                container_statuses=[
                    _make_container_status(True),
                    _make_container_status(True),
                    _make_container_status(True),
                ],
            ),
        ]
        discovery = self._setup_discovery(pods)
        result = discovery._list_csi_pods_sync()

        assert result[0].ready is True

    def test_ready_false_when_any_container_not_ready(self):
        pods = [
            _make_pod(
                container_statuses=[
                    _make_container_status(True),
                    _make_container_status(False),
                    _make_container_status(True),
                ],
            ),
        ]
        discovery = self._setup_discovery(pods)
        result = discovery._list_csi_pods_sync()

        assert result[0].ready is False

    def test_ready_false_when_container_statuses_missing(self):
        pods = [_make_pod(container_statuses=None)]
        discovery = self._setup_discovery(pods)
        result = discovery._list_csi_pods_sync()

        assert result[0].ready is False

    def test_ready_false_when_container_statuses_empty(self):
        pods = [_make_pod(container_statuses=[])]
        discovery = self._setup_discovery(pods)
        result = discovery._list_csi_pods_sync()

        # all() on empty iterable returns True, but the code checks truthiness
        # of container_statuses first — empty list is falsy.
        assert result[0].ready is False

    def test_handles_none_node_name(self):
        pods = [_make_pod(node_name=None, pod_ip="10.0.1.5")]
        discovery = self._setup_discovery(pods)
        result = discovery._list_csi_pods_sync()

        assert result[0].node_name == ""

    def test_handles_none_pod_ip(self):
        pods = [_make_pod(pod_ip=None)]
        discovery = self._setup_discovery(pods)
        result = discovery._list_csi_pods_sync()

        assert result[0].pod_ip == ""

    def test_handles_none_pod_name(self):
        pods = [_make_pod(pod_name=None)]
        discovery = self._setup_discovery(pods)
        result = discovery._list_csi_pods_sync()

        assert result[0].pod_name == ""

    def test_empty_pod_list(self):
        discovery = self._setup_discovery([])
        result = discovery._list_csi_pods_sync()

        assert result == []

    def test_api_exception_propagates(self):
        from kubernetes.client.rest import ApiException

        discovery = NodeDiscovery()
        mock_api = Mock()
        mock_api.list_namespaced_pod.side_effect = ApiException(status=403, reason="Forbidden")
        discovery._core_v1 = mock_api

        with pytest.raises(ApiException):
            discovery._list_csi_pods_sync()


# ===========================================================================
# get_fileops_address
# ===========================================================================


@pytest.mark.unit
class TestGetFileopsAddress:
    """Address resolution for FileOps gRPC."""

    @pytest.mark.asyncio
    async def test_returns_correct_address(self):
        discovery = NodeDiscovery()
        info = CSINodeInfo("node-1", "10.0.1.5", "csi-pod", True)
        discovery._cache["node-1"] = (info, time.monotonic() + 600)

        addr = await discovery.get_fileops_address("node-1")
        assert addr == f"10.0.1.5:{_FILEOPS_PORT}"
        assert addr == "10.0.1.5:9742"

    @pytest.mark.asyncio
    async def test_raises_value_error_when_node_not_found(self):
        discovery = NodeDiscovery()
        # Pre-populate cache with a different node so _refresh_cache returns quickly
        info = CSINodeInfo("other-node", "10.0.2.2", "csi-other", True)
        discovery._cache["other-node"] = (info, time.monotonic() + 600)

        with patch.object(discovery, "_list_csi_pods_sync", return_value=[info]):
            with pytest.raises(ValueError, match="not found"):
                await discovery.get_fileops_address("missing-node")

    @pytest.mark.asyncio
    async def test_raises_value_error_when_pod_not_ready(self):
        discovery = NodeDiscovery()
        info = CSINodeInfo("node-1", "10.0.1.5", "csi-pod", False)
        discovery._cache["node-1"] = (info, time.monotonic() + 600)

        with pytest.raises(ValueError, match="not ready"):
            await discovery.get_fileops_address("node-1")


# ===========================================================================
# get_nodeops_address
# ===========================================================================


@pytest.mark.unit
class TestGetNodeopsAddress:
    """Address resolution for NodeOps gRPC."""

    @pytest.mark.asyncio
    async def test_returns_correct_address(self):
        discovery = NodeDiscovery()
        info = CSINodeInfo("node-1", "10.0.1.5", "csi-pod", True)
        discovery._cache["node-1"] = (info, time.monotonic() + 600)

        addr = await discovery.get_nodeops_address("node-1")
        assert addr == f"10.0.1.5:{_NODEOPS_PORT}"
        assert addr == "10.0.1.5:9741"

    @pytest.mark.asyncio
    async def test_raises_value_error_when_node_not_found(self):
        discovery = NodeDiscovery()
        info = CSINodeInfo("other-node", "10.0.2.2", "csi-other", True)
        discovery._cache["other-node"] = (info, time.monotonic() + 600)

        with patch.object(discovery, "_list_csi_pods_sync", return_value=[info]):
            with pytest.raises(ValueError, match="not found"):
                await discovery.get_nodeops_address("missing-node")

    @pytest.mark.asyncio
    async def test_raises_value_error_when_pod_not_ready(self):
        discovery = NodeDiscovery()
        info = CSINodeInfo("node-1", "10.0.1.5", "csi-pod", False)
        discovery._cache["node-1"] = (info, time.monotonic() + 600)

        with pytest.raises(ValueError, match="not ready"):
            await discovery.get_nodeops_address("node-1")


# ===========================================================================
# get_all_csi_nodes
# ===========================================================================


@pytest.mark.unit
class TestGetAllCSINodes:
    """Listing all cached CSI nodes."""

    @pytest.mark.asyncio
    async def test_returns_all_valid_nodes(self):
        discovery = NodeDiscovery()
        far_future = time.monotonic() + 600

        info1 = CSINodeInfo("node-1", "10.0.1.5", "csi-a", True)
        info2 = CSINodeInfo("node-2", "10.0.2.6", "csi-b", True)
        discovery._cache["node-1"] = (info1, far_future)
        discovery._cache["node-2"] = (info2, far_future)

        result = await discovery.get_all_csi_nodes()
        assert len(result) == 2
        assert info1 in result
        assert info2 in result

    @pytest.mark.asyncio
    async def test_triggers_refresh_when_cache_empty(self):
        discovery = NodeDiscovery()
        info = CSINodeInfo("node-1", "10.0.1.5", "csi-a", True)

        with patch.object(discovery, "_list_csi_pods_sync", return_value=[info]):
            result = await discovery.get_all_csi_nodes()

        assert len(result) == 1
        assert result[0] == info

    @pytest.mark.asyncio
    async def test_triggers_refresh_when_all_expired(self):
        discovery = NodeDiscovery()
        expired_time = time.monotonic() - 10  # already expired

        info_old = CSINodeInfo("node-1", "10.0.1.5", "csi-a", True)
        discovery._cache["node-1"] = (info_old, expired_time)

        info_new = CSINodeInfo("node-1", "10.0.1.99", "csi-a-new", True)
        with patch.object(discovery, "_list_csi_pods_sync", return_value=[info_new]):
            result = await discovery.get_all_csi_nodes()

        assert len(result) == 1
        assert result[0].pod_ip == "10.0.1.99"

    @pytest.mark.asyncio
    async def test_includes_not_ready_nodes(self):
        """get_all_csi_nodes returns ALL cached nodes, including not-ready ones."""
        discovery = NodeDiscovery()
        far_future = time.monotonic() + 600

        ready = CSINodeInfo("node-1", "10.0.1.5", "csi-a", True)
        not_ready = CSINodeInfo("node-2", "10.0.2.6", "csi-b", False)
        discovery._cache["node-1"] = (ready, far_future)
        discovery._cache["node-2"] = (not_ready, far_future)

        result = await discovery.get_all_csi_nodes()
        assert len(result) == 2


# ===========================================================================
# Cache behavior
# ===========================================================================


@pytest.mark.unit
class TestCacheBehavior:
    """Cache TTL, expiry, refresh lock, and node_name filtering."""

    @pytest.mark.asyncio
    async def test_cache_hit_within_ttl(self):
        """Cached entry within TTL is returned without calling the API."""
        discovery = NodeDiscovery()
        info = CSINodeInfo("node-1", "10.0.1.5", "csi-pod", True)
        discovery._cache["node-1"] = (info, time.monotonic() + 600)

        with patch.object(discovery, "_list_csi_pods_sync") as mock_list:
            result = await discovery.get_fileops_address("node-1")

        mock_list.assert_not_called()
        assert result == "10.0.1.5:9742"

    @pytest.mark.asyncio
    async def test_cache_expiry_triggers_refresh(self):
        """Expired cache entry triggers a refresh from the Kubernetes API."""
        discovery = NodeDiscovery()
        info_old = CSINodeInfo("node-1", "10.0.1.5", "csi-pod", True)
        discovery._cache["node-1"] = (info_old, time.monotonic() - 10)

        info_new = CSINodeInfo("node-1", "10.0.1.99", "csi-pod-new", True)
        with patch.object(discovery, "_list_csi_pods_sync", return_value=[info_new]):
            result = await discovery.get_fileops_address("node-1")

        assert result == "10.0.1.99:9742"

    @pytest.mark.asyncio
    async def test_empty_node_name_not_cached(self):
        """Pods with empty node_name should not be stored in the cache."""
        discovery = NodeDiscovery()
        pods = [
            CSINodeInfo("", "10.0.1.5", "csi-unscheduled", False),
            CSINodeInfo("node-1", "10.0.2.6", "csi-scheduled", True),
        ]

        with patch.object(discovery, "_list_csi_pods_sync", return_value=pods):
            await discovery._refresh_cache()

        assert "" not in discovery._cache
        assert "node-1" in discovery._cache

    @pytest.mark.asyncio
    async def test_cache_refresh_sets_correct_expiry(self):
        """After refresh, cached entries have expires_at ~ now + TTL."""
        discovery = NodeDiscovery()
        info = CSINodeInfo("node-1", "10.0.1.5", "csi-pod", True)

        before = time.monotonic()
        with patch.object(discovery, "_list_csi_pods_sync", return_value=[info]):
            await discovery._refresh_cache()
        after = time.monotonic()

        _, expires_at = discovery._cache["node-1"]
        # expires_at should be between before + TTL and after + TTL
        assert before + _CACHE_TTL_SECONDS <= expires_at <= after + _CACHE_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_cache_refresh_clears_old_entries(self):
        """Refresh replaces the entire cache, removing nodes that no longer exist."""
        discovery = NodeDiscovery()
        # Set the old entry as expired so _refresh_cache's double-check won't skip
        old_info = CSINodeInfo("old-node", "10.0.0.1", "csi-old", True)
        discovery._cache["old-node"] = (old_info, time.monotonic() - 10)

        new_info = CSINodeInfo("new-node", "10.0.0.2", "csi-new", True)
        with patch.object(discovery, "_list_csi_pods_sync", return_value=[new_info]):
            await discovery._refresh_cache()

        assert "old-node" not in discovery._cache
        assert "new-node" in discovery._cache

    @pytest.mark.asyncio
    async def test_refresh_lock_prevents_thundering_herd(self):
        """Only one refresh should run at a time; concurrent callers wait."""
        discovery = NodeDiscovery()
        call_count = 0

        def slow_list():
            nonlocal call_count
            call_count += 1
            # Simulate slow API call — in real code this runs in to_thread
            return [CSINodeInfo("node-1", "10.0.1.5", "csi-pod", True)]

        with patch.object(discovery, "_list_csi_pods_sync", side_effect=slow_list):
            # Launch multiple concurrent refresh calls
            await asyncio.gather(
                discovery._refresh_cache(),
                discovery._refresh_cache(),
                discovery._refresh_cache(),
            )

        # The lock + double-check pattern means only the first call actually
        # refreshes; subsequent calls see a populated cache and skip.
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_double_check_skips_refresh_when_cache_valid(self):
        """After acquiring the lock, _refresh_cache re-checks cache validity."""
        discovery = NodeDiscovery()
        info = CSINodeInfo("node-1", "10.0.1.5", "csi-pod", True)
        discovery._cache["node-1"] = (info, time.monotonic() + 600)

        with patch.object(discovery, "_list_csi_pods_sync") as mock_list:
            await discovery._refresh_cache()

        # Cache is valid, so no API call should have been made
        mock_list.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_node_refreshes_on_cache_miss(self):
        """_get_node triggers refresh when the requested node is not in cache."""
        discovery = NodeDiscovery()
        info = CSINodeInfo("node-1", "10.0.1.5", "csi-pod", True)

        with patch.object(discovery, "_list_csi_pods_sync", return_value=[info]):
            result = await discovery._get_node("node-1")

        assert result == info

    @pytest.mark.asyncio
    async def test_get_node_raises_after_refresh_if_still_missing(self):
        """_get_node raises ValueError if node is not found even after refresh."""
        discovery = NodeDiscovery()

        with patch.object(discovery, "_list_csi_pods_sync", return_value=[]):
            with pytest.raises(ValueError, match="not found"):
                await discovery._get_node("ghost-node")

    @pytest.mark.asyncio
    async def test_monotonic_time_used_for_cache(self):
        """Cache uses time.monotonic, which is not affected by wall-clock changes."""
        discovery = NodeDiscovery()
        info = CSINodeInfo("node-1", "10.0.1.5", "csi-pod", True)

        # Patch monotonic to control time precisely
        fake_time = 1000.0

        def mock_monotonic():
            return fake_time

        with (
            patch("app.services.node_discovery.time.monotonic", side_effect=mock_monotonic),
            patch.object(discovery, "_list_csi_pods_sync", return_value=[info]),
        ):
            await discovery._refresh_cache()

        _, expires_at = discovery._cache["node-1"]
        assert expires_at == 1000.0 + _CACHE_TTL_SECONDS
