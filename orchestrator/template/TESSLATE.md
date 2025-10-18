# TESSLATE.md - Project Context

> This file provides context and guidelines for AI agents working on this project.

## Project Overview

- **Framework**: React 18 with Vite
- **Build Tool**: Vite
- **Styling**: Tailwind CSS
- **Routing**: React Router DOM v6
- **Port**: 5173 (Vite default)

## Application Routing

**React Router Setup:**

This template includes React Router DOM v6 pre-configured for client-side navigation with automatic base path handling:

- **Router Location**: `BrowserRouter` is configured inside `src/App.jsx` with dynamic `basename` support
- **Base Path**: Automatically configured via `import.meta.env.BASE_URL` (set by Vite from the `base` config)
- **Routes**: Define routes in `src/App.jsx` using `<Routes>` and `<Route>` components
- **Navigation**: Use `<Link>` components instead of `<a>` tags to prevent page reloads
- **Programmatic Navigation**: Use the `useNavigate()` hook

**Configuration:**

The `vite.config.js` file is pre-configured to use the `VITE_BASE_PATH` environment variable:

```javascript
export default defineConfig({
  base: process.env.VITE_BASE_PATH || '/',
  // ... other config
})
```

This allows the application to work correctly regardless of where it's deployed (root path or subpath).

**Adding New Routes:**

1. Create a new page component (can be a simple function component)
2. Import it in `src/App.jsx`
3. Add a new `<Route>` inside the `<Routes>` component:
   ```jsx
   <Route path="/your-path" element={<YourComponent />} />
   ```

**Example:**

```jsx
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';

function Home() {
  return (
    <div>
      <h1>Home</h1>
      {/* Links are relative to the base path automatically */}
      <Link to="/about">Go to About</Link>
    </div>
  );
}

function About() {
  return <div><h1>About Page</h1></div>;
}

function App() {
  // basename is automatically set from import.meta.env.BASE_URL
  const basename = import.meta.env.BASE_URL;

  return (
    <Router basename={basename}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </Router>
  );
}
```

**Routing Best Practices:**

- Always use `<Link to="/path">` for internal navigation instead of `<a href="/path">`
- Use `useNavigate()` for programmatic navigation instead of `window.location`
- All routes are relative to the base path - write them as absolute paths starting with `/`
- For external links, use regular `<a href="https://...">` tags

## File Structure

```
project/
├── src/
│   ├── components/      # Reusable components
│   ├── pages/           # Page components
│   ├── styles/          # Style files
│   ├── utils/           # Utility functions
│   ├── App.jsx          # Main app with routing
│   └── main.jsx         # Entry point
├── public/              # Static assets
├── index.html           # HTML template
├── package.json         # Dependencies
├── vite.config.js       # Vite configuration
└── TESSLATE.md          # This file
```

## AI Agent Guidelines

When building features for this project, follow these guidelines:

### General Principles

1. **Understand the context**: Read this entire TESSLATE.md file before making changes
2. **Surgical edits**: Modify only the specific files needed for the requested change
3. **Complete files**: Always output complete file contents, never truncate with "..."
4. **Preserve existing code**: Keep all existing logic, state, and patterns when editing
5. **Follow project conventions**: Match the existing code style, naming, and structure
6. **Test your changes**: Verify that modifications work with the existing codebase

### Development Workflow

1. Edit files via Monaco editor or AI chat
2. Files are auto-saved to dev container
3. Vite detects changes and rebuilds automatically
4. Preview updates automatically via HMR

## Build & Deployment

### Development Server
```bash
npm run dev
```
Starts Vite dev server on port 5173 with hot module replacement.

### Production Build
```bash
npm run build
```
Builds optimized production bundle to `dist/` directory.

### Preview Production Build
```bash
npm run preview
```
Preview production build locally.

## Development Server

This project uses Vite's built-in development server with Hot Module Replacement (HMR).

**Starting the server:**
```bash
npm run dev
```

**Key features:**
- Instant server start
- Hot Module Replacement - changes appear instantly
- Optimized dependency pre-bundling
- Runs on port 5173 by default
