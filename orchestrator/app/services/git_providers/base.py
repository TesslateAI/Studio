"""
Base classes and normalized models for Git providers.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import httpx
import re


class GitProviderType(str, Enum):
    """Supported Git provider types."""
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"


class NormalizedUser(BaseModel):
    """Normalized user data across all providers."""
    id: str
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


class NormalizedRepository(BaseModel):
    """Normalized repository data across all providers."""
    id: str
    name: str
    full_name: str  # owner/repo format
    description: Optional[str] = None
    clone_url: str
    ssh_url: Optional[str] = None
    web_url: str
    default_branch: str = "main"
    private: bool = False
    updated_at: Optional[datetime] = None
    owner: str
    provider: GitProviderType
    language: Optional[str] = None
    size: int = 0
    stars_count: int = 0
    forks_count: int = 0


class NormalizedBranch(BaseModel):
    """Normalized branch data across all providers."""
    name: str
    is_default: bool = False
    commit_sha: str
    protected: bool = False


class BaseGitProvider(ABC):
    """
    Abstract base class for Git hosting providers.

    All provider implementations (GitHub, GitLab, Bitbucket) must inherit from this
    class and implement the abstract methods.
    """

    PROVIDER_NAME: GitProviderType
    OAUTH_AUTHORIZE_URL: str
    OAUTH_TOKEN_URL: str
    API_BASE_URL: str

    def __init__(self, access_token: str):
        """
        Initialize the provider with an access token.

        Args:
            access_token: OAuth access token for API authentication
        """
        self.access_token = access_token
        self._headers = self._build_headers()

    @abstractmethod
    def _build_headers(self) -> Dict[str, str]:
        """
        Build provider-specific HTTP headers for API requests.

        Returns:
            Dictionary of HTTP headers
        """
        pass

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict] = None,
        params: Optional[Dict] = None,
        timeout: float = 30.0
    ) -> Any:
        """
        Make an authenticated request to the provider API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without base URL)
            json: JSON payload for POST/PUT requests
            params: URL query parameters
            timeout: Request timeout in seconds

        Returns:
            JSON response

        Raises:
            httpx.HTTPStatusError: If the request fails
        """
        url = f"{self.API_BASE_URL}{endpoint}"

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                headers=self._headers,
                json=json,
                params=params,
                timeout=timeout
            )
            response.raise_for_status()
            return response.json()

    @abstractmethod
    async def get_user_info(self) -> NormalizedUser:
        """
        Get authenticated user information.

        Returns:
            Normalized user data
        """
        pass

    @abstractmethod
    async def get_user_emails(self) -> List[str]:
        """
        Get user email addresses.

        Returns:
            List of email addresses
        """
        pass

    @abstractmethod
    async def list_repositories(
        self,
        visibility: str = "all",
        sort: str = "updated"
    ) -> List[NormalizedRepository]:
        """
        List repositories accessible by the authenticated user.

        Args:
            visibility: Filter by visibility (all, public, private)
            sort: Sort order (updated, created, name)

        Returns:
            List of normalized repository data
        """
        pass

    @abstractmethod
    async def get_repository(
        self,
        owner: str,
        repo: str
    ) -> NormalizedRepository:
        """
        Get information about a specific repository.

        Args:
            owner: Repository owner/namespace
            repo: Repository name

        Returns:
            Normalized repository data
        """
        pass

    @abstractmethod
    async def list_branches(
        self,
        owner: str,
        repo: str
    ) -> List[NormalizedBranch]:
        """
        List branches for a repository.

        Args:
            owner: Repository owner/namespace
            repo: Repository name

        Returns:
            List of normalized branch data
        """
        pass

    @abstractmethod
    async def get_default_branch(
        self,
        owner: str,
        repo: str
    ) -> str:
        """
        Get the default branch name for a repository.

        Args:
            owner: Repository owner/namespace
            repo: Repository name

        Returns:
            Default branch name (e.g., "main" or "master")
        """
        pass

    async def validate_token(self) -> bool:
        """
        Validate that the access token is valid.

        Returns:
            True if token is valid, False otherwise
        """
        try:
            await self.get_user_info()
            return True
        except httpx.HTTPStatusError:
            return False

    @staticmethod
    @abstractmethod
    def parse_repo_url(repo_url: str) -> Optional[Dict[str, str]]:
        """
        Parse a repository URL to extract owner and repo name.

        Args:
            repo_url: Repository URL (HTTPS or SSH format)

        Returns:
            Dictionary with 'owner' and 'repo' keys, or None if invalid
        """
        pass

    @staticmethod
    @abstractmethod
    def format_clone_url(
        owner: str,
        repo: str,
        access_token: Optional[str] = None
    ) -> str:
        """
        Format a clone URL with optional authentication.

        Args:
            owner: Repository owner/namespace
            repo: Repository name
            access_token: Optional token for authenticated cloning

        Returns:
            Clone URL string
        """
        pass

    @staticmethod
    def detect_provider_from_url(repo_url: str) -> Optional[GitProviderType]:
        """
        Detect which provider a repository URL belongs to.

        Args:
            repo_url: Repository URL

        Returns:
            GitProviderType or None if not recognized
        """
        url_lower = repo_url.lower()

        if "github.com" in url_lower:
            return GitProviderType.GITHUB
        elif "gitlab.com" in url_lower or "gitlab" in url_lower:
            return GitProviderType.GITLAB
        elif "bitbucket.org" in url_lower or "bitbucket" in url_lower:
            return GitProviderType.BITBUCKET

        return None
