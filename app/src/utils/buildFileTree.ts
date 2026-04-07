// ── Shared file tree utilities ──────────────────────────────────────
// Extracted from CodeEditor so both CodeEditor and DesignView FileTreePanel
// can share the same tree-building logic.

export interface FileNode {
  name: string;
  path: string;
  isDirectory: boolean;
  children?: FileNode[];
}

export interface FileTreeEntry {
  path: string;
  name: string;
  is_dir: boolean;
  size: number;
  mod_time: number;
}

/**
 * Build a hierarchical FileNode tree from a flat list of FileTreeEntry objects.
 * Directories are sorted before files; both are sorted alphabetically.
 */
export function buildFileTree(entries: FileTreeEntry[]): FileNode[] {
  const tree: FileNode[] = [];
  const pathMap = new Map<string, FileNode>();

  const sorted = [...entries]
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

  sortFileNodes(tree);
  return tree;
}

/** Sort directories before files, then alphabetically (case-insensitive). */
function sortFileNodes(nodes: FileNode[]) {
  nodes.sort((a, b) => {
    if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
  });
  nodes.forEach((n) => {
    if (n.children) sortFileNodes(n.children);
  });
}

/** Recursively filter a file tree by filename (case-insensitive). */
export function filterFileTree(nodes: FileNode[], query: string): FileNode[] {
  if (!query) return nodes;
  const lower = query.toLowerCase();
  return nodes.reduce<FileNode[]>((acc, node) => {
    if (node.isDirectory) {
      const filtered = filterFileTree(node.children || [], query);
      if (filtered.length > 0) {
        acc.push({ ...node, children: filtered });
      }
    } else if (node.name.toLowerCase().includes(lower)) {
      acc.push(node);
    }
    return acc;
  }, []);
}
