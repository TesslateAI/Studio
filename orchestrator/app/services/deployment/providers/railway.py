"""
Railway deployment provider.

Deploys applications to Railway via their GraphQL API. Requires a git repository
as the deployment source - Railway builds directly from the repo.
"""

import logging
import re

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

# Pattern to extract owner/repo from various GitHub URL formats
_GITHUB_REPO_RE = re.compile(
    r"(?:https?://)?(?:[^@]+@)?github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?/?$"
)


def _parse_repo_slug(url: str) -> str:
    """Convert a full GitHub URL to the ``owner/repo`` slug Railway expects.

    Accepts:
      - https://github.com/owner/repo
      - https://github.com/owner/repo.git
      - https://token@github.com/owner/repo.git
      - git@github.com:owner/repo.git
      - owner/repo  (already a slug — returned as-is)

    Raises ValueError with a user-friendly message if the URL can't be parsed.
    """
    url = url.strip()

    # Already a slug like "owner/repo"
    if "/" in url and ":" not in url and "." not in url.split("/")[0]:
        return url

    m = _GITHUB_REPO_RE.match(url)
    if m:
        return f"{m.group('owner')}/{m.group('repo')}"

    raise ValueError(
        f"Railway requires a GitHub repository in 'owner/repo' format, "
        f"but got: {url!r}. Make sure the Git panel is connected to a GitHub repository."
    )


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

            # Railway expects "owner/repo" format, not a full URL
            repo_slug = _parse_repo_slug(repo_url)

            project_name = self._sanitize_name(config.project_name)
            logs.append(f"Deploying '{project_name}' to Railway from {repo_slug}@{branch}")

            async with httpx.AsyncClient(timeout=120.0) as client:
                # Step 1 - Create project
                logs.append("Creating Railway project...")
                try:
                    project_data = await self._gql(
                        client,
                        """
                        mutation($name: String!) {
                            projectCreate(input: { name: $name }) {
                                id
                                name
                                environments {
                                    edges { node { id name } }
                                }
                            }
                        }
                        """,
                        {"name": project_name},
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"Failed to create Railway project '{project_name}'. "
                        f"Check that your Railway token has project-create permissions. Detail: {exc}"
                    ) from exc
                project_id = project_data["projectCreate"]["id"]
                logs.append(f"Project created: {project_id}")

                # Step 2 - Resolve the default environment ID
                env_edges = (
                    project_data["projectCreate"]
                    .get("environments", {})
                    .get("edges", [])
                )
                if env_edges:
                    environment_id = env_edges[0]["node"]["id"]
                else:
                    # Fallback: query environments separately
                    logs.append("Fetching project environments...")
                    env_data = await self._gql(
                        client,
                        """
                        query($projectId: String!) {
                            environments(projectId: $projectId, isEphemeral: false) {
                                edges { node { id name } }
                            }
                        }
                        """,
                        {"projectId": project_id},
                    )
                    env_list = env_data.get("environments", {}).get("edges", [])
                    if not env_list:
                        raise ValueError(
                            "Railway created the project but it has no environments. "
                            "This is unexpected — try creating the project manually in the Railway dashboard."
                        )
                    environment_id = env_list[0]["node"]["id"]
                logs.append(f"Using environment: {environment_id}")

                # Step 3 - Create service, then connect repo
                logs.append("Creating Railway service...")
                try:
                    service_data = await self._gql(
                        client,
                        """
                        mutation($projectId: String!) {
                            serviceCreate(input: {
                                projectId: $projectId,
                                name: "web"
                            }) {
                                id
                                name
                            }
                        }
                        """,
                        {"projectId": project_id},
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"Failed to create Railway service in project '{project_name}'. "
                        f"Check that your Railway token has the required permissions. Detail: {exc}"
                    ) from exc
                service_id = service_data["serviceCreate"]["id"]
                logs.append(f"Service created: {service_id}")

                # Step 3b - Connect the repo to the service (triggers deploy automatically)
                logs.append(f"Connecting repository {repo_slug} (branch: {branch})...")
                try:
                    await self._gql(
                        client,
                        """
                        mutation($id: String!, $input: ServiceConnectInput!) {
                            serviceConnect(id: $id, input: $input) { id }
                        }
                        """,
                        {
                            "id": service_id,
                            "input": {"repo": repo_slug, "branch": branch},
                        },
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"Failed to link repository '{repo_slug}' to Railway service. "
                        f"Make sure Railway has access to this GitHub repo "
                        f"(check Railway dashboard → GitHub integration). Detail: {exc}"
                    ) from exc
                logs.append("Repository connected — deployment triggered automatically")

                # Step 4 - Set environment variables (filter out internal keys)
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
                                "environmentId": environment_id,
                                "variables": public_vars,
                            }
                        },
                    )

                # Step 5 - serviceConnect already triggers a deploy, but if
                # no deployment appears after polling we use serviceInstanceDeployV2
                # as a fallback trigger.

                # Step 6 - Fetch first deployment and poll
                logs.append("Waiting for deployment to start...")
                import asyncio as _asyncio

                deployment_id = None
                for _attempt in range(12):
                    deploy_list = await self._gql(
                        client,
                        """
                        query($projectId: String!) {
                            deployments(input: { projectId: $projectId }, first: 1) {
                                edges { node { id status } }
                            }
                        }
                        """,
                        {"projectId": project_id},
                    )
                    edges = deploy_list.get("deployments", {}).get("edges", [])
                    if edges:
                        deployment_id = edges[0]["node"]["id"]
                        break
                    await _asyncio.sleep(5)

                if not deployment_id:
                    # Fallback: explicitly trigger a deploy via serviceInstanceDeployV2
                    logs.append(
                        "No deployment detected from serviceConnect — "
                        "triggering deploy explicitly..."
                    )
                    try:
                        await self._gql(
                            client,
                            """
                            mutation($serviceId: String!, $environmentId: String!) {
                                serviceInstanceDeployV2(
                                    serviceId: $serviceId,
                                    environmentId: $environmentId
                                )
                            }
                            """,
                            {
                                "serviceId": service_id,
                                "environmentId": environment_id,
                            },
                        )
                    except ValueError as exc:
                        raise ValueError(
                            f"Failed to trigger Railway deployment. "
                            f"The project and service were created but the build could not start. "
                            f"Try deploying manually from the Railway dashboard. Detail: {exc}"
                        ) from exc

                    # Poll again for the deployment to appear
                    for _retry in range(12):
                        deploy_list = await self._gql(
                            client,
                            """
                            query($projectId: String!) {
                                deployments(input: { projectId: $projectId }, first: 1) {
                                    edges { node { id status } }
                                }
                            }
                            """,
                            {"projectId": project_id},
                        )
                        edges = deploy_list.get("deployments", {}).get("edges", [])
                        if edges:
                            deployment_id = edges[0]["node"]["id"]
                            break
                        await _asyncio.sleep(5)

                if not deployment_id:
                    raise ValueError(
                        "Railway accepted the deploy request but no deployment appeared after 120s. "
                        "This usually means the repository is empty or has no buildable content. "
                        "Check the Railway dashboard for more details."
                    )
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

                # Query the actual deployment URL from Railway
                deployment_url = None
                if success:
                    try:
                        domain_data = await self._gql(
                            client,
                            """
                            query($projectId: String!, $serviceId: String!, $environmentId: String!) {
                                domains(
                                    projectId: $projectId,
                                    serviceId: $serviceId,
                                    environmentId: $environmentId
                                ) {
                                    serviceDomains { domain }
                                    customDomains { domain }
                                }
                            }
                            """,
                            {
                                "projectId": project_id,
                                "serviceId": service_id,
                                "environmentId": environment_id,
                            },
                        )
                        domains_info = domain_data.get("domains", {})
                        # Prefer custom domains, fall back to service domains
                        custom = domains_info.get("customDomains", [])
                        service_domains = domains_info.get("serviceDomains", [])
                        if custom:
                            deployment_url = f"https://{custom[0]['domain']}"
                        elif service_domains:
                            deployment_url = f"https://{service_domains[0]['domain']}"
                    except Exception as exc:
                        logger.warning(
                            "Could not fetch Railway domain for service %s: %s",
                            service_id, exc,
                        )

                if not deployment_url:
                    deployment_url = f"https://railway.app/project/{project_id}"
                    if success:
                        logs.append(
                            "Could not determine the live URL automatically. "
                            "Check the Railway dashboard for your deployment's public domain."
                        )

                return DeploymentResult(
                    success=success,
                    deployment_id=deployment_id,
                    deployment_url=deployment_url,
                    logs=logs,
                    error=None if success else f"Deployment ended with status: {final_status}",
                    metadata={
                        "project_id": project_id,
                        "service_id": service_id,
                        "status": final_status,
                    },
                )

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text[:500]
            if status == 401:
                error_msg = (
                    "Railway rejected your API token (401 Unauthorized). "
                    "Go to Settings → Deployments and reconnect your Railway account."
                )
            elif status == 403:
                error_msg = (
                    "Railway denied access (403 Forbidden). "
                    "Your token may lack the required scopes — regenerate it in Railway dashboard."
                )
            else:
                error_msg = f"Railway API returned HTTP {status}: {body}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except (ValueError, TimeoutError) as exc:
            logs.append(str(exc))
            return DeploymentResult(success=False, error=str(exc), logs=logs)
        except Exception as exc:
            error_msg = f"Railway deployment failed unexpectedly: {exc}"
            logger.error(error_msg, exc_info=True)
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
