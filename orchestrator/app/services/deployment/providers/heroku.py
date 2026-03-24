"""
Heroku deployment provider.

This provider implements deployment to Heroku's platform using their Platform API.
It handles source tarball uploads, build creation, and deployment status polling.
"""

import logging

import httpx

from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentFile, DeploymentResult
from .utils import create_source_tarball, poll_until_terminal

logger = logging.getLogger(__name__)

API_BASE = "https://api.heroku.com"


class HerokuProvider(BaseDeploymentProvider):
    """
    Heroku deployment provider.

    Supports deploying applications to Heroku via the Platform API.
    Handles source tarball uploads, build creation, and provides deployment URLs.
    """

    def validate_credentials(self) -> None:
        """Validate required Heroku credentials."""
        if "api_key" not in self.credentials:
            raise ValueError("Missing required Heroku credential: api_key")

    def _get_headers(self) -> dict[str, str]:
        """Get headers for Heroku API requests."""
        return {
            "Authorization": f"Bearer {self.credentials['api_key']}",
            "Accept": "application/vnd.heroku+json; version=3",
            "Content-Type": "application/json",
        }

    async def test_credentials(self) -> dict:
        """
        Test if credentials are valid by fetching the Heroku account info.

        Returns:
            Dictionary with validation result and account email.

        Raises:
            ValueError: If credentials are invalid.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{API_BASE}/account",
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "valid": True,
                    "email": data.get("email"),
                    "id": data.get("id"),
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid Heroku API key") from e
            raise ValueError(f"Heroku API error: {e.response.status_code}") from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to Heroku API timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate credentials: {e}") from e

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Heroku.

        The deployment process:
        1. Create or get existing app
        2. Set environment variables
        3. Create source upload, upload tarball
        4. Create build from source
        5. Poll build status until terminal

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
                # Step 1: Create or get app
                app_id = await self._ensure_app(client, app_name, logs)

                # Step 2: Set env vars
                if config.env_vars:
                    await self._set_config_vars(client, app_name, config.env_vars, logs)

                # Step 3: Create source upload and upload tarball
                source_urls = await self._create_source(client, logs)
                put_url = source_urls["source_blob"]["put_url"]
                get_url = source_urls["source_blob"]["get_url"]

                tarball = create_source_tarball(files)
                logs.append(f"Uploading tarball ({len(tarball)} bytes)...")

                upload_resp = await client.put(
                    put_url,
                    content=tarball,
                    headers={"Content-Type": "application/gzip"},
                )
                upload_resp.raise_for_status()
                logs.append("Tarball uploaded successfully")

                # Step 4: Create build
                build_data = await self._create_build(client, app_name, get_url, logs)
                build_id = build_data["id"]

                # Step 5: Poll build status
                logs.append(f"Polling build {build_id}...")
                final_build = await poll_until_terminal(
                    check_fn=lambda: self._get_build(client, app_name, build_id),
                    terminal_states={"succeeded", "failed"},
                    status_key="status",
                    interval=5,
                    timeout=600,
                )

                build_status = final_build.get("status", "unknown")
                output_url = final_build.get("output_stream_url")

                if build_status == "succeeded":
                    deployment_url = f"https://{app_name}.herokuapp.com"
                    logs.append(f"Build succeeded. App live at {deployment_url}")
                    return DeploymentResult(
                        success=True,
                        deployment_id=app_name,
                        deployment_url=deployment_url,
                        logs=logs,
                        metadata={
                            "app_id": app_id,
                            "build_id": build_id,
                            "output_stream_url": output_url,
                        },
                    )

                logs.append(f"Build failed with status: {build_status}")
                return DeploymentResult(
                    success=False,
                    deployment_id=app_name,
                    error=f"Heroku build {build_status}",
                    logs=logs,
                    metadata={"build_id": build_id, "output_stream_url": output_url},
                )

        except TimeoutError as e:
            logs.append(str(e))
            return DeploymentResult(
                success=False,
                deployment_id=app_name,
                error="Build polling timed out",
                logs=logs,
            )
        except httpx.HTTPStatusError as e:
            error_msg = f"Heroku API error: {e.response.status_code} - {e.response.text}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except Exception as e:
            error_msg = f"Deployment failed: {e}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    async def _ensure_app(
        self, client: httpx.AsyncClient, app_name: str, logs: list[str]
    ) -> str:
        """Create a Heroku app or return the existing one's id."""
        logs.append(f"Creating Heroku app '{app_name}'...")
        resp = await client.post(
            f"{API_BASE}/apps",
            headers=self._get_headers(),
            json={"name": app_name},
        )

        if resp.status_code == 409:
            logs.append(f"App '{app_name}' already exists, reusing")
            get_resp = await client.get(
                f"{API_BASE}/apps/{app_name}",
                headers=self._get_headers(),
            )
            get_resp.raise_for_status()
            return get_resp.json()["id"]

        resp.raise_for_status()
        data = resp.json()
        logs.append(f"App created: {data['id']}")
        return data["id"]

    async def _set_config_vars(
        self,
        client: httpx.AsyncClient,
        app_name: str,
        env_vars: dict[str, str],
        logs: list[str],
    ) -> None:
        """Set environment variables on the Heroku app."""
        logs.append(f"Setting {len(env_vars)} config vars...")
        resp = await client.patch(
            f"{API_BASE}/apps/{app_name}/config-vars",
            headers=self._get_headers(),
            json=env_vars,
        )
        resp.raise_for_status()
        logs.append("Config vars updated")

    async def _create_source(
        self, client: httpx.AsyncClient, logs: list[str]
    ) -> dict:
        """Create a source upload endpoint and return URLs."""
        logs.append("Creating source upload...")
        resp = await client.post(
            f"{API_BASE}/sources",
            headers=self._get_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def _create_build(
        self,
        client: httpx.AsyncClient,
        app_name: str,
        source_url: str,
        logs: list[str],
    ) -> dict:
        """Create a build from the uploaded source."""
        logs.append("Creating build...")
        resp = await client.post(
            f"{API_BASE}/apps/{app_name}/builds",
            headers=self._get_headers(),
            json={"source_blob": {"url": source_url}},
        )
        resp.raise_for_status()
        data = resp.json()
        logs.append(f"Build created: {data['id']}")
        return data

    async def _get_build(
        self, client: httpx.AsyncClient, app_name: str, build_id: str
    ) -> dict:
        """Fetch the current build status."""
        resp = await client.get(
            f"{API_BASE}/apps/{app_name}/builds/{build_id}",
            headers=self._get_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """
        Get app status from Heroku.

        Args:
            deployment_id: Heroku app name

        Returns:
            App status data
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/apps/{deployment_id}",
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
        Delete a Heroku app.

        Args:
            deployment_id: Heroku app name

        Returns:
            True if deletion was successful
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    f"{API_BASE}/apps/{deployment_id}",
                    headers=self._get_headers(),
                )
                return resp.status_code in (200, 204)
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch recent logs from a Heroku app via a log session.

        Args:
            deployment_id: Heroku app name

        Returns:
            List of log lines
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                session_resp = await client.post(
                    f"{API_BASE}/apps/{deployment_id}/log-sessions",
                    headers=self._get_headers(),
                    json={"lines": 100, "source": "app"},
                )
                session_resp.raise_for_status()
                logplex_url = session_resp.json().get("logplex_url")

                if not logplex_url:
                    return ["No logplex URL returned"]

                log_resp = await client.get(logplex_url, timeout=15.0)
                if log_resp.status_code == 200:
                    lines = log_resp.text.strip().splitlines()
                    return lines if lines else ["No logs available"]
                return [f"Failed to fetch logs: HTTP {log_resp.status_code}"]
        except Exception as e:
            return [f"Error fetching logs: {e}"]
