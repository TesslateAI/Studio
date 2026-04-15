import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Editor from '@monaco-editor/react';
import { File, Folder, ArrowLeft } from '@phosphor-icons/react';
import { useApps } from '../contexts/AppsContext';
import { marketplaceAppsApi, type MarketplaceApp } from '../lib/api';

/**
 * AppSourceBrowserPage — /apps/:appId/source
 *
 * View app source code if visibility allows:
 *   - public    → any authenticated user
 *   - installers → only users who have installed the app
 *   - private   → denied
 */

interface SourceFileNode {
  path: string;
  name: string;
  kind: 'file' | 'dir';
  children?: SourceFileNode[];
  content?: string;
}

// TODO(app-source): Replace this mock with a real backend endpoint such as
// `GET /api/marketplace-apps/:appId/source` returning {tree, files}. The
// endpoint should enforce visibility + installer checks server-side.
const MOCK_TREE: SourceFileNode[] = [
  {
    path: '/',
    name: 'root',
    kind: 'dir',
    children: [
      {
        path: '/manifest.json',
        name: 'manifest.json',
        kind: 'file',
        content: '{\n  "name": "example-app",\n  "version": "0.1.0"\n}\n',
      },
      {
        path: '/src',
        name: 'src',
        kind: 'dir',
        children: [
          {
            path: '/src/index.ts',
            name: 'index.ts',
            kind: 'file',
            content: "// entrypoint\nexport function main() {\n  return 'hello';\n}\n",
          },
        ],
      },
    ],
  },
];

function flattenFiles(tree: SourceFileNode[]): Record<string, string> {
  const map: Record<string, string> = {};
  const walk = (n: SourceFileNode) => {
    if (n.kind === 'file' && n.content !== undefined) map[n.path] = n.content;
    n.children?.forEach(walk);
  };
  tree.forEach(walk);
  return map;
}

function languageFor(path: string): string {
  if (path.endsWith('.ts') || path.endsWith('.tsx')) return 'typescript';
  if (path.endsWith('.js') || path.endsWith('.jsx')) return 'javascript';
  if (path.endsWith('.json')) return 'json';
  if (path.endsWith('.md')) return 'markdown';
  if (path.endsWith('.css')) return 'css';
  if (path.endsWith('.html')) return 'html';
  return 'plaintext';
}

function TreeView({
  nodes,
  onSelect,
  selected,
  depth = 0,
}: {
  nodes: SourceFileNode[];
  onSelect: (n: SourceFileNode) => void;
  selected: string | null;
  depth?: number;
}) {
  return (
    <ul className="space-y-0.5">
      {nodes.map((n) => (
        <li key={n.path}>
          {n.kind === 'dir' ? (
            <>
              <div
                className="flex items-center gap-1.5 text-xs text-[var(--muted)] py-1"
                style={{ paddingLeft: depth * 12 }}
              >
                <Folder className="w-3.5 h-3.5" />
                <span>{n.name}</span>
              </div>
              {n.children && (
                <TreeView
                  nodes={n.children}
                  onSelect={onSelect}
                  selected={selected}
                  depth={depth + 1}
                />
              )}
            </>
          ) : (
            <button
              onClick={() => onSelect(n)}
              className={`w-full flex items-center gap-1.5 text-xs py-1 rounded hover:bg-white/5 transition ${
                selected === n.path ? 'bg-white/10 text-[var(--text)]' : 'text-[var(--muted)]'
              }`}
              style={{ paddingLeft: depth * 12 + 4 }}
            >
              <File className="w-3.5 h-3.5" />
              <span>{n.name}</span>
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function AppSourceBrowserPage() {
  const { appId } = useParams<{ appId: string }>();
  const navigate = useNavigate();
  const { myInstalls } = useApps();

  const [app, setApp] = useState<MarketplaceApp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  useEffect(() => {
    if (!appId) return;
    let cancelled = false;
    (async () => {
      try {
        const a = await marketplaceAppsApi.get(appId);
        if (!cancelled) setApp(a);
      } catch {
        if (!cancelled) setError('Failed to load app');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [appId]);

  const canView = useMemo(() => {
    if (!app) return false;
    if (app.visibility === 'public') return true;
    if (app.visibility === 'private') return false;
    if (app.visibility === 'installers') {
      return myInstalls.some(
        (i) => i.app_id === app.id && i.state !== 'uninstalled'
      );
    }
    return false;
  }, [app, myInstalls]);

  // TODO(app-source): fetch real tree here once backend is available.
  const tree = MOCK_TREE;
  const files = useMemo(() => flattenFiles(tree), [tree]);
  const selectedContent = selectedPath ? files[selectedPath] : null;

  if (error) {
    return (
      <div className="p-8 text-sm text-red-400" data-testid="source-error">
        {error}
      </div>
    );
  }
  if (!app) {
    return (
      <div className="p-8 text-sm text-[var(--muted)]" data-testid="source-loading">
        Loading…
      </div>
    );
  }

  if (!canView) {
    return (
      <div
        className="flex flex-col items-center justify-center min-h-[60vh] px-6 text-center"
        data-testid="source-denied"
      >
        <h1 className="font-heading text-2xl font-semibold text-[var(--text)] mb-2">
          Source is private
        </h1>
        <p className="text-sm text-[var(--muted)] max-w-md">
          The author of <strong>{app.name}</strong> has not made this app's source code available
          {app.visibility === 'installers' ? ' to non-installers.' : '.'}
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0" data-testid="source-browser-page">
      <aside className="w-64 border-r border-[var(--border)] bg-[var(--surface)] p-3 overflow-auto">
        <div className="flex items-center gap-2 mb-3">
          <button
            onClick={() => navigate(-1)}
            className="p-1 rounded-md hover:bg-white/5 text-[var(--muted)]"
            aria-label="Back"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="font-heading text-sm font-semibold truncate">{app.name}</div>
        </div>
        <TreeView nodes={tree[0]?.children ?? []} onSelect={(n) => setSelectedPath(n.path)} selected={selectedPath} />
      </aside>
      <section className="flex-1 min-w-0 min-h-0 flex flex-col">
        {selectedPath ? (
          <>
            <div className="px-4 py-2 border-b border-[var(--border)] text-xs text-[var(--muted)] font-mono">
              {selectedPath}
            </div>
            <div className="flex-1 min-h-0">
              <Editor
                value={selectedContent ?? ''}
                language={languageFor(selectedPath)}
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 13,
                  scrollBeyondLastLine: false,
                }}
                theme="vs-dark"
              />
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-[var(--muted)]">
            Select a file to view its source.
          </div>
        )}
      </section>
    </div>
  );
}
