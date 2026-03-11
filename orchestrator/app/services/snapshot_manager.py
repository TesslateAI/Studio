"""
Snapshot Manager for EBS VolumeSnapshots

Handles Kubernetes VolumeSnapshot operations for project hibernation:
- Near-instant snapshot creation (< 5 seconds)
- Near-instant restore via lazy loading (< 10 seconds)
- Full volume preservation (node_modules included - no npm install)
- Versioning support (up to 5 snapshots per project)
- Soft delete with 30-day retention

CRITICAL: Always wait for snapshot.status.readyToUse=true before deleting the source PVC.
Deleting the PVC before the snapshot is ready will result in data corruption.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Project, ProjectSnapshot

logger = logging.getLogger(__name__)


class SnapshotManager:
    """Manages Kubernetes VolumeSnapshots for project hibernation and versioning."""

    def __init__(self):
        """Initialize Kubernetes client for VolumeSnapshot operations."""
        self.settings = get_settings()

        try:
            config.load_incluster_config()
            logger.info("SnapshotManager: Loaded in-cluster Kubernetes configuration")
        except config.ConfigException:
            try:
                config.load_kube_config()
                logger.info("SnapshotManager: Loaded kubeconfig for development")
            except config.ConfigException as e:
                logger.error(f"SnapshotManager: Failed to load Kubernetes config: {e}")
                raise RuntimeError("Cannot load Kubernetes configuration") from e

        # CustomObjectsApi for VolumeSnapshot CRDs
        self.custom_api = client.CustomObjectsApi()
        self.core_v1 = client.CoreV1Api()

        # VolumeSnapshot API configuration
        self.snapshot_group = "snapshot.storage.k8s.io"
        self.snapshot_version = "v1"
        self.snapshot_plural = "volumesnapshots"
        self.snapshot_class = self.settings.k8s_snapshot_class

    def _get_project_namespace(self, project_id: str) -> str:
        """Get the Kubernetes namespace for a project."""
        if self.settings.k8s_namespace_per_project:
            return f"proj-{project_id}"
        return self.settings.k8s_user_environments_namespace

    def _generate_snapshot_name(self, project_id: str, snapshot_type: str = "hibernation") -> str:
        """Generate a unique snapshot name."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        prefix = "snap" if snapshot_type == "hibernation" else "manual"
        return f"{prefix}-{project_id[:8]}-{timestamp}"

    async def create_snapshot(
        self,
        project_id: UUID,
        user_id: UUID,
        db: AsyncSession,
        snapshot_type: str = "hibernation",
        label: str | None = None,
        pvc_name: str = "project-storage",
    ) -> tuple[ProjectSnapshot | None, str | None]:
        """
        Create a VolumeSnapshot from a project's PVC.

        This operation is nearly instant (< 1 second to initiate).
        The snapshot uses EBS's copy-on-write mechanism.

        CRITICAL: Caller must call wait_for_snapshot_ready() before deleting the PVC.

        Args:
            project_id: Project UUID
            user_id: User UUID
            db: Database session
            snapshot_type: "hibernation" or "manual"
            label: Optional user-provided label for manual snapshots
            pvc_name: Name of the PVC to snapshot (default: "project-storage")

        Returns:
            Tuple of (ProjectSnapshot record, error message or None)
        """
        namespace = self._get_project_namespace(str(project_id))
        snapshot_name = self._generate_snapshot_name(str(project_id), snapshot_type)

        logger.info(
            f"[SNAPSHOT] Creating {snapshot_type} snapshot for project {project_id}: {snapshot_name}"
        )

        try:
            # Get PVC size for metadata
            volume_size_bytes = await self._get_pvc_size_bytes(namespace, pvc_name)

            # Create VolumeSnapshot manifest
            snapshot_manifest = {
                "apiVersion": f"{self.snapshot_group}/{self.snapshot_version}",
                "kind": "VolumeSnapshot",
                "metadata": {
                    "name": snapshot_name,
                    "namespace": namespace,
                    "labels": {
                        "app": "tesslate",
                        "managed-by": "tesslate-backend",
                        "project-id": str(project_id),
                        "user-id": str(user_id),
                        "snapshot-type": snapshot_type,
                    },
                },
                "spec": {
                    "volumeSnapshotClassName": self.snapshot_class,
                    "source": {"persistentVolumeClaimName": pvc_name},
                },
            }

            # Create snapshot in Kubernetes
            await asyncio.to_thread(
                self.custom_api.create_namespaced_custom_object,
                group=self.snapshot_group,
                version=self.snapshot_version,
                namespace=namespace,
                plural=self.snapshot_plural,
                body=snapshot_manifest,
            )

            logger.info(f"[SNAPSHOT] ✅ VolumeSnapshot created: {snapshot_name}")

            # Rotate old snapshots if we exceed the limit
            await self._rotate_snapshots(project_id, db, pvc_name=pvc_name)

            # Mark existing snapshots for this PVC as not latest
            await db.execute(
                update(ProjectSnapshot)
                .where(
                    and_(
                        ProjectSnapshot.project_id == project_id,
                        ProjectSnapshot.pvc_name == pvc_name,
                    )
                )
                .values(is_latest=False)
            )

            # Create database record
            snapshot_record = ProjectSnapshot(
                project_id=project_id,
                user_id=user_id,
                snapshot_name=snapshot_name,
                snapshot_namespace=namespace,
                pvc_name=pvc_name,
                volume_size_bytes=volume_size_bytes,
                snapshot_type=snapshot_type,
                status="pending",
                label=label or ("Auto-save" if snapshot_type == "hibernation" else "Manual save"),
                is_latest=True,
                is_soft_deleted=False,
            )
            db.add(snapshot_record)
            await db.commit()
            await db.refresh(snapshot_record)

            return snapshot_record, None

        except ApiException as e:
            error_msg = f"Kubernetes API error creating snapshot: {e.reason}"
            logger.error(f"[SNAPSHOT] ❌ {error_msg}")
            return None, error_msg
        except Exception as e:
            error_msg = f"Failed to create snapshot: {str(e)}"
            logger.error(f"[SNAPSHOT] ❌ {error_msg}", exc_info=True)
            return None, error_msg

    async def wait_for_snapshot_ready(
        self, snapshot: ProjectSnapshot, db: AsyncSession, timeout_seconds: int | None = None
    ) -> tuple[bool, str | None]:
        """
        Wait for a VolumeSnapshot to become ready (readyToUse: true).

        CRITICAL: This MUST be called and return True before deleting the source PVC.
        If the PVC is deleted before the snapshot is ready, the data will be corrupted.

        Args:
            snapshot: ProjectSnapshot record
            db: Database session
            timeout_seconds: Maximum wait time (default from config)

        Returns:
            Tuple of (success, error message or None)
        """
        if timeout_seconds is None:
            timeout_seconds = self.settings.k8s_snapshot_ready_timeout_seconds

        logger.info(
            f"[SNAPSHOT] Waiting for snapshot {snapshot.snapshot_name} to become ready (timeout: {timeout_seconds}s)"
        )

        start_time = datetime.now(UTC)
        last_status: dict[str, Any] = {}

        while True:
            elapsed = (datetime.now(UTC) - start_time).total_seconds()
            if elapsed >= timeout_seconds:
                status_bits = []
                if "readyToUse" in last_status:
                    status_bits.append(f"readyToUse={last_status.get('readyToUse')}")
                if last_status.get("error"):
                    status_bits.append(f"error={last_status.get('error')}")
                if last_status.get("boundVolumeSnapshotContentName"):
                    status_bits.append(
                        "content="
                        f"{last_status.get('boundVolumeSnapshotContentName')}"
                    )
                error_msg = (
                    f"Snapshot {snapshot.snapshot_name} did not become ready within "
                    f"{timeout_seconds} seconds"
                )
                if status_bits:
                    error_msg = f"{error_msg} (last_status: {', '.join(status_bits)})"
                logger.error(f"[SNAPSHOT] ❌ {error_msg}")

                # Update status to error
                snapshot.status = "error"
                await db.commit()

                return False, error_msg

            try:
                # Get snapshot status from Kubernetes
                k8s_snapshot = await asyncio.to_thread(
                    self.custom_api.get_namespaced_custom_object,
                    group=self.snapshot_group,
                    version=self.snapshot_version,
                    namespace=snapshot.snapshot_namespace,
                    plural=self.snapshot_plural,
                    name=snapshot.snapshot_name,
                )

                status = k8s_snapshot.get("status", {})
                last_status = status
                ready_to_use = status.get("readyToUse", False)

                if ready_to_use:
                    logger.info(
                        f"[SNAPSHOT] ✅ Snapshot {snapshot.snapshot_name} is ready ({elapsed:.1f}s)"
                    )

                    # Update database record
                    snapshot.status = "ready"
                    snapshot.ready_at = datetime.now(UTC)

                    # Update project's latest_snapshot_id
                    project = await db.get(Project, snapshot.project_id)
                    if project:
                        project.latest_snapshot_id = snapshot.id

                    await db.commit()

                    return True, None

                # Log progress
                if int(elapsed) % 5 == 0:
                    logger.info(
                        "[SNAPSHOT] Waiting for %s... (%ss, ready=%s, error=%s, content=%s)",
                        snapshot.snapshot_name,
                        int(elapsed),
                        status.get("readyToUse"),
                        status.get("error"),
                        status.get("boundVolumeSnapshotContentName"),
                    )

            except ApiException as e:
                if e.status == 404:
                    error_msg = f"Snapshot {snapshot.snapshot_name} not found"
                    logger.error(f"[SNAPSHOT] ❌ {error_msg}")
                    snapshot.status = "error"
                    await db.commit()
                    return False, error_msg
                logger.warning(f"[SNAPSHOT] API error checking snapshot status: {e.reason}")
            except Exception as e:
                logger.warning(f"[SNAPSHOT] Error checking snapshot status: {e}")

            await asyncio.sleep(1)

    async def restore_from_snapshot(
        self,
        project_id: UUID,
        user_id: UUID,
        db: AsyncSession,
        snapshot_id: UUID | None = None,
        pvc_name: str = "project-storage",
    ) -> tuple[bool, str | None]:
        """
        Create a PVC from a VolumeSnapshot for project restore.

        EBS snapshots use lazy loading - the volume is available immediately,
        and data blocks are loaded on first read. This makes restore nearly instant.

        Args:
            project_id: Project UUID
            user_id: User UUID
            db: Database session
            snapshot_id: Specific snapshot ID (defaults to latest)
            pvc_name: Name for the new PVC (default: "project-source")

        Returns:
            Tuple of (success, error message or None)
        """
        namespace = self._get_project_namespace(str(project_id))

        # Get snapshot record
        if snapshot_id:
            snapshot = await db.get(ProjectSnapshot, snapshot_id)
            if not snapshot:
                return False, f"Snapshot {snapshot_id} not found"
        else:
            snapshot = await self.get_latest_ready_snapshot(
                project_id=project_id,
                db=db,
                pvc_name=pvc_name,
            )
            if not snapshot:
                return False, f"No ready snapshot found for project {project_id} PVC {pvc_name}"

        logger.info(
            f"[SNAPSHOT] Restoring from snapshot {snapshot.snapshot_name} to PVC {pvc_name}"
        )

        try:
            # First, check if VolumeSnapshot exists in the new namespace
            # If not, we need to recreate it from the retained VolumeSnapshotContent
            snapshot_exists = await self._ensure_volumesnapshot_exists(
                snapshot_name=snapshot.snapshot_name,
                namespace=namespace,
                original_namespace=snapshot.snapshot_namespace,
            )

            if not snapshot_exists:
                return False, "Could not recreate VolumeSnapshot from retained content"

            # Create PVC with dataSource pointing to the snapshot
            pvc_manifest = client.V1PersistentVolumeClaim(
                metadata=client.V1ObjectMeta(
                    name=pvc_name,
                    namespace=namespace,
                    labels={
                        "app": "tesslate",
                        "managed-by": "tesslate-backend",
                        "project-id": str(project_id),
                        "user-id": str(user_id),
                        "restored-from": snapshot.snapshot_name,
                    },
                ),
                spec=client.V1PersistentVolumeClaimSpec(
                    access_modes=[self.settings.k8s_pvc_access_mode],
                    storage_class_name=self.settings.k8s_storage_class,
                    resources=client.V1ResourceRequirements(
                        requests={"storage": self.settings.k8s_pvc_size}
                    ),
                    data_source=client.V1TypedLocalObjectReference(
                        api_group=self.snapshot_group,
                        kind="VolumeSnapshot",
                        name=snapshot.snapshot_name,
                    ),
                ),
            )

            await asyncio.to_thread(
                self.core_v1.create_namespaced_persistent_volume_claim,
                namespace=namespace,
                body=pvc_manifest,
            )

            logger.info(
                f"[SNAPSHOT] ✅ PVC {pvc_name} created from snapshot {snapshot.snapshot_name}"
            )
            return True, None

        except ApiException as e:
            if e.status == 409:
                logger.info(f"[SNAPSHOT] PVC {pvc_name} already exists in {namespace}")
                return True, None
            error_msg = f"Kubernetes API error creating PVC: {e.reason}"
            logger.error(f"[SNAPSHOT] ❌ {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"Failed to create PVC from snapshot: {str(e)}"
            logger.error(f"[SNAPSHOT] ❌ {error_msg}", exc_info=True)
            return False, error_msg

    async def _ensure_volumesnapshot_exists(
        self, snapshot_name: str, namespace: str, original_namespace: str
    ) -> bool:
        """
        Ensure a VolumeSnapshot exists in the target namespace.

        When a project hibernates, the VolumeSnapshot in the original namespace is deleted
        along with the namespace, but the VolumeSnapshotContent is retained (deletionPolicy: Retain).

        This method creates a PRE-PROVISIONED snapshot from the retained EBS snapshot:
        1. Checks if VolumeSnapshot already exists in target namespace
        2. If not, finds the retained VolumeSnapshotContent and extracts the EBS snapshotHandle
        3. Creates a NEW pre-provisioned VolumeSnapshotContent with the snapshotHandle
        4. Creates a VolumeSnapshot bound to the new content

        The key insight: We can't reuse the old VolumeSnapshotContent because it's marked as
        "dynamically provisioned". We must create a new one that's "pre-provisioned" with the
        snapshotHandle from the underlying EBS snapshot.

        Args:
            snapshot_name: Name of the VolumeSnapshot
            namespace: Target namespace (new project namespace)
            original_namespace: Original namespace where snapshot was created

        Returns:
            True if VolumeSnapshot exists or was recreated, False otherwise
        """
        try:
            # Check if VolumeSnapshot already exists
            try:
                await asyncio.to_thread(
                    self.custom_api.get_namespaced_custom_object,
                    group=self.snapshot_group,
                    version=self.snapshot_version,
                    namespace=namespace,
                    plural="volumesnapshots",
                    name=snapshot_name,
                )
                logger.info(
                    f"[SNAPSHOT] VolumeSnapshot {snapshot_name} already exists in {namespace}"
                )
                return True
            except ApiException as e:
                if e.status != 404:
                    raise
                # VolumeSnapshot doesn't exist, need to recreate from retained content

            # Find the retained VolumeSnapshotContent
            # VolumeSnapshotContent is cluster-scoped, so search all
            vsc_list = await asyncio.to_thread(
                self.custom_api.list_cluster_custom_object,
                group=self.snapshot_group,
                version=self.snapshot_version,
                plural="volumesnapshotcontents",
            )

            # Find content that matches our snapshot name and original namespace
            retained_vsc = None
            for vsc in vsc_list.get("items", []):
                spec = vsc.get("spec", {})
                vs_ref = spec.get("volumeSnapshotRef", {})

                # Match by volumeSnapshotRef
                if (
                    vs_ref.get("name") == snapshot_name
                    and vs_ref.get("namespace") == original_namespace
                ):
                    retained_vsc = vsc
                    logger.info(
                        f"[SNAPSHOT] Found retained VolumeSnapshotContent: {vsc.get('metadata', {}).get('name')}"
                    )
                    break

            if not retained_vsc:
                logger.error(f"[SNAPSHOT] ❌ No VolumeSnapshotContent found for {snapshot_name}")
                return False

            # Extract the EBS snapshot handle from the retained content
            snapshot_handle = retained_vsc.get("status", {}).get("snapshotHandle")
            if not snapshot_handle:
                logger.error("[SNAPSHOT] ❌ No snapshotHandle in retained VolumeSnapshotContent")
                return False

            # Extract other necessary fields
            retained_vsc.get("status", {}).get("restoreSize")
            driver = retained_vsc.get("spec", {}).get("driver", "ebs.csi.aws.com")

            logger.info(
                f"[SNAPSHOT] Creating pre-provisioned snapshot from EBS handle: {snapshot_handle}"
            )

            # Create a new pre-provisioned VolumeSnapshotContent with a unique name
            new_vsc_name = f"restored-{snapshot_name}-{namespace[-8:]}"

            new_vsc_manifest = {
                "apiVersion": f"{self.snapshot_group}/{self.snapshot_version}",
                "kind": "VolumeSnapshotContent",
                "metadata": {
                    "name": new_vsc_name,
                    "labels": {
                        "app": "tesslate",
                        "managed-by": "tesslate-backend",
                        "restored-from": snapshot_name,
                    },
                },
                "spec": {
                    "driver": driver,
                    "deletionPolicy": "Retain",
                    "source": {
                        "snapshotHandle": snapshot_handle  # Key: pre-provisioned uses snapshotHandle
                    },
                    "volumeSnapshotClassName": self.snapshot_class,
                    "volumeSnapshotRef": {"name": snapshot_name, "namespace": namespace},
                },
            }

            await asyncio.to_thread(
                self.custom_api.create_cluster_custom_object,
                group=self.snapshot_group,
                version=self.snapshot_version,
                plural="volumesnapshotcontents",
                body=new_vsc_manifest,
            )

            logger.info(
                f"[SNAPSHOT] ✅ Created pre-provisioned VolumeSnapshotContent: {new_vsc_name}"
            )

            # Create VolumeSnapshot that binds to the pre-provisioned content
            vs_manifest = {
                "apiVersion": f"{self.snapshot_group}/{self.snapshot_version}",
                "kind": "VolumeSnapshot",
                "metadata": {
                    "name": snapshot_name,
                    "namespace": namespace,
                    "labels": {"app": "tesslate", "managed-by": "tesslate-backend"},
                },
                "spec": {"source": {"volumeSnapshotContentName": new_vsc_name}},
            }

            await asyncio.to_thread(
                self.custom_api.create_namespaced_custom_object,
                group=self.snapshot_group,
                version=self.snapshot_version,
                namespace=namespace,
                plural="volumesnapshots",
                body=vs_manifest,
            )

            logger.info(f"[SNAPSHOT] ✅ Created VolumeSnapshot {snapshot_name} in {namespace}")

            # Wait briefly for the snapshot to become ready
            for _ in range(10):
                await asyncio.sleep(1)
                try:
                    vs = await asyncio.to_thread(
                        self.custom_api.get_namespaced_custom_object,
                        group=self.snapshot_group,
                        version=self.snapshot_version,
                        namespace=namespace,
                        plural="volumesnapshots",
                        name=snapshot_name,
                    )
                    if vs.get("status", {}).get("readyToUse"):
                        logger.info(f"[SNAPSHOT] ✅ VolumeSnapshot {snapshot_name} is ready to use")
                        return True
                except ApiException:
                    pass

            # Even if not immediately ready, the snapshot should work for PVC creation
            logger.info(f"[SNAPSHOT] VolumeSnapshot {snapshot_name} created (may still be syncing)")
            return True

        except ApiException as e:
            logger.error(f"[SNAPSHOT] ❌ K8s API error recreating VolumeSnapshot: {e.reason}")
            return False
        except Exception as e:
            logger.error(f"[SNAPSHOT] ❌ Error ensuring VolumeSnapshot exists: {e}", exc_info=True)
            return False

    async def soft_delete_project_snapshots(self, project_id: UUID, db: AsyncSession) -> int:
        """
        Mark all snapshots for a project as soft-deleted.

        This is called when a user deletes a project. Snapshots are retained
        for the configured retention period (default 30 days) for admin recovery.
        The Kubernetes VolumeSnapshot resources are NOT deleted immediately.

        Args:
            project_id: Project UUID
            db: Database session

        Returns:
            Number of snapshots marked as soft-deleted
        """
        expiry_date = datetime.now(UTC) + timedelta(days=self.settings.k8s_snapshot_retention_days)

        result = await db.execute(
            update(ProjectSnapshot)
            .where(
                and_(ProjectSnapshot.project_id == project_id, ProjectSnapshot.is_soft_deleted.is_(False))
            )
            .values(is_soft_deleted=True, soft_delete_expires_at=expiry_date)
        )
        await db.commit()

        count = result.rowcount
        logger.info(
            f"[SNAPSHOT] Soft-deleted {count} snapshots for project {project_id} (expires: {expiry_date})"
        )
        return count

    async def cleanup_expired_snapshots(self, db: AsyncSession) -> int:
        """
        Delete expired soft-deleted snapshots from both Kubernetes and database.

        This should be called by a scheduled cleanup job (e.g., daily cron).

        Args:
            db: Database session

        Returns:
            Number of snapshots deleted
        """
        now = datetime.now(UTC)

        # Find expired snapshots
        result = await db.execute(
            select(ProjectSnapshot).where(
                and_(ProjectSnapshot.is_soft_deleted, ProjectSnapshot.soft_delete_expires_at < now)
            )
        )
        expired_snapshots = result.scalars().all()

        deleted_count = 0
        for snapshot in expired_snapshots:
            try:
                # Delete from Kubernetes
                await asyncio.to_thread(
                    self.custom_api.delete_namespaced_custom_object,
                    group=self.snapshot_group,
                    version=self.snapshot_version,
                    namespace=snapshot.snapshot_namespace,
                    plural=self.snapshot_plural,
                    name=snapshot.snapshot_name,
                )
                logger.info(f"[SNAPSHOT] Deleted K8s VolumeSnapshot: {snapshot.snapshot_name}")
            except ApiException as e:
                if e.status != 404:
                    logger.warning(
                        f"[SNAPSHOT] Failed to delete K8s snapshot {snapshot.snapshot_name}: {e.reason}"
                    )

            # Mark as deleted in database
            snapshot.status = "deleted"
            deleted_count += 1

        await db.commit()
        logger.info(f"[SNAPSHOT] Cleaned up {deleted_count} expired snapshots")
        return deleted_count

    async def get_project_snapshots(
        self, project_id: UUID, db: AsyncSession, include_soft_deleted: bool = False
    ) -> list[ProjectSnapshot]:
        """
        Get all snapshots for a project (for Timeline UI).

        Args:
            project_id: Project UUID
            db: Database session
            include_soft_deleted: Whether to include soft-deleted snapshots

        Returns:
            List of ProjectSnapshot records, ordered by creation date (newest first)
        """
        conditions = [ProjectSnapshot.project_id == project_id]
        if not include_soft_deleted:
            conditions.append(ProjectSnapshot.is_soft_deleted.is_(False))

        result = await db.execute(
            select(ProjectSnapshot)
            .where(and_(*conditions))
            .order_by(ProjectSnapshot.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_latest_ready_snapshot(
        self,
        project_id: UUID,
        db: AsyncSession,
        pvc_name: str,
        snapshot_type: str | None = None,
    ) -> ProjectSnapshot | None:
        """Get the latest ready snapshot for a specific PVC."""
        conditions = [
            ProjectSnapshot.project_id == project_id,
            ProjectSnapshot.pvc_name == pvc_name,
            ProjectSnapshot.status == "ready",
            ProjectSnapshot.is_soft_deleted.is_(False),
        ]
        if snapshot_type:
            conditions.append(ProjectSnapshot.snapshot_type == snapshot_type)

        result = await db.execute(
            select(ProjectSnapshot)
            .where(and_(*conditions))
            .order_by(ProjectSnapshot.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_ready_snapshots_by_pvc(
        self,
        project_id: UUID,
        db: AsyncSession,
        snapshot_type: str | None = None,
    ) -> dict[str, ProjectSnapshot]:
        """Get the latest ready snapshot for each PVC in a project."""
        conditions = [
            ProjectSnapshot.project_id == project_id,
            ProjectSnapshot.status == "ready",
            ProjectSnapshot.is_soft_deleted.is_(False),
        ]
        if snapshot_type:
            conditions.append(ProjectSnapshot.snapshot_type == snapshot_type)

        result = await db.execute(
            select(ProjectSnapshot)
            .where(and_(*conditions))
            .order_by(ProjectSnapshot.created_at.desc())
        )

        latest_by_pvc: dict[str, ProjectSnapshot] = {}
        for snapshot in result.scalars().all():
            if snapshot.pvc_name and snapshot.pvc_name not in latest_by_pvc:
                latest_by_pvc[snapshot.pvc_name] = snapshot
        return latest_by_pvc

    async def _rotate_snapshots(
        self, project_id: UUID, db: AsyncSession, pvc_name: str | None = None
    ) -> None:
        """
        Delete oldest snapshots when we exceed the max limit.

        Rotation policy:
        1. Delete oldest non-manual snapshot first
        2. If all are manual, delete oldest manual snapshot
        3. Always keep at least 1 snapshot
        """
        max_snapshots = self.settings.k8s_max_snapshots_per_project

        # Get current snapshot count
        conditions = [
            ProjectSnapshot.project_id == project_id,
            ProjectSnapshot.is_soft_deleted.is_(False),
        ]
        if pvc_name:
            conditions.append(ProjectSnapshot.pvc_name == pvc_name)

        result = await db.execute(
            select(ProjectSnapshot).where(and_(*conditions)).order_by(ProjectSnapshot.created_at.asc())
        )
        snapshots = list(result.scalars().all())

        if len(snapshots) < max_snapshots:
            return

        # Need to delete (len - max + 1) snapshots to make room for new one
        to_delete = len(snapshots) - max_snapshots + 1

        # Prefer deleting hibernation snapshots over manual ones
        hibernation_snapshots = [s for s in snapshots if s.snapshot_type == "hibernation"]
        manual_snapshots = [s for s in snapshots if s.snapshot_type == "manual"]

        deleted = 0
        # Delete oldest hibernation snapshots first
        for snapshot in hibernation_snapshots:
            if deleted >= to_delete:
                break
            await self._delete_snapshot(snapshot, db)
            deleted += 1

        # If still need to delete, remove oldest manual snapshots
        for snapshot in manual_snapshots:
            if deleted >= to_delete:
                break
            await self._delete_snapshot(snapshot, db)
            deleted += 1

        logger.info(f"[SNAPSHOT] Rotated {deleted} old snapshots for project {project_id}")

    async def _delete_snapshot(self, snapshot: ProjectSnapshot, db: AsyncSession) -> None:
        """Delete a snapshot from both Kubernetes and database."""
        snapshot_content_name = None

        try:
            # First, get the VolumeSnapshot to find its bound VolumeSnapshotContent
            try:
                k8s_snapshot = await asyncio.to_thread(
                    self.custom_api.get_namespaced_custom_object,
                    group=self.snapshot_group,
                    version=self.snapshot_version,
                    namespace=snapshot.snapshot_namespace,
                    plural=self.snapshot_plural,
                    name=snapshot.snapshot_name,
                )
                # Get the bound VolumeSnapshotContent name
                snapshot_content_name = k8s_snapshot.get("status", {}).get(
                    "boundVolumeSnapshotContentName"
                )
            except ApiException as e:
                if e.status != 404:
                    logger.warning(
                        f"[SNAPSHOT] Failed to get K8s snapshot {snapshot.snapshot_name}: {e.reason}"
                    )

            # Delete the VolumeSnapshot
            await asyncio.to_thread(
                self.custom_api.delete_namespaced_custom_object,
                group=self.snapshot_group,
                version=self.snapshot_version,
                namespace=snapshot.snapshot_namespace,
                plural=self.snapshot_plural,
                name=snapshot.snapshot_name,
            )
            logger.info(f"[SNAPSHOT] Deleted K8s VolumeSnapshot: {snapshot.snapshot_name}")
        except ApiException as e:
            if e.status != 404:
                logger.warning(
                    f"[SNAPSHOT] Failed to delete K8s snapshot {snapshot.snapshot_name}: {e.reason}"
                )

        # Also delete the VolumeSnapshotContent (the actual EBS snapshot)
        # This is needed because our VolumeSnapshotClass has deletionPolicy: Retain
        if snapshot_content_name:
            try:
                await asyncio.to_thread(
                    self.custom_api.delete_cluster_custom_object,
                    group=self.snapshot_group,
                    version=self.snapshot_version,
                    plural="volumesnapshotcontents",
                    name=snapshot_content_name,
                )
                logger.info(
                    f"[SNAPSHOT] Deleted K8s VolumeSnapshotContent: {snapshot_content_name}"
                )
            except ApiException as e:
                if e.status != 404:
                    logger.warning(
                        f"[SNAPSHOT] Failed to delete VolumeSnapshotContent {snapshot_content_name}: {e.reason}"
                    )

        # Delete from database
        await db.delete(snapshot)

    async def _get_pvc_size_bytes(self, namespace: str, pvc_name: str) -> int | None:
        """Get the size of a PVC in bytes."""
        try:
            pvc = await asyncio.to_thread(
                self.core_v1.read_namespaced_persistent_volume_claim,
                name=pvc_name,
                namespace=namespace,
            )
            # Parse storage size (e.g., "5Gi")
            size_str = pvc.spec.resources.requests.get("storage", "0")
            return self._parse_storage_size(size_str)
        except Exception as e:
            logger.warning(f"[SNAPSHOT] Could not get PVC size: {e}")
            return None

    def _parse_storage_size(self, size_str: str) -> int:
        """Parse Kubernetes storage size string to bytes."""
        size_str = str(size_str).strip()
        multipliers = {
            "Ki": 1024,
            "Mi": 1024**2,
            "Gi": 1024**3,
            "Ti": 1024**4,
            "K": 1000,
            "M": 1000**2,
            "G": 1000**3,
            "T": 1000**4,
        }
        for suffix, multiplier in multipliers.items():
            if size_str.endswith(suffix):
                return int(float(size_str[: -len(suffix)]) * multiplier)
        return int(size_str)

    async def has_existing_snapshot(
        self,
        project_id: UUID,
        db: AsyncSession,
        pvc_name: str | None = None,
        snapshot_type: str | None = None,
    ) -> bool:
        """Check if a project has any ready snapshots (for restore eligibility)."""
        conditions = [
            ProjectSnapshot.project_id == project_id,
            ProjectSnapshot.status == "ready",
            ProjectSnapshot.is_soft_deleted.is_(False),
        ]
        if pvc_name:
            conditions.append(ProjectSnapshot.pvc_name == pvc_name)
        if snapshot_type:
            conditions.append(ProjectSnapshot.snapshot_type == snapshot_type)

        result = await db.execute(select(ProjectSnapshot).where(and_(*conditions)).limit(1))
        return result.scalar_one_or_none() is not None


# Global instance - lazily initialized
_snapshot_manager_instance: SnapshotManager | None = None


def get_snapshot_manager() -> SnapshotManager:
    """Get or create the global SnapshotManager instance."""
    global _snapshot_manager_instance
    if _snapshot_manager_instance is None:
        _snapshot_manager_instance = SnapshotManager()
    return _snapshot_manager_instance
