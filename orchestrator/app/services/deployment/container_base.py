"""Base class for container-push deployment providers (AWS ECS, GCP Cloud Run, etc.)."""

from abc import abstractmethod

from pydantic import BaseModel, Field

from .base import BaseDeploymentProvider, DeploymentConfig, DeploymentFile, DeploymentResult


class ContainerDeployConfig(BaseModel):
    """Configuration specific to container-push deployments."""

    image_ref: str = Field(..., description="Full image reference (registry/repo:tag)")
    port: int = Field(default=8080)
    cpu: str = Field(default="0.25")
    memory: str = Field(default="512Mi")
    env_vars: dict[str, str] = Field(default_factory=dict)
    region: str = Field(default="us-east-1")


class BaseContainerDeploymentProvider(BaseDeploymentProvider):
    """Abstract base for providers that deploy pre-built container images."""

    @abstractmethod
    async def push_image(self, image_ref: str) -> str:
        """Push a Docker image to the provider's registry. Returns the pushed image URI."""
        pass

    @abstractmethod
    async def deploy_image(self, config: ContainerDeployConfig) -> DeploymentResult:
        """Deploy a pushed image to compute. Returns deployment result."""
        pass

    async def deploy(
        self, files: list[DeploymentFile], config: DeploymentConfig
    ) -> DeploymentResult:
        """Container providers don't use file-based deploy. Override in subclass or raise."""
        raise NotImplementedError(
            "Container providers use push_image + deploy_image, not file-based deploy"
        )
