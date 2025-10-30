# Quick Start Guide

Get Tesslate Studio running in 5 minutes.

## Prerequisites

Before you begin, make sure you have:

- **Docker Desktop** (Windows/Mac) or **Docker Engine** (Linux)
  - [Download Docker Desktop](https://www.docker.com/products/docker-desktop/)
  - Linux: `curl -fsSL https://get.docker.com | sh`
- **8GB RAM minimum** (16GB recommended)
- **API key** for at least one AI provider:
  - OpenAI (GPT-5, GPT-4)
  - Anthropic (Claude)
  - Or use local LLMs with Ollama (free)

## Installation Steps

### Step 1: Clone the Repository

```bash
git clone https://github.com/TesslateAI/Studio.git
cd Studio
```

### Step 2: Create Environment Configuration

```bash
cp .env.example .env
```

### Step 3: Generate Secure Keys

Generate your secret keys using Python:

```bash
# Generate SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate LITELLM_MASTER_KEY
python -c "import secrets; print('sk-' + secrets.token_urlsafe(32))"
```

### Step 4: Configure Your API Keys

Edit the `.env` file and add your credentials:

```env
# Required: Application secret key (use the key generated above)
SECRET_KEY=your-generated-secret-key

# Required: LiteLLM master key (use the key generated above)
LITELLM_MASTER_KEY=sk-your-litellm-master-key

# Required: At least one AI provider API key
OPENAI_API_KEY=sk-your-openai-key
# OR
ANTHROPIC_API_KEY=sk-your-anthropic-key
```

### Step 5: Start Tesslate Studio

```bash
docker compose up -d
```

This command will:
- Pull required Docker images
- Start all services (orchestrator, frontend, database, proxy)
- Automatically seed the database with agents and templates

**Wait about 30-60 seconds** for all services to start.

### Step 6: Access the Application

Open your browser and navigate to:

```
http://studio.localhost
```

### Step 7: Create Your Account

1. Click "Sign Up" on the login page
2. Enter your email and password
3. The first user is automatically granted admin privileges

### Step 8: Create Your First Project

1. Click "New Project"
2. Choose a starter template:
   - **Next.js 15** - Full-stack React with App Router
   - **Vite + React + FastAPI** - React frontend with Python backend
   - **Vite + React + Go** - React frontend with Go backend
3. Give your project a name
4. Click "Create"

### Step 9: Start Building

1. In the chat interface, describe what you want to build:
   ```
   "Build a todo app with dark mode"
   ```
2. Watch the AI generate code in real-time
3. View your app at `http://your-project.studio.localhost`
4. Make changes by chatting with the AI

## Troubleshooting

### Port Already in Use

If you see errors about ports being in use:

```bash
# Stop any existing containers
docker compose down

# Check what's using port 80
# Windows:
netstat -ano | findstr :80
# Mac/Linux:
lsof -i :80

# Start again
docker compose up -d
```

### Can't Access studio.localhost

If `studio.localhost` doesn't work:

1. **Check Docker is running**: Open Docker Desktop
2. **Verify containers are running**:
   ```bash
   docker compose ps
   ```
3. **Check logs**:
   ```bash
   docker compose logs orchestrator
   docker compose logs app
   ```

### Database Connection Issues

If you see database errors:

```bash
# Stop everything
docker compose down

# Remove old database volume
docker volume rm tesslate-studio_postgres_data

# Start fresh
docker compose up -d
```

### API Key Issues

If you get "Invalid API key" errors:

1. Verify your key is correct in `.env`
2. Make sure there are no extra spaces or quotes
3. Restart the orchestrator:
   ```bash
   docker compose restart orchestrator
   ```

## Next Steps

- **[Configuration Guide](configuration.md)** - Customize your installation
- **[Creating Custom Agents](custom-agents.md)** - Build your own AI agents
- **[Project Templates](templates.md)** - Create custom starter templates

## Development Mode

For active development with hot reload:

```bash
# Start infrastructure only
docker compose up -d traefik postgres

# Run backend (terminal 1)
cd orchestrator
uv run uvicorn app.main:app --reload

# Run frontend (terminal 2)
cd app
npm run dev
```

Your frontend will be at `http://localhost:5173` and auto-reload on changes.

## Stopping Tesslate Studio

To stop all services:

```bash
docker compose down
```

To stop and remove all data:

```bash
docker compose down -v
```

## Getting Help

- **[GitHub Issues](https://github.com/TesslateAI/Studio/issues)** - Report bugs
- **[GitHub Discussions](https://github.com/TesslateAI/Studio/discussions)** - Ask questions
- **[Email Support](mailto:support@tesslate.com)** - Direct support
