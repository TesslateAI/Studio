"""
Tests for deployment manager.

Tests the factory pattern, provider registration, and deployment orchestration.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile
import os

from app.services.deployment.manager import DeploymentManager, deployment_manager
from app.services.deployment.base import (
    BaseDeploymentProvider,
    DeploymentConfig,
    DeploymentFile,
    DeploymentResult
)
from app.services.deployment.providers.cloudflare import CloudflareWorkersProvider
from app.services.deployment.providers.vercel import VercelProvider
from app.services.deployment.providers.netlify import NetlifyProvider


class TestDeploymentManager:
    """Tests for DeploymentManager class."""

    def test_get_provider_cloudflare(self):
        """Test getting Cloudflare provider."""
        credentials = {
            "account_id": "test-account",
            "api_token": "test-token"
        }

        provider = DeploymentManager.get_provider("cloudflare", credentials)

        assert isinstance(provider, CloudflareWorkersProvider)
        assert provider.credentials == credentials

    def test_get_provider_vercel(self):
        """Test getting Vercel provider."""
        credentials = {"token": "test-token"}

        provider = DeploymentManager.get_provider("vercel", credentials)

        assert isinstance(provider, VercelProvider)
        assert provider.credentials == credentials

    def test_get_provider_netlify(self):
        """Test getting Netlify provider."""
        credentials = {"token": "test-token"}

        provider = DeploymentManager.get_provider("netlify", credentials)

        assert isinstance(provider, NetlifyProvider)
        assert provider.credentials == credentials

    def test_get_provider_case_insensitive(self):
        """Test provider name is case insensitive."""
        credentials = {"token": "test-token"}

        provider1 = DeploymentManager.get_provider("VERCEL", credentials)
        provider2 = DeploymentManager.get_provider("Vercel", credentials)
        provider3 = DeploymentManager.get_provider("vercel", credentials)

        assert isinstance(provider1, VercelProvider)
        assert isinstance(provider2, VercelProvider)
        assert isinstance(provider3, VercelProvider)

    def test_get_provider_unknown(self):
        """Test getting unknown provider raises error."""
        credentials = {"token": "test-token"}

        with pytest.raises(ValueError, match="Unknown provider: unknown"):
            DeploymentManager.get_provider("unknown", credentials)

        # Check error message includes available providers
        try:
            DeploymentManager.get_provider("invalid", credentials)
        except ValueError as e:
            assert "cloudflare" in str(e).lower()
            assert "vercel" in str(e).lower()
            assert "netlify" in str(e).lower()

    def test_list_available_providers(self):
        """Test listing available providers."""
        providers = DeploymentManager.list_available_providers()

        assert len(providers) == 3

        # Check Cloudflare
        cloudflare = next(p for p in providers if p["name"] == "cloudflare")
        assert cloudflare["display_name"] == "Cloudflare Workers"
        assert cloudflare["auth_type"] == "api_token"
        assert "account_id" in cloudflare["required_credentials"]
        assert "api_token" in cloudflare["required_credentials"]

        # Check Vercel
        vercel = next(p for p in providers if p["name"] == "vercel")
        assert vercel["display_name"] == "Vercel"
        assert vercel["auth_type"] == "oauth"
        assert "token" in vercel["required_credentials"]

        # Check Netlify
        netlify = next(p for p in providers if p["name"] == "netlify")
        assert netlify["display_name"] == "Netlify"
        assert netlify["auth_type"] == "oauth"
        assert "token" in netlify["required_credentials"]

    def test_register_provider(self):
        """Test registering custom provider."""
        class CustomProvider(BaseDeploymentProvider):
            def validate_credentials(self):
                pass

            async def deploy(self, files, config):
                pass

            async def get_deployment_status(self, deployment_id):
                pass

            async def delete_deployment(self, deployment_id):
                pass

            async def get_deployment_logs(self, deployment_id):
                pass

        # Register new provider
        DeploymentManager.register_provider("custom", CustomProvider)

        # Verify it's registered
        assert "custom" in DeploymentManager._providers

        # Verify we can instantiate it
        provider = DeploymentManager.get_provider("custom", {})
        assert isinstance(provider, CustomProvider)

        # Clean up
        del DeploymentManager._providers["custom"]

    def test_register_provider_invalid_class(self):
        """Test registering invalid provider class."""
        class NotAProvider:
            pass

        with pytest.raises(ValueError, match="must inherit from BaseDeploymentProvider"):
            DeploymentManager.register_provider("invalid", NotAProvider)

    def test_is_provider_available(self):
        """Test checking provider availability."""
        assert DeploymentManager.is_provider_available("cloudflare") is True
        assert DeploymentManager.is_provider_available("VERCEL") is True
        assert DeploymentManager.is_provider_available("Netlify") is True
        assert DeploymentManager.is_provider_available("unknown") is False
        assert DeploymentManager.is_provider_available("") is False

    @pytest.mark.asyncio
    async def test_deploy_project_success(self, tmp_path):
        """Test successful project deployment."""
        # Create temporary project with build output
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html>Test</html>")

        config = DeploymentConfig(
            project_id="test-123",
            project_name="Test Project",
            framework="vite"
        )

        credentials = {
            "account_id": "test-account",
            "api_token": "test-token"
        }

        # Mock the provider's deploy method
        mock_result = DeploymentResult(
            success=True,
            deployment_id="deploy-123",
            deployment_url="https://test.workers.dev",
            logs=["Deployment successful"]
        )

        with patch.object(
            CloudflareWorkersProvider,
            "deploy",
            new_callable=AsyncMock,
            return_value=mock_result
        ):
            result = await DeploymentManager.deploy_project(
                project_path=str(tmp_path),
                provider_name="cloudflare",
                credentials=credentials,
                config=config
            )

            assert result.success is True
            assert result.deployment_id == "deploy-123"
            assert result.deployment_url == "https://test.workers.dev"

    @pytest.mark.asyncio
    async def test_deploy_project_missing_build_output(self, tmp_path):
        """Test deployment with missing build output."""
        config = DeploymentConfig(
            project_id="test-123",
            project_name="Test Project",
            framework="vite"
        )

        credentials = {
            "account_id": "test-account",
            "api_token": "test-token"
        }

        with pytest.raises(FileNotFoundError):
            await DeploymentManager.deploy_project(
                project_path=str(tmp_path),
                provider_name="cloudflare",
                credentials=credentials,
                config=config,
                build_output_dir="dist"  # This doesn't exist
            )

    @pytest.mark.asyncio
    async def test_deploy_project_unknown_provider(self, tmp_path):
        """Test deployment with unknown provider."""
        config = DeploymentConfig(
            project_id="test-123",
            project_name="Test Project",
            framework="vite"
        )

        credentials = {"token": "test-token"}

        with pytest.raises(ValueError, match="Unknown provider"):
            await DeploymentManager.deploy_project(
                project_path=str(tmp_path),
                provider_name="unknown-provider",
                credentials=credentials,
                config=config
            )

    def test_singleton_instance(self):
        """Test singleton deployment_manager instance."""
        assert deployment_manager is not None
        assert isinstance(deployment_manager, DeploymentManager)

    @pytest.mark.asyncio
    async def test_deploy_project_custom_build_dir(self, tmp_path):
        """Test deployment with custom build output directory."""
        # Create custom build output directory
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "index.html").write_text("<html>Custom Build</html>")

        config = DeploymentConfig(
            project_id="test-123",
            project_name="Test Project",
            framework="react"  # React uses 'build' directory
        )

        credentials = {"token": "test-token"}

        mock_result = DeploymentResult(
            success=True,
            deployment_id="deploy-123",
            deployment_url="https://test.vercel.app",
            logs=["Deployment successful"]
        )

        with patch.object(
            VercelProvider,
            "deploy",
            new_callable=AsyncMock,
            return_value=mock_result
        ):
            result = await DeploymentManager.deploy_project(
                project_path=str(tmp_path),
                provider_name="vercel",
                credentials=credentials,
                config=config,
                build_output_dir="build"
            )

            assert result.success is True

    @pytest.mark.asyncio
    async def test_deploy_project_with_env_vars(self, tmp_path):
        """Test deployment with environment variables."""
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html>Test</html>")

        config = DeploymentConfig(
            project_id="test-123",
            project_name="Test Project",
            framework="vite",
            env_vars={
                "API_URL": "https://api.example.com",
                "NODE_ENV": "production"
            }
        )

        credentials = {"token": "test-token"}

        mock_result = DeploymentResult(
            success=True,
            deployment_id="deploy-123",
            deployment_url="https://test.netlify.app",
            logs=["Deployment successful"]
        )

        with patch.object(
            NetlifyProvider,
            "deploy",
            new_callable=AsyncMock,
            return_value=mock_result
        ) as mock_deploy:
            result = await DeploymentManager.deploy_project(
                project_path=str(tmp_path),
                provider_name="netlify",
                credentials=credentials,
                config=config
            )

            assert result.success is True

            # Verify env_vars were passed to deploy
            call_args = mock_deploy.call_args
            assert call_args is not None
            deployed_config = call_args[0][1]  # Second argument is config
            assert deployed_config.env_vars == config.env_vars
