"""
Azure ACR + Container Apps deployment provider.

Pushes container images to Azure Container Registry and deploys them
via Azure Container Apps.
"""

import logging

import httpx

from ..base import DeploymentResult
from ..container_base import BaseContainerDeploymentProvider, ContainerDeployConfig
from .utils import poll_until_terminal

logger = logging.getLogger(__name__)

AZURE_LOGIN_URL = "https://login.microsoftonline.com"
AZURE_MGMT_URL = "https://management.azure.com"
CONTAINER_APPS_API = "2024-03-01"


class AzureContainerProvider(BaseContainerDeploymentProvider):
    """
    Azure ACR + Container Apps deployment provider.

    Pushes container images to Azure Container Registry and deploys
    them on Azure Container Apps for managed serverless containers.
    """

    def validate_credentials(self) -> None:
        """Validate all required Azure credentials are present."""
        required = (
            "tenant_id",
            "client_id",
            "client_secret",
            "subscription_id",
            "resource_group",
            "registry_name",
            "container_app_environment_id",
        )
        missing = [k for k in required if not self.credentials.get(k)]
        if missing:
            raise ValueError(f"Missing required Azure credentials: {', '.join(missing)}")

        if "azure_region" not in self.credentials:
            self.credentials = {**self.credentials, "azure_region": "eastus"}

    @property
    def _tenant_id(self) -> str:
        return self.credentials["tenant_id"]

    @property
    def _client_id(self) -> str:
        return self.credentials["client_id"]

    @property
    def _client_secret(self) -> str:
        return self.credentials["client_secret"]

    @property
    def _subscription_id(self) -> str:
        return self.credentials["subscription_id"]

    @property
    def _resource_group(self) -> str:
        return self.credentials["resource_group"]

    @property
    def _registry_name(self) -> str:
        return self.credentials["registry_name"]

    @property
    def _region(self) -> str:
        return self.credentials["azure_region"]

    async def _get_access_token(self) -> str:
        """
        Obtain an Azure AD access token via client_credentials grant.

        Returns:
            Bearer access token string.
        """
        url = f"{AZURE_LOGIN_URL}/{self._tenant_id}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": "https://management.azure.com/.default",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, data=data)
            resp.raise_for_status()
            return resp.json()["access_token"]

    def _bearer_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def test_credentials(self) -> dict:
        """
        Verify Azure credentials by checking subscription access.

        Returns:
            Dict with subscription info.
        """
        try:
            token = await self._get_access_token()
            url = (
                f"{AZURE_MGMT_URL}/subscriptions/{self._subscription_id}"
                f"?api-version=2022-12-01"
            )
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=self._bearer_headers(token))
                resp.raise_for_status()
                data = resp.json()
                return {
                    "valid": True,
                    "subscription_id": data.get("subscriptionId"),
                    "display_name": data.get("displayName"),
                    "state": data.get("state"),
                }
        except httpx.HTTPStatusError as e:
            raise ValueError(
                f"Azure authentication failed: HTTP {e.response.status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to Azure API timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate Azure credentials: {e}") from e

    async def push_image(self, image_ref: str) -> str:
        """
        Push a container image to Azure Container Registry.

        Prepares ACR authentication and returns the target image URI.
        Full layer-level push requires a Docker client.

        Args:
            image_ref: Source image reference (e.g. myapp:latest)

        Returns:
            ACR image URI (e.g. myregistry.azurecr.io/myapp:latest)
        """
        repo, tag = _parse_image_ref(image_ref)
        acr_host = f"{self._registry_name}.azurecr.io"
        pushed_uri = f"{acr_host}/{repo}:{tag}"

        try:
            # Validate ACR access by fetching a catalog listing
            await self._get_acr_token(repo)
            logger.info(
                "ACR push target: %s (full push requires Docker client)", pushed_uri
            )
            return pushed_uri
        except Exception as e:
            raise ValueError(f"Failed to prepare ACR push: {e}") from e

    async def _get_acr_token(self, repo: str) -> str:
        """Exchange Azure AD token for an ACR refresh/access token."""
        acr_host = f"{self._registry_name}.azurecr.io"
        url = f"https://{acr_host}/oauth2/exchange"
        ad_token = await self._get_access_token()

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                data={
                    "grant_type": "access_token",
                    "service": acr_host,
                    "tenant": self._tenant_id,
                    "access_token": ad_token,
                },
            )
            resp.raise_for_status()
            refresh_token = resp.json()["refresh_token"]

            # Exchange refresh token for access token scoped to repo
            token_resp = await client.post(
                f"https://{acr_host}/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "service": acr_host,
                    "scope": f"repository:{repo}:push,pull",
                    "refresh_token": refresh_token,
                },
            )
            token_resp.raise_for_status()
            return token_resp.json()["access_token"]

    async def deploy_image(self, config: ContainerDeployConfig) -> DeploymentResult:
        """
        Deploy a container image to Azure Container Apps.

        Args:
            config: Container deployment configuration.

        Returns:
            DeploymentResult with Container App URL.
        """
        logs: list[str] = []
        app_name = config.image_ref.split("/")[-1].split(":")[0][:32]

        try:
            token = await self._get_access_token()
            headers = self._bearer_headers(token)

            url = (
                f"{AZURE_MGMT_URL}/subscriptions/{self._subscription_id}"
                f"/resourceGroups/{self._resource_group}"
                f"/providers/Microsoft.App/containerApps/{app_name}"
                f"?api-version={CONTAINER_APPS_API}"
            )

            env_list = [{"name": k, "value": v} for k, v in config.env_vars.items()]

            acr_host = f"{self._registry_name}.azurecr.io"
            body = {
                "location": self._region,
                "properties": {
                    "environmentId": self.credentials.get(
                        "container_app_environment_id", ""
                    ),
                    "configuration": {
                        "ingress": {
                            "external": True,
                            "targetPort": config.port,
                        },
                        "registries": [
                            {
                                "server": acr_host,
                                "username": self._client_id,
                                "passwordSecretRef": "acr-password",
                            }
                        ],
                        "secrets": [
                            {"name": "acr-password", "value": self._client_secret}
                        ],
                    },
                    "template": {
                        "containers": [
                            {
                                "name": app_name,
                                "image": config.image_ref,
                                "env": env_list,
                                "resources": {
                                    "cpu": float(config.cpu),
                                    "memory": _normalize_memory_to_gi(config.memory),
                                },
                            }
                        ],
                    },
                },
            }

            logs.append(f"Creating Container App '{app_name}' in {self._region}...")

            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.put(url, json=body, headers=headers)
                resp.raise_for_status()

                logs.append("Waiting for provisioning to complete...")
                final = await poll_until_terminal(
                    check_fn=lambda: self._get_container_app(app_name, token),
                    terminal_states={"Succeeded", "Failed", "Canceled"},
                    status_key="provisioningState",
                    interval=10,
                    timeout=600,
                )

                state = final.get("provisioningState", "Unknown")
                if state == "Succeeded":
                    fqdn = final.get("properties", {}).get("configuration", {}).get(
                        "ingress", {}
                    ).get("fqdn", "")
                    live_url = f"https://{fqdn}" if fqdn else ""
                    logs.append(f"Container App deployed at {live_url}")
                    return DeploymentResult(
                        success=True,
                        deployment_id=app_name,
                        deployment_url=live_url,
                        logs=logs,
                        metadata={"resource_group": self._resource_group},
                    )

                logs.append(f"Provisioning failed: {state}")
                return DeploymentResult(
                    success=False,
                    deployment_id=app_name,
                    error=f"Container App provisioning {state}",
                    logs=logs,
                )

        except TimeoutError as e:
            logs.append(str(e))
            return DeploymentResult(
                success=False, error="Container App provisioning timed out", logs=logs
            )
        except httpx.HTTPStatusError as e:
            msg = f"Azure API error: HTTP {e.response.status_code} - {e.response.text}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)
        except Exception as e:
            msg = f"Deployment failed: {e}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)

    async def _get_container_app(self, app_name: str, token: str) -> dict:
        """Fetch Container App status for polling."""
        url = (
            f"{AZURE_MGMT_URL}/subscriptions/{self._subscription_id}"
            f"/resourceGroups/{self._resource_group}"
            f"/providers/Microsoft.App/containerApps/{app_name}"
            f"?api-version={CONTAINER_APPS_API}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self._bearer_headers(token))
            resp.raise_for_status()
            data = resp.json()
            return {
                "provisioningState": data.get("properties", {}).get(
                    "provisioningState", "Unknown"
                ),
                "properties": data.get("properties", {}),
            }

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """Get Container App status by name."""
        try:
            token = await self._get_access_token()
            result = await self._get_container_app(deployment_id, token)
            props = result.get("properties", {})
            fqdn = props.get("configuration", {}).get("ingress", {}).get("fqdn", "")
            return {
                "status": result.get("provisioningState", "Unknown"),
                "url": f"https://{fqdn}" if fqdn else None,
            }
        except Exception as e:
            return {"status": "unknown", "error": str(e)}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a Container App by name."""
        try:
            token = await self._get_access_token()
            url = (
                f"{AZURE_MGMT_URL}/subscriptions/{self._subscription_id}"
                f"/resourceGroups/{self._resource_group}"
                f"/providers/Microsoft.App/containerApps/{deployment_id}"
                f"?api-version={CONTAINER_APPS_API}"
            )
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(url, headers=self._bearer_headers(token))
                return resp.status_code in (200, 202, 204)
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch deployment logs. Azure Monitor integration required for full logs.

        Returns:
            Empty list (Azure Monitor / Log Analytics integration not implemented).
        """
        return ["Azure Monitor integration required for Container Apps logs"]


def _normalize_memory_to_gi(memory: str) -> str:
    """
    Normalize a memory string to the ``Gi`` format required by Azure Container Apps.

    Accepted inputs:
        - Already in Gi (e.g. ``"0.5Gi"``, ``"1Gi"``) -- returned as-is.
        - Mi suffix (e.g. ``"512Mi"``) -- converted to Gi (``"0.5Gi"``).
        - Plain number (e.g. ``"1"``, ``"2.5"``) -- treated as Gi (``"1Gi"``).
        - Anything else -- logged as a warning and passed through unchanged.
    """
    value = memory.strip()

    if value.endswith("Gi"):
        return value

    if value.endswith("Mi"):
        mi_part = value[:-2]
        try:
            gi_value = float(mi_part) / 1024
            # Use a clean representation: drop trailing zeros
            normalized = f"{gi_value:g}Gi"
            logger.info(
                "Converted memory '%s' to '%s' for Azure Container Apps",
                memory,
                normalized,
            )
            return normalized
        except ValueError:
            logger.warning(
                "Unrecognizable Mi memory value '%s'; passing through to Azure as-is",
                memory,
            )
            return value

    # Plain number (no suffix) -- assume Gi
    try:
        float(value)
        normalized = f"{value}Gi"
        logger.info(
            "Memory '%s' has no unit suffix; assuming Gi ('%s') for Azure Container Apps",
            memory,
            normalized,
        )
        return normalized
    except ValueError:
        pass

    logger.warning(
        "Unrecognizable memory format '%s'; passing through to Azure as-is. "
        "Azure Container Apps expects values like '0.5Gi' or '1Gi'.",
        memory,
    )
    return value


def _parse_image_ref(image_ref: str) -> tuple[str, str]:
    """Split image_ref into (repo, tag). Default tag is 'latest'."""
    last_segment = image_ref.split("/")[-1]
    if ":" in last_segment:
        parts = image_ref.rsplit(":", 1)
        return parts[0], parts[1]
    return image_ref, "latest"
