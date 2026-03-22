"""
GCP Artifact Registry + Cloud Run deployment provider.

Pushes container images to Artifact Registry and deploys them via Cloud Run.
Authenticates using a GCP service account JSON key.
"""

import base64
import json
import logging
import time

import httpx

from ..base import DeploymentResult
from ..container_base import BaseContainerDeploymentProvider, ContainerDeployConfig
from .utils import poll_until_terminal

logger = logging.getLogger(__name__)

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
JWT_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"


class GCPContainerProvider(BaseContainerDeploymentProvider):
    """
    GCP Artifact Registry + Cloud Run deployment provider.

    Pushes container images to Google Artifact Registry and deploys them
    on Cloud Run for fully managed serverless container hosting.
    """

    def validate_credentials(self) -> None:
        """Validate required GCP credentials."""
        if not self.credentials.get("service_account_json"):
            raise ValueError("Missing required GCP credential: service_account_json")

        try:
            sa = json.loads(self.credentials["service_account_json"])
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError("service_account_json must be valid JSON") from e

        required_keys = ("client_email", "private_key", "project_id", "token_uri")
        missing = [k for k in required_keys if k not in sa]
        if missing:
            raise ValueError(f"Service account JSON missing keys: {', '.join(missing)}")

        if "gcp_region" not in self.credentials:
            self.credentials = {**self.credentials, "gcp_region": "us-central1"}

    @property
    def _region(self) -> str:
        return self.credentials["gcp_region"]

    @property
    def _sa(self) -> dict:
        return json.loads(self.credentials["service_account_json"])

    @property
    def _project_id(self) -> str:
        return self._sa["project_id"]

    async def _get_access_token(self) -> str:
        """
        Exchange a signed JWT for a Google OAuth2 access token.

        Signs a JWT using the service account private key, then posts it
        to Google's token endpoint for an access token.
        """
        sa = self._sa
        now = int(time.time())

        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": sa["client_email"],
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "aud": sa.get("token_uri", OAUTH_TOKEN_URL),
            "iat": now,
            "exp": now + 3600,
        }

        segments = [
            _b64url_encode(json.dumps(header).encode()),
            _b64url_encode(json.dumps(payload).encode()),
        ]
        signing_input = f"{segments[0]}.{segments[1]}"

        signature = _rs256_sign(sa["private_key"], signing_input.encode())
        jwt_token = f"{signing_input}.{_b64url_encode(signature)}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                sa.get("token_uri", OAUTH_TOKEN_URL),
                data={"grant_type": JWT_GRANT_TYPE, "assertion": jwt_token},
            )
            resp.raise_for_status()
            return resp.json()["access_token"]

    def _bearer_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def test_credentials(self) -> dict:
        """
        Verify GCP credentials by checking project access.

        Returns:
            Dict with project_id and project name.
        """
        try:
            token = await self._get_access_token()
            url = (
                f"https://cloudresourcemanager.googleapis.com/v1/projects/{self._project_id}"
            )
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=self._bearer_headers(token))
                resp.raise_for_status()
                data = resp.json()
                return {
                    "valid": True,
                    "project_id": data.get("projectId"),
                    "project_name": data.get("name"),
                }
        except httpx.HTTPStatusError as e:
            raise ValueError(
                f"GCP authentication failed: HTTP {e.response.status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to GCP API timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate GCP credentials: {e}") from e

    async def push_image(self, image_ref: str) -> str:
        """
        Push a container image to Google Artifact Registry.

        Prepares authentication for Artifact Registry and returns the target URI.
        Full layer-level push requires a Docker client.

        Args:
            image_ref: Source image reference (e.g. myapp:latest)

        Returns:
            Artifact Registry image URI.
        """
        repo, tag = _parse_image_ref(image_ref)

        try:
            token = await self._get_access_token()
            registry_host = f"{self._region}-docker.pkg.dev"
            pushed_uri = f"{registry_host}/{self._project_id}/{repo}:{tag}"

            logger.info(
                "Artifact Registry push target: %s (auth: oauth2accesstoken, full push requires Docker client)",
                pushed_uri,
            )
            return pushed_uri

        except Exception as e:
            raise ValueError(f"Failed to prepare Artifact Registry push: {e}") from e

    async def deploy_image(self, config: ContainerDeployConfig) -> DeploymentResult:
        """
        Deploy a container image to Cloud Run.

        Args:
            config: Container deployment configuration.

        Returns:
            DeploymentResult with Cloud Run service URL.
        """
        logs: list[str] = []
        service_name = config.image_ref.split("/")[-1].split(":")[0][:49]
        region = config.region or self._region

        try:
            token = await self._get_access_token()
            headers = self._bearer_headers(token)

            parent = f"projects/{self._project_id}/locations/{region}"
            url = f"https://run.googleapis.com/v2/{parent}/services?serviceId={service_name}"

            env_list = [{"name": k, "value": v} for k, v in config.env_vars.items()]

            service_body = {
                "template": {
                    "containers": [
                        {
                            "image": config.image_ref,
                            "ports": [{"containerPort": config.port}],
                            "env": env_list,
                            "resources": {
                                "limits": {
                                    "cpu": config.cpu,
                                    "memory": config.memory,
                                }
                            },
                        }
                    ],
                },
            }

            logs.append(f"Creating Cloud Run service '{service_name}' in {region}...")

            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(url, json=service_body, headers=headers)
                resp.raise_for_status()
                operation = resp.json()

                op_name = operation.get("name", "")
                if op_name:
                    logs.append(f"Operation started: {op_name}")
                    final = await poll_until_terminal(
                        check_fn=lambda: self._poll_operation(op_name, token),
                        terminal_states={"true", "false"},
                        status_key="done",
                        interval=5,
                        timeout=300,
                    )

                    if str(final.get("done")) == "true" and "error" not in final:
                        service_url = await self._get_service_url(
                            parent, service_name, token
                        )
                        logs.append(f"Service deployed at {service_url}")
                        return DeploymentResult(
                            success=True,
                            deployment_id=f"{parent}/services/{service_name}",
                            deployment_url=service_url,
                            logs=logs,
                            metadata={"operation": op_name, "region": region},
                        )

                    error = final.get("error", {})
                    msg = error.get("message", "Unknown error")
                    logs.append(f"Deployment failed: {msg}")
                    return DeploymentResult(
                        success=False,
                        deployment_id=f"{parent}/services/{service_name}",
                        error=msg,
                        logs=logs,
                    )

                # No LRO, service may have been created directly
                service_url = await self._get_service_url(parent, service_name, token)
                logs.append(f"Service deployed at {service_url}")
                return DeploymentResult(
                    success=True,
                    deployment_id=f"{parent}/services/{service_name}",
                    deployment_url=service_url,
                    logs=logs,
                )

        except TimeoutError as e:
            logs.append(str(e))
            return DeploymentResult(
                success=False, error="Cloud Run deployment timed out", logs=logs
            )
        except httpx.HTTPStatusError as e:
            msg = f"Cloud Run API error: HTTP {e.response.status_code} - {e.response.text}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)
        except Exception as e:
            msg = f"Deployment failed: {e}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)

    async def _poll_operation(self, op_name: str, token: str) -> dict:
        """Poll a long-running operation."""
        url = f"https://run.googleapis.com/v2/{op_name}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self._bearer_headers(token))
            resp.raise_for_status()
            result = resp.json()
            return {**result, "done": str(result.get("done", False)).lower()}

    async def _get_service_url(
        self, parent: str, service_name: str, token: str
    ) -> str:
        """Fetch the URL of a deployed Cloud Run service."""
        url = f"https://run.googleapis.com/v2/{parent}/services/{service_name}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self._bearer_headers(token))
            resp.raise_for_status()
            return resp.json().get("uri", "")

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """Get Cloud Run service status by full resource name."""
        try:
            token = await self._get_access_token()
            url = f"https://run.googleapis.com/v2/{deployment_id}"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=self._bearer_headers(token))
                resp.raise_for_status()
                data = resp.json()
                conditions = data.get("conditions", [])
                ready = next(
                    (c for c in conditions if c.get("type") == "Ready"), {}
                )
                return {
                    "status": ready.get("state", "UNKNOWN"),
                    "url": data.get("uri"),
                    "conditions": conditions,
                }
        except Exception as e:
            return {"status": "unknown", "error": str(e)}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a Cloud Run service by full resource name."""
        try:
            token = await self._get_access_token()
            url = f"https://run.googleapis.com/v2/{deployment_id}"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(url, headers=self._bearer_headers(token))
                return resp.status_code in (200, 204)
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch deployment logs. Cloud Logging integration required for full logs.

        Returns:
            Empty list (Cloud Logging integration not implemented).
        """
        return ["Cloud Logging integration required for Cloud Run logs"]


def _b64url_encode(data: bytes) -> str:
    """URL-safe base64 encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _rs256_sign(private_key_pem: str, message: bytes) -> bytes:
    """
    Sign a message with RS256 using the cryptography library.

    Falls back to a clear error if the library is unavailable.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as e:
        raise ImportError(
            "The 'cryptography' package is required for GCP service account auth. "
            "Install it with: pip install cryptography"
        ) from e

    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"), password=None
    )
    return private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())  # type: ignore[union-attr]


def _parse_image_ref(image_ref: str) -> tuple[str, str]:
    """Split image_ref into (repo, tag). Default tag is 'latest'."""
    last_segment = image_ref.split("/")[-1]
    if ":" in last_segment:
        parts = image_ref.rsplit(":", 1)
        return parts[0], parts[1]
    return image_ref, "latest"
