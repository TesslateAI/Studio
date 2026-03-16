"""
Unit tests for KubernetesOrchestrator v2 (volume-first architecture).

Tests project environment lifecycle, container start/stop, file initialization,
hibernation via VolumeSnapshots, project status, and name sanitization.

Mocking strategy: patch at the service layer — get_k8s_client(), get_snapshot_manager(),
get_compute_manager(), and app.config.get_settings.
"""

from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.services.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock ApiException (avoids importing the real kubernetes package)
# ---------------------------------------------------------------------------


class MockApiException(Exception):
    """Stand-in for kubernetes.client.rest.ApiException."""

    def __init__(self, status=404, reason="Not Found"):
        self.status = status
        self.reason = reason
        super().__init__(f"({status}) Reason: {reason}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def patch_to_thread(monkeypatch):
    """Make asyncio.to_thread execute synchronously in tests."""

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)


@pytest.fixture(autouse=True)
def patch_api_exception(monkeypatch):
    """Swap the real ApiException for our mock everywhere the orchestrator catches it."""
    monkeypatch.setattr(
        "app.services.orchestration.kubernetes_orchestrator.ApiException",
        MockApiException,
    )


@pytest.fixture
def orchestrator(mock_settings):
    """Create KubernetesOrchestrator with mocked dependencies."""
    with patch(
        "app.services.orchestration.kubernetes_orchestrator.get_k8s_client"
    ) as mock_get_client:
        mock_client = AsyncMock()
        mock_client.get_project_namespace = Mock(side_effect=lambda pid: f"proj-{pid}")
        mock_client.create_namespace_if_not_exists = AsyncMock()
        mock_client.namespace_exists = AsyncMock(return_value=True)
        mock_client.apply_network_policy = AsyncMock()
        mock_client.create_pvc = AsyncMock()
        mock_client.create_deployment = AsyncMock()
        mock_client.create_service = AsyncMock()
        mock_client.create_ingress = AsyncMock()
        mock_client.delete_deployment = AsyncMock()
        mock_client.delete_service = AsyncMock()
        mock_client.delete_ingress = AsyncMock()
        mock_client.wait_for_deployment_ready = AsyncMock()
        mock_client.get_file_manager_pod = AsyncMock(return_value="file-manager-pod")
        mock_client.copy_wildcard_tls_secret = AsyncMock()
        mock_client.is_pod_ready = Mock(return_value=True)
        mock_client.core_v1 = Mock()
        mock_client.core_v1.delete_namespace = Mock()
        mock_client.core_v1.read_namespace = Mock()
        mock_client.core_v1.list_namespaced_pod = Mock()
        mock_client.core_v1.list_namespaced_persistent_volume_claim = Mock()
        mock_client.apps_v1 = Mock()
        mock_client.apps_v1.read_namespaced_deployment = Mock()
        mock_client._exec_in_pod = Mock(return_value="EXISTS:5")
        mock_get_client.return_value = mock_client

        orch = KubernetesOrchestrator()
        orch._mock_client = mock_client  # expose for assertions
        yield orch


# ===========================================================================
# TestKubernetesOrchestratorEnvironment
# ===========================================================================


class TestKubernetesOrchestratorEnvironment:
    """Tests for ensure_project_environment / delete_project_environment."""

    async def test_ensure_project_environment_creates_namespace_pvc_file_manager(
        self, orchestrator
    ):
        """Verify namespace, network policy, PVC, file-manager deploy, and readiness wait."""
        project_id = uuid4()
        user_id = uuid4()
        client = orchestrator._mock_client

        ns = await orchestrator.ensure_project_environment(project_id, user_id)

        assert ns == f"proj-{project_id}"
        client.create_namespace_if_not_exists.assert_awaited_once()
        client.apply_network_policy.assert_awaited_once()
        client.create_pvc.assert_awaited_once()
        # file-manager deployment created
        client.create_deployment.assert_awaited_once()
        client.wait_for_deployment_ready.assert_awaited_once_with(
            deployment_name="file-manager",
            namespace=f"proj-{project_id}",
            timeout=60,
        )

    async def test_ensure_project_environment_restores_from_snapshot(self, orchestrator):
        """Hibernated project should restore from snapshot; PVC should NOT be created from scratch."""
        project_id = uuid4()
        user_id = uuid4()
        client = orchestrator._mock_client
        mock_db = AsyncMock()

        with patch.object(
            orchestrator, "_restore_from_snapshot", new_callable=AsyncMock, return_value=True
        ) as mock_restore:
            await orchestrator.ensure_project_environment(
                project_id, user_id, is_hibernated=True, db=mock_db
            )

            mock_restore.assert_awaited_once_with(
                project_id, user_id, f"proj-{project_id}", mock_db
            )
            # PVC should NOT be created from scratch when restore succeeds
            client.create_pvc.assert_not_awaited()

    async def test_ensure_project_environment_fallback_empty_pvc(self, orchestrator):
        """If snapshot restore fails, fall back to creating an empty PVC."""
        project_id = uuid4()
        user_id = uuid4()
        client = orchestrator._mock_client
        mock_db = AsyncMock()

        with patch.object(
            orchestrator, "_restore_from_snapshot", new_callable=AsyncMock, return_value=False
        ):
            await orchestrator.ensure_project_environment(
                project_id, user_id, is_hibernated=True, db=mock_db
            )

            # Fallback: PVC created from scratch
            client.create_pvc.assert_awaited_once()

    async def test_delete_project_environment_saves_snapshot_then_deletes(self, orchestrator):
        """save_snapshot=True should snapshot first, then delete namespace."""
        project_id = uuid4()
        user_id = uuid4()
        client = orchestrator._mock_client
        mock_db = AsyncMock()

        with patch.object(
            orchestrator, "_save_to_snapshot", new_callable=AsyncMock, return_value=True
        ) as mock_save:
            await orchestrator.delete_project_environment(
                project_id, user_id, save_snapshot=True, db=mock_db
            )

            mock_save.assert_awaited_once_with(project_id, user_id, f"proj-{project_id}", mock_db)
            client.core_v1.delete_namespace.assert_called_once_with(name=f"proj-{project_id}")

    async def test_delete_project_environment_snapshot_failure_preserves_namespace(
        self, orchestrator
    ):
        """If snapshot fails, raise RuntimeError and do NOT delete namespace."""
        project_id = uuid4()
        user_id = uuid4()
        client = orchestrator._mock_client
        mock_db = AsyncMock()

        with patch.object(
            orchestrator, "_save_to_snapshot", new_callable=AsyncMock, return_value=False
        ):
            with pytest.raises(RuntimeError, match="Snapshot creation failed"):
                await orchestrator.delete_project_environment(
                    project_id, user_id, save_snapshot=True, db=mock_db
                )

            # Namespace must NOT be deleted
            client.core_v1.delete_namespace.assert_not_called()

    async def test_delete_project_environment_without_snapshot(self, orchestrator):
        """save_snapshot=False should delete namespace immediately, no snapshot."""
        project_id = uuid4()
        user_id = uuid4()
        client = orchestrator._mock_client

        with patch.object(orchestrator, "_save_to_snapshot") as mock_save:
            await orchestrator.delete_project_environment(project_id, user_id, save_snapshot=False)

            mock_save.assert_not_called()
            client.core_v1.delete_namespace.assert_called_once_with(name=f"proj-{project_id}")


# ===========================================================================
# TestKubernetesOrchestratorFileOps
# ===========================================================================


class TestKubernetesOrchestratorFileOps:
    """Tests for _build_volume_path (static method — no mocking needed)."""

    def test_build_volume_path_simple(self):
        result = KubernetesOrchestrator._build_volume_path("src/App.tsx")
        assert result == "src/App.tsx"

    def test_build_volume_path_with_subdir(self):
        result = KubernetesOrchestrator._build_volume_path("App.tsx", subdir="frontend")
        assert result == "frontend/App.tsx"

    def test_build_volume_path_prevents_traversal(self):
        with pytest.raises(ValueError, match="escapes volume boundary"):
            KubernetesOrchestrator._build_volume_path("../../etc/passwd")

    def test_build_volume_path_normalizes_dots(self):
        result = KubernetesOrchestrator._build_volume_path("./src/../lib/file.ts")
        assert result == "lib/file.ts"

    def test_build_volume_path_root_subdir(self):
        result = KubernetesOrchestrator._build_volume_path("file.ts", subdir=".")
        assert result == "file.ts"


# ===========================================================================
# TestKubernetesOrchestratorContainerLifecycle
# ===========================================================================


class TestKubernetesOrchestratorContainerLifecycle:
    """Tests for start_container, stop_container, get_container_status."""

    async def test_start_container_delegates_to_compute_manager(self, orchestrator):
        """start_container should delegate to ComputeManager.start_environment."""
        project = Mock()
        project.id = uuid4()
        project.slug = "my-proj"
        container = Mock()
        container.name = "frontend"
        container.directory = "."
        container.container_type = "base"
        mock_db = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.start_environment = AsyncMock(
            return_value={"frontend": "https://my-proj-frontend.example.com"}
        )

        with (
            patch(
                "app.services.compute_manager.get_compute_manager",
                return_value=mock_cm,
            ),
            patch(
                "app.services.compute_manager.resolve_k8s_container_dir",
                return_value="frontend",
            ),
        ):
            result = await orchestrator.start_container(
                project, container, [container], [], uuid4(), mock_db
            )

        assert result["status"] == "running"
        assert result["url"] == "https://my-proj-frontend.example.com"
        mock_cm.start_environment.assert_awaited_once()

    async def test_stop_container_base_deletes_k8s_resources(self, orchestrator):
        """Stopping a base container should delete deployment, service, AND ingress."""
        project_id = uuid4()
        client = orchestrator._mock_client

        await orchestrator.stop_container(
            project_slug="proj",
            project_id=project_id,
            container_name="frontend",
            user_id=uuid4(),
            container_type="base",
        )

        ns = f"proj-{project_id}"
        client.delete_deployment.assert_awaited_once_with("dev-frontend", ns)
        client.delete_service.assert_awaited_once_with("dev-frontend", ns)
        client.delete_ingress.assert_awaited_once_with("dev-frontend", ns)

    async def test_stop_container_service_deletes_without_ingress(self, orchestrator):
        """Stopping a service container should delete deployment + service, NOT ingress."""
        project_id = uuid4()
        client = orchestrator._mock_client

        await orchestrator.stop_container(
            project_slug="proj",
            project_id=project_id,
            container_name="Postgres",
            user_id=uuid4(),
            container_type="service",
            service_slug="postgres",
        )

        ns = f"proj-{project_id}"
        client.delete_deployment.assert_awaited_once_with("svc-postgres", ns)
        client.delete_service.assert_awaited_once_with("svc-postgres", ns)
        client.delete_ingress.assert_not_awaited()

    async def test_get_container_status_running(self, orchestrator):
        """Running deployment (ready_replicas=1) should report status 'running'."""
        project_id = uuid4()
        client = orchestrator._mock_client

        mock_deployment = Mock()
        mock_deployment.status.ready_replicas = 1
        mock_deployment.status.replicas = 1
        client.apps_v1.read_namespaced_deployment.return_value = mock_deployment

        result = await orchestrator.get_container_status(
            project_slug="proj",
            project_id=project_id,
            container_name="frontend",
            user_id=uuid4(),
        )

        assert result["status"] == "running"
        assert result["ready"] is True

    async def test_get_container_status_stopped(self, orchestrator):
        """404 on all candidate deployments should report status 'stopped'."""
        project_id = uuid4()
        client = orchestrator._mock_client

        client.apps_v1.read_namespaced_deployment.side_effect = MockApiException(status=404)

        result = await orchestrator.get_container_status(
            project_slug="proj",
            project_id=project_id,
            container_name="frontend",
            user_id=uuid4(),
        )

        assert result["status"] == "stopped"

    async def test_get_container_status_file_manager(self, orchestrator):
        """container_name=None should check file-manager deployment."""
        project_id = uuid4()
        client = orchestrator._mock_client

        mock_deployment = Mock()
        mock_deployment.status.ready_replicas = 1
        mock_deployment.status.replicas = 1
        client.apps_v1.read_namespaced_deployment.return_value = mock_deployment

        result = await orchestrator.get_container_status(
            project_slug="proj",
            project_id=project_id,
            container_name=None,
            user_id=uuid4(),
        )

        assert result["status"] == "running"
        client.apps_v1.read_namespaced_deployment.assert_called_once_with(
            name="file-manager",
            namespace=f"proj-{project_id}",
        )


# ===========================================================================
# TestContainerFileInitialization
# ===========================================================================


class TestContainerFileInitialization:
    """Tests for initialize_container_files."""

    async def test_initialize_container_files_with_git_url(self, orchestrator):
        """With a git_url, should check existence then clone."""
        project_id = uuid4()
        client = orchestrator._mock_client

        # First exec call: directory check → NOT_EXISTS
        # Second exec call: git clone → success
        # Third exec call: verify file count → "10"
        client._exec_in_pod = Mock(side_effect=["NOT_EXISTS", "Cloning into...", "10"])

        with patch(
            "app.services.orchestration.kubernetes_orchestrator.generate_git_clone_script",
            return_value="git clone ...",
        ) as mock_gen:
            result = await orchestrator.initialize_container_files(
                project_id=project_id,
                user_id=uuid4(),
                container_id=uuid4(),
                container_directory="frontend",
                git_url="https://github.com/example/repo.git",
                git_branch="main",
            )

        assert result is True
        mock_gen.assert_called_once_with(
            git_url="https://github.com/example/repo.git",
            branch="main",
            target_dir="/app/frontend",
            install_deps=False,
        )

    async def test_initialize_container_files_without_git_creates_dir(self, orchestrator):
        """Without git_url, should mkdir -p the target directory."""
        project_id = uuid4()
        client = orchestrator._mock_client

        # First exec: directory check → NOT_EXISTS
        # Second exec: mkdir → ""
        client._exec_in_pod = Mock(side_effect=["NOT_EXISTS", ""])

        result = await orchestrator.initialize_container_files(
            project_id=project_id,
            user_id=uuid4(),
            container_id=uuid4(),
            container_directory="frontend",
            git_url=None,
        )

        assert result is True
        # The second _exec_in_pod call should be the mkdir
        mkdir_call = client._exec_in_pod.call_args_list[1]
        cmd_args = mkdir_call[0][3]  # 4th positional arg is the command list
        cmd_str = " ".join(cmd_args)
        assert "mkdir -p" in cmd_str

    async def test_initialize_container_files_skips_existing(self, orchestrator):
        """If directory exists with >= 3 files, skip clone and return True."""
        project_id = uuid4()
        client = orchestrator._mock_client

        # Single exec call: directory check → EXISTS with 10 files
        client._exec_in_pod = Mock(return_value="EXISTS:10")

        result = await orchestrator.initialize_container_files(
            project_id=project_id,
            user_id=uuid4(),
            container_id=uuid4(),
            container_directory="frontend",
            git_url="https://github.com/example/repo.git",
        )

        assert result is True
        # Only the check call, no clone call
        assert client._exec_in_pod.call_count == 1


# ===========================================================================
# TestHibernationViaVolumeSnapshots
# ===========================================================================


class TestHibernationViaVolumeSnapshots:
    """Tests for _save_to_snapshot, _restore_from_snapshot."""

    async def test_save_to_snapshot_creates_and_waits(self, orchestrator):
        """Should create a snapshot and wait for it to become ready."""
        project_id = uuid4()
        user_id = uuid4()
        namespace = f"proj-{project_id}"
        mock_db = AsyncMock()

        mock_sm = AsyncMock()
        mock_snapshot = Mock(id=uuid4(), snapshot_name="snap-123")
        mock_sm.create_snapshot = AsyncMock(return_value=(mock_snapshot, None))
        mock_sm.wait_for_snapshot_ready = AsyncMock(return_value=(True, None))

        # Mock PVC listing to return project-storage
        mock_pvc = Mock()
        mock_pvc.metadata.name = "project-storage"
        mock_pvc.metadata.labels = {}
        mock_pvc_list = Mock()
        mock_pvc_list.items = [mock_pvc]
        orchestrator._mock_client.core_v1.list_namespaced_persistent_volume_claim.return_value = (
            mock_pvc_list
        )

        with (
            patch.object(
                orchestrator, "_is_project_initialized", new_callable=AsyncMock, return_value=True
            ),
            patch(
                "app.services.orchestration.kubernetes_orchestrator.get_snapshot_manager",
                return_value=mock_sm,
            ),
        ):
            result = await orchestrator._save_to_snapshot(project_id, user_id, namespace, mock_db)

        assert result is True
        mock_sm.create_snapshot.assert_awaited_once()
        mock_sm.wait_for_snapshot_ready.assert_awaited_once()

    async def test_save_to_snapshot_skips_uninitialized(self, orchestrator):
        """If project is not initialized (no files), skip snapshot, return True."""
        project_id = uuid4()
        user_id = uuid4()
        namespace = f"proj-{project_id}"
        mock_db = AsyncMock()

        mock_sm = AsyncMock()

        # Mock PVC listing: only project-storage, no service PVCs
        mock_pvc = Mock()
        mock_pvc.metadata.name = "project-storage"
        mock_pvc.metadata.labels = {}
        mock_pvc_list = Mock()
        mock_pvc_list.items = [mock_pvc]
        orchestrator._mock_client.core_v1.list_namespaced_persistent_volume_claim.return_value = (
            mock_pvc_list
        )

        with (
            patch.object(
                orchestrator, "_is_project_initialized", new_callable=AsyncMock, return_value=False
            ),
            patch(
                "app.services.orchestration.kubernetes_orchestrator.get_snapshot_manager",
                return_value=mock_sm,
            ),
        ):
            result = await orchestrator._save_to_snapshot(project_id, user_id, namespace, mock_db)

        # Returns True so namespace can be cleaned up (no data to preserve)
        assert result is True
        mock_sm.create_snapshot.assert_not_awaited()

    async def test_restore_from_snapshot_delegates(self, orchestrator):
        """Restore should delegate to snapshot_manager.restore_from_snapshot."""
        project_id = uuid4()
        user_id = uuid4()
        namespace = f"proj-{project_id}"
        mock_db = AsyncMock()

        mock_sm = AsyncMock()
        mock_sm.has_existing_snapshot = AsyncMock(return_value=True)
        mock_sm.restore_from_snapshot = AsyncMock(return_value=(True, None))
        mock_sm.get_latest_ready_snapshots_by_pvc = AsyncMock(return_value={})

        with patch(
            "app.services.orchestration.kubernetes_orchestrator.get_snapshot_manager",
            return_value=mock_sm,
        ):
            result = await orchestrator._restore_from_snapshot(
                project_id, user_id, namespace, mock_db
            )

        assert result is True
        mock_sm.restore_from_snapshot.assert_awaited_once()


# ===========================================================================
# TestProjectStatus
# ===========================================================================


class TestProjectStatus:
    """Tests for get_project_status."""

    async def test_get_project_status_running(self, orchestrator):
        """With file-manager and dev-container pods, status should be 'running'."""
        project_id = uuid4()
        client = orchestrator._mock_client

        fm_pod = Mock()
        fm_pod.metadata.labels = {
            "tesslate.io/component": "file-manager",
        }
        fm_pod.status.phase = "Running"

        dev_pod = Mock()
        dev_pod.metadata.labels = {
            "tesslate.io/component": "dev-container",
            "tesslate.io/container-directory": "frontend",
            "tesslate.io/container-id": str(uuid4()),
        }
        dev_pod.status.phase = "Running"

        pod_list = Mock()
        pod_list.items = [fm_pod, dev_pod]
        client.core_v1.list_namespaced_pod.return_value = pod_list

        result = await orchestrator.get_project_status("my-proj", project_id)

        assert result["status"] == "running"
        assert "file-manager" in result["containers"]
        assert "frontend" in result["containers"]

    async def test_get_project_status_stopped(self, orchestrator):
        """With only file-manager pod (no dev containers), status should be 'stopped'."""
        project_id = uuid4()
        client = orchestrator._mock_client

        fm_pod = Mock()
        fm_pod.metadata.labels = {
            "tesslate.io/component": "file-manager",
        }
        fm_pod.status.phase = "Running"

        pod_list = Mock()
        pod_list.items = [fm_pod]
        client.core_v1.list_namespaced_pod.return_value = pod_list

        result = await orchestrator.get_project_status("my-proj", project_id)

        assert result["status"] == "stopped"

    async def test_get_project_status_not_found(self, orchestrator):
        """If namespace doesn't exist (404), status should be 'not_found'."""
        project_id = uuid4()
        client = orchestrator._mock_client

        client.core_v1.read_namespace.side_effect = MockApiException(status=404)

        result = await orchestrator.get_project_status("my-proj", project_id)

        assert result["status"] == "not_found"


# ===========================================================================
# TestSanitizeName
# ===========================================================================


class TestSanitizeName:
    """Tests for _sanitize_name."""

    def test_sanitize_basic(self, orchestrator):
        assert orchestrator._sanitize_name("My App") == "my-app"

    def test_sanitize_dots(self, orchestrator):
        assert orchestrator._sanitize_name("my.app") == "my-app"

    def test_sanitize_truncation(self, orchestrator):
        long_name = "a" * 100
        result = orchestrator._sanitize_name(long_name)
        assert len(result) == 59
