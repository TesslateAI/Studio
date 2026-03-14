"""
Template Builder Service - Pre-builds marketplace base templates as btrfs subvolumes.

After a template is built, new projects from that base are created via ~1ms btrfs
reflink snapshot instead of 60-240s git clone + dependency install.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import MarketplaceBase, TemplateBuild
from .nodeops_client import NodeOpsClient
from .orchestration.kubernetes.client import get_k8s_client
from .orchestration.kubernetes.helpers import (
    create_builder_network_policy,
    create_template_builder_job,
)

logger = logging.getLogger(__name__)

# CSI driver provisioner name (must match the CSI driver's registration)
CSI_PROVISIONER = "btrfs.csi.tesslate.io"

# Sentinel UUID for template build namespaces (no real user owns them)
_TEMPLATE_BUILD_USER_ID = UUID("00000000-0000-0000-0000-000000000000")

# How long to wait for a PVC to bind before giving up (seconds)
_PVC_BIND_TIMEOUT = 120
_PVC_BIND_POLL_INTERVAL = 3


class TemplateBuilderService:
    """Orchestrates building btrfs templates from marketplace bases."""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build_template(
        self, base: MarketplaceBase, db: AsyncSession
    ) -> TemplateBuild:
        """Build a template for a marketplace base.

        1. Create TemplateBuild record (pending)
        2. Create build namespace + PVC + NetworkPolicy
        3. Create K8s Job (devserver image clones repo + installs deps)
        4. Poll job completion
        5. Call PromoteToTemplate via NodeOps gRPC
        6. Create dynamic StorageClass for this template
        7. Update MarketplaceBase.template_slug
        8. Cleanup build namespace
        """
        settings = self._settings
        build_id = str(uuid4())
        namespace = f"{settings.template_build_namespace_prefix}{build_id[:8]}"
        pvc_name = "template-build-storage"
        job_name = f"tmpl-build-{build_id[:8]}"

        # 1. Create TemplateBuild record --------------------------------
        build = TemplateBuild(
            id=UUID(build_id),
            base_id=base.id,
            base_slug=base.slug,
            status="pending",
        )
        db.add(build)
        await db.commit()
        await db.refresh(build)

        k8s = get_k8s_client()

        try:
            # Transition to building -----------------------------------
            build.status = "building"
            build.started_at = datetime.now(UTC)
            await db.commit()

            start_time = time.monotonic()

            # Capture git HEAD SHA for freshness tracking
            git_url = base.git_repo_url
            git_branch = base.default_branch or "main"
            build.git_commit_sha = await self._get_remote_head_sha(
                git_url, git_branch
            )
            await db.commit()

            # 2. Create build namespace --------------------------------
            await k8s.create_namespace_if_not_exists(
                namespace,
                project_id=f"tmpl-{build_id[:8]}",
                user_id=_TEMPLATE_BUILD_USER_ID,
            )

            # Apply network policy (allow egress for git/npm, deny ingress)
            net_policy = create_builder_network_policy(namespace)
            await k8s.apply_network_policy(net_policy, namespace)

            # 3. Create PVC (empty btrfs subvolume) --------------------
            pvc = k8s_client.V1PersistentVolumeClaim(
                metadata=k8s_client.V1ObjectMeta(
                    name=pvc_name,
                    namespace=namespace,
                    labels={
                        "app.kubernetes.io/managed-by": "tesslate",
                        "tesslate.io/component": "template-builder",
                        "tesslate.io/build-id": build_id,
                    },
                ),
                spec=k8s_client.V1PersistentVolumeClaimSpec(
                    storage_class_name=settings.k8s_storage_class,
                    access_modes=["ReadWriteOnce"],
                    resources=k8s_client.V1ResourceRequirements(
                        requests={"storage": "10Gi"}
                    ),
                ),
            )
            await k8s.create_pvc(pvc, namespace)

            # 4. Create builder Job ------------------------------------
            job = create_template_builder_job(
                namespace=namespace,
                build_id=build_id,
                git_url=git_url,
                git_branch=git_branch,
                pvc_name=pvc_name,
                devserver_image=settings.k8s_devserver_image,
                timeout_seconds=settings.template_build_timeout,
            )
            await k8s.create_job(namespace, job)

            # 5. Poll job completion -----------------------------------
            poll_interval = 10
            timeout = settings.template_build_timeout + 60  # extra grace
            elapsed = 0
            while elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                status = await k8s.get_job_status(job_name, namespace)
                if status == "succeeded":
                    break
                if status == "failed":
                    raise RuntimeError(
                        f"Builder job failed for base {base.slug}"
                    )
            else:
                raise RuntimeError(
                    f"Builder job timed out after {timeout}s for base {base.slug}"
                )

            # 6. Promote to template via NodeOps gRPC ------------------
            build.status = "promoting"
            await db.commit()

            # The PVC is backed by a btrfs volume.  We need the PV name
            # (which is the CSI volume ID) to pass to PromoteToTemplate.
            pv_name = await self._wait_for_pvc_bound(k8s, pvc_name, namespace)
            if not pv_name:
                raise RuntimeError(
                    f"PVC {pvc_name} in {namespace} never became Bound"
                )

            async with NodeOpsClient(
                settings.template_build_nodeops_address
            ) as nodeops:
                await nodeops.promote_to_template(pv_name, base.slug)

            # 7. Create StorageClass for this template -----------------
            sc_name = f"tesslate-btrfs-{base.slug}"
            if not await k8s.storage_class_exists(sc_name):
                await k8s.create_storage_class(
                    name=sc_name,
                    provisioner=CSI_PROVISIONER,
                    parameters={"template": base.slug},
                )

            # 8. Update MarketplaceBase --------------------------------
            base.template_slug = base.slug
            build.status = "ready"
            build.build_duration_seconds = int(time.monotonic() - start_time)
            build.completed_at = datetime.now(UTC)
            await db.commit()

            logger.info(
                "Template build completed: base=%s duration=%ds",
                base.slug,
                build.build_duration_seconds,
            )
            return build

        except Exception as e:
            logger.error("Template build failed for %s: %s", base.slug, e)
            build.status = "failed"
            build.error_message = str(e)[:1000]
            build.retry_count = (build.retry_count or 0) + 1
            build.completed_at = datetime.now(UTC)
            await db.commit()
            raise
        finally:
            # Cleanup build namespace (best-effort, non-blocking)
            await self._delete_namespace_best_effort(k8s, namespace)

    async def rebuild_template(
        self, base_slug: str, db: AsyncSession
    ) -> TemplateBuild:
        """Force rebuild of a template for the given base slug."""
        base = await db.scalar(
            select(MarketplaceBase).where(MarketplaceBase.slug == base_slug)
        )
        if not base:
            raise ValueError(f"Base not found: {base_slug}")
        return await self.build_template(base, db)

    async def build_all_official(
        self, db: AsyncSession
    ) -> list[TemplateBuild]:
        """Build templates for all featured bases that don't have one yet.

        Skipped entirely when template_build_enabled is False.
        """
        if not self._settings.template_build_enabled:
            return []

        result = await db.execute(
            select(MarketplaceBase).where(
                MarketplaceBase.is_featured.is_(True),
                MarketplaceBase.is_active.is_(True),
                MarketplaceBase.template_slug.is_(None),
                MarketplaceBase.git_repo_url.isnot(None),
            )
        )
        bases = result.scalars().all()

        builds: list[TemplateBuild] = []
        for base in bases:
            try:
                build = await self.build_template(base, db)
                builds.append(build)
            except Exception:
                logger.exception(
                    "Failed to build template for %s", base.slug
                )
        return builds

    async def get_build_status(
        self, build_id: UUID, db: AsyncSession
    ) -> TemplateBuild | None:
        """Retrieve a TemplateBuild record by ID."""
        return await db.get(TemplateBuild, build_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _wait_for_pvc_bound(
        self,
        k8s,
        pvc_name: str,
        namespace: str,
    ) -> str | None:
        """Poll until a PVC is Bound, then return the backing PV name.

        Returns None if the PVC never binds within the timeout.
        """
        elapsed = 0
        while elapsed < _PVC_BIND_TIMEOUT:
            try:
                pvc = await asyncio.to_thread(
                    k8s.core_v1.read_namespaced_persistent_volume_claim,
                    name=pvc_name,
                    namespace=namespace,
                )
                if pvc.status and pvc.status.phase == "Bound":
                    return pvc.spec.volume_name
            except ApiException:
                logger.debug(
                    "PVC %s/%s read failed, retrying...",
                    namespace,
                    pvc_name,
                )
            await asyncio.sleep(_PVC_BIND_POLL_INTERVAL)
            elapsed += _PVC_BIND_POLL_INTERVAL

        logger.error(
            "PVC %s/%s did not bind within %ds",
            namespace,
            pvc_name,
            _PVC_BIND_TIMEOUT,
        )
        return None

    @staticmethod
    async def _get_remote_head_sha(git_url: str, branch: str) -> str | None:
        """Get the HEAD commit SHA of a remote git branch.

        Returns None if the command fails (network error, bad URL, etc.).
        Uses create_subprocess_exec (not shell) to avoid injection risks —
        git_url and branch come from trusted MarketplaceBase DB records.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "ls-remote", git_url, f"refs/heads/{branch}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0 and stdout:
                return stdout.decode().split()[0][:40]
        except Exception:
            logger.debug("Failed to get HEAD SHA for %s branch %s", git_url, branch)
        return None

    @staticmethod
    async def _delete_namespace_best_effort(k8s, namespace: str) -> None:
        """Delete a namespace, swallowing any errors.

        Namespace deletion cascades to all resources inside it (PVC, Job,
        NetworkPolicy, etc.) so a single call cleans everything up.
        """
        try:
            await asyncio.to_thread(
                k8s.core_v1.delete_namespace,
                name=namespace,
            )
            logger.info("Cleaned up build namespace %s", namespace)
        except Exception as cleanup_err:
            logger.warning(
                "Failed to cleanup build namespace %s: %s",
                namespace,
                cleanup_err,
            )
