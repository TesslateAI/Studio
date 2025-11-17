"""
Cloudflare Workers deployment provider.

This provider implements deployment to Cloudflare Workers with static assets.
It handles asset manifest creation, batch uploads, and worker script deployment.
"""

from typing import List, Dict, Optional
import httpx
import hashlib
import base64
import json
from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentResult, DeploymentFile


class CloudflareWorkersProvider(BaseDeploymentProvider):
    """
    Cloudflare Workers deployment provider.

    Supports deploying static sites and applications to Cloudflare Workers
    with the Assets feature for serving static files.
    """

    API_BASE = "https://api.cloudflare.com/client/v4"

    def validate_credentials(self) -> None:
        """Validate required Cloudflare credentials."""
        required = ["account_id", "api_token"]
        for key in required:
            if key not in self.credentials:
                raise ValueError(f"Missing required Cloudflare credential: {key}")

    async def deploy(
        self,
        files: List[DeploymentFile],
        config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Cloudflare Workers with Assets.

        The deployment process:
        1. Create asset manifest with file hashes
        2. Create upload session
        3. Upload assets in batches
        4. Deploy worker script with asset binding
        5. Return deployment URL

        Args:
            files: List of files to deploy
            config: Deployment configuration

        Returns:
            DeploymentResult with deployment information
        """
        logs = []

        try:
            script_name = self._sanitize_name(config.project_name)
            logs.append(f"Deploying to Cloudflare Workers as '{script_name}'")

            # Step 1: Create asset manifest
            logs.append(f"Creating asset manifest for {len(files)} files...")
            manifest = self._create_asset_manifest(files)

            # Step 2: Create upload session
            logs.append("Creating upload session...")
            session = await self._create_upload_session(script_name, manifest)

            # Step 3: Upload assets in batches
            completion_token = session['jwt']
            if session.get('buckets'):
                logs.append(f"Uploading {len(files)} assets in {len(session['buckets'])} batches...")
                completion_token = await self._upload_assets(
                    session['jwt'],
                    session['buckets'],
                    files,
                    manifest
                )
                logs.append("Asset upload completed")

            # Step 4: Deploy worker script
            logs.append("Deploying worker script...")
            worker_content = self._generate_worker_script(config)
            await self._deploy_worker(
                script_name,
                worker_content,
                completion_token,
                config
            )

            # Step 5: Generate deployment URL
            dispatch_namespace = self.credentials.get("dispatch_namespace")
            if dispatch_namespace:
                deployment_url = f"https://{script_name}.{dispatch_namespace}.workers.dev"
            else:
                deployment_url = f"https://{script_name}.{self.credentials['account_id']}.workers.dev"

            logs.append(f"Deployment successful: {deployment_url}")

            return DeploymentResult(
                success=True,
                deployment_id=script_name,
                deployment_url=deployment_url,
                logs=logs,
                metadata={
                    "account_id": self.credentials['account_id'],
                    "script_name": script_name,
                    "file_count": len(files)
                }
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"Cloudflare API error: {e.response.status_code} - {e.response.text}"
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

    def _create_asset_manifest(self, files: List[DeploymentFile]) -> Dict:
        """
        Create Cloudflare asset manifest with SHA256 hashes.

        Args:
            files: List of files to include in manifest

        Returns:
            Dictionary mapping file paths to metadata
        """
        manifest = {}
        for file in files:
            # Calculate SHA256 hash
            file_hash = hashlib.sha256(file.content).hexdigest()

            # Normalize path (use forward slashes)
            normalized_path = file.path.replace('\\', '/')
            if not normalized_path.startswith('/'):
                normalized_path = '/' + normalized_path

            manifest[normalized_path] = {
                "hash": file_hash,
                "size": len(file.content)
            }
        return manifest

    async def _create_upload_session(
        self,
        script_name: str,
        manifest: Dict
    ) -> Dict:
        """
        Create asset upload session with Cloudflare.

        Args:
            script_name: Name of the worker script
            manifest: Asset manifest

        Returns:
            Session data including JWT and buckets
        """
        url = (
            f"{self.API_BASE}/accounts/{self.credentials['account_id']}/"
            f"workers/scripts/{script_name}/assets-upload-session"
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                headers=self._get_headers(),
                json=manifest
            )
            response.raise_for_status()
            data = response.json()
            return data['result']

    async def _upload_assets(
        self,
        jwt: str,
        buckets: List[List[str]],
        files: List[DeploymentFile],
        manifest: Dict
    ) -> str:
        """
        Upload assets in batches to Cloudflare.

        Args:
            jwt: Session JWT token
            buckets: List of file hash buckets
            files: List of files to upload
            manifest: Asset manifest

        Returns:
            Completion token (JWT)
        """
        # Create hash -> content mapping for quick lookup
        hash_to_content = {}
        for file in files:
            normalized_path = file.path.replace('\\', '/')
            if not normalized_path.startswith('/'):
                normalized_path = '/' + normalized_path

            file_hash = manifest[normalized_path]['hash']
            hash_to_content[file_hash] = file.content

        completion_token = jwt

        # Upload each bucket
        for bucket_index, bucket in enumerate(buckets):
            # Prepare batch data
            batch_data = []
            for file_hash in bucket:
                content = hash_to_content.get(file_hash)
                if content is None:
                    continue

                batch_data.append({
                    "key": file_hash,
                    "value": base64.b64encode(content).decode('utf-8'),
                    "metadata": {},
                    "base64": True
                })

            # Upload batch
            url = f"{self.API_BASE}/accounts/{self.credentials['account_id']}/workers/assets/upload"

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    headers={
                        **self._get_headers(),
                        "Authorization": f"Bearer {jwt}"
                    },
                    params={"base64": "true"},
                    json=batch_data
                )
                response.raise_for_status()
                result = response.json()['result']

                # Update completion token if provided
                if result.get('jwt'):
                    completion_token = result['jwt']

        return completion_token

    async def _deploy_worker(
        self,
        script_name: str,
        worker_content: str,
        asset_jwt: str,
        config: DeploymentConfig
    ) -> None:
        """
        Deploy worker script with metadata and assets.

        Args:
            script_name: Name of the worker script
            worker_content: JavaScript worker code
            asset_jwt: Asset upload completion token
            config: Deployment configuration
        """
        url = f"{self.API_BASE}/accounts/{self.credentials['account_id']}/workers/scripts/{script_name}"

        # Prepare metadata
        metadata = {
            "main_module": "index.js",
            "compatibility_date": "2025-01-13",
            "compatibility_flags": ["nodejs_compat"],
            "assets": {
                "jwt": asset_jwt,
                "config": {
                    "not_found_handling": "single-page-application",
                    "run_worker_first": True,
                    "binding": "ASSETS"
                }
            },
            "bindings": [],
            "vars": config.env_vars
        }

        # Prepare multipart form data
        files_data = {
            'metadata': (None, json.dumps(metadata), 'application/json'),
            'index.js': (None, worker_content, 'application/javascript+module')
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.put(
                url,
                headers={
                    "Authorization": f"Bearer {self.credentials['api_token']}"
                },
                files=files_data
            )
            response.raise_for_status()

    def _generate_worker_script(self, config: DeploymentConfig) -> str:
        """
        Generate worker script for serving static assets.

        Args:
            config: Deployment configuration

        Returns:
            JavaScript worker code
        """
        return """
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Try to serve from assets
    try {
      const response = await env.ASSETS.fetch(request);
      return response;
    } catch (e) {
      // Fallback to index.html for SPA routing
      if (url.pathname !== '/' && !url.pathname.includes('.')) {
        const indexRequest = new Request(
          new URL('/index.html', request.url),
          request
        );
        try {
          return await env.ASSETS.fetch(indexRequest);
        } catch (err) {
          return new Response('Not Found', { status: 404 });
        }
      }
      return new Response('Not Found', { status: 404 });
    }
  }
}
"""

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Cloudflare API requests."""
        return {
            "Authorization": f"Bearer {self.credentials['api_token']}",
            "Content-Type": "application/json"
        }

    async def test_credentials(self) -> Dict[str, any]:
        """
        Test if credentials are valid by making a real API call to Cloudflare.

        Returns:
            Dictionary with validation result

        Raises:
            ValueError: If credentials are invalid
        """
        url = f"{self.API_BASE}/accounts/{self.credentials['account_id']}/workers/scripts"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=self._get_headers())
                response.raise_for_status()

                # If we get here, credentials are valid
                data = response.json()
                return {
                    "valid": True,
                    "account_id": self.credentials['account_id'],
                    "script_count": len(data.get('result', []))
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid API token")
            elif e.response.status_code == 403:
                raise ValueError("API token does not have required permissions")
            elif e.response.status_code == 404:
                raise ValueError("Account ID not found")
            else:
                raise ValueError(f"Cloudflare API error: {e.response.status_code}")
        except httpx.TimeoutException:
            raise ValueError("Connection to Cloudflare API timed out")
        except Exception as e:
            raise ValueError(f"Failed to validate credentials: {str(e)}")

    async def get_deployment_status(self, deployment_id: str) -> Dict:
        """
        Get deployment status from Cloudflare.

        Args:
            deployment_id: Worker script name

        Returns:
            Status information
        """
        url = f"{self.API_BASE}/accounts/{self.credentials['account_id']}/workers/scripts/{deployment_id}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=self._get_headers())
                if response.status_code == 200:
                    return {
                        "status": "deployed",
                        "script": response.json()['result']
                    }
                return {"status": "not_found"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Delete worker deployment.

        Args:
            deployment_id: Worker script name

        Returns:
            True if deletion was successful
        """
        url = f"{self.API_BASE}/accounts/{self.credentials['account_id']}/workers/scripts/{deployment_id}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(url, headers=self._get_headers())
                return response.status_code == 200
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> List[str]:
        """
        Get deployment logs.

        Note: Cloudflare Workers doesn't provide deployment logs via API.

        Args:
            deployment_id: Worker script name

        Returns:
            Empty list (logs not available)
        """
        return ["Cloudflare Workers deployment logs are not available via API"]
