"""
Git Providers package for unified GitHub, GitLab, and Bitbucket integration.
"""

from .base import (
    BaseGitProvider,
    GitProviderType,
    NormalizedBranch,
    NormalizedRepository,
    NormalizedUser,
)
from .credential_service import GitProviderCredentialService, get_git_provider_credential_service
from .manager import GitProviderManager, get_git_provider_manager

__all__ = [
    # Base classes and models
    "BaseGitProvider",
    "NormalizedRepository",
    "NormalizedBranch",
    "NormalizedUser",
    "GitProviderType",
    # Manager
    "GitProviderManager",
    "get_git_provider_manager",
    # Credential service
    "GitProviderCredentialService",
    "get_git_provider_credential_service",
]
