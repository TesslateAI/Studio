"""
Kubernetes Orchestrator for Multi-Container Projects

This service manages multi-container monorepo projects using Kubernetes.
It creates multiple Deployments/Services within a project namespace,
similar to how DockerComposeOrchestrator works with Docker Compose.

Architecture:
- Each project gets its own namespace: proj-{project_uuid}
- Containers become separate Deployments + Services within the namespace
- Shared source code via ReadWriteMany PVC mounted to all containers
- NetworkPolicy for inter-container communication and external isolation
- Ingress rules for each container with exposed ports
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)


class KubernetesOrchestrator:
    """
    Orchestrates multi-container projects using Kubernetes.

    Creates multiple Deployments/Services from Container database models and manages
    the lifecycle of all containers in a project as a cohesive unit within a dedicated namespace.
    """

    def __init__(self):
        # Import here to avoid circular dependencies
        from ..k8s_client import get_k8s_manager
        from ..config import get_settings

        self.k8s_manager = get_k8s_manager()
        self.settings = get_settings()
        logger.info(f"[K8S-ORCH] Kubernetes Orchestrator initialized")

    async def start_project(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Start all containers for a project in Kubernetes.

        Args:
            project: Project model
            containers: List of Container models
            connections: List of ContainerConnection models
            user_id: User ID
            db: Database session

        Returns:
            Dictionary with status and container URLs
        """
        from kubernetes import client
        from ..k8s_client_helpers import create_dynamic_pvc_manifest

        project_id = str(project.id)
        namespace = self.k8s_manager._get_project_namespace(project_id)

        logger.info(f"[K8S-ORCH] Starting project {project.slug} in namespace {namespace}")
        logger.info(f"[K8S-ORCH] Containers: {len(containers)}, Connections: {len(connections)}")

        try:
            # Phase 1: Create namespace and NetworkPolicy
            await self.k8s_manager._create_namespace_if_not_exists(namespace, project_id, user_id)
            await self.k8s_manager._create_network_policy(namespace, project_id)

            # Phase 2: Create shared PVC for source code
            # Note: DO block storage only supports ReadWriteOnce, so multi-container
            # projects require S3 storage mode for proper file sharing
            pvc_name = f"project-source-{project_id}"

            # Use ReadWriteOnce since DO block storage doesn't support ReadWriteMany
            access_mode = "ReadWriteOnce"
            storage_class = self.settings.k8s_pvc_storage_class
            logger.info(f"[K8S-ORCH] Creating PVC: {pvc_name} ({access_mode})")

            # Check if PVC already exists
            try:
                await asyncio.to_thread(
                    self.k8s_manager.core_v1.read_namespaced_persistent_volume_claim,
                    name=pvc_name,
                    namespace=namespace
                )
                logger.info(f"[K8S-ORCH] PVC {pvc_name} already exists, skipping creation")
            except client.ApiException as e:
                if e.status == 404:
                    # PVC doesn't exist, create it
                    pvc_manifest = create_dynamic_pvc_manifest(
                        pvc_name=pvc_name,
                        namespace=namespace,
                        storage_class=storage_class,
                        size=self.settings.k8s_pvc_size,
                        user_id=user_id,
                        project_id=UUID(project_id),
                        access_mode=access_mode
                    )
                    await asyncio.to_thread(
                        self.k8s_manager.core_v1.create_namespaced_persistent_volume_claim,
                        namespace=namespace,
                        body=pvc_manifest
                    )
                    logger.info(f"[K8S-ORCH] ✅ Created PVC: {pvc_name}")
                else:
                    raise

            # Phase 3: Build dependency map from connections
            dependencies_map = {}  # container_id -> [dependent_container_ids]
            for connection in connections:
                if connection.connection_type == "depends_on":
                    source_id = str(connection.source_container_id)
                    target_id = str(connection.target_container_id)

                    if source_id not in dependencies_map:
                        dependencies_map[source_id] = []
                    dependencies_map[source_id].append(target_id)

            # Phase 4: Create Deployment + Service for each container
            container_urls = {}

            for container in containers:
                container_id = str(container.id)
                container_name = container.name

                logger.info(f"[K8S-ORCH] Creating resources for container: {container_name}")

                # Generate resource names for this container
                names = self.k8s_manager._generate_resource_names(
                    user_id=user_id,
                    project_id=project_id,
                    project_slug=project.slug,
                    container_name=container_name
                )

                # Determine container type and create appropriate deployment
                if container.container_type == "service":
                    # Service container (Postgres, Redis, etc.)
                    await self._create_service_container(
                        container=container,
                        names=names,
                        namespace=namespace,
                        project=project,
                        user_id=user_id
                    )
                else:
                    # Base container (user application)
                    await self._create_base_container(
                        container=container,
                        names=names,
                        namespace=namespace,
                        pvc_name=pvc_name,
                        project=project,
                        user_id=user_id
                    )

                # Track URL for this container
                container_urls[container_name] = f"https://{names['hostname']}"

            logger.info(f"[K8S-ORCH] ✅ Project {project.slug} started successfully in namespace {namespace}")

            return {
                "status": "running",
                "project_slug": project.slug,
                "namespace": namespace,
                "containers": container_urls,
                "pvc_name": pvc_name
            }

        except Exception as e:
            logger.error(f"[K8S-ORCH] Error starting project: {e}", exc_info=True)
            raise

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
        Start a single container for a project in Kubernetes.

        Args:
            project: Project model
            container: Container model to start
            all_containers: List of all Container models in project
            connections: List of ContainerConnection models
            user_id: User ID
            db: Database session

        Returns:
            Dictionary with status and container URL
        """
        from kubernetes import client
        from ..k8s_client_helpers import create_dynamic_pvc_manifest

        project_id = str(project.id)
        namespace = self.k8s_manager._get_project_namespace(project_id)
        container_name = container.name

        logger.info(f"[K8S-ORCH] Starting container '{container_name}' in namespace {namespace}")

        try:
            # Phase 1: Create namespace and NetworkPolicy if needed
            await self.k8s_manager._create_namespace_if_not_exists(namespace, project_id, user_id)
            await self.k8s_manager._create_network_policy(namespace, project_id)

            # Phase 2: Create shared PVC for source code
            pvc_name = f"project-source-{project_id}"
            logger.info(f"[K8S-ORCH] Ensuring PVC exists: {pvc_name}")

            try:
                await asyncio.to_thread(
                    self.k8s_manager.core_v1.read_namespaced_persistent_volume_claim,
                    name=pvc_name,
                    namespace=namespace
                )
                logger.info(f"[K8S-ORCH] PVC {pvc_name} already exists")
            except client.ApiException as e:
                if e.status == 404:
                    pvc_manifest = create_dynamic_pvc_manifest(
                        pvc_name=pvc_name,
                        namespace=namespace,
                        storage_class=self.settings.k8s_rwx_storage_class,
                        size=self.settings.k8s_pvc_size,
                        user_id=user_id,
                        project_id=UUID(project_id),
                        access_mode="ReadWriteOnce"  # DO block storage only supports RWO
                    )
                    await asyncio.to_thread(
                        self.k8s_manager.core_v1.create_namespaced_persistent_volume_claim,
                        namespace=namespace,
                        body=pvc_manifest
                    )
                    logger.info(f"[K8S-ORCH] Created PVC: {pvc_name}")
                else:
                    raise

            # Phase 3: Generate resource names for this container
            names = self.k8s_manager._generate_resource_names(
                user_id=user_id,
                project_id=project_id,
                project_slug=project.slug,
                container_name=container_name
            )

            # Phase 4: Create deployment based on container type
            if container.container_type == "service":
                await self._create_service_container(
                    container=container,
                    names=names,
                    namespace=namespace,
                    project=project,
                    user_id=user_id
                )
            else:
                await self._create_base_container(
                    container=container,
                    names=names,
                    namespace=namespace,
                    pvc_name=pvc_name,
                    project=project,
                    user_id=user_id
                )

            container_url = f"https://{names['hostname']}"

            # Phase 5: Sync files from database to PVC (for base containers only)
            if container.container_type != "service":
                logger.info(f"[K8S-ORCH] Syncing files from database to PVC...")
                try:
                    files_synced = await self._sync_files_to_pvc(
                        project_id=str(project.id),
                        namespace=namespace,
                        deployment_name=names["deployment"],
                        db=db
                    )
                    logger.info(f"[K8S-ORCH] ✅ Synced {files_synced} files to PVC")
                except Exception as sync_error:
                    logger.warning(f"[K8S-ORCH] File sync failed (container may still work): {sync_error}")

            logger.info(f"[K8S-ORCH] Container '{container_name}' started at {container_url}")

            return {
                "status": "running",
                "container_name": container_name,
                "url": container_url,
                "namespace": namespace
            }

        except Exception as e:
            logger.error(f"[K8S-ORCH] Error starting container '{container_name}': {e}", exc_info=True)
            raise


    async def _sync_files_to_pvc(
        self,
        project_id: str,
        namespace: str,
        deployment_name: str,
        db: AsyncSession
    ) -> int:
        """
        Sync project files to PVC via the running pod.

        Supports two modes:
        - S3 mode (k8s_use_s3_storage=True): Sync from S3 bucket
        - Database mode (default): Sync from PostgreSQL ProjectFile table

        Args:
            project_id: Project ID
            namespace: Kubernetes namespace
            deployment_name: Name of the deployment
            db: Database session

        Returns:
            Number of files synced
        """
        from sqlalchemy import select
        from ..models import ProjectFile

        # Check if S3 mode is enabled
        if self.settings.k8s_use_s3_storage:
            logger.info(f"[K8S-ORCH] S3 storage mode enabled, syncing from S3...")
            return await self._sync_files_from_s3(project_id, namespace, deployment_name)

        # Database mode: Get files from database
        result = await db.execute(
            select(ProjectFile).where(ProjectFile.project_id == project_id)
        )
        files = result.scalars().all()

        if not files:
            logger.info(f"[K8S-ORCH] No files in database for project {project_id}")
            return 0

        logger.info(f"[K8S-ORCH] Found {len(files)} files to sync")

        # Step 2: Wait for pod to be ready
        max_wait = 60  # seconds
        wait_interval = 2
        waited = 0
        pod_name = None

        while waited < max_wait:
            try:
                pods = await asyncio.to_thread(
                    self.k8s_manager.core_v1.list_namespaced_pod,
                    namespace=namespace,
                    label_selector=f"app={deployment_name}"
                )

                for pod in pods.items:
                    if pod.status.phase == "Running":
                        # Check if container is ready
                        if pod.status.container_statuses:
                            for cs in pod.status.container_statuses:
                                if cs.ready:
                                    pod_name = pod.metadata.name
                                    break
                    if pod_name:
                        break

                if pod_name:
                    break

            except Exception as e:
                logger.debug(f"[K8S-ORCH] Waiting for pod: {e}")

            await asyncio.sleep(wait_interval)
            waited += wait_interval

        if not pod_name:
            logger.warning(f"[K8S-ORCH] No ready pod found after {max_wait}s, skipping file sync")
            return 0

        logger.info(f"[K8S-ORCH] Pod ready: {pod_name}, syncing files...")

        # Step 3: Sync files to pod using kubectl exec
        files_synced = 0
        for file in files:
            try:
                # Create directory and write file
                file_path = file.file_path
                content = file.content

                # Escape content for shell
                # Use base64 encoding to safely transfer file content
                import base64
                encoded_content = base64.b64encode(content.encode('utf-8')).decode('ascii')

                # Create parent directory and decode content to file
                command = [
                    "/bin/sh", "-c",
                    f"mkdir -p \"$(dirname '/app/{file_path}')\" && echo '{encoded_content}' | base64 -d > '/app/{file_path}'"
                ]

                # Execute in pod
                from kubernetes.stream import stream
                await asyncio.to_thread(
                    stream,
                    self.k8s_manager.core_v1.connect_get_namespaced_pod_exec,
                    pod_name,
                    namespace,
                    command=command,
                    stderr=True,
                    stdin=False,
                    stdout=True,
                    tty=False
                )

                files_synced += 1
                if files_synced % 10 == 0:
                    logger.debug(f"[K8S-ORCH] Synced {files_synced}/{len(files)} files...")

            except Exception as e:
                logger.warning(f"[K8S-ORCH] Failed to sync file {file.file_path}: {e}")

        return files_synced

    async def _sync_files_from_s3(
        self,
        project_id: str,
        namespace: str,
        deployment_name: str
    ) -> int:
        """
        Sync project files from S3 to PVC via the running pod.

        Uses AWS CLI in the pod to sync files from S3 bucket.

        Args:
            project_id: Project ID
            namespace: Kubernetes namespace
            deployment_name: Name of the deployment

        Returns:
            Number of files synced (estimated)
        """
        # Wait for pod to be ready
        max_wait = 60
        wait_interval = 2
        waited = 0
        pod_name = None

        while waited < max_wait:
            try:
                pods = await asyncio.to_thread(
                    self.k8s_manager.core_v1.list_namespaced_pod,
                    namespace=namespace,
                    label_selector=f"app={deployment_name}"
                )

                for pod in pods.items:
                    if pod.status.phase == "Running":
                        if pod.status.container_statuses:
                            for cs in pod.status.container_statuses:
                                if cs.ready:
                                    pod_name = pod.metadata.name
                                    break
                    if pod_name:
                        break

                if pod_name:
                    break

            except Exception as e:
                logger.debug(f"[K8S-ORCH] Waiting for pod: {e}")

            await asyncio.sleep(wait_interval)
            waited += wait_interval

        if not pod_name:
            logger.warning(f"[K8S-ORCH] No ready pod found after {max_wait}s, skipping S3 sync")
            return 0

        logger.info(f"[K8S-ORCH] Pod ready: {pod_name}, syncing from S3...")

        # Build S3 path
        s3_prefix = self.settings.s3_projects_prefix
        s3_bucket = self.settings.s3_bucket_name
        s3_path = f"s3://{s3_bucket}/{s3_prefix}/{project_id}/"

        # Sync using AWS CLI (assumes pod has AWS CLI and credentials configured)
        command = [
            "/bin/sh", "-c",
            f"aws s3 sync {s3_path} /app/ --quiet && echo 'S3 sync complete'"
        ]

        try:
            from kubernetes.stream import stream
            resp = await asyncio.to_thread(
                stream,
                self.k8s_manager.core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                command=command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False
            )
            logger.info(f"[K8S-ORCH] S3 sync response: {resp}")
            return 1  # S3 sync doesn't give us file count easily

        except Exception as e:
            logger.error(f"[K8S-ORCH] S3 sync failed: {e}")
            return 0

    async def _create_base_container(
        self,
        container,
        names: Dict[str, str],
        namespace: str,
        pvc_name: str,
        project,
        user_id: UUID
    ) -> None:
        """
        Create Deployment + Service + Ingress for a base container (user application).

        Args:
            container: Container model
            names: Generated resource names (deployment, service, ingress, hostname)
            namespace: Project namespace
            pvc_name: Shared PVC name for source code
            project: Project model
            user_id: User ID
        """
        from kubernetes import client
        from ..services.base_config_parser import (
            get_base_config_from_cache,
            generate_startup_command
        )

        # Read base configuration for port and startup command
        base_config = None
        if container.base:
            try:
                base_slug = container.base.slug
                base_config = await asyncio.to_thread(get_base_config_from_cache, base_slug)
            except Exception as e:
                logger.debug(f"[K8S-ORCH] Could not read config from cache: {e}")

        # Determine port
        container_port = container.internal_port or (base_config.port if base_config else 3000)

        # Determine working directory
        working_dir = '/app'
        if base_config and base_config.structure_type == "multi":
            container_name_lower = container.name.lower()
            if 'frontend' in container_name_lower or 'client' in container_name_lower:
                working_dir = '/app/frontend'
            elif 'backend' in container_name_lower or 'server' in container_name_lower or 'api' in container_name_lower:
                working_dir = '/app/backend'

        # Generate startup command
        startup_command = generate_startup_command(base_config) if base_config else "npm run dev"

        # Generate init script based on whether we have a base with git_repo_url
        init_script = self._generate_init_script(container)

        # Create Deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=names["deployment"],
                namespace=namespace,
                labels={
                    "app": "dev-environment",
                    "project-id": str(project.id),
                    "container-id": str(container.id),
                    "container-name": names.get("safe_container_name", names["deployment"]),  # Use sanitized name
                    "managed-by": "tesslate-backend"
                }
            ),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(
                    match_labels={"app": names["deployment"]}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": names["deployment"]}
                    ),
                    spec=client.V1PodSpec(
                        security_context=client.V1PodSecurityContext(
                            run_as_non_root=True,
                            run_as_user=1000,
                            fs_group=1000
                        ),
                        init_containers=[
                            # Init container to set up project files (clone from git or copy template)
                            client.V1Container(
                                name="init-template",
                                image=self.settings.k8s_devserver_image,
                                command=["/bin/sh", "-c"],
                                args=[init_script],
                                volume_mounts=[
                                    client.V1VolumeMount(
                                        name="project-source",
                                        mount_path="/app"
                                    )
                                ],
                                resources=client.V1ResourceRequirements(
                                    requests={"memory": "256Mi", "cpu": "100m"},
                                    limits={"memory": "512Mi", "cpu": "500m"}
                                )
                            )
                        ],
                        containers=[
                            client.V1Container(
                                name="dev-server",
                                image=self.settings.k8s_devserver_image,  # Full registry path
                                working_dir=working_dir,
                                command=["/bin/sh", "-c"],
                                args=[startup_command],
                                ports=[client.V1ContainerPort(container_port=container_port)],
                                volume_mounts=[
                                    client.V1VolumeMount(
                                        name="project-source",
                                        mount_path="/app"
                                    )
                                ],
                                env=[
                                    client.V1EnvVar(name="PROJECT_ID", value=str(project.id)),
                                    client.V1EnvVar(name="CONTAINER_ID", value=str(container.id)),
                                    client.V1EnvVar(name="CONTAINER_NAME", value=container.name),
                                    *[client.V1EnvVar(name=k, value=v) for k, v in (container.environment_vars or {}).items()]
                                ],
                                resources=client.V1ResourceRequirements(
                                    requests={"memory": "256Mi", "cpu": "100m"},
                                    limits={"memory": "512Mi", "cpu": "500m"}
                                )
                            )
                        ],
                        volumes=[
                            client.V1Volume(
                                name="project-source",
                                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                    claim_name=pvc_name
                                )
                            )
                        ],
                        image_pull_secrets=[
                            client.V1LocalObjectReference(name=self.settings.k8s_image_pull_secret)
                        ]
                    )
                )
            )
        )

        await self._create_or_update_deployment(namespace, deployment)

        # Create Service
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=names["service"],
                namespace=namespace
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"app": names["deployment"]},
                ports=[
                    client.V1ServicePort(
                        port=container_port,
                        target_port=container_port,
                        protocol="TCP",
                        name="http"
                    )
                ]
            )
        )

        await self._create_or_update_service(namespace, service)

        # Create Ingress (if container has a port)
        if container_port:
            await self._create_ingress(names, namespace, container_port, user_id)

    async def _create_service_container(
        self,
        container,
        names: Dict[str, str],
        namespace: str,
        project,
        user_id: UUID
    ) -> None:
        """
        Create Deployment + Service for a service container (Postgres, Redis, etc.).

        Args:
            container: Container model
            names: Generated resource names
            namespace: Project namespace
            project: Project model
            user_id: User ID
        """
        from kubernetes import client
        from ..services.service_definitions import get_service

        service_def = get_service(container.service_slug)
        if not service_def:
            logger.error(f"[K8S-ORCH] Service '{container.service_slug}' not found, skipping")
            return

        # Create volume for service data persistence
        service_pvc_name = f"service-{container.service_slug}-{project.id}"

        # Create PVC for service data
        pvc = client.V1PersistentVolumeClaim(
            metadata=client.V1ObjectMeta(
                name=service_pvc_name,
                namespace=namespace
            ),
            spec=client.V1PersistentVolumeClaimSpec(
                storage_class_name=self.settings.k8s_pvc_storage_class,
                access_modes=["ReadWriteOnce"],
                resources=client.V1ResourceRequirements(
                    requests={"storage": "5Gi"}
                )
            )
        )

        await self._create_or_update_pvc(namespace, pvc)

        # Build volume mounts
        volume_mounts = [
            client.V1VolumeMount(
                name="service-data",
                mount_path=volume_path
            )
            for volume_path in service_def.volumes
        ]

        # Create Deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=names["deployment"],
                namespace=namespace
            ),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(
                    match_labels={"app": names["deployment"]}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": names["deployment"]}
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name=container.service_slug,
                                image=service_def.docker_image,
                                ports=[client.V1ContainerPort(container_port=service_def.internal_port)],
                                volume_mounts=volume_mounts,
                                env=[
                                    client.V1EnvVar(name=k, value=v)
                                    for k, v in service_def.environment_vars.items()
                                ]
                            )
                        ],
                        volumes=[
                            client.V1Volume(
                                name="service-data",
                                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                    claim_name=service_pvc_name
                                )
                            )
                        ]
                    )
                )
            )
        )

        await self._create_or_update_deployment(namespace, deployment)

        # Create Service
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=names["service"],
                namespace=namespace
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"app": names["deployment"]},
                ports=[
                    client.V1ServicePort(
                        port=service_def.internal_port,
                        target_port=service_def.internal_port,
                        protocol="TCP",
                        name="service"
                    )
                ]
            )
        )

        await self._create_or_update_service(namespace, service)

    def _generate_init_script(self, container) -> str:
        """
        Generate init script for container setup.

        If container has a base with git_repo_url, clones from git and installs dependencies.
        Otherwise, copies the default template from the devserver image.

        Args:
            container: Container model with optional base relationship

        Returns:
            Shell script string for the init container
        """
        # Check if container has a base with git_repo_url
        if container.base and container.base.git_repo_url:
            git_url = container.base.git_repo_url
            branch = container.base.default_branch or "main"
            base_name = container.base.name

            logger.info(f"[K8S-ORCH] Container '{container.name}' uses base '{base_name}' with git: {git_url}")

            return f"""
set -e
echo "[INIT] ======================================"
echo "[INIT] Tesslate Project Init (Git Clone Mode)"
echo "[INIT] Base: {base_name}"
echo "[INIT] Git URL: {git_url}"
echo "[INIT] Branch: {branch}"
echo "[INIT] ======================================"

# Check if project already has files
if [ -f /app/package.json ] || [ -f /app/go.mod ] || [ -f /app/requirements.txt ]; then
    echo "[INIT] Project files already exist, skipping clone"
    ls -la /app/
    exit 0
fi

# Clone from git repository
echo "[INIT] Cloning from git repository..."
git clone --depth 1 --branch {branch} --single-branch {git_url} /tmp/base

# Copy files to /app (preserving hidden files but not .git)
echo "[INIT] Copying files to /app..."
cd /tmp/base
find . -maxdepth 1 ! -name '.' ! -name '.git' -exec cp -r {{}} /app/ \\;

# Install dependencies based on project type
cd /app

if [ -f "package.json" ]; then
    echo "[INIT] Installing Node.js dependencies..."
    npm install --prefer-offline --no-audit 2>&1 || echo "[INIT] npm install completed with warnings"
fi

if [ -f "requirements.txt" ]; then
    echo "[INIT] Installing Python dependencies..."
    python3 -m venv .venv 2>/dev/null || true
    .venv/bin/pip install --upgrade pip 2>/dev/null || pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt 2>/dev/null || pip install -r requirements.txt
fi

if [ -f "go.mod" ]; then
    echo "[INIT] Downloading Go modules..."
    go mod download 2>&1 || echo "[INIT] go mod download completed with warnings"
fi

# Cleanup
rm -rf /tmp/base

echo "[INIT] ======================================"
echo "[INIT] ✅ Project initialized from git"
echo "[INIT] Files in /app:"
ls -la /app/ | head -20
echo "[INIT] ======================================"
"""
        else:
            # Default template copy (fallback)
            logger.info(f"[K8S-ORCH] Container '{container.name}' using default template (no git_repo_url)")

            return """
set -e
echo "[INIT] ======================================"
echo "[INIT] Tesslate Project Init (Default Template)"
echo "[INIT] ======================================"

# Check if project already has files
if [ -f /app/package.json ]; then
    echo "[INIT] Project files already exist"
    ls -la /app/
    exit 0
fi

# Copy default template from devserver image
echo "[INIT] Copying template files to /app..."
cp -r /template/. /app/ 2>/dev/null || cp -r /home/node/template/. /app/ 2>/dev/null || echo "[INIT] No template found"

echo "[INIT] ======================================"
echo "[INIT] ✅ Template copied"
echo "[INIT] Files in /app:"
ls -la /app/ | head -20
echo "[INIT] ======================================"
"""

    async def _create_or_update_deployment(
        self,
        namespace: str,
        deployment
    ) -> None:
        """Create or update a Deployment (handles 409 AlreadyExists)."""
        from kubernetes import client

        deployment_name = deployment.metadata.name
        try:
            await asyncio.to_thread(
                self.k8s_manager.apps_v1.create_namespaced_deployment,
                namespace=namespace,
                body=deployment
            )
            logger.info(f"[K8S-ORCH] ✅ Created deployment: {deployment_name}")
        except client.ApiException as e:
            if e.status == 409:
                # Deployment already exists, patch it
                logger.info(f"[K8S-ORCH] Deployment {deployment_name} exists, updating...")
                await asyncio.to_thread(
                    self.k8s_manager.apps_v1.patch_namespaced_deployment,
                    name=deployment_name,
                    namespace=namespace,
                    body=deployment
                )
                logger.info(f"[K8S-ORCH] ✅ Updated deployment: {deployment_name}")
            else:
                raise

    async def _create_or_update_service(
        self,
        namespace: str,
        service
    ) -> None:
        """Create or update a Service (handles 409 AlreadyExists)."""
        from kubernetes import client

        service_name = service.metadata.name
        try:
            await asyncio.to_thread(
                self.k8s_manager.core_v1.create_namespaced_service,
                namespace=namespace,
                body=service
            )
            logger.info(f"[K8S-ORCH] ✅ Created service: {service_name}")
        except client.ApiException as e:
            if e.status == 409:
                # Service already exists, patch it
                logger.info(f"[K8S-ORCH] Service {service_name} exists, updating...")
                await asyncio.to_thread(
                    self.k8s_manager.core_v1.patch_namespaced_service,
                    name=service_name,
                    namespace=namespace,
                    body=service
                )
                logger.info(f"[K8S-ORCH] ✅ Updated service: {service_name}")
            else:
                raise

    async def _create_or_update_ingress(
        self,
        namespace: str,
        ingress
    ) -> None:
        """Create or update an Ingress (handles 409 AlreadyExists)."""
        from kubernetes import client

        ingress_name = ingress.metadata.name
        try:
            await asyncio.to_thread(
                self.k8s_manager.networking_v1.create_namespaced_ingress,
                namespace=namespace,
                body=ingress
            )
            logger.info(f"[K8S-ORCH] ✅ Created ingress: {ingress_name}")
        except client.ApiException as e:
            if e.status == 409:
                # Ingress already exists, patch it
                logger.info(f"[K8S-ORCH] Ingress {ingress_name} exists, updating...")
                await asyncio.to_thread(
                    self.k8s_manager.networking_v1.patch_namespaced_ingress,
                    name=ingress_name,
                    namespace=namespace,
                    body=ingress
                )
                logger.info(f"[K8S-ORCH] ✅ Updated ingress: {ingress_name}")
            else:
                raise

    async def _create_or_update_pvc(
        self,
        namespace: str,
        pvc
    ) -> None:
        """Create or skip a PVC if it already exists (PVCs can't be updated)."""
        from kubernetes import client

        pvc_name = pvc.metadata.name
        try:
            await asyncio.to_thread(
                self.k8s_manager.core_v1.create_namespaced_persistent_volume_claim,
                namespace=namespace,
                body=pvc
            )
            logger.info(f"[K8S-ORCH] ✅ Created PVC: {pvc_name}")
        except client.ApiException as e:
            if e.status == 409:
                # PVC already exists, skip (PVCs are immutable)
                logger.info(f"[K8S-ORCH] PVC {pvc_name} already exists, skipping")
            else:
                raise

    async def _create_ingress(
        self,
        names: Dict[str, str],
        namespace: str,
        port: int,
        user_id: UUID
    ) -> None:
        """Create Ingress for external access."""
        from kubernetes import client

        # Get base URL from centralized config
        app_base_url = self.settings.get_app_base_url

        ingress = client.V1Ingress(
            metadata=client.V1ObjectMeta(
                name=names["ingress"],
                namespace=namespace,
                annotations={
                    # SSL configuration (ssl-redirect=false to avoid loops with Cloudflare Flexible SSL)
                    "cert-manager.io/cluster-issuer": "letsencrypt-prod",
                    "nginx.ingress.kubernetes.io/ssl-redirect": "false",
                    # Auth configuration
                    "nginx.ingress.kubernetes.io/auth-url": f"{app_base_url}/api/auth/verify-access",
                    "nginx.ingress.kubernetes.io/auth-method": "GET",
                    "nginx.ingress.kubernetes.io/auth-response-headers": "X-User-ID",
                    "nginx.ingress.kubernetes.io/auth-snippet": f"""
                        proxy_set_header X-Original-URI $request_uri;
                        proxy_set_header X-Expected-User-ID {user_id};
                        proxy_set_header X-Forwarded-Host $host;
                    """,
                    # WebSocket support
                    "nginx.ingress.kubernetes.io/proxy-http-version": "1.1",
                    "nginx.ingress.kubernetes.io/websocket-services": names["service"],
                    # Allow iframe embedding in Tesslate Studio preview
                    # Use server-snippet to ensure headers are properly handled
                    "nginx.ingress.kubernetes.io/server-snippet": """
                        proxy_hide_header X-Frame-Options;
                        proxy_hide_header Content-Security-Policy;
                    """,
                    "nginx.ingress.kubernetes.io/configuration-snippet": """
                        more_clear_headers "X-Frame-Options";
                        add_header X-Frame-Options "ALLOWALL" always;
                        add_header Content-Security-Policy "frame-ancestors *;" always;
                    """
                }
            ),
            spec=client.V1IngressSpec(
                ingress_class_name=self.settings.k8s_ingress_class,
                tls=[
                    client.V1IngressTLS(
                        hosts=[names["hostname"]],
                        secret_name=self.settings.k8s_wildcard_tls_secret
                    )
                ],
                rules=[
                    client.V1IngressRule(
                        host=names["hostname"],
                        http=client.V1HTTPIngressRuleValue(
                            paths=[
                                client.V1HTTPIngressPath(
                                    path="/",
                                    path_type="Prefix",
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=names["service"],
                                            port=client.V1ServiceBackendPort(number=port)
                                        )
                                    )
                                )
                            ]
                        )
                    )
                ]
            )
        )

        await self._create_or_update_ingress(namespace, ingress)

    async def stop_project(self, project_slug: str, project_id: UUID, user_id: UUID) -> None:
        """
        Stop all containers for a project by deleting the namespace.

        Args:
            project_slug: Project slug
            project_id: Project ID
            user_id: User ID
        """
        namespace = self.k8s_manager._get_project_namespace(str(project_id))

        logger.info(f"[K8S-ORCH] Stopping project {project_slug} (namespace: {namespace})")

        try:
            # Delete the entire namespace (cascades to all resources)
            await asyncio.to_thread(
                self.k8s_manager.core_v1.delete_namespace,
                name=namespace
            )
            logger.info(f"[K8S-ORCH] ✅ Deleted namespace: {namespace}")

        except Exception as e:
            logger.error(f"[K8S-ORCH] Error stopping project: {e}", exc_info=True)
            raise

    async def get_project_status(self, project_slug: str, project_id: UUID) -> Dict[str, Any]:
        """
        Get status of all containers in a project.

        Args:
            project_slug: Project slug
            project_id: Project ID

        Returns:
            Dictionary with container statuses
        """
        namespace = self.k8s_manager._get_project_namespace(str(project_id))

        try:
            # List all pods in the namespace
            pods = await asyncio.to_thread(
                self.k8s_manager.core_v1.list_namespaced_pod,
                namespace=namespace
            )

            container_statuses = {}
            for pod in pods.items:
                container_name = pod.metadata.labels.get("container-name", "unknown")
                container_statuses[container_name] = {
                    "pod_name": pod.metadata.name,
                    "phase": pod.status.phase,
                    "ready": self.k8s_manager._is_pod_ready(pod)
                }

            all_running = all(
                status["ready"] for status in container_statuses.values()
            ) if container_statuses else False

            return {
                "status": "running" if all_running else "partial",
                "namespace": namespace,
                "containers": container_statuses,
                "project_slug": project_slug
            }

        except Exception as e:
            logger.error(f"[K8S-ORCH] Error getting status: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }


# Singleton instance
_kubernetes_orchestrator: Optional[KubernetesOrchestrator] = None


def get_kubernetes_orchestrator() -> KubernetesOrchestrator:
    """Get the singleton Kubernetes orchestrator instance."""
    global _kubernetes_orchestrator

    if _kubernetes_orchestrator is None:
        _kubernetes_orchestrator = KubernetesOrchestrator()

    return _kubernetes_orchestrator
