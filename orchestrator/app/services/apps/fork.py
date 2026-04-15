"""Fork a MarketplaceApp into a new creator-owned row.

Forking creates:
  - A brand-new MarketplaceApp with forker as creator, `forked_from`
    pointing at the source app id, fresh reputation, state='draft'.
  - An editable source Project owned by the forker (app_role='app_source')
    whose volume is materialized from the source AppVersion's bundle.
    This is what surfaces in the forker's Projects list so they can edit
    and republish.

Matches plan docs/proposed/plans/tesslate-apps.md.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppVersion, MarketplaceApp, Project
from ..hub_client import HubClient

logger = logging.getLogger(__name__)


_FORKABLE_ALLOWED = frozenset({"true", "restricted"})


class ForkError(Exception):
    """Base class for fork service errors."""


class NotForkableError(ForkError):
    """Raised when the source app's forkable policy is 'no'."""


@dataclass(frozen=True)
class ForkResult:
    new_app_id: UUID
    new_slug: str
    forked_from_app_id: UUID
    forked_from_version_id: UUID
    project_id: UUID | None = None
    project_slug: str | None = None


async def fork_app(
    db: AsyncSession,
    *,
    forker_user_id: UUID,
    source_app_version_id: UUID,
    new_slug: str,
    new_name: str,
    team_id: UUID | None = None,
    hub_client: HubClient | None = None,
) -> ForkResult:
    row = (
        await db.execute(
            select(AppVersion, MarketplaceApp)
            .join(MarketplaceApp, MarketplaceApp.id == AppVersion.app_id)
            .where(AppVersion.id == source_app_version_id)
        )
    ).one_or_none()
    if row is None:
        raise ForkError(f"app_version {source_app_version_id} not found")
    source_version, parent = row

    forkable = (parent.forkable or "").lower()
    if forkable not in _FORKABLE_ALLOWED:
        raise NotForkableError(
            f"source app {parent.id} forkable={parent.forkable!r} — forking not permitted"
        )
    # 'restricted' is allowed this wave; approval gating is a later wave.

    new_id = uuid4()
    new_app = MarketplaceApp(
        id=new_id,
        slug=new_slug,
        name=new_name,
        creator_user_id=forker_user_id,
        description=parent.description,
        category=parent.category,
        icon_ref=parent.icon_ref,
        forkable="restricted",
        forked_from=parent.id,
        visibility="private",
        state="draft",
        reputation={},
    )
    db.add(new_app)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ForkError(
            f"could not create forked app (slug={new_slug!r} likely already exists): {exc.orig}"
        ) from exc

    # Optionally materialize an editable source Project for the forker.
    # Requires hub_client + team_id + a bundle on the source version.
    project_id: UUID | None = None
    project_slug: str | None = None
    if hub_client is not None and team_id is not None and source_version.bundle_hash:
        try:
            volume_id, cache_node = await hub_client.create_volume_from_bundle(
                bundle_hash=source_version.bundle_hash,
            )
        except Exception:
            logger.exception(
                "apps.fork: create_volume_from_bundle failed for app=%s version=%s",
                parent.id, source_version.id,
            )
            raise ForkError("failed to provision fork volume from bundle")
        suffix = uuid.uuid4().hex[:8]
        base = "".join(
            c if c.isalnum() or c in "-_" else "-" for c in new_name.lower()
        ).strip("-") or "app"
        project_slug = f"{base}-{suffix}"
        project = Project(
            name=new_name,
            slug=project_slug,
            owner_id=forker_user_id,
            team_id=team_id,
            visibility="team",
            volume_id=volume_id,
            cache_node=cache_node,
            app_role="app_source",
        )
        db.add(project)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            raise ForkError(
                f"could not create fork project (slug conflict: {project_slug!r})"
            ) from exc
        project_id = project.id

    logger.info(
        "apps.fork new_app=%s parent=%s from_version=%s forker=%s project=%s",
        new_id, parent.id, source_version.id, forker_user_id, project_id,
    )
    return ForkResult(
        new_app_id=new_id,
        new_slug=new_slug,
        forked_from_app_id=parent.id,
        forked_from_version_id=source_version.id,
        project_id=project_id,
        project_slug=project_slug,
    )
