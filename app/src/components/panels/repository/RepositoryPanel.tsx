import { useEffect, useState } from 'react';
import {
  FilesIcon,
  GitBranch,
  GithubLogo,
  GraphIcon,
  Info,
} from '@phosphor-icons/react';
import { BranchesTab } from './BranchesTab';
import { FilesTab } from './FilesTab';
import { GraphTab } from './GraphTab';
import { OverviewTab } from './OverviewTab';
import { GitHubPanel } from '../GitHubPanel';

interface RepositoryPanelProps {
  projectSlug: string;
  projectId?: number;
}

type TabId = 'overview' | 'graph' | 'branches' | 'files' | 'github';

interface TabDef {
  id: TabId;
  label: string;
  short: string;
  icon: React.ReactNode;
}

const TABS: TabDef[] = [
  {
    id: 'github',
    label: 'GitHub',
    short: 'GitHub',
    icon: <GithubLogo size={12} weight="bold" />,
  },
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
  return 'github';
}

export function RepositoryPanel({ projectSlug, projectId }: RepositoryPanelProps) {
  const [active, setActive] = useState<TabId>(() => readInitialTab());

  useEffect(() => {
    try {
      localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, active);
    } catch {
      // Non-critical — if storage is blocked we just reset on reload.
    }
  }, [active]);

  return (
    <div className="w-full h-full flex flex-col bg-[var(--bg)] overflow-hidden">
      {/* Tabs */}
      <div
        className="flex-shrink-0 px-2 pt-2 border-b border-[var(--border)]"
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
        {active === 'files' && <FilesTab projectSlug={projectSlug} />}
        {active === 'github' &&
          (projectId !== undefined ? (
            <GitHubPanel projectId={projectId} />
          ) : (
            <div className="p-4 text-xs text-[var(--text-muted)]">
              GitHub sync requires a saved project.
            </div>
          ))}
      </div>
    </div>
  );
}

export default RepositoryPanel;
