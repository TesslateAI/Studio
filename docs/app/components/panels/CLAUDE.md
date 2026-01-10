# Panels - AI Agent Context

## Adding a New Panel

1. **Create component** in `components/panels/`:
```typescript
// NewFeaturePanel.tsx
export function NewFeaturePanel({ projectSlug }: { projectSlug: string }) {
  return (
    <div className="h-full flex flex-col">
      <div className="panel-section p-6">
        {/* Panel content */}
      </div>
    </div>
  );
}
```

2. **Export** from `components/panels/index.ts`:
```typescript
export { NewFeaturePanel } from './NewFeaturePanel';
```

3. **Add to parent** (e.g., Project.tsx):
```typescript
{activePanel === 'new-feature' && (
  <FloatingPanel title="New Feature" onClose={() => setActivePanel(null)}>
    <NewFeaturePanel projectSlug={project.slug} />
  </FloatingPanel>
)}
```

4. **Add trigger button**:
```typescript
<button onClick={() => setActivePanel('new-feature')}>
  Open New Feature
</button>
```

## Panel Communication

### Panel → Parent

Use callback props:
```typescript
interface PanelProps {
  projectSlug: string;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

// In panel
onComplete?.();
```

### Parent → Panel

Use props:
```typescript
<Panel
  projectSlug={slug}
  refreshTrigger={refreshCount}  // Increment to trigger reload
/>

// In panel
useEffect(() => {
  loadData();
}, [refreshTrigger]);
```

## Architecture Diagram Tips

### Custom Sanitization

Mermaid syntax errors are common. Add sanitization:
```typescript
const sanitizeDiagram = (diagramCode: string): string => {
  let sanitized = diagramCode;

  // Remove problematic characters
  sanitized = sanitized.replace(/@/g, 'at-');
  sanitized = sanitized.replace(/\["([^"]+)"\]/g, '[$1]');

  return sanitized;
};
```

### Kroki API for PlantUML

```typescript
const renderPlantUML = async (diagram: string) => {
  const response = await fetch('https://kroki.io/c4plantuml/svg', {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: diagram
  });

  return await response.text();
};
```

## Git Panel Integration

### Commit Flow

```typescript
const handleCommit = async () => {
  try {
    // 1. Stage files
    await gitApi.stageFiles(projectSlug, ['*']);

    // 2. Create commit
    await gitApi.commit(projectSlug, {
      message: commitMessage,
      author: user.email
    });

    // 3. Push to remote
    await gitApi.push(projectSlug);

    toast.success('Changes pushed!');
  } catch (error) {
    toast.error('Git operation failed');
  }
};
```

## Assets Panel File Upload

### Upload Flow

```typescript
const handleFileUpload = async (files: FileList) => {
  const formData = new FormData();

  Array.from(files).forEach(file => {
    formData.append('files', file);
  });

  const response = await assetsApi.upload(projectSlug, formData);
  setAssets(prev => [...prev, ...response.uploaded]);
};
```

### Drag-and-Drop

```typescript
const AssetUploadZone = ({ onUpload }: Props) => {
  const [isDragging, setIsDragging] = useState(false);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        onUpload(e.dataTransfer.files);
      }}
      className={isDragging ? 'border-orange-500' : 'border-gray-600'}
    >
      Drop files here
    </div>
  );
};
```

## Terminal Integration

### xterm.js Setup

```typescript
import { Terminal } from 'xterm';
import { FitAddon } from 'xterm-addon-fit';

const terminal = new Terminal({
  cursorBlink: true,
  fontSize: 14,
  fontFamily: 'JetBrains Mono, monospace',
  theme: {
    background: '#0a0a0a',
    foreground: '#e2e2e2',
  }
});

const fitAddon = new FitAddon();
terminal.loadAddon(fitAddon);

terminal.open(terminalRef.current);
fitAddon.fit();

// Connect to backend shell
const ws = new WebSocket(`ws://api/shell/${projectSlug}`);
terminal.onData((data) => ws.send(data));
ws.onmessage = (evt) => terminal.write(evt.data);
```

## Troubleshooting

### Diagram Not Rendering

Check:
1. Mermaid syntax valid
2. SVG container has proper sizing
3. Theme variables defined

Debug:
```typescript
try {
  const { svg } = await mermaid.render(id, diagram);
  console.log('[Diagram] Rendered:', svg.substring(0, 100));
} catch (error) {
  console.error('[Diagram] Render error:', error);
}
```

### Panel Not Updating

Check:
1. Props changing trigger re-render
2. useEffect dependencies correct
3. API calls completing

Debug:
```typescript
useEffect(() => {
  console.log('[Panel] Props changed:', { projectSlug, ...props });
  loadData();
}, [projectSlug, ...dependencies]);
```

---

**Remember**: Panels are modular. Keep them self-contained with minimal parent dependencies.
