"""
Deployment Mode Enumeration

Defines the supported deployment modes for container orchestration.
This enum provides type-safe deployment mode handling throughout the codebase.
"""

from enum import StrEnum


class DeploymentMode(StrEnum):
    """
    Supported deployment modes for container orchestration.

    Attributes:
        DOCKER: Local development using Docker Compose + Traefik
        KUBERNETES: Production deployment using Kubernetes + NGINX Ingress
        LOCAL: Direct filesystem + subprocess execution on the host machine
            (no container isolation — used for sandboxed benchmark environments)
        DESKTOP: Shell mode for the Tauri desktop client. Projects still resolve
            per-project (local | docker | k8s-remote) via Project.runtime; this
            value only marks the orchestrator-wide deployment shell.
    """

    DOCKER = "docker"
    KUBERNETES = "kubernetes"
    LOCAL = "local"
    DESKTOP = "desktop"

    @classmethod
    def from_string(cls, value: str) -> "DeploymentMode":
        """
        Convert a string to DeploymentMode enum.

        Args:
            value: String value ("docker", "kubernetes", or "local")

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
        raise ValueError(f"Invalid deployment mode: '{value}'. Valid modes: {valid_modes}")

    @property
    def is_docker(self) -> bool:
        """Check if this is Docker deployment mode."""
        return self == DeploymentMode.DOCKER

    @property
    def is_kubernetes(self) -> bool:
        """Check if this is Kubernetes deployment mode."""
        return self == DeploymentMode.KUBERNETES

    @property
    def is_local(self) -> bool:
        """Check if this is local (filesystem + subprocess) deployment mode."""
        return self == DeploymentMode.LOCAL

    @property
    def is_desktop(self) -> bool:
        """Check if this is the desktop (Tauri shell) deployment mode."""
        return self == DeploymentMode.DESKTOP

    def __str__(self) -> str:
        return self.value
