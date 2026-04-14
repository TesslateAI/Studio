"""
Comprehensive tests for all 19 new deployment providers.

Tests cover:
- Credential validation (missing fields -> ValueError)
- Credential validation (valid credentials -> no error)
- test_credentials() with mocked httpx responses
- deploy() with mocked httpx responses for key providers
- Shared utility functions (tarball, zip, poll, graphql)
- DownloadExportProvider deploy (no HTTP needed)

- BaseContainerDeploymentProvider.deploy raises NotImplementedError
"""

import io
import json
import tarfile
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.mocked

import httpx

from app.services.deployment.base import DeploymentConfig, DeploymentFile, DeploymentResult
from app.services.deployment.container_base import (
    BaseContainerDeploymentProvider,
)
from app.services.deployment.providers.utils import (
    create_source_tarball,
    create_source_zip,
    graphql_request,
    poll_until_terminal,
)


def _mock_response(status_code=200, json_data=None, text=""):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or json.dumps(json_data or {})
    resp.json = lambda: json_data or {}
    resp.raise_for_status = lambda: None
    resp.headers = {"content-type": "application/json"}
    return resp


# ============================================================================
# Shared Utilities Tests
# ============================================================================


class TestCreateSourceTarball:
    def test_creates_valid_tarball(self):
        files = [
            DeploymentFile(path="index.html", content=b"<html>hello</html>"),
            DeploymentFile(path="style.css", content=b"body{}"),
        ]
        result = create_source_tarball(files)
        assert isinstance(result, bytes)
        assert len(result) > 0

        buf = io.BytesIO(result)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            names = tar.getnames()
            assert "index.html" in names
            assert "style.css" in names

    def test_empty_files(self):
        result = create_source_tarball([])
        assert isinstance(result, bytes)


class TestCreateSourceZip:
    def test_creates_valid_zip(self):
        files = [
            DeploymentFile(path="index.html", content=b"<html>hello</html>"),
            DeploymentFile(path="app.js", content=b"console.log('hi')"),
        ]
        result = create_source_zip(files)
        assert isinstance(result, bytes)

        buf = io.BytesIO(result)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert "index.html" in names
            assert "app.js" in names


class TestPollUntilTerminal:
    @pytest.mark.asyncio
    async def test_returns_on_terminal_state(self):
        check_fn = AsyncMock(return_value={"status": "SUCCESS"})
        result = await poll_until_terminal(
            check_fn, terminal_states={"SUCCESS", "FAILED"}, interval=0
        )
        assert result["status"] == "SUCCESS"

    @pytest.mark.asyncio
    async def test_polls_until_terminal(self):
        call_count = 0

        async def check():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return {"status": "READY"}
            return {"status": "BUILDING"}

        result = await poll_until_terminal(
            check, terminal_states={"READY", "FAILED"}, interval=0, timeout=10
        )
        assert result["status"] == "READY"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        check_fn = AsyncMock(return_value={"status": "BUILDING"})
        with pytest.raises(TimeoutError):
            await poll_until_terminal(check_fn, terminal_states={"DONE"}, interval=0, timeout=0)


class TestGraphqlRequest:
    @pytest.mark.asyncio
    async def test_returns_data(self):
        from unittest.mock import MagicMock

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"me": {"id": "123"}}}
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        result = await graphql_request(
            mock_client, "https://api.example.com/graphql", "{ me { id } }"
        )
        assert result == {"me": {"id": "123"}}

    @pytest.mark.asyncio
    async def test_raises_on_graphql_errors(self):
        from unittest.mock import MagicMock

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {"errors": [{"message": "Unauthorized"}]}
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        with pytest.raises(ValueError, match="GraphQL errors"):
            await graphql_request(mock_client, "https://api.example.com/graphql", "{ me { id } }")


# ============================================================================
# Source-Upload Provider Credential Validation Tests
# ============================================================================


class TestHerokuProvider:
    def test_validate_missing_creds(self):
        from app.services.deployment.providers.heroku import HerokuProvider

        with pytest.raises(ValueError, match="api_key"):
            HerokuProvider(credentials={})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.heroku import HerokuProvider

        provider = HerokuProvider(credentials={"api_key": "test-key"})
        assert provider.credentials["api_key"] == "test-key"


class TestKoyebProvider:
    def test_validate_missing_creds(self):
        from app.services.deployment.providers.koyeb import KoyebProvider

        with pytest.raises(ValueError, match="api_token"):
            KoyebProvider(credentials={})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.koyeb import KoyebProvider

        provider = KoyebProvider(credentials={"api_token": "test-token"})
        assert provider.credentials["api_token"] == "test-token"


class TestZeaburProvider:
    def test_validate_missing_creds(self):
        from app.services.deployment.providers.zeabur import ZeaburProvider

        with pytest.raises(ValueError, match="api_key"):
            ZeaburProvider(credentials={})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.zeabur import ZeaburProvider

        provider = ZeaburProvider(credentials={"api_key": "test-key"})
        assert provider.credentials["api_key"] == "test-key"


class TestSurgeProvider:
    def test_validate_missing_email(self):
        from app.services.deployment.providers.surge import SurgeProvider

        with pytest.raises(ValueError):
            SurgeProvider(credentials={"token": "t"})

    def test_validate_missing_token(self):
        from app.services.deployment.providers.surge import SurgeProvider

        with pytest.raises(ValueError):
            SurgeProvider(credentials={"email": "e@e.com"})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.surge import SurgeProvider

        provider = SurgeProvider(credentials={"email": "e@e.com", "token": "t"})
        assert provider.credentials["email"] == "e@e.com"


class TestDenoDeployProvider:
    def test_validate_missing_token(self):
        from app.services.deployment.providers.deno_deploy import DenoDeployProvider

        with pytest.raises(ValueError):
            DenoDeployProvider(credentials={"org_id": "o"})

    def test_validate_missing_org_id(self):
        from app.services.deployment.providers.deno_deploy import DenoDeployProvider

        with pytest.raises(ValueError):
            DenoDeployProvider(credentials={"token": "t"})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.deno_deploy import DenoDeployProvider

        provider = DenoDeployProvider(credentials={"token": "t", "org_id": "o"})
        assert provider.credentials["org_id"] == "o"


class TestFirebaseHostingProvider:
    def test_validate_missing_sa_json(self):
        from app.services.deployment.providers.firebase import FirebaseHostingProvider

        with pytest.raises(ValueError):
            FirebaseHostingProvider(credentials={"site_id": "s"})

    def test_validate_missing_site_id(self):
        from app.services.deployment.providers.firebase import FirebaseHostingProvider

        with pytest.raises(ValueError):
            FirebaseHostingProvider(credentials={"service_account_json": "{}"})

    def test_validate_valid_creds(self):
        import json

        from app.services.deployment.providers.firebase import FirebaseHostingProvider

        sa_json = json.dumps(
            {
                "client_email": "test@test.iam.gserviceaccount.com",
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n",
                "project_id": "test-project",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        provider = FirebaseHostingProvider(
            credentials={"service_account_json": sa_json, "site_id": "my-site"}
        )
        assert provider.credentials["site_id"] == "my-site"


# ============================================================================
# Git-Repo-Required Provider Credential Validation Tests
# ============================================================================


class TestRailwayProvider:
    def test_validate_missing_creds(self):
        from app.services.deployment.providers.railway import RailwayProvider

        with pytest.raises(ValueError, match="token"):
            RailwayProvider(credentials={})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.railway import RailwayProvider

        provider = RailwayProvider(credentials={"token": "test-token"})
        assert provider.credentials["token"] == "test-token"


class TestRenderProvider:
    def test_validate_missing_creds(self):
        from app.services.deployment.providers.render import RenderProvider

        with pytest.raises(ValueError, match="api_key"):
            RenderProvider(credentials={})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.render import RenderProvider

        provider = RenderProvider(credentials={"api_key": "test-key"})
        assert provider.credentials["api_key"] == "test-key"


class TestNorthflankProvider:
    def test_validate_missing_creds(self):
        from app.services.deployment.providers.northflank import NorthflankProvider

        with pytest.raises(ValueError, match="api_token"):
            NorthflankProvider(credentials={})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.northflank import NorthflankProvider

        provider = NorthflankProvider(credentials={"api_token": "test-token"})
        assert provider.credentials["api_token"] == "test-token"


class TestGitHubPagesProvider:
    def test_validate_missing_creds(self):
        from app.services.deployment.providers.github_pages import GitHubPagesProvider

        with pytest.raises(ValueError, match="token"):
            GitHubPagesProvider(credentials={})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.github_pages import GitHubPagesProvider

        provider = GitHubPagesProvider(credentials={"token": "ghp_test"})
        assert provider.credentials["token"] == "ghp_test"


# ============================================================================
# Container-Push Provider Credential Validation Tests
# ============================================================================


class TestAWSContainerProvider:
    def test_validate_missing_access_key(self):
        from app.services.deployment.providers.aws_container import AWSContainerProvider

        with pytest.raises(ValueError):
            AWSContainerProvider(credentials={"aws_secret_access_key": "s", "aws_region": "r"})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.aws_container import AWSContainerProvider

        provider = AWSContainerProvider(
            credentials={
                "aws_access_key_id": "AKID",
                "aws_secret_access_key": "secret",
                "aws_region": "us-east-1",
            }
        )
        assert provider.credentials["aws_region"] == "us-east-1"


class TestGCPContainerProvider:
    def test_validate_missing_sa_json(self):
        from app.services.deployment.providers.gcp_container import GCPContainerProvider

        with pytest.raises(ValueError):
            GCPContainerProvider(credentials={"gcp_region": "us-central1"})

    def test_validate_valid_creds(self):
        import json

        from app.services.deployment.providers.gcp_container import GCPContainerProvider

        sa_json = json.dumps(
            {
                "client_email": "test@test.iam.gserviceaccount.com",
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----\n",
                "project_id": "test-project",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        provider = GCPContainerProvider(
            credentials={"service_account_json": sa_json, "gcp_region": "us-central1"}
        )
        assert provider.credentials["gcp_region"] == "us-central1"


class TestAzureContainerProvider:
    def test_validate_missing_tenant(self):
        from app.services.deployment.providers.azure_container import AzureContainerProvider

        with pytest.raises(ValueError):
            AzureContainerProvider(credentials={"client_id": "x"})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.azure_container import AzureContainerProvider

        provider = AzureContainerProvider(
            credentials={
                "tenant_id": "t",
                "client_id": "c",
                "client_secret": "s",
                "subscription_id": "sub",
                "resource_group": "rg",
                "registry_name": "acr",
                "azure_region": "eastus",
                "container_app_environment_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/managedEnvironments/env",
            }
        )
        assert provider.credentials["tenant_id"] == "t"


class TestDigitalOceanContainerProvider:
    def test_validate_missing_token(self):
        from app.services.deployment.providers.do_container import DigitalOceanContainerProvider

        with pytest.raises(ValueError):
            DigitalOceanContainerProvider(credentials={"registry_name": "r"})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.do_container import DigitalOceanContainerProvider

        provider = DigitalOceanContainerProvider(
            credentials={"api_token": "t", "registry_name": "r"}
        )
        assert provider.credentials["registry_name"] == "r"


class TestFlyProvider:
    def test_validate_missing_creds(self):
        from app.services.deployment.providers.fly import FlyProvider

        with pytest.raises(ValueError, match="api_token"):
            FlyProvider(credentials={})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.fly import FlyProvider

        provider = FlyProvider(credentials={"api_token": "test-token"})
        assert provider.credentials["api_token"] == "test-token"


# ============================================================================
# Export Provider Tests
# ============================================================================


class TestDockerHubExportProvider:
    def test_validate_missing_username(self):
        from app.services.deployment.providers.dockerhub_export import DockerHubExportProvider

        with pytest.raises(ValueError):
            DockerHubExportProvider(credentials={"token": "t"})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.dockerhub_export import DockerHubExportProvider

        provider = DockerHubExportProvider(credentials={"username": "user", "token": "pat"})
        assert provider.credentials["username"] == "user"


class TestGHCRExportProvider:
    def test_validate_missing_username(self):
        from app.services.deployment.providers.ghcr_export import GHCRExportProvider

        with pytest.raises(ValueError):
            GHCRExportProvider(credentials={"token": "t"})

    def test_validate_valid_creds(self):
        from app.services.deployment.providers.ghcr_export import GHCRExportProvider

        provider = GHCRExportProvider(credentials={"username": "user", "token": "ghp_xxx"})
        assert provider.credentials["username"] == "user"


class TestDownloadExportProvider:
    def test_validate_no_creds_needed(self):
        from app.services.deployment.providers.download_export import DownloadExportProvider

        provider = DownloadExportProvider(credentials={})
        assert provider is not None

    @pytest.mark.asyncio
    async def test_deploy_creates_zip(self):
        from app.services.deployment.providers.download_export import DownloadExportProvider

        provider = DownloadExportProvider(credentials={})
        files = [
            DeploymentFile(path="index.html", content=b"<html>test</html>"),
            DeploymentFile(path="app.js", content=b"alert('hi')"),
        ]
        config = DeploymentConfig(
            project_id="test-123",
            project_name="Test Project",
            framework="vite",
        )
        result = await provider.deploy(files, config)
        assert result.success is True
        assert result.metadata.get("format") == "zip"
        assert result.metadata.get("size_bytes") > 0

    @pytest.mark.asyncio
    async def test_test_credentials(self):
        from app.services.deployment.providers.download_export import DownloadExportProvider

        provider = DownloadExportProvider(credentials={})
        result = await provider.test_credentials()
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_deploy_empty_files(self):
        from app.services.deployment.providers.download_export import DownloadExportProvider

        provider = DownloadExportProvider(credentials={})
        config = DeploymentConfig(
            project_id="test-123",
            project_name="Empty Project",
            framework="vite",
        )
        result = await provider.deploy([], config)
        assert result.success is False
        assert "No files" in result.error

    @pytest.mark.asyncio
    async def test_get_deployment_status(self):
        from app.services.deployment.providers.download_export import DownloadExportProvider

        provider = DownloadExportProvider(credentials={})
        status = await provider.get_deployment_status("test-id")
        assert status["status"] == "completed"

    @pytest.mark.asyncio
    async def test_delete_deployment(self):
        from app.services.deployment.providers.download_export import DownloadExportProvider

        provider = DownloadExportProvider(credentials={})
        result = await provider.delete_deployment("test-id")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_deployment_logs(self):
        from app.services.deployment.providers.download_export import DownloadExportProvider

        provider = DownloadExportProvider(credentials={})
        logs = await provider.get_deployment_logs("test-id")
        assert logs == []


# ============================================================================
# test_credentials() with mocked HTTP responses
# ============================================================================


class TestHerokuTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.heroku import HerokuProvider

        provider = HerokuProvider(credentials={"api_key": "test-key"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                return_value=_mock_response(json_data={"email": "u@test.com", "id": "uid"})
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["email"] == "u@test.com"

    @pytest.mark.asyncio
    async def test_401_raises(self):
        from app.services.deployment.providers.heroku import HerokuProvider

        provider = HerokuProvider(credentials={"api_key": "bad"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized"
            mock_instance.get = AsyncMock(
                side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=mock_resp)
            )
            with pytest.raises(ValueError, match="Invalid Heroku API key"):
                await provider.test_credentials()


class TestKoyebTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.koyeb import KoyebProvider

        provider = KoyebProvider(credentials={"api_token": "test-token"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                return_value=_mock_response(json_data={"user": {"name": "alice"}})
            )
            result = await provider.test_credentials()
            assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_401_raises(self):
        from app.services.deployment.providers.koyeb import KoyebProvider

        provider = KoyebProvider(credentials={"api_token": "bad"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized"
            mock_instance.get = AsyncMock(
                side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=mock_resp)
            )
            with pytest.raises(ValueError, match="Invalid Koyeb API token"):
                await provider.test_credentials()


class TestRailwayTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.railway import RailwayProvider

        provider = RailwayProvider(credentials={"token": "tok"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(
                return_value=_mock_response(
                    json_data={"data": {"me": {"id": "uid", "email": "u@test.com"}}}
                )
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["account_name"] == "u@test.com"

    @pytest.mark.asyncio
    async def test_401_raises(self):
        from app.services.deployment.providers.railway import RailwayProvider

        provider = RailwayProvider(credentials={"token": "bad"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized"
            mock_instance.post = AsyncMock(
                side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=mock_resp)
            )
            with pytest.raises(ValueError, match="Invalid Railway token"):
                await provider.test_credentials()


class TestRenderTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.render import RenderProvider

        provider = RenderProvider(credentials={"api_key": "key"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                return_value=_mock_response(json_data=[{"owner": {"name": "Alice", "id": "o1"}}])
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["account_name"] == "Alice"


class TestGitHubPagesTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.github_pages import GitHubPagesProvider

        provider = GitHubPagesProvider(credentials={"token": "tok"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                return_value=_mock_response(json_data={"login": "alice", "id": 42})
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["account_name"] == "alice"


class TestNorthflankTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.northflank import NorthflankProvider

        provider = NorthflankProvider(credentials={"api_token": "tok"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                return_value=_mock_response(json_data={"data": {"name": "Bob", "id": "uid"}})
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["account_name"] == "Bob"


class TestDigitalOceanContainerTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.do_container import DigitalOceanContainerProvider

        provider = DigitalOceanContainerProvider(
            credentials={"api_token": "tok", "registry_name": "r"}
        )
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                return_value=_mock_response(
                    json_data={"account": {"email": "u@test.com", "uuid": "u1", "status": "active"}}
                )
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["email"] == "u@test.com"

    @pytest.mark.asyncio
    async def test_401_raises(self):
        from app.services.deployment.providers.do_container import DigitalOceanContainerProvider

        provider = DigitalOceanContainerProvider(
            credentials={"api_token": "bad", "registry_name": "r"}
        )
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized"
            mock_instance.get = AsyncMock(
                side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=mock_resp)
            )
            with pytest.raises(ValueError, match="Invalid DigitalOcean API token"):
                await provider.test_credentials()


class TestFlyTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.fly import FlyProvider

        provider = FlyProvider(credentials={"api_token": "tok"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                return_value=_mock_response(json_data=[{"organization": {"name": "personal"}}])
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["account_name"] == "personal"


class TestDockerHubTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.dockerhub_export import DockerHubExportProvider

        provider = DockerHubExportProvider(credentials={"username": "user", "token": "tok"})
        with patch(
            "app.services.deployment.providers.dockerhub_export.httpx.AsyncClient"
        ) as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            # First call: _get_hub_jwt (POST login), second call: GET user profile
            mock_instance.post = AsyncMock(
                return_value=_mock_response(json_data={"token": "jwt-token"})
            )
            mock_instance.get = AsyncMock(
                return_value=_mock_response(json_data={"username": "user"})
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["username"] == "user"

    @pytest.mark.asyncio
    async def test_401_raises(self):
        from app.services.deployment.providers.dockerhub_export import DockerHubExportProvider

        provider = DockerHubExportProvider(credentials={"username": "user", "token": "bad"})
        with patch(
            "app.services.deployment.providers.dockerhub_export.httpx.AsyncClient"
        ) as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            # _get_hub_jwt POST returns 401
            mock_instance.post = AsyncMock(
                return_value=_mock_response(status_code=401, json_data={})
            )
            with pytest.raises(ValueError, match="Invalid Docker Hub credentials"):
                await provider.test_credentials()


class TestGHCRTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.ghcr_export import GHCRExportProvider

        provider = GHCRExportProvider(credentials={"username": "user", "token": "tok"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                side_effect=[
                    _mock_response(json_data=[]),
                    _mock_response(json_data={"login": "user"}),
                ]
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["username"] == "user"


class TestDenoDeployTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.deno_deploy import DenoDeployProvider

        provider = DenoDeployProvider(credentials={"token": "tok", "org_id": "org1"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                return_value=_mock_response(json_data={"id": "org1", "name": "MyOrg"})
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["org_name"] == "MyOrg"

    @pytest.mark.asyncio
    async def test_401_raises(self):
        from app.services.deployment.providers.deno_deploy import DenoDeployProvider

        provider = DenoDeployProvider(credentials={"token": "bad", "org_id": "org1"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized"
            mock_instance.get = AsyncMock(
                side_effect=httpx.HTTPStatusError("err", request=MagicMock(), response=mock_resp)
            )
            with pytest.raises(ValueError, match="Invalid Deno Deploy token"):
                await provider.test_credentials()


class TestZeaburTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.zeabur import ZeaburProvider

        provider = ZeaburProvider(credentials={"api_key": "key"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock(
                return_value=_mock_response(
                    json_data={"data": {"me": {"_id": "u1", "username": "bob"}}}
                )
            )
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["username"] == "bob"


class TestSurgeTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.surge import SurgeProvider

        provider = SurgeProvider(credentials={"email": "a@b.com", "token": "tok"})
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.get = AsyncMock(
                return_value=_mock_response(json_data={"email": "a@b.com"})
            )
            result = await provider.test_credentials()
            assert result["valid"] is True


class TestAWSContainerTestCredentials:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.services.deployment.providers.aws_container import AWSContainerProvider

        provider = AWSContainerProvider(
            credentials={
                "aws_access_key_id": "AKID",
                "aws_secret_access_key": "secret",
                "aws_region": "us-east-1",
            }
        )
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {
            "Account": "123456",
            "Arn": "arn:aws:iam::123456:user/test",
        }
        mock_session = MagicMock()
        mock_session.client.return_value = mock_sts
        with patch.object(provider, "_boto_session", return_value=mock_session):
            result = await provider.test_credentials()
            assert result["valid"] is True
            assert result["account_id"] == "123456"


# ============================================================================
# deploy() with mocked HTTP responses for key providers
# ============================================================================


class TestHerokuDeploy:
    @pytest.mark.asyncio
    async def test_deploy_success(self):
        from app.services.deployment.providers.heroku import HerokuProvider

        provider = HerokuProvider(credentials={"api_key": "test-key"})
        files = [DeploymentFile(path="index.html", content=b"<html>hello</html>")]
        config = DeploymentConfig(
            project_id="test-123", project_name="Test Project", framework="vite"
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock()
            mock_instance.get = AsyncMock()
            mock_instance.put = AsyncMock()
            mock_instance.patch = AsyncMock()

            mock_instance.post.side_effect = [
                _mock_response(json_data={"id": "app-id-1"}),
                _mock_response(
                    json_data={
                        "source_blob": {
                            "put_url": "https://s3.example.com/upload",
                            "get_url": "https://s3.example.com/source.tar.gz",
                        }
                    }
                ),
                _mock_response(json_data={"id": "build-1"}),
            ]
            mock_instance.put.return_value = _mock_response()
            mock_instance.get.return_value = _mock_response(
                json_data={"status": "succeeded", "output_stream_url": "https://log.url"}
            )

            result = await provider.deploy(files, config)
            assert result.success is True
            assert "herokuapp.com" in result.deployment_url


class TestSurgeDeploy:
    @pytest.mark.asyncio
    async def test_deploy_success(self):
        from app.services.deployment.providers.surge import SurgeProvider

        provider = SurgeProvider(credentials={"email": "a@b.com", "token": "tok"})
        files = [DeploymentFile(path="index.html", content=b"<html>hello</html>")]
        config = DeploymentConfig(
            project_id="test-123", project_name="Test Project", framework="vite"
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = mock_client.return_value.__aenter__.return_value
            mock_instance.put = AsyncMock(return_value=_mock_response(status_code=200))
            result = await provider.deploy(files, config)
            assert result.success is True
            assert "surge.sh" in result.deployment_url


# ============================================================================
# BaseContainerDeploymentProvider.deploy() raises NotImplementedError
# ============================================================================


class TestBaseContainerDeploymentProviderDeploy:
    @pytest.mark.asyncio
    async def test_deploy_raises_not_implemented(self):
        """The base container provider deploy() should raise NotImplementedError."""

        class StubContainerProvider(BaseContainerDeploymentProvider):
            def validate_credentials(self):
                pass

            async def push_image(self, image_ref):
                return image_ref

            async def deploy_image(self, config):
                return DeploymentResult(success=True)

            async def test_credentials(self):
                return {"valid": True}

            async def get_deployment_status(self, deployment_id):
                return {}

            async def delete_deployment(self, deployment_id):
                return True

            async def get_deployment_logs(self, deployment_id):
                return []

        provider = StubContainerProvider({})
        files = [DeploymentFile(path="a.txt", content=b"hello")]
        config = DeploymentConfig(project_id="test-123", project_name="Test", framework="vite")
        with pytest.raises(NotImplementedError, match="Container providers use push_image"):
            await provider.deploy(files, config)
