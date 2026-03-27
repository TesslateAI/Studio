"""
GitHub Pages deployment provider.

Deploys static sites to GitHub Pages using the Git Data API. Files are pushed
as blobs/trees/commits to a branch (default: gh-pages), then Pages is enabled.
"""

import base64
import logging
import re

import httpx

from ..base import (
    ENV_BRANCH,
    ENV_REPO_URL,
    BaseDeploymentProvider,
    DeploymentConfig,
    DeploymentFile,
    DeploymentResult,
)
from .utils import poll_until_terminal

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"

TERMINAL_STATES = {"built", "errored"}


class GitHubPagesProvider(BaseDeploymentProvider):
    """
    GitHub Pages deployment provider.

    Deploys static files by pushing them to a GitHub repository branch via
    the Git Data API, then enabling GitHub Pages on that branch.
    """

    def validate_credentials(self) -> None:
        """Validate required GitHub credentials."""
        if not self.credentials.get("token"):
            raise ValueError("Missing required GitHub credential: token")

    def _get_headers(self) -> dict[str, str]:
        """Build auth headers for GitHub API."""
        return {
            "Authorization": f"Bearer {self.credentials['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _parse_repo_url(self, url: str) -> tuple[str, str]:
        """Extract owner and repo from a GitHub URL (HTTPS or SSH)."""
        match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$", url)
        if match:
            return match.group("owner"), match.group("repo")
        raise ValueError(f"Cannot parse GitHub repo from URL: {url}")

    async def test_credentials(self) -> dict:
        """Test GitHub credentials by querying the authenticated user."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{API_BASE}/user", headers=self._get_headers())
                resp.raise_for_status()
                user = resp.json()
                return {
                    "valid": True,
                    "account_name": user.get("login", "unknown"),
                    "user_id": user.get("id"),
                }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise ValueError("Invalid GitHub token") from exc
            raise ValueError(f"GitHub API error: {exc.response.status_code}") from exc
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Failed to validate GitHub credentials: {exc}") from exc

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """Deploy static files to GitHub Pages via the Git Data API."""
        logs: list[str] = []

        try:
            repo_url = config.env_vars.get(ENV_REPO_URL, "")
            branch = config.env_vars.get(ENV_BRANCH, "gh-pages")

            async with httpx.AsyncClient(timeout=120.0) as client:
                # Step 1 - Determine repo
                if repo_url:
                    owner, repo = self._parse_repo_url(repo_url)
                    logs.append(f"Using existing repo: {owner}/{repo}")
                else:
                    owner, repo = await self._create_repo(client, config.project_name, logs)

                repo_path = f"{owner}/{repo}"
                logs.append(f"Deploying {len(files)} files to {repo_path}@{branch}")

                # Step 2 - Create blobs
                logs.append("Creating file blobs...")
                tree_items: list[dict] = []
                for file in files:
                    blob_sha = await self._create_blob(client, repo_path, file.content)
                    normalized_path = file.path.replace("\\", "/")
                    tree_items.append({
                        "path": normalized_path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_sha,
                    })
                logs.append(f"Created {len(tree_items)} blob(s)")

                # Step 3 - Create tree
                logs.append("Creating tree...")
                tree_sha = await self._create_tree(client, repo_path, tree_items)

                # Step 4 - Get current commit (if branch exists)
                parent_sha = await self._get_branch_head(client, repo_path, branch)

                # Step 5 - Create commit
                logs.append("Creating commit...")
                parents = [parent_sha] if parent_sha else []
                commit_sha = await self._create_commit(
                    client,
                    repo_path,
                    tree_sha,
                    parents,
                    f"Deploy {config.project_name} via Tesslate",
                )

                # Step 6 - Update or create branch ref
                if parent_sha:
                    await self._update_ref(client, repo_path, branch, commit_sha)
                else:
                    await self._create_ref(client, repo_path, branch, commit_sha)
                logs.append(f"Branch '{branch}' updated to {commit_sha[:8]}")

                # Step 7 - Enable Pages
                await self._enable_pages(client, repo_path, branch, logs)

                # Step 8 - Poll build
                logs.append("Waiting for GitHub Pages build...")

                async def _check_build() -> dict:
                    r = await client.get(
                        f"{API_BASE}/repos/{repo_path}/pages/builds/latest",
                        headers=self._get_headers(),
                    )
                    if r.status_code == 404:
                        return {"status": "queued"}
                    r.raise_for_status()
                    return r.json()

                try:
                    final = await poll_until_terminal(
                        _check_build, TERMINAL_STATES, status_key="status", interval=5, timeout=300
                    )
                except TimeoutError:
                    final = {"status": "timeout"}

                final_status = final.get("status", "unknown")
                logs.append(f"Pages build status: {final_status}")

                deployment_url = f"https://{owner}.github.io/{repo}"
                success = final_status == "built"

                return DeploymentResult(
                    success=success,
                    deployment_id=repo_path,
                    deployment_url=deployment_url,
                    logs=logs,
                    error=None if success else f"Pages build status: {final_status}",
                    metadata={
                        "owner": owner,
                        "repo": repo,
                        "branch": branch,
                        "commit_sha": commit_sha,
                        "build_status": final_status,
                    },
                )

        except httpx.HTTPStatusError as exc:
            error_msg = f"GitHub API error: {exc.response.status_code} - {exc.response.text}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except (ValueError, TimeoutError) as exc:
            logs.append(str(exc))
            return DeploymentResult(success=False, error=str(exc), logs=logs)
        except Exception as exc:
            error_msg = f"GitHub Pages deployment failed: {exc}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    async def _create_repo(self, client: httpx.AsyncClient, name: str, logs: list[str]) -> tuple[str, str]:
        """Create a new GitHub repo for the authenticated user."""
        sanitized = self._sanitize_name(name)
        logs.append(f"Creating repository: {sanitized}")
        resp = await client.post(
            f"{API_BASE}/user/repos",
            headers=self._get_headers(),
            json={"name": sanitized, "auto_init": True},
        )
        resp.raise_for_status()
        repo_data = resp.json()
        return repo_data["owner"]["login"], repo_data["name"]

    async def _create_blob(self, client: httpx.AsyncClient, repo_path: str, content: bytes) -> str:
        """Create a blob in the repo and return its SHA."""
        resp = await client.post(
            f"{API_BASE}/repos/{repo_path}/git/blobs",
            headers=self._get_headers(),
            json={
                "content": base64.b64encode(content).decode("utf-8"),
                "encoding": "base64",
            },
        )
        resp.raise_for_status()
        return resp.json()["sha"]

    async def _create_tree(self, client: httpx.AsyncClient, repo_path: str, tree_items: list[dict]) -> str:
        """Create a tree from blob references and return its SHA."""
        resp = await client.post(
            f"{API_BASE}/repos/{repo_path}/git/trees",
            headers=self._get_headers(),
            json={"tree": tree_items},
        )
        resp.raise_for_status()
        return resp.json()["sha"]

    async def _get_branch_head(self, client: httpx.AsyncClient, repo_path: str, branch: str) -> str | None:
        """Get the HEAD commit SHA for a branch, or None if it doesn't exist.

        Uses the singular /git/ref/ endpoint which returns a single ref object
        (not an array), avoiding TypeError when parsing the response.
        """
        resp = await client.get(
            f"{API_BASE}/repos/{repo_path}/git/ref/heads/{branch}",
            headers=self._get_headers(),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        ref_obj = data.get("object")
        if not ref_obj or "sha" not in ref_obj:
            raise ValueError(
                f"Unexpected GitHub API response for branch '{branch}' in {repo_path}: "
                f"missing 'object.sha' in ref data"
            )
        return ref_obj["sha"]

    async def _create_commit(
        self,
        client: httpx.AsyncClient,
        repo_path: str,
        tree_sha: str,
        parents: list[str],
        message: str,
    ) -> str:
        """Create a commit and return its SHA."""
        resp = await client.post(
            f"{API_BASE}/repos/{repo_path}/git/commits",
            headers=self._get_headers(),
            json={"message": message, "tree": tree_sha, "parents": parents},
        )
        resp.raise_for_status()
        return resp.json()["sha"]

    async def _update_ref(
        self, client: httpx.AsyncClient, repo_path: str, branch: str, sha: str
    ) -> None:
        """Update an existing branch ref to a new commit SHA."""
        resp = await client.patch(
            f"{API_BASE}/repos/{repo_path}/git/refs/heads/{branch}",
            headers=self._get_headers(),
            json={"sha": sha},
        )
        resp.raise_for_status()

    async def _create_ref(
        self, client: httpx.AsyncClient, repo_path: str, branch: str, sha: str
    ) -> None:
        """Create a new branch ref pointing to a commit SHA."""
        resp = await client.post(
            f"{API_BASE}/repos/{repo_path}/git/refs",
            headers=self._get_headers(),
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        resp.raise_for_status()

    async def _enable_pages(
        self,
        client: httpx.AsyncClient,
        repo_path: str,
        branch: str,
        logs: list[str],
    ) -> None:
        """Enable GitHub Pages on the specified branch. Ignores 409 (already enabled)."""
        resp = await client.post(
            f"{API_BASE}/repos/{repo_path}/pages",
            headers=self._get_headers(),
            json={"source": {"branch": branch, "path": "/"}},
        )
        if resp.status_code == 409:
            logs.append("GitHub Pages already enabled")
            return
        if resp.status_code in {200, 201}:
            logs.append("GitHub Pages enabled")
            return
        resp.raise_for_status()

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """Get GitHub Pages status. deployment_id is 'owner/repo'."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/repos/{deployment_id}/pages",
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("Failed to get GitHub Pages status: %s", exc)
            return {"status": "unknown", "error": str(exc)}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """Disable GitHub Pages. deployment_id is 'owner/repo'."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    f"{API_BASE}/repos/{deployment_id}/pages",
                    headers=self._get_headers(),
                )
                return resp.status_code in {200, 204, 404}
        except Exception as exc:
            logger.error("Failed to disable GitHub Pages for %s: %s", deployment_id, exc)
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """Fetch GitHub Pages build history. deployment_id is 'owner/repo'."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/repos/{deployment_id}/pages/builds",
                    headers=self._get_headers(),
                    params={"per_page": 20},
                )
                resp.raise_for_status()
                builds = resp.json()
                return [
                    f"[{build.get('status', 'unknown')}] "
                    f"commit={build.get('commit', 'N/A')[:8]} "
                    f"created={build.get('created_at', 'N/A')} "
                    f"duration={build.get('duration', 'N/A')}s"
                    for build in builds
                ] or ["No builds found"]
        except Exception as exc:
            logger.error("Failed to fetch GitHub Pages builds: %s", exc)
            return [f"Error fetching builds: {exc}"]
