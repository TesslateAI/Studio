# TESSLATE.md - Project Context

> This file provides context and guidelines for AI agents working on this project.
> Feel free to customize it to match your project's specific needs!

## Project Overview

- **Project Name**: My Tesslate Project
- **Framework**: [Specify your framework: React, Vue, Angular, vanilla JS, etc.]
- **Build Tool**: [Specify: Vite, Webpack, Parcel, none, etc.]
- **Styling**: [Specify: Tailwind CSS, Bootstrap, CSS Modules, Sass, etc.]
- **Additional Libraries**: [List key dependencies]
- **Created**: [Auto-generated timestamp]

## Application Summary

**What this app does:**
[Describe your application's purpose, features, and functionality here. Be specific about:
- Main use case and target users
- Key features and capabilities
- Any unique requirements or constraints
- Business logic or domain concepts]

**Tech Stack:**
[Detail the specific technologies and versions you're using]

**Architecture:**
[Describe the application structure, patterns, and design decisions]

## Dev Server Configuration

### Routing & Access

- **Local Development**: `http://localhost:[PORT]` [Specify your dev server port]
- **Tesslate Studio Preview**: `https://user{USER_ID}-project{PROJECT_ID}.studio-test.tesslate.com`
- **Port**: [Specify: 5173 for Vite, 3000 for Create React App, 8080 for Vue CLI, etc.]
- **Hot Module Replacement**: [Specify if enabled and how it's configured]
- **Build Tool Configuration**: [Specify config file: vite.config.js, webpack.config.js, etc.]

### Application Routing

**React Router Setup:**

This template includes React Router DOM v6 pre-configured for client-side navigation:

- **Router Location**: `BrowserRouter` is configured inside `src/App.jsx`
- **Routes**: Define routes in `src/App.jsx` using `<Routes>` and `<Route>` components
- **Navigation**: Use `<Link>` components instead of `<a>` tags to prevent page reloads
- **Programmatic Navigation**: Use the `useNavigate()` hook

**Adding New Routes:**

1. Create a new page component (can be a simple function component)
2. Import it in `src/App.jsx`
3. Add a new `<Route>` inside the `<Routes>` component:
   ```jsx
   <Route path="/your-path" element={<YourComponent />} />
   ```

**Important for Tesslate Studio Preview:**

- The app automatically communicates URL changes to the parent Tesslate Studio window
- Back/forward navigation from the Studio UI is supported via `postMessage`
- This communication is handled automatically - no additional setup needed

**Example:**

```jsx
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';

function Home() {
  return (
    <div>
      <h1>Home</h1>
      <Link to="/about">Go to About</Link>
    </div>
  );
}

function About() {
  return <div><h1>About Page</h1></div>;
}

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </Router>
  );
}
```

## File Structure

```
project/
├── [Describe your project structure here]
├── src/                 # Source code directory (if applicable)
│   ├── components/      # Reusable components (if applicable)
│   ├── pages/           # Page components or views (if applicable)
│   ├── styles/          # Style files
│   ├── utils/           # Utility functions
│   └── [other directories]
├── public/              # Static assets (if applicable)
├── package.json         # Node.js dependencies (if applicable)
├── [config files]       # Build tool, linter, formatter configs
└── TESSLATE.md          # This file - Project context for AI agents
```

**Key Directories:**
[Explain the purpose of each major directory in your project]

**Important Files:**
[List and explain critical configuration files]

## AI Agent Guidelines

When building features for this project, follow these guidelines:

### 🎯 General Principles

1. **Understand the context**: Read this entire TESSLATE.md file before making changes
2. **Surgical edits**: Modify only the specific files needed for the requested change
3. **Complete files**: Always output complete file contents, never truncate with "..."
4. **Preserve existing code**: Keep all existing logic, state, and patterns when editing
5. **Follow project conventions**: Match the existing code style, naming, and structure
6. **Test your changes**: Verify that modifications work with the existing codebase

### 📦 Dependency Management

[Specify how dependencies are managed in your project:
- For Node.js projects: Dependencies in `package.json`, installed with `npm install` or `yarn install`
- For Python projects: Requirements in `requirements.txt` or `pyproject.toml`, installed with `pip install`
- For other ecosystems: Specify your package manager and dependency files]

### 🎨 Code Style and Conventions

**File Naming:**
[Specify your naming conventions:
- Components: PascalCase, camelCase, kebab-case?
- Files: .jsx, .tsx, .vue, .js?
- Directories: lowercase, camelCase?]

**Code Organization:**
[Specify how code should be organized:
- One component per file or multiple related components?
- Where should new features be added?
- How should imports be ordered?]

**Styling Approach:**
[Specify your styling method:
- Utility classes (Tailwind, Bootstrap)
- CSS Modules
- Styled Components / CSS-in-JS
- Plain CSS/Sass files
- Include specific class naming conventions]

### 🔧 Development Workflow

#### Hot Module Replacement (HMR)

[Specify if HMR is enabled and how it works in your project:
- Which file types trigger updates?
- Is state preserved?
- Any special HMR configuration?]

#### Making Changes

1. Edit files via Monaco editor or AI chat
2. Files are auto-saved to dev container
3. [Build tool] detects changes and rebuilds (if applicable)
4. Preview updates automatically (if HMR is enabled)

#### Debugging

[Specify debugging tools and approaches:
- Browser DevTools usage
- Framework-specific devtools (React DevTools, Vue DevTools, etc.)
- Console logging conventions
- Error handling patterns
- Where to find build errors]

## Common Tasks

[Provide examples of common development tasks specific to your project. Here are some templates:]

### Adding a New Page/View

[Provide step-by-step instructions for adding a new page:
1. Create the page file in [directory]
2. Register the route in [file]
3. Add navigation link in [file]
4. Follow [naming convention]]

### Adding a Dependency

[Explain how to add dependencies in your project:
- For Node.js: Edit package.json and run npm install
- For Python: Add to requirements.txt and run pip install
- Specify any automatic installation triggers]

### Creating a Reusable Component

[Provide a template or example for creating components in your framework:
- Where to create the file
- How to name it
- How to import and use it
- Any component patterns to follow]

### Working with State/Data

[Explain state management patterns:
- Global state: Redux, Vuex, Context, etc.
- Local state: Component state patterns
- Data fetching: Where and how to fetch data
- Form handling: Preferred approach]

## Build & Deployment

[Specify build and deployment commands for your project]

### Development Server
```bash
[Your dev server command, e.g., npm run dev, python manage.py runserver, etc.]
```
[Describe what this command does, port it runs on, and any configuration]

### Production Build
```bash
[Your build command, e.g., npm run build, make build, etc.]
```
[Describe build output location and any post-build steps]

### Testing
```bash
[Your test command, e.g., npm test, pytest, etc.]
```
[Describe testing setup and coverage requirements]

### Linting/Code Quality
```bash
[Your linting command, e.g., npm run lint, flake8, etc.]
```
[Describe code quality tools and standards]

## Technical Details

### Build Tool Configuration

[Specify your build tool configuration details:
- Config file location and key settings
- Environment-specific configuration
- Proxy settings (if applicable)
- Plugin/loader configuration]

### Container Environment

This project runs in a Tesslate Studio development container:

- **Base Image**: [Specify: Node.js, Python, etc. with version]
- **Working Directory**: `/app/project`
- **Storage**: Persistent volume with user isolation
- **Resources**: Memory and CPU limits managed by Tesslate Studio
- **Networking**: HTTPS ingress with authentication

### File Persistence

Files are automatically saved:
1. **Database** - Version history and backup
2. **Dev Container** - Live development environment
3. Changes persist across restarts

## Styling Guidelines

### UI Patterns and Components

[Provide common UI patterns and component examples for your project:

**For Tailwind CSS:**
- Common utility class combinations
- Responsive design patterns
- Component examples (buttons, cards, forms)

**For CSS Modules:**
- Class naming conventions
- How to import and use styles
- Theme/variable usage

**For Styled Components:**
- Component styling patterns
- Theme configuration
- Reusable style utilities

**For Plain CSS:**
- Class naming conventions (BEM, etc.)
- File organization
- CSS variable usage]

### Design System

[If applicable, document your design system:
- Color palette
- Typography scale
- Spacing system
- Component library
- Accessibility requirements]

## Customizing This File

**This TESSLATE.md file is yours to customize!**

This file helps AI agents understand your project. Edit it to document your project's specific requirements:

### Recommended Customizations

Fill in all the bracketed placeholders `[...]` throughout this file with your actual project information:

- **Project Overview**: Specify your exact tech stack and architecture
- **File Structure**: Document your actual directory structure
- **AI Guidelines**: Add project-specific coding conventions and patterns
- **Common Tasks**: Provide real examples from your project
- **API Integration**: Document API endpoints, authentication, and data models
- **Environment Variables**: List required configuration
- **External Services**: Note third-party integrations (databases, auth providers, payment gateways, etc.)
- **Business Logic**: Explain domain-specific concepts and workflows
- **Testing Strategy**: Document testing requirements and patterns
- **Deployment Process**: Add deployment instructions and environments

### Tips for Effective Context

1. **Be Specific**: Replace placeholders with actual project details
2. **Include Examples**: Real code examples help AI agents understand patterns
3. **Document Constraints**: Note any limitations, gotchas, or special requirements
4. **Keep It Updated**: Update this file as your project evolves
5. **Think Like an Agent**: What would a new developer need to know?

### Example Customizations

Instead of:
```
- **Framework**: [Specify your framework]
```

Write:
```
- **Framework**: React 18.2 with TypeScript 5.0
- **Key Libraries**: React Query for data fetching, Zustand for state management
```

Instead of:
```
[Describe your application's purpose]
```

Write:
```
This is a task management application for remote teams. Features include:
- Real-time collaboration on task boards
- Kanban-style workflow management
- Integration with Slack and GitHub
- Role-based access control (Owner, Admin, Member)
```

---

**Resources:**
- Tesslate Studio Documentation: [docs.tesslate.com](https://docs.tesslate.com)
- Add links to your framework docs
- Add links to your design system or component library
- Add links to internal documentation

**Last Updated**: [Update this when you make major changes]
**Maintained By**: [Your team name]
