"""
Firebase Hosting deployment provider.

This provider implements deployment to Firebase Hosting using the Firebase
Hosting REST API. It handles service-account JWT authentication, file hashing,
gzip upload, version creation, and release publishing.
"""

import gzip
import hashlib
import json
import logging
import time

import httpx
import jwt

from ..base import BaseDeploymentProvider, DeploymentConfig, DeploymentFile, DeploymentResult

logger = logging.getLogger(__name__)

HOSTING_BASE = "https://firebasehosting.googleapis.com/v1beta1"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/firebase.hosting"


class FirebaseHostingProvider(BaseDeploymentProvider):
    """
    Firebase Hosting deployment provider.

    Supports deploying static sites to Firebase Hosting via the REST API.
    Uses service-account JSON credentials for authentication (RS256 JWT exchange).
    """

    def validate_credentials(self) -> None:
        """Validate required Firebase Hosting credentials."""
        required = ["service_account_json", "site_id"]
        missing = [k for k in required if k not in self.credentials]
        if missing:
            raise ValueError(
                f"Missing required Firebase credential(s): {', '.join(missing)}"
            )

        # Validate that the service account JSON is parseable
        try:
            sa = json.loads(self.credentials["service_account_json"])
            for key in ("client_email", "private_key", "token_uri"):
                if key not in sa:
                    raise ValueError(
                        f"Service account JSON missing required field: {key}"
                    )
        except json.JSONDecodeError as e:
            raise ValueError(f"service_account_json is not valid JSON: {e}") from e

    @property
    def _site_id(self) -> str:
        return self.credentials["site_id"]

    def _parse_service_account(self) -> dict:
        """Parse and return the service account JSON (immutable copy)."""
        return json.loads(self.credentials["service_account_json"])

    async def _get_access_token(self, client: httpx.AsyncClient) -> str:
        """
        Exchange a self-signed JWT for a Google OAuth2 access token.

        Uses RS256 signing with the service account's private key.
        """
        sa = self._parse_service_account()
        now = int(time.time())
        payload = {
            "iss": sa["client_email"],
            "sub": sa["client_email"],
            "aud": sa.get("token_uri", TOKEN_URL),
            "scope": SCOPE,
            "iat": now,
            "exp": now + 3600,
        }

        signed_jwt = jwt.encode(payload, sa["private_key"], algorithm="RS256")

        resp = await client.post(
            sa.get("token_uri", TOKEN_URL),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": signed_jwt,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _auth_headers(self, access_token: str) -> dict[str, str]:
        """Build Authorization headers from an access token."""
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    async def test_credentials(self) -> dict:
        """
        Test if credentials are valid by fetching the Firebase Hosting site.

        Returns:
            Dictionary with validation result and site info.

        Raises:
            ValueError: If credentials are invalid.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                token = await self._get_access_token(client)
                resp = await client.get(
                    f"{HOSTING_BASE}/sites/{self._site_id}",
                    headers=self._auth_headers(token),
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "valid": True,
                    "site_id": data.get("name", "").split("/")[-1],
                    "default_url": data.get("defaultUrl"),
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid Firebase service account credentials") from e
            if e.response.status_code == 403:
                raise ValueError(
                    "Service account lacks Firebase Hosting permissions"
                ) from e
            if e.response.status_code == 404:
                raise ValueError(
                    f"Firebase Hosting site '{self._site_id}' not found"
                ) from e
            raise ValueError(
                f"Firebase API error: {e.response.status_code}"
            ) from e
        except jwt.PyJWTError as e:
            raise ValueError(f"JWT signing failed: {e}") from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to Firebase API timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate credentials: {e}") from e

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """
        Deploy to Firebase Hosting.

        The deployment process:
        1. Get access token from service account
        2. Create a new version
        3. Hash + gzip each file, build file map
        4. populateFiles to determine which files need uploading
        5. Upload required files
        6. Finalize version
        7. Create release

        Args:
            files: List of files to deploy
            config: Deployment configuration

        Returns:
            DeploymentResult with deployment information
        """
        logs: list[str] = []
        site_id = self._site_id

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                # Step 1: Get access token
                token = await self._get_access_token(client)
                headers = self._auth_headers(token)
                logs.append("Authenticated with Firebase")

                # Step 2: Create version
                version_resp = await client.post(
                    f"{HOSTING_BASE}/sites/{site_id}/versions",
                    headers=headers,
                    json={},
                )
                version_resp.raise_for_status()
                version_data = version_resp.json()
                version_name = version_data["name"]
                version_id = version_name.split("/")[-1]
                logs.append(f"Created version: {version_id}")

                # Step 3: Hash + gzip each file
                file_map, gzipped_by_hash = self._prepare_file_hashes(files, logs)

                # Step 4: populateFiles
                populate_resp = await client.post(
                    f"{HOSTING_BASE}/{version_name}:populateFiles",
                    headers=headers,
                    json={"files": file_map},
                )
                populate_resp.raise_for_status()
                populate_data = populate_resp.json()

                upload_url = populate_data.get("uploadUrl", "")
                required_hashes = set(
                    populate_data.get("uploadRequiredHashes", [])
                )
                logs.append(
                    f"Files to upload: {len(required_hashes)} of {len(file_map)}"
                )

                # Step 5: Upload required files
                for file_hash in required_hashes:
                    gzipped = gzipped_by_hash.get(file_hash)
                    if not gzipped:
                        logs.append(f"Warning: no content for hash {file_hash}")
                        continue

                    up_resp = await client.post(
                        f"{upload_url}/{file_hash}",
                        content=gzipped,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/octet-stream",
                        },
                    )
                    up_resp.raise_for_status()

                logs.append("All files uploaded")

                # Step 6: Finalize version
                finalize_resp = await client.patch(
                    f"{HOSTING_BASE}/{version_name}",
                    headers=headers,
                    json={"status": "FINALIZED"},
                    params={"updateMask": "status"},
                )
                finalize_resp.raise_for_status()
                logs.append("Version finalized")

                # Step 7: Create release
                release_resp = await client.post(
                    f"{HOSTING_BASE}/sites/{site_id}/releases",
                    headers=headers,
                    params={"versionName": version_name},
                    json={},
                )
                release_resp.raise_for_status()
                release_data = release_resp.json()

                deployment_url = f"https://{site_id}.web.app"
                logs.append(f"Release published: {deployment_url}")

                return DeploymentResult(
                    success=True,
                    deployment_id=version_id,
                    deployment_url=deployment_url,
                    logs=logs,
                    metadata={
                        "version_name": version_name,
                        "release_name": release_data.get("name"),
                        "site_id": site_id,
                    },
                )

        except httpx.HTTPStatusError as e:
            error_msg = (
                f"Firebase API error: {e.response.status_code} - {e.response.text}"
            )
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except jwt.PyJWTError as e:
            error_msg = f"JWT signing failed: {e}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)
        except Exception as e:
            error_msg = f"Deployment failed: {e}"
            logs.append(error_msg)
            return DeploymentResult(success=False, error=error_msg, logs=logs)

    @staticmethod
    def _prepare_file_hashes(
        files: list[DeploymentFile], logs: list[str]
    ) -> tuple[dict[str, str], dict[str, bytes]]:
        """
        Hash and gzip each file.

        Returns:
            (file_map, gzipped_by_hash) where file_map maps "/path" -> sha256
            and gzipped_by_hash maps sha256 -> gzipped bytes.
        """
        file_map: dict[str, str] = {}
        gzipped_by_hash: dict[str, bytes] = {}

        for f in files:
            normalized = f.path.replace("\\", "/")
            key = normalized if normalized.startswith("/") else f"/{normalized}"

            compressed = gzip.compress(f.content)
            file_hash = hashlib.sha256(compressed).hexdigest()

            file_map[key] = file_hash
            gzipped_by_hash[file_hash] = compressed

        logs.append(f"Hashed {len(file_map)} files")
        return file_map, gzipped_by_hash

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """
        Get release status from Firebase Hosting.

        Args:
            deployment_id: Firebase version ID

        Returns:
            Release status data
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                token = await self._get_access_token(client)
                resp = await client.get(
                    f"{HOSTING_BASE}/sites/{self._site_id}/releases",
                    headers=self._auth_headers(token),
                    params={"pageSize": 1},
                )
                resp.raise_for_status()
                data = resp.json()
                releases = data.get("releases", [])
                if releases:
                    latest = releases[0]
                    return {
                        "status": latest.get("type", "unknown"),
                        "version": latest.get("version", {}).get("name"),
                        "create_time": latest.get("releaseTime"),
                    }
                return {"status": "no_releases"}
        except Exception as e:
            return {"error": str(e), "status": "unknown"}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """
        Firebase Hosting does not support deleting individual releases.

        Args:
            deployment_id: Firebase version ID (unused)

        Returns:
            Always False -- deletion is not supported.
        """
        return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Firebase Hosting does not expose deployment logs via its REST API.

        Args:
            deployment_id: Firebase version ID (unused)

        Returns:
            Empty list (logs not available)
        """
        return []
