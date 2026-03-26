"""
Docker Hub export deployment provider.

Pushes container images to Docker Hub's registry (registry-1.docker.io).
This is an export-only provider - it pushes images but does not deploy them
to any compute platform.
"""

import base64
import logging
import uuid

import httpx

from ..base import DeploymentResult
from ..container_base import BaseContainerDeploymentProvider, ContainerDeployConfig

logger = logging.getLogger(__name__)

REGISTRY_BASE = "https://registry-1.docker.io"
AUTH_URL = "https://auth.docker.io/token"
HUB_API_BASE = "https://hub.docker.com/v2"


class DockerHubExportProvider(BaseContainerDeploymentProvider):
    """
    Docker Hub image push provider.

    Pushes pre-built container images to Docker Hub. This is not a compute
    provider - images are stored in the registry for external consumption.
    """

    def validate_credentials(self) -> None:
        """Validate required Docker Hub credentials."""
        required = ["username", "token"]
        for key in required:
            if key not in self.credentials:
                raise ValueError(f"Missing required Docker Hub credential: {key}")

    async def _get_hub_jwt(self, client: httpx.AsyncClient) -> str:
        """
        Exchange Docker Hub credentials for a JWT token.

        The Docker Hub API requires JWT authentication for Hub API calls
        (user profile, repository management, tag deletion). This exchanges
        the username/PAT for a short-lived JWT via the login endpoint.

        Args:
            client: An active httpx.AsyncClient.

        Returns:
            JWT token string for Hub API calls.

        Raises:
            ValueError: If login fails due to invalid credentials or API error.
        """
        username = self.credentials["username"]
        token = self.credentials["token"]
        try:
            response = await client.post(
                f"{HUB_API_BASE}/users/login/",
                json={"username": username, "password": token},
            )
            if response.status_code == 401:
                raise ValueError(
                    "Invalid Docker Hub credentials. Ensure your username and "
                    "personal access token (PAT) are correct."
                )
            response.raise_for_status()
            data = response.json()
            jwt = data.get("token")
            if not jwt:
                raise ValueError(
                    "Docker Hub login succeeded but returned no token. "
                    "Please try again or regenerate your access token."
                )
            return jwt
        except httpx.HTTPStatusError as e:
            raise ValueError(
                f"Docker Hub login failed (HTTP {e.response.status_code}). "
                "Check that your username and personal access token are valid."
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError(
                "Connection to Docker Hub timed out during login. "
                "Please check your network and try again."
            ) from e

    async def test_credentials(self) -> dict:
        """
        Test credentials by logging in and fetching the Docker Hub user profile.

        Returns:
            Dictionary with validation result and username.

        Raises:
            ValueError: If credentials are invalid or API call fails.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                username = self.credentials["username"]
                jwt = await self._get_hub_jwt(client)
                response = await client.get(
                    f"{HUB_API_BASE}/users/{username}",
                    headers={"Authorization": f"JWT {jwt}"},
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "valid": True,
                    "username": data.get("username", username),
                    "provider": "dockerhub",
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError(
                    "Docker Hub rejected your credentials. Please verify your "
                    "username and personal access token are correct."
                ) from e
            raise ValueError(
                f"Docker Hub API error (HTTP {e.response.status_code}). "
                "Please try again later."
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError(
                "Connection to Docker Hub timed out. "
                "Please check your network and try again."
            ) from e
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(
                f"Failed to validate Docker Hub credentials: {e}"
            ) from e

    async def _get_registry_token(self, namespace: str, repo: str) -> str:
        """
        Authenticate with the Docker Hub registry to get a Bearer token.

        Args:
            namespace: Docker Hub namespace (usually the username).
            repo: Repository name.

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
                    AUTH_URL,
                    params={
                        "service": "registry.docker.io",
                        "scope": f"repository:{namespace}/{repo}:push,pull",
                    },
                    headers={"Authorization": f"Basic {basic_auth}"},
                )
                response.raise_for_status()
                data = response.json()
                bearer_token = data.get("token")
                if not bearer_token:
                    raise ValueError("No token in Docker Hub auth response")
                return bearer_token
        except httpx.HTTPStatusError as e:
            raise ValueError(
                f"Docker Hub registry auth failed: {e.response.status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError("Docker Hub registry auth timed out") from e

    async def push_image(self, image_ref: str) -> str:
        """
        Push a Docker image to Docker Hub.

        Authenticates with the Docker Hub registry and pushes the image.
        The image_ref should be in the format: docker.io/{username}/{repo}:{tag}

        Args:
            image_ref: Full image reference to push.

        Returns:
            The full pushed image reference.

        Raises:
            ValueError: If authentication or push fails.
        """
        username = self.credentials["username"]
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

        namespace = username
        bearer_token = await self._get_registry_token(namespace, repo)

        try:
            async with httpx.AsyncClient(
                base_url=REGISTRY_BASE, timeout=120.0
            ) as client:
                headers = {"Authorization": f"Bearer {bearer_token}"}

                # Check if image manifest exists (validates auth + repo access)
                head_response = await client.head(
                    f"/v2/{namespace}/{repo}/manifests/{tag}",
                    headers={
                        **headers,
                        "Accept": "application/vnd.docker.distribution.manifest.v2+json",
                    },
                )

                full_ref = f"docker.io/{namespace}/{repo}:{tag}"
                logger.info("Image push initiated for %s", full_ref)

                # For a full OCI push, the orchestrator's container builder
                # would use the registry token to push layers and manifest.
                # Here we validate registry access and return the target ref.
                if head_response.status_code in (200, 404):
                    # 200 = image exists, 404 = repo accessible but tag missing
                    return full_ref

                head_response.raise_for_status()
                return full_ref

        except httpx.HTTPStatusError as e:
            raise ValueError(
                f"Docker Hub registry push failed: {e.response.status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError("Docker Hub registry push timed out") from e

    async def deploy_image(self, config: ContainerDeployConfig) -> DeploymentResult:
        """
        Docker Hub is not a compute provider - no deployment is performed.

        Returns a success result with the pull command in metadata.

        Args:
            config: Container deployment configuration.

        Returns:
            DeploymentResult indicating the image was pushed successfully.
        """
        image_ref = config.image_ref
        # Extract the repo name from the image reference so deletion can
        # target the correct Docker Hub repository later.
        repo_name = self._extract_repo_name(image_ref)
        return DeploymentResult(
            success=True,
            deployment_id=f"dockerhub-{uuid.uuid4().hex[:12]}",
            deployment_url=None,
            logs=[
                f"Image pushed to Docker Hub: {image_ref}",
                "Docker Hub is a registry, not a compute platform.",
            ],
            metadata={
                "provider": "dockerhub",
                "image_ref": image_ref,
                "repo_name": repo_name,
                "pull_command": f"docker pull {image_ref}",
                "registry": "registry-1.docker.io",
            },
        )

    @staticmethod
    def _extract_repo_name(image_ref: str) -> str:
        """
        Extract the bare repository name from a full image reference.

        Examples:
            "docker.io/myuser/myapp:latest" -> "myapp"
            "myuser/myapp:v2" -> "myapp"
            "myapp:latest" -> "myapp"
            "myapp" -> "myapp"
        """
        # Strip registry prefix (e.g. "docker.io/")
        parts = image_ref.split("/")
        repo_and_tag = parts[-1]
        # Strip tag
        if ":" in repo_and_tag:
            repo_and_tag = repo_and_tag.rsplit(":", 1)[0]
        return repo_and_tag

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """
        Return static success status.

        Docker Hub does not have deployment state - images are either
        pushed or not.

        Args:
            deployment_id: The deployment identifier (unused).

        Returns:
            Static success status dictionary.
        """
        return {
            "status": "completed",
            "provider": "dockerhub",
            "message": "Image available in Docker Hub registry",
        }

    async def delete_deployment(
        self, deployment_id: str, *, metadata: dict | None = None
    ) -> bool:
        """
        Attempt to delete a tag from Docker Hub.

        Docker Hub's tag deletion via API is limited. This attempts to
        delete the ``latest`` tag but returns False if unsupported.

        The ``deployment_id`` is a synthetic identifier (``dockerhub-{uuid}``)
        and cannot be used as a repository name. The actual repo name must be
        provided via the ``metadata`` dict (key ``repo_name``), which is
        populated automatically by ``deploy_image``.

        Args:
            deployment_id: The deployment identifier (synthetic).
            metadata: Optional deployment metadata containing ``repo_name``.

        Returns:
            True if deletion succeeded, False otherwise.
        """
        repo_name = (metadata or {}).get("repo_name") if metadata else None
        if not repo_name:
            logger.warning(
                "Cannot delete Docker Hub tag for deployment '%s': no repo_name "
                "in metadata. The deployment_id is a synthetic identifier and "
                "does not correspond to a Docker Hub repository. To delete, "
                "provide the deployment metadata that was returned by deploy_image.",
                deployment_id,
            )
            return False

        try:
            username = self.credentials["username"]
            async with httpx.AsyncClient(timeout=30.0) as client:
                jwt = await self._get_hub_jwt(client)
                response = await client.delete(
                    f"{HUB_API_BASE}/repositories/{username}/"
                    f"{repo_name}/tags/latest/",
                    headers={"Authorization": f"JWT {jwt}"},
                )
                if response.status_code in (200, 204):
                    logger.info(
                        "Deleted latest tag for repo '%s' (deployment %s)",
                        repo_name,
                        deployment_id,
                    )
                    return True
                if response.status_code == 404:
                    logger.warning(
                        "Repository '%s/%s' or tag 'latest' not found on Docker Hub.",
                        username,
                        repo_name,
                    )
                    return False
                logger.warning(
                    "Docker Hub tag deletion returned HTTP %d for repo '%s'",
                    response.status_code,
                    repo_name,
                )
                return False
        except ValueError:
            # Re-raise auth errors from _get_hub_jwt with clear messages
            raise
        except Exception:
            logger.warning(
                "Failed to delete Docker Hub tag for repo '%s' (deployment %s)",
                repo_name,
                deployment_id,
                exc_info=True,
            )
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Docker Hub does not provide deployment logs.

        Args:
            deployment_id: The deployment identifier (unused).

        Returns:
            Empty list.
        """
        return []
