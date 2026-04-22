# TESSLATE.md - Project Context

> Context for AI agents working on this project.

## Framework Configuration

**Framework**: Next.js
**Version**: 16.1
**Port**: 3000

**Tech Stack:**
- Next.js 16.1
- React 19.2
- TypeScript 5.9
- Tailwind CSS v4.2
- App Router
- Turbopack
- React Compiler

## File Structure

```
app/
├── api/                 # API routes
├── components/          # React components
├── globals.css          # Global styles (Tailwind v4)
├── layout.tsx           # Root layout
└── page.tsx             # Home page
public/                  # Static assets
next.config.ts           # Next.js config
postcss.config.mjs       # PostCSS config (Tailwind v4)
```

## Development Server

**Start Command**:
```bash
bun install --frozen-lockfile
bun run dev -- --hostname 0.0.0.0 --port 3000
```

**Production Build**:
```bash
bun run build
bun start
```

## Notes

- Dependencies are pre-baked (node_modules included)
- Uses bun for package management (fastest)
- Turbopack enabled for fast compilation
- React Compiler enabled for automatic memoization
- Tailwind CSS v4 with @import syntax
- Geist font family (sans + mono)
