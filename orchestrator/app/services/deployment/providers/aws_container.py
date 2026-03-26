"""
AWS ECR + App Runner deployment provider.

Pushes container images to ECR and deploys them via AWS App Runner.
Uses minimal SigV4 signing for authentication (boto3 preferred in production).
"""

import datetime
import hashlib
import hmac
import json
import logging

import httpx

from ..base import DeploymentResult
from ..container_base import BaseContainerDeploymentProvider, ContainerDeployConfig
from .utils import poll_until_terminal

logger = logging.getLogger(__name__)


def _sign_v4(
    method: str,
    url: str,
    headers: dict[str, str],
    body: str,
    region: str,
    service: str,
    access_key: str,
    secret_key: str,
    timestamp: datetime.datetime,
) -> dict[str, str]:
    """
    Minimal AWS Signature V4 signer.

    NOTE: In production, prefer boto3/botocore for robust SigV4 signing.
    This is a simplified implementation covering the common case.
    """
    datestamp = timestamp.strftime("%Y%m%d")
    amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")

    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or ""
    canonical_uri = parsed.path or "/"
    canonical_querystring = parsed.query or ""

    signed_headers_map = {
        "host": host,
        "x-amz-date": amz_date,
        **{k.lower(): v for k, v in headers.items() if k.lower().startswith("content-type")},
    }
    signed_header_keys = sorted(signed_headers_map.keys())
    signed_headers_str = ";".join(signed_header_keys)
    canonical_headers = "".join(f"{k}:{signed_headers_map[k]}\n" for k in signed_header_keys)

    payload_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    canonical_request = "\n".join([
        method,
        canonical_uri,
        canonical_querystring,
        canonical_headers,
        signed_headers_str,
        payload_hash,
    ])

    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    def _hmac_sha256(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _hmac_sha256(f"AWS4{secret_key}".encode(), datestamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    k_signing = _hmac_sha256(k_service, "aws4_request")

    signature = hmac.new(
        k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, Signature={signature}"
    )

    return {
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Authorization": authorization,
        "Host": host,
    }


class AWSContainerProvider(BaseContainerDeploymentProvider):
    """
    AWS ECR + App Runner deployment provider.

    Pushes container images to Amazon ECR and deploys them
    on AWS App Runner for fully managed container hosting.
    """

    def validate_credentials(self) -> None:
        """Validate required AWS credentials are present."""
        required = ("aws_access_key_id", "aws_secret_access_key")
        missing = [k for k in required if not self.credentials.get(k)]
        if missing:
            raise ValueError(f"Missing required AWS credentials: {', '.join(missing)}")
        if "aws_region" not in self.credentials:
            self.credentials = {**self.credentials, "aws_region": "us-east-1"}

    @property
    def _region(self) -> str:
        return self.credentials["aws_region"]

    @property
    def _access_key(self) -> str:
        return self.credentials["aws_access_key_id"]

    @property
    def _secret_key(self) -> str:
        return self.credentials["aws_secret_access_key"]

    def _auth_headers(
        self,
        method: str,
        url: str,
        body: str,
        service: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build SigV4-signed headers for an AWS API call."""
        now = datetime.datetime.now(datetime.UTC)
        base_headers = extra_headers or {}
        signed = _sign_v4(
            method=method,
            url=url,
            headers=base_headers,
            body=body,
            region=self._region,
            service=service,
            access_key=self._access_key,
            secret_key=self._secret_key,
            timestamp=now,
        )
        return {**base_headers, **signed}

    async def test_credentials(self) -> dict:
        """
        Verify AWS credentials via STS GetCallerIdentity.

        Returns:
            Dict with account_id and caller ARN.
        """
        url = f"https://sts.{self._region}.amazonaws.com/"
        body = "Action=GetCallerIdentity&Version=2011-06-15"
        content_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        headers = self._auth_headers("POST", url, body, "sts", content_headers)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, content=body, headers=headers)
                resp.raise_for_status()

                text = resp.text
                # Parse simple XML response for Account and Arn
                account_id = _extract_xml_tag(text, "Account")
                arn = _extract_xml_tag(text, "Arn")

                return {"valid": True, "account_id": account_id, "arn": arn}
        except httpx.HTTPStatusError as e:
            raise ValueError(
                f"AWS STS authentication failed: HTTP {e.response.status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to AWS STS timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate AWS credentials: {e}") from e

    async def push_image(self, image_ref: str) -> str:
        """
        Push a container image to Amazon ECR.

        This retrieves an ECR authorization token and returns the target image URI.
        Full registry push (layer upload) requires a Docker client; this method
        prepares the auth and returns the destination URI.

        Args:
            image_ref: Source image reference (e.g. myapp:latest)

        Returns:
            ECR image URI (e.g. 123456.dkr.ecr.us-east-1.amazonaws.com/myapp:latest)
        """
        repo, tag = _parse_image_ref(image_ref)

        url = f"https://api.ecr.{self._region}.amazonaws.com/"
        body = json.dumps({})
        content_headers = {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AmazonEC2ContainerRegistry_V20150921.GetAuthorizationToken",
        }
        headers = self._auth_headers("POST", url, body, "ecr", content_headers)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, content=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                auth_data = data.get("authorizationData", [{}])[0]
                proxy_endpoint = auth_data.get("proxyEndpoint", "")
                registry = proxy_endpoint.replace("https://", "").rstrip("/")

                pushed_uri = f"{registry}/{repo}:{tag}"
                logger.info("ECR push target: %s (full push requires Docker client)", pushed_uri)
                return pushed_uri

        except httpx.HTTPStatusError as e:
            raise ValueError(f"ECR auth failed: HTTP {e.response.status_code}") from e
        except Exception as e:
            raise ValueError(f"Failed to get ECR auth token: {e}") from e

    async def deploy_image(self, config: ContainerDeployConfig) -> DeploymentResult:
        """
        Deploy a container image to AWS App Runner.

        Args:
            config: Container deployment configuration with image_ref, port, cpu, memory.

        Returns:
            DeploymentResult with App Runner service URL.
        """
        logs: list[str] = []
        service_name = config.image_ref.split("/")[-1].split(":")[0][:40]

        create_body = json.dumps({
            "ServiceName": service_name,
            "SourceConfiguration": {
                "ImageRepository": {
                    "ImageIdentifier": config.image_ref,
                    "ImageRepositoryType": "ECR",
                    "ImageConfiguration": {
                        "Port": str(config.port),
                        "RuntimeEnvironmentVariables": config.env_vars,
                    },
                },
                "AutoDeploymentsEnabled": False,
                "AuthenticationConfiguration": {
                    "AccessRoleArn": self.credentials.get("apprunner_access_role_arn", ""),
                },
            },
            "InstanceConfiguration": {
                "Cpu": config.cpu,
                "Memory": config.memory,
            },
        })

        url = f"https://apprunner.{self._region}.amazonaws.com/"
        content_headers = {
            "Content-Type": "application/x-amz-json-1.0",
            "X-Amz-Target": "AppRunner.CreateService",
        }
        headers = self._auth_headers("POST", url, create_body, "apprunner", content_headers)

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                logs.append(f"Creating App Runner service '{service_name}'...")
                resp = await client.post(url, content=create_body, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                service = data.get("Service", {})
                service_arn = service.get("ServiceArn", "")
                service_url = service.get("ServiceUrl", "")
                logs.append(f"Service created: {service_arn}")

                # Poll until RUNNING or CREATE_FAILED
                logs.append("Waiting for service to become active...")
                final = await poll_until_terminal(
                    check_fn=lambda: self._describe_service(service_arn),
                    terminal_states={"RUNNING", "CREATE_FAILED", "DELETED", "DELETE_FAILED", "PAUSED"},
                    status_key="Status",
                    interval=10,
                    timeout=600,
                )

                status = final.get("Status", "UNKNOWN")
                if status == "RUNNING":
                    live_url = f"https://{final.get('ServiceUrl', service_url)}"
                    logs.append(f"Service running at {live_url}")
                    return DeploymentResult(
                        success=True,
                        deployment_id=service_arn,
                        deployment_url=live_url,
                        logs=logs,
                        metadata={"service_arn": service_arn},
                    )

                logs.append(f"Service creation failed with status: {status}")
                return DeploymentResult(
                    success=False,
                    deployment_id=service_arn,
                    error=f"App Runner service {status}",
                    logs=logs,
                )

        except TimeoutError as e:
            logs.append(str(e))
            return DeploymentResult(success=False, error="Service creation timed out", logs=logs)
        except httpx.HTTPStatusError as e:
            msg = f"App Runner API error: HTTP {e.response.status_code} - {e.response.text}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)
        except Exception as e:
            msg = f"Deployment failed: {e}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)

    async def _describe_service(self, service_arn: str) -> dict:
        """Describe an App Runner service by ARN."""
        url = f"https://apprunner.{self._region}.amazonaws.com/"
        body = json.dumps({"ServiceArn": service_arn})
        content_headers = {
            "Content-Type": "application/x-amz-json-1.0",
            "X-Amz-Target": "AppRunner.DescribeService",
        }
        headers = self._auth_headers("POST", url, body, "apprunner", content_headers)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, content=body, headers=headers)
            resp.raise_for_status()
            return resp.json().get("Service", {})

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """Get App Runner service status by service ARN."""
        try:
            service = await self._describe_service(deployment_id)
            return {
                "status": service.get("Status", "UNKNOWN"),
                "url": service.get("ServiceUrl"),
                "updated_at": service.get("UpdatedAt"),
            }
        except Exception as e:
            return {"status": "unknown", "error": str(e)}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """Delete an App Runner service by ARN."""
        url = f"https://apprunner.{self._region}.amazonaws.com/"
        body = json.dumps({"ServiceArn": deployment_id})
        content_headers = {
            "Content-Type": "application/x-amz-json-1.0",
            "X-Amz-Target": "AppRunner.DeleteService",
        }
        headers = self._auth_headers("POST", url, body, "apprunner", content_headers)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, content=body, headers=headers)
                return resp.status_code in (200, 204)
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch deployment logs. CloudWatch integration required for full logs.

        Returns:
            Empty list (CloudWatch Logs integration not implemented).
        """
        return ["CloudWatch Logs integration required for App Runner logs"]


def _extract_xml_tag(xml: str, tag: str) -> str:
    """Extract text content of a simple XML tag."""
    start = xml.find(f"<{tag}>")
    end = xml.find(f"</{tag}>")
    if start == -1 or end == -1:
        return ""
    return xml[start + len(tag) + 2 : end]


def _parse_image_ref(image_ref: str) -> tuple[str, str]:
    """Split image_ref into (repo, tag). Default tag is 'latest'."""
    if ":" in image_ref.split("/")[-1]:
        parts = image_ref.rsplit(":", 1)
        return parts[0], parts[1]
    return image_ref, "latest"
