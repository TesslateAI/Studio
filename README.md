# Tesslate Studio

AI-powered web application builder with microservices architecture.

## 🏗️ Project Structure

```
tesslate-studio/
├── orchestrator/          # Backend orchestration service (FastAPI)
├── app/                   # Frontend application (React + Vite)
├── ai-service/           # AI code generation service (FastAPI)
├── k8s/                  # Kubernetes deployment configurations
├── traefik/              # Traefik reverse proxy configuration
├── test-workspace/       # Integration tests
└── docker-compose.yml    # Local development setup
```

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 20+
- Python 3.11+
- uv (Python package manager)

### Local Development

1. **Start all services:**
```bash
docker compose up -d
```

2. **Access services:**
- Frontend: http://studio.localhost
- Orchestrator API: http://api.localhost
- AI Service: http://ai.localhost
- Traefik Dashboard: http://traefik.localhost:8080

### Individual Service Development

**Orchestrator Service:**
```bash
cd orchestrator
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend Application:**
```bash
cd app
npm install
npm run dev
```

**AI Service:**
```bash
cd ai-service
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

## 🏛️ Architecture

### Services

1. **Orchestrator** (`orchestrator/`)
   - User authentication and authorization
   - Project and file management
   - Docker container orchestration
   - Database persistence (SQLAlchemy + SQLite/PostgreSQL)

2. **Frontend Application** (`app/`)
   - React + TypeScript SPA
   - Monaco Editor for code editing
   - Real-time project preview
   - Tailwind CSS for styling

3. **AI Service** (`ai-service/`)
   - Code generation with multiple AI providers
   - Template-based project scaffolding
   - Chat interface with streaming support
   - Code refactoring and explanation

### Container Management

The system uses Docker containers to provide isolated development environments for each user project:

- Each project runs in its own container
- Automatic routing via Traefik: `user{id}-project{id}.localhost`
- Hot module replacement for live development
- Automatic cleanup and resource management

## 🔧 Configuration

### Environment Variables

Create `.env` files in each service directory:

**orchestrator/.env:**
```env
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///./orchestrator.db
```

**ai-service/.env:**
```env
OPENAI_API_KEY=your-openai-key
ANTHROPIC_API_KEY=your-anthropic-key
ORCHESTRATOR_URL=http://localhost:8000
```

**app/.env:**
```env
VITE_API_URL=http://localhost:8000
VITE_AI_SERVICE_URL=http://localhost:8001
```

## 📦 Deployment

### Docker Compose (Development)
```bash
docker compose up -d
```

### Kubernetes (Production)
```bash
kubectl apply -f k8s/
```

## 🧪 Testing

```bash
cd test-workspace
python test_multi_user_containers.py
python test_container_system.py
```

## 📚 Documentation

- [Orchestrator API](orchestrator/README.md)
- [Frontend Application](app/README.md)
- [AI Service](ai-service/README.md)
- [Development Guide](CLAUDE.md)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details