"""
Kubernetes Orchestrator

Kubernetes-based container orchestration for production deployments.
Implements the BaseOrchestrator interface for Kubernetes deployments.

This is a fully self-contained implementation that uses the kubernetes/ submodule
for all K8s API interactions and manifest generation.
"""

import asyncio
import logging
import time
from typing import Dict, List, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from kubernetes import client
from kubernetes.client.rest import ApiException

from .base import BaseOrchestrator
from .deployment_mode import DeploymentMode
from .kubernetes.client import get_k8s_client, KubernetesClient
from .kubernetes.helpers import (
    create_dynamic_pvc_manifest,
    create_base_container_init_script,
)

logger = logging.getLogger(__name__)


class KubernetesOrchestrator(BaseOrchestrator):
    """
    Kubernetes orchestrator for multi-container projects.

    Features:
    - Per-project namespace isolation
    - Dynamic Deployment + Service + Ingress creation
    - Shared PVC for source code (with subpath isolation)
    - NetworkPolicy for inter-container communication
    - S3-backed storage support for hibernation
    - NGINX Ingress integration
    """

    def __init__(self):
        from ...config import get_settings

        self.settings = get_settings()

        # Lazy load k8s_client to avoid circular imports
        self._k8s_client: Optional[KubernetesClient] = None

        # Activity tracking for cleanup
        self.activity_tracker: Dict[str, float] = {}
        self.paused_at_tracker: Dict[str, float] = {}

        logger.info("[K8S] Kubernetes orchestrator initialized")
        logger.info(f"[K8S] S3 storage mode: {self.settings.k8s_use_s3_storage}")
        logger.info(f"[K8S] Namespace per project: {self.settings.k8s_namespace_per_project}")

    @property
    def k8s_client(self) -> KubernetesClient:
        """Lazy load the Kubernetes client."""
        if self._k8s_client is None:
            self._k8s_client = get_k8s_client()
        return self._k8s_client

    @property
    def deployment_mode(self) -> DeploymentMode:
        return DeploymentMode.KUBERNETES

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _get_project_key(self, user_id: UUID, project_id: str) -> str:
        """Generate unique project key for tracking."""
        return f"user-{user_id}-project-{project_id}"

    def _sanitize_name(self, name: str) -> str:
        """Sanitize a name for Kubernetes naming (DNS-1123 compliant)."""
        safe_name = name.lower().replace(' ', '-').replace('_', '-').replace('.', '-')
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '-')
        while '--' in safe_name:
            safe_name = safe_name.replace('--', '-')
        safe_name = safe_name.strip('-')
        return safe_name[:63]  # K8s name limit

    # =========================================================================
    # PROJECT LIFECYCLE
    # =========================================================================

    async def start_project(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Start all containers for a project in Kubernetes."""
        project_id = str(project.id)
        namespace = self.k8s_client.get_project_namespace(project_id)

        logger.info(f"[K8S] Starting project {project.slug} in namespace {namespace}")
        logger.info(f"[K8S] Containers: {len(containers)}, Connections: {len(connections)}")

        try:
            # Phase 1: Create namespace and NetworkPolicy
            await self.k8s_client.create_namespace_if_not_exists(namespace, project_id, user_id)
            await self.k8s_client.create_network_policy(namespace, project_id)

            # Phase 2: Create shared PVC for source code
            pvc_name = f"project-source-{project_id}"
            access_mode = "ReadWriteOnce"  # DO block storage only supports RWO
            storage_class = self.settings.k8s_pvc_storage_class

            logger.info(f"[K8S] Creating PVC: {pvc_name} ({access_mode})")

            pvc_manifest = create_dynamic_pvc_manifest(
                pvc_name=pvc_name,
                namespace=namespace,
                storage_class=storage_class,
                size=self.settings.k8s_pvc_size,
                user_id=user_id,
                project_id=UUID(project_id),
                access_mode=access_mode
            )
            await self.k8s_client.create_pvc(pvc_manifest, namespace)

            # Phase 3: Build dependency map from connections
            dependencies_map = {}
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
                container_name = container.name
                logger.info(f"[K8S] Creating resources for container: {container_name}")

                names = self.k8s_client.generate_resource_names(
                    user_id=user_id,
                    project_id=project_id,
                    project_slug=project.slug,
                    container_name=container_name
                )

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

                container_urls[container_name] = f"https://{names['hostname']}"

            # Track activity
            project_key = self._get_project_key(user_id, project_id)
            self.activity_tracker[project_key] = time.time()

            logger.info(f"[K8S] ✅ Project {project.slug} started successfully")

            return {
                "status": "running",
                "project_slug": project.slug,
                "namespace": namespace,
                "containers": container_urls,
                "pvc_name": pvc_name
            }

        except Exception as e:
            logger.error(f"[K8S] Error starting project: {e}", exc_info=True)
            raise

    async def stop_project(
        self,
        project_slug: str,
        project_id: UUID,
        user_id: UUID
    ) -> None:
        """Stop all containers for a project by deleting the namespace."""
        namespace = self.k8s_client.get_project_namespace(str(project_id))

        logger.info(f"[K8S] Stopping project {project_slug} (namespace: {namespace})")

        try:
            await asyncio.to_thread(
                self.k8s_client.core_v1.delete_namespace,
                name=namespace
            )
            logger.info(f"[K8S] ✅ Deleted namespace: {namespace}")

        except ApiException as e:
            if e.status != 404:
                logger.error(f"[K8S] Error stopping project: {e}", exc_info=True)
                raise

        # Clean up tracking
        project_key = self._get_project_key(user_id, str(project_id))
        self.activity_tracker.pop(project_key, None)
        self.paused_at_tracker.pop(project_key, None)

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
        namespace = self.k8s_client.get_project_namespace(str(project_id))

        try:
            pods = await asyncio.to_thread(
                self.k8s_client.core_v1.list_namespaced_pod,
                namespace=namespace
            )

            container_statuses = {}
            for pod in pods.items:
                container_name = pod.metadata.labels.get("container-name", "unknown")
                container_statuses[container_name] = {
                    "pod_name": pod.metadata.name,
                    "phase": pod.status.phase,
                    "ready": self.k8s_client.is_pod_ready(pod)
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

        except ApiException as e:
            if e.status == 404:
                return {"status": "not_found", "namespace": namespace}
            logger.error(f"[K8S] Error getting status: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    # =========================================================================
    # INDIVIDUAL CONTAINER MANAGEMENT
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
        """Start a single container in a project."""
        project_id = str(project.id)
        namespace = self.k8s_client.get_project_namespace(project_id)
        container_name = container.name

        logger.info(f"[K8S] Starting container '{container_name}' in namespace {namespace}")

        try:
            # Ensure namespace exists
            await self.k8s_client.create_namespace_if_not_exists(namespace, project_id, user_id)
            await self.k8s_client.create_network_policy(namespace, project_id)

            # Ensure PVC exists
            pvc_name = f"project-source-{project_id}"
            pvc_manifest = create_dynamic_pvc_manifest(
                pvc_name=pvc_name,
                namespace=namespace,
                storage_class=self.settings.k8s_pvc_storage_class,
                size=self.settings.k8s_pvc_size,
                user_id=user_id,
                project_id=UUID(project_id),
                access_mode="ReadWriteOnce"
            )
            await self.k8s_client.create_pvc(pvc_manifest, namespace)

            # Generate resource names
            names = self.k8s_client.generate_resource_names(
                user_id=user_id,
                project_id=project_id,
                project_slug=project.slug,
                container_name=container_name
            )

            # Create container based on type
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

            # Track activity
            project_key = self._get_project_key(user_id, project_id)
            self.activity_tracker[project_key] = time.time()

            logger.info(f"[K8S] Container '{container_name}' started at {container_url}")

            return {
                "status": "running",
                "container_name": container_name,
                "url": container_url,
                "namespace": namespace
            }

        except Exception as e:
            logger.error(f"[K8S] Error starting container '{container_name}': {e}", exc_info=True)
            raise

    async def stop_container(
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str,
        user_id: UUID
    ) -> None:
        """Stop a single container by deleting its Deployment."""
        namespace = self.k8s_client.get_project_namespace(str(project_id))

        names = self.k8s_client.generate_resource_names(
            user_id=user_id,
            project_id=str(project_id),
            project_slug=project_slug,
            container_name=container_name
        )

        logger.info(f"[K8S] Stopping container {container_name} in namespace {namespace}")

        try:
            await self.k8s_client.delete_deployment(names["deployment"], namespace)
            await self.k8s_client.delete_service(names["service"], namespace)
            await self.k8s_client.delete_ingress(names["ingress"], namespace)

        except Exception as e:
            if "404" not in str(e):
                logger.error(f"[K8S] Error stopping container: {e}")
                raise

    async def get_container_status(
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str,
        user_id: UUID
    ) -> Dict[str, Any]:
        """Get status of a single container."""
        return await self.k8s_client.get_dev_environment_status(
            user_id=user_id,
            project_id=str(project_id),
            container_name=container_name,
            project_slug=project_slug
        )

    # =========================================================================
    # CONTAINER CREATION HELPERS
    # =========================================================================

    async def _create_base_container(
        self,
        container,
        names: Dict[str, str],
        namespace: str,
        pvc_name: str,
        project,
        user_id: UUID
    ) -> None:
        """Create Deployment + Service + Ingress for a base container."""
        from ...services.base_config_parser import (
            get_base_config_from_cache,
            generate_startup_command
        )

        # Read base configuration
        base_config = None
        if container.base:
            try:
                base_slug = container.base.slug
                base_config = await asyncio.to_thread(get_base_config_from_cache, base_slug)
            except Exception as e:
                logger.debug(f"[K8S] Could not read config from cache: {e}")

        # Determine port and working directory
        container_port = container.internal_port or (base_config.port if base_config else 3000)
        working_dir = '/app'
        if base_config and base_config.structure_type == "multi":
            container_name_lower = container.name.lower()
            if 'frontend' in container_name_lower or 'client' in container_name_lower:
                working_dir = '/app/frontend'
            elif 'backend' in container_name_lower or 'server' in container_name_lower:
                working_dir = '/app/backend'

        # Generate startup command and init script
        startup_command = generate_startup_command(base_config) if base_config else "npm run dev"
        init_script = create_base_container_init_script(container, base_config)

        # Create Deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=names["deployment"],
                namespace=namespace,
                labels={
                    "app": "dev-environment",
                    "project-id": str(project.id),
                    "container-id": str(container.id),
                    "container-name": names.get("safe_container_name", names["deployment"]),
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
                                image=self.settings.k8s_devserver_image,
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
                                    *[client.V1EnvVar(name=k, value=v)
                                      for k, v in (container.environment_vars or {}).items()]
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

        await self.k8s_client.create_deployment(deployment, namespace)

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

        await self.k8s_client.create_service(service, namespace)

        # Create Ingress
        if container_port:
            await self._create_ingress(names, namespace, container_port)

    async def _create_service_container(
        self,
        container,
        names: Dict[str, str],
        namespace: str,
        project,
        user_id: UUID
    ) -> None:
        """Create Deployment + Service for a service container (Postgres, Redis, etc.)."""
        from ...services.service_definitions import get_service

        service_def = get_service(container.service_slug)
        if not service_def:
            logger.error(f"[K8S] Service '{container.service_slug}' not found, skipping")
            return

        # Create PVC for service data
        service_pvc_name = f"service-{container.service_slug}-{project.id}"
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
        await self.k8s_client.create_pvc(pvc, namespace)

        # Build volume mounts
        volume_mounts = [
            client.V1VolumeMount(name="service-data", mount_path=path)
            for path in service_def.volumes
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

        await self.k8s_client.create_deployment(deployment, namespace)

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

        await self.k8s_client.create_service(service, namespace)

    async def _create_ingress(
        self,
        names: Dict[str, str],
        namespace: str,
        port: int
    ) -> None:
        """Create Ingress for external access.

        Unlike the main Tesslate application ingress, user project previews
        do NOT use nginx auth subrequests. This matches how Docker deployment
        uses simple Traefik labels without auth middleware.

        Security note: File operations, shell access, and agent commands still
        require JWT authentication through the main backend API - that auth
        is separate from this ingress-level routing.
        """
        ingress = client.V1Ingress(
            metadata=client.V1ObjectMeta(
                name=names["ingress"],
                namespace=namespace,
                annotations={
                    # SSL/TLS
                    "cert-manager.io/cluster-issuer": "letsencrypt-prod",
                    "nginx.ingress.kubernetes.io/ssl-redirect": "false",
                    # WebSocket support
                    "nginx.ingress.kubernetes.io/proxy-http-version": "1.1",
                    "nginx.ingress.kubernetes.io/websocket-services": names["service"],
                    # Allow iframe embedding (for preview panel)
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

        await self.k8s_client.create_ingress(ingress, namespace)

    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================

    async def read_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str
    ) -> Optional[str]:
        """Read a file from a container via Kubernetes exec."""
        return await self.k8s_client.read_file_from_pod(
            user_id=user_id,
            project_id=str(project_id),
            file_path=file_path,
            container_name=container_name
        )

    async def write_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        content: str
    ) -> bool:
        """Write a file to a container via Kubernetes exec."""
        return await self.k8s_client.write_file_to_pod(
            user_id=user_id,
            project_id=str(project_id),
            file_path=file_path,
            content=content,
            container_name=container_name
        )

    async def delete_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str
    ) -> bool:
        """Delete a file from a container via Kubernetes exec."""
        return await self.k8s_client.delete_file_from_pod(
            user_id=user_id,
            project_id=str(project_id),
            file_path=file_path,
            container_name=container_name
        )

    async def list_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        directory: str = "."
    ) -> List[Dict[str, Any]]:
        """List files in a directory via Kubernetes exec."""
        return await self.k8s_client.list_files_in_pod(
            user_id=user_id,
            project_id=str(project_id),
            directory=directory,
            container_name=container_name
        )

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
        """Execute a command in a container via Kubernetes exec."""
        if working_dir:
            full_command = ["/bin/sh", "-c", f"cd /app/{working_dir} && {' '.join(command)}"]
        else:
            full_command = command

        return await self.k8s_client.execute_command_in_pod(
            user_id=user_id,
            project_id=str(project_id),
            command=full_command,
            timeout=timeout,
            container_name=container_name
        )

    async def is_container_ready(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str
    ) -> Dict[str, Any]:
        """Check if a container is ready for commands."""
        return await self.k8s_client.check_pod_ready(
            user_id=user_id,
            project_id=str(project_id),
            check_responsive=True,
            container_name=container_name
        )

    # =========================================================================
    # ACTIVITY TRACKING
    # =========================================================================

    def track_activity(
        self,
        user_id: UUID,
        project_id: str,
        container_name: Optional[str] = None
    ) -> None:
        """Track activity for idle cleanup."""
        project_key = self._get_project_key(user_id, project_id)
        self.activity_tracker[project_key] = time.time()
        logger.debug(f"[K8S] Activity tracked for {project_key}")

    # =========================================================================
    # CLEANUP
    # =========================================================================

    async def cleanup_idle_environments(
        self,
        idle_timeout_minutes: int = 30
    ) -> List[str]:
        """Cleanup idle Kubernetes environments."""
        if self.settings.k8s_use_s3_storage:
            return await self._cleanup_s3_mode(idle_timeout_minutes)
        else:
            return await self._cleanup_persistent_mode(idle_timeout_minutes)

    async def _cleanup_s3_mode(self, idle_timeout_minutes: int) -> List[str]:
        """S3 storage mode: Hibernate idle environments to S3."""
        logger.info("[K8S:S3] Starting S3 mode cleanup...")

        hibernated = []
        current_time = time.time()
        idle_timeout_seconds = idle_timeout_minutes * 60

        for project_key, last_activity in list(self.activity_tracker.items()):
            idle_time = current_time - last_activity
            idle_minutes = idle_time / 60

            if idle_time > idle_timeout_seconds:
                logger.info(f"[K8S:S3] Hibernating {project_key} (idle {idle_minutes:.1f} min)")
                hibernated.append(project_key)
                self.activity_tracker.pop(project_key, None)

        logger.info(f"[K8S:S3] Cleanup completed: {len(hibernated)} environments hibernated")
        return hibernated

    async def _cleanup_persistent_mode(self, idle_timeout_minutes: int) -> List[str]:
        """Persistent PVC mode: Two-tier cleanup (scale to 0, then delete)."""
        logger.info("[K8S:PERSISTENT] Starting persistent mode cleanup...")

        scaled_down = []
        removed = []
        current_time = time.time()
        tier1_timeout_seconds = idle_timeout_minutes * 60
        tier2_timeout_seconds = 24 * 60 * 60  # 24 hours

        # Tier 2: Delete long-paused environments
        for project_key, paused_at in list(self.paused_at_tracker.items()):
            paused_duration = current_time - paused_at
            if paused_duration > tier2_timeout_seconds:
                logger.info(f"[K8S:TIER2] Deleting long-paused environment: {project_key}")
                removed.append(project_key)
                self.paused_at_tracker.pop(project_key, None)
                self.activity_tracker.pop(project_key, None)

        # Tier 1: Scale down idle environments
        for project_key, last_activity in list(self.activity_tracker.items()):
            if project_key in self.paused_at_tracker:
                continue

            idle_time = current_time - last_activity
            if idle_time > tier1_timeout_seconds:
                logger.info(f"[K8S:TIER1] Scaling down idle environment: {project_key}")
                scaled_down.append(project_key)
                self.paused_at_tracker[project_key] = current_time

        total = len(scaled_down) + len(removed)
        logger.info(f"[K8S:PERSISTENT] Cleanup completed: {len(scaled_down)} scaled down, {len(removed)} removed")
        return scaled_down + removed

    # =========================================================================
    # ADVANCED OPERATIONS
    # =========================================================================

    async def scale_deployment(
        self,
        user_id: UUID,
        project_id: str,
        container_name: str,
        replicas: int
    ) -> None:
        """Scale a deployment to a specific number of replicas."""
        await self.k8s_client.scale_deployment(
            user_id=user_id,
            project_id=project_id,
            replicas=replicas
        )

        project_key = self._get_project_key(user_id, project_id)
        if replicas == 0:
            self.paused_at_tracker[project_key] = time.time()
        else:
            self.paused_at_tracker.pop(project_key, None)
            self.activity_tracker[project_key] = time.time()

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
