import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  File,
  Folder,
  ChevronRight,
  ChevronDown,
  Code,
  FilePlus,
  FolderPlus,
  Pencil,
  Trash2,
  X,
  Search,
} from 'lucide-react';
import {
  buildFileTree as buildFileTreeUtil,
  filterFileTree as filterFileTreeUtil,
  type FileNode,
  type FileTreeEntry,
} from '../../../utils/buildFileTree';

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

interface FileTreePanelProps {
  fileTree: FileTreeEntry[];
  selectedFile: string | null;
  onFileSelect: (path: string) => void;
  onFileCreate?: (filePath: string) => void;
  onFileDelete?: (filePath: string, isDirectory: boolean) => void;
  onFileRename?: (oldPath: string, newPath: string) => void;
  onDirectoryCreate?: (dirPath: string) => void;
  isFilesSyncing?: boolean;
  slug: string;
  projectId: number;
}

// ── File icon (VS Code style — color-coded by extension) ────────────

function getFileIcon(fileName: string, size = 14) {
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
}

function FileTreePanel({
  fileTree: fileTreeProp = [],
  selectedFile,
  onFileSelect,
  onFileCreate,
  onFileDelete,
  onFileRename,
  onDirectoryCreate,
  isFilesSyncing,
  slug: _slug,
  projectId: _projectId,
}: FileTreePanelProps) {
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [selectedDir, setSelectedDir] = useState<string | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set(['']));

  // Context menu state
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [inlineInput, setInlineInput] = useState<InlineInputState | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<FileNode | null>(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const menuRef = useRef<HTMLDivElement>(null);
  const inlineInputRef = useRef<HTMLInputElement>(null);

  // Memoize file paths so the tree only rebuilds when paths change
  const filePathsKey = useMemo(
    () => fileTreeProp.map((f) => f.path).join('\0'),
    [fileTreeProp],
  );

  // ── Build file tree ───────────────────────────────────────────────

  useEffect(() => {
    const tree = buildFileTreeUtil(fileTreeProp);
    setFileTree(tree);
  }, [filePathsKey]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, node: FileNode | null) => {
      e.preventDefault();
      e.stopPropagation();
      setContextMenu({ x: e.clientX, y: e.clientY, node });
    },
    [],
  );

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  useEffect(() => {
    if (!contextMenu) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node))
        closeContextMenu();
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
        const val = inlineInput.initialValue;
        const dotIdx = val.lastIndexOf('.');
        inlineInputRef.current.setSelectionRange(
          0,
          dotIdx > 0 ? dotIdx : val.length,
        );
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
          ? current.originalPath.substring(
              0,
              current.originalPath.lastIndexOf('/'),
            )
          : '';
        const newPath = parentDir ? `${parentDir}/${trimmed}` : trimmed;
        if (newPath !== current.originalPath) {
          onFileRename?.(current.originalPath, newPath);
        }
      } else if (current.kind === 'file') {
        const fullPath = current.parentPath
          ? `${current.parentPath}/${trimmed}`
          : trimmed;
        onFileCreate?.(fullPath);
      } else if (current.kind === 'folder') {
        const fullPath = current.parentPath
          ? `${current.parentPath}/${trimmed}`
          : trimmed;
        onDirectoryCreate?.(fullPath);
      }
    },
    [inlineInput, onFileRename, onFileCreate, onDirectoryCreate],
  );

  // ── Context menu actions ──────────────────────────────────────────

  const startNewFile = useCallback(
    (parentPath: string) => {
      closeContextMenu();
      if (parentPath)
        setExpandedDirs((prev) => new Set([...prev, parentPath]));
      setInlineInput({ parentPath, kind: 'file' });
    },
    [closeContextMenu],
  );

  const startNewFolder = useCallback(
    (parentPath: string) => {
      closeContextMenu();
      if (parentPath)
        setExpandedDirs((prev) => new Set([...prev, parentPath]));
      setInlineInput({ parentPath, kind: 'folder' });
    },
    [closeContextMenu],
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
    [closeContextMenu],
  );

  const confirmDelete = useCallback(
    (node: FileNode) => {
      closeContextMenu();
      setDeleteConfirm(node);
    },
    [closeContextMenu],
  );

  const executeDelete = useCallback(() => {
    if (!deleteConfirm) return;
    onFileDelete?.(deleteConfirm.path, deleteConfirm.isDirectory);
    setDeleteConfirm(null);
  }, [deleteConfirm, onFileDelete]);

  // ── Search filtering ──────────────────────────────────────────────

  const displayTree = searchQuery
    ? filterFileTreeUtil(fileTree, searchQuery)
    : fileTree;

  // ── Determine target directory for toolbar new file/folder ────────

  const targetDir =
    selectedDir ||
    (selectedFile?.includes('/')
      ? selectedFile.substring(0, selectedFile.lastIndexOf('/'))
      : '') ||
    '';

  // ── Render inline input row ───────────────────────────────────────

  const renderInlineInput = (depth: number) => {
    if (!inlineInput) return null;
    const icon =
      inlineInput.kind === 'folder' ? (
        <Folder size={14} className="mr-1.5 text-[var(--text-muted)] shrink-0" />
      ) : inlineInput.kind === 'rename' ? null : (
        <File size={14} className="mr-1.5 text-[var(--text-subtle)] shrink-0" />
      );

    return (
      <div
        className="flex items-center h-[22px] px-2"
        style={{ paddingLeft: `${depth * 12 + 16}px` }}
      >
        {inlineInput.kind !== 'rename' && <div className="w-4 mr-1" />}
        {icon}
        <input
          ref={inlineInputRef}
          className="flex-1 text-xs bg-[var(--bg)] text-[var(--text)] border border-[var(--primary)] rounded-[var(--radius-small)] px-1.5 py-0.5 outline-none"
          defaultValue={inlineInput.initialValue || ''}
          onKeyDown={(e) => {
            if (e.key === 'Enter')
              handleInlineSubmit((e.target as HTMLInputElement).value);
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
      const isBeingRenamed =
        inlineInput?.kind === 'rename' &&
        inlineInput.originalPath === node.path;
      const isActive = selectedFile === node.path;
      const isDirSelected = selectedDir === node.path;

      items.push(
        <div key={node.path} className="select-none">
          {isBeingRenamed ? (
            <div
              className="flex items-center h-[22px] px-2"
              style={{ paddingLeft: `${depth * 12 + 16}px` }}
            >
              {node.isDirectory ? (
                <>
                  <ChevronRight
                    size={12}
                    className="mr-1 text-[var(--text-subtle)] shrink-0"
                  />
                  <Folder
                    size={14}
                    className="mr-1.5 text-[var(--text-muted)] shrink-0"
                  />
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
                  if (e.key === 'Enter')
                    handleInlineSubmit(
                      (e.target as HTMLInputElement).value,
                    );
                  else if (e.key === 'Escape') setInlineInput(null);
                }}
                onBlur={(e) => handleInlineSubmit(e.target.value)}
              />
            </div>
          ) : (
            <div
              className={`flex items-center h-[22px] px-2 cursor-pointer transition-colors ${
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
                  onFileSelect(node.path);
                }
              }}
              onContextMenu={(e) => handleContextMenu(e, node)}
            >
              {node.isDirectory ? (
                <>
                  {expandedDirs.has(node.path) ? (
                    <ChevronDown
                      size={12}
                      className="mr-1 text-[var(--text-subtle)] shrink-0"
                    />
                  ) : (
                    <ChevronRight
                      size={12}
                      className="mr-1 text-[var(--text-subtle)] shrink-0"
                    />
                  )}
                  <Folder
                    size={14}
                    className="mr-1.5 text-[var(--text-muted)] shrink-0"
                  />
                </>
              ) : (
                <>
                  <div className="w-3 mr-1" />
                  {getFileIcon(node.name)}
                  <div className="mr-1.5" />
                </>
              )}
              <span className="text-xs flex-1 truncate">{node.name}</span>
            </div>
          )}

          {node.isDirectory && expandedDirs.has(node.path) && (
            <>
              {inlineInput &&
                inlineInput.kind !== 'rename' &&
                inlineInput.parentPath === node.path &&
                renderInlineInput(depth + 1)}
              {node.children && renderFileTree(node.children, depth + 1)}
            </>
          )}
        </div>,
      );
    });

    return items;
  };

  return (
    <div className="h-full flex flex-col bg-[var(--bg)]">
      {/* ── Explorer header ─────────────────────────────────────────── */}
      <div className="h-8 flex items-center justify-between px-3 shrink-0">
        <span className="text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wider">
          Explorer
        </span>
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

      {/* ── Search input ────────────────────────────────────────────── */}
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

      {/* ── Syncing indicator ───────────────────────────────────────── */}
      {isFilesSyncing && (
        <div className="px-3 py-1 shrink-0">
          <span className="text-[10px] text-[var(--text-subtle)] animate-pulse">
            Syncing files...
          </span>
        </div>
      )}

      {/* ── File tree ───────────────────────────────────────────────── */}
      <div
        className="flex-1 overflow-y-auto overflow-x-hidden"
        onContextMenu={(e) => handleContextMenu(e, null)}
      >
        {/* Root-level inline input */}
        {inlineInput &&
          inlineInput.kind !== 'rename' &&
          inlineInput.parentPath === '' &&
          renderInlineInput(0)}
        {renderFileTree(displayTree)}
      </div>

      {/* ── Context menu (portal-style fixed position) ──────────────── */}
      {contextMenu && (
        <div
          ref={menuRef}
          className="fixed z-50 bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] py-1 shadow-lg min-w-[140px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            className="w-full text-left px-3 py-1.5 text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] flex items-center gap-2 transition-colors"
            onClick={() => {
              const parent = contextMenu.node?.isDirectory
                ? contextMenu.node.path
                : contextMenu.node?.path.includes('/')
                  ? contextMenu.node.path.substring(
                      0,
                      contextMenu.node.path.lastIndexOf('/'),
                    )
                  : '';
              startNewFile(parent);
            }}
          >
            <FilePlus size={13} />
            New File
          </button>
          <button
            className="w-full text-left px-3 py-1.5 text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] flex items-center gap-2 transition-colors"
            onClick={() => {
              const parent = contextMenu.node?.isDirectory
                ? contextMenu.node.path
                : contextMenu.node?.path.includes('/')
                  ? contextMenu.node.path.substring(
                      0,
                      contextMenu.node.path.lastIndexOf('/'),
                    )
                  : '';
              startNewFolder(parent);
            }}
          >
            <FolderPlus size={13} />
            New Folder
          </button>
          {contextMenu.node && (
            <>
              <div className="border-t border-[var(--border)] my-1" />
              <button
                className="w-full text-left px-3 py-1.5 text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] flex items-center gap-2 transition-colors"
                onClick={() => startRename(contextMenu.node!)}
              >
                <Pencil size={13} />
                Rename
              </button>
              <button
                className="w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-[var(--surface-hover)] hover:text-red-300 flex items-center gap-2 transition-colors"
                onClick={() => confirmDelete(contextMenu.node!)}
              >
                <Trash2 size={13} />
                Delete
              </button>
            </>
          )}
        </div>
      )}

      {/* ── Delete confirmation modal ───────────────────────────────── */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-4 max-w-sm w-full mx-4 shadow-xl">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-[var(--text)]">
                Delete {deleteConfirm.isDirectory ? 'Folder' : 'File'}
              </h3>
              <button
                onClick={() => setDeleteConfirm(null)}
                className="p-0.5 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] text-[var(--text-subtle)]"
              >
                <X size={14} />
              </button>
            </div>
            <p className="text-xs text-[var(--text-muted)] mb-1">
              Are you sure you want to delete{' '}
              <span className="font-medium text-[var(--text)]">
                {deleteConfirm.name}
              </span>
              ?
            </p>
            {deleteConfirm.isDirectory && (
              <p className="text-xs text-red-400 mb-3">
                This will recursively delete all files and folders inside.
              </p>
            )}
            {!deleteConfirm.isDirectory && <div className="mb-3" />}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-3 py-1.5 text-xs rounded-[var(--radius-small)] border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={executeDelete}
                className="px-3 py-1.5 text-xs rounded-[var(--radius-small)] bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 transition-colors"
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

export default FileTreePanel;
