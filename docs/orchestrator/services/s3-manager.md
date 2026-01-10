# S3 Manager - Project Hibernation & Hydration

**File**: `orchestrator/app/services/s3_manager.py` (583 lines)

The S3Manager handles persistent storage of user projects in S3-compatible object storage (AWS S3, DigitalOcean Spaces, MinIO). It implements the "S3 Sandwich" pattern for Kubernetes ephemeral storage.

## Overview

In Kubernetes mode with S3 enabled, projects are:
1. **Hydrated** on pod start (download from S3 to PVC)
2. **Run** on fast local PVC storage
3. **Dehydrated** on pod stop (upload from PVC to S3)

This provides:
- **Persistence**: Projects survive pod restarts
- **Cost Efficiency**: Pay for block storage only when running
- **Performance**: Local PVC I/O during development
- **Hibernation**: Delete idle projects, restore on demand

## Architecture

```
S3 Storage Pattern (Kubernetes)
┌──────────────────────────────────────────────┐
│ Pod Lifecycle                                │
├──────────────────────────────────────────────┤
│ 1. Init Container (Hydration)               │
│    ├─ Check if project exists in S3          │
│    ├─ Download: s3://bucket/projects/{user}/{proj}/latest.zip │
│    ├─ Extract to /app (PVC)                  │
│    └─ Or: Copy template if no S3 backup     │
│                                              │
│ 2. Main Container (Runtime)                 │
│    ├─ Fast local I/O on PVC                  │
│    ├─ npm install, file edits, etc.          │
│    └─ Work continues...                      │
│                                              │
│ 3. PreStop Hook (Dehydration)               │
│    ├─ Compress /app to ZIP                   │
│    ├─ Upload to S3: latest.zip               │
│    └─ Pod terminates                         │
└──────────────────────────────────────────────┘

S3 Path Structure:
s3://bucket/projects/{user_id}/{project_id}/latest.zip
s3://bucket/deleted/{user_id}/{project_id}/latest.zip  # Deleted backup
```

## Key Operations

### Upload (Dehydration)

```python
async def upload_project(
    self,
    user_id: UUID,
    project_id: UUID,
    source_path: str,
    exclude_node_modules: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Upload project to S3 as compressed archive.

    1. Create temp zip file
    2. Compress source directory (excluding .git, __pycache__, etc.)
    3. Upload to S3: projects/{user_id}/{project_id}/latest.zip
    4. Cleanup temp file

    Returns:
        (success, error_message)
    """
```

**Usage in PreStop Hook**:
```yaml
# kubernetes/helpers.py
lifecycle:
  preStop:
    exec:
      command: ['/bin/sh', '-c', '''
        echo "Dehydrating to S3..."
        python3 -c "
        from s3_manager import get_s3_manager
        import asyncio
        s3 = get_s3_manager()
        asyncio.run(s3.upload_project(user_id, project_id, '/app'))
        "
      ''']
```

### Download (Hydration)

```python
async def download_project(
    self,
    user_id: UUID,
    project_id: UUID,
    dest_path: str
) -> Tuple[bool, Optional[str]]:
    """
    Download project from S3 and extract.

    1. Download zip from S3 to temp file
    2. Extract to destination directory
    3. Cleanup temp file

    Returns:
        (success, error_message)
    """
```

**Usage in Init Container**:
```yaml
# kubernetes/helpers.py
initContainers:
  - name: hydrate-project
    command: ['/bin/sh', '-c', '''
      if python3 -c "from s3_manager import get_s3_manager; ...exists()..."; then
        echo "Hydrating from S3..."
        python3 -c "
        from s3_manager import get_s3_manager
        import asyncio
        s3 = get_s3_manager()
        asyncio.run(s3.download_project(user_id, project_id, '/app'))
        "
      else
        echo "No S3 backup, using template"
        cp -r /templates/base/* /app/
      fi
    ''']
```

### Check Existence

```python
async def project_exists(self, user_id: UUID, project_id: UUID) -> bool:
    """Check if project exists in S3 (uses HEAD request)."""
```

### Compression Details

```python
def _compress_directory(
    self,
    source_dir: str,
    output_zip: str,
    exclude_node_modules: bool = False
):
    """
    Compress directory to ZIP with exclusions.

    Excluded by default:
    - .git/
    - __pycache__/
    - *.pyc
    - .DS_Store

    Optional exclusion:
    - node_modules/ (can save significant upload time)
    """
```

## Configuration

### AWS S3

```bash
# .env
K8S_USE_S3_STORAGE=true
S3_BUCKET_NAME=tesslate-project-storage-prod
S3_REGION=us-east-1
S3_ENDPOINT_URL=  # Empty for AWS S3

# Authentication (IRSA preferred for EKS)
AWS_ROLE_ARN=arn:aws:iam::123456789:role/tesslate-s3-access  # IRSA
# Or explicit credentials:
S3_ACCESS_KEY_ID=AKIA...
S3_SECRET_ACCESS_KEY=...
```

### DigitalOcean Spaces

```bash
# .env
K8S_USE_S3_STORAGE=true
S3_BUCKET_NAME=tesslate-projects
S3_REGION=nyc3
S3_ENDPOINT_URL=https://nyc3.digitaloceanspaces.com
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
```

### MinIO (Local Dev)

```bash
# .env
K8S_USE_S3_STORAGE=true
S3_BUCKET_NAME=tesslate-projects
S3_REGION=us-east-1
S3_ENDPOINT_URL=http://minio.minio-system.svc.cluster.local:9000
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
```

## Usage Examples

### Example 1: Manual Upload/Download

```python
from services.s3_manager import get_s3_manager

s3 = get_s3_manager()

# Upload project
success, error = await s3.upload_project(
    user_id=user.id,
    project_id=project.id,
    source_path="/app",
    exclude_node_modules=True  # Faster upload, slower hydration
)

if success:
    logger.info("Project backed up to S3")
else:
    logger.error(f"S3 upload failed: {error}")

# Download project
success, error = await s3.download_project(
    user_id=user.id,
    project_id=project.id,
    dest_path="/app"
)
```

### Example 2: Check Before Hydration

```python
from services.s3_manager import get_s3_manager

s3 = get_s3_manager()

# Check if project backup exists
if await s3.project_exists(user.id, project.id):
    # Restore from S3
    await s3.download_project(user.id, project.id, "/app")
else:
    # Use template instead
    shutil.copytree("/templates/base", "/app")
```

### Example 3: Backup on Project Deletion

```python
from services.s3_manager import get_s3_manager

async def delete_project(project_id: UUID, user_id: UUID):
    s3 = get_s3_manager()

    # Copy to deleted/ prefix before deleting active backup
    await s3.copy_to_deleted(user_id, project_id)

    # Delete active backup
    await s3.delete_project(user_id, project_id)
```

## Additional Features

### Presigned URLs

```python
url, error = await s3.get_presigned_url(
    user_id=user.id,
    project_id=project.id,
    expiration=3600  # 1 hour
)

# User can download directly: curl <url>
```

### Project Size

```python
size_bytes, error = await s3.get_project_size(user.id, project.id)
size_mb = size_bytes / (1024 * 1024)
logger.info(f"Project size: {size_mb:.2f} MB")
```

### Deleted Backup

```python
# Copy to deleted archive for retention
success, error = await s3.copy_to_deleted(user.id, project.id)

# Projects in deleted/ have separate lifecycle rules
# e.g., auto-delete after 30 days
```

## Retry & Error Handling

Built-in retry configuration for S3 operations:

```python
S3_RETRY_CONFIG = Config(
    retries={
        'max_attempts': 3,
        'mode': 'adaptive'  # Adaptive retry for better resilience
    },
    connect_timeout=10,
    read_timeout=120  # 2 minutes for large files
)
```

## Cleanup Integration

When cleanup deletes idle environments in S3 mode:

```python
# kubernetes/manager.py
async def _cleanup_s3_mode(self, idle_timeout_minutes: int):
    """Delete idle environments (triggers S3 upload via preStop)."""
    for env in k8s_environments:
        if env['idle_time'] > idle_timeout_minutes * 60:
            # Delete pod - preStop hook uploads to S3 automatically
            await self.stop_container(env['project_id'], env['user_id'])
            logger.info(f"Hibernated {env['project_key']} to S3")
```

## Performance Considerations

### Upload Speed
- **node_modules excluded**: ~5-10 seconds for typical React app
- **node_modules included**: ~30-60 seconds (100MB+)
- **Trade-off**: Faster upload but slower hydration (need npm install)

### Download Speed
- **With node_modules**: ~10-20 seconds
- **Without node_modules**: ~5 seconds + npm install time (~30-60s)

### Optimization Tips
1. Exclude node_modules for faster uploads (user pays with npm install time)
2. Use regional S3 buckets (same region as K8s cluster)
3. Compress before upload (ZIP format with gzip)
4. Batch operations (don't upload on every file save)

## Troubleshooting

**Problem**: S3 upload fails with "Access Denied"
- Check S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY
- For EKS, verify IRSA role has s3:PutObject permission
- Check bucket policy allows access

**Problem**: Init container stuck at "Hydrating from S3"
- Check init container logs: `kubectl logs <pod> -c hydrate-project`
- Verify S3_ENDPOINT_URL is correct
- Test S3 access: `aws s3 ls s3://bucket/projects/`

**Problem**: PreStop hook times out
- Default terminationGracePeriodSeconds may be too short
- Increase in deployment manifest:
  ```yaml
  spec:
    terminationGracePeriodSeconds: 120  # 2 minutes
  ```

**Problem**: Corrupted zip file
- Check disk space on pod
- Verify no errors in compression logs
- Try manual download and extraction to debug

## Related Documentation

- [orchestration.md](./orchestration.md) - Kubernetes orchestrator uses S3Manager
- [../../../k8s/ARCHITECTURE.md](../../../k8s/ARCHITECTURE.md) - K8s storage architecture
- [../../../k8s/overlays/aws/README.md](../../../k8s/overlays/aws/README.md) - AWS S3 configuration
