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
