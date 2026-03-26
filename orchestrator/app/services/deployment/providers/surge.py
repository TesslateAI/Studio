"""
Surge.sh deployment provider.

This provider implements deployment to Surge.sh, a simple static web publishing
platform. Deployments are synchronous -- the PUT request completes when the site
is live.
"""

import base64
import logging
from datetime import datetime, timezone

import httpx

from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentFile, DeploymentResult
from .utils import create_source_tarball

logger = logging.getLogger(__name__)

SURGE_BASE = "https://surge.surge.sh"


class SurgeProvider(BaseDeploymentProvider):
    """
    Surge.sh deployment provider.

    Supports deploying static sites to Surge.sh. Deployments are synchronous,
    so no polling is required. The PUT response indicates success or failure
    immediately.
    """

    def validate_credentials(self) -> None:
        """Validate required Surge.sh credentials."""
        required = ["email", "token"]
        missing = [k for k in required if k not in self.credentials]
        if missing:
            raise ValueError(
                f"Missing required Surge.sh credential(s): {', '.join(missing)}"
            )

    def _get_headers(self) -> dict[str, str]:
        """Get headers for Surge API requests using HTTP Basic auth."""
        credentials_b64 = base64.b64encode(
            f"{self.credentials['email']}:{self.credentials['token']}".encode()
        ).decode()
        return {
            "Authorization": f"Basic {credentials_b64}",
            "Content-Type": "application/octet-stream",
        }

    async def test_credentials(self) -> dict:
        """
        Test if credentials are valid by querying the Surge account endpoint.

        Returns:
            Dictionary with validation result and user email.

        Raises:
            ValueError: If credentials are invalid.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{SURGE_BASE}/account",
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                data = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                return {
                    "valid": True,
                    "email": data.get("email", self.credentials.get("email")),
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise ValueError(
                    "Invalid Surge.sh credentials -- check your email and token"
                ) from e
            raise ValueError(
                f"Surge API returned an unexpected error (HTTP {e.response.status_code})"
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError(
                "Connection to Surge.sh timed out -- please try again later"
            ) from e
        except Exception as e:
            raise ValueError(f"Failed to validate Surge.sh credentials: {e}") from e

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Surge.sh.

        The deployment is synchronous:
        1. Create tarball from files
        2. PUT tarball to the target domain
        3. Response completes when deploy is live

        Args:
            files: List of files to deploy
            config: Deployment configuration

        Returns:
            DeploymentResult with deployment information
        """
        logs: list[str] = []
        domain = f"{self._sanitize_name(config.project_name)}.surge.sh"

        try:
            tarball = create_source_tarball(files)
            logs.append(f"Deploying {len(files)} files to {domain}")
            logs.append(f"Tarball size: {len(tarball)} bytes")

            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.put(
                    f"{SURGE_BASE}/{domain}",
                    content=tarball,
                    headers={
                        **self._get_headers(),
                        "Content-Type": "application/x-tar",
                        "file-count": str(len(files)),
                        "project-size": str(len(tarball)),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

                if resp.status_code in (200, 201):
                    deployment_url = f"https://{domain}"
                    logs.append(f"Deployment successful: {deployment_url}")
                    return DeploymentResult(
                        success=True,
                        deployment_id=domain,
                        deployment_url=deployment_url,
                        logs=logs,
                        metadata={"domain": domain},
                    )

                error_text = resp.text[:500] if resp.text else "No response body"
                error_msg = f"Surge deploy returned HTTP {resp.status_code}: {error_text}"
                logs.append(error_msg)
                return DeploymentResult(
                    success=False,
                    deployment_id=domain,
                    error=error_msg,
                    logs=logs,
                )

        except httpx.HTTPStatusError as e:
            error_msg = f"Surge API error: {e.response.status_code} - {e.response.text}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except Exception as e:
            error_msg = f"Deployment failed: {e}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """
        Get deployment status for a Surge site.

        Surge deploys are synchronous, so a successful deploy means the site is live.

        Args:
            deployment_id: The surge.sh domain

        Returns:
            Static status dict
        """
        return {
            "status": "live",
            "domain": deployment_id,
            "url": f"https://{deployment_id}",
        }

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Tear down a Surge.sh site.

        Args:
            deployment_id: The surge.sh domain to delete

        Returns:
            True if deletion was successful
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    f"{SURGE_BASE}/{deployment_id}",
                    headers=self._get_headers(),
                )
                return resp.status_code in (200, 204)
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch deployment logs from Surge.sh.

        Surge does not provide a log retrieval API, so this always returns an
        empty list.

        Args:
            deployment_id: The surge.sh domain

        Returns:
            Empty list (logs not available)
        """
        return []
