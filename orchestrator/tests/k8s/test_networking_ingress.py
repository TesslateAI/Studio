"""
Unit tests for Kubernetes networking and ingress configuration.

Tests:
- Service creation for deployments
- Ingress creation with authentication
- TLS/HTTPS configuration
- WebSocket support for HMR
- CORS and security headers
- Multi-container ingress routing
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch

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
class TestServiceCreation:
    """Test Kubernetes Service creation for deployments."""

    @pytest.mark.asyncio
    async def test_create_service_for_deployment(self, mock_k8s_apis):
        """Test service creation exposes deployment pods."""
        deployment_name = "test-deployment"
        namespace = f"proj-{uuid4()}"
        port = 5173

        mock_k8s_apis.core_v1.create_namespaced_service = AsyncMock()

        with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
            service_manifest = await mock_k8s_apis._create_service_manifest(
                deployment_name=deployment_name,
                namespace=namespace,
                port=port
            )

            await mock_k8s_apis.core_v1.create_namespaced_service(
                namespace=namespace,
                body=service_manifest
            )

        # Verify service created
        assert mock_k8s_apis.core_v1.create_namespaced_service.called
        call_args = mock_k8s_apis.core_v1.create_namespaced_service.call_args
        service = call_args.kwargs['body']

        # Verify service properties
        assert service.metadata.name == f"{deployment_name}-service"
        assert service.spec.type == "ClusterIP"
        assert service.spec.selector == {"app": deployment_name}

    @pytest.mark.asyncio
    async def test_service_port_mapping(self, mock_k8s_apis):
        """Test service maps correct ports."""
        deployment_name = "backend"
        port = 8000

        service = await mock_k8s_apis._create_service_manifest(
            deployment_name=deployment_name,
            namespace="test",
            port=port
        )

        # Verify port mapping
        assert len(service.spec.ports) == 1
        assert service.spec.ports[0].port == 80  # External port
        assert service.spec.ports[0].target_port == port  # Container port
        assert service.spec.ports[0].protocol == "TCP"

    @pytest.mark.asyncio
    async def test_service_dns_name(self, mock_k8s_apis):
        """Test service is accessible via cluster DNS."""
        deployment_name = "backend"
        namespace = f"proj-{uuid4()}"

        service = await mock_k8s_apis._create_service_manifest(
            deployment_name=deployment_name,
            namespace=namespace,
            port=8000
        )

        # Service should be accessible at: {service-name}.{namespace}.svc.cluster.local
        expected_dns = f"{deployment_name}-service.{namespace}.svc.cluster.local"

        # Verify service name matches expected DNS pattern
        assert service.metadata.name == f"{deployment_name}-service"


@pytest.mark.unit
@pytest.mark.kubernetes
class TestIngressCreation:
    """Test Kubernetes Ingress creation with authentication."""

    @pytest.mark.asyncio
    async def test_create_ingress_with_tls(self, mock_k8s_apis):
        """Test ingress is created with TLS configuration."""
        project_slug = "my-project-abc123"
        namespace = f"proj-{uuid4()}"
        service_name = "test-service"

        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.app_domain = "tesslate.com"

            ingress = await mock_k8s_apis._create_ingress_manifest(
                project_slug=project_slug,
                namespace=namespace,
                service_name=service_name,
                service_port=80
            )

        # Verify TLS configuration
        assert ingress.spec.tls is not None
        assert len(ingress.spec.tls) >= 1
        assert project_slug in ingress.spec.tls[0].hosts[0]

        # Verify cert-manager annotation
        assert "cert-manager.io/cluster-issuer" in ingress.metadata.annotations
        assert ingress.metadata.annotations["cert-manager.io/cluster-issuer"] == "letsencrypt-prod"

    @pytest.mark.asyncio
    async def test_ingress_has_auth_annotations(self, mock_k8s_apis):
        """Test ingress includes authentication annotations."""
        project_slug = "test-project"
        namespace = "test-namespace"
        user_id = str(uuid4())

        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.app_domain = "tesslate.com"

            ingress = await mock_k8s_apis._create_ingress_manifest(
                project_slug=project_slug,
                namespace=namespace,
                service_name="test-service",
                service_port=80,
                user_id=user_id
            )

        annotations = ingress.metadata.annotations

        # Verify auth annotations
        assert "nginx.ingress.kubernetes.io/auth-url" in annotations
        assert "verify-access" in annotations["nginx.ingress.kubernetes.io/auth-url"]

        # Verify user_id is passed to auth service
        assert user_id in annotations["nginx.ingress.kubernetes.io/auth-snippet"]

    @pytest.mark.asyncio
    async def test_ingress_websocket_support(self, mock_k8s_apis):
        """Test ingress supports WebSocket for HMR."""
        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.app_domain = "tesslate.com"

            ingress = await mock_k8s_apis._create_ingress_manifest(
                project_slug="test",
                namespace="test",
                service_name="test-service",
                service_port=80
            )

        annotations = ingress.metadata.annotations

        # Verify WebSocket annotations
        assert "nginx.ingress.kubernetes.io/websocket-services" in annotations or \
               annotations.get("nginx.ingress.kubernetes.io/proxy-http-version") == "1.1"
        assert annotations.get("nginx.ingress.kubernetes.io/proxy-read-timeout") == "3600"

    @pytest.mark.asyncio
    async def test_ingress_cors_headers(self, mock_k8s_apis):
        """Test ingress includes CORS headers for iframe embedding."""
        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.app_domain = "tesslate.com"

            ingress = await mock_k8s_apis._create_ingress_manifest(
                project_slug="test",
                namespace="test",
                service_name="test-service",
                service_port=80
            )

        annotations = ingress.metadata.annotations

        # Verify CORS annotations
        assert "nginx.ingress.kubernetes.io/enable-cors" in annotations
        assert annotations["nginx.ingress.kubernetes.io/enable-cors"] == "true"
        assert "nginx.ingress.kubernetes.io/cors-allow-origin" in annotations

    @pytest.mark.asyncio
    async def test_ingress_rate_limiting(self, mock_k8s_apis):
        """Test ingress has rate limiting configured."""
        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.app_domain = "tesslate.com"

            ingress = await mock_k8s_apis._create_ingress_manifest(
                project_slug="test",
                namespace="test",
                service_name="test-service",
                service_port=80
            )

        annotations = ingress.metadata.annotations

        # Verify rate limit annotations
        assert "nginx.ingress.kubernetes.io/limit-rps" in annotations
        # Should be reasonable (e.g., 20 req/s)
        assert int(annotations["nginx.ingress.kubernetes.io/limit-rps"]) >= 10

    @pytest.mark.asyncio
    async def test_ingress_hostname_generation(self, mock_k8s_apis):
        """Test ingress generates correct hostname."""
        project_slug = "my-awesome-project-xyz"

        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.app_domain = "tesslate.com"

            ingress = await mock_k8s_apis._create_ingress_manifest(
                project_slug=project_slug,
                namespace="test",
                service_name="test-service",
                service_port=80
            )

        # Verify hostname
        assert len(ingress.spec.rules) >= 1
        host = ingress.spec.rules[0].host
        assert host == f"{project_slug}.tesslate.com"


@pytest.mark.unit
@pytest.mark.kubernetes
class TestMultiContainerIngress:
    """Test ingress routing for multi-container projects."""

    @pytest.mark.asyncio
    async def test_multiple_ingresses_for_containers(self, mock_k8s_apis):
        """Test separate ingress created for each exposed container."""
        project_slug = "my-app"
        namespace = f"proj-{uuid4()}"

        containers = [
            {"name": "frontend", "port": 5173, "service_name": "frontend-service"},
            {"name": "backend", "port": 8000, "service_name": "backend-service"}
        ]

        ingresses = []
        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.app_domain = "tesslate.com"

            for container in containers:
                ingress = await mock_k8s_apis._create_ingress_manifest(
                    project_slug=project_slug,
                    namespace=namespace,
                    service_name=container["service_name"],
                    service_port=80,
                    container_name=container["name"]
                )
                ingresses.append(ingress)

        # Verify each container has unique hostname
        hostnames = [ing.spec.rules[0].host for ing in ingresses]
        assert len(set(hostnames)) == len(containers)  # All unique

        # Frontend should be main domain, backend should have suffix
        assert f"{project_slug}.tesslate.com" in hostnames
        assert f"{project_slug}-backend.tesslate.com" in hostnames

    @pytest.mark.asyncio
    async def test_ingress_routes_to_correct_service(self, mock_k8s_apis):
        """Test ingress backend points to correct service."""
        service_name = "backend-service"
        service_port = 80

        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.app_domain = "tesslate.com"

            ingress = await mock_k8s_apis._create_ingress_manifest(
                project_slug="test",
                namespace="test",
                service_name=service_name,
                service_port=service_port
            )

        # Verify routing
        rule = ingress.spec.rules[0]
        path = rule.http.paths[0]

        assert path.backend.service.name == service_name
        assert path.backend.service.port.number == service_port


@pytest.mark.unit
@pytest.mark.kubernetes
class TestServiceDiscovery:
    """Test inter-container communication via service DNS."""

    @pytest.mark.asyncio
    async def test_container_can_resolve_service_dns(self, mock_k8s_apis):
        """Test containers can communicate via service DNS names."""
        namespace = f"proj-{uuid4()}"

        # Create services for frontend and backend
        frontend_service = await mock_k8s_apis._create_service_manifest(
            deployment_name="frontend",
            namespace=namespace,
            port=5173
        )

        backend_service = await mock_k8s_apis._create_service_manifest(
            deployment_name="backend",
            namespace=namespace,
            port=8000
        )

        # Frontend should be able to call backend at:
        # http://backend-service.proj-{uuid}.svc.cluster.local:80
        backend_dns = f"{backend_service.metadata.name}.{namespace}.svc.cluster.local"

        # Verify DNS format is correct
        assert backend_dns == f"backend-service.{namespace}.svc.cluster.local"

    @pytest.mark.asyncio
    async def test_network_policy_allows_pod_to_pod(self, mock_k8s_apis):
        """Test network policy allows communication within namespace."""
        namespace = f"proj-{uuid4()}"

        with patch('app.k8s_client.get_settings') as mock_settings:
            mock_settings.return_value.k8s_enable_network_policies = True

            mock_k8s_apis.networking_v1.create_namespaced_network_policy = AsyncMock()

            with patch('asyncio.to_thread', new=lambda f, *args, **kwargs: f(*args, **kwargs)):
                await mock_k8s_apis._create_network_policy_if_not_exists(namespace)

            call_args = mock_k8s_apis.networking_v1.create_namespaced_network_policy.call_args
            policy = call_args.kwargs['body']

            # Verify ingress allows from same namespace
            same_namespace_rule = policy.spec.ingress[0]
            assert same_namespace_rule.from_[0].pod_selector == {}

            # Verify egress allows to same namespace
            egress_rules = policy.spec.egress
            same_namespace_egress = next((r for r in egress_rules if r.to and
                                         any(hasattr(t, 'pod_selector') and t.pod_selector == {} for t in r.to)), None)
            assert same_namespace_egress is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
