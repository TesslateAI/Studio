"""
Kubernetes Orchestrator - EBS VolumeSnapshot Architecture

Kubernetes-based container orchestration with EBS snapshot-based hibernation:
- File lifecycle is SEPARATE from container lifecycle
- EBS VolumeSnapshots for hibernation/restoration (NOT S3)

Key Concepts:
1. PROJECT LIFECYCLE (namespace + storage):
   - Open project: Create namespace + PVC (from snapshot if hibernated) + file-manager pod
   - Leave project: Create VolumeSnapshot → Delete namespace
   - Return to project: Create namespace + PVC from snapshot

2. CONTAINER LIFECYCLE (per container):
   - Add to graph: Clone template files to /<container-dir>/
   - Start container: Create Deployment + Service + Ingress
   - Stop container: Delete Deployment (files persist on PVC)

3. FILE MANAGER POD:
   - Always running while project is open
   - Enables file operations without dev server running
   - Handles git clone when containers added to graph

4. EBS VOLUMESNAPSHOTS:
   - Near-instant hibernation (< 5 seconds)
   - Near-instant restore (< 10 seconds, lazy loading)
   - Full volume preserved (node_modules included - no npm install on restore)
   - Versioning: up to 5 snapshots per project (Timeline UI)
   - Soft delete: 30-day retention after project deletion
"""

import asyncio
import contextlib
import logging
import os
import shlex
from collections.abc import AsyncIterator
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from uuid import UUID

import grpc
import grpc.aio
from kubernetes.client.rest import ApiException
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from ..fileops_client import FileOpsClient

from ..snapshot_manager import get_snapshot_manager
from ..volume_manager import VolumeRestoringError, VolumeUnavailableError
from .base import BaseOrchestrator
from .deployment_mode import DeploymentMode
from .kubernetes.client import KubernetesClient, get_k8s_client
from .kubernetes.helpers import (
    create_file_manager_deployment,
    create_network_policy_manifest,
    create_pvc_manifest,
    generate_git_clone_script,
)

logger = logging.getLogger(__name__)

# Directories, files, and extensions to exclude from tree listings (matches docker.py).
_TREE_EXCLUDE_DIRS = [
    "node_modules",
    ".git",
    "__pycache__",
    ".next",
    "dist",
    "build",
    ".venv",
    "venv",
    ".cache",
    ".turbo",
    "coverage",
    ".nyc_output",
    "lost+found",
]
_TREE_EXCLUDE_FILES = [".DS_Store", "Thumbs.db", ".env.local", ".ash_history"]
_TREE_EXCLUDE_EXTS = [
    "png",
    "jpg",
    "jpeg",
    "gif",
    "ico",
    "svg",
    "webp",
    "bmp",
    "woff",
    "woff2",
    "ttf",
    "eot",
    "otf",
    "mp3",
    "mp4",
    "wav",
    "ogg",
    "webm",
    "avi",
    "mov",
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "zip",
    "tar",
    "gz",
    "rar",
    "7z",
    "bin",
    "exe",
    "dll",
    "so",
    "dylib",
    "class",
    "jar",
    "pyc",
    "pyo",
    "lock",
    "map",
]


class KubernetesOrchestrator(BaseOrchestrator):
    """
    Kubernetes orchestrator with EBS VolumeSnapshot hibernation.

    Architecture:
    - File Manager Pod: Always running for file operations
    - Dev Containers: Only run when explicitly started
    - EBS VolumeSnapshots: For hibernation/restoration (near-instant)
    - Pod Affinity: Multi-container projects share RWO storage
    """

    def __init__(self):
        from ...config import get_settings

        self.settings = get_settings()
        self._k8s_client: KubernetesClient | None = None

        # Note: Activity tracking is now database-based (Project.last_activity)
        # No in-memory tracking - supports horizontal scaling of backend

        logger.info("[K8S] Kubernetes orchestrator initialized (New Architecture)")
        logger.info(f"[K8S] Storage class: {self.settings.k8s_storage_class}")
        logger.info(f"[K8S] Pod affinity enabled: {self.settings.k8s_enable_pod_affinity}")

    @property
    def k8s_client(self) -> KubernetesClient:
        """Lazy load the Kubernetes client."""
        if self._k8s_client is None:
            self._k8s_client = get_k8s_client()
        return self._k8s_client

    @property
    def deployment_mode(self) -> DeploymentMode:
        return DeploymentMode.KUBERNETES

    def _sanitize_name(self, name: str) -> str:
        """Sanitize a name for Kubernetes (DNS-1123 compliant).

        Truncates to 59 chars to leave room for 4-char prefixes like
        'dev-' or 'svc-' that helpers.py adds to build resource names
        (K8s resource names must be <= 63 chars).
        """
        safe_name = name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
        safe_name = "".join(c for c in safe_name if c.isalnum() or c == "-")
        while "--" in safe_name:
            safe_name = safe_name.replace("--", "-")
        safe_name = safe_name.strip("-")
        return safe_name[:59]

    def _get_namespace(self, project_id: str) -> str:
        """Get namespace for a project."""
        return self.k8s_client.get_project_namespace(project_id)

    # =========================================================================
    # VOLUME-FIRST HELPERS
    # =========================================================================

    async def _get_fileops_client(
        self, cache_node: str | None = None, volume_id: str | None = None
    ) -> "FileOpsClient":
        """Get a FileOps client routed via the Volume Hub.

        The Hub is the single source of truth for node liveness and
        volume placement.  cache_node is accepted for signature compat
        but ignored — the Hub decides the node.
        """
        if not volume_id:
            raise RuntimeError("volume_id is required for FileOps routing")

        from ..volume_manager import get_volume_manager

        return await get_volume_manager().get_fileops_client(volume_id)

    async def _fileops_call(self, volume_id: str, fn, *args, **kwargs):
        """Execute a FileOps RPC with automatic volume-miss recovery.

        If the FileOps server returns FAILED_PRECONDITION (volume subvolume
        missing from disk), re-resolve through the Hub — which triggers a
        CAS restore — then retry the call once with a fresh client.

        This gives every file operation the same guarantee: either you get
        your data, or you get a clear VolumeRestoringError/VolumeUnavailableError.
        """
        from ..volume_manager import get_volume_manager

        vm = get_volume_manager()
        client = await vm.get_fileops_client(volume_id)
        try:
            async with client:
                return await fn(client, *args, **kwargs)
        except grpc.aio.AioRpcError as e:
            if e.code() != grpc.StatusCode.FAILED_PRECONDITION:
                raise
            logger.warning(
                "[K8S] FileOps volume missing (FAILED_PRECONDITION) for %s — re-resolving via Hub",
                volume_id,
            )
        # Re-resolve triggers CAS restore in the Hub if volume is gone.
        # This will raise VolumeRestoringError or VolumeUnavailableError
        # if the volume can't be made ready immediately.
        retry_client = await vm.get_fileops_client(volume_id)
        try:
            async with retry_client:
                return await fn(retry_client, *args, **kwargs)
        except grpc.aio.AioRpcError as retry_err:
            if retry_err.code() == grpc.StatusCode.FAILED_PRECONDITION:
                # Volume still not on disk — restore is in progress.
                logger.info(
                    "[K8S] FileOps volume %s still restoring after re-resolve — signaling restoring",
                    volume_id,
                )
                raise VolumeRestoringError(volume_id) from retry_err
            raise

    async def _get_project_volume_info(self, project_id: UUID) -> tuple[str | None, str | None]:
        """Look up volume fields from DB.

        Returns: (volume_id, cache_node)
        """
        from sqlalchemy import select as sa_select

        from ...database import AsyncSessionLocal
        from ...models import Project

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                sa_select(Project.volume_id, Project.cache_node).where(Project.id == project_id)
            )
            row = result.one_or_none()
            if row:
                return row.volume_id, row.cache_node
            raise ValueError(f"Project {project_id} not found")

    @staticmethod
    def _build_volume_path(file_path: str, subdir: str | None = None) -> str:
        """Build a normalized path for FileOps (relative to volume root).

        Same containment logic as _build_pod_path but without the /app prefix.
        Volume root IS the /app equivalent. Uses an absolute anchor for
        robust relative_to() checking — mirrors _build_pod_path's approach.
        """
        anchor = PurePosixPath("/vol")
        base = anchor
        if subdir and subdir != ".":
            base = base / subdir

        normalized = PurePosixPath(os.path.normpath(str(base / file_path)))

        # Containment: must still be under /vol
        try:
            normalized.relative_to(anchor)
        except ValueError as err:
            raise ValueError(
                f"Path escapes volume boundary: {file_path!r} (resolved to {normalized})"
            ) from err

        # Return path relative to the anchor (strip the /vol prefix)
        return str(normalized.relative_to(anchor))

    async def _get_tesslate_config_from_volume(
        self, volume_id: str, cache_node: str | None, container_directory: str
    ) -> Any | None:
        """Read and parse .tesslate/config.json via FileOps."""
        from ...services.base_config_parser import parse_tesslate_config

        config_path = (
            f"{container_directory}/.tesslate/config.json"
            if container_directory not in (".", "", None)
            else ".tesslate/config.json"
        )
        try:
            async with await self._get_fileops_client(cache_node, volume_id) as client:
                content = await client.read_file_text(volume_id, config_path)
                return parse_tesslate_config(content)
        except Exception as e:
            logger.debug(f"[K8S] Could not read config.json via FileOps: {e}")
            return None

    async def _sync_db_files_to_pvc(
        self,
        project,
        container_directory: str,
        raw_directory: str | None,
        _namespace: str,
        db: AsyncSession,
        # Volume routing hints
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> None:
        """
        Sync ProjectFile records from the database to the PVC via FileOps.

        Used for forked projects and bases without a git_repo_url.

        For multi-container projects, only files belonging to this
        container are synced (matched by raw_directory prefix).

        Args:
            project: Project model
            container_directory: Sanitized K8s directory name (target on PVC)
            raw_directory: Original container.directory (".", "", None, or "frontend")
            _namespace: K8s namespace (unused - volume routing uses FileOps)
            db: Database session
        """
        from sqlalchemy import select

        from ...models import ProjectFile

        result = await db.execute(select(ProjectFile).where(ProjectFile.project_id == project.id))
        all_files = result.scalars().all()

        if not all_files:
            logger.warning(f"[K8S] No ProjectFile records for {project.slug} — PVC will be empty")
            return

        # Scope files to this container:
        # - root dir (".", "", None): all files belong to this container, no prefix stripping
        # - specific dir (e.g., "frontend"): only files with that prefix, strip it
        is_root = raw_directory in (".", "", None)
        if is_root:
            files_to_sync = [(pf.file_path, pf.content) for pf in all_files]
        else:
            prefix = f"{raw_directory}/"
            files_to_sync = [
                (pf.file_path[len(prefix) :], pf.content)
                for pf in all_files
                if pf.file_path.startswith(prefix)
            ]

        if not files_to_sync:
            logger.warning(
                f"[K8S] No files matched container directory '{raw_directory}' "
                f"(total project files: {len(all_files)})"
            )
            return

        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project.id)

        async with await self._get_fileops_client(cache_node, volume_id) as client:
            base_path = container_directory if container_directory != "." else ""
            if base_path:
                await client.mkdir_all(volume_id, base_path)
            synced = 0
            for rel_path, content in files_to_sync:
                try:
                    vol_path = f"{base_path}/{rel_path}" if base_path else rel_path
                    data = content.encode("utf-8") if isinstance(content, str) else content
                    await client.write_file(volume_id, vol_path, data)
                    synced += 1
                except Exception as e:
                    logger.warning(f"[K8S] Failed to sync {rel_path} via FileOps: {e}")
        logger.info(
            f"[K8S] Synced {synced}/{len(files_to_sync)} files via FileOps "
            f"for {container_directory}"
        )

    # =========================================================================
    # PROJECT ENVIRONMENT LIFECYCLE
    # =========================================================================

    async def ensure_project_environment(
        self,
        project_id: UUID,
        user_id: UUID,
        is_hibernated: bool = False,
        db: AsyncSession | None = None,
        storage_class_override: str | None = None,
    ) -> str:
        """
        Ensure project environment exists (namespace + PVC + file-manager).

        Called when user opens a project in the builder.
        Creates the infrastructure needed for file operations.

        For hibernated projects, creates PVC from VolumeSnapshot (lazy loading).

        Args:
            project_id: Project UUID
            user_id: User UUID
            is_hibernated: Whether project was hibernated (needs snapshot restoration)
            db: Database session (required if is_hibernated=True)
            storage_class_override: Override StorageClass for PVC creation
                (used for template-based projects with btrfs CSI snapshots)

        Returns:
            Namespace name
        """
        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)

        logger.info(f"[K8S] Ensuring environment for project {project_id_str}")
        logger.info(f"[K8S] Namespace: {namespace}, Hibernated: {is_hibernated}")

        try:
            # 1. Create namespace
            await self.k8s_client.create_namespace_if_not_exists(namespace, project_id_str, user_id)

            # 2. Create NetworkPolicy for isolation
            network_policy = create_network_policy_manifest(namespace, project_id)
            await self.k8s_client.apply_network_policy(network_policy, namespace)

            # 3. Create PVC for project storage
            # If hibernated, try to restore from snapshot (near-instant with lazy loading)
            restore_success = False
            if is_hibernated and db:
                restore_success = await self._restore_from_snapshot(
                    project_id, user_id, namespace, db
                )

            # Create empty PVC if not hibernated or snapshot restore failed
            if not restore_success:
                if is_hibernated:
                    logger.warning(f"[K8S] No snapshot found for {project_id}, creating empty PVC")
                storage_class = storage_class_override or self.settings.k8s_storage_class
                if storage_class_override:
                    logger.info(
                        f"[K8S] Using template StorageClass {storage_class} for project {project_id}"
                    )
                pvc = create_pvc_manifest(
                    namespace=namespace,
                    project_id=project_id,
                    user_id=user_id,
                    storage_class=storage_class,
                    size=self.settings.k8s_pvc_size,
                    access_mode=self.settings.k8s_pvc_access_mode,
                )
                await self.k8s_client.create_pvc(pvc, namespace)

            # 4. Copy wildcard TLS secret (needed for HTTPS ingress)
            if self.settings.k8s_wildcard_tls_secret:
                await self.k8s_client.copy_wildcard_tls_secret(namespace)

            # 5. Create file-manager deployment
            file_manager = create_file_manager_deployment(
                namespace=namespace,
                project_id=project_id,
                user_id=user_id,
                image=self.settings.k8s_devserver_image,
                image_pull_policy=self.settings.k8s_image_pull_policy,
                image_pull_secret=self.settings.k8s_image_pull_secret or None,
                enable_pod_affinity=self.settings.k8s_enable_pod_affinity,
                affinity_topology_key=self.settings.k8s_affinity_topology_key,
            )
            await self.k8s_client.create_deployment(file_manager, namespace)

            # 6. Wait for file-manager to be ready
            await self.k8s_client.wait_for_deployment_ready(
                deployment_name="file-manager", namespace=namespace, timeout=60
            )

            # Activity tracking is now database-based (via activity_tracker service)

            logger.info(f"[K8S] ✅ Environment ready for project {project_id_str}")
            return namespace

        except Exception as e:
            logger.error(f"[K8S] Error ensuring environment: {e}", exc_info=True)
            raise

    async def delete_project_environment(
        self,
        project_id: UUID,
        user_id: UUID,
        save_snapshot: bool = True,
        db: AsyncSession | None = None,
    ) -> None:
        """
        Delete project environment (for hibernation or cleanup).

        Called when user leaves project or project is idle too long.

        CRITICAL: If save_snapshot=True, a VolumeSnapshot is created FIRST and
        we wait for it to become ready before deleting the namespace.
        Deleting the PVC before the snapshot is ready will corrupt the data.

        Args:
            project_id: Project UUID
            user_id: User UUID
            save_snapshot: Whether to create snapshot before deleting (hibernation)
            db: Database session (required if save_snapshot=True)
        """
        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)

        logger.info(f"[K8S] Deleting environment for project {project_id_str}")

        try:
            if save_snapshot and db:
                # Hibernate: Create snapshot first - CRITICAL: Must succeed before deleting
                snapshot_success = await self._save_to_snapshot(project_id, user_id, namespace, db)
                if not snapshot_success:
                    # Snapshot failed - DO NOT delete namespace to preserve data
                    logger.error(
                        "[K8S] ❌ Snapshot failed - NOT deleting namespace to preserve data"
                    )
                    raise RuntimeError(
                        f"Cannot hibernate project {project_id_str}: Snapshot creation failed"
                    )
            elif save_snapshot and not db:
                logger.warning(
                    "[K8S] save_snapshot=True but no db session provided - skipping snapshot"
                )

            # Delete namespace (cascades all resources including PVC)
            await asyncio.to_thread(self.k8s_client.core_v1.delete_namespace, name=namespace)
            logger.info(f"[K8S] ✅ Deleted namespace: {namespace}")

        except ApiException as e:
            if e.status != 404:
                logger.error(f"[K8S] Error deleting environment: {e}")
                raise

        # Activity tracking is now database-based (no in-memory cleanup needed)

    async def ensure_project_directory(self, project_slug: str) -> None:
        """
        Ensure the project directory exists.

        In Kubernetes mode, the project directory is created on the PVC
        when the pod starts (via init container or file-manager pod).
        This method is a no-op for K8s since directories are created
        as part of the pod initialization process.
        """
        logger.debug(
            f"[K8S] ensure_project_directory called for {project_slug} (no-op in K8s mode)"
        )
        # No-op in K8s mode - directories are created by pods on PVC
        pass

    # =========================================================================
    # CONTAINER FILE INITIALIZATION
    # =========================================================================

    async def initialize_container_files(
        self,
        project_id: UUID,
        user_id: UUID,
        container_id: UUID,
        container_directory: str,
        git_url: str | None = None,
        git_branch: str = "main",
    ) -> bool:
        """
        Initialize files for a container (called when container added to graph).

        This populates the files BEFORE the container is started.
        Files go to /app/{container_directory}/ on the shared PVC.

        Args:
            project_id: Project UUID
            user_id: User UUID
            container_id: Container UUID
            container_directory: Directory name for this container
            git_url: Optional git URL to clone from
            git_branch: Git branch to clone

        Returns:
            True if successful
        """
        _ = container_id  # Part of interface; unused in K8s mode

        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)
        target_dir = "/app" if container_directory in (".", "") else f"/app/{container_directory}"

        logger.info(f"[K8S] Initializing files for container {container_directory}")
        logger.info(f"[K8S] Git URL: {git_url or 'None (using template)'}")

        try:
            # Ensure environment exists first (check K8s namespace)
            namespace_exists = await self.k8s_client.namespace_exists(namespace)
            if not namespace_exists:
                await self.ensure_project_environment(project_id, user_id)

            # Get file-manager pod name (with retries - pod may still be starting)
            pod_name = None
            for attempt in range(10):  # Up to 30 seconds
                pod_name = await self.k8s_client.get_file_manager_pod(namespace)
                if pod_name:
                    break
                logger.info(f"[K8S] Waiting for file-manager pod... (attempt {attempt + 1}/10)")
                await asyncio.sleep(3)

            if not pod_name:
                raise RuntimeError("File manager pod not found after waiting 30 seconds")

            # Check if directory already exists with actual content (not just empty dir)
            # This prevents skipping git clone when directory exists but is empty
            check_script = f"""
if [ -d '{target_dir}' ]; then
    file_count=$(ls -1A '{target_dir}' 2>/dev/null | wc -l)
    echo "EXISTS:$file_count"
else
    echo "NOT_EXISTS"
fi
"""
            check_result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["/bin/sh", "-c", check_script],
                30,
            )
            check_result = check_result.strip()
            logger.info(f"[K8S] Directory check result for {target_dir}: '{check_result}'")

            if check_result.startswith("EXISTS:"):
                file_count = int(check_result.split(":")[1]) if ":" in check_result else 0
                if file_count >= 3:
                    logger.info(
                        f"[K8S] Directory {target_dir} already exists with {file_count} files, skipping git clone"
                    )
                    return True
                else:
                    logger.warning(
                        f"[K8S] Directory {target_dir} exists but only has {file_count} files, will re-clone"
                    )
                    # Fall through to clone

            # No git_url — ensure the directory at least exists with correct ownership
            # so the dev container (uid 1000) can write to it.
            # This handles forked projects and git-imported containers where
            # files may arrive later via the editor or agent.
            if not git_url:
                await asyncio.to_thread(
                    self.k8s_client._exec_in_pod,
                    pod_name,
                    namespace,
                    "file-manager",
                    ["/bin/sh", "-c", f"mkdir -p '{target_dir}'"],
                    10,
                )
                logger.warning(
                    f"[K8S] No git_url for '{container_directory}' — created empty directory. "
                    "Files should be imported via editor or agent."
                )
                return True

            # Clone from git repository
            # install_deps=False - dependencies are installed by the container's start_command
            # This keeps file init fast and non-blocking
            script = generate_git_clone_script(
                git_url=git_url, branch=git_branch, target_dir=target_dir, install_deps=False
            )

            # Execute script in file-manager pod
            result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["/bin/sh", "-c", script],
                timeout=60,  # Just git clone, should be fast
            )

            logger.debug(f"[K8S] Init output: {result[:500]}...")

            # Verify files actually landed on the PVC — _exec_in_pod doesn't
            # propagate exit codes, so the clone script can fail silently.
            verify_result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["/bin/sh", "-c", f"ls -1A '{target_dir}' 2>/dev/null | wc -l"],
                10,
            )
            file_count = int(verify_result.strip()) if verify_result.strip().isdigit() else 0
            if file_count < 3:
                logger.error(
                    f"[K8S] ❌ Clone appeared to succeed but {target_dir} has {file_count} files. "
                    f"Clone output: {result[:300]}"
                )
                raise RuntimeError(
                    f"Git clone failed for {container_directory}: directory has {file_count} files after clone"
                )

            logger.info(
                f"[K8S] ✅ Files initialized for {container_directory} ({file_count} files)"
            )
            return True

        except Exception as e:
            logger.error(f"[K8S] Error initializing files: {e}", exc_info=True)
            raise  # Re-raise to stop container start if files can't be initialized

    # =========================================================================
    # CONTAINER LIFECYCLE (START/STOP)
    # =========================================================================

    async def start_container(
        self,
        project,
        container,
        all_containers: list,
        connections: list,
        user_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Start a single container via ComputeManager.

        Delegates to ComputeManager which handles all container types
        (base and service) within the volume-first architecture.

        Args:
            project: Project model
            container: Container model
            all_containers: All containers in project (for affinity)
            connections: Container connections
            user_id: User UUID
            db: Database session

        Returns:
            Dict with status and URL
        """
        from ..compute_manager import get_compute_manager, resolve_k8s_container_dir

        container_dir = resolve_k8s_container_dir(container)
        urls = await get_compute_manager().start_environment(
            project, all_containers, connections, user_id, db
        )
        return {
            "status": "running",
            "container_name": container.name,
            "container_directory": container_dir,
            "url": urls.get(container_dir),
            "namespace": f"proj-{project.id}",
        }

    async def stop_container(
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str,
        user_id: UUID,
        container_type: str = "base",
        service_slug: str | None = None,
    ) -> None:
        """
        Stop a single container (delete Deployment + Service + Ingress).

        Files PERSIST on PVC via file-manager pod.

        Args:
            project_slug: Project slug
            project_id: Project UUID
            container_name: Container name
            user_id: User UUID
            container_type: "base" or "service"
            service_slug: Service slug (for service containers)
        """
        _ = project_slug, user_id  # Part of interface; unused in K8s mode

        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)

        if container_type == "service" and service_slug:
            container_directory = self._sanitize_name(service_slug)
            deployment_name = f"svc-{container_directory}"
            svc_name = f"svc-{container_directory}"

            logger.info(
                f"[K8S] Stopping service container '{container_directory}' in namespace {namespace}"
            )

            try:
                await self.k8s_client.delete_deployment(deployment_name, namespace)
                await self.k8s_client.delete_service(svc_name, namespace)
                # No Ingress to delete for service containers
                logger.info("[K8S] ✅ Service container stopped (data PVC persists)")
            except Exception as e:
                if "404" not in str(e):
                    logger.error(f"[K8S] Error stopping service container: {e}")
                    raise
        else:
            container_directory = self._sanitize_name(container_name)
            deployment_name = f"dev-{container_directory}"
            svc_name = f"dev-{container_directory}"
            ingress_name = f"dev-{container_directory}"

            logger.info(
                f"[K8S] Stopping container '{container_directory}' in namespace {namespace}"
            )

            try:
                await self.k8s_client.delete_deployment(deployment_name, namespace)
                await self.k8s_client.delete_service(svc_name, namespace)
                await self.k8s_client.delete_ingress(ingress_name, namespace)
                logger.info("[K8S] ✅ Container stopped (files persist on PVC)")
            except Exception as e:
                if "404" not in str(e):
                    logger.error(f"[K8S] Error stopping container: {e}")
                    raise

    async def get_container_status(
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str | None,
        user_id: UUID,
        service_slug: str | None = None,
    ) -> dict[str, Any]:
        """Get status of a single container or the project environment.

        If container_name is None, returns overall project/file-manager status.

        Args:
            project_slug: Project slug
            project_id: Project UUID
            container_name: Container name (or None for project-level status)
            user_id: User UUID
            service_slug: Service slug for service containers (used to find
                          the svc-{slug} deployment instead of sanitizing the name)
        """
        _ = project_slug, user_id  # Part of interface; unused in K8s mode

        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)

        # If container_name is None, get file-manager status (overall project status)
        if container_name is None:
            deployment_name = "file-manager"
            try:
                deployment = await asyncio.to_thread(
                    self.k8s_client.apps_v1.read_namespaced_deployment,
                    name=deployment_name,
                    namespace=namespace,
                )
                ready = (deployment.status.ready_replicas or 0) > 0
                return {
                    "status": "running" if ready else "starting",
                    "deployment_ready": ready,
                    "ready": ready,
                    "replicas": deployment.status.replicas,
                    "ready_replicas": deployment.status.ready_replicas,
                    "url": None,  # Project-level doesn't have a single URL
                }
            except ApiException as e:
                if e.status == 404:
                    return {"status": "stopped", "deployment_ready": False, "ready": False}
                raise

        # Build candidate deployment names to check.
        # For service containers the deployment uses the service_slug, not the
        # display name, so we need both variants.
        container_directory = self._sanitize_name(container_name)
        candidates = [f"dev-{container_directory}", f"svc-{container_directory}"]

        if service_slug:
            svc_directory = self._sanitize_name(service_slug)
            svc_candidate = f"svc-{svc_directory}"
            if svc_candidate not in candidates:
                candidates.append(svc_candidate)

        for deployment_name in candidates:
            try:
                deployment = await asyncio.to_thread(
                    self.k8s_client.apps_v1.read_namespaced_deployment,
                    name=deployment_name,
                    namespace=namespace,
                )

                ready = (deployment.status.ready_replicas or 0) > 0

                return {
                    "status": "running" if ready else "starting",
                    "container_name": container_name,
                    "ready": ready,
                    "replicas": deployment.status.replicas,
                    "ready_replicas": deployment.status.ready_replicas,
                }

            except ApiException as e:
                if e.status == 404:
                    continue  # Try next candidate
                raise

        return {"status": "stopped", "container_name": container_name}

    # =========================================================================
    # PROJECT LIFECYCLE (START/STOP ALL)
    # =========================================================================

    async def start_project(
        self, project, containers: list, connections: list, user_id: UUID, db: AsyncSession
    ) -> dict[str, Any]:
        """Start all containers for a project via ComputeManager."""
        from ..compute_manager import get_compute_manager

        urls = await get_compute_manager().start_environment(
            project, containers, connections, user_id, db
        )
        return {
            "status": "running",
            "project_slug": project.slug,
            "namespace": f"proj-{project.id}",
            "containers": urls,
        }

    async def stop_project(self, project_slug: str, project_id: UUID, user_id: UUID) -> None:
        """Stop all containers for a project (but keep files)."""
        _ = project_slug, user_id  # Part of interface; unused in K8s mode

        from ...database import AsyncSessionLocal
        from ...models import Project
        from ..compute_manager import get_compute_manager

        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
            if project:
                await get_compute_manager().stop_environment(project, db)

    async def delete_project_namespace(self, project_id: UUID, user_id: UUID) -> None:
        """
        Delete the entire Kubernetes namespace for a project.

        This completely removes all resources (pods, services, ingresses, PVCs)
        and should only be called when permanently deleting a project.
        """
        _ = user_id  # Retained for interface consistency; unused in K8s mode

        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)

        logger.info(f"[K8S] Deleting namespace {namespace}")

        try:
            # Check if namespace exists
            try:
                await asyncio.to_thread(self.k8s_client.core_v1.read_namespace, name=namespace)
            except ApiException as e:
                if e.status == 404:
                    logger.info(f"[K8S] Namespace {namespace} does not exist, nothing to delete")
                    return
                raise

            # Delete the namespace (this cascades to all resources in it)
            await asyncio.to_thread(self.k8s_client.core_v1.delete_namespace, name=namespace)

            logger.info(f"[K8S] Namespace {namespace} deleted successfully")

        except ApiException as e:
            if e.status != 404:
                logger.error(f"[K8S] Error deleting namespace {namespace}: {e}")
                raise

    async def restart_project(
        self, project, containers: list, connections: list, user_id: UUID, db: AsyncSession
    ) -> dict[str, Any]:
        """Restart all containers for a project."""
        await self.stop_project(project.slug, project.id, user_id)
        return await self.start_project(project, containers, connections, user_id, db)

    async def get_project_status(self, project_slug: str, project_id: UUID) -> dict[str, Any]:
        """Get status of all containers in a project."""
        namespace = self._get_namespace(str(project_id))

        try:
            # Check if namespace exists
            await asyncio.to_thread(self.k8s_client.core_v1.read_namespace, name=namespace)

            # Get all pods
            pods = await asyncio.to_thread(
                self.k8s_client.core_v1.list_namespaced_pod, namespace=namespace
            )

            # Build URL helper
            protocol = self.settings.k8s_container_url_protocol
            app_domain = self.settings.app_domain

            container_statuses = {}
            for pod in pods.items:
                component = pod.metadata.labels.get("tesslate.io/component", "unknown")
                container_dir = pod.metadata.labels.get("tesslate.io/container-directory")

                container_id = pod.metadata.labels.get("tesslate.io/container-id")

                if component == "file-manager":
                    container_statuses["file-manager"] = {
                        "phase": pod.status.phase,
                        "ready": self.k8s_client.is_pod_ready(pod),
                        "running": self.k8s_client.is_pod_ready(pod),
                    }
                elif component == "service-container" and container_dir:
                    is_ready = self.k8s_client.is_pod_ready(pod)
                    container_statuses[container_dir] = {
                        "phase": pod.status.phase,
                        "ready": is_ready,
                        "running": is_ready,
                        "url": None,  # Service containers are internal only
                        "service": True,
                        "container_id": container_id,
                    }
                elif container_dir:
                    is_ready = self.k8s_client.is_pod_ready(pod)
                    # Generate URL for this container
                    url = f"{protocol}://{project_slug}-{container_dir}.{app_domain}"
                    container_statuses[container_dir] = {
                        "phase": pod.status.phase,
                        "ready": is_ready,
                        "running": is_ready,
                        "url": url,
                        "container_id": container_id,
                    }

            # Derive overall status from user containers (exclude file-manager)
            user_containers = {k: v for k, v in container_statuses.items() if k != "file-manager"}
            if user_containers:
                all_running = all(info.get("running") for info in user_containers.values())
                overall_status = "running" if all_running else "partial"
            else:
                overall_status = "stopped"

            return {
                "status": overall_status,
                "namespace": namespace,
                "containers": container_statuses,
            }

        except ApiException as e:
            if e.status == 404:
                return {"status": "not_found", "namespace": namespace}
            return {"status": "error", "error": str(e)}

    # =========================================================================
    # EBS VOLUMESNAPSHOT HIBERNATION/RESTORATION
    # =========================================================================
    #
    # Uses Kubernetes VolumeSnapshots backed by AWS EBS CSI driver for:
    # - Near-instant hibernation (< 5 seconds)
    # - Near-instant restore (< 10 seconds, lazy loading)
    # - Full volume preservation (node_modules included - no npm install)
    # - Versioning (up to 5 snapshots per project)
    # - Soft delete (30-day retention after project deletion)
    #
    # CRITICAL: Always wait for snapshot.status.readyToUse=true before deleting PVC.
    # Deleting the PVC before the snapshot is ready will corrupt the data.
    # =========================================================================

    async def _is_project_initialized(self, namespace: str) -> bool:
        """
        Check if the project has actual files (not just an empty volume).

        This prevents creating empty snapshots when hibernation is triggered
        before the project has been fully initialized with files.

        Args:
            namespace: Kubernetes namespace for the project

        Returns:
            True if project has files, False if empty or not initialized
        """
        try:
            # Get file-manager pod
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            if not pod_name:
                logger.warning(
                    f"[K8S] No file-manager pod found in {namespace} - assuming not initialized"
                )
                return False

            # Check if /app has any subdirectories with actual files
            # We look for package.json as a marker of an initialized project
            check_script = """
find /app -maxdepth 2 -name 'package.json' 2>/dev/null | head -1
"""
            result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["/bin/sh", "-c", check_script],
                10,  # Short timeout since this is a quick check
            )

            has_files = bool(result and result.strip())
            logger.info(
                f"[K8S] Project initialization check for {namespace}: {'initialized' if has_files else 'NOT initialized'}"
            )
            return has_files

        except Exception as e:
            logger.warning(
                f"[K8S] Error checking project initialization: {e} - assuming not initialized"
            )
            return False

    async def _save_to_snapshot(
        self, project_id: UUID, user_id: UUID, namespace: str, db: AsyncSession
    ) -> bool:
        """
        Create VolumeSnapshots of the project PVC and any service PVCs (for hibernation).

        This operation is nearly instant (< 5 seconds total).
        EBS snapshots use copy-on-write - only changed blocks are stored.

        CRITICAL: We wait for the snapshot to become ready before returning.
        The caller should NOT delete the namespace until this returns True.

        Args:
            project_id: Project UUID
            user_id: User UUID
            namespace: Kubernetes namespace
            db: Database session

        Returns:
            True if snapshot created and ready, False otherwise
        """
        logger.info(f"[K8S:HIBERNATE] Creating VolumeSnapshot for project {project_id}")

        try:
            pvc_names = await self._get_hibernation_pvc_names(namespace)
            service_pvc_names = [name for name in pvc_names if name != "project-storage"]

            # IMPORTANT: Check if project is initialized before creating snapshot
            # This prevents creating empty snapshots for projects that haven't
            # been populated with files yet (e.g., newly created but not yet cloned)
            is_initialized = await self._is_project_initialized(namespace)
            if not is_initialized and not service_pvc_names:
                logger.warning(
                    f"[K8S:HIBERNATE] ⚠️ Skipping snapshot for {project_id} - project not initialized (no files). "
                    "This is normal for newly created projects that haven't been populated yet."
                )
                # Return True so the namespace can be deleted cleanly
                # (no data to preserve anyway)
                return True

            snapshot_manager = get_snapshot_manager()
            snapshot_pvcs = service_pvc_names.copy()
            if is_initialized and "project-storage" in pvc_names:
                snapshot_pvcs.insert(0, "project-storage")

            for pvc_name in snapshot_pvcs:
                snapshot, error = await snapshot_manager.create_snapshot(
                    project_id=project_id,
                    user_id=user_id,
                    db=db,
                    snapshot_type="hibernation",
                    pvc_name=pvc_name,
                )

                if error or snapshot is None:
                    logger.error(
                        f"[K8S:HIBERNATE] ❌ Failed to create snapshot for PVC {pvc_name}: {error}"
                    )
                    return False

                success, wait_error = await snapshot_manager.wait_for_snapshot_ready(
                    snapshot=snapshot, db=db
                )

                if not success:
                    logger.error(
                        f"[K8S:HIBERNATE] ❌ Snapshot for PVC {pvc_name} did not become ready: {wait_error}"
                    )
                    return False

                logger.info(
                    f"[K8S:HIBERNATE] ✅ VolumeSnapshot ready for PVC {pvc_name}: {snapshot.snapshot_name}"
                )

            return True

        except Exception as e:
            logger.error(f"[K8S:HIBERNATE] Error creating snapshot: {e}", exc_info=True)
            return False

    async def _restore_from_snapshot(
        self, project_id: UUID, user_id: UUID, _namespace: str, db: AsyncSession
    ) -> bool:
        """
        Create a PVC from a VolumeSnapshot (after hibernation).

        This operation is nearly instant (< 10 seconds).
        EBS lazy-loads data blocks on first read - no waiting for full restore.

        The PVC is created with dataSource pointing to the VolumeSnapshot.
        The volume is available immediately; data is loaded on-demand.

        Args:
            project_id: Project UUID
            user_id: User UUID
            _namespace: Kubernetes namespace (unused - snapshot manager handles namespace)
            db: Database session

        Returns:
            True if PVC created successfully, False otherwise
        """
        logger.info(f"[K8S:RESTORE] Restoring project {project_id} from VolumeSnapshot")

        try:
            snapshot_manager = get_snapshot_manager()

            restored_project_storage = False

            if await snapshot_manager.has_existing_snapshot(
                project_id, db, pvc_name="project-storage", snapshot_type="hibernation"
            ):
                restored_project_storage, error = await snapshot_manager.restore_from_snapshot(
                    project_id=project_id,
                    user_id=user_id,
                    db=db,
                    pvc_name="project-storage",
                )
                if not restored_project_storage:
                    logger.error(
                        f"[K8S:RESTORE] ❌ Failed to restore project-storage from snapshot: {error}"
                    )
            else:
                logger.warning(f"[K8S:RESTORE] No project-storage snapshot found for {project_id}")

            service_snapshots = await snapshot_manager.get_latest_ready_snapshots_by_pvc(
                project_id=project_id,
                db=db,
                snapshot_type="hibernation",
            )

            for pvc_name, snapshot in service_snapshots.items():
                if pvc_name == "project-storage":
                    continue
                success, error = await snapshot_manager.restore_from_snapshot(
                    project_id=project_id,
                    user_id=user_id,
                    db=db,
                    snapshot_id=snapshot.id,
                    pvc_name=pvc_name,
                )
                if not success:
                    logger.error(
                        f"[K8S:RESTORE] ❌ Failed to restore service PVC {pvc_name}: {error}"
                    )
                    return restored_project_storage

                logger.info(
                    f"[K8S:RESTORE] ✅ Restored service PVC {pvc_name} from snapshot {snapshot.snapshot_name}"
                )

            if restored_project_storage:
                logger.info("[K8S:RESTORE] ✅ PVCs restored from snapshot (lazy loading active)")
            return restored_project_storage

        except Exception as e:
            logger.error(f"[K8S:RESTORE] Error restoring from snapshot: {e}", exc_info=True)
            return False

    async def _get_hibernation_pvc_names(self, namespace: str) -> list[str]:
        """List PVCs that should be included in project hibernation snapshots."""
        pvcs = await asyncio.to_thread(
            self.k8s_client.core_v1.list_namespaced_persistent_volume_claim,
            namespace=namespace,
        )

        snapshot_pvcs = {"project-storage"}
        for pvc in pvcs.items:
            name = pvc.metadata.name
            labels = pvc.metadata.labels or {}
            if labels.get("tesslate.io/component") == "service-storage" or name.startswith("svc-"):
                snapshot_pvcs.add(name)

        return sorted(snapshot_pvcs)

    # =========================================================================
    # FILE OPERATIONS (via FileOps)
    # =========================================================================

    @staticmethod
    def _build_pod_path(file_path: str, subdir: str | None = None) -> str:
        """Build a normalized path inside /app in the container.

        Handles:
        - Absolute paths (e.g. /app/src/file.tsx) used as-is
        - subdir="." treated as no subdir
        - Path normalization (collapsing .., ., double slashes)
        - Containment check to ensure path stays within /app/
        """
        base = PurePosixPath("/app")
        if subdir and subdir != ".":
            base = base / subdir

        normalized = PurePosixPath(os.path.normpath(str(base / file_path)))

        # Containment: must still be under /app
        try:
            normalized.relative_to(PurePosixPath("/app"))
        except ValueError as err:
            raise ValueError(
                f"Path escapes container boundary: {file_path!r} (resolved to {normalized})"
            ) from err

        return str(normalized)

    async def read_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        project_slug: str = None,
        subdir: str = None,
        # Volume routing hints (optional -- avoids DB lookup when provided)
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> str | None:
        """Read a file from project storage via FileOps."""
        _ = user_id, container_name, project_slug  # Interface params; FileOps uses volume routing

        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project_id)

        vol_path = self._build_volume_path(file_path, subdir)
        try:
            return await self._fileops_call(
                volume_id,
                lambda c, vid=volume_id, vp=vol_path: c.read_file_text(vid, vp),
            )
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                return None
            logger.error(f"[K8S] FileOps read_file error: {e}")
            return None
        except (VolumeRestoringError, VolumeUnavailableError):
            raise
        except Exception as e:
            logger.error(f"[K8S] FileOps read_file error: {e}")
            return None

    async def write_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        content: str,
        project_slug: str = None,
        subdir: str = None,
        # Volume routing hints
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> bool:
        """Write a file to project storage via FileOps."""
        _ = user_id, container_name, project_slug  # Interface params; FileOps uses volume routing

        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project_id)

        vol_path = self._build_volume_path(file_path, subdir)
        try:
            await self._fileops_call(
                volume_id,
                lambda c, vid=volume_id, vp=vol_path, ct=content: c.write_file_text(vid, vp, ct),
            )
            return True
        except Exception as e:
            logger.error(f"[K8S] FileOps write_file error: {e}")
            raise

    async def write_binary_to_container(
        self,
        project_id: UUID,
        file_path: str,
        data: bytes,
        # Volume routing hints
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> bool:
        """Write binary data to a file in the project via FileOps."""
        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project_id)

        vol_path = self._build_volume_path(file_path)
        try:
            await self._fileops_call(
                volume_id,
                lambda c, vid=volume_id, vp=vol_path, d=data: c.write_file(vid, vp, d),
            )
            return True
        except Exception as e:
            logger.error(f"[K8S] FileOps write_binary error: {e}")
            raise

    async def delete_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        # Volume routing hints
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> bool:
        """Delete a file from project storage via FileOps."""
        _ = user_id, container_name  # Interface params; FileOps uses volume routing

        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project_id)

        vol_path = self._build_volume_path(file_path)
        try:
            await self._fileops_call(
                volume_id,
                lambda c, vid=volume_id, vp=vol_path: c.delete_path(vid, vp),
            )
            return True
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                return True  # Already gone
            logger.error(f"[K8S] FileOps delete_file error: {e}")
            return False
        except (VolumeRestoringError, VolumeUnavailableError):
            raise
        except Exception as e:
            logger.error(f"[K8S] FileOps delete_file error: {e}")
            return False

    async def list_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        directory: str = ".",
        # Volume routing hints
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> list[dict[str, Any]]:
        """List files in project storage via FileOps."""
        _ = user_id, container_name  # Interface params; FileOps uses volume routing

        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project_id)

        vol_path = self._build_volume_path(directory) if directory != "." else "."
        try:
            entries = await self._fileops_call(
                volume_id,
                lambda c, vid=volume_id, vp=vol_path: c.list_dir(vid, vp),
            )
            return [
                {
                    "name": entry.name,
                    "type": "directory" if entry.is_dir else "file",
                    "size": entry.size,
                    "permissions": "",
                }
                for entry in entries
            ]
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                return []
            logger.error(f"[K8S] FileOps list_files error: {e}")
            return []
        except (VolumeRestoringError, VolumeUnavailableError):
            raise
        except Exception as e:
            logger.error(f"[K8S] FileOps list_files error: {e}")
            return []

    async def list_tree(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        subdir: str | None = None,
        # Volume routing hints
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> list[dict[str, Any]]:
        """Recursive filtered file tree via FileOps ListTree RPC."""
        _ = user_id, container_name

        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project_id)

        vol_path = self._build_volume_path(subdir) if subdir else "."
        try:
            entries = await self._fileops_call(
                volume_id,
                lambda c, vid=volume_id, vp=vol_path: c.list_tree(
                    vid,
                    vp,
                    exclude_dirs=_TREE_EXCLUDE_DIRS,
                    exclude_files=_TREE_EXCLUDE_FILES,
                    exclude_extensions=_TREE_EXCLUDE_EXTS,
                ),
            )
            return [
                {
                    "path": entry.path,
                    "name": entry.name,
                    "is_dir": entry.is_dir,
                    "size": entry.size,
                    "mod_time": entry.mod_time,
                }
                for entry in entries
            ]
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                return []
            logger.error(f"[K8S] FileOps list_tree error: {e}")
            return []
        except (VolumeRestoringError, VolumeUnavailableError):
            raise
        except Exception as e:
            logger.error(f"[K8S] FileOps list_tree error: {e}")
            return []

    async def read_file_content(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        subdir: str | None = None,
        # Volume routing hints
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> dict[str, Any] | None:
        """Read a single file via FileOps."""
        _ = user_id, container_name

        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project_id)

        vol_path = self._build_volume_path(file_path, subdir)
        try:
            content = await self._fileops_call(
                volume_id,
                lambda c, vid=volume_id, vp=vol_path: c.read_file_text(vid, vp),
            )
            return {"path": file_path, "content": content, "size": len(content)}
        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                return None
            logger.error(f"[K8S] FileOps read_file_content error: {e}")
            return None
        except (VolumeRestoringError, VolumeUnavailableError):
            raise
        except Exception as e:
            logger.error(f"[K8S] FileOps read_file_content error: {e}")
            return None

    async def read_files_batch(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        paths: list[str],
        subdir: str | None = None,
        # Volume routing hints
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Batch-read multiple files via FileOps ReadFiles RPC."""
        _ = user_id, container_name

        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project_id)

        vol_paths = [self._build_volume_path(p, subdir) for p in paths]
        # Map volume paths back to original caller paths for the response.
        vol_to_orig = dict(zip(vol_paths, paths, strict=True))
        try:
            file_contents, rpc_errors = await self._fileops_call(
                volume_id,
                lambda c, vid=volume_id, vp=vol_paths: c.read_files(vid, vp, max_file_size=100_000),
            )
            files = [
                {"path": vol_to_orig.get(fc.path, fc.path), "content": fc.data, "size": fc.size}
                for fc in file_contents
            ]
            errors = [vol_to_orig.get(e, e) for e in rpc_errors]
            return files, errors
        except (VolumeRestoringError, VolumeUnavailableError):
            raise
        except Exception as e:
            logger.error(f"[K8S] FileOps read_files_batch error: {e}")
            return [], list(paths)

    # =========================================================================
    # SHELL OPERATIONS
    # =========================================================================

    async def execute_command(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        command: list[str],
        timeout: int = 120,
        working_dir: str | None = None,
    ) -> str:
        """Execute a command in project environment."""
        namespace = self._get_namespace(str(project_id))

        # Build full command with working directory
        if working_dir:
            full_command = [
                "sh",
                "-c",
                f"cd {shlex.quote(self._build_pod_path(working_dir))} && {shlex.join(command)}",
            ]
        else:
            full_command = command

        try:
            # Try file-manager first, then dev container
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            container = "file-manager"

            if not pod_name:
                # Fall back to dev container
                return await self.k8s_client.execute_command_in_pod(
                    user_id=user_id,
                    project_id=str(project_id),
                    command=full_command,
                    timeout=timeout,
                    container_name=container_name,
                )

            return await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                container,
                full_command,
                timeout=timeout,
            )

        except Exception as e:
            logger.error(f"[K8S] Error executing command: {e}")
            raise

    async def is_container_ready(
        self, user_id: UUID, project_id: UUID, container_name: str
    ) -> dict[str, Any]:
        """Check if a container is ready for commands."""
        namespace = self._get_namespace(str(project_id))

        # Check if file-manager is ready (for file operations)
        pod_name = await self.k8s_client.get_file_manager_pod(namespace)
        if pod_name:
            return {"ready": True, "pod": "file-manager"}

        # Fall back to checking dev container
        return await self.k8s_client.check_pod_ready(
            user_id=user_id,
            project_id=str(project_id),
            check_responsive=True,
            container_name=container_name,
        )

    # =========================================================================
    # ACTIVITY TRACKING & CLEANUP (Database-based for horizontal scaling)
    # =========================================================================

    def track_activity(
        self, user_id: UUID, project_id: str, container_name: str | None = None
    ) -> None:
        """
        DEPRECATED: No-op method retained for interface compatibility.

        Activity tracking is now database-based. Use track_project_activity()
        from orchestrator/app/services/activity_tracker.py instead.
        """
        _ = user_id, project_id, container_name  # No-op; all params unused

        # Log warning on first call to help identify callers that need updating
        logger.debug(
            "[K8S] track_activity() called but is a no-op. "
            "Use activity_tracker.track_project_activity() instead."
        )

    # =========================================================================
    # LOG STREAMING
    # =========================================================================

    async def stream_logs(
        self,
        project_id: UUID,
        user_id: UUID,
        container_id: UUID | None = None,
        tail_lines: int = 100,
    ) -> AsyncIterator[str]:
        _ = user_id  # Part of interface; unused in K8s mode

        namespace = self._get_namespace(str(project_id))

        try:
            core_v1 = self.k8s_client.core_v1

            # Find the target pod
            if container_id:
                pods = await asyncio.to_thread(
                    core_v1.list_namespaced_pod,
                    namespace,
                    label_selector=f"tesslate.io/container-id={container_id}",
                )
            else:
                pods = await asyncio.to_thread(
                    core_v1.list_namespaced_pod,
                    namespace,
                    label_selector="tesslate.io/component=dev-container",
                )

            if not pods.items:
                logger.warning(f"[K8S] No pods found for log streaming in {namespace}")
                return

            pod = pods.items[0]
            pod_name = pod.metadata.name

            # Determine container name within pod
            k8s_container_name = "dev-server"
            if (
                container_id
                and pod.metadata.labels.get("tesslate.io/component") == "service-container"
                and pod.spec.containers
            ):
                k8s_container_name = pod.spec.containers[0].name

            # Ensure tmux pipe-pane routes dev server output to container stdout.
            # New containers get this in the startup command (helpers.py), but
            # existing containers started before the fix need it enabled on-demand.
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    self.k8s_client._exec_in_pod,
                    pod_name,
                    namespace,
                    k8s_container_name,
                    [
                        "sh",
                        "-c",
                        "tmux pipe-pane -o -t main 'cat > /proc/1/fd/1' 2>/dev/null || true",
                    ],
                    10,
                )

            # Stream logs using queue bridge (K8s stream is synchronous)
            stop_event = asyncio.Event()
            queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1000)

            def _read_k8s_logs():
                resp = None
                try:
                    resp = core_v1.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=namespace,
                        container=k8s_container_name,
                        follow=True,
                        tail_lines=tail_lines,
                        _preload_content=False,
                    )
                    # resp is a RESTResponse wrapping urllib3.HTTPResponse.
                    # Iterating directly blocks forever with follow=True —
                    # must use .stream() on the underlying urllib3 response.
                    raw = getattr(resp, "urllib3_response", resp)
                    buffer = b""
                    for chunk in raw.stream(amt=4096, decode_content=True):
                        if stop_event.is_set():
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line_bytes, buffer = buffer.split(b"\n", 1)
                            line_str = line_bytes.decode("utf-8", errors="replace")
                            with contextlib.suppress(asyncio.QueueFull):
                                queue.put_nowait(line_str)
                    # Flush remaining partial line
                    if buffer and not stop_event.is_set():
                        with contextlib.suppress(asyncio.QueueFull):
                            queue.put_nowait(buffer.decode("utf-8", errors="replace"))
                except Exception as e:
                    if not stop_event.is_set():
                        logger.error(f"[K8S] Log stream error: {e}")
                finally:
                    if resp is not None:
                        with contextlib.suppress(Exception):
                            raw = getattr(resp, "urllib3_response", resp)
                            raw.close()
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(None)

            asyncio.get_running_loop().run_in_executor(None, _read_k8s_logs)

            try:
                while True:
                    line = await queue.get()
                    if line is None:
                        break
                    yield line
            finally:
                stop_event.set()

        except ApiException as e:
            if e.status == 404:
                logger.warning(f"[K8S] Namespace or pod not found: {namespace}")
            else:
                logger.error(f"[K8S] API error streaming logs: {e}")
        except Exception as e:
            logger.error(f"[K8S] Error streaming logs: {e}")

    # =========================================================================
    # ADVANCED OPERATIONS
    # =========================================================================

    async def glob_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        pattern: str,
        directory: str = ".",
        # Volume routing hints
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find files matching a glob pattern via FileOps."""
        _ = user_id, container_name  # Interface params; FileOps uses volume routing

        import fnmatch

        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project_id)

        vol_path = self._build_volume_path(directory) if directory != "." else "."
        try:
            entries = await self._fileops_call(
                volume_id,
                lambda c, vid=volume_id, vp=vol_path: c.list_dir(vid, vp, recursive=True),
            )
            return [
                {
                    "name": entry.name,
                    "path": entry.path,
                    "type": "directory" if entry.is_dir else "file",
                    "size": entry.size,
                }
                for entry in entries
                if not entry.is_dir and fnmatch.fnmatch(entry.name, pattern)
            ]
        except (VolumeRestoringError, VolumeUnavailableError):
            raise
        except Exception as e:
            logger.error(f"[K8S] FileOps glob_files error: {e}")
            return []

    async def grep_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        pattern: str,
        directory: str = ".",
        file_pattern: str = "*",
        case_sensitive: bool = True,
        max_results: int = 100,
        # Volume routing hints
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search file contents for a pattern via FileOps."""
        _ = user_id, container_name  # Interface params; FileOps uses volume routing

        import fnmatch
        import re

        if volume_id is None:
            volume_id, cache_node = await self._get_project_volume_info(project_id)

        vol_path = self._build_volume_path(directory) if directory != "." else "."

        async def _grep(client):
            regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
            entries = await client.list_dir(volume_id, vol_path, recursive=True)
            results = []
            for entry in entries:
                if entry.is_dir:
                    continue
                if file_pattern != "*" and not fnmatch.fnmatch(entry.name, file_pattern):
                    continue
                try:
                    content = await client.read_file_text(volume_id, entry.path)
                    for line_no, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            results.append(
                                {
                                    "file": entry.path,
                                    "line": line_no,
                                    "content": line.rstrip(),
                                }
                            )
                            if len(results) >= max_results:
                                return results
                except Exception:
                    continue
            return results

        try:
            return await self._fileops_call(volume_id, _grep)
        except (VolumeRestoringError, VolumeUnavailableError):
            raise
        except Exception as e:
            logger.error(f"[K8S] FileOps grep_files error: {e}")
            return []


# Singleton instance
_kubernetes_orchestrator: KubernetesOrchestrator | None = None


def get_kubernetes_orchestrator() -> KubernetesOrchestrator:
    """Get the singleton Kubernetes orchestrator instance."""
    global _kubernetes_orchestrator

    if _kubernetes_orchestrator is None:
        _kubernetes_orchestrator = KubernetesOrchestrator()

    return _kubernetes_orchestrator
