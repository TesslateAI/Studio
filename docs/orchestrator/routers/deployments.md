# Deployments Router

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/deployments.py` (923 lines)

The deployments router handles external deployments to production hosting providers like Vercel, Netlify, and Cloudflare Workers.

## Overview

Tesslate Studio supports deploying projects to external hosting providers for production use. The internal dev environments (Docker/Kubernetes) are for development only; external deployments are for live websites.

Supported providers:
- **Vercel**: Ideal for Next.js, React, Vue
- **Netlify**: Great for static sites and serverless functions
- **Cloudflare Workers**: Edge computing, ultra-fast global delivery

## Base Path

All endpoints are mounted at `/api/deployments`

## Deployment Operations

### Create Deployment

```
POST /api/deployments/
```

Deploys a project to a hosting provider.

**Request Body**:
```json
{
  "project_id": "uuid",
  "provider": "vercel|netlify|cloudflare",
  "deployment_mode": "source|pre-built",  // Optional
  "custom_domain": "myapp.com",            // Optional
  "env_vars": {
    "API_URL": "https://api.myapp.com",
    "DATABASE_URL": "postgresql://..."
  },
  "build_command": "npm run build",        // Optional override
  "framework": "nextjs"                    // Optional, auto-detected if not provided
}
```

**Response**:
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "provider": "vercel",
  "deployment_id": "dpl_xxx",
  "deployment_url": "https://my-app-abc123.vercel.app",
  "status": "building",
  "created_at": "2025-01-09T10:00:00Z"
}
```

**Deployment Modes**:

1. **Source Mode** (default for Vercel/Netlify):
   - Uploads source code to provider
   - Provider builds the project
   - Best for frameworks with build optimization

2. **Pre-Built Mode** (default for Cloudflare):
   - Tesslate builds project locally
   - Uploads built files
   - Faster deployment, more control

**Behind the Scenes**:

1. Fetch OAuth credentials for provider
2. Detect framework if not specified
3. Build project (if pre-built mode)
4. Create deployment via provider API
5. Stream build logs to database
6. Update deployment status

### Get Deployment Status

```
GET /api/deployments/{deployment_id}/status
```

Returns current deployment status and live URL.

**Response**:
```json
{
  "status": "queued|building|deploying|ready|error",
  "deployment_url": "https://my-app-abc123.vercel.app",
  "provider_status": {
    "readyState": "READY",
    "buildingAt": "2025-01-09T10:01:00Z",
    "readyAt": "2025-01-09T10:03:30Z"
  },
  "updated_at": "2025-01-09T10:03:30Z"
}
```

**Status Flow**:
- `queued` → `building` → `deploying` → `ready`
- Or: `queued` → `error` (if build fails)

### Get Deployment Logs

```
GET /api/deployments/{deployment_id}/logs
```

Returns build and deployment logs.

**Response**:
```json
{
  "logs": [
    "[2025-01-09 10:01:00] Installing dependencies...",
    "[2025-01-09 10:01:15] npm install completed",
    "[2025-01-09 10:01:20] Running build command...",
    "[2025-01-09 10:02:45] Build completed successfully",
    "[2025-01-09 10:03:00] Deploying to CDN...",
    "[2025-01-09 10:03:30] Deployment complete!"
  ],
  "deployment_id": "uuid"
}
```

### Redeploy

```
POST /api/deployments/{deployment_id}/redeploy
```

Triggers a new deployment using the same configuration.

**Response**: New Deployment object

**Use Cases**:
- Deploy after code changes
- Retry failed deployment
- Update environment variables

### Delete Deployment

```
DELETE /api/deployments/{deployment_id}
```

Deletes a deployment from the provider.

**Response**:
```json
{
  "message": "Deployment deleted successfully"
}
```

**Note**: This removes the deployment from the provider but keeps the database record (status set to "deleted").

### List Deployments

```
GET /api/deployments/
```

Returns all deployments for the authenticated user.

**Query Parameters**:
- `project_id`: Filter by project (optional)
- `provider`: Filter by provider (optional)
- `status`: Filter by status (optional)

**Response**:
```json
{
  "deployments": [
    {
      "id": "uuid",
      "project_id": "uuid",
      "provider": "vercel",
      "deployment_url": "https://my-app.vercel.app",
      "status": "ready",
      "created_at": "2025-01-09T10:00:00Z"
    }
  ],
  "total": 15
}
```

## Provider-Specific Details

### Vercel

**Features**:
- Automatic framework detection
- Edge caching
- Serverless functions
- Custom domains
- Preview deployments per commit

**API Used**: Vercel REST API v13
**Auth**: OAuth token or deployment token

**Deployment Request**:
```python
import httpx

async with httpx.AsyncClient() as client:
    response = await client.post(
        "https://api.vercel.com/v13/deployments",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": project.slug,
            "files": [...],  # Source files
            "projectSettings": {
                "framework": "nextjs",
                "buildCommand": "npm run build",
                "outputDirectory": ".next"
            }
        }
    )
```

### Netlify

**Features**:
- Drag-and-drop deployments
- Form handling
- Split testing
- Large file storage
- Netlify functions (serverless)

**API Used**: Netlify API v1
**Auth**: OAuth token or personal access token

**Deployment Request**:
```python
# Upload files to Netlify
response = await client.post(
    f"https://api.netlify.com/api/v1/sites/{site_id}/deploys",
    headers={"Authorization": f"Bearer {token}"},
    files={"file": open(tarball, "rb")}
)
```

### Cloudflare Workers

**Features**:
- Edge computing (runs on 300+ locations)
- Ultra-low latency
- KV storage
- Durable Objects
- WebSockets support

**API Used**: Cloudflare Workers API
**Auth**: API token

**Deployment Request**:
```python
# Upload worker script
response = await client.put(
    f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/scripts/{script_name}",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/javascript"
    },
    data=worker_script
)
```

## Framework Detection

The `FrameworkDetector` service auto-detects project frameworks:

```python
from ..services.framework_detector import FrameworkDetector

detector = FrameworkDetector(project_path)
framework = detector.detect()

# Returns: "nextjs", "react", "vue", "angular", "svelte", "static", etc.
```

**Detection Methods**:
1. Check `package.json` dependencies
2. Look for framework-specific files (`next.config.js`, `vite.config.ts`)
3. Analyze project structure

**Framework Configs**:
```python
FRAMEWORK_CONFIGS = {
    "nextjs": {
        "build_command": "npm run build",
        "output_directory": ".next",
        "dev_command": "npm run dev"
    },
    "react": {
        "build_command": "npm run build",
        "output_directory": "build",
        "dev_command": "npm start"
    },
    "vue": {
        "build_command": "npm run build",
        "output_directory": "dist",
        "dev_command": "npm run serve"
    }
}
```

## Deployment Builder Service

The `DeploymentBuilder` service handles project builds:

```python
from ..services.deployment.builder import get_deployment_builder

builder = get_deployment_builder(provider, project_path)

# Build project
build_result = await builder.build(
    framework="nextjs",
    env_vars={"NODE_ENV": "production"},
    build_command="npm run build"  # Optional override
)

# Returns build output directory
output_dir = build_result["output_dir"]
```

**Build Steps**:
1. Install dependencies (`npm install`)
2. Set environment variables
3. Run build command
4. Verify output directory exists
5. Return build artifacts

## Deployment Manager Service

The `DeploymentManager` service orchestrates deployments:

```python
from ..services.deployment.manager import DeploymentManager

manager = DeploymentManager(db)

# Create deployment
deployment = await manager.create_deployment(
    project_id=project_id,
    provider="vercel",
    config={
        "env_vars": {...},
        "custom_domain": "myapp.com"
    }
)

# Monitor deployment
status = await manager.get_deployment_status(deployment.id)
```

## OAuth Credentials

Deployments require OAuth credentials for each provider. These are stored in the `DeploymentCredential` model:

```python
class DeploymentCredential(Base):
    user_id: UUID
    provider: str  # "vercel", "netlify", "cloudflare"
    access_token: str  # Encrypted
    refresh_token: str  # Encrypted (if supported)
    expires_at: datetime
    project_id: UUID  # Optional, project-specific credential
    metadata: dict  # Provider-specific data (account_id, team_id, etc.)
```

### Setting Up OAuth

1. **User connects provider**:
   ```
   GET /api/deployment-oauth/vercel/authorize
   ```

2. **Redirected to provider OAuth**

3. **User authorizes Tesslate**

4. **Callback with code**:
   ```
   GET /api/deployment-oauth/vercel/callback?code=xxx
   ```

5. **Backend exchanges code for token**

6. **Token stored encrypted**

7. **User can now deploy to provider**

## Example Workflows

### Deploying Next.js App to Vercel

1. **User creates Next.js project in Tesslate**

2. **User builds app with agent**

3. **User clicks "Deploy to Vercel"**:
   ```
   POST /api/deployments/
   {
     "project_id": "uuid",
     "provider": "vercel"
   }
   ```

4. **Backend processes**:
   - Checks OAuth credentials
   - Detects framework: "nextjs"
   - Creates Vercel deployment
   - Uploads source files
   - Monitors build progress

5. **Build completes**:
   - Status: "ready"
   - URL: `https://my-app-abc123.vercel.app`

6. **User accesses live site**

### Deploying Static Site to Netlify

1. **User creates static site**

2. **Pre-build locally**:
   ```
   POST /api/deployments/
   {
     "project_id": "uuid",
     "provider": "netlify",
     "deployment_mode": "pre-built"
   }
   ```

3. **Backend builds**:
   ```bash
   npm install
   npm run build
   ```

4. **Backend uploads build output** (`dist/` folder)

5. **Netlify deploys**:
   - URL: `https://my-site.netlify.app`

6. **Custom domain** (optional):
   ```
   PATCH /api/deployments/{id}
   {"custom_domain": "www.mysite.com"}
   ```

7. **User configures DNS** (CNAME to Netlify)

8. **Site live on custom domain**

## Security

1. **Credential Encryption**: OAuth tokens encrypted at rest
2. **Token Refresh**: Automatic token refresh when expired
3. **Project Ownership**: Only owner can deploy project
4. **Environment Variable Encryption**: Sensitive env vars encrypted
5. **Build Isolation**: Each build runs in isolated environment

## Monitoring

Deployments are monitored in real-time:

```python
# Poll deployment status every 5 seconds
while deployment.status in ["queued", "building", "deploying"]:
    await asyncio.sleep(5)
    status = await provider.get_deployment_status(deployment.deployment_id)
    deployment.status = status
    await db.commit()
```

Frontend can poll `GET /api/deployments/{id}/status` to show progress.

## Related Files

- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/deployment/manager.py` - Deployment orchestration
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/deployment/builder.py` - Project building
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/framework_detector.py` - Framework detection
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/deployment_credentials.py` - Credential management
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/deployment_oauth.py` - OAuth flows
