# Project Builder Page

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/Project.tsx`
**Route**: `/project/:slug/builder?container={containerId}`
**Layout**: Standalone (full-screen with custom layout)

## Purpose

The Project Builder is the main development environment where users write code, chat with AI agents, preview their applications, and manage project files. It combines a Monaco code editor, live browser preview, AI chat interface, and multiple specialized panels into a unified workspace.

## Key Features

### 1. Monaco Code Editor
- Full VS Code-powered editor with syntax highlighting
- IntelliSense and code completion
- File tree navigation
- Multi-file editing
- Save with Cmd/Ctrl+S
- Read-only mode for view-only access

### 2. Live Browser Preview
- iframe embedding of running container
- URL navigation bar with back/forward
- Responsive device simulator (desktop, tablet, mobile)
- Refresh button
- Open in new tab
- Two preview modes:
  - **Normal**: Single iframe preview
  - **Browser Tabs**: Multiple preview tabs (experimental)

### 3. AI Chat Interface
- Streaming responses from AI agents
- Tool execution visualization
- File attachment support
- Edit mode (ask vs edit)
- Agent selection dropdown
- View-scoped tools (builder tools only)
- Container-scoped agents (filter files by container)

### 4. Multiple View Modes
Switch between different main content areas:
- **Preview**: Browser preview of running app
- **Code**: Monaco editor with file tree
- **Kanban**: Task board for project planning
- **Assets**: File browser with upload/download
- **Terminal**: xterm.js terminal for shell commands

### 5. Floating Panels
Toggle-able sidebar panels for additional features:
- **GitHub**: Git operations (commit, push, pull, branch)
- **Architecture**: Container visualization
- **Notes**: Rich text notes with TipTap editor
- **Settings**: Project configuration (env vars, preview mode)

## Navigation

The Builder view provides intuitive navigation between views:

- **Back to Projects**: Left sidebar button navigates to `/dashboard` (project list)
- **Architecture Button**: Top bar button navigates to `/project/:slug` (architecture canvas)
- **Container Selector**: Dropdown in top bar to switch between containers in multi-container projects

This mirrors the architecture canvas which has a reciprocal "Builder" button, allowing users to seamlessly switch between views like different perspectives of the same project (similar to ClickUp's view system).

## Component Structure

```
Project Builder
├── Left Sidebar (collapsible)
│   ├── Back to Projects button (→ /dashboard)
│   ├── View mode tabs
│   │   ├── Preview
│   │   ├── Code
│   │   ├── Kanban
│   │   ├── Assets
│   │   └── Terminal
│   └── Panel toggles
│       ├── GitHub
│       ├── Architecture
│       ├── Notes
│       └── Settings
│
├── Top Bar
│   ├── Breadcrumbs (Projects → Project Name → Builder)
│   ├── Container Selector (for multi-container projects)
│   ├── Architecture button (→ /project/:slug)
│   └── Deploy button
│
├── Main Content Area
│   └── (Dynamic based on activeView)
│       ├── BrowserPreview
│       ├── CodeEditor
│       ├── KanbanPanel
│       ├── AssetsPanel
│       └── TerminalPanel
│
├── Right Sidebar (chat)
│   └── ChatContainer
│       ├── Message history
│       ├── Agent selector
│       ├── Edit mode toggle
│       └── Message input
│
└── Floating Panels (overlay)
    ├── GitHubPanel
    ├── ArchitecturePanel
    ├── NotesPanel
    └── SettingsPanel
```

## State Management

```typescript
// Project and files
const [project, setProject] = useState<Record<string, unknown> | null>(null);
const [files, setFiles] = useState<Array<Record<string, unknown>>>([]);
const [container, setContainer] = useState<Record<string, unknown> | null>(null);

// View state
const [activeView, setActiveView] = useState<'preview' | 'code' | 'kanban' | 'assets' | 'terminal'>('preview');
const [activePanel, setActivePanel] = useState<PanelType>(null);
const [isLeftSidebarExpanded, setIsLeftSidebarExpanded] = useState(true);

// Preview state
const [devServerUrl, setDevServerUrl] = useState<string | null>(null);
const [devServerUrlWithAuth, setDevServerUrlWithAuth] = useState<string | null>(null);
const [currentPreviewUrl, setCurrentPreviewUrl] = useState<string>('');
const [previewMode, setPreviewMode] = useState<'normal' | 'browser-tabs'>('normal');

// Agents
const [agents, setAgents] = useState<UIAgent[]>([]);
const [currentAgent, setCurrentAgent] = useState<UIAgent | null>(null);

// Modals
const [showDeploymentsDropdown, setShowDeploymentsDropdown] = useState(false);
const [showDeployModal, setShowDeployModal] = useState(false);
```

## URL Parameters

```typescript
const { slug } = useParams<{ slug: string }>(); // Project slug
const [searchParams] = useSearchParams();
const containerId = searchParams.get('container'); // Optional container filter
```

## Data Flow

### Loading Project Data

```typescript
useEffect(() => {
  if (slug) {
    loadProject();
    loadDevServerUrl();
    loadSettings();
    loadAgents();
  }
}, [slug]);

const loadProject = async () => {
  try {
    const data = await projectsApi.getBySlug(slug);
    setProject(data);
  } catch (error) {
    toast.error('Failed to load project');
    navigate('/dashboard');
  }
};

const loadDevServerUrl = async () => {
  try {
    const { url, url_with_auth } = await projectsApi.getDevServerUrl(slug, containerId);
    setDevServerUrl(url);
    setDevServerUrlWithAuth(url_with_auth);
  } catch (error) {
    console.error('Failed to load dev server URL:', error);
  }
};
```

### Container-Scoped Files

When a container is selected via URL param, only show files belonging to that container:

```typescript
useEffect(() => {
  if (containerId && slug) {
    loadContainer();
  }
}, [containerId, slug]);

const loadContainer = async () => {
  try {
    const data = await projectsApi.getContainer(slug, containerId);
    setContainer(data);
  } catch (error) {
    console.error('Failed to load container:', error);
  }
};

// Filter files by container
useEffect(() => {
  if (container) {
    loadFiles(); // loadFiles will filter by container.root_path
  }
}, [container]);
```

### File Operations

```typescript
// Load files
const loadFiles = async () => {
  try {
    const data = await projectsApi.getFiles(slug);
    let filtered = data;

    // Filter by container root path if applicable
    if (container?.root_path) {
      filtered = data.filter(f =>
        f.file_path.startsWith(container.root_path)
      );
    }

    setFiles(filtered);
  } catch (error) {
    toast.error('Failed to load files');
  }
};

// Save file
const handleSaveFile = async (filePath: string, content: string) => {
  try {
    await projectsApi.updateFile(slug, filePath, content);

    // Emit file event for other components
    fileEvents.emit('fileUpdated', { filePath, content });

    toast.success('File saved');
  } catch (error) {
    toast.error('Failed to save file');
  }
};

// Create file
const handleCreateFile = async (filePath: string) => {
  try {
    await projectsApi.createFile(slug, filePath, '');
    await loadFiles();
    toast.success('File created');
  } catch (error) {
    toast.error('Failed to create file');
  }
};

// Delete file
const handleDeleteFile = async (filePath: string) => {
  if (!confirm(`Delete ${filePath}?`)) return;

  try {
    await projectsApi.deleteFile(slug, filePath);
    await loadFiles();
    toast.success('File deleted');
  } catch (error) {
    toast.error('Failed to delete file');
  }
};
```

### Preview URL Tracking

Track iframe navigation and update the URL bar:

```typescript
useEffect(() => {
  const handleMessage = (event: MessageEvent) => {
    if (event.data && event.data.type === 'url-change') {
      const url = event.data.url;

      // Remove auth token from display
      try {
        const urlObj = new URL(url);
        urlObj.searchParams.delete('auth_token');
        urlObj.searchParams.delete('t');
        setCurrentPreviewUrl(urlObj.toString());
      } catch {
        setCurrentPreviewUrl(url);
      }
    }
  };

  window.addEventListener('message', handleMessage);
  return () => window.removeEventListener('message', handleMessage);
}, []);
```

### View Switching

```typescript
const handleViewChange = (view: MainViewType) => {
  setActiveView(view);

  // Close panels when switching views
  if (view !== 'preview') {
    setActivePanel(null);
  }

  // Load view-specific data
  if (view === 'code' && files.length === 0) {
    loadFiles();
  } else if (view === 'terminal') {
    // Initialize terminal
  }
};
```

## View Components

### 1. Preview View

```typescript
{activeView === 'preview' && (
  <BrowserPreview
    url={devServerUrlWithAuth}
    currentUrl={currentPreviewUrl}
    onUrlChange={(url) => {
      setCurrentPreviewUrl(url);
      // Navigate iframe
      if (iframeRef.current) {
        iframeRef.current.src = url;
      }
    }}
    onRefresh={() => {
      if (iframeRef.current) {
        iframeRef.current.src = iframeRef.current.src;
      }
    }}
  />
)}
```

### 2. Code View

```typescript
{activeView === 'code' && (
  <CodeEditor
    projectId={project.id}
    files={files}
    onSave={handleSaveFile}
    onFileSelect={setSelectedFile}
    readOnly={false}
  />
)}
```

### 3. Kanban View

```typescript
{activeView === 'kanban' && (
  <KanbanPanel
    projectId={project.id}
    projectSlug={slug}
  />
)}
```

### 4. Assets View

```typescript
{activeView === 'assets' && (
  <AssetsPanel
    projectSlug={slug}
    files={files}
    onFilesChange={loadFiles}
  />
)}
```

### 5. Terminal View

```typescript
{activeView === 'terminal' && (
  <TerminalPanel
    projectSlug={slug}
    containerId={containerId}
  />
)}
```

## Chat Integration

The chat interface is always visible in the right sidebar:

```typescript
<ChatContainer
  projectId={project.id}
  containerId={containerId} // Optional: filter to container files
  viewContext="builder"      // Enable builder-scoped tools only
  agents={agents}
  currentAgent={currentAgent}
  onSelectAgent={setCurrentAgent}
  onFileUpdate={(filePath, content) => {
    // Agent wrote a file
    fileEvents.emit('fileUpdated', { filePath, content });
    loadFiles();
  }}
  projectFiles={files}
  projectName={project.name}
  sidebarExpanded={isLeftSidebarExpanded}
/>
```

### View-Scoped Tools

When `viewContext="builder"` is set, the AI agent only has access to builder-specific tools:
- File operations (read, write, edit)
- Bash commands
- Project metadata

Graph-specific tools (add container, create connection) are hidden.

### Container-Scoped Files

When `containerId` is provided, file operations are scoped to that container's root directory:

```typescript
// Agent tries to read file
read_file("src/App.tsx")

// With container scope, this becomes:
// read_file("frontend/src/App.tsx")  // if container.root_path = "frontend"
```

## Floating Panels

Panels overlay the main content and can be toggled on/off:

```typescript
// Toggle panel
const togglePanel = (panel: PanelType) => {
  setActivePanel(activePanel === panel ? null : panel);
};

// Render active panel
{activePanel === 'github' && (
  <FloatingPanel
    title="GitHub"
    onClose={() => setActivePanel(null)}
  >
    <GitHubPanel projectSlug={slug} />
  </FloatingPanel>
)}

{activePanel === 'architecture' && (
  <FloatingPanel
    title="Architecture"
    onClose={() => setActivePanel(null)}
  >
    <ArchitecturePanel projectSlug={slug} />
  </FloatingPanel>
)}

{activePanel === 'notes' && (
  <FloatingPanel
    title="Notes"
    onClose={() => setActivePanel(null)}
  >
    <NotesPanel projectSlug={slug} />
  </FloatingPanel>
)}

{activePanel === 'settings' && (
  <FloatingPanel
    title="Settings"
    onClose={() => setActivePanel(null)}
  >
    <SettingsPanel
      projectSlug={slug}
      settings={project.settings}
      onSettingsChange={loadSettings}
    />
  </FloatingPanel>
)}
```

## Preview Modes

### Normal Mode (default)
Single iframe showing the main container URL:

```typescript
<iframe
  ref={iframeRef}
  src={devServerUrlWithAuth}
  className="w-full h-full"
  sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
/>
```

### Browser Tabs Mode (experimental)
Multiple preview tabs for different pages/routes:

```typescript
<BrowserPreview
  mode="browser-tabs"
  tabs={[
    { id: '1', url: devServerUrl, title: 'Home' },
    { id: '2', url: `${devServerUrl}/about`, title: 'About' },
  ]}
  activeTabId={activeTabId}
  onTabChange={setActiveTabId}
  onAddTab={() => {
    // Add new tab
  }}
/>
```

## Sidebar Collapse

The left sidebar can be collapsed to provide more space for the main content:

```typescript
const toggleSidebar = () => {
  setIsLeftSidebarExpanded(!isLeftSidebarExpanded);
};

// Persist to localStorage
useEffect(() => {
  localStorage.setItem('projectSidebarExpanded', JSON.stringify(isLeftSidebarExpanded));
}, [isLeftSidebarExpanded]);

// Collapsed sidebar shows icon-only buttons
<div className={`sidebar ${isLeftSidebarExpanded ? 'expanded' : 'collapsed'}`}>
  {isLeftSidebarExpanded ? (
    <>
      <CaretLeft onClick={toggleSidebar} />
      <span>Views</span>
    </>
  ) : (
    <CaretRight onClick={toggleSidebar} />
  )}
</div>
```

## Keyboard Shortcuts

```typescript
useEffect(() => {
  const handleKeyboard = (e: KeyboardEvent) => {
    // Save file (Cmd/Ctrl+S)
    if ((e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault();
      handleSaveFile(currentFilePath, currentFileContent);
    }

    // Toggle sidebar (Cmd/Ctrl+B)
    if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
      e.preventDefault();
      toggleSidebar();
    }

    // Open command palette (Cmd/Ctrl+K)
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      // Open command palette
    }
  };

  window.addEventListener('keydown', handleKeyboard);
  return () => window.removeEventListener('keydown', handleKeyboard);
}, [currentFilePath, currentFileContent]);
```

## API Endpoints Used

```typescript
// Get project
GET /api/projects/{slug}

// Get files
GET /api/projects/{slug}/files

// Update file
PUT /api/projects/{slug}/files
{ file_path: string, content: string }

// Create file
POST /api/projects/{slug}/files
{ file_path: string, content: string }

// Delete file
DELETE /api/projects/{slug}/files/{file_path}

// Get dev server URL
GET /api/projects/{slug}/dev-server-url?container_id={containerId}

// Get container
GET /api/projects/{slug}/containers/{containerId}

// Get settings
GET /api/projects/{slug}/settings

// Update settings
PUT /api/projects/{slug}/settings
{ settings: { preview_mode: 'normal' | 'browser-tabs' } }
```

## Related Components

- **`ChatContainer`**: AI chat interface
- **`CodeEditor`**: Monaco editor wrapper
- **`BrowserPreview`**: iframe preview with controls
- **`FloatingPanel`**: Panel overlay wrapper
- **`GitHubPanel`**: Git operations
- **`ArchitecturePanel`**: Container visualization
- **`NotesPanel`**: Rich text notes
- **`SettingsPanel`**: Project configuration
- **`KanbanPanel`**: Task board
- **`AssetsPanel`**: File browser
- **`TerminalPanel`**: Terminal emulator

## Best Practices

### 1. File Event Propagation
Always emit file events after modifying files so all components stay in sync:

```typescript
const handleSaveFile = async (filePath: string, content: string) => {
  await projectsApi.updateFile(slug, filePath, content);
  fileEvents.emit('fileUpdated', { filePath, content });
};
```

### 2. Preview Refresh
Auto-refresh preview after file saves (with debounce):

```typescript
useEffect(() => {
  const handler = (detail: { filePath: string }) => {
    // Debounce refresh
    if (refreshTimeoutRef.current) {
      clearTimeout(refreshTimeoutRef.current);
    }

    refreshTimeoutRef.current = setTimeout(() => {
      if (iframeRef.current) {
        iframeRef.current.src = iframeRef.current.src;
      }
    }, 500);
  };

  fileEvents.on('fileUpdated', handler);
  return () => fileEvents.off('fileUpdated', handler);
}, []);
```

### 3. Clean up Intervals
Always clean up polling and timeouts:

```typescript
useEffect(() => {
  return () => {
    if (refreshTimeoutRef.current) {
      clearTimeout(refreshTimeoutRef.current);
    }
  };
}, []);
```

## Troubleshooting

**Issue**: Preview not loading
- Check dev server URL is valid
- Verify container is running
- Check auth token in URL

**Issue**: File saves not reflecting in preview
- Ensure file event is emitted
- Check auto-refresh is working
- Verify dev server picks up changes

**Issue**: Chat not working
- Check WebSocket connection
- Verify agent is enabled
- Check project ID is correct
