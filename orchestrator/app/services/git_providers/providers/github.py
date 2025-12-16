"""
GitHub provider implementation.

Refactored from the original github_client.py to follow the unified provider pattern.
"""
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

from ..base import (
    BaseGitProvider,
    GitProviderType,
    NormalizedRepository,
    NormalizedBranch,
    NormalizedUser,
)


class GitHubProvider(BaseGitProvider):
    """
    GitHub API client implementation.

    Provides access to GitHub repositories, branches, and user information
    through the GitHub REST API v3.
    """

    PROVIDER_NAME = GitProviderType.GITHUB
    OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
    API_BASE_URL = "https://api.github.com"

    def _build_headers(self) -> Dict[str, str]:
        """Build GitHub-specific HTTP headers."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

    async def get_user_info(self) -> NormalizedUser:
        """Get authenticated user information from GitHub."""
        data = await self._request("GET", "/user")

        return NormalizedUser(
            id=str(data["id"]),
            username=data["login"],
            email=data.get("email"),
            display_name=data.get("name"),
            avatar_url=data.get("avatar_url")
        )

    async def get_user_emails(self) -> List[str]:
        """Get user email addresses from GitHub."""
        try:
            emails_data = await self._request("GET", "/user/emails")
            # Return primary email first, then others
            emails = []
            for email_info in emails_data:
                if email_info.get("primary"):
                    emails.insert(0, email_info["email"])
                else:
                    emails.append(email_info["email"])
            return emails
        except Exception:
            return []

    async def list_repositories(
        self,
        visibility: str = "all",
        sort: str = "updated"
    ) -> List[NormalizedRepository]:
        """List repositories for the authenticated GitHub user."""
        params = {
            "visibility": visibility,
            "sort": sort,
            "per_page": 100
        }
        repos_data = await self._request("GET", "/user/repos", params=params)

        return [
            self._normalize_repository(repo)
            for repo in repos_data
        ]

    async def get_repository(
        self,
        owner: str,
        repo: str
    ) -> NormalizedRepository:
        """Get information about a specific GitHub repository."""
        data = await self._request("GET", f"/repos/{owner}/{repo}")
        return self._normalize_repository(data)

    async def list_branches(
        self,
        owner: str,
        repo: str
    ) -> List[NormalizedBranch]:
        """List branches for a GitHub repository."""
        # Get branches
        branches_data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/branches",
            params={"per_page": 100}
        )

        # Get default branch name
        repo_info = await self._request("GET", f"/repos/{owner}/{repo}")
        default_branch = repo_info.get("default_branch", "main")

        return [
            NormalizedBranch(
                name=branch["name"],
                is_default=(branch["name"] == default_branch),
                commit_sha=branch["commit"]["sha"],
                protected=branch.get("protected", False)
            )
            for branch in branches_data
        ]

    async def get_default_branch(
        self,
        owner: str,
        repo: str
    ) -> str:
        """Get the default branch name for a GitHub repository."""
        repo_info = await self._request("GET", f"/repos/{owner}/{repo}")
        return repo_info.get("default_branch", "main")

    def _normalize_repository(self, data: Dict[str, Any]) -> NormalizedRepository:
        """Convert GitHub API response to normalized repository format."""
        owner = data["owner"]["login"] if isinstance(data.get("owner"), dict) else data.get("owner", "")

        updated_at = None
        if data.get("updated_at"):
            try:
                updated_at = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return NormalizedRepository(
            id=str(data["id"]),
            name=data["name"],
            full_name=data["full_name"],
            description=data.get("description"),
            clone_url=data["clone_url"],
            ssh_url=data.get("ssh_url"),
            web_url=data["html_url"],
            default_branch=data.get("default_branch", "main"),
            private=data.get("private", False),
            updated_at=updated_at,
            owner=owner,
            provider=GitProviderType.GITHUB,
            language=data.get("language"),
            size=data.get("size", 0),
            stars_count=data.get("stargazers_count", 0),
            forks_count=data.get("forks_count", 0)
        )

    @staticmethod
    def parse_repo_url(repo_url: str) -> Optional[Dict[str, str]]:
        """
        Parse a GitHub repository URL to extract owner and repo name.

        Supports:
        - https://github.com/owner/repo
        - https://github.com/owner/repo.git
        - git@github.com:owner/repo.git

        Args:
            repo_url: GitHub repository URL

        Returns:
            Dictionary with 'owner' and 'repo' keys, or None if invalid
        """
        # Pattern for HTTPS URLs
        https_pattern = r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$"
        # Pattern for SSH URLs
        ssh_pattern = r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$"

        # Try HTTPS pattern
        match = re.match(https_pattern, repo_url)
        if match:
            return {"owner": match.group(1), "repo": match.group(2)}

        # Try SSH pattern
        match = re.match(ssh_pattern, repo_url)
        if match:
            return {"owner": match.group(1), "repo": match.group(2)}

        return None

    @staticmethod
    def format_clone_url(
        owner: str,
        repo: str,
        access_token: Optional[str] = None
    ) -> str:
        """
        Format a GitHub clone URL with optional authentication.

        Args:
            owner: Repository owner
            repo: Repository name
            access_token: Optional token for authenticated cloning

        Returns:
            Clone URL string
        """
        if access_token:
            return f"https://{access_token}@github.com/{owner}/{repo}.git"
        return f"https://github.com/{owner}/{repo}.git"

    async def get_rate_limit(self) -> Dict[str, Any]:
        """Get rate limit status for the authenticated user."""
        return await self._request("GET", "/rate_limit")

    async def list_commits(
        self,
        owner: str,
        repo: str,
        sha: Optional[str] = None,
        per_page: int = 30
    ) -> List[Dict[str, Any]]:
        """List commits for a repository."""
        params = {"per_page": per_page}
        if sha:
            params["sha"] = sha

        return await self._request("GET", f"/repos/{owner}/{repo}/commits", params=params)

    async def create_repository(
        self,
        name: str,
        description: Optional[str] = None,
        private: bool = True,
        auto_init: bool = False
    ) -> Dict[str, Any]:
        """Create a new repository for the authenticated user."""
        payload = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": auto_init
        }
        return await self._request("POST", "/user/repos", json=payload)
