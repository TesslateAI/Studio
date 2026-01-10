# Panel Components

**Location**: `app/src/components/panels/`

Side panels provide specialized functionality for project management, architecture visualization, asset management, Git operations, deployment, and settings.

## Components Overview

### ArchitecturePanel.tsx

**AI-Generated Diagrams**: Visualizes project architecture using Mermaid or C4 PlantUML diagrams.

**Features**:
- Generate Mermaid flowcharts or C4 architecture diagrams
- AI-powered diagram generation from codebase
- Zoom controls (zoom in/out, reset, percentage display)
- Theme-aware rendering (dark/light colors)
- PlantUML rendering via Kroki API
- Diagram persistence (saved in project settings)

**Props**:
```typescript
interface ArchitecturePanelProps {
  projectSlug: string;
}
```

**Usage**:
```typescript
<ArchitecturePanel projectSlug={project.slug} />
```

**Diagram Types**:
- **Mermaid**: Flowcharts, sequence diagrams, rendered client-side
- **C4 PlantUML**: Context, container, component diagrams, rendered via Kroki

**Generation**:
```typescript
const handleGenerateDiagram = async (type: 'mermaid' | 'c4_plantuml') => {
  const response = await diagramApi.generateDiagram(projectSlug, type);
  setDiagram(response.diagram);
  setModelUsed(response.model_used);
};
```

---

### GitHubPanel.tsx

**Git Operations UI**: Commit, push, pull, branch management, and commit history.

**Features**:
- View commit history with diffs
- Create commits with message
- Push/pull to remote
- Branch management
- OAuth-based GitHub authentication
- File status (modified/added/deleted)

---

### AssetsPanel.tsx

**File Upload & Management**: Upload images, videos, and static assets. Browse project file system.

**Features**:
- Drag-and-drop file upload
- File preview (images, videos)
- Directory tree navigation
- File deletion
- Asset organization by folder

**Sub-components**:
- `AssetComponents.tsx` - Individual asset cards
- `AssetUploadZone.tsx` - Drag-and-drop zone
- `DirectoryTree.tsx` - File system tree

---

### KanbanPanel.tsx

**Task Board**: Kanban-style task management (To Do, In Progress, Done).

**Features**:
- Drag-and-drop task cards
- Create/edit/delete tasks
- Task status transitions
- Task descriptions and assignments

---

### TerminalPanel.tsx

**Shell Access**: Execute shell commands in container environment.

**Features**:
- Interactive terminal (xterm.js)
- Command history
- Multiple terminal tabs
- ANSI color support

---

### NotesPanel.tsx

**Markdown Notes**: Project-specific notes with markdown rendering.

**Features**:
- Rich text editing
- Markdown preview
- Auto-save
- Note search

---

### DeploymentsPanel.tsx

**Deployment History**: View past deployments to Vercel, Netlify, Cloudflare.

**Features**:
- Deployment list with status
- View deployment logs
- Rollback to previous version
- External deployment URLs

---

### SettingsPanel.tsx

**Project Settings**: Configure project name, environment variables, danger zone.

**Features**:
- Update project name
- Manage environment variables
- Delete project (confirmation required)
- Project metadata

---

### MarketplacePanel.tsx

**Agent Store**: Browse and purchase AI agents from marketplace.

**Features**:
- Agent cards with ratings
- Search/filter agents
- Purchase with credits
- Agent details modal

## Common Panel Pattern

All panels share a similar structure:

```tsx
export function Panel({ projectSlug }: Props) {
  return (
    <div className="h-full flex flex-col">
      <div className="panel-section p-6 flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-orange-500/20 rounded-lg">
              <Icon size={20} className="text-orange-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">Panel Title</h2>
              <p className="text-xs text-[var(--text)]/60">Description</p>
            </div>
          </div>
          <div className="flex gap-2">
            {/* Action buttons */}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto">
          {/* Panel-specific content */}
        </div>
      </div>
    </div>
  );
}
```

## Panel Usage in Project View

Panels are rendered in FloatingPanel components:

```typescript
// Project.tsx
const [activePanel, setActivePanel] = useState<PanelType | null>(null);

{activePanel === 'architecture' && (
  <FloatingPanel
    title="Architecture"
    onClose={() => setActivePanel(null)}
  >
    <ArchitecturePanel projectSlug={project.slug} />
  </FloatingPanel>
)}

{activePanel === 'git' && (
  <FloatingPanel title="Git">
    <GitHubPanel projectSlug={project.slug} />
  </FloatingPanel>
)}
```

## Styling Conventions

- **Header icon**: Orange background with rounded corners
- **Action buttons**: Orange hover states
- **Content area**: Scrollable with overflow-auto
- **Loading states**: Spinner with descriptive text
- **Empty states**: Centered icon + message

## Performance Notes

- **ArchitecturePanel**: Memoize diagram SVG, debounce zoom changes
- **AssetsPanel**: Virtualize file tree for large directories
- **TerminalPanel**: Limit terminal buffer size to prevent memory issues
- **GitHubPanel**: Paginate commit history

---

**See individual CLAUDE.md for detailed implementation guidance.**
