import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Clock,
  FloppyDisk,
  ArrowCounterClockwise,
  CheckCircle,
  Warning,
  Spinner,
  Camera,
  HardDrive,
  ArrowsClockwise,
  FirstAid,
  GitBranch,
  GitFork,
  CaretDown,
  CloudArrowUp,
} from '@phosphor-icons/react';
import {
  snapshotsApi,
  volumeApi,
  type Snapshot,
  type TimelineBranch,
  type TimelineGraphResponse,
  type VolumeStatus,
} from '../../lib/api';
import toast from 'react-hot-toast';

interface TimelinePanelProps {
  projectId: string;
  projectSlug: string;
  projectStatus: string;
  /** Called after a successful snapshot restore so the parent can refresh file tree etc. */
  onRestored?: () => void;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TimelineItem =
  | { type: 'checkpoint'; snapshot: Snapshot; isHead: boolean }
  | { type: 'autosaves'; count: number };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(ts: string): string {
  if (!ts) return '';
  const date = new Date(ts);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function buildTimelineItems(
  tipHash: string,
  snapMap: Map<string, Snapshot>,
  headHash: string
): TimelineItem[] {
  const items: TimelineItem[] = [];
  let hash = tipHash;
  const seen = new Set<string>();
  let syncCount = 0;

  while (hash && snapMap.has(hash) && !seen.has(hash)) {
    seen.add(hash);
    const snap = snapMap.get(hash)!;

    if (snap.role === 'checkpoint') {
      if (syncCount > 0 && items.length > 0) {
        items.push({ type: 'autosaves', count: syncCount });
        syncCount = 0;
      }
      items.push({
        type: 'checkpoint',
        snapshot: snap,
        isHead: snap.hash === headHash,
      });
    } else {
      syncCount++;
    }

    hash = snap.prev || snap.parent;
  }

  if (syncCount > 0 && items.length > 0) {
    items.push({ type: 'autosaves', count: syncCount });
  }

  return items;
}

function findForkPoints(
  activeAncestors: Set<string>,
  branches: TimelineBranch[],
  snapMap: Map<string, Snapshot>
): Map<string, TimelineBranch[]> {
  const forks = new Map<string, TimelineBranch[]>();
  for (const branch of branches) {
    if (branch.is_current) continue;
    let hash = branch.hash;
    const seen = new Set<string>();
    while (hash && snapMap.has(hash) && !seen.has(hash)) {
      seen.add(hash);
      if (activeAncestors.has(hash)) {
        const existing = forks.get(hash) || [];
        existing.push(branch);
        forks.set(hash, existing);
        break;
      }
      const snap = snapMap.get(hash)!;
      hash = snap.prev || snap.parent;
    }
  }
  return forks;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CurrentChip() {
  return (
    <span
      className="px-1.5 py-0.5 text-[10px] rounded-[var(--radius-small)] flex-shrink-0 font-medium"
      style={{
        color: 'var(--status-success)',
        backgroundColor: 'color-mix(in srgb, var(--status-success) 12%, transparent)',
      }}
    >
      current
    </span>
  );
}

function BranchSelector({
  branches,
  activeBranch,
  onSelect,
  onCreate,
}: {
  branches: TimelineBranch[];
  activeBranch: string;
  onSelect: (name: string) => void;
  onCreate: (name: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const active = branches.find((b) => b.name === activeBranch) || branches[0];

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await onCreate(newName.trim());
      setNewName('');
      setShowCreate(false);
      setOpen(false);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 bg-[var(--surface-hover)] border border-[var(--border)] hover:border-[var(--border-hover)] rounded-[var(--radius-small)] text-xs text-[var(--text)] transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <GitBranch size={12} weight="bold" className="text-[var(--text-muted)] flex-shrink-0" />
          <span className="truncate">{active?.display_name}</span>
          {active?.is_current && <CurrentChip />}
        </div>
        <CaretDown
          size={11}
          className={`text-[var(--text-subtle)] transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] z-10 overflow-hidden p-1.5">
          {branches.map((branch) => (
            <button
              key={branch.name}
              onClick={() => {
                onSelect(branch.name);
                setOpen(false);
              }}
              className={`w-full flex items-center justify-between gap-2 px-2.5 py-1.5 text-xs rounded-[var(--radius-small)] transition-colors ${
                branch.name === activeBranch
                  ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)]'
              }`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <GitBranch
                  size={11}
                  weight="bold"
                  className="text-[var(--text-subtle)] flex-shrink-0"
                />
                <span className="truncate">{branch.display_name}</span>
                {branch.is_current && <CurrentChip />}
              </div>
              <span className="text-[10px] text-[var(--text-subtle)] flex-shrink-0">
                {branch.checkpoint_count} saves
              </span>
            </button>
          ))}

          <div className="border-t border-[var(--border)] mt-1 pt-1">
            {showCreate ? (
              <div className="p-1 flex flex-col gap-1.5">
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Branch name"
                  className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] placeholder-[var(--text-subtle)] focus:outline-none focus:border-[var(--border-hover)]"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleCreate();
                    if (e.key === 'Escape') {
                      setShowCreate(false);
                      setNewName('');
                    }
                  }}
                />
                <div className="flex gap-1.5">
                  <button
                    onClick={handleCreate}
                    disabled={creating || !newName.trim()}
                    className="btn btn-sm btn-primary flex-1"
                    style={
                      creating || !newName.trim()
                        ? { opacity: 0.4, cursor: 'not-allowed' }
                        : undefined
                    }
                  >
                    {creating ? 'Creating…' : 'Create'}
                  </button>
                  <button
                    onClick={() => {
                      setShowCreate(false);
                      setNewName('');
                    }}
                    className="btn btn-sm flex-1"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setShowCreate(true)}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] rounded-[var(--radius-small)] transition-colors"
              >
                <GitBranch size={11} weight="bold" />
                New branch from current state
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ForkIndicator({
  branches,
  onSwitchBranch,
}: {
  branches: TimelineBranch[];
  onSwitchBranch: (name: string) => void;
}) {
  return (
    <div className="relative pl-8 my-1">
      <div className="absolute left-[9px] top-1/2 w-4 h-px bg-[var(--border-hover)]" />
      <div className="absolute left-[25px] top-1/2 -translate-y-1/2">
        <GitFork size={10} className="text-[var(--text-muted)]" weight="bold" />
      </div>
      <div className="ml-4 bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius-small)] px-2.5 py-1.5">
        {branches.map((branch) => (
          <button
            key={branch.name}
            onClick={() => onSwitchBranch(branch.name)}
            className="w-full flex items-center justify-between gap-2 text-xs group"
          >
            <div className="flex items-center gap-1.5 min-w-0">
              <GitBranch
                size={11}
                weight="bold"
                className="text-[var(--text-muted)] flex-shrink-0"
              />
              <span className="text-[var(--text-muted)] group-hover:text-[var(--text)] truncate transition-colors">
                {branch.display_name}
              </span>
            </div>
            <span className="text-[10px] text-[var(--text-subtle)] group-hover:text-[var(--text-muted)] flex-shrink-0 transition-colors">
              {branch.checkpoint_count} saves
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function AutoSaveIndicator({ count }: { count: number }) {
  return (
    <div className="relative pl-8 my-0.5">
      <div className="flex items-center gap-1.5 py-1 px-2">
        <CloudArrowUp size={10} className="text-[var(--text-subtle)]" weight="bold" />
        <span className="text-[10px] text-[var(--text-subtle)]">
          {count} auto-save{count !== 1 ? 's' : ''}
        </span>
      </div>
    </div>
  );
}

function RestoreConfirmDialog({
  snapshot,
  isOnCurrentBranch,
  onConfirm,
  onCancel,
}: {
  snapshot: Snapshot;
  isOnCurrentBranch: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius)] p-5 max-w-sm mx-4">
        <h3 className="text-[var(--text)] text-sm font-semibold mb-2">
          Restore to &ldquo;{snapshot.label || 'Checkpoint'}&rdquo;?
        </h3>
        <p className="text-[var(--text-muted)] text-xs mb-4 leading-relaxed">
          {isOnCurrentBranch
            ? 'Your current work will be saved as a separate branch so you can return to it later.'
            : 'This will switch your project to this saved state.'}
        </p>
        {isOnCurrentBranch && (
          <div className="bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius-small)] px-2.5 py-1.5 mb-4">
            <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
              <GitBranch size={11} weight="bold" />
              <span>Current state will be preserved as a branch</span>
            </div>
          </div>
        )}
        <div className="flex gap-2">
          <button onClick={onCancel} className="btn flex-1">
            Cancel
          </button>
          <button onClick={onConfirm} className="btn btn-filled flex-1">
            Restore
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function TimelinePanel({
  projectId,
  projectSlug,
  projectStatus: _projectStatus,
  onRestored,
}: TimelinePanelProps) {
  const [graph, setGraph] = useState<TimelineGraphResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [showLabelInput, setShowLabelInput] = useState(false);
  const [newLabel, setNewLabel] = useState('');
  const [activeBranch, setActiveBranch] = useState('main');
  const [restoreTarget, setRestoreTarget] = useState<Snapshot | null>(null);

  const [volumeStatus, setVolumeStatus] = useState<VolumeStatus | null>(null);
  const [isRecovering, setIsRecovering] = useState(false);

  const loadGraph = useCallback(async () => {
    try {
      const response = await snapshotsApi.graph(projectId);
      setGraph(response);
    } catch {
      setGraph(null);
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  const checkVolumeHealth = useCallback(async () => {
    try {
      const s = await volumeApi.status(projectSlug);
      setVolumeStatus(s);
    } catch {
      setVolumeStatus({ status: 'unavailable', message: 'Cannot reach volume service' });
    }
  }, [projectSlug]);

  useEffect(() => {
    loadGraph();
    checkVolumeHealth();
  }, [loadGraph, checkVolumeHealth]);

  useEffect(() => {
    const id = setInterval(checkVolumeHealth, 30000);
    return () => clearInterval(id);
  }, [checkVolumeHealth]);

  const snapMap = useMemo(() => {
    const map = new Map<string, Snapshot>();
    if (graph) {
      for (const snap of graph.snapshots) {
        map.set(snap.hash, snap);
      }
    }
    return map;
  }, [graph]);

  const activeBranchObj = useMemo(
    () => graph?.branches.find((b) => b.name === activeBranch) || graph?.branches[0],
    [graph, activeBranch]
  );

  const timelineItems = useMemo(() => {
    if (!activeBranchObj) return [];
    return buildTimelineItems(activeBranchObj.hash, snapMap, graph?.head ?? '');
  }, [activeBranchObj, snapMap, graph]);

  const activeAncestors = useMemo(() => {
    const ancestors = new Set<string>();
    if (!activeBranchObj) return ancestors;
    let hash = activeBranchObj.hash;
    const seen = new Set<string>();
    while (hash && snapMap.has(hash) && !seen.has(hash)) {
      seen.add(hash);
      ancestors.add(hash);
      const snap = snapMap.get(hash)!;
      hash = snap.prev || snap.parent;
    }
    return ancestors;
  }, [activeBranchObj, snapMap]);

  const forkPoints = useMemo(() => {
    if (!graph) return new Map<string, TimelineBranch[]>();
    return findForkPoints(activeAncestors, graph.branches, snapMap);
  }, [graph, activeAncestors, snapMap]);

  const handleCreateSnapshot = async () => {
    setIsCreating(true);
    try {
      const result = await snapshotsApi.create(projectId, newLabel || undefined);
      toast.success(`Checkpoint saved: ${result.label || 'Manual save'}`);
      setNewLabel('');
      setShowLabelInput(false);
      await loadGraph();
    } catch (error: unknown) {
      toast.error(error instanceof Error ? error.message : 'Failed to save checkpoint');
    } finally {
      setIsCreating(false);
    }
  };

  const handleRestore = async (snapshot: Snapshot) => {
    setRestoreTarget(null);
    const loadingToast = toast.loading('Restoring...');
    try {
      const response = await snapshotsApi.restore(projectId, snapshot.hash);
      toast.success(response.message, { id: loadingToast });
      await Promise.all([loadGraph(), checkVolumeHealth()]);
      setActiveBranch('main');
      onRestored?.();
    } catch (error: unknown) {
      toast.error(error instanceof Error ? error.message : 'Restore failed', { id: loadingToast });
    }
  };

  const handleCreateBranch = async (name: string) => {
    try {
      await snapshotsApi.createBranch(projectId, name);
      toast.success(`Branch "${name}" created`);
      await loadGraph();
    } catch (error: unknown) {
      toast.error(error instanceof Error ? error.message : 'Failed to create branch');
    }
  };

  const handleRecover = async () => {
    setIsRecovering(true);
    try {
      const result = await volumeApi.recover(projectSlug);
      toast.success(`Storage recovered to node ${result.node}`);
      setVolumeStatus({ status: 'healthy', node: result.node });
      await loadGraph();
    } catch (error: unknown) {
      toast.error(error instanceof Error ? error.message : 'Recovery failed');
    } finally {
      setIsRecovering(false);
    }
  };

  const isHealthy = volumeStatus?.status === 'healthy';
  const isDegraded = volumeStatus && !isHealthy;
  const totalCheckpoints = graph?.branches.reduce((sum, b) => sum + b.checkpoint_count, 0) ?? 0;
  const checkpointItems = timelineItems.filter((i) => i.type === 'checkpoint');

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center bg-[var(--bg)]">
        <Spinner className="w-6 h-6 text-[var(--text-muted)] animate-spin" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[var(--bg)] overflow-hidden">
      {/* Storage Health */}
      <div className="px-4 py-3 border-b border-[var(--border)]">
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-1.5">
            <HardDrive size={12} className="text-[var(--text-subtle)]" weight="bold" />
            <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--text-subtle)]">
              Storage
            </span>
          </div>
          <button
            onClick={checkVolumeHealth}
            className="p-1 rounded-[var(--radius-small)] text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
            title="Refresh status"
          >
            <ArrowsClockwise size={11} weight="bold" />
          </button>
        </div>

        <div className="flex items-center gap-2">
          {isHealthy ? (
            <CheckCircle
              size={14}
              weight="fill"
              style={{ color: 'var(--status-success)' }}
            />
          ) : isDegraded ? (
            <Warning size={14} weight="fill" style={{ color: 'var(--status-error)' }} />
          ) : (
            <Spinner size={14} className="animate-spin text-[var(--text-muted)]" />
          )}
          <span
            className="text-xs"
            style={{
              color: isHealthy
                ? 'var(--status-success)'
                : isDegraded
                  ? 'var(--status-error)'
                  : 'var(--text-muted)',
            }}
          >
            {isHealthy
              ? 'Connected'
              : isDegraded
                ? 'Unavailable — storage needs recovery'
                : 'Checking…'}
          </span>
        </div>

        {isDegraded && volumeStatus.recoverable && (
          <div className="mt-2">
            <button
              onClick={handleRecover}
              disabled={isRecovering}
              className="btn btn-sm w-full flex items-center justify-center gap-1.5"
              style={{
                color: 'var(--status-warning)',
                ...(isRecovering ? { opacity: 0.5, cursor: 'not-allowed' } : {}),
              }}
            >
              <FirstAid size={12} weight="bold" />
              {isRecovering ? 'Recovering…' : 'Recover to Latest'}
            </button>
          </div>
        )}
      </div>

      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Clock size={13} className="text-[var(--text-muted)]" weight="bold" />
          <h3 className="text-xs font-semibold text-[var(--text)]">Timeline</h3>
        </div>
        <span className="text-[10px] text-[var(--text-subtle)]">{totalCheckpoints} saved</span>
      </div>

      {/* Branch Selector */}
      {graph && (
        <div className="px-4 py-3 border-b border-[var(--border)]">
          <BranchSelector
            branches={graph.branches}
            activeBranch={activeBranch}
            onSelect={setActiveBranch}
            onCreate={handleCreateBranch}
          />
        </div>
      )}

      {/* Create Checkpoint */}
      <div className="px-4 py-3 border-b border-[var(--border)]">
        {showLabelInput ? (
          <div className="flex flex-col gap-2">
            <input
              type="text"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="Checkpoint label (optional)"
              className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] placeholder-[var(--text-subtle)] focus:outline-none focus:border-[var(--border-hover)]"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreateSnapshot();
                if (e.key === 'Escape') {
                  setShowLabelInput(false);
                  setNewLabel('');
                }
              }}
            />
            <div className="flex gap-2">
              <button
                onClick={handleCreateSnapshot}
                disabled={isCreating || !isHealthy}
                className="btn btn-filled flex-1 flex items-center justify-center gap-1.5"
                style={
                  isCreating || !isHealthy ? { opacity: 0.4, cursor: 'not-allowed' } : undefined
                }
              >
                {isCreating ? (
                  <Spinner className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Camera size={13} weight="bold" />
                )}
                Save
              </button>
              <button
                onClick={() => {
                  setShowLabelInput(false);
                  setNewLabel('');
                }}
                className="btn flex-1"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setShowLabelInput(true)}
            disabled={!isHealthy}
            className="btn w-full flex items-center justify-center gap-1.5"
            style={!isHealthy ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
          >
            <FloppyDisk size={13} weight="bold" />
            Create Checkpoint
          </button>
        )}
        {!isHealthy && (
          <p className="mt-2 text-[10px] text-[var(--text-subtle)] text-center">
            Storage must be available to save checkpoints
          </p>
        )}
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {checkpointItems.length === 0 ? (
          <div className="text-center py-10">
            <Clock
              size={32}
              className="text-[var(--text-subtle)] mx-auto mb-2 opacity-50"
              weight="bold"
            />
            <p className="text-xs text-[var(--text-muted)]">No checkpoints yet</p>
            <p className="text-[10px] text-[var(--text-subtle)] mt-1">
              Save your project state to restore later
            </p>
          </div>
        ) : (
          <div className="relative">
            <div className="absolute left-3 top-3 bottom-3 w-px bg-[var(--border)]" />

            <div className="space-y-1">
              {timelineItems.map((item, idx) => {
                if (item.type === 'autosaves') {
                  return <AutoSaveIndicator key={`autosave-${idx}`} count={item.count} />;
                }

                const { snapshot, isHead } = item;
                const forkedBranches = forkPoints.get(snapshot.hash);
                const isFirst = idx === timelineItems.findIndex((i) => i.type === 'checkpoint');

                return (
                  <div key={snapshot.hash}>
                    {/* Checkpoint node */}
                    <div className="relative pl-8">
                      <div
                        className="absolute left-1.5 top-3 w-2.5 h-2.5 rounded-full"
                        style={{
                          backgroundColor: isHead
                            ? 'var(--status-success)'
                            : 'var(--text-muted)',
                          boxShadow: '0 0 0 4px var(--bg)',
                        }}
                      />

                      <div className="bg-[var(--surface-hover)] rounded-[var(--radius-small)] px-3 py-2 border border-[var(--border)] hover:border-[var(--border-hover)] transition-colors">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 mb-0.5">
                              <CheckCircle
                                weight="fill"
                                size={12}
                                style={{ color: 'var(--status-success)' }}
                                className="flex-shrink-0"
                              />
                              <span className="text-xs font-medium text-[var(--text)] truncate">
                                {snapshot.label || 'Checkpoint'}
                              </span>
                              {isHead && (
                                <span
                                  className="px-1.5 py-0.5 text-[10px] rounded-[var(--radius-small)] flex-shrink-0 font-medium"
                                  style={{
                                    color: 'var(--status-success)',
                                    backgroundColor:
                                      'color-mix(in srgb, var(--status-success) 12%, transparent)',
                                  }}
                                >
                                  Current
                                </span>
                              )}
                              {isFirst && !isHead && (
                                <span
                                  className="px-1.5 py-0.5 text-[10px] rounded-[var(--radius-small)] flex-shrink-0 font-medium text-[var(--text-muted)] bg-[var(--surface)]"
                                >
                                  Latest
                                </span>
                              )}
                            </div>
                            <div className="text-[10px] text-[var(--text-subtle)]">
                              {formatDate(snapshot.ts)}
                            </div>
                          </div>

                          {!isHead && (
                            <button
                              onClick={() => setRestoreTarget(snapshot)}
                              title="Restore to this checkpoint"
                              className="p-1.5 rounded-[var(--radius-small)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-colors"
                            >
                              <ArrowCounterClockwise size={13} weight="bold" />
                            </button>
                          )}
                        </div>
                      </div>
                    </div>

                    {forkedBranches && forkedBranches.length > 0 && (
                      <ForkIndicator branches={forkedBranches} onSwitchBranch={setActiveBranch} />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div className="h-2" />

      {restoreTarget && (
        <RestoreConfirmDialog
          snapshot={restoreTarget}
          isOnCurrentBranch={activeBranchObj?.is_current ?? true}
          onConfirm={() => handleRestore(restoreTarget)}
          onCancel={() => setRestoreTarget(null)}
        />
      )}
    </div>
  );
}
