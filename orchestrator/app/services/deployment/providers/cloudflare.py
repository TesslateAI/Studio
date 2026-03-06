"""
Cloudflare Workers deployment provider.

This provider implements deployment to Cloudflare Workers with static assets.
It handles asset manifest creation, batch uploads, and worker script deployment.
"""

import base64
import hashlib
import json
import mimetypes

import httpx

from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentFile, DeploymentResult


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
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Cloudflare Workers with Assets.

        The deployment process:
        1. Create asset manifest with file hashes
        2. Create upload session
        3. Upload assets in batches
        4. Deploy worker script with asset binding
        5. Enable workers.dev subdomain
        6. Return deployment URL

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
            completion_token = session["jwt"]
            if session.get("buckets"):
                logs.append(
                    f"Uploading {len(files)} assets in {len(session['buckets'])} batches..."
                )
                completion_token = await self._upload_assets(
                    session["jwt"], session["buckets"], files, manifest
                )
                logs.append("Asset upload completed")

            # Step 4: Deploy worker script
            logs.append("Deploying worker script...")
            worker_content = self._generate_worker_script(config)
            await self._deploy_worker(script_name, worker_content, completion_token, config)

            # Step 5: Enable workers.dev subdomain
            logs.append("Enabling workers.dev subdomain...")
            subdomain_info = await self._enable_subdomain(script_name)
            logs.append(f"Subdomain enabled: {subdomain_info}")

            # Step 6: Generate deployment URL
            dispatch_namespace = self.credentials.get("dispatch_namespace")
            if dispatch_namespace:
                deployment_url = f"https://{script_name}.{dispatch_namespace}.workers.dev"
            else:
                # Get the subdomain from account settings
                subdomain_name = await self._get_account_subdomain()
                if subdomain_name:
                    deployment_url = f"https://{script_name}.{subdomain_name}.workers.dev"
                else:
                    deployment_url = f"https://{script_name}.workers.dev"

            logs.append(f"Deployment successful: {deployment_url}")

            return DeploymentResult(
                success=True,
                deployment_id=script_name,
                deployment_url=deployment_url,
                logs=logs,
                metadata={
                    "account_id": self.credentials["account_id"],
                    "script_name": script_name,
                    "file_count": len(files),
                },
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"Cloudflare API error: {e.response.status_code} - {e.response.text}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

        except Exception as e:
            error_msg = f"Deployment failed: {str(e)}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    def _create_asset_manifest(self, files: list[DeploymentFile]) -> dict:
        """
        Create Cloudflare asset manifest with 32-char truncated SHA256 hashes.

        Cloudflare requires hashes to be exactly 32 hex characters. The hash is
        computed over base64(content) + file_extension to match the expected format.

        Args:
            files: List of files to include in manifest

        Returns:
            Dictionary mapping file paths to hash/size metadata
        """
        manifest = {}
        for file in files:
            # Normalize path (use forward slashes, ensure leading slash)
            normalized_path = file.path.replace("\\", "/")
            if not normalized_path.startswith("/"):
                normalized_path = "/" + normalized_path

            # Compute hash: SHA256 of base64(content) + extension, truncated to 32 hex chars
            b64_content = base64.b64encode(file.content).decode("utf-8")
            ext = normalized_path.rsplit(".", 1)[-1] if "." in normalized_path else ""
            file_hash = hashlib.sha256((b64_content + ext).encode("utf-8")).hexdigest()[:32]

            manifest[normalized_path] = {"hash": file_hash, "size": len(file.content)}
        return manifest

    async def _create_upload_session(self, script_name: str, manifest: dict) -> dict:
        """
        Create asset upload session with Cloudflare.

        Args:
            script_name: Name of the worker script
            manifest: Asset manifest (path -> {hash, size})

        Returns:
            Session data including JWT and buckets
        """
        url = (
            f"{self.API_BASE}/accounts/{self.credentials['account_id']}/"
            f"workers/scripts/{script_name}/assets-upload-session"
        )

        # Cloudflare requires the manifest wrapped in a {"manifest": ...} envelope
        payload = {"manifest": manifest}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=self._get_headers(), json=payload)
            response.raise_for_status()
            data = response.json()
            return data["result"]

    async def _upload_assets(
        self, jwt: str, buckets: list[list[str]], files: list[DeploymentFile], manifest: dict
    ) -> str:
        """
        Upload assets in batches to Cloudflare using multipart/form-data.

        Args:
            jwt: Session JWT token
            buckets: List of file hash buckets from upload session
            files: List of files to upload
            manifest: Asset manifest for hash lookups

        Returns:
            Completion token (JWT)
        """
        # Create hash -> (content, path) mapping for quick lookup
        hash_to_file = {}
        for file in files:
            normalized_path = file.path.replace("\\", "/")
            if not normalized_path.startswith("/"):
                normalized_path = "/" + normalized_path

            file_hash = manifest[normalized_path]["hash"]
            hash_to_file[file_hash] = (file.content, normalized_path)

        completion_token = jwt

        # Upload each bucket as multipart/form-data
        for bucket in buckets:
            form_files = {}
            for file_hash in bucket:
                file_info = hash_to_file.get(file_hash)
                if file_info is None:
                    continue

                content, path = file_info
                content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
                b64_content = base64.b64encode(content).decode("utf-8")
                form_files[file_hash] = (file_hash, b64_content, content_type)

            if not form_files:
                continue

            url = f"{self.API_BASE}/accounts/{self.credentials['account_id']}/workers/assets/upload"

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {jwt}"},
                    params={"base64": "true"},
                    files=form_files,
                )
                # Cloudflare returns 201 on successful asset upload
                if response.status_code not in (200, 201):
                    response.raise_for_status()

                result = response.json().get("result", {})

                # Update completion token if provided
                if result.get("jwt"):
                    completion_token = result["jwt"]

        return completion_token

    async def _deploy_worker(
        self, script_name: str, worker_content: str, asset_jwt: str, config: DeploymentConfig
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
            "assets": {
                "jwt": asset_jwt,
                "config": {
                    "html_handling": "auto-trailing-slash",
                    "not_found_handling": "single-page-application",
                    "run_worker_first": True,
                },
            },
            "bindings": [
                {
                    "type": "assets",
                    "name": "ASSETS",
                },
            ],
        }

        # Add env vars if present
        if config.env_vars:
            metadata["vars"] = config.env_vars

        # Prepare multipart form data
        files_data = {
            "metadata": ("metadata.json", json.dumps(metadata), "application/json"),
            "index.js": ("index.js", worker_content, "application/javascript+module"),
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.put(
                url,
                headers={"Authorization": f"Bearer {self.credentials['api_token']}"},
                files=files_data,
            )
            response.raise_for_status()

    async def _enable_subdomain(self, script_name: str) -> dict:
        """
        Enable the workers.dev subdomain for a deployed worker script.

        After deploying a worker, the .workers.dev route must be explicitly enabled
        for the worker to be accessible at its subdomain URL.

        Args:
            script_name: Name of the worker script

        Returns:
            API response result
        """
        url = (
            f"{self.API_BASE}/accounts/{self.credentials['account_id']}/"
            f"workers/scripts/{script_name}/subdomain"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers=self._get_headers(),
                json={"enabled": True},
            )
            if response.status_code not in (200, 409):
                # 409 means already enabled, which is fine
                response.raise_for_status()
            return response.json().get("result", {})

    async def _get_account_subdomain(self) -> str | None:
        """
        Get the account's workers.dev subdomain name.

        Returns:
            The subdomain string (e.g., 'username') or None if not set
        """
        url = f"{self.API_BASE}/accounts/{self.credentials['account_id']}/workers/subdomain"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=self._get_headers())
                if response.status_code == 200:
                    data = response.json()
                    return data.get("result", {}).get("subdomain")
        except Exception:
            pass
        return None

    def _generate_worker_script(self, config: DeploymentConfig) -> str:
        """
        Generate worker script for serving static assets.

        With run_worker_first=True, this worker handles all requests. It delegates
        to Cloudflare's asset serving and provides SPA fallback for client-side routing.

        Args:
            config: Deployment configuration

        Returns:
            JavaScript worker code
        """
        return """\
export default {
  async fetch(request, env) {
    const response = await env.ASSETS.fetch(request);
    if (response.ok) {
      return response;
    }

    // SPA fallback: serve index.html for navigation requests
    const indexResponse = await env.ASSETS.fetch(
      new Request(new URL('/index.html', request.url), request)
    );
    if (indexResponse.ok) {
      return new Response(indexResponse.body, {
        status: 200,
        headers: indexResponse.headers,
      });
    }

    return new Response('Not Found', { status: 404 });
  }
}
"""

    def _get_headers(self) -> dict[str, str]:
        """Get headers for Cloudflare API requests."""
        return {
            "Authorization": f"Bearer {self.credentials['api_token']}",
            "Content-Type": "application/json",
        }

    async def test_credentials(self) -> dict[str, any]:
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
                    "account_id": self.credentials["account_id"],
                    "script_count": len(data.get("result", [])),
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid API token") from e
            elif e.response.status_code == 403:
                raise ValueError("API token does not have required permissions") from e
            elif e.response.status_code == 404:
                raise ValueError("Account ID not found") from e
            else:
                raise ValueError(f"Cloudflare API error: {e.response.status_code}") from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to Cloudflare API timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate credentials: {str(e)}") from e

    async def get_deployment_status(self, deployment_id: str) -> dict:
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
                    return {"status": "deployed", "script": response.json()["result"]}
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

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Get deployment logs.

        Note: Cloudflare Workers doesn't provide deployment logs via API.

        Args:
            deployment_id: Worker script name

        Returns:
            Empty list (logs not available)
        """
        return ["Cloudflare Workers deployment logs are not available via API"]
