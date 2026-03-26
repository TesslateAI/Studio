"""
Render deployment provider.

Deploys applications to Render via their REST API. Requires a git repository
as the deployment source - Render builds directly from the repo.
"""

import logging

import httpx

from ..base import (
    ENV_BRANCH,
    ENV_REPO_URL,
    INTERNAL_ENV_PREFIX,
    NO_GIT_REPO_ERROR,
    BaseDeploymentProvider,
    DeploymentConfig,
    DeploymentFile,
    DeploymentResult,
)
from .utils import poll_until_terminal

logger = logging.getLogger(__name__)

API_BASE = "https://api.render.com/v1"

TERMINAL_STATES = {"live", "deactivated", "build_failed", "update_failed", "canceled"}


class RenderProvider(BaseDeploymentProvider):
    """
    Render deployment provider.

    Deploys applications by creating a Render web service linked to a git repo.
    Render auto-deploys on service creation and builds from the repo source.
    """

    def validate_credentials(self) -> None:
        """Validate required Render credentials."""
        if not self.credentials.get("api_key"):
            raise ValueError("Missing required Render credential: api_key")

    def _get_headers(self) -> dict[str, str]:
        """Build auth headers for Render API."""
        return {
            "Authorization": f"Bearer {self.credentials['api_key']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def test_credentials(self) -> dict:
        """
        Test Render credentials by listing account owners.

        Returns:
            Dictionary with valid flag and account_name.

        Raises:
            ValueError: If credentials are invalid.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/owners",
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                owners = resp.json()
                first_owner = owners[0] if owners else {}
                owner_data = first_owner.get("owner", first_owner)
                return {
                    "valid": True,
                    "account_name": owner_data.get("name", owner_data.get("email", "unknown")),
                    "owner_id": owner_data.get("id"),
                }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise ValueError("Invalid Render API key") from exc
            raise ValueError(f"Render API error: {exc.response.status_code}") from exc
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Failed to validate Render credentials: {exc}") from exc

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Render by creating a web service linked to a git repo.

        The flow:
        1. Extract repo URL and branch from config env vars.
        2. Create a Render web service with the repo.
        3. Render auto-deploys on creation; fetch the initial deploy.
        4. Poll until the deploy reaches a terminal state.

        Args:
            files: Unused for Render (builds from git repo).
            config: Deployment configuration with repo info in env_vars.

        Returns:
            DeploymentResult with deployment information.
        """
        logs: list[str] = []

        try:
            repo_url = config.env_vars.get(ENV_REPO_URL, "")
            branch = config.env_vars.get(ENV_BRANCH, "main")

            if not repo_url:
                raise ValueError(NO_GIT_REPO_ERROR)

            project_name = self._sanitize_name(config.project_name)
            framework_config = self.get_framework_config(config.framework)
            logs.append(f"Deploying '{project_name}' to Render from {repo_url}@{branch}")

            # Build env var list (excluding internal keys)
            env_vars_payload = [
                {"key": k, "value": v}
                for k, v in config.env_vars.items()
                if not k.startswith(INTERNAL_ENV_PREFIX)
            ]

            # Map frameworks to Render runtime identifiers
            runtime_map = {
                "nextjs": "node",
                "vite": "node",
                "react": "node",
                "vue": "node",
                "nuxt": "node",
                "svelte": "node",
                "python": "python",
                "flask": "python",
                "django": "python",
                "fastapi": "python",
                "go": "go",
                "rust": "rust",
                "ruby": "ruby",
                "elixir": "elixir",
            }
            runtime = runtime_map.get(config.framework, "node")
            if config.framework not in runtime_map:
                logger.warning(
                    "Unrecognized framework '%s' for Render deploy — defaulting to runtime='node' "
                    "with npm build/start commands. Set build_command/start_command in config to override.",
                    config.framework,
                )

            # Build/start commands for native runtime
            build_cmd = config.build_command or framework_config.get("build_command", "npm run build")
            start_cmd = config.start_command or framework_config.get("start_command", "npm start")

            service_payload = {
                "type": "web_service",
                "name": project_name,
                "repo": repo_url,
                "branch": branch,
                "autoDeploy": "yes",
                "envVars": env_vars_payload,
                "serviceDetails": {
                    "runtime": runtime,
                    "envSpecificDetails": {
                        "buildCommand": build_cmd,
                        "startCommand": start_cmd,
                    },
                },
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                # Step 0 - Resolve owner ID (required by Render API)
                owners_resp = await client.get(
                    f"{API_BASE}/owners",
                    headers=self._get_headers(),
                )
                owners_resp.raise_for_status()
                owners = owners_resp.json()
                if not owners:
                    raise ValueError("No Render account owner found — verify your API key permissions")
                first_owner = owners[0]
                owner_data = first_owner.get("owner", first_owner)
                owner_id = owner_data.get("id")
                if not owner_id:
                    raise ValueError("Could not resolve Render owner ID from API response")
                service_payload["ownerId"] = owner_id
                logs.append(f"Resolved Render owner: {owner_data.get('name', owner_id)}")

                # Step 1 - Create service
                logs.append("Creating Render web service...")
                resp = await client.post(
                    f"{API_BASE}/services",
                    headers=self._get_headers(),
                    json=service_payload,
                )
                resp.raise_for_status()
                service_data = resp.json()
                service = service_data.get("service", service_data)
                service_id = service["id"]
                logs.append(f"Service created: {service_id}")

                # Step 2 - Fetch initial deploy
                logs.append("Fetching initial deployment...")
                deploys_resp = await client.get(
                    f"{API_BASE}/services/{service_id}/deploys",
                    headers=self._get_headers(),
                    params={"limit": 1},
                )
                deploys_resp.raise_for_status()
                deploys = deploys_resp.json()

                if not deploys:
                    raise ValueError("No deploy created after service creation")

                deploy_entry = deploys[0]
                deploy_data = deploy_entry.get("deploy", deploy_entry)
                deploy_id = deploy_data["id"]
                logs.append(f"Deploy started: {deploy_id}")

                # Step 3 - Poll until terminal
                async def _check_status() -> dict:
                    r = await client.get(
                        f"{API_BASE}/services/{service_id}/deploys/{deploy_id}",
                        headers=self._get_headers(),
                    )
                    r.raise_for_status()
                    body = r.json()
                    return body.get("deploy", body) if isinstance(body, dict) else body

                final = await poll_until_terminal(
                    _check_status, TERMINAL_STATES, status_key="status", interval=5, timeout=600
                )
                final_status = final.get("status", "unknown")
                logs.append(f"Deploy finished with status: {final_status}")

                service_url = service.get("serviceDetails", {}).get("url", "")
                if not service_url:
                    service_url = f"https://{project_name}.onrender.com"

                success = final_status == "live"
                return DeploymentResult(
                    success=success,
                    deployment_id=service_id,
                    deployment_url=service_url,
                    logs=logs,
                    error=None if success else f"Deploy ended with status: {final_status}",
                    metadata={
                        "service_id": service_id,
                        "deploy_id": deploy_id,
                        "status": final_status,
                    },
                )

        except httpx.HTTPStatusError as exc:
            error_msg = f"Render API error: {exc.response.status_code} - {exc.response.text}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except (ValueError, TimeoutError) as exc:
            logs.append(str(exc))
            return DeploymentResult(success=False, error=str(exc), logs=logs)
        except Exception as exc:
            error_msg = f"Render deployment failed: {exc}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """
        Get service status from Render.

        Args:
            deployment_id: Render service ID.

        Returns:
            Dictionary with service status information.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/services/{deployment_id}",
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                body = resp.json()
                return body.get("service", body) if isinstance(body, dict) else body
        except Exception as exc:
            logger.error("Failed to get Render service status: %s", exc)
            return {"status": "unknown", "error": str(exc)}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Delete a Render service.

        Args:
            deployment_id: Render service ID.

        Returns:
            True if deletion succeeded.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    f"{API_BASE}/services/{deployment_id}",
                    headers=self._get_headers(),
                )
                return resp.status_code in {200, 204}
        except Exception as exc:
            logger.error("Failed to delete Render service %s: %s", deployment_id, exc)
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Render does not expose deployment logs via REST API.

        Args:
            deployment_id: Render service ID.

        Returns:
            Empty list (logs not available via REST).
        """
        return []
