"""
Deno Deploy deployment provider.

This provider implements deployment to Deno Deploy using their REST API.
It handles project creation, asset uploads (inline), and deployment status polling.
"""

import base64
import logging

import httpx

from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentFile, DeploymentResult
from .utils import poll_until_terminal

logger = logging.getLogger(__name__)

API_BASE = "https://api.deno.com/v1"


class DenoDeployProvider(BaseDeploymentProvider):
    """
    Deno Deploy deployment provider.

    Supports deploying applications to Deno Deploy with inline asset uploads.
    Handles project creation, deployment with assets, and status polling.
    """

    def validate_credentials(self) -> None:
        """Validate required Deno Deploy credentials."""
        required = ["token", "org_id"]
        missing = [k for k in required if k not in self.credentials]
        if missing:
            raise ValueError(
                f"Missing required Deno Deploy credential(s): {', '.join(missing)}"
            )

    def _get_headers(self) -> dict[str, str]:
        """Get headers for Deno Deploy API requests."""
        return {
            "Authorization": f"Bearer {self.credentials['token']}",
            "Content-Type": "application/json",
        }

    @property
    def _org_id(self) -> str:
        return self.credentials["org_id"]

    async def test_credentials(self) -> dict:
        """
        Test if credentials are valid by fetching the Deno Deploy organization.

        Returns:
            Dictionary with validation result and org info.

        Raises:
            ValueError: If credentials are invalid.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/organizations/{self._org_id}",
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "valid": True,
                    "org_id": data.get("id"),
                    "org_name": data.get("name"),
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid Deno Deploy token") from e
            if e.response.status_code == 404:
                raise ValueError(
                    f"Organization '{self._org_id}' not found"
                ) from e
            raise ValueError(
                f"Deno Deploy API error: {e.response.status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to Deno Deploy API timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate credentials: {e}") from e

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Deno Deploy.

        The deployment process:
        1. Create project in the organization
        2. Prepare inline assets from files
        3. Create deployment with assets
        4. Poll deployment status

        Args:
            files: List of files to deploy
            config: Deployment configuration

        Returns:
            DeploymentResult with deployment information
        """
        logs: list[str] = []
        project_name = self._sanitize_name(config.project_name)

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                # Step 1: Create project
                project_id = await self._ensure_project(
                    client, project_name, logs
                )

                # Step 2: Build assets dict
                assets = self._build_assets(files, logs)

                # Step 3: Determine entry point
                entry_point = self._find_entry_point(files)
                logs.append(f"Entry point: {entry_point}")

                # Step 4: Create deployment
                env_vars = dict(config.env_vars) if config.env_vars else {}

                deploy_payload = {
                    "entryPointUrl": entry_point,
                    "assets": assets,
                    "envVars": env_vars,
                }

                logs.append("Creating deployment...")
                resp = await client.post(
                    f"{API_BASE}/projects/{project_id}/deployments",
                    headers=self._get_headers(),
                    json=deploy_payload,
                )
                resp.raise_for_status()
                deploy_data = resp.json()
                deployment_id = deploy_data["id"]
                logs.append(f"Deployment created: {deployment_id}")

                # Step 5: Poll deployment status
                logs.append("Polling deployment status...")
                final = await poll_until_terminal(
                    check_fn=lambda: self._check_deployment(
                        client, project_id, deployment_id
                    ),
                    terminal_states={"success", "failed", "error"},
                    status_key="status",
                    interval=5,
                    timeout=300,
                )

                status = final.get("status", "unknown")
                domains = final.get("domains", [])
                primary_domain = domains[0] if domains else f"{project_name}.deno.dev"
                deployment_url = f"https://{primary_domain}"

                if status == "success":
                    logs.append(f"Deployment live at {deployment_url}")
                    return DeploymentResult(
                        success=True,
                        deployment_id=f"{project_id}/{deployment_id}",
                        deployment_url=deployment_url,
                        logs=logs,
                        metadata={
                            "project_id": project_id,
                            "deployment_id": deployment_id,
                            "domains": domains,
                        },
                    )

                logs.append(f"Deployment status: {status}")
                return DeploymentResult(
                    success=False,
                    deployment_id=f"{project_id}/{deployment_id}",
                    error=f"Deno Deploy deployment {status}",
                    logs=logs,
                    metadata={
                        "project_id": project_id,
                        "deployment_id": deployment_id,
                    },
                )

        except TimeoutError as e:
            logs.append(str(e))
            return DeploymentResult(
                success=False, error="Deployment polling timed out", logs=logs
            )
        except httpx.HTTPStatusError as e:
            error_msg = (
                f"Deno Deploy API error: {e.response.status_code} - {e.response.text}"
            )
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except Exception as e:
            error_msg = f"Deployment failed: {e}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    async def _ensure_project(
        self, client: httpx.AsyncClient, name: str, logs: list[str]
    ) -> str:
        """Create a Deno Deploy project or return existing one's ID."""
        logs.append(f"Creating Deno Deploy project '{name}'...")
        resp = await client.post(
            f"{API_BASE}/organizations/{self._org_id}/projects",
            headers=self._get_headers(),
            json={"name": name},
        )

        if resp.status_code == 409:
            logs.append(f"Project '{name}' already exists, fetching ID...")
            get_resp = await client.get(
                f"{API_BASE}/organizations/{self._org_id}/projects",
                headers=self._get_headers(),
                params={"q": name, "limit": "10"},
            )
            if get_resp.status_code == 200:
                for proj in get_resp.json():
                    if proj.get("name") == name:
                        logs.append(f"Found existing project: {proj['id']}")
                        return proj["id"]
            logs.append("Could not resolve project ID, falling back to name")
            return name

        resp.raise_for_status()
        data = resp.json()
        project_id = data.get("id", name)
        logs.append(f"Project created: {project_id}")
        return project_id

    def _build_assets(
        self, files: list[DeploymentFile], logs: list[str]
    ) -> dict[str, dict]:
        """
        Build the inline assets dictionary for the deployment payload.

        Text files are sent as plain content; binary files are base64-encoded.
        """
        assets: dict[str, dict] = {}
        for f in files:
            normalized = f.path.replace("\\", "/")
            key = normalized.lstrip("/")

            if self._is_text_file(normalized):
                try:
                    text = f.content.decode("utf-8")
                    assets[key] = {"kind": "file", "content": text, "encoding": "utf-8"}
                except UnicodeDecodeError:
                    encoded = base64.b64encode(f.content).decode("ascii")
                    assets[key] = {
                        "kind": "file",
                        "content": encoded,
                        "encoding": "base64",
                    }
            else:
                encoded = base64.b64encode(f.content).decode("ascii")
                assets[key] = {
                    "kind": "file",
                    "content": encoded,
                    "encoding": "base64",
                }

        logs.append(f"Prepared {len(assets)} assets")
        return assets

    @staticmethod
    def _is_text_file(path: str) -> bool:
        """Heuristic: return True if the file extension is a known text type."""
        text_extensions = {
            ".ts", ".tsx", ".js", ".jsx", ".json", ".html", ".css",
            ".md", ".txt", ".yaml", ".yml", ".toml", ".xml", ".svg",
            ".sh", ".bash", ".env", ".cfg", ".ini", ".py", ".rs",
        }
        return any(path.endswith(ext) for ext in text_extensions)

    @staticmethod
    def _find_entry_point(files: list[DeploymentFile]) -> str:
        """Pick the best entry-point file from the file list."""
        candidates = ["main.ts", "main.tsx", "mod.ts", "index.ts", "server.ts", "main.js", "index.js"]
        paths = {f.path.replace("\\", "/") for f in files}
        for candidate in candidates:
            if candidate in paths:
                return candidate
        # Fall back to first .ts or .js file
        for f in files:
            p = f.path.replace("\\", "/")
            if p.endswith((".ts", ".js")):
                return p
        return "main.ts"

    async def _check_deployment(
        self,
        client: httpx.AsyncClient,
        project_id: str,
        deployment_id: str,
    ) -> dict:
        """Check the status of a deployment."""
        resp = await client.get(
            f"{API_BASE}/projects/{project_id}/deployments/{deployment_id}",
            headers=self._get_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "status": data.get("status", "unknown"),
            "domains": data.get("domains", []),
            "deployment": data,
        }

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """
        Get deployment status from Deno Deploy.

        Args:
            deployment_id: String in format "project_id/deployment_id"

        Returns:
            Deployment status data
        """
        try:
            parts = deployment_id.split("/", 1)
            if len(parts) != 2:
                return {"error": "Invalid deployment_id format", "status": "unknown"}
            project_id, deploy_id = parts

            async with httpx.AsyncClient(timeout=30.0) as client:
                return await self._check_deployment(client, project_id, deploy_id)
        except Exception as e:
            return {"error": str(e), "status": "unknown"}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Delete a Deno Deploy project.

        Args:
            deployment_id: String in format "project_id/deployment_id"

        Returns:
            True if deletion was successful
        """
        try:
            parts = deployment_id.split("/", 1)
            project_id = parts[0]

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    f"{API_BASE}/projects/{project_id}",
                    headers=self._get_headers(),
                )
                return resp.status_code in (200, 204)
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch deployment logs from Deno Deploy.

        Args:
            deployment_id: String in format "project_id/deployment_id"

        Returns:
            List of log lines
        """
        try:
            parts = deployment_id.split("/", 1)
            if len(parts) != 2:
                return ["Invalid deployment_id format"]
            _project_id, deploy_id = parts

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{API_BASE}/deployments/{deploy_id}/app_logs",
                    headers=self._get_headers(),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    entries = data if isinstance(data, list) else data.get("logs", [])
                    lines = []
                    for entry in entries:
                        msg = entry.get("message") or entry.get("msg", "")
                        if msg:
                            lines.append(msg)
                    return lines if lines else ["No logs available"]
                return [f"Failed to fetch logs: HTTP {resp.status_code}"]
        except Exception as e:
            return [f"Error fetching logs: {e}"]
