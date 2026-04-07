import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  Panel,
  Group as PanelGroup,
  Separator as PanelResizeHandle,
} from 'react-resizable-panels';
import CodeEditor from '../CodeEditor';
import FileTreePanel from './design/FileTreePanel';
import { PreviewCanvas } from './design/PreviewCanvas';
import { DesignToolbar, type Breakpoint, BREAKPOINT_WIDTHS } from './design/DesignToolbar';
import InspectorPanel from './design/InspectorPanel';
import { sendDesignMessage, type ElementData } from './design/DesignBridge';
import { installBridge } from './design/bridgeInstaller';
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
  chatProps: Record<string, unknown>;
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
  chatProps,
  containerDir,
  onRefreshPreview,
}: DesignViewProps) {
  // ── State ──────────────────────────────────────────────────────────
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [externalOpenFile, setExternalOpenFile] = useState<string | undefined>(undefined);
  const [openFiles, setOpenFiles] = useState<{ path: string; name: string }[]>([]);
  const editorRefState = useRef<unknown>(null);

  // Preview & selection
  const [designMode, setDesignMode] = useState<'select' | 'text' | 'move'>('select');
  const [selectedElement, setSelectedElement] = useState<ElementData | null>(null);
  const [viewportBreakpoint, setViewportBreakpoint] = useState<Breakpoint>('fit');

  // Inspector
  const [activeInspectorTab, setActiveInspectorTab] = useState<'visual' | 'inspector' | 'ai'>('visual');
  const [cursorClasses, setCursorClasses] = useState<ClassInfo | null>(null);
  const [cursorElement, setCursorElement] = useState<ElementInfo | null>(null);

  // Cursor tracking debounce
  const cursorDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Bridge lifecycle — always attempt install, optimistically mark as installed
  const [bridgeInstalled, setBridgeInstalled] = useState(true); // optimistic
  const installRanRef = useRef(false);

  const hasFiles = fileTree.length > 0;
  useEffect(() => {
    if (!hasFiles || installRanRef.current) return;
    installRanRef.current = true;
    // Fire and forget — install is idempotent (skips if already installed)
    installBridge(slug, fileTree, containerDir).then((ok) => {
      if (!ok) setBridgeInstalled(false);
    });
  }, [hasFiles, slug]); // eslint-disable-line react-hooks/exhaustive-deps
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

  const handleTabsChange = useCallback((tabs: { path: string; name: string }[]) => {
    setOpenFiles(tabs);
  }, []);

  const handleSelectedFileChange = useCallback((path: string | null) => {
    setSelectedFile(path);
  }, []);

  const handleElementSelect = useCallback((element: ElementData) => {
    setSelectedElement(element);
    setActiveInspectorTab('inspector');

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
  }, [fileTree]);

  const handleElementHover = useCallback((_element: ElementData | null) => {
    // Could update a hover indicator — currently a no-op
  }, []);

  const handleInsert = useCallback((snippet: string) => {
    const editor = editorRefState.current as {
      executeEdits: (source: string, edits: Array<{ range: unknown; text: string }>) => void;
      getPosition: () => { lineNumber: number; column: number } | null;
      getModel: () => { getLineContent: (line: number) => string } | null;
    } | null;
    if (!editor) return;

    const position = editor.getPosition();
    if (!position) return;

    const range = {
      startLineNumber: position.lineNumber,
      startColumn: position.column,
      endLineNumber: position.lineNumber,
      endColumn: position.column,
    };

    editor.executeEdits('design-insert', [{ range, text: snippet }]);
  }, []);

  const _handleAIAssist = useCallback((_prompt: string) => {
    setActiveInspectorTab('ai');
  }, []);

  const handleTextChanged = useCallback((_designId: string, _text: string, _sourceFile?: string, _lineNumber?: number) => {
    // TODO: Write the text change back to the source file
    // For now, this is handled by the bridge's contenteditable
    // The text will be written when we implement source-level writes
  }, []);

  const handleInstallBridge = useCallback(() => {
    installBridge(slug, fileTree, containerDir).then((ok) => {
      if (ok) setBridgeInstalled(true);
    });
  }, [slug, fileTree, containerDir]);

  // Send style update to bridge (live preview via runtime stylesheet)
  const handleStyleUpdate = useCallback((designId: string, property: string, value: string) => {
    // Find the iframe and send message
    const iframe = document.querySelector<HTMLIFrameElement>('#design-preview-iframe');
    if (iframe) {
      sendDesignMessage(iframe, { type: 'design:update-style', designId, property, value });
    }
  }, []);

  const handleElementMoved = useCallback((designId: string, deltaX: number, deltaY: number) => {
    // Apply position via bridge style update
    handleStyleUpdate(designId, 'position', 'relative');
    handleStyleUpdate(designId, 'left', `${deltaX}px`);
    handleStyleUpdate(designId, 'top', `${deltaY}px`);
  }, [handleStyleUpdate]);

  const handleStyleRemove = useCallback((designId: string, property: string) => {
    const iframe = document.querySelector<HTMLIFrameElement>('#design-preview-iframe');
    if (iframe) {
      sendDesignMessage(iframe, { type: 'design:remove-style', designId, property });
    }
  }, []);

  const handleClassUpdate = useCallback((designId: string, classes: string[]) => {
    const iframe = document.querySelector<HTMLIFrameElement>('#design-preview-iframe');
    if (iframe) {
      sendDesignMessage(iframe, { type: 'design:update-classes', designId, classes });
    }
  }, []);

  // Compute viewport width
  const viewportWidth = BREAKPOINT_WIDTHS[viewportBreakpoint];

  // Clean up debounce on unmount
  useEffect(() => {
    return () => {
      if (cursorDebounceRef.current) clearTimeout(cursorDebounceRef.current);
    };
  }, []);

  // Listen for bridge messages: text-changed, element-moved, source-location
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const data = event.data;
      if (!data || typeof data !== 'object' || typeof data.type !== 'string') return;

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
  return (
    <div className="w-full h-full overflow-hidden">
      <PanelGroup
        orientation="horizontal"
      >
        {/* ── Left: File Tree ─────────────────────────────────────── */}
        <Panel
          id="design-filetree"
          defaultSize="15"
          minSize="10"
          maxSize="25"
          collapsible
          className="overflow-hidden"
        >
          <FileTreePanel
            fileTree={fileTree}
            selectedFile={selectedFile}
            onFileSelect={handleFileSelect}
            onFileCreate={onFileCreate}
            onFileDelete={onFileDelete}
            onFileRename={onFileRename}
            onDirectoryCreate={onDirectoryCreate}
            isFilesSyncing={isFilesSyncing}
            slug={slug}
            projectId={projectId}
          />
        </Panel>

        <PanelResizeHandle className="w-1.5 bg-transparent cursor-col-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />

        {/* ── Center: Toolbar + Preview + Code ────────────────────── */}
        <Panel id="design-center" minSize="40" className="overflow-hidden">
          <div className="h-full flex flex-col overflow-hidden">
            {/* Toolbar */}
            <DesignToolbar
              openFiles={openFiles}
              activeFile={selectedFile}
              onFileSelect={handleFileSelect}
              designMode={designMode}
              onDesignModeChange={setDesignMode}
              viewportBreakpoint={viewportBreakpoint}
              onViewportChange={setViewportBreakpoint}
              onRefresh={onRefreshPreview}
              onInsert={handleInsert}
              fileTree={fileTree}
            />

            {/* Preview + Code split */}
            <div className="flex-1 min-h-0">
              <PanelGroup
                orientation="vertical"
              >
                {/* Preview Canvas */}
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

                {/* Code Editor */}
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
                    onTabsChange={handleTabsChange}
                    onSelectedFileChange={handleSelectedFileChange}
                  />
                </Panel>
              </PanelGroup>
            </div>
          </div>
        </Panel>

        <PanelResizeHandle className="w-1.5 bg-transparent cursor-col-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />

        {/* ── Right: Inspector Panel ──────────────────────────────── */}
        <Panel
          id="design-inspector"
          defaultSize="22"
          minSize="15"
          maxSize="35"
          collapsible
          className="overflow-hidden"
        >
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
            chatProps={chatProps}
          />
        </Panel>
      </PanelGroup>
    </div>
  );
}
