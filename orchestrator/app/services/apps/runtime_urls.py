"""Single source of truth for container preview URLs.

Both the pod-spec/ingress side (``compute_manager.py``) and the runtime
status endpoint must agree on the exact hostname shape; extracting this
helper keeps them in lockstep.

``app_container_url`` emits the creator-branded form for installed
AppInstance containers; ``container_url`` emits the legacy slug-based
form for non-app source projects. Both shapes fit under the existing
``*.{app_domain}`` wildcard cert (single-level subdomain).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ...models import Container

__all__ = [
    "container_url",
    "app_container_url",
    "resolve_app_url_for_container",
]


def container_url(
    project_slug: str,
    container_dir_or_name: str,
    app_domain: str,
    protocol: str = "http",
) -> str:
    """Build the public URL for a container in a non-app user project.

    Shape: ``{protocol}://{project_slug}-{container_dir_or_name}.{app_domain}``.

    ``container_dir_or_name`` is the value used when the ingress was
    created — typically ``Container.directory`` for user projects, which
    falls back to ``Container.name`` for app-installed services.
    """
    hostname = f"{project_slug}-{container_dir_or_name}.{app_domain}"
    return f"{protocol}://{hostname}"


def app_container_url(
    app_handle: str,
    creator_handle: str,
    container_dir: str,
    app_domain: str,
    protocol: str = "http",
    *,
    only_primary: bool = False,
) -> str:
    """Build the creator-branded URL for an installed AppInstance container.

    Multi-container shape: ``{protocol}://{container_dir}-{app_handle}-{creator_handle}.{app_domain}``
    Single-container (only_primary=True): ``{protocol}://{app_handle}-{creator_handle}.{app_domain}``

    All handle components must already be DNS-label-clean (lowercase
    alphanumeric + hyphens, start/end alphanumeric). Validation is
    enforced at the model / endpoint boundary; this builder trusts its
    inputs.
    """
    if only_primary:
        hostname = f"{app_handle}-{creator_handle}.{app_domain}"
    else:
        hostname = f"{container_dir}-{app_handle}-{creator_handle}.{app_domain}"
    return f"{protocol}://{hostname}"


async def resolve_app_url_for_container(
    db: "AsyncSession",
    container: "Container",
    *,
    protocol: str = "http",
) -> str | None:
    """Resolve the creator-branded URL for an AppInstance container.

    Loads Container -> Project -> AppInstance -> MarketplaceApp -> User
    and assembles the URL from the two handles. Returns ``None`` if any
    handle is missing — caller should then fall back to the legacy
    ``container_url`` shape so non-migrated apps keep working.
    """
    # Late imports to avoid cycles (models imports services indirectly).
    from sqlalchemy import select

    from ...config import get_settings
    from ...models import AppInstance, MarketplaceApp, Project, User

    if container is None or container.project_id is None:
        return None

    project = await db.get(Project, container.project_id)
    if project is None or project.app_role != "app_instance":
        return None

    inst = (
        await db.execute(
            select(AppInstance).where(AppInstance.project_id == project.id).limit(1)
        )
    ).scalar_one_or_none()
    if inst is None:
        return None

    app_row = await db.get(MarketplaceApp, inst.app_id)
    if app_row is None:
        return None
    app_handle = getattr(app_row, "handle", None)
    if not app_handle:
        return None

    if app_row.creator_user_id is None:
        return None
    creator = await db.get(User, app_row.creator_user_id)
    if creator is None:
        return None
    creator_handle = getattr(creator, "handle", None)
    if not creator_handle:
        return None

    settings = get_settings()
    domain = settings.app_domain

    # Determine only_primary: single-container app or this is the
    # primary and there is no sibling dev container.
    only_primary = False
    if inst.primary_container_id is not None and inst.primary_container_id == container.id:
        # Count siblings with a directory (dev containers exposed via ingress).
        from ...models import Container as _Container

        sibling_count = (
            await db.execute(
                select(_Container.id).where(_Container.project_id == project.id)
            )
        ).all()
        if len(sibling_count) <= 1:
            only_primary = True

    container_dir = (container.directory or container.name or "app").lower()
    return app_container_url(
        app_handle=app_handle,
        creator_handle=creator_handle,
        container_dir=container_dir,
        app_domain=domain,
        protocol=protocol,
        only_primary=only_primary,
    )
