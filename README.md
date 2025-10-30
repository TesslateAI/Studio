<div align="center">

<img src="images/banner.png" alt="Tesslate Studio Banner" width="100%">

# Tesslate Studio

**The Open-Source AI Development Platform Built for Self-Hosting**

AI-powered development environment with advanced agent orchestration - designed for complete data sovereignty and infrastructure control.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Ready-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)

[Quick Start](#quick-start) · [Features](#key-features) · [Documentation](#documentation) · [Contributing](#contributing)

</div>

---

<div align="center">
<img src="images/screenshot.png" alt="Tesslate Studio Screenshot" width="100%">
</div>

---

## What Makes Tesslate Studio Different?

**Infrastructure-first AI development platform designed for complete ownership and control.**

Tesslate Studio isn't just another code generation tool - it's a complete development platform architected from the ground up for self-hosting and data sovereignty:

### Self-Hosted Architecture
- **Run anywhere**: Your machine, your cloud, your datacenter
- **Container isolation**: Each project runs in its own sandboxed Docker container
- **Subdomain routing**: Clean URLs (`project.studio.localhost`) for easy project access
- **Data sovereignty**: Your code never leaves your infrastructure

### Advanced Multi-Agent System
- **Iterative Agents**: Autonomous "think-act-reflect" loops that debug, research, and iterate independently
- **Tool Registry**: File operations (read/write/patch), persistent shell sessions, web fetch, planning tools
- **Command Validation**: Security sandboxing with allowlists, blocklists, and injection protection
- **Multi-agent orchestration**: Built on TframeX framework - agents collaborate across frontend, backend, database concerns
- **Model Context Protocol (MCP)**: Inter-agent communication for complex task coordination

### Enterprise-Grade Security
- **JWT authentication** with refresh token rotation and revocable sessions
- **Encrypted credential storage** using Fernet encryption for API keys and tokens
- **Audit logging**: Complete command history for compliance
- **Container isolation**: Projects run in isolated environments
- **Command sanitization**: AI-generated shell commands validated before execution

### Full Development Lifecycle
- **Kanban project management**: Built-in task tracking with priorities, assignees, and comments
- **Architecture visualization**: AI-generated Mermaid diagrams of your codebase
- **Git integration**: Full version control with commit history, branching, and GitHub push/pull
- **Agent marketplace**: Pluggable architecture - fork agents, swap models, customize prompts
- **Database integration**: PostgreSQL with migration scripts and schema management

### Extensibility & Customization
- **Tesslate Forge**: Train, fine-tune, and deploy custom models as agents
- **Open source agents**: All 10 marketplace agents are forkable and modifiable
- **Model flexibility**: OpenAI, Anthropic, Google, local LLMs via Ollama/LM Studio
- **Platform customization**: Fork the entire platform for proprietary workflows

**Built for:**
- **Developers** who want complete control over their AI development environment
- **Teams** needing data privacy and on-premises deployment
- **Regulated industries** (healthcare, finance, government) requiring data sovereignty
- **Organizations** building AI-powered internal tools
- **Engineers** wanting to customize the platform itself

---

## Quick Start

**Get running in 3 steps, 3 minutes:**

```bash
# 1. Clone and configure
git clone https://github.com/TesslateAI/Studio.git
cd Studio
cp .env.example .env

# 2. Add your API keys (OpenAI, Anthropic, etc.) to .env
# Edit .env: Set SECRET_KEY and LITELLM_MASTER_KEY

# 3. Start everything
docker compose up -d
```

**That's it!** Open http://studio.localhost

**What's included:**
- 10 AI agents ready to use
- 3 project templates pre-loaded
- Live preview with hot reload
- Authentication system ready

<details>
<summary><b>First time with Docker? Click here for help</b></summary>

**Install Docker:**
- **Windows/Mac**: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **Linux**: `curl -fsSL https://get.docker.com | sh`

**Generate secure keys:**
```bash
# SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"

# LITELLM_MASTER_KEY
python -c "import secrets; print('sk-' + secrets.token_urlsafe(32))"
```

</details>

---

## Key Features

### AI-Powered Code Generation
Natural language to full-stack applications. Describe what you want, watch it build in real-time with streaming responses.

### Live Preview with Real URLs
Every project gets its own subdomain (`your-app.studio.localhost`) with hot module replacement. See changes instantly as AI writes code.

### Customizable AI Agents Marketplace
10 pre-built, open-source agents: Stream Builder, Full Stack Agent, Code Analyzer, Test Generator, API Designer, and more. Fork them, swap models (GPT-5, Claude, local LLMs), edit prompts - it's your code.

### Project Templates
Start fast with production-ready templates:
- Next.js 15 (App Router, SSR, API routes)
- Vite + React + FastAPI (Python backend)
- Vite + React + Go (high-performance backend)

### Docker-Based Architecture
- **One command deployment**: `docker compose up -d`
- **Container per project**: Isolated development environments
- **PostgreSQL** for persistent data
- **Traefik** ingress with subdomain routing
- **JWT authentication**, audit logging, secrets management

### Monaco Code Editor
Full VSCode-like editing experience in the browser. Syntax highlighting, IntelliSense, multi-file editing.

### Privacy & Security First
Your code never leaves your infrastructure. GitHub OAuth, encrypted secrets, comprehensive audit logs, role-based access control.

---

## The Story

**Why we built this:**

We needed an AI development platform that could run on our own infrastructure without sacrificing data sovereignty or architectural control. Every existing solution required choosing between convenience and control - cloud platforms were fast but locked us in, while local tools lacked the sophistication we needed.

So we built Tesslate Studio as infrastructure-first: Docker for simple deployment, container isolation for project sandboxing, and enterprise security built-in. It's designed for developers and organizations that need the power of AI-assisted development while maintaining complete ownership of their code and data.

**The name "Tesslate"** comes from tessellation - the mathematical concept of tiles fitting together perfectly without gaps. That's our architecture: AI agents, human developers, isolated environments, and scalable infrastructure working together seamlessly.

**Open source from the start:** We believe critical development infrastructure should be transparent, auditable, and owned by the teams using it - not controlled by vendors who can change terms overnight.

---

## Architecture

Tesslate Studio creates **isolated containerized environments** for each project:

```
┌─────────────────────────────────────────────────────┐
│  Your Machine / Your Cloud / Your Datacenter       │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────────────────────────────────────────┐     │
│  │  Tesslate Studio (You control this)     │     │
│  │                                           │     │
│  │  • FastAPI Orchestrator (Python)         │     │
│  │  • React Frontend (TypeScript)           │     │
│  │  • PostgreSQL Database                    │     │
│  │  • AI Agent Marketplace                   │     │
│  └───────────┬──────────────────────────────┘     │
│              │                                      │
│              ▼                                      │
│  ┌──────────────────────────────────────────┐     │
│  │  Project Containers (Isolated)           │     │
│  │                                           │     │
│  │  todo-app.studio.localhost               │     │
│  │  dashboard.studio.localhost              │     │
│  │  prototype.studio.localhost              │     │
│  └──────────────────────────────────────────┘     │
│                                                     │
│  ┌──────────────────────────────────────────┐     │
│  │  Your AI Models (You choose)             │     │
│  │                                           │     │
│  │  • OpenAI GPT-5 (API)                    │     │
│  │  • Anthropic Claude (API)                │     │
│  │  • Local LLMs via Ollama                 │     │
│  │  • Or any LiteLLM-compatible provider    │     │
│  └──────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

**Key Architecture Principles:**
1. **Container-per-project** - True isolation, no conflicts
2. **Subdomain routing** - Clean URLs, easy project access
3. **Bring your own models** - No vendor lock-in for AI
4. **Self-hosted** - Complete infrastructure control

---

## Getting Started

### Prerequisites

- **Docker Desktop** (Windows/Mac) or **Docker Engine** (Linux)
- **8GB RAM minimum** (16GB recommended)
- **OpenAI or Anthropic API key** (or run local LLMs with Ollama)

### Installation

**Step 1: Clone the repository**

```bash
git clone https://github.com/TesslateAI/Studio.git
cd Studio
```

**Step 2: Configure environment**

```bash
cp .env.example .env
```

Edit `.env` and set these required values:

```env
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
SECRET_KEY=your-generated-secret-key

# Your LiteLLM master key
LITELLM_MASTER_KEY=sk-your-litellm-key

# AI provider API keys (at least one required)
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-your-anthropic-key
```

**Step 3: Start Tesslate Studio**

```bash
docker compose up -d
```

**Step 4: Create your account**

Open http://studio.localhost and sign up. The first user becomes admin automatically.

**Step 5: Start building**

1. Click "New Project" → Choose a template
2. Describe what you want in natural language
3. Watch AI generate your app in real-time
4. Open live preview at `{your-project}.studio.localhost`

### Development Modes

**Full Docker** (Recommended for most users)
```bash
docker compose up -d
```
Everything runs in containers. One command, fully isolated.

**Hybrid Mode** (Fastest for active development)
```bash
# Start infrastructure
docker compose up -d traefik postgres

# Run services natively (separate terminals)
cd orchestrator && uv run uvicorn app.main:app --reload
cd app && npm run dev
```
Native services for instant hot reload, Docker for infrastructure.

---

## Configuration

### AI Models

Tesslate uses [LiteLLM](https://github.com/BerriAI/litellm) as a unified gateway. This means you can use:

- **OpenAI** (GPT-5, GPT-4, GPT-3.5)
- **Anthropic** (Claude 3.5, Claude 3)
- **Google** (Gemini Pro)
- **Local LLMs** (Ollama, LocalAI)
- **100+ other providers**

Configure in `.env`:

```env
# Default models
LITELLM_DEFAULT_MODELS=gpt-5o-mini,claude-3-haiku,gemini-pro

# Per-user budget (USD)
LITELLM_INITIAL_BUDGET=10.0
```

### Database

**Development:** PostgreSQL runs in Docker automatically.

**Production:** Use a managed database:
```env
DATABASE_URL=postgresql+asyncpg://user:pass@your-postgres:5432/tesslate
```

### Domain Configuration

**Local development:**
```env
APP_DOMAIN=studio.localhost
```

**Production:**
```env
APP_DOMAIN=studio.yourcompany.com
APP_PROTOCOL=https
```

Projects will be accessible at `{project}.studio.yourcompany.com`

---

## Contributing

We'd love your help making Tesslate Studio better!

### Quick Contribution Guide

1. **Fork the repo** and clone your fork
2. **Create a branch**: `git checkout -b feature/amazing-feature`
3. **Make your changes** and test locally
4. **Commit**: `git commit -m 'Add amazing feature'`
5. **Push**: `git push origin feature/amazing-feature`
6. **Open a Pull Request** with a clear description

### Good First Issues

New to the project? Check out issues labeled [`good first issue`](https://github.com/TesslateAI/Studio/labels/good%20first%20issue).

### Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR-USERNAME/Studio.git
cd Studio

# Start in hybrid mode (fastest for development)
docker compose up -d traefik postgres
cd orchestrator && uv run uvicorn app.main:app --reload
cd app && npm run dev
```

### Contribution Guidelines

- **Tests**: Add tests for new features
- **Docs**: Update documentation if you change functionality
- **Commits**: Use clear, descriptive commit messages
- **PRs**: One feature per PR, keep them focused

**Before submitting:**
- Run tests: `npm test` (frontend), `pytest` (backend)
- Update docs if needed
- Test with `docker compose up -d`

---

## Documentation

Visit our complete documentation at **[docs.tesslate.com](https://docs.tesslate.com)**

### Self-Hosting Guides
- **[Self-Hosting Quickstart](https://docs.tesslate.com/self-hosting/quickstart)** - Get running in 5 minutes
- **[Configuration Guide](https://docs.tesslate.com/self-hosting/configuration)** - All environment variables explained
- **[Production Deployment](https://docs.tesslate.com/self-hosting/deployment)** - Deploy with custom domains and SSL
- **[Architecture Overview](https://docs.tesslate.com/self-hosting/architecture)** - How everything works under the hood

### Development Guides
- **[Development Setup](https://docs.tesslate.com/development/guide)** - Contributor and developer guide
- **[API Documentation](https://docs.tesslate.com/api-reference/introduction)** - Backend API reference

### Using Tesslate Studio
- **[Getting Started](https://docs.tesslate.com/quickstart)** - Cloud version quickstart
- **[Working with Projects](https://docs.tesslate.com/guides/creating-projects)** - Create and manage projects
- **[AI Agents Guide](https://docs.tesslate.com/guides/agents)** - Understanding and using AI agents
- **[FAQ](https://docs.tesslate.com/faq)** - Frequently asked questions

---

## Security

We take security seriously. Found a vulnerability?

**Please DO NOT open a public issue.** Instead:

**Email us:** security@tesslate.com

We'll respond within 24 hours and work with you to address it.

### Security Features

- **JWT authentication** with refresh tokens
- **Encrypted secrets** storage (GitHub tokens, API keys)
- **Audit logging** (who did what, when)
- **Role-based access** control (admin, user, viewer)
- **Container isolation** (projects can't access each other)
- **HTTPS/TLS** in production (automatic Let's Encrypt)

---

## License

Tesslate Studio is **Apache 2.0 licensed**. See [LICENSE](LICENSE).

**What this means:**
- **Commercial use** - Build paid products with it
- **Modification** - Fork and customize freely
- **Distribution** - Share your modifications
- **Patent grant** - Protected from patent claims
- **Trademark** - "Tesslate" name is reserved
- **Liability** - Provided "as is" (standard for open source)

### Third-Party Licenses

This project uses open-source software. Full attributions in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=TesslateAI/Studio&type=Date)](https://star-history.com/#TesslateAI/Studio&Date)

---

## Roadmap

**Coming soon:**
- [ ] GitHub Copilot integration
- [ ] VSCode extension for direct editing
- [ ] Multiplayer editing (real-time collaboration)
- [ ] Built-in Git integration (commits, branches, PRs)
- [ ] Mobile app for iOS/Android
- [ ] Plugin system for custom integrations
- [ ] Self-hosted AI model support (Ollama by default)
- [ ] Advanced analytics dashboard

**Have an idea?** [Open a feature request](https://github.com/TesslateAI/Studio/issues/new?template=feature_request.md)

---

## FAQ

<details>
<summary><b>Q: Do I need to pay for OpenAI/Claude API?</b></summary>

**A:** You bring your own API keys. Tesslate Studio doesn't charge for AI - you pay your provider directly (usually pennies per request). You can also use free local models via Ollama.

</details>

<details>
<summary><b>Q: Can I use this commercially?</b></summary>

**A:** Yes! Apache 2.0 license allows commercial use. Build SaaS products, internal tools, whatever you want.

</details>

<details>
<summary><b>Q: Is my code/data sent to Tesslate's servers?</b></summary>

**A:** No. Tesslate Studio is self-hosted - everything runs on YOUR infrastructure. We never see your code or data.

</details>

<details>
<summary><b>Q: Can I modify the AI agents?</b></summary>

**A:** Absolutely! All 10 agents are open source. Fork them, edit prompts, swap models (GPT → Claude → local LLM), or create entirely new agents.

</details>

<details>
<summary><b>Q: Can I run this without Docker?</b></summary>

**A:** While Docker is recommended, you can run services natively. You'll need to manually set up PostgreSQL, Traefik, and configure networking.

</details>

<details>
<summary><b>Q: What hardware do I need?</b></summary>

**A:** Minimum 8GB RAM, 16GB recommended. Works on Windows, Mac, and Linux. An internet connection is needed for AI API calls (unless using local models).

</details>

---

## Community & Support

### Get Help

- **[Documentation](https://docs.tesslate.com)** - Comprehensive guides
- **[GitHub Discussions](https://github.com/TesslateAI/Studio/discussions)** - Ask questions, share ideas
- **[Issues](https://github.com/TesslateAI/Studio/issues)** - Report bugs, request features
- **[Email](mailto:support@tesslate.com)** - Direct support (response within 24h)

### Stay Updated

- **Star this repo** to get notified of updates
- **Watch releases** for new versions
- **[Follow on Twitter/X](https://twitter.com/tesslate)** - News and tips

### Contributing

Contributions are **welcome and encouraged**! See our **[Development Guide](https://docs.tesslate.com/development/guide)** for setup instructions and contribution guidelines.

**Special thanks to our contributors:**

[![Contributors](https://contrib.rocks/image?repo=TesslateAI/Studio)](https://github.com/TesslateAI/Studio/graphs/contributors)

---

## Acknowledgments

Tesslate Studio wouldn't exist without these amazing open-source projects:

- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [React](https://react.dev/) - UI library
- [Vite](https://vitejs.dev/) - Lightning-fast build tool
- [Monaco Editor](https://microsoft.github.io/monaco-editor/) - VSCode's editor
- [LiteLLM](https://github.com/BerriAI/litellm) - Unified AI gateway
- [Traefik](https://traefik.io/) - Cloud-native proxy
- [PostgreSQL](https://www.postgresql.org/) - Reliable database

---

<div align="center">

**Built by developers who believe critical infrastructure should be open**

[Star this repo](https://github.com/TesslateAI/Studio) · [Fork it](https://github.com/TesslateAI/Studio/fork) · [Share it](https://twitter.com/intent/tweet?text=Check%20out%20Tesslate%20Studio%20-%20Open%20source%20AI%20development%20platform%20for%20self-hosting!&url=https://github.com/TesslateAI/Studio)

</div>
