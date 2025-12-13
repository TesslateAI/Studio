"""
Deployment Mode Enumeration

Defines the supported deployment modes for container orchestration.
This enum provides type-safe deployment mode handling throughout the codebase.
"""

from enum import Enum


class DeploymentMode(str, Enum):
    """
    Supported deployment modes for container orchestration.

    Attributes:
        DOCKER: Local development using Docker Compose + Traefik
        KUBERNETES: Production deployment using Kubernetes + NGINX Ingress
    """

    DOCKER = "docker"
    KUBERNETES = "kubernetes"

    @classmethod
    def from_string(cls, value: str) -> "DeploymentMode":
        """
        Convert a string to DeploymentMode enum.

        Args:
            value: String value ("docker" or "kubernetes")

        Returns:
            DeploymentMode enum value

        Raises:
            ValueError: If value is not a valid deployment mode
        """
        value_lower = value.lower().strip()
        for mode in cls:
            if mode.value == value_lower:
                return mode
        valid_modes = ", ".join([m.value for m in cls])
        raise ValueError(
            f"Invalid deployment mode: '{value}'. Valid modes: {valid_modes}"
        )

    @property
    def is_docker(self) -> bool:
        """Check if this is Docker deployment mode."""
        return self == DeploymentMode.DOCKER

    @property
    def is_kubernetes(self) -> bool:
        """Check if this is Kubernetes deployment mode."""
        return self == DeploymentMode.KUBERNETES

    def __str__(self) -> str:
        return self.value
