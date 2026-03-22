"""
Deployment manager for multi-provider deployments.

This module provides a unified interface for deploying to different providers
(Cloudflare Workers, Vercel, Netlify, etc.) using a factory pattern.
"""

from .base import BaseDeploymentProvider, DeploymentConfig, DeploymentResult
from .container_base import BaseContainerDeploymentProvider
from .providers.cloudflare import CloudflareWorkersProvider
from .providers.netlify import NetlifyProvider
from .providers.vercel import VercelProvider
from .providers.heroku import HerokuProvider
from .providers.koyeb import KoyebProvider
from .providers.zeabur import ZeaburProvider
from .providers.surge import SurgeProvider
from .providers.deno_deploy import DenoDeployProvider
from .providers.firebase import FirebaseHostingProvider
from .providers.railway import RailwayProvider
from .providers.render import RenderProvider
from .providers.northflank import NorthflankProvider
from .providers.github_pages import GitHubPagesProvider
from .providers.aws_container import AWSContainerProvider
from .providers.gcp_container import GCPContainerProvider
from .providers.azure_container import AzureContainerProvider
from .providers.do_container import DigitalOceanContainerProvider
from .providers.fly import FlyProvider
from .providers.dockerhub_export import DockerHubExportProvider
from .providers.ghcr_export import GHCRExportProvider
from .providers.download_export import DownloadExportProvider


class DeploymentManager:
    """
    Manages deployment operations across multiple providers.

    This class acts as a factory for creating provider instances and provides
    a unified interface for deployment operations.
    """

    # Registry of available providers
    _providers: dict[str, type[BaseDeploymentProvider]] = {
        # Source-push providers (upload files/source directly)
        "cloudflare": CloudflareWorkersProvider,
        "vercel": VercelProvider,
        "netlify": NetlifyProvider,
        "heroku": HerokuProvider,
        "koyeb": KoyebProvider,
        "zeabur": ZeaburProvider,
        "surge": SurgeProvider,
        "deno-deploy": DenoDeployProvider,
        "firebase": FirebaseHostingProvider,
        # Git-repo-required providers
        "railway": RailwayProvider,
        "render": RenderProvider,
        "northflank": NorthflankProvider,
        "github-pages": GitHubPagesProvider,
        # DigitalOcean source mode (alias — same provider handles both modes)
        "digitalocean": DigitalOceanContainerProvider,
        # Container-push providers
        "aws-apprunner": AWSContainerProvider,
        "gcp-cloudrun": GCPContainerProvider,
        "azure-container-apps": AzureContainerProvider,
        "do-container": DigitalOceanContainerProvider,
        "fly": FlyProvider,
        # Export providers
        "dockerhub": DockerHubExportProvider,
        "ghcr": GHCRExportProvider,
        "download": DownloadExportProvider,
    }

    # Container-push providers registry (subset of _providers)
    _container_providers: set[str] = {
        "aws-apprunner",
        "gcp-cloudrun",
        "azure-container-apps",
        "do-container",
        "fly",
        "dockerhub",
        "ghcr",
    }

    # Export-only providers (push image but no compute deployment)
    _export_providers: set[str] = {
        "dockerhub",
        "ghcr",
        "download",
    }

    @classmethod
    def get_provider(
        cls, provider_name: str, credentials: dict[str, str]
    ) -> BaseDeploymentProvider:
        """
        Get a provider instance by name.

        Args:
            provider_name: Name of the provider (cloudflare, vercel, netlify)
            credentials: Provider-specific credentials

        Returns:
            Initialized provider instance

        Raises:
            ValueError: If provider is not supported
        """
        provider_name_lower = provider_name.lower()

        if provider_name_lower not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(f"Unknown provider: {provider_name}. Available providers: {available}")

        provider_class = cls._providers[provider_name_lower]
        return provider_class(credentials)

    @classmethod
    async def deploy_project(
        cls,
        project_path: str,
        provider_name: str,
        credentials: dict[str, str],
        config: DeploymentConfig,
        build_output_dir: str = "dist",
    ) -> DeploymentResult:
        """
        Deploy a project to the specified provider.

        This method handles the complete deployment flow:
        1. Collect files from the build output directory
        2. Get the appropriate provider instance
        3. Deploy using the provider

        Args:
            project_path: Path to the project directory
            provider_name: Name of the deployment provider
            credentials: Provider-specific credentials
            config: Deployment configuration
            build_output_dir: Name of the build output directory

        Returns:
            DeploymentResult with deployment information

        Raises:
            ValueError: If provider is not supported
            FileNotFoundError: If build output directory doesn't exist
        """
        # Get provider instance
        provider = cls.get_provider(provider_name, credentials)

        # Container-push providers use push_image + deploy_image, not file-based deploy
        if cls.is_container_provider(provider_name) and isinstance(provider, BaseContainerDeploymentProvider):
            from .container_base import ContainerDeployConfig

            container_config = ContainerDeployConfig(
                image_ref=config.env_vars.get("_TESSLATE_IMAGE_REF", ""),
                port=int(config.env_vars.get("_TESSLATE_PORT", "8080")),
                cpu=config.env_vars.get("_TESSLATE_CPU", "0.25"),
                memory=config.env_vars.get("_TESSLATE_MEMORY", "512Mi"),
                env_vars={k: v for k, v in config.env_vars.items() if not k.startswith("_TESSLATE_")},
                region=config.env_vars.get("_TESSLATE_REGION", "us-east-1"),
            )
            pushed_uri = await provider.push_image(container_config.image_ref)
            container_config = ContainerDeployConfig(**{**container_config.model_dump(), "image_ref": pushed_uri})
            return await provider.deploy_image(container_config)

        # Collect files from build output
        files = await provider.collect_files_from_container(project_path, build_output_dir)

        # Deploy using provider
        result = await provider.deploy(files, config)

        return result

    @classmethod
    def is_container_provider(cls, provider_name: str) -> bool:
        """Check if a provider uses container-push deployment."""
        return provider_name.lower() in cls._container_providers

    @classmethod
    def is_export_provider(cls, provider_name: str) -> bool:
        """Check if a provider is export-only (no compute deployment)."""
        return provider_name.lower() in cls._export_providers

    @classmethod
    def list_available_providers(cls) -> list[dict]:
        """
        List all available deployment providers.

        Returns:
            List of provider metadata dictionaries
        """
        providers = [
            # --- Existing providers ---
            {
                "name": "cloudflare",
                "display_name": "Cloudflare Workers",
                "description": "Deploy to Cloudflare Workers with static assets",
                "auth_type": "api_token",
                "required_fields": ["account_id", "api_token"],
                "optional_fields": ["dispatch_namespace"],
                "deploy_type": "source",
            },
            {
                "name": "vercel",
                "display_name": "Vercel",
                "description": "Deploy to Vercel with automatic builds",
                "auth_type": "oauth",
                "required_fields": ["token"],
                "optional_fields": ["team_id"],
                "deploy_type": "source",
            },
            {
                "name": "netlify",
                "display_name": "Netlify",
                "description": "Deploy to Netlify with optimized file uploads",
                "auth_type": "oauth",
                "required_fields": ["token"],
                "optional_fields": [],
                "deploy_type": "source",
            },
            # --- Source-upload providers ---
            {
                "name": "heroku",
                "display_name": "Heroku",
                "description": "Deploy to Heroku via source tarball upload",
                "auth_type": "token",
                "required_fields": ["api_key"],
                "optional_fields": [],
                "deploy_type": "source",
                "field_labels": {"api_key": "Heroku API Key"},
                "field_help": {"api_key": "Dashboard → Account Settings → API Key → Reveal"},
            },
            {
                "name": "koyeb",
                "display_name": "Koyeb",
                "description": "Deploy to Koyeb serverless platform",
                "auth_type": "token",
                "required_fields": ["api_token"],
                "optional_fields": [],
                "deploy_type": "source",
                "field_labels": {"api_token": "Koyeb API Token"},
                "field_help": {"api_token": "Dashboard → Account Settings → API Access → Create Token"},
            },
            {
                "name": "zeabur",
                "display_name": "Zeabur",
                "description": "Deploy to Zeabur with ZIP upload",
                "auth_type": "token",
                "required_fields": ["api_key"],
                "optional_fields": [],
                "deploy_type": "source",
                "field_labels": {"api_key": "Zeabur API Key"},
                "field_help": {"api_key": "Dashboard → Settings → API Keys → Create"},
            },
            {
                "name": "surge",
                "display_name": "Surge.sh",
                "description": "Deploy static sites to Surge.sh",
                "auth_type": "token",
                "required_fields": ["email", "token"],
                "optional_fields": [],
                "deploy_type": "source",
                "field_labels": {"email": "Surge Email", "token": "Surge Token"},
                "field_help": {"token": "Run 'npx surge token' in terminal to get your token"},
            },
            {
                "name": "deno-deploy",
                "display_name": "Deno Deploy",
                "description": "Deploy to Deno Deploy serverless platform",
                "auth_type": "token",
                "required_fields": ["token", "org_id"],
                "optional_fields": [],
                "deploy_type": "source",
                "field_labels": {"token": "Deno Deploy Access Token", "org_id": "Organization ID"},
                "field_help": {"token": "Dashboard → Account Settings → Access Tokens", "org_id": "Dashboard URL: dash.deno.com/orgs/{org_id}"},
            },
            {
                "name": "firebase",
                "display_name": "Firebase Hosting",
                "description": "Deploy static sites to Firebase Hosting",
                "auth_type": "token",
                "required_fields": ["service_account_json", "site_id"],
                "optional_fields": [],
                "deploy_type": "source",
                "field_labels": {"service_account_json": "Service Account Key (JSON)", "site_id": "Firebase Site ID"},
                "field_help": {"service_account_json": "GCP Console → IAM → Service Accounts → Create Key (JSON)", "site_id": "Firebase Console → Hosting → your site ID"},
                "field_types": {"service_account_json": "textarea"},
            },
            # --- Git-repo-required providers ---
            {
                "name": "railway",
                "display_name": "Railway",
                "description": "Deploy to Railway from Git repository",
                "auth_type": "token",
                "required_fields": ["token"],
                "optional_fields": [],
                "deploy_type": "source",
                "requires_git_repo": True,
                "field_labels": {"token": "Railway API Token"},
                "field_help": {"token": "Dashboard → Account Settings → Tokens → Create Token"},
            },
            {
                "name": "render",
                "display_name": "Render",
                "description": "Deploy to Render from Git repository",
                "auth_type": "token",
                "required_fields": ["api_key"],
                "optional_fields": [],
                "deploy_type": "source",
                "requires_git_repo": True,
                "field_labels": {"api_key": "Render API Key"},
                "field_help": {"api_key": "Dashboard → Account Settings → API Keys → Create API Key"},
            },
            {
                "name": "northflank",
                "display_name": "Northflank",
                "description": "Deploy to Northflank from Git repository",
                "auth_type": "token",
                "required_fields": ["api_token"],
                "optional_fields": [],
                "deploy_type": "source",
                "requires_git_repo": True,
                "field_labels": {"api_token": "Northflank API Token"},
                "field_help": {"api_token": "Team Settings → API → Create Token"},
            },
            {
                "name": "github-pages",
                "display_name": "GitHub Pages",
                "description": "Deploy static sites to GitHub Pages",
                "auth_type": "git_provider",
                "required_fields": ["token"],
                "optional_fields": [],
                "deploy_type": "source",
                "field_labels": {"token": "GitHub Token"},
                "field_help": {"token": "Uses your connected GitHub account from Git Providers"},
            },
            # --- DigitalOcean (source mode — git repo required) ---
            {
                "name": "digitalocean",
                "display_name": "DigitalOcean App Platform",
                "description": "Deploy to DigitalOcean App Platform from Git repository",
                "auth_type": "token",
                "required_fields": ["api_token"],
                "optional_fields": ["registry_name"],
                "deploy_type": "source",
                "requires_git_repo": True,
                "field_labels": {"api_token": "DigitalOcean API Token"},
                "field_help": {"api_token": "Dashboard → API → Tokens → Generate New Token (read+write)"},
            },
            # --- Container-push providers ---
            {
                "name": "aws-apprunner",
                "display_name": "AWS App Runner",
                "description": "Deploy containers via ECR to AWS App Runner",
                "auth_type": "token",
                "required_fields": ["aws_access_key_id", "aws_secret_access_key", "aws_region"],
                "optional_fields": [],
                "deploy_type": "container",
                "field_labels": {"aws_access_key_id": "AWS Access Key ID", "aws_secret_access_key": "AWS Secret Access Key", "aws_region": "AWS Region"},
                "field_help": {"aws_access_key_id": "IAM → Users → Security credentials → Create access key", "aws_region": "e.g. us-east-1"},
            },
            {
                "name": "gcp-cloudrun",
                "display_name": "GCP Cloud Run",
                "description": "Deploy containers via Artifact Registry to Cloud Run",
                "auth_type": "token",
                "required_fields": ["service_account_json", "gcp_region"],
                "optional_fields": [],
                "deploy_type": "container",
                "field_labels": {"service_account_json": "Service Account Key (JSON)", "gcp_region": "GCP Region"},
                "field_help": {"service_account_json": "GCP Console → IAM → Service Accounts → Create Key (JSON)", "gcp_region": "e.g. us-central1"},
                "field_types": {"service_account_json": "textarea"},
            },
            {
                "name": "azure-container-apps",
                "display_name": "Azure Container Apps",
                "description": "Deploy containers via ACR to Azure Container Apps",
                "auth_type": "token",
                "required_fields": ["tenant_id", "client_id", "client_secret", "subscription_id", "resource_group", "registry_name", "azure_region"],
                "optional_fields": [],
                "deploy_type": "container",
                "field_labels": {
                    "tenant_id": "Azure Tenant ID", "client_id": "App (Client) ID",
                    "client_secret": "Client Secret", "subscription_id": "Subscription ID",
                    "resource_group": "Resource Group", "registry_name": "ACR Registry Name",
                    "azure_region": "Azure Region",
                },
            },
            {
                "name": "do-container",
                "display_name": "DigitalOcean App Platform (Container)",
                "description": "Deploy containers via DOCR to DigitalOcean App Platform",
                "auth_type": "token",
                "required_fields": ["api_token", "registry_name"],
                "optional_fields": [],
                "deploy_type": "container",
                "field_labels": {"api_token": "DigitalOcean API Token", "registry_name": "DOCR Registry Name"},
                "field_help": {"api_token": "Dashboard → API → Tokens → Generate New Token (read+write)"},
            },
            {
                "name": "fly",
                "display_name": "Fly.io",
                "description": "Deploy containers to Fly.io Machines",
                "auth_type": "token",
                "required_fields": ["api_token"],
                "optional_fields": ["org_slug"],
                "deploy_type": "container",
                "field_labels": {"api_token": "Fly.io API Token", "org_slug": "Organization Slug"},
                "field_help": {"api_token": "Run 'fly tokens create deploy' or Dashboard → Account → Access Tokens"},
            },
            # --- Export providers ---
            {
                "name": "dockerhub",
                "display_name": "Docker Hub",
                "description": "Push container images to Docker Hub",
                "auth_type": "token",
                "required_fields": ["username", "token"],
                "optional_fields": [],
                "deploy_type": "export",
                "field_labels": {"username": "Docker Hub Username", "token": "Personal Access Token"},
                "field_help": {"token": "Docker Hub → Account Settings → Personal access tokens → Generate (Read+Write scope)"},
            },
            {
                "name": "ghcr",
                "display_name": "GitHub Container Registry",
                "description": "Push container images to GHCR",
                "auth_type": "token",
                "required_fields": ["username", "token"],
                "optional_fields": [],
                "deploy_type": "export",
                "field_labels": {"username": "GitHub Username", "token": "Personal Access Token (Classic)"},
                "field_help": {"token": "GitHub → Settings → Developer settings → Tokens (classic) → Generate with 'write:packages' scope"},
            },
            {
                "name": "download",
                "display_name": "Download Export",
                "description": "Export project as a downloadable ZIP archive",
                "auth_type": "none",
                "required_fields": [],
                "optional_fields": [],
                "deploy_type": "export",
            },
        ]
        return providers

    @classmethod
    def register_provider(cls, name: str, provider_class: type[BaseDeploymentProvider]) -> None:
        """
        Register a new deployment provider.

        This allows for dynamic registration of custom providers.

        Args:
            name: Provider name (will be lowercased)
            provider_class: Provider class that inherits from BaseDeploymentProvider
        """
        if not issubclass(provider_class, BaseDeploymentProvider):
            raise ValueError("Provider class must inherit from BaseDeploymentProvider")

        cls._providers[name.lower()] = provider_class

    @classmethod
    def is_provider_available(cls, provider_name: str) -> bool:
        """
        Check if a provider is available.

        Args:
            provider_name: Name of the provider

        Returns:
            True if provider is available, False otherwise
        """
        return provider_name.lower() in cls._providers


# Singleton instance for convenience
deployment_manager = DeploymentManager()
