"""
Bitbucket provider implementation.

Uses Bitbucket Cloud REST API 2.0.
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


class BitbucketProvider(BaseGitProvider):
    """
    Bitbucket API client implementation.

    Provides access to Bitbucket repositories, branches, and user information
    through the Bitbucket Cloud REST API 2.0.
    """

    PROVIDER_NAME = GitProviderType.BITBUCKET
    OAUTH_AUTHORIZE_URL = "https://bitbucket.org/site/oauth2/authorize"
    OAUTH_TOKEN_URL = "https://bitbucket.org/site/oauth2/access_token"
    API_BASE_URL = "https://api.bitbucket.org/2.0"

    def _build_headers(self) -> Dict[str, str]:
        """Build Bitbucket-specific HTTP headers."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    async def get_user_info(self) -> NormalizedUser:
        """Get authenticated user information from Bitbucket."""
        data = await self._request("GET", "/user")

        return NormalizedUser(
            id=data["uuid"],
            username=data["username"],
            email=None,  # Bitbucket requires separate call for emails
            display_name=data.get("display_name"),
            avatar_url=data.get("links", {}).get("avatar", {}).get("href")
        )

    async def get_user_emails(self) -> List[str]:
        """Get user email addresses from Bitbucket."""
        try:
            # Bitbucket returns emails via /user/emails endpoint
            emails_data = await self._request("GET", "/user/emails")
            emails = []
            for email_info in emails_data.get("values", []):
                if email_info.get("is_primary"):
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
        """
        List repositories for the authenticated Bitbucket user.

        Bitbucket requires fetching repositories per workspace.
        """
        # First get user's workspaces
        workspaces_data = await self._request("GET", "/workspaces")
        workspaces = workspaces_data.get("values", [])

        all_repos = []

        for workspace in workspaces:
            workspace_slug = workspace["slug"]

            # Map sort parameter to Bitbucket's sort field
            sort_map = {
                "updated": "-updated_on",
                "created": "-created_on",
                "name": "name"
            }
            sort_field = sort_map.get(sort, "-updated_on")

            params = {
                "sort": sort_field,
                "pagelen": 100
            }

            # Add privacy filter if not "all"
            if visibility == "private":
                params["q"] = "is_private=true"
            elif visibility == "public":
                params["q"] = "is_private=false"

            try:
                repos_data = await self._request(
                    "GET",
                    f"/repositories/{workspace_slug}",
                    params=params
                )

                for repo in repos_data.get("values", []):
                    all_repos.append(self._normalize_repository(repo))
            except Exception:
                # Skip workspaces we can't access
                continue

        return all_repos

    async def get_repository(
        self,
        owner: str,
        repo: str
    ) -> NormalizedRepository:
        """
        Get information about a specific Bitbucket repository.

        Args:
            owner: Workspace slug
            repo: Repository slug
        """
        data = await self._request("GET", f"/repositories/{owner}/{repo}")
        return self._normalize_repository(data)

    async def list_branches(
        self,
        owner: str,
        repo: str
    ) -> List[NormalizedBranch]:
        """List branches for a Bitbucket repository."""
        # Get branches
        branches_data = await self._request(
            "GET",
            f"/repositories/{owner}/{repo}/refs/branches",
            params={"pagelen": 100}
        )

        # Get repo info for default branch
        repo_info = await self._request("GET", f"/repositories/{owner}/{repo}")
        default_branch = repo_info.get("mainbranch", {}).get("name", "main")

        branches = []
        for branch in branches_data.get("values", []):
            branches.append(NormalizedBranch(
                name=branch["name"],
                is_default=(branch["name"] == default_branch),
                commit_sha=branch.get("target", {}).get("hash", ""),
                protected=False  # Bitbucket has branch restrictions, not simple protected flag
            ))

        return branches

    async def get_default_branch(
        self,
        owner: str,
        repo: str
    ) -> str:
        """Get the default branch name for a Bitbucket repository."""
        repo_info = await self._request("GET", f"/repositories/{owner}/{repo}")
        return repo_info.get("mainbranch", {}).get("name", "main")

    def _normalize_repository(self, data: Dict[str, Any]) -> NormalizedRepository:
        """Convert Bitbucket API response to normalized repository format."""
        # Bitbucket uses full_name which is workspace/repo_slug
        full_name = data.get("full_name", "")
        owner = full_name.split("/")[0] if "/" in full_name else ""

        updated_at = None
        if data.get("updated_on"):
            try:
                updated_at = datetime.fromisoformat(data["updated_on"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Get clone URLs from links
        clone_url = ""
        ssh_url = None
        for clone_link in data.get("links", {}).get("clone", []):
            if clone_link.get("name") == "https":
                clone_url = clone_link.get("href", "")
            elif clone_link.get("name") == "ssh":
                ssh_url = clone_link.get("href")

        # Web URL
        web_url = data.get("links", {}).get("html", {}).get("href", "")

        return NormalizedRepository(
            id=data.get("uuid", ""),
            name=data.get("slug", data.get("name", "")),
            full_name=full_name,
            description=data.get("description"),
            clone_url=clone_url,
            ssh_url=ssh_url,
            web_url=web_url,
            default_branch=data.get("mainbranch", {}).get("name", "main"),
            private=data.get("is_private", False),
            updated_at=updated_at,
            owner=owner,
            provider=GitProviderType.BITBUCKET,
            language=data.get("language"),
            size=data.get("size", 0),
            stars_count=0,  # Bitbucket doesn't have stars
            forks_count=0   # Would need separate API call
        )

    @staticmethod
    def parse_repo_url(repo_url: str) -> Optional[Dict[str, str]]:
        """
        Parse a Bitbucket repository URL to extract workspace and repo slug.

        Supports:
        - https://bitbucket.org/workspace/repo
        - https://bitbucket.org/workspace/repo.git
        - git@bitbucket.org:workspace/repo.git

        Args:
            repo_url: Bitbucket repository URL

        Returns:
            Dictionary with 'owner' (workspace) and 'repo' (slug) keys, or None if invalid
        """
        # Pattern for HTTPS URLs
        https_pattern = r"https?://bitbucket\.org/([^/]+)/([^/]+?)(?:\.git)?/?$"
        # Pattern for SSH URLs
        ssh_pattern = r"git@bitbucket\.org:([^/]+)/([^/]+?)(?:\.git)?$"

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
        Format a Bitbucket clone URL with optional authentication.

        Args:
            owner: Workspace slug
            repo: Repository slug
            access_token: Optional token for authenticated cloning

        Returns:
            Clone URL string
        """
        if access_token:
            # Bitbucket uses x-token-auth:token format
            return f"https://x-token-auth:{access_token}@bitbucket.org/{owner}/{repo}.git"
        return f"https://bitbucket.org/{owner}/{repo}.git"

    async def get_workspaces(self) -> List[Dict[str, Any]]:
        """Get all workspaces the user has access to."""
        data = await self._request("GET", "/workspaces")
        return data.get("values", [])
