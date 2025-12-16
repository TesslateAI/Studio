"""
Git Provider Manager - Factory for creating provider instances.
"""
from typing import Dict, Type, Optional, List
import logging

from .base import BaseGitProvider, GitProviderType

logger = logging.getLogger(__name__)


class GitProviderManager:
    """
    Factory class for managing Git provider instances.

    Handles registration of provider classes and instantiation with credentials.
    """

    _providers: Dict[GitProviderType, Type[BaseGitProvider]] = {}

    @classmethod
    def register_provider(
        cls,
        provider_type: GitProviderType,
        provider_class: Type[BaseGitProvider]
    ) -> None:
        """
        Register a provider class for a given provider type.

        Args:
            provider_type: The provider type enum value
            provider_class: The provider implementation class
        """
        cls._providers[provider_type] = provider_class
        logger.debug(f"Registered git provider: {provider_type.value}")

    @classmethod
    def get_provider(
        cls,
        provider_type: GitProviderType,
        access_token: str
    ) -> BaseGitProvider:
        """
        Get an initialized provider instance.

        Args:
            provider_type: The provider type to instantiate
            access_token: OAuth access token for the provider

        Returns:
            Initialized provider instance

        Raises:
            ValueError: If provider type is not registered
        """
        if provider_type not in cls._providers:
            available = ", ".join(p.value for p in cls._providers.keys())
            raise ValueError(
                f"Unknown provider: {provider_type.value}. "
                f"Available providers: {available}"
            )

        provider_class = cls._providers[provider_type]
        return provider_class(access_token)

    @classmethod
    def get_provider_by_name(
        cls,
        provider_name: str,
        access_token: str
    ) -> BaseGitProvider:
        """
        Get an initialized provider instance by name string.

        Args:
            provider_name: The provider name (e.g., "github", "gitlab")
            access_token: OAuth access token for the provider

        Returns:
            Initialized provider instance

        Raises:
            ValueError: If provider name is invalid
        """
        try:
            provider_type = GitProviderType(provider_name.lower())
        except ValueError:
            available = ", ".join(p.value for p in GitProviderType)
            raise ValueError(
                f"Invalid provider name: {provider_name}. "
                f"Valid providers: {available}"
            )

        return cls.get_provider(provider_type, access_token)

    @classmethod
    def is_provider_available(cls, provider_type: GitProviderType) -> bool:
        """
        Check if a provider is registered and available.

        Args:
            provider_type: The provider type to check

        Returns:
            True if provider is registered
        """
        return provider_type in cls._providers

    @classmethod
    def list_available_providers(cls) -> List[Dict[str, str]]:
        """
        List all available providers with their metadata.

        Returns:
            List of provider info dictionaries
        """
        providers = []

        # GitHub
        if GitProviderType.GITHUB in cls._providers:
            providers.append({
                "name": "github",
                "display_name": "GitHub",
                "icon": "github-logo",
                "oauth_scopes": "repo user:email",
                "description": "Connect your GitHub account to import repositories"
            })

        # GitLab
        if GitProviderType.GITLAB in cls._providers:
            providers.append({
                "name": "gitlab",
                "display_name": "GitLab",
                "icon": "gitlab-logo",
                "oauth_scopes": "read_user read_repository read_api",
                "description": "Connect your GitLab account to import repositories"
            })

        # Bitbucket
        if GitProviderType.BITBUCKET in cls._providers:
            providers.append({
                "name": "bitbucket",
                "display_name": "Bitbucket",
                "icon": "bitbucket-logo",
                "oauth_scopes": "repository account",
                "description": "Connect your Bitbucket account to import repositories"
            })

        return providers


def _register_providers() -> None:
    """
    Register all available provider implementations.

    This is called on module import to ensure providers are available.
    """
    try:
        from .providers.github import GitHubProvider
        GitProviderManager.register_provider(GitProviderType.GITHUB, GitHubProvider)
    except ImportError as e:
        logger.warning(f"Failed to register GitHub provider: {e}")

    try:
        from .providers.gitlab import GitLabProvider
        GitProviderManager.register_provider(GitProviderType.GITLAB, GitLabProvider)
    except ImportError as e:
        logger.warning(f"Failed to register GitLab provider: {e}")

    try:
        from .providers.bitbucket import BitbucketProvider
        GitProviderManager.register_provider(GitProviderType.BITBUCKET, BitbucketProvider)
    except ImportError as e:
        logger.warning(f"Failed to register Bitbucket provider: {e}")


# Register providers on module import
_register_providers()


# Global instance
_git_provider_manager: Optional[GitProviderManager] = None


def get_git_provider_manager() -> GitProviderManager:
    """Get the global GitProviderManager instance."""
    global _git_provider_manager
    if _git_provider_manager is None:
        _git_provider_manager = GitProviderManager()
    return _git_provider_manager
