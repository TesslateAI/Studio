"""
Deployment manager for multi-provider deployments.

This module provides a unified interface for deploying to different providers
(Cloudflare Workers, Vercel, Netlify, etc.) using a factory pattern.
"""

from typing import Dict, List, Optional, Type
from .base import BaseDeploymentProvider, DeploymentConfig, DeploymentFile, DeploymentResult
from .providers.cloudflare import CloudflareWorkersProvider
from .providers.vercel import VercelProvider
from .providers.netlify import NetlifyProvider


class DeploymentManager:
    """
    Manages deployment operations across multiple providers.

    This class acts as a factory for creating provider instances and provides
    a unified interface for deployment operations.
    """

    # Registry of available providers
    _providers: Dict[str, Type[BaseDeploymentProvider]] = {
        "cloudflare": CloudflareWorkersProvider,
        "vercel": VercelProvider,
        "netlify": NetlifyProvider,
    }

    @classmethod
    def get_provider(
        cls,
        provider_name: str,
        credentials: Dict[str, str]
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
            raise ValueError(
                f"Unknown provider: {provider_name}. "
                f"Available providers: {available}"
            )

        provider_class = cls._providers[provider_name_lower]
        return provider_class(credentials)

    @classmethod
    async def deploy_project(
        cls,
        project_path: str,
        provider_name: str,
        credentials: Dict[str, str],
        config: DeploymentConfig,
        build_output_dir: str = "dist"
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

        # Collect files from build output
        files = await provider.collect_files_from_container(
            project_path,
            build_output_dir
        )

        # Deploy using provider
        result = await provider.deploy(files, config)

        return result

    @classmethod
    def list_available_providers(cls) -> List[Dict[str, str]]:
        """
        List all available deployment providers.

        Returns:
            List of provider metadata dictionaries
        """
        providers = [
            {
                "name": "cloudflare",
                "display_name": "Cloudflare Workers",
                "description": "Deploy to Cloudflare Workers with static assets",
                "auth_type": "api_token",
                "required_credentials": ["account_id", "api_token"],
                "optional_credentials": ["dispatch_namespace"]
            },
            {
                "name": "vercel",
                "display_name": "Vercel",
                "description": "Deploy to Vercel with automatic builds",
                "auth_type": "oauth",
                "required_credentials": ["token"],
                "optional_credentials": ["team_id"]
            },
            {
                "name": "netlify",
                "display_name": "Netlify",
                "description": "Deploy to Netlify with optimized file uploads",
                "auth_type": "oauth",
                "required_credentials": ["token"],
                "optional_credentials": []
            }
        ]
        return providers

    @classmethod
    def register_provider(
        cls,
        name: str,
        provider_class: Type[BaseDeploymentProvider]
    ) -> None:
        """
        Register a new deployment provider.

        This allows for dynamic registration of custom providers.

        Args:
            name: Provider name (will be lowercased)
            provider_class: Provider class that inherits from BaseDeploymentProvider
        """
        if not issubclass(provider_class, BaseDeploymentProvider):
            raise ValueError(
                f"Provider class must inherit from BaseDeploymentProvider"
            )

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
