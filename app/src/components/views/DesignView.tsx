import { useState, useCallback, useRef, useEffect } from 'react';
import {
  Panel,
  Group as PanelGroup,
  Separator as PanelResizeHandle,
} from 'react-resizable-panels';
import { useHotkeys } from 'react-hotkeys-hook';
import CodeEditor from '../CodeEditor';
import FileTreePanel from './design/FileTreePanel';
import { PreviewCanvas } from './design/PreviewCanvas';
import { DesignToolbar, type Breakpoint, BREAKPOINT_WIDTHS } from './design/DesignToolbar';
import InspectorPanel from './design/InspectorPanel';
import { sendDesignMessage, type ElementData } from './design/DesignBridge';
import { installBridge } from './design/bridgeInstaller';
import { bindSlug as bindCanvasSlug } from './design/canvasStore';
import {
  bindSlug as bindDesignSlug,
  rebuildIndex as rebuildDesignIndex,
  pushStyleEdit,
  pushClassEdit,
  pushTextEdit,
  undo as designUndo,
  redo as designRedo,
  useDesignStore,
  selectElement as selectDesignElement,
  clearSelection as clearDesignSelection,
  deleteSelected as deleteDesignSelected,
  copySelection as copyDesignSelection,
  pasteClipboard as pasteDesignClipboard,
  groupSelected as groupDesignSelected,
  armPendingInsert,
  clearPendingInsert,
} from './design/designStore';
import { detectClassesAtCursor, detectElementAtCursor, type ClassInfo, type ElementInfo } from '../../utils/classDetection';
import type { FileTreeEntry } from '../../utils/buildFileTree';

interface DesignViewProps {
  slug: string;
  projectId: number;
  fileTree: FileTreeEntry[];
  devServerUrl: string;
  devServerUrlWithAuth: string;
  onFileUpdate: (filePath: string, content: string) => void;
  onFileCreate?: (filePath: string) => void;
  onFileDelete?: (filePath: string, isDir: boolean) => void;
  onFileRename?: (oldPath: string, newPath: string) => void;
  onDirectoryCreate?: (dirPath: string) => void;
  isFilesSyncing: boolean;
  containerDir?: string;
  onRefreshPreview: () => void;
}

export default function DesignView({
  slug,
  projectId,
  fileTree,
  devServerUrl,
  devServerUrlWithAuth,
  onFileUpdate,
  onFileCreate,
  onFileDelete,
  onFileRename,
  onDirectoryCreate,
  isFilesSyncing,
  containerDir,
  onRefreshPreview,
}: DesignViewProps) {
  // ── State ──────────────────────────────────────────────────────────
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [externalOpenFile, setExternalOpenFile] = useState<string | undefined>(undefined);
  const editorRefState = useRef<unknown>(null);

  // Narrow-screen layout — file tree + inspector become slide-overs.
  const [isNarrow, setIsNarrow] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.matchMedia('(max-width: 767px)').matches : false,
  );
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia('(max-width: 767px)');
    const onChange = (e: MediaQueryListEvent) => setIsNarrow(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  const [mobileFileTreeOpen, setMobileFileTreeOpen] = useState(false);
  const [mobileInspectorOpen, setMobileInspectorOpen] = useState(false);
  // Auto-close any open slide-over when we leave narrow mode.
  useEffect(() => {
    if (!isNarrow) {
      setMobileFileTreeOpen(false);
      setMobileInspectorOpen(false);
    }
  }, [isNarrow]);

  // Preview & selection
  const [designMode, setDesignMode] = useState<'select' | 'text' | 'move'>('select');
  const [selectedElement, setSelectedElement] = useState<ElementData | null>(null);
  const [viewportBreakpoint, setViewportBreakpoint] = useState<Breakpoint>('fit');

  // Inspector
  const [activeInspectorTab, setActiveInspectorTab] = useState<'visual' | 'inspector'>('visual');
  const [cursorClasses, setCursorClasses] = useState<ClassInfo | null>(null);
  const [cursorElement, setCursorElement] = useState<ElementInfo | null>(null);

  // Cursor tracking debounce
  const cursorDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Bridge lifecycle — always attempt install, optimistically mark as installed
  const [bridgeInstalled, setBridgeInstalled] = useState(true); // optimistic
  const installRanRef = useRef(false);
  const indexRanRef = useRef<string | null>(null);

  // Design store state (undo/redo + flush status)
  const canUndo = useDesignStore((s) => s.past.length > 0);
  const canRedo = useDesignStore((s) => s.future.length > 0);
  const flushing = useDesignStore((s) => s.flushing);
  const persistError = useDesignStore((s) => s.lastError);
  const indexLoaded = useDesignStore((s) => s.indexLoaded);
  const indexLoading = useDesignStore((s) => s.indexLoading);
  const pendingInsert = useDesignStore((s) => s.pendingInsert);
  const designIndex = useDesignStore((s) => s.index);

  // Pending insert needs to be readable inside callbacks without re-binding
  // them on every store update — keep a ref in sync.
  const pendingInsertRef = useRef(pendingInsert);
  pendingInsertRef.current = pendingInsert;
  const designIndexRef = useRef(designIndex);
  designIndexRef.current = designIndex;

  const hasFiles = fileTree.length > 0;
  useEffect(() => {
    if (!hasFiles || installRanRef.current) return;
    installRanRef.current = true;
    // Fire and forget — install is idempotent (skips if already installed)
    installBridge(slug, fileTree, containerDir).then((ok) => {
      if (!ok) setBridgeInstalled(false);
    });
  }, [hasFiles, slug]); // eslint-disable-line react-hooks/exhaustive-deps

  // Design index: load on mount, rebuild once per project to inject any
  // new OIDs. We guard with a ref so opening the view multiple times
  // doesn't re-rebuild needlessly.
  useEffect(() => {
    if (!hasFiles) return;
    void bindDesignSlug(slug);
    bindCanvasSlug(slug);
    if (indexRanRef.current !== slug) {
      indexRanRef.current = slug;
      void rebuildDesignIndex();
    }
  }, [hasFiles, slug]);

  // Undo / redo — Cmd/Ctrl+Z and Cmd/Ctrl+Shift+Z.
  useHotkeys(
    'mod+z',
    (e) => {
      e.preventDefault();
      void designUndo();
    },
    { enableOnContentEditable: false, enableOnFormTags: false },
    [],
  );
  useHotkeys(
    'mod+shift+z',
    (e) => {
      e.preventDefault();
      void designRedo();
    },
    { enableOnContentEditable: false, enableOnFormTags: false },
    [],
  );

  // Delete selected element(s)
  useHotkeys(
    'backspace,delete',
    (e) => {
      // Only fire when focus isn't in an editable surface; the design
      // selection is owned by the iframe, not the host DOM.
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return;
      }
      e.preventDefault();
      void deleteDesignSelected();
    },
    { enableOnContentEditable: false, enableOnFormTags: false },
    [],
  );
  // Copy/paste selection
  useHotkeys(
    'mod+c',
    (e) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return;
      }
      copyDesignSelection();
    },
    { enableOnContentEditable: false, enableOnFormTags: false },
    [],
  );
  useHotkeys(
    'mod+v',
    (e) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return;
      }
      void pasteDesignClipboard();
    },
    { enableOnContentEditable: false, enableOnFormTags: false },
    [],
  );
  useHotkeys(
    'mod+g',
    (e) => {
      e.preventDefault();
      void groupDesignSelected();
    },
    { enableOnContentEditable: false, enableOnFormTags: false },
    [],
  );
  useHotkeys(
    'escape',
    () => {
      // Esc cancels an armed insert before clearing the selection so the
      // user gets out of placement mode with one keypress.
      if (pendingInsertRef.current) {
        clearPendingInsert();
        return;
      }
      clearDesignSelection();
    },
    [],
  );
  // The bridge script is inert until it receives 'design:activate' via postMessage,
  // so it's harmless to leave in the project. Removing it on every HMR/re-render
  // causes a race condition where the bridge gets deleted before it can load.

  // ── Callbacks ──────────────────────────────────────────────────────

  const handleFileSelect = useCallback((path: string) => {
    setExternalOpenFile(path);
    // Reset after a tick so subsequent clicks on the same file work
    setTimeout(() => setExternalOpenFile(undefined), 0);
  }, []);

  const handleEditorRef = useCallback((editor: unknown) => {
    editorRefState.current = editor;

    // Set up cursor position tracking for class/element detection
    const monacoEditor = editor as {
      onDidChangeCursorPosition: (cb: (e: { position: { lineNumber: number; column: number } }) => void) => { dispose: () => void };
      getModel: () => { getLineContent: (line: number) => string; getLineCount: () => number } | null;
    };

    const disposable = monacoEditor.onDidChangeCursorPosition((e) => {
      if (cursorDebounceRef.current) clearTimeout(cursorDebounceRef.current);
      cursorDebounceRef.current = setTimeout(() => {
        const model = monacoEditor.getModel();
        if (!model) return;

        const classes = detectClassesAtCursor(model, e.position);
        setCursorClasses(classes);

        const element = detectElementAtCursor(model, e.position);
        setCursorElement(element);
      }, 150);
    });

    return () => disposable.dispose();
  }, []);

  const handleSelectedFileChange = useCallback((path: string | null) => {
    setSelectedFile(path);
  }, []);

  // Insert flow:
  //   1. User picks a snippet from InsertPalette → arm placement mode.
  //   2. PreviewCanvas surfaces a pill + the bridge keeps passing clicks
  //      through as element-data → handleElementSelect intercepts.
  // The fallback (no element bridge / no source mapping) drops the
  // snippet at the current Monaco cursor like before.
  const insertSnippetAtCursor = useCallback((snippet: string) => {
    const editor = editorRefState.current as {
      executeEdits: (source: string, edits: Array<{ range: unknown; text: string }>) => void;
      getPosition: () => { lineNumber: number; column: number } | null;
      focus?: () => void;
    } | null;
    if (!editor) return false;
    const position = editor.getPosition();
    if (!position) return false;
    const range = {
      startLineNumber: position.lineNumber,
      startColumn: position.column,
      endLineNumber: position.lineNumber,
      endColumn: position.column,
    };
    editor.executeEdits('design-insert', [{ range, text: snippet }]);
    editor.focus?.();
    return true;
  }, []);

  // Insert at the end of a specific (file, line) — used by placement mode.
  const insertSnippetAtLine = useCallback((targetLine: number, snippet: string) => {
    const editor = editorRefState.current as {
      executeEdits: (source: string, edits: Array<{ range: unknown; text: string }>) => void;
      getModel: () => { getLineContent: (line: number) => string; getLineCount: () => number } | null;
      setPosition?: (pos: { lineNumber: number; column: number }) => void;
      revealLineInCenter?: (line: number) => void;
      focus?: () => void;
    } | null;
    if (!editor) return false;
    const model = editor.getModel();
    if (!model) return false;
    const lineCount = model.getLineCount();
    const line = Math.max(1, Math.min(targetLine, lineCount));
    const lineText = model.getLineContent(line);
    // Indent the snippet to match the opening tag's indentation so the
    // pasted JSX lands flush rather than at column 1.
    const indentMatch = lineText.match(/^(\s*)/);
    const indent = indentMatch ? indentMatch[1] : '';
    const indented = snippet
      .split('\n')
      .map((row, i) => (i === 0 ? row : indent + row))
      .join('\n');
    const text = '\n' + indent + indented;
    const endCol = lineText.length + 1;
    const range = {
      startLineNumber: line,
      startColumn: endCol,
      endLineNumber: line,
      endColumn: endCol,
    };
    editor.executeEdits('design-insert-at-line', [{ range, text }]);
    editor.setPosition?.({ lineNumber: line + 1, column: endCol });
    editor.revealLineInCenter?.(line + 1);
    editor.focus?.();
    return true;
  }, []);

  const handleElementSelect = useCallback((element: ElementData, opts?: { additive?: boolean }) => {
    // Placement mode: the next click is a target drop, not a selection.
    const armed = pendingInsertRef.current;
    if (armed && !opts?.additive) {
      const indexEntry = element.oid ? designIndexRef.current[element.oid] : null;
      const sourceFile = indexEntry?.path || element.reactComponent?.sourceFile || null;
      const startLine = indexEntry?.start_line ?? null;
      if (sourceFile) {
        const filePath = sourceFile
          .replace(/^\/app\//, '')
          .replace(/^(\.\/|\/src\/|\/project\/)/, '');
        const match = fileTree.find((f) =>
          f.path === filePath ||
          f.path.endsWith('/' + filePath) ||
          f.path === 'app/' + filePath ||
          f.path === 'src/' + filePath ||
          f.path === 'src/app/' + filePath,
        );
        const finalPath = match?.path || filePath;
        setExternalOpenFile(finalPath);
        setTimeout(() => setExternalOpenFile(undefined), 0);
        // Wait for the file to mount in Monaco before inserting.
        const tryInsert = (attempt = 0) => {
          const ok = startLine
            ? insertSnippetAtLine(startLine, armed.snippet)
            : insertSnippetAtCursor(armed.snippet);
          if (!ok && attempt < 10) {
            setTimeout(() => tryInsert(attempt + 1), 60);
          }
        };
        setTimeout(tryInsert, 80);
      } else {
        // No source mapping — fall back to current Monaco cursor.
        insertSnippetAtCursor(armed.snippet);
      }
      clearPendingInsert();
      return;
    }

    setSelectedElement(element);
    setActiveInspectorTab('inspector');
    // Mirror into the design store so hotkeys (delete/copy/group) can
    // operate on the current selection without drilling through props.
    if (element.oid) {
      selectDesignElement(
        {
          oid: element.oid,
          designId: element.designId,
          tagName: element.tagName,
          classList: element.classList,
          textContent: element.textContent,
        },
        { additive: opts?.additive },
      );
    }

    // Open source file in code editor
    const rc = element.reactComponent;
    let sourceFile = rc?.sourceFile || null;

    // Next.js: try pagePath prop (e.g., "/page.tsx" → "app/page.tsx")
    if (!sourceFile && rc?.props?.pagePath) {
      const pagePath = String(rc.props.pagePath);
      sourceFile = 'app' + (pagePath.startsWith('/') ? pagePath : '/' + pagePath);
    }

    // Fallback: search for unique class names in project source files
    if (!sourceFile && element.classList.length > 0) {
      // Look for .tsx/.jsx/.html files that might contain these classes
      const uniqueClass = element.classList.find(c => !c.startsWith('sm:') && !c.startsWith('md:') && c.length > 4);
      if (uniqueClass) {
        const candidates = fileTree.filter(f =>
          !f.is_dir &&
          /\.(tsx|jsx|html|vue|svelte)$/.test(f.path) &&
          !f.path.includes('node_modules') &&
          !f.path.includes('.next')
        );
        // For now, open the main page file as best guess
        const pageFile = candidates.find(f =>
          f.path.match(/app\/page\.(tsx|jsx)$/) ||
          f.path.match(/pages\/index\.(tsx|jsx)$/) ||
          f.path === 'index.html'
        );
        if (pageFile) sourceFile = pageFile.path;
      }
    }

    if (sourceFile) {
      let filePath = sourceFile;
      filePath = filePath.replace(/^\/app\//, '');
      filePath = filePath.replace(/^(\.\/|\/src\/|\/project\/)/, '');

      const match = fileTree.find(f =>
        f.path === filePath ||
        f.path.endsWith('/' + filePath) ||
        f.path === 'app/' + filePath ||
        f.path === 'src/' + filePath ||
        f.path === 'src/app/' + filePath
      );

      const finalPath = match?.path || filePath;
      setExternalOpenFile(finalPath);
      setTimeout(() => setExternalOpenFile(undefined), 0);
    }
  }, [fileTree, insertSnippetAtCursor, insertSnippetAtLine]);

  const handleElementHover = useCallback((_element: ElementData | null) => {
    // Could update a hover indicator — currently a no-op
  }, []);

  const handleInsert = useCallback((snippet: string) => {
    // Arm placement mode — the next canvas click drops the snippet at
    // that element's source location. PreviewCanvas shows the pill cue.
    armPendingInsert(snippet);
  }, []);

  const handleTextChanged = useCallback((designId: string, text: string, _sourceFile?: string, _lineNumber?: number) => {
    // Resolve oid from the selected element. When text is edited on an
    // element other than the current selection, the bridge still sends
    // us a designId but no oid — so fall back to reading the oid off the
    // live DOM inside the iframe by querying for data-did.
    let oid = selectedElement && selectedElement.designId === designId ? selectedElement.oid : null;
    if (!oid) {
      const iframe = document.querySelector<HTMLIFrameElement>('#design-preview-iframe');
      const doc = iframe?.contentDocument;
      const el = doc?.querySelector(`[data-did="${CSS.escape(designId)}"]`);
      oid = el?.closest('[data-oid]')?.getAttribute('data-oid') || null;
    }
    if (!oid) return;
    const prevText = selectedElement?.textContent || '';
    pushTextEdit(oid, text, prevText);
  }, [selectedElement]);

  const handleInstallBridge = useCallback(() => {
    installBridge(slug, fileTree, containerDir).then((ok) => {
      if (ok) setBridgeInstalled(true);
    });
  }, [slug, fileTree, containerDir]);

  // Send style update to bridge (live preview via runtime stylesheet) and
  // enqueue a persist diff so the change lands in the source file.
  const handleStyleUpdate = useCallback((designId: string, property: string, value: string) => {
    // 1. Live preview update (immediate visual feedback)
    const iframe = document.querySelector<HTMLIFrameElement>('#design-preview-iframe');
    if (iframe) {
      sendDesignMessage(iframe, { type: 'design:update-style', designId, property, value });
    }
    // 2. Resolve oid for persistence
    const oid =
      selectedElement && selectedElement.designId === designId ? selectedElement.oid : null;
    if (!oid) return;
    const prevValue = selectedElement?.computedStyles?.[property] ?? '';
    pushStyleEdit(oid, { [property]: value }, { [property]: prevValue });
  }, [selectedElement]);

  const handleElementMoved = useCallback((designId: string, deltaX: number, deltaY: number) => {
    // Apply position via bridge style update. We emit a compound style_patch
    // so all three properties land as one coalesced action.
    const iframe = document.querySelector<HTMLIFrameElement>('#design-preview-iframe');
    if (iframe) {
      sendDesignMessage(iframe, { type: 'design:update-style', designId, property: 'position', value: 'relative' });
      sendDesignMessage(iframe, { type: 'design:update-style', designId, property: 'left', value: `${deltaX}px` });
      sendDesignMessage(iframe, { type: 'design:update-style', designId, property: 'top', value: `${deltaY}px` });
    }
    const oid =
      selectedElement && selectedElement.designId === designId ? selectedElement.oid : null;
    if (!oid) return;
    pushStyleEdit(
      oid,
      { position: 'relative', left: `${deltaX}px`, top: `${deltaY}px` },
      {
        position: selectedElement?.computedStyles?.position ?? '',
        left: selectedElement?.computedStyles?.left ?? '',
        top: selectedElement?.computedStyles?.top ?? '',
      },
    );
  }, [selectedElement]);

  const handleStyleRemove = useCallback((designId: string, property: string) => {
    const iframe = document.querySelector<HTMLIFrameElement>('#design-preview-iframe');
    if (iframe) {
      sendDesignMessage(iframe, { type: 'design:remove-style', designId, property });
    }
    const oid =
      selectedElement && selectedElement.designId === designId ? selectedElement.oid : null;
    if (!oid) return;
    const prevValue = selectedElement?.computedStyles?.[property] ?? '';
    // Setting to empty string in style_patch removes the key.
    pushStyleEdit(oid, { [property]: '' }, { [property]: prevValue });
  }, [selectedElement]);

  const handleClassUpdate = useCallback((designId: string, classes: string[]) => {
    const iframe = document.querySelector<HTMLIFrameElement>('#design-preview-iframe');
    if (iframe) {
      sendDesignMessage(iframe, { type: 'design:update-classes', designId, classes });
    }
    const oid =
      selectedElement && selectedElement.designId === designId ? selectedElement.oid : null;
    if (!oid) return;
    const prev = (selectedElement?.classList || []).join(' ');
    pushClassEdit(oid, classes.join(' '), prev, true);
  }, [selectedElement]);

  // Compute viewport width
  const viewportWidth = BREAKPOINT_WIDTHS[viewportBreakpoint];

  // Clean up debounce on unmount
  useEffect(() => {
    return () => {
      if (cursorDebounceRef.current) clearTimeout(cursorDebounceRef.current);
    };
  }, []);

  // Listen for bridge messages: text-changed, element-moved, source-location,
  // element-data (for multi-select additive flag)
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const data = event.data;
      if (!data || typeof data !== 'object' || typeof data.type !== 'string') return;

      if (data.type === 'design:element-data' && data.data && data.additive) {
        // Shift/cmd-click additive selection. The non-additive path
        // already flows through PreviewCanvas → handleElementSelect.
        const el = data.data as ElementData;
        if (el.oid) {
          selectDesignElement(
            {
              oid: el.oid,
              designId: el.designId,
              tagName: el.tagName,
              classList: el.classList,
              textContent: el.textContent,
            },
            { additive: true },
          );
        }
      }
      if (data.type === 'design:text-changed') {
        handleTextChanged(data.designId, data.text, data.sourceFile, data.lineNumber);
      }
      if (data.type === 'design:element-moved') {
        handleElementMoved(data.designId, data.deltaX, data.deltaY);
      }
      if (data.type === 'design:source-location') {
        const filePath = data.sourceFile?.replace(/^(\/app\/|\.\/|\/src\/)/, '') || '';
        if (filePath) {
          setExternalOpenFile(filePath);
          setTimeout(() => setExternalOpenFile(undefined), 0);
        }
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [handleTextChanged, handleElementMoved]);

  // ── Render ─────────────────────────────────────────────────────────
  const fileTreeNode = (
    <FileTreePanel
      fileTree={fileTree}
      selectedFile={selectedFile}
      onFileSelect={(p) => {
        handleFileSelect(p);
        if (isNarrow) setMobileFileTreeOpen(false);
      }}
      onFileCreate={onFileCreate}
      onFileDelete={onFileDelete}
      onFileRename={onFileRename}
      onDirectoryCreate={onDirectoryCreate}
      isFilesSyncing={isFilesSyncing}
      slug={slug}
      projectId={projectId}
    />
  );

  const inspectorNode = (
    <InspectorPanel
      activeTab={activeInspectorTab}
      onTabChange={setActiveInspectorTab}
      cursorClasses={cursorClasses}
      editorRef={editorRefState.current}
      selectedElement={selectedElement}
      cursorElement={cursorElement}
      onStyleUpdate={handleStyleUpdate}
      onStyleRemove={handleStyleRemove}
      onClassUpdate={handleClassUpdate}
    />
  );

  const centerColumn = (
    <div className="h-full flex flex-col overflow-hidden">
      <DesignToolbar
        designMode={designMode}
        onDesignModeChange={setDesignMode}
        viewportBreakpoint={viewportBreakpoint}
        onViewportChange={setViewportBreakpoint}
        onRefresh={onRefreshPreview}
        onInsert={handleInsert}
        fileTree={fileTree}
        canUndo={canUndo}
        canRedo={canRedo}
        flushing={flushing}
        persistError={persistError}
        indexLoaded={indexLoaded}
        indexLoading={indexLoading}
        onUndo={() => { void designUndo(); }}
        onRedo={() => { void designRedo(); }}
        showPanelToggles={isNarrow}
        onToggleFileTree={isNarrow ? () => setMobileFileTreeOpen((v) => !v) : undefined}
        onToggleInspector={isNarrow ? () => setMobileInspectorOpen((v) => !v) : undefined}
      />

      <div className="flex-1 min-h-0">
        <PanelGroup orientation="vertical">
          <Panel
            id="design-preview"
            defaultSize="58"
            minSize="25"
            className="overflow-hidden"
          >
            <PreviewCanvas
              devServerUrl={devServerUrl}
              devServerUrlWithAuth={devServerUrlWithAuth}
              designMode={designMode}
              viewportWidth={viewportWidth}
              onElementSelect={handleElementSelect}
              onElementHover={handleElementHover}
              onRefresh={onRefreshPreview}
              bridgeInstalled={bridgeInstalled}
              onInstallBridge={handleInstallBridge}
            />
          </Panel>

          <PanelResizeHandle className="h-1.5 bg-transparent cursor-row-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />

          <Panel
            id="design-editor"
            defaultSize="42"
            minSize="20"
            collapsible
            className="overflow-hidden"
          >
            <CodeEditor
              projectId={projectId}
              slug={slug}
              fileTree={fileTree}
              containerDir={containerDir}
              onFileUpdate={onFileUpdate}
              onFileCreate={onFileCreate}
              onFileDelete={onFileDelete}
              onFileRename={onFileRename}
              onDirectoryCreate={onDirectoryCreate}
              isFilesSyncing={isFilesSyncing}
              showSidebar={false}
              externalOpenFile={externalOpenFile}
              onEditorRef={handleEditorRef}
              onSelectedFileChange={handleSelectedFileChange}
            />
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );

  if (isNarrow) {
    return (
      <div className="relative w-full h-full overflow-hidden">
        {centerColumn}

        {(mobileFileTreeOpen || mobileInspectorOpen) && (
          <div
            className="absolute inset-0 z-30 bg-black/40"
            onClick={() => {
              setMobileFileTreeOpen(false);
              setMobileInspectorOpen(false);
            }}
          />
        )}

        <aside
          className="absolute top-0 left-0 bottom-0 z-40 w-72 max-w-[80vw] border-r border-[var(--border)] bg-[var(--bg)] shadow-2xl transition-transform duration-200"
          style={{ transform: mobileFileTreeOpen ? 'translateX(0)' : 'translateX(-100%)' }}
        >
          {fileTreeNode}
        </aside>

        <aside
          className="absolute top-0 right-0 bottom-0 z-40 w-80 max-w-[85vw] border-l border-[var(--border)] bg-[var(--bg)] shadow-2xl transition-transform duration-200"
          style={{ transform: mobileInspectorOpen ? 'translateX(0)' : 'translateX(100%)' }}
        >
          {inspectorNode}
        </aside>
      </div>
    );
  }

  return (
    <div className="w-full h-full overflow-hidden">
      <PanelGroup orientation="horizontal">
        <Panel
          id="design-filetree"
          defaultSize="15"
          minSize="10"
          maxSize="25"
          collapsible
          className="overflow-hidden"
        >
          {fileTreeNode}
        </Panel>

        <PanelResizeHandle className="w-1.5 bg-transparent cursor-col-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />

        <Panel id="design-center" minSize="40" className="overflow-hidden">
          {centerColumn}
        </Panel>

        <PanelResizeHandle className="w-1.5 bg-transparent cursor-col-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />

        <Panel
          id="design-inspector"
          defaultSize="22"
          minSize="15"
          maxSize="35"
          collapsible
          className="overflow-hidden"
        >
          {inspectorNode}
        </Panel>
      </PanelGroup>
    </div>
  );
}
