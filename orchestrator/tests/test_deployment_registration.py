"""
Tests for Deployment Provider Registration & Wiring.

Covers:
- All providers registered in __init__.py and DeploymentManager
- All providers have guard capabilities
- Container-push and export endpoint request/response models
- Credential metadata fields and config settings
- prepare_provider_credentials delegation to _build_provider_credentials
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from uuid import uuid4

import sys
import os

# Ensure orchestrator is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# =============================================================================
# Provider Registration Tests
# =============================================================================


class TestProviderRegistration:
    """Verify all providers are importable and registered in the manager."""

    def test_all_providers_importable_from_init(self):
        """All 22 provider classes can be imported from providers __init__."""
        from app.services.deployment.providers import (
            CloudflareWorkersProvider,
            VercelProvider,
            NetlifyProvider,
            HerokuProvider,
            KoyebProvider,
            ZeaburProvider,
            SurgeProvider,
            DenoDeployProvider,
            FirebaseHostingProvider,
            RailwayProvider,
            RenderProvider,
            NorthflankProvider,
            GitHubPagesProvider,
            AWSContainerProvider,
            GCPContainerProvider,
            AzureContainerProvider,
            DigitalOceanContainerProvider,
            FlyProvider,
            DockerHubExportProvider,
            GHCRExportProvider,
            DownloadExportProvider,
        )

        # All should be classes
        assert callable(CloudflareWorkersProvider)
        assert callable(DownloadExportProvider)

    def test_manager_has_22_providers(self):
        """DeploymentManager._providers has at least 22 entries."""
        from app.services.deployment.manager import DeploymentManager

        assert len(DeploymentManager._providers) >= 22

    def test_manager_provider_keys_match_expected(self):
        """All expected provider keys are registered."""
        from app.services.deployment.manager import DeploymentManager

        expected_keys = {
            "cloudflare", "vercel", "netlify", "heroku", "koyeb", "zeabur",
            "surge", "deno-deploy", "firebase", "railway", "render",
            "northflank", "github-pages", "digitalocean", "aws-apprunner",
            "gcp-cloudrun", "azure-container-apps", "do-container", "fly",
            "dockerhub", "ghcr", "download",
        }
        actual_keys = set(DeploymentManager._providers.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"Missing provider keys: {missing}"

    def test_container_providers_subset(self):
        """Container providers are a subset of all providers."""
        from app.services.deployment.manager import DeploymentManager

        for name in DeploymentManager._container_providers:
            assert name in DeploymentManager._providers, (
                f"Container provider '{name}' not in _providers registry"
            )

    def test_export_providers_subset(self):
        """Export providers are a subset of all providers."""
        from app.services.deployment.manager import DeploymentManager

        for name in DeploymentManager._export_providers:
            assert name in DeploymentManager._providers, (
                f"Export provider '{name}' not in _providers registry"
            )

    def test_is_container_provider(self):
        """is_container_provider returns True for container-push providers."""
        from app.services.deployment.manager import DeploymentManager

        assert DeploymentManager.is_container_provider("aws-apprunner")
        assert DeploymentManager.is_container_provider("gcp-cloudrun")
        assert DeploymentManager.is_container_provider("fly")
        assert not DeploymentManager.is_container_provider("vercel")
        assert not DeploymentManager.is_container_provider("netlify")
        assert not DeploymentManager.is_container_provider("download")

    def test_is_export_provider(self):
        """is_export_provider returns True for export-only providers."""
        from app.services.deployment.manager import DeploymentManager

        assert DeploymentManager.is_export_provider("dockerhub")
        assert DeploymentManager.is_export_provider("ghcr")
        assert DeploymentManager.is_export_provider("download")
        assert not DeploymentManager.is_export_provider("vercel")
        assert not DeploymentManager.is_export_provider("aws-apprunner")

    def test_list_available_providers_returns_all(self):
        """list_available_providers returns metadata for all providers."""
        from app.services.deployment.manager import DeploymentManager

        providers = DeploymentManager.list_available_providers()
        names = {p["name"] for p in providers}
        assert len(names) >= 22
        assert "aws-apprunner" in names
        assert "dockerhub" in names
        assert "download" in names

    def test_get_provider_returns_instance(self):
        """get_provider creates a valid provider instance."""
        from app.services.deployment.manager import DeploymentManager

        # Download provider requires no credentials
        provider = DeploymentManager.get_provider("download", {})
        assert provider is not None

    def test_get_provider_unknown_raises(self):
        """get_provider raises ValueError for unknown provider."""
        from app.services.deployment.manager import DeploymentManager

        with pytest.raises(ValueError, match="Unknown provider"):
            DeploymentManager.get_provider("nonexistent", {})


# =============================================================================
# Guard Capabilities Tests
# =============================================================================


class TestGuardCapabilities:
    """Verify all providers have capability entries in guards."""

    def test_all_providers_have_capabilities(self):
        """Every provider in the manager has a PROVIDER_CAPABILITIES entry."""
        from app.services.deployment.manager import DeploymentManager
        from app.services.deployment.guards import PROVIDER_CAPABILITIES

        for key in DeploymentManager._providers:
            assert key in PROVIDER_CAPABILITIES, (
                f"Provider '{key}' missing from PROVIDER_CAPABILITIES"
            )

    def test_capability_fields_present(self):
        """Each capability entry has required fields."""
        from app.services.deployment.guards import PROVIDER_CAPABILITIES

        required_fields = {
            "display_name", "types", "frameworks",
            "supports_serverless", "supports_static", "supports_fullstack",
            "deployment_mode", "icon", "color",
        }

        for provider, capability in PROVIDER_CAPABILITIES.items():
            for field in required_fields:
                assert field in capability, (
                    f"Provider '{provider}' missing field '{field}' in capabilities"
                )

    def test_deployment_mode_values(self):
        """deployment_mode is one of the expected values."""
        from app.services.deployment.guards import PROVIDER_CAPABILITIES

        valid_modes = {"source", "pre-built", "container", "export"}
        for provider, cap in PROVIDER_CAPABILITIES.items():
            assert cap["deployment_mode"] in valid_modes, (
                f"Provider '{provider}' has invalid deployment_mode: {cap['deployment_mode']}"
            )

    def test_container_providers_have_container_mode(self):
        """Container-push providers have deployment_mode='container'."""
        from app.services.deployment.guards import PROVIDER_CAPABILITIES
        from app.services.deployment.manager import DeploymentManager

        for name in DeploymentManager._container_providers:
            if name in PROVIDER_CAPABILITIES:
                cap = PROVIDER_CAPABILITIES[name]
                assert cap["deployment_mode"] in ("container", "export"), (
                    f"Container provider '{name}' should have container or export mode"
                )

    def test_validate_deployment_connection_known_provider(self):
        """validate_deployment_connection works for known providers."""
        from app.services.deployment.guards import validate_deployment_connection

        result = validate_deployment_connection(
            provider="railway",
            container_type="base",
            framework="react",
        )
        assert result["allowed"] is True

    def test_validate_deployment_connection_unknown_provider(self):
        """validate_deployment_connection rejects unknown providers."""
        from app.services.deployment.guards import validate_deployment_connection

        result = validate_deployment_connection(
            provider="nonexistent",
            container_type="base",
        )
        assert result["allowed"] is False

    def test_validate_database_rejected_by_frontend_providers(self):
        """Database containers rejected by frontend-only providers."""
        from app.services.deployment.guards import validate_deployment_connection

        result = validate_deployment_connection(
            provider="vercel",
            container_type="service",
            service_slug="postgres",
        )
        assert result["allowed"] is False


# =============================================================================
# Endpoint Request/Response Model Tests
# =============================================================================


class TestContainerDeployRequestModel:
    """Test ContainerDeployRequest Pydantic model."""

    def test_minimal_request(self):
        from app.routers.deployments import ContainerDeployRequest

        req = ContainerDeployRequest(provider="aws-apprunner")
        assert req.provider == "aws-apprunner"
        assert req.port == 8080
        assert req.cpu == "0.25"
        assert req.memory == "512Mi"
        assert req.region == "us-east-1"
        assert req.env_vars == {}
        assert req.container_id is None

    def test_full_request(self):
        from app.routers.deployments import ContainerDeployRequest

        cid = uuid4()
        req = ContainerDeployRequest(
            provider="gcp-cloudrun",
            container_id=cid,
            port=3000,
            cpu="1",
            memory="1Gi",
            region="us-central1",
            env_vars={"NODE_ENV": "production"},
        )
        assert req.container_id == cid
        assert req.port == 3000
        assert req.region == "us-central1"


class TestExportRequestModel:
    """Test ExportRequest Pydantic model."""

    def test_minimal_request(self):
        from app.routers.deployments import ExportRequest

        req = ExportRequest(provider="dockerhub")
        assert req.provider == "dockerhub"
        assert req.tag == "latest"
        assert req.image_name is None

    def test_full_request(self):
        from app.routers.deployments import ExportRequest

        req = ExportRequest(
            provider="ghcr",
            image_name="my-app",
            tag="v1.2.3",
            container_id=uuid4(),
        )
        assert req.image_name == "my-app"
        assert req.tag == "v1.2.3"


class TestExportResponseModel:
    """Test ExportResponse Pydantic model."""

    def test_success_response(self):
        from app.routers.deployments import ExportResponse

        resp = ExportResponse(
            id=uuid4(),
            project_id=uuid4(),
            provider="dockerhub",
            status="success",
            image_ref="docker.io/user/app:latest",
            pull_command="docker pull docker.io/user/app:latest",
            logs=["Image pushed"],
            created_at="2026-03-22T00:00:00",
        )
        assert resp.status == "success"
        assert resp.pull_command is not None

    def test_download_response(self):
        from app.routers.deployments import ExportResponse

        resp = ExportResponse(
            id=uuid4(),
            project_id=uuid4(),
            provider="download",
            status="success",
            download_url="/api/downloads/abc123.zip",
            logs=["Archive created with 50 files"],
            created_at="2026-03-22T00:00:00",
        )
        assert resp.download_url is not None
        assert resp.image_ref is None


# =============================================================================
# Container Deploy Endpoint Validation Tests
# =============================================================================


class TestDeployContainerValidation:
    """Test deploy-container endpoint validation logic."""

    def test_rejects_non_container_provider(self):
        """Should reject source-push providers like vercel."""
        from app.services.deployment.manager import DeploymentManager

        assert not DeploymentManager.is_container_provider("vercel")
        assert not DeploymentManager.is_container_provider("netlify")
        assert not DeploymentManager.is_container_provider("railway")

    def test_accepts_container_providers(self):
        """Should accept container-push providers."""
        from app.services.deployment.manager import DeploymentManager

        assert DeploymentManager.is_container_provider("aws-apprunner")
        assert DeploymentManager.is_container_provider("gcp-cloudrun")
        assert DeploymentManager.is_container_provider("azure-container-apps")
        assert DeploymentManager.is_container_provider("do-container")
        assert DeploymentManager.is_container_provider("fly")


class TestExportEndpointValidation:
    """Test export endpoint validation logic."""

    def test_rejects_non_export_provider(self):
        """Should reject non-export providers."""
        from app.services.deployment.manager import DeploymentManager

        assert not DeploymentManager.is_export_provider("vercel")
        assert not DeploymentManager.is_export_provider("aws-apprunner")

    def test_accepts_export_providers(self):
        """Should accept export providers."""
        from app.services.deployment.manager import DeploymentManager

        assert DeploymentManager.is_export_provider("dockerhub")
        assert DeploymentManager.is_export_provider("ghcr")
        assert DeploymentManager.is_export_provider("download")


# =============================================================================
# Credential Metadata Tests
# =============================================================================


class TestCredentialMetadata:
    """Verify CredentialMetadata has all required fields for new providers."""

    def test_all_fields_present(self):
        from app.routers.deployment_credentials import CredentialMetadata

        meta = CredentialMetadata()
        # OAuth providers
        assert hasattr(meta, "team_id")
        assert hasattr(meta, "account_id")
        assert hasattr(meta, "account_name")
        # Git providers
        assert hasattr(meta, "repo_owner")
        assert hasattr(meta, "org_slug")
        # Cloud providers
        assert hasattr(meta, "client_id")
        assert hasattr(meta, "project_id")
        assert hasattr(meta, "aws_region")
        assert hasattr(meta, "gcp_region")
        assert hasattr(meta, "azure_region")
        assert hasattr(meta, "subscription_id")
        assert hasattr(meta, "resource_group")
        assert hasattr(meta, "registry_name")
        assert hasattr(meta, "tenant_id")
        assert hasattr(meta, "site_id")
        assert hasattr(meta, "org_id")
        # Token refresh
        assert hasattr(meta, "refresh_token")

    def test_fields_default_to_none(self):
        from app.routers.deployment_credentials import CredentialMetadata

        meta = CredentialMetadata()
        assert meta.team_id is None
        assert meta.aws_region is None
        assert meta.refresh_token is None


class TestContainerPushConfig:
    """Verify container push settings exist in config."""

    def test_config_has_container_push_settings(self):
        from app.config import get_settings

        settings = get_settings()
        assert hasattr(settings, "container_push_timeout")
        assert hasattr(settings, "kaniko_image")
        assert hasattr(settings, "container_push_default_cpu")
        assert hasattr(settings, "container_push_default_memory")

    def test_config_defaults(self):
        from app.config import get_settings

        settings = get_settings()
        assert settings.container_push_timeout == 900
        assert settings.container_push_default_cpu == "0.25"
        assert settings.container_push_default_memory == "512Mi"


# =============================================================================
# prepare_provider_credentials Delegation Tests
# =============================================================================


class TestPrepareProviderCredentials:
    """Test that deployments.prepare_provider_credentials delegates correctly."""

    def test_cloudflare_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "cloudflare", "my-token",
            {"account_id": "acc123", "dispatch_namespace": "ns1"},
        )
        assert creds["api_token"] == "my-token"
        assert creds["account_id"] == "acc123"
        assert creds["dispatch_namespace"] == "ns1"

    def test_vercel_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "vercel", "vercel-token", {"team_id": "team123"}
        )
        assert creds["token"] == "vercel-token"
        assert creds["team_id"] == "team123"

    def test_aws_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "aws-apprunner", "access-key-id",
            {"aws_secret_access_key": "secret", "aws_region": "eu-west-1"},
        )
        assert creds["aws_access_key_id"] == "access-key-id"
        assert creds["aws_secret_access_key"] == "secret"
        assert creds["aws_region"] == "eu-west-1"

    def test_gcp_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "gcp-cloudrun", '{"type":"service_account"}',
            {"gcp_region": "us-central1"},
        )
        assert creds["service_account_json"] == '{"type":"service_account"}'
        assert creds["gcp_region"] == "us-central1"

    def test_azure_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        meta = {
            "tenant_id": "t1",
            "client_id": "c1",
            "subscription_id": "s1",
            "resource_group": "rg1",
            "registry_name": "reg1",
            "azure_region": "eastus",
        }
        creds = prepare_provider_credentials(
            "azure-container-apps", "client-secret", meta
        )
        assert creds["client_secret"] == "client-secret"
        assert creds["tenant_id"] == "t1"
        assert creds["registry_name"] == "reg1"

    def test_heroku_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials("heroku", "heroku-key", None)
        assert creds["api_key"] == "heroku-key"

    def test_dockerhub_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "dockerhub", "pat-token", {"account_name": "myuser"}
        )
        assert creds["username"] == "myuser"
        assert creds["token"] == "pat-token"

    def test_ghcr_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "ghcr", "ghp_token", {"account_name": "ghuser"}
        )
        assert creds["username"] == "ghuser"
        assert creds["token"] == "ghp_token"

    def test_download_no_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials("download", "", None)
        # Should not raise, download needs no real credentials
        assert isinstance(creds, dict)

    def test_railway_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials("railway", "rail-token", None)
        assert creds["token"] == "rail-token"

    def test_render_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials("render", "render-key", None)
        assert creds["api_key"] == "render-key"

    def test_koyeb_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials("koyeb", "koyeb-token", None)
        assert creds["api_token"] == "koyeb-token"

    def test_fly_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "fly", "fly-token", {"org_slug": "my-org"}
        )
        assert creds["api_token"] == "fly-token"
        assert creds["org_slug"] == "my-org"

    def test_firebase_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "firebase", '{"type":"service_account"}',
            {"site_id": "my-site"},
        )
        assert creds["service_account_json"] == '{"type":"service_account"}'
        assert creds["site_id"] == "my-site"

    def test_surge_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "surge", "surge-token", {"account_name": "user@email.com"}
        )
        assert creds["email"] == "user@email.com"
        assert creds["token"] == "surge-token"

    def test_deno_deploy_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "deno-deploy", "deno-token", {"org_id": "org123"}
        )
        assert creds["token"] == "deno-token"
        assert creds["org_id"] == "org123"

    def test_do_container_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        creds = prepare_provider_credentials(
            "do-container", "do-token",
            {"registry_name": "my-registry"},
        )
        assert creds["api_token"] == "do-token"
        assert creds["registry_name"] == "my-registry"

    def test_digitalocean_source_credentials(self):
        from app.routers.deployments import prepare_provider_credentials

        # digitalocean (source mode) is mapped to do-container provider class
        # but uses the same credential key as do-container or a generic token
        creds = prepare_provider_credentials(
            "digitalocean", "do-token", {"registry_name": "reg"}
        )
        assert creds["token"] == "do-token"


# =============================================================================
# Container Base Class Tests
# =============================================================================


class TestContainerDeployConfig:
    """Test ContainerDeployConfig model."""

    def test_defaults(self):
        from app.services.deployment.container_base import ContainerDeployConfig

        config = ContainerDeployConfig(image_ref="myapp:latest")
        assert config.port == 8080
        assert config.cpu == "0.25"
        assert config.memory == "512Mi"
        assert config.env_vars == {}
        assert config.region == "us-east-1"

    def test_custom_values(self):
        from app.services.deployment.container_base import ContainerDeployConfig

        config = ContainerDeployConfig(
            image_ref="myapp:v2",
            port=3000,
            cpu="1",
            memory="2Gi",
            env_vars={"KEY": "val"},
            region="eu-west-1",
        )
        assert config.port == 3000
        assert config.memory == "2Gi"


class TestBaseContainerDeploymentProvider:
    """Test that container base raises NotImplementedError for file deploy."""

    @pytest.mark.asyncio
    async def test_deploy_raises_not_implemented(self):
        from app.services.deployment.container_base import BaseContainerDeploymentProvider
        from app.services.deployment.base import DeploymentConfig

        class TestProvider(BaseContainerDeploymentProvider):
            def validate_credentials(self):
                pass
            async def test_credentials(self):
                return {}
            async def push_image(self, image_ref):
                return image_ref
            async def deploy_image(self, config):
                pass
            async def get_deployment_status(self, deployment_id):
                return {}
            async def delete_deployment(self, deployment_id):
                return True
            async def get_deployment_logs(self, deployment_id):
                return []

        provider = TestProvider({})
        with pytest.raises(NotImplementedError):
            await provider.deploy([], DeploymentConfig(
                project_id="test",
                project_name="test",
                framework="vite",
            ))


# =============================================================================
# Download Export Provider Tests
# =============================================================================


class TestDownloadExportProvider:
    """Test the download export provider."""

    @pytest.mark.asyncio
    async def test_deploy_creates_zip(self):
        from app.services.deployment.providers.download_export import DownloadExportProvider
        from app.services.deployment.base import DeploymentConfig, DeploymentFile

        provider = DownloadExportProvider({})
        files = [
            DeploymentFile(path="index.html", content=b"<h1>Hello</h1>"),
            DeploymentFile(path="style.css", content=b"body { color: red; }"),
        ]
        config = DeploymentConfig(
            project_id="test", project_name="test-app", framework="vite"
        )

        result = await provider.deploy(files, config)
        assert result.success is True
        assert result.metadata["format"] == "zip"
        assert result.metadata["file_count"] == 2

    @pytest.mark.asyncio
    async def test_deploy_empty_files_fails(self):
        from app.services.deployment.providers.download_export import DownloadExportProvider
        from app.services.deployment.base import DeploymentConfig

        provider = DownloadExportProvider({})
        config = DeploymentConfig(
            project_id="test", project_name="test-app", framework="vite"
        )

        result = await provider.deploy([], config)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_no_credentials_required(self):
        from app.services.deployment.providers.download_export import DownloadExportProvider

        provider = DownloadExportProvider({})
        provider.validate_credentials()  # Should not raise
        result = await provider.test_credentials()
        assert result["valid"] is True
