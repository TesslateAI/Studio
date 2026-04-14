import { useState, useEffect, useMemo, useCallback, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { AnimatePresence, motion } from 'framer-motion';
import { FolderPlus, GitBranch, Storefront, Folder, FolderOpen, ArrowRight } from '@phosphor-icons/react';
import { TesslateLogo } from '../components/ui/TesslateLogo';
import { MoodyFace } from '../components/ui/MoodyFace';
import { CreateProjectModal, RepoImportModal } from '../components/modals';
import { projectsApi, tasksApi } from '../lib/api';
import { useTeam } from '../contexts/TeamContext';

type RecentProject = {
  id: string;
  name: string;
  slug: string;
  updatedAt: string;
};

// Relative time helper — "2h ago", "3d ago", etc.
// Uses Intl.RelativeTimeFormat so it respects the browser locale.
const RELATIVE_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ['year', 60 * 60 * 24 * 365],
  ['month', 60 * 60 * 24 * 30],
  ['week', 60 * 60 * 24 * 7],
  ['day', 60 * 60 * 24],
  ['hour', 60 * 60],
  ['minute', 60],
  ['second', 1],
];

function formatRelativeTime(iso: string): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const deltaSec = Math.round((then - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto', style: 'short' });
  for (const [unit, secondsInUnit] of RELATIVE_UNITS) {
    if (Math.abs(deltaSec) >= secondsInUnit || unit === 'second') {
      const value = Math.round(deltaSec / secondsInUnit);
      return formatter.format(value, unit);
    }
  }
  return '';
}

interface ActionCardProps {
  icon: ReactNode;
  title: string;
  tooltip: string;
  onClick?: () => void;
  disabled?: boolean;
  badge?: string;
}

function ActionCard({ icon, title, tooltip, onClick, disabled, badge }: ActionCardProps) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const showTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [visible, setVisible] = useState(false);
  const [tipPos, setTipPos] = useState({ top: 0, left: 0 });

  const computePosition = () => {
    if (!buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    setTipPos({ top: rect.top - 10, left: rect.left + rect.width / 2 });
  };

  const handleEnter = () => {
    if (showTimerRef.current) clearTimeout(showTimerRef.current);
    showTimerRef.current = setTimeout(() => {
      computePosition();
      setVisible(true);
    }, 250);
  };

  const handleLeave = () => {
    if (showTimerRef.current) {
      clearTimeout(showTimerRef.current);
      showTimerRef.current = null;
    }
    setVisible(false);
  };

  useEffect(() => {
    return () => {
      if (showTimerRef.current) clearTimeout(showTimerRef.current);
    };
  }, []);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={disabled ? undefined : onClick}
        onMouseEnter={handleEnter}
        onMouseLeave={handleLeave}
        onFocus={() => {
          computePosition();
          setVisible(true);
        }}
        onBlur={handleLeave}
        disabled={disabled}
        aria-disabled={disabled || undefined}
        aria-label={`${title} — ${tooltip}`}
        className={[
          'group relative flex h-full w-full min-h-[84px] sm:min-h-[92px] flex-col items-start justify-between gap-2',
          'rounded-[var(--radius)] border px-3 py-3 sm:px-3.5 sm:py-3.5 text-left',
          'motion-safe:transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2',
          'focus-visible:ring-offset-[var(--bg)]',
          disabled
            ? 'cursor-not-allowed border-[var(--border)] bg-[var(--surface)] opacity-60'
            : 'cursor-pointer border-[var(--border)] bg-[var(--surface)] hover:bg-[var(--surface-hover)] hover:border-[var(--border-hover)]',
        ].join(' ')}
      >
        {badge && (
          <span className="absolute right-2.5 top-2.5 rounded-full bg-[var(--bg)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
            {badge}
          </span>
        )}
        <div
          className={[
            'flex h-7 w-7 items-center justify-center',
            disabled
              ? 'text-[var(--text-subtle)]'
              : 'text-[var(--text-muted)] group-hover:text-[var(--primary)] motion-safe:transition-colors',
          ].join(' ')}
        >
          {icon}
        </div>
        <span className="text-sm font-semibold text-[var(--text)]">{title}</span>
      </button>
      {createPortal(
        <AnimatePresence>
          {visible && (
            <motion.div
              role="tooltip"
              initial={{ opacity: 0, y: 4, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96 }}
              transition={{ type: 'spring', stiffness: 600, damping: 25, mass: 0.4 }}
              className="pointer-events-none fixed z-[9999]"
              style={{
                top: `${tipPos.top}px`,
                left: `${tipPos.left}px`,
                transform: 'translate(-50%, -100%)',
              }}
            >
              <div className="relative max-w-[240px] rounded-md border border-[var(--border-hover)] bg-black px-2.5 py-1.5 text-center shadow-[var(--shadow-large)]">
                <span className="text-[11px] font-medium leading-snug text-white">{tooltip}</span>
                <span
                  aria-hidden="true"
                  className="absolute left-1/2 top-full h-0 w-0 -translate-x-1/2 border-l-[5px] border-r-[5px] border-t-[5px] border-l-transparent border-r-transparent border-t-black"
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </>
  );
}

// Monochrome brand logos from Simple Icons CDN. `filter: invert(1)` turns the
// default black SVG into pure white so every logo reads consistently on the
// dark sidebar surface regardless of theme preset.
const CONNECTORS: Array<{ name: string; slug: string }> = [
  { name: 'Linear', slug: 'linear' },
  { name: 'Slack', slug: 'slack' },
  { name: 'GitHub', slug: 'github' },
  { name: 'Salesforce', slug: 'salesforce' },
  { name: 'Sentry', slug: 'sentry' },
];

interface ConnectorsCardProps {
  onClick: () => void;
}

function ConnectorsCard({ onClick }: ConnectorsCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Connect your connectors — Linear, Slack, GitHub, Salesforce, Sentry and more"
      title="Hook your workspace up to Linear, Slack, GitHub, Salesforce, Sentry and more via MCP."
      className="group relative col-span-2 flex w-full min-h-[72px] items-center gap-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-3.5 py-3 text-left motion-safe:transition-colors hover:border-[var(--border-hover)] hover:bg-[var(--surface-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)] sm:gap-4 sm:px-4"
    >
      {/* Logo row */}
      <div className="flex flex-shrink-0 items-center -space-x-1.5">
        {CONNECTORS.map((c, i) => {
          const url = `https://cdn.simpleicons.org/${c.slug}`;
          return (
            <span
              key={c.slug}
              className="flex h-7 w-7 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--bg)] motion-safe:transition-transform group-hover:scale-[1.03]"
              style={{ zIndex: CONNECTORS.length - i }}
              aria-hidden="true"
            >
              {/* Mask-image technique: the SVG becomes a silhouette colored by
                  background-color, so logos inherit --text-muted and match
                  every other icon on the page across theme presets. */}
              <span
                className="block h-3.5 w-3.5 bg-[var(--text-muted)] group-hover:bg-[var(--text)] motion-safe:transition-colors"
                style={{
                  maskImage: `url(${url})`,
                  WebkitMaskImage: `url(${url})`,
                  maskRepeat: 'no-repeat',
                  WebkitMaskRepeat: 'no-repeat',
                  maskSize: 'contain',
                  WebkitMaskSize: 'contain',
                  maskPosition: 'center',
                  WebkitMaskPosition: 'center',
                }}
              />
            </span>
          );
        })}
      </div>

      {/* Text block */}
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="text-sm font-semibold text-[var(--text)]">
          Connect your connectors
        </span>
        <span className="truncate text-[11px] text-[var(--text-muted)]">
          {CONNECTORS.map((c) => c.name).join(' · ')}
        </span>
      </div>

      <ArrowRight
        size={16}
        className="flex-shrink-0 text-[var(--text-muted)] motion-safe:transition-transform group-hover:translate-x-0.5 group-hover:text-[var(--text)]"
      />
    </button>
  );
}

export default function Home() {
  const navigate = useNavigate();
  const { activeTeam, teamSwitchKey } = useTeam();

  const [recent, setRecent] = useState<RecentProject[]>([]);
  const [recentLoading, setRecentLoading] = useState(true);

  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [showImportDialog, setShowImportDialog] = useState(false);
  const [isCreating, setIsCreating] = useState(false);

  // Subscription / plan line — mirrors NavigationSidebar.tsx:133-135
  const subscriptionTier = activeTeam?.subscription_tier || 'free';
  const tierLabel = useMemo(
    () => subscriptionTier.charAt(0).toUpperCase() + subscriptionTier.slice(1),
    [subscriptionTier]
  );
  const isPaidPlan = subscriptionTier !== 'free';

  // Load recent projects — mirror NavigationSidebar.tsx:231-268 fetch pattern
  useEffect(() => {
    let cancelled = false;
    setRecentLoading(true);
    projectsApi
      .getAll(activeTeam?.slug)
      .then((data: unknown) => {
        if (cancelled) return;
        const list = (Array.isArray(data) ? data : []) as Array<Record<string, unknown>>;
        const mapped: RecentProject[] = list
          .map((p) => ({
            id: (p.id as string) || '',
            name: (p.name as string) || 'Untitled workspace',
            slug: (p.slug as string) || '',
            updatedAt:
              (p.updated_at as string) || (p.created_at as string) || new Date(0).toISOString(),
          }))
          .filter((p) => p.slug)
          .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
          .slice(0, 5);
        setRecent(mapped);
      })
      .catch(() => {
        if (!cancelled) setRecent([]);
      })
      .finally(() => {
        if (!cancelled) setRecentLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTeam?.slug, teamSwitchKey]);

  // Create-project handler — same flow as Dashboard.handleCreateProject.
  // Duplicated intentionally to keep blast radius to this file (see plan).
  const handleCreateProject = useCallback(
    async (projectName: string, baseId?: string, baseVersion?: string) => {
      if (isCreating) return;
      setIsCreating(true);
      const creatingToast = toast.loading('Creating workspace...');
      try {
        const response = await projectsApi.create(
          projectName,
          '',
          'base',
          undefined,
          'main',
          baseId,
          baseVersion || undefined
        );
        const project = response.project;
        const taskId = response.task_id;
        if (taskId) {
          toast.loading('Setting up workspace...', { id: creatingToast });
          try {
            await tasksApi.pollUntilComplete(taskId);
            toast.success('Workspace created!', { id: creatingToast, duration: 2000 });
            setShowCreateDialog(false);
            setIsCreating(false);
            navigate(`/project/${project.slug}/setup`);
          } catch (taskError) {
            const taskErrMsg = taskError instanceof Error ? taskError.message : 'Setup failed';
            toast.error(taskErrMsg, { id: creatingToast });
            setIsCreating(false);
            navigate(`/project/${project.slug}`);
          }
        } else {
          toast.success('Workspace created!', { id: creatingToast, duration: 2000 });
          setShowCreateDialog(false);
          setIsCreating(false);
          navigate(`/project/${project.slug}/setup`);
        }
      } catch (error: unknown) {
        const err = error as { response?: { data?: { detail?: string } } };
        const detail = err?.response?.data?.detail;
        const errorMessage = typeof detail === 'string' ? detail : 'Failed to create workspace';
        toast.error(errorMessage, { id: creatingToast });
        setIsCreating(false);
      }
    },
    [isCreating, navigate]
  );

  // Clone-repo handler — mirror Dashboard.tsx:1298-… onCreateProject.
  const handleImportRepo = useCallback(
    async (provider: string, repoUrl: string, branch: string, projectName: string) => {
      if (isCreating) return;
      setIsCreating(true);
      const creatingToast = toast.loading(`Importing from ${provider}...`);
      try {
        const response = await projectsApi.create(
          projectName,
          '',
          provider as 'github' | 'gitlab' | 'bitbucket',
          repoUrl,
          branch,
          undefined
        );
        const project = response.project;
        const taskId = response.task_id;
        if (taskId) {
          toast.loading('Setting up workspace...', { id: creatingToast });
          try {
            await tasksApi.pollUntilComplete(taskId);
            toast.success('Workspace imported!', { id: creatingToast, duration: 2000 });
            setShowImportDialog(false);
            setIsCreating(false);
            navigate(`/project/${project.slug}/setup`);
          } catch (taskError) {
            const taskErrMsg = taskError instanceof Error ? taskError.message : 'Import failed';
            toast.error(taskErrMsg, { id: creatingToast });
            setIsCreating(false);
            navigate(`/project/${project.slug}`);
          }
        } else {
          toast.success('Workspace imported!', { id: creatingToast, duration: 2000 });
          setShowImportDialog(false);
          setIsCreating(false);
          navigate(`/project/${project.slug}/setup`);
        }
      } catch (error: unknown) {
        const err = error as { response?: { data?: { detail?: string } } };
        const detail = err?.response?.data?.detail;
        const errorMessage = typeof detail === 'string' ? detail : 'Failed to import workspace';
        toast.error(errorMessage, { id: creatingToast });
        setIsCreating(false);
      }
    },
    [isCreating, navigate]
  );

  const handleUpgrade = () => navigate('/settings/team/billing');
  const handleOpenProject = (slug: string) => navigate(`/project/${slug}`);

  return (
    <div className="h-full w-full overflow-y-auto">
      <div className="flex min-h-full items-center justify-center">
        <div className="flex w-full max-w-[560px] flex-col gap-6 px-4 py-8 sm:px-6 sm:py-12 lg:px-8 lg:py-16">
        {/* Logo + title + plan line */}
        <header className="flex flex-col items-center gap-2 text-center">
          <TesslateLogo
            width={56}
            height={44}
            className="text-[var(--primary)] sm:h-[52px] sm:w-[64px]"
          />
          <h1 className="text-xl font-semibold tracking-tight text-[var(--text)] sm:text-2xl">
            Tesslate Studio
          </h1>
          <p className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] sm:text-sm">
            <span>{tierLabel} Plan</span>
            {!isPaidPlan && (
              <>
                <span aria-hidden="true">·</span>
                <button
                  type="button"
                  onClick={handleUpgrade}
                  className="text-[var(--primary)] hover:underline focus-visible:outline-none focus-visible:underline"
                >
                  Upgrade
                </button>
              </>
            )}
          </p>
        </header>

        {/* Action grid — 2x2 */}
        <div className="grid grid-cols-2 gap-2 sm:gap-2.5">
          <ActionCard
            icon={<FolderPlus size={20} weight="duotone" />}
            title="New Project"
            tooltip="Create a fresh workspace — name it, pick a template, and start building."
            onClick={() => setShowCreateDialog(true)}
          />
          <ActionCard
            icon={<GitBranch size={20} weight="duotone" />}
            title="Clone Repo"
            tooltip="Import an existing GitHub, GitLab, or Bitbucket repo as a new workspace."
            onClick={() => setShowImportDialog(true)}
          />
          <ActionCard
            icon={<Storefront size={20} weight="duotone" />}
            title="Apps"
            tooltip="Coming soon — prebuilt apps you can install into a workspace."
            disabled
            badge="Soon"
          />
          <ActionCard
            icon={<MoodyFace size={20} animate trackPointer />}
            title="Agents"
            tooltip="Browse marketplace agents to automate workflows in your projects."
            onClick={() => navigate('/marketplace/browse/agent')}
          />
          <ConnectorsCard onClick={() => navigate('/marketplace/browse/mcp_server')} />
        </div>

        {/* Recent Projects — finder-style list */}
        <section
          aria-labelledby="recent-projects-heading"
          className="flex flex-col gap-2"
        >
          <div className="flex items-center justify-between">
            <h2
              id="recent-projects-heading"
              className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]"
            >
              Recent Projects
            </h2>
            {recent.length > 0 && (
              <button
                type="button"
                onClick={() => navigate('/dashboard')}
                className="flex items-center gap-1 text-[11px] font-medium text-[var(--text-muted)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:text-[var(--text)]"
              >
                View all
                <ArrowRight size={12} />
              </button>
            )}
          </div>

          {recentLoading ? (
            <div
              className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-4 py-6 text-center text-xs text-[var(--text-muted)]"
              role="status"
              aria-live="polite"
            >
              Loading workspaces…
            </div>
          ) : recent.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-[var(--radius)] border border-dashed border-[var(--border)] bg-[var(--surface)] px-4 py-8 text-center">
              <FolderOpen size={24} className="text-[var(--text-subtle)]" />
              <p className="text-sm text-[var(--text-muted)]">No workspaces yet</p>
              <p className="text-xs text-[var(--text-subtle)]">
                Click <span className="text-[var(--text-muted)]">New Project</span> above to create your first one.
              </p>
            </div>
          ) : (
            <ul className="flex flex-col overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)]">
              {recent.map((p, i) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => handleOpenProject(p.slug)}
                    className={[
                      'flex w-full items-center gap-3 px-3 py-2.5 text-left motion-safe:transition-colors',
                      'hover:bg-[var(--surface-hover)] focus-visible:outline-none focus-visible:bg-[var(--surface-hover)]',
                      i !== recent.length - 1 ? 'border-b border-[var(--border)]' : '',
                    ].join(' ')}
                  >
                    <Folder
                      size={18}
                      weight="duotone"
                      className="flex-shrink-0 text-[var(--text-muted)]"
                    />
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-sm text-[var(--text)]">{p.name}</span>
                      <span className="truncate text-[11px] text-[var(--text-subtle)]">
                        {activeTeam?.slug ? `${activeTeam.slug}/` : ''}
                        {p.slug}
                      </span>
                    </div>
                    <span
                      className="hidden flex-shrink-0 text-[11px] text-[var(--text-muted)] sm:inline"
                      title={new Date(p.updatedAt).toLocaleString()}
                    >
                      {formatRelativeTime(p.updatedAt)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        </div>
      </div>

      {/* Modals */}
      <CreateProjectModal
        isOpen={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        onConfirm={handleCreateProject}
        isLoading={isCreating}
      />
      <RepoImportModal
        isOpen={showImportDialog}
        onClose={() => setShowImportDialog(false)}
        onCreateProject={handleImportRepo}
      />
    </div>
  );
}
