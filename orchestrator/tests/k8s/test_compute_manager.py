"""
Unit tests for ComputeManager — ephemeral pod lifecycle (Tier 1) and environment
lifecycle (Tier 2).

Tier 1 tests mock CoreV1Api directly (the raw K8s Python client).
Tier 2 tests mock the KubernetesClient wrapper used by stop_environment.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest
from kubernetes.client.rest import ApiException

from app.services.compute_manager import (
    ComputeManager,
    ComputeQuotaExceeded,
    _sanitize_k8s_name,
    resolve_k8s_container_dir,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pod(
    name: str,
    phase: str = "Running",
    creation_timestamp: datetime | None = None,
    container_statuses: list | None = None,
) -> Mock:
    """Build a minimal mock V1Pod."""
    pod = Mock()
    pod.metadata = Mock()
    pod.metadata.name = name
    pod.metadata.creation_timestamp = creation_timestamp or datetime.now(UTC)
    pod.status = Mock()
    pod.status.phase = phase
    pod.status.container_statuses = container_statuses or []
    pod.status.conditions = []
    return pod


def _make_pod_list(pods: list) -> Mock:
    """Build a mock V1PodList."""
    pod_list = Mock()
    pod_list.items = pods
    return pod_list


def _make_pv(name: str) -> Mock:
    """Build a minimal mock V1PersistentVolume."""
    pv = Mock()
    pv.metadata = Mock()
    pv.metadata.name = name
    return pv


def _make_pv_list(pvs: list) -> Mock:
    """Build a mock V1PersistentVolumeList."""
    pv_list = Mock()
    pv_list.items = pvs
    return pv_list


def _make_container_mock(
    directory: str = "frontend",
    container_id=None,
    name: str = "frontend",
) -> Mock:
    """Build a minimal mock Container model."""
    c = Mock()
    c.id = container_id or uuid4()
    c.directory = directory
    c.name = name
    return c


def _api_exception(status: int, reason: str = "test") -> ApiException:
    """Build a synthetic ApiException."""
    exc = ApiException(status=status, reason=reason)
    exc.status = status
    exc.reason = reason
    return exc


# ===========================================================================
# _sanitize_k8s_name
# ===========================================================================


class TestSanitizeK8sName:
    """_sanitize_k8s_name() — DNS-1123 compliant name sanitisation."""

    def test_lowercase_and_replace_spaces(self):
        assert _sanitize_k8s_name("My App") == "my-app"

    def test_replace_dots_and_underscores(self):
        assert _sanitize_k8s_name("my.app_v2") == "my-app-v2"

    def test_collapse_double_hyphens(self):
        assert _sanitize_k8s_name("my--app") == "my-app"

    def test_strip_leading_trailing_hyphens(self):
        assert _sanitize_k8s_name("-my-app-") == "my-app"

    def test_truncate_to_59_chars(self):
        long_name = "a" * 100
        result = _sanitize_k8s_name(long_name)
        assert len(result) == 59
        assert result == "a" * 59


# ===========================================================================
# resolve_k8s_container_dir
# ===========================================================================


class TestResolveK8sContainerDir:
    """resolve_k8s_container_dir() — directory to K8s identifier."""

    def test_normal_directory(self):
        container = _make_container_mock(directory="frontend")
        assert resolve_k8s_container_dir(container) == "frontend"

    def test_root_directory_uses_uuid_prefix(self):
        cid = uuid4()
        container = _make_container_mock(directory=".", container_id=cid)
        expected = _sanitize_k8s_name(str(cid).replace("-", "")[:12])
        result = resolve_k8s_container_dir(container)
        assert result == expected
        # Should be 12 hex chars (no hyphens)
        assert len(result) == 12

    def test_empty_directory_uses_uuid_prefix(self):
        cid = uuid4()
        container = _make_container_mock(directory="", container_id=cid)
        expected = _sanitize_k8s_name(str(cid).replace("-", "")[:12])
        result = resolve_k8s_container_dir(container)
        assert result == expected
        assert len(result) == 12


# ===========================================================================
# ComputeManager — Tier 1 (ephemeral pods)
# ===========================================================================


@pytest.mark.asyncio
class TestComputeManagerTier1:
    """Tier 1: ephemeral pod operations via raw CoreV1Api."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the module-level singleton before and after each test."""
        import app.services.compute_manager as cm_module

        cm_module._instance = None
        yield
        cm_module._instance = None

    @pytest.fixture
    def mock_v1(self):
        """Create a mock CoreV1Api."""
        return MagicMock()

    @pytest.fixture
    def cm(self, mock_v1, mock_settings):
        """Build a ComputeManager with mocked _api() and settings."""
        manager = ComputeManager()
        manager._v1 = mock_v1
        return manager

    # Helper to make asyncio.to_thread pass calls through synchronously
    @staticmethod
    def _sync_to_thread(func, *args, **kwargs):
        """Execute synchronous function directly (bypass threading)."""
        return func(*args, **kwargs)

    async def test_run_command_creates_pod_waits_cleans_up(self, cm, mock_v1, mock_settings):
        """run_command creates a pod, waits for Succeeded, reads logs, then deletes."""
        succeeded_pod = _make_pod("t1-test-abc123", phase="Succeeded")

        mock_v1.create_namespaced_pod.return_value = None
        mock_v1.read_namespaced_pod.return_value = succeeded_pod
        mock_v1.read_namespaced_pod_log.return_value = "build output here"
        mock_v1.delete_namespaced_pod.return_value = None
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([])

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            output, exit_code, pod_name = await cm.run_command(
                volume_id="vol-abc123def456",
                node_name="node-1",
                command=["/bin/sh", "-c", "npm install"],
                timeout=60,
            )

        assert exit_code == 0
        assert output == "build output here"
        assert pod_name.startswith("t1-")

        # Pod was created
        mock_v1.create_namespaced_pod.assert_called_once()
        # Pod was deleted in finally block
        mock_v1.delete_namespaced_pod.assert_called_once()

    async def test_run_command_quota_exceeded(self, cm, mock_v1, mock_settings):
        """run_command raises ComputeQuotaExceeded when limit is reached."""
        mock_settings.compute_max_concurrent_pods = 5

        # Return 5 active pods (at limit)
        active_pods = [_make_pod(f"t1-pod-{i}") for i in range(5)]
        mock_v1.list_namespaced_pod.return_value = _make_pod_list(active_pods)

        with (
            patch("asyncio.to_thread", side_effect=self._sync_to_thread),
            pytest.raises(ComputeQuotaExceeded, match="Compute pod limit reached"),
        ):
            await cm.run_command(
                volume_id="vol-abc123def456",
                node_name="node-1",
                command=["/bin/sh", "-c", "echo hello"],
            )

    async def test_build_pod_manifest_structure(self, cm, mock_settings):
        """_build_pod_manifest produces correct labels, volumes, security context."""
        manifest = cm._build_pod_manifest(
            pod_name="t1-test-abcdef",
            namespace="tesslate",
            volume_id="vol-abc123def456",
            node_name="node-1",
            command=["/bin/sh", "-c", "npm install"],
            image="tesslate-devserver:latest",
            timeout=120,
        )

        # Labels
        labels = manifest.metadata.labels
        assert labels["tesslate.io/tier"] == "1"
        assert labels["tesslate.io/volume-id"] == "vol-abc123def456"
        assert labels["app.kubernetes.io/part-of"] == "tesslate"

        # Volume hostPath
        volume = manifest.spec.volumes[0]
        assert volume.name == "project-source"
        assert volume.host_path.path == "/mnt/tesslate-pool/volumes/vol-abc123def456"

        # Node name (bypasses scheduler for volume locality)
        assert manifest.spec.node_name == "node-1"

        # Pod-level security context
        pod_sc = manifest.spec.security_context
        assert pod_sc.run_as_user == 1000
        assert pod_sc.run_as_non_root is True

        # Container-level security context
        container = manifest.spec.containers[0]
        assert container.security_context.run_as_user == 1000
        assert container.security_context.allow_privilege_escalation is False

        # Restart policy
        assert manifest.spec.restart_policy == "Never"

    async def test_reap_orphaned_pods_deletes_old(self, cm, mock_v1, mock_settings):
        """reap_orphaned_pods deletes pods older than max_age_seconds."""
        old_time = datetime.now(UTC) - timedelta(hours=2)
        old_pod = _make_pod("t1-old-pod", phase="Running", creation_timestamp=old_time)

        mock_v1.list_namespaced_pod.return_value = _make_pod_list([old_pod])
        mock_v1.delete_namespaced_pod.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pods(max_age_seconds=900)

        assert reaped == 1
        mock_v1.delete_namespaced_pod.assert_called_once_with(
            "t1-old-pod", "tesslate", grace_period_seconds=0
        )

    async def test_reap_orphaned_pods_skips_recent(self, cm, mock_v1, mock_settings):
        """reap_orphaned_pods does NOT delete pods younger than max_age_seconds."""
        recent_time = datetime.now(UTC) - timedelta(minutes=1)
        young_pod = _make_pod("t1-young-pod", phase="Running", creation_timestamp=recent_time)

        mock_v1.list_namespaced_pod.return_value = _make_pod_list([young_pod])

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pods(max_age_seconds=900)

        assert reaped == 0
        mock_v1.delete_namespaced_pod.assert_not_called()

    async def test_run_command_returns_exit_code(self, cm, mock_v1, mock_settings):
        """run_command returns (output, exit_code, pod_name) tuple."""
        # Simulate a Failed pod with exit code 42
        terminated = Mock()
        terminated.state = Mock()
        terminated.state.terminated = Mock()
        terminated.state.terminated.exit_code = 42
        terminated.state.terminated.reason = "Error"
        terminated.state.terminated.message = "process exited with code 42"
        terminated.state.waiting = None
        terminated.name = "cmd"

        failed_pod = _make_pod(
            "t1-fail-pod",
            phase="Failed",
            container_statuses=[terminated],
        )

        mock_v1.create_namespaced_pod.return_value = None
        mock_v1.read_namespaced_pod.return_value = failed_pod
        mock_v1.read_namespaced_pod_log.return_value = "error output"
        mock_v1.delete_namespaced_pod.return_value = None
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([])

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            output, exit_code, pod_name = await cm.run_command(
                volume_id="vol-abc123def456",
                node_name="node-1",
                command=["/bin/sh", "-c", "exit 42"],
                timeout=60,
            )

        assert exit_code == 42
        assert isinstance(output, str)
        assert isinstance(pod_name, str)

    async def test_run_command_timeout_returns_124(self, cm, mock_v1, mock_settings):
        """run_command returns exit code 124 on timeout (Unix convention)."""
        pending_pod = _make_pod("t1-stuck-pod", phase="Pending")

        mock_v1.create_namespaced_pod.return_value = None
        mock_v1.read_namespaced_pod.return_value = pending_pod
        mock_v1.delete_namespaced_pod.return_value = None
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([])

        # Patch asyncio.sleep to be instant and patch the event loop time
        # to simulate immediate timeout

        async def mock_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        with (
            patch("asyncio.to_thread", side_effect=mock_to_thread),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            # Use a very short timeout. The loop checks
            # asyncio.get_event_loop().time() < deadline. We make time jump
            # past the deadline after the first read_namespaced_pod call.
            read_calls = 0

            def read_side_effect(*args, **kwargs):
                nonlocal read_calls
                read_calls += 1
                return pending_pod

            mock_v1.read_namespaced_pod.side_effect = read_side_effect

            # Patch loop time so it jumps past deadline after pod creation
            times = iter([0, 0, 0, 1000, 1000, 1000])

            with patch.object(
                asyncio.get_event_loop(),
                "time",
                side_effect=lambda: next(times, 1000),
            ):
                output, exit_code, pod_name = await cm.run_command(
                    volume_id="vol-abc123def456",
                    node_name="node-1",
                    command=["/bin/sh", "-c", "sleep infinity"],
                    timeout=1,
                )

        assert exit_code == 124
        assert output == ""
        # Pod should still be cleaned up in finally block
        mock_v1.delete_namespaced_pod.assert_called_once()


# ===========================================================================
# ComputeManager — Tier 2 (full environment lifecycle)
# ===========================================================================


@pytest.mark.asyncio
class TestComputeManagerTier2:
    """Tier 2: environment lifecycle via KubernetesClient wrapper."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the module-level singleton before and after each test."""
        import app.services.compute_manager as cm_module

        cm_module._instance = None
        yield
        cm_module._instance = None

    @pytest.fixture
    def mock_v1(self):
        """Create a mock CoreV1Api for PV operations."""
        return MagicMock()

    @pytest.fixture
    def mock_k8s_client(self):
        """Create a mock KubernetesClient wrapper."""
        k8s = MagicMock()
        k8s.core_v1 = MagicMock()
        return k8s

    @pytest.fixture
    def cm(self, mock_v1, mock_k8s_client, mock_settings):
        """Build a ComputeManager with mocked K8s clients."""
        manager = ComputeManager()
        manager._v1 = mock_v1
        manager._k8s = mock_k8s_client
        return manager

    @staticmethod
    def _sync_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def test_stop_environment_deletes_namespace_and_pvs(
        self, cm, mock_v1, mock_k8s_client, mock_settings
    ):
        """stop_environment deletes namespace, PVs, and sets compute_tier to 'none'."""
        project_id = uuid4()

        project = Mock()
        project.id = project_id
        project.compute_tier = "environment"

        db = AsyncMock()

        namespace = f"proj-{project_id}"

        # Mock namespace deletion (via KubernetesClient wrapper)
        mock_k8s_client.core_v1.delete_namespace.return_value = None

        # Mock PV listing and deletion (via raw CoreV1Api)
        pv1 = _make_pv("pv-vol-abc123")
        pv2 = _make_pv("pv-vol-abc123-postgres")
        mock_v1.list_persistent_volume.return_value = _make_pv_list([pv1, pv2])
        mock_v1.delete_persistent_volume.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            await cm.stop_environment(project, db)

        # Namespace deleted
        mock_k8s_client.core_v1.delete_namespace.assert_called_once_with(name=namespace)

        # PVs listed by project label
        mock_v1.list_persistent_volume.assert_called_once_with(
            label_selector=f"tesslate.io/project-id={project_id}"
        )

        # Both PVs deleted
        assert mock_v1.delete_persistent_volume.call_count == 2
        mock_v1.delete_persistent_volume.assert_any_call(name="pv-vol-abc123")
        mock_v1.delete_persistent_volume.assert_any_call(name="pv-vol-abc123-postgres")

        # Project state updated
        assert project.compute_tier == "none"
        db.commit.assert_awaited_once()
