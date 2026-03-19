import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  File,
  Folder,
  ChevronRight,
  ChevronDown,
  FileText,
  Code,
  PanelLeftClose,
  PanelLeft,
  FilePlus,
  FolderPlus,
  Pencil,
  Trash2,
} from 'lucide-react';
import Editor from '@monaco-editor/react';
import { useTheme } from '../theme/ThemeContext';
import { projectsApi } from '../lib/api';

interface FileNode {
  name: string;
  path: string;
  isDirectory: boolean;
  children?: FileNode[];
}

interface FileTreeEntry {
  path: string;
  name: string;
  is_dir: boolean;
  size: number;
  mod_time: number;
}

interface ContextMenuState {
  x: number;
  y: number;
  node: FileNode | null; // null = right-clicked on empty space
}

interface InlineInputState {
  parentPath: string; // '' for root
  kind: 'file' | 'folder' | 'rename';
  initialValue?: string;
  originalPath?: string; // for rename
}

interface CodeEditorProps {
  projectId: number;
  slug: string;
  fileTree: FileTreeEntry[];
  containerDir?: string;
  onFileUpdate: (filePath: string, content: string) => void;
  onFileCreate?: (filePath: string) => void;
  onFileDelete?: (filePath: string, isDirectory: boolean) => void;
  onFileRename?: (oldPath: string, newPath: string) => void;
  onDirectoryCreate?: (dirPath: string) => void;
  isFilesSyncing?: boolean;
  startupOverlay?: React.ReactNode;
}

function CodeEditor({
  projectId: _projectId,
  slug,
  fileTree: fileTreeProp,
  containerDir,
  onFileUpdate,
  onFileCreate,
  onFileDelete,
  onFileRename,
  onDirectoryCreate,
  isFilesSyncing,
  startupOverlay,
}: CodeEditorProps) {
  const { theme } = useTheme();
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [selectedDir, setSelectedDir] = useState<string | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set(['']));
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const editorRef = useRef<unknown>(null);

  // ── Zero-render stats: ref + direct DOM mutation instead of useState ──
  const statsRef = useRef<{ lines: number; chars: number } | null>(null);
  const statsElementRef = useRef<HTMLParagraphElement>(null);

  function updateStatsDisplay(lines: number, chars: number) {
    statsRef.current = { lines, chars };
    if (statsElementRef.current) {
      statsElementRef.current.textContent = `${lines} lines \u2022 ${chars} characters`;
    }
  }

  // Local content cache: tracks what the user has typed so server refreshes
  // don't overwrite in-progress edits and cause cursor jumps.
  const localContentRef = useRef<Map<string, string>>(new Map());

  // Debounced save: only call onFileUpdate after 500ms of idle
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingFileRef = useRef<string | null>(null);

  // Stable ref to onFileUpdate to avoid re-creating callbacks when prop changes
  const onFileUpdateRef = useRef(onFileUpdate);
  onFileUpdateRef.current = onFileUpdate;

  // Stable ref to selectedFile for callbacks that must not re-create on selection change
  const selectedFileRef = useRef(selectedFile);
  selectedFileRef.current = selectedFile;

  // Context menu state
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  // Inline input state (create file/folder or rename)
  const [inlineInput, setInlineInput] = useState<InlineInputState | null>(null);
  // Delete confirmation
  const [deleteConfirm, setDeleteConfirm] = useState<FileNode | null>(null);
  // Loading state for lazy content fetch
  const [loadingContent, setLoadingContent] = useState(false);

  const menuRef = useRef<HTMLDivElement>(null);
  const inlineInputRef = useRef<HTMLInputElement>(null);

  // ── Memoized Monaco options — same reference across all renders ──────
  const editorOptions = useMemo(
    () => ({
      fontSize: 14,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
      lineNumbers: 'on' as const,
      minimap: { enabled: true },
      scrollBeyondLastLine: false,
      automaticLayout: true,
      tabSize: 2,
      wordWrap: 'on' as const,
      padding: { top: 16, bottom: 16 },
      smoothScrolling: true,
      cursorBlinking: 'smooth' as const,
      cursorSmoothCaretAnimation: 'on' as const,
      renderLineHighlight: 'all' as const,
      bracketPairColorization: { enabled: true },
      guides: { bracketPairs: true, indentation: true },
      suggestOnTriggerCharacters: true,
      quickSuggestions: true,
      formatOnPaste: true,
      formatOnType: true,
    }),
    []
  );

  // Flush any pending debounced save immediately
  const flushPendingSave = useCallback(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    const file = pendingFileRef.current;
    if (file) {
      const content = localContentRef.current.get(file);
      if (content !== undefined) {
        onFileUpdateRef.current(file, content);
      }
      pendingFileRef.current = null;
    }
  }, []);

  // Flush pending save before switching files
  const switchToFile = useCallback(
    (path: string) => {
      flushPendingSave();
      setSelectedFile(path);
    },
    [flushPendingSave]
  );

  // Flush on unmount
  useEffect(() => {
    return () => flushPendingSave();
  }, [flushPendingSave]);

  const getLanguage = (fileName: string): string => {
    const ext = fileName.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'js':
        return 'javascript';
      case 'jsx':
        return 'javascript';
      case 'ts':
        return 'typescript';
      case 'tsx':
        return 'typescript';
      case 'html':
        return 'html';
      case 'css':
        return 'css';
      case 'json':
        return 'json';
      case 'md':
        return 'markdown';
      case 'py':
        return 'python';
      case 'yml':
      case 'yaml':
        return 'yaml';
      default:
        return 'plaintext';
    }
  };

  // ── Memoized Monaco callbacks — stable refs, zero re-renders on typing ──

  const handleEditorDidMount = useCallback((editor: unknown) => {
    editorRef.current = editor;
    const file = selectedFileRef.current;
    if (file) {
      const model = (editor as { getModel(): { getValue(): string } | null })?.getModel();
      if (model) {
        const content = model.getValue();
        localContentRef.current.set(file, content);
        updateStatsDisplay(content.split('\n').length, content.length);
      }
    }
  }, []);

  const handleEditorChange = useCallback((value: string | undefined) => {
    const file = selectedFileRef.current;
    if (!file || value === undefined) return;

    // Update local cache immediately — Monaco owns the content
    localContentRef.current.set(file, value);

    // Update stats via direct DOM mutation — NO React re-render
    updateStatsDisplay(value.split('\n').length, value.length);

    // Debounced save: fire onFileUpdate after 500ms of idle
    pendingFileRef.current = file;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      const pendingFile = pendingFileRef.current;
      if (pendingFile) {
        const latest = localContentRef.current.get(pendingFile);
        if (latest !== undefined) {
          onFileUpdateRef.current(pendingFile, latest);
        }
        pendingFileRef.current = null;
      }
      saveTimerRef.current = null;
    }, 500);
  }, []);

  // Memoize file paths so the tree only rebuilds when paths change
  const filePathsKey = useMemo(() => fileTreeProp.map((f) => f.path).join('\0'), [fileTreeProp]);

  useEffect(() => {
    // Build hierarchical FileNode[] tree from flat fileTreeProp entries
    const tree: FileNode[] = [];
    const pathMap = new Map<string, FileNode>();

    // Sort entries by path for proper tree building
    const sorted = [...fileTreeProp]
      .filter((e) => e.path && e.path !== '.')
      .sort((a, b) => a.path.localeCompare(b.path));

    sorted.forEach((entry) => {
      const parts = entry.path.split('/').filter(Boolean);
      let currentPath = '';

      parts.forEach((part: string, index: number) => {
        const fullPath = currentPath ? `${currentPath}/${part}` : part;
        const isLeaf = index === parts.length - 1;

        if (!pathMap.has(fullPath)) {
          const node: FileNode = {
            name: part,
            path: fullPath,
            isDirectory: isLeaf ? entry.is_dir : true,
            children: (isLeaf ? entry.is_dir : true) ? [] : undefined,
          };

          pathMap.set(fullPath, node);

          if (currentPath === '') {
            tree.push(node);
          } else {
            const parent = pathMap.get(currentPath);
            if (parent && parent.children) {
              parent.children.push(node);
            }
          }
        }

        currentPath = fullPath;
      });
    });

    // Sort: folders first (alphabetically), then files (alphabetically)
    const sortNodes = (nodes: FileNode[]) => {
      nodes.sort((a, b) => {
        if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
        return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
      });
      nodes.forEach((n) => {
        if (n.children) sortNodes(n.children);
      });
    };
    sortNodes(tree);

    setFileTree(tree);

    // Auto-select the first actual file if none selected
    if (!selectedFile && sorted.length > 0) {
      const firstFile = sorted.find((e) => !e.is_dir);
      if (firstFile) {
        switchToFile(firstFile.path);
      }
    }
  }, [filePathsKey]);

  // Lazy-load file content when selectedFile changes
  useEffect(() => {
    if (!selectedFile || localContentRef.current.has(selectedFile)) return;
    let cancelled = false;
    setLoadingContent(true);
    projectsApi
      .getFileContent(slug, selectedFile, containerDir)
      .then((res) => {
        if (cancelled) return;
        localContentRef.current.set(selectedFile, res.content);
        setLoadingContent(false);
      })
      .catch(() => {
        if (!cancelled) setLoadingContent(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedFile, slug, containerDir]);

  const toggleDirectory = (path: string) => {
    setExpandedDirs((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(path)) {
        newSet.delete(path);
      } else {
        newSet.add(path);
      }
      return newSet;
    });
  };

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

  // ── Context menu handlers ──────────────────────────────────────────

  const handleContextMenu = useCallback((e: React.MouseEvent, node: FileNode | null) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, node });
  }, []);

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  // Close context menu on outside click or Escape
  useEffect(() => {
    if (!contextMenu) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        closeContextMenu();
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeContextMenu();
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [contextMenu, closeContextMenu]);

  // Auto-focus inline input
  useEffect(() => {
    if (inlineInput && inlineInputRef.current) {
      inlineInputRef.current.focus();
      if (inlineInput.kind === 'rename' && inlineInput.initialValue) {
        // Select the name part (without extension for files)
        const val = inlineInput.initialValue;
        const dotIdx = val.lastIndexOf('.');
        inlineInputRef.current.setSelectionRange(0, dotIdx > 0 ? dotIdx : val.length);
      } else {
        inlineInputRef.current.select();
      }
    }
  }, [inlineInput]);

  // ── Inline input submission ────────────────────────────────────────

  const handleInlineSubmit = useCallback(
    (value: string) => {
      if (!inlineInput) return;
      // Clear state first to prevent double-submission from blur after Enter
      const current = inlineInput;
      setInlineInput(null);

      const trimmed = value.trim();
      if (!trimmed) return;

      // Validate name
      if (trimmed.includes('/') || trimmed.includes('\\')) {
        return;
      }

      if (current.kind === 'rename' && current.originalPath) {
        const parentDir = current.originalPath.includes('/')
          ? current.originalPath.substring(0, current.originalPath.lastIndexOf('/'))
          : '';
        const newPath = parentDir ? `${parentDir}/${trimmed}` : trimmed;

        if (newPath !== current.originalPath) {
          onFileRename?.(current.originalPath, newPath);
          // If the renamed item was selected, update selection
          if (selectedFile === current.originalPath) {
            setSelectedFile(newPath);
          } else if (selectedFile?.startsWith(current.originalPath + '/')) {
            setSelectedFile(newPath + selectedFile.substring(current.originalPath.length));
          }
        }
      } else if (current.kind === 'file') {
        const fullPath = current.parentPath ? `${current.parentPath}/${trimmed}` : trimmed;
        onFileCreate?.(fullPath);
      } else if (current.kind === 'folder') {
        const fullPath = current.parentPath ? `${current.parentPath}/${trimmed}` : trimmed;
        onDirectoryCreate?.(fullPath);
      }
    },
    [inlineInput, onFileRename, onFileCreate, onDirectoryCreate, selectedFile]
  );

  // ── Context menu actions ───────────────────────────────────────────

  const startNewFile = useCallback(
    (parentPath: string) => {
      closeContextMenu();
      // Expand parent directory so the input is visible
      if (parentPath) {
        setExpandedDirs((prev) => new Set([...prev, parentPath]));
      }
      setInlineInput({ parentPath, kind: 'file' });
    },
    [closeContextMenu]
  );

  const startNewFolder = useCallback(
    (parentPath: string) => {
      closeContextMenu();
      if (parentPath) {
        setExpandedDirs((prev) => new Set([...prev, parentPath]));
      }
      setInlineInput({ parentPath, kind: 'folder' });
    },
    [closeContextMenu]
  );

  const startRename = useCallback(
    (node: FileNode) => {
      closeContextMenu();
      const parentPath = node.path.includes('/')
        ? node.path.substring(0, node.path.lastIndexOf('/'))
        : '';
      setInlineInput({
        parentPath,
        kind: 'rename',
        initialValue: node.name,
        originalPath: node.path,
      });
    },
    [closeContextMenu]
  );

  const confirmDelete = useCallback(
    (node: FileNode) => {
      closeContextMenu();
      setDeleteConfirm(node);
    },
    [closeContextMenu]
  );

  const executeDelete = useCallback(() => {
    if (!deleteConfirm) return;
    onFileDelete?.(deleteConfirm.path, deleteConfirm.isDirectory);
    // If the deleted item was the selected file, clear selection
    if (
      selectedFile === deleteConfirm.path ||
      (deleteConfirm.isDirectory && selectedFile?.startsWith(deleteConfirm.path + '/'))
    ) {
      setSelectedFile(null);
    }
    setDeleteConfirm(null);
  }, [deleteConfirm, onFileDelete, selectedFile]);

  // ── Render inline input row ────────────────────────────────────────

  const renderInlineInput = (depth: number) => {
    if (!inlineInput) return null;

    const icon =
      inlineInput.kind === 'folder' ? (
        <Folder size={14} className="mr-2 text-blue-400" />
      ) : inlineInput.kind === 'rename' ? null : (
        <File size={14} className="mr-2 text-gray-400" />
      );

    return (
      <div className="flex items-center py-1 px-3" style={{ paddingLeft: `${depth * 16 + 12}px` }}>
        {inlineInput.kind !== 'rename' && <div className="w-4 mr-2" />}
        {icon}
        <input
          ref={inlineInputRef}
          className="flex-1 text-sm bg-[var(--surface)] text-[var(--text)] border border-[var(--primary)] rounded px-1.5 py-0.5 outline-none"
          defaultValue={inlineInput.initialValue || ''}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              handleInlineSubmit((e.target as HTMLInputElement).value);
            } else if (e.key === 'Escape') {
              setInlineInput(null);
            }
          }}
          onBlur={(e) => handleInlineSubmit(e.target.value)}
        />
      </div>
    );
  };

  // ── Render file tree ───────────────────────────────────────────────

  const renderFileTree = (nodes: FileNode[], depth = 0) => {
    const items: React.ReactNode[] = [];

    nodes.forEach((node) => {
      const isBeingRenamed =
        inlineInput?.kind === 'rename' && inlineInput.originalPath === node.path;

      items.push(
        <div key={node.path} className="select-none">
          {isBeingRenamed ? (
            <div
              className="flex items-center py-1 px-3"
              style={{ paddingLeft: `${depth * 16 + 12}px` }}
            >
              {node.isDirectory ? (
                <>
                  <ChevronRight size={14} className="mr-2 text-[var(--text)]/50" />
                  <Folder size={14} className="mr-2 text-blue-400" />
                </>
              ) : (
                <>
                  <div className="w-4 mr-2" />
                  {getFileIcon(node.name)}
                  <div className="mr-2" />
                </>
              )}
              <input
                ref={inlineInputRef}
                className="flex-1 text-sm bg-[var(--surface)] text-[var(--text)] border border-[var(--primary)] rounded px-1.5 py-0.5 outline-none"
                defaultValue={inlineInput?.initialValue || ''}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleInlineSubmit((e.target as HTMLInputElement).value);
                  } else if (e.key === 'Escape') {
                    setInlineInput(null);
                  }
                }}
                onBlur={(e) => handleInlineSubmit(e.target.value)}
              />
            </div>
          ) : (
            <div
              className={`flex items-center py-2 px-3 cursor-pointer rounded-lg mb-0.5 transition-all duration-150 ${
                selectedFile === node.path
                  ? 'bg-orange-500/20 text-orange-300 border-l-2 border-orange-500'
                  : selectedDir === node.path
                    ? 'bg-[var(--text)]/10 text-[var(--text)] border-l-2 border-[var(--text)]/30'
                    : 'hover:bg-[var(--surface)]/70 text-[var(--text)]/80 hover:text-[var(--text)]'
              }`}
              style={{ paddingLeft: `${depth * 16 + 12}px` }}
              onClick={() => {
                if (node.isDirectory) {
                  toggleDirectory(node.path);
                  setSelectedDir(node.path);
                } else {
                  switchToFile(node.path);
                  setSelectedDir(null);
                }
              }}
              onContextMenu={(e) => handleContextMenu(e, node)}
            >
              {node.isDirectory ? (
                <>
                  {expandedDirs.has(node.path) ? (
                    <ChevronDown size={14} className="mr-2 text-[var(--text)]/50" />
                  ) : (
                    <ChevronRight size={14} className="mr-2 text-[var(--text)]/50" />
                  )}
                  <Folder size={14} className="mr-2 text-blue-400" />
                </>
              ) : (
                <>
                  <div className="w-4 mr-2"></div>
                  {getFileIcon(node.name)}
                  <div className="mr-2"></div>
                </>
              )}
              <span
                className={`text-sm flex-1 font-medium truncate ${
                  selectedFile === node.path ? 'text-orange-200' : ''
                }`}
              >
                {node.name}
              </span>
            </div>
          )}

          {node.isDirectory && expandedDirs.has(node.path) && (
            <>
              {/* Inline input for new file/folder inside this directory */}
              {inlineInput &&
                inlineInput.kind !== 'rename' &&
                inlineInput.parentPath === node.path &&
                renderInlineInput(depth + 1)}
              {node.children && renderFileTree(node.children, depth + 1)}
            </>
          )}
        </div>
      );
    });

    return items;
  };

  // Editor should stay mounted if we have local content (lazy-loaded)
  const hasEditorContent = selectedFile != null && localContentRef.current.has(selectedFile);

  // Compute initial stats text for the DOM ref (used when editor hasn't mounted yet)
  const initialStatsText = useMemo(() => {
    if (!selectedFile) return '';
    const local = localContentRef.current.get(selectedFile);
    if (local !== undefined) {
      return `${local.split('\n').length} lines \u2022 ${local.length} characters`;
    }
    return '';
  }, [selectedFile, hasEditorContent]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="h-full flex bg-[var(--surface)] overflow-hidden">
      {/* File tree sidebar */}
      <div
        className={`bg-[var(--background)] border-r border-[var(--border-color)] overflow-y-auto flex flex-col transition-all duration-300 ${
          isSidebarCollapsed ? 'w-0 border-0' : 'w-72'
        }`}
      >
        <div className="px-4 h-12 border-b border-[var(--border-color)] bg-[var(--surface)]/50 backdrop-blur-sm flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-gradient-to-br from-orange-500 to-pink-600 rounded-lg flex items-center justify-center shadow-lg">
              <FileText size={16} className="text-white" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--text)]">Explorer</h3>
              <p className="text-xs text-[var(--text)]/60">
                {fileTreeProp.length} {fileTreeProp.length === 1 ? 'entry' : 'entries'}
              </p>
            </div>
          </div>
          {/* Toolbar buttons */}
          {(onFileCreate || onDirectoryCreate) &&
            (() => {
              const targetDir =
                selectedDir ||
                (selectedFile?.includes('/')
                  ? selectedFile.substring(0, selectedFile.lastIndexOf('/'))
                  : '') ||
                '';
              return (
                <div className="flex items-center gap-0.5">
                  {onFileCreate && (
                    <button
                      onClick={() => startNewFile(targetDir)}
                      className="p-1.5 hover:bg-[var(--text)]/10 active:bg-[var(--text)]/20 rounded transition-colors"
                      title={targetDir ? `New File in ${targetDir}` : 'New File'}
                    >
                      <FilePlus size={15} className="text-[var(--text)]/60" />
                    </button>
                  )}
                  {onDirectoryCreate && (
                    <button
                      onClick={() => startNewFolder(targetDir)}
                      className="p-1.5 hover:bg-[var(--text)]/10 active:bg-[var(--text)]/20 rounded transition-colors"
                      title={targetDir ? `New Folder in ${targetDir}` : 'New Folder'}
                    >
                      <FolderPlus size={15} className="text-[var(--text)]/60" />
                    </button>
                  )}
                </div>
              );
            })()}
        </div>

        <div
          className="flex-1 p-2 overflow-y-auto"
          key={fileTreeProp.length}
          onClick={(e) => {
            // Click on empty space clears directory selection
            if (e.target === e.currentTarget) setSelectedDir(null);
          }}
          onContextMenu={(e) => handleContextMenu(e, null)}
        >
          {fileTree.length > 0 ? (
            <>
              {/* Inline input at root level */}
              {inlineInput &&
                inlineInput.kind !== 'rename' &&
                inlineInput.parentPath === '' &&
                renderInlineInput(0)}
              {renderFileTree(fileTree)}
            </>
          ) : isFilesSyncing ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-[var(--text)]/60 text-sm p-6 text-center rounded-xl bg-[var(--surface)]/50">
                <div className="w-8 h-8 mx-auto mb-3 border-2 border-[var(--text)]/20 border-t-orange-500 rounded-full animate-spin" />
                <p className="font-medium mb-1 text-[var(--text)]">Syncing files...</p>
                <p className="text-xs text-[var(--text)]/40">Waiting for container to be ready</p>
              </div>
            </div>
          ) : (
            <>
              {/* Inline input when tree is empty */}
              {inlineInput &&
                inlineInput.kind !== 'rename' &&
                inlineInput.parentPath === '' &&
                renderInlineInput(0)}
              <div className="text-[var(--text)]/60 text-sm p-6 text-center rounded-xl bg-[var(--surface)]/50">
                <Code size={32} className="mx-auto mb-3 opacity-50" />
                <p className="font-medium mb-1 text-[var(--text)]">No files yet</p>
                <p className="text-xs text-[var(--text)]/40">Files will appear here as you build</p>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Code editor area */}
      <div className="flex-1 bg-[var(--background)] overflow-hidden flex flex-col">
        {selectedFile && hasEditorContent ? (
          <>
            {/* File header */}
            <div className="px-4 h-12 border-b border-[var(--border-color)] bg-[var(--surface)]/50 backdrop-blur-sm flex items-center">
              <div className="flex items-center gap-3">
                {/* Toggle sidebar button */}
                <button
                  onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                  className="p-1.5 hover:bg-[var(--text)]/10 active:bg-[var(--text)]/20 rounded transition-colors"
                  title={isSidebarCollapsed ? 'Show file explorer' : 'Hide file explorer'}
                >
                  {isSidebarCollapsed ? (
                    <PanelLeft size={16} className="text-[var(--text)]/60" />
                  ) : (
                    <PanelLeftClose size={16} className="text-[var(--text)]/60" />
                  )}
                </button>
                {getFileIcon(selectedFile.split('/').pop() || '')}
                <div className="flex-1">
                  <h4 className="text-sm font-semibold text-[var(--text)]">{selectedFile}</h4>
                  <p ref={statsElementRef} className="text-xs text-[var(--text)]/50">
                    {initialStatsText}
                  </p>
                </div>
              </div>
            </div>

            {/* Monaco Editor */}
            <div className="flex-1 overflow-hidden">
              <Editor
                key={selectedFile}
                height="100%"
                language={getLanguage(selectedFile)}
                defaultValue={localContentRef.current.get(selectedFile) ?? ''}
                onChange={handleEditorChange}
                onMount={handleEditorDidMount}
                theme={theme === 'dark' ? 'vs-dark' : 'vs'}
                options={editorOptions}
              />
            </div>
          </>
        ) : startupOverlay ? (
          startupOverlay
        ) : loadingContent ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center p-8">
              <div className="w-10 h-10 mx-auto mb-4 border-2 border-[var(--text)]/20 border-t-orange-500 rounded-full animate-spin" />
              <p className="text-sm text-[var(--text)]/50">Loading file...</p>
            </div>
          </div>
        ) : isFilesSyncing && fileTreeProp.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center p-8">
              <div className="w-12 h-12 mx-auto mb-4 border-3 border-[var(--text)]/20 border-t-orange-500 rounded-full animate-spin" />
              <h3 className="text-lg font-semibold mb-2 text-[var(--text)]">Syncing files...</h3>
              <p className="text-sm text-[var(--text)]/50 max-w-sm">
                Waiting for container to be ready
              </p>
            </div>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-[var(--text)]/60">
            <div className="text-center p-8">
              <div className="w-20 h-20 bg-gradient-to-br from-orange-500/20 to-pink-600/20 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg">
                <Code size={40} className="opacity-60 text-orange-500" />
              </div>
              <h3 className="text-lg font-semibold mb-2 text-[var(--text)]">
                {fileTreeProp.length > 0 ? 'Select a file to edit' : 'No files yet'}
              </h3>
              <p className="text-sm text-[var(--text)]/50 max-w-sm">
                {fileTreeProp.length > 0
                  ? 'Choose a file from the explorer to start editing'
                  : 'Chat with your AI agent to generate code'}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* ── Context Menu (portal-rendered) ────────────────────────────── */}
      {contextMenu && (
        <div
          ref={menuRef}
          className="fixed z-50 min-w-[180px] py-1.5 bg-[var(--surface)] border border-[var(--border-color)] rounded-lg shadow-xl backdrop-blur-sm"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          {/* New File / New Folder — available on any right-click */}
          <button
            className="w-full px-3 py-1.5 text-left text-sm text-[var(--text)] hover:bg-[var(--text)]/10 flex items-center gap-2"
            onClick={() => {
              // Directory: create inside it. File: create in its parent. Empty space: root.
              const parent = contextMenu.node
                ? contextMenu.node.isDirectory
                  ? contextMenu.node.path
                  : contextMenu.node.path.includes('/')
                    ? contextMenu.node.path.substring(0, contextMenu.node.path.lastIndexOf('/'))
                    : ''
                : '';
              startNewFile(parent);
            }}
          >
            <FilePlus size={14} className="text-[var(--text)]/60" />
            New File
          </button>
          <button
            className="w-full px-3 py-1.5 text-left text-sm text-[var(--text)] hover:bg-[var(--text)]/10 flex items-center gap-2"
            onClick={() => {
              const parent = contextMenu.node
                ? contextMenu.node.isDirectory
                  ? contextMenu.node.path
                  : contextMenu.node.path.includes('/')
                    ? contextMenu.node.path.substring(0, contextMenu.node.path.lastIndexOf('/'))
                    : ''
                : '';
              startNewFolder(parent);
            }}
          >
            <FolderPlus size={14} className="text-[var(--text)]/60" />
            New Folder
          </button>
          {/* For files and directories: Rename / Delete */}
          {contextMenu.node && (
            <>
              <div className="h-px bg-[var(--border-color)] my-1" />
              <button
                className="w-full px-3 py-1.5 text-left text-sm text-[var(--text)] hover:bg-[var(--text)]/10 flex items-center gap-2"
                onClick={() => startRename(contextMenu.node!)}
              >
                <Pencil size={14} className="text-[var(--text)]/60" />
                Rename
              </button>
              <button
                className="w-full px-3 py-1.5 text-left text-sm text-red-400 hover:bg-red-500/10 flex items-center gap-2"
                onClick={() => confirmDelete(contextMenu.node!)}
              >
                <Trash2 size={14} />
                Delete
              </button>
            </>
          )}
        </div>
      )}

      {/* ── Delete Confirmation Dialog ────────────────────────────────── */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-[var(--surface)] border border-[var(--border-color)] rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
            <h3 className="text-base font-semibold text-[var(--text)] mb-2">
              Delete {deleteConfirm.isDirectory ? 'Folder' : 'File'}
            </h3>
            <p className="text-sm text-[var(--text)]/70 mb-1">
              Are you sure you want to delete{' '}
              <span className="font-mono text-[var(--text)]">{deleteConfirm.name}</span>?
            </p>
            {deleteConfirm.isDirectory && (
              <p className="text-xs text-red-400 mb-4">
                This will recursively delete the folder and all its contents.
              </p>
            )}
            {!deleteConfirm.isDirectory && <div className="mb-4" />}
            <div className="flex justify-end gap-2">
              <button
                className="px-3 py-1.5 text-sm rounded-lg border border-[var(--border-color)] text-[var(--text)] hover:bg-[var(--text)]/10 transition-colors"
                onClick={() => setDeleteConfirm(null)}
              >
                Cancel
              </button>
              <button
                className="px-3 py-1.5 text-sm rounded-lg bg-red-500 text-white hover:bg-red-600 transition-colors"
                onClick={executeDelete}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default React.memo(CodeEditor);
