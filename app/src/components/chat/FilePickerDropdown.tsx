import { useState, useEffect, useRef, useCallback } from 'react';
import { projectsApi } from '../../lib/api';

interface FilePickerDropdownProps {
  slug: string;
  query: string;
  onSelect: (filePath: string, fileName: string) => void;
  onClose: () => void;
}

interface FileEntry {
  path: string;
  is_dir: boolean;
}

export function FilePickerDropdown({ slug, query, onSelect, onClose }: FilePickerDropdownProps) {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const filesCache = useRef<FileEntry[] | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Fetch file tree once
  useEffect(() => {
    if (filesCache.current) {
      setFiles(filesCache.current);
      return;
    }
    let cancelled = false;
    projectsApi.getFileTree(slug).then((tree) => {
      if (cancelled) return;
      const fileEntries = tree.filter((e: FileEntry) => !e.is_dir);
      filesCache.current = fileEntries;
      setFiles(fileEntries);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [slug]);

  // Filter files by query
  const filtered = files
    .filter((f) => {
      if (!query) return true;
      const lower = query.toLowerCase();
      return f.path.toLowerCase().includes(lower);
    })
    .slice(0, 8);

  // Reset selection when query changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Keyboard navigation
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => Math.min(prev + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => Math.max(prev - 1, 0));
    } else if (e.key === 'Enter' && filtered.length > 0) {
      e.preventDefault();
      const selected = filtered[selectedIndex];
      if (selected) {
        const parts = selected.path.split('/');
        onSelect(selected.path, parts[parts.length - 1]);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  }, [filtered, selectedIndex, onSelect, onClose]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown, true);
    return () => window.removeEventListener('keydown', handleKeyDown, true);
  }, [handleKeyDown]);

  // Close on click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClick, true);
    return () => document.removeEventListener('mousedown', handleClick, true);
  }, [onClose]);

  if (filtered.length === 0 && files.length > 0) {
    return (
      <div ref={containerRef} className="absolute bottom-full left-0 right-0 mb-2 px-3">
        <div className="bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-3 shadow-lg">
          <p className="text-xs text-[var(--text-muted)]">No files matching &ldquo;{query}&rdquo;</p>
        </div>
      </div>
    );
  }

  if (filtered.length === 0) return null;

  return (
    <div ref={containerRef} className="absolute bottom-full left-0 right-0 mb-2 px-3 z-10">
      <div className="bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-1.5 shadow-lg max-h-64 overflow-y-auto">
        {filtered.map((file, idx) => {
          const parts = file.path.split('/');
          const fileName = parts[parts.length - 1];
          const dirPath = parts.slice(0, -1).join('/');
          return (
            <div
              key={file.path}
              onClick={() => onSelect(file.path, fileName)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-[var(--radius-small)] cursor-pointer transition-colors ${
                idx === selectedIndex
                  ? 'bg-[var(--primary)]/10 text-[var(--primary)]'
                  : 'hover:bg-[var(--surface-hover)]'
              }`}
            >
              <svg className="w-3.5 h-3.5 flex-shrink-0 opacity-50" fill="currentColor" viewBox="0 0 256 256">
                <path d="M213.66,82.34l-56-56A8,8,0,0,0,152,24H56A16,16,0,0,0,40,40V216a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V88A8,8,0,0,0,213.66,82.34ZM160,51.31,188.69,80H160ZM200,216H56V40h88V88a8,8,0,0,0,8,8h48V216Z" />
              </svg>
              <span className="text-xs truncate min-w-0">
                {dirPath && (
                  <span className="text-[var(--text-muted)]">{dirPath}/</span>
                )}
                <span className="font-medium text-[var(--text)]">{fileName}</span>
              </span>
            </div>
          );
        })}
        <div className="mt-1 pt-1.5 border-t border-[var(--border)]">
          <span className="text-[10px] text-[var(--text)]/40 px-3">↑↓ to navigate, Enter to select</span>
        </div>
      </div>
    </div>
  );
}
