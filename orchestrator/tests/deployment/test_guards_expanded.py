"""Tests for expanded PROVIDER_CAPABILITIES in guards.py."""

import pytest

from app.services.deployment.guards import (
    PROVIDER_CAPABILITIES,
    get_compatible_providers,
    get_provider_info,
    list_all_providers,
    validate_deployment_connection,
)

# All expected providers (22 total)
ALL_PROVIDERS = [
    "vercel", "netlify", "cloudflare", "digitalocean", "railway", "fly",
    "heroku", "render", "koyeb", "zeabur", "northflank",
    "github-pages", "surge", "deno-deploy", "firebase",
    "aws-apprunner", "gcp-cloudrun", "azure-container-apps", "do-container",
    "dockerhub", "ghcr", "download",
]


class TestProviderCapabilitiesComplete:
    def test_all_providers_registered(self):
        for provider in ALL_PROVIDERS:
            assert provider in PROVIDER_CAPABILITIES, f"Missing provider: {provider}"

    def test_provider_count(self):
        assert len(PROVIDER_CAPABILITIES) >= 22

    def test_all_providers_have_required_fields(self):
        required_keys = {"display_name", "types", "frameworks", "supports_serverless",
                         "supports_static", "supports_fullstack", "deployment_mode",
                         "icon", "color"}
        for name, cap in PROVIDER_CAPABILITIES.items():
            for key in required_keys:
                assert key in cap, f"Provider {name} missing field: {key}"


class TestNewProviderValidation:
    @pytest.mark.parametrize("provider", ["heroku", "railway", "render", "koyeb", "zeabur", "northflank"])
    def test_fullstack_providers_accept_backend(self, provider):
        result = validate_deployment_connection(
            provider=provider, container_type="base", framework="python"
        )
        assert result["allowed"] is True

    @pytest.mark.parametrize("provider", ["github-pages", "surge", "firebase"])
    def test_static_providers_accept_frontend(self, provider):
        result = validate_deployment_connection(
            provider=provider, container_type="base", framework="react"
        )
        assert result["allowed"] is True

    def test_static_provider_rejects_database(self):
        result = validate_deployment_connection(
            provider="github-pages", container_type="service", service_slug="postgres"
        )
        assert result["allowed"] is False

    @pytest.mark.parametrize("provider", ["aws-apprunner", "gcp-cloudrun", "azure-container-apps"])
    def test_container_providers_accept_all(self, provider):
        result = validate_deployment_connection(
            provider=provider, container_type="base", framework="python"
        )
        assert result["allowed"] is True


class TestGetCompatibleProviders:
    def test_frontend_returns_many_providers(self):
        providers = get_compatible_providers(container_type="base", framework="react")
        assert len(providers) >= 10
        assert "vercel" in providers
        assert "netlify" in providers
        assert "github-pages" in providers

    def test_backend_returns_fullstack_providers(self):
        providers = get_compatible_providers(container_type="base", framework="python")
        assert "heroku" in providers
        assert "railway" in providers
        assert "fly" in providers


class TestListAllProviders:
    def test_returns_all(self):
        all_p = list_all_providers()
        assert len(all_p) >= 22

    def test_get_provider_info_works(self):
        info = get_provider_info("heroku")
        assert info is not None
        assert info["display_name"] == "Heroku"

    def test_unknown_provider_returns_none(self):
        info = get_provider_info("nonexistent-provider")
        assert info is None


class TestNewProviderValidationExtended:
    """Extended validation tests for individual new providers."""

    def test_heroku_allows_frontend(self):
        result = validate_deployment_connection("heroku", "base", framework="react")
        assert result["allowed"] is True

    def test_heroku_blocks_database(self):
        result = validate_deployment_connection("heroku", "service", service_slug="postgres")
        assert result["allowed"] is False

    def test_surge_blocks_backend(self):
        result = validate_deployment_connection("surge", "base", framework="python")
        assert result["allowed"] is False

    def test_firebase_blocks_unknown_framework(self):
        result = validate_deployment_connection("firebase", "base", framework="python")
        assert result["allowed"] is False

    def test_github_pages_blocks_backend(self):
        result = validate_deployment_connection("github-pages", "base", framework="python")
        assert result["allowed"] is False

    def test_deno_deploy_allows_frontend(self):
        result = validate_deployment_connection("deno-deploy", "base", framework="react")
        assert result["allowed"] is True

    def test_fly_allows_any(self):
        result = validate_deployment_connection("fly", "base", framework="python")
        assert result["allowed"] is True

    def test_do_container_allows_any(self):
        result = validate_deployment_connection("do-container", "base", framework="rust")
        assert result["allowed"] is True

    def test_dockerhub_allows_any(self):
        result = validate_deployment_connection("dockerhub", "base", framework="python")
        assert result["allowed"] is True

    def test_ghcr_allows_any(self):
        result = validate_deployment_connection("ghcr", "base", framework="go")
        assert result["allowed"] is True

    def test_download_allows_any(self):
        result = validate_deployment_connection("download", "base", framework="react")
        assert result["allowed"] is True

    def test_unknown_provider(self):
        result = validate_deployment_connection("nonexistent", "base", framework="react")
        assert result["allowed"] is False
        assert "Unknown deployment provider" in result["reason"]

    @pytest.mark.parametrize(
        "provider",
        ["railway", "fly", "heroku", "render", "koyeb", "zeabur",
         "northflank", "aws-apprunner", "gcp-cloudrun",
         "azure-container-apps", "do-container",
         "dockerhub", "ghcr", "download"],
    )
    def test_blocks_database_service(self, provider):
        result = validate_deployment_connection(provider, "service", service_slug="postgres")
        assert result["allowed"] is False


class TestGetCompatibleProvidersExtended:
    """Extended compatible-providers tests."""

    def test_backend_python_excludes_static_only(self):
        providers = get_compatible_providers(container_type="base", framework="python")
        assert "surge" not in providers
        assert "firebase" not in providers
        assert "github-pages" not in providers

    def test_backend_python_includes_export(self):
        providers = get_compatible_providers(container_type="base", framework="python")
        assert "dockerhub" in providers
        assert "ghcr" in providers
        assert "download" in providers

    def test_database_returns_empty(self):
        providers = get_compatible_providers("service", service_slug="postgres")
        assert providers == []

    def test_container_push_providers_available(self):
        providers = get_compatible_providers(container_type="base", framework="node")
        assert "aws-apprunner" in providers
        assert "gcp-cloudrun" in providers
        assert "azure-container-apps" in providers
        assert "do-container" in providers
