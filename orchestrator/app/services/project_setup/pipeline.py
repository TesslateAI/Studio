"""Four-step project setup pipeline.

Replaces the duplicated logic previously spread across
``_setup_base_project``, ``_setup_git_provider_project``, and
``_setup_archive_base_project`` in ``routers/projects.py``.

Steps:
1. Build a :class:`SourceSpec` from the creation request.
2. Acquire source files (template snapshot, cache, git clone, or archive).
3. Resolve project configuration (.tesslate/config.json → fallback).
4. Place files into Docker volume or K8s btrfs volume.

Container creation is deferred to the Setup page where the user
can review and adjust the config before committing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import MarketplaceBase, Project
from ...schemas import ProjectCreate
from .config_resolver import (
    fallback_config,
    resolve_config,
    resolve_config_from_volume,
)
from .file_placement import PlacedFiles, place_files
from .source_acquisition import AcquiredSource, SourceSpec, acquire_source

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class SetupResult:
    """Returned by :func:`setup_project`."""

    container_id: str | None = None
    container_ids: list[str] | None = None


# ---------------------------------------------------------------------------
# Source spec builder
# ---------------------------------------------------------------------------


async def _build_source_spec(
    project_data: ProjectCreate,
    db_project: Project,
    settings,
    db: AsyncSession,
) -> SourceSpec:
    """Translate a :class:`ProjectCreate` request into a :class:`SourceSpec`."""

    # ---- Git provider imports (github / gitlab / bitbucket) ----
    if project_data.source_type in ("github", "gitlab", "bitbucket"):
        return await _build_git_provider_spec(project_data, db, settings, db_project.owner_id)  # type: ignore[arg-type]

    # ---- Marketplace base ----
    if project_data.source_type == "base":
        if not project_data.base_id:
            raise ValueError("base_id is required for source_type 'base'")

        base_repo = await db.get(MarketplaceBase, project_data.base_id)
        if not base_repo:
            raise ValueError("Project base not found.")

        # Ensure user has the base in their library (auto-add free ones)
        await _ensure_user_has_base(base_repo, project_data, db, db_project)

        # Template snapshot path (instant btrfs clone)
        if settings.deployment_mode == "kubernetes" and base_repo.template_slug:
            return SourceSpec(
                kind="template_snapshot",
                template_slug=base_repo.template_slug,
                base_slug=base_repo.slug,
                base_id=base_repo.id,
                git_url=base_repo.git_repo_url,
            )

        # Archive-based template
        if base_repo.source_type == "archive" and base_repo.archive_path:
            return SourceSpec(
                kind="archive",
                archive_path=base_repo.archive_path,
                base_slug=base_repo.slug,
                base_id=base_repo.id,
            )

        # Git-based base — try local cache first
        from ...services.base_cache_manager import get_base_cache_manager

        cache_mgr = get_base_cache_manager()
        cached = await cache_mgr.get_base_path(base_repo.slug)

        if cached and os.path.exists(cached):
            return SourceSpec(
                kind="cache",
                cache_path=cached,
                base_slug=base_repo.slug,
                base_id=base_repo.id,
                git_url=base_repo.git_repo_url,
            )

        # Fallback: clone from git
        branch = project_data.base_version or base_repo.default_branch or "main"
        return SourceSpec(
            kind="git_clone",
            git_url=base_repo.git_repo_url,
            git_branch=branch,
            base_slug=base_repo.slug,
            base_id=base_repo.id,
        )

    raise ValueError(
        f"Invalid source_type: {project_data.source_type}. "
        "Must be 'base', 'github', 'gitlab', or 'bitbucket'."
    )


async def _build_git_provider_spec(
    project_data: ProjectCreate,
    db: AsyncSession,
    settings,
    user_id: UUID,
) -> SourceSpec:
    """Build a SourceSpec for git-provider imports (GitHub/GitLab/Bitbucket)."""
    from ...services.git_providers import GitProviderType, get_git_provider_manager
    from ...services.git_providers.credential_service import get_git_provider_credential_service

    provider_name = project_data.source_type
    repo_url = project_data.git_repo_url or project_data.github_repo_url
    if not repo_url:
        raise ValueError(f"No repository URL provided for {provider_name} import")

    provider_type = GitProviderType(provider_name)
    provider_manager = get_git_provider_manager()
    provider_class = provider_manager.get_provider_class(provider_type)

    # Parse URL and get credentials
    repo_info = provider_class.parse_repo_url(repo_url)
    if not repo_info:
        raise ValueError(f"Invalid {provider_name} repository URL: {repo_url}")

    credential_service = get_git_provider_credential_service()
    access_token = await credential_service.get_access_token(db, user_id, provider_type)

    # Resolve branch
    branch = project_data.git_branch or project_data.github_branch or "main"
    if not (project_data.git_branch or project_data.github_branch) and access_token:
        try:
            provider_instance = provider_class(access_token)
            branch = await provider_instance.get_default_branch(
                repo_info["owner"], repo_info["repo"]
            )
        except Exception:
            pass  # Use "main" as fallback

    # Build authenticated URL
    authenticated_url = provider_class.format_clone_url(
        repo_info["owner"], repo_info["repo"], access_token
    )

    return SourceSpec(
        kind="git_clone",
        git_url=authenticated_url,
        git_branch=branch,
    )


async def _ensure_user_has_base(
    base_repo: MarketplaceBase,
    project_data: ProjectCreate,
    db: AsyncSession,
    db_project: Project,
) -> None:
    """Auto-add free bases to the user's library if not already purchased."""
    from ...models import UserPurchasedBase

    user_id = db_project.owner_id
    team_id = db_project.team_id
    ownership_filter = (
        UserPurchasedBase.team_id == team_id
        if team_id
        else UserPurchasedBase.user_id == user_id
    )
    purchase = await db.scalar(
        select(UserPurchasedBase).where(
            ownership_filter,
            UserPurchasedBase.base_id == project_data.base_id,
        )
    )

    if purchase and not purchase.is_active:
        if base_repo.pricing_type != "free":
            raise ValueError(
                f"'{base_repo.name}' requires purchase. Please buy it from the marketplace first."
            )
        from datetime import UTC, datetime

        purchase.is_active = True
        purchase.purchase_date = datetime.now(UTC)
        base_repo.downloads += 1
        await db.flush()
    elif not purchase:
        if base_repo.pricing_type != "free":
            raise ValueError(
                f"'{base_repo.name}' requires purchase. Please buy it from the marketplace first."
            )
        purchase = UserPurchasedBase(
            user_id=user_id,
            team_id=team_id,
            base_id=project_data.base_id,
            purchase_type="free",
            is_active=True,
        )
        db.add(purchase)
        base_repo.downloads += 1
        await db.flush()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def setup_project(
    project_data: ProjectCreate,
    db_project: Project,
    user_id: UUID,
    settings,
    db: AsyncSession,
    task,
) -> SetupResult:
    """Run the 4-step project creation pipeline.

    Steps:
        1. Build source spec from creation request
        2. Acquire source files
        3. Resolve config (.tesslate/config.json → fallback)
        4. Place files (skip for template snapshots)

    Container creation is deferred to the Setup page.

    Returns:
        :class:`SetupResult` with ``container_id=None`` and empty ``container_ids``.
    """
    source: AcquiredSource | None = None
    try:
        # Step 1: Build source spec
        task.update_progress(5, 100, "Preparing project source...")
        spec = await _build_source_spec(project_data, db_project, settings, db)
        logger.info(f"[PIPELINE] Source spec: kind={spec.kind}, base={spec.base_slug}")

        # Step 2: Acquire source files
        task.update_progress(10, 100, "Acquiring source files...")
        source = await acquire_source(spec, task)
        logger.info(
            f"[PIPELINE] Source acquired: local_path={source.local_path}, "
            f"volume_id={source.volume_id}"
        )

        # Step 3: Resolve config
        task.update_progress(55, 100, "Resolving project configuration...")
        config = None
        config_from_template = False

        if source.local_path:
            config = await resolve_config(source.local_path)
        elif source.volume_id and source.node_name:
            config = await resolve_config_from_volume(source.volume_id, source.node_name)

        if config:
            config_from_template = True
        else:
            # No config.json found — use fallback (user can run AI analysis from Setup page)
            logger.info("[PIPELINE] Using fallback config")
            config = fallback_config(db_project.name)

        logger.info(
            f"[PIPELINE] Config resolved: {len(config.apps)} apps, primary={config.primaryApp}"
        )

        # Step 4: Place files (skip for template snapshots — files already in place)
        placed: PlacedFiles
        if spec.kind == "template_snapshot":
            placed = PlacedFiles(volume_id=source.volume_id, node_name=source.node_name)
        else:
            if source.local_path:
                task.update_progress(65, 100, "Placing files...")
                placed = await place_files(
                    source_path=source.local_path,
                    config=config,
                    project_slug=db_project.slug,
                    deployment_mode=settings.deployment_mode,
                    task=task,
                    write_config=config_from_template,
                )
            else:
                # Volume already created (shouldn't happen except template_snapshot above)
                placed = PlacedFiles(volume_id=source.volume_id, node_name=source.node_name)

        # Container creation deferred to Setup page
        task.update_progress(90, 100, "Finalizing...")
        primary_id, all_ids = None, []

        # Update project metadata — cache_node is NOT written (Hub is truth).
        if placed.volume_id:
            db_project.volume_id = placed.volume_id
        if spec.kind == "template_snapshot":
            db_project.compute_tier = "none"
        if spec.git_url:
            db_project.has_git_repo = True
            db_project.git_remote_url = spec.git_url
        await db.commit()

        return SetupResult(container_id=primary_id, container_ids=all_ids)

    finally:
        if source:
            await source.cleanup()
