"""
Git Providers package for unified GitHub, GitLab, and Bitbucket integration.
"""
from .base import (
    BaseGitProvider,
    NormalizedRepository,
    NormalizedBranch,
    NormalizedUser,
    GitProviderType,
)
from .manager import GitProviderManager, get_git_provider_manager
from .credential_service import GitProviderCredentialService, get_git_provider_credential_service

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
