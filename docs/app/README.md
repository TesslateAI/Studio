# Tesslate Studio Frontend

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/`

The Tesslate Studio frontend is a sophisticated React application that provides a visual interface for building, editing, and deploying full-stack applications through AI-powered code generation. Users interact with AI agents to describe what they want, see code being written in real-time, and manage their containerized deployments.

## Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| **React** | 19.1.1 | Core UI framework with modern hooks and concurrent features |
| **TypeScript** | 5.8.3 | Type-safe development |
| **Vite** | 7.1.2 | Lightning-fast build tool and dev server |
| **React Router** | 7.8.2 | Client-side routing |
| **Tailwind CSS** | 4.1.12 | Utility-first styling |
| **Monaco Editor** | 4.7.0 | VS Code-powered code editor |
| **XYFlow** | 12.9.3 | Interactive graph canvas for architecture visualization |
| **Framer Motion** | 12.23.24 | Smooth animations and transitions |
| **Axios** | 1.11.0 | HTTP client for API calls |
| **PostHog** | 1.292.0 | Analytics and feature flags |
| **xterm.js** | 5.5.0 | Terminal emulator |
| **TipTap** | 3.7.0 | Rich text editor for notes |

## Directory Structure

```
app/
├── src/
│   ├── main.tsx                    # App entry point, PostHog provider setup
│   ├── App.tsx                     # Router configuration, auth guards, toast setup
│   ├── index.css                   # Global styles
│   ├── vite-env.d.ts              # Vite TypeScript declarations
│   │
│   ├── pages/                      # Top-level route components
│   │   ├── Dashboard.tsx           # Project list, creation, user profile
│   │   ├── Project.tsx             # Main builder: editor + chat + preview
│   │   ├── ProjectGraphCanvas.tsx  # Architecture visualization with XYFlow
│   │   ├── Marketplace.tsx         # Browse AI agents and project bases
│   │   ├── MarketplaceDetail.tsx   # Agent/base details and purchase
│   │   ├── MarketplaceAuthor.tsx   # Creator profile page
│   │   ├── Library.tsx             # User's purchased agents and bases
│   │   ├── settings/               # Modular settings pages
│   │   │   ├── ProfileSettings.tsx       # Profile, avatar, bio
│   │   │   ├── PreferencesSettings.tsx   # Theme, diagram model
│   │   │   ├── SecuritySettings.tsx      # Password, 2FA, sessions
│   │   │   ├── DeploymentSettings.tsx    # Provider credentials
│   │   │   └── BillingSettings.tsx       # Subscription, invoices
│   │   ├── Login.tsx               # JWT and OAuth login forms
│   │   ├── Register.tsx            # User registration
│   │   ├── Landing.tsx             # Marketing landing page (old)
│   │   ├── NewLandingPage.tsx      # New landing page with animations
│   │   ├── Feedback.tsx            # User feedback submission
│   │   ├── AdminDashboard.tsx      # Admin panel for platform management
│   │   ├── Referrals.tsx           # Referral program page
│   │   ├── AuthCallback.tsx        # GitHub OAuth callback for git operations
│   │   ├── OAuthLoginCallback.tsx  # General OAuth login callback
│   │   └── Logout.tsx              # Logout handler
│   │
│   ├── components/                 # Reusable UI components
│   │   ├── chat/                   # AI chat interface
│   │   │   ├── ChatContainer.tsx   # Main chat component with streaming
│   │   │   ├── ChatInput.tsx       # Message input with file attachments
│   │   │   ├── ChatMessage.tsx     # User/AI message rendering
│   │   │   ├── AgentSelector.tsx   # Agent switcher dropdown
│   │   │   ├── ApprovalRequestCard.tsx # Tool execution approval UI
│   │   │   ├── EditModeStatus.tsx  # Ask vs Edit mode indicator
│   │   │   ├── ToolDropdown.tsx    # Tool selection dropdown
│   │   │   ├── TypingIndicator.tsx # Animated typing indicator
│   │   │   └── UsageRibbon.tsx     # Token usage display
│   │   │
│   │   ├── panels/                 # Sidebar panels for project features
│   │   │   ├── ArchitecturePanel.tsx   # View containers and connections
│   │   │   ├── AssetsPanel.tsx         # File browser with upload
│   │   │   ├── GitHubPanel.tsx         # Git operations (commit, push, pull)
│   │   │   ├── DeploymentsPanel.tsx    # External deployments (Vercel, etc.)
│   │   │   ├── KanbanPanel.tsx         # Task board for project planning
│   │   │   ├── NotesPanel.tsx          # Rich text notes with TipTap
│   │   │   ├── SettingsPanel.tsx       # Project settings
│   │   │   ├── TerminalPanel.tsx       # xterm.js terminal for shell access
│   │   │   └── MarketplacePanel.tsx    # In-project marketplace browser
│   │   │
│   │   ├── billing/                # Subscription and payment components
│   │   │   ├── SubscriptionPlans.tsx    # Plan selection and upgrade
│   │   │   ├── UsageDashboard.tsx       # Resource usage charts
│   │   │   ├── TransactionHistory.tsx   # Payment history
│   │   │   ├── AgentPurchaseButton.tsx  # Marketplace purchase flow
│   │   │   ├── CreditsPurchaseModal.tsx # Buy credits
│   │   │   ├── ProjectLimitBanner.tsx   # Upgrade prompts
│   │   │   ├── SubscriptionStatus.tsx   # Current plan badge
│   │   │   ├── UpgradeModal.tsx         # Upgrade modal
│   │   │   └── DeployButton.tsx         # Deploy with usage checks
│   │   │
│   │   ├── modals/                 # Modal dialogs
│   │   │   ├── CreateProjectModal.tsx   # New project wizard
│   │   │   ├── DeploymentModal.tsx      # Deploy to Vercel/Netlify/CF
│   │   │   ├── GitCommitDialog.tsx      # Git commit UI
│   │   │   ├── GitHubConnectModal.tsx   # Connect GitHub account
│   │   │   ├── GitHubImportModal.tsx    # Import from GitHub
│   │   │   ├── RepoImportModal/         # Unified repo import (GH/GL/BB)
│   │   │   ├── ConfirmDialog.tsx        # Generic confirmation
│   │   │   ├── FeedbackModal.tsx        # Submit feedback
│   │   │   └── CreateFeedbackModal.tsx  # Create feedback (admin)
│   │   │
│   │   ├── marketplace/            # Marketplace-specific components
│   │   │   ├── AgentCard.tsx       # Agent preview card
│   │   │   ├── FeaturedCard.tsx    # Featured item card
│   │   │   ├── ReviewCard.tsx      # User review display
│   │   │   ├── RatingPicker.tsx    # Star rating input
│   │   │   └── StatsBar.tsx        # Stats display (downloads, rating)
│   │   │
│   │   ├── edges/                  # XYFlow custom edge types
│   │   │   ├── HttpApiEdge.tsx     # HTTP API connection visual
│   │   │   ├── DatabaseEdge.tsx    # Database connection visual
│   │   │   ├── CacheEdge.tsx       # Cache connection visual
│   │   │   ├── EnvInjectionEdge.tsx # Environment variable injection
│   │   │   └── BrowserPreviewEdge.tsx # Preview node connection
│   │   │
│   │   ├── ui/                     # Generic UI components
│   │   │   ├── NavigationSidebar.tsx   # Main app navigation
│   │   │   ├── FloatingPanel.tsx       # Floating panel wrapper
│   │   │   ├── FloatingSidebar.tsx     # Resizable sidebar
│   │   │   ├── Breadcrumbs.tsx         # Breadcrumb navigation
│   │   │   ├── Tooltip.tsx             # Tooltip component
│   │   │   ├── Dropdown.tsx            # Generic dropdown
│   │   │   ├── Toast.tsx               # Custom toast notifications
│   │   │   ├── Tabs.tsx                # Tab component
│   │   │   ├── StatusBadge.tsx         # Status indicator
│   │   │   ├── TaskProgress.tsx        # Task progress bar
│   │   │   ├── ToggleSwitch.tsx        # Toggle switch
│   │   │   ├── HelpModal.tsx           # Help documentation modal
│   │   │   ├── MobileMenu.tsx          # Mobile navigation menu
│   │   │   ├── MarketplaceCard.tsx     # Marketplace item card
│   │   │   ├── GlassContainer.tsx      # Glassmorphism container
│   │   │   ├── TechStackIcons.tsx      # Technology icons
│   │   │   ├── MarkerPill.tsx          # Tag/marker pill
│   │   │   ├── MarkerEditor.tsx        # Edit markers
│   │   │   ├── MarkerPalette.tsx       # Marker color picker
│   │   │   ├── button.tsx              # Button component
│   │   │   ├── textarea.tsx            # Textarea component
│   │   │   └── ruixen-moon-chat.tsx    # Animated chat icon
│   │   │
│   │   ├── AgentMessage.tsx        # Agent response message rendering
│   │   ├── AgentStep.tsx           # Agent execution step display
│   │   ├── AgentDebugPanel.tsx     # Agent debugging interface
│   │   ├── CodeEditor.tsx          # Monaco editor wrapper
│   │   ├── BrowserPreview.tsx      # iframe preview with controls
│   │   ├── BrowserPreviewNode.tsx  # XYFlow preview node component
│   │   ├── ContainerNode.tsx       # XYFlow container node component
│   │   ├── ContainerPropertiesPanel.tsx # Container configuration panel
│   │   ├── GraphCanvas.tsx         # XYFlow canvas wrapper
│   │   ├── DashboardLayout.tsx     # Dashboard layout with sidebar
│   │   ├── Layout.tsx              # Generic page layout
│   │   ├── DottedSurface.tsx       # Animated dot background
│   │   ├── PulsingGridSpinner.tsx  # Loading spinner
│   │   ├── MobileWarning.tsx       # Mobile device warning
│   │   ├── DiscordSupport.tsx      # Discord support link
│   │   ├── Walkthrough.tsx         # Onboarding walkthrough
│   │   ├── DeploymentsDropdown.tsx # Deployment actions dropdown
│   │   ├── ExternalServiceCredentialModal.tsx # API keys for external services
│   │   ├── ImageUpload.tsx         # Image upload component
│   │   ├── MarketplaceSidebar.tsx  # Marketplace filtering sidebar
│   │   ├── Preview.tsx             # Legacy preview component
│   │   ├── ToolCallDisplay.tsx     # Tool execution visualization
│   │   └── ToolManagement.tsx      # Manage agent tools
│   │
│   ├── lib/                        # Core libraries and utilities
│   │   ├── api.ts                  # Axios instance, auth interceptors, API methods
│   │   ├── git-api.ts              # Git operations API calls
│   │   ├── github-api.ts           # GitHub-specific API calls
│   │   ├── git-providers-api.ts    # Unified git provider API (GH/GL/BB)
│   │   └── utils.ts                # Utility functions (classNames, etc.)
│   │
│   ├── hooks/                      # Custom React hooks
│   │   ├── useTask.ts              # Task polling and status tracking
│   │   ├── useTaskNotifications.ts # WebSocket notifications for tasks
│   │   └── useReferralTracking.ts  # Track referral codes from URL
│   │
│   ├── services/                   # Business logic services
│   │   └── taskService.ts          # Task management service
│   │
│   ├── types/                      # TypeScript type definitions
│   │   ├── agent.ts                # Agent and chat message types
│   │   ├── billing.ts              # Billing and subscription types
│   │   ├── git.ts                  # Git operation types
│   │   ├── git-providers.ts        # Git provider types (GH/GL/BB)
│   │   └── assets.ts               # Asset management types
│   │
│   ├── theme/                      # Theme and styling
│   │   ├── index.ts                # Theme provider and context
│   │   ├── ThemeContext.tsx        # Theme state management
│   │   ├── variables.css           # CSS custom properties
│   │   └── fonts.ts                # Font definitions
│   │
│   ├── utils/                      # Utility modules
│   │   └── fileEvents.ts           # Custom event system for file updates
│   │
│   └── test/                       # Test setup
│       └── setup.ts                # Vitest configuration
│
├── public/                         # Static assets
├── Dockerfile.prod                 # Production Docker build
├── nginx.conf                      # NGINX config for production
├── package.json                    # Dependencies and scripts
├── tsconfig.json                   # TypeScript configuration
├── vite.config.ts                  # Vite build configuration
├── tailwind.config.js              # Tailwind CSS configuration
└── .env.example                    # Environment variable template

```

## Key Features

### 1. AI-Powered Code Generation
The chat interface connects to AI agents that can write code, modify files, execute commands, and answer questions. Streaming responses show code being generated in real-time.

### 2. Multi-View Project Builder
- **Code View**: Monaco editor with syntax highlighting, IntelliSense, and file tree
- **Preview**: Live iframe preview of running containers with URL navigation
- **Graph View**: XYFlow-based architecture visualization showing containers and connections
- **Kanban**: Drag-and-drop task board for project planning
- **Terminal**: xterm.js terminal for direct shell access

### 3. Container Management
Each project can have multiple containers (frontend, backend, database, etc.). The UI shows container status, allows starting/stopping, and routes to specific container URLs.

### 4. Real-Time Collaboration Features
- WebSocket-based agent streaming
- File change events propagate across components
- Container status polling
- Task notifications via WebSocket

### 5. Marketplace Integration
Browse, purchase, and use pre-built AI agents and project templates. Agents can be enabled per-project and selected in the chat interface.

### 6. External Deployments
Deploy to Vercel, Netlify, Cloudflare Pages, or AWS Amplify directly from the UI. OAuth integration for one-click deployment.

### 7. Git Integration
Commit, push, pull, and manage GitHub repositories. Import existing repos or connect new ones. Visual git history and diff viewing.

## Build and Development Commands

```bash
# Install dependencies
npm install

# Start dev server (http://localhost:5173)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Run tests
npm run test

# Run tests with UI
npm run test:ui

# Run tests with coverage
npm run test:coverage

# Lint code
npm run lint

# Lint and auto-fix
npm run lint:fix

# Format code with Prettier
npm run format

# Check formatting
npm run format:check
```

## Environment Variables

Create `.env` in the `app/` directory:

```bash
# API backend URL
VITE_API_URL=http://localhost:8000

# PostHog analytics (optional)
VITE_PUBLIC_POSTHOG_KEY=your_posthog_key
VITE_PUBLIC_POSTHOG_HOST=https://app.posthog.com
```

## Common Patterns

### API Calls
All API calls go through `lib/api.ts`, which handles:
- JWT Bearer token authentication (localStorage)
- Cookie-based OAuth authentication (withCredentials)
- CSRF token management for state-changing operations
- 401 redirect to login (except for task polling)
- Request/response interceptors

```typescript
import { projectsApi } from '../lib/api';

// Fetch all projects
const projects = await projectsApi.getAll();

// Create a project
const newProject = await projectsApi.create({ name: 'My App', base_id: null });

// Start containers
await projectsApi.startProject(projectSlug);
```

### WebSocket Streaming
Agent responses stream over WebSocket. The connection is established once and reused:

```typescript
import { createWebSocket } from '../lib/api';

const ws = createWebSocket();

ws.addEventListener('message', (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'agent_response') {
    // Handle streaming token
    setCurrentStream(prev => prev + data.content);
  }
});

ws.send(JSON.stringify({
  type: 'chat_message',
  project_id: projectId,
  message: userMessage,
  agent_id: currentAgent.backendId
}));
```

### File Events
Components communicate file changes via a custom event system:

```typescript
import { fileEvents } from '../utils/fileEvents';

// Emit file change
fileEvents.emit('fileUpdated', { filePath: 'src/App.tsx', content: newContent });

// Listen for file changes
useEffect(() => {
  const handler = (detail: { filePath: string, content: string }) => {
    // Update editor content
    setEditorContent(detail.content);
  };
  fileEvents.on('fileUpdated', handler);
  return () => fileEvents.off('fileUpdated', handler);
}, []);
```

### Theme Context
Dark/light mode is managed via React context:

```typescript
import { useTheme } from '../theme/ThemeContext';

function MyComponent() {
  const { theme, toggleTheme } = useTheme();

  return (
    <button onClick={toggleTheme}>
      {theme === 'dark' ? <Sun /> : <Moon />}
    </button>
  );
}
```

### Route Guards
Private routes check authentication before rendering:

```typescript
// App.tsx
function PrivateRoute({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const token = localStorage.getItem('token');
        if (token) {
          setIsAuthenticated(true);
          return;
        }

        // Check cookie-based auth (OAuth)
        const response = await axios.get(`${API_URL}/api/users/me`, {
          withCredentials: true,
        });
        setIsAuthenticated(response.status === 200);
      } catch {
        setIsAuthenticated(false);
      }
    };
    checkAuth();
  }, []);

  if (isAuthenticated === null) return null;
  if (!isAuthenticated) return <Navigate to="/login" />;
  return <>{children}</>;
}
```

## Related Documentation

- **Pages**: See `pages/README.md` for detailed page documentation
- **Components**: See individual component files for usage examples
- **API**: See `c:/Users/Smirk/Downloads/Tesslate-Studio/docs/orchestrator/routers/` for backend API docs
- **Architecture**: See `c:/Users/Smirk/Downloads/Tesslate-Studio/CLAUDE.md` for system architecture

## Troubleshooting

### API Calls Failing
- Check `VITE_API_URL` in `.env`
- Verify backend is running on correct port
- Check browser console for CORS errors
- Verify JWT token in localStorage or cookies

### WebSocket Connection Errors
- Ensure backend WebSocket endpoint is accessible
- Check for proxy/firewall blocking WebSocket connections
- Verify `wss://` protocol in production, `ws://` in dev

### Monaco Editor Not Loading
- Check that `@monaco-editor/react` is installed
- Verify Vite is properly bundling the editor
- Look for console errors about worker files

### XYFlow Graph Not Rendering
- Ensure `@xyflow/react` CSS is imported
- Check that node/edge types are properly registered
- Verify node positions are valid numbers

### File Events Not Propagating
- Confirm both emitter and listener use same event name
- Check that listener is registered before events are emitted
- Verify cleanup in useEffect return to prevent memory leaks
