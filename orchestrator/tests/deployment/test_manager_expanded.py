"""
Expanded tests for DeploymentManager — validates that all 22 providers are
registered, provider lookup works, and classification methods return correct
results for every new provider.
"""

import json

import pytest

pytestmark = pytest.mark.unit

from app.services.deployment.container_base import BaseContainerDeploymentProvider
from app.services.deployment.manager import DeploymentManager
from app.services.deployment.providers.aws_container import AWSContainerProvider
from app.services.deployment.providers.azure_container import AzureContainerProvider
from app.services.deployment.providers.deno_deploy import DenoDeployProvider
from app.services.deployment.providers.do_container import DigitalOceanContainerProvider
from app.services.deployment.providers.dockerhub_export import DockerHubExportProvider
from app.services.deployment.providers.download_export import DownloadExportProvider
from app.services.deployment.providers.firebase import FirebaseHostingProvider
from app.services.deployment.providers.fly import FlyProvider
from app.services.deployment.providers.gcp_container import GCPContainerProvider
from app.services.deployment.providers.ghcr_export import GHCRExportProvider
from app.services.deployment.providers.github_pages import GitHubPagesProvider
from app.services.deployment.providers.heroku import HerokuProvider
from app.services.deployment.providers.koyeb import KoyebProvider
from app.services.deployment.providers.northflank import NorthflankProvider
from app.services.deployment.providers.railway import RailwayProvider
from app.services.deployment.providers.render import RenderProvider
from app.services.deployment.providers.surge import SurgeProvider
from app.services.deployment.providers.zeabur import ZeaburProvider

# All 23 provider keys expected in _providers (includes digitalocean alias)
ALL_PROVIDER_KEYS = [
    "cloudflare",
    "vercel",
    "netlify",
    "heroku",
    "koyeb",
    "zeabur",
    "surge",
    "deno-deploy",
    "firebase",
    "railway",
    "render",
    "northflank",
    "github-pages",
    "digitalocean",
    "aws-apprunner",
    "gcp-cloudrun",
    "azure-container-apps",
    "do-container",
    "fly",
    "dockerhub",
    "ghcr",
    "download",
]

CONTAINER_PROVIDERS = [
    "aws-apprunner",
    "gcp-cloudrun",
    "azure-container-apps",
    "do-container",
    "fly",
    "dockerhub",
    "ghcr",
]

EXPORT_PROVIDERS = ["dockerhub", "ghcr", "download"]

NON_CONTAINER_PROVIDERS = [
    "cloudflare",
    "vercel",
    "netlify",
    "heroku",
    "koyeb",
    "zeabur",
    "surge",
    "deno-deploy",
    "firebase",
    "railway",
    "render",
    "northflank",
    "github-pages",
]

NON_EXPORT_PROVIDERS = [
    "cloudflare",
    "vercel",
    "netlify",
    "heroku",
    "koyeb",
    "zeabur",
    "surge",
    "deno-deploy",
    "firebase",
    "railway",
    "render",
    "northflank",
    "github-pages",
    "aws-apprunner",
    "gcp-cloudrun",
    "azure-container-apps",
    "do-container",
    "fly",
]


class TestDeploymentManagerRegistration:
    """Tests for the _providers registry."""

    def test_has_at_least_22_entries(self):
        # 22 unique providers + digitalocean alias = 23
        assert len(DeploymentManager._providers) >= 22

    @pytest.mark.parametrize("key", ALL_PROVIDER_KEYS)
    def test_provider_key_present(self, key):
        assert key in DeploymentManager._providers


class TestIsProviderAvailable:
    """Tests for is_provider_available across all new providers."""

    @pytest.mark.parametrize("provider", ALL_PROVIDER_KEYS)
    def test_available(self, provider):
        assert DeploymentManager.is_provider_available(provider) is True

    def test_unknown_not_available(self):
        assert DeploymentManager.is_provider_available("nonexistent") is False

    def test_case_insensitive(self):
        assert DeploymentManager.is_provider_available("HEROKU") is True
        assert DeploymentManager.is_provider_available("Railway") is True
        assert DeploymentManager.is_provider_available("FLY") is True


class TestIsContainerProvider:
    """Tests for is_container_provider classification."""

    @pytest.mark.parametrize("provider", CONTAINER_PROVIDERS)
    def test_true(self, provider):
        assert DeploymentManager.is_container_provider(provider) is True

    @pytest.mark.parametrize("provider", NON_CONTAINER_PROVIDERS)
    def test_false(self, provider):
        assert DeploymentManager.is_container_provider(provider) is False

    def test_download_is_not_container(self):
        assert DeploymentManager.is_container_provider("download") is False

    def test_case_insensitive(self):
        assert DeploymentManager.is_container_provider("AWS-APPRUNNER") is True


class TestIsExportProvider:
    """Tests for is_export_provider classification."""

    @pytest.mark.parametrize("provider", EXPORT_PROVIDERS)
    def test_true(self, provider):
        assert DeploymentManager.is_export_provider(provider) is True

    @pytest.mark.parametrize("provider", NON_EXPORT_PROVIDERS)
    def test_false(self, provider):
        assert DeploymentManager.is_export_provider(provider) is False

    def test_case_insensitive(self):
        assert DeploymentManager.is_export_provider("DOCKERHUB") is True
        assert DeploymentManager.is_export_provider("Ghcr") is True


class TestListAvailableProviders:
    """Tests for list_available_providers including new providers."""

    def test_returns_22(self):
        providers = DeploymentManager.list_available_providers()
        assert len(providers) == 22

    def test_all_names_present(self):
        providers = DeploymentManager.list_available_providers()
        names = {p["name"] for p in providers}
        for key in ALL_PROVIDER_KEYS:
            assert key in names, f"Missing: {key}"

    def test_each_entry_has_required_fields(self):
        providers = DeploymentManager.list_available_providers()
        for p in providers:
            assert "name" in p
            assert "display_name" in p
            assert "required_fields" in p
            assert "deploy_type" in p

    def test_heroku_metadata(self):
        providers = DeploymentManager.list_available_providers()
        heroku = next(p for p in providers if p["name"] == "heroku")
        assert heroku["display_name"] == "Heroku"
        assert "api_key" in heroku["required_fields"]
        assert heroku["deploy_type"] == "source"

    def test_surge_metadata(self):
        providers = DeploymentManager.list_available_providers()
        surge = next(p for p in providers if p["name"] == "surge")
        assert "email" in surge["required_fields"]
        assert "token" in surge["required_fields"]

    def test_aws_apprunner_metadata(self):
        providers = DeploymentManager.list_available_providers()
        aws = next(p for p in providers if p["name"] == "aws-apprunner")
        assert aws["deploy_type"] == "container"
        assert "aws_access_key_id" in aws["required_fields"]

    def test_download_metadata(self):
        providers = DeploymentManager.list_available_providers()
        download = next(p for p in providers if p["name"] == "download")
        assert download["deploy_type"] == "export"
        assert download["required_fields"] == []
        assert download["auth_type"] == "none"


class TestGetProviderReturnsCorrectClass:
    """Tests that get_provider returns the correct class for each provider."""

    def test_heroku(self):
        provider = DeploymentManager.get_provider("heroku", {"api_key": "k"})
        assert isinstance(provider, HerokuProvider)

    def test_koyeb(self):
        provider = DeploymentManager.get_provider("koyeb", {"api_token": "t"})
        assert isinstance(provider, KoyebProvider)

    def test_zeabur(self):
        provider = DeploymentManager.get_provider("zeabur", {"api_key": "k"})
        assert isinstance(provider, ZeaburProvider)

    def test_surge(self):
        provider = DeploymentManager.get_provider("surge", {"email": "a@b", "token": "t"})
        assert isinstance(provider, SurgeProvider)

    def test_deno_deploy(self):
        provider = DeploymentManager.get_provider("deno-deploy", {"token": "t", "org_id": "o"})
        assert isinstance(provider, DenoDeployProvider)

    def test_firebase(self):
        sa = json.dumps(
            {
                "client_email": "x@y.com",
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        provider = DeploymentManager.get_provider(
            "firebase", {"service_account_json": sa, "site_id": "s"}
        )
        assert isinstance(provider, FirebaseHostingProvider)

    def test_railway(self):
        provider = DeploymentManager.get_provider("railway", {"token": "t"})
        assert isinstance(provider, RailwayProvider)

    def test_render(self):
        provider = DeploymentManager.get_provider("render", {"api_key": "k"})
        assert isinstance(provider, RenderProvider)

    def test_northflank(self):
        provider = DeploymentManager.get_provider("northflank", {"api_token": "t"})
        assert isinstance(provider, NorthflankProvider)

    def test_github_pages(self):
        provider = DeploymentManager.get_provider("github-pages", {"token": "t"})
        assert isinstance(provider, GitHubPagesProvider)

    def test_aws_apprunner(self):
        provider = DeploymentManager.get_provider(
            "aws-apprunner",
            {
                "aws_access_key_id": "AK",
                "aws_secret_access_key": "SK",
                "aws_region": "us-east-1",
            },
        )
        assert isinstance(provider, AWSContainerProvider)

    def test_gcp_cloudrun(self):
        sa = json.dumps(
            {
                "client_email": "x@y.com",
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
                "project_id": "proj",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        provider = DeploymentManager.get_provider(
            "gcp-cloudrun", {"service_account_json": sa, "gcp_region": "us-central1"}
        )
        assert isinstance(provider, GCPContainerProvider)

    def test_azure_container_apps(self):
        provider = DeploymentManager.get_provider(
            "azure-container-apps",
            {
                "tenant_id": "t",
                "client_id": "c",
                "client_secret": "s",
                "subscription_id": "sub",
                "resource_group": "rg",
                "registry_name": "reg",
                "azure_region": "eastus",
                "container_app_environment_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/managedEnvironments/env",
            },
        )
        assert isinstance(provider, AzureContainerProvider)

    def test_do_container(self):
        provider = DeploymentManager.get_provider(
            "do-container", {"api_token": "t", "registry_name": "r"}
        )
        assert isinstance(provider, DigitalOceanContainerProvider)

    def test_fly(self):
        provider = DeploymentManager.get_provider("fly", {"api_token": "t"})
        assert isinstance(provider, FlyProvider)

    def test_dockerhub(self):
        provider = DeploymentManager.get_provider("dockerhub", {"username": "u", "token": "t"})
        assert isinstance(provider, DockerHubExportProvider)

    def test_ghcr(self):
        provider = DeploymentManager.get_provider("ghcr", {"username": "u", "token": "t"})
        assert isinstance(provider, GHCRExportProvider)

    def test_download(self):
        provider = DeploymentManager.get_provider("download", {})
        assert isinstance(provider, DownloadExportProvider)

    def test_case_insensitive_lookup(self):
        provider = DeploymentManager.get_provider("HEROKU", {"api_key": "k"})
        assert isinstance(provider, HerokuProvider)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            DeploymentManager.get_provider("nonexistent", {})

    def test_unknown_error_includes_provider_names(self):
        try:
            DeploymentManager.get_provider("invalid", {})
        except ValueError as e:
            error_msg = str(e).lower()
            assert "heroku" in error_msg
            assert "railway" in error_msg
            assert "fly" in error_msg
            assert "download" in error_msg


class TestContainerProviderSubclass:
    """Verify container-push providers extend BaseContainerDeploymentProvider."""

    @pytest.mark.parametrize(
        "key,creds",
        [
            (
                "aws-apprunner",
                {"aws_access_key_id": "A", "aws_secret_access_key": "S", "aws_region": "us-east-1"},
            ),
            ("do-container", {"api_token": "t", "registry_name": "r"}),
            ("fly", {"api_token": "t"}),
            ("dockerhub", {"username": "u", "token": "t"}),
            ("ghcr", {"username": "u", "token": "t"}),
        ],
    )
    def test_is_container_base_subclass(self, key, creds):
        provider = DeploymentManager.get_provider(key, creds)
        assert isinstance(provider, BaseContainerDeploymentProvider)
