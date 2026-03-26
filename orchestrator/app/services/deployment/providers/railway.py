"""
Railway deployment provider.

Deploys applications to Railway via their GraphQL API. Requires a git repository
as the deployment source - Railway builds directly from the repo.
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
from .utils import graphql_request, poll_until_terminal

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://backboard.railway.app/graphql/v2"

TERMINAL_STATES = {"SUCCESS", "FAILED", "CRASHED", "REMOVED"}


class RailwayProvider(BaseDeploymentProvider):
    """
    Railway deployment provider.

    Deploys applications by linking a git repository to a Railway service.
    Railway builds and runs the application from the repo source.
    """

    def validate_credentials(self) -> None:
        """Validate required Railway credentials."""
        if not self.credentials.get("token"):
            raise ValueError("Missing required Railway credential: token")

    def _get_headers(self) -> dict[str, str]:
        """Build auth headers for Railway API."""
        return {
            "Authorization": f"Bearer {self.credentials['token']}",
            "Content-Type": "application/json",
        }

    async def _gql(self, client: httpx.AsyncClient, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL request against Railway's API."""
        return await graphql_request(client, GRAPHQL_URL, query, variables, self._get_headers())

    async def test_credentials(self) -> dict:
        """
        Test Railway credentials by querying the authenticated user.

        Returns:
            Dictionary with valid flag and account_name.

        Raises:
            ValueError: If credentials are invalid.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                data = await self._gql(client, "query { me { id email } }")
                me = data.get("me", {})
                return {
                    "valid": True,
                    "account_name": me.get("email", "unknown"),
                    "user_id": me.get("id"),
                }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise ValueError("Invalid Railway token") from exc
            raise ValueError(f"Railway API error: {exc.response.status_code}") from exc
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Failed to validate Railway credentials: {exc}") from exc

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Railway by linking a git repository.

        The flow:
        1. Extract repo URL and branch from config env vars.
        2. Create (or reuse) a Railway project.
        3. Create a service linked to the repo.
        4. Upsert environment variables.
        5. Trigger a deployment and poll until terminal.

        Args:
            files: Unused for Railway (builds from git repo).
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
            logs.append(f"Deploying '{project_name}' to Railway from {repo_url}@{branch}")

            async with httpx.AsyncClient(timeout=120.0) as client:
                # Step 1 - Create project
                logs.append("Creating Railway project...")
                project_data = await self._gql(
                    client,
                    """
                    mutation($name: String!) {
                        projectCreate(input: { name: $name }) {
                            id
                            name
                        }
                    }
                    """,
                    {"name": project_name},
                )
                project_id = project_data["projectCreate"]["id"]
                logs.append(f"Project created: {project_id}")

                # Step 2 - Create service linked to repo
                logs.append("Creating service linked to repository...")
                service_data = await self._gql(
                    client,
                    """
                    mutation($projectId: String!, $repo: String!, $branch: String!) {
                        serviceCreate(input: {
                            projectId: $projectId,
                            name: "web",
                            source: { repo: $repo, branch: $branch }
                        }) {
                            id
                            name
                        }
                    }
                    """,
                    {"projectId": project_id, "repo": repo_url, "branch": branch},
                )
                service_id = service_data["serviceCreate"]["id"]
                logs.append(f"Service created: {service_id}")

                # Step 3 - Set environment variables (filter out internal keys)
                public_vars = {
                    k: v
                    for k, v in config.env_vars.items()
                    if not k.startswith(INTERNAL_ENV_PREFIX)
                }
                if public_vars:
                    logs.append(f"Setting {len(public_vars)} environment variable(s)...")
                    await self._gql(
                        client,
                        """
                        mutation($input: VariableCollectionUpsertInput!) {
                            variableCollectionUpsert(input: $input)
                        }
                        """,
                        {
                            "input": {
                                "projectId": project_id,
                                "serviceId": service_id,
                                "variables": public_vars,
                            }
                        },
                    )

                # Step 4 - Trigger deploy
                logs.append("Triggering deployment...")
                trigger_data = await self._gql(
                    client,
                    """
                    mutation($serviceId: String!) {
                        deploymentTriggerCreate(input: { serviceId: $serviceId }) {
                            id
                        }
                    }
                    """,
                    {"serviceId": service_id},
                )
                trigger_id = trigger_data["deploymentTriggerCreate"]["id"]
                logs.append(f"Deploy trigger created: {trigger_id}")

                # Step 5 - Fetch first deployment and poll
                logs.append("Waiting for deployment to start...")
                deploy_list = await self._gql(
                    client,
                    """
                    query($serviceId: String!) {
                        deployments(input: { serviceId: $serviceId }, first: 1) {
                            edges { node { id status } }
                        }
                    }
                    """,
                    {"serviceId": service_id},
                )

                edges = deploy_list.get("deployments", {}).get("edges", [])
                if not edges:
                    raise ValueError("No deployment created after trigger")

                deployment_id = edges[0]["node"]["id"]
                logs.append(f"Deployment started: {deployment_id}")

                # Poll until terminal
                async def _check_status() -> dict:
                    data = await self._gql(
                        client,
                        """
                        query($id: String!) {
                            deployment(id: $id) { id status }
                        }
                        """,
                        {"id": deployment_id},
                    )
                    return data.get("deployment", {})

                final = await poll_until_terminal(
                    _check_status, TERMINAL_STATES, status_key="status", interval=5, timeout=600
                )
                final_status = final.get("status", "UNKNOWN")
                logs.append(f"Deployment finished with status: {final_status}")

                success = final_status == "SUCCESS"
                return DeploymentResult(
                    success=success,
                    deployment_id=deployment_id,
                    deployment_url=f"https://{project_name}.up.railway.app",
                    logs=logs,
                    error=None if success else f"Deployment ended with status: {final_status}",
                    metadata={
                        "project_id": project_id,
                        "service_id": service_id,
                        "status": final_status,
                    },
                )

        except httpx.HTTPStatusError as exc:
            error_msg = f"Railway API error: {exc.response.status_code} - {exc.response.text}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except (ValueError, TimeoutError) as exc:
            logs.append(str(exc))
            return DeploymentResult(success=False, error=str(exc), logs=logs)
        except Exception as exc:
            error_msg = f"Railway deployment failed: {exc}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """
        Query deployment status from Railway.

        Args:
            deployment_id: Railway deployment ID.

        Returns:
            Dictionary with deployment status information.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                data = await self._gql(
                    client,
                    """
                    query($id: String!) {
                        deployment(id: $id) { id status createdAt updatedAt }
                    }
                    """,
                    {"id": deployment_id},
                )
                return data.get("deployment", {})
        except Exception as exc:
            logger.error("Failed to get Railway deployment status: %s", exc)
            return {"status": "UNKNOWN", "error": str(exc)}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Delete a Railway project (and all its deployments).

        Args:
            deployment_id: Railway project ID to delete.

        Returns:
            True if deletion succeeded.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await self._gql(
                    client,
                    """
                    mutation($id: String!) {
                        projectDelete(id: $id)
                    }
                    """,
                    {"id": deployment_id},
                )
                return True
        except Exception as exc:
            logger.error("Failed to delete Railway project %s: %s", deployment_id, exc)
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch deployment logs from Railway.

        Args:
            deployment_id: Railway deployment ID.

        Returns:
            List of log messages.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                data = await self._gql(
                    client,
                    """
                    query($id: String!) {
                        deploymentLogs(deploymentId: $id, limit: 200) {
                            message
                            timestamp
                            severity
                        }
                    }
                    """,
                    {"id": deployment_id},
                )
                log_entries = data.get("deploymentLogs", [])
                return [
                    f"[{entry.get('severity', 'INFO')}] {entry.get('message', '')}"
                    for entry in log_entries
                ] or ["No logs available"]
        except Exception as exc:
            logger.error("Failed to fetch Railway deployment logs: %s", exc)
            return [f"Error fetching logs: {exc}"]
