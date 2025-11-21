"""
Unit tests for Kubernetes multi-container orchestration.

Tests:
- Multi-container project startup
- Shared PVC creation (ReadWriteMany)
- Multiple Deployment/Service creation
- Service discovery between containers
- Ingress routing for multiple containers
- Service containers (Postgres, Redis, etc.)
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch

pytest.importorskip("kubernetes")

from kubernetes.client.rest import ApiException
from app.services.kubernetes_orchestrator import KubernetesOrchestrator


@pytest.fixture
def mock_k8s_manager():
    """Mock KubernetesManager for orchestrator."""
    manager = AsyncMock()
    manager.core_v1 = AsyncMock()
    manager.apps_v1 = AsyncMock()
    manager.networking_v1 = AsyncMock()
    manager._get_project_namespace = Mock(return_value=f"proj-{uuid4()}")
    manager._create_namespace_if_not_exists = AsyncMock()
    manager._create_network_policy = AsyncMock()
    return manager


@pytest.fixture
def mock_settings():
    """Mock settings for orchestrator."""
    settings = Mock()
    settings.k8s_rwx_storage_class = "nfs-client"
    settings.k8s_pvc_size = "5Gi"
    settings.app_domain = "tesslate.com"
    settings.k8s_ingress_class = "nginx"
    return settings


@pytest.fixture
def orchestrator(mock_k8s_manager, mock_settings):
    """Create KubernetesOrchestrator with mocked dependencies."""
    with patch('app.services.kubernetes_orchestrator.get_k8s_manager', return_value=mock_k8s_manager):
        with patch('app.services.kubernetes_orchestrator.get_settings', return_value=mock_settings):
            orch = KubernetesOrchestrator()
            orch.k8s_manager = mock_k8s_manager
            orch.settings = mock_settings
            return orch


@pytest.fixture
def mock_project():
    """Create mock project."""
    project = Mock()
    project.id = uuid4()
    project.slug = "my-awesome-app"
    project.name = "My Awesome App"
    return project


@pytest.fixture
def mock_containers():
    """Create mock containers for multi-container project."""
    frontend = Mock()
    frontend.id = uuid4()
    frontend.name = "frontend"
    frontend.type = "base"
    frontend.port = 5173

    backend = Mock()
    backend.id = uuid4()
    backend.name = "backend"
    backend.type = "base"
    backend.port = 8000

    return [frontend, backend]


@pytest.mark.unit
@pytest.mark.kubernetes
class TestMultiContainerStartup:
    """Test starting multi-container projects."""

    @pytest.mark.asyncio
    async def test_creates_project_namespace(self, orchestrator, mock_project, mock_containers, mock_k8s_manager):
        """Test orchestrator creates dedicated namespace for project."""
        user_id = uuid4()
        db = AsyncMock()

        with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
            await orchestrator.start_project(
                project=mock_project,
                containers=mock_containers,
                connections=[],
                user_id=user_id,
                db=db
            )

        mock_k8s_manager._create_namespace_if_not_exists.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_shared_pvc_for_source_code(self, orchestrator, mock_project, mock_containers, mock_k8s_manager):
        """Test orchestrator creates shared ReadWriteMany PVC."""
        user_id = uuid4()
        db = AsyncMock()

        mock_k8s_manager.core_v1.read_namespaced_persistent_volume_claim = AsyncMock(
            side_effect=ApiException(status=404)
        )
        mock_k8s_manager.core_v1.create_namespaced_persistent_volume_claim = AsyncMock()

        with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
            with patch('app.services.kubernetes_orchestrator.create_dynamic_pvc_manifest') as mock_pvc:
                mock_pvc.return_value = Mock()

                await orchestrator.start_project(
                    project=mock_project,
                    containers=mock_containers,
                    connections=[],
                    user_id=user_id,
                    db=db
                )

        assert mock_pvc.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
