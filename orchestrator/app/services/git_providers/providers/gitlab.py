"""
GitLab provider implementation.

Supports both gitlab.com and self-hosted GitLab instances.
"""
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import quote_plus

from ..base import (
    BaseGitProvider,
    GitProviderType,
    NormalizedRepository,
    NormalizedBranch,
    NormalizedUser,
)


class GitLabProvider(BaseGitProvider):
    """
    GitLab API client implementation.

    Provides access to GitLab repositories, branches, and user information
    through the GitLab REST API v4.

    Supports both gitlab.com and self-hosted GitLab instances via
    configurable API base URL.
    """

    PROVIDER_NAME = GitProviderType.GITLAB
    OAUTH_AUTHORIZE_URL = "https://gitlab.com/oauth/authorize"
    OAUTH_TOKEN_URL = "https://gitlab.com/oauth/token"
    API_BASE_URL = "https://gitlab.com/api/v4"

    def __init__(self, access_token: str, api_base_url: Optional[str] = None):
        """
        Initialize the GitLab provider.

        Args:
            access_token: OAuth access token for API authentication
            api_base_url: Optional custom API base URL for self-hosted GitLab
        """
        if api_base_url:
            self.API_BASE_URL = api_base_url.rstrip("/")
            if not self.API_BASE_URL.endswith("/api/v4"):
                self.API_BASE_URL = f"{self.API_BASE_URL}/api/v4"

        super().__init__(access_token)

    def _build_headers(self) -> Dict[str, str]:
        """Build GitLab-specific HTTP headers."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    async def get_user_info(self) -> NormalizedUser:
        """Get authenticated user information from GitLab."""
        data = await self._request("GET", "/user")

        return NormalizedUser(
            id=str(data["id"]),
            username=data["username"],
            email=data.get("email"),
            display_name=data.get("name"),
            avatar_url=data.get("avatar_url")
        )

    async def get_user_emails(self) -> List[str]:
        """Get user email addresses from GitLab."""
        try:
            # GitLab returns emails via /user/emails endpoint
            emails_data = await self._request("GET", "/user/emails")
            return [email_info["email"] for email_info in emails_data]
        except Exception:
            # Fallback to user info email
            try:
                user_info = await self._request("GET", "/user")
                if user_info.get("email"):
                    return [user_info["email"]]
            except Exception:
                pass
            return []

    async def list_repositories(
        self,
        visibility: str = "all",
        sort: str = "updated"
    ) -> List[NormalizedRepository]:
        """
        List repositories (projects) for the authenticated GitLab user.

        GitLab uses "projects" terminology instead of "repositories".
        """
        # Map sort parameter to GitLab's order_by
        order_by_map = {
            "updated": "updated_at",
            "created": "created_at",
            "name": "name"
        }
        order_by = order_by_map.get(sort, "updated_at")

        params = {
            "membership": "true",  # Only projects user is a member of
            "order_by": order_by,
            "sort": "desc",
            "per_page": 100
        }

        # Add visibility filter if not "all"
        if visibility != "all":
            params["visibility"] = visibility

        projects_data = await self._request("GET", "/projects", params=params)

        return [
            self._normalize_repository(project)
            for project in projects_data
        ]

    async def get_repository(
        self,
        owner: str,
        repo: str
    ) -> NormalizedRepository:
        """
        Get information about a specific GitLab project.

        Uses URL-encoded project path (namespace/project_name).
        """
        # GitLab uses URL-encoded path: namespace%2Fproject
        project_path = quote_plus(f"{owner}/{repo}")
        data = await self._request("GET", f"/projects/{project_path}")
        return self._normalize_repository(data)

    async def list_branches(
        self,
        owner: str,
        repo: str
    ) -> List[NormalizedBranch]:
        """List branches for a GitLab project."""
        project_path = quote_plus(f"{owner}/{repo}")

        # Get branches
        branches_data = await self._request(
            "GET",
            f"/projects/{project_path}/repository/branches",
            params={"per_page": 100}
        )

        # Get project info for default branch
        project_info = await self._request("GET", f"/projects/{project_path}")
        default_branch = project_info.get("default_branch", "main")

        return [
            NormalizedBranch(
                name=branch["name"],
                is_default=(branch["name"] == default_branch),
                commit_sha=branch["commit"]["id"],
                protected=branch.get("protected", False)
            )
            for branch in branches_data
        ]

    async def get_default_branch(
        self,
        owner: str,
        repo: str
    ) -> str:
        """Get the default branch name for a GitLab project."""
        project_path = quote_plus(f"{owner}/{repo}")
        project_info = await self._request("GET", f"/projects/{project_path}")
        return project_info.get("default_branch", "main")

    def _normalize_repository(self, data: Dict[str, Any]) -> NormalizedRepository:
        """Convert GitLab API response to normalized repository format."""
        # GitLab uses path_with_namespace which is namespace/project_name
        full_name = data.get("path_with_namespace", "")
        owner = full_name.split("/")[0] if "/" in full_name else ""

        updated_at = None
        if data.get("last_activity_at"):
            try:
                updated_at = datetime.fromisoformat(data["last_activity_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # GitLab visibility mapping
        private = data.get("visibility", "private") == "private"

        return NormalizedRepository(
            id=str(data["id"]),
            name=data["path"],  # GitLab uses "path" for the repo name
            full_name=full_name,
            description=data.get("description"),
            clone_url=data.get("http_url_to_repo", ""),
            ssh_url=data.get("ssh_url_to_repo"),
            web_url=data.get("web_url", ""),
            default_branch=data.get("default_branch", "main"),
            private=private,
            updated_at=updated_at,
            owner=owner,
            provider=GitProviderType.GITLAB,
            language=None,  # GitLab doesn't return this in project listing
            size=0,  # GitLab returns this differently
            stars_count=data.get("star_count", 0),
            forks_count=data.get("forks_count", 0)
        )

    @staticmethod
    def parse_repo_url(repo_url: str) -> Optional[Dict[str, str]]:
        """
        Parse a GitLab repository URL to extract owner and repo name.

        Supports:
        - https://gitlab.com/owner/repo
        - https://gitlab.com/owner/repo.git
        - https://gitlab.example.com/owner/repo (self-hosted)
        - git@gitlab.com:owner/repo.git

        Note: GitLab supports nested groups (owner/subgroup/repo).
        This returns the namespace as owner and project as repo.

        Args:
            repo_url: GitLab repository URL

        Returns:
            Dictionary with 'owner' and 'repo' keys, or None if invalid
        """
        # Pattern for HTTPS URLs (handles nested groups)
        # Captures everything before last segment as owner, last segment as repo
        https_pattern = r"https?://[^/]+/(.+)/([^/]+?)(?:\.git)?/?$"
        # Pattern for SSH URLs
        ssh_pattern = r"git@[^:]+:(.+)/([^/]+?)(?:\.git)?$"

        # Try HTTPS pattern
        match = re.match(https_pattern, repo_url)
        if match and "gitlab" in repo_url.lower():
            return {"owner": match.group(1), "repo": match.group(2)}

        # Try SSH pattern
        match = re.match(ssh_pattern, repo_url)
        if match and "gitlab" in repo_url.lower():
            return {"owner": match.group(1), "repo": match.group(2)}

        return None

    @staticmethod
    def format_clone_url(
        owner: str,
        repo: str,
        access_token: Optional[str] = None,
        base_url: str = "https://gitlab.com"
    ) -> str:
        """
        Format a GitLab clone URL with optional authentication.

        Args:
            owner: Repository owner/namespace (can include subgroups)
            repo: Repository name
            access_token: Optional token for authenticated cloning
            base_url: GitLab instance base URL

        Returns:
            Clone URL string
        """
        base_url = base_url.rstrip("/")

        if access_token:
            # GitLab uses oauth2:token format for authenticated cloning
            return f"https://oauth2:{access_token}@{base_url.replace('https://', '').replace('http://', '')}/{owner}/{repo}.git"
        return f"{base_url}/{owner}/{repo}.git"

    async def get_project_by_id(self, project_id: int) -> NormalizedRepository:
        """Get a project by its numeric ID."""
        data = await self._request("GET", f"/projects/{project_id}")
        return self._normalize_repository(data)
