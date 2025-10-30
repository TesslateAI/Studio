# Configuration Guide

Complete reference for all Tesslate Studio environment variables and configuration options.

## Configuration File

All configuration is done through the `.env` file in the root directory. Start by copying the example:

```bash
cp .env.example .env
```

## Required Variables

These variables must be set for Tesslate Studio to function.

### SECRET_KEY

**Description**: Secret key for JWT token signing and session encryption.

**Required**: Yes

**Generate**:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Example**:
```env
SECRET_KEY=your-generated-secret-key-here
```

### LITELLM_MASTER_KEY

**Description**: Master key for LiteLLM proxy authentication.

**Required**: Yes

**Generate**:
```bash
python -c "import secrets; print('sk-' + secrets.token_urlsafe(32))"
```

**Example**:
```env
LITELLM_MASTER_KEY=sk-your-litellm-master-key
```

### AI Provider API Keys

**Description**: At least one AI provider API key is required.

**Required**: At least one

**Supported Providers**:

```env
# OpenAI (GPT-5, GPT-4, GPT-3.5)
OPENAI_API_KEY=sk-your-openai-key

# Anthropic (Claude 3.5, Claude 3)
ANTHROPIC_API_KEY=sk-your-anthropic-key

# Google Gemini
GOOGLE_API_KEY=your-google-api-key

# Azure OpenAI
AZURE_API_KEY=your-azure-key
AZURE_API_BASE=https://your-resource.openai.azure.com
AZURE_API_VERSION=2024-02-15-preview
```

## Optional Variables

### Application Settings

#### APP_DOMAIN

**Description**: Domain where Tesslate Studio is hosted.

**Default**: `studio.localhost`

**Example**:
```env
# Local development
APP_DOMAIN=studio.localhost

# Production
APP_DOMAIN=studio.yourcompany.com
```

#### APP_PROTOCOL

**Description**: Protocol for accessing the application.

**Default**: `http`

**Options**: `http`, `https`

**Example**:
```env
# Local
APP_PROTOCOL=http

# Production with SSL
APP_PROTOCOL=https
```

#### FRONTEND_URL

**Description**: Full URL where the frontend is accessible.

**Default**: `http://studio.localhost`

**Example**:
```env
FRONTEND_URL=https://studio.yourcompany.com
```

### Database Configuration

#### DATABASE_URL

**Description**: PostgreSQL connection string.

**Default**: Uses Docker PostgreSQL container

**Format**: `postgresql+asyncpg://user:password@host:port/database`

**Example**:
```env
# Docker default (no change needed)
DATABASE_URL=postgresql+asyncpg://tesslate:tesslate_password@postgres:5432/tesslate_db

# External managed database
DATABASE_URL=postgresql+asyncpg://admin:secure_pass@db.yourcompany.com:5432/tesslate
```

#### POSTGRES_USER

**Description**: PostgreSQL username (Docker only).

**Default**: `tesslate`

#### POSTGRES_PASSWORD

**Description**: PostgreSQL password (Docker only).

**Default**: `tesslate_password`

**Example**:
```env
POSTGRES_PASSWORD=your-secure-database-password
```

#### POSTGRES_DB

**Description**: PostgreSQL database name (Docker only).

**Default**: `tesslate_db`

### LiteLLM Configuration

#### LITELLM_DEFAULT_MODELS

**Description**: Comma-separated list of default AI models.

**Default**: `gpt-5o-mini,claude-3-haiku,gemini-pro`

**Example**:
```env
# Use only GPT-5 models
LITELLM_DEFAULT_MODELS=gpt-5o,gpt-5o-mini

# Mix of providers
LITELLM_DEFAULT_MODELS=gpt-5o-mini,claude-3-haiku,gemini-flash
```

#### LITELLM_INITIAL_BUDGET

**Description**: Initial API budget per user (USD).

**Default**: `10.0`

**Example**:
```env
# $50 initial budget
LITELLM_INITIAL_BUDGET=50.0
```

#### LITELLM_PROXY_URL

**Description**: LiteLLM proxy endpoint URL.

**Default**: `http://litellm:4000`

**Example**:
```env
# External LiteLLM instance
LITELLM_PROXY_URL=http://litellm.yourcompany.com:4000
```

### Container Runtime

#### CONTAINER_MODE

**Description**: Container orchestration system to use.

**Default**: `docker`

**Options**: `docker`

**Example**:
```env
CONTAINER_MODE=docker
```

#### DOCKER_SOCKET_PATH

**Description**: Path to Docker socket for container management.

**Default**: `/var/run/docker.sock` (Linux/Mac), `//./pipe/docker_engine` (Windows)

**Example**:
```env
# Linux/Mac
DOCKER_SOCKET_PATH=/var/run/docker.sock

# Windows
DOCKER_SOCKET_PATH=//./pipe/docker_engine
```

### Auto-Seeding

#### AUTO_SEED_DATABASE

**Description**: Automatically seed database with agents and templates on startup.

**Default**: `true`

**Options**: `true`, `false`

**Example**:
```env
# Enable auto-seeding (recommended)
AUTO_SEED_DATABASE=true

# Disable for manual control
AUTO_SEED_DATABASE=false
```

**What gets seeded**:
- 4 marketplace agents (Stream Builder, Full Stack Agent, etc.)
- 3 project templates (Next.js, Vite+React+FastAPI, Vite+React+Go)
- 6 open-source customizable agents

### GitHub Integration

#### GITHUB_CLIENT_ID

**Description**: GitHub OAuth app client ID.

**Required**: For GitHub integration

**Setup**: Create OAuth app at https://github.com/settings/developers

**Example**:
```env
GITHUB_CLIENT_ID=your-github-client-id
```

#### GITHUB_CLIENT_SECRET

**Description**: GitHub OAuth app client secret.

**Required**: For GitHub integration

**Example**:
```env
GITHUB_CLIENT_SECRET=your-github-client-secret
```

### Logging

#### LOG_LEVEL

**Description**: Application logging level.

**Default**: `INFO`

**Options**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

**Example**:
```env
# Development
LOG_LEVEL=DEBUG

# Production
LOG_LEVEL=INFO
```

## Docker Compose Configuration

Some settings are configured in `docker-compose.yml` rather than `.env`:

### Port Mappings

By default:
- **Port 80**: Main application (Traefik proxy)
- **Port 8080**: Traefik dashboard (development only)

To change ports, edit `docker-compose.yml`:

```yaml
services:
  traefik:
    ports:
      - "8000:80"  # Change main port to 8000
```

### Resource Limits

Set memory/CPU limits in `docker-compose.yml`:

```yaml
services:
  orchestrator:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G
```

## Production Configuration

Recommended settings for production deployments:

```env
# Security
SECRET_KEY=<strong-random-key>
LITELLM_MASTER_KEY=sk-<strong-random-key>

# Domain
APP_DOMAIN=studio.yourcompany.com
APP_PROTOCOL=https
FRONTEND_URL=https://studio.yourcompany.com

# Database (use managed service)
DATABASE_URL=postgresql+asyncpg://user:pass@managed-db.provider.com:5432/tesslate

# Logging
LOG_LEVEL=INFO

# Auto-seed (optional in production)
AUTO_SEED_DATABASE=false
```

## Local AI Models (Ollama)

To use local AI models with Ollama:

1. **Install Ollama**: https://ollama.ai/download
2. **Pull a model**:
   ```bash
   ollama pull llama2
   ```
3. **Configure LiteLLM** to use Ollama endpoint:
   ```env
   LITELLM_DEFAULT_MODELS=ollama/llama2
   ```

## Environment Variable Precedence

Configuration is loaded in this order (later overrides earlier):

1. Default values in code
2. `.env` file
3. Environment variables set in shell
4. Docker Compose environment section

## Validation

To validate your configuration:

```bash
# Check all services are running
docker compose ps

# Check orchestrator logs for config errors
docker compose logs orchestrator | grep -i error

# Test database connection
docker compose exec orchestrator python -c "from app.database import get_db; print('DB connected')"
```

## Troubleshooting

### "Invalid SECRET_KEY"

**Problem**: SECRET_KEY is missing or invalid.

**Solution**: Generate a new key and update `.env`:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### "Database connection failed"

**Problem**: PostgreSQL is not accessible.

**Solution**:
```bash
# Check if postgres container is running
docker compose ps postgres

# Restart database
docker compose restart postgres

# Check logs
docker compose logs postgres
```

### "API key not found"

**Problem**: Missing or invalid AI provider API key.

**Solution**:
1. Verify key in `.env` has no extra spaces
2. Test key with provider directly
3. Restart orchestrator:
   ```bash
   docker compose restart orchestrator
   ```

## Configuration Examples

### Minimal Setup (Free Tier)

```env
SECRET_KEY=<generated>
LITELLM_MASTER_KEY=sk-<generated>
# No paid API keys - use local models
LITELLM_DEFAULT_MODELS=ollama/llama2
```

### Development Setup

```env
SECRET_KEY=dev-secret-key-not-for-production
LITELLM_MASTER_KEY=sk-dev-master-key
OPENAI_API_KEY=sk-your-dev-key
LOG_LEVEL=DEBUG
AUTO_SEED_DATABASE=true
```

### Production Setup

```env
SECRET_KEY=<strong-random-key>
LITELLM_MASTER_KEY=sk-<strong-random-key>
APP_DOMAIN=studio.company.com
APP_PROTOCOL=https
OPENAI_API_KEY=sk-your-prod-key
ANTHROPIC_API_KEY=sk-your-prod-key
DATABASE_URL=postgresql+asyncpg://user:pass@managed-db:5432/tesslate
LOG_LEVEL=INFO
AUTO_SEED_DATABASE=false
```

## Getting Help

If you're having configuration issues:

- **[GitHub Issues](https://github.com/TesslateAI/Studio/issues)** - Report bugs
- **[GitHub Discussions](https://github.com/TesslateAI/Studio/discussions)** - Ask questions
- **[Email Support](mailto:support@tesslate.com)** - Direct support
