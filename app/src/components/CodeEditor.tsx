import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  File,
  Folder,
  ChevronRight,
  ChevronDown,
  Code,
  PanelLeftClose,
  PanelLeft,
  FilePlus,
  FolderPlus,
  Pencil,
  Trash2,
  X,
  Search,
  Save,
} from 'lucide-react';
import Editor from '@monaco-editor/react';
import { useTheme } from '../theme/ThemeContext';
import { projectsApi } from '../lib/api';
import { fileEvents } from '../utils/fileEvents';

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
  node: FileNode | null;
}

interface InlineInputState {
  parentPath: string;
  kind: 'file' | 'folder' | 'rename';
  initialValue?: string;
  originalPath?: string;
}

interface OpenTab {
  path: string;
  name: string;
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

  // VS Code-style tabs
  const [openTabs, setOpenTabs] = useState<OpenTab[]>([]);
  // Dirty (unsaved) file buffers: path → modified content
  const [dirtyBuffers, setDirtyBuffers] = useState<Map<string, string>>(new Map());

  // Context menu state
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [inlineInput, setInlineInput] = useState<InlineInputState | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<FileNode | null>(null);
  // Loading state for lazy content fetch
  const [loadingContent, setLoadingContent] = useState(false);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Mobile detection
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  // Auto-collapse sidebar on mobile
  useEffect(() => { if (isMobile) setIsSidebarCollapsed(true); }, [isMobile]);

  // Mobile explorer overlay
  const [mobileExplorerOpen, setMobileExplorerOpen] = useState(false);

  const menuRef = useRef<HTMLDivElement>(null);
  const inlineInputRef = useRef<HTMLInputElement>(null);
  const saveRef = useRef<() => void>(() => {});
  const closeTabRef = useRef<(path: string) => void>(() => {});
  const selectedFileRef = useRef<string | null>(null);
  useEffect(() => { selectedFileRef.current = selectedFile; }, [selectedFile]);

  // Lazy-loaded content cache: path → server content (baseline for dirty tracking)
  const localContentRef = useRef<Map<string, string>>(new Map());

  // ── Language detection ─────────────────────────────────────────────

  const getLanguage = (fileName: string): string => {
    const ext = fileName.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'js': case 'jsx': return 'javascript';
      case 'ts': case 'tsx': return 'typescript';
      case 'html': return 'html';
      case 'css': case 'scss': case 'less': return 'css';
      case 'json': return 'json';
      case 'md': return 'markdown';
      case 'py': return 'python';
      case 'yml': case 'yaml': return 'yaml';
      case 'sh': case 'bash': return 'shell';
      case 'sql': return 'sql';
      case 'xml': case 'svg': return 'xml';
      default: return 'plaintext';
    }
  };

  // ── File icon (VS Code style — no gradients) ──────────────────────

  const getFileIcon = (fileName: string, size = 14) => {
    const ext = fileName.split('.').pop()?.toLowerCase();
    switch (ext) {
      case 'js': case 'jsx':
        return <Code size={size} className="text-yellow-500 shrink-0" />;
      case 'ts': case 'tsx':
        return <Code size={size} className="text-blue-400 shrink-0" />;
      case 'html':
        return <File size={size} className="text-orange-400 shrink-0" />;
      case 'css': case 'scss': case 'less':
        return <File size={size} className="text-blue-400 shrink-0" />;
      case 'json':
        return <File size={size} className="text-yellow-300 shrink-0" />;
      case 'md':
        return <File size={size} className="text-[var(--text-muted)] shrink-0" />;
      case 'py':
        return <Code size={size} className="text-green-400 shrink-0" />;
      case 'yml': case 'yaml':
        return <File size={size} className="text-red-400 shrink-0" />;
      case 'svg': case 'png': case 'jpg': case 'gif':
        return <File size={size} className="text-purple-400 shrink-0" />;
      default:
        return <File size={size} className="text-[var(--text-subtle)] shrink-0" />;
    }
  };

  // ── Editor mount + Ctrl+S binding ─────────────────────────────────

  const handleEditorDidMount = useCallback((editor: unknown) => {
    editorRef.current = editor;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const monacoEditor = editor as any;
    // Bind Ctrl+S / Cmd+S to save (uses ref to avoid stale closure)
    monacoEditor.addCommand(
      2048 | 49, // CtrlCmd = 2048, KeyS = 49
      () => { saveRef.current(); }
    );
    // Bind Ctrl+W / Cmd+W to close tab
    monacoEditor.addCommand(
      2048 | 53, // CtrlCmd = 2048, KeyW = 53
      () => { if (selectedFileRef.current) closeTabRef.current(selectedFileRef.current); }
    );
  }, []);

  // ── Save logic ────────────────────────────────────────────────────

  const saveCurrentFile = useCallback(() => {
    if (!selectedFile) return;
    const buffer = dirtyBuffers.get(selectedFile);
    if (buffer !== undefined) {
      onFileUpdate(selectedFile, buffer);
      // Update baseline so the buffer is now "clean"
      localContentRef.current.set(selectedFile, buffer);
      setDirtyBuffers(prev => {
        const next = new Map(prev);
        next.delete(selectedFile);
        return next;
      });
    }
  }, [selectedFile, dirtyBuffers, onFileUpdate]);

  // Keep ref current for Monaco command binding (avoids stale closure)
  useEffect(() => { saveRef.current = saveCurrentFile; }, [saveCurrentFile]);

  const saveAllFiles = useCallback(() => {
    dirtyBuffers.forEach((content, path) => {
      onFileUpdate(path, content);
      localContentRef.current.set(path, content);
    });
    setDirtyBuffers(new Map());
  }, [dirtyBuffers, onFileUpdate]);

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (e.shiftKey) {
          saveAllFiles();
        } else {
          saveCurrentFile();
        }
      }
      // Ctrl+W closes active tab
      if ((e.ctrlKey || e.metaKey) && e.key === 'w') {
        e.preventDefault();
        if (selectedFile) closeTabRef.current(selectedFile);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [saveCurrentFile, saveAllFiles, selectedFile]);

  // ── Editor change — buffer locally, don't save ────────────────────

  const handleEditorChange = (value: string | undefined) => {
    if (selectedFile && value !== undefined) {
      const original = localContentRef.current.get(selectedFile);
      if (value === original) {
        // Content matches saved version — mark clean
        setDirtyBuffers(prev => {
          const next = new Map(prev);
          next.delete(selectedFile);
          return next;
        });
      } else {
        setDirtyBuffers(prev => new Map(prev).set(selectedFile, value));
      }
    }
  };

  // Memoize file paths so the tree only rebuilds when paths change
  const filePathsKey = useMemo(() => fileTreeProp.map((f) => f.path).join('\0'), [fileTreeProp]);

  const isFileDirty = (path: string) => dirtyBuffers.has(path);

  // ── Tab management ────────────────────────────────────────────────

  const openFile = useCallback((path: string) => {
    setSelectedFile(path);
    setSelectedDir(null);
    setMobileExplorerOpen(false);
    setOpenTabs(prev => {
      if (prev.some(t => t.path === path)) return prev;
      const name = path.split('/').pop() || path;
      return [...prev, { path, name }];
    });
  }, []);

  const closeTab = useCallback((path: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    // If dirty, save before closing
    const buffer = dirtyBuffers.get(path);
    if (buffer !== undefined) {
      onFileUpdate(path, buffer);
      localContentRef.current.set(path, buffer);
      setDirtyBuffers(prev => {
        const next = new Map(prev);
        next.delete(path);
        return next;
      });
    }
    setOpenTabs(prev => {
      const next = prev.filter(t => t.path !== path);
      if (selectedFile === path) {
        const idx = prev.findIndex(t => t.path === path);
        const newSelected = next[Math.min(idx, next.length - 1)]?.path || null;
        setSelectedFile(newSelected);
      }
      return next;
    });
  }, [selectedFile, dirtyBuffers, onFileUpdate]);

  // Keep ref current for keyboard shortcut (avoids stale closure)
  useEffect(() => { closeTabRef.current = (p) => closeTab(p); }, [closeTab]);

  // ── Build file tree ───────────────────────────────────────────────

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
            if (parent && parent.children) parent.children.push(node);
          }
        }
        currentPath = fullPath;
      });
    });

    const sortNodes = (nodes: FileNode[]) => {
      nodes.sort((a, b) => {
        if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
        return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
      });
      nodes.forEach((n) => { if (n.children) sortNodes(n.children); });
    };
    sortNodes(tree);
    setFileTree(tree);

    // Auto-select the first actual file if none selected
    if (!selectedFile && sorted.length > 0) {
      const firstFile = sorted.find((e) => !e.is_dir);
      if (firstFile) {
        openFile(firstFile.path);
      }
    }
  }, [filePathsKey]); // eslint-disable-line react-hooks/exhaustive-deps

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

  // Invalidate content cache when files are updated externally (e.g. Save Config)
  useEffect(() => {
    const unsubscribe = fileEvents.on((detail) => {
      if (detail.type === 'file-updated' && detail.filePath) {
        localContentRef.current.delete(detail.filePath);
        // Re-fetch if this is the currently selected file
        if (selectedFileRef.current === detail.filePath) {
          setLoadingContent(true);
          projectsApi
            .getFileContent(slug, detail.filePath, containerDir)
            .then((res) => {
              localContentRef.current.set(detail.filePath!, res.content);
              setLoadingContent(false);
            })
            .catch(() => setLoadingContent(false));
        }
      }
    });
    return () => unsubscribe();
  }, [slug, containerDir]);

  // ── Directory toggle ──────────────────────────────────────────────

  const toggleDirectory = (path: string) => {
    setExpandedDirs((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(path)) newSet.delete(path);
      else newSet.add(path);
      return newSet;
    });
  };

  // ── Context menu ──────────────────────────────────────────────────

  const handleContextMenu = useCallback((e: React.MouseEvent, node: FileNode | null) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, node });
  }, []);

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  useEffect(() => {
    if (!contextMenu) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) closeContextMenu();
    };
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeContextMenu(); };
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
        const val = inlineInput.initialValue;
        const dotIdx = val.lastIndexOf('.');
        inlineInputRef.current.setSelectionRange(0, dotIdx > 0 ? dotIdx : val.length);
      } else {
        inlineInputRef.current.select();
      }
    }
  }, [inlineInput]);

  // ── Inline input submission ───────────────────────────────────────

  const handleInlineSubmit = useCallback(
    (value: string) => {
      if (!inlineInput) return;
      const current = inlineInput;
      setInlineInput(null);
      const trimmed = value.trim();
      if (!trimmed || trimmed.includes('/') || trimmed.includes('\\')) return;

      if (current.kind === 'rename' && current.originalPath) {
        const parentDir = current.originalPath.includes('/')
          ? current.originalPath.substring(0, current.originalPath.lastIndexOf('/'))
          : '';
        const newPath = parentDir ? `${parentDir}/${trimmed}` : trimmed;
        if (newPath !== current.originalPath) {
          onFileRename?.(current.originalPath, newPath);
          if (selectedFile === current.originalPath) setSelectedFile(newPath);
          else if (selectedFile?.startsWith(current.originalPath + '/'))
            setSelectedFile(newPath + selectedFile.substring(current.originalPath.length));
          // Update tab
          setOpenTabs(prev => prev.map(t =>
            t.path === current.originalPath ? { path: newPath, name: trimmed } :
            t.path.startsWith(current.originalPath! + '/') ? { ...t, path: newPath + t.path.substring(current.originalPath!.length) } : t
          ));
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

  // ── Context menu actions ──────────────────────────────────────────

  const startNewFile = useCallback((parentPath: string) => {
    closeContextMenu();
    if (parentPath) setExpandedDirs(prev => new Set([...prev, parentPath]));
    setInlineInput({ parentPath, kind: 'file' });
  }, [closeContextMenu]);

  const startNewFolder = useCallback((parentPath: string) => {
    closeContextMenu();
    if (parentPath) setExpandedDirs(prev => new Set([...prev, parentPath]));
    setInlineInput({ parentPath, kind: 'folder' });
  }, [closeContextMenu]);

  const startRename = useCallback((node: FileNode) => {
    closeContextMenu();
    const parentPath = node.path.includes('/')
      ? node.path.substring(0, node.path.lastIndexOf('/'))
      : '';
    setInlineInput({ parentPath, kind: 'rename', initialValue: node.name, originalPath: node.path });
  }, [closeContextMenu]);

  const confirmDelete = useCallback((node: FileNode) => {
    closeContextMenu();
    setDeleteConfirm(node);
  }, [closeContextMenu]);

  const executeDelete = useCallback(() => {
    if (!deleteConfirm) return;
    onFileDelete?.(deleteConfirm.path, deleteConfirm.isDirectory);
    if (selectedFile === deleteConfirm.path ||
        (deleteConfirm.isDirectory && selectedFile?.startsWith(deleteConfirm.path + '/'))) {
      setSelectedFile(null);
    }
    // Remove from tabs
    setOpenTabs(prev => prev.filter(t =>
      t.path !== deleteConfirm.path &&
      !(deleteConfirm.isDirectory && t.path.startsWith(deleteConfirm.path + '/'))
    ));
    // Clean dirty buffers
    setDirtyBuffers(prev => {
      const next = new Map(prev);
      next.delete(deleteConfirm.path);
      if (deleteConfirm.isDirectory) {
        for (const key of next.keys()) {
          if (key.startsWith(deleteConfirm.path + '/')) next.delete(key);
        }
      }
      return next;
    });
    setDeleteConfirm(null);
  }, [deleteConfirm, onFileDelete, selectedFile]);

  // ── Search filtering ──────────────────────────────────────────────

  const filterTree = useCallback((nodes: FileNode[], query: string): FileNode[] => {
    if (!query) return nodes;
    const lower = query.toLowerCase();
    return nodes.reduce<FileNode[]>((acc, node) => {
      if (node.isDirectory) {
        const filtered = filterTree(node.children || [], query);
        if (filtered.length > 0) {
          acc.push({ ...node, children: filtered });
        }
      } else if (node.name.toLowerCase().includes(lower)) {
        acc.push(node);
      }
      return acc;
    }, []);
  }, []);

  const displayTree = searchQuery ? filterTree(fileTree, searchQuery) : fileTree;

  // ── Render inline input row ───────────────────────────────────────

  const renderInlineInput = (depth: number) => {
    if (!inlineInput) return null;
    const icon = inlineInput.kind === 'folder'
      ? <Folder size={14} className="mr-1.5 text-[var(--text-muted)] shrink-0" />
      : inlineInput.kind === 'rename' ? null
      : <File size={14} className="mr-1.5 text-[var(--text-subtle)] shrink-0" />;

    return (
      <div className={`flex items-center ${isMobile ? 'h-9' : 'h-[22px]'} px-2`} style={{ paddingLeft: `${depth * 12 + 16}px` }}>
        {inlineInput.kind !== 'rename' && <div className="w-4 mr-1" />}
        {icon}
        <input
          ref={inlineInputRef}
          className="flex-1 text-xs bg-[var(--bg)] text-[var(--text)] border border-[var(--primary)] rounded-[var(--radius-small)] px-1.5 py-0.5 outline-none"
          defaultValue={inlineInput.initialValue || ''}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleInlineSubmit((e.target as HTMLInputElement).value);
            else if (e.key === 'Escape') setInlineInput(null);
          }}
          onBlur={(e) => handleInlineSubmit(e.target.value)}
        />
      </div>
    );
  };

  // ── Render file tree (VS Code style) ──────────────────────────────

  const renderFileTree = (nodes: FileNode[], depth = 0) => {
    const items: React.ReactNode[] = [];

    nodes.forEach((node) => {
      const isBeingRenamed = inlineInput?.kind === 'rename' && inlineInput.originalPath === node.path;
      const isActive = selectedFile === node.path;
      const isDirSelected = selectedDir === node.path;
      const isDirty = !node.isDirectory && isFileDirty(node.path);

      items.push(
        <div key={node.path} className="select-none">
          {isBeingRenamed ? (
            <div className={`flex items-center ${isMobile ? 'h-9' : 'h-[22px]'} px-2`} style={{ paddingLeft: `${depth * 12 + 16}px` }}>
              {node.isDirectory ? (
                <>
                  <ChevronRight size={12} className="mr-1 text-[var(--text-subtle)] shrink-0" />
                  <Folder size={14} className="mr-1.5 text-[var(--text-muted)] shrink-0" />
                </>
              ) : (
                <>
                  <div className="w-3 mr-1" />
                  {getFileIcon(node.name)}
                  <div className="mr-1.5" />
                </>
              )}
              <input
                ref={inlineInputRef}
                className="flex-1 text-xs bg-[var(--bg)] text-[var(--text)] border border-[var(--primary)] rounded-[var(--radius-small)] px-1.5 py-0.5 outline-none"
                defaultValue={inlineInput?.initialValue || ''}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleInlineSubmit((e.target as HTMLInputElement).value);
                  else if (e.key === 'Escape') setInlineInput(null);
                }}
                onBlur={(e) => handleInlineSubmit(e.target.value)}
              />
            </div>
          ) : (
            <div
              className={`flex items-center ${isMobile ? 'h-9' : 'h-[22px]'} px-2 cursor-pointer transition-colors ${
                isActive
                  ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                  : isDirSelected
                    ? 'bg-[var(--surface-hover)]/50 text-[var(--text)]'
                    : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]/50 hover:text-[var(--text)]'
              }`}
              style={{ paddingLeft: `${depth * 12 + 16}px` }}
              onClick={() => {
                if (node.isDirectory) {
                  toggleDirectory(node.path);
                  setSelectedDir(node.path);
                } else {
                  openFile(node.path);
                }
              }}
              onContextMenu={(e) => handleContextMenu(e, node)}
            >
              {node.isDirectory ? (
                <>
                  {expandedDirs.has(node.path) ? (
                    <ChevronDown size={12} className="mr-1 text-[var(--text-subtle)] shrink-0" />
                  ) : (
                    <ChevronRight size={12} className="mr-1 text-[var(--text-subtle)] shrink-0" />
                  )}
                  <Folder size={14} className="mr-1.5 text-[var(--text-muted)] shrink-0" />
                </>
              ) : (
                <>
                  <div className="w-3 mr-1" />
                  {getFileIcon(node.name)}
                  <div className="mr-1.5" />
                </>
              )}
              <span className="text-xs flex-1 truncate">{node.name}</span>
              {isDirty && (
                <span className="w-2 h-2 rounded-full bg-[var(--text-muted)] shrink-0 ml-1" />
              )}
            </div>
          )}

          {node.isDirectory && expandedDirs.has(node.path) && (
            <>
              {inlineInput && inlineInput.kind !== 'rename' &&
                inlineInput.parentPath === node.path && renderInlineInput(depth + 1)}
              {node.children && renderFileTree(node.children, depth + 1)}
            </>
          )}
        </div>
      );
    });

    return items;
  };

  // ── Get content for selected file (buffer or lazy-loaded) ─────────

  const getFileContent = (path: string): string | undefined => {
    const buffer = dirtyBuffers.get(path);
    if (buffer !== undefined) return buffer;
    return localContentRef.current.get(path);
  };

  const selectedFileContent = selectedFile ? getFileContent(selectedFile) : undefined;
  const dirtyCount = dirtyBuffers.size;

  // ── Determine target directory for toolbar new file/folder ────────

  const targetDir = selectedDir ||
    (selectedFile?.includes('/') ? selectedFile.substring(0, selectedFile.lastIndexOf('/')) : '') || '';

  return (
    <div className="h-full flex bg-[var(--bg)] overflow-hidden">
      {/* ── Mobile explorer overlay backdrop ──────────────────────── */}
      {isMobile && mobileExplorerOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40"
          onClick={() => setMobileExplorerOpen(false)}
        />
      )}

      {/* ── Explorer sidebar ───────────────────────────────────────── */}
      <div
        className={`bg-[var(--bg)] border-r border-[var(--border)] overflow-hidden flex flex-col transition-all duration-200 ${
          isMobile
            ? `fixed top-0 left-0 h-full z-50 w-64 ${mobileExplorerOpen ? 'translate-x-0' : '-translate-x-full'}`
            : isSidebarCollapsed ? 'w-0 border-0' : 'w-56'
        }`}
      >
        {/* Explorer header */}
        <div className={`${isMobile ? 'h-10' : 'h-8'} flex items-center justify-between px-3 shrink-0`}>
          <div className="flex items-center gap-2">
            {isMobile && (
              <button
                onClick={() => setMobileExplorerOpen(false)}
                className="p-1 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] text-[var(--text-subtle)]"
              >
                <X size={14} />
              </button>
            )}
            <span className="text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wider">Explorer</span>
          </div>
          <div className="flex items-center gap-0.5">
            <button
              onClick={() => setIsSearching(!isSearching)}
              className="p-0.5 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] text-[var(--text-subtle)] hover:text-[var(--text-muted)] transition-colors"
              title="Search files"
            >
              <Search size={13} />
            </button>
            {onFileCreate && (
              <button
                onClick={() => startNewFile(targetDir)}
                className="p-0.5 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] text-[var(--text-subtle)] hover:text-[var(--text-muted)] transition-colors"
                title="New File"
              >
                <FilePlus size={13} />
              </button>
            )}
            {onDirectoryCreate && (
              <button
                onClick={() => startNewFolder(targetDir)}
                className="p-0.5 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] text-[var(--text-subtle)] hover:text-[var(--text-muted)] transition-colors"
                title="New Folder"
              >
                <FolderPlus size={13} />
              </button>
            )}
          </div>
        </div>

        {/* Search input */}
        {isSearching && (
          <div className="px-2 pb-1.5 shrink-0">
            <input
              ref={searchInputRef}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search files..."
              className="w-full px-2 py-1 bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  setIsSearching(false);
                  setSearchQuery('');
                }
              }}
            />
          </div>
        )}

        {/* File tree */}
        <div
          className="flex-1 py-0.5 overflow-y-auto scrollbar-none"
          key={fileTreeProp.length}
          onClick={(e) => { if (e.target === e.currentTarget) setSelectedDir(null); }}
          onContextMenu={(e) => handleContextMenu(e, null)}
        >
          {displayTree.length > 0 ? (
            <>
              {inlineInput && inlineInput.kind !== 'rename' &&
                inlineInput.parentPath === '' && renderInlineInput(0)}
              {renderFileTree(displayTree)}
            </>
          ) : isFilesSyncing ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center px-4">
                <div className="w-5 h-5 mx-auto mb-2 border border-[var(--text-subtle)] border-t-[var(--text-muted)] rounded-full animate-spin" />
                <p className="text-xs text-[var(--text-muted)]">Syncing...</p>
              </div>
            </div>
          ) : searchQuery ? (
            <div className="px-4 py-6 text-center">
              <p className="text-xs text-[var(--text-subtle)]">No matching files</p>
            </div>
          ) : (
            <>
              {inlineInput && inlineInput.kind !== 'rename' &&
                inlineInput.parentPath === '' && renderInlineInput(0)}
              <div className="px-4 py-6 text-center">
                <Code size={20} className="mx-auto mb-2 text-[var(--text-subtle)]" />
                <p className="text-xs text-[var(--text-muted)]">No files yet</p>
                <p className="text-[10px] text-[var(--text-subtle)] mt-0.5">Files appear as you build</p>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Editor area ────────────────────────────────────────────── */}
      <div className="flex-1 bg-[var(--bg)] overflow-hidden flex flex-col min-w-0">
        {/* Tab bar */}
        <div className={`${isMobile ? 'h-[40px]' : 'h-[35px]'} bg-[var(--bg)] border-b border-[var(--border)] flex items-end shrink-0`}>
          {/* Sidebar toggle */}
          <button
            onClick={() => isMobile ? setMobileExplorerOpen(true) : setIsSidebarCollapsed(!isSidebarCollapsed)}
            className="h-full px-2 flex items-center text-[var(--text-subtle)] hover:text-[var(--text-muted)] transition-colors shrink-0"
            title={isSidebarCollapsed || isMobile ? 'Show explorer' : 'Hide explorer'}
          >
            {isSidebarCollapsed || isMobile ? <PanelLeft size={14} /> : <PanelLeftClose size={14} />}
          </button>

          {/* Tabs */}
          <div className="flex-1 flex items-end overflow-x-auto scrollbar-none min-w-0">
            {openTabs.map(tab => {
              const isActive = selectedFile === tab.path;
              const isDirty = isFileDirty(tab.path);
              return (
                <div
                  key={tab.path}
                  onClick={() => setSelectedFile(tab.path)}
                  className={`group flex items-center gap-1.5 ${isMobile ? 'h-[39px] px-3' : 'h-[34px] px-3'} cursor-pointer border-r border-[var(--border)] shrink-0 transition-colors ${
                    isActive
                      ? 'bg-[var(--surface)] text-[var(--text)] border-t border-t-[var(--primary)] border-b-0'
                      : 'bg-[var(--bg)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)]/50 border-t border-t-transparent'
                  }`}
                  style={{ maxWidth: isMobile ? 140 : 160 }}
                >
                  {getFileIcon(tab.name, 12)}
                  <span className="text-xs truncate">{tab.name}</span>
                  {isDirty && !isMobile && (
                    <span className="w-2 h-2 rounded-full bg-[var(--text-muted)] shrink-0 group-hover:hidden" />
                  )}
                  {isDirty && isMobile && (
                    <span className="w-2 h-2 rounded-full bg-[var(--text-muted)] shrink-0" />
                  )}
                  <button
                    onClick={(e) => closeTab(tab.path, e)}
                    className={`shrink-0 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] ${isMobile ? 'p-1' : 'p-0.5'} transition-colors ${
                      isMobile
                        ? '' // Always visible on mobile
                        : isDirty ? 'hidden group-hover:block' : 'invisible group-hover:visible'
                    }`}
                  >
                    <X size={isMobile ? 14 : 12} className="text-[var(--text-subtle)]" />
                  </button>
                </div>
              );
            })}
          </div>

          {/* Save indicator */}
          {dirtyCount > 0 && (
            <button
              onClick={saveAllFiles}
              className="h-full px-2 flex items-center gap-1 text-[var(--text-muted)] hover:text-[var(--text)] transition-colors shrink-0"
              title={`Save all (${dirtyCount} unsaved)`}
            >
              <span className="w-2 h-2 rounded-full bg-[var(--text-muted)]" />
              <span className="text-[10px]">{dirtyCount}</span>
            </button>
          )}
        </div>

        {/* Breadcrumb bar + save button */}
        {selectedFile && (
          <div className={`${isMobile ? 'h-[34px]' : 'h-[26px]'} bg-[var(--bg)] border-b border-[var(--border)] flex items-center px-3 shrink-0 gap-2`}>
            <span className={`${isMobile ? 'text-xs' : 'text-[11px]'} text-[var(--text-subtle)] truncate flex-1`}>{selectedFile}</span>
            {isFileDirty(selectedFile) && (
              <button
                onClick={saveCurrentFile}
                className={`btn flex items-center gap-1 shrink-0 ${isMobile ? 'btn-sm h-[24px] px-3 text-xs' : 'btn-sm h-[18px] px-2 text-[10px]'}`}
                title="Save (Ctrl+S)"
              >
                <Save size={isMobile ? 13 : 11} />
                Save
              </button>
            )}
          </div>
        )}

        {/* Editor content */}
        {selectedFile && selectedFileContent !== undefined ? (
          <div className="flex-1 overflow-hidden">
            <Editor
              key={selectedFile}
              height="100%"
              language={getLanguage(selectedFile)}
              defaultValue={selectedFileContent}
              onChange={handleEditorChange}
              onMount={handleEditorDidMount}
              theme={theme === 'dark' ? 'vs-dark' : 'vs'}
              options={{
                fontSize: isMobile ? 12 : 13,
                fontFamily: "'JetBrains Mono', 'Fira Code', 'Consolas', monospace",
                lineNumbers: isMobile ? 'off' : 'on',
                minimap: { enabled: !isMobile, maxColumn: 80 },
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 2,
                wordWrap: 'on',
                padding: { top: 8, bottom: 8 },
                smoothScrolling: true,
                cursorBlinking: 'smooth',
                cursorSmoothCaretAnimation: 'on',
                renderLineHighlight: 'line',
                bracketPairColorization: { enabled: true },
                guides: { bracketPairs: true, indentation: true },
                suggestOnTriggerCharacters: true,
                quickSuggestions: !isMobile,
                formatOnPaste: true,
                formatOnType: true,
                lineHeight: 20,
                renderWhitespace: 'selection',
                overviewRulerBorder: false,
                hideCursorInOverviewRuler: true,
                glyphMargin: !isMobile,
                folding: !isMobile,
                scrollbar: {
                  verticalScrollbarSize: isMobile ? 6 : 10,
                  horizontalScrollbarSize: isMobile ? 6 : 10,
                },
              }}
            />
          </div>
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
            <div className="text-center">
              <div className="w-6 h-6 mx-auto mb-3 border border-[var(--text-subtle)] border-t-[var(--text-muted)] rounded-full animate-spin" />
              <p className="text-xs text-[var(--text-muted)]">Syncing files...</p>
              <p className="text-[10px] text-[var(--text-subtle)] mt-1">Waiting for container</p>
            </div>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <Code size={24} className="mx-auto mb-3 text-[var(--text-subtle)]" />
              <p className="text-xs text-[var(--text-muted)]">
                {fileTreeProp.length > 0 ? 'Select a file to edit' : 'No files yet'}
              </p>
              <p className="text-[10px] text-[var(--text-subtle)] mt-1">
                {fileTreeProp.length > 0 ? 'Choose from the explorer' : 'Chat with your agent to generate code'}
              </p>
            </div>
          </div>
        )}

        {/* Status bar */}
        <div className="h-[22px] bg-[var(--surface)] border-t border-[var(--border)] flex items-center px-3 justify-between shrink-0">
          <div className="flex items-center gap-3">
            {selectedFile && (
              <>
                <span className="text-[10px] text-[var(--text-subtle)]">
                  {getLanguage(selectedFile).charAt(0).toUpperCase() + getLanguage(selectedFile).slice(1)}
                </span>
                {!isMobile && selectedFileContent !== undefined && (
                  <span className="text-[10px] text-[var(--text-subtle)]">
                    {selectedFileContent.split('\n').length} lines
                  </span>
                )}
              </>
            )}
          </div>
          <div className="flex items-center gap-3">
            {selectedFile && isFileDirty(selectedFile) && (
              <span className="text-[10px] text-[var(--text-muted)]">Modified</span>
            )}
            {!isMobile && <span className="text-[10px] text-[var(--text-subtle)]">UTF-8</span>}
            {!isMobile && <span className="text-[10px] text-[var(--text-subtle)]">Spaces: 2</span>}
          </div>
        </div>
      </div>

      {/* ── Context Menu ───────────────────────────────────────────── */}
      {contextMenu && (
        <div
          ref={menuRef}
          className="fixed z-50 min-w-[180px] py-1 bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] overflow-hidden"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            className="w-full px-3 py-1.5 text-left text-xs text-[var(--text)] hover:bg-[var(--surface-hover)] flex items-center gap-2 transition-colors"
            onClick={() => {
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
            <FilePlus size={13} className="text-[var(--text-subtle)]" />
            New File
          </button>
          <button
            className="w-full px-3 py-1.5 text-left text-xs text-[var(--text)] hover:bg-[var(--surface-hover)] flex items-center gap-2 transition-colors"
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
            <FolderPlus size={13} className="text-[var(--text-subtle)]" />
            New Folder
          </button>
          {contextMenu.node && (
            <>
              <div className="h-px bg-[var(--border)] my-0.5 mx-1.5" />
              <button
                className="w-full px-3 py-1.5 text-left text-xs text-[var(--text)] hover:bg-[var(--surface-hover)] flex items-center gap-2 transition-colors"
                onClick={() => startRename(contextMenu.node!)}
              >
                <Pencil size={13} className="text-[var(--text-subtle)]" />
                Rename
              </button>
              <button
                className="w-full px-3 py-1.5 text-left text-xs text-[var(--status-error)] hover:bg-[var(--status-error)]/10 flex items-center gap-2 transition-colors"
                onClick={() => confirmDelete(contextMenu.node!)}
              >
                <Trash2 size={13} />
                Delete
              </button>
            </>
          )}
        </div>
      )}

      {/* ── Delete Confirmation ─────────────────────────────────────── */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] p-5 max-w-sm w-full mx-4">
            <h3 className="text-xs font-semibold text-[var(--text)] mb-2">
              Delete {deleteConfirm.isDirectory ? 'Folder' : 'File'}
            </h3>
            <p className="text-xs text-[var(--text-muted)] mb-1">
              Are you sure you want to delete{' '}
              <span className="font-mono text-[var(--text)]">{deleteConfirm.name}</span>?
            </p>
            {deleteConfirm.isDirectory && (
              <p className="text-[10px] text-[var(--status-error)] mb-3">
                This will recursively delete the folder and all its contents.
              </p>
            )}
            {!deleteConfirm.isDirectory && <div className="mb-3" />}
            <div className="flex justify-end gap-2">
              <button className="btn btn-sm" onClick={() => setDeleteConfirm(null)}>
                Cancel
              </button>
              <button className="btn btn-sm btn-danger" onClick={executeDelete}>
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
