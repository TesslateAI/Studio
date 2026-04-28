# Next.js 16 Base Template

A production-ready Next.js 16.1 starter template for Tesslate Studio with pre-baked dependencies for instant startup.

## Features

- **Next.js 16.1** with App Router and Turbopack
- **React 19.2** with Server Components and the stable React Compiler
- **TypeScript 5.9** for type safety
- **Tailwind CSS v4.2** for utility-first styling
- **Geist** font family (sans and mono)
- **bun** for fastest package management
- **Pre-baked node_modules** for instant startup

## What's Included

- App Router with nested layouts
- Tailwind CSS v4 integration (new @import syntax)
- TypeScript strict mode
- Example API route (`/api/hello`)
- Polished landing page with dark mode support
- React Compiler for automatic optimization
- ESLint and PostCSS configuration

## Development

The development server starts automatically when you create a project from this base in Tesslate Studio.

Access your app at the preview URL provided in the IDE.

## Project Structure

```
/app
  /api
    /hello
      route.ts          # Example API route
  layout.tsx            # Root layout (Geist font)
  page.tsx              # Home page
  globals.css           # Global styles (Tailwind v4)
next.config.ts          # Next.js configuration
postcss.config.mjs      # PostCSS configuration
tsconfig.json           # TypeScript configuration
package.json            # Dependencies
```

## API Routes

Create new API routes in `/app/api/`. Example:

```typescript
// app/api/users/route.ts
import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({ users: [] });
}
```

## Server Actions

Mutate data directly from components:

```typescript
async function createUser(formData: FormData) {
  "use server";
  // runs on the server
}
```

## Styling

This template uses Tailwind CSS v4 with the new `@import "tailwindcss"` syntax. Add custom styles in `app/globals.css` or use Tailwind utilities directly in your components.

## Learn More

- [Next.js 16 Documentation](https://nextjs.org/docs)
- [React 19 Documentation](https://react.dev)
- [Tailwind CSS v4 Documentation](https://tailwindcss.com/docs)
- [TypeScript Documentation](https://www.typescriptlang.org/docs)

## Tesslate Studio

This base is optimized for Tesslate Studio. The `TESSLATE.md` file contains configuration for automatic dev server setup.

**Performance Note**: Dependencies are pre-baked (node_modules included) for instant startup -- no install step required.
