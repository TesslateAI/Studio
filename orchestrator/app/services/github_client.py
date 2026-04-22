"""
GitHub API Client for repository and user operations.
"""

from typing import Any

import httpx


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
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(
        self, method: str, endpoint: str, json: dict | None = None, params: dict | None = None
    ) -> dict[str, Any]:
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
                method=method, url=url, headers=self.headers, json=json, params=params, timeout=30.0
            )
            response.raise_for_status()
            return response.json()

    async def get_user_info(self) -> dict[str, Any]:
        """
        Get authenticated user information.

        Returns:
            Dictionary with user info (login, email, id, etc.)
        """
        return await self._request("GET", "/user")

    async def get_user_emails(self) -> list[dict[str, Any]]:
        """
        Get authenticated user's email addresses.

        Returns:
            List of email dictionaries
        """
        return await self._request("GET", "/user/emails")

    async def list_user_repositories(
        self, visibility: str = "all", sort: str = "updated", per_page: int = 100
    ) -> list[dict[str, Any]]:
        """
        List repositories for the authenticated user.

        Args:
            visibility: Repository visibility (all, public, private)
            sort: Sort order (created, updated, pushed, full_name)
            per_page: Results per page (max 100)

        Returns:
            List of repository dictionaries
        """
        params = {"visibility": visibility, "sort": sort, "per_page": per_page}
        return await self._request("GET", "/user/repos", params=params)

    async def create_repository(
        self,
        name: str,
        description: str | None = None,
        private: bool = True,
        auto_init: bool = False,
    ) -> dict[str, Any]:
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
            "auto_init": auto_init,
        }
        return await self._request("POST", "/user/repos", json=payload)

    async def get_repository_info(self, owner: str, repo: str) -> dict[str, Any]:
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
        self, owner: str, repo: str, per_page: int = 100
    ) -> list[dict[str, Any]]:
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

    async def get_default_branch(self, owner: str, repo: str) -> str:
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

    async def get_repository_tree(
        self, owner: str, repo: str, branch: str | None = None, recursive: bool = True
    ) -> dict[str, Any]:
        """
        Get the full file tree for a repository branch.

        Uses GitHub's Git Trees API, which returns every blob/tree entry in a
        single call. If the repo exceeds the 100k-entry / 7 MB response cap,
        GitHub sets `truncated: true` — the caller should surface that to the
        user so they know the listing is incomplete.

        Args:
            owner: Repository owner
            repo: Repository name
            branch: Branch to list (defaults to the repository's default branch)
            recursive: Fetch the full tree in one request. Setting False only
                returns entries at the root — rarely what the UI wants.

        Returns:
            dict with keys:
                branch: resolved branch name
                sha: commit SHA the tree was read from
                truncated: bool — True if GitHub's limit was hit
                tree: list of entries with path, type ('blob'|'tree'),
                      size (blobs only), mode, sha, url
        """
        if not branch:
            branch = await self.get_default_branch(owner, repo)

        branch_info = await self._request("GET", f"/repos/{owner}/{repo}/branches/{branch}")
        commit_sha = branch_info.get("commit", {}).get("sha")
        tree_sha = branch_info.get("commit", {}).get("commit", {}).get("tree", {}).get("sha")
        if not tree_sha:
            return {"branch": branch, "sha": commit_sha, "truncated": False, "tree": []}

        params: dict[str, str] = {"recursive": "1"} if recursive else {}
        tree = await self._request(
            "GET", f"/repos/{owner}/{repo}/git/trees/{tree_sha}", params=params
        )
        return {
            "branch": branch,
            "sha": commit_sha,
            "truncated": bool(tree.get("truncated", False)),
            "tree": tree.get("tree", []),
        }

    async def list_commits(
        self, owner: str, repo: str, sha: str | None = None, per_page: int = 30
    ) -> list[dict[str, Any]]:
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
        params: dict[str, Any] = {"per_page": per_page}
        if sha:
            params["sha"] = sha

        return await self._request("GET", f"/repos/{owner}/{repo}/commits", params=params)

    async def get_commit(self, owner: str, repo: str, ref: str) -> dict[str, Any]:
        """
        Get a single commit including stats and file changes.

        This hits the per-commit endpoint which returns ``stats`` (additions,
        deletions, total) and ``files`` (patches) in addition to the fields
        returned by ``list_commits``. Use sparingly — it costs one request per
        commit.

        Args:
            owner: Repository owner
            repo: Repository name
            ref: Commit SHA or ref (branch/tag)

        Returns:
            Commit dictionary with ``stats`` and ``files`` keys.
        """
        return await self._request("GET", f"/repos/{owner}/{repo}/commits/{ref}")

    async def compare_commits(self, owner: str, repo: str, base: str, head: str) -> dict[str, Any]:
        """
        Compare two commits/branches.

        GitHub's compare endpoint returns ``ahead_by``, ``behind_by``,
        ``total_commits`` and a list of commits between the two refs. Useful
        for rendering "3 ahead · 1 behind" style branch status.

        Args:
            owner: Repository owner
            repo: Repository name
            base: Base ref (e.g. default branch name)
            head: Head ref (e.g. feature branch name)

        Returns:
            Compare response dictionary.
        """
        return await self._request("GET", f"/repos/{owner}/{repo}/compare/{base}...{head}")

    async def list_contributors(
        self, owner: str, repo: str, per_page: int = 30
    ) -> list[dict[str, Any]]:
        """
        List contributors for a repository, ordered by commit count.

        Args:
            owner: Repository owner
            repo: Repository name
            per_page: Max contributors to return (GitHub caps per_page at 100)

        Returns:
            List of contributor dictionaries (login, avatar_url, contributions).
        """
        params = {"per_page": per_page}
        return await self._request("GET", f"/repos/{owner}/{repo}/contributors", params=params)

    async def list_pulls(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        per_page: int = 30,
    ) -> list[dict[str, Any]]:
        """
        List pull requests for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            state: One of ``open``, ``closed`` or ``all``
            per_page: Results per page (max 100)

        Returns:
            List of pull request dictionaries.
        """
        params = {"state": state, "per_page": per_page}
        return await self._request("GET", f"/repos/{owner}/{repo}/pulls", params=params)

    async def get_rate_limit(self) -> dict[str, Any]:
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
    def parse_repo_url(repo_url: str) -> dict[str, str] | None:
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
