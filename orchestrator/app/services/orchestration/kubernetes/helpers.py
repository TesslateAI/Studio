"""
Kubernetes Helpers for VolumeSnapshot Architecture

This module contains helper methods for the Kubernetes architecture that separates:
- File lifecycle (populate files when container added to graph)
- Container lifecycle (start/stop dev servers)
- Snapshot lifecycle (hibernation/restoration via EBS VolumeSnapshots)

Key components:
- File Manager Pod: Always-running pod for file operations
- Dev Container Deployment: Simple deployment with no init containers
- VolumeSnapshots: Near-instant hibernation/restoration (handled by snapshot_manager.py)
"""

import logging
from uuid import UUID

from kubernetes import client

from ...apps.env_resolver import resolve_env_for_pod

logger = logging.getLogger(__name__)

# Kubernetes DNS-1123 name limit
_K8S_NAME_MAX = 63


def _k8s_name(prefix: str, directory: str) -> str:
    """Build a K8s resource name like 'dev-{directory}', truncated to 63 chars."""
    name = f"{prefix}{directory}"
    if len(name) > _K8S_NAME_MAX:
        name = name[:_K8S_NAME_MAX].rstrip("-")
    return name


# =============================================================================
# Labels and Affinity
# =============================================================================


def create_pod_affinity_spec(
    project_id: str, topology_key: str = "kubernetes.io/hostname"
) -> client.V1Affinity:
    """
    Create pod affinity configuration for multi-container projects.

    Pod affinity ensures all containers in a project run on the same node.
    This is REQUIRED for sharing RWO (ReadWriteOnce) block storage.

    Args:
        project_id: Project UUID (for label matching)
        topology_key: Key for topology (default: hostname = same node)

    Returns:
        V1Affinity spec for deployment
    """
    return client.V1Affinity(
        pod_affinity=client.V1PodAffinity(
            required_during_scheduling_ignored_during_execution=[
                client.V1PodAffinityTerm(
                    label_selector=client.V1LabelSelector(
                        match_labels={"tesslate.io/project-id": str(project_id)}
                    ),
                    topology_key=topology_key,
                )
            ]
        )
    )


def get_standard_labels(
    project_id: str,
    user_id: str,
    component: str,
    container_id: str = None,
    container_directory: str = None,
) -> dict[str, str]:
    """
    Get standard labels for project resources.

    Args:
        project_id: Project UUID
        user_id: User UUID
        component: Component name (file-manager, dev-container)
        container_id: Optional container UUID
        container_directory: Optional container directory name

    Returns:
        Dict of labels
    """
    labels = {
        "app.kubernetes.io/managed-by": "tesslate-backend",
        "tesslate.io/project-id": str(project_id),
        "tesslate.io/user-id": str(user_id),
        "tesslate.io/component": component,
    }

    if container_id:
        labels["tesslate.io/container-id"] = str(container_id)

    if container_directory:
        labels["tesslate.io/container-directory"] = container_directory

    return labels


# =============================================================================
# PVC Manifest
# =============================================================================


def create_pvc_manifest(
    namespace: str,
    project_id: UUID,
    user_id: UUID,
    storage_class: str,
    size: str = "5Gi",
    access_mode: str = "ReadWriteOnce",
) -> client.V1PersistentVolumeClaim:
    """
    Create PVC manifest for project storage.

    Each project gets one PVC that is shared by:
    - file-manager pod
    - all dev container pods

    Args:
        namespace: Kubernetes namespace
        project_id: Project UUID
        user_id: User UUID
        storage_class: StorageClass to use
        size: Storage size (default: 5Gi)
        access_mode: Access mode (default: ReadWriteOnce)

    Returns:
        V1PersistentVolumeClaim manifest
    """
    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name="project-storage",
            namespace=namespace,
            labels=get_standard_labels(
                project_id=str(project_id), user_id=str(user_id), component="storage"
            ),
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            storage_class_name=storage_class,
            access_modes=[access_mode],
            resources=client.V1ResourceRequirements(requests={"storage": size}),
        ),
    )


# =============================================================================
# File Manager Pod
# =============================================================================


def create_file_manager_deployment(
    namespace: str,
    project_id: UUID,
    user_id: UUID,
    image: str,
    image_pull_policy: str = "IfNotPresent",
    image_pull_secret: str = None,
    enable_pod_affinity: bool = True,
    affinity_topology_key: str = "kubernetes.io/hostname",
) -> client.V1Deployment:
    """
    Create file-manager deployment manifest.

    The file-manager pod is always running while a project is open. It:
    - Enables file operations (read/write) for the code editor
    - Executes git clone when containers are added to graph
    - Keeps the PVC mounted so it doesn't become unbound

    NOTE: S3 operations are handled by the backend pod (not here) for security.
    No AWS credentials are exposed to user-accessible namespaces.

    Args:
        namespace: Kubernetes namespace
        project_id: Project UUID
        user_id: User UUID
        image: Container image (tesslate-devserver)
        image_pull_policy: Image pull policy
        image_pull_secret: Optional image pull secret name

    Returns:
        V1Deployment manifest
    """
    labels = get_standard_labels(
        project_id=str(project_id), user_id=str(user_id), component="file-manager"
    )
    labels["app"] = "file-manager"

    # File manager container - just keeps alive
    # NO AWS credentials here - S3 ops handled securely by backend
    container = client.V1Container(
        name="file-manager",
        image=image,
        image_pull_policy=image_pull_policy,
        # tsinit as PID 1 with no managed processes — just a proper init
        # that handles signals and zombie reaping. No working_dir set to avoid
        # CWD holding the PVC mount busy during teardown (umount EBUSY fix).
        command=["tsinit", "serve"],
        volume_mounts=[client.V1VolumeMount(name="project-storage", mount_path="/app")],
        resources=client.V1ResourceRequirements(
            # File-manager needs enough memory for npm install (Next.js needs ~1GB)
            requests={"memory": "256Mi", "cpu": "50m"},
            limits={"memory": "1536Mi", "cpu": "1000m"},
        ),
    )

    # Pod spec
    pod_spec = client.V1PodSpec(
        containers=[container],
        volumes=[
            client.V1Volume(
                name="project-storage",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name="project-storage"
                ),
            )
        ],
        # Security context
        security_context=client.V1PodSecurityContext(
            run_as_non_root=True, run_as_user=1000, fs_group=1000
        ),
    )

    # File-manager is the anchor pod — it schedules freely on any node.
    # Dev containers use pod affinity to co-locate WITH the file-manager.
    # Giving file-manager affinity causes deadlock: both pods wait for each other.

    # Add image pull secret if provided
    if image_pull_secret:
        pod_spec.image_pull_secrets = [client.V1LocalObjectReference(name=image_pull_secret)]

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(name="file-manager", namespace=namespace, labels=labels),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": "file-manager"}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels), spec=pod_spec
            ),
        ),
    )


# =============================================================================
# Dev Container Deployment
# =============================================================================


def create_container_deployment(
    namespace: str,
    project_id: UUID,
    user_id: UUID,
    container_id: UUID,
    container_directory: str,
    image: str,
    port: int,
    startup_command: str,
    working_directory: str = "",
    image_pull_policy: str = "IfNotPresent",
    image_pull_secret: str = None,
    enable_pod_affinity: bool = True,
    affinity_topology_key: str = "kubernetes.io/hostname",
    extra_env: dict[str, str] | None = None,
) -> client.V1Deployment:
    """
    Create dev container deployment manifest.

    This deployment is created when a user STARTS a container.
    Files should already exist on PVC (populated when container was added to graph).
    NO init containers needed - files already exist!

    Args:
        namespace: Kubernetes namespace
        project_id: Project UUID
        user_id: User UUID
        container_id: Container UUID
        container_directory: Container directory name for K8s resource naming (DNS-safe)
        image: Container image
        port: Port the dev server listens on
        startup_command: Command to start the dev server (e.g., "npm run dev")
        working_directory: Actual filesystem path ("." for root, "frontend", etc.).
            Defaults to container_directory if not provided.
        image_pull_policy: Image pull policy
        image_pull_secret: Optional image pull secret
        enable_pod_affinity: Whether to enable pod affinity (for shared PVC)
        affinity_topology_key: Topology key for pod affinity

    Returns:
        V1Deployment manifest
    """
    deployment_name = _k8s_name("dev-", container_directory)

    labels = get_standard_labels(
        project_id=str(project_id),
        user_id=str(user_id),
        component="dev-container",
        container_id=str(container_id),
        container_directory=container_directory,
    )
    labels["app"] = "dev-container"

    # Selector labels (must be subset of pod labels)
    selector_labels = {"tesslate.io/container-id": str(container_id)}

    # Working directory inside container
    # working_directory overrides container_directory for the actual filesystem path
    effective_dir = working_directory or container_directory
    working_dir = "/app" if effective_dir in (".", "") else f"/app/{effective_dir}"

    # Dev server container
    # Use exec to replace shell process - prevents exit when stdin closes
    env_vars = [
        client.V1EnvVar(name="HOST", value="0.0.0.0"),
        client.V1EnvVar(name="PORT", value=str(port)),
        client.V1EnvVar(name="NODE_ENV", value="development"),
    ]

    # Filter out reserved keys, then resolve ${secret:name/key} references
    # to V1EnvVar(valueFrom=secretKeyRef(...)) — never plaintext in pod spec.
    _filtered = {k: v for k, v in (extra_env or {}).items() if k not in {"HOST", "PORT", "NODE_ENV"}}
    env_vars.extend(resolve_env_for_pod(_filtered))

    dev_container = client.V1Container(
        name="dev-server",
        image=image,
        image_pull_policy=image_pull_policy,
        # tsinit as PID 1: proper signal forwarding, process group kill,
        # zombie reaping. Dev server runs as managed process "main".
        # Agent can restart via tsinit API without killing the container.
        # NOTE: Do NOT set working_dir on the container spec. containerd creates
        # the working directory as root before the container process starts, causing
        # EACCES errors for uid 1000. tsinit handles mkdir + cd internally.
        command=["tsinit", "serve"],
        args=[
            "--process",
            f"main=mkdir -p {working_dir} && cd {working_dir} && rm -rf .next/dev/lock && {startup_command}",
            "--dir",
            "/",
            "--grace-period",
            "10s",
            "--restart-policy",
            "never",
            "--sock-path",
            "/tmp/tsinit.sock",
        ],
        ports=[client.V1ContainerPort(container_port=port, name="http")],
        volume_mounts=[client.V1VolumeMount(name="project-storage", mount_path="/app")],
        env=env_vars,
        resources=client.V1ResourceRequirements(
            requests={"memory": "256Mi", "cpu": "50m"}, limits={"memory": "1Gi", "cpu": "1000m"}
        ),
        # Startup probe - tsinit health check (passes fast — checks supervisor, not dev server)
        # Container stays alive even if dev server never starts. Agent can fix it.
        startup_probe=client.V1Probe(
            _exec=client.V1ExecAction(command=["tsinit", "health", "/tmp/tsinit.sock"]),
            initial_delay_seconds=2,
            period_seconds=3,
            timeout_seconds=5,
            failure_threshold=30,
        ),
        # Readiness probe - HTTP GET (controls traffic routing, NOT container lifecycle)
        readiness_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/", port=port),
            initial_delay_seconds=5,
            period_seconds=5,
            timeout_seconds=3,
            failure_threshold=3,
        ),
        # Liveness probe - tsinit alive (keeps container alive regardless of dev server state)
        liveness_probe=client.V1Probe(
            _exec=client.V1ExecAction(command=["tsinit", "health", "/tmp/tsinit.sock"]),
            initial_delay_seconds=10,
            period_seconds=10,
            timeout_seconds=5,
            failure_threshold=3,
        ),
    )

    # Pod spec
    pod_spec = client.V1PodSpec(
        containers=[dev_container],
        volumes=[
            client.V1Volume(
                name="project-storage",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name="project-storage"
                ),
            )
        ],
        security_context=client.V1PodSecurityContext(
            run_as_non_root=True, run_as_user=1000, fs_group=1000
        ),
    )

    # Add pod affinity if enabled (for shared PVC)
    if enable_pod_affinity:
        pod_spec.affinity = create_pod_affinity_spec(
            project_id=str(project_id), topology_key=affinity_topology_key
        )

    # Add image pull secret if provided
    if image_pull_secret:
        pod_spec.image_pull_secrets = [client.V1LocalObjectReference(name=image_pull_secret)]

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(name=deployment_name, namespace=namespace, labels=labels),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels=selector_labels),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={**labels, **selector_labels}), spec=pod_spec
            ),
        ),
    )


# =============================================================================
# Service and Ingress
# =============================================================================


def create_service_manifest(
    namespace: str, project_id: UUID, container_id: UUID, container_directory: str, port: int
) -> client.V1Service:
    """
    Create Service manifest for a dev container.

    Args:
        namespace: Kubernetes namespace
        project_id: Project UUID
        container_id: Container UUID
        container_directory: Container directory name
        port: Port the dev server listens on

    Returns:
        V1Service manifest
    """
    service_name = _k8s_name("dev-", container_directory)

    return client.V1Service(
        metadata=client.V1ObjectMeta(
            name=service_name,
            namespace=namespace,
            labels={
                "tesslate.io/project-id": str(project_id),
                "tesslate.io/container-id": str(container_id),
                "tesslate.io/container-directory": container_directory,
            },
        ),
        spec=client.V1ServiceSpec(
            selector={"tesslate.io/container-id": str(container_id)},
            ports=[client.V1ServicePort(port=port, target_port=port, protocol="TCP")],
            type="ClusterIP",
        ),
    )


def create_ingress_manifest(
    namespace: str,
    project_id: UUID,
    container_id: UUID,
    container_directory: str,
    project_slug: str,
    port: int,
    domain: str,
    ingress_class: str = "nginx",
    tls_secret: str = None,
) -> client.V1Ingress:
    """
    Create Ingress manifest for a dev container.

    Args:
        namespace: Kubernetes namespace
        project_id: Project UUID
        container_id: Container UUID
        container_directory: Container directory name
        project_slug: Project slug (e.g., "my-app-abc123")
        port: Port the dev server listens on
        domain: Base domain (e.g., "localhost" or "your-domain.com")
        ingress_class: Ingress class name
        tls_secret: Optional TLS secret name for HTTPS

    Returns:
        V1Ingress manifest
    """
    ingress_name = _k8s_name("dev-", container_directory)
    # Single subdomain level for wildcard cert compatibility (*.domain)
    host = f"{project_slug}-{container_directory}.{domain}"
    service_name = _k8s_name("dev-", container_directory)

    # Build ingress spec
    ingress_spec = client.V1IngressSpec(
        ingress_class_name=ingress_class,
        rules=[
            client.V1IngressRule(
                host=host,
                http=client.V1HTTPIngressRuleValue(
                    paths=[
                        client.V1HTTPIngressPath(
                            path="/",
                            path_type="Prefix",
                            backend=client.V1IngressBackend(
                                service=client.V1IngressServiceBackend(
                                    name=service_name, port=client.V1ServiceBackendPort(number=port)
                                )
                            ),
                        )
                    ]
                ),
            )
        ],
    )

    # Add TLS if secret provided
    if tls_secret:
        ingress_spec.tls = [client.V1IngressTLS(hosts=[host], secret_name=tls_secret)]

    return client.V1Ingress(
        metadata=client.V1ObjectMeta(
            name=ingress_name,
            namespace=namespace,
            labels={
                "tesslate.io/project-id": str(project_id),
                "tesslate.io/container-id": str(container_id),
                "tesslate.io/container-directory": container_directory,
            },
            annotations={
                # WebSocket support for HMR
                "nginx.ingress.kubernetes.io/proxy-http-version": "1.1",
                "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
                "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600",
            },
        ),
        spec=ingress_spec,
    )


# =============================================================================
# Network Policy
# =============================================================================


def create_network_policy_manifest(namespace: str, project_id: UUID) -> client.V1NetworkPolicy:
    """
    Create NetworkPolicy for project isolation.

    Allows:
    - Ingress from ingress-nginx namespace
    - Ingress from tesslate namespace (for file operations)
    - Egress to DNS (UDP 53)
    - Egress to HTTPS (TCP 443) for npm/git
    - Egress to MinIO (minio-system namespace)

    Args:
        namespace: Kubernetes namespace
        project_id: Project UUID

    Returns:
        V1NetworkPolicy manifest
    """
    return client.V1NetworkPolicy(
        metadata=client.V1ObjectMeta(
            name="project-isolation",
            namespace=namespace,
            labels={"tesslate.io/project-id": str(project_id)},
        ),
        spec=client.V1NetworkPolicySpec(
            pod_selector=client.V1LabelSelector(),  # Select all pods
            policy_types=["Ingress", "Egress"],
            ingress=[
                # Allow from ingress controller
                client.V1NetworkPolicyIngressRule(
                    _from=[
                        client.V1NetworkPolicyPeer(
                            namespace_selector=client.V1LabelSelector(
                                match_labels={"kubernetes.io/metadata.name": "ingress-nginx"}
                            )
                        )
                    ]
                ),
                # Allow from tesslate backend (for file operations)
                client.V1NetworkPolicyIngressRule(
                    _from=[
                        client.V1NetworkPolicyPeer(
                            namespace_selector=client.V1LabelSelector(
                                match_labels={"kubernetes.io/metadata.name": "tesslate"}
                            )
                        )
                    ]
                ),
                # Allow from same namespace (inter-container communication)
                # This enables NextJS -> Postgres, Frontend -> Backend, etc.
                client.V1NetworkPolicyIngressRule(
                    _from=[
                        client.V1NetworkPolicyPeer(
                            pod_selector=client.V1LabelSelector()  # Empty = all pods in same namespace
                        )
                    ]
                ),
            ],
            egress=[
                # Allow DNS
                client.V1NetworkPolicyEgressRule(
                    to=[client.V1NetworkPolicyPeer(namespace_selector=client.V1LabelSelector())],
                    ports=[client.V1NetworkPolicyPort(protocol="UDP", port=53)],
                ),
                # Allow HTTPS (npm, git)
                client.V1NetworkPolicyEgressRule(
                    to=[client.V1NetworkPolicyPeer(ip_block=client.V1IPBlock(cidr="0.0.0.0/0"))],
                    ports=[client.V1NetworkPolicyPort(protocol="TCP", port=443)],
                ),
                # Allow HTTP (some registries)
                client.V1NetworkPolicyEgressRule(
                    to=[client.V1NetworkPolicyPeer(ip_block=client.V1IPBlock(cidr="0.0.0.0/0"))],
                    ports=[client.V1NetworkPolicyPort(protocol="TCP", port=80)],
                ),
                # Allow MinIO
                client.V1NetworkPolicyEgressRule(
                    to=[
                        client.V1NetworkPolicyPeer(
                            namespace_selector=client.V1LabelSelector(
                                match_labels={"kubernetes.io/metadata.name": "minio-system"}
                            )
                        )
                    ]
                ),
            ],
        ),
    )


# =============================================================================
# Git Clone Script (for container initialization)
# =============================================================================


def generate_git_clone_script(
    git_url: str, branch: str, target_dir: str, install_deps: bool = True
) -> str:
    """
    Generate script to clone a git repository and optionally install dependencies.

    This script is executed via kubectl exec into the file-manager pod
    when a container is added to the architecture graph.

    Args:
        git_url: Git repository URL
        branch: Branch to clone
        target_dir: Target directory (e.g., "/app/frontend")
        install_deps: Whether to run npm install after clone

    Returns:
        Shell script as string
    """
    install_section = (
        """
# Install dependencies based on project type
# Detect bun (bun.lock or bun.lockb), pnpm (pnpm-lock.yaml), or npm (package.json)
if [ -f "bun.lock" ] || [ -f "bun.lockb" ]; then
    echo "[CLONE] Installing Node.js dependencies with bun..."
    bun install --frozen-lockfile 2>&1 || echo "[CLONE] bun install completed with warnings"
elif [ -f "pnpm-lock.yaml" ]; then
    echo "[CLONE] Installing Node.js dependencies with pnpm..."
    pnpm install --frozen-lockfile 2>&1 || echo "[CLONE] pnpm install completed with warnings"
elif [ -f "package.json" ]; then
    echo "[CLONE] Installing Node.js dependencies with npm..."
    npm install --prefer-offline --no-audit 2>&1 || echo "[CLONE] npm install completed with warnings"
fi

if [ -f "requirements.txt" ]; then
    echo "[CLONE] Installing Python dependencies..."
    pip install -r requirements.txt 2>&1 || echo "[CLONE] pip install completed with warnings"
fi

if [ -f "go.mod" ]; then
    echo "[CLONE] Downloading Go modules..."
    go mod download 2>&1 || echo "[CLONE] go mod download completed with warnings"
fi
"""
        if install_deps
        else ""
    )

    # Sanitize URL for logging (hide tokens)
    import re as _re

    safe_log_url = _re.sub(r"https://[^@]+@", "https://***@", git_url)

    return f'''#!/bin/sh
set -e

TARGET_DIR="{target_dir}"

echo "[CLONE] ======================================"
echo "[CLONE] Cloning repository"
echo "[CLONE] URL: {safe_log_url}"
echo "[CLONE] Branch: {branch}"
echo "[CLONE] Target: $TARGET_DIR"
echo "[CLONE] ======================================"

# Clear target directory contents (target may be a mount point that cannot be removed)
rm -rf "$TARGET_DIR"/* "$TARGET_DIR"/.[!.]* 2>/dev/null || true

# Clone to a temporary directory first
TEMP_CLONE="/tmp/git-clone-$$"
rm -rf "$TEMP_CLONE"
echo "[CLONE] Running git clone..."
# Skip LFS smudge during clone - large LFS objects (e.g., pre-baked node_modules
# binaries) are not needed because npm install runs at container start anyway.
# This also prevents clone failures when the repo's LFS budget is exceeded.
GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 --branch {branch} --single-branch {git_url} "$TEMP_CLONE"

# Verify clone succeeded
if [ ! -f "$TEMP_CLONE/package.json" ] && [ ! -f "$TEMP_CLONE/requirements.txt" ] && [ ! -f "$TEMP_CLONE/go.mod" ]; then
    echo "[CLONE] ERROR: Clone failed - no package.json, requirements.txt, or go.mod found"
    ls -la "$TEMP_CLONE/" 2>/dev/null || echo "[CLONE] Temp directory is empty or doesn't exist"
    exit 1
fi

echo "[CLONE] Clone successful"

echo "[CLONE] Copying files..."

# Remove .git folder to save space
rm -rf "$TEMP_CLONE/.git"

# Use cp -a with trailing dot to copy ALL files including hidden ones reliably
# This works better than mv with glob patterns in BusyBox
cp -a "$TEMP_CLONE"/. "$TARGET_DIR"/

# Fix ownership: change files to node:node for dev container compatibility
# File-manager runs as root, but dev containers run as node user
chown -R node:node "$TARGET_DIR" 2>/dev/null || echo "[CLONE] Warning: could not chown to node:node"

# Fix execute permissions for node_modules binaries (Git on Windows doesn't preserve them)
# This is needed for pre-baked node_modules to work correctly
if [ -d "$TARGET_DIR/node_modules" ]; then
    echo "[CLONE] Fixing execute permissions on node_modules binaries..."
    find "$TARGET_DIR/node_modules" -path "*/bin/*" -type f -exec chmod +x {{}} \\; 2>/dev/null || true
    find "$TARGET_DIR/node_modules" -name "*.sh" -type f -exec chmod +x {{}} \\; 2>/dev/null || true
fi

# Cleanup temp directory
rm -rf "$TEMP_CLONE"

# Verify files were copied
if [ ! -f "$TARGET_DIR/package.json" ] && [ ! -f "$TARGET_DIR/requirements.txt" ] && [ ! -f "$TARGET_DIR/go.mod" ]; then
    echo "[CLONE] ERROR: Copy failed - target directory is empty"
    ls -la "$TARGET_DIR/" 2>/dev/null || true
    exit 1
fi

echo "[CLONE] Files copied successfully"

# Move to target directory for dependency install
cd "$TARGET_DIR"
{install_section}
echo "[CLONE] ======================================"
echo "[CLONE] ✅ Clone complete"
echo "[CLONE] Files:"
ls -la "$TARGET_DIR/" | head -20
echo "[CLONE] ======================================"
'''


# =============================================================================
# Service Container Deployment (PostgreSQL, Redis, MongoDB, etc.)
# =============================================================================


def create_service_container_deployment(
    namespace: str,
    project_id: UUID,
    user_id: UUID,
    container_id: UUID,
    container_directory: str,
    image: str,
    port: int,
    environment_vars: dict[str, str],
    volumes: list[str],
    command: list[str] | None = None,
    health_check: dict | None = None,
    enable_pod_affinity: bool = True,
    affinity_topology_key: str = "kubernetes.io/hostname",
) -> client.V1Deployment:
    """
    Create a Deployment for a service container (database, cache, queue, etc.).

    Unlike dev containers, service containers:
    - Use their own Docker image (e.g., postgres:16-alpine)
    - Have their own PVC for data persistence
    - Don't need file-manager or git clone
    - Don't need tsinit or dev-server wrappers
    - Don't need ingress (internal services only)

    Args:
        namespace: Kubernetes namespace
        project_id: Project UUID
        user_id: User UUID
        container_id: Container UUID
        container_directory: Sanitized container name (used for resource naming)
        image: Docker image (e.g., "postgres:16-alpine")
        port: Service port (e.g., 5432 for postgres)
        environment_vars: Environment variables for the service
        volumes: Volume mount paths (e.g., ["/var/lib/postgresql/data"])
        command: Optional command override
        health_check: Optional health check config (Docker format)
        enable_pod_affinity: Whether to enable pod affinity
        affinity_topology_key: Topology key for pod affinity

    Returns:
        V1Deployment manifest
    """
    deployment_name = _k8s_name("svc-", container_directory)

    labels = get_standard_labels(
        project_id=str(project_id),
        user_id=str(user_id),
        component="service-container",
        container_id=str(container_id),
        container_directory=container_directory,
    )
    labels["app"] = _k8s_name("svc-", container_directory)

    selector_labels = {"tesslate.io/container-id": str(container_id)}

    # Build environment variables
    env_vars = resolve_env_for_pod(environment_vars)

    # Build volume mounts and volumes
    # Each volume path gets its own mount backed by the same PVC.
    # Currently all services define a single volume, but this handles multiple.
    volume_mounts = []
    volume_specs = []
    pvc_name = _k8s_name("svc-", f"{container_directory}-data")

    for idx, vol_path in enumerate(volumes):
        vol_name = "service-data" if idx == 0 else f"service-data-{idx}"
        volume_mounts.append(client.V1VolumeMount(name=vol_name, mount_path=vol_path))
        volume_specs.append(
            client.V1Volume(
                name=vol_name,
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=pvc_name
                ),
            )
        )

    # Build container spec
    container_spec = client.V1Container(
        name="service",
        image=image,
        env=env_vars,
        ports=[client.V1ContainerPort(container_port=port, name="service")],
        volume_mounts=volume_mounts if volume_mounts else None,
        resources=client.V1ResourceRequirements(
            requests={"memory": "256Mi", "cpu": "50m"},
            limits={"memory": "512Mi", "cpu": "500m"},
        ),
    )

    # Add command if specified
    if command:
        container_spec.command = command

    # Convert Docker-format health check to K8s probes
    if health_check and "test" in health_check:
        test_cmd = health_check["test"]
        # Docker format: ["CMD-SHELL", "pg_isready -U postgres"] or ["CMD", "mysqladmin", ...]
        if isinstance(test_cmd, list):
            if test_cmd[0] == "CMD-SHELL":
                exec_command = ["/bin/sh", "-c", test_cmd[1]]
            elif test_cmd[0] == "CMD":
                exec_command = test_cmd[1:]
            else:
                exec_command = test_cmd
        else:
            exec_command = ["/bin/sh", "-c", test_cmd]

        probe = client.V1Probe(
            _exec=client.V1ExecAction(command=exec_command),
            initial_delay_seconds=10,
            period_seconds=10,
            timeout_seconds=5,
            failure_threshold=5,
        )
        container_spec.readiness_probe = probe
        container_spec.liveness_probe = client.V1Probe(
            _exec=client.V1ExecAction(command=exec_command),
            initial_delay_seconds=30,
            period_seconds=10,
            timeout_seconds=5,
            failure_threshold=3,
        )

    # Pod spec - no security context restrictions for service images
    # (postgres, redis, etc. often need to run as their own user)
    pod_spec = client.V1PodSpec(
        containers=[container_spec],
        volumes=volume_specs if volume_specs else None,
    )

    # Add pod affinity if enabled
    if enable_pod_affinity:
        pod_spec.affinity = create_pod_affinity_spec(
            project_id=str(project_id), topology_key=affinity_topology_key
        )

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(name=deployment_name, namespace=namespace, labels=labels),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels=selector_labels),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={**labels, **selector_labels}),
                spec=pod_spec,
            ),
        ),
    )


def create_service_pvc_manifest(
    namespace: str,
    project_id: UUID,
    user_id: UUID,
    container_directory: str,
    storage_class: str,
    size: str = "1Gi",
) -> client.V1PersistentVolumeClaim:
    """
    Create a PVC for a service container's data (separate from project PVC).

    Args:
        namespace: Kubernetes namespace
        project_id: Project UUID
        user_id: User UUID
        container_directory: Sanitized container name
        storage_class: StorageClass to use
        size: Storage size

    Returns:
        V1PersistentVolumeClaim manifest
    """
    pvc_name = _k8s_name("svc-", f"{container_directory}-data")

    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name=pvc_name,
            namespace=namespace,
            labels=get_standard_labels(
                project_id=str(project_id),
                user_id=str(user_id),
                component="service-storage",
                container_directory=container_directory,
            ),
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            storage_class_name=storage_class,
            access_modes=["ReadWriteOnce"],
            resources=client.V1ResourceRequirements(requests={"storage": size}),
        ),
    )


# =============================================================================
# NOTE: S3 hibernation scripts removed - now using EBS VolumeSnapshots
# =============================================================================
# Hibernation is now handled by snapshot_manager.py using Kubernetes VolumeSnapshots.
# Benefits:
# - Near-instant hibernation (< 5 seconds)
# - Near-instant restore (< 10 seconds, lazy loading)
# - Full volume preserved (node_modules included - no npm install)
# - Versioning (up to 5 snapshots per project)
# =============================================================================


# =============================================================================
# Template Builder Job
# =============================================================================


def create_template_builder_job(
    namespace: str,
    build_id: str,
    git_url: str,
    git_branch: str,
    pvc_name: str,
    devserver_image: str,
    timeout_seconds: int = 600,
) -> client.V1Job:
    """Create a K8s Job that clones a repo and installs dependencies into a PVC."""

    build_script = r'''set -e
echo "TEMPLATE_BUILD_STARTING"

# 1. Clone repo
git clone --depth=1 --branch "$GIT_BRANCH" "$GIT_URL" /tmp/src
cp -r /tmp/src/. /workspace/
rm -rf /workspace/.git

# 2. Read .tesslate/config.json for app directories
cd /workspace
DIRS=""
if [ -f ".tesslate/config.json" ]; then
    # Extract directory values from config.json using lightweight parsing
    # Handles both "." (root) and subdirectories like "frontend", "backend"
    DIRS=$(python3 -c "
import json, sys
try:
    cfg = json.load(open('.tesslate/config.json'))
    dirs = set()
    for app in cfg.get('apps', {}).values():
        d = app.get('directory', '.')
        dirs.add('.' if d in ('', '.', None) else d)
    print(' '.join(dirs))
except Exception:
    sys.exit(1)
" 2>/dev/null) || DIRS=""
fi

# 3. Fallback: scan common directories if no config found
if [ -z "$DIRS" ]; then
    DIRS=". frontend backend client server api web"
fi

# 4. Install dependencies in each directory
for dir in $DIRS; do
    [ "$dir" != "." ] && [ ! -d "/workspace/$dir" ] && continue
    cd "/workspace/$dir"
    if [ -f package-lock.json ]; then npm ci
    elif [ -f yarn.lock ]; then yarn install --frozen-lockfile
    elif [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile
    elif [ -f bun.lockb ] || [ -f bun.lock ]; then bun install
    elif [ -f package.json ]; then npm install
    elif [ -f requirements.txt ]; then pip install -r requirements.txt
    elif [ -f go.mod ]; then go mod download
    fi
    cd /workspace
done

echo "TEMPLATE_BUILD_COMPLETE"'''

    job_name = f"tmpl-build-{build_id[:8]}"

    return client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=namespace,
            labels={
                "app.kubernetes.io/managed-by": "tesslate",
                "tesslate.io/component": "template-builder",
                "tesslate.io/build-id": build_id,
            },
        ),
        spec=client.V1JobSpec(
            backoff_limit=0,
            active_deadline_seconds=timeout_seconds,
            ttl_seconds_after_finished=300,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={
                        "app.kubernetes.io/managed-by": "tesslate",
                        "tesslate.io/component": "template-builder",
                    },
                ),
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    security_context=client.V1PodSecurityContext(
                        run_as_user=1000,
                        run_as_group=1000,
                        fs_group=1000,
                        run_as_non_root=True,
                    ),
                    containers=[
                        client.V1Container(
                            name="builder",
                            image=devserver_image,
                            command=["/bin/sh", "-c", build_script],
                            env=[
                                client.V1EnvVar(name="GIT_URL", value=git_url),
                                client.V1EnvVar(name="GIT_BRANCH", value=git_branch),
                            ],
                            volume_mounts=[
                                client.V1VolumeMount(
                                    name="workspace",
                                    mount_path="/workspace",
                                ),
                            ],
                            resources=client.V1ResourceRequirements(
                                requests={"memory": "256Mi", "cpu": "50m"},
                                limits={"memory": "1536Mi", "cpu": "1000m"},
                            ),
                        ),
                    ],
                    volumes=[
                        client.V1Volume(
                            name="workspace",
                            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=pvc_name,
                            ),
                        ),
                    ],
                ),
            ),
        ),
    )


def create_builder_network_policy(namespace: str) -> client.V1NetworkPolicy:
    """Create NetworkPolicy for template builder: allow all egress, deny ingress."""
    return client.V1NetworkPolicy(
        api_version="networking.k8s.io/v1",
        kind="NetworkPolicy",
        metadata=client.V1ObjectMeta(
            name="template-builder-policy",
            namespace=namespace,
        ),
        spec=client.V1NetworkPolicySpec(
            pod_selector=client.V1LabelSelector(),  # all pods
            policy_types=["Ingress", "Egress"],
            ingress=[],  # deny all ingress
            egress=[client.V1NetworkPolicyEgressRule()],  # allow all egress
        ),
    )


# =============================================================================
# Tier 2: CSI-backed PV/PVC + Deployments
# =============================================================================


def create_v2_project_pv(
    volume_id: str,
    node_name: str,
    project_id: UUID,
    size: str = "10Gi",
) -> client.V1PersistentVolume:
    """Create a static PV referencing an existing btrfs subvolume via CSI.

    The btrfs CSI driver's NodePublishVolume resolves volume_handle to
    /mnt/tesslate-pool/volumes/{volume_handle} and bind-mounts it into the pod.
    CSI NodePublishVolume materializes the volume on demand if missing
    (safety net via Hub.EnsureCached). No hard nodeAffinity — pods use
    soft affinity instead, allowing the scheduler to place elsewhere when
    the preferred node is full.

    Args:
        volume_id: btrfs subvolume ID (used as CSI volume handle)
        node_name: Node where the subvolume lives (unused — kept for API compat)
        project_id: Project UUID
        size: Capacity (informational — btrfs has no per-subvolume quota)
    """
    pv_name = f"pv-{volume_id}"
    return client.V1PersistentVolume(
        metadata=client.V1ObjectMeta(
            name=pv_name,
            labels={
                "tesslate.io/volume-id": volume_id,
                "tesslate.io/project-id": str(project_id),
            },
        ),
        spec=client.V1PersistentVolumeSpec(
            capacity={"storage": size},
            access_modes=["ReadWriteOnce"],
            persistent_volume_reclaim_policy="Retain",
            storage_class_name="",
            csi=client.V1CSIPersistentVolumeSource(
                driver="btrfs.csi.tesslate.io",
                volume_handle=volume_id,
            ),
        ),
    )


def create_v2_project_pvc(
    namespace: str,
    volume_id: str,
    project_id: UUID,
    user_id: UUID,
    size: str = "10Gi",
) -> client.V1PersistentVolumeClaim:
    """Create a PVC that binds to a specific static PV for the project volume.

    Args:
        namespace: Project namespace (proj-{uuid})
        volume_id: btrfs subvolume ID (matches PV name pv-{volume_id})
        project_id: Project UUID
        user_id: User UUID
        size: Must match the PV capacity
    """
    pv_name = f"pv-{volume_id}"
    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name="project-source",
            namespace=namespace,
            labels=get_standard_labels(str(project_id), str(user_id), "storage"),
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            storage_class_name="",
            volume_name=pv_name,
            resources=client.V1ResourceRequirements(requests={"storage": size}),
        ),
    )


def create_v2_service_pv(
    service_volume_id: str,
    node_name: str,
    project_id: UUID,
    service_dir: str,
    size: str = "10Gi",
) -> client.V1PersistentVolume:
    """Create a static PV for a service container's btrfs subvolume.

    No hard nodeAffinity — CSI NodePublishVolume materializes the volume
    on demand. Pods use soft affinity for the preferred node.

    Args:
        service_volume_id: btrfs service subvolume ID
        node_name: Node where the subvolume lives (unused — kept for API compat)
        project_id: Project UUID
        service_dir: Sanitized service directory name (for labeling)
        size: Capacity (informational)
    """
    pv_name = f"pv-{service_volume_id}"
    return client.V1PersistentVolume(
        metadata=client.V1ObjectMeta(
            name=pv_name,
            labels={
                "tesslate.io/volume-id": service_volume_id,
                "tesslate.io/project-id": str(project_id),
                "tesslate.io/service-dir": service_dir,
            },
        ),
        spec=client.V1PersistentVolumeSpec(
            capacity={"storage": size},
            access_modes=["ReadWriteOnce"],
            persistent_volume_reclaim_policy="Retain",
            storage_class_name="",
            csi=client.V1CSIPersistentVolumeSource(
                driver="btrfs.csi.tesslate.io",
                volume_handle=service_volume_id,
            ),
        ),
    )


def create_v2_service_pvc(
    namespace: str,
    service_volume_id: str,
    project_id: UUID,
    user_id: UUID,
    service_dir: str,
    size: str = "10Gi",
) -> client.V1PersistentVolumeClaim:
    """Create a PVC that binds to a specific static PV for a service volume.

    Args:
        namespace: Project namespace (proj-{uuid})
        service_volume_id: btrfs service subvolume ID
        project_id: Project UUID
        user_id: User UUID
        service_dir: Sanitized service directory name (used in PVC name)
        size: Must match the PV capacity
    """
    pv_name = f"pv-{service_volume_id}"
    pvc_name = f"svc-{service_dir}-data"
    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name=pvc_name,
            namespace=namespace,
            labels=get_standard_labels(str(project_id), str(user_id), "storage"),
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            storage_class_name="",
            volume_name=pv_name,
            resources=client.V1ResourceRequirements(requests={"storage": size}),
        ),
    )


def create_v2_dev_deployment(
    namespace: str,
    project_id: UUID,
    user_id: UUID,
    container_id: UUID,
    container_directory: str,
    image: str,
    port: int,
    startup_command: str,
    pvc_name: str = "project-source",
    working_directory: str = "",
    image_pull_policy: str = "IfNotPresent",
    image_pull_secret: str = None,
    extra_env: dict[str, str] | None = None,
    preferred_node: str | None = None,
) -> client.V1Deployment:
    """
    Create a v2 dev container deployment using CSI-backed PVC volumes.

    Pods use soft affinity for the preferred node (where volume is cached).
    If the preferred node is full, the scheduler can place elsewhere —
    CSI NodePublishVolume materializes the volume on demand.

    Args:
        namespace: Kubernetes namespace
        project_id: Project UUID
        user_id: User UUID
        container_id: Container UUID
        container_directory: Container directory name for K8s resource naming (DNS-safe)
        image: Container image (tesslate-devserver)
        port: Port the dev server listens on
        startup_command: Command to start the dev server
        pvc_name: PVC claim name (default "project-source")
        working_directory: Actual filesystem path ("." for root, "frontend", etc.)
        image_pull_policy: Image pull policy
        image_pull_secret: Optional image pull secret
        extra_env: Additional environment variables

    Returns:
        V1Deployment manifest
    """
    deployment_name = _k8s_name("dev-", container_directory)

    labels = get_standard_labels(
        project_id=str(project_id),
        user_id=str(user_id),
        component="dev-container",
        container_id=str(container_id),
        container_directory=container_directory,
    )
    labels["app"] = "dev-container"
    labels["tesslate.io/tier"] = "2"

    selector_labels = {"tesslate.io/container-id": str(container_id)}

    # Working directory inside container
    effective_dir = working_directory or container_directory
    working_dir = "/app" if effective_dir in (".", "") else f"/app/{effective_dir}"

    # Environment variables
    env_vars = [
        client.V1EnvVar(name="HOST", value="0.0.0.0"),
        client.V1EnvVar(name="PORT", value=str(port)),
        client.V1EnvVar(name="NODE_ENV", value="development"),
    ]
    # Filter out reserved keys, then resolve ${secret:name/key} references
    # to V1EnvVar(valueFrom=secretKeyRef(...)) — never plaintext in pod spec.
    _filtered = {k: v for k, v in (extra_env or {}).items() if k not in {"HOST", "PORT", "NODE_ENV"}}
    env_vars.extend(resolve_env_for_pod(_filtered))

    dev_container = client.V1Container(
        name="dev-server",
        image=image,
        image_pull_policy=image_pull_policy,
        # tsinit as PID 1: proper signal forwarding, process group kill,
        # zombie reaping. Dev server runs as managed process "main".
        command=["tsinit", "serve"],
        args=[
            "--process",
            f"main=mkdir -p {working_dir} && cd {working_dir} && rm -rf .next/dev/lock && {startup_command}",
            "--dir",
            "/",
            "--grace-period",
            "10s",
            "--restart-policy",
            "never",
            "--sock-path",
            "/tmp/tsinit.sock",
        ],
        ports=[client.V1ContainerPort(container_port=port, name="http")],
        volume_mounts=[client.V1VolumeMount(name="project-source", mount_path="/app")],
        env=env_vars,
        resources=client.V1ResourceRequirements(
            requests={"memory": "256Mi", "cpu": "50m"},
            limits={"memory": "1Gi", "cpu": "1000m"},
        ),
        startup_probe=client.V1Probe(
            _exec=client.V1ExecAction(command=["tsinit", "health", "/tmp/tsinit.sock"]),
            initial_delay_seconds=2,
            period_seconds=3,
            timeout_seconds=5,
            failure_threshold=30,
        ),
        readiness_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/", port=port),
            initial_delay_seconds=5,
            period_seconds=5,
            timeout_seconds=3,
            failure_threshold=3,
        ),
        liveness_probe=client.V1Probe(
            _exec=client.V1ExecAction(command=["tsinit", "health", "/tmp/tsinit.sock"]),
            initial_delay_seconds=10,
            period_seconds=10,
            timeout_seconds=5,
            failure_threshold=3,
        ),
    )

    # Pod spec — PVC volume, scheduler uses PV node affinity for placement
    pod_spec = client.V1PodSpec(
        priority_class_name="tesslate-environment",
        containers=[dev_container],
        automount_service_account_token=False,
        volumes=[
            client.V1Volume(
                name="project-source",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=pvc_name,
                ),
            )
        ],
        security_context=client.V1PodSecurityContext(
            run_as_non_root=True, run_as_user=1000, fs_group=1000
        ),
    )

    if image_pull_secret:
        pod_spec.image_pull_secrets = [client.V1LocalObjectReference(name=image_pull_secret)]

    # Soft affinity: prefer the node where the volume is cached, but allow
    # the scheduler to place elsewhere if the preferred node is full.
    if preferred_node:
        pod_spec.affinity = client.V1Affinity(
            node_affinity=client.V1NodeAffinity(
                preferred_during_scheduling_ignored_during_execution=[
                    client.V1PreferredSchedulingTerm(
                        weight=80,
                        preference=client.V1NodeSelectorTerm(
                            match_expressions=[
                                client.V1NodeSelectorRequirement(
                                    key="kubernetes.io/hostname",
                                    operator="In",
                                    values=[preferred_node],
                                )
                            ]
                        ),
                    )
                ]
            )
        )

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(name=deployment_name, namespace=namespace, labels=labels),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels=selector_labels),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={**labels, **selector_labels}),
                spec=pod_spec,
            ),
        ),
    )


def create_v2_service_deployment(
    namespace: str,
    project_id: UUID,
    user_id: UUID,
    container_id: UUID,
    container_directory: str,
    image: str,
    port: int,
    environment_vars: dict[str, str],
    volumes: list[str],
    service_pvc_name: str | None = None,
    command: list[str] | None = None,
    health_check: dict | None = None,
    service_slug: str | None = None,
    preferred_node: str | None = None,
) -> client.V1Deployment:
    """
    Create a v2 service container deployment using CSI-backed PVC volumes.

    Uses a PVC (bound to a static PV with CSI node affinity) instead of
    hostPath + nodeName. The scheduler places pods on the correct node
    via the PV's node affinity.

    Args:
        namespace: Kubernetes namespace
        project_id: Project UUID
        user_id: User UUID
        container_id: Container UUID
        container_directory: Sanitized container name
        image: Docker image (e.g., "postgres:16-alpine")
        port: Service port
        environment_vars: Environment variables
        volumes: Volume mount paths (e.g., ["/var/lib/postgresql/data"])
        service_pvc_name: PVC claim name for the service volume
        command: Optional command override
        health_check: Optional health check config (Docker format)

    Returns:
        V1Deployment manifest
    """
    deployment_name = _k8s_name("svc-", container_directory)

    labels = get_standard_labels(
        project_id=str(project_id),
        user_id=str(user_id),
        component="service-container",
        container_id=str(container_id),
        container_directory=container_directory,
    )
    labels["app"] = _k8s_name("svc-", container_directory)
    labels["tesslate.io/tier"] = "2"

    selector_labels = {"tesslate.io/container-id": str(container_id)}

    env_vars = resolve_env_for_pod(environment_vars)

    # All mount paths backed by the same PVC (CSI-backed service volume)
    volume_mounts = []
    for idx, vol_path in enumerate(volumes):
        vol_name = "service-data" if idx == 0 else f"service-data-{idx}"
        volume_mounts.append(client.V1VolumeMount(name=vol_name, mount_path=vol_path))

    # Single PVC, referenced by all volume mount names
    volume_specs = []
    for idx, _ in enumerate(volumes):
        vol_name = "service-data" if idx == 0 else f"service-data-{idx}"
        volume_specs.append(
            client.V1Volume(
                name=vol_name,
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=service_pvc_name,
                ),
            )
        )

    # Resolve resource profile from service definition
    _svc_def = None
    if service_slug:
        from app.services.service_definitions import get_service

        _svc_def = get_service(service_slug)

    container_spec = client.V1Container(
        name="service",
        image=image,
        env=env_vars,
        ports=[client.V1ContainerPort(container_port=port, name="service")],
        volume_mounts=volume_mounts if volume_mounts else None,
        resources=client.V1ResourceRequirements(
            requests={
                "cpu": _svc_def.cpu_request if _svc_def else "50m",
                "memory": _svc_def.mem_request if _svc_def else "256Mi",
            },
            limits={
                "cpu": _svc_def.cpu_limit if _svc_def else "500m",
                "memory": _svc_def.mem_limit if _svc_def else "512Mi",
            },
        ),
    )

    if command:
        container_spec.command = command

    # Convert Docker-format health check to K8s probes
    if health_check and "test" in health_check:
        test_cmd = health_check["test"]
        if isinstance(test_cmd, list):
            if test_cmd[0] == "CMD-SHELL":
                exec_command = ["/bin/sh", "-c", test_cmd[1]]
            elif test_cmd[0] == "CMD":
                exec_command = test_cmd[1:]
            else:
                exec_command = test_cmd
        else:
            exec_command = ["/bin/sh", "-c", test_cmd]

        container_spec.readiness_probe = client.V1Probe(
            _exec=client.V1ExecAction(command=exec_command),
            initial_delay_seconds=10,
            period_seconds=10,
            timeout_seconds=5,
            failure_threshold=5,
        )
        container_spec.liveness_probe = client.V1Probe(
            _exec=client.V1ExecAction(command=exec_command),
            initial_delay_seconds=30,
            period_seconds=10,
            timeout_seconds=5,
            failure_threshold=3,
        )

    # Pod spec — soft affinity for preferred node, CSI materializes volume on demand
    pod_spec = client.V1PodSpec(
        priority_class_name="tesslate-environment",
        containers=[container_spec],
        automount_service_account_token=False,
        volumes=volume_specs if volume_specs else None,
    )

    # Soft affinity: prefer the node where the volume is cached
    if preferred_node:
        pod_spec.affinity = client.V1Affinity(
            node_affinity=client.V1NodeAffinity(
                preferred_during_scheduling_ignored_during_execution=[
                    client.V1PreferredSchedulingTerm(
                        weight=80,
                        preference=client.V1NodeSelectorTerm(
                            match_expressions=[
                                client.V1NodeSelectorRequirement(
                                    key="kubernetes.io/hostname",
                                    operator="In",
                                    values=[preferred_node],
                                )
                            ]
                        ),
                    )
                ]
            )
        )

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(name=deployment_name, namespace=namespace, labels=labels),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels=selector_labels),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={**labels, **selector_labels}),
                spec=pod_spec,
            ),
        ),
    )
