"""Single source of truth for container preview URLs.

Both the pod-spec/ingress side (``compute_manager.py``) and the runtime
status endpoint must agree on the exact hostname shape; extracting this
helper keeps them in lockstep.
"""

from __future__ import annotations

__all__ = ["container_url"]


def container_url(
    project_slug: str,
    container_dir_or_name: str,
    app_domain: str,
    protocol: str = "http",
) -> str:
    """Build the public URL for a container in a project.

    Shape: ``{protocol}://{project_slug}-{container_dir_or_name}.{app_domain}``.

    ``container_dir_or_name`` is the value used when the ingress was
    created — typically ``Container.directory`` for user projects, which
    falls back to ``Container.name`` for app-installed services.
    """
    hostname = f"{project_slug}-{container_dir_or_name}.{app_domain}"
    return f"{protocol}://{hostname}"
