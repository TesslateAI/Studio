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
import logging
from datetime import UTC
from typing import Any
from uuid import UUID

from kubernetes.client.rest import ApiException
from sqlalchemy.ext.asyncio import AsyncSession

from ..secret_manager_env import build_env_overrides
from ..snapshot_manager import get_snapshot_manager
from .base import BaseOrchestrator
from .deployment_mode import DeploymentMode
from .kubernetes.client import KubernetesClient, get_k8s_client
from .kubernetes.helpers import (
    create_container_deployment,
    create_file_manager_deployment,
    create_ingress_manifest,
    create_network_policy_manifest,
    create_pvc_manifest,
    create_service_manifest,
    generate_git_clone_script,
)

logger = logging.getLogger(__name__)


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
        """Sanitize a name for Kubernetes (DNS-1123 compliant)."""
        safe_name = name.lower().replace(" ", "-").replace("_", "-").replace(".", "-")
        safe_name = "".join(c for c in safe_name if c.isalnum() or c == "-")
        while "--" in safe_name:
            safe_name = safe_name.replace("--", "-")
        safe_name = safe_name.strip("-")
        return safe_name[:63]

    def _get_namespace(self, project_id: str) -> str:
        """Get namespace for a project."""
        return self.k8s_client.get_project_namespace(project_id)

    async def _get_tesslate_config_from_pod(
        self, namespace: str, container_directory: str
    ) -> Any | None:
        """
        Read and parse TESSLATE.md from the file-manager pod.

        In K8s mode, we can't use Docker volumes, so we read directly from the pod.

        Args:
            namespace: K8s namespace
            container_directory: Container directory name (e.g., "next-js-15")

        Returns:
            Parsed BaseConfig or None
        """
        from ...services.base_config_parser import parse_tesslate_md

        try:
            # Find file-manager pod
            logger.info(f"[K8S] Looking for file-manager pod in namespace {namespace}")
            pods = self.k8s_client.core_v1.list_namespaced_pod(
                namespace=namespace, label_selector="app=file-manager"
            )

            if not pods.items:
                logger.warning(f"[K8S] No file-manager pod found in {namespace}")
                return None

            pod_name = pods.items[0].metadata.name
            logger.info(f"[K8S] Found file-manager pod: {pod_name}")

            # Read TESSLATE.md from the pod
            tesslate_path = f"/app/{container_directory}/TESSLATE.md"
            logger.info(f"[K8S] Reading TESSLATE.md from {tesslate_path}")

            result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["cat", tesslate_path],
                timeout=10,
            )

            logger.info(f"[K8S] TESSLATE.md read result: {result[:200] if result else 'None'}...")

            if result and not result.startswith("cat:"):
                config = parse_tesslate_md(result)
                logger.info(
                    f"[K8S] Parsed config: start_command={config.start_command if config else 'None'}"
                )

                if config and config.validate():
                    logger.info(
                        f"[K8S] ✅ Validated TESSLATE.md: start_command={config.start_command}"
                    )
                    return config
                else:
                    logger.warning(
                        f"[K8S] TESSLATE.md validation failed: {config.validation_error if config else 'no config'}"
                    )
            else:
                logger.warning(f"[K8S] TESSLATE.md not found or error: {result}")

        except Exception as e:
            logger.error(f"[K8S] Could not read TESSLATE.md from pod: {e}", exc_info=True)

        return None

    # =========================================================================
    # PROJECT ENVIRONMENT LIFECYCLE
    # =========================================================================

    async def ensure_project_environment(
        self,
        project_id: UUID,
        user_id: UUID,
        is_hibernated: bool = False,
        db: AsyncSession | None = None,
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
                pvc = create_pvc_manifest(
                    namespace=namespace,
                    project_id=project_id,
                    user_id=user_id,
                    storage_class=self.settings.k8s_storage_class,
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
        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)
        target_dir = f"/app/{container_directory}"

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
if [ -d '{target_dir}' ] && [ -f '{target_dir}/package.json' ]; then
    file_count=$(ls -1 '{target_dir}' 2>/dev/null | wc -l)
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
                if file_count >= 3:  # At least package.json, README.md, and one more file
                    logger.info(
                        f"[K8S] Directory {target_dir} already exists with {file_count} files, skipping git clone"
                    )
                    return True
                else:
                    logger.warning(
                        f"[K8S] Directory {target_dir} exists but only has {file_count} files, will re-clone"
                    )
                    # Fall through to clone

            # CRITICAL: git_url is REQUIRED - containers must have a marketplace base with git repo
            if not git_url:
                raise RuntimeError(
                    f"Container '{container_directory}' has no git_url. "
                    "All containers must be created from a marketplace base with a git repository."
                )

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

            logger.info(f"[K8S] ✅ Files initialized for {container_directory}")
            logger.debug(f"[K8S] Init output: {result[:500]}...")
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
        Start a single container (create Deployment + Service + Ingress).

        Files should already exist from initialize_container_files().
        NO init containers needed - files already exist on PVC!

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
        project_id = str(project.id)
        namespace = self._get_namespace(project_id)
        # Use container.name if directory is "." or empty (root directory = use container name)
        dir_for_k8s = (
            container.name if container.directory in (".", "", None) else container.directory
        )
        container_directory = self._sanitize_name(dir_for_k8s)

        logger.info(f"[K8S] Starting container '{container_directory}' in namespace {namespace}")

        # Import WebSocket manager for status updates
        from ...routers.chat import get_chat_connection_manager

        ws_manager = get_chat_connection_manager()

        async def send_progress(phase: str, message: str, progress: int, **kwargs):
            """Helper to send progress updates via WebSocket."""
            try:
                status = {
                    "container_status": "starting",
                    "phase": phase,
                    "message": message,
                    "progress": progress,
                    **kwargs,
                }
                await ws_manager.send_status_update(user_id, project.id, status)
            except Exception:
                pass  # Don't fail container start if WebSocket fails

        try:
            # Check if project was hibernated (needs snapshot restoration)
            is_hibernated = project.environment_status == "hibernated"

            # Send initial progress
            await send_progress("creating_environment", "Creating project environment...", 10)

            # Ensure environment exists (check K8s namespace)
            namespace_exists = await self.k8s_client.namespace_exists(namespace)
            if not namespace_exists:
                if is_hibernated:
                    await send_progress(
                        "restoring_files", "Restoring project files from snapshot...", 20
                    )

                await self.ensure_project_environment(
                    project.id, user_id, is_hibernated=is_hibernated, db=db
                )

                # Update environment_status to 'active' after restore
                if is_hibernated:
                    project.environment_status = "active"
                    project.hibernated_at = None
                    await db.commit()
                    logger.info(f"[K8S] Restored hibernated project {project.slug} from snapshot")
                    await send_progress("files_restored", "Project files restored successfully", 40)

            # CRITICAL: Initialize container files BEFORE starting
            # Skip if project was restored from snapshot (files already exist)
            if is_hibernated:
                logger.info("[K8S] Skipping git clone - project restored from snapshot")
            else:
                # This clones from git or sets up the project directory
                git_url = None
                if container.base and hasattr(container.base, "git_repo_url"):
                    git_url = container.base.git_repo_url

                await send_progress("initializing_files", "Setting up project files...", 50)
                logger.info(
                    f"[K8S] Initializing files for container {container_directory} (git_url={git_url})"
                )
                await self.initialize_container_files(
                    project_id=project.id,
                    user_id=user_id,
                    container_id=container.id,
                    container_directory=container_directory,
                    git_url=git_url,
                )

            # Get base config for port and startup command
            # Read TESSLATE.md directly from the file-manager pod
            base_config = await self._get_tesslate_config_from_pod(namespace, container_directory)

            # Determine port and startup command from base config
            port = container.internal_port or (base_config.port if base_config else 3000)

            # Get startup command as a string for tmux (convert newlines to &&)
            if base_config and base_config.start_command:
                # Convert multi-line commands to single-line shell command
                startup_command = " && ".join(
                    line.strip()
                    for line in base_config.start_command.strip().split("\n")
                    if line.strip() and not line.strip().startswith("#")
                )
                logger.info(f"[K8S] ✅ Using TESSLATE.md start_command: {startup_command}")
            else:
                # Fallback: generic command that installs deps and starts dev server
                startup_command = "npm install && npm run dev"
                logger.warning(f"[K8S] ⚠️ No base_config found, using fallback: {startup_command}")

            # Prepend node_modules/.bin permission fix (safety net for all platforms)
            from ...services.base_config_parser import get_node_modules_fix_prefix

            startup_command = get_node_modules_fix_prefix() + startup_command

            logger.info(f"[K8S] Container config: port={port}, cmd={startup_command}")

            await send_progress("starting_server", "Starting development server...", 70)

            env_overrides = await build_env_overrides(db, project.id, [container])
            extra_env = env_overrides.get(container.id, {})

            # Create Deployment (NO init containers - files already exist!)
            deployment = create_container_deployment(
                namespace=namespace,
                project_id=project.id,
                user_id=user_id,
                container_id=container.id,
                container_directory=container_directory,
                image=self.settings.k8s_devserver_image,
                port=port,
                startup_command=startup_command,
                image_pull_policy=self.settings.k8s_image_pull_policy,
                image_pull_secret=self.settings.k8s_image_pull_secret or None,
                enable_pod_affinity=self.settings.k8s_enable_pod_affinity
                and len(all_containers) > 1,
                affinity_topology_key=self.settings.k8s_affinity_topology_key,
                extra_env=extra_env,
            )
            await self.k8s_client.create_deployment(deployment, namespace)

            # Create Service
            service = create_service_manifest(
                namespace=namespace,
                project_id=project.id,
                container_id=container.id,
                container_directory=container_directory,
                port=port,
            )
            await self.k8s_client.create_service(service, namespace)

            # Create Ingress
            ingress = create_ingress_manifest(
                namespace=namespace,
                project_id=project.id,
                container_id=container.id,
                container_directory=container_directory,
                project_slug=project.slug,
                port=port,
                domain=self.settings.app_domain,
                ingress_class=self.settings.k8s_ingress_class,
                tls_secret=self.settings.k8s_wildcard_tls_secret or None,
            )
            await self.k8s_client.create_ingress(ingress, namespace)

            # Build preview URL (single subdomain level for wildcard cert compatibility)
            hostname = f"{project.slug}-{container_directory}.{self.settings.app_domain}"
            protocol = "https" if self.settings.k8s_wildcard_tls_secret else "http"
            preview_url = f"{protocol}://{hostname}"

            # Activity tracking is now database-based (via activity_tracker service)

            logger.info(f"[K8S] ✅ Container started: {preview_url}")

            # Send ready notification with URL
            await send_progress(
                "ready", "Container is ready!", 100, container_status="ready", url=preview_url
            )

            return {
                "status": "running",
                "container_name": container.name,
                "container_directory": container_directory,
                "url": preview_url,
                "namespace": namespace,
                "port": port,
            }

        except Exception as e:
            logger.error(f"[K8S] Error starting container: {e}", exc_info=True)
            raise

    async def stop_container(
        self, project_slug: str, project_id: UUID, container_name: str, user_id: UUID
    ) -> None:
        """
        Stop a single container (delete Deployment + Service + Ingress).

        Files PERSIST on PVC via file-manager pod.

        Args:
            project_slug: Project slug
            project_id: Project UUID
            container_name: Container name
            user_id: User UUID
        """
        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)
        container_directory = self._sanitize_name(container_name)

        deployment_name = f"dev-{container_directory}"
        service_name = f"dev-{container_directory}"
        ingress_name = f"dev-{container_directory}"

        logger.info(f"[K8S] Stopping container '{container_directory}' in namespace {namespace}")

        try:
            # Delete Deployment
            await self.k8s_client.delete_deployment(deployment_name, namespace)
            # Delete Service
            await self.k8s_client.delete_service(service_name, namespace)
            # Delete Ingress
            await self.k8s_client.delete_ingress(ingress_name, namespace)

            logger.info("[K8S] ✅ Container stopped (files persist on PVC)")

        except Exception as e:
            if "404" not in str(e):
                logger.error(f"[K8S] Error stopping container: {e}")
                raise

    async def get_container_status(
        self, project_slug: str, project_id: UUID, container_name: str | None, user_id: UUID
    ) -> dict[str, Any]:
        """Get status of a single container or the project environment.

        If container_name is None, returns overall project/file-manager status.
        """
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

        # Specific container status
        container_directory = self._sanitize_name(container_name)
        deployment_name = f"dev-{container_directory}"

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
                return {"status": "stopped", "container_name": container_name}
            raise

    # =========================================================================
    # PROJECT LIFECYCLE (START/STOP ALL)
    # =========================================================================

    async def start_project(
        self, project, containers: list, connections: list, user_id: UUID, db: AsyncSession
    ) -> dict[str, Any]:
        """Start all containers for a project."""
        logger.info(f"[K8S] Starting project {project.slug} with {len(containers)} containers")

        # Check if project was hibernated (needs snapshot restoration)
        is_hibernated = project.environment_status == "hibernated"

        # Ensure environment exists (with snapshot restoration if hibernated)
        namespace = await self.ensure_project_environment(
            project.id, user_id, is_hibernated=is_hibernated, db=db
        )

        # Update environment_status to 'active' after restore
        if is_hibernated:
            project.environment_status = "active"
            project.hibernated_at = None
            await db.commit()
            logger.info(f"[K8S] Restored hibernated project {project.slug} from snapshot")

        # Start each container
        container_urls = {}
        for container in containers:
            result = await self.start_container(
                project=project,
                container=container,
                all_containers=containers,
                connections=connections,
                user_id=user_id,
                db=db,
            )
            container_urls[container.name] = result.get("url")

        logger.info(f"[K8S] ✅ Project {project.slug} started")

        return {
            "status": "running",
            "project_slug": project.slug,
            "namespace": namespace,
            "containers": container_urls,
        }

    async def stop_project(self, project_slug: str, project_id: UUID, user_id: UUID) -> None:
        """Stop all containers for a project (but keep files)."""
        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)

        logger.info(f"[K8S] Stopping project {project_slug}")

        try:
            # Delete all dev container deployments (but keep file-manager)
            deployments = await asyncio.to_thread(
                self.k8s_client.apps_v1.list_namespaced_deployment,
                namespace=namespace,
                label_selector="tesslate.io/component=dev-container",
            )

            for deployment in deployments.items:
                await self.k8s_client.delete_deployment(deployment.metadata.name, namespace)

            # Delete all dev container services
            services = await asyncio.to_thread(
                self.k8s_client.core_v1.list_namespaced_service,
                namespace=namespace,
                label_selector="tesslate.io/container-id",
            )

            for service in services.items:
                await self.k8s_client.delete_service(service.metadata.name, namespace)

            # Delete all dev container ingresses
            ingresses = await asyncio.to_thread(
                self.k8s_client.networking_v1.list_namespaced_ingress,
                namespace=namespace,
                label_selector="tesslate.io/container-id",
            )

            for ingress in ingresses.items:
                await self.k8s_client.delete_ingress(ingress.metadata.name, namespace)

            logger.info("[K8S] ✅ Project stopped (file-manager and files persist)")

        except ApiException as e:
            if e.status != 404:
                logger.error(f"[K8S] Error stopping project: {e}")
                raise

    async def delete_project_namespace(self, project_id: UUID, user_id: UUID) -> None:
        """
        Delete the entire Kubernetes namespace for a project.

        This completely removes all resources (pods, services, ingresses, PVCs)
        and should only be called when permanently deleting a project.
        """
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
            protocol = "https" if self.settings.k8s_wildcard_tls_secret else "http"
            app_domain = self.settings.app_domain

            container_statuses = {}
            for pod in pods.items:
                component = pod.metadata.labels.get("tesslate.io/component", "unknown")
                container_dir = pod.metadata.labels.get("tesslate.io/container-directory")

                if component == "file-manager":
                    container_statuses["file-manager"] = {
                        "phase": pod.status.phase,
                        "ready": self.k8s_client.is_pod_ready(pod),
                        "running": self.k8s_client.is_pod_ready(pod),
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
                    }

            return {"status": "active", "namespace": namespace, "containers": container_statuses}

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
        Create a VolumeSnapshot of the project PVC (for hibernation).

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
            # IMPORTANT: Check if project is initialized before creating snapshot
            # This prevents creating empty snapshots for projects that haven't
            # been populated with files yet (e.g., newly created but not yet cloned)
            is_initialized = await self._is_project_initialized(namespace)
            if not is_initialized:
                logger.warning(
                    f"[K8S:HIBERNATE] ⚠️ Skipping snapshot for {project_id} - project not initialized (no files). "
                    "This is normal for newly created projects that haven't been populated yet."
                )
                # Return True so the namespace can be deleted cleanly
                # (no data to preserve anyway)
                return True

            snapshot_manager = get_snapshot_manager()

            # Create the snapshot record and K8s VolumeSnapshot
            snapshot, error = await snapshot_manager.create_snapshot(
                project_id=project_id,
                user_id=user_id,
                db=db,
                snapshot_type="hibernation",
                pvc_name="project-storage",
            )

            if error:
                logger.error(f"[K8S:HIBERNATE] ❌ Failed to create snapshot: {error}")
                return False

            # CRITICAL: Wait for snapshot to become ready before allowing PVC deletion
            success, wait_error = await snapshot_manager.wait_for_snapshot_ready(
                snapshot=snapshot, db=db
            )

            if not success:
                logger.error(f"[K8S:HIBERNATE] ❌ Snapshot did not become ready: {wait_error}")
                return False

            logger.info(f"[K8S:HIBERNATE] ✅ VolumeSnapshot ready: {snapshot.snapshot_name}")
            return True

        except Exception as e:
            logger.error(f"[K8S:HIBERNATE] Error creating snapshot: {e}", exc_info=True)
            return False

    async def _restore_from_snapshot(
        self, project_id: UUID, user_id: UUID, namespace: str, db: AsyncSession
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
            namespace: Kubernetes namespace
            db: Database session

        Returns:
            True if PVC created successfully, False otherwise
        """
        logger.info(f"[K8S:RESTORE] Restoring project {project_id} from VolumeSnapshot")

        try:
            snapshot_manager = get_snapshot_manager()

            # Check if project has a snapshot to restore from
            has_snapshot = await snapshot_manager.has_existing_snapshot(project_id, db)
            if not has_snapshot:
                logger.warning(f"[K8S:RESTORE] No snapshot found for project {project_id}")
                return False

            # Create PVC from snapshot
            success, error = await snapshot_manager.restore_from_snapshot(
                project_id=project_id, user_id=user_id, db=db, pvc_name="project-storage"
            )

            if not success:
                logger.error(f"[K8S:RESTORE] ❌ Failed to restore from snapshot: {error}")
                return False

            logger.info("[K8S:RESTORE] ✅ PVC created from snapshot (lazy loading active)")
            return True

        except Exception as e:
            logger.error(f"[K8S:RESTORE] Error restoring from snapshot: {e}", exc_info=True)
            return False

    async def hibernate_project(
        self, project_id: UUID, user_id: UUID, db: AsyncSession | None = None
    ) -> bool:
        """
        Hibernate a project (create snapshot and delete K8s resources).

        Called when user leaves project or project is idle too long.

        Args:
            project_id: Project UUID
            user_id: User UUID
            db: Database session (required for snapshot creation)

        Returns:
            True if hibernation successful
        """
        logger.info(f"[K8S] Hibernating project {project_id}")

        await self.delete_project_environment(
            project_id=project_id, user_id=user_id, save_snapshot=True, db=db
        )

        return True

    async def restore_project(
        self, project_id: UUID, user_id: UUID, db: AsyncSession | None = None
    ) -> str:
        """
        Restore a hibernated project (create K8s resources from snapshot).

        Called when user returns to a hibernated project.
        Creates PVC from VolumeSnapshot (lazy loading - near instant).

        Args:
            project_id: Project UUID
            user_id: User UUID
            db: Database session (required for snapshot restore)

        Returns:
            Namespace name
        """
        logger.info(f"[K8S] Restoring project {project_id}")

        namespace = await self.ensure_project_environment(
            project_id=project_id, user_id=user_id, is_hibernated=True, db=db
        )

        return namespace

    # =========================================================================
    # FILE OPERATIONS (via file-manager pod)
    # =========================================================================

    async def read_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        project_slug: str = None,
        subdir: str = None,
    ) -> str | None:
        """Read a file from project storage."""
        namespace = self._get_namespace(str(project_id))

        # Build full path including subdir for multi-container projects
        full_path = f"/app/{subdir}/{file_path}" if subdir else f"/app/{file_path}"

        try:
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            if not pod_name:
                # Fall back to dev container if no file-manager
                return await self.k8s_client.read_file_from_pod(
                    user_id=user_id,
                    project_id=str(project_id),
                    file_path=file_path,
                    container_name=container_name,
                    subdir=subdir,
                )

            result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["cat", full_path],
                timeout=30,
            )
            return result

        except Exception as e:
            logger.error(f"[K8S] Error reading file: {e}")
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
    ) -> bool:
        """Write a file to project storage."""
        namespace = self._get_namespace(str(project_id))

        # Build full path including subdir for multi-container projects
        full_path = f"/app/{subdir}/{file_path}" if subdir else f"/app/{file_path}"

        try:
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            if not pod_name:
                return await self.k8s_client.write_file_to_pod(
                    user_id=user_id,
                    project_id=str(project_id),
                    file_path=file_path,
                    content=content,
                    container_name=container_name,
                    subdir=subdir,
                )

            # Use base64 to handle special characters
            import base64

            encoded = base64.b64encode(content.encode()).decode()

            # Ensure directory exists
            dir_path = "/".join(full_path.split("/")[:-1])
            await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["mkdir", "-p", dir_path],
                timeout=10,
            )

            # Write file
            await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["sh", "-c", f"echo '{encoded}' | base64 -d > {full_path}"],
                timeout=30,
            )

            return True

        except Exception as e:
            logger.error(f"[K8S] Error writing file: {e}")
            return False

    async def delete_file(
        self, user_id: UUID, project_id: UUID, container_name: str, file_path: str
    ) -> bool:
        """Delete a file from project storage."""
        namespace = self._get_namespace(str(project_id))

        try:
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            if not pod_name:
                return await self.k8s_client.delete_file_from_pod(
                    user_id=user_id,
                    project_id=str(project_id),
                    file_path=file_path,
                    container_name=container_name,
                )

            await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["rm", "-f", f"/app/{file_path}"],
                timeout=10,
            )

            return True

        except Exception as e:
            logger.error(f"[K8S] Error deleting file: {e}")
            return False

    async def list_files(
        self, user_id: UUID, project_id: UUID, container_name: str, directory: str = "."
    ) -> list[dict[str, Any]]:
        """List files in project storage."""
        namespace = self._get_namespace(str(project_id))

        try:
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            if not pod_name:
                return await self.k8s_client.list_files_in_pod(
                    user_id=user_id,
                    project_id=str(project_id),
                    directory=directory,
                    container_name=container_name,
                )

            # Use ls with JSON-friendly output
            full_path = f"/app/{directory}" if directory != "." else "/app"
            result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["sh", "-c", f"ls -la {full_path} 2>/dev/null || echo 'EMPTY'"],
                timeout=30,
            )

            # Parse ls output into file list
            files = []
            for line in result.strip().split("\n"):
                if line.startswith("total") or line == "EMPTY" or not line:
                    continue
                parts = line.split()
                if len(parts) >= 9:
                    name = " ".join(parts[8:])
                    if name in [".", ".."]:
                        continue
                    files.append(
                        {
                            "name": name,
                            "type": "directory" if parts[0].startswith("d") else "file",
                            "size": int(parts[4]) if parts[4].isdigit() else 0,
                            "permissions": parts[0],
                        }
                    )

            return files

        except Exception as e:
            logger.error(f"[K8S] Error listing files: {e}")
            return []

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
            full_command = ["sh", "-c", f"cd /app/{working_dir} && {' '.join(command)}"]
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
        # Log warning on first call to help identify callers that need updating
        logger.debug(
            "[K8S] track_activity() called but is a no-op. "
            "Use activity_tracker.track_project_activity() instead."
        )

    async def cleanup_idle_environments(self, idle_timeout_minutes: int = None) -> list[str]:
        """
        Cleanup idle environments by querying database for inactive projects.

        Called periodically by cleanup cronjob.
        Projects are considered idle if last_activity is older than threshold.
        """
        from datetime import datetime, timedelta

        from sqlalchemy import or_, select

        from ...database import AsyncSessionLocal
        from ...models import Project

        if idle_timeout_minutes is None:
            idle_timeout_minutes = self.settings.k8s_hibernation_idle_minutes

        logger.info(
            f"[K8S:CLEANUP] Checking for idle environments (timeout: {idle_timeout_minutes} min)"
        )

        hibernated = []
        cutoff_time = datetime.now(UTC) - timedelta(minutes=idle_timeout_minutes)

        try:
            async with AsyncSessionLocal() as db:
                # Find projects with running K8s environments that are idle
                # environment_status='active' means K8s resources exist
                # Include projects where last_activity is NULL (never tracked) or older than cutoff
                result = await db.execute(
                    select(Project).where(
                        Project.environment_status == "active",
                        or_(Project.last_activity < cutoff_time, Project.last_activity.is_(None)),
                    )
                )
                idle_projects = result.scalars().all()

                logger.info(f"[K8S:CLEANUP] Found {len(idle_projects)} idle projects")

                # Import WebSocket manager for status updates
                from ...routers.chat import get_chat_connection_manager

                ws_manager = get_chat_connection_manager()

                for project in idle_projects:
                    if project.last_activity:
                        idle_minutes = (
                            datetime.now(UTC) - project.last_activity
                        ).total_seconds() / 60
                        logger.info(
                            f"[K8S:CLEANUP] Hibernating project {project.slug} (idle {idle_minutes:.1f} min)"
                        )
                    else:
                        logger.info(
                            f"[K8S:CLEANUP] Hibernating project {project.slug} (no activity tracked)"
                        )

                    try:
                        # Mark as hibernating and notify user
                        project.environment_status = "hibernating"
                        await db.commit()

                        # Send WebSocket notification to redirect user
                        try:
                            await ws_manager.send_status_update(
                                user_id=project.owner_id,
                                project_id=project.id,
                                status={
                                    "environment_status": "hibernating",
                                    "message": "Saving project files...",
                                    "action": "redirect_to_projects",
                                },
                            )
                        except Exception as ws_err:
                            logger.debug(
                                f"[K8S:CLEANUP] Could not send WebSocket notification: {ws_err}"
                            )

                        # Hibernate project (create snapshot + delete namespace)
                        await self.hibernate_project(project.id, project.owner_id, db=db)

                        # Update database status
                        project.environment_status = "hibernated"
                        project.hibernated_at = datetime.now(UTC)
                        await db.commit()

                        # Send completion notification
                        try:
                            await ws_manager.send_status_update(
                                user_id=project.owner_id,
                                project_id=project.id,
                                status={
                                    "environment_status": "hibernated",
                                    "message": "Project saved successfully",
                                },
                            )
                        except Exception as ws_err:
                            logger.debug(
                                f"[K8S:CLEANUP] Could not send completion notification: {ws_err}"
                            )

                        hibernated.append(str(project.id))
                        logger.info(f"[K8S:CLEANUP] ✅ Hibernated {project.slug}")

                    except Exception as e:
                        logger.error(f"[K8S:CLEANUP] ❌ Error hibernating {project.slug}: {e}")
                        await db.rollback()
                        # CRITICAL: Reset status to 'active' so project isn't stuck in 'hibernating'
                        # The earlier commit set it to 'hibernating', so we need a new commit to fix it
                        try:
                            project.environment_status = "active"
                            await db.commit()
                            logger.info(
                                f"[K8S:CLEANUP] Reset {project.slug} status to 'active' after hibernation failure"
                            )
                        except Exception as reset_err:
                            logger.error(
                                f"[K8S:CLEANUP] Failed to reset status for {project.slug}: {reset_err}"
                            )

        except Exception as e:
            logger.error(f"[K8S:CLEANUP] ❌ Database error: {e}")

        logger.info(f"[K8S:CLEANUP] ✅ Cleanup complete: Hibernated {len(hibernated)} environments")
        return hibernated

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
    ) -> list[dict[str, Any]]:
        """Find files matching a glob pattern."""
        return await self.k8s_client.glob_files_in_pod(
            user_id=user_id,
            project_id=str(project_id),
            pattern=pattern,
            directory=directory,
            container_name=container_name,
        )

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
    ) -> list[dict[str, Any]]:
        """Search file contents for a pattern."""
        return await self.k8s_client.grep_in_pod(
            user_id=user_id,
            project_id=str(project_id),
            pattern=pattern,
            directory=directory,
            file_pattern=file_pattern,
            case_sensitive=case_sensitive,
            max_results=max_results,
            container_name=container_name,
        )


# Singleton instance
_kubernetes_orchestrator: KubernetesOrchestrator | None = None


def get_kubernetes_orchestrator() -> KubernetesOrchestrator:
    """Get the singleton Kubernetes orchestrator instance."""
    global _kubernetes_orchestrator

    if _kubernetes_orchestrator is None:
        _kubernetes_orchestrator = KubernetesOrchestrator()

    return _kubernetes_orchestrator
