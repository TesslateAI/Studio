# S3 Sandwich Pattern (Hibernation)

Ephemeral storage pattern for Kubernetes user projects using S3 persistence.

## Overview

The S3 Sandwich pattern provides:
- **Fast local I/O** during development (block storage PVC)
- **Persistent storage** in S3 (survives pod termination)
- **Cost savings** by deleting idle PVCs (5Gi × idle projects = $$$)
- **Quick restoration** when user returns

**Pattern Name**: "Sandwich" because project storage is sandwiched between S3 (bread) and ephemeral PVC (filling).

## Lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│ 1. HYDRATION (Init Container)                               │
│    S3 → PVC                                                  │
│    Download project.zip from S3, extract to /workspace      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. RUNTIME (Main Container)                                 │
│    User edits files on PVC                                  │
│    Fast local I/O, npm install, file operations             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. DEHYDRATION (PreStop Hook)                               │
│    PVC → S3                                                  │
│    Zip /workspace (exclude node_modules), upload to S3      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. CLEANUP (CronJob)                                        │
│    Delete namespace → PVC deleted                           │
│    Project stays in S3, ready for next hydration            │
└─────────────────────────────────────────────────────────────┘
```

## Implementation

### Hydration (Init Container)

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes/helpers.py`

**Function**: `_create_deployment_manifest()`

**Init Container**:
```python
init_containers=[
    client.V1Container(
        name="hydrate-project",
        image=settings.k8s_devserver_image,
        command=["sh", "-c"],
        args=["""
            # Check if project exists in S3
            if aws s3 ls s3://${S3_BUCKET}/${S3_PREFIX}/${PROJECT_ID}.zip; then
                echo "Project found in S3, hydrating..."
                aws s3 cp s3://${S3_BUCKET}/${S3_PREFIX}/${PROJECT_ID}.zip /workspace/project.zip
                cd /workspace && unzip -o project.zip && rm project.zip
            else
                echo "New project, copying template..."
                cp -r /template/* /workspace/
            fi
            echo "Hydration complete"
        """],
        env=[
            {"name": "S3_BUCKET", "value": s3_bucket},
            {"name": "S3_PREFIX", "value": "projects"},
            {"name": "PROJECT_ID", "value": str(project_id)},
            # S3 credentials from secret
        ],
        volume_mounts=[
            {"name": "project-source", "mountPath": "/workspace"}
        ]
    )
]
```

**Process**:
1. Check if `projects/{project_id}.zip` exists in S3
2. If exists: Download zip, extract to `/workspace`
3. If not exists: Copy template files from image
4. Exit (main container starts)

**Timeout**: Configured via `K8S_HYDRATION_TIMEOUT_SECONDS` (default: 300s)

### Runtime (Main Container)

**Volume Mount**:
```python
volume_mounts=[
    {"name": "project-source", "mountPath": "/workspace"}
]
```

**Working Directory**: `/workspace`

**Process**:
- User edits files via agent
- npm install, pip install work normally
- All changes written to PVC (fast local I/O)
- No S3 interaction during runtime

### Dehydration (PreStop Hook)

**PreStop Hook**:
```python
lifecycle=client.V1Lifecycle(
    pre_stop=client.V1LifecycleHandler(
        _exec=client.V1ExecAction(
            command=["sh", "-c", """
                echo "Dehydrating project to S3..."
                cd /workspace
                zip -r /tmp/project.zip . -x '${EXCLUDE_PATTERNS}'
                aws s3 cp /tmp/project.zip s3://${S3_BUCKET}/${S3_PREFIX}/${PROJECT_ID}.zip
                echo "Dehydration complete"
            """]
        )
    )
)
```

**Exclude Patterns** (from `K8S_DEHYDRATION_EXCLUDE_PATTERNS`):
- `node_modules`
- `.git`
- `__pycache__`
- `venv`
- `.venv`

**Process**:
1. Kubernetes calls PreStop hook before terminating pod
2. Script zips `/workspace` (excluding patterns)
3. Uploads to S3 as `projects/{project_id}.zip`
4. Hook exits, pod terminates

**Grace Period**: `K8S_HIBERNATION_GRACE_SECONDS` (default: 120s)
- If dehydration takes longer, pod is killed (data loss)
- Adjust grace period for large projects

### Cleanup (CronJob)

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/base/core/cleanup-cronjob.yaml`

**Schedule**: `*/2 * * * *` (every 2 minutes)

**Logic**:
```python
# In orchestrator backend
async def cleanup_idle_environments(idle_timeout_minutes: int):
    # 1. Get all project namespaces
    namespaces = await k8s_api.list_namespace()
    project_namespaces = [ns for ns in namespaces if ns.name.startswith("proj-")]

    # 2. Check last activity time in database
    for ns in project_namespaces:
        project = await db.get_project_by_namespace(ns.name)
        idle_time = now() - project.last_activity_at

        if idle_time > timedelta(minutes=idle_timeout_minutes):
            # 3. Delete namespace (triggers PreStop hook → dehydration)
            await k8s_api.delete_namespace(ns.name)
            logger.info(f"Hibernated project {project.id}")
```

**Timeout**: `K8S_HIBERNATION_IDLE_MINUTES` (default: 30)
- Minikube: 5 minutes (for testing)
- AWS: 30 minutes (production)

**Concurrency**: `Forbid` (only one cleanup job runs at a time)

## Configuration

### Environment Variables

**Backend** (`k8s/base/core/backend-deployment.yaml`):
```yaml
# S3 settings
- name: S3_BUCKET_NAME
  value: tesslate-projects-production-7761157a
- name: S3_ENDPOINT_URL
  value: ""  # Empty for AWS, http://minio... for Minikube
- name: S3_REGION
  value: us-east-1

# Hibernation settings
- name: K8S_HIBERNATION_IDLE_MINUTES
  value: "30"
- name: K8S_HIBERNATION_GRACE_SECONDS
  value: "120"
- name: K8S_HYDRATION_TIMEOUT_SECONDS
  value: "300"
- name: K8S_DEHYDRATION_EXCLUDE_PATTERNS
  value: "node_modules,.git,__pycache__,venv,.venv"
```

### Storage

**Minikube**: MinIO in `minio-system` namespace
```yaml
S3_ENDPOINT_URL: http://minio.minio-system.svc.cluster.local:9000
S3_BUCKET_NAME: tesslate-projects
```

**AWS**: Native S3
```yaml
S3_ENDPOINT_URL: ""  # Uses AWS SDK default
S3_BUCKET_NAME: tesslate-projects-production-7761157a
```

## Workflow Example

**User creates project**:
1. Backend creates namespace `proj-abc123`
2. Backend creates PVC `project-storage` (5Gi)
3. Backend creates deployment with init container
4. Init container: No S3 file, copies template → PVC
5. Dev server starts, user edits files

**User leaves for 30 minutes**:
1. Cleanup cronjob detects idle project
2. Cronjob deletes namespace
3. Kubernetes calls PreStop hook
4. Hook zips files, uploads to S3
5. Pod terminates, PVC deleted
6. Cost: $0.10/GB/month for S3 vs $0.80/GB/month for EBS (80% savings)

**User returns**:
1. Backend creates namespace `proj-abc123` (same or new UUID)
2. Backend creates PVC
3. Init container: S3 file found, downloads and extracts → PVC
4. Dev server starts, user continues work

## Troubleshooting

### Hydration Failures

**Symptom**: Init container fails, pod stuck in Init:Error

**Check logs**:
```bash
kubectl logs -n proj-{uuid} {pod-name} -c hydrate-project
```

**Common Issues**:
- S3 credentials invalid
- Network policy blocking S3 access
- Timeout (file too large)
- Corrupted zip file

**Fix**:
```bash
# Check S3 credentials
kubectl get secret -n tesslate s3-credentials -o yaml

# Check S3 bucket
aws s3 ls s3://tesslate-projects-production-7761157a/projects/

# Increase timeout
kubectl set env deployment/tesslate-backend -n tesslate K8S_HYDRATION_TIMEOUT_SECONDS=600
```

### Dehydration Not Happening

**Symptom**: Project deleted but no file in S3

**Check**:
1. PreStop hook executed?
```bash
kubectl describe pod -n proj-{uuid} {pod-name} | grep -A 10 "PreStop"
```

2. Grace period too short?
```bash
kubectl get pod -n proj-{uuid} {pod-name} -o yaml | grep terminationGracePeriodSeconds
```

**Fix**: Increase grace period
```bash
# In helpers.py, pod spec:
termination_grace_period_seconds=settings.k8s_hibernation_grace_seconds
```

### Large node_modules Being Uploaded

**Symptom**: Dehydration slow, S3 costs high

**Check**:
```bash
aws s3 ls --human-readable s3://tesslate-projects-production-7761157a/projects/
```

**Fix**: Ensure exclude patterns are working
```bash
# Test zip command manually in pod
kubectl exec -n proj-{uuid} {pod-name} -- sh -c "cd /workspace && zip -r /tmp/test.zip . -x 'node_modules/*' '*.git/*'"
```

### Restoration Incomplete

**Symptom**: User returns, some files missing

**Check**:
1. Download S3 file manually:
```bash
aws s3 cp s3://tesslate-projects-production-7761157a/projects/{project_id}.zip .
unzip -l {project_id}.zip
```

2. Check for zip errors in logs

**Fix**: May need to increase dehydration timeout or exclude patterns

## Cost Analysis

**Example**: 10 projects, 5Gi each, idle 90% of time

**Without S3 Sandwich** (always-on PVCs):
- Storage: 10 × 5Gi × $0.10/GB/month = $50/month
- Running: 10 × 5 = 50Gi always allocated

**With S3 Sandwich**:
- Active PVCs: 1 × 5Gi × $0.10/GB/month = $5/month (10% uptime)
- S3 storage: 10 × 0.5GB × $0.023/GB/month = $0.12/month (compressed)
- Total: ~$5.12/month

**Savings**: 90% ($45/month per 10 projects)

## Best Practices

1. **Exclude large directories**: Always exclude `node_modules`, `.git`, caches
2. **Monitor S3 size**: Alert if individual projects > 100MB
3. **Set appropriate timeouts**: Balance between cost (longer idle) and UX (shorter wait)
4. **Test restoration**: Regularly verify projects restore correctly
5. **Implement retries**: Network issues can cause upload failures
6. **Versioning**: Enable S3 versioning for data protection
7. **Lifecycle policies**: Move old versions to cheaper storage

## Future Improvements

- **Incremental sync**: Use rsync instead of full zip
- **Compression**: Use better compression (zstd instead of zip)
- **Background dehydration**: Don't wait for user logout, sync periodically
- **Smart caching**: Keep frequently accessed projects cached
- **Multi-region**: Replicate critical projects to multiple regions

## Related Documentation

- [../README.md](../README.md): Kubernetes overview
- [../overlays/aws.md](overlays/aws.md): AWS S3 configuration
- [../overlays/minikube.md](overlays/minikube.md): MinIO configuration
