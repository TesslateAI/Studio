# Deployment Providers - External Platform Deployments

**Directory**: `orchestrator/app/services/deployment/`

Multi-provider deployment system for publishing user projects to external platforms. Providers are grouped into source-push (Vercel, Netlify, Fly), container-push (AWS, GCP, Azure, DO, Fly, Koyeb, Northflank, Railway, Render, Heroku, Zeabur), and export (Docker Hub, GHCR, download zip, GitHub Pages, Surge, Firebase).

## Files covered

### Framework and factories

| File | Purpose |
|------|---------|
| `deployment/__init__.py` | Re-exports `BaseDeploymentProvider`, config types. |
| `deployment/base.py` | `BaseDeploymentProvider` ABC plus `DeploymentConfig`, `DeploymentFile`, `DeploymentResult` models. |
| `deployment/container_base.py` | Base class for container-push providers (AWS ECS, GCP Cloud Run, Azure Container Apps, etc.). |
| `deployment/manager.py` | `DeploymentManager` factory. |
| `deployment/builder.py` | `DeploymentBuilder` coordinates build before deploy (detect framework, npm install, npm build, verify output). |
| `deployment/guards.py` | Validates container-to-provider compatibility (uses `service_definitions.DEPLOYMENT_COMPATIBILITY`). |
| `deployment/providers/__init__.py` | Re-exports. |
| `deployment/providers/utils.py` | Shared helpers (file-collection, hash, chunked upload). |

### Providers

| File | Provider | Auth | Mode |
|------|----------|------|------|
| `providers/vercel.py` | Vercel | OAuth token | source-push |
| `providers/netlify.py` | Netlify | OAuth token | source-push |
| `providers/cloudflare.py` | Cloudflare Workers | API token | source-push |
| `providers/fly.py` | Fly.io | API token | container-push (Fly Machines) |
| `providers/railway.py` | Railway | API token | container-push |
| `providers/render.py` | Render | API token | container-push |
| `providers/heroku.py` | Heroku | API token | container-push |
| `providers/koyeb.py` | Koyeb | API token | container-push |
| `providers/northflank.py` | Northflank | API token | container-push |
| `providers/zeabur.py` | Zeabur | API token | container-push |
| `providers/aws_container.py` | AWS ECR + App Runner | IAM | container-push |
| `providers/gcp_container.py` | GCP Artifact Registry + Cloud Run | service account | container-push |
| `providers/azure_container.py` | Azure ACR + Container Apps | service principal | container-push |
| `providers/do_container.py` | DigitalOcean DOCR + App Platform | API token | container-push |
| `providers/firebase.py` | Firebase Hosting | service account | source-push |
| `providers/deno_deploy.py` | Deno Deploy | API token | source-push |
| `providers/github_pages.py` | GitHub Pages | OAuth token | source-push |
| `providers/surge.py` | Surge.sh | CLI token | source-push |
| `providers/dockerhub_export.py` | Docker Hub | registry credentials | export (image push only) |
| `providers/ghcr_export.py` | GitHub Container Registry | OAuth token | export (image push only) |
| `providers/download_export.py` | User download | none | export (zip) |

## Overview

The deployment system uses a factory pattern with an abstract base class. Source-push providers inherit from `BaseDeploymentProvider`; container-push providers inherit from `ContainerDeploymentBase` (in `container_base.py`), which adds image-build and registry-push steps.

```
BaseDeploymentProvider (Abstract)
├── Source-push providers (Vercel, Netlify, Cloudflare, Firebase, Deno, GitHub Pages, Surge)
├── ContainerDeploymentBase (Abstract)
│   └── Container-push providers (AWS, GCP, Azure, DO, Fly, Koyeb, Northflank, Railway, Render, Heroku, Zeabur)
└── Export providers (Docker Hub, GHCR, download zip)

DeploymentManager: factory + registry
DeploymentBuilder: build process coordination
DeploymentGuards: container-to-provider compatibility checks
```

## Architecture

### Core Files

- **base.py** (276 lines) - `BaseDeploymentProvider` abstract class
- **manager.py** (180 lines) - `DeploymentManager` factory
- **builder.py** - Build process coordination
- **providers/vercel.py** - Vercel implementation
- **providers/netlify.py** - Netlify implementation
- **providers/cloudflare.py** - Cloudflare Workers implementation

## Base Provider Interface

```python
# deployment/base.py
class BaseDeploymentProvider(ABC):
    """Abstract base for deployment providers."""

    @abstractmethod
    async def deploy(
        self,
        files: List[DeploymentFile],
        config: DeploymentConfig
    ) -> DeploymentResult:
        """Deploy files to provider."""
        pass

    @abstractmethod
    async def get_deployment_status(self, deployment_id: str) -> Dict:
        """Get deployment status."""
        pass

    @abstractmethod
    async def delete_deployment(self, deployment_id: str) -> bool:
        """Delete deployment."""
        pass

    @abstractmethod
    async def test_credentials(self) -> Dict:
        """Validate credentials with real API call."""
        pass
```

### Data Models

```python
class DeploymentFile(BaseModel):
    """File to deploy."""
    path: str
    content: bytes
    encoding: str = "utf-8"

class DeploymentConfig(BaseModel):
    """Deployment configuration."""
    project_id: str
    project_name: str
    framework: str  # vite, nextjs, react
    deployment_mode: str  # "source" or "pre-built"
    build_command: Optional[str]
    env_vars: Dict[str, str]
    custom_domain: Optional[str]

class DeploymentResult(BaseModel):
    """Deployment result."""
    success: bool
    deployment_id: Optional[str]
    deployment_url: Optional[str]
    logs: List[str]
    error: Optional[str]
```

## Usage

### Deploy Project

```python
from services.deployment.manager import DeploymentManager
from services.deployment.base import DeploymentConfig

# Deploy to Vercel
result = await DeploymentManager.deploy_project(
    project_path="/projects/my-app",
    provider_name="vercel",
    credentials={"token": "vercel_token", "team_id": "team_xyz"},
    config=DeploymentConfig(
        project_id="123",
        project_name="my-app",
        framework="vite",
        deployment_mode="pre-built",  # or "source"
        env_vars={"API_URL": "https://api.example.com"}
    ),
    build_output_dir="dist"
)

if result.success:
    print(f"Deployed to: {result.deployment_url}")
else:
    print(f"Deployment failed: {result.error}")
    for log in result.logs:
        print(log)
```

## Vercel Provider

**File**: `deployment/providers/vercel.py`

### Features
- Automatic builds for source deployments
- Pre-built static file uploads
- Framework detection (Vite, Next.js, React)
- Build status polling
- Team support

### Deployment Modes

**Pre-Built Mode** (Recommended):
```python
config = DeploymentConfig(
    deployment_mode="pre-built",
    framework="vite"
)
# Uploads dist/ files directly, no build on Vercel
```

**Source Mode**:
```python
config = DeploymentConfig(
    deployment_mode="source",
    framework="vite",
    build_command="npm run build"
)
# Vercel builds the project
```

### Example

```python
from services.deployment.manager import DeploymentManager

# Get Vercel provider
provider = DeploymentManager.get_provider(
    "vercel",
    {"token": "vercel_...", "team_id": "team_..."}
)

# Test credentials
try:
    info = await provider.test_credentials()
    print(f"Connected to Vercel team: {info['team_name']}")
except ValueError as e:
    print(f"Invalid credentials: {e}")

# Deploy
files = await provider.collect_files_from_container("/projects/my-app", "dist")
config = DeploymentConfig(...)
result = await provider.deploy(files, config)
```

## Netlify Provider

**File**: `deployment/providers/netlify.py`

### Features
- Optimized file uploads (SHA-256 deduplication)
- Deploy previews for branches
- Serverless functions
- Form handling

### Example

```python
provider = DeploymentManager.get_provider(
    "netlify",
    {"token": "netlify_..."}
)

result = await provider.deploy(files, config)
```

## Cloudflare Workers Provider

**File**: `deployment/providers/cloudflare.py`

### Features
- Edge compute deployment
- KV storage integration
- Wrangler-compatible
- Pages (static) + Workers (serverless)

### Example

```python
provider = DeploymentManager.get_provider(
    "cloudflare",
    {
        "account_id": "abc123",
        "api_token": "cf_...",
        "dispatch_namespace": "production"
    }
)

result = await provider.deploy(files, config)
```

## Deployment Manager (Factory)

```python
# List available providers
providers = DeploymentManager.list_available_providers()
# Returns: [
#   {
#       "name": "vercel",
#       "display_name": "Vercel",
#       "auth_type": "oauth",
#       "required_credentials": ["token"]
#   },
#   ...
# ]

# Check if provider available
if DeploymentManager.is_provider_available("vercel"):
    provider = DeploymentManager.get_provider("vercel", creds)

# Register custom provider
DeploymentManager.register_provider("custom", CustomProvider)
```

## Build Process

```python
# deployment/builder.py
class DeploymentBuilder:
    """Coordinates build process before deployment."""

    async def build_project(
        self,
        project_path: str,
        framework: str,
        build_command: Optional[str] = None
    ) -> str:
        """
        Build project and return output directory.

        1. Detect framework if not provided
        2. Install dependencies (npm install)
        3. Run build command
        4. Verify build output exists
        5. Return output directory path
        """
        # Get framework config
        config = self.get_framework_config(framework)

        # Install dependencies
        await self._run_command(
            project_path,
            config['install_command']  # npm install
        )

        # Build
        build_cmd = build_command or config['build_command']
        await self._run_command(project_path, build_cmd)

        # Verify output
        output_dir = os.path.join(project_path, config['output_dir'])
        if not os.path.exists(output_dir):
            raise RuntimeError(f"Build output not found: {output_dir}")

        return output_dir
```

## Framework Detection

```python
def get_framework_config(framework: str) -> Dict:
    """Get framework-specific configuration."""
    configs = {
        "vite": {
            "build_command": "npm run build",
            "output_dir": "dist",
            "install_command": "npm install"
        },
        "nextjs": {
            "build_command": "npm run build",
            "output_dir": ".next",
            "install_command": "npm install",
            "requires_server": True
        },
        "react": {
            "build_command": "npm run build",
            "output_dir": "build",
            "install_command": "npm install"
        }
    }
    return configs.get(framework, configs["vite"])
```

## Credential Storage

Deployment credentials are stored encrypted in the database:

```python
# models.py
class DeploymentCredential(Base):
    __tablename__ = "deployment_credentials"

    user_id = Column(UUID, ForeignKey("users.id"))
    provider = Column(String)  # "vercel", "netlify", "cloudflare"
    credentials = Column(JSON)  # Encrypted
    created_at = Column(DateTime)

# services/credential_manager.py
from cryptography.fernet import Fernet

class CredentialManager:
    """Encrypt/decrypt deployment credentials."""

    def encrypt(self, data: Dict) -> str:
        """Encrypt credentials."""
        json_data = json.dumps(data)
        encrypted = self.cipher.encrypt(json_data.encode())
        return base64.b64encode(encrypted).decode()

    def decrypt(self, encrypted_data: str) -> Dict:
        """Decrypt credentials."""
        encrypted = base64.b64decode(encrypted_data)
        decrypted = self.cipher.decrypt(encrypted)
        return json.loads(decrypted.decode())
```

## OAuth Integration

For providers using OAuth (Vercel, Netlify):

```python
# routers/deployments.py
@router.get("/oauth/vercel/callback")
async def vercel_oauth_callback(code: str, user: User, db: AsyncSession):
    """Handle Vercel OAuth callback."""

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.vercel.com/v2/oauth/access_token",
            json={
                "client_id": settings.vercel_client_id,
                "client_secret": settings.vercel_client_secret,
                "code": code,
                "redirect_uri": "https://app.tesslate.com/api/deployments/oauth/vercel/callback"
            }
        )
        token_data = response.json()

    # Save encrypted credentials
    cred_manager = CredentialManager()
    encrypted = cred_manager.encrypt({"token": token_data['access_token']})

    credential = DeploymentCredential(
        user_id=user.id,
        provider="vercel",
        credentials=encrypted
    )
    db.add(credential)
    await db.commit()

    return RedirectResponse("/deployments")
```

## Common Patterns

### Pre-Build Locally, Deploy

```python
# 1. Build in user's container
orchestrator = get_orchestrator()
await orchestrator.execute_command(
    user_id, project_id, container_name,
    ["npm", "run", "build"]
)

# 2. Collect built files
files = await provider.collect_files_from_container(
    project_path="/projects/my-app",
    build_output_dir="dist"
)

# 3. Deploy to provider
result = await provider.deploy(files, config)
```

### Monitor Deployment

```python
# Poll status until ready
while True:
    status = await provider.get_deployment_status(deployment_id)

    if status['state'] == 'READY':
        print(f"Deployed: {status['url']}")
        break
    elif status['state'] == 'ERROR':
        print(f"Failed: {status['error']}")
        break

    await asyncio.sleep(5)
```

## Troubleshooting

**Problem**: Build fails in deployment
- Use `deployment_mode="pre-built"` to build locally first
- Check build logs in Vercel/Netlify dashboard
- Verify environment variables are set

**Problem**: "Invalid credentials" error
- Re-authenticate with provider
- Check OAuth token hasn't expired
- Verify API key has correct permissions

**Problem**: Files not uploading
- Check file size limits (Vercel: 100MB, Netlify: 200MB)
- Verify `collect_files_from_container()` finds files
- Check network connectivity to provider API

## Related Documentation

- [orchestration.md](./orchestration.md) - Execute build commands
- [credential_manager.md](./credential-manager.md) - Encrypt credentials
- [../routers/deployments.md](../routers/deployments.md) - Deployment API
