"""
Netlify deployment provider.

This provider implements deployment to Netlify using their REST API.
It uses digest-based file uploads for efficient deployments.
"""

from typing import List, Dict, Optional
import httpx
import asyncio
import hashlib
import mimetypes
from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentResult, DeploymentFile


class NetlifyProvider(BaseDeploymentProvider):
    """
    Netlify deployment provider.

    Supports deploying applications to Netlify with automatic build and deployment.
    Uses digest-based uploads to only transfer files that Netlify doesn't already have.
    """

    API_BASE = "https://api.netlify.com/api/v1"

    def validate_credentials(self) -> None:
        """Validate required Netlify credentials."""
        if "token" not in self.credentials:
            raise ValueError("Missing required Netlify credential: token")

    async def deploy(
        self,
        files: List[DeploymentFile],
        config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Netlify.

        The deployment process:
        1. Get or create site
        2. Create deploy with file digests
        3. Upload only required files
        4. Wait for deploy to be ready
        5. Return deployment URL

        Args:
            files: List of files to deploy
            config: Deployment configuration

        Returns:
            DeploymentResult with deployment information
        """
        logs = []

        try:
            site_name = self._sanitize_name(config.project_name)
            logs.append(f"Deploying to Netlify as '{site_name}'")

            # Step 1: Get or create site
            logs.append("Setting up Netlify site...")
            site_id = await self._get_or_create_site(site_name)
            logs.append(f"Using site: {site_id}")

            # Step 2: Calculate file digests
            logs.append(f"Calculating digests for {len(files)} files...")
            file_digests = {}
            file_map = {}  # Map digest to file for upload
            for file in files:
                # Normalize path with leading slash
                normalized_path = file.path.replace('\\', '/')
                if not normalized_path.startswith('/'):
                    normalized_path = '/' + normalized_path

                # Calculate SHA1 digest (Netlify uses SHA1)
                digest = hashlib.sha1(file.content).hexdigest()
                file_digests[normalized_path] = digest
                file_map[digest] = file

            # Step 3: Create deploy
            logs.append("Creating deploy...")
            deploy_data = {"files": file_digests}

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.API_BASE}/sites/{site_id}/deploys",
                    headers=self._get_headers(),
                    json=deploy_data
                )
                response.raise_for_status()
                deploy = response.json()

            deploy_id = deploy['id']
            required_digests = deploy.get('required', [])
            deployment_url = deploy.get('ssl_url') or deploy.get('deploy_ssl_url')

            logs.append(f"Deploy created: {deploy_id}")

            # Step 4: Upload required files
            if required_digests:
                logs.append(f"Uploading {len(required_digests)} files...")
                await self._upload_files(deploy_id, file_map, required_digests)
                logs.append("File upload completed")
            else:
                logs.append("No files to upload (all cached)")

            # Step 5: Wait for deploy to be ready
            logs.append("Processing deployment...")
            state = await self._wait_for_deploy(deploy_id, logs)

            if state == 'ready':
                logs.append(f"Deployment successful: {deployment_url}")
                return DeploymentResult(
                    success=True,
                    deployment_id=deploy_id,
                    deployment_url=deployment_url,
                    logs=logs,
                    metadata={
                        "site_id": site_id,
                        "site_name": site_name,
                        "files_uploaded": len(required_digests),
                        "total_files": len(files)
                    }
                )
            else:
                error_msg = f"Deploy failed with state: {state}"
                logs.append(error_msg)
                return DeploymentResult(
                    success=False,
                    error=error_msg,
                    logs=logs,
                    metadata={"deploy_id": deploy_id}
                )

        except httpx.HTTPStatusError as e:
            error_msg = f"Netlify API error: {e.response.status_code} - {e.response.text}"
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

    async def _get_or_create_site(self, name: str) -> str:
        """
        Get existing site or create new one.

        Args:
            name: Site name

        Returns:
            Site ID
        """
        site_name = self._sanitize_name(name)

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Try to get existing sites
            response = await client.get(
                f"{self.API_BASE}/sites",
                headers=self._get_headers()
            )
            response.raise_for_status()
            sites = response.json()

            # Check if site with this name exists
            for site in sites:
                if site.get('name') == site_name:
                    return site['id']

            # Create new site
            # Try with the preferred name first, if it fails (422), let Netlify auto-generate
            try:
                response = await client.post(
                    f"{self.API_BASE}/sites",
                    headers=self._get_headers(),
                    json={"name": site_name}
                )
                response.raise_for_status()
                return response.json()['id']
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 422:
                    # Subdomain taken - let Netlify auto-generate a unique one
                    response = await client.post(
                        f"{self.API_BASE}/sites",
                        headers=self._get_headers(),
                        json={}  # No name = Netlify auto-generates subdomain
                    )
                    response.raise_for_status()
                    return response.json()['id']
                raise

    async def _upload_files(
        self,
        deploy_id: str,
        file_map: Dict[str, DeploymentFile],
        required_digests: List[str]
    ) -> None:
        """
        Upload required files to Netlify.

        Args:
            deploy_id: Deploy ID
            file_map: Mapping of digest to file
            required_digests: List of file digests that need to be uploaded
        """
        async with httpx.AsyncClient(timeout=180.0) as client:
            for digest in required_digests:
                file = file_map.get(digest)
                if not file:
                    continue

                # Normalize path
                normalized_path = file.path.replace('\\', '/')
                if not normalized_path.startswith('/'):
                    normalized_path = '/' + normalized_path

                # Determine correct MIME type based on file extension
                content_type = self._get_content_type(normalized_path)

                # Upload file
                url = f"{self.API_BASE}/deploys/{deploy_id}/files{normalized_path}"
                response = await client.put(
                    url,
                    headers={
                        **self._get_headers(),
                        "Content-Type": content_type
                    },
                    content=file.content
                )
                response.raise_for_status()

    async def _wait_for_deploy(
        self,
        deploy_id: str,
        logs: List[str],
        max_wait: int = 600
    ) -> str:
        """
        Wait for deploy to be ready.

        Args:
            deploy_id: Deploy ID
            logs: List to append progress logs to
            max_wait: Maximum wait time in seconds

        Returns:
            Final deploy state
        """
        start_time = asyncio.get_event_loop().time()
        poll_interval = 5  # Poll every 5 seconds

        while True:
            try:
                status_data = await self.get_deployment_status(deploy_id)
                state = status_data.get('state', 'unknown')

                # Terminal states
                if state in ['ready', 'error']:
                    return state

                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > max_wait:
                    logs.append(f"Deploy timed out after {max_wait} seconds")
                    return 'timeout'

                # Log progress
                if state in ['processing', 'building']:
                    logs.append(f"Processing... ({int(elapsed)}s elapsed)")

                # Wait before next poll
                await asyncio.sleep(poll_interval)

            except Exception as e:
                logs.append(f"Error polling status: {str(e)}")
                return 'error'

    def _get_content_type(self, file_path: str) -> str:
        """
        Determine the correct MIME type for a file based on its extension.

        Args:
            file_path: Path to the file

        Returns:
            MIME type string
        """
        # Initialize mimetypes if not already done
        if not mimetypes.inited:
            mimetypes.init()

        # Add custom MIME types for common web files
        mimetypes.add_type('application/javascript', '.js')
        mimetypes.add_type('application/javascript', '.mjs')
        mimetypes.add_type('text/javascript', '.jsx')
        mimetypes.add_type('text/css', '.css')
        mimetypes.add_type('text/html', '.html')
        mimetypes.add_type('application/json', '.json')
        mimetypes.add_type('image/svg+xml', '.svg')
        mimetypes.add_type('text/plain', '.txt')
        mimetypes.add_type('text/plain', '.md')
        mimetypes.add_type('application/wasm', '.wasm')

        # Guess MIME type from file extension
        mime_type, _ = mimetypes.guess_type(file_path)

        # Default to application/octet-stream if unknown
        return mime_type or 'application/octet-stream'

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Netlify API requests."""
        return {
            "Authorization": f"Bearer {self.credentials['token']}",
            "Content-Type": "application/json"
        }

    async def test_credentials(self) -> Dict[str, any]:
        """
        Test if credentials are valid by making a real API call to Netlify.

        Returns:
            Dictionary with validation result

        Raises:
            ValueError: If credentials are invalid
        """
        url = f"{self.API_BASE}/sites"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=self._get_headers())
                response.raise_for_status()

                # If we get here, credentials are valid
                data = response.json()
                return {
                    "valid": True,
                    "site_count": len(data) if isinstance(data, list) else 0
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid Netlify access token")
            elif e.response.status_code == 403:
                raise ValueError("Access token does not have required permissions")
            else:
                raise ValueError(f"Netlify API error: {e.response.status_code}")
        except httpx.TimeoutException:
            raise ValueError("Connection to Netlify API timed out")
        except Exception as e:
            raise ValueError(f"Failed to validate credentials: {str(e)}")

    async def get_deployment_status(self, deployment_id: str) -> Dict:
        """
        Get deployment status from Netlify.

        Args:
            deployment_id: Deploy ID

        Returns:
            Deploy status data
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.API_BASE}/deploys/{deployment_id}",
                headers=self._get_headers()
            )
            response.raise_for_status()
            return response.json()

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Delete deployment from Netlify.

        Args:
            deployment_id: Deploy ID

        Returns:
            True if deletion was successful
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    f"{self.API_BASE}/deploys/{deployment_id}",
                    headers=self._get_headers()
                )
                return response.status_code == 204
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> List[str]:
        """
        Get deploy logs from Netlify.

        Args:
            deployment_id: Deploy ID

        Returns:
            List of log messages
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Netlify doesn't have a direct logs endpoint, but we can get the deploy info
                response = await client.get(
                    f"{self.API_BASE}/deploys/{deployment_id}",
                    headers=self._get_headers()
                )
                if response.status_code == 200:
                    deploy = response.json()
                    logs = []

                    # Include deploy information
                    if deploy.get('error_message'):
                        logs.append(f"Error: {deploy['error_message']}")

                    if deploy.get('deploy_time'):
                        logs.append(f"Deploy time: {deploy['deploy_time']}s")

                    if deploy.get('state'):
                        logs.append(f"State: {deploy['state']}")

                    return logs if logs else ["No detailed logs available"]
                return []
        except Exception:
            return []
