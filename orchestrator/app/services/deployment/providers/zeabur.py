"""
Zeabur deployment provider.

This provider implements deployment to Zeabur's platform using their GraphQL API
and REST upload endpoints. It handles project/service creation, ZIP uploads, and
deployment status polling.
"""

import hashlib
import logging

import httpx

from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentFile, DeploymentResult
from .utils import create_source_zip, graphql_request, poll_until_terminal

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://gateway.zeabur.com/graphql"
REST_BASE = "https://api.zeabur.com/v2"


class ZeaburProvider(BaseDeploymentProvider):
    """
    Zeabur deployment provider.

    Supports deploying applications to Zeabur's platform via GraphQL and REST APIs.
    Handles project/service creation, ZIP uploads, and deployment status polling.
    """

    def validate_credentials(self) -> None:
        """Validate required Zeabur credentials."""
        if "api_key" not in self.credentials:
            raise ValueError("Missing required Zeabur credential: api_key")

    def _get_headers(self) -> dict[str, str]:
        """Get headers for Zeabur API requests."""
        return {
            "Authorization": f"Bearer {self.credentials['api_key']}",
            "Content-Type": "application/json",
        }

    async def test_credentials(self) -> dict:
        """Test if credentials are valid by querying the Zeabur user profile."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                data = await graphql_request(
                    client,
                    GRAPHQL_URL,
                    "query { me { _id username } }",
                    headers=self._get_headers(),
                )
                me = data.get("me", {})
                return {
                    "valid": True,
                    "user_id": me.get("_id"),
                    "username": me.get("username"),
                }
        except ValueError as e:
            raise ValueError(f"Zeabur credential validation failed: {e}") from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid Zeabur API key") from e
            raise ValueError(f"Zeabur API error: {e.response.status_code}") from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to Zeabur API timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate credentials: {e}") from e

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """Deploy to Zeabur via GraphQL project/service creation and REST ZIP upload."""
        logs: list[str] = []
        project_name = self._sanitize_name(config.project_name)

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                headers = self._get_headers()

                # Step 1: Create project
                project_id = await self._create_project(
                    client, project_name, headers, logs
                )

                # Step 2: Create service
                service_id = await self._create_service(
                    client, project_id, project_name, headers, logs
                )

                # Step 3: Upload ZIP
                zip_bytes = create_source_zip(files)
                logs.append(f"Uploading ZIP archive ({len(zip_bytes)} bytes)...")
                await self._upload_archive(
                    client, service_id, zip_bytes, headers, logs
                )

                # Step 4: Set env vars if provided
                if config.env_vars:
                    await self._set_env_vars(
                        client, service_id, config.env_vars, headers, logs
                    )

                # Step 5: Poll deployment
                logs.append("Polling deployment status...")
                final = await poll_until_terminal(
                    check_fn=lambda: self._check_deployment(
                        client, service_id, headers
                    ),
                    terminal_states={"RUNNING", "ERROR", "FAILED", "STOPPED"},
                    status_key="status",
                    interval=10,
                    timeout=600,
                )

                status = final.get("status", "unknown")
                if status == "RUNNING":
                    domain = final.get("domain", f"{project_name}.zeabur.app")
                    deployment_url = f"https://{domain}"
                    logs.append(f"Deployment running at {deployment_url}")
                    return DeploymentResult(
                        success=True,
                        deployment_id=service_id,
                        deployment_url=deployment_url,
                        logs=logs,
                        metadata={
                            "project_id": project_id,
                            "service_id": service_id,
                        },
                    )

                logs.append(f"Deployment entered status: {status}")
                return DeploymentResult(
                    success=False,
                    deployment_id=service_id,
                    error=f"Zeabur deployment status: {status}",
                    logs=logs,
                    metadata={"project_id": project_id, "service_id": service_id},
                )

        except TimeoutError as e:
            logs.append(str(e))
            return DeploymentResult(
                success=False, error="Deployment polling timed out", logs=logs
            )
        except httpx.HTTPStatusError as e:
            error_msg = f"Zeabur API error: {e.response.status_code} - {e.response.text}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except Exception as e:
            error_msg = f"Deployment failed: {e}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    async def _create_project(
        self,
        client: httpx.AsyncClient,
        name: str,
        headers: dict[str, str],
        logs: list[str],
    ) -> str:
        """Create a Zeabur project and return its ID."""
        mutation = """
        mutation CreateProject($name: String!) {
            createProject(name: $name) {
                _id
                name
            }
        }
        """
        logs.append(f"Creating Zeabur project '{name}'...")
        data = await graphql_request(
            client, GRAPHQL_URL, mutation, {"name": name}, headers
        )
        project_id = data["createProject"]["_id"]
        logs.append(f"Project created: {project_id}")
        return project_id

    async def _create_service(
        self,
        client: httpx.AsyncClient,
        project_id: str,
        name: str,
        headers: dict[str, str],
        logs: list[str],
    ) -> str:
        """Create a Zeabur service inside a project and return its ID."""
        mutation = """
        mutation CreateService($projectID: ObjectID!, $name: String!) {
            createService(projectID: $projectID, template: CODE, name: $name) {
                _id
                name
            }
        }
        """
        logs.append("Creating Zeabur service...")
        data = await graphql_request(
            client,
            GRAPHQL_URL,
            mutation,
            {"projectID": project_id, "name": name},
            headers,
        )
        service_id = data["createService"]["_id"]
        logs.append(f"Service created: {service_id}")
        return service_id

    async def _upload_archive(
        self,
        client: httpx.AsyncClient,
        service_id: str,
        zip_bytes: bytes,
        headers: dict[str, str],
        logs: list[str],
    ) -> None:
        """Upload a ZIP archive for a service via the REST upload flow."""
        file_hash = hashlib.sha256(zip_bytes).hexdigest()

        # Initiate upload
        init_resp = await client.post(
            f"{REST_BASE}/upload",
            headers=headers,
            json={
                "serviceID": service_id,
                "hash": file_hash,
                "size": len(zip_bytes),
            },
        )
        init_resp.raise_for_status()
        upload_data = init_resp.json()

        upload_url = upload_data.get("presignedURL") or upload_data.get("url")
        upload_id = upload_data.get("id", "")

        if upload_url:
            put_resp = await client.put(
                upload_url,
                content=zip_bytes,
                headers={"Content-Type": "application/zip"},
            )
            put_resp.raise_for_status()
            logs.append("Archive uploaded to presigned URL")

        # Finalize upload
        prepare_resp = await client.post(
            f"{REST_BASE}/upload/{upload_id}/prepare",
            headers=headers,
        )
        prepare_resp.raise_for_status()
        logs.append("Upload finalized")

    async def _set_env_vars(
        self,
        client: httpx.AsyncClient,
        service_id: str,
        env_vars: dict[str, str],
        headers: dict[str, str],
        logs: list[str],
    ) -> None:
        """Set environment variables on a Zeabur service."""
        mutation = """
        mutation UpdateEnvironmentVariable(
            $serviceID: ObjectID!,
            $key: String!,
            $value: String!
        ) {
            updateEnvironmentVariable(
                serviceID: $serviceID,
                data: { key: $key, value: $value }
            )
        }
        """
        for key, value in env_vars.items():
            await graphql_request(
                client,
                GRAPHQL_URL,
                mutation,
                {"serviceID": service_id, "key": key, "value": value},
                headers,
            )
        logs.append(f"Set {len(env_vars)} environment variables")

    async def _check_deployment(
        self,
        client: httpx.AsyncClient,
        service_id: str,
        headers: dict[str, str],
    ) -> dict:
        """Check the deployment status of a service."""
        query = """
        query GetService($serviceID: ObjectID!) {
            service(_id: $serviceID) {
                _id
                status
                deployments {
                    _id
                    status
                }
                domains {
                    domain
                }
            }
        }
        """
        data = await graphql_request(
            client, GRAPHQL_URL, query, {"serviceID": service_id}, headers
        )
        service = data.get("service", {})
        domains = service.get("domains", [])
        domain = domains[0]["domain"] if domains else None
        return {
            "status": service.get("status", "UNKNOWN"),
            "domain": domain,
            "service": service,
        }

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """Get service status from Zeabur by service ID."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await self._check_deployment(
                    client, deployment_id, self._get_headers()
                )
        except Exception as e:
            return {"error": str(e), "status": "unknown"}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a Zeabur service by service ID."""
        mutation = """
        mutation DeleteService($serviceID: ObjectID!) {
            deleteService(_id: $serviceID)
        }
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await graphql_request(
                    client,
                    GRAPHQL_URL,
                    mutation,
                    {"serviceID": deployment_id},
                    self._get_headers(),
                )
                return True
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """Fetch deployment logs from Zeabur by service ID."""
        query = """
        query GetServiceLogs($serviceID: ObjectID!) {
            service(_id: $serviceID) {
                deployments(limit: 1) {
                    _id
                    logs {
                        message
                        timestamp
                    }
                }
            }
        }
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                data = await graphql_request(
                    client,
                    GRAPHQL_URL,
                    query,
                    {"serviceID": deployment_id},
                    self._get_headers(),
                )
                service = data.get("service", {})
                deployments = service.get("deployments", [])
                if not deployments:
                    return ["No deployments found"]
                log_entries = deployments[0].get("logs", [])
                lines = [
                    entry.get("message", "")
                    for entry in log_entries
                    if entry.get("message")
                ]
                return lines if lines else ["No logs available"]
        except Exception as e:
            return [f"Error fetching logs: {e}"]
