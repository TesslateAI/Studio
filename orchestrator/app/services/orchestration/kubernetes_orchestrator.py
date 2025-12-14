"""
Kubernetes Orchestrator - New Architecture

Kubernetes-based container orchestration with correct lifecycle separation:
- File lifecycle is SEPARATE from container lifecycle
- S3 is ONLY for hibernation/restoration, NOT for new project setup

Key Concepts:
1. PROJECT LIFECYCLE (namespace + storage):
   - Open project: Create namespace + PVC + file-manager pod
   - Leave project: S3 dehydration → Delete namespace
   - Return to project: Create namespace + PVC → S3 hydration

2. CONTAINER LIFECYCLE (per container):
   - Add to graph: Clone template files to /<container-dir>/
   - Start container: Create Deployment + Service + Ingress
   - Stop container: Delete Deployment (files persist on PVC)

3. FILE MANAGER POD:
   - Always running while project is open
   - Enables file operations without dev server running
   - Handles git clone when containers added to graph
"""

import asyncio
import logging
import time
import tempfile
import os
from typing import Dict, List, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from kubernetes.client.rest import ApiException

from .base import BaseOrchestrator
from .deployment_mode import DeploymentMode
from .kubernetes.client import get_k8s_client, KubernetesClient
from .kubernetes.helpers import (
    create_pvc_manifest,
    create_file_manager_deployment,
    create_container_deployment,
    create_service_manifest,
    create_ingress_manifest,
    create_network_policy_manifest,
    generate_git_clone_script,
)

logger = logging.getLogger(__name__)


class KubernetesOrchestrator(BaseOrchestrator):
    """
    Kubernetes orchestrator with proper lifecycle separation.

    Architecture:
    - File Manager Pod: Always running for file operations
    - Dev Containers: Only run when explicitly started
    - S3: Only for hibernation/restoration (NOT for template setup)
    - Pod Affinity: Multi-container projects share RWO storage
    """

    def __init__(self):
        from ...config import get_settings

        self.settings = get_settings()
        self._k8s_client: Optional[KubernetesClient] = None

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
        safe_name = name.lower().replace(' ', '-').replace('_', '-').replace('.', '-')
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '-')
        while '--' in safe_name:
            safe_name = safe_name.replace('--', '-')
        safe_name = safe_name.strip('-')
        return safe_name[:63]

    def _get_namespace(self, project_id: str) -> str:
        """Get namespace for a project."""
        return self.k8s_client.get_project_namespace(project_id)

    # =========================================================================
    # PROJECT ENVIRONMENT LIFECYCLE
    # =========================================================================

    async def ensure_project_environment(
        self,
        project_id: UUID,
        user_id: UUID,
        is_hibernated: bool = False
    ) -> str:
        """
        Ensure project environment exists (namespace + PVC + file-manager).

        Called when user opens a project in the builder.
        Creates the infrastructure needed for file operations.

        Args:
            project_id: Project UUID
            user_id: User UUID
            is_hibernated: Whether project was hibernated (needs S3 restoration)

        Returns:
            Namespace name
        """
        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)

        logger.info(f"[K8S] Ensuring environment for project {project_id_str}")
        logger.info(f"[K8S] Namespace: {namespace}, Hibernated: {is_hibernated}")

        try:
            # 1. Create namespace
            await self.k8s_client.create_namespace_if_not_exists(
                namespace, project_id_str, user_id
            )

            # 2. Create NetworkPolicy for isolation
            network_policy = create_network_policy_manifest(namespace, project_id)
            await self.k8s_client.apply_network_policy(network_policy, namespace)

            # 3. Create PVC for project storage
            pvc = create_pvc_manifest(
                namespace=namespace,
                project_id=project_id,
                user_id=user_id,
                storage_class=self.settings.k8s_storage_class,
                size=self.settings.k8s_pvc_size,
                access_mode=self.settings.k8s_pvc_access_mode
            )
            await self.k8s_client.create_pvc(pvc, namespace)

            # 4. S3 credentials NOT copied to project namespace (security)
            # All S3 operations are handled by the backend pod using boto3

            # 5. Copy wildcard TLS secret (needed for HTTPS ingress)
            if self.settings.k8s_wildcard_tls_secret:
                await self.k8s_client.copy_wildcard_tls_secret(namespace)

            # 6. Create file-manager deployment
            file_manager = create_file_manager_deployment(
                namespace=namespace,
                project_id=project_id,
                user_id=user_id,
                image=self.settings.k8s_devserver_image,
                image_pull_policy=self.settings.k8s_image_pull_policy,
                image_pull_secret=self.settings.k8s_image_pull_secret or None
            )
            await self.k8s_client.create_deployment(file_manager, namespace)

            # 7. Wait for file-manager to be ready
            await self.k8s_client.wait_for_deployment_ready(
                deployment_name="file-manager",
                namespace=namespace,
                timeout=60
            )

            # 8. If hibernated, restore from S3
            if is_hibernated:
                await self._restore_from_s3(project_id, user_id, namespace)

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
        save_to_s3: bool = True
    ) -> None:
        """
        Delete project environment (for hibernation or cleanup).

        Called when user leaves project or project is idle too long.

        Args:
            project_id: Project UUID
            user_id: User UUID
            save_to_s3: Whether to save to S3 before deleting (hibernation)
        """
        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)

        logger.info(f"[K8S] Deleting environment for project {project_id_str}")

        try:
            if save_to_s3:
                # Hibernate: Save to S3 first - CRITICAL: Must succeed before deleting
                s3_success = await self._save_to_s3(project_id, user_id, namespace)
                if not s3_success:
                    # S3 save failed - DO NOT delete namespace to preserve data
                    logger.error(f"[K8S] ❌ S3 save failed - NOT deleting namespace to preserve data")
                    raise RuntimeError(f"Cannot hibernate project {project_id_str}: S3 save failed")

            # Delete namespace (cascades all resources)
            await asyncio.to_thread(
                self.k8s_client.core_v1.delete_namespace,
                name=namespace
            )
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
        logger.debug(f"[K8S] ensure_project_directory called for {project_slug} (no-op in K8s mode)")
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
        git_url: Optional[str] = None,
        git_branch: str = "main"
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
                30
            )
            check_result = check_result.strip()
            logger.info(f"[K8S] Directory check result for {target_dir}: '{check_result}'")

            if check_result.startswith("EXISTS:"):
                file_count = int(check_result.split(":")[1]) if ":" in check_result else 0
                if file_count >= 3:  # At least package.json, README.md, and one more file
                    logger.info(f"[K8S] Directory {target_dir} already exists with {file_count} files, skipping git clone")
                    return True
                else:
                    logger.warning(f"[K8S] Directory {target_dir} exists but only has {file_count} files, will re-clone")
                    # Fall through to clone

            # CRITICAL: git_url is REQUIRED - containers must have a marketplace base with git repo
            if not git_url:
                raise RuntimeError(
                    f"Container '{container_directory}' has no git_url. "
                    "All containers must be created from a marketplace base with a git repository."
                )

            # Clone from git repository
            script = generate_git_clone_script(
                git_url=git_url,
                branch=git_branch,
                target_dir=target_dir,
                install_deps=True
            )

            # Execute script in file-manager pod
            result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["/bin/sh", "-c", script],
                timeout=300  # 5 minutes for npm install
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
        all_containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
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
        from ...services.base_config_parser import (
            get_base_config_from_cache,
            generate_startup_command
        )

        project_id = str(project.id)
        namespace = self._get_namespace(project_id)
        container_directory = self._sanitize_name(container.directory or container.name)

        logger.info(f"[K8S] Starting container '{container_directory}' in namespace {namespace}")

        try:
            # Check if project was hibernated (needs S3 restoration)
            is_hibernated = project.environment_status == 'hibernated'

            # Ensure environment exists (check K8s namespace)
            namespace_exists = await self.k8s_client.namespace_exists(namespace)
            if not namespace_exists:
                await self.ensure_project_environment(project.id, user_id, is_hibernated=is_hibernated)

                # Update environment_status to 'active' after restore
                if is_hibernated:
                    project.environment_status = 'active'
                    project.hibernated_at = None
                    await db.commit()
                    logger.info(f"[K8S] Restored hibernated project {project.slug} from S3")

            # CRITICAL: Initialize container files BEFORE starting
            # Skip if project was restored from S3 (files already exist)
            if is_hibernated:
                logger.info(f"[K8S] Skipping git clone - project restored from S3")
            else:
                # This clones from git or sets up the project directory
                git_url = None
                if container.base and hasattr(container.base, 'git_repo_url'):
                    git_url = container.base.git_repo_url

                logger.info(f"[K8S] Initializing files for container {container_directory} (git_url={git_url})")
                await self.initialize_container_files(
                    project_id=project.id,
                    user_id=user_id,
                    container_id=container.id,
                    container_directory=container_directory,
                    git_url=git_url
                )

            # Get base config for port and startup command
            base_config = None
            if container.base:
                try:
                    base_config = await asyncio.to_thread(
                        get_base_config_from_cache,
                        container.base.slug
                    )
                except Exception as e:
                    logger.debug(f"[K8S] Could not read base config: {e}")

            # Determine port and startup command from base config
            port = container.internal_port or (base_config.port if base_config else 3000)
            startup_command = generate_startup_command(base_config) if base_config else "npm run dev"

            logger.info(f"[K8S] Container config: port={port}, cmd={startup_command}")

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
                enable_pod_affinity=self.settings.k8s_enable_pod_affinity and len(all_containers) > 1,
                affinity_topology_key=self.settings.k8s_affinity_topology_key
            )
            await self.k8s_client.create_deployment(deployment, namespace)

            # Create Service
            service = create_service_manifest(
                namespace=namespace,
                project_id=project.id,
                container_id=container.id,
                container_directory=container_directory,
                port=port
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
                tls_secret=self.settings.k8s_wildcard_tls_secret or None
            )
            await self.k8s_client.create_ingress(ingress, namespace)

            # Build preview URL (single subdomain level for wildcard cert compatibility)
            hostname = f"{project.slug}-{container_directory}.{self.settings.app_domain}"
            protocol = "https" if self.settings.k8s_wildcard_tls_secret else "http"
            preview_url = f"{protocol}://{hostname}"

            # Activity tracking is now database-based (via activity_tracker service)

            logger.info(f"[K8S] ✅ Container started: {preview_url}")

            return {
                "status": "running",
                "container_name": container.name,
                "container_directory": container_directory,
                "url": preview_url,
                "namespace": namespace,
                "port": port
            }

        except Exception as e:
            logger.error(f"[K8S] Error starting container: {e}", exc_info=True)
            raise

    async def stop_container(
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str,
        user_id: UUID
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

            logger.info(f"[K8S] ✅ Container stopped (files persist on PVC)")

        except Exception as e:
            if "404" not in str(e):
                logger.error(f"[K8S] Error stopping container: {e}")
                raise

    async def get_container_status(
        self,
        project_slug: str,
        project_id: UUID,
        container_name: Optional[str],
        user_id: UUID
    ) -> Dict[str, Any]:
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
                    namespace=namespace
                )
                ready = (deployment.status.ready_replicas or 0) > 0
                return {
                    "status": "running" if ready else "starting",
                    "deployment_ready": ready,
                    "ready": ready,
                    "replicas": deployment.status.replicas,
                    "ready_replicas": deployment.status.ready_replicas,
                    "url": None  # Project-level doesn't have a single URL
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
                namespace=namespace
            )

            ready = (deployment.status.ready_replicas or 0) > 0

            return {
                "status": "running" if ready else "starting",
                "container_name": container_name,
                "ready": ready,
                "replicas": deployment.status.replicas,
                "ready_replicas": deployment.status.ready_replicas
            }

        except ApiException as e:
            if e.status == 404:
                return {"status": "stopped", "container_name": container_name}
            raise

    # =========================================================================
    # PROJECT LIFECYCLE (START/STOP ALL)
    # =========================================================================

    async def start_project(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Start all containers for a project."""
        project_id = str(project.id)

        logger.info(f"[K8S] Starting project {project.slug} with {len(containers)} containers")

        # Check if project was hibernated (needs S3 restoration)
        is_hibernated = project.environment_status == 'hibernated'

        # Ensure environment exists (with S3 restoration if hibernated)
        namespace = await self.ensure_project_environment(project.id, user_id, is_hibernated=is_hibernated)

        # Update environment_status to 'active' after restore
        if is_hibernated:
            project.environment_status = 'active'
            project.hibernated_at = None
            await db.commit()
            logger.info(f"[K8S] Restored hibernated project {project.slug} from S3")

        # Start each container
        container_urls = {}
        for container in containers:
            result = await self.start_container(
                project=project,
                container=container,
                all_containers=containers,
                connections=connections,
                user_id=user_id,
                db=db
            )
            container_urls[container.name] = result.get("url")

        logger.info(f"[K8S] ✅ Project {project.slug} started")

        return {
            "status": "running",
            "project_slug": project.slug,
            "namespace": namespace,
            "containers": container_urls
        }

    async def stop_project(
        self,
        project_slug: str,
        project_id: UUID,
        user_id: UUID
    ) -> None:
        """Stop all containers for a project (but keep files)."""
        project_id_str = str(project_id)
        namespace = self._get_namespace(project_id_str)

        logger.info(f"[K8S] Stopping project {project_slug}")

        try:
            # Delete all dev container deployments (but keep file-manager)
            deployments = await asyncio.to_thread(
                self.k8s_client.apps_v1.list_namespaced_deployment,
                namespace=namespace,
                label_selector="tesslate.io/component=dev-container"
            )

            for deployment in deployments.items:
                await self.k8s_client.delete_deployment(
                    deployment.metadata.name, namespace
                )

            # Delete all dev container services
            services = await asyncio.to_thread(
                self.k8s_client.core_v1.list_namespaced_service,
                namespace=namespace,
                label_selector="tesslate.io/container-id"
            )

            for service in services.items:
                await self.k8s_client.delete_service(
                    service.metadata.name, namespace
                )

            # Delete all dev container ingresses
            ingresses = await asyncio.to_thread(
                self.k8s_client.networking_v1.list_namespaced_ingress,
                namespace=namespace,
                label_selector="tesslate.io/container-id"
            )

            for ingress in ingresses.items:
                await self.k8s_client.delete_ingress(
                    ingress.metadata.name, namespace
                )

            logger.info(f"[K8S] ✅ Project stopped (file-manager and files persist)")

        except ApiException as e:
            if e.status != 404:
                logger.error(f"[K8S] Error stopping project: {e}")
                raise

    async def delete_project_namespace(
        self,
        project_id: UUID,
        user_id: UUID
    ) -> None:
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
                await asyncio.to_thread(
                    self.k8s_client.core_v1.read_namespace,
                    name=namespace
                )
            except ApiException as e:
                if e.status == 404:
                    logger.info(f"[K8S] Namespace {namespace} does not exist, nothing to delete")
                    return
                raise

            # Delete the namespace (this cascades to all resources in it)
            await asyncio.to_thread(
                self.k8s_client.core_v1.delete_namespace,
                name=namespace
            )

            logger.info(f"[K8S] Namespace {namespace} deleted successfully")

        except ApiException as e:
            if e.status != 404:
                logger.error(f"[K8S] Error deleting namespace {namespace}: {e}")
                raise

    async def restart_project(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Restart all containers for a project."""
        await self.stop_project(project.slug, project.id, user_id)
        return await self.start_project(project, containers, connections, user_id, db)

    async def get_project_status(
        self,
        project_slug: str,
        project_id: UUID
    ) -> Dict[str, Any]:
        """Get status of all containers in a project."""
        namespace = self._get_namespace(str(project_id))

        try:
            # Check if namespace exists
            await asyncio.to_thread(
                self.k8s_client.core_v1.read_namespace,
                name=namespace
            )

            # Get all pods
            pods = await asyncio.to_thread(
                self.k8s_client.core_v1.list_namespaced_pod,
                namespace=namespace
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
                        "running": self.k8s_client.is_pod_ready(pod)
                    }
                elif container_dir:
                    is_ready = self.k8s_client.is_pod_ready(pod)
                    # Generate URL for this container
                    url = f"{protocol}://{project_slug}-{container_dir}.{app_domain}"
                    container_statuses[container_dir] = {
                        "phase": pod.status.phase,
                        "ready": is_ready,
                        "running": is_ready,
                        "url": url
                    }

            return {
                "status": "active",
                "namespace": namespace,
                "containers": container_statuses
            }

        except ApiException as e:
            if e.status == 404:
                return {"status": "not_found", "namespace": namespace}
            return {"status": "error", "error": str(e)}

    # =========================================================================
    # S3 HIBERNATION/RESTORATION (Secure Backend-Side Operations)
    # =========================================================================
    #
    # SECURITY: S3 credentials NEVER leave the backend pod.
    # Flow:
    #   Save:    Pod zip → Backend (via k8s stream) → S3 (via boto3)
    #   Restore: S3 (via boto3) → Backend → Pod (via k8s stream) → unzip
    #
    # This prevents exposing AWS credentials to user-accessible namespaces.
    # =========================================================================

    async def _save_to_s3(
        self,
        project_id: UUID,
        user_id: UUID,
        namespace: str
    ) -> bool:
        """
        Save project files to S3 (for hibernation) - SECURE VERSION.

        Flow:
        1. Execute zip in file-manager pod (creates /tmp/project.zip)
        2. Copy zip from pod to backend temp directory (via k8s stream API)
        3. Upload to S3 using boto3 (credentials stay in backend)
        4. Cleanup temp files
        """
        logger.info(f"[K8S:HIBERNATE] Saving project {project_id} to S3 (secure)")

        temp_zip = None
        try:
            # 1. Get file-manager pod
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            if not pod_name:
                logger.warning("[K8S:HIBERNATE] No file-manager pod, skipping S3 save")
                return False

            # 2. Create zip in pod (excluding node_modules, .git, etc.)
            # Use */pattern/* to match in subdirectories (e.g., next-js-15/node_modules)
            zip_script = '''
cd /app
rm -f /tmp/project.zip
zip -r -q /tmp/project.zip . \
    -x "*/node_modules/*" \
    -x "node_modules/*" \
    -x "*/.git/*" \
    -x ".git/*" \
    -x "*/__pycache__/*" \
    -x "__pycache__/*" \
    -x "*/.next/*" \
    -x ".next/*" \
    -x "*.pyc" \
    -x ".DS_Store" \
    -x "*.log"
echo "ZIP_SIZE=$(stat -f%z /tmp/project.zip 2>/dev/null || stat -c%s /tmp/project.zip)"
'''
            result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["/bin/sh", "-c", zip_script],
                timeout=120
            )
            logger.info(f"[K8S:HIBERNATE] Zip created in pod: {result.strip()}")

            # 3. Copy zip from pod to backend temp directory
            temp_fd, temp_zip = tempfile.mkstemp(suffix='.zip', prefix='tesslate-hibernate-')
            os.close(temp_fd)

            await self.k8s_client.copy_file_from_pod(
                pod_name=pod_name,
                namespace=namespace,
                container_name="file-manager",
                pod_path="/tmp/project.zip",
                local_path=temp_zip,
                timeout=300  # 5 min for large projects
            )

            file_size_mb = os.path.getsize(temp_zip) / (1024 * 1024)
            logger.info(f"[K8S:HIBERNATE] Copied zip to backend: {file_size_mb:.2f} MB")

            # 4. Upload to S3 using s3_manager (boto3 - credentials in backend only)
            from ..s3_manager import get_s3_manager
            s3_manager = get_s3_manager()
            s3_key = s3_manager._get_project_key(user_id, project_id)

            await asyncio.to_thread(
                s3_manager.s3_client.upload_file,
                temp_zip,
                s3_manager.bucket_name,
                s3_key,
                ExtraArgs={
                    'ContentType': 'application/zip',
                    'Metadata': {
                        'user_id': str(user_id),
                        'project_id': str(project_id),
                    }
                }
            )

            logger.info(f"[K8S:HIBERNATE] ✅ Project saved to S3: {s3_key} ({file_size_mb:.2f} MB)")

            # 5. Cleanup zip in pod
            await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["/bin/sh", "-c", "rm -f /tmp/project.zip"],
                timeout=10
            )

            return True

        except Exception as e:
            logger.error(f"[K8S:HIBERNATE] Error saving to S3: {e}", exc_info=True)
            return False

        finally:
            # Cleanup local temp file
            if temp_zip and os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                except Exception:
                    pass

    async def _restore_from_s3(
        self,
        project_id: UUID,
        user_id: UUID,
        namespace: str
    ) -> bool:
        """
        Restore project files from S3 (after hibernation) - SECURE VERSION.

        Flow:
        1. Download from S3 to backend temp directory (via boto3)
        2. Copy zip from backend to pod (via k8s stream API)
        3. Execute unzip in file-manager pod
        4. Cleanup temp files
        """
        logger.info(f"[K8S:RESTORE] Restoring project {project_id} from S3 (secure)")

        temp_zip = None
        try:
            # 1. Check if project exists in S3
            from ..s3_manager import get_s3_manager
            s3_manager = get_s3_manager()

            if not await s3_manager.project_exists(user_id, project_id):
                logger.warning(f"[K8S:RESTORE] No S3 archive found for project {project_id}")
                return False

            # 2. Download from S3 to backend temp directory
            temp_fd, temp_zip = tempfile.mkstemp(suffix='.zip', prefix='tesslate-restore-')
            os.close(temp_fd)

            s3_key = s3_manager._get_project_key(user_id, project_id)
            await asyncio.to_thread(
                s3_manager.s3_client.download_file,
                s3_manager.bucket_name,
                s3_key,
                temp_zip
            )

            file_size_mb = os.path.getsize(temp_zip) / (1024 * 1024)
            logger.info(f"[K8S:RESTORE] Downloaded from S3: {file_size_mb:.2f} MB")

            # 3. Get file-manager pod
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            if not pod_name:
                raise RuntimeError("File manager pod not found")

            # 4. Copy zip from backend to pod
            await self.k8s_client.copy_file_to_pod(
                pod_name=pod_name,
                namespace=namespace,
                container_name="file-manager",
                local_path=temp_zip,
                pod_path="/tmp/project.zip",
                timeout=300  # 5 min for large projects
            )
            logger.info(f"[K8S:RESTORE] Copied zip to pod")

            # 5. Extract zip in pod
            unzip_script = '''
cd /app
unzip -o -q /tmp/project.zip
rm -f /tmp/project.zip
echo "FILES_RESTORED=$(ls -1 /app | wc -l)"
'''
            result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["/bin/sh", "-c", unzip_script],
                timeout=120
            )
            logger.info(f"[K8S:RESTORE] Extracted in pod: {result.strip()}")

            logger.info(f"[K8S:RESTORE] ✅ Project restored from S3")
            return True

        except Exception as e:
            logger.error(f"[K8S:RESTORE] Error restoring from S3: {e}", exc_info=True)
            return False

        finally:
            # Cleanup local temp file
            if temp_zip and os.path.exists(temp_zip):
                try:
                    os.remove(temp_zip)
                except Exception:
                    pass

    async def hibernate_project(
        self,
        project_id: UUID,
        user_id: UUID
    ) -> bool:
        """
        Hibernate a project (save to S3 and delete K8s resources).

        Called when user leaves project or project is idle too long.
        """
        logger.info(f"[K8S] Hibernating project {project_id}")

        await self.delete_project_environment(
            project_id=project_id,
            user_id=user_id,
            save_to_s3=True
        )

        return True

    async def restore_project(
        self,
        project_id: UUID,
        user_id: UUID
    ) -> str:
        """
        Restore a hibernated project (create K8s resources and restore from S3).

        Called when user returns to a hibernated project.
        Returns the namespace name.
        """
        logger.info(f"[K8S] Restoring project {project_id}")

        namespace = await self.ensure_project_environment(
            project_id=project_id,
            user_id=user_id,
            is_hibernated=True
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
        subdir: str = None
    ) -> Optional[str]:
        """Read a file from project storage."""
        namespace = self._get_namespace(str(project_id))

        # Build full path including subdir for multi-container projects
        if subdir:
            full_path = f"/app/{subdir}/{file_path}"
        else:
            full_path = f"/app/{file_path}"

        try:
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            if not pod_name:
                # Fall back to dev container if no file-manager
                return await self.k8s_client.read_file_from_pod(
                    user_id=user_id,
                    project_id=str(project_id),
                    file_path=file_path,
                    container_name=container_name,
                    subdir=subdir
                )

            result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["cat", full_path],
                timeout=30
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
        subdir: str = None
    ) -> bool:
        """Write a file to project storage."""
        namespace = self._get_namespace(str(project_id))

        # Build full path including subdir for multi-container projects
        if subdir:
            full_path = f"/app/{subdir}/{file_path}"
        else:
            full_path = f"/app/{file_path}"

        try:
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            if not pod_name:
                return await self.k8s_client.write_file_to_pod(
                    user_id=user_id,
                    project_id=str(project_id),
                    file_path=file_path,
                    content=content,
                    container_name=container_name,
                    subdir=subdir
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
                timeout=10
            )

            # Write file
            await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["sh", "-c", f"echo '{encoded}' | base64 -d > {full_path}"],
                timeout=30
            )

            return True

        except Exception as e:
            logger.error(f"[K8S] Error writing file: {e}")
            return False

    async def delete_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str
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
                    container_name=container_name
                )

            await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["rm", "-f", f"/app/{file_path}"],
                timeout=10
            )

            return True

        except Exception as e:
            logger.error(f"[K8S] Error deleting file: {e}")
            return False

    async def list_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        directory: str = "."
    ) -> List[Dict[str, Any]]:
        """List files in project storage."""
        namespace = self._get_namespace(str(project_id))

        try:
            pod_name = await self.k8s_client.get_file_manager_pod(namespace)
            if not pod_name:
                return await self.k8s_client.list_files_in_pod(
                    user_id=user_id,
                    project_id=str(project_id),
                    directory=directory,
                    container_name=container_name
                )

            # Use ls with JSON-friendly output
            full_path = f"/app/{directory}" if directory != "." else "/app"
            result = await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                "file-manager",
                ["sh", "-c", f"ls -la {full_path} 2>/dev/null || echo 'EMPTY'"],
                timeout=30
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
                    files.append({
                        "name": name,
                        "type": "directory" if parts[0].startswith("d") else "file",
                        "size": int(parts[4]) if parts[4].isdigit() else 0,
                        "permissions": parts[0]
                    })

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
        command: List[str],
        timeout: int = 120,
        working_dir: Optional[str] = None
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
                    container_name=container_name
                )

            return await asyncio.to_thread(
                self.k8s_client._exec_in_pod,
                pod_name,
                namespace,
                container,
                full_command,
                timeout=timeout
            )

        except Exception as e:
            logger.error(f"[K8S] Error executing command: {e}")
            raise

    async def is_container_ready(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str
    ) -> Dict[str, Any]:
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
            container_name=container_name
        )

    # =========================================================================
    # ACTIVITY TRACKING & CLEANUP (Database-based for horizontal scaling)
    # =========================================================================

    def track_activity(
        self,
        user_id: UUID,
        project_id: str,
        container_name: Optional[str] = None
    ) -> None:
        """
        Track activity for idle cleanup.

        Note: This is a sync no-op. Use track_project_activity() from
        orchestrator/app/services/activity_tracker.py for actual DB updates.
        """
        # No-op: Activity tracking is now database-based
        # Call track_project_activity() directly from routers with db session
        pass

    async def cleanup_idle_environments(
        self,
        idle_timeout_minutes: int = None
    ) -> List[str]:
        """
        Cleanup idle environments by querying database for inactive projects.

        Called periodically by cleanup cronjob.
        Projects are considered idle if last_activity is older than threshold.
        """
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import select, or_
        from ...database import AsyncSessionLocal
        from ...models import Project

        if idle_timeout_minutes is None:
            idle_timeout_minutes = self.settings.k8s_hibernation_idle_minutes

        logger.info(f"[K8S:CLEANUP] Checking for idle environments (timeout: {idle_timeout_minutes} min)")

        hibernated = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=idle_timeout_minutes)

        try:
            async with AsyncSessionLocal() as db:
                # Find projects with running K8s environments that are idle
                # environment_status='active' means K8s resources exist
                # Include projects where last_activity is NULL (never tracked) or older than cutoff
                result = await db.execute(
                    select(Project).where(
                        Project.environment_status == 'active',
                        or_(
                            Project.last_activity < cutoff_time,
                            Project.last_activity.is_(None)
                        )
                    )
                )
                idle_projects = result.scalars().all()

                logger.info(f"[K8S:CLEANUP] Found {len(idle_projects)} idle projects")

                for project in idle_projects:
                    if project.last_activity:
                        idle_minutes = (datetime.now(timezone.utc) - project.last_activity).total_seconds() / 60
                        logger.info(f"[K8S:CLEANUP] Hibernating project {project.slug} (idle {idle_minutes:.1f} min)")
                    else:
                        logger.info(f"[K8S:CLEANUP] Hibernating project {project.slug} (no activity tracked)")

                    try:
                        # Hibernate project (S3 upload + delete namespace)
                        await self.hibernate_project(project.id, project.owner_id)

                        # Update database status
                        project.environment_status = 'hibernated'
                        project.hibernated_at = datetime.now(timezone.utc)
                        await db.commit()

                        hibernated.append(str(project.id))
                        logger.info(f"[K8S:CLEANUP] ✅ Hibernated {project.slug}")

                    except Exception as e:
                        logger.error(f"[K8S:CLEANUP] ❌ Error hibernating {project.slug}: {e}")
                        await db.rollback()

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
        directory: str = "."
    ) -> List[Dict[str, Any]]:
        """Find files matching a glob pattern."""
        return await self.k8s_client.glob_files_in_pod(
            user_id=user_id,
            project_id=str(project_id),
            pattern=pattern,
            directory=directory,
            container_name=container_name
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
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """Search file contents for a pattern."""
        return await self.k8s_client.grep_in_pod(
            user_id=user_id,
            project_id=str(project_id),
            pattern=pattern,
            directory=directory,
            file_pattern=file_pattern,
            case_sensitive=case_sensitive,
            max_results=max_results,
            container_name=container_name
        )


# Singleton instance
_kubernetes_orchestrator: Optional[KubernetesOrchestrator] = None


def get_kubernetes_orchestrator() -> KubernetesOrchestrator:
    """Get the singleton Kubernetes orchestrator instance."""
    global _kubernetes_orchestrator

    if _kubernetes_orchestrator is None:
        _kubernetes_orchestrator = KubernetesOrchestrator()

    return _kubernetes_orchestrator
