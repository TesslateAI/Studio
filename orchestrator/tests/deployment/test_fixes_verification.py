"""
Tests that verify all 13 fixes from the deployment provider review.

Each test targets a specific fix to ensure the bug was corrected and
won't regress.
"""

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.mocked

import pytest

# =============================================================================
# Fix #1: Fly.io double /v1 in API URLs
# =============================================================================


class TestFix1FlyApiUrls:
    """Fly.io MACHINES_API must not include /v1 — paths add it themselves."""

    def test_machines_api_base_has_no_v1(self):
        from app.services.deployment.providers.fly import MACHINES_API

        assert MACHINES_API == "https://api.machines.dev"
        assert not MACHINES_API.endswith("/v1")

    def test_test_credentials_url_correct(self):
        from app.services.deployment.providers.fly import FlyProvider

        src = inspect.getsource(FlyProvider.test_credentials)
        # Should construct MACHINES_API/v1/apps (one /v1 total)
        assert "MACHINES_API}/v1/apps" in src

    def test_deploy_image_url_correct(self):
        from app.services.deployment.providers.fly import FlyProvider

        src = inspect.getsource(FlyProvider.deploy_image)
        assert "MACHINES_API}/v1/apps" in src
        # Must NOT have /v1/v1
        assert "/v1/v1/" not in src


# =============================================================================
# Fix #2: GCP Cloud Run polling exits immediately
# =============================================================================


class TestFix2GcpTerminalStates:
    """GCP terminal_states must only contain 'true', not 'false'."""

    def test_terminal_states_exclude_false(self):
        from app.services.deployment.providers.gcp_container import GCPContainerProvider

        src = inspect.getsource(GCPContainerProvider.deploy_image)
        # The terminal_states should be {"true"} only
        assert '"false"' not in src or 'terminal_states={"true"}' in src

    def test_poll_operation_normalizes_done_field(self):
        from app.services.deployment.providers.gcp_container import GCPContainerProvider

        src = inspect.getsource(GCPContainerProvider._poll_operation)
        # Should convert done to lowercase string
        assert "str(result.get" in src or "lower()" in src


# =============================================================================
# Fix #3: AWS ECR endpoint
# =============================================================================


class TestFix3AwsEcrEndpoint:
    """AWS ECR must use ecr.{region}.amazonaws.com, not api.ecr."""

    def test_ecr_endpoint_correct(self):
        from app.services.deployment.providers.aws_container import AWSContainerProvider

        src = inspect.getsource(AWSContainerProvider.push_image)
        assert "api.ecr" not in src
        assert "ecr.{self._region}.amazonaws.com" in src


# =============================================================================
# Fix #4: GitHub Pages /git/ref → /git/refs
# =============================================================================


class TestFix4GitHubPagesRefs:
    """GitHub Pages _get_branch_head must use /git/refs/ (plural)."""

    def test_branch_head_uses_plural_refs(self):
        from app.services.deployment.providers.github_pages import GitHubPagesProvider

        src = inspect.getsource(GitHubPagesProvider._get_branch_head)
        assert "/git/refs/heads/" in src
        assert "/git/ref/heads/" not in src

    def test_update_ref_uses_plural_refs(self):
        from app.services.deployment.providers.github_pages import GitHubPagesProvider

        src = inspect.getsource(GitHubPagesProvider._update_ref)
        assert "/git/refs/heads/" in src

    def test_create_ref_uses_plural_refs(self):
        from app.services.deployment.providers.github_pages import GitHubPagesProvider

        src = inspect.getsource(GitHubPagesProvider._create_ref)
        assert "/git/refs" in src


# =============================================================================
# Fix #5: Deno Deploy 409 conflict returns name instead of UUID
# =============================================================================


class TestFix5DenoProjectIdOnConflict:
    """On 409 conflict, Deno Deploy should attempt to fetch the real project ID."""

    def test_ensure_project_fetches_id_on_conflict(self):
        from app.services.deployment.providers.deno_deploy import DenoDeployProvider

        src = inspect.getsource(DenoDeployProvider._ensure_project)
        # Should have logic to fetch existing project on 409
        assert "409" in src
        # Should try to get the real project ID, not just return name
        assert "organizations" in src or "projects" in src


# =============================================================================
# Fix #6: Azure container_app_environment_id validation
# =============================================================================


class TestFix6AzureEnvironmentIdValidation:
    """Azure must validate container_app_environment_id is present."""

    def test_missing_environment_id_raises(self):
        from app.services.deployment.providers.azure_container import AzureContainerProvider

        with pytest.raises(ValueError, match="container_app_environment_id"):
            AzureContainerProvider(
                credentials={
                    "tenant_id": "t",
                    "client_id": "c",
                    "client_secret": "s",
                    "subscription_id": "sub",
                    "resource_group": "rg",
                    "registry_name": "reg",
                }
            )

    def test_valid_creds_with_environment_id(self):
        from app.services.deployment.providers.azure_container import AzureContainerProvider

        provider = AzureContainerProvider(
            credentials={
                "tenant_id": "t",
                "client_id": "c",
                "client_secret": "s",
                "subscription_id": "sub",
                "resource_group": "rg",
                "registry_name": "reg",
                "container_app_environment_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/managedEnvironments/env",
            }
        )
        assert provider.credentials["container_app_environment_id"].startswith("/subscriptions/")


# =============================================================================
# Fix #7: Manager routes container providers through push_image + deploy_image
# =============================================================================


class TestFix7ManagerContainerRouting:
    """deploy_project must route container providers through push_image + deploy_image."""

    def test_deploy_project_has_container_routing(self):
        from app.services.deployment.manager import DeploymentManager

        src = inspect.getsource(DeploymentManager.deploy_project)
        assert "is_container_provider" in src
        assert "push_image" in src
        assert "deploy_image" in src

    def test_is_container_provider_correct(self):
        from app.services.deployment.manager import DeploymentManager

        assert DeploymentManager.is_container_provider("aws-apprunner") is True
        assert DeploymentManager.is_container_provider("fly") is True
        assert DeploymentManager.is_container_provider("heroku") is False
        assert DeploymentManager.is_container_provider("netlify") is False


# =============================================================================
# Fix #8: CredentialMetadata missing client_id for Azure
# =============================================================================


class TestFix8CredentialMetadataClientId:
    """CredentialMetadata must have a client_id field for Azure SP."""

    def test_client_id_field_exists(self):
        from app.routers.deployment_credentials import CredentialMetadata

        fields = CredentialMetadata.model_fields
        assert "client_id" in fields

    def test_client_id_is_optional(self):
        from app.routers.deployment_credentials import CredentialMetadata

        meta = CredentialMetadata()
        assert meta.client_id is None

    def test_client_id_can_be_set(self):
        from app.routers.deployment_credentials import CredentialMetadata

        meta = CredentialMetadata(client_id="test-app-id")
        assert meta.client_id == "test-app-id"


# =============================================================================
# Fix #9: Test count and ALL_PROVIDER_KEYS
# =============================================================================


class TestFix9ProviderCounts:
    """Provider registry and list must be consistent at 22 entries."""

    def test_providers_count_is_22(self):
        from app.services.deployment.manager import DeploymentManager

        assert len(DeploymentManager._providers) == 22

    def test_list_available_providers_count_is_22(self):
        from app.services.deployment.manager import DeploymentManager

        assert len(DeploymentManager.list_available_providers()) == 22

    def test_digitalocean_alias_present(self):
        from app.services.deployment.manager import DeploymentManager

        assert "digitalocean" in DeploymentManager._providers
        assert DeploymentManager.is_provider_available("digitalocean")

    def test_all_provider_keys_in_list(self):
        from app.services.deployment.manager import DeploymentManager

        list_names = {p["name"] for p in DeploymentManager.list_available_providers()}
        for key in DeploymentManager._providers:
            assert key in list_names, f"Key '{key}' in _providers but not in list_available_providers"


# =============================================================================
# Fix #10: Fly.io missing timeouts on AsyncClient
# =============================================================================


class TestFix10FlyTimeouts:
    """All Fly.io AsyncClient instances must have a timeout parameter."""

    def test_get_deployment_status_has_timeout(self):
        from app.services.deployment.providers.fly import FlyProvider

        src = inspect.getsource(FlyProvider.get_deployment_status)
        assert "timeout=" in src

    def test_delete_deployment_has_timeout(self):
        from app.services.deployment.providers.fly import FlyProvider

        src = inspect.getsource(FlyProvider.delete_deployment)
        assert "timeout=" in src

    def test_get_deployment_logs_has_timeout(self):
        from app.services.deployment.providers.fly import FlyProvider

        src = inspect.getsource(FlyProvider.get_deployment_logs)
        assert "timeout=" in src

    def test_test_credentials_has_timeout(self):
        from app.services.deployment.providers.fly import FlyProvider

        src = inspect.getsource(FlyProvider.test_credentials)
        assert "timeout=" in src


# =============================================================================
# Fix #11: Koyeb scopes field shape
# =============================================================================


class TestFix11KoyebScopeField:
    """Koyeb env vars must use singular 'scope' string, not 'scopes' array."""

    def test_uses_singular_scope(self):
        from app.services.deployment.providers.koyeb import KoyebProvider

        src = inspect.getsource(KoyebProvider._create_service)
        assert '"scope"' in src

    def test_env_vars_use_singular_scope_not_plural(self):
        from app.services.deployment.providers.koyeb import KoyebProvider

        src = inspect.getsource(KoyebProvider._create_service)
        # The env_list comprehension must use "scope" (singular string),
        # not "scopes" (array). The scalings section may still use "scopes" for regions.
        lines = src.split("\n")
        for line in lines:
            if "env_list" in line or ("key" in line and "value" in line and "scope" in line):
                assert '"scopes"' not in line, f"env_list line still uses plural scopes: {line}"


# =============================================================================
# Fix #12: Surge Content-Type
# =============================================================================


class TestFix12SurgeContentType:
    """Surge deploy must use application/x-tar, not application/tar."""

    def test_content_type_is_x_tar(self):
        from app.services.deployment.providers.surge import SurgeProvider

        src = inspect.getsource(SurgeProvider.deploy)
        assert "application/x-tar" in src
        assert '"application/tar"' not in src


# =============================================================================
# Fix #13: KANIKO_IMAGE config wiring
# =============================================================================


class TestFix13KanikoImageConfig:
    """KANIKO_IMAGE must be present in config settings."""

    def test_kaniko_image_in_settings(self):
        from app.config import Settings

        settings = Settings()
        assert hasattr(settings, "kaniko_image")
        assert settings.kaniko_image == "gcr.io/kaniko-project/executor:latest"

    def test_kaniko_image_can_be_overridden(self):
        import os

        os.environ["KANIKO_IMAGE"] = "custom-registry/kaniko:v1.0"
        try:
            from app.config import Settings

            settings = Settings()
            assert settings.kaniko_image == "custom-registry/kaniko:v1.0"
        finally:
            del os.environ["KANIKO_IMAGE"]


# =============================================================================
# Cross-cutting: Container push base class contract
# =============================================================================


class TestContainerPushBaseContract:
    """Verify container-push providers inherit correct base and implement methods."""

    @pytest.mark.parametrize(
        "key,creds",
        [
            ("aws-apprunner", {"aws_access_key_id": "A", "aws_secret_access_key": "S"}),
            ("do-container", {"api_token": "t", "registry_name": "r"}),
            ("fly", {"api_token": "t"}),
        ],
    )
    def test_container_providers_have_push_and_deploy_image(self, key, creds):
        from app.services.deployment.container_base import BaseContainerDeploymentProvider
        from app.services.deployment.manager import DeploymentManager

        provider = DeploymentManager.get_provider(key, creds)
        assert isinstance(provider, BaseContainerDeploymentProvider)
        assert hasattr(provider, "push_image")
        assert hasattr(provider, "deploy_image")

    def test_base_deploy_raises_not_implemented(self):
        from app.services.deployment.container_base import BaseContainerDeploymentProvider

        src = inspect.getsource(BaseContainerDeploymentProvider.deploy)
        assert "NotImplementedError" in src


# =============================================================================
# Cross-cutting: Credential builder covers new providers
# =============================================================================


class TestCredentialBuilderCoverage:
    """_build_provider_credentials must handle all new providers."""

    def test_azure_includes_client_id(self):
        from app.routers.deployment_credentials import _build_provider_credentials

        creds = _build_provider_credentials(
            "azure-container-apps",
            "my-client-secret",
            {"tenant_id": "t", "client_id": "c", "subscription_id": "sub", "resource_group": "rg", "registry_name": "reg", "azure_region": "eastus"},
        )
        assert creds["client_secret"] == "my-client-secret"
        assert creds["client_id"] == "c"
        assert creds["tenant_id"] == "t"

    def test_fly_maps_token_to_api_token(self):
        from app.routers.deployment_credentials import _build_provider_credentials

        creds = _build_provider_credentials("fly", "my-token", {"org_slug": "personal"})
        assert creds["api_token"] == "my-token"
        assert creds["org_slug"] == "personal"

    def test_deno_maps_org_id(self):
        from app.routers.deployment_credentials import _build_provider_credentials

        creds = _build_provider_credentials("deno-deploy", "my-token", {"org_id": "org123"})
        assert creds["token"] == "my-token"
        assert creds["org_id"] == "org123"

    def test_firebase_maps_sa_json(self):
        from app.routers.deployment_credentials import _build_provider_credentials

        sa_json = json.dumps({"client_email": "x@y.com", "private_key": "pk", "project_id": "p", "token_uri": "t"})
        creds = _build_provider_credentials("firebase", sa_json, {"site_id": "my-site"})
        assert creds["service_account_json"] == sa_json
        assert creds["site_id"] == "my-site"

    def test_heroku_maps_api_key(self):
        from app.routers.deployment_credentials import _build_provider_credentials

        creds = _build_provider_credentials("heroku", "my-api-key", {})
        assert creds["api_key"] == "my-api-key"

    def test_dockerhub_maps_username(self):
        from app.routers.deployment_credentials import _build_provider_credentials

        creds = _build_provider_credentials("dockerhub", "my-pat", {"account_name": "myuser"})
        assert creds["username"] == "myuser"
        assert creds["token"] == "my-pat"

    def test_download_needs_no_creds(self):
        from app.routers.deployment_credentials import _build_provider_credentials

        creds = _build_provider_credentials("download", "", {})
        assert "token" in creds  # base token key is always set
