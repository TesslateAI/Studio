# Troubleshooting Guide

This guide covers common issues and solutions when developing and deploying OpenSail.

## Container Issues

### Container Not Starting

**Symptoms**: Pod stuck in `CrashLoopBackOff` or `Error` state.

**Diagnosis**:
```powershell
# Check pod status
kubectl get pods -n tesslate

# Check pod events
kubectl describe pod <pod-name> -n tesslate

# Check container logs
kubectl logs <pod-name> -n tesslate
kubectl logs <pod-name> -n tesslate --previous  # Previous container logs
```

**Common Causes**:

1. **Missing environment variables**
   ```powershell
   # Check environment
   kubectl exec -n tesslate deployment/tesslate-backend -- env | grep DATABASE
   ```
   Fix: Verify secrets are properly mounted.

2. **Database connection failure**
   ```
   Error: Connection refused to database
   ```
   Fix: Check DATABASE_URL and ensure database pod is running.

3. **Missing dependencies**
   ```
   ModuleNotFoundError: No module named 'xyz'
   ```
   Fix: Rebuild image with `--no-cache` to ensure dependencies are installed.

### Image Not Updating (Cache Issue)

**Symptoms**: Code changes not appearing after rebuilding and deploying.

**Root Cause**: Docker/Minikube caches images and does not overwrite existing images with the same tag.

**Solution (Minikube)**:
```powershell
# 1. Delete old image from minikube
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest

# 2. Rebuild with --no-cache
docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# 3. Load to minikube
minikube -p tesslate image load tesslate-backend:latest

# 4. Delete pod to force restart
kubectl delete pod -n tesslate -l app=tesslate-backend
```

**Solution (AWS EKS)**:
```powershell
# Build with --no-cache and push
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Delete pod to pull new image
kubectl delete pod -n tesslate -l app=tesslate-backend
```

### User Container ImagePullBackOff

**Symptoms**: User project pods fail with `ImagePullBackOff`.

**Diagnosis**:
```powershell
# Check which image is being requested
kubectl describe pod -n proj-<uuid> | grep Image

# Check backend environment
kubectl exec -n tesslate deployment/tesslate-backend -- env | grep K8S_DEVSERVER
```

**Solution**:

For Minikube:
```powershell
# Ensure devserver image is loaded
minikube -p tesslate image load tesslate-devserver:latest

# Verify K8S_DEVSERVER_IMAGE in backend-patch.yaml:
# Should be: tesslate-devserver:latest (no registry prefix)
```

For AWS:
```powershell
# Ensure devserver image is pushed to ECR
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest

# Verify K8S_DEVSERVER_IMAGE includes full ECR path
```

## Network Issues

### 503 Service Unavailable

**Symptoms**: Browser shows 503 error when accessing the application.

**Possible Causes**:

1. **Pod not ready**
   ```powershell
   kubectl get pods -n tesslate
   # Check if pods are in Running state with ready containers
   ```

2. **Service endpoint not updated**
   ```powershell
   # Check service endpoints
   kubectl get endpoints -n tesslate

   # Restart ingress controller
   kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
   ```

3. **Ingress misconfiguration**
   ```powershell
   # Check ingress configuration
   kubectl describe ingress -n tesslate
   ```

### WebSocket Connection Issues

**Symptoms**: Real-time features (chat streaming, live updates) not working.

**Diagnosis**:
```powershell
# Check backend logs for WebSocket errors
kubectl logs -n tesslate deployment/tesslate-backend | grep -i websocket
```

**Common Causes**:

1. **CORS blocking WebSocket**
   - Check that WebSocket origins are included in CORS configuration
   - Verify `APP_DOMAIN` is set correctly

2. **Ingress not configured for WebSocket**
   - Ensure ingress has WebSocket annotations
   - NGINX Ingress requires specific timeout settings

3. **Kubernetes client WebSocket bug**
   ```
   WebSocketBadStatusException: Handshake status 200 OK
   ```
   Fix: Pin kubernetes client to <32.0.0 in pyproject.toml

### CORS Errors

**Symptoms**: Browser console shows CORS errors.

**Diagnosis**:
```javascript
// Browser console error:
Access to fetch at 'https://api.example.com' from origin 'https://app.example.com'
has been blocked by CORS policy
```

**Solution**:

1. Check backend CORS configuration in `main.py`:
   ```python
   # Verify APP_DOMAIN matches your frontend origin
   ```

2. Verify allowed patterns in `DynamicCORSMiddleware`

3. Check that both http and https origins are allowed if needed

## Database Issues

### Connection Errors

**Symptoms**: `Connection refused` or `timeout` errors.

**Diagnosis**:
```powershell
# Check database pod
kubectl get pods -n tesslate | grep postgres

# Check database logs
kubectl logs -n tesslate deployment/tesslate-postgres

# Test connection from backend
kubectl exec -n tesslate deployment/tesslate-backend -- python -c "
from sqlalchemy import create_engine
engine = create_engine('$DATABASE_URL')
conn = engine.connect()
print('Connected!')
"
```

**Common Causes**:

1. **Database not running**
   ```powershell
   kubectl rollout restart deployment/tesslate-postgres -n tesslate
   ```

2. **Wrong DATABASE_URL**
   ```powershell
   # Check the URL format
   kubectl exec -n tesslate deployment/tesslate-backend -- env | grep DATABASE_URL
   # Should be: postgresql+asyncpg://user:pass@host:5432/dbname
   ```

3. **Network policy blocking**
   - Check NetworkPolicy allows backend-to-database traffic

### Migration Errors

**Symptoms**: Alembic migration fails.

**Diagnosis**:
```bash
cd orchestrator
alembic current  # Show current revision
alembic history  # Show migration history
```

**Common Issues**:

1. **Multiple heads**
   ```
   alembic: ERROR: Multiple heads detected
   ```
   Fix: Create a merge migration:
   ```bash
   alembic merge heads -m "merge_heads"
   ```

2. **Missing table**
   ```
   relation "tablename" does not exist
   ```
   Fix: Run all migrations:
   ```bash
   alembic upgrade head
   ```

See [Database Migrations](database-migrations.md) for more details.

## S3 Storage Issues

### S3 Access Errors

**Symptoms**: File uploads/downloads fail with S3 errors.

**Diagnosis**:
```powershell
# Check S3 configuration
kubectl exec -n tesslate deployment/tesslate-backend -- env | grep S3

# Test S3 access
kubectl exec -n tesslate deployment/tesslate-backend -- python -c "
import boto3
s3 = boto3.client('s3', endpoint_url='$S3_ENDPOINT_URL')
print(s3.list_buckets())
"
```

**Common Causes**:

1. **Wrong endpoint URL**
   - Minikube: `http://minio.minio-system.svc.cluster.local:9000`
   - AWS: `https://s3.us-east-1.amazonaws.com`

2. **Missing credentials**
   - Check `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`

3. **Bucket doesn't exist**
   ```powershell
   # Create bucket if needed
   aws s3 mb s3://tesslate-project-storage-prod --region us-east-1
   ```

### S3 Hydration Failures

**Symptoms**: User container init container fails with hydration error.

**Diagnosis**:
```powershell
# Check init container logs
kubectl logs -n proj-<uuid> <pod-name> -c hydrate-project
```

**Common Causes**:

1. **S3 bucket or object not found**
   - Check if project files exist in S3

2. **Permission denied**
   - Verify IAM permissions for the S3 bucket

## SSL Certificate Issues

### Certificate Not Valid

**Symptoms**: Browser shows certificate warning.

**Diagnosis**:
```powershell
# Check certificate status
kubectl get certificate -n tesslate
kubectl describe certificate tesslate-wildcard-tls -n tesslate

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager --tail=50
```

**Common Causes**:

1. **DNS not propagated**
   - Wait for DNS propagation (up to 24-48 hours)

2. **Cloudflare API token invalid**
   - Token needs Zone:Zone:Read and Zone:DNS:Edit permissions

3. **Wildcard cert subdomain limitation**
   - `*.domain.com` only covers one level
   - `foo.bar.domain.com` requires separate cert or Cloudflare proxy

## Agent/Chat Issues

### Agent Not Responding

**Symptoms**: Chat messages don't get responses.

**Diagnosis**:
```powershell
# Check backend logs for chat errors
kubectl logs -n tesslate deployment/tesslate-backend | grep -i "chat\|agent"

# Check LiteLLM configuration
kubectl exec -n tesslate deployment/tesslate-backend -- env | grep LITELLM
```

**Common Causes**:

1. **Missing API key**
   ```powershell
   kubectl exec -n tesslate deployment/tesslate-backend -- env | grep LITELLM_API_KEY
   ```

2. **Rate limiting**
   - Check for rate limit errors in logs
   - Implement exponential backoff

3. **Model not available**
   - Verify model name in `LITELLM_DEFAULT_MODEL`

### Tool Execution Failures

**Symptoms**: Agent tool calls fail.

**Diagnosis**:
```powershell
# Check for tool execution errors
kubectl logs -n tesslate deployment/tesslate-backend | grep -i "tool\|execute"
```

**Common Causes**:

1. **Container not running**
   - Ensure user project container is started

2. **File path issues**
   - Check file path format (relative to project root)

3. **Permission denied**
   - Check container has write access

## Performance Issues

### Slow Response Times

**Diagnosis**:
```powershell
# Check resource usage
kubectl top pods -n tesslate
kubectl top nodes

# Check for resource limits
kubectl describe pod -n tesslate <pod-name> | grep -A5 Limits
```

**Solutions**:

1. **Increase resource limits**
   - Edit deployment to increase CPU/memory limits

2. **Enable horizontal scaling**
   - Add HPA for auto-scaling

3. **Optimize database queries**
   - Add indexes for frequently queried fields

### Memory Issues

**Symptoms**: Pod killed with `OOMKilled`.

**Solution**:
```yaml
# Increase memory limit in deployment
resources:
  limits:
    memory: "2Gi"  # Increase from default
  requests:
    memory: "1Gi"
```

## Quick Diagnostic Commands

```powershell
# Overall cluster health
kubectl get pods --all-namespaces
kubectl get events --all-namespaces --sort-by=.lastTimestamp | tail -20

# Tesslate-specific
kubectl get pods -n tesslate -o wide
kubectl describe pods -n tesslate
kubectl logs -n tesslate deployment/tesslate-backend --tail=100
kubectl logs -n tesslate deployment/tesslate-frontend --tail=100

# User projects
kubectl get pods --all-namespaces | grep proj-
kubectl get ingress --all-namespaces | grep proj-

# Resource usage
kubectl top pods -n tesslate
kubectl top nodes

# Network
kubectl get svc -n tesslate
kubectl get endpoints -n tesslate
kubectl get ingress -n tesslate -o yaml
```

## Getting Help

If you cannot resolve an issue:

1. Collect diagnostic information:
   ```powershell
   kubectl get pods -n tesslate -o yaml > pods.yaml
   kubectl logs -n tesslate deployment/tesslate-backend > backend.log
   kubectl describe pods -n tesslate > describe.txt
   ```

2. Check for known issues in CLAUDE.md

3. Search the codebase for error messages

4. Create a detailed issue report with:
   - Steps to reproduce
   - Expected vs actual behavior
   - Relevant logs and configuration
   - Environment (Minikube/AWS, versions)

## Next Steps

- [Image Update Workflow](image-update-workflow.md) - Proper deployment process
- [Database Migrations](database-migrations.md) - Schema change procedures
- [Minikube Setup](minikube-setup.md) - Local Kubernetes setup
- [AWS Deployment](aws-deployment.md) - Production deployment
