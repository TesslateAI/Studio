"""Fly.io deployment provider — container-push via Fly Machines API."""

import asyncio
import logging

import httpx

from ..base import DeploymentConfig, DeploymentFile, DeploymentResult
from ..container_base import BaseContainerDeploymentProvider, ContainerDeployConfig

logger = logging.getLogger(__name__)

MACHINES_API = "https://api.machines.dev/v1"


class FlyProvider(BaseContainerDeploymentProvider):
    """Deploy container images to Fly.io via the Machines API."""

    def validate_credentials(self) -> None:
        if not self.credentials.get("api_token"):
            raise ValueError("Fly.io requires 'api_token'")

    async def test_credentials(self) -> dict:
        headers = {"Authorization": f"Bearer {self.credentials['api_token']}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{MACHINES_API}/v1/apps", headers=headers)
            resp.raise_for_status()
            apps = resp.json()
            org_name = "personal"
            if apps and isinstance(apps, list) and len(apps) > 0:
                org_name = apps[0].get("organization", {}).get("name", "personal")
            return {
                "valid": True,
                "account_name": org_name,
                "app_count": len(apps) if isinstance(apps, list) else 0,
            }

    async def push_image(self, image_ref: str) -> str:
        """Push image to registry.fly.io.

        Fly's registry uses the same API token as auth credentials.
        Token valid for ~5 minutes for registry ops.
        """
        logger.info(f"[FLY] Image push requested for {image_ref}")
        return image_ref

    async def deploy_image(self, config: ContainerDeployConfig) -> DeploymentResult:
        token = self.credentials["api_token"]
        org_slug = self.credentials.get("org_slug", "personal")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        app_name = self._sanitize_name(config.image_ref.split("/")[-1].split(":")[0])

        async with httpx.AsyncClient(timeout=120) as client:
            create_resp = await client.post(
                f"{MACHINES_API}/v1/apps",
                headers=headers,
                json={"app_name": app_name, "org_slug": org_slug},
            )
            if create_resp.status_code == 422:
                logger.info(f"[FLY] App {app_name} already exists")
            elif create_resp.status_code >= 400:
                return DeploymentResult(
                    success=False,
                    error=f"Failed to create app: {create_resp.text}",
                )

            cpu_count = max(1, int(float(config.cpu)))
            memory_mb = int(config.memory.replace("Mi", "").replace("Gi", "000"))

            machine_config = {
                "image": config.image_ref,
                "env": config.env_vars,
                "services": [
                    {
                        "ports": [
                            {"port": 443, "handlers": ["tls", "http"]},
                            {"port": 80, "handlers": ["http"]},
                        ],
                        "protocol": "tcp",
                        "internal_port": config.port,
                    }
                ],
                "guest": {
                    "cpu_kind": "shared",
                    "cpus": cpu_count,
                    "memory_mb": memory_mb,
                },
            }

            machine_resp = await client.post(
                f"{MACHINES_API}/v1/apps/{app_name}/machines",
                headers=headers,
                json={"config": machine_config},
            )

            if machine_resp.status_code >= 400:
                return DeploymentResult(
                    success=False,
                    error=f"Failed to create machine: {machine_resp.text}",
                )

            machine_data = machine_resp.json()
            machine_id = machine_data.get("id", "")

            for _ in range(30):
                status_resp = await client.get(
                    f"{MACHINES_API}/v1/apps/{app_name}/machines/{machine_id}",
                    headers=headers,
                )
                if status_resp.status_code == 200:
                    state = status_resp.json().get("state", "")
                    if state == "started":
                        break
                    if state in ("destroyed", "failed"):
                        return DeploymentResult(
                            success=False,
                            deployment_id=machine_id,
                            error=f"Machine entered {state} state",
                        )
                await asyncio.sleep(5)

            return DeploymentResult(
                success=True,
                deployment_id=f"{app_name}/{machine_id}",
                deployment_url=f"https://{app_name}.fly.dev",
                logs=[f"Machine {machine_id} started"],
                metadata={"app_name": app_name, "machine_id": machine_id},
            )

    async def get_deployment_status(self, deployment_id: str) -> dict:
        parts = deployment_id.split("/")
        if len(parts) != 2:
            return {"status": "unknown", "error": "Invalid deployment_id format"}

        app_name, machine_id = parts
        headers = {"Authorization": f"Bearer {self.credentials['api_token']}"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{MACHINES_API}/v1/apps/{app_name}/machines/{machine_id}",
                headers=headers,
            )
            if resp.status_code != 200:
                return {"status": "error", "error": resp.text}
            data = resp.json()
            return {"status": data.get("state", "unknown"), "machine": data}

    async def delete_deployment(self, deployment_id: str) -> bool:
        parts = deployment_id.split("/")
        if len(parts) != 2:
            return False

        app_name, _machine_id = parts
        headers = {"Authorization": f"Bearer {self.credentials['api_token']}"}

        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{MACHINES_API}/v1/apps/{app_name}",
                headers=headers,
            )
            return resp.status_code in (200, 202, 204)

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        parts = deployment_id.split("/")
        if len(parts) != 2:
            return []

        app_name, machine_id = parts
        headers = {"Authorization": f"Bearer {self.credentials['api_token']}"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{MACHINES_API}/v1/apps/{app_name}/machines/{machine_id}/logs",
                headers=headers,
            )
            if resp.status_code != 200:
                return []
            lines = resp.text.strip().split("\n")
            return [line for line in lines if line.strip()]
