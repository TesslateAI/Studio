"""
AWS ECR + App Runner deployment provider.

Pushes container images to ECR and deploys them via AWS App Runner.
Uses boto3 for all AWS API interactions.
"""

import asyncio
import logging
from functools import partial

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from ..base import DeploymentResult
from ..container_base import BaseContainerDeploymentProvider, ContainerDeployConfig

logger = logging.getLogger(__name__)


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

    def _boto_session(self) -> boto3.Session:
        """Create a boto3 session with the provider credentials."""
        return boto3.Session(
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
        )

    async def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous boto3 call in a thread pool to avoid blocking."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def test_credentials(self) -> dict:
        """
        Verify AWS credentials via STS GetCallerIdentity.

        Returns:
            Dict with account_id and caller ARN.
        """
        try:
            session = self._boto_session()
            sts = session.client("sts")
            identity = await self._run_sync(sts.get_caller_identity)
            return {
                "valid": True,
                "account_id": identity.get("Account", ""),
                "arn": identity.get("Arn", ""),
            }
        except ClientError as e:
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            raise ValueError(f"AWS STS authentication failed: {error_msg}") from e
        except BotoCoreError as e:
            raise ValueError(f"Failed to validate AWS credentials: {e}") from e

    async def push_image(self, image_ref: str) -> str:
        """
        Get ECR authorization and return the target image URI.

        Full registry push (layer upload) requires a Docker client; this method
        prepares the auth and returns the destination URI.

        Args:
            image_ref: Source image reference (e.g. myapp:latest)

        Returns:
            ECR image URI (e.g. 123456.dkr.ecr.us-east-1.amazonaws.com/myapp:latest)
        """
        repo, tag = _parse_image_ref(image_ref)

        try:
            session = self._boto_session()
            ecr = session.client("ecr")
            response = await self._run_sync(ecr.get_authorization_token)

            auth_data = response.get("authorizationData", [{}])[0]
            proxy_endpoint = auth_data.get("proxyEndpoint", "")
            registry = proxy_endpoint.replace("https://", "").rstrip("/")

            if not registry:
                raise ValueError(
                    "ECR returned empty registry endpoint. "
                    "Check that your IAM user has ecr:GetAuthorizationToken permission."
                )

            pushed_uri = f"{registry}/{repo}:{tag}"
            logger.info("ECR push target: %s (full push requires Docker client)", pushed_uri)
            return pushed_uri

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            raise ValueError(
                f"ECR auth failed ({error_code}): {error_msg}"
            ) from e
        except BotoCoreError as e:
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

        try:
            session = self._boto_session()
            apprunner = session.client("apprunner")

            create_params = {
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
                },
                "InstanceConfiguration": {
                    "Cpu": config.cpu,
                    "Memory": config.memory,
                },
            }

            # Only include AuthenticationConfiguration if a role ARN is provided
            access_role_arn = self.credentials.get("apprunner_access_role_arn", "").strip()
            if access_role_arn:
                create_params["SourceConfiguration"]["AuthenticationConfiguration"] = {
                    "AccessRoleArn": access_role_arn,
                }

            logs.append(f"Creating App Runner service '{service_name}'...")
            response = await self._run_sync(apprunner.create_service, **create_params)

            service = response.get("Service", {})
            service_arn = service.get("ServiceArn", "")
            service_url = service.get("ServiceUrl", "")
            logs.append(f"Service created: {service_arn}")

            # Poll until RUNNING or terminal failure
            logs.append("Waiting for service to become active...")
            final_status = await self._poll_service_status(
                apprunner, service_arn, timeout=600, interval=10
            )

            if final_status == "RUNNING":
                described = await self._run_sync(
                    apprunner.describe_service, ServiceArn=service_arn
                )
                live_url = f"https://{described.get('Service', {}).get('ServiceUrl', service_url)}"
                logs.append(f"Service running at {live_url}")
                return DeploymentResult(
                    success=True,
                    deployment_id=service_arn,
                    deployment_url=live_url,
                    logs=logs,
                    metadata={"service_arn": service_arn},
                )

            logs.append(f"Service creation failed with status: {final_status}")
            return DeploymentResult(
                success=False,
                deployment_id=service_arn,
                error=f"App Runner service {final_status}",
                logs=logs,
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            msg = f"App Runner API error ({error_code}): {error_msg}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)
        except BotoCoreError as e:
            msg = f"AWS SDK error: {e}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)
        except TimeoutError as e:
            logs.append(str(e))
            return DeploymentResult(success=False, error="Service creation timed out", logs=logs)
        except Exception as e:
            msg = f"Deployment failed: {e}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)

    async def _poll_service_status(
        self, apprunner, service_arn: str, timeout: int = 600, interval: int = 10
    ) -> str:
        """Poll App Runner service until it reaches a terminal state."""
        terminal_states = {"RUNNING", "CREATE_FAILED", "DELETED", "DELETE_FAILED", "PAUSED"}
        elapsed = 0
        while elapsed < timeout:
            described = await self._run_sync(
                apprunner.describe_service, ServiceArn=service_arn
            )
            status = described.get("Service", {}).get("Status", "UNKNOWN")
            if status in terminal_states:
                return status
            await asyncio.sleep(interval)
            elapsed += interval
        raise TimeoutError(f"Service {service_arn} did not reach terminal state in {timeout}s")

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """Get App Runner service status by service ARN."""
        try:
            session = self._boto_session()
            apprunner = session.client("apprunner")
            described = await self._run_sync(
                apprunner.describe_service, ServiceArn=deployment_id
            )
            service = described.get("Service", {})
            return {
                "status": service.get("Status", "UNKNOWN"),
                "url": service.get("ServiceUrl"),
                "updated_at": service.get("UpdatedAt"),
            }
        except Exception as e:
            return {"status": "unknown", "error": str(e)}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """Delete an App Runner service by ARN."""
        try:
            session = self._boto_session()
            apprunner = session.client("apprunner")
            await self._run_sync(
                apprunner.delete_service, ServiceArn=deployment_id
            )
            return True
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch deployment logs. CloudWatch integration required for full logs.

        Returns:
            Empty list (CloudWatch Logs integration not implemented).
        """
        return ["CloudWatch Logs integration required for App Runner logs"]


def _parse_image_ref(image_ref: str) -> tuple[str, str]:
    """Split image_ref into (repo, tag). Default tag is 'latest'."""
    if ":" in image_ref.split("/")[-1]:
        parts = image_ref.rsplit(":", 1)
        return parts[0], parts[1]
    return image_ref, "latest"
