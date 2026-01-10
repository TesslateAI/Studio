# Code Editor - AI Agent Context

## Quick Modifications

### Adding Syntax Support for New Language

1. **Add extension mapping**:
```typescript
const getLanguage = (fileName: string): string => {
  const ext = fileName.split('.').pop()?.toLowerCase();

  switch (ext) {
    // ... existing cases
    case 'go': return 'go';          // Add Go support
    case 'rs': return 'rust';        // Add Rust support
    case 'rb': return 'ruby';        // Add Ruby support
    default: return 'plaintext';
  }
};
```

2. **Add file icon** (optional):
```typescript
const getFileIcon = (fileName: string) => {
  const ext = fileName.split('.').pop()?.toLowerCase();

  switch (ext) {
    // ... existing cases
    case 'go':
      return <File size={14} className="text-cyan-400" />;
    case 'rs':
      return <File size={14} className="text-orange-600" />;
    default:
      return <File size={14} className="text-gray-400" />;
  }
};
```

### Customizing Monaco Theme

Create custom theme matching Tesslate colors:
```typescript
import { editor } from 'monaco-editor';

const defineCustomTheme = () => {
  editor.defineTheme('tesslate-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '6B7280' },
      { token: 'keyword', foreground: 'F89521', fontStyle: 'bold' },
      { token: 'string', foreground: '22C55E' },
    ],
    colors: {
      'editor.background': '#0a0a0a',
      'editor.foreground': '#e2e2e2',
      'editor.lineHighlightBackground': '#1a1a1a',
      'editorCursor.foreground': '#F89521',
    }
  });
};

// Use in component
useEffect(() => {
  defineCustomTheme();
}, []);

<Editor theme="tesslate-dark" />
```

### Adding Keyboard Shortcuts

```typescript
const handleEditorDidMount = (editor: editor.IStandaloneCodeEditor) => {
  editorRef.current = editor;

  // Add custom keybindings
  editor.addCommand(
    monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
    () => {
      // Save file
      const content = editor.getValue();
      onFileUpdate(selectedFile, content);
      toast.success('File saved');
    }
  );

  editor.addCommand(
    monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyF,
    () => {
      // Toggle file search
      editor.getAction('actions.find').run();
    }
  );
};
```

### Implementing File Search

Add search input above file tree:
```typescript
const [searchQuery, setSearchQuery] = useState('');

const filteredFiles = useMemo(() => {
  if (!searchQuery) return fileTree;

  return fileTree.filter(node =>
    node.name.toLowerCase().includes(searchQuery.toLowerCase())
  );
}, [fileTree, searchQuery]);

<div className="p-2">
  <input
    type="text"
    placeholder="Search files..."
    value={searchQuery}
    onChange={(e) => setSearchQuery(e.target.value)}
    className="w-full px-3 py-2 bg-[var(--surface)] rounded-lg"
  />
</div>

<div className="flex-1 overflow-y-auto">
  {renderFileTree(filteredFiles)}
</div>
```

## Performance Optimization

### Lazy Load Monaco

Monaco is large (~5MB). Load only when editor visible:
```typescript
import { lazy, Suspense } from 'react';

const Editor = lazy(() => import('@monaco-editor/react'));

export default function CodeEditor({ files }: Props) {
  if (files.length === 0) {
    return <EmptyState />;
  }

  return (
    <Suspense fallback={<div>Loading editor...</div>}>
      <Editor {...props} />
    </Suspense>
  );
}
```

### Memoize File Tree

Building file tree is expensive for large projects:
```typescript
const fileTree = useMemo(() => {
  // Build tree from files
  return buildFileTree(files);
}, [files]);  // Only rebuild when files change
```

### Debounce Autosave

Save file changes after user stops typing:
```typescript
const debouncedSave = useMemo(
  () => debounce((path: string, content: string) => {
    onFileUpdate(path, content);
    toast.success('Saved', { duration: 1000 });
  }, 1000),
  [onFileUpdate]
);

const handleEditorChange = (value: string | undefined) => {
  if (selectedFile && value !== undefined) {
    debouncedSave(selectedFile, value);
  }
};
```

## Advanced Features

### Diff Editor

Show file changes side-by-side:
```typescript
import { DiffEditor } from '@monaco-editor/react';

<DiffEditor
  original={originalContent}  // Old version
  modified={currentContent}    // New version
  language="typescript"
  theme="vs-dark"
/>
```

### Multiple Editor Instances

Split view with multiple files:
```typescript
const [leftFile, setLeftFile] = useState<string | null>(null);
const [rightFile, setRightFile] = useState<string | null>(null);

<div className="flex">
  <div className="flex-1">
    <Editor
      value={files.find(f => f.file_path === leftFile)?.content}
      // ...
    />
  </div>
  <div className="flex-1">
    <Editor
      value={files.find(f => f.file_path === rightFile)?.content}
      // ...
    />
  </div>
</div>
```

### Code Formatting

Format on save:
```typescript
const handleEditorDidMount = (editor: editor.IStandaloneCodeEditor) => {
  editor.addCommand(
    monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
    async () => {
      await editor.getAction('editor.action.formatDocument').run();
      const content = editor.getValue();
      onFileUpdate(selectedFile, content);
    }
  );
};
```

### Language Server Protocol (LSP)

Add IntelliSense for TypeScript:
```typescript
import { configureMonacoTsWorker } from './monaco-ts-worker';

const handleEditorDidMount = (editor: editor.IStandaloneCodeEditor) => {
  configureMonacoTsWorker(monaco, {
    compilerOptions: {
      target: 'ES2020',
      module: 'ESNext',
      jsx: 'react',
    }
  });
};
```

## Debugging Tips

### Editor Not Showing Content

**Check**:
1. `selectedFileContent` is not null
2. `value` prop is a string
3. `language` is valid Monaco language

**Debug**:
```typescript
console.log('[Editor] Selected file:', selectedFile);
console.log('[Editor] Content:', selectedFileContent?.content.substring(0, 100));
console.log('[Editor] Language:', getLanguage(selectedFile));
```

### File Tree Not Expanding

**Check**:
1. `expandedDirs` Set includes directory path
2. `node.children` is defined and has items
3. Click handler calls `toggleDirectory()`

**Debug**:
```typescript
const toggleDirectory = (path: string) => {
  console.log('[Tree] Toggling:', path);
  console.log('[Tree] Current expanded:', Array.from(expandedDirs));

  setExpandedDirs(prev => {
    const newSet = new Set(prev);
    if (newSet.has(path)) {
      newSet.delete(path);
    } else {
      newSet.add(path);
    }
    console.log('[Tree] New expanded:', Array.from(newSet));
    return newSet;
  });
};
```

### Monaco Memory Leak

**Problem**: Editor not disposed on unmount
**Fix**: Add cleanup:
```typescript
const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);

useEffect(() => {
  return () => {
    editorRef.current?.dispose();
  };
}, []);
```

## Testing

### Unit Tests

```typescript
import { render, screen } from '@testing-library/react';
import CodeEditor from './CodeEditor';

test('renders file tree', () => {
  const files = [
    { file_path: 'App.tsx', content: 'code' },
    { file_path: 'index.tsx', content: 'code' }
  ];

  render(<CodeEditor projectId={1} files={files} onFileUpdate={jest.fn()} />);

  expect(screen.getByText('App.tsx')).toBeInTheDocument();
  expect(screen.getByText('index.tsx')).toBeInTheDocument();
});

test('selects file on click', () => {
  const files = [{ file_path: 'App.tsx', content: 'test content' }];

  render(<CodeEditor projectId={1} files={files} onFileUpdate={jest.fn()} />);

  fireEvent.click(screen.getByText('App.tsx'));

  // Editor should mount with file content
  // (Monaco testing requires more setup)
});
```

### Integration Tests

```typescript
test('updates file content', async () => {
  const onFileUpdate = jest.fn();
  const files = [{ file_path: 'App.tsx', content: 'old content' }];

  render(<CodeEditor projectId={1} files={files} onFileUpdate={onFileUpdate} />);

  // Click file
  fireEvent.click(screen.getByText('App.tsx'));

  // Type in editor (requires Monaco mock)
  // ...

  await waitFor(() => {
    expect(onFileUpdate).toHaveBeenCalledWith('App.tsx', 'new content');
  });
});
```

---

**Common Gotcha**: Monaco Editor loads asynchronously. Always check `editorRef.current` before calling methods.
