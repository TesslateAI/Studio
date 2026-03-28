"""
Seed marketplace skills (item_type='skill').

Creates open-source skills (fetched from GitHub SKILL.md files) and
Tesslate custom skills (bundled descriptions).

Can be run standalone or called from the startup seeder.
"""

import logging
import re

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MarketplaceAgent
from .marketplace_agents import get_or_create_tesslate_account

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GitHub-sourced open-source skills
# ---------------------------------------------------------------------------

OPENSOURCE_SKILLS = [
    {
        "name": "Vercel React Best Practices",
        "slug": "vercel-react-best-practices",
        "description": "React and Next.js performance patterns from Vercel",
        "long_description": (
            "Community-maintained skill that teaches agents Vercel's recommended "
            "patterns for React and Next.js applications, including server "
            "components, streaming, caching, and performance optimization."
        ),
        "category": "frontend",
        "item_type": "skill",
        "icon": "▲",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "git_repo_url": "https://github.com/vercel-labs/agent-skills",
        "downloads": 0,
        "rating": 5.0,
        "tags": ["react", "nextjs", "vercel", "performance", "open-source"],
        "features": [
            "Server component patterns",
            "Streaming & Suspense",
            "Caching strategies",
            "Performance optimization",
        ],
        "github_raw_url": (
            "https://raw.githubusercontent.com/vercel-labs/agent-skills"
            "/main/skills/vercel-react-best-practices/SKILL.md"
        ),
        "fallback_skill_body": (
            "## Vercel React Best Practices\n\n"
            "### Guidelines\n"
            "- Prefer React Server Components for data fetching\n"
            "- Use Suspense boundaries for streaming UI\n"
            "- Leverage Next.js App Router conventions\n"
            "- Implement proper caching with revalidation strategies\n"
            "- Use `next/image` for optimized image loading\n"
            "- Minimize client-side JavaScript with selective hydration\n"
            "- Follow the recommended file-based routing patterns\n"
            "- Use `loading.tsx` and `error.tsx` for graceful states\n"
        ),
    },
    {
        "name": "Web Design Guidelines",
        "slug": "web-design-guidelines",
        "description": "Web interface design guidelines and accessibility",
        "long_description": (
            "Community-maintained skill covering web design principles, "
            "accessibility standards (WCAG), responsive layouts, color theory, "
            "and typography best practices for building inclusive web interfaces."
        ),
        "category": "design",
        "item_type": "skill",
        "icon": "🎨",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "git_repo_url": "https://github.com/vercel-labs/agent-skills",
        "downloads": 0,
        "rating": 5.0,
        "tags": ["design", "accessibility", "wcag", "responsive", "open-source"],
        "features": [
            "WCAG accessibility",
            "Responsive design",
            "Color & typography",
            "Layout patterns",
        ],
        "github_raw_url": (
            "https://raw.githubusercontent.com/vercel-labs/agent-skills"
            "/main/skills/web-design-guidelines/SKILL.md"
        ),
        "fallback_skill_body": (
            "## Web Design Guidelines\n\n"
            "### Accessibility\n"
            "- Follow WCAG 2.1 AA standards at minimum\n"
            "- Ensure sufficient color contrast ratios (4.5:1 for text)\n"
            "- Provide alt text for all meaningful images\n"
            "- Support keyboard navigation throughout\n\n"
            "### Responsive Design\n"
            "- Use mobile-first approach\n"
            "- Design for common breakpoints (320px, 768px, 1024px, 1440px)\n"
            "- Use relative units (rem, em, %) over fixed pixels\n\n"
            "### Typography\n"
            "- Limit to 2-3 font families\n"
            "- Maintain clear visual hierarchy with font sizes\n"
            "- Use line-height of 1.5-1.75 for body text\n"
        ),
    },
    {
        "name": "Frontend Design",
        "slug": "frontend-design",
        "description": "Frontend design patterns and best practices",
        "long_description": (
            "Community-maintained skill from Anthropic covering frontend design "
            "patterns, component architecture, state management approaches, "
            "and UI/UX best practices for modern web applications."
        ),
        "category": "frontend",
        "item_type": "skill",
        "icon": "🖼️",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "git_repo_url": "https://github.com/anthropics/skills",
        "downloads": 0,
        "rating": 5.0,
        "tags": ["frontend", "design-patterns", "components", "ui", "open-source"],
        "features": [
            "Component architecture",
            "State management",
            "UI/UX patterns",
            "Modern CSS",
        ],
        "github_raw_url": (
            "https://raw.githubusercontent.com/anthropics/skills"
            "/main/skills/frontend-design/SKILL.md"
        ),
        "fallback_skill_body": (
            "## Frontend Design\n\n"
            "### Component Architecture\n"
            "- Build small, composable components with single responsibilities\n"
            "- Separate presentational and container components\n"
            "- Use composition over inheritance\n\n"
            "### State Management\n"
            "- Keep state as local as possible\n"
            "- Lift state up only when necessary\n"
            "- Use context for cross-cutting concerns (theme, auth)\n\n"
            "### Styling\n"
            "- Use utility-first CSS (Tailwind) or CSS modules\n"
            "- Maintain consistent spacing and sizing scales\n"
            "- Design tokens for colors, typography, and spacing\n"
        ),
    },
    {
        "name": "Remotion Best Practices",
        "slug": "remotion-best-practices",
        "description": "Best practices for Remotion video creation in React",
        "long_description": (
            "Community-maintained skill covering Remotion framework best practices "
            "for programmatic video creation using React. Covers composition "
            "patterns, animation, audio sync, and rendering optimization."
        ),
        "category": "media",
        "item_type": "skill",
        "icon": "🎬",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": False,
        "is_active": True,
        "is_published": True,
        "git_repo_url": "https://github.com/remotion-dev/skills",
        "downloads": 0,
        "rating": 5.0,
        "tags": ["remotion", "video", "react", "animation", "open-source"],
        "features": [
            "Video compositions",
            "Animation patterns",
            "Audio synchronization",
            "Render optimization",
        ],
        "github_raw_url": (
            "https://raw.githubusercontent.com/remotion-dev/skills"
            "/main/skills/remotion-best-practices/SKILL.md"
        ),
        "fallback_skill_body": (
            "## Remotion Best Practices\n\n"
            "### Compositions\n"
            "- Define compositions with explicit width, height, and fps\n"
            "- Use `useCurrentFrame()` and `useVideoConfig()` hooks\n"
            "- Keep compositions pure and deterministic\n\n"
            "### Animation\n"
            "- Use `interpolate()` for smooth transitions\n"
            "- Leverage `spring()` for natural motion\n"
            "- Use `Sequence` components for timeline control\n\n"
            "### Performance\n"
            "- Avoid heavy computations during render\n"
            "- Pre-calculate values outside the render loop\n"
            "- Use `delayRender()` for async operations\n"
        ),
    },
    {
        "name": "Simplify",
        "slug": "simplify",
        "description": "Review code for reuse, quality, efficiency",
        "long_description": (
            "Community-maintained skill that guides agents to review code for "
            "simplification opportunities, identifying redundancy, improving "
            "readability, and suggesting more efficient implementations."
        ),
        "category": "code-quality",
        "item_type": "skill",
        "icon": "✨",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "git_repo_url": "https://github.com/roin-orca/skills",
        "downloads": 0,
        "rating": 5.0,
        "tags": ["code-quality", "refactoring", "review", "efficiency", "open-source"],
        "features": [
            "Code simplification",
            "Redundancy detection",
            "Readability improvements",
            "Efficiency suggestions",
        ],
        "github_raw_url": (
            "https://raw.githubusercontent.com/roin-orca/skills"
            "/main/skills/simplify/SKILL.md"
        ),
        "fallback_skill_body": (
            "## Simplify\n\n"
            "### Code Review Checklist\n"
            "- Identify duplicated logic and extract shared utilities\n"
            "- Simplify complex conditionals with guard clauses\n"
            "- Replace imperative loops with declarative alternatives\n"
            "- Remove dead code and unused imports\n"
            "- Flatten deeply nested structures\n\n"
            "### Quality Principles\n"
            "- Prefer readability over cleverness\n"
            "- Keep functions under 20 lines when possible\n"
            "- Use meaningful variable and function names\n"
            "- Apply the DRY principle judiciously\n"
            "- Write code that is easy to delete, not easy to extend\n"
        ),
    },
]

# ---------------------------------------------------------------------------
# Tesslate custom skills (bundled, no GitHub fetch)
# ---------------------------------------------------------------------------

TESSLATE_SKILLS = [
    {
        "name": "Deploy to Vercel",
        "slug": "deploy-vercel",
        "description": "Deploy Tesslate projects to Vercel with environment setup",
        "long_description": (
            "Tesslate skill that guides agents through deploying projects to "
            "Vercel, including vercel.json configuration, environment variables, "
            "build settings, and preview deployment setup."
        ),
        "category": "deployment",
        "item_type": "skill",
        "icon": "🚀",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["deployment", "vercel", "ci-cd", "hosting"],
        "features": [
            "Vercel configuration",
            "Environment variables",
            "Build optimization",
            "Preview deployments",
        ],
        "skill_body": (
            "## Deploy to Vercel\n\n"
            "### Steps\n"
            "1. Check if the project has a `vercel.json` configuration\n"
            "2. Ensure the build command is configured correctly\n"
            "3. Set up environment variables\n"
            "4. Run `vercel deploy` or guide the user through Vercel dashboard setup\n\n"
            "### Build Configuration\n"
            "- Detect the framework (Next.js, Vite, CRA) and set the correct build command\n"
            "- Configure the output directory (`out`, `dist`, `.next`, `build`)\n"
            "- Set the install command if using a non-standard package manager\n\n"
            "### Environment Variables\n"
            "- Identify all required env vars from `.env.example` or `.env.local`\n"
            "- Guide user to add them in Vercel dashboard or via `vercel env add`\n"
            "- Ensure `NODE_ENV=production` is set for production builds\n\n"
            "### Best Practices\n"
            "- Always set `NODE_ENV=production` for deployments\n"
            "- Configure build output directory correctly\n"
            "- Set up preview deployments for branches\n"
            "- Use `vercel.json` rewrites for SPA routing\n"
            "- Enable speed insights and analytics if available\n"
        ),
    },
    {
        "name": "Testing Setup",
        "slug": "testing-setup",
        "description": "Set up testing frameworks (Jest, Vitest, Pytest) with proper config",
        "long_description": (
            "Tesslate skill that helps agents configure testing frameworks "
            "for JavaScript and Python projects, including test runners, "
            "coverage reporting, and CI integration."
        ),
        "category": "testing",
        "item_type": "skill",
        "icon": "🧪",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["testing", "jest", "vitest", "pytest", "coverage"],
        "features": [
            "Framework detection",
            "Config generation",
            "Coverage setup",
            "CI integration",
        ],
        "skill_body": (
            "## Testing Setup\n\n"
            "### Framework Detection\n"
            "1. Check `package.json` for existing test dependencies\n"
            "2. Detect the project type (React/Vite -> Vitest, CRA -> Jest, Python -> Pytest)\n"
            "3. Check for existing test configuration files\n\n"
            "### JavaScript/TypeScript Projects\n\n"
            "#### Vitest (Recommended for Vite projects)\n"
            "- Install: `npm install -D vitest @testing-library/react @testing-library/jest-dom`\n"
            "- Create `vitest.config.ts` with proper test environment (jsdom/happy-dom)\n"
            "- Add test scripts to `package.json`: `\"test\": \"vitest\", \"test:coverage\": \"vitest --coverage\"`\n"
            "- Set up `setupTests.ts` with testing-library matchers\n\n"
            "#### Jest (For CRA or non-Vite projects)\n"
            "- Install: `npm install -D jest @testing-library/react @testing-library/jest-dom`\n"
            "- Create `jest.config.js` with moduleNameMapper for aliases\n"
            "- Configure transform for TypeScript if needed\n\n"
            "### Python Projects\n"
            "- Install: `pip install pytest pytest-cov pytest-asyncio`\n"
            "- Create `pytest.ini` or `pyproject.toml` [tool.pytest] section\n"
            "- Set up `conftest.py` with shared fixtures\n"
            "- Configure coverage: `pytest --cov=app --cov-report=html`\n\n"
            "### Best Practices\n"
            "- Create a `tests/` directory with `__init__.py` (Python) or `__tests__/` (JS)\n"
            "- Add a sample test file to verify the setup works\n"
            "- Configure coverage thresholds (aim for 80%+)\n"
            "- Add test commands to CI pipeline\n"
        ),
    },
    {
        "name": "API Design",
        "slug": "api-design",
        "description": "Design RESTful APIs following OpenAPI spec and best practices",
        "long_description": (
            "Tesslate skill for designing clean, well-documented RESTful APIs "
            "with OpenAPI specifications, proper error handling, versioning, "
            "and authentication patterns."
        ),
        "category": "backend",
        "item_type": "skill",
        "icon": "📡",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["api", "rest", "openapi", "backend", "design"],
        "features": [
            "RESTful conventions",
            "OpenAPI spec",
            "Error handling",
            "Authentication patterns",
        ],
        "skill_body": (
            "## API Design\n\n"
            "### RESTful Conventions\n"
            "- Use nouns for resources: `/users`, `/posts`, `/comments`\n"
            "- Use HTTP methods correctly: GET (read), POST (create), PUT (replace), PATCH (update), DELETE (remove)\n"
            "- Return appropriate status codes: 200 (OK), 201 (Created), 204 (No Content), 400 (Bad Request), 401 (Unauthorized), 404 (Not Found), 422 (Unprocessable Entity)\n"
            "- Use plural nouns for collections: `/api/v1/users` not `/api/v1/user`\n\n"
            "### Response Format\n"
            "- Wrap responses in a consistent envelope: `{\"data\": ..., \"meta\": ...}`\n"
            "- Include pagination for list endpoints: `{\"data\": [...], \"meta\": {\"total\": 100, \"page\": 1, \"per_page\": 20}}`\n"
            "- Use consistent error format: `{\"error\": {\"code\": \"NOT_FOUND\", \"message\": \"User not found\"}}`\n\n"
            "### Versioning\n"
            "- Use URL path versioning: `/api/v1/resources`\n"
            "- Never break backward compatibility within a version\n"
            "- Deprecate old versions with sunset headers\n\n"
            "### Authentication\n"
            "- Use Bearer tokens in Authorization header\n"
            "- Implement rate limiting with X-RateLimit headers\n"
            "- Return 401 for missing auth, 403 for insufficient permissions\n\n"
            "### Documentation\n"
            "- Generate OpenAPI/Swagger spec from code annotations\n"
            "- Include request/response examples for every endpoint\n"
            "- Document query parameters, path parameters, and request bodies\n"
        ),
    },
    {
        "name": "Docker Setup",
        "slug": "docker-setup",
        "description": "Containerize applications with Docker and docker-compose",
        "long_description": (
            "Tesslate skill for containerizing applications with Docker, "
            "writing efficient Dockerfiles, setting up docker-compose for "
            "multi-service architectures, and production deployment patterns."
        ),
        "category": "devops",
        "item_type": "skill",
        "icon": "🐳",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["docker", "containers", "devops", "docker-compose"],
        "features": [
            "Dockerfile generation",
            "Multi-stage builds",
            "Docker Compose setup",
            "Production patterns",
        ],
        "skill_body": (
            "## Docker Setup\n\n"
            "### Dockerfile Best Practices\n"
            "1. Use official base images with specific version tags (e.g., `node:20-alpine`)\n"
            "2. Use multi-stage builds to minimize final image size\n"
            "3. Copy dependency files first, then install, then copy source (layer caching)\n"
            "4. Use `.dockerignore` to exclude `node_modules`, `.git`, `.env`\n"
            "5. Run as non-root user in production\n"
            "6. Use `HEALTHCHECK` instruction for container health monitoring\n\n"
            "### Multi-Stage Build Pattern\n"
            "```dockerfile\n"
            "# Stage 1: Dependencies\n"
            "FROM node:20-alpine AS deps\n"
            "WORKDIR /app\n"
            "COPY package*.json ./\n"
            "RUN npm ci --only=production\n\n"
            "# Stage 2: Build\n"
            "FROM node:20-alpine AS builder\n"
            "WORKDIR /app\n"
            "COPY --from=deps /app/node_modules ./node_modules\n"
            "COPY . .\n"
            "RUN npm run build\n\n"
            "# Stage 3: Runtime\n"
            "FROM node:20-alpine AS runner\n"
            "WORKDIR /app\n"
            "RUN addgroup -g 1001 -S app && adduser -S app -u 1001\n"
            "COPY --from=builder /app/dist ./dist\n"
            "COPY --from=deps /app/node_modules ./node_modules\n"
            "USER app\n"
            "CMD [\"node\", \"dist/index.js\"]\n"
            "```\n\n"
            "### Docker Compose\n"
            "- Define services, networks, and volumes clearly\n"
            "- Use `depends_on` with health checks for startup ordering\n"
            "- Mount source code as volumes for development hot-reload\n"
            "- Use environment files (`.env`) for configuration\n"
            "- Expose only necessary ports\n\n"
            "### Security\n"
            "- Never store secrets in the image (use env vars or secrets)\n"
            "- Scan images for vulnerabilities with `docker scout`\n"
            "- Pin base image digests for reproducible builds\n"
        ),
    },
    {
        "name": "Auth Integration",
        "slug": "auth-integration",
        "description": "Add authentication flows (OAuth, JWT, sessions) to web apps",
        "long_description": (
            "Tesslate skill for implementing authentication and authorization "
            "in web applications, covering OAuth 2.0, JWT tokens, session-based "
            "auth, and role-based access control."
        ),
        "category": "security",
        "item_type": "skill",
        "icon": "🔐",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["auth", "oauth", "jwt", "security", "sessions"],
        "features": [
            "OAuth 2.0 flows",
            "JWT management",
            "Session handling",
            "RBAC patterns",
        ],
        "skill_body": (
            "## Auth Integration\n\n"
            "### Choose the Right Auth Strategy\n"
            "- **JWT (stateless)**: Best for APIs and SPAs. Token contains claims, no server-side session.\n"
            "- **Sessions (stateful)**: Best for server-rendered apps. Session ID stored in cookie, data on server.\n"
            "- **OAuth 2.0**: Best for third-party login (Google, GitHub). Delegates auth to identity provider.\n\n"
            "### JWT Implementation\n"
            "1. Generate tokens with short expiry (15-30 min for access, 7 days for refresh)\n"
            "2. Store refresh tokens in HTTP-only, Secure, SameSite cookies\n"
            "3. Never store access tokens in localStorage (XSS risk)\n"
            "4. Implement token rotation on refresh\n"
            "5. Include minimal claims: `sub`, `exp`, `iat`, `roles`\n\n"
            "### OAuth 2.0 Flow\n"
            "1. Redirect user to provider's authorize endpoint\n"
            "2. Receive authorization code via callback\n"
            "3. Exchange code for access token (server-side)\n"
            "4. Fetch user profile from provider\n"
            "5. Create or link local user account\n\n"
            "### Security Checklist\n"
            "- Hash passwords with bcrypt (cost factor 12+)\n"
            "- Use CSRF tokens for session-based auth\n"
            "- Implement rate limiting on login endpoints\n"
            "- Add account lockout after failed attempts\n"
            "- Log authentication events for auditing\n"
            "- Use HTTPS everywhere\n"
            "- Validate redirect URIs to prevent open redirect attacks\n"
        ),
    },
    {
        "name": "Database Schema",
        "slug": "database-schema",
        "description": "Design and create database schemas with migrations",
        "long_description": (
            "Tesslate skill for designing normalized database schemas, writing "
            "migrations, setting up ORMs, and following data modeling best "
            "practices for relational and document databases."
        ),
        "category": "database",
        "item_type": "skill",
        "icon": "🗄️",
        "pricing_type": "free",
        "price": 0,
        "source_type": "open",
        "is_forkable": True,
        "is_featured": False,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["database", "schema", "migrations", "sql", "orm"],
        "features": [
            "Schema design",
            "Migration generation",
            "ORM configuration",
            "Index optimization",
        ],
        "skill_body": (
            "## Database Schema\n\n"
            "### Schema Design Principles\n"
            "- Start with a clear entity-relationship diagram\n"
            "- Normalize to 3NF, then denormalize intentionally for performance\n"
            "- Use UUIDs for primary keys in distributed systems, BIGSERIAL for single-DB apps\n"
            "- Always include `created_at` and `updated_at` timestamps\n"
            "- Use soft deletes (`deleted_at`) for recoverable data\n\n"
            "### Relationships\n"
            "- One-to-Many: Foreign key on the 'many' side\n"
            "- Many-to-Many: Junction/association table with composite primary key\n"
            "- One-to-One: Foreign key with unique constraint\n"
            "- Always define `ON DELETE` behavior (CASCADE, SET NULL, RESTRICT)\n\n"
            "### Migrations\n"
            "- Generate migrations from model changes, never edit the DB directly\n"
            "- Make migrations reversible (include both `upgrade` and `downgrade`)\n"
            "- Test migrations on a copy of production data before deploying\n"
            "- Use descriptive migration names: `add_user_email_verification_columns`\n\n"
            "### Indexing\n"
            "- Index columns used in WHERE, JOIN, and ORDER BY clauses\n"
            "- Use composite indexes for multi-column queries (leftmost prefix rule)\n"
            "- Add partial indexes for filtered queries\n"
            "- Monitor slow queries and add indexes based on actual usage\n\n"
            "### ORM Setup\n"
            "- **SQLAlchemy (Python)**: Define models with `DeclarativeBase`, use Alembic for migrations\n"
            "- **Prisma (TypeScript)**: Define schema in `schema.prisma`, use `prisma migrate`\n"
            "- **Drizzle (TypeScript)**: Define schema in TypeScript, use `drizzle-kit`\n"
        ),
    },
    {
        "name": "Project Architecture",
        "slug": "project-architecture",
        "description": "Understand and modify .tesslate/config.json — project containers, services, connections, env vars, and lifecycle control",
        "long_description": (
            "Tesslate skill that teaches agents the full .tesslate/config.json schema, "
            "how to safely modify project architecture (add services, change ports, "
            "wire connections), and control container lifecycle (restart, status, logs). "
            "Loaded on-demand when users ask about project structure, containers, "
            "ports, services, databases, or environment configuration."
        ),
        "category": "infrastructure",
        "item_type": "skill",
        "icon": "\U0001f3d7",
        "pricing_type": "free",
        "price": 0,
        "source_type": "tesslate",
        "is_forkable": False,
        "is_featured": True,
        "is_active": True,
        "is_published": True,
        "downloads": 0,
        "rating": 5.0,
        "tags": ["infrastructure", "containers", "config", "architecture", "lifecycle"],
        "features": [
            "Config.json schema reference",
            "Service management (add/remove/modify)",
            "Container lifecycle control",
            "Environment variable management",
            "Connection wiring",
        ],
        "skill_body": (
            "# Project Architecture — .tesslate/config.json\n\n"
            "This skill covers the full `.tesslate/config.json` schema, how to safely\n"
            "modify project architecture, and how to control container lifecycle.\n\n"
            "---\n\n"
            "## 1. Schema Reference\n\n"
            "`.tesslate/config.json` is the single source of truth for a project's\n"
            "services, infrastructure, connections, and deployment targets.\n\n"
            "### Top-Level Structure\n\n"
            "```json\n"
            "{\n"
            '  "apps": { ... },\n'
            '  "infrastructure": { ... },\n'
            '  "connections": [ ... ],\n'
            '  "deployments": { ... },\n'
            '  "previews": { ... },\n'
            '  "primaryApp": "frontend"\n'
            "}\n"
            "```\n\n"
            "### `apps` — Application Services\n\n"
            "Each key is the service name. Fields:\n\n"
            "| Field | Type | Default | Description |\n"
            "|-------|------|---------|-------------|\n"
            "| `directory` | string | `\".\"` | Working directory relative to project root |\n"
            "| `port` | int or null | `3000` | Port the app listens on |\n"
            "| `start` | string | `\"\"` | Startup command (validated for security) |\n"
            "| `build` | string or null | `null` | Build command (e.g. `npm run build`) |\n"
            "| `output` | string or null | `null` | Build output directory |\n"
            "| `framework` | string or null | `null` | Framework hint (e.g. `nextjs`, `vite`) |\n"
            "| `env` | object | `{}` | Environment variables as key-value pairs |\n"
            "| `exports` | object | `{}` | Values exported to other services via connections |\n"
            "| `x`, `y` | float or null | `null` | Canvas position (UI layout only) |\n\n"
            "### `infrastructure` — Infrastructure Services\n\n"
            "Databases, caches, message queues, and external services.\n\n"
            "| Field | Type | Default | Description |\n"
            "|-------|------|---------|-------------|\n"
            "| `image` | string | `\"\"` | Docker image (e.g. `postgres:16-alpine`) |\n"
            "| `port` | int | `5432` | Service port |\n"
            "| `env` | object | `{}` | Environment variables |\n"
            "| `exports` | object | `{}` | Values exported to connected services |\n"
            "| `type` | string | `\"container\"` | `\"container\"` or `\"external\"` |\n"
            "| `provider` | string or null | `null` | For external services (e.g. `supabase`) |\n"
            "| `endpoint` | string or null | `null` | For external services |\n"
            "| `x`, `y` | float or null | `null` | Canvas position |\n\n"
            "### `connections` — Service Wiring\n\n"
            "Array of `{\"from\": \"<source>\", \"to\": \"<target>\"}` objects.\n"
            "Connections declare dependencies and control startup ordering.\n\n"
            "### `deployments` — Deployment Targets\n\n"
            "| Field | Type | Description |\n"
            "|-------|------|-------------|\n"
            "| `provider` | string | `vercel`, `netlify`, `cloudflare` |\n"
            "| `targets` | string[] | App names to deploy |\n"
            "| `env` | object | Deployment-specific env vars |\n"
            "| `x`, `y` | float or null | Canvas position |\n\n"
            "### `previews` — Browser Preview Nodes\n\n"
            "| Field | Type | Description |\n"
            "|-------|------|-------------|\n"
            "| `target` | string | App name to preview |\n"
            "| `x`, `y` | float or null | Canvas position |\n\n"
            "### `primaryApp`\n\n"
            "String. Name of the default app (must exist in `apps`). Used as the\n"
            "main preview target. If missing or invalid, the first app is used.\n\n"
            "### Full Example — Multi-Service Project\n\n"
            "```json\n"
            "{\n"
            '  "apps": {\n'
            '    "frontend": {\n'
            '      "directory": ".",\n'
            '      "port": 3000,\n'
            '      "start": "npm install && npm run dev -- --hostname 0.0.0.0 --port 3000",\n'
            '      "build": "npm run build",\n'
            '      "output": ".next/standalone",\n'
            '      "framework": "nextjs",\n'
            '      "env": {\n'
            '        "DATABASE_URL": "postgresql://postgres:postgres@postgres:5432/app",\n'
            '        "REDIS_URL": "redis://redis:6379"\n'
            "      }\n"
            "    },\n"
            '    "api": {\n'
            '      "directory": "api",\n'
            '      "port": 8000,\n'
            '      "start": "pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port 8000",\n'
            '      "framework": "fastapi",\n'
            '      "env": {\n'
            '        "DATABASE_URL": "postgresql://postgres:postgres@postgres:5432/app"\n'
            "      }\n"
            "    }\n"
            "  },\n"
            '  "infrastructure": {\n'
            '    "postgres": {\n'
            '      "image": "postgres:16-alpine",\n'
            '      "port": 5432,\n'
            '      "env": {\n'
            '        "POSTGRES_USER": "postgres",\n'
            '        "POSTGRES_PASSWORD": "postgres",\n'
            '        "POSTGRES_DB": "app"\n'
            "      }\n"
            "    },\n"
            '    "redis": {\n'
            '      "image": "redis:7-alpine",\n'
            '      "port": 6379\n'
            "    }\n"
            "  },\n"
            '  "connections": [\n'
            '    {"from": "frontend", "to": "postgres"},\n'
            '    {"from": "frontend", "to": "redis"},\n'
            '    {"from": "api", "to": "postgres"}\n'
            "  ],\n"
            '  "primaryApp": "frontend"\n'
            "}\n"
            "```\n\n"
            "---\n\n"
            "## 2. Validation Rules\n\n"
            "All `start` commands are security-validated before execution.\n\n"
            "### Blocked Dangerous Patterns\n\n"
            "The following patterns are **always rejected**:\n\n"
            "- `rm -rf /` — filesystem destruction\n"
            "- `curl|sh`, `wget|sh` — download-and-execute\n"
            "- `nc -l` — netcat listener / reverse shell\n"
            "- `dd if=/dev/zero` — disk fill\n"
            "- `eval $(...)` — eval with command substitution\n"
            "- `sudo`, `su` — privilege escalation\n"
            "- `docker` — docker-in-docker\n"
            "- `chmod 777 /`, `chown ... /` — system file permission changes\n"
            "- `$(curl`, `$(wget` — command substitution with network\n"
            "- `> /dev/sda`, `> /proc/` — device/proc writes\n"
            "- `iptables`, `setuid`, `passwd` — system modification\n"
            "- Fork bombs, `/dev/tcp/`, `mkfifo...nc` — shell exploits\n\n"
            "### Safe Command Prefixes (Whitelist)\n\n"
            "Commands must start with one of these prefixes:\n\n"
            "- **Node.js**: `npm`, `node`, `npx`, `yarn`, `pnpm`, `bun`, `bunx`\n"
            "- **Python**: `python`, `python3`, `pip`, `pip3`, `uv`, `uvicorn`, "
            "`gunicorn`, `flask`, `poetry`\n"
            "- **Go**: `go`, `air`\n"
            "- **Rust**: `cargo`, `rustc`\n"
            "- **Java**: `java`, `mvn`, `gradle`\n"
            "- **.NET**: `dotnet`\n"
            "- **Ruby**: `ruby`, `bundle`, `rails`\n"
            "- **PHP**: `php`, `composer`\n"
            "- **Shell**: `cd`, `ls`, `echo`, `sleep`, `cat`, `mkdir`, `cp`, `mv`\n"
            "- **Control flow**: `if`, `for`, `while`, `test`, `[`\n\n"
            "### Other Constraints\n\n"
            "- Max command length: **10,000 characters**\n"
            "- All `start` commands **MUST bind to `0.0.0.0`** (not `localhost` or "
            "`127.0.0.1`), otherwise the service is unreachable from outside the container.\n"
            "- Commands are split on `&&`, `||`, `;`, `|` and each segment is validated.\n\n"
            "---\n\n"
            "## 3. Modification Workflow\n\n"
            "Follow these steps to modify project architecture:\n\n"
            "1. **Read current config:**\n"
            "   ```\n"
            '   read_file(".tesslate/config.json")\n'
            "   ```\n\n"
            "2. **Plan changes** — decide what to add/modify/remove.\n\n"
            "3. **Write updated config:**\n"
            "   ```\n"
            '   write_file(".tesslate/config.json", updated_json)\n'
            "   ```\n"
            "   Writing the config auto-syncs Container database records via the\n"
            "   `setup-config` endpoint.\n\n"
            "4. **Restart affected containers:**\n"
            "   ```\n"
            '   project_control(action="restart_container", container_name="api")\n'
            "   ```\n\n"
            "5. **Verify health:**\n"
            "   ```\n"
            '   project_control(action="health_check", container_name="api")\n'
            "   ```\n\n"
            "**Important:** Always read before writing. Never blindly overwrite the config.\n\n"
            "---\n\n"
            "## 4. Common Operations\n\n"
            "### Adding a Database (PostgreSQL)\n\n"
            "1. Add to `infrastructure`:\n"
            "   ```json\n"
            '   "postgres": {\n'
            '     "image": "postgres:16-alpine",\n'
            '     "port": 5432,\n'
            '     "env": {\n'
            '       "POSTGRES_USER": "postgres",\n'
            '       "POSTGRES_PASSWORD": "postgres",\n'
            '       "POSTGRES_DB": "mydb"\n'
            "     }\n"
            "   }\n"
            "   ```\n"
            "2. Add connection: `{\"from\": \"frontend\", \"to\": \"postgres\"}`\n"
            "3. Add env var to app:\n"
            '   `"DATABASE_URL": "postgresql://postgres:postgres@postgres:5432/mydb"`\n'
            "4. Restart the app container.\n\n"
            "### Adding Redis\n\n"
            "1. Add to `infrastructure`:\n"
            "   ```json\n"
            '   "redis": {\n'
            '     "image": "redis:7-alpine",\n'
            '     "port": 6379\n'
            "   }\n"
            "   ```\n"
            "2. Add connection from the consuming app.\n"
            "3. Add `REDIS_URL` env var: `\"redis://redis:6379\"`\n\n"
            "### Changing a Startup Command\n\n"
            "1. Update the `start` field in the app.\n"
            "2. Ensure the command binds to `0.0.0.0`.\n"
            "3. Restart the container.\n\n"
            "### Modifying Environment Variables\n\n"
            "1. Update the `env` object in the app or infrastructure service.\n"
            "2. Restart the affected container.\n\n"
            "### Changing Ports\n\n"
            "1. Update the `port` field.\n"
            "2. Update any `start` command that references the port.\n"
            "3. Update env vars in connected services that reference the old port.\n"
            "4. Restart the container.\n\n"
            "### Adding a Connection\n\n"
            "1. Add `{\"from\": \"<source>\", \"to\": \"<target>\"}` to `connections`.\n"
            "2. Add relevant env vars to the source service so it knows how to reach\n"
            "   the target (e.g., connection string, host/port).\n\n"
            "### Adding a New App Service\n\n"
            "1. Add to `apps` with `directory`, `port`, `start`, and `framework`.\n"
            "2. Wire connections to any infrastructure it depends on.\n"
            "3. Add env vars for connection strings.\n"
            "4. Consider updating `primaryApp` if this should be the default.\n\n"
            "---\n\n"
            "## 5. Lifecycle Control\n\n"
            "Use the `project_control` tool to manage running containers.\n\n"
            "| Action | Description | Example |\n"
            "|--------|-------------|---------|\n"
            '| `status` | Get all container statuses and URLs | `project_control(action="status")` |\n'
            '| `restart_container` | Restart a single container by name | `project_control(action="restart_container", container_name="api")` |\n'
            '| `restart_all` | Restart all containers in the project | `project_control(action="restart_all")` |\n'
            '| `reload_config` | Re-sync config.json to database | `project_control(action="reload_config")` |\n'
            '| `container_logs` | View last 100 lines of logs | `project_control(action="container_logs", container_name="api")` |\n'
            '| `health_check` | HTTP health check on a container | `project_control(action="health_check", container_name="api")` |\n\n'
            "**Typical workflow after config changes:**\n"
            "1. Write updated config.json\n"
            "2. `reload_config` to sync DB records\n"
            "3. `restart_container` for each affected service\n"
            "4. `health_check` to verify services are healthy\n"
            "5. `container_logs` if health check fails\n\n"
            "---\n\n"
            "## 6. Dependency Ordering\n\n"
            "- Infrastructure services (databases, caches) start **before** app services.\n"
            "- The platform uses `connections` to determine startup order automatically.\n"
            "- When adding a new dependency, **always add the connection** so the platform\n"
            "  knows to start the dependency first.\n"
            "- If an app fails to start because a database is not ready, the platform\n"
            "  retries with backoff based on the connection graph.\n\n"
            "---\n\n"
            "## 7. Platform Notes\n\n"
            "- Config works identically in Docker and Kubernetes modes. Do not add\n"
            "  platform-specific conditional logic.\n"
            "- URLs are auto-generated by the platform (e.g., `<container>.localhost`\n"
            "  in Docker, `<container>.<domain>` in Kubernetes). Never hardcode URLs.\n"
            "- Infrastructure service names in config become the hostname for\n"
            "  inter-container networking (e.g., `postgres` resolves to the PostgreSQL\n"
            "  container).\n"
            "- The `exports` field lets a service expose values to connected services\n"
            "  for automatic env-var injection.\n"
            "- The `x` and `y` fields are for the visual architecture canvas only;\n"
            "  they have no effect on runtime behavior.\n"
        ),
    },
]


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from markdown content."""
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL).strip()


async def _fetch_skill_body(url: str, fallback: str) -> str:
    """Fetch SKILL.md from a GitHub raw URL, stripping frontmatter.

    Falls back to the bundled description on any error.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                body = _strip_frontmatter(resp.text)
                if body:
                    return body
                logger.warning("Empty SKILL.md from %s, using fallback", url)
            else:
                logger.warning(
                    "Failed to fetch SKILL.md from %s (HTTP %d), using fallback",
                    url,
                    resp.status_code,
                )
    except Exception:
        logger.warning("Error fetching SKILL.md from %s, using fallback", url, exc_info=True)
    return fallback


async def seed_skills(db: AsyncSession) -> int:
    """Seed marketplace skills (item_type='skill'). Upserts by slug.

    Returns:
        Number of newly created skills.
    """
    tesslate_user = await get_or_create_tesslate_account(db)
    created = 0
    updated = 0

    # --- Open-source skills (fetch from GitHub) ---
    for skill_data in OPENSOURCE_SKILLS:
        skill_data = {**skill_data}
        github_url = skill_data.pop("github_raw_url")
        fallback = skill_data.pop("fallback_skill_body")
        skill_data["skill_body"] = await _fetch_skill_body(github_url, fallback)

        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == skill_data["slug"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in skill_data.items():
                if key != "slug":
                    setattr(existing, key, value)
            existing.git_repo_url = skill_data.get("git_repo_url")
            if not existing.created_by_user_id:
                existing.created_by_user_id = tesslate_user.id
            updated += 1
            logger.info("Updated skill: %s", skill_data["slug"])
        else:
            agent = MarketplaceAgent(
                **skill_data,
                created_by_user_id=tesslate_user.id,
            )
            db.add(agent)
            created += 1
            logger.info("Created skill: %s", skill_data["name"])

    # --- Tesslate custom skills (bundled) ---
    for skill_data in TESSLATE_SKILLS:
        skill_data = {**skill_data}

        result = await db.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.slug == skill_data["slug"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in skill_data.items():
                if key != "slug":
                    setattr(existing, key, value)
            if not existing.created_by_user_id:
                existing.created_by_user_id = tesslate_user.id
            updated += 1
            logger.info("Updated skill: %s", skill_data["slug"])
        else:
            agent = MarketplaceAgent(
                **skill_data,
                created_by_user_id=tesslate_user.id,
            )
            db.add(agent)
            created += 1
            logger.info("Created skill: %s", skill_data["name"])

    await db.commit()

    logger.info(
        "Skills: %d created, %d updated",
        created,
        updated,
    )
    return created
