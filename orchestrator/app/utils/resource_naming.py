"""
Resource naming utilities for users and projects.

Centralized functions for generating consistent identifiers across:
- File system paths
- Container/pod names
- URLs and hostnames
- Database queries

Uses UUIDs to ensure:
- Non-enumerable (secure)
- Collision-free
- Distributed system compatible
- URL-safe
"""

from typing import Union
from uuid import UUID


def get_project_path(user_id: Union[UUID, str], project_id: Union[UUID, str]) -> str:
    """
    Get file system path for a project.

    Used for:
    - Docker: Volume mount paths
    - Kubernetes: PVC subpaths
    - Local file operations

    Args:
        user_id: User UUID (can be UUID or string)
        project_id: Project UUID (can be UUID or string)

    Returns:
        Path string: "users/{user_id}/{project_id}"

    Examples:
        >>> get_project_path(user_id, project_id)
        "users/550e8400-e29b-41d4-a716-446655440000/7c9e6679-7425-40de-944b-e07fc1f90ae7"
    """
    return f"users/{str(user_id)}/{str(project_id)}"


def get_container_name(user_id: Union[UUID, str], project_id: Union[UUID, str], mode: str = "docker") -> str:
    """
    Get container/pod name for a project's development environment.

    Args:
        user_id: User UUID
        project_id: Project UUID
        mode: "docker" or "kubernetes" (default: "docker")

    Returns:
        Container/pod name string

    Examples:
        >>> get_container_name(user_id, project_id, "docker")
        "tesslate-dev-550e8400-e29b-41d4-a716-446655440000-7c9e6679-7425-40de-944b-e07fc1f90ae7"

        >>> get_container_name(user_id, project_id, "kubernetes")
        "dev-550e8400-e29b-41d4-a716-446655440000-7c9e6679-7425-40de-944b-e07fc1f90ae7"
    """
    user_str = str(user_id)
    project_str = str(project_id)

    if mode == "kubernetes":
        # Kubernetes naming: shorter prefix, no "tesslate-" branding
        # Must be DNS-1123 compliant: lowercase alphanumeric + hyphens
        return f"dev-{user_str}-{project_str}"
    else:
        # Docker naming: include branding prefix
        return f"tesslate-dev-{user_str}-{project_str}"


def get_short_container_name(user_id: Union[UUID, str], project_id: Union[UUID, str]) -> str:
    """
    Get shortened container/pod name using first 8 chars of UUIDs.

    Use this for labels, tags, or display purposes where full UUID is too long.
    NOT recommended for actual container names (use get_container_name instead).

    Args:
        user_id: User UUID
        project_id: Project UUID

    Returns:
        Shortened name string

    Example:
        >>> get_short_container_name(user_id, project_id)
        "dev-550e8400-7c9e6679"
    """
    user_short = str(user_id)[:8]
    project_short = str(project_id)[:8]
    return f"dev-{user_short}-{project_short}"


def get_dev_hostname(user_id: Union[UUID, str], project_id: Union[UUID, str], base_domain: str = "localhost") -> str:
    """
    Get development server hostname/URL.

    Args:
        user_id: User UUID
        project_id: Project UUID
        base_domain: Base domain (default: "localhost")

    Returns:
        Full hostname string

    Examples:
        >>> get_dev_hostname(user_id, project_id)
        "550e8400-e29b-41d4-a716-446655440000-7c9e6679-7425-40de-944b-e07fc1f90ae7.localhost"

        >>> get_dev_hostname(user_id, project_id, "studio-test.tesslate.com")
        "550e8400-e29b-41d4-a716-446655440000-7c9e6679-7425-40de-944b-e07fc1f90ae7.studio-test.tesslate.com"
    """
    container_name = get_container_name(user_id, project_id, mode="kubernetes")
    # Remove "dev-" prefix for hostname (shorter URLs)
    name_without_prefix = container_name.replace("dev-", "")
    return f"{name_without_prefix}.{base_domain}"


def get_kubectl_exec_prefix(user_id: Union[UUID, str], project_id: Union[UUID, str], namespace: str = "tesslate-user-environments") -> str:
    """
    Get kubectl exec command prefix for executing commands in user's pod.

    Args:
        user_id: User UUID
        project_id: Project UUID
        namespace: Kubernetes namespace (default: "tesslate-user-environments")

    Returns:
        kubectl exec command prefix

    Example:
        >>> get_kubectl_exec_prefix(user_id, project_id)
        "kubectl exec -n tesslate-user-environments dev-550e8400-e29b-41d4-a716-446655440000-7c9e6679-7425-40de-944b-e07fc1f90ae7 --"
    """
    pod_name = get_container_name(user_id, project_id, mode="kubernetes")
    return f"kubectl exec -n {namespace} {pod_name} --"


def get_docker_exec_prefix(user_id: Union[UUID, str], project_id: Union[UUID, str]) -> str:
    """
    Get docker exec command prefix for executing commands in user's container.

    Args:
        user_id: User UUID
        project_id: Project UUID

    Returns:
        docker exec command prefix

    Example:
        >>> get_docker_exec_prefix(user_id, project_id)
        "docker exec tesslate-dev-550e8400-e29b-41d4-a716-446655440000-7c9e6679-7425-40de-944b-e07fc1f90ae7"
    """
    container_name = get_container_name(user_id, project_id, mode="docker")
    return f"docker exec {container_name}"


def parse_container_name(container_name: str) -> tuple[str, str]:
    """
    Extract user_id and project_id from a container/pod name.

    Args:
        container_name: Container or pod name

    Returns:
        Tuple of (user_id, project_id) as strings

    Raises:
        ValueError: If container name format is invalid

    Examples:
        >>> parse_container_name("dev-550e8400-e29b-41d4-a716-446655440000-7c9e6679-7425-40de-944b-e07fc1f90ae7")
        ("550e8400-e29b-41d4-a716-446655440000", "7c9e6679-7425-40de-944b-e07fc1f90ae7")

        >>> parse_container_name("tesslate-dev-550e8400-e29b-41d4-a716-446655440000-7c9e6679-7425-40de-944b-e07fc1f90ae7")
        ("550e8400-e29b-41d4-a716-446655440000", "7c9e6679-7425-40de-944b-e07fc1f90ae7")
    """
    # Remove common prefixes
    name = container_name.replace("tesslate-dev-", "").replace("dev-", "")

    # UUIDs are 36 characters (32 hex + 4 hyphens)
    # Format: {user_uuid}-{project_uuid}
    if len(name) < 73:  # 36 + 1 + 36 = 73 minimum
        raise ValueError(f"Invalid container name format: {container_name}")

    # Extract user and project UUIDs
    user_id = name[:36]
    project_id = name[37:73]  # Skip the hyphen separator

    # Validate UUID format
    try:
        UUID(user_id)
        UUID(project_id)
    except ValueError as e:
        raise ValueError(f"Invalid UUID in container name: {container_name}") from e

    return user_id, project_id


def parse_hostname(hostname: str) -> tuple[str, str]:
    """
    Extract user_id and project_id from a development server hostname.

    Args:
        hostname: Full hostname (e.g., "user-project.localhost")

    Returns:
        Tuple of (user_id, project_id) as strings

    Raises:
        ValueError: If hostname format is invalid

    Example:
        >>> parse_hostname("550e8400-e29b-41d4-a716-446655440000-7c9e6679-7425-40de-944b-e07fc1f90ae7.localhost")
        ("550e8400-e29b-41d4-a716-446655440000", "7c9e6679-7425-40de-944b-e07fc1f90ae7")
    """
    # Extract subdomain (everything before first dot)
    subdomain = hostname.split('.')[0]

    # Parse as container name
    return parse_container_name(f"dev-{subdomain}")
