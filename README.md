<div align="center">

<img src="images/Banner.png" alt="Tesslate Studio Banner" width="100%">

# Tesslate Studio

**AI Coding Across Your Entire Stack — Frontend, Backend, Infrastructure & Mobile**

AI-powered development environment with advanced agent orchestration, designed for complete data sovereignty and infrastructure control.
The open-source platform where AI agents build complete applications: React frontends, FastAPI/Go backends, Kubernetes deployments, and Expo mobile apps — all from natural language.

🚀 **Multi-Container Architecture** | 🔒 **Self-Hosted & Private** | 🤖 **Autonomous AI Agents**

[![GitHub Stars](https://img.shields.io/github/stars/TesslateAI/Studio?style=social)](https://github.com/TesslateAI/Studio/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/TesslateAI/Studio?style=social)](https://github.com/TesslateAI/Studio/fork)

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-Ready-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Go](https://img.shields.io/badge/Go-Backend-00ADD8?logo=go&logoColor=white)](https://go.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Ready-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)

[Quick Start](#quick-start) · [Features](#key-features) · [Documentation](https://docs.tesslate.com) · [Contributing](#contributing)

**Includes support for llama.cpp, LM Studio, Ollama, Openrouter, and any provider you choose.**

</div>

---

<div align="center">

<img src="images/screenshot.png" alt="Tesslate Studio Screenshot" width="100%">

</div>

---

<table>
<tr>
<td width="50%" valign="top">

<div align="center">

### TL;DR? Get an AI Summary

**Click to auto-load the summary:**

[![ChatGPT](https://img.shields.io/badge/Ask-ChatGPT-74aa9c?style=for-the-badge&logo=openai&logoColor=white)](https://chatgpt.com/?q=Summarize%20https%3A%2F%2Fgithub.com%2FTesslateAI%2FStudio)

[![Claude](https://img.shields.io/badge/Ask-Claude-191919?style=for-the-badge&logo=anthropic&logoColor=d4a574)](https://claude.ai/new?q=Summarize%20https%3A%2F%2Fgithub.com%2FTesslateAI%2FStudio)

[![Gemini](https://img.shields.io/badge/Ask-Gemini-8E75B2?style=for-the-badge&logo=google&logoColor=white)](https://www.google.com/search?udm=50&q=Summarize+https://github.com/TesslateAI/Studio)

[![Perplexity](https://img.shields.io/badge/Ask-Perplexity-20808d?style=for-the-badge&logo=perplexity&logoColor=white)](https://www.perplexity.ai/?q=Summarize%20https://github.com/TesslateAI/Studio)

<sub>Links open with the prompt pre-loaded</sub>

</div>

</td>
<td width="50%" valign="top">

<div align="center">

### Community & Resources

[![Discord](https://img.shields.io/badge/Discord-Join%20Community-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/YR5aKPyMuW)
[![Website](https://img.shields.io/badge/Website-tesslate.com-FF6B6B?style=for-the-badge&logo=google-chrome&logoColor=white)](https://tesslate.com)
[![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97-Models-FFD21E?style=for-the-badge)](https://huggingface.co/Tesslate)

[![Twitter](https://img.shields.io/badge/Twitter-1DA1F2?style=for-the-badge&logo=twitter&logoColor=white)](https://twitter.com/TesslateAI)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-0077B5?style=for-the-badge&logo=linkedin&logoColor=white)](https://linkedin.com/company/tesslate-ai)
[![YouTube](https://img.shields.io/badge/YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://youtube.com/@TesslateAI)
[![Instagram](https://img.shields.io/badge/Instagram-E4405F?style=for-the-badge&logo=instagram&logoColor=white)](https://instagram.com/tesslateai)

**Email:** [team@tesslate.com](mailto:team@tesslate.com)

</div>

</td>
</tr>
</table>

---


## What Makes Tesslate Studio Different?

**AI coding across your entire stack — not just frontend snippets.**

Most AI coding tools generate UI components. Tesslate builds **complete systems**: React frontends talking to FastAPI backends, Go microservices with WebSocket support, Kubernetes deployments with proper networking, and cross-platform Expo mobile apps. One AI agent, full-stack applications.

### Multi-Container Architecture (New!)
- **Beyond single-container**: Run frontend + backend + database as separate services
- **Real microservices**: Each container has its own process, ports, and environment
- **Inter-service communication**: Containers discover each other automatically
- **Production-ready patterns**: The same architecture you'd deploy to production

### Self-Hosted & Private
- **Run anywhere**: Your machine, your cloud, your datacenter
- **Container isolation**: Each project runs in its own sandboxed environment
- **Subdomain routing**: Clean URLs (`project.studio.localhost`) for easy project access
- **Data sovereignty**: Your code never leaves your infrastructure

### Advanced Multi-Agent System
- **Iterative Agents**: Autonomous "think-act-reflect" loops that debug, research, and iterate independently
- **Tool Registry**: File operations (read/write/patch), persistent shell sessions, web fetch, planning tools
- **Command Validation**: Security sandboxing with allowlists, blocklists, and injection protection
- (Coming soon) **Multi-agent orchestration**: Built on TframeX framework - agents collaborate across frontend, backend, database concerns
- (Coming soon) **Model Context Protocol (MCP)**: Inter-agent communication for complex task coordination

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
- **Open source agent**: The Tesslate Agent is fully forkable and customizable
- **Create your own agents**: Build specialized agents for your workflow
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

### Seed the Marketplace (Optional)

After starting, seed the marketplace with project templates and the Tesslate Agent:

```bash
# Copy seed script into container
docker cp scripts/seed/seed_marketplace.py tesslate-orchestrator:/tmp/

# Run the seeder
docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_marketplace.py
```

This adds:
- **4 Project Templates**: Next.js 15, Vite+React+FastAPI, Vite+React+Go, Expo
- **Tesslate Agent**: The official AI agent with full Plan-Act-Observe-Verify methodology

**What's included after setup:**
- Tesslate Agent ready to use (autonomous coding agent)
- 4 project templates for different stack combinations
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

### AI-Powered Full-Stack Development
Natural language to complete applications. Not just UI components — entire systems with frontends, backends, databases, and APIs. Watch AI write across your entire stack in real-time.

### Multi-Container Projects
Build real microservices architectures:
- **Vite + React + FastAPI**: Frontend + Python backend in separate containers
- **Vite + React + Go**: Frontend + high-performance Go backend
- **Next.js 15**: Integrated fullstack with API routes
- **Expo**: Cross-platform mobile (iOS/Android/Web)

Each service runs independently with proper inter-container networking.

### Live Preview with Real URLs
Every project gets its own subdomain (`your-app.studio.localhost`) with hot module replacement. See changes instantly as AI writes code.

### The Tesslate Agent
The official open-source AI agent using Plan-Act-Observe-Verify methodology. Autonomous coding with:
- Multi-step task planning
- File operations (read/write/edit)
- Command execution with security controls
- Git integration
- Self-correction and error recovery

Fork it, customize the prompt, swap models — it's fully open source.

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

**What we've shipped:**
- [x] Multi-container architecture (frontend + backend + db)
- [x] Tesslate Agent with Plan-Act-Observe-Verify methodology
- [x] 4 project templates (Next.js, FastAPI, Go, Expo)
- [x] Kubernetes support for production deployments
- [x] Full Git integration with GitHub push/pull

**Coming soon:**
- [ ] Multi-agent orchestration (agents collaborating on complex tasks)
- [ ] Model Context Protocol (MCP) for inter-agent communication
- [ ] Two-way Git sync (pull external changes)
- [ ] Plugin system for custom integrations
- [ ] Agent marketplace for community-created agents

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
<summary><b>Q: Can I modify the AI agent?</b></summary>

**A:** Absolutely! The Tesslate Agent is fully open source. Fork it, edit the system prompt, swap models (GPT → Claude → local LLM), or create entirely new agents from scratch.

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

**Built by developers who believe AI coding tools should work across your entire stack**

### If you find this useful, please star the repo!

[![Star on GitHub](https://img.shields.io/badge/Star%20on%20GitHub-⭐-yellow?style=for-the-badge&logo=github)](https://github.com/TesslateAI/Studio)

[Star this repo](https://github.com/TesslateAI/Studio) · [Fork it](https://github.com/TesslateAI/Studio/fork) · [Share it](https://twitter.com/intent/tweet?text=Check%20out%20Tesslate%20Studio%20-%20Open%20source%20AI%20coding%20across%20your%20entire%20stack%20(frontend,%20backend,%20infra,%20mobile)!&url=https://github.com/TesslateAI/Studio)

</div>
 
