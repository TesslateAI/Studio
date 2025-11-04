import { useState } from 'react';
import { Folder, FolderOpen, Plus, Check, X } from '@phosphor-icons/react';

interface DirectoryTreeProps {
  directories: string[];
  selectedDirectory: string | null;
  onDirectorySelect: (directory: string) => void;
  onCreateDirectory: (path: string) => void;
  assetCounts?: Record<string, number>;  // Optional asset counts per directory
}

export default function DirectoryTree({
  directories,
  selectedDirectory,
  onDirectorySelect,
  onCreateDirectory,
  assetCounts = {},
}: DirectoryTreeProps) {
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set(['/']));
  const [isCreating, setIsCreating] = useState(false);
  const [newDirName, setNewDirName] = useState('');

  // Build tree structure from flat directory list
  const buildTree = () => {
    const tree: { [key: string]: any } = {};

    directories.forEach((dir) => {
      const parts = dir.split('/').filter(Boolean);
      let current = tree;

      parts.forEach((part, index) => {
        if (!current[part]) {
          current[part] = {
            name: part,
            fullPath: '/' + parts.slice(0, index + 1).join('/'),
            children: {},
          };
        }
        current = current[part].children;
      });
    });

    return tree;
  };

  const toggleExpand = (path: string) => {
    const newExpanded = new Set(expandedDirs);
    if (newExpanded.has(path)) {
      newExpanded.delete(path);
    } else {
      newExpanded.add(path);
    }
    setExpandedDirs(newExpanded);
  };

  const renderTree = (node: any, level: number = 0) => {
    return Object.keys(node).map((key) => {
      const item = node[key];
      const isExpanded = expandedDirs.has(item.fullPath);
      const isSelected = selectedDirectory === item.fullPath;
      const hasChildren = Object.keys(item.children).length > 0;
      const count = assetCounts[item.fullPath] || 0;

      return (
        <div key={item.fullPath}>
          <div
            className={`
              flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer
              hover:bg-white/5 transition-colors
              ${isSelected ? 'bg-orange-500/20 text-orange-400' : 'text-gray-300'}
            `}
            style={{ paddingLeft: `${level * 16 + 12}px` }}
            onClick={() => {
              onDirectorySelect(item.fullPath);
              if (hasChildren) {
                toggleExpand(item.fullPath);
              }
            }}
          >
            {hasChildren ? (
              isExpanded ? (
                <FolderOpen size={18} weight="fill" />
              ) : (
                <Folder size={18} weight="fill" />
              )
            ) : (
              <Folder size={18} weight="fill" />
            )}
            <span className="text-sm font-medium truncate flex-1">{item.name}</span>
            {count > 0 && (
              <span className="text-xs px-1.5 py-0.5 bg-white/10 text-gray-400 rounded">
                {count}
              </span>
            )}
          </div>
          {hasChildren && isExpanded && (
            <div>{renderTree(item.children, level + 1)}</div>
          )}
        </div>
      );
    });
  };

  const tree = buildTree();

  const handleCreateDirectory = () => {
    if (!newDirName.trim()) return;
    onCreateDirectory(newDirName.trim());
    setNewDirName('');
    setIsCreating(false);
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/10">
        <h3 className="text-sm font-semibold text-gray-300">Directories</h3>
        <button
          onClick={() => setIsCreating(true)}
          className="p-1 rounded hover:bg-white/10 transition-colors text-gray-400 hover:text-gray-200"
          title="Add directory"
        >
          <Plus size={18} weight="bold" />
        </button>
      </div>

      {/* Directory Tree */}
      <div className="flex-1 overflow-y-auto py-2">
        {/* Inline Directory Creation */}
        {isCreating && (
          <div className="px-3 mb-2">
            <div className="flex items-center gap-2 p-2 bg-white/5 border border-orange-500/50 rounded-lg">
              <Folder size={18} weight="fill" className="text-orange-500 flex-shrink-0" />
              <input
                type="text"
                value={newDirName}
                onChange={(e) => setNewDirName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreateDirectory();
                  if (e.key === 'Escape') {
                    setIsCreating(false);
                    setNewDirName('');
                  }
                }}
                placeholder="e.g., public/images"
                className="flex-1 bg-transparent border-none outline-none text-sm text-gray-200 placeholder-gray-500"
                autoFocus
              />
              <button
                onClick={handleCreateDirectory}
                className="p-1 hover:bg-white/10 rounded transition-colors text-green-500"
                title="Create"
              >
                <Check size={16} weight="bold" />
              </button>
              <button
                onClick={() => {
                  setIsCreating(false);
                  setNewDirName('');
                }}
                className="p-1 hover:bg-white/10 rounded transition-colors text-red-500"
                title="Cancel"
              >
                <X size={16} weight="bold" />
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-1 ml-2">
              Creating: <span className="text-orange-400">/{newDirName || '...'}</span>
            </p>
          </div>
        )}

        {directories.length === 0 && !isCreating ? (
          <div className="px-3 py-8 text-center text-gray-500 text-sm">
            <Folder size={32} weight="duotone" className="mx-auto mb-2 opacity-50" />
            <p>No directories yet</p>
            <p className="text-xs mt-1">Click + to add one</p>
          </div>
        ) : (
          <div>{renderTree(tree)}</div>
        )}
      </div>
    </div>
  );
}
