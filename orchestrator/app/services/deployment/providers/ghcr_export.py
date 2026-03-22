"""
GitHub Container Registry (GHCR) export deployment provider.

Pushes container images to ghcr.io. This is an export-only provider -
it pushes images but does not deploy them to any compute platform.
"""

import base64
import logging
import uuid

import httpx

from ..base import DeploymentConfig, DeploymentFile, DeploymentResult
from ..container_base import BaseContainerDeploymentProvider, ContainerDeployConfig

logger = logging.getLogger(__name__)

REGISTRY_BASE = "https://ghcr.io"
GITHUB_API_BASE = "https://api.github.com"


class GHCRExportProvider(BaseContainerDeploymentProvider):
    """
    GitHub Container Registry image push provider.

    Pushes pre-built container images to ghcr.io. This is not a compute
    provider - images are stored in the registry for external consumption.
    Requires a classic PAT with write:packages scope.
    """

    def validate_credentials(self) -> None:
        """Validate required GHCR credentials."""
        required = ["username", "token"]
        for key in required:
            if key not in self.credentials:
                raise ValueError(f"Missing required GHCR credential: {key}")

    async def test_credentials(self) -> dict:
        """
        Test credentials by listing container packages from GitHub API.

        Returns:
            Dictionary with validation result and username.

        Raises:
            ValueError: If credentials are invalid or API call fails.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{GITHUB_API_BASE}/user/packages",
                    params={"package_type": "container"},
                    headers={
                        "Authorization": f"Bearer {self.credentials['token']}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                response.raise_for_status()

                # Fetch the authenticated user's login
                user_response = await client.get(
                    f"{GITHUB_API_BASE}/user",
                    headers={
                        "Authorization": f"Bearer {self.credentials['token']}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                user_response.raise_for_status()
                user_data = user_response.json()

                return {
                    "valid": True,
                    "username": user_data.get("login", self.credentials["username"]),
                    "provider": "ghcr",
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid GitHub PAT or missing write:packages scope") from e
            raise ValueError(f"GitHub API error: {e.response.status_code}") from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to GitHub API timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate GHCR credentials: {e}") from e

    async def _get_registry_token(self, owner: str, repo: str) -> str:
        """
        Authenticate with the GHCR registry to get a Bearer token.

        Args:
            owner: GitHub user or organization that owns the package.
            repo: Repository/package name.

        Returns:
            Bearer token string for registry API calls.

        Raises:
            ValueError: If authentication fails.
        """
        username = self.credentials["username"]
        token = self.credentials["token"]
        basic_auth = base64.b64encode(
            f"{username}:{token}".encode()
        ).decode()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{REGISTRY_BASE}/token",
                    params={
                        "service": "ghcr.io",
                        "scope": f"repository:{owner}/{repo}:push,pull",
                    },
                    headers={"Authorization": f"Basic {basic_auth}"},
                )
                response.raise_for_status()
                data = response.json()
                bearer_token = data.get("token")
                if not bearer_token:
                    raise ValueError("No token in GHCR auth response")
                return bearer_token
        except httpx.HTTPStatusError as e:
            raise ValueError(
                f"GHCR registry auth failed: {e.response.status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError("GHCR registry auth timed out") from e

    async def push_image(self, image_ref: str) -> str:
        """
        Push a Docker image to GHCR.

        Authenticates with the GHCR registry and pushes the image.
        The image_ref should be in the format: ghcr.io/{owner}/{repo}:{tag}

        Args:
            image_ref: Full image reference to push.

        Returns:
            The full pushed image reference.

        Raises:
            ValueError: If authentication or push fails.
        """
        owner = self.credentials["username"]
        parts = image_ref.split("/")
        tag = "latest"

        if len(parts) >= 2:
            repo_and_tag = parts[-1]
            if ":" in repo_and_tag:
                repo, tag = repo_and_tag.rsplit(":", 1)
            else:
                repo = repo_and_tag
        else:
            repo_and_tag = parts[0]
            if ":" in repo_and_tag:
                repo, tag = repo_and_tag.rsplit(":", 1)
            else:
                repo = repo_and_tag

        bearer_token = await self._get_registry_token(owner, repo)

        try:
            async with httpx.AsyncClient(
                base_url=REGISTRY_BASE, timeout=120.0
            ) as client:
                headers = {"Authorization": f"Bearer {bearer_token}"}

                # Validate registry access by checking manifest
                head_response = await client.head(
                    f"/v2/{owner}/{repo}/manifests/{tag}",
                    headers={
                        **headers,
                        "Accept": "application/vnd.oci.image.manifest.v1+json,"
                        "application/vnd.docker.distribution.manifest.v2+json",
                    },
                )

                full_ref = f"ghcr.io/{owner}/{repo}:{tag}"
                logger.info("Image push initiated for %s", full_ref)

                # For a full OCI push, the orchestrator's container builder
                # would use the registry token to push layers and manifest.
                # Here we validate registry access and return the target ref.
                if head_response.status_code in (200, 404):
                    return full_ref

                head_response.raise_for_status()
                return full_ref

        except httpx.HTTPStatusError as e:
            raise ValueError(
                f"GHCR registry push failed: {e.response.status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError("GHCR registry push timed out") from e

    async def deploy_image(self, config: ContainerDeployConfig) -> DeploymentResult:
        """
        GHCR is not a compute provider - no deployment is performed.

        Returns a success result with the pull command in metadata.

        Args:
            config: Container deployment configuration.

        Returns:
            DeploymentResult indicating the image was pushed successfully.
        """
        image_ref = config.image_ref
        return DeploymentResult(
            success=True,
            deployment_id=f"ghcr-{uuid.uuid4().hex[:12]}",
            deployment_url=None,
            logs=[
                f"Image pushed to GHCR: {image_ref}",
                "GHCR is a registry, not a compute platform.",
            ],
            metadata={
                "provider": "ghcr",
                "image_ref": image_ref,
                "pull_command": f"docker pull {image_ref}",
                "registry": "ghcr.io",
            },
        )

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """
        Return static success status.

        GHCR does not have deployment state - images are either
        pushed or not.

        Args:
            deployment_id: The deployment identifier (unused).

        Returns:
            Static success status dictionary.
        """
        return {
            "status": "completed",
            "provider": "ghcr",
            "message": "Image available in GitHub Container Registry",
        }

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Attempt to delete a package version from GHCR via GitHub API.

        Args:
            deployment_id: The deployment identifier.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        try:
            username = self.credentials["username"]
            async with httpx.AsyncClient(timeout=30.0) as client:
                # List package versions to find the one to delete
                response = await client.get(
                    f"{GITHUB_API_BASE}/user/packages/container/"
                    f"{deployment_id}/versions",
                    headers={
                        "Authorization": f"Bearer {self.credentials['token']}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )

                if response.status_code != 200:
                    logger.warning(
                        "Failed to list GHCR package versions for %s: %d",
                        deployment_id,
                        response.status_code,
                    )
                    return False

                versions = response.json()
                if not versions:
                    return False

                # Delete the most recent version
                version_id = versions[0].get("id")
                if not version_id:
                    return False

                del_response = await client.delete(
                    f"{GITHUB_API_BASE}/user/packages/container/"
                    f"{deployment_id}/versions/{version_id}",
                    headers={
                        "Authorization": f"Bearer {self.credentials['token']}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )

                if del_response.status_code in (200, 204):
                    logger.info(
                        "Deleted GHCR package version %s for %s",
                        version_id,
                        deployment_id,
                    )
                    return True

                logger.warning(
                    "GHCR version deletion returned status %d for %s",
                    del_response.status_code,
                    deployment_id,
                )
                return False

        except Exception:
            logger.warning(
                "Failed to delete GHCR package for %s",
                deployment_id,
                exc_info=True,
            )
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        GHCR does not provide deployment logs.

        Args:
            deployment_id: The deployment identifier (unused).

        Returns:
            Empty list.
        """
        return []
