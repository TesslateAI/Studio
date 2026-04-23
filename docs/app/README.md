# OpenSail Frontend

**Location**: `app/`

React 19 + TypeScript app that provides the OpenSail visual interface: AI chat, code editor, architecture canvas, design engineer, marketplace, apps, billing, and admin.

## Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| React | 19.1.x | Core UI framework |
| TypeScript | 5.8.x | Type-safe development |
| Vite | 7.1.x | Build tool and dev server |
| React Router | 7.8.x | Client-side routing |
| Tailwind CSS | 4.1.x | Utility-first styling |
| Monaco Editor | 4.7.x | Code editor |
| XYFlow | 12.9.x | Architecture canvas |
| Framer Motion | 12.23.x | Animations |
| Axios | 1.11.x | HTTP client |
| PostHog | 1.29x | Analytics and feature flags |
| xterm.js | 5.5.x | Terminal emulator |
| TipTap | 3.7.x | Rich text (Notes panel) |
| cmdk | – | Command palette |
| react-hotkeys-hook | – | Keyboard shortcuts |

## Directory Navigation

| Directory | Purpose | Doc |
|-----------|---------|-----|
| `app/src/App.tsx`, `main.tsx`, `config.ts` | App entry | `docs/app/CLAUDE.md` |
| `app/src/contexts/` | Global providers | `docs/app/contexts/CLAUDE.md` |
| `app/src/hooks/` | Custom hooks | `docs/app/hooks/CLAUDE.md` |
| `app/src/layouts/` | Page layouts | `docs/app/layouts/CLAUDE.md` |
| `app/src/lib/` | API client, helpers | `docs/app/api/CLAUDE.md` |
| `app/src/pages/` | Route components | `docs/app/pages/CLAUDE.md` |
| `app/src/components/` | Feature + shared components | `docs/app/components/CLAUDE.md` |
| `app/src/services/` | Singleton services | `docs/app/state/task-service.md` |
| `app/src/theme/` | Theme system | `docs/app/state/theme.md` |
| `app/src/types/` | TypeScript definitions | `docs/app/types/CLAUDE.md` |
| `app/src/utils/` | Pure helper modules | `docs/app/utils/CLAUDE.md` |

## Key Features

1. AI chat with streaming agent responses, approval flow, multi-session per project, and a standalone `/chat` route.
2. Multi-view project builder: Code (Monaco), Preview (iframe), Design (Onlook-style visual editor), Architecture (XYFlow canvas), Kanban, Terminal (xterm.js), Assets, Settings.
3. Architecture canvas with container/browser-preview/deployment-target/hosted-agent nodes and typed edges.
4. Design engineer with in-iframe bridge script, pan/zoom canvas, snap overlay, insert palette, inspector, undo/redo with action coalescing.
5. Marketplace + library for agents, bases, skills, MCP servers, themes, models, and Tesslate Apps.
6. Teams + RBAC with per-team billing, invitations, and audit log.
7. External deployments via Vercel, Netlify, Cloudflare, Amplify with OAuth credential storage.
8. Desktop shell (Tauri) with `TitleBar` and runtime config injection.

## Build Commands

```bash
cd app
npm install
npm run dev          # Vite dev server on :5173
npm run build        # Production bundle
npm run preview      # Serve production build
npm run test         # Vitest suite
npm run test:ui      # Vitest UI
npm run lint
npm run lint:fix
npm run format
```

## Environment Variables

`app/.env`:

```
VITE_API_URL=http://localhost:8000
VITE_PUBLIC_POSTHOG_KEY=
VITE_PUBLIC_POSTHOG_HOST=https://app.posthog.com
```

In production, `config.ts` reads `window._env_` injected by nginx at container startup, so a single Docker image can be deployed with per-environment config.

## Related Docs

- `docs/app/CLAUDE.md` – full context for AI agents working on the frontend
- `docs/app/api/CLAUDE.md` – lib/ index
- `docs/app/pages/CLAUDE.md` – every route
- `docs/app/components/CLAUDE.md` – every component
