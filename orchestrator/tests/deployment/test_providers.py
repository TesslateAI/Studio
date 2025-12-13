"""
Comprehensive tests for deployment providers.

Tests cover:
- Base provider interface and helpers
- Cloudflare Workers provider
- Vercel provider
- Netlify provider
- Error handling and edge cases
"""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import tempfile
import os
from pathlib import Path

from app.services.deployment.base import (
    BaseDeploymentProvider,
    DeploymentConfig,
    DeploymentFile,
    DeploymentResult
)
from app.services.deployment.providers.cloudflare import CloudflareWorkersProvider
from app.services.deployment.providers.vercel import VercelProvider
from app.services.deployment.providers.netlify import NetlifyProvider


# Test Fixtures

@pytest.fixture
def sample_files():
    """Create sample deployment files."""
    return [
        DeploymentFile(
            path="index.html",
            content=b"<html><body>Hello World</body></html>"
        ),
        DeploymentFile(
            path="assets/style.css",
            content=b"body { margin: 0; }"
        ),
        DeploymentFile(
            path="assets/app.js",
            content=b"console.log('Hello');"
        )
    ]


@pytest.fixture
def deployment_config():
    """Create sample deployment configuration."""
    return DeploymentConfig(
        project_id="test-project-123",
        project_name="Test Project",
        framework="vite",
        env_vars={"API_URL": "https://api.example.com"}
    )


@pytest.fixture
def temp_project_dir(tmp_path):
    """Create temporary project directory with build output."""
    # Create dist directory with files
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    (dist_dir / "index.html").write_text("<html><body>Test</body></html>")
    (dist_dir / "style.css").write_text("body { margin: 0; }")

    # Create subdirectory
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log('test');")

    return str(tmp_path)


# Cloudflare Workers Provider Tests

class TestCloudflareWorkersProvider:
    """Tests for Cloudflare Workers provider."""

    def test_validate_credentials_success(self):
        """Test successful credential validation."""
        credentials = {
            "account_id": "test-account-123",
            "api_token": "test-token-456"
        }
        provider = CloudflareWorkersProvider(credentials)
        assert provider.credentials == credentials

    def test_validate_credentials_missing_account_id(self):
        """Test credential validation fails with missing account_id."""
        credentials = {"api_token": "test-token-456"}
        with pytest.raises(ValueError, match="Missing required Cloudflare credential: account_id"):
            CloudflareWorkersProvider(credentials)

    def test_validate_credentials_missing_api_token(self):
        """Test credential validation fails with missing api_token."""
        credentials = {"account_id": "test-account-123"}
        with pytest.raises(ValueError, match="Missing required Cloudflare credential: api_token"):
            CloudflareWorkersProvider(credentials)

    def test_create_asset_manifest(self, sample_files):
        """Test asset manifest creation."""
        credentials = {
            "account_id": "test-account-123",
            "api_token": "test-token-456"
        }
        provider = CloudflareWorkersProvider(credentials)
        manifest = provider._create_asset_manifest(sample_files)

        # Check manifest structure
        assert "/index.html" in manifest
        assert "/assets/style.css" in manifest
        assert "/assets/app.js" in manifest

        # Check manifest content
        assert "hash" in manifest["/index.html"]
        assert "size" in manifest["/index.html"]
        assert manifest["/index.html"]["size"] == len(sample_files[0].content)

    def test_generate_worker_script(self, deployment_config):
        """Test worker script generation."""
        credentials = {
            "account_id": "test-account-123",
            "api_token": "test-token-456"
        }
        provider = CloudflareWorkersProvider(credentials)
        script = provider._generate_worker_script(deployment_config)

        # Check script contains expected elements
        assert "export default" in script
        assert "async fetch" in script
        assert "env.ASSETS.fetch" in script
        assert "index.html" in script

    @pytest.mark.asyncio
    async def test_deploy_success(self, sample_files, deployment_config):
        """Test successful deployment flow."""
        credentials = {
            "account_id": "test-account-123",
            "api_token": "test-token-456"
        }
        provider = CloudflareWorkersProvider(credentials)

        # Mock HTTP responses
        mock_session_response = {
            "result": {
                "jwt": "test-jwt-token",
                "buckets": [["hash1", "hash2"]]
            }
        }

        mock_upload_response = {
            "result": {"jwt": "completion-jwt-token"}
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock()
            mock_instance.put = AsyncMock()

            # Configure mock responses
            mock_instance.post.side_effect = [
                MagicMock(
                    status_code=200,
                    json=lambda: mock_session_response,
                    raise_for_status=lambda: None
                ),
                MagicMock(
                    status_code=200,
                    json=lambda: mock_upload_response,
                    raise_for_status=lambda: None
                )
            ]

            mock_instance.put.return_value = MagicMock(
                status_code=200,
                raise_for_status=lambda: None
            )

            result = await provider.deploy(sample_files, deployment_config)

            assert result.success is True
            assert result.deployment_id is not None
            assert result.deployment_url is not None
            assert "Deployment successful" in result.logs[-1]

    @pytest.mark.asyncio
    async def test_deploy_api_error(self, sample_files, deployment_config):
        """Test deployment with API error."""
        credentials = {
            "account_id": "test-account-123",
            "api_token": "test-token-456"
        }
        provider = CloudflareWorkersProvider(credentials)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_response.text = "Forbidden"
            mock_instance.post = AsyncMock(side_effect=httpx.HTTPStatusError(
                "Error", request=MagicMock(), response=mock_response
            ))

            result = await provider.deploy(sample_files, deployment_config)

            assert result.success is False
            assert "Cloudflare API error" in result.error
            assert "403" in result.error

    @pytest.mark.asyncio
    async def test_get_deployment_status(self):
        """Test getting deployment status."""
        credentials = {
            "account_id": "test-account-123",
            "api_token": "test-token-456"
        }
        provider = CloudflareWorkersProvider(credentials)

        mock_response = {
            "result": {"id": "worker-123", "created_on": "2025-01-15"}
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(return_value=MagicMock(
                status_code=200,
                json=lambda: mock_response,
                raise_for_status=lambda: None
            ))

            status = await provider.get_deployment_status("test-worker")

            assert status["status"] == "deployed"
            assert "script" in status

    @pytest.mark.asyncio
    async def test_delete_deployment(self):
        """Test deleting deployment."""
        credentials = {
            "account_id": "test-account-123",
            "api_token": "test-token-456"
        }
        provider = CloudflareWorkersProvider(credentials)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.delete = AsyncMock(return_value=MagicMock(status_code=200))

            result = await provider.delete_deployment("test-worker")

            assert result is True


# Vercel Provider Tests

class TestVercelProvider:
    """Tests for Vercel provider."""

    def test_validate_credentials_success(self):
        """Test successful credential validation."""
        credentials = {"token": "test-token-123"}
        provider = VercelProvider(credentials)
        assert provider.credentials == credentials

    def test_validate_credentials_missing_token(self):
        """Test credential validation fails with missing token."""
        credentials = {}
        with pytest.raises(ValueError, match="Missing required Vercel credential: token"):
            VercelProvider(credentials)

    def test_map_framework(self):
        """Test framework name mapping."""
        credentials = {"token": "test-token-123"}
        provider = VercelProvider(credentials)

        assert provider._map_framework("vite") == "vite"
        assert provider._map_framework("nextjs") == "nextjs"
        assert provider._map_framework("react") == "create-react-app"
        assert provider._map_framework("unknown") is None

    @pytest.mark.asyncio
    async def test_deploy_success(self, sample_files, deployment_config):
        """Test successful deployment flow."""
        credentials = {"token": "test-token-123"}
        provider = VercelProvider(credentials)

        mock_create_response = {
            "id": "deployment-123",
            "url": "test-project.vercel.app",
            "readyState": "BUILDING"
        }

        mock_status_response = {
            "readyState": "READY"
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value

            # Mock deployment creation
            mock_instance.post = AsyncMock(return_value=MagicMock(
                status_code=200,
                json=lambda: mock_create_response,
                raise_for_status=lambda: None
            ))

            # Mock status polling
            mock_instance.get = AsyncMock(return_value=MagicMock(
                status_code=200,
                json=lambda: mock_status_response,
                raise_for_status=lambda: None
            ))

            result = await provider.deploy(sample_files, deployment_config)

            assert result.success is True
            assert result.deployment_id == "deployment-123"
            assert "vercel.app" in result.deployment_url

    @pytest.mark.asyncio
    async def test_wait_for_deployment_timeout(self):
        """Test deployment timeout handling."""
        credentials = {"token": "test-token-123"}
        provider = VercelProvider(credentials)

        logs = []

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(return_value=MagicMock(
                status_code=200,
                json=lambda: {"readyState": "BUILDING"},
                raise_for_status=lambda: None
            ))

            # Use very short timeout for testing
            state = await provider._wait_for_deployment("test-123", logs, max_wait=1)

            assert state == "TIMEOUT"
            assert any("timed out" in log.lower() for log in logs)

    @pytest.mark.asyncio
    async def test_get_deployment_logs(self):
        """Test fetching deployment logs."""
        credentials = {"token": "test-token-123"}
        provider = VercelProvider(credentials)

        mock_events = [
            {"type": "stdout", "payload": {"text": "Building..."}},
            {"type": "stderr", "payload": {"text": "Warning: deprecated"}}
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(return_value=MagicMock(
                status_code=200,
                json=lambda: mock_events
            ))

            logs = await provider.get_deployment_logs("test-123")

            assert len(logs) == 2
            assert "Building..." in logs[0]
            assert "Warning" in logs[1]


# Netlify Provider Tests

class TestNetlifyProvider:
    """Tests for Netlify provider."""

    def test_validate_credentials_success(self):
        """Test successful credential validation."""
        credentials = {"token": "test-token-123"}
        provider = NetlifyProvider(credentials)
        assert provider.credentials == credentials

    def test_validate_credentials_missing_token(self):
        """Test credential validation fails with missing token."""
        credentials = {}
        with pytest.raises(ValueError, match="Missing required Netlify credential: token"):
            NetlifyProvider(credentials)

    @pytest.mark.asyncio
    async def test_get_or_create_site_existing(self):
        """Test getting existing site."""
        credentials = {"token": "test-token-123"}
        provider = NetlifyProvider(credentials)

        mock_sites = [
            {"id": "site-123", "name": "test-project"},
            {"id": "site-456", "name": "other-project"}
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(return_value=MagicMock(
                status_code=200,
                json=lambda: mock_sites,
                raise_for_status=lambda: None
            ))

            site_id = await provider._get_or_create_site("test-project")

            assert site_id == "site-123"

    @pytest.mark.asyncio
    async def test_get_or_create_site_new(self):
        """Test creating new site."""
        credentials = {"token": "test-token-123"}
        provider = NetlifyProvider(credentials)

        mock_sites = []
        mock_new_site = {"id": "new-site-789", "name": "new-project"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value

            # Mock GET (no existing sites) and POST (create new)
            mock_instance.get = AsyncMock(return_value=MagicMock(
                status_code=200,
                json=lambda: mock_sites,
                raise_for_status=lambda: None
            ))

            mock_instance.post = AsyncMock(return_value=MagicMock(
                status_code=200,
                json=lambda: mock_new_site,
                raise_for_status=lambda: None
            ))

            site_id = await provider._get_or_create_site("new-project")

            assert site_id == "new-site-789"

    @pytest.mark.asyncio
    async def test_deploy_success(self, sample_files, deployment_config):
        """Test successful deployment flow."""
        credentials = {"token": "test-token-123"}
        provider = NetlifyProvider(credentials)

        mock_deploy = {
            "id": "deploy-123",
            "state": "processing",
            "required": ["hash1", "hash2"],
            "ssl_url": "https://test-project.netlify.app"
        }

        mock_status = {
            "state": "ready"
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value

            # Mock get sites, create deploy, upload files, check status
            mock_instance.get = AsyncMock()
            mock_instance.post = AsyncMock()
            mock_instance.put = AsyncMock()

            # Configure side effects for different calls
            mock_instance.get.side_effect = [
                # Get sites
                MagicMock(status_code=200, json=lambda: [{"id": "site-123", "name": "test-project"}], raise_for_status=lambda: None),
                # Check deploy status
                MagicMock(status_code=200, json=lambda: mock_status, raise_for_status=lambda: None)
            ]

            mock_instance.post.return_value = MagicMock(
                status_code=200,
                json=lambda: mock_deploy,
                raise_for_status=lambda: None
            )

            mock_instance.put.return_value = MagicMock(
                status_code=200,
                raise_for_status=lambda: None
            )

            result = await provider.deploy(sample_files, deployment_config)

            assert result.success is True
            assert result.deployment_id == "deploy-123"
            assert "netlify.app" in result.deployment_url


# Base Provider Tests

class TestBaseProvider:
    """Tests for base provider functionality."""

    @pytest.mark.asyncio
    async def test_collect_files_from_container(self, temp_project_dir):
        """Test file collection from container."""
        # Create a concrete implementation for testing
        class TestProvider(BaseDeploymentProvider):
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

        provider = TestProvider({})
        files = await provider.collect_files_from_container(temp_project_dir, "dist")

        assert len(files) == 3  # index.html, style.css, app.js
        paths = [f.path for f in files]
        assert "index.html" in paths
        assert "style.css" in paths
        assert os.path.join("assets", "app.js") in paths or "assets/app.js" in paths

    @pytest.mark.asyncio
    async def test_collect_files_missing_directory(self):
        """Test file collection with missing directory."""
        class TestProvider(BaseDeploymentProvider):
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

        provider = TestProvider({})

        with pytest.raises(FileNotFoundError):
            await provider.collect_files_from_container("/nonexistent/path", "dist")

    def test_get_framework_config(self):
        """Test framework configuration lookup."""
        class TestProvider(BaseDeploymentProvider):
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

        provider = TestProvider({})

        # Test known frameworks
        vite_config = provider.get_framework_config("vite")
        assert vite_config["output_dir"] == "dist"
        assert vite_config["build_command"] == "npm run build"

        nextjs_config = provider.get_framework_config("nextjs")
        assert nextjs_config["output_dir"] == ".next"
        assert nextjs_config.get("requires_server") is True

        # Test unknown framework (should return default)
        unknown_config = provider.get_framework_config("unknown-framework")
        assert unknown_config["output_dir"] == "dist"
        assert unknown_config["build_command"] == "npm run build"

    def test_sanitize_name(self):
        """Test name sanitization."""
        class TestProvider(BaseDeploymentProvider):
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

        provider = TestProvider({})

        assert provider._sanitize_name("My Project") == "my-project"
        assert provider._sanitize_name("Test_Project") == "test-project"
        assert provider._sanitize_name("Project@123!") == "project123"
        assert provider._sanitize_name("---test---") == "test"

        # Test length limit
        long_name = "a" * 100
        sanitized = provider._sanitize_name(long_name)
        assert len(sanitized) <= 63
