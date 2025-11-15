"""
Vercel deployment provider.

This provider implements deployment to Vercel's platform using their REST API.
It handles file uploads, build triggering, and deployment status polling.
"""

from typing import List, Dict, Optional
import httpx
import asyncio
import base64
from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentResult, DeploymentFile


class VercelProvider(BaseDeploymentProvider):
    """
    Vercel deployment provider.

    Supports deploying applications to Vercel with automatic build and deployment.
    Handles file uploads, build process, and provides deployment URLs.
    """

    API_BASE = "https://api.vercel.com"

    def validate_credentials(self) -> None:
        """Validate required Vercel credentials."""
        if "token" not in self.credentials:
            raise ValueError("Missing required Vercel credential: token")

    async def deploy(
        self,
        files: List[DeploymentFile],
        config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Vercel.

        The deployment process:
        1. Prepare files payload with base64 encoding
        2. Create deployment via API
        3. Poll for build completion
        4. Return deployment URL

        Args:
            files: List of files to deploy
            config: Deployment configuration

        Returns:
            DeploymentResult with deployment information
        """
        logs = []

        try:
            project_name = self._sanitize_name(config.project_name)
            logs.append(f"Deploying to Vercel as '{project_name}'")

            # Step 1: Prepare deployment payload
            logs.append(f"Preparing {len(files)} files for upload...")
            files_payload = []
            for file in files:
                # Normalize path
                normalized_path = file.path.replace('\\', '/')

                files_payload.append({
                    "file": normalized_path,
                    "data": base64.b64encode(file.content).decode('utf-8'),
                    "encoding": "base64"
                })

            # Step 2: Create deployment
            logs.append("Creating deployment...")
            framework_config = self.get_framework_config(config.framework)

            deployment_data = {
                "name": project_name,
                "files": files_payload,
                "projectSettings": {
                    "framework": self._map_framework(config.framework),
                    "buildCommand": config.build_command or framework_config.get("build_command"),
                    "devCommand": config.start_command or framework_config.get("dev_command"),
                    "outputDirectory": framework_config.get("output_dir", "dist")
                },
                "target": "production"
            }

            # Add environment variables if provided
            if config.env_vars:
                deployment_data["env"] = [
                    {"key": k, "value": v}
                    for k, v in config.env_vars.items()
                ]

            # Add team if specified
            team_id = self.credentials.get("team_id")
            url = f"{self.API_BASE}/v13/deployments"
            params = {}
            if team_id:
                params["teamId"] = team_id

            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    params=params,
                    json=deployment_data
                )
                response.raise_for_status()
                result = response.json()

            deployment_id = result['id']
            deployment_url = f"https://{result['url']}"

            logs.append(f"Deployment created: {deployment_id}")

            # Step 3: Wait for build to complete
            logs.append("Building deployment...")
            status = await self._wait_for_deployment(deployment_id, logs)

            if status == "READY":
                logs.append(f"Deployment successful: {deployment_url}")
                return DeploymentResult(
                    success=True,
                    deployment_id=deployment_id,
                    deployment_url=deployment_url,
                    logs=logs,
                    metadata={
                        "vercel_deployment": result,
                        "team_id": team_id
                    }
                )
            else:
                # Fetch error logs
                error_logs = await self.get_deployment_logs(deployment_id)
                all_logs = logs + error_logs
                error_msg = f"Build failed with status: {status}"
                all_logs.append(error_msg)

                return DeploymentResult(
                    success=False,
                    error=error_msg,
                    logs=all_logs,
                    metadata={"deployment_id": deployment_id}
                )

        except httpx.HTTPStatusError as e:
            error_msg = f"Vercel API error: {e.response.status_code} - {e.response.text}"
            logs.append(error_msg)
            return DeploymentResult(
                success=False,
                error=error_msg,
                logs=logs
            )

        except Exception as e:
            error_msg = f"Deployment failed: {str(e)}"
            logs.append(error_msg)
            return DeploymentResult(
                success=False,
                error=error_msg,
                logs=logs
            )

    async def _wait_for_deployment(
        self,
        deployment_id: str,
        logs: List[str],
        max_wait: int = 600
    ) -> str:
        """
        Poll deployment status until ready or failed.

        Args:
            deployment_id: Vercel deployment ID
            logs: List to append progress logs to
            max_wait: Maximum wait time in seconds

        Returns:
            Final deployment state
        """
        start_time = asyncio.get_event_loop().time()
        poll_interval = 5  # Poll every 5 seconds

        while True:
            try:
                status_data = await self.get_deployment_status(deployment_id)
                state = status_data.get('readyState', 'UNKNOWN')

                # Terminal states
                if state in ['READY', 'ERROR', 'CANCELED']:
                    return state

                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > max_wait:
                    logs.append(f"Deployment timed out after {max_wait} seconds")
                    return 'TIMEOUT'

                # Log progress
                if state == 'BUILDING':
                    logs.append(f"Building... ({int(elapsed)}s elapsed)")

                # Wait before next poll
                await asyncio.sleep(poll_interval)

            except Exception as e:
                logs.append(f"Error polling status: {str(e)}")
                return 'ERROR'

    def _map_framework(self, framework: str) -> Optional[str]:
        """
        Map internal framework names to Vercel framework names.

        Args:
            framework: Internal framework identifier

        Returns:
            Vercel framework name or None
        """
        mapping = {
            "vite": "vite",
            "nextjs": "nextjs",
            "react": "create-react-app",
            "vue": "vue",
            "svelte": "svelte",
            "nuxt": "nuxtjs",
            "angular": "angular"
        }
        return mapping.get(framework.lower())

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Vercel API requests."""
        return {
            "Authorization": f"Bearer {self.credentials['token']}",
            "Content-Type": "application/json"
        }

    async def get_deployment_status(self, deployment_id: str) -> Dict:
        """
        Get deployment status from Vercel.

        Args:
            deployment_id: Vercel deployment ID

        Returns:
            Deployment status data
        """
        team_id = self.credentials.get("team_id")
        url = f"{self.API_BASE}/v13/deployments/{deployment_id}"
        params = {}
        if team_id:
            params["teamId"] = team_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers=self._get_headers(),
                params=params
            )
            response.raise_for_status()
            return response.json()

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Delete deployment from Vercel.

        Args:
            deployment_id: Vercel deployment ID

        Returns:
            True if deletion was successful
        """
        team_id = self.credentials.get("team_id")
        url = f"{self.API_BASE}/v13/deployments/{deployment_id}"
        params = {}
        if team_id:
            params["teamId"] = team_id

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    url,
                    headers=self._get_headers(),
                    params=params
                )
                return response.status_code == 200
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> List[str]:
        """
        Fetch build logs from Vercel.

        Args:
            deployment_id: Vercel deployment ID

        Returns:
            List of log messages
        """
        team_id = self.credentials.get("team_id")
        url = f"{self.API_BASE}/v2/deployments/{deployment_id}/events"
        params = {}
        if team_id:
            params["teamId"] = team_id

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers=self._get_headers(),
                    params=params
                )
                if response.status_code == 200:
                    events = response.json()
                    return [
                        f"[{event.get('type', 'INFO')}] {event.get('payload', {}).get('text', '')}"
                        for event in events
                        if event.get('payload', {}).get('text')
                    ]
                return []
        except Exception:
            return []
