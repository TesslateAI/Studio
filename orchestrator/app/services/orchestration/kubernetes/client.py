"""
Kubernetes Client for Managing Development Environments

This module provides a production-ready interface to the Kubernetes API
for creating, managing, and cleaning up user development environments.

Refactored from: orchestrator/app/k8s_client.py
"""

import asyncio
import logging
import os
import shlex
from typing import Any
from uuid import UUID

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream

logger = logging.getLogger(__name__)


class KubernetesClient:
    """
    Manages Kubernetes resources for user development environments.

    This class provides methods to create, delete, and manage Kubernetes
    resources (Deployments, Services, Ingresses) for isolated user dev environments.
    """

    def __init__(self):
        """Initialize Kubernetes client with in-cluster or kubeconfig."""
        from ....config import get_settings

        self.settings = get_settings()

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
        self.batch_v1 = client.BatchV1Api()
        self.core_v1 = client.CoreV1Api()
        self.networking_v1 = client.NetworkingV1Api()
        self.storage_v1 = client.StorageV1Api()

        # Use centralized config for namespaces
        self.namespace = os.getenv("KUBERNETES_NAMESPACE", self.settings.k8s_default_namespace)
        self.user_namespace = self.settings.k8s_user_environments_namespace

        logger.info(
            f"Kubernetes client initialized - Main namespace: {self.namespace}, User environments: {self.user_namespace}"
        )

    # =========================================================================
    # NAMESPACE MANAGEMENT
    # =========================================================================

    async def _wait_for_namespace_active(self, namespace: str, max_wait: int = 60) -> None:
        """
        Wait for a namespace to be active (not Terminating).

        If the namespace is Terminating, waits for it to be fully deleted,
        then recreates it. This is a defense-in-depth helper called when K8s
        rejects resource creation with 403 "namespace is being terminated".

        Args:
            namespace: Namespace name
            max_wait: Maximum seconds to wait
        """
        wait_interval = 2
        for attempt in range(max_wait // wait_interval):
            try:
                ns = await asyncio.to_thread(self.core_v1.read_namespace, name=namespace)
                if ns.status and ns.status.phase == "Terminating":
                    logger.info(
                        f"[K8S] Namespace {namespace} still terminating, waiting... "
                        f"(attempt {attempt + 1})"
                    )
                    await asyncio.sleep(wait_interval)
                    continue
                # Namespace exists and is Active
                return
            except ApiException as e:
                if e.status == 404:
                    # Namespace fully deleted — caller will need to recreate it
                    return
                raise
        raise RuntimeError(f"Namespace {namespace} stuck in Terminating state after {max_wait}s")

    @staticmethod
    def _is_namespace_terminating_error(e: ApiException) -> bool:
        """Check if an ApiException is a 403 due to namespace being terminated."""
        if e.status != 403:
            return False
        try:
            import json

            body = json.loads(e.body) if isinstance(e.body, str) else e.body
            causes = body.get("details", {}).get("causes", [])
            return any(c.get("reason") == "NamespaceTerminating" for c in causes)
        except Exception:
            return "being terminated" in str(e.body)

    async def create_namespace_if_not_exists(
        self, namespace: str, project_id: str, user_id: UUID
    ) -> None:
        """
        Create a Kubernetes namespace if it doesn't exist.

        If namespace is in Terminating state, waits for it to finish (non-blocking).

        Args:
            namespace: Namespace name
            project_id: Project ID (for labels)
            user_id: User ID (for labels)
        """
        max_wait_seconds = 60
        wait_interval = 2

        for attempt in range(max_wait_seconds // wait_interval):
            try:
                ns = await asyncio.to_thread(self.core_v1.read_namespace, name=namespace)
                # Check if namespace is terminating
                if ns.status and ns.status.phase == "Terminating":
                    logger.info(
                        f"[K8S] Namespace {namespace} is terminating, waiting... (attempt {attempt + 1})"
                    )
                    await asyncio.sleep(wait_interval)
                    continue
                # Namespace exists and is active
                logger.debug(f"[K8S] Namespace {namespace} already exists")
                return
            except ApiException as e:
                if e.status == 404:
                    # Namespace doesn't exist, create it
                    namespace_manifest = client.V1Namespace(
                        metadata=client.V1ObjectMeta(
                            name=namespace,
                            labels={
                                "app": "tesslate",
                                "managed-by": "tesslate-backend",
                                "project-id": project_id,
                                "user-id": str(user_id),
                            },
                        )
                    )
                    await asyncio.to_thread(self.core_v1.create_namespace, body=namespace_manifest)
                    logger.info(f"[K8S] ✅ Created namespace: {namespace}")
                    return
                else:
                    raise

        # If we get here, namespace was stuck terminating for too long
        raise RuntimeError(
            f"Namespace {namespace} stuck in Terminating state after {max_wait_seconds}s"
        )

    async def namespace_exists(self, namespace: str) -> bool:
        """
        Check if a Kubernetes namespace exists and is usable.

        Returns False for namespaces in "Terminating" state, since K8s rejects
        new resource creation in terminating namespaces (403 Forbidden).
        Callers that get False will call ensure_project_environment() →
        create_namespace_if_not_exists(), which waits for termination to
        complete before recreating.

        Args:
            namespace: Namespace name to check

        Returns:
            True if namespace exists and is Active, False otherwise
        """
        try:
            ns = await asyncio.to_thread(self.core_v1.read_namespace, name=namespace)
            if ns.status and ns.status.phase == "Terminating":
                logger.info(
                    f"[K8S] Namespace {namespace} exists but is Terminating — treating as non-existent"
                )
                return False
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    async def apply_network_policy(
        self, network_policy: client.V1NetworkPolicy, namespace: str
    ) -> None:
        """
        Apply a NetworkPolicy manifest (create or update).

        Args:
            network_policy: NetworkPolicy manifest
            namespace: Namespace to apply to
        """
        if not self.settings.k8s_enable_network_policies:
            logger.debug("[K8S] NetworkPolicy creation disabled, skipping")
            return

        policy_name = network_policy.metadata.name

        try:
            await asyncio.to_thread(
                self.networking_v1.create_namespaced_network_policy,
                namespace=namespace,
                body=network_policy,
            )
            logger.info(f"[K8S] ✅ Created NetworkPolicy: {policy_name}")
        except ApiException as e:
            if e.status == 409:
                logger.debug(f"[K8S] NetworkPolicy {policy_name} exists, updating...")
                await asyncio.to_thread(
                    self.networking_v1.patch_namespaced_network_policy,
                    name=policy_name,
                    namespace=namespace,
                    body=network_policy,
                )
                logger.info(f"[K8S] ✅ Updated NetworkPolicy: {policy_name}")
            else:
                raise

    async def copy_wildcard_tls_secret(
        self, target_namespace: str, source_namespace: str = None, secret_name: str = None
    ) -> bool:
        """
        Copy wildcard TLS secret from source namespace to target namespace.

        This is required for HTTPS ingress in project namespaces - the wildcard
        certificate needs to be available in each project namespace for TLS termination.

        Args:
            target_namespace: Namespace to copy the secret to
            source_namespace: Namespace to copy from (defaults to tesslate)
            secret_name: Name of the secret (defaults to k8s_wildcard_tls_secret)

        Returns:
            True if copied successfully, False if secret doesn't exist in source
        """
        if source_namespace is None:
            source_namespace = self.settings.k8s_default_namespace
        if secret_name is None:
            secret_name = self.settings.k8s_wildcard_tls_secret

        # Skip if no TLS secret configured (e.g., local dev without TLS)
        if not secret_name:
            logger.debug("[K8S] No wildcard TLS secret configured, skipping copy")
            return False

        # Check if secret already exists in target namespace
        try:
            await asyncio.to_thread(
                self.core_v1.read_namespaced_secret, name=secret_name, namespace=target_namespace
            )
            logger.debug(f"[K8S] TLS secret {secret_name} already exists in {target_namespace}")
            return True
        except ApiException as e:
            if e.status != 404:
                raise

        # Read secret from source namespace
        try:
            source_secret = await asyncio.to_thread(
                self.core_v1.read_namespaced_secret, name=secret_name, namespace=source_namespace
            )
        except ApiException as e:
            if e.status == 404:
                logger.warning(
                    f"[K8S] Wildcard TLS secret {secret_name} not found in {source_namespace}"
                )
                return False
            raise

        # Create new secret in target namespace (copy data, new metadata)
        # TLS secrets have type kubernetes.io/tls
        new_secret = client.V1Secret(
            metadata=client.V1ObjectMeta(
                name=secret_name,
                namespace=target_namespace,
                labels={
                    "app": "tesslate",
                    "managed-by": "tesslate-backend",
                    "copied-from": source_namespace,
                },
            ),
            type=source_secret.type,
            data=source_secret.data,
        )

        await asyncio.to_thread(
            self.core_v1.create_namespaced_secret, namespace=target_namespace, body=new_secret
        )
        logger.info(f"[K8S] ✅ Copied wildcard TLS secret to {target_namespace}")
        return True

    def get_project_namespace(self, project_id: str) -> str:
        """
        Get the namespace name for a project.

        Args:
            project_id: Project ID (UUID as string)

        Returns:
            Namespace name (e.g., "proj-123e4567-e89b-12d3-a456-426614174000")
        """
        if self.settings.k8s_namespace_per_project:
            return f"proj-{project_id}"
        else:
            return self.user_namespace

    # =========================================================================
    # RESOURCE NAMING
    # =========================================================================

    def generate_resource_names(
        self, user_id: UUID, project_id: str, project_slug: str = None, container_name: str = None
    ) -> dict[str, str]:
        """
        Generate consistent resource names for a user's project/container.

        Kubernetes naming constraints:
        - Labels: max 63 chars, alphanumeric + '-' + '_' + '.'
        - Names: max 253 chars, DNS-1123 compliant (lowercase alphanumeric + '-')

        Returns:
            Dictionary with namespace, deployment, service, ingress, hostname, and safe_container_name
        """
        namespace = self.get_project_namespace(project_id)

        # Use shortened UUIDs to keep names under 63 chars
        user_short = str(user_id)[:8]
        project_short = str(project_id)[:8]

        # Generate safe container name
        if container_name:
            safe_container = container_name.lower()
            safe_container = safe_container.replace("_", "-").replace(" ", "-").replace(".", "-")
            safe_container = "".join(c for c in safe_container if c.isalnum() or c == "-")
            while "--" in safe_container:
                safe_container = safe_container.replace("--", "-")
            safe_container = safe_container.strip("-")
            # 63 max - 22 prefix (dev- + 8 + - + 8 + -) - 4 suffix (-svc/-ing)
            max_container_len = 63 - 22 - 4
            safe_container = safe_container[:max_container_len]
            base_name = f"dev-{user_short}-{project_short}-{safe_container}"
        else:
            base_name = f"dev-{user_short}-{project_short}"
            safe_container = base_name

        # Hostname uses project slug for clean URLs
        if not project_slug:
            project_slug = f"{user_short}-{project_short}"

        if container_name:
            hostname = f"{project_slug}-{safe_container}.{self.settings.app_domain}"
        else:
            hostname = f"{project_slug}.{self.settings.app_domain}"

        return {
            "namespace": namespace,
            "deployment": base_name,
            "service": f"{base_name}-svc",
            "ingress": f"{base_name}-ing",
            "hostname": hostname,
            "safe_container_name": safe_container,
        }

    # =========================================================================
    # DEPLOYMENT LIFECYCLE
    # =========================================================================

    async def create_deployment(self, deployment: client.V1Deployment, namespace: str) -> None:
        """Create or update a Deployment."""
        deployment_name = deployment.metadata.name
        try:
            await asyncio.to_thread(
                self.apps_v1.create_namespaced_deployment, namespace=namespace, body=deployment
            )
            logger.info(f"[K8S] ✅ Created deployment: {deployment_name}")
        except ApiException as e:
            if e.status == 409:
                logger.info(f"[K8S] Deployment {deployment_name} exists, updating...")
                await asyncio.to_thread(
                    self.apps_v1.patch_namespaced_deployment,
                    name=deployment_name,
                    namespace=namespace,
                    body=deployment,
                )
                logger.info(f"[K8S] ✅ Updated deployment: {deployment_name}")
            elif self._is_namespace_terminating_error(e):
                logger.warning(
                    f"[K8S] Namespace {namespace} is terminating during deployment creation, waiting..."
                )
                await self._wait_for_namespace_active(namespace)
                # Retry once after namespace is active
                await asyncio.to_thread(
                    self.apps_v1.create_namespaced_deployment, namespace=namespace, body=deployment
                )
                logger.info(
                    f"[K8S] ✅ Created deployment (after namespace wait): {deployment_name}"
                )
            else:
                raise

    async def delete_deployment(self, name: str, namespace: str) -> None:
        """Delete a Deployment."""
        try:
            await asyncio.to_thread(
                self.apps_v1.delete_namespaced_deployment, name=name, namespace=namespace
            )
            logger.info(f"[K8S] Deleted deployment: {name}")
        except ApiException as e:
            if e.status != 404:
                raise

    async def scale_deployment(self, user_id: UUID, project_id: str, replicas: int) -> None:
        """Scale a deployment to a specific number of replicas."""
        names = self.generate_resource_names(user_id, project_id)
        namespace = names["namespace"]

        try:
            deployment = await asyncio.to_thread(
                self.apps_v1.read_namespaced_deployment,
                name=names["deployment"],
                namespace=namespace,
            )

            deployment.spec.replicas = replicas

            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_deployment,
                name=names["deployment"],
                namespace=namespace,
                body=deployment,
            )

            action = "paused" if replicas == 0 else "resumed"
            logger.info(f"[K8S] Deployment {names['deployment']} {action} (replicas: {replicas})")

        except ApiException as e:
            if e.status != 404:
                logger.error(f"[K8S] Failed to scale deployment {names['deployment']}: {e}")
                raise RuntimeError(f"Failed to scale deployment: {e.reason}") from e

    # =========================================================================
    # SERVICE MANAGEMENT
    # =========================================================================

    async def create_service(self, service: client.V1Service, namespace: str) -> None:
        """Create or update a Service."""
        service_name = service.metadata.name
        try:
            await asyncio.to_thread(
                self.core_v1.create_namespaced_service, namespace=namespace, body=service
            )
            logger.info(f"[K8S] ✅ Created service: {service_name}")
        except ApiException as e:
            if e.status == 409:
                logger.info(f"[K8S] Service {service_name} exists, updating...")
                await asyncio.to_thread(
                    self.core_v1.patch_namespaced_service,
                    name=service_name,
                    namespace=namespace,
                    body=service,
                )
                logger.info(f"[K8S] ✅ Updated service: {service_name}")
            elif self._is_namespace_terminating_error(e):
                logger.warning(
                    f"[K8S] Namespace {namespace} is terminating during service creation, waiting..."
                )
                await self._wait_for_namespace_active(namespace)
                await asyncio.to_thread(
                    self.core_v1.create_namespaced_service, namespace=namespace, body=service
                )
                logger.info(f"[K8S] ✅ Created service (after namespace wait): {service_name}")
            else:
                raise

    async def delete_service(self, name: str, namespace: str) -> None:
        """Delete a Service."""
        try:
            await asyncio.to_thread(
                self.core_v1.delete_namespaced_service, name=name, namespace=namespace
            )
            logger.info(f"[K8S] Deleted service: {name}")
        except ApiException as e:
            if e.status != 404:
                raise

    # =========================================================================
    # INGRESS MANAGEMENT
    # =========================================================================

    async def create_ingress(self, ingress: client.V1Ingress, namespace: str) -> None:
        """Create or update an Ingress."""
        ingress_name = ingress.metadata.name
        try:
            await asyncio.to_thread(
                self.networking_v1.create_namespaced_ingress, namespace=namespace, body=ingress
            )
            logger.info(f"[K8S] ✅ Created ingress: {ingress_name}")
        except ApiException as e:
            if e.status == 409:
                logger.info(f"[K8S] Ingress {ingress_name} exists, updating...")
                await asyncio.to_thread(
                    self.networking_v1.patch_namespaced_ingress,
                    name=ingress_name,
                    namespace=namespace,
                    body=ingress,
                )
                logger.info(f"[K8S] ✅ Updated ingress: {ingress_name}")
            elif self._is_namespace_terminating_error(e):
                logger.warning(
                    f"[K8S] Namespace {namespace} is terminating during ingress creation, waiting..."
                )
                await self._wait_for_namespace_active(namespace)
                await asyncio.to_thread(
                    self.networking_v1.create_namespaced_ingress, namespace=namespace, body=ingress
                )
                logger.info(f"[K8S] ✅ Created ingress (after namespace wait): {ingress_name}")
            else:
                raise

    async def delete_ingress(self, name: str, namespace: str) -> None:
        """Delete an Ingress."""
        try:
            await asyncio.to_thread(
                self.networking_v1.delete_namespaced_ingress, name=name, namespace=namespace
            )
            logger.info(f"[K8S] Deleted ingress: {name}")
        except ApiException as e:
            if e.status != 404:
                raise

    # =========================================================================
    # PVC MANAGEMENT
    # =========================================================================

    async def create_pvc(self, pvc: client.V1PersistentVolumeClaim, namespace: str) -> None:
        """Create a PVC if it doesn't exist (PVCs are immutable)."""
        pvc_name = pvc.metadata.name
        try:
            await asyncio.to_thread(
                self.core_v1.create_namespaced_persistent_volume_claim,
                namespace=namespace,
                body=pvc,
            )
            logger.info(f"[K8S] ✅ Created PVC: {pvc_name}")
        except ApiException as e:
            if e.status == 409:
                logger.info(f"[K8S] PVC {pvc_name} already exists, skipping")
            elif self._is_namespace_terminating_error(e):
                logger.warning(
                    f"[K8S] Namespace {namespace} is terminating during PVC creation, waiting..."
                )
                await self._wait_for_namespace_active(namespace)
                await asyncio.to_thread(
                    self.core_v1.create_namespaced_persistent_volume_claim,
                    namespace=namespace,
                    body=pvc,
                )
                logger.info(f"[K8S] ✅ Created PVC (after namespace wait): {pvc_name}")
            else:
                raise

    async def delete_pvc(self, name: str, namespace: str) -> None:
        """Delete a PVC."""
        try:
            await asyncio.to_thread(
                self.core_v1.delete_namespaced_persistent_volume_claim,
                name=name,
                namespace=namespace,
            )
            logger.info(f"[K8S] Deleted PVC: {name}")
        except ApiException as e:
            if e.status != 404:
                raise

    # =========================================================================
    # POD OPERATIONS
    # =========================================================================

    def _get_stream_client(self) -> client.CoreV1Api:
        """
        Create a fresh CoreV1Api client for stream operations.

        IMPORTANT: The kubernetes-python `stream()` function temporarily patches
        the api_client.request method to use WebSocket. If we use the shared
        self.core_v1 client, concurrent regular API calls (like read_namespace)
        will accidentally use the WebSocket-patched method, causing errors like:
        "WebSocketBadStatusException: Handshake status 200 OK"

        By creating a fresh client for each stream operation, we isolate the
        WebSocket patching and prevent it from affecting other concurrent calls.
        """
        return client.CoreV1Api()

    def _exec_in_pod(
        self,
        pod_name: str,
        namespace: str,
        container_name: str,
        command: list[str],
        timeout: int = 30,
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
        """
        try:
            logger.debug(f"[K8S:EXEC] Executing in pod {pod_name}: {' '.join(command[:3])}...")

            # Use a fresh client for stream operations to avoid concurrency issues
            # The stream() function patches api_client.request to use WebSocket,
            # which would break concurrent regular API calls if using shared client
            stream_client = self._get_stream_client()

            resp = stream(
                stream_client.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                container=container_name,
                command=command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=True,
                _request_timeout=timeout,
            )

            logger.debug("[K8S:EXEC] Command completed successfully")
            return resp

        except Exception as e:
            logger.error(f"[K8S:EXEC] Command failed in pod {pod_name}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to execute command in pod: {str(e)}") from e

    def _copy_from_pod(
        self,
        pod_name: str,
        namespace: str,
        container_name: str,
        pod_path: str,
        local_path: str,
        timeout: int = 120,
    ) -> bool:
        """
        Copy a file from a pod to local filesystem using tar stream.

        This is a secure alternative to putting AWS credentials in pods.
        The file is streamed directly to the backend without using kubectl CLI.

        Args:
            pod_name: Name of the pod
            namespace: Namespace
            container_name: Container name within pod
            pod_path: Path to file in the pod (e.g., /tmp/project.zip)
            local_path: Local destination path
            timeout: Command timeout in seconds

        Returns:
            True if successful
        """
        import base64

        try:
            logger.info(f"[K8S:COPY] Copying from pod: {pod_path} -> {local_path}")

            stream_client = self._get_stream_client()

            # Use base64 encoding to safely transfer binary data over WebSocket
            # This avoids all encoding issues with the kubernetes stream API
            command = ["sh", "-c", f"base64 < {pod_path}"]

            resp = stream(
                stream_client.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                container=container_name,
                command=command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
                _preload_content=False,
                _request_timeout=timeout,
            )

            # Read base64-encoded data (safe ASCII text)
            base64_data = ""
            while resp.is_open():
                resp.update(timeout=timeout)
                if resp.peek_stdout():
                    chunk = resp.read_stdout()
                    if chunk:
                        base64_data += chunk
                if resp.peek_stderr():
                    stderr = resp.read_stderr()
                    if stderr:
                        logger.debug(f"[K8S:COPY] stderr: {stderr}")
            resp.close()

            if not base64_data:
                raise RuntimeError(f"No data received from pod for {pod_path}")

            # Decode base64 and write to file
            local_dir = os.path.dirname(local_path)
            os.makedirs(local_dir, exist_ok=True)

            # Remove any whitespace from base64 data
            base64_data = base64_data.replace("\n", "").replace("\r", "").strip()
            file_data = base64.b64decode(base64_data)

            with open(local_path, "wb") as f:
                f.write(file_data)

            logger.info(
                f"[K8S:COPY] ✅ Copied from pod: {pod_path} ({os.path.getsize(local_path)} bytes)"
            )
            return True

        except Exception as e:
            logger.error(f"[K8S:COPY] Failed to copy from pod: {e}", exc_info=True)
            raise RuntimeError(f"Failed to copy file from pod: {str(e)}") from e

    def _write_bytes_to_pod(
        self,
        pod_name: str,
        namespace: str,
        container_name: str,
        data: bytes,
        pod_path: str,
        timeout: int = 120,
    ) -> bool:
        """
        Write raw bytes to a file in a pod using tar stream via stdin.

        Handles binary data of any size without hitting command argument limits
        (ARG_MAX). Uses the same tar streaming approach as _copy_to_pod but
        accepts in-memory bytes instead of a local file path.
        """
        import io
        import tarfile

        try:
            logger.info(f"[K8S:WRITE] Writing {len(data)} bytes to pod: {pod_path}")

            stream_client = self._get_stream_client()

            # Create tar archive in memory containing the file data
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                info = tarfile.TarInfo(name=os.path.basename(pod_path))
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            tar_stream.seek(0)
            tar_data = tar_stream.read()

            # Ensure directory exists
            pod_dir = os.path.dirname(pod_path)
            self._exec_in_pod(
                pod_name,
                namespace,
                container_name,
                ["mkdir", "-p", pod_dir],
                timeout=10,
            )

            # Stream tar data to pod via stdin
            command = ["tar", "xf", "-", "-C", pod_dir]

            resp = stream(
                stream_client.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                container=container_name,
                command=command,
                stderr=True,
                stdin=True,
                stdout=True,
                tty=False,
                _preload_content=False,
                _request_timeout=timeout,
            )

            resp.write_stdin(tar_data)
            resp.close()

            logger.info(f"[K8S:WRITE] ✅ Wrote to pod: {pod_path} ({len(data)} bytes)")
            return True

        except Exception as e:
            logger.error(f"[K8S:WRITE] Failed to write to pod: {e}", exc_info=True)
            raise RuntimeError(f"Failed to write bytes to pod: {str(e)}") from e

    def _copy_to_pod(
        self,
        pod_name: str,
        namespace: str,
        container_name: str,
        local_path: str,
        pod_path: str,
        timeout: int = 120,
    ) -> bool:
        """
        Copy a file from local filesystem to a pod using tar stream.

        This is a secure alternative to putting AWS credentials in pods.
        The file is streamed directly from the backend without using kubectl CLI.

        Args:
            pod_name: Name of the pod
            namespace: Namespace
            container_name: Container name within pod
            local_path: Local source file path
            pod_path: Destination path in the pod
            timeout: Command timeout in seconds

        Returns:
            True if successful
        """
        import io
        import tarfile

        try:
            logger.info(f"[K8S:COPY] Copying to pod: {local_path} -> {pod_path}")

            if not os.path.exists(local_path):
                raise RuntimeError(f"Local file does not exist: {local_path}")

            stream_client = self._get_stream_client()

            # Create tar archive in memory
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                tar.add(local_path, arcname=os.path.basename(pod_path))
            tar_stream.seek(0)
            tar_data = tar_stream.read()

            # Use tar to extract file in pod
            pod_dir = os.path.dirname(pod_path)
            command = ["tar", "xf", "-", "-C", pod_dir]

            resp = stream(
                stream_client.connect_get_namespaced_pod_exec,
                pod_name,
                namespace,
                container=container_name,
                command=command,
                stderr=True,
                stdin=True,
                stdout=True,
                tty=False,
                _preload_content=False,
                _request_timeout=timeout,
            )

            # Send tar data to stdin
            resp.write_stdin(tar_data)
            resp.close()

            logger.info(f"[K8S:COPY] ✅ Copied to pod: {pod_path} ({len(tar_data)} bytes)")
            return True

        except Exception as e:
            logger.error(f"[K8S:COPY] Failed to copy to pod: {e}", exc_info=True)
            raise RuntimeError(f"Failed to copy file to pod: {str(e)}") from e

    async def copy_file_from_pod(
        self,
        pod_name: str,
        namespace: str,
        container_name: str,
        pod_path: str,
        local_path: str,
        timeout: int = 120,
    ) -> bool:
        """Async wrapper for _copy_from_pod."""
        return await asyncio.to_thread(
            self._copy_from_pod, pod_name, namespace, container_name, pod_path, local_path, timeout
        )

    async def copy_file_to_pod(
        self,
        pod_name: str,
        namespace: str,
        container_name: str,
        local_path: str,
        pod_path: str,
        timeout: int = 120,
    ) -> bool:
        """Async wrapper for _copy_to_pod."""
        return await asyncio.to_thread(
            self._copy_to_pod, pod_name, namespace, container_name, local_path, pod_path, timeout
        )

    async def get_pod_for_deployment(
        self, deployment_name: str, namespace: str, use_prefix_match: bool = False
    ) -> str | None:
        """Get a ready pod name for a deployment.

        Args:
            deployment_name: Deployment name or prefix if use_prefix_match=True
            namespace: Kubernetes namespace
            use_prefix_match: If True, match any pod whose app label starts with deployment_name
        """
        try:
            if use_prefix_match:
                # Get all pods in namespace and filter by prefix
                pods = await asyncio.to_thread(
                    self.core_v1.list_namespaced_pod, namespace=namespace
                )
                # Filter by app label prefix
                matching_pods = []
                for pod in pods.items:
                    app_label = pod.metadata.labels.get("app", "") if pod.metadata.labels else ""
                    if app_label.startswith(deployment_name):
                        matching_pods.append(pod)
                pods.items = matching_pods
            else:
                pods = await asyncio.to_thread(
                    self.core_v1.list_namespaced_pod,
                    namespace=namespace,
                    label_selector=f"app={deployment_name}",
                )

            for pod in pods.items:
                if pod.status.phase == "Running" and pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        if cs.ready:
                            return pod.metadata.name
            return None

        except Exception as e:
            logger.error(f"[K8S] Error getting pod for deployment: {e}")
            return None

    def is_pod_ready(self, pod: client.V1Pod) -> bool:
        """Check if a pod is ready."""
        if not pod.status.conditions:
            return False

        for condition in pod.status.conditions:
            if condition.type == "Ready":
                return condition.status == "True"
        return False

    async def get_file_manager_pod(self, namespace: str) -> str | None:
        """
        Get the file-manager pod name in a namespace.

        The file-manager pod is the always-running pod that handles
        file operations when no dev containers are running.

        Args:
            namespace: Namespace to search

        Returns:
            Pod name if found, None otherwise
        """
        try:
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector="app=file-manager",
            )

            for pod in pods.items:
                if pod.status.phase == "Running" and pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        if cs.ready:
                            return pod.metadata.name

            logger.debug(f"[K8S] No ready file-manager pod found in {namespace}")
            return None

        except ApiException as e:
            if e.status == 404:
                return None
            logger.error(f"[K8S] Error getting file-manager pod: {e}")
            return None
        except Exception as e:
            logger.error(f"[K8S] Error getting file-manager pod: {e}")
            return None

    async def wait_for_deployment_ready(
        self, deployment_name: str, namespace: str, timeout: int = 120
    ) -> None:
        """Wait for a deployment to be ready."""
        for _ in range(timeout):
            try:
                deployment = await asyncio.to_thread(
                    self.apps_v1.read_namespaced_deployment,
                    name=deployment_name,
                    namespace=namespace,
                )

                if (
                    deployment.status.ready_replicas
                    and deployment.status.ready_replicas == deployment.status.replicas
                ):
                    logger.info(f"[K8S] Deployment {deployment_name} is ready")
                    return

            except ApiException as e:
                if e.status != 404:
                    logger.warning(f"[K8S] Error checking deployment status: {e}")

            await asyncio.sleep(1)

        raise RuntimeError(
            f"Deployment {deployment_name} did not become ready within {timeout} seconds"
        )

    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================

    @staticmethod
    def _safe_pod_path(file_path: str, subdir: str | None = None) -> str:
        """
        Validate file_path stays within /app/ inside the pod.

        Uses PurePosixPath + os.path.normpath to normalize and contain.
        No filesystem access needed — this runs on the orchestrator, not in the pod.

        Raises ValueError if the path would escape /app/.
        """
        from pathlib import PurePosixPath

        base = PurePosixPath("/app")
        if subdir:
            base = base / subdir

        # Join and normalize (collapses ..)
        normalized = PurePosixPath(os.path.normpath(str(base / file_path)))

        # Containment: must still be under /app
        try:
            normalized.relative_to(PurePosixPath("/app"))
        except ValueError as err:
            raise ValueError(
                f"Path escapes container boundary: {file_path!r} (resolved to {normalized})"
            ) from err

        return str(normalized)

    async def read_file_from_pod(
        self,
        user_id: UUID,
        project_id: str,
        file_path: str,
        container_name: str | None = None,
        project_slug: str | None = None,
        subdir: str | None = None,
    ) -> str | None:
        """Read a file from a dev container pod."""
        names = self.generate_resource_names(user_id, project_id, project_slug, container_name)
        namespace = names["namespace"]

        try:
            # Use prefix match if no specific container, to find any pod for this project
            use_prefix = container_name is None
            pod_name = await self.get_pod_for_deployment(
                names["deployment"], namespace, use_prefix_match=use_prefix
            )
            if not pod_name:
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            k8s_container = "dev-server"
            full_path = self._safe_pod_path(file_path, subdir)

            # Check if file exists
            check_cmd = [
                "/bin/sh",
                "-c",
                f"test -f {shlex.quote(full_path)} && echo exists || echo notfound",
            ]
            result = await asyncio.to_thread(
                self._exec_in_pod, pod_name, namespace, k8s_container, check_cmd, timeout=10
            )

            if "notfound" in result:
                return None

            # Read file content
            read_cmd = ["/bin/sh", "-c", f"cat {shlex.quote(full_path)}"]
            content = await asyncio.to_thread(
                self._exec_in_pod, pod_name, namespace, k8s_container, read_cmd, timeout=30
            )

            logger.info(f"[K8S] Read {file_path} ({len(content)} bytes)")
            return content

        except ValueError as e:
            logger.warning(f"[K8S] Path traversal blocked in read_file_from_pod: {e}")
            return None
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[K8S] Failed to read file {file_path}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to read file from pod: {str(e)}") from e

    async def write_file_to_pod(
        self,
        user_id: UUID,
        project_id: str,
        file_path: str,
        content: str,
        container_name: str | None = None,
        project_slug: str | None = None,
        subdir: str | None = None,
    ) -> bool:
        """Write a file to a dev container pod."""
        names = self.generate_resource_names(user_id, project_id, project_slug, container_name)
        namespace = names["namespace"]

        try:
            # Use prefix match if no specific container, to find any pod for this project
            use_prefix = container_name is None
            pod_name = await self.get_pod_for_deployment(
                names["deployment"], namespace, use_prefix_match=use_prefix
            )
            if not pod_name:
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            k8s_container = "dev-server"
            full_path = self._safe_pod_path(file_path, subdir)

            # Use tar streaming to write file (heredoc/echo breaks for files >100KB)
            data = content.encode("utf-8")
            await asyncio.to_thread(
                self._write_bytes_to_pod,
                pod_name,
                namespace,
                k8s_container,
                data,
                full_path,
                timeout=60,
            )

            logger.info(f"[K8S] Wrote {file_path} ({len(content)} bytes)")
            return True

        except ValueError as e:
            logger.warning(f"[K8S] Path traversal blocked in write_file_to_pod: {e}")
            return False
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[K8S] Failed to write file {file_path}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to write file to pod: {str(e)}") from e

    async def delete_file_from_pod(
        self,
        user_id: UUID,
        project_id: str,
        file_path: str,
        container_name: str | None = None,
        project_slug: str | None = None,
    ) -> bool:
        """Delete a file from a dev container pod."""
        names = self.generate_resource_names(user_id, project_id, project_slug, container_name)
        namespace = names["namespace"]

        try:
            # Use prefix match if no specific container, to find any pod for this project
            use_prefix = container_name is None
            pod_name = await self.get_pod_for_deployment(
                names["deployment"], namespace, use_prefix_match=use_prefix
            )
            if not pod_name:
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            k8s_container = "dev-server"
            full_path = self._safe_pod_path(file_path)

            delete_cmd = ["/bin/sh", "-c", f"rm -f {shlex.quote(full_path)}"]
            await asyncio.to_thread(
                self._exec_in_pod, pod_name, namespace, k8s_container, delete_cmd, timeout=10
            )

            logger.info(f"[K8S] Deleted {file_path}")
            return True

        except ValueError as e:
            logger.warning(f"[K8S] Path traversal blocked in delete_file_from_pod: {e}")
            return False
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[K8S] Failed to delete file {file_path}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to delete file from pod: {str(e)}") from e

    async def list_files_in_pod(
        self,
        user_id: UUID,
        project_id: str,
        directory: str = ".",
        container_name: str | None = None,
        project_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        """List files in a directory within a dev container pod."""
        names = self.generate_resource_names(user_id, project_id, project_slug, container_name)
        namespace = names["namespace"]

        try:
            # Use prefix match if no specific container, to find any pod for this project
            use_prefix = container_name is None
            pod_name = await self.get_pod_for_deployment(
                names["deployment"], namespace, use_prefix_match=use_prefix
            )
            if not pod_name:
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            k8s_container = "dev-server"
            full_path = self._safe_pod_path(directory if directory and directory != "." else ".")

            # Use ls -la instead of find -printf (BusyBox find doesn't support -printf)
            list_cmd = ["/bin/sh", "-c", f"cd {shlex.quote(full_path)} && ls -la"]

            output = await asyncio.to_thread(
                self._exec_in_pod, pod_name, namespace, k8s_container, list_cmd, timeout=30
            )

            files = []
            for line in output.strip().split("\n"):
                if not line:
                    continue

                # Parse ls -la output: drwxr-xr-x 2 user group 4096 Dec 10 12:00 filename
                parts = line.split()
                if len(parts) < 9:
                    continue

                # Skip total line and . / .. entries
                name = parts[-1]
                if name in (".", "..", "total") or line.startswith("total"):
                    continue

                perms = parts[0]
                file_type = "directory" if perms.startswith("d") else "file"
                size = int(parts[4]) if parts[4].isdigit() else 0

                # Skip hidden files and node_modules
                if name.startswith(".") or name in ("node_modules", "lost+found"):
                    continue

                files.append(
                    {
                        "name": name,
                        "type": file_type,
                        "size": size,
                        "path": f"{full_path.removeprefix('/app/')}/{name}"
                        if full_path != "/app"
                        else name,
                    }
                )

            logger.info(f"[K8S] Found {len(files)} files in {directory}")
            return files

        except ValueError as e:
            logger.warning(f"[K8S] Path traversal blocked in list_files_in_pod: {e}")
            return []
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[K8S] Failed to list files in {directory}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to list files in pod: {str(e)}") from e

    async def glob_files_in_pod(
        self,
        user_id: UUID,
        project_id: str,
        pattern: str,
        directory: str = ".",
        container_name: str | None = None,
        project_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find files matching a glob pattern in a dev container pod."""
        names = self.generate_resource_names(user_id, project_id, project_slug, container_name)
        namespace = names["namespace"]

        try:
            pod_name = await self.get_pod_for_deployment(names["deployment"], namespace)
            if not pod_name:
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            k8s_container = "dev-server"
            full_path = self._safe_pod_path(directory if directory and directory != "." else ".")

            # Use find with -exec stat for BusyBox compatibility (no -printf support)
            glob_cmd = [
                "/bin/sh",
                "-c",
                f"cd {shlex.quote(full_path)} && find . -type f -name {shlex.quote(pattern)} 2>/dev/null",
            ]

            output = await asyncio.to_thread(
                self._exec_in_pod, pod_name, namespace, k8s_container, glob_cmd, timeout=30
            )

            matches = []
            for line in output.strip().split("\n"):
                if not line:
                    continue

                path = line.lstrip("./")
                if not path:
                    continue

                # Default values since we can't easily get size/mtime with BusyBox
                size = 0
                modified = 0

                matches.append({"path": path, "size": size, "modified": modified})

            logger.info(f"[K8S] Found {len(matches)} files matching '{pattern}'")
            return matches

        except ValueError as e:
            logger.warning(f"[K8S] Path traversal blocked in glob_files_in_pod: {e}")
            return []
        except Exception as e:
            logger.error(f"[K8S] Failed to glob files: {e}", exc_info=True)
            return []

    async def grep_in_pod(
        self,
        user_id: UUID,
        project_id: str,
        pattern: str,
        directory: str = ".",
        file_pattern: str = "*",
        case_sensitive: bool = True,
        max_results: int = 100,
        container_name: str | None = None,
        project_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search file contents for a pattern in a dev container pod."""
        names = self.generate_resource_names(user_id, project_id, project_slug, container_name)
        namespace = names["namespace"]

        try:
            pod_name = await self.get_pod_for_deployment(names["deployment"], namespace)
            if not pod_name:
                raise RuntimeError(f"No pod found for user {user_id}, project {project_id}")

            k8s_container = "dev-server"
            full_path = self._safe_pod_path(directory if directory and directory != "." else ".")

            case_flag = "" if case_sensitive else "-i"
            grep_cmd = [
                "/bin/sh",
                "-c",
                f"cd {shlex.quote(full_path)} && grep -rn {case_flag} {shlex.quote(pattern)} --include={shlex.quote(file_pattern)} . 2>/dev/null | head -n {max_results}",
            ]

            output = await asyncio.to_thread(
                self._exec_in_pod, pod_name, namespace, k8s_container, grep_cmd, timeout=30
            )

            matches = []
            for line in output.strip().split("\n"):
                if not line:
                    continue

                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue

                file_path = parts[0].lstrip("./")
                line_num = parts[1]
                content = parts[2]

                if line_num.isdigit():
                    matches.append({"file": file_path, "line": int(line_num), "content": content})

            logger.info(f"[K8S] Found {len(matches)} matches for '{pattern}'")
            return matches

        except ValueError as e:
            logger.warning(f"[K8S] Path traversal blocked in grep_in_pod: {e}")
            return []
        except Exception as e:
            logger.error(f"[K8S] Failed to grep files: {e}", exc_info=True)
            return []

    async def execute_command_in_pod(
        self,
        user_id: UUID,
        project_id: str,
        command: list[str],
        timeout: int = 120,
        container_name: str | None = None,
        project_slug: str | None = None,
    ) -> str:
        """Execute a command in a dev container pod."""
        names = self.generate_resource_names(user_id, project_id, project_slug, container_name)
        namespace = names["namespace"]

        try:
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}",
            )

            if not pods.items:
                raise RuntimeError(
                    f"Development environment not found for user {user_id}, project {project_id}. "
                    f"Please start the development server first."
                )

            pod_name = pods.items[0].metadata.name
            pod_phase = pods.items[0].status.phase
            k8s_container = "dev-server"

            if pod_phase != "Running":
                raise RuntimeError(
                    f"Development environment is not ready (status: {pod_phase}). "
                    f"Please wait for it to start."
                )

            # Handle command format
            if command and command[0] in ["/bin/sh", "/bin/bash"]:
                full_command = command
            else:
                full_command = ["/bin/sh", "-c", f"cd /app && {shlex.join(command)}"]

            logger.info(f"[K8S] Running command in pod {pod_name}")

            try:
                output = await asyncio.to_thread(
                    self._exec_in_pod,
                    pod_name,
                    namespace,
                    k8s_container,
                    full_command,
                    timeout=timeout,
                )

                logger.info(f"[K8S] Command completed ({len(output)} bytes)")
                return output

            except Exception as exec_error:
                error_msg = str(exec_error)
                logger.error(f"[K8S] Command execution failed: {error_msg}")

                if "timeout" in error_msg.lower():
                    raise RuntimeError(
                        f"Command timed out after {timeout} seconds."
                    ) from exec_error
                elif "connection" in error_msg.lower():
                    raise RuntimeError(
                        "Lost connection to pod. The development environment may have restarted."
                    ) from exec_error
                else:
                    raise RuntimeError(f"Command execution failed: {error_msg}") from exec_error

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"[K8S] Unexpected error executing command: {e}", exc_info=True)
            raise RuntimeError(
                f"Failed to execute command in pod: {str(e)}. "
                f"Please ensure the development environment is running."
            ) from e

    async def check_pod_ready(
        self,
        user_id: UUID,
        project_id: str,
        check_responsive: bool = True,
        container_name: str | None = None,
        project_slug: str | None = None,
    ) -> dict[str, Any]:
        """Enhanced pod readiness check with responsiveness testing."""
        names = self.generate_resource_names(user_id, project_id, project_slug, container_name)
        namespace = names["namespace"]

        try:
            # If no specific container_name, find ANY pod in the project namespace
            # This handles multi-container projects where we don't care which container
            if container_name:
                label_selector = f"app={names['deployment']}"
            else:
                # Match any pod with the user-project prefix (e.g., dev-976599df-7745b013-*)
                user_short = str(user_id)[:8]
                project_short = str(project_id)[:8]
                # List all pods in namespace and filter by app label prefix
                label_selector = None  # Will filter manually

            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod, namespace=namespace, label_selector=label_selector
            )

            # If no specific container, filter pods by prefix
            if not container_name and pods.items:
                user_short = str(user_id)[:8]
                project_short = str(project_id)[:8]
                prefix = f"dev-{user_short}-{project_short}"
                filtered_pods = []
                for pod in pods.items:
                    app_label = pod.metadata.labels.get("app", "")
                    if app_label.startswith(prefix):
                        filtered_pods.append(pod)
                pods.items = filtered_pods

            if not pods.items:
                return {
                    "ready": False,
                    "phase": "NotFound",
                    "conditions": [],
                    "responsive": False,
                    "message": "No pod found for this project",
                }

            pod = pods.items[0]
            pod_name = pod.metadata.name
            phase = pod.status.phase

            conditions = []
            is_ready = False
            if pod.status.conditions:
                for condition in pod.status.conditions:
                    conditions.append(condition.type)
                    if condition.type == "Ready" and condition.status == "True":
                        is_ready = True

            responsive = False
            if is_ready and check_responsive:
                try:
                    test_cmd = ["/bin/sh", "-c", "echo ready"]
                    await asyncio.to_thread(
                        self._exec_in_pod, pod_name, namespace, "dev-server", test_cmd, timeout=5
                    )
                    responsive = True
                except Exception as e:
                    logger.warning(f"[K8S] Pod {pod_name} ready but not responsive: {e}")

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
                "pod_name": pod_name,
            }

        except Exception as e:
            logger.error(f"[K8S] Failed to check pod readiness: {e}", exc_info=True)
            return {
                "ready": False,
                "phase": "Error",
                "conditions": [],
                "responsive": False,
                "message": f"Error checking pod: {str(e)}",
            }

    # =========================================================================
    # ENVIRONMENT MANAGEMENT
    # =========================================================================

    async def get_dev_environment_status(
        self,
        user_id: UUID,
        project_id: str,
        container_name: str | None = None,
        project_slug: str | None = None,
    ) -> dict[str, Any]:
        """Get the status of a development environment."""
        names = self.generate_resource_names(user_id, project_id, project_slug, container_name)
        namespace = names["namespace"]

        try:
            deployment = await asyncio.to_thread(
                self.apps_v1.read_namespaced_deployment,
                name=names["deployment"],
                namespace=namespace,
            )

            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={names['deployment']}",
            )

            deployment_status = deployment.status
            pod_statuses = []

            for pod in pods.items:
                pod_statuses.append(
                    {
                        "name": pod.metadata.name,
                        "phase": pod.status.phase,
                        "ready": self.is_pod_ready(pod),
                    }
                )

            return {
                "hostname": names["hostname"],
                "url": f"{self.settings.k8s_container_url_protocol}://{names['hostname']}",
                "deployment_ready": deployment_status.ready_replicas == deployment_status.replicas,
                "replicas": {
                    "desired": deployment_status.replicas,
                    "ready": deployment_status.ready_replicas or 0,
                    "available": deployment_status.available_replicas or 0,
                },
                "pods": pod_statuses,
                "status": "ready"
                if deployment_status.ready_replicas == deployment_status.replicas
                else "pending",
            }

        except ApiException as e:
            if e.status == 404:
                return {"status": "not_found", "hostname": names["hostname"]}
            logger.error(f"[K8S] Error getting dev environment status: {e}")
            return {"status": "error", "error": str(e), "hostname": names["hostname"]}

    async def check_dev_environment_health(self, user_id: UUID, project_id: str) -> dict[str, Any]:
        """Check if a development environment exists and is healthy."""
        status = await self.get_dev_environment_status(user_id, project_id)

        if status["status"] == "not_found":
            return {
                "exists": False,
                "ready": False,
                "url": None,
                "message": "Development environment does not exist",
            }

        if status["status"] == "error":
            return {
                "exists": False,
                "ready": False,
                "url": None,
                "message": f"Error checking environment: {status.get('error', 'Unknown error')}",
            }

        is_ready = status.get("deployment_ready", False)
        return {
            "exists": True,
            "ready": is_ready,
            "url": status["url"] if is_ready else None,
            "message": "Environment is ready" if is_ready else "Environment is starting up",
            "replicas": status.get("replicas"),
            "pods": status.get("pods"),
        }

    async def list_dev_environments(self, user_id: UUID | None = None) -> list:
        """List all development environments, optionally filtered by user."""
        try:
            label_selector = "app=dev-environment"
            if user_id:
                label_selector += f",user-id={str(user_id)}"

            deployments = await asyncio.to_thread(
                self.apps_v1.list_namespaced_deployment,
                namespace=self.user_namespace,
                label_selector=label_selector,
            )

            environments = []
            for deployment in deployments.items:
                labels = deployment.metadata.labels
                env_user_id = labels.get("user-id")
                project_id = labels.get("project-id")

                if env_user_id and project_id:
                    status = await self.get_dev_environment_status(env_user_id, project_id)
                    environments.append(
                        {
                            "user_id": env_user_id,
                            "project_id": project_id,
                            "deployment_name": deployment.metadata.name,
                            **status,
                        }
                    )

            return environments

        except ApiException as e:
            logger.error(f"[K8S] Error listing dev environments: {e}")
            return []

    def track_activity(self, user_id: UUID, project_id: str) -> None:
        """Track activity for a development environment (no-op in K8s mode)."""
        logger.debug(f"[K8S] Activity tracked for user {user_id}, project {project_id}")

    # =========================================================================
    # JOB MANAGEMENT
    # =========================================================================

    async def create_job(self, namespace: str, job: client.V1Job) -> client.V1Job | None:
        """Create a Job in the given namespace."""
        job_name = job.metadata.name if job.metadata else "unknown"
        try:
            result = await asyncio.to_thread(
                self.batch_v1.create_namespaced_job,
                namespace=namespace,
                body=job,
            )
            logger.info(f"[K8S] Created Job: {job_name} in {namespace}")
            return result
        except ApiException as e:
            if e.status == 409:
                logger.info(f"[K8S] Job {job_name} already exists in {namespace}")
                return None
            raise

    async def get_job_status(self, name: str, namespace: str) -> str:
        """Get job status. Returns 'running', 'succeeded', or 'failed'."""
        try:
            job = await asyncio.to_thread(
                self.batch_v1.read_namespaced_job,
                name=name,
                namespace=namespace,
            )
            if job.status.succeeded and job.status.succeeded > 0:
                return "succeeded"
            if job.status.failed and job.status.failed > 0:
                return "failed"
            return "running"
        except ApiException as e:
            if e.status == 404:
                return "failed"
            raise

    async def delete_job(self, name: str, namespace: str) -> None:
        """Delete a Job and its dependent pods."""
        try:
            await asyncio.to_thread(
                self.batch_v1.delete_namespaced_job,
                name=name,
                namespace=namespace,
                body=client.V1DeleteOptions(propagation_policy="Background"),
            )
            logger.info(f"[K8S] Deleted Job: {name} in {namespace}")
        except ApiException as e:
            if e.status != 404:
                raise

    # =========================================================================
    # STORAGE CLASS MANAGEMENT
    # =========================================================================

    async def create_storage_class(
        self, name: str, provisioner: str, parameters: dict
    ) -> client.V1StorageClass | None:
        """Create a StorageClass with the given provisioner and parameters."""
        sc = client.V1StorageClass(
            api_version="storage.k8s.io/v1",
            kind="StorageClass",
            metadata=client.V1ObjectMeta(name=name),
            provisioner=provisioner,
            parameters=parameters,
            reclaim_policy="Delete",
            volume_binding_mode="Immediate",
        )
        try:
            result = await asyncio.to_thread(
                self.storage_v1.create_storage_class,
                body=sc,
            )
            logger.info(f"[K8S] Created StorageClass: {name}")
            return result
        except ApiException as e:
            if e.status == 409:
                logger.info(f"[K8S] StorageClass {name} already exists")
                return None
            raise

    async def delete_storage_class(self, name: str) -> None:
        """Delete a StorageClass."""
        try:
            await asyncio.to_thread(
                self.storage_v1.delete_storage_class,
                name=name,
            )
            logger.info(f"[K8S] Deleted StorageClass: {name}")
        except ApiException as e:
            if e.status != 404:
                raise

    async def storage_class_exists(self, name: str) -> bool:
        """Check if a StorageClass exists."""
        try:
            await asyncio.to_thread(
                self.storage_v1.read_storage_class,
                name=name,
            )
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise


# Global instance - lazily initialized
_k8s_client_instance: KubernetesClient | None = None


def get_k8s_client() -> KubernetesClient:
    """Get or create the global Kubernetes client instance."""
    global _k8s_client_instance
    if _k8s_client_instance is None:
        _k8s_client_instance = KubernetesClient()
    return _k8s_client_instance
