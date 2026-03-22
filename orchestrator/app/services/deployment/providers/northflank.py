"""
Northflank deployment provider.

Deploys applications to Northflank via their REST API. Requires a git repository
as the deployment source - Northflank builds directly from the repo.
"""

import logging

import httpx

from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentFile, DeploymentResult
from .utils import poll_until_terminal

logger = logging.getLogger(__name__)

API_BASE = "https://api.northflank.com/v1"

TERMINAL_STATES = {"running", "errored", "completed"}


class NorthflankProvider(BaseDeploymentProvider):
    """
    Northflank deployment provider.

    Deploys applications by creating a Northflank project and combined service
    linked to a git repository. Northflank builds and runs from the repo source.
    """

    def validate_credentials(self) -> None:
        """Validate required Northflank credentials."""
        if not self.credentials.get("api_token"):
            raise ValueError("Missing required Northflank credential: api_token")

    def _get_headers(self) -> dict[str, str]:
        """Build auth headers for Northflank API."""
        return {
            "Authorization": f"Bearer {self.credentials['api_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def test_credentials(self) -> dict:
        """
        Test Northflank credentials by querying the authenticated user.

        Returns:
            Dictionary with valid flag and account info.

        Raises:
            ValueError: If credentials are invalid.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{API_BASE}/me", headers=self._get_headers())
                resp.raise_for_status()
                data = resp.json()
                user = data.get("data", data)
                return {
                    "valid": True,
                    "account_name": user.get("name", user.get("email", "unknown")),
                    "user_id": user.get("id"),
                }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise ValueError("Invalid Northflank API token") from exc
            raise ValueError(f"Northflank API error: {exc.response.status_code}") from exc
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Failed to validate Northflank credentials: {exc}") from exc

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Northflank by creating a project and combined service.

        The flow:
        1. Extract repo URL and branch from config env vars.
        2. Create a Northflank project.
        3. Create a combined service with git repo + build settings.
        4. Poll until the service reaches a running or errored state.

        Args:
            files: Unused for Northflank (builds from git repo).
            config: Deployment configuration with repo info in env_vars.

        Returns:
            DeploymentResult with deployment information.
        """
        logs: list[str] = []

        try:
            repo_url = config.env_vars.get("_TESSLATE_REPO_URL", "")
            branch = config.env_vars.get("_TESSLATE_BRANCH", "main")

            if not repo_url:
                raise ValueError(
                    "Northflank requires a git repository. "
                    "Set _TESSLATE_REPO_URL in config.env_vars."
                )

            project_name = self._sanitize_name(config.project_name)
            framework_config = self.get_framework_config(config.framework)
            logs.append(f"Deploying '{project_name}' to Northflank from {repo_url}@{branch}")

            # Build runtime env vars (excluding internal keys)
            runtime_vars = {
                k: v
                for k, v in config.env_vars.items()
                if not k.startswith("_TESSLATE_")
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                # Step 1 - Create project
                logs.append("Creating Northflank project...")
                proj_resp = await client.post(
                    f"{API_BASE}/projects",
                    headers=self._get_headers(),
                    json={
                        "name": project_name,
                        "description": f"Tesslate deployment: {config.project_name}",
                    },
                )
                proj_resp.raise_for_status()
                proj_body = proj_resp.json()
                project_data = proj_body.get("data", proj_body)
                nf_project_id = project_data["id"]
                logs.append(f"Project created: {nf_project_id}")

                # Step 2 - Create combined service
                logs.append("Creating combined service...")
                build_cmd = config.build_command or framework_config.get("build_command", "npm run build")
                start_cmd = config.start_command or "npm start"

                service_payload: dict = {
                    "name": "web",
                    "billing": {"deploymentPlan": "nf-compute-10"},
                    "vcsData": {
                        "projectUrl": repo_url,
                        "projectType": "github",
                        "projectBranch": branch,
                    },
                    "buildConfiguration": {
                        "buildCmd": build_cmd,
                    },
                    "ports": [
                        {
                            "name": "http",
                            "internalPort": 3000,
                            "public": True,
                            "protocol": "HTTP",
                        }
                    ],
                    "runtimeEnvironment": runtime_vars,
                }

                svc_resp = await client.post(
                    f"{API_BASE}/projects/{nf_project_id}/services/combined",
                    headers=self._get_headers(),
                    json=service_payload,
                )
                svc_resp.raise_for_status()
                svc_body = svc_resp.json()
                service_data = svc_body.get("data", svc_body)
                service_id = service_data["id"]
                logs.append(f"Service created: {service_id}")

                # Step 3 - Poll until running or errored
                logs.append("Waiting for build and deployment...")
                composite_id = f"{nf_project_id}/{service_id}"

                async def _check_status() -> dict:
                    r = await client.get(
                        f"{API_BASE}/projects/{nf_project_id}/services/{service_id}",
                        headers=self._get_headers(),
                    )
                    r.raise_for_status()
                    body = r.json()
                    svc = body.get("data", body)
                    return {
                        "status": svc.get("status", svc.get("deployment", {}).get("status", "unknown")),
                        "raw": svc,
                    }

                final = await poll_until_terminal(
                    _check_status, TERMINAL_STATES, status_key="status", interval=10, timeout=600
                )
                final_status = final.get("status", "unknown")
                logs.append(f"Service status: {final_status}")

                # Extract URL from service data
                raw = final.get("raw", {})
                ports_data = raw.get("ports", [])
                deployment_url = ""
                for port in ports_data:
                    dns = port.get("dns", "")
                    if dns:
                        deployment_url = f"https://{dns}"
                        break

                success = final_status == "running"
                return DeploymentResult(
                    success=success,
                    deployment_id=composite_id,
                    deployment_url=deployment_url or None,
                    logs=logs,
                    error=None if success else f"Service ended with status: {final_status}",
                    metadata={
                        "project_id": nf_project_id,
                        "service_id": service_id,
                        "status": final_status,
                    },
                )

        except httpx.HTTPStatusError as exc:
            error_msg = f"Northflank API error: {exc.response.status_code} - {exc.response.text}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except (ValueError, TimeoutError) as exc:
            logs.append(str(exc))
            return DeploymentResult(success=False, error=str(exc), logs=logs)
        except Exception as exc:
            error_msg = f"Northflank deployment failed: {exc}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    def _parse_composite_id(self, deployment_id: str) -> tuple[str, str]:
        """
        Parse a composite deployment ID into project_id and service_id.

        Args:
            deployment_id: Format: "project_id/service_id"

        Returns:
            Tuple of (project_id, service_id).

        Raises:
            ValueError: If the format is invalid.
        """
        parts = deployment_id.split("/", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid Northflank deployment ID format: '{deployment_id}'. "
                "Expected 'project_id/service_id'."
            )
        return parts[0], parts[1]

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """
        Get service status from Northflank.

        Args:
            deployment_id: Composite ID in format "project_id/service_id".

        Returns:
            Dictionary with service status information.
        """
        try:
            project_id, service_id = self._parse_composite_id(deployment_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/projects/{project_id}/services/{service_id}",
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                body = resp.json()
                return body.get("data", body)
        except ValueError:
            raise
        except Exception as exc:
            logger.error("Failed to get Northflank service status: %s", exc)
            return {"status": "unknown", "error": str(exc)}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Delete a Northflank service.

        Args:
            deployment_id: Composite ID in format "project_id/service_id".

        Returns:
            True if deletion succeeded.
        """
        try:
            project_id, service_id = self._parse_composite_id(deployment_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    f"{API_BASE}/projects/{project_id}/services/{service_id}",
                    headers=self._get_headers(),
                )
                return resp.status_code in {200, 204}
        except Exception as exc:
            logger.error("Failed to delete Northflank service %s: %s", deployment_id, exc)
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch service logs from Northflank.

        Args:
            deployment_id: Composite ID in format "project_id/service_id".

        Returns:
            List of log messages.
        """
        try:
            project_id, service_id = self._parse_composite_id(deployment_id)
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/projects/{project_id}/services/{service_id}/logs",
                    headers=self._get_headers(),
                    params={"limit": 200},
                )
                resp.raise_for_status()
                body = resp.json()
                log_data = body.get("data", body)
                if isinstance(log_data, dict):
                    entries = log_data.get("logs", [])
                elif isinstance(log_data, list):
                    entries = log_data
                else:
                    return ["No logs available"]
                return [
                    entry.get("message", str(entry)) if isinstance(entry, dict) else str(entry)
                    for entry in entries
                ] or ["No logs available"]
        except Exception as exc:
            logger.error("Failed to fetch Northflank logs: %s", exc)
            return [f"Error fetching logs: {exc}"]
