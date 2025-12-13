"""
Kubernetes Helpers for S3-Backed Ephemeral Architecture

This module contains helper methods for Kubernetes ephemeral storage architecture
that uses S3-backed storage with ephemeral pods (hibernation/hydration model).

These helpers are used by KubernetesOrchestrator to create init containers,
lifecycle hooks, and dynamic PVCs for the S3 storage mode.

Refactored from: orchestrator/app/k8s_client_helpers.py
"""

from kubernetes import client
from typing import Dict
from uuid import UUID
import logging

logger = logging.getLogger(__name__)


def create_s3_init_container_manifest(
    user_id: UUID,
    project_id: UUID,
    s3_bucket: str,
    s3_endpoint: str,
    s3_region: str,
    pvc_name: str
) -> client.V1Container:
    """
    Create init container for hydration (S3 download).

    This container runs before the main dev server container and:
    1. Checks if project archive exists in S3
    2. If exists: Downloads and extracts to /app
    3. If not: Copies template from /template (baked into image)

    Args:
        user_id: User UUID
        project_id: Project UUID
        s3_bucket: S3 bucket name
        s3_endpoint: S3 endpoint URL
        s3_region: S3 region
        pvc_name: Name of the PVC to mount

    Returns:
        V1Container for init container
    """
    s3_key = f"projects/{user_id}/{project_id}/latest.zip"

    init_script = f"""
    set -e  # Exit on error

    echo "[HYDRATION] ======================================"
    echo "[HYDRATION] Tesslate Project Hydration"
    echo "[HYDRATION] User: {user_id}"
    echo "[HYDRATION] Project: {project_id}"
    echo "[HYDRATION] S3 Bucket: {s3_bucket}"
    echo "[HYDRATION] S3 Key: {s3_key}"
    echo "[HYDRATION] ======================================"

    # Configure AWS CLI
    export AWS_ACCESS_KEY_ID="${{S3_ACCESS_KEY_ID}}"
    export AWS_SECRET_ACCESS_KEY="${{S3_SECRET_ACCESS_KEY}}"
    export AWS_DEFAULT_REGION="{s3_region}"

    # Check if S3 archive exists
    echo "[HYDRATION] Checking if project exists in S3..."
    if aws s3 ls s3://{s3_bucket}/{s3_key} --endpoint-url={s3_endpoint} 2>/dev/null; then
        echo "[HYDRATION] ✓ Project found in S3, downloading..."

        # Download archive
        aws s3 cp s3://{s3_bucket}/{s3_key} /tmp/project.zip --endpoint-url={s3_endpoint}

        # Get file size
        SIZE=$(du -h /tmp/project.zip | cut -f1)
        echo "[HYDRATION] Downloaded archive size: $SIZE"

        # Extract to /app
        echo "[HYDRATION] Extracting archive to /app..."
        unzip -q /tmp/project.zip -d /app

        # Cleanup
        rm /tmp/project.zip

        echo "[HYDRATION] ✓ Project hydrated from S3"
        echo "[HYDRATION] Files in /app: $(ls -A /app | head -10 | tr '\\n' ' ')..."
    else
        echo "[HYDRATION] Project not found in S3 (new project)"
        echo "[HYDRATION] Copying template from /template..."

        # Copy pre-built template (includes node_modules)
        cp -r /template/. /app/

        echo "[HYDRATION] ✓ Template initialized"
        echo "[HYDRATION] Template size: $(du -sh /app | cut -f1)"
    fi

    # Verify critical files
    if [ ! -f "/app/package.json" ]; then
        echo "[HYDRATION] ERROR: No package.json found after hydration!"
        exit 1
    fi

    echo "[HYDRATION] ======================================"
    echo "[HYDRATION] ✅ Hydration complete"
    echo "[HYDRATION] ======================================"
    """

    return client.V1Container(
        name="hydrate-project",
        image="amazon/aws-cli:latest",
        command=["/bin/sh", "-c"],
        args=[init_script],
        volume_mounts=[
            client.V1VolumeMount(
                name="project-data",
                mount_path="/app"
            ),
            client.V1VolumeMount(
                name="template",
                mount_path="/template",
                read_only=True
            )
        ],
        env_from=[
            client.V1EnvFromSource(
                secret_ref=client.V1SecretEnvSource(
                    name="s3-credentials"
                )
            )
        ],
        resources=client.V1ResourceRequirements(
            requests={"memory": "64Mi", "cpu": "50m"},
            limits={"memory": "128Mi", "cpu": "200m"}
        )
    )


def create_dehydration_lifecycle_hook(
    user_id: UUID,
    project_id: UUID,
    s3_bucket: str,
    s3_endpoint: str,
    s3_region: str
) -> client.V1Lifecycle:
    """
    Create lifecycle hook for dehydration (S3 upload on pod shutdown).

    This hook runs BEFORE the container is terminated and:
    1. Compresses /app directory to zip
    2. Uploads to S3
    3. Verifies upload succeeded

    Kubernetes will wait for this hook to complete before killing the pod.
    The terminationGracePeriodSeconds should be set to at least 120s to
    allow time for large projects to upload.

    Args:
        user_id: User UUID
        project_id: Project UUID
        s3_bucket: S3 bucket name
        s3_endpoint: S3 endpoint URL
        s3_region: S3 region

    Returns:
        V1Lifecycle with preStop hook
    """
    s3_key = f"projects/{user_id}/{project_id}/latest.zip"

    dehydration_script = f"""
    set -e  # Exit on error

    echo "[DEHYDRATION] ======================================"
    echo "[DEHYDRATION] Tesslate Project Dehydration"
    echo "[DEHYDRATION] User: {user_id}"
    echo "[DEHYDRATION] Project: {project_id}"
    echo "[DEHYDRATION] S3 Bucket: {s3_bucket}"
    echo "[DEHYDRATION] S3 Key: {s3_key}"
    echo "[DEHYDRATION] ======================================"

    # Configure AWS CLI
    export AWS_ACCESS_KEY_ID="${{S3_ACCESS_KEY_ID}}"
    export AWS_SECRET_ACCESS_KEY="${{S3_SECRET_ACCESS_KEY}}"
    export AWS_DEFAULT_REGION="{s3_region}"

    # Change to /app directory
    cd /app

    # Create zip archive (exclude .git, node_modules/.cache, etc.)
    echo "[DEHYDRATION] Compressing project files..."
    zip -r -q /tmp/project.zip . \\
        -x "*.git/*" \\
        -x "*__pycache__/*" \\
        -x "*.pyc" \\
        -x ".DS_Store" \\
        -x "node_modules/.cache/*" \\
        -x "*.log"

    # Get archive size
    SIZE=$(du -h /tmp/project.zip | cut -f1)
    echo "[DEHYDRATION] Archive size: $SIZE"

    # Upload to S3
    echo "[DEHYDRATION] Uploading to S3..."
    aws s3 cp /tmp/project.zip s3://{s3_bucket}/{s3_key} --endpoint-url={s3_endpoint}

    # Verify upload succeeded
    if aws s3 ls s3://{s3_bucket}/{s3_key} --endpoint-url={s3_endpoint} >/dev/null 2>&1; then
        echo "[DEHYDRATION] ✓ Upload verified"
    else
        echo "[DEHYDRATION] ERROR: Upload verification failed!"
        exit 1
    fi

    # Cleanup
    rm /tmp/project.zip

    echo "[DEHYDRATION] ======================================"
    echo "[DEHYDRATION] ✅ Dehydration complete"
    echo "[DEHYDRATION] ======================================"
    """

    return client.V1Lifecycle(
        pre_stop=client.V1LifecycleHandler(
            _exec=client.V1ExecAction(
                command=["/bin/sh", "-c", dehydration_script]
            )
        )
    )


def create_dynamic_pvc_manifest(
    pvc_name: str,
    namespace: str,
    storage_class: str,
    size: str,
    user_id: UUID,
    project_id: UUID,
    access_mode: str = "ReadWriteOnce"
) -> client.V1PersistentVolumeClaim:
    """
    Create a dynamic PVC manifest for a single project.

    Unlike the shared PVC in persistent mode, each project gets its own PVC in S3 mode.
    This allows for granular deletion and no pod affinity constraints.

    For multi-container projects, use ReadWriteMany to allow multiple pods to mount the same volume.

    Args:
        pvc_name: Name of the PVC (e.g., "pvc-{user_id}-{project_id}")
        namespace: Kubernetes namespace
        storage_class: StorageClass to use (e.g., "do-block-storage" for RWO, "nfs-client" for RWX)
        size: Storage size (e.g., "5Gi")
        user_id: User UUID (for labels)
        project_id: Project UUID (for labels)
        access_mode: Access mode - "ReadWriteOnce" or "ReadWriteMany" (for multi-container)

    Returns:
        V1PersistentVolumeClaim manifest
    """
    storage_type = "shared" if access_mode == "ReadWriteMany" else "ephemeral"

    return client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(
            name=pvc_name,
            labels={
                "app": "dev-environment",
                "user-id": str(user_id),
                "project-id": str(project_id),
                "managed-by": "tesslate-backend",
                "storage-type": storage_type,
                "access-mode": access_mode.lower().replace("write", "")
            }
        ),
        spec=client.V1PersistentVolumeClaimSpec(
            storage_class_name=storage_class,
            access_modes=[access_mode],
            resources=client.V1ResourceRequirements(
                requests={"storage": size}
            )
        )
    )


def create_deployment_manifest_s3(
    deployment_name: str,
    user_id: UUID,
    project_id: UUID,
    pvc_name: str,
    s3_bucket: str,
    s3_endpoint: str,
    s3_region: str,
    dev_image: str,
    image_pull_secret: str = None
) -> client.V1Deployment:
    """
    Create deployment manifest for S3-backed ephemeral architecture.

    Key differences from persistent mode:
    - Uses dynamic PVC (not shared)
    - Has init container for S3 hydration
    - Has preStop hook for S3 dehydration
    - NO pod affinity (each project has own PVC)
    - Longer terminationGracePeriodSeconds for upload time

    Args:
        deployment_name: Name of the deployment
        user_id: User UUID
        project_id: Project UUID
        pvc_name: Name of the dynamic PVC
        s3_bucket: S3 bucket name
        s3_endpoint: S3 endpoint URL
        s3_region: S3 region
        dev_image: Dev server container image
        image_pull_secret: Image pull secret name (optional)

    Returns:
        V1Deployment manifest
    """
    # Create init container for hydration
    init_container = create_s3_init_container_manifest(
        user_id, project_id, s3_bucket, s3_endpoint, s3_region, pvc_name
    )

    # Create lifecycle hook for dehydration
    lifecycle = create_dehydration_lifecycle_hook(
        user_id, project_id, s3_bucket, s3_endpoint, s3_region
    )

    # Main dev server container
    dev_container = client.V1Container(
        name="dev-server",
        image=dev_image,
        ports=[client.V1ContainerPort(container_port=5173)],
        working_dir="/app",
        command=["/bin/sh"],
        args=[
            "-c",
            f"""
            set -e  # Exit on error

            echo "[DEV] ======================================"
            echo "[DEV] Tesslate Dev Server (S3-Backed)"
            echo "[DEV] User: {user_id}, Project: {project_id}"
            echo "[DEV] Node: $(node --version), NPM: $(npm --version)"
            echo "[DEV] ======================================"

            # Verify project was hydrated
            if [ ! -f "/app/package.json" ]; then
                echo "[DEV] ERROR: No package.json found!"
                echo "[DEV] Hydration may have failed"
                exit 1
            fi

            # Ensure node_modules is complete
            if [ ! -f "/app/node_modules/.bin/vite" ] && [ ! -L "/app/node_modules/.bin/vite" ]; then
                echo "[DEV] node_modules missing or incomplete"
                echo "[DEV] Running npm install..."
                npm install
            fi

            # Configure Vite for Kubernetes ingress
            if [ -f "/app/vite.config.js" ]; then
                echo "[DEV] Patching vite.config.js for Kubernetes ingress..."
                cat > /app/vite.config.js.new << 'VITECONFIG'
import {{{{ defineConfig }}}} from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({{{{
  plugins: [react()],
  server: {{{{
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    hmr: {{{{
      host: true,
      protocol: 'wss'
    }}}},
    allowedHosts: true
  }}}}
}}}})
VITECONFIG
                mv /app/vite.config.js.new /app/vite.config.js
                echo "[DEV] ✓ Vite config patched"
            fi

            echo "[DEV] ======================================"
            echo "[DEV] 🚀 Starting Vite dev server..."
            echo "[DEV] Port: 5173"
            echo "[DEV] ======================================"
            exec npx vite --host 0.0.0.0 --port 5173 --strictPort
            """
        ],
        volume_mounts=[
            client.V1VolumeMount(
                name="project-data",
                mount_path="/app"
            )
        ],
        resources=client.V1ResourceRequirements(
            requests={"memory": "256Mi", "cpu": "100m"},
            limits={"memory": "512Mi", "cpu": "500m"}
        ),
        env=[
            client.V1EnvVar(name="NODE_ENV", value="development"),
            client.V1EnvVar(name="PORT", value="5173"),
            client.V1EnvVar(name="HOST", value="0.0.0.0")
        ],
        env_from=[
            client.V1EnvFromSource(
                secret_ref=client.V1SecretEnvSource(
                    name="s3-credentials"
                )
            )
        ],
        lifecycle=lifecycle,
        readiness_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/", port=5173),
            initial_delay_seconds=5,
            period_seconds=3,
            timeout_seconds=3,
            failure_threshold=5
        ),
        startup_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/", port=5173),
            initial_delay_seconds=10,
            period_seconds=3,
            timeout_seconds=5,
            failure_threshold=20
        ),
        liveness_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/", port=5173),
            initial_delay_seconds=15,
            period_seconds=10,
            timeout_seconds=5,
            failure_threshold=3
        )
    )

    # Pod spec
    pod_spec = client.V1PodSpec(
        termination_grace_period_seconds=120,
        security_context=client.V1PodSecurityContext(
            run_as_non_root=True,
            run_as_user=1000,
            fs_group=1000,
            seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault")
        ),
        init_containers=[init_container],
        containers=[dev_container],
        volumes=[
            client.V1Volume(
                name="project-data",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=pvc_name
                )
            ),
            client.V1Volume(
                name="template",
                empty_dir=client.V1EmptyDirVolumeSource()
            )
        ]
    )

    # Add image pull secret if provided
    if image_pull_secret:
        pod_spec.image_pull_secrets = [
            client.V1LocalObjectReference(name=image_pull_secret)
        ]

    # Deployment manifest
    return client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=deployment_name,
            labels={
                "app": "dev-environment",
                "dev-environment": "true",
                "user-id": str(user_id),
                "project-id": str(project_id),
                "managed-by": "tesslate-backend",
                "storage-mode": "s3-ephemeral"
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
                        "app": deployment_name,
                        "dev-environment": "true",
                        "storage-mode": "s3-ephemeral"
                    }
                ),
                spec=pod_spec
            )
        )
    )


def create_base_container_init_script(container, base_config=None) -> str:
    """
    Generate init script for container setup.

    If container has a base with git_repo_url, clones from git and installs dependencies.
    Otherwise, copies the default template from the devserver image.

    Args:
        container: Container model with optional base relationship
        base_config: Optional base configuration for startup

    Returns:
        Shell script string for the init container
    """
    if container.base and container.base.git_repo_url:
        git_url = container.base.git_repo_url
        branch = container.base.default_branch or "main"
        base_name = container.base.name

        logger.info(f"[K8S] Container '{container.name}' uses base '{base_name}' with git: {git_url}")

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
        logger.info(f"[K8S] Container '{container.name}' using default template (no git_repo_url)")

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
