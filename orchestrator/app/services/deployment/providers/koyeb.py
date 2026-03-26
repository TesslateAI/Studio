"""
Koyeb deployment provider.

This provider implements deployment to Koyeb's serverless platform using their REST API.
It handles archive uploads, app/service creation, and deployment status polling.
"""

import logging

import httpx

from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentFile, DeploymentResult
from .utils import create_source_tarball, poll_until_terminal

logger = logging.getLogger(__name__)

API_BASE = "https://app.koyeb.com"


class KoyebProvider(BaseDeploymentProvider):
    """
    Koyeb deployment provider.

    Supports deploying applications to Koyeb's serverless platform.
    Handles archive uploads, app/service creation, and provides deployment URLs.
    """

    def validate_credentials(self) -> None:
        """Validate required Koyeb credentials."""
        if "api_token" not in self.credentials:
            raise ValueError("Missing required Koyeb credential: api_token")

    def _get_headers(self) -> dict[str, str]:
        """Get headers for Koyeb API requests."""
        return {
            "Authorization": f"Bearer {self.credentials['api_token']}",
            "Content-Type": "application/json",
        }

    async def test_credentials(self) -> dict:
        """
        Test if credentials are valid by fetching the Koyeb user profile.

        Returns:
            Dictionary with validation result and user info.

        Raises:
            ValueError: If credentials are invalid.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/v1/profile",
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "valid": True,
                    "user": data.get("user", {}),
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid Koyeb API token") from e
            raise ValueError(f"Koyeb API error: {e.response.status_code}") from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to Koyeb API timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate credentials: {e}") from e

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Koyeb.

        The deployment process:
        1. Upload archive via multipart form
        2. Create app
        3. Create service with archive source
        4. Poll deployment until ready

        Args:
            files: List of files to deploy
            config: Deployment configuration

        Returns:
            DeploymentResult with deployment information
        """
        logs: list[str] = []
        app_name = self._sanitize_name(config.project_name)

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                # Step 1: Upload archive
                tarball = create_source_tarball(files)
                logs.append(f"Uploading archive ({len(tarball)} bytes)...")

                archive_id = await self._upload_archive(client, tarball, logs)

                # Step 2: Create app
                app_id = await self._create_app(client, app_name, logs)

                # Step 3: Create service
                service_id = await self._create_service(
                    client, app_id, archive_id, config, logs
                )

                # Step 4: Poll deployment status
                logs.append("Waiting for deployment to become healthy...")
                final = await poll_until_terminal(
                    check_fn=lambda: self._check_service(client, service_id),
                    terminal_states={"HEALTHY", "ERRORING", "ERROR", "UNHEALTHY"},
                    status_key="status",
                    interval=10,
                    timeout=600,
                )

                status = final.get("status", "unknown")
                if status == "HEALTHY":
                    deployment_url = f"https://{app_name}.koyeb.app"
                    logs.append(f"Deployment healthy at {deployment_url}")
                    return DeploymentResult(
                        success=True,
                        deployment_id=app_id,
                        deployment_url=deployment_url,
                        logs=logs,
                        metadata={
                            "app_id": app_id,
                            "service_id": service_id,
                            "archive_id": archive_id,
                        },
                    )

                logs.append(f"Service entered status: {status}")
                return DeploymentResult(
                    success=False,
                    deployment_id=app_id,
                    error=f"Koyeb service status: {status}",
                    logs=logs,
                    metadata={"app_id": app_id, "service_id": service_id},
                )

        except TimeoutError as e:
            logs.append(str(e))
            return DeploymentResult(
                success=False,
                deployment_id=app_name,
                error="Deployment polling timed out",
                logs=logs,
            )
        except httpx.HTTPStatusError as e:
            error_msg = f"Koyeb API error: {e.response.status_code} - {e.response.text}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except Exception as e:
            error_msg = f"Deployment failed: {e}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    async def _upload_archive(
        self, client: httpx.AsyncClient, tarball: bytes, logs: list[str]
    ) -> str:
        """Upload a tarball archive to Koyeb and return the archive ID."""
        resp = await client.post(
            f"{API_BASE}/v1/archives",
            headers={"Authorization": f"Bearer {self.credentials['api_token']}"},
            files={"file": ("source.tar.gz", tarball, "application/gzip")},
        )
        resp.raise_for_status()
        data = resp.json()
        archive_id = data["archive"]["id"]
        logs.append(f"Archive uploaded: {archive_id}")
        return archive_id

    async def _create_app(
        self, client: httpx.AsyncClient, app_name: str, logs: list[str]
    ) -> str:
        """Create a Koyeb app and return its ID, or return existing app ID on conflict."""
        logs.append(f"Creating Koyeb app '{app_name}'...")
        resp = await client.post(
            f"{API_BASE}/v1/apps",
            headers=self._get_headers(),
            json={"name": app_name},
        )

        if resp.status_code == 409:
            logs.append(f"App '{app_name}' already exists, looking up...")
            list_resp = await client.get(
                f"{API_BASE}/v1/apps",
                headers=self._get_headers(),
                params={"name": app_name},
            )
            list_resp.raise_for_status()
            apps = list_resp.json().get("apps", [])
            for app in apps:
                if app.get("name") == app_name:
                    logs.append(f"Reusing app: {app['id']}")
                    return app["id"]
            raise ValueError(f"App '{app_name}' conflict but could not be found")

        resp.raise_for_status()
        data = resp.json()
        app_id = data["app"]["id"]
        logs.append(f"App created: {app_id}")
        return app_id

    async def _create_service(
        self,
        client: httpx.AsyncClient,
        app_id: str,
        archive_id: str,
        config: DeploymentConfig,
        logs: list[str],
    ) -> str:
        """Create a Koyeb service with archive source and return its ID."""
        port = 8000
        env_list = [
            {"key": k, "value": v, "scopes": ["region:was"]}
            for k, v in config.env_vars.items()
        ]

        service_payload = {
            "app_id": app_id,
            "definition": {
                "name": self._sanitize_name(config.project_name),
                "type": "WEB",
                "archive": {
                    "id": archive_id,
                    "buildpack": {
                        "build_command": config.build_command or "npm run build",
                        "run_command": config.start_command or "npm start",
                    },
                },
                "env": env_list,
                "ports": [
                    {
                        "port": port,
                        "protocol": "http",
                    }
                ],
                "routes": [{"path": "/", "port": port}],
                "regions": ["was"],
                "instance_types": [{"type": "nano"}],
                "scalings": [{"min": 1, "max": 1, "scopes": ["region:*"]}],
            },
        }

        logs.append("Creating Koyeb service...")
        resp = await client.post(
            f"{API_BASE}/v1/services",
            headers=self._get_headers(),
            json=service_payload,
        )
        resp.raise_for_status()
        data = resp.json()
        service_id = data["service"]["id"]
        logs.append(f"Service created: {service_id}")
        return service_id

    async def _check_service(self, client: httpx.AsyncClient, service_id: str) -> dict:
        """Check the current status of a service."""
        resp = await client.get(
            f"{API_BASE}/v1/services/{service_id}",
            headers=self._get_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        service = data.get("service", {})
        return {"status": service.get("status", "UNKNOWN"), "service": service}

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """
        Get service status from Koyeb.

        Args:
            deployment_id: Koyeb app ID (used to list services)

        Returns:
            Service status data
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/v1/apps/{deployment_id}",
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}", "status": "unknown"}
        except Exception as e:
            return {"error": str(e), "status": "unknown"}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Delete a Koyeb app and all its services.

        Args:
            deployment_id: Koyeb app ID

        Returns:
            True if deletion was successful
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    f"{API_BASE}/v1/apps/{deployment_id}",
                    headers=self._get_headers(),
                )
                return resp.status_code in (200, 204)
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch logs for services in a Koyeb app.

        Args:
            deployment_id: Koyeb app ID

        Returns:
            List of log lines
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # First list services for this app
                svc_resp = await client.get(
                    f"{API_BASE}/v1/services",
                    headers=self._get_headers(),
                    params={"app_id": deployment_id},
                )
                svc_resp.raise_for_status()
                services = svc_resp.json().get("services", [])

                if not services:
                    return ["No services found for this app"]

                service_id = services[0]["id"]
                log_resp = await client.get(
                    f"{API_BASE}/v1/streams/logs/tail",
                    headers=self._get_headers(),
                    params={
                        "service_id": service_id,
                        "type": "runtime",
                        "limit": "100",
                    },
                )
                if log_resp.status_code == 200:
                    data = log_resp.json()
                    lines = [
                        entry.get("msg", "")
                        for entry in data.get("logs", [])
                        if entry.get("msg")
                    ]
                    return lines if lines else ["No logs available"]
                return [f"Failed to fetch logs: HTTP {log_resp.status_code}"]
        except Exception as e:
            return [f"Error fetching logs: {e}"]
