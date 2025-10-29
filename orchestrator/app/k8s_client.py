"""
Kubernetes client for managing development environments.

This module provides a production-ready interface to the Kubernetes API
for creating, managing, and cleaning up user development environments.
"""

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream
import os
import logging
import asyncio
import shlex
import json
from typing import Dict, Optional, Any, List
from uuid import UUID
from .utils.resource_naming import get_container_name, get_project_path

logger = logging.getLogger(__name__)

# Configuration constants
# Custom dev server image with pre-installed dependencies for fast startup
DEV_CONTAINER_IMAGE = "registry.digitalocean.com/finetune/tesslate-dev-server:latest"
IMAGE_PULL_SECRET = "docr-secret"  # Required for private DigitalOcean registry
DEFAULT_NAMESPACE = "tesslate"
USER_ENVIRONMENTS_NAMESPACE = "tesslate-user-environments"


class KubernetesManager:
    """
    Manages Kubernetes resources for user development environments.

    This class provides methods to create, delete, and manage Kubernetes
    resources (Deployments, Services, Ingresses) for isolated user dev environments.
    """

    def __init__(self):
        """Initialize Kubernetes client with in-cluster or kubeconfig."""
        try:
            # Try in-cluster config first (for production)
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes configuration")
        except config.ConfigException:
            try:
                # Fall back to kubeconfig (for development)
                config.load_kube_config()
                logger.info("Loaded kubeconfig for development")
            except config.ConfigException as e:
                logger.error(f"Failed to load Kubernetes config: {e}")
                raise RuntimeError("Cannot load Kubernetes configuration") from e

        # Initialize API clients
        self.apps_v1 = client.AppsV1Api()
        self.core_v1 = client.CoreV1Api()
        self.networking_v1 = client.NetworkingV1Api()
        self.namespace = os.getenv("KUBERNETES_NAMESPACE", DEFAULT_NAMESPACE)
        self.user_namespace = USER_ENVIRONMENTS_NAMESPACE

        logger.info(f"Kubernetes client initialized - Main namespace: {self.namespace}, User environments: {self.user_namespace}")

    def _generate_resource_names(self, user_id: UUID, project_id: str, project_slug: str = None) -> Dict[str, str]:
        """
        Generate consistent resource names for a user's project.

        Args:
            user_id: User ID (for internal resource naming)
            project_id: Project ID (for internal resource naming)
            project_slug: Project slug for hostname (e.g., "my-app-k3x8n2")

        Returns:
            Dictionary with namespace, deployment, service, ingress, and hostname
        """
        from .config import get_settings
        settings = get_settings()

        # Internal resource names still use IDs for uniqueness
        base_name = get_container_name(user_id, project_id, mode="kubernetes")

        # Hostname uses project slug for clean URLs (fallback to ID-based for backwards compat)
        if not project_slug:
            project_slug = f"{user_id}-{project_id}"
        hostname = f"{project_slug}.{settings.app_domain}"

        return {
            "namespace": self.user_namespace,
            "deployment": base_name,
            "service": f"{base_name}-service",
            "ingress": f"{base_name}-ingress",
            "hostname": hostname
        }

    def _create_deployment_manifest(
        self,
        deployment_name: str,
        user_id: UUID,
        project_id: str,
        project_path: str
    ) -> client.V1Deployment:
        """Create a deployment manifest for dev environment."""

        # Generate subPath for user isolation
        sub_path = get_project_path(user_id, project_id)

        return client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=deployment_name,
                labels={
                    "app": "dev-environment",
                    "dev-environment": "true",
                    "user-id": str(user_id),
                    "project-id": project_id,
                    "managed-by": "tesslate-backend"
                }
            ),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(
                    match_labels={"app": deployment_name}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={
                            "app": deployment_name,  # Specific label for this deployment
                            "dev-environment": "true"  # Common label for pod affinity
                        }
                    ),
                    spec=client.V1PodSpec(
                        # REQUIRED pod affinity to ensure all user environment pods are scheduled on the same node
                        # This is CRITICAL because the shared PVC uses ReadWriteOnce (RWO) on DigitalOcean
                        # RWO volumes can only be mounted by pods on a single node
                        affinity=client.V1Affinity(
                            pod_affinity=client.V1PodAffinity(
                                required_during_scheduling_ignored_during_execution=[
                                    client.V1PodAffinityTerm(
                                        label_selector=client.V1LabelSelector(
                                            match_labels={"dev-environment": "true"}
                                        ),
                                        topology_key="kubernetes.io/hostname"
                                    )
                                ]
                            )
                        ),
                        security_context=client.V1PodSecurityContext(
                            run_as_non_root=True,
                            run_as_user=1000,
                            fs_group=1000,
                            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault")
                        ),
                        # Include image pull secrets for private registry access
                        image_pull_secrets=[
                            client.V1LocalObjectReference(name=IMAGE_PULL_SECRET)
                        ] if IMAGE_PULL_SECRET else None,
                        # No init container needed - template is baked into dev server image
                        containers=[
                            client.V1Container(
                                name="dev-server",
                                image=DEV_CONTAINER_IMAGE,
                                ports=[client.V1ContainerPort(container_port=5173)],
                                working_dir="/app",
                                command=["/bin/sh"],
                                args=[
                                    "-c",
                                    """
                                    set -e  # Exit on error

                                    echo "[DEV] ======================================"
                                    echo "[DEV] Tesslate Dev Server - Fast Startup"
                                    echo "[DEV] User: {user_id}, Project: {project_id}"
                                    echo "[DEV] Node: $(node --version), NPM: $(npm --version)"
                                    echo "[DEV] ======================================"

                                    # Check if project directory exists and is writable
                                    if [ ! -d "/app" ]; then
                                        echo "[DEV] ERROR: Project directory /app not found!"
                                        exit 1
                                    fi

                                    # Initialize project from template
                                    # Template is baked into the image at /template with all dependencies
                                    if [ -z "$(ls -A /app 2>/dev/null)" ]; then
                                        echo "[DEV] Initializing new project from template..."
                                        echo "[DEV] Copying pre-built template with dependencies..."
                                        cp -r /template/. /app/
                                        echo "[DEV] ✓ Template copied (includes node_modules)"
                                        echo "[DEV] Project size: $(du -sh /app | cut -f1)"
                                    else
                                        echo "[DEV] Project directory has existing files"
                                        echo "[DEV] Files: $(ls -A /app | head -5 | tr '\n' ' ')..."
                                    fi

                                    # Ensure node_modules is complete - critical for fast startup
                                    # If Vite binary is missing, copy pre-built node_modules from template
                                    if [ ! -f "/app/node_modules/.bin/vite" ] && [ ! -L "/app/node_modules/.bin/vite" ]; then
                                        echo "[DEV] node_modules missing or incomplete"
                                        echo "[DEV] Copying pre-built node_modules from template..."
                                        rm -rf /app/node_modules 2>/dev/null || true
                                        cp -r /template/node_modules /app/
                                        echo "[DEV] ✓ node_modules restored from template"
                                    fi

                                    # Verify critical files exist
                                    if [ ! -f "/app/package.json" ]; then
                                        echo "[DEV] ERROR: No package.json found!"
                                        exit 1
                                    fi
                                    if [ ! -f "/app/node_modules/.bin/vite" ] && [ ! -L "/app/node_modules/.bin/vite" ]; then
                                        echo "[DEV] ERROR: Vite binary still missing after template copy!"
                                        echo "[DEV] This should not happen - template may be corrupted"
                                        exit 1
                                    fi

                                    # Configure Vite to allow all hosts (required for ingress routing)
                                    if [ -f "/app/vite.config.js" ]; then
                                        echo "[DEV] Patching vite.config.js for Kubernetes ingress..."

                                        cat > /app/vite.config.js.new << 'VITECONFIG'
import {{ defineConfig }} from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({{
  plugins: [react()],
  server: {{
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: true
  }}
}})
VITECONFIG
                                        mv /app/vite.config.js.new /app/vite.config.js
                                        echo "[DEV] ✓ Vite config patched"
                                    fi

                                    # Start development server (working directory is already /app)
                                    echo "[DEV] ======================================"
                                    echo "[DEV] 🚀 Starting Vite dev server..."
                                    echo "[DEV] Port: 5173"
                                    echo "[DEV] ======================================"
                                    exec npx vite --host 0.0.0.0 --port 5173 --strictPort
                                    """.format(user_id=user_id, project_id=project_id)
                                ],
                                volume_mounts=[
                                    client.V1VolumeMount(
                                        name="projects-storage",
                                        mount_path="/app",
                                        sub_path=sub_path
                                    )
                                ],
                                resources=client.V1ResourceRequirements(
                                    requests={"memory": "128Mi", "cpu": "50m"},
                                    limits={"memory": "256Mi", "cpu": "250m"}
                                ),
                                env=[
                                    client.V1EnvVar(name="NODE_ENV", value="development"),
                                    client.V1EnvVar(name="PORT", value="5173"),
                                    client.V1EnvVar(name="HOST", value="0.0.0.0")
                                ],
                                readiness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(
                                        path="/",
                                        port=5173
                                    ),
                                    initial_delay_seconds=3,
                                    period_seconds=2,
                                    timeout_seconds=3,
                                    failure_threshold=3
                                ),
                                startup_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(
                                        path="/",
                                        port=5173
                                    ),
                                    initial_delay_seconds=5,  # Start checking after 5 seconds (Vite takes ~3-4s)
                                    period_seconds=2,  # Check every 2 seconds
                                    timeout_seconds=3,
                                    failure_threshold=10  # Allow 25 seconds total (5s + 10*2s)
                                ),
                                liveness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(
                                        path="/",
                                        port=5173
                                    ),
                                    initial_delay_seconds=10,
                                    period_seconds=10,
                                    timeout_seconds=5,
                                    failure_threshold=3
                                )
                            )
                        ],
                        volumes=[
                            client.V1Volume(
                                name="projects-storage",
                                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                    claim_name="tesslate-projects-pvc"
                                )
                            )
                        ]
                    )
                )
            )
        )

    def _create_service_manifest(self, service_name: str, deployment_name: str) -> client.V1Service:
        """Create a service manifest for dev environment."""
        return client.V1Service(
            metadata=client.V1ObjectMeta(
                name=service_name,
                labels={
                    "app": "dev-environment",
                    "deployment": deployment_name
                }
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"app": deployment_name},
                ports=[
                    client.V1ServicePort(
                        port=5173,
                        target_port=5173,
                        protocol="TCP",
                        name="http"
                    )
                ]
            )
        )

    def _create_ingress_manifest(
        self,
        ingress_name: str,
        service_name: str,
        hostname: str,
        user_id: UUID,
        namespace: str
    ) -> client.V1Ingress:
        """Create an ingress manifest for dev environment with NGINX external authentication."""
        return client.V1Ingress(
            metadata=client.V1ObjectMeta(
                name=ingress_name,
                annotations={
                    # ===== AUTHENTICATION & AUTHORIZATION =====
                    # External authentication via backend API to verify user ownership
                    "nginx.ingress.kubernetes.io/auth-url": "https://studio-test.tesslate.com/api/auth/verify",
                    "nginx.ingress.kubernetes.io/auth-method": "GET",
                    "nginx.ingress.kubernetes.io/auth-response-headers": "X-User-ID",

                    # Pass request metadata to auth endpoint for validation
                    # Extract token from URL parameter (?auth_token=xxx) and set as Authorization header
                    "nginx.ingress.kubernetes.io/configuration-snippet": f"""
                        # Extract token from URL parameter for iframe-based authentication
                        set $token "";
                        if ($arg_auth_token != "") {{
                            set $token "Bearer $arg_auth_token";
                        }}
                        # Use header token if present (for direct API calls)
                        if ($http_authorization != "") {{
                            set $token $http_authorization;
                        }}
                    """,

                    # Auth snippet to pass headers to the auth subrequest
                    "nginx.ingress.kubernetes.io/auth-snippet": f"""
                        # Pass metadata to auth endpoint via subrequest
                        proxy_set_header X-Original-URI $request_uri;
                        proxy_set_header X-Expected-User-ID {user_id};
                        proxy_set_header X-Forwarded-Host $host;
                        proxy_set_header Authorization $token;
                    """,

                    # Cache auth decisions for 200 seconds to reduce backend load
                    # Uses user's token as cache key
                    # Note: auth-cache-duration expects HTTP status codes (200 202) and a time value
                    # Format: "200 202 5m" means cache 200 and 202 responses for 5 minutes
                    "nginx.ingress.kubernetes.io/auth-cache-key": "$http_authorization",
                    "nginx.ingress.kubernetes.io/auth-cache-duration": "200 202 5m",

                    # SSL configuration
                    "cert-manager.io/cluster-issuer": "letsencrypt-prod",
                    "nginx.ingress.kubernetes.io/ssl-redirect": "true",

                    # Rate limiting to prevent abuse
                    "nginx.ingress.kubernetes.io/limit-rps": "20",
                    "nginx.ingress.kubernetes.io/limit-burst-multiplier": "3",

                    # Proxy configuration for development server
                    "nginx.ingress.kubernetes.io/proxy-body-size": "50m",
                    "nginx.ingress.kubernetes.io/proxy-connect-timeout": "3600",
                    "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600",
                    "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",

                    # WebSocket support for HMR (Hot Module Replacement)
                    "nginx.ingress.kubernetes.io/proxy-http-version": "1.1",
                    "nginx.ingress.kubernetes.io/websocket-services": service_name,

                    # CORS headers to allow iframe embedding from main app
                    "nginx.ingress.kubernetes.io/enable-cors": "true",
                    "nginx.ingress.kubernetes.io/cors-allow-origin": "https://studio-test.tesslate.com",
                    "nginx.ingress.kubernetes.io/cors-allow-credentials": "true",
                    "nginx.ingress.kubernetes.io/cors-allow-methods": "GET, POST, PUT, DELETE, OPTIONS",
                    "nginx.ingress.kubernetes.io/cors-allow-headers": "DNT,Keep-Alive,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization",

                    # Security headers
                    "nginx.ingress.kubernetes.io/server-snippet": f"""
                        add_header X-Content-Type-Options "nosniff" always;
                        add_header X-Frame-Options "ALLOW-FROM https://studio-test.tesslate.com" always;
                        add_header X-XSS-Protection "1; mode=block" always;
                        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
                    """
                }
            ),
            spec=client.V1IngressSpec(
                ingress_class_name="nginx",
                tls=[
                    client.V1IngressTLS(
                        hosts=[hostname],
                        secret_name="tesslate-wildcard-tls"
                    )
                ],
                rules=[
                    client.V1IngressRule(
                        host=hostname,
                        http=client.V1HTTPIngressRuleValue(
                            paths=[
                                client.V1HTTPIngressPath(
                                    path="/",
                                    path_type="Prefix",
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=service_name,
                                            port=client.V1ServiceBackendPort(number=5173)
                                        )
                                    )
                                )
                            ]
                        )
                    )
                ]
            )
        )

    async def create_dev_environment(
        self,
        user_id: UUID,
        project_id: str,
        project_path: str,
        project_slug: str = None
    ) -> Dict[str, Any]:
        """
        Create a complete development environment for a user's project.

        Args:
            user_id: Unique identifier for the user
            project_id: Unique identifier for the project (for internal naming)
            project_path: Path to the project files (used for metadata only)
            project_slug: Project slug for URL generation (e.g., "my-app-k3x8n2")

        Returns:
            Dict containing environment details including hostname

        Raises:
            RuntimeError: If Kubernetes resource creation fails
        """
        names = self._generate_resource_names(user_id, project_id, project_slug)
        namespace = names["namespace"]

        logger.info(f"[K8S] Creating dev environment for user {user_id}, project {project_id}")
        logger.info(f"[K8S] Namespace: {namespace}")
        logger.info(f"[K8S] Hostname: {names['hostname']}")

        try:
            # Clean up any existing resources first
            logger.info(f"[K8S] Cleaning up any existing resources...")
            await self.delete_dev_environment(user_id, project_id)

            # Create Deployment
            logger.info(f"[K8S] Creating Deployment: {names['deployment']}")
            deployment = self._create_deployment_manifest(
                names["deployment"], user_id, project_id, project_path
            )
            await asyncio.to_thread(
                self.apps_v1.create_namespaced_deployment,
                namespace=namespace,
                body=deployment
            )
            logger.info(f"[K8S] ✅ Created deployment: {names['deployment']}")

            # Create Service
            logger.info(f"[K8S] Creating Service: {names['service']}")
            service = self._create_service_manifest(
                names["service"], names["deployment"]
            )
            await asyncio.to_thread(
                self.core_v1.create_namespaced_service,
                namespace=namespace,
                body=service
            )
            logger.info(f"[K8S] ✅ Created service: {names['service']}")

            # Create Ingress
            logger.info(f"[K8S] Creating Ingress: {names['ingress']}")
            ingress = self._create_ingress_manifest(
                names["ingress"], names["service"], names["hostname"], user_id, namespace
            )
            await asyncio.to_thread(
                self.networking_v1.create_namespaced_ingress,
                namespace=namespace,
                body=ingress
            )
            logger.info(f"[K8S] ✅ Created ingress: {names['ingress']}")

            # Wait for deployment to be ready (longer timeout for first startup with npm install)
            logger.info(f"[K8S] Waiting for deployment to be ready (timeout: 300s)...")
            await self._wait_for_deployment_ready(names["deployment"], namespace, timeout=300)

            logger.info(f"[K8S] ✅ Dev environment created successfully!")

            return {
                "hostname": names["hostname"],
                "url": f"https://{names['hostname']}",
                "deployment_name": names["deployment"],
                "service_name": names["service"],
                "ingress_name": names["ingress"],
                "namespace": namespace,
                "status": "ready"
            }

        except ApiException as e:
            logger.error(f"[K8S] ❌ Kubernetes API error: {e.status} - {e.reason}", exc_info=True)
            logger.error(f"[K8S] Error body: {e.body}")

            # Cleanup on failure
            try:
                await self.delete_dev_environment(user_id, project_id)
            except Exception as cleanup_error:
                logger.error(f"[K8S] Error during cleanup: {cleanup_error}", exc_info=True)

            raise RuntimeError(f"Failed to create dev environment: {e.status} {e.reason}") from e

        except Exception as e:
            logger.error(f"[K8S] ❌ Unexpected error creating dev environment: {e}", exc_info=True)

            # Cleanup on failure
            try:
                await self.delete_dev_environment(user_id, project_id)
            except Exception as cleanup_error:
                logger.error(f"[K8S] Error during cleanup: {cleanup_error}", exc_info=True)

            raise RuntimeError(f"Failed to create dev environment: {str(e)}") from e

    async def delete_dev_environment(self, user_id: UUID, project_id: str) -> None:
        """
        Delete all Kubernetes resources for a development environment.

        Args:
            user_id: Unique identifier for the user
            project_id: Unique identifier for the project
        """
        names = self._generate_resource_names(user_id, project_id)
        namespace = names["namespace"]
        cleanup_errors = []

        # Delete resources in reverse order (graceful cleanup)

        # Delete Ingress
        try:
            await asyncio.to_thread(
                self.networking_v1.delete_namespaced_ingress,
                name=names["ingress"],
                namespace=namespace
            )
            logger.info(f"Deleted ingress: {names['ingress']} from namespace: {namespace}")
        except ApiException as e:
            if e.status != 404:  # Ignore "not found" errors
                cleanup_errors.append(f"Ingress {names['ingress']}: {e}")

        # Delete Service
        try:
            await asyncio.to_thread(
                self.core_v1.delete_namespaced_service,
                name=names["service"],
                namespace=namespace
            )
            logger.info(f"Deleted service: {names['service']} from namespace: {namespace}")
        except ApiException as e:
            if e.status != 404:
                cleanup_errors.append(f"Service {names['service']}: {e}")

        # Delete Deployment
        try:
            await asyncio.to_thread(
                self.apps_v1.delete_namespaced_deployment,
                name=names["deployment"],
                namespace=namespace
            )
            logger.info(f"Deleted deployment: {names['deployment']} from namespace: {namespace}")
        except ApiException as e:
            if e.status != 404:
                cleanup_errors.append(f"Deployment {names['deployment']}: {e}")

        if cleanup_errors:
            logger.warning(f"Cleanup warnings for user {user_id}, project {project_id}: {cleanup_errors}")

    async def get_dev_environment_status(self, user_id: UUID, project_id: str) -> Dict[str, Any]:
        """
        Get the status of a development environment.

        Args:
            user_id: Unique identifier for the user
            project_id: Unique identifier for the project

        Returns:
            Dict containing environment status information
        """
        names = self._generate_resource_names(user_id, project_id)
        namespace = names["namespace"]

        try:
            # Check deployment status
            deployment = await asyncio.to_thread(
                self.apps_v1.read_namespaced_deployment,
                name=names["deployment"],
                namespace=namespace
            )

            # Check pod status
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}"
            )

            deployment_status = deployment.status
            pod_statuses = []

            for pod in pods.items:
                pod_statuses.append({
                    "name": pod.metadata.name,
                    "phase": pod.status.phase,
                    "ready": self._is_pod_ready(pod)
                })

            return {
                "hostname": names["hostname"],
                "url": f"https://{names['hostname']}",
                "deployment_ready": deployment_status.ready_replicas == deployment_status.replicas,
                "replicas": {
                    "desired": deployment_status.replicas,
                    "ready": deployment_status.ready_replicas or 0,
                    "available": deployment_status.available_replicas or 0
                },
                "pods": pod_statuses,
                "status": "ready" if deployment_status.ready_replicas == deployment_status.replicas else "pending"
            }

        except ApiException as e:
            if e.status == 404:
                return {
                    "status": "not_found",
                    "hostname": names["hostname"]
                }
            logger.error(f"Error getting dev environment status: {e}")
            return {
                "status": "error",
                "error": str(e),
                "hostname": names["hostname"]
            }

    async def check_dev_environment_health(self, user_id: UUID, project_id: str) -> Dict[str, Any]:
        """
        Check if a development environment exists and is healthy.

        Best practice: Always verify container exists and is ready before returning URLs.

        Args:
            user_id: Unique identifier for the user
            project_id: Unique identifier for the project

        Returns:
            Dict with 'exists', 'ready', and 'url' keys
        """
        status = await self.get_dev_environment_status(user_id, project_id)

        if status["status"] == "not_found":
            return {
                "exists": False,
                "ready": False,
                "url": None,
                "message": "Development environment does not exist"
            }

        if status["status"] == "error":
            return {
                "exists": False,
                "ready": False,
                "url": None,
                "message": f"Error checking environment: {status.get('error', 'Unknown error')}"
            }

        is_ready = status.get("deployment_ready", False)
        return {
            "exists": True,
            "ready": is_ready,
            "url": status["url"] if is_ready else None,
            "message": "Environment is ready" if is_ready else "Environment is starting up",
            "replicas": status.get("replicas"),
            "pods": status.get("pods")
        }

    def _is_pod_ready(self, pod: client.V1Pod) -> bool:
        """Check if a pod is ready."""
        if not pod.status.conditions:
            return False

        for condition in pod.status.conditions:
            if condition.type == "Ready":
                return condition.status == "True"
        return False

    async def _wait_for_deployment_ready(self, deployment_name: str, namespace: str, timeout: int = 120) -> None:
        """
        Wait for a deployment to be ready.

        Args:
            deployment_name: Name of the deployment to wait for
            namespace: Namespace of the deployment
            timeout: Maximum time to wait in seconds
        """
        for _ in range(timeout):
            try:
                deployment = await asyncio.to_thread(
                    self.apps_v1.read_namespaced_deployment,
                    name=deployment_name,
                    namespace=namespace
                )

                if (deployment.status.ready_replicas and
                    deployment.status.ready_replicas == deployment.status.replicas):
                    logger.info(f"Deployment {deployment_name} is ready")
                    return

            except ApiException as e:
                if e.status != 404:
                    logger.warning(f"Error checking deployment status: {e}")

            await asyncio.sleep(1)

        raise RuntimeError(f"Deployment {deployment_name} did not become ready within {timeout} seconds")

    async def list_dev_environments(self, user_id: Optional[UUID] = None) -> list:
        """
        List all development environments, optionally filtered by user.

        Args:
            user_id: Optional user ID to filter environments

        Returns:
            List of development environment information
        """
        try:
            label_selector = "app=dev-environment"
            if user_id:
                label_selector += f",user-id={str(user_id)}"

            deployments = await asyncio.to_thread(
                self.apps_v1.list_namespaced_deployment,
                namespace=self.user_namespace,
                label_selector=label_selector
            )

            environments = []
            for deployment in deployments.items:
                labels = deployment.metadata.labels
                env_user_id = labels.get("user-id")
                project_id = labels.get("project-id")

                if env_user_id and project_id:
                    status = await self.get_dev_environment_status(env_user_id, project_id)
                    environments.append({
                        "user_id": env_user_id,
                        "project_id": project_id,
                        "deployment_name": deployment.metadata.name,
                        **status
                    })

            return environments

        except ApiException as e:
            logger.error(f"Error listing dev environments: {e}")
            return []

    # ========================================================================
    # FILE OPERATIONS - K8s API-based file management (maintains stateless backend)
    # ========================================================================

    def _exec_in_pod(
        self,
        pod_name: str,
        namespace: str,
        container_name: str,
        command: List[str],
        timeout: int = 30
    ) -> str:
        """
        Execute a command in a pod and return output.

        Args:
            pod_name: Name of the pod
            namespace: Namespace
            container_name: Container name within pod
            command: Command to execute as list
            timeout: Command timeout in seconds

        Returns:
            Command output (stdout + stderr)

        Raises:
            RuntimeError: If command execution fails
        """
        try:
            logger.debug(f"[EXEC] Executing in pod {pod_name}: {' '.join(command)}")

            resp = stream(
                self.core_v1.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                container=container_name,
                command=command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=True,
                _request_timeout=timeout
            )

            logger.debug(f"[EXEC] Command completed successfully")
            return resp

        except Exception as e:
            logger.error(f"[EXEC] Command failed in pod {pod_name}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to execute command in pod: {str(e)}") from e

    async def read_file_from_pod(
        self,
        user_id: UUID,
        project_id: str,
        file_path: str
    ) -> Optional[str]:
        """
        Read a file from a dev container pod via Kubernetes API.

        Args:
            user_id: User ID
            project_id: Project ID
            file_path: Relative path within project (e.g., "src/App.jsx")

        Returns:
            File content as string, or None if file doesn't exist

        Raises:
            RuntimeError: If pod is not found or read fails
        """
        names = self._generate_resource_names(user_id, project_id)
        namespace = names["namespace"]

        try:
            # Get the pod for this deployment
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}"
            )

            if not pods.items:
                logger.error(f"[READ] No pod found for deployment {names['deployment']}")
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            pod_name = pods.items[0].metadata.name
            container_name = "dev-server"

            # Secure path - prevent directory traversal
            safe_path = file_path.replace("..", "").strip("/")
            full_path = f"/app/{safe_path}"

            # Check if file exists first
            check_cmd = ["/bin/sh", "-c", f"test -f {shlex.quote(full_path)} && echo exists || echo notfound"]
            result = await asyncio.to_thread(
                self._exec_in_pod,
                pod_name,
                namespace,
                container_name,
                check_cmd,
                timeout=10
            )

            if "notfound" in result:
                logger.warning(f"[READ] File not found: {file_path}")
                return None

            # Read file content
            read_cmd = ["/bin/sh", "-c", f"cat {shlex.quote(full_path)}"]
            content = await asyncio.to_thread(
                self._exec_in_pod,
                pod_name,
                namespace,
                container_name,
                read_cmd,
                timeout=30
            )

            logger.info(f"[READ] Successfully read {file_path} ({len(content)} bytes)")
            return content

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[READ] Failed to read file {file_path}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to read file from pod: {str(e)}") from e

    async def write_file_to_pod(
        self,
        user_id: UUID,
        project_id: str,
        file_path: str,
        content: str
    ) -> bool:
        """
        Write a file directly to a dev container pod via Kubernetes API.

        This maintains separation of concerns - the backend doesn't need to know
        about PVCs or storage, it just asks the container to save the file.

        Args:
            user_id: User ID
            project_id: Project ID
            file_path: Relative path within project (e.g., "src/App.jsx")
            content: File content to write

        Returns:
            True if successful

        Raises:
            RuntimeError: If pod is not found or write fails
        """
        names = self._generate_resource_names(user_id, project_id)
        namespace = names["namespace"]

        try:
            # Get the pod for this deployment
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}"
            )

            if not pods.items:
                logger.error(f"[WRITE] No pod found for deployment {names['deployment']}")
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            pod_name = pods.items[0].metadata.name
            container_name = "dev-server"

            # Secure path - prevent directory traversal
            safe_path = file_path.replace("..", "").strip("/")
            full_path = f"/app/{safe_path}"

            # Ensure parent directory exists
            dir_path = os.path.dirname(full_path)
            if dir_path and dir_path != "/app":
                mkdir_cmd = ["/bin/sh", "-c", f"mkdir -p {shlex.quote(dir_path)}"]
                await asyncio.to_thread(
                    self._exec_in_pod,
                    pod_name,
                    namespace,
                    container_name,
                    mkdir_cmd,
                    timeout=10
                )

            # Write file using cat with heredoc for safety with special characters
            # Use a unique marker to avoid conflicts
            marker = "EOF_MARKER_K8S_WRITE"
            write_cmd = [
                "/bin/sh", "-c",
                f"cat > {shlex.quote(full_path)} << '{marker}'\n{content}\n{marker}"
            ]

            await asyncio.to_thread(
                self._exec_in_pod,
                pod_name,
                namespace,
                container_name,
                write_cmd,
                timeout=60  # Longer timeout for large files
            )

            logger.info(f"[WRITE] Successfully wrote {file_path} ({len(content)} bytes) to pod {pod_name}")
            return True

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[WRITE] Failed to write file {file_path}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to write file to pod: {str(e)}") from e

    async def delete_file_from_pod(
        self,
        user_id: UUID,
        project_id: str,
        file_path: str
    ) -> bool:
        """
        Delete a file from a dev container pod via Kubernetes API.

        Args:
            user_id: User ID
            project_id: Project ID
            file_path: Relative path within project (e.g., "src/OldComponent.jsx")

        Returns:
            True if successful (or file didn't exist)

        Raises:
            RuntimeError: If pod is not found or delete fails
        """
        names = self._generate_resource_names(user_id, project_id)
        namespace = names["namespace"]

        try:
            # Get the pod for this deployment
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}"
            )

            if not pods.items:
                logger.error(f"[DELETE] No pod found for deployment {names['deployment']}")
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            pod_name = pods.items[0].metadata.name
            container_name = "dev-server"

            # Secure path - prevent directory traversal
            safe_path = file_path.replace("..", "").strip("/")
            full_path = f"/app/{safe_path}"

            # Delete file (rm -f won't fail if file doesn't exist)
            delete_cmd = ["/bin/sh", "-c", f"rm -f {shlex.quote(full_path)}"]
            await asyncio.to_thread(
                self._exec_in_pod,
                pod_name,
                namespace,
                container_name,
                delete_cmd,
                timeout=10
            )

            logger.info(f"[DELETE] Successfully deleted {file_path} from pod {pod_name}")
            return True

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[DELETE] Failed to delete file {file_path}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to delete file from pod: {str(e)}") from e

    async def execute_command_in_pod(
        self,
        user_id: UUID,
        project_id: str,
        command: List[str],
        timeout: int = 120
    ) -> str:
        """
        Execute an arbitrary command in a dev container pod.

        Enhanced for agent use with better error handling and security.

        Args:
            user_id: User ID
            project_id: Project ID
            command: Command to execute as list (e.g., ["/bin/sh", "-c", "cd /app && npm install"])
                     If first element is /bin/sh or /bin/bash, uses command as-is (pre-sanitized)
                     Otherwise, wraps in shell with proper working directory
            timeout: Command timeout in seconds

        Returns:
            Command output (stdout + stderr)

        Raises:
            RuntimeError: If pod is not found or command fails
        """
        names = self._generate_resource_names(user_id, project_id)
        namespace = names["namespace"]

        try:
            # Get the pod for this deployment
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}"
            )

            if not pods.items:
                logger.error(f"[EXEC] No pod found for deployment {names['deployment']}")
                raise RuntimeError(
                    f"Development environment not found for user {user_id}, project {project_id}. "
                    f"Please start the development server first."
                )

            pod_name = pods.items[0].metadata.name
            pod_phase = pods.items[0].status.phase
            container_name = "dev-server"

            # Check pod is in running state
            if pod_phase != "Running":
                logger.error(f"[EXEC] Pod {pod_name} is not running (phase: {pod_phase})")
                raise RuntimeError(
                    f"Development environment is not ready (status: {pod_phase}). "
                    f"Please wait for it to start."
                )

            # Check if command is already sanitized (starts with shell)
            if command and command[0] in ["/bin/sh", "/bin/bash"]:
                # Command is already properly formatted (from command_validator)
                full_command = command
                display_command = " ".join(command[-1].split("&&")[-1].strip() if len(command) > 2 else command)
            else:
                # Legacy format - wrap in shell (maintain backward compatibility)
                full_command = ["/bin/sh", "-c", f"cd /app && {' '.join(command)}"]
                display_command = " ".join(command)

            logger.info(f"[EXEC] Running command in pod {pod_name}: {display_command[:100]}")

            try:
                output = await asyncio.to_thread(
                    self._exec_in_pod,
                    pod_name,
                    namespace,
                    container_name,
                    full_command,
                    timeout=timeout
                )

                logger.info(f"[EXEC] Command completed successfully (output length: {len(output)} bytes)")
                return output

            except Exception as exec_error:
                error_msg = str(exec_error)
                logger.error(f"[EXEC] Command execution failed: {error_msg}")

                # Provide more helpful error messages
                if "timeout" in error_msg.lower():
                    raise RuntimeError(
                        f"Command timed out after {timeout} seconds. "
                        f"The command may be taking too long to execute."
                    )
                elif "connection" in error_msg.lower():
                    raise RuntimeError(
                        f"Lost connection to pod. The development environment may have restarted."
                    )
                else:
                    raise RuntimeError(f"Command execution failed: {error_msg}")

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[EXEC] Unexpected error executing command: {e}", exc_info=True)
            raise RuntimeError(
                f"Failed to execute command in pod: {str(e)}. "
                f"Please ensure the development environment is running."
            ) from e

    async def is_pod_ready(
        self,
        user_id: UUID,
        project_id: str,
        check_responsive: bool = True
    ) -> Dict[str, Any]:
        """
        Enhanced pod readiness check with responsiveness testing.

        Args:
            user_id: User ID
            project_id: Project ID
            check_responsive: Whether to test if pod responds to commands

        Returns:
            Dict with keys:
                - ready: bool
                - phase: str (Running, Pending, Failed, etc.)
                - conditions: list of condition types
                - responsive: bool (if check_responsive=True)
                - message: str (human-readable status)
        """
        names = self._generate_resource_names(user_id, project_id)
        namespace = names["namespace"]

        try:
            # Get pods for this deployment
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}"
            )

            if not pods.items:
                return {
                    "ready": False,
                    "phase": "NotFound",
                    "conditions": [],
                    "responsive": False,
                    "message": "No pod found for this project"
                }

            pod = pods.items[0]
            pod_name = pod.metadata.name
            phase = pod.status.phase

            # Check pod conditions
            conditions = []
            is_ready = False
            if pod.status.conditions:
                for condition in pod.status.conditions:
                    conditions.append(condition.type)
                    if condition.type == "Ready" and condition.status == "True":
                        is_ready = True

            # If pod is ready and requested, test responsiveness
            responsive = False
            if is_ready and check_responsive:
                try:
                    # Simple command to test pod responsiveness
                    test_cmd = ["/bin/sh", "-c", "echo ready"]
                    await asyncio.to_thread(
                        self._exec_in_pod,
                        pod_name,
                        namespace,
                        "dev-server",
                        test_cmd,
                        timeout=5
                    )
                    responsive = True
                except Exception as e:
                    logger.warning(f"[READY] Pod {pod_name} ready but not responsive: {e}")
                    responsive = False

            # Determine message
            if phase == "Running" and is_ready and responsive:
                message = "Pod is ready and responsive"
            elif phase == "Running" and is_ready:
                message = "Pod is ready but not yet responsive"
            elif phase == "Running":
                message = "Pod is running but not ready"
            elif phase == "Pending":
                message = "Pod is starting up"
            elif phase == "Failed":
                message = "Pod has failed"
            else:
                message = f"Pod is in {phase} state"

            return {
                "ready": is_ready and (responsive if check_responsive else True),
                "phase": phase,
                "conditions": conditions,
                "responsive": responsive if check_responsive else None,
                "message": message,
                "pod_name": pod_name
            }

        except Exception as e:
            logger.error(f"[READY] Failed to check pod readiness: {e}", exc_info=True)
            return {
                "ready": False,
                "phase": "Error",
                "conditions": [],
                "responsive": False,
                "message": f"Error checking pod: {str(e)}"
            }

    async def list_files_in_pod(
        self,
        user_id: UUID,
        project_id: str,
        directory: str = "."
    ) -> List[Dict[str, Any]]:
        """
        List files in a directory within the dev container pod.

        Args:
            user_id: User ID
            project_id: Project ID
            directory: Directory path relative to project root (default: ".")

        Returns:
            List of dicts with keys: name, type (file/directory), size, path

        Raises:
            RuntimeError: If pod is not found or listing fails
        """
        names = self._generate_resource_names(user_id, project_id)
        namespace = names["namespace"]

        try:
            # Get the pod for this deployment
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}"
            )

            if not pods.items:
                logger.error(f"[LIST] No pod found for deployment {names['deployment']}")
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            pod_name = pods.items[0].metadata.name
            container_name = "dev-server"

            # Secure path - prevent directory traversal
            safe_dir = directory.replace("..", "").strip("/")
            if not safe_dir or safe_dir == ".":
                full_path = "/app"
            else:
                full_path = f"/app/{safe_dir}"

            # List files with details using ls -lA and parse output
            # -l: long format, -A: all except . and .., -1: one per line
            list_cmd = [
                "/bin/sh", "-c",
                f"cd {shlex.quote(full_path)} && find . -maxdepth 1 -mindepth 1 -printf '%y %s %p\\n' | sort"
            ]

            output = await asyncio.to_thread(
                self._exec_in_pod,
                pod_name,
                namespace,
                container_name,
                list_cmd,
                timeout=30
            )

            # Parse output
            files = []
            for line in output.strip().split('\n'):
                if not line:
                    continue

                parts = line.split(' ', 2)
                if len(parts) < 3:
                    continue

                file_type = "directory" if parts[0] == 'd' else "file"
                size = int(parts[1]) if parts[1].isdigit() else 0
                name = parts[2].lstrip('./')

                # Skip hidden files and node_modules
                if name.startswith('.') or name == 'node_modules':
                    continue

                files.append({
                    "name": name,
                    "type": file_type,
                    "size": size,
                    "path": f"{safe_dir}/{name}" if safe_dir != "." else name
                })

            logger.info(f"[LIST] Found {len(files)} files in {directory}")
            return files

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[LIST] Failed to list files in {directory}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to list files in pod: {str(e)}") from e

    async def glob_files_in_pod(
        self,
        user_id: UUID,
        project_id: str,
        pattern: str,
        directory: str = "."
    ) -> List[Dict[str, Any]]:
        """
        Find files matching a glob pattern in the dev container pod.

        Args:
            user_id: User ID
            project_id: Project ID
            pattern: Glob pattern (e.g., "**/*.tsx")
            directory: Directory to search (default: ".")

        Returns:
            List of matching file paths with metadata
        """
        names = self._generate_resource_names(user_id, project_id)
        namespace = names["namespace"]

        try:
            # Get the pod
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}"
            )

            if not pods.items:
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            pod_name = pods.items[0].metadata.name
            container_name = "dev-server"

            # Secure path
            safe_dir = directory.replace("..", "").strip("/")
            if not safe_dir or safe_dir == ".":
                full_path = "/app"
            else:
                full_path = f"/app/{safe_dir}"

            # Use find with glob pattern
            # Convert glob pattern to find-compatible format
            glob_cmd = [
                "/bin/sh", "-c",
                f"cd {shlex.quote(full_path)} && find . -type f -name {shlex.quote(pattern)} -printf '%s %T@ %p\\n' | sort -rn -k2"
            ]

            output = await asyncio.to_thread(
                self._exec_in_pod,
                pod_name,
                namespace,
                container_name,
                glob_cmd,
                timeout=30
            )

            # Parse output
            matches = []
            for line in output.strip().split('\n'):
                if not line:
                    continue

                parts = line.split(' ', 2)
                if len(parts) < 3:
                    continue

                size = int(parts[0]) if parts[0].isdigit() else 0
                modified = float(parts[1]) if parts[1].replace('.', '').isdigit() else 0
                path = parts[2].lstrip('./')

                matches.append({
                    "path": path,
                    "size": size,
                    "modified": modified
                })

            logger.info(f"[GLOB] Found {len(matches)} files matching '{pattern}'")
            return matches

        except Exception as e:
            logger.error(f"[GLOB] Failed to glob files: {e}", exc_info=True)
            return []

    async def grep_in_pod(
        self,
        user_id: UUID,
        project_id: str,
        pattern: str,
        directory: str = ".",
        file_pattern: str = "*",
        case_sensitive: bool = True,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search file contents for a pattern in the dev container pod.

        Args:
            user_id: User ID
            project_id: Project ID
            pattern: Regex pattern to search for
            directory: Directory to search
            file_pattern: File glob pattern to filter
            case_sensitive: Case sensitive search
            max_results: Maximum results to return

        Returns:
            List of matches with file, line number, and content
        """
        names = self._generate_resource_names(user_id, project_id)
        namespace = names["namespace"]

        try:
            # Get the pod
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}"
            )

            if not pods.items:
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            pod_name = pods.items[0].metadata.name
            container_name = "dev-server"

            # Secure path
            safe_dir = directory.replace("..", "").strip("/")
            if not safe_dir or safe_dir == ".":
                full_path = "/app"
            else:
                full_path = f"/app/{safe_dir}"

            # Build grep command
            case_flag = "" if case_sensitive else "-i"
            grep_cmd = [
                "/bin/sh", "-c",
                f"cd {shlex.quote(full_path)} && grep -rn {case_flag} {shlex.quote(pattern)} --include={shlex.quote(file_pattern)} . 2>/dev/null | head -n {max_results}"
            ]

            output = await asyncio.to_thread(
                self._exec_in_pod,
                pod_name,
                namespace,
                container_name,
                grep_cmd,
                timeout=30
            )

            # Parse output (format: ./path/to/file:line_num:content)
            matches = []
            for line in output.strip().split('\n'):
                if not line:
                    continue

                # Split on first two colons
                parts = line.split(':', 2)
                if len(parts) < 3:
                    continue

                file_path = parts[0].lstrip('./')
                line_num = parts[1]
                content = parts[2]

                if line_num.isdigit():
                    matches.append({
                        "file": file_path,
                        "line": int(line_num),
                        "content": content
                    })

            logger.info(f"[GREP] Found {len(matches)} matches for '{pattern}'")
            return matches

        except Exception as e:
            logger.error(f"[GREP] Failed to grep files: {e}", exc_info=True)
            return []

    def track_activity(self, user_id: UUID, project_id: str) -> None:
        """
        Track activity for a development environment.

        This is a compatibility method for the Docker-based implementation.
        In Kubernetes mode, we don't need to track activity for cleanup purposes
        as resources are managed declaratively.

        Args:
            user_id: User ID
            project_id: Project ID
        """
        # No-op in Kubernetes mode - resources are managed declaratively
        logger.debug(f"[TRACK] Activity tracked for user {user_id}, project {project_id}")


# Global instance - lazily initialized
_k8s_manager_instance = None

def get_k8s_manager() -> KubernetesManager:
    """Get or create the global Kubernetes manager instance (lazy initialization)."""
    global _k8s_manager_instance
    if _k8s_manager_instance is None:
        _k8s_manager_instance = KubernetesManager()
    return _k8s_manager_instance