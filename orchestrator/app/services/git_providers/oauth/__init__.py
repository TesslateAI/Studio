"""
OAuth service implementations for Git providers.
"""
from .github import GitHubOAuthService, get_github_oauth_service
from .gitlab import GitLabOAuthService, get_gitlab_oauth_service
from .bitbucket import BitbucketOAuthService, get_bitbucket_oauth_service

__all__ = [
    "GitHubOAuthService",
    "get_github_oauth_service",
    "GitLabOAuthService",
    "get_gitlab_oauth_service",
    "BitbucketOAuthService",
    "get_bitbucket_oauth_service",
]
