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

        # Mock _ensure_compute_pv_pvc to return a PVC name (reusable per-volume)
        cm._ensure_compute_pv_pvc = AsyncMock(return_value="vol-pvc-vol-abc123def456")

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

        # PV/PVC ensured via reusable helper
        cm._ensure_compute_pv_pvc.assert_awaited_once_with("vol-abc123def456", "node-1")

        # Pod was created
        mock_v1.create_namespaced_pod.assert_called_once()
        # Pod was deleted in finally block (but PV/PVC are NOT deleted — reusable)
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
        """_build_pod_manifest produces correct labels, PVC volume, security context."""
        manifest = cm._build_pod_manifest(
            pod_name="t1-test-abcdef",
            namespace="tesslate-compute-pool",
            command=["/bin/sh", "-c", "npm install"],
            image="tesslate-devserver:latest",
            timeout=120,
            pvc_name="vol-pvc-vol-abc123def456",
        )

        # Labels
        labels = manifest.metadata.labels
        assert labels["tesslate.io/tier"] == "1"
        assert labels["app.kubernetes.io/part-of"] == "tesslate"

        # Volume uses PVC (not hostPath) — reusable across pods
        volume = manifest.spec.volumes[0]
        assert volume.name == "project-source"
        assert volume.persistent_volume_claim.claim_name == "vol-pvc-vol-abc123def456"

        # No node_name on pod (scheduling is driven by PV node affinity)
        assert manifest.spec.node_name is None

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

    async def test_build_pod_manifest_default_pvc_name(self, cm, mock_settings):
        """_build_pod_manifest uses a default PVC name when pvc_name is None."""
        manifest = cm._build_pod_manifest(
            pod_name="t1-test-abcdef",
            namespace="tesslate-compute-pool",
            command=["/bin/sh", "-c", "echo hello"],
            image="tesslate-devserver:latest",
            timeout=60,
        )

        volume = manifest.spec.volumes[0]
        assert volume.persistent_volume_claim.claim_name == "compute-pvc-t1-test-abcdef"

    async def test_reap_orphaned_pods_deletes_old(self, cm, mock_v1, mock_settings):
        """reap_orphaned_pods deletes pods older than max_age_seconds (no PV/PVC cleanup)."""
        old_time = datetime.now(UTC) - timedelta(hours=2)
        old_pod = _make_pod("t1-old-pod", phase="Running", creation_timestamp=old_time)

        mock_v1.list_namespaced_pod.return_value = _make_pod_list([old_pod])
        mock_v1.delete_namespaced_pod.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pods(max_age_seconds=900)

        assert reaped == 1
        mock_v1.delete_namespaced_pod.assert_called_once_with(
            "t1-old-pod", mock_settings.compute_pool_namespace, grace_period_seconds=0
        )
        # PV/PVC are NOT deleted — reusable across pods
        mock_v1.delete_persistent_volume.assert_not_called()

    async def test_reap_orphaned_pods_skips_recent(self, cm, mock_v1, mock_settings):
        """reap_orphaned_pods does NOT delete pods younger than max_age_seconds."""
        recent_time = datetime.now(UTC) - timedelta(minutes=1)
        young_pod = _make_pod("t1-young-pod", phase="Running", creation_timestamp=recent_time)

        mock_v1.list_namespaced_pod.return_value = _make_pod_list([young_pod])

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pods(max_age_seconds=900)

        assert reaped == 0
        mock_v1.delete_namespaced_pod.assert_not_called()

    async def test_delete_pod_does_not_clean_up_pv_pvc(self, cm, mock_v1, mock_settings):
        """delete_pod only deletes the pod — PV/PVC are reusable and not deleted."""
        mock_v1.delete_namespaced_pod.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            await cm.delete_pod("eph-vol-abc-xyz123")

        mock_v1.delete_namespaced_pod.assert_called_once()
        # No PV/PVC cleanup
        mock_v1.delete_persistent_volume.assert_not_called()
        mock_v1.delete_namespaced_persistent_volume_claim.assert_not_called()

    async def test_delete_pod_swallows_404(self, cm, mock_v1, mock_settings):
        """delete_pod does not raise when pod is already gone (404)."""
        mock_v1.delete_namespaced_pod.side_effect = _api_exception(404, "Not Found")

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            # Should not raise
            await cm.delete_pod("eph-vol-gone-123456")

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

        cm._ensure_compute_pv_pvc = AsyncMock(return_value="vol-pvc-vol-abc123def456")

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

        cm._ensure_compute_pv_pvc = AsyncMock(return_value="vol-pvc-vol-abc123def456")

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
# ComputeManager — _ensure_compute_pv_pvc
# ===========================================================================


@pytest.mark.asyncio
class TestEnsureComputePvPvc:
    """_ensure_compute_pv_pvc() — reusable per-volume PV+PVC."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        import app.services.compute_manager as cm_module

        cm_module._instance = None
        yield
        cm_module._instance = None

    @pytest.fixture
    def mock_v1(self):
        return MagicMock()

    @pytest.fixture
    def cm(self, mock_v1, mock_settings):
        manager = ComputeManager()
        manager._v1 = mock_v1
        return manager

    @staticmethod
    def _sync_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def test_returns_pvc_name(self, cm, mock_v1, mock_settings):
        """Returns the pvc_name keyed by volume_id."""
        # PVC does not exist yet (404)
        mock_v1.read_namespaced_persistent_volume_claim.side_effect = _api_exception(404)
        # PV does not exist yet (404)
        mock_v1.read_persistent_volume.side_effect = _api_exception(404)
        mock_v1.create_persistent_volume.return_value = None
        mock_v1.create_namespaced_persistent_volume_claim.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            pvc_name = await cm._ensure_compute_pv_pvc("vol-test123", "node-1")

        assert pvc_name == "vol-pvc-vol-test123"

    async def test_reuses_existing_bound_pvc(self, cm, mock_v1, mock_settings):
        """Returns immediately if PVC already exists and is Bound."""
        existing_pvc = Mock()
        existing_pvc.status = Mock()
        existing_pvc.status.phase = "Bound"
        mock_v1.read_namespaced_persistent_volume_claim.return_value = existing_pvc

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            pvc_name = await cm._ensure_compute_pv_pvc("vol-test123", "node-1")

        assert pvc_name == "vol-pvc-vol-test123"
        # Should not create PV or PVC
        mock_v1.create_persistent_volume.assert_not_called()
        mock_v1.create_namespaced_persistent_volume_claim.assert_not_called()


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

    async def test_stop_environment_scales_to_zero_and_hibernates(
        self, cm, mock_v1, mock_k8s_client, mock_settings
    ):
        """stop_environment scales deployments to zero and sets compute_tier to 'none'.

        Namespace and PVs are preserved for fast warm-resume (hibernate model).
        Full teardown only happens via delete_project_namespace on uninstall.
        """
        from unittest.mock import MagicMock

        from kubernetes import client as _k8s

        project_id = uuid4()
        project = Mock()
        project.id = project_id
        project.compute_tier = "environment"
        project.volume_id = None  # no volume sync needed

        db = AsyncMock()
        namespace = f"proj-{project_id}"

        # Namespace exists
        mock_v1.read_namespace.return_value = MagicMock()

        # Two deployments to scale down
        dep1 = MagicMock()
        dep1.metadata.name = "frontend"
        dep2 = MagicMock()
        dep2.metadata.name = "backend"
        dep_list = MagicMock()
        dep_list.items = [dep1, dep2]

        apps_v1_mock = MagicMock()
        apps_v1_mock.list_namespaced_deployment.return_value = dep_list
        apps_v1_mock.patch_namespaced_deployment_scale.return_value = None

        with (
            patch("asyncio.to_thread", side_effect=self._sync_to_thread),
            patch.object(_k8s, "AppsV1Api", return_value=apps_v1_mock),
        ):
            await cm.stop_environment(project, db)

        # Namespace must NOT be deleted
        mock_k8s_client.core_v1.delete_namespace.assert_not_called()

        # Deployments listed with project label
        apps_v1_mock.list_namespaced_deployment.assert_called_once_with(
            namespace, label_selector=f"tesslate.io/project-id={project_id}"
        )

        # Both deployments scaled to zero
        assert apps_v1_mock.patch_namespaced_deployment_scale.call_count == 2

        # Project state converged
        assert project.compute_tier == "none"
        assert project.environment_status == "stopped"
        db.commit.assert_awaited_once()


# ===========================================================================
# ComputeManager — reap_orphaned_pvcs (Option 1: reaper-based PVC cleanup)
# ===========================================================================


@pytest.mark.asyncio
class TestReapOrphanedPvcs:
    """reap_orphaned_pvcs() — clean up PVCs with no active pod after a grace period."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        import app.services.compute_manager as cm_module

        cm_module._instance = None
        yield
        cm_module._instance = None

    @pytest.fixture
    def mock_v1(self):
        return MagicMock()

    @pytest.fixture
    def cm(self, mock_v1, mock_settings):
        manager = ComputeManager()
        manager._v1 = mock_v1
        return manager

    @staticmethod
    def _sync_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    def _make_pvc(
        self,
        name: str,
        volume_name: str = "",
        creation_timestamp: datetime | None = None,
    ) -> Mock:
        pvc = Mock()
        pvc.metadata = Mock()
        pvc.metadata.name = name
        pvc.metadata.creation_timestamp = creation_timestamp or datetime.now(UTC)
        pvc.spec = Mock()
        pvc.spec.volume_name = volume_name
        return pvc

    def _make_pvc_list(self, pvcs: list) -> Mock:
        lst = Mock()
        lst.items = pvcs
        return lst

    def _make_pod_with_pvc(self, pod_name: str, pvc_name: str, phase: str = "Running") -> Mock:
        pod = Mock()
        pod.metadata = Mock()
        pod.metadata.name = pod_name
        pod.status = Mock()
        pod.status.phase = phase
        volume = Mock()
        volume.persistent_volume_claim = Mock()
        volume.persistent_volume_claim.claim_name = pvc_name
        pod.spec = Mock()
        pod.spec.volumes = [volume]
        return pod

    async def test_reaps_pvc_and_pv_with_no_active_pod(self, cm, mock_v1, mock_settings):
        """Deletes a PVC (and its PV) when no active pod references it and it is past grace."""
        old_time = datetime.now(UTC) - timedelta(minutes=10)
        pvc = self._make_pvc(
            "vol-pvc-vol-abc123", volume_name="vol-pv-vol-abc123", creation_timestamp=old_time
        )

        mock_v1.list_namespaced_persistent_volume_claim.return_value = self._make_pvc_list([pvc])
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([])
        mock_v1.delete_namespaced_persistent_volume_claim.return_value = None
        mock_v1.delete_persistent_volume.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        assert reaped == 1
        mock_v1.delete_namespaced_persistent_volume_claim.assert_called_once_with(
            "vol-pvc-vol-abc123", mock_settings.compute_pool_namespace
        )
        mock_v1.delete_persistent_volume.assert_called_once_with("vol-pv-vol-abc123")

    async def test_skips_pvc_within_grace_period(self, cm, mock_v1, mock_settings):
        """Does NOT delete a PVC that is younger than grace_seconds."""
        recent_time = datetime.now(UTC) - timedelta(minutes=2)
        pvc = self._make_pvc(
            "vol-pvc-vol-recent", volume_name="vol-pv-vol-recent", creation_timestamp=recent_time
        )

        mock_v1.list_namespaced_persistent_volume_claim.return_value = self._make_pvc_list([pvc])
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([])

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        assert reaped == 0
        mock_v1.delete_namespaced_persistent_volume_claim.assert_not_called()

    async def test_skips_pvc_with_active_running_pod(self, cm, mock_v1, mock_settings):
        """Does NOT delete a PVC that a Running pod is currently using."""
        old_time = datetime.now(UTC) - timedelta(hours=1)
        pvc = self._make_pvc(
            "vol-pvc-vol-abc123", volume_name="vol-pv-vol-abc123", creation_timestamp=old_time
        )
        active_pod = self._make_pod_with_pvc("t1-abc123-xyz", "vol-pvc-vol-abc123", phase="Running")

        mock_v1.list_namespaced_persistent_volume_claim.return_value = self._make_pvc_list([pvc])
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([active_pod])

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        assert reaped == 0
        mock_v1.delete_namespaced_persistent_volume_claim.assert_not_called()

    async def test_skips_pvc_with_pending_pod(self, cm, mock_v1, mock_settings):
        """Does NOT delete a PVC that a Pending pod is currently using."""
        old_time = datetime.now(UTC) - timedelta(hours=1)
        pvc = self._make_pvc(
            "vol-pvc-vol-abc123", volume_name="vol-pv-vol-abc123", creation_timestamp=old_time
        )
        pending_pod = self._make_pod_with_pvc(
            "t1-abc123-xyz", "vol-pvc-vol-abc123", phase="Pending"
        )

        mock_v1.list_namespaced_persistent_volume_claim.return_value = self._make_pvc_list([pvc])
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([pending_pod])

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        assert reaped == 0
        mock_v1.delete_namespaced_persistent_volume_claim.assert_not_called()

    async def test_reaps_only_unreferenced_pvcs(self, cm, mock_v1, mock_settings):
        """Reaps only PVCs with no active pod; skips PVC that is in use."""
        old_time = datetime.now(UTC) - timedelta(hours=1)
        orphaned_pvc = self._make_pvc(
            "vol-pvc-vol-orphan", volume_name="vol-pv-vol-orphan", creation_timestamp=old_time
        )
        active_pvc = self._make_pvc(
            "vol-pvc-vol-active", volume_name="vol-pv-vol-active", creation_timestamp=old_time
        )
        active_pod = self._make_pod_with_pvc("t1-active-xyz", "vol-pvc-vol-active", phase="Running")

        mock_v1.list_namespaced_persistent_volume_claim.return_value = self._make_pvc_list(
            [orphaned_pvc, active_pvc]
        )
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([active_pod])
        mock_v1.delete_namespaced_persistent_volume_claim.return_value = None
        mock_v1.delete_persistent_volume.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        assert reaped == 1
        mock_v1.delete_namespaced_persistent_volume_claim.assert_called_once_with(
            "vol-pvc-vol-orphan", mock_settings.compute_pool_namespace
        )
        mock_v1.delete_persistent_volume.assert_called_once_with("vol-pv-vol-orphan")

    async def test_returns_zero_when_no_pvcs(self, cm, mock_v1, mock_settings):
        """Returns 0 immediately when there are no PVCs in the namespace."""
        mock_v1.list_namespaced_persistent_volume_claim.return_value = self._make_pvc_list([])

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        assert reaped == 0
        mock_v1.list_namespaced_pod.assert_not_called()

    async def test_returns_zero_on_namespace_404(self, cm, mock_v1, mock_settings):
        """Returns 0 gracefully when the namespace does not exist yet."""
        mock_v1.list_namespaced_persistent_volume_claim.side_effect = _api_exception(404)

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        assert reaped == 0

    async def test_skips_pvc_deletion_on_404_continues(self, cm, mock_v1, mock_settings):
        """Swallows 404 on PVC delete and continues to next PVC."""
        old_time = datetime.now(UTC) - timedelta(hours=1)
        pvc1 = self._make_pvc(
            "vol-pvc-vol-gone", volume_name="vol-pv-vol-gone", creation_timestamp=old_time
        )
        pvc2 = self._make_pvc(
            "vol-pvc-vol-real", volume_name="vol-pv-vol-real", creation_timestamp=old_time
        )

        mock_v1.list_namespaced_persistent_volume_claim.return_value = self._make_pvc_list(
            [pvc1, pvc2]
        )
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([])
        mock_v1.delete_namespaced_persistent_volume_claim.side_effect = [
            _api_exception(404),
            None,
        ]
        mock_v1.delete_persistent_volume.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        # pvc1 got 404 (counts as 0), pvc2 succeeded (counts as 1)
        assert reaped == 1

    async def test_completed_pod_does_not_protect_pvc(self, cm, mock_v1, mock_settings):
        """A Succeeded/Failed pod does NOT protect its PVC — only Running/Pending do."""
        old_time = datetime.now(UTC) - timedelta(hours=1)
        pvc = self._make_pvc(
            "vol-pvc-vol-done", volume_name="vol-pv-vol-done", creation_timestamp=old_time
        )
        completed_pod = self._make_pod_with_pvc(
            "t1-done-xyz", "vol-pvc-vol-done", phase="Succeeded"
        )

        mock_v1.list_namespaced_persistent_volume_claim.return_value = self._make_pvc_list([pvc])
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([completed_pod])
        mock_v1.delete_namespaced_persistent_volume_claim.return_value = None
        mock_v1.delete_persistent_volume.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        assert reaped == 1
        mock_v1.delete_namespaced_persistent_volume_claim.assert_called_once_with(
            "vol-pvc-vol-done", mock_settings.compute_pool_namespace
        )

    async def test_reaps_pvc_without_pv_name(self, cm, mock_v1, mock_settings):
        """Deletes PVC even when spec.volume_name is empty; skips PV delete safely."""
        old_time = datetime.now(UTC) - timedelta(hours=1)
        pvc = self._make_pvc("vol-pvc-vol-nopv", volume_name="", creation_timestamp=old_time)

        mock_v1.list_namespaced_persistent_volume_claim.return_value = self._make_pvc_list([pvc])
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([])
        mock_v1.delete_namespaced_persistent_volume_claim.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        assert reaped == 1
        mock_v1.delete_namespaced_persistent_volume_claim.assert_called_once()
        mock_v1.delete_persistent_volume.assert_not_called()

    async def test_pv_delete_non_404_error_does_not_raise(self, cm, mock_v1, mock_settings):
        """PVC deleted successfully but PV delete returns 500 — logs warning, does not raise."""
        old_time = datetime.now(UTC) - timedelta(hours=1)
        pvc = self._make_pvc(
            "vol-pvc-vol-abc123", volume_name="vol-pv-vol-abc123", creation_timestamp=old_time
        )

        mock_v1.list_namespaced_persistent_volume_claim.return_value = self._make_pvc_list([pvc])
        mock_v1.list_namespaced_pod.return_value = _make_pod_list([])
        mock_v1.delete_namespaced_persistent_volume_claim.return_value = None
        mock_v1.delete_persistent_volume.side_effect = _api_exception(500, "Internal Server Error")

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            reaped = await cm.reap_orphaned_pvcs(grace_seconds=300)

        # PVC was counted as reaped; PV failure is best-effort
        assert reaped == 1


# ===========================================================================
# ComputeManager — delete_compute_pool_pvc (Option 3: deletion-triggered cleanup)
# ===========================================================================


@pytest.mark.asyncio
class TestDeleteComputePoolPvc:
    """delete_compute_pool_pvc() — explicit cleanup on project deletion."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        import app.services.compute_manager as cm_module

        cm_module._instance = None
        yield
        cm_module._instance = None

    @pytest.fixture
    def mock_v1(self):
        return MagicMock()

    @pytest.fixture
    def cm(self, mock_v1, mock_settings):
        manager = ComputeManager()
        manager._v1 = mock_v1
        return manager

    @staticmethod
    def _sync_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def test_deletes_pvc_and_pv_for_volume(self, cm, mock_v1, mock_settings):
        """Deletes vol-pvc-{volume_id} from compute-pool and vol-pv-{volume_id} cluster-wide."""
        mock_v1.delete_namespaced_persistent_volume_claim.return_value = None
        mock_v1.delete_persistent_volume.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            await cm.delete_compute_pool_pvc("vol-abc123def456")

        mock_v1.delete_namespaced_persistent_volume_claim.assert_called_once_with(
            "vol-pvc-vol-abc123def456", mock_settings.compute_pool_namespace
        )
        mock_v1.delete_persistent_volume.assert_called_once_with("vol-pv-vol-abc123def456")

    async def test_swallows_404_on_pvc_not_found(self, cm, mock_v1, mock_settings):
        """Does not raise when PVC was never created (project never ran a compute pod)."""
        mock_v1.delete_namespaced_persistent_volume_claim.side_effect = _api_exception(404)
        mock_v1.delete_persistent_volume.side_effect = _api_exception(404)

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            await cm.delete_compute_pool_pvc("vol-never-existed")

    async def test_swallows_404_pvc_deleted_pv_still_deleted(self, cm, mock_v1, mock_settings):
        """Still attempts PV delete even if PVC returns 404 (PVC may already be gone)."""
        mock_v1.delete_namespaced_persistent_volume_claim.side_effect = _api_exception(404)
        mock_v1.delete_persistent_volume.return_value = None

        with patch("asyncio.to_thread", side_effect=self._sync_to_thread):
            await cm.delete_compute_pool_pvc("vol-partial")

        mock_v1.delete_persistent_volume.assert_called_once_with("vol-pv-vol-partial")
