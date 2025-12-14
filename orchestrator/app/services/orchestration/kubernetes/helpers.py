"""
Kubernetes Helpers for New Architecture

This module contains helper methods for the new Kubernetes architecture that separates:
- File lifecycle (populate files when container added to graph)
- Container lifecycle (start/stop dev servers)
- S3 lifecycle (hibernation/restoration only)

Key components:
- File Manager Pod: Always-running pod for file operations
- Dev Container Deployment: Simple deployment with no init containers
- S3 Scripts: Only used for project hibernation/restoration
"""

from kubernetes import client
from typing import Dict, Optional
from uuid import UUID
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Labels and Affinity
# =============================================================================

def create_pod_affinity_spec(
    project_id: str,
    topology_key: str = "kubernetes.io/hostname"
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
                        match_labels={
                            "tesslate.io/project-id": str(project_id)
                        }
                    ),
                    topology_key=topology_key
                )
            ]
        )
    )


def get_standard_labels(
    project_id: str,
    user_id: str,
    component: str,
    container_id: str = None,
    container_directory: str = None
) -> Dict[str, str]:
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
    access_mode: str = "ReadWriteOnce"
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
                project_id=str(project_id),
                user_id=str(user_id),
                component="storage"
            )
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            storage_class_name=storage_class,
            access_modes=[access_mode],
            resources=client.V1ResourceRequirements(
                requests={"storage": size}
            )
        )
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
    image_pull_secret: str = None
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
        project_id=str(project_id),
        user_id=str(user_id),
        component="file-manager"
    )
    labels["app"] = "file-manager"

    # File manager container - just keeps alive
    # NO AWS credentials here - S3 ops handled securely by backend
    container = client.V1Container(
        name="file-manager",
        image=image,
        image_pull_policy=image_pull_policy,
        command=["tail", "-f", "/dev/null"],  # Keep alive
        working_dir="/app",
        volume_mounts=[
            client.V1VolumeMount(
                name="project-storage",
                mount_path="/app"
            )
        ],
        resources=client.V1ResourceRequirements(
            # File-manager needs enough memory for npm install (Next.js needs ~1GB)
            requests={"memory": "256Mi", "cpu": "100m"},
            limits={"memory": "1536Mi", "cpu": "1000m"}
        )
    )

    # Pod spec
    pod_spec = client.V1PodSpec(
        containers=[container],
        volumes=[
            client.V1Volume(
                name="project-storage",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name="project-storage"
                )
            )
        ],
        # Security context
        security_context=client.V1PodSecurityContext(
            run_as_non_root=True,
            run_as_user=1000,
            fs_group=1000
        )
    )

    # Add image pull secret if provided
    if image_pull_secret:
        pod_spec.image_pull_secrets = [
            client.V1LocalObjectReference(name=image_pull_secret)
        ]

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name="file-manager",
            namespace=namespace,
            labels=labels
        ),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(
                match_labels={"app": "file-manager"}
            ),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=pod_spec
            )
        )
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
    image_pull_policy: str = "IfNotPresent",
    image_pull_secret: str = None,
    enable_pod_affinity: bool = True,
    affinity_topology_key: str = "kubernetes.io/hostname"
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
        container_directory: Container directory name (e.g., "frontend", "backend")
        image: Container image
        port: Port the dev server listens on
        startup_command: Command to start the dev server (e.g., "npm run dev")
        image_pull_policy: Image pull policy
        image_pull_secret: Optional image pull secret
        enable_pod_affinity: Whether to enable pod affinity (for shared PVC)
        affinity_topology_key: Topology key for pod affinity

    Returns:
        V1Deployment manifest
    """
    deployment_name = f"dev-{container_directory}"

    labels = get_standard_labels(
        project_id=str(project_id),
        user_id=str(user_id),
        component="dev-container",
        container_id=str(container_id),
        container_directory=container_directory
    )
    labels["app"] = "dev-container"

    # Selector labels (must be subset of pod labels)
    selector_labels = {
        "tesslate.io/container-id": str(container_id)
    }

    # Working directory inside container
    working_dir = f"/app/{container_directory}"

    # Dev server container
    # Use exec to replace shell process - prevents exit when stdin closes
    dev_container = client.V1Container(
        name="dev-server",
        image=image,
        image_pull_policy=image_pull_policy,
        command=["sh", "-c"],
        # Run dev server in tmux session so agent can stop/restart without crashing container
        # PID 1 is immortal tail -f, dev server runs in tmux session "main"
        # Agent can: tmux send-keys -t main C-c (stop), tmux send-keys -t main 'npm run dev' Enter (start)
        args=[f"cd {working_dir} && ([ -d node_modules ] || npm install) && tmux new-session -d -s main '{startup_command}' && exec tail -f /dev/null"],
        ports=[
            client.V1ContainerPort(
                container_port=port,
                name="http"
            )
        ],
        working_dir=working_dir,
        volume_mounts=[
            client.V1VolumeMount(
                name="project-storage",
                mount_path="/app"
            )
        ],
        env=[
            client.V1EnvVar(name="HOST", value="0.0.0.0"),
            client.V1EnvVar(name="PORT", value=str(port)),
            client.V1EnvVar(name="NODE_ENV", value="development"),
        ],
        resources=client.V1ResourceRequirements(
            requests={"memory": "256Mi", "cpu": "100m"},
            limits={"memory": "1Gi", "cpu": "1000m"}
        ),
        # Startup probe - wait for dev server to be ready
        startup_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/", port=port),
            initial_delay_seconds=5,
            period_seconds=3,
            timeout_seconds=5,
            failure_threshold=30  # Allow up to 90 seconds for npm install
        ),
        # Readiness probe
        readiness_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/", port=port),
            initial_delay_seconds=5,
            period_seconds=5,
            timeout_seconds=3,
            failure_threshold=3
        ),
        # Liveness probe
        liveness_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/", port=port),
            initial_delay_seconds=30,
            period_seconds=10,
            timeout_seconds=5,
            failure_threshold=3
        )
    )

    # Pod spec
    pod_spec = client.V1PodSpec(
        containers=[dev_container],
        volumes=[
            client.V1Volume(
                name="project-storage",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name="project-storage"
                )
            )
        ],
        security_context=client.V1PodSecurityContext(
            run_as_non_root=True,
            run_as_user=1000,
            fs_group=1000
        )
    )

    # Add pod affinity if enabled (for shared PVC)
    if enable_pod_affinity:
        pod_spec.affinity = create_pod_affinity_spec(
            project_id=str(project_id),
            topology_key=affinity_topology_key
        )

    # Add image pull secret if provided
    if image_pull_secret:
        pod_spec.image_pull_secrets = [
            client.V1LocalObjectReference(name=image_pull_secret)
        ]

    return client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=deployment_name,
            namespace=namespace,
            labels=labels
        ),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(
                match_labels=selector_labels
            ),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={**labels, **selector_labels}),
                spec=pod_spec
            )
        )
    )


# =============================================================================
# Service and Ingress
# =============================================================================

def create_service_manifest(
    namespace: str,
    project_id: UUID,
    container_id: UUID,
    container_directory: str,
    port: int
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
    service_name = f"dev-{container_directory}"

    return client.V1Service(
        metadata=client.V1ObjectMeta(
            name=service_name,
            namespace=namespace,
            labels={
                "tesslate.io/project-id": str(project_id),
                "tesslate.io/container-id": str(container_id),
                "tesslate.io/container-directory": container_directory
            }
        ),
        spec=client.V1ServiceSpec(
            selector={
                "tesslate.io/container-id": str(container_id)
            },
            ports=[
                client.V1ServicePort(
                    port=port,
                    target_port=port,
                    protocol="TCP"
                )
            ],
            type="ClusterIP"
        )
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
    tls_secret: str = None
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
        domain: Base domain (e.g., "localhost" or "studio.tesslate.com")
        ingress_class: Ingress class name
        tls_secret: Optional TLS secret name for HTTPS

    Returns:
        V1Ingress manifest
    """
    ingress_name = f"dev-{container_directory}"
    # Single subdomain level for wildcard cert compatibility (*.domain)
    host = f"{project_slug}-{container_directory}.{domain}"
    service_name = f"dev-{container_directory}"

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
                                    name=service_name,
                                    port=client.V1ServiceBackendPort(
                                        number=port
                                    )
                                )
                            )
                        )
                    ]
                )
            )
        ]
    )

    # Add TLS if secret provided
    if tls_secret:
        ingress_spec.tls = [
            client.V1IngressTLS(
                hosts=[host],
                secret_name=tls_secret
            )
        ]

    return client.V1Ingress(
        metadata=client.V1ObjectMeta(
            name=ingress_name,
            namespace=namespace,
            labels={
                "tesslate.io/project-id": str(project_id),
                "tesslate.io/container-id": str(container_id),
                "tesslate.io/container-directory": container_directory
            },
            annotations={
                # WebSocket support for HMR
                "nginx.ingress.kubernetes.io/proxy-http-version": "1.1",
                "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
                "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600",
            }
        ),
        spec=ingress_spec
    )


# =============================================================================
# Network Policy
# =============================================================================

def create_network_policy_manifest(
    namespace: str,
    project_id: UUID
) -> client.V1NetworkPolicy:
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
            labels={
                "tesslate.io/project-id": str(project_id)
            }
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
                                match_labels={
                                    "kubernetes.io/metadata.name": "ingress-nginx"
                                }
                            )
                        )
                    ]
                ),
                # Allow from tesslate backend (for file operations)
                client.V1NetworkPolicyIngressRule(
                    _from=[
                        client.V1NetworkPolicyPeer(
                            namespace_selector=client.V1LabelSelector(
                                match_labels={
                                    "kubernetes.io/metadata.name": "tesslate"
                                }
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
                )
            ],
            egress=[
                # Allow DNS
                client.V1NetworkPolicyEgressRule(
                    to=[
                        client.V1NetworkPolicyPeer(
                            namespace_selector=client.V1LabelSelector()
                        )
                    ],
                    ports=[
                        client.V1NetworkPolicyPort(protocol="UDP", port=53)
                    ]
                ),
                # Allow HTTPS (npm, git)
                client.V1NetworkPolicyEgressRule(
                    to=[
                        client.V1NetworkPolicyPeer(
                            ip_block=client.V1IPBlock(cidr="0.0.0.0/0")
                        )
                    ],
                    ports=[
                        client.V1NetworkPolicyPort(protocol="TCP", port=443)
                    ]
                ),
                # Allow HTTP (some registries)
                client.V1NetworkPolicyEgressRule(
                    to=[
                        client.V1NetworkPolicyPeer(
                            ip_block=client.V1IPBlock(cidr="0.0.0.0/0")
                        )
                    ],
                    ports=[
                        client.V1NetworkPolicyPort(protocol="TCP", port=80)
                    ]
                ),
                # Allow MinIO
                client.V1NetworkPolicyEgressRule(
                    to=[
                        client.V1NetworkPolicyPeer(
                            namespace_selector=client.V1LabelSelector(
                                match_labels={
                                    "kubernetes.io/metadata.name": "minio-system"
                                }
                            )
                        )
                    ]
                )
            ]
        )
    )


# =============================================================================
# Git Clone Script (for container initialization)
# =============================================================================

def generate_git_clone_script(
    git_url: str,
    branch: str,
    target_dir: str,
    install_deps: bool = True
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
    install_section = """
# Install dependencies based on project type
if [ -f "package.json" ]; then
    echo "[CLONE] Installing Node.js dependencies..."
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
""" if install_deps else ""

    return f'''#!/bin/sh
set -e

echo "[CLONE] ======================================"
echo "[CLONE] Cloning repository"
echo "[CLONE] URL: {git_url}"
echo "[CLONE] Branch: {branch}"
echo "[CLONE] Target: {target_dir}"
echo "[CLONE] ======================================"

# Remove target directory if exists (may have wrong permissions from failed starts)
rm -rf {target_dir}

# Clone directly to target directory
git clone --depth 1 --branch {branch} --single-branch {git_url} {target_dir}

# Remove .git folder to save space
rm -rf {target_dir}/.git

# Move to target directory for dependency install
cd {target_dir}
{install_section}
echo "[CLONE] ======================================"
echo "[CLONE] ✅ Clone complete"
echo "[CLONE] Files:"
ls -la {target_dir}/ | head -20
echo "[CLONE] ======================================"
'''


# =============================================================================
# S3 Scripts (for hibernation/restoration ONLY)
# =============================================================================

def generate_s3_upload_script(
    s3_bucket: str,
    s3_key: str,
    s3_endpoint: str,
    s3_region: str,
    source_dir: str = "/app",
    exclude_patterns: list = None
) -> str:
    """
    Generate script to zip and upload project to S3.

    This is ONLY used for project hibernation (when user leaves).
    NOT used for container startup!

    Args:
        s3_bucket: S3 bucket name
        s3_key: S3 key path
        s3_endpoint: S3 endpoint URL (empty for AWS)
        s3_region: S3 region
        source_dir: Directory to archive
        exclude_patterns: Patterns to exclude from zip

    Returns:
        Shell script as string
    """
    if exclude_patterns is None:
        exclude_patterns = ["node_modules", ".git", "__pycache__", "venv", ".venv"]

    exclude_args = " ".join([f'-x "{p}/*"' for p in exclude_patterns])
    endpoint_arg = f'--endpoint-url="{s3_endpoint}"' if s3_endpoint else ""

    return f'''#!/bin/sh
set -e

echo "[HIBERNATE] ======================================"
echo "[HIBERNATE] Uploading project to S3"
echo "[HIBERNATE] Bucket: {s3_bucket}"
echo "[HIBERNATE] Key: {s3_key}"
echo "[HIBERNATE] ======================================"

# Configure AWS CLI
export AWS_DEFAULT_REGION="{s3_region}"

# Create archive
cd {source_dir}
zip -r -q /tmp/project.zip . {exclude_args} -x "*.log" -x ".DS_Store"

# Upload to S3
aws s3 cp /tmp/project.zip s3://{s3_bucket}/{s3_key} {endpoint_arg}

# Verify upload
if aws s3 ls s3://{s3_bucket}/{s3_key} {endpoint_arg} >/dev/null 2>&1; then
    echo "[HIBERNATE] ✓ Upload verified"
else
    echo "[HIBERNATE] ERROR: Upload failed!"
    exit 1
fi

rm -f /tmp/project.zip

echo "[HIBERNATE] ======================================"
echo "[HIBERNATE] ✅ Hibernation complete"
echo "[HIBERNATE] ======================================"
'''


def generate_s3_download_script(
    s3_bucket: str,
    s3_key: str,
    s3_endpoint: str,
    s3_region: str,
    target_dir: str = "/app"
) -> str:
    """
    Generate script to download and extract project from S3.

    This is ONLY used for project restoration (when user returns to hibernated project).
    NOT used for new project setup!

    Args:
        s3_bucket: S3 bucket name
        s3_key: S3 key path
        s3_endpoint: S3 endpoint URL (empty for AWS)
        s3_region: S3 region
        target_dir: Directory to extract to

    Returns:
        Shell script as string
    """
    endpoint_arg = f'--endpoint-url="{s3_endpoint}"' if s3_endpoint else ""

    return f'''#!/bin/sh
set -e

echo "[RESTORE] ======================================"
echo "[RESTORE] Downloading project from S3"
echo "[RESTORE] Bucket: {s3_bucket}"
echo "[RESTORE] Key: {s3_key}"
echo "[RESTORE] ======================================"

# Configure AWS CLI
export AWS_DEFAULT_REGION="{s3_region}"

# Check if archive exists
if ! aws s3 ls s3://{s3_bucket}/{s3_key} {endpoint_arg} 2>/dev/null; then
    echo "[RESTORE] ERROR: Archive not found in S3!"
    exit 1
fi

# Download archive
aws s3 cp s3://{s3_bucket}/{s3_key} /tmp/project.zip {endpoint_arg}

# Extract to target
mkdir -p {target_dir}
unzip -q -o /tmp/project.zip -d {target_dir}

rm -f /tmp/project.zip

echo "[RESTORE] ======================================"
echo "[RESTORE] ✅ Restoration complete"
echo "[RESTORE] Files:"
ls -la {target_dir}/ | head -20
echo "[RESTORE] ======================================"
'''
