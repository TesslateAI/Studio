"""Four-step project setup pipeline.

Replaces the duplicated logic previously spread across
``_setup_base_project``, ``_setup_git_provider_project``, and
``_setup_archive_base_project`` in ``routers/projects.py``.

Steps:
1. Build a :class:`SourceSpec` from the creation request.
2. Acquire source files (template snapshot, cache, git clone, or archive).
3. Resolve project configuration (.tesslate/config.json → fallback).
4. Place files into Docker volume or K8s btrfs volume.
5. Initialize git in the project root if no `.git/` already exists.

Container creation is deferred to the Setup page where the user
can review and adjust the config before committing.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
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

        # Template snapshot path (instant btrfs clone — Kubernetes only)
        if settings.deployment_mode == "kubernetes" and base_repo.template_slug:
            return SourceSpec(
                kind="template_snapshot",
                template_slug=base_repo.template_slug,
                base_slug=base_repo.slug,
                base_id=base_repo.id,
                git_url=base_repo.git_repo_url,
            )

        # Desktop / local fast-path: check warm cache before any network I/O.
        # This mirrors the k8s template_snapshot shortcut and avoids a full git
        # clone when the user has created a project from this base before.
        if settings.deployment_mode in ("desktop", "local"):
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

        # Archive-based template
        if base_repo.source_type == "archive" and base_repo.archive_path:
            return SourceSpec(
                kind="archive",
                archive_path=base_repo.archive_path,
                base_slug=base_repo.slug,
                base_id=base_repo.id,
            )

        # Git-based base — try local cache first (docker / other modes)
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

    # Two URLs are built intentionally: clean_url is token-free and written to
    # the DB (git_url column) so it remains valid after the OAuth token rotates.
    # authenticated_url embeds the current access token for the clone subprocess
    # and is discarded after setup — it is never persisted.
    clean_url = provider_class.format_clone_url(repo_info["owner"], repo_info["repo"])
    # Public repos have no token, so fall back to clean_url rather than
    # producing an unauthenticated URL with a None token embedded.
    authenticated_url = (
        provider_class.format_clone_url(repo_info["owner"], repo_info["repo"], access_token)
        if access_token
        else clean_url
    )

    return SourceSpec(
        kind="git_clone",
        git_url=clean_url,
        git_clone_url=authenticated_url,
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
        UserPurchasedBase.team_id == team_id if team_id else UserPurchasedBase.user_id == user_id
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
                    project_id=str(db_project.id),
                )
            else:
                # Volume already created (shouldn't happen except template_snapshot above)
                placed = PlacedFiles(volume_id=source.volume_id, node_name=source.node_name)

        # Step 5: Ensure the project has a working git repo.
        # Every project — base / template / archive / git import — should
        # have `.git/` so the Repository panel renders local history and
        # the agent can commit/diff without an extra setup step. Acquired
        # sources have their `.git/` stripped (intentional — they're
        # templates, not forks), so we re-init.
        task.update_progress(85, 100, "Initializing repository...")
        try:
            await _ensure_git_initialized(placed, settings)
        except Exception as exc:  # noqa: BLE001
            # Non-blocking: file placement already succeeded — the project
            # is usable without git. The user can run /api/projects/{id}/git/init
            # manually from the Repository panel if needed.
            logger.warning(
                "[PIPELINE] git init skipped (best-effort): %s", exc
            )

        # Container creation deferred to Setup page
        task.update_progress(90, 100, "Finalizing...")
        primary_id, all_ids = None, []

        # Update project metadata — cache_node is NOT written (Hub is truth).
        if placed.volume_id:
            db_project.volume_id = placed.volume_id
        if spec.kind == "template_snapshot":
            db_project.compute_tier = "none"

        # has_git_repo: every project gets a local `.git/` from Step 5.
        db_project.has_git_repo = True

        # git_remote_url is the *user's* remote, only set when they
        # explicitly imported their own repo. Base templates / archives
        # are copies, not forks — recording the upstream URL here would
        # make the Repository panel try to render the template's GitHub
        # history as if it were the user's project.
        if project_data.source_type in ("github", "gitlab", "bitbucket") and spec.git_url:
            db_project.git_remote_url = spec.git_url
        await db.commit()

        return SetupResult(container_id=primary_id, container_ids=all_ids)

    finally:
        if source:
            await source.cleanup()


# ---------------------------------------------------------------------------
# Git initialization (Step 5)
# ---------------------------------------------------------------------------


async def _ensure_git_initialized(placed: PlacedFiles, settings) -> None:
    """Make sure the placed project has a working `.git/` directory.

    Idempotent — if `.git/` already exists (e.g. user imported a project via
    `import_path`), this is a no-op.

    Mode handling:
    - local / docker (placed.project_path set): run `git init` directly
      against the on-disk path. The orchestrator container has direct
      filesystem access to both paths.
    - kubernetes (placed.volume_id set): build a `.git/` skeleton on the
      orchestrator host (via real `git init` in a tempdir) and stream it
      to the btrfs volume via FileOps `tar_extract`. Avoids needing an
      Exec RPC on the CSI driver.
    """
    if placed.project_path:
        await _init_git_local_path(placed.project_path)
        return
    if placed.volume_id and placed.node_name:
        await _init_git_volume(placed.volume_id, placed.node_name)
        return
    logger.info("[PIPELINE] git init: nothing to initialize (no path or volume)")


async def _init_git_local_path(project_path: str) -> None:
    """Run `git init -b main` in the on-disk project root if missing."""
    git_dir = os.path.join(project_path, ".git")
    if os.path.exists(git_dir):
        logger.info("[PIPELINE] git init: %s already has .git, skipping", project_path)
        return

    proc = await asyncio.create_subprocess_exec(
        "git",
        "-c",
        "init.defaultBranch=main",
        "init",
        "-b",
        "main",
        cwd=project_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git init failed (exit {proc.returncode}): {stderr.decode(errors='replace')[:300]}"
        )
    logger.info("[PIPELINE] git init: initialized %s", project_path)


async def _init_git_volume(volume_id: str, node_name: str) -> None:
    """Push a `.git/` skeleton to a btrfs volume via FileOps tar_extract.

    We can't run subprocesses against a btrfs volume from the orchestrator,
    and the FileOps gRPC service doesn't expose an Exec RPC. So we run a
    real `git init -b main` in a tempdir on the orchestrator host, tar up
    the resulting `.git/` directory, and ship it via the existing
    `tar_extract` RPC. The result on the volume is byte-identical to a
    fresh local `git init`.
    """
    from ...services.fileops_client import FileOpsClient
    from ...services.node_discovery import NodeDiscovery

    # Cheap idempotency check — list the volume root and see if `.git`
    # already exists. Skips network round-trip on the actual init when not
    # needed.
    discovery = NodeDiscovery()
    address = await discovery.get_fileops_address(node_name)
    async with FileOpsClient(address) as client:
        try:
            entries = await client.list_dir(volume_id, ".")
            if any(getattr(e, "name", None) == ".git" for e in entries):
                logger.info("[PIPELINE] git init: volume %s already has .git", volume_id)
                return
        except Exception as exc:  # noqa: BLE001
            logger.debug("[PIPELINE] git init: list_dir probe failed (%s) — continuing", exc)

        tar_bytes = await asyncio.to_thread(_build_empty_git_tar)
        await client.tar_extract(volume_id, ".", tar_bytes)
    logger.info(
        "[PIPELINE] git init: pushed .git skeleton to volume %s (%d bytes)",
        volume_id,
        len(tar_bytes),
    )


def _build_empty_git_tar() -> bytes:
    """Run `git init -b main` in a tempdir and tar up the resulting `.git/`.

    Synchronous — caller wraps in `asyncio.to_thread`. Uses an empty repo
    on disk as the source of truth so the tar's contents always match what
    a real `git init` produces (avoids hand-coded skeletons going stale
    against future git versions).
    """
    tmp = tempfile.mkdtemp(prefix="tesslate-gitinit-")
    try:
        result = subprocess.run(
            ["git", "-c", "init.defaultBranch=main", "init", "-b", "main", tmp],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git init in tempdir failed (exit {result.returncode}): "
                f"{result.stderr.decode(errors='replace')[:300]}"
            )
        git_dir = os.path.join(tmp, ".git")
        if not os.path.isdir(git_dir):
            raise RuntimeError("git init did not produce a .git directory")

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(git_dir, arcname=".git")
        return buf.getvalue()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
