"""
GitHub API Client for repository and user operations.
"""
import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime


class GitHubClient:
    """Client for interacting with the GitHub API."""

    def __init__(self, access_token: str):
        """
        Initialize the GitHub API client.

        Args:
            access_token: GitHub OAuth access token or Personal Access Token
        """
        self.token = access_token
        self.api_base = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to the GitHub API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without base URL)
            json: JSON payload for POST/PUT requests
            params: URL query parameters

        Returns:
            JSON response as dictionary

        Raises:
            httpx.HTTPStatusError: If the request fails
        """
        url = f"{self.api_base}{endpoint}"

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                headers=self.headers,
                json=json,
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()

    async def get_user_info(self) -> Dict[str, Any]:
        """
        Get authenticated user information.

        Returns:
            Dictionary with user info (login, email, id, etc.)
        """
        return await self._request("GET", "/user")

    async def get_user_emails(self) -> List[Dict[str, Any]]:
        """
        Get authenticated user's email addresses.

        Returns:
            List of email dictionaries
        """
        return await self._request("GET", "/user/emails")

    async def list_user_repositories(
        self,
        visibility: str = "all",
        sort: str = "updated",
        per_page: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List repositories for the authenticated user.

        Args:
            visibility: Repository visibility (all, public, private)
            sort: Sort order (created, updated, pushed, full_name)
            per_page: Results per page (max 100)

        Returns:
            List of repository dictionaries
        """
        params = {
            "visibility": visibility,
            "sort": sort,
            "per_page": per_page
        }
        return await self._request("GET", "/user/repos", params=params)

    async def create_repository(
        self,
        name: str,
        description: Optional[str] = None,
        private: bool = True,
        auto_init: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new repository for the authenticated user.

        Args:
            name: Repository name
            description: Repository description
            private: Whether the repository should be private
            auto_init: Initialize with README

        Returns:
            Dictionary with repository info
        """
        payload = {
            "name": name,
            "description": description,
            "private": private,
            "auto_init": auto_init
        }
        return await self._request("POST", "/user/repos", json=payload)

    async def get_repository_info(
        self,
        owner: str,
        repo: str
    ) -> Dict[str, Any]:
        """
        Get information about a specific repository.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            Dictionary with repository info
        """
        return await self._request("GET", f"/repos/{owner}/{repo}")

    async def list_branches(
        self,
        owner: str,
        repo: str,
        per_page: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List branches for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            per_page: Results per page (max 100)

        Returns:
            List of branch dictionaries
        """
        params = {"per_page": per_page}
        return await self._request("GET", f"/repos/{owner}/{repo}/branches", params=params)

    async def get_default_branch(
        self,
        owner: str,
        repo: str
    ) -> str:
        """
        Get the default branch name for a repository.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            Default branch name (e.g., "main" or "master")
        """
        repo_info = await self.get_repository_info(owner, repo)
        return repo_info.get("default_branch", "main")

    async def list_commits(
        self,
        owner: str,
        repo: str,
        sha: Optional[str] = None,
        per_page: int = 30
    ) -> List[Dict[str, Any]]:
        """
        List commits for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            sha: SHA or branch to start listing commits from
            per_page: Results per page (max 100)

        Returns:
            List of commit dictionaries
        """
        params = {"per_page": per_page}
        if sha:
            params["sha"] = sha

        return await self._request("GET", f"/repos/{owner}/{repo}/commits", params=params)

    async def get_rate_limit(self) -> Dict[str, Any]:
        """
        Get rate limit status for the authenticated user.

        Returns:
            Dictionary with rate limit info
        """
        return await self._request("GET", "/rate_limit")

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
    def parse_repo_url(repo_url: str) -> Optional[Dict[str, str]]:
        """
        Parse a GitHub repository URL to extract owner and repo name.

        Args:
            repo_url: GitHub repository URL (https://github.com/owner/repo or git@github.com:owner/repo.git)

        Returns:
            Dictionary with 'owner' and 'repo' keys, or None if invalid
        """
        import re

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
    def format_repo_url(owner: str, repo: str, use_https: bool = True) -> str:
        """
        Format a repository URL from owner and repo name.

        Args:
            owner: Repository owner
            repo: Repository name
            use_https: Use HTTPS URL (default) or SSH

        Returns:
            Formatted repository URL
        """
        if use_https:
            return f"https://github.com/{owner}/{repo}.git"
        else:
            return f"git@github.com:{owner}/{repo}.git"
