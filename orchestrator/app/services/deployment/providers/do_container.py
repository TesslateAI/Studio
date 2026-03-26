"""
DigitalOcean DOCR + App Platform deployment provider.

Pushes container images to DigitalOcean Container Registry and deploys
them via the App Platform.
"""

import logging

import httpx

from ..base import DeploymentResult
from ..container_base import BaseContainerDeploymentProvider, ContainerDeployConfig
from .utils import poll_until_terminal

logger = logging.getLogger(__name__)

DO_API_BASE = "https://api.digitalocean.com/v2"


class DigitalOceanContainerProvider(BaseContainerDeploymentProvider):
    """
    DigitalOcean DOCR + App Platform deployment provider.

    Pushes container images to DigitalOcean Container Registry (DOCR)
    and deploys them on App Platform for managed container hosting.
    """

    def validate_credentials(self) -> None:
        """Validate required DigitalOcean credentials."""
        required = ("api_token", "registry_name")
        missing = [k for k in required if not self.credentials.get(k)]
        if missing:
            raise ValueError(
                f"Missing required DigitalOcean credentials: {', '.join(missing)}"
            )

    @property
    def _token(self) -> str:
        return self.credentials["api_token"]

    @property
    def _registry_name(self) -> str:
        return self.credentials["registry_name"]

    def _bearer_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def test_credentials(self) -> dict:
        """
        Verify DigitalOcean API token by fetching account info.

        Returns:
            Dict with account email and UUID.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{DO_API_BASE}/account", headers=self._bearer_headers()
                )
                resp.raise_for_status()
                account = resp.json().get("account", {})
                return {
                    "valid": True,
                    "email": account.get("email"),
                    "uuid": account.get("uuid"),
                    "status": account.get("status"),
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid DigitalOcean API token") from e
            raise ValueError(
                f"DigitalOcean API error: HTTP {e.response.status_code}"
            ) from e
        except httpx.TimeoutException as e:
            raise ValueError("Connection to DigitalOcean API timed out") from e
        except Exception as e:
            raise ValueError(f"Failed to validate credentials: {e}") from e

    async def push_image(self, image_ref: str) -> str:
        """
        Push a container image to DigitalOcean Container Registry.

        Prepares registry credentials and returns the target URI.
        Full layer-level push requires a Docker client.

        Args:
            image_ref: Source image reference (e.g. myapp:latest)

        Returns:
            DOCR image URI (e.g. registry.digitalocean.com/myregistry/myapp:latest)
        """
        repo, tag = _parse_image_ref(image_ref)
        registry_host = f"registry.digitalocean.com/{self._registry_name}"
        pushed_uri = f"{registry_host}/{repo}:{tag}"

        try:
            # Validate registry access
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{DO_API_BASE}/registry", headers=self._bearer_headers()
                )
                resp.raise_for_status()

            logger.info(
                "DOCR push target: %s (credentials: token as username+password)", pushed_uri
            )
            return pushed_uri
        except Exception as e:
            raise ValueError(f"Failed to prepare DOCR push: {e}") from e

    async def deploy_image(self, config: ContainerDeployConfig) -> DeploymentResult:
        """
        Deploy a container image to DigitalOcean App Platform.

        Args:
            config: Container deployment configuration.

        Returns:
            DeploymentResult with App Platform URL.
        """
        logs: list[str] = []
        app_name = config.image_ref.split("/")[-1].split(":")[0][:32]
        repo, tag = _parse_image_ref(config.image_ref)

        env_list = [
            {"key": k, "value": v, "scope": "RUN_AND_BUILD_TIME"}
            for k, v in config.env_vars.items()
        ]

        app_spec = {
            "name": app_name,
            "region": _map_do_region(config.region),
            "services": [
                {
                    "name": app_name,
                    "image": {
                        "registry_type": "DOCR",
                        "repository": repo,
                        "tag": tag,
                    },
                    "instance_count": 1,
                    "instance_size_slug": _map_instance_size(config.cpu, config.memory),
                    "http_port": config.port,
                    "envs": env_list,
                }
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                logs.append(f"Creating App Platform app '{app_name}'...")
                resp = await client.post(
                    f"{DO_API_BASE}/apps",
                    json={"spec": app_spec},
                    headers=self._bearer_headers(),
                )
                resp.raise_for_status()
                data = resp.json()

                app = data.get("app", {})
                app_id = app.get("id", "")
                logs.append(f"App created: {app_id}")

                # Poll deployments until active
                logs.append("Waiting for deployment to become active...")
                final = await poll_until_terminal(
                    check_fn=lambda: self._get_latest_deployment_phase(client, app_id),
                    terminal_states={"ACTIVE", "ERROR", "CANCELED"},
                    status_key="phase",
                    interval=10,
                    timeout=600,
                )

                phase = final.get("phase", "UNKNOWN")
                if phase == "ACTIVE":
                    live_url = final.get("live_url", f"https://{app_name}.ondigitalocean.app")
                    logs.append(f"App deployed at {live_url}")
                    return DeploymentResult(
                        success=True,
                        deployment_id=app_id,
                        deployment_url=live_url,
                        logs=logs,
                        metadata={"app_id": app_id},
                    )

                logs.append(f"Deployment failed with phase: {phase}")
                return DeploymentResult(
                    success=False,
                    deployment_id=app_id,
                    error=f"App Platform deployment {phase}",
                    logs=logs,
                )

        except TimeoutError as e:
            logs.append(str(e))
            return DeploymentResult(
                success=False, error="App Platform deployment timed out", logs=logs
            )
        except httpx.HTTPStatusError as e:
            msg = f"DigitalOcean API error: HTTP {e.response.status_code} - {e.response.text}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)
        except Exception as e:
            msg = f"Deployment failed: {e}"
            logs.append(msg)
            return DeploymentResult(success=False, error=msg, logs=logs)

    async def _get_latest_deployment_phase(
        self, client: httpx.AsyncClient, app_id: str
    ) -> dict:
        """Fetch the latest deployment phase and app-level live_url."""
        # Fetch the app object to get the authoritative live_url
        app_resp = await client.get(
            f"{DO_API_BASE}/apps/{app_id}",
            headers=self._bearer_headers(),
        )
        app_resp.raise_for_status()
        app = app_resp.json().get("app", {})
        app_live_url = app.get("live_url", "")

        # Fetch deployments for the current phase
        resp = await client.get(
            f"{DO_API_BASE}/apps/{app_id}/deployments",
            headers=self._bearer_headers(),
        )
        resp.raise_for_status()
        deployments = resp.json().get("deployments", [])

        if not deployments:
            return {"phase": "PENDING", "live_url": app_live_url}

        latest = deployments[0]
        return {
            "phase": latest.get("phase", "UNKNOWN"),
            "deployment_id": latest.get("id"),
            "live_url": app_live_url,
        }

    async def get_deployment_status(self, deployment_id: str) -> dict:
        """Get App Platform app status by app ID."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{DO_API_BASE}/apps/{deployment_id}",
                    headers=self._bearer_headers(),
                )
                resp.raise_for_status()
                app = resp.json().get("app", {})

                # phase lives on the deployment sub-objects, not the app;
                # prefer in_progress_deployment, fall back to active_deployment
                in_prog = app.get("in_progress_deployment") or {}
                active = app.get("active_deployment") or {}
                deployment = in_prog if in_prog else active
                phase = deployment.get("phase", "UNKNOWN")

                return {
                    "status": phase,
                    "url": app.get("live_url"),
                    "updated_at": app.get("updated_at"),
                }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"status": "unknown", "error": f"App '{deployment_id}' not found on DigitalOcean"}
            return {"status": "unknown", "error": f"DigitalOcean API error (HTTP {e.response.status_code})"}
        except httpx.TimeoutException:
            return {"status": "unknown", "error": "Request to DigitalOcean API timed out"}
        except Exception as e:
            return {"status": "unknown", "error": f"Failed to fetch deployment status: {e}"}

    async def delete_deployment(self, deployment_id: str) -> bool:
        """Delete an App Platform app by app ID."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    f"{DO_API_BASE}/apps/{deployment_id}",
                    headers=self._bearer_headers(),
                )
                return resp.status_code in (200, 204)
        except Exception:
            return False

    async def get_deployment_logs(self, deployment_id: str) -> list[str]:
        """
        Fetch deployment logs from App Platform.

        Args:
            deployment_id: App Platform app ID.

        Returns:
            List of log lines from the latest deployment.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get latest deployment ID
                dep_resp = await client.get(
                    f"{DO_API_BASE}/apps/{deployment_id}/deployments",
                    headers=self._bearer_headers(),
                )
                dep_resp.raise_for_status()
                deployments = dep_resp.json().get("deployments", [])

                if not deployments:
                    return ["No deployments found"]

                latest_dep_id = deployments[0].get("id", "")

                # Fetch aggregated logs
                log_resp = await client.get(
                    f"{DO_API_BASE}/apps/{deployment_id}/deployments/{latest_dep_id}/logs",
                    params={"type": "BUILD", "follow": "false"},
                    headers=self._bearer_headers(),
                    timeout=15.0,
                )
                if log_resp.status_code == 200:
                    data = log_resp.json()
                    urls = data.get("historic_urls", [])
                    if urls:
                        # Fetch actual log content from the first URL
                        content_resp = await client.get(urls[0], timeout=15.0)
                        if content_resp.status_code == 200:
                            lines = content_resp.text.strip().splitlines()
                            return lines if lines else ["No logs available"]
                    return ["No log URLs available"]
                return [f"Failed to fetch logs: HTTP {log_resp.status_code}"]
        except Exception as e:
            return [f"Error fetching logs: {e}"]


def _parse_image_ref(image_ref: str) -> tuple[str, str]:
    """Split image_ref into (repo, tag). Default tag is 'latest'."""
    last_segment = image_ref.split("/")[-1]
    if ":" in last_segment:
        parts = image_ref.rsplit(":", 1)
        # Strip registry prefix if present for DOCR repo name
        repo = parts[0].split("/")[-1]
        return repo, parts[1]
    return image_ref.split("/")[-1], "latest"


def _map_do_region(region: str) -> str:
    """Map generic region identifiers to DigitalOcean region slugs."""
    region_map = {
        "us-east-1": "nyc",
        "us-west-1": "sfo",
        "us-west-2": "sfo",
        "eu-west-1": "ams",
        "eu-central-1": "fra",
        "ap-southeast-1": "sgp",
        "ap-south-1": "blr",
    }
    return region_map.get(region, region[:3] if len(region) >= 3 else "nyc")


def _map_instance_size(cpu: str, memory: str) -> str:
    """Map CPU/memory specs to a DigitalOcean App Platform instance size slug."""
    try:
        cpu_val = float(cpu)
    except (ValueError, TypeError):
        cpu_val = 0.25

    if cpu_val <= 0.25:
        return "basic-xxs"
    if cpu_val <= 0.5:
        return "basic-xs"
    if cpu_val <= 1:
        return "basic-s"
    if cpu_val <= 2:
        return "basic-m"
    return "professional-s"
