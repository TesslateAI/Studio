import { useEffect, useState } from 'react';
import {
  ArrowSquareOut,
  FilesIcon,
  GitBranch,
  GitCommit,
  GithubLogo,
  GraphIcon,
  HardDrives,
  Info,
} from '@phosphor-icons/react';
import { BranchesTab } from './BranchesTab';
import { FilesTab, type RepoMeta } from './FilesTab';
import { GraphTab } from './GraphTab';
import { OverviewTab } from './OverviewTab';

interface RepositoryPanelProps {
  projectSlug: string;
}

type TabId = 'overview' | 'graph' | 'branches' | 'files';

interface TabDef {
  id: TabId;
  label: string;
  short: string;
  icon: React.ReactNode;
}

const TABS: TabDef[] = [
  {
    id: 'overview',
    label: 'Overview',
    short: 'Overview',
    icon: <Info size={12} weight="bold" />,
  },
  {
    id: 'graph',
    label: 'Graph',
    short: 'Graph',
    icon: <GraphIcon size={12} weight="bold" />,
  },
  {
    id: 'branches',
    label: 'Branches',
    short: 'Branches',
    icon: <GitBranch size={12} weight="bold" />,
  },
  {
    id: 'files',
    label: 'Files',
    short: 'Files',
    icon: <FilesIcon size={12} weight="bold" />,
  },
];

const ACTIVE_TAB_STORAGE_KEY = 'tesslate.repositoryPanel.activeTab.v1';

function readInitialTab(): TabId {
  try {
    const raw = localStorage.getItem(ACTIVE_TAB_STORAGE_KEY);
    if (raw && (TABS as { id: string }[]).some((t) => t.id === raw)) {
      return raw as TabId;
    }
  } catch {
    // ignore — default below
  }
  return 'overview';
}

export function RepositoryPanel({ projectSlug }: RepositoryPanelProps) {
  const [active, setActive] = useState<TabId>(() => readInitialTab());
  const [meta, setMeta] = useState<RepoMeta | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, active);
    } catch {
      // Non-critical — if storage is blocked we just reset on reload.
    }
  }, [active]);

  return (
    <div className="w-full h-full flex flex-col bg-[var(--bg)] overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 p-2 pb-0">
        <div className="flex items-center gap-2 px-2 py-1.5">
          <span className="flex-shrink-0 text-[var(--text-muted)]">
            {meta?.source === 'github' ? (
              <GithubLogo size={15} weight="bold" />
            ) : (
              <HardDrives size={15} weight="bold" />
            )}
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="text-[12px] font-semibold text-[var(--text)] truncate">
                {meta?.source === 'github' && meta.owner && meta.repo
                  ? `${meta.owner}/${meta.repo}`
                  : 'Project files'}
              </span>
              {meta?.source === 'github' && meta.htmlUrl && (
                <a
                  href={meta.htmlUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--text-subtle)] hover:text-[var(--text)] transition-colors flex-shrink-0"
                  title="Open on GitHub"
                  aria-label="Open on GitHub"
                >
                  <ArrowSquareOut size={11} weight="bold" />
                </a>
              )}
            </div>
            {meta?.branch && (
              <div className="flex items-center gap-1 mt-0.5 text-[10px] text-[var(--text-muted)]">
                <GitCommit size={10} weight="bold" />
                <span className="truncate max-w-[140px]">{meta.branch}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div
        className="flex-shrink-0 px-2 pt-1 border-b border-[var(--border)]"
        role="tablist"
        aria-label="Repository views"
      >
        <div className="flex items-stretch gap-0.5 overflow-x-auto no-scrollbar">
          {TABS.map((tab) => {
            const isActive = tab.id === active;
            return (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={isActive}
                aria-controls={`repo-tab-${tab.id}`}
                id={`repo-tab-trigger-${tab.id}`}
                onClick={() => setActive(tab.id)}
                className={`relative flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-medium rounded-t-[var(--radius-small)] whitespace-nowrap transition-colors ${
                  isActive
                    ? 'text-[var(--text)] bg-[var(--surface-hover)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)]'
                }`}
              >
                <span aria-hidden="true">{tab.icon}</span>
                <span>{tab.short}</span>
                {isActive && (
                  <span
                    aria-hidden="true"
                    className="absolute left-1.5 right-1.5 bottom-[-1px] h-[2px] bg-[var(--primary)] rounded-t-full"
                  />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Body */}
      <div
        className="flex-1 min-h-0 overflow-auto"
        role="tabpanel"
        id={`repo-tab-${active}`}
        aria-labelledby={`repo-tab-trigger-${active}`}
      >
        {active === 'overview' && <OverviewTab projectSlug={projectSlug} />}
        {active === 'graph' && <GraphTab projectSlug={projectSlug} />}
        {active === 'branches' && <BranchesTab projectSlug={projectSlug} />}
        {active === 'files' && <FilesTab projectSlug={projectSlug} onMeta={setMeta} />}
      </div>
    </div>
  );
}

export default RepositoryPanel;
