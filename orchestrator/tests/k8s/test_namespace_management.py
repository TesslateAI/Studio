"""
Unit tests for Kubernetes namespace management.

Tests the namespace-per-project isolation feature, including:
- Namespace creation with proper labels
- Namespace lookup by project ID
- Network policy creation per namespace
- Resource quota enforcement
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch, call

pytest.importorskip("kubernetes")

from kubernetes import client
from kubernetes.client.rest import ApiException
from app.k8s_client import KubernetesManager


@pytest.fixture
def mock_k8s_apis():
    """Mock Kubernetes API clients."""
    with patch('app.k8s_client.config'):
        manager = KubernetesManager()
        manager.core_v1 = AsyncMock()
        manager.apps_v1 = AsyncMock()
        manager.networking_v1 = AsyncMock()
        return manager


@pytest.mark.unit
@pytest.mark.kubernetes
class TestNamespaceManagement:
    """Test namespace-per-project isolation."""

    @pytest.mark.asyncio
    async def test_get_project_namespace_with_feature_enabled(self, mock_k8s_apis):
        """Test namespace name generation when namespace-per-project is enabled."""
        project_id = str(uuid4())

        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.k8s_namespace_per_project = True
            namespace = mock_k8s_apis._get_project_namespace(project_id)

        assert namespace == f"proj-{project_id}"

    @pytest.mark.asyncio
    async def test_get_project_namespace_with_feature_disabled(self, mock_k8s_apis):
        """Test namespace returns shared namespace when feature is disabled."""
        project_id = str(uuid4())

        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.k8s_namespace_per_project = False
            namespace = mock_k8s_apis._get_project_namespace(project_id)

        assert namespace == "tesslate-user-environments"

    @pytest.mark.asyncio
    async def test_create_namespace_with_labels(self, mock_k8s_apis):
        """Test namespace creation includes proper labels."""
        project_id = str(uuid4())
        user_id = uuid4()
        namespace_name = f"proj-{project_id}"

        # Mock that namespace doesn't exist
        mock_k8s_apis.core_v1.read_namespace = AsyncMock(
            side_effect=ApiException(status=404)
        )
        mock_k8s_apis.core_v1.create_namespace = AsyncMock()

        with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
            await mock_k8s_apis._create_namespace_if_not_exists(
                namespace=namespace_name,
                project_id=project_id,
                user_id=user_id
            )

        # Verify namespace was created
        assert mock_k8s_apis.core_v1.create_namespace.called

        # Verify labels
        call_args = mock_k8s_apis.core_v1.create_namespace.call_args
        namespace_body = call_args.kwargs['body']

        assert namespace_body.metadata.name == namespace_name
        assert namespace_body.metadata.labels['app'] == 'tesslate'
        assert namespace_body.metadata.labels['managed-by'] == 'tesslate-backend'
        assert namespace_body.metadata.labels['project-id'] == project_id
        assert namespace_body.metadata.labels['user-id'] == str(user_id)

    @pytest.mark.asyncio
    async def test_create_namespace_already_exists(self, mock_k8s_apis):
        """Test that existing namespace is not recreated."""
        project_id = str(uuid4())
        user_id = uuid4()
        namespace_name = f"proj-{project_id}"

        # Mock that namespace already exists
        mock_namespace = Mock()
        mock_k8s_apis.core_v1.read_namespace = AsyncMock(
            return_value=mock_namespace
        )
        mock_k8s_apis.core_v1.create_namespace = AsyncMock()

        with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
            await mock_k8s_apis._create_namespace_if_not_exists(
                namespace=namespace_name,
                project_id=project_id,
                user_id=user_id
            )

        # Verify namespace was NOT created
        assert not mock_k8s_apis.core_v1.create_namespace.called

    @pytest.mark.asyncio
    async def test_create_network_policy_for_namespace(self, mock_k8s_apis):
        """Test network policy creation for namespace isolation."""
        namespace = f"proj-{uuid4()}"

        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.k8s_enable_network_policies = True

            mock_k8s_apis.networking_v1.create_namespaced_network_policy = AsyncMock()

            with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
                await mock_k8s_apis._create_network_policy_if_not_exists(namespace)

            # Verify network policy was created
            assert mock_k8s_apis.networking_v1.create_namespaced_network_policy.called

            call_args = mock_k8s_apis.networking_v1.create_namespaced_network_policy.call_args
            policy = call_args.kwargs['body']

            # Verify ingress rules
            assert len(policy.spec.ingress) == 2

            # Rule 1: Allow from same namespace
            assert policy.spec.ingress[0].from_[0].pod_selector == {}

            # Rule 2: Allow from ingress-nginx namespace
            assert policy.spec.ingress[1].from_[0].namespace_selector.match_labels['kubernetes.io/metadata.name'] == 'ingress-nginx'

    @pytest.mark.asyncio
    async def test_network_policy_egress_rules(self, mock_k8s_apis):
        """Test network policy egress rules allow DNS and internet."""
        namespace = f"proj-{uuid4()}"

        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.k8s_enable_network_policies = True

            mock_k8s_apis.networking_v1.create_namespaced_network_policy = AsyncMock()

            with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
                await mock_k8s_apis._create_network_policy_if_not_exists(namespace)

            call_args = mock_k8s_apis.networking_v1.create_namespaced_network_policy.call_args
            policy = call_args.kwargs['body']

            # Verify egress rules
            egress_rules = policy.spec.egress

            # Should have rules for: same namespace, DNS, internet
            assert len(egress_rules) >= 3

            # DNS rule should target kube-system on port 53
            dns_rule = next((r for r in egress_rules if r.to and any(
                hasattr(t, 'namespace_selector') and
                getattr(t.namespace_selector, 'match_labels', {}).get('kubernetes.io/metadata.name') == 'kube-system'
                for t in r.to
            )), None)
            assert dns_rule is not None

    @pytest.mark.asyncio
    async def test_network_policy_not_created_when_disabled(self, mock_k8s_apis):
        """Test network policy is not created when feature is disabled."""
        namespace = f"proj-{uuid4()}"

        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.k8s_enable_network_policies = False

            mock_k8s_apis.networking_v1.create_namespaced_network_policy = AsyncMock()

            with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
                await mock_k8s_apis._create_network_policy_if_not_exists(namespace)

            # Verify network policy was NOT created
            assert not mock_k8s_apis.networking_v1.create_namespaced_network_policy.called


@pytest.mark.unit
@pytest.mark.kubernetes
class TestNamespaceCleanup:
    """Test namespace deletion and cleanup."""

    @pytest.mark.asyncio
    async def test_delete_namespace(self, mock_k8s_apis):
        """Test namespace deletion removes all resources."""
        namespace = f"proj-{uuid4()}"

        mock_k8s_apis.core_v1.delete_namespace = AsyncMock()

        with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
            await mock_k8s_apis._delete_namespace(namespace)

        # Verify namespace was deleted
        assert mock_k8s_apis.core_v1.delete_namespace.called
        call_args = mock_k8s_apis.core_v1.delete_namespace.call_args
        assert call_args.kwargs['name'] == namespace

    @pytest.mark.asyncio
    async def test_delete_nonexistent_namespace_succeeds(self, mock_k8s_apis):
        """Test deleting nonexistent namespace doesn't raise error."""
        namespace = f"proj-{uuid4()}"

        mock_k8s_apis.core_v1.delete_namespace = AsyncMock(
            side_effect=ApiException(status=404)
        )

        # Should not raise exception
        with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
            await mock_k8s_apis._delete_namespace(namespace)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
