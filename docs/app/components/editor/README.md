# Code Editor Components

**Location**: `app/src/components/`

The code editor provides a full-featured IDE experience with Monaco Editor integration, file tree navigation, and syntax highlighting.

## CodeEditor.tsx

**Full-Featured Code Editor**: Monaco Editor with collapsible file tree, auto-language detection, and real-time file updates.

### Key Features

- **Monaco Editor Integration**: VS Code's editor engine
- **File Tree**: Nested folder/file navigation with expand/collapse
- **Language Detection**: Auto-detects language from file extension
- **Theme Support**: Dark/light mode sync
- **Collapsible Sidebar**: Hide/show file explorer
- **Auto-Select**: Opens first file on mount
- **Live Updates**: File changes propagate to parent via `onFileUpdate`

### Props

```typescript
interface CodeEditorProps {
  projectId: number;
  files: FileData[];                                    // All project files
  onFileUpdate: (filePath: string, content: string) => void;
}

interface FileData {
  file_path: string;  // e.g., "src/App.tsx"
  content: string;
}
```

### Usage

```typescript
<CodeEditor
  projectId={project.id}
  files={[
    { file_path: 'src/App.tsx', content: '...' },
    { file_path: 'src/index.tsx', content: '...' },
    { file_path: 'package.json', content: '...' }
  ]}
  onFileUpdate={(path, content) => {
    // Update parent state
    updateProjectFile(path, content);
  }}
/>
```

### File Tree Structure

Files are organized into a tree hierarchy:

```
src/
├── components/
│   ├── Button.tsx
│   └── Header.tsx
├── App.tsx
└── index.tsx
package.json
README.md
```

**Building the Tree**:
```typescript
// Sort files to ensure parent folders created before children
const sortedFiles = [...files].sort((a, b) =>
  a.file_path.localeCompare(b.file_path)
);

// Split paths and build tree
sortedFiles.forEach(file => {
  const parts = file.file_path.split('/').filter(Boolean);
  // src/App.tsx → ['src', 'App.tsx']

  parts.forEach((part, index) => {
    const isFile = index === parts.length - 1;
    // Create node for each part
  });
});
```

### Language Detection

File extension → Monaco language:
```typescript
const getLanguage = (fileName: string): string => {
  const ext = fileName.split('.').pop()?.toLowerCase();

  switch (ext) {
    case 'js':
    case 'jsx': return 'javascript';
    case 'ts':
    case 'tsx': return 'typescript';
    case 'html': return 'html';
    case 'css': return 'css';
    case 'json': return 'json';
    case 'md': return 'markdown';
    case 'py': return 'python';
    case 'yml':
    case 'yaml': return 'yaml';
    default: return 'plaintext';
  }
};
```

### File Tree Rendering

```typescript
const renderFileTree = (nodes: FileNode[], depth = 0) => {
  return nodes.map(node => (
    <div key={node.path}>
      {/* Indentation based on depth */}
      <div
        className={selectedFile === node.path ? 'bg-orange-500/20 border-l-2 border-orange-500' : ''}
        style={{ paddingLeft: `${depth * 16 + 12}px` }}
        onClick={() => {
          if (node.isDirectory) {
            toggleDirectory(node.path);  // Expand/collapse
          } else {
            setSelectedFile(node.path);  // Open file
          }
        }}
      >
        {/* Directory: Chevron + Folder icon */}
        {node.isDirectory && (
          <>
            {expandedDirs.has(node.path) ? <ChevronDown /> : <ChevronRight />}
            <Folder className="text-blue-400" />
          </>
        )}

        {/* File: Language-specific icon */}
        {!node.isDirectory && getFileIcon(node.name)}

        <span>{node.name}</span>
      </div>

      {/* Recursively render children */}
      {node.isDirectory && expandedDirs.has(node.path) && node.children && (
        renderFileTree(node.children, depth + 1)
      )}
    </div>
  ));
};
```

### Monaco Editor Configuration

```typescript
<Editor
  key={selectedFile}              // Force remount on file change
  height="100%"
  language={getLanguage(selectedFile)}
  value={selectedFileContent.content}
  onChange={handleEditorChange}
  onMount={handleEditorDidMount}
  theme={theme === 'dark' ? 'vs-dark' : 'vs'}
  options={{
    fontSize: 14,
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
    lineNumbers: 'on',
    minimap: { enabled: true },
    scrollBeyondLastLine: false,
    automaticLayout: true,          // Auto-resize on container change
    tabSize: 2,
    wordWrap: 'on',
    padding: { top: 16, bottom: 16 },
    smoothScrolling: true,
    cursorBlinking: 'smooth',
    cursorSmoothCaretAnimation: 'on',
    renderLineHighlight: 'all',
    bracketPairColorization: { enabled: true },
    guides: {
      bracketPairs: true,
      indentation: true,
    },
    suggestOnTriggerCharacters: true,
    quickSuggestions: true,
    formatOnPaste: true,
    formatOnType: true,
  }}
/>
```

### Collapsible Sidebar

```typescript
const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

<div className={`transition-all duration-300 ${
  isSidebarCollapsed ? 'w-0 border-0' : 'w-72'
}`}>
  {/* File tree */}
</div>

<button onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}>
  {isSidebarCollapsed ? <PanelLeft /> : <PanelLeftClose />}
</button>
```

### File Icon Mapping

```typescript
const getFileIcon = (fileName: string) => {
  const ext = fileName.split('.').pop()?.toLowerCase();

  switch (ext) {
    case 'js':
    case 'jsx':
    case 'ts':
    case 'tsx':
      return <Code size={14} className="text-yellow-400" />;
    case 'html':
      return <File size={14} className="text-orange-400" />;
    case 'css':
      return <File size={14} className="text-blue-400" />;
    case 'json':
      return <File size={14} className="text-green-400" />;
    default:
      return <File size={14} className="text-gray-400" />;
  }
};
```

### Empty State

When no files or no file selected:

```tsx
<div className="h-full flex items-center justify-center">
  <div className="text-center p-8">
    <div className="w-20 h-20 bg-gradient-to-br from-orange-500/20 to-pink-600/20 rounded-2xl flex items-center justify-center mx-auto mb-4">
      <Code size={40} className="text-orange-500" />
    </div>
    <h3 className="text-lg font-semibold mb-2">
      {files.length > 0 ? 'Select a file to edit' : 'No files yet'}
    </h3>
    <p className="text-sm text-[var(--text)]/50">
      {files.length > 0
        ? 'Choose a file from the explorer to start editing'
        : 'Chat with your AI agent to generate code'}
    </p>
  </div>
</div>
```

## Component Layout

```
┌────────────────────────────────────────────────────────┐
│ [==] Explorer          │ [<] App.tsx                  │
│ 12 files               │ 150 lines • 3420 characters  │
├────────────────────────┼──────────────────────────────┤
│                        │                              │
│ 📁 src/               │  import React from 'react';  │
│   📁 components/       │                              │
│     📄 Button.tsx      │  function App() {            │
│     📄 Header.tsx      │    return (                  │
│   📄 App.tsx ◄────────┼── <div>...</div>             │
│   📄 index.tsx         │    );                        │
│ 📄 package.json        │  }                           │
│ 📄 README.md           │                              │
│                        │  export default App;         │
│                        │                              │
│ [No files yet]         │  [Select a file to edit]    │
│                        │                              │
└────────────────────────┴──────────────────────────────┘
```

## Performance Considerations

### Avoid Re-mounting Editor

Using `key={selectedFile}` forces remount when file changes. This is intentional to ensure clean state, but can be expensive for large files.

**Alternative**: Use `editor.setValue()` to update content without remount:
```typescript
const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);

const handleEditorDidMount = (editor: editor.IStandaloneCodeEditor) => {
  editorRef.current = editor;
};

// When file changes, update value directly
useEffect(() => {
  if (editorRef.current && selectedFileContent) {
    editorRef.current.setValue(selectedFileContent.content);
  }
}, [selectedFile]);
```

### Debounce File Updates

Rapid typing triggers many `onFileUpdate` calls:
```typescript
const handleEditorChange = debounce((value: string | undefined) => {
  if (selectedFile && value !== undefined) {
    onFileUpdate(selectedFile, value);
  }
}, 300);
```

### Virtualize File Tree

For projects with 1000+ files, render only visible nodes:
```typescript
import { FixedSizeTree } from 'react-vtree';
// Implementation details depend on library
```

## Common Issues

### Monaco Not Loading

**Symptoms**: White screen, no editor
**Cause**: Monaco workers not loaded
**Fix**: Ensure `@monaco-editor/react` is installed and workers are configured in vite.config.ts

### Theme Not Syncing

**Symptoms**: Editor stays light when app is dark
**Cause**: Theme prop not updating
**Fix**: Pass theme from context:
```typescript
const { theme } = useTheme();
<Editor theme={theme === 'dark' ? 'vs-dark' : 'vs'} />
```

### File Tree Not Updating

**Symptoms**: New files don't appear in tree
**Cause**: Tree built in useEffect with missing dependency
**Fix**: Ensure `files` in dependency array:
```typescript
useEffect(() => {
  buildFileTree();
}, [files]);  // Re-build when files change
```

### Selected File Content Wrong

**Symptoms**: Opening file shows old content
**Cause**: Stale closure in `selectedFileContent` calculation
**Fix**: Calculate inside render:
```typescript
const selectedFileContent = files.find(f => f.file_path === selectedFile);
// Don't store in state
```

## Integration with Chat

When agent creates files, parent updates `files` prop:
```typescript
// Project.tsx (parent)
const [files, setFiles] = useState<FileData[]>([]);

<ChatContainer
  onFileUpdate={(path, content) => {
    setFiles(prev => {
      const existing = prev.find(f => f.file_path === path);
      if (existing) {
        // Update existing file
        return prev.map(f => f.file_path === path ? { ...f, content } : f);
      } else {
        // Add new file
        return [...prev, { file_path: path, content }];
      }
    });
  }}
/>

<CodeEditor
  files={files}
  onFileUpdate={(path, content) => {
    // Manual edit from user
    setFiles(prev => prev.map(f =>
      f.file_path === path ? { ...f, content } : f
    ));
  }}
/>
```

## Accessibility

- **Keyboard navigation**: Arrow keys to navigate tree, Enter to open file
- **Screen reader**: File names announced when focused
- **Contrast**: File icons use high-contrast colors

---

**Next Steps**: For Monaco configuration options, see [Monaco Editor API](https://microsoft.github.io/monaco-editor/api/index.html).
