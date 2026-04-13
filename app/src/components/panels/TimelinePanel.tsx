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

/** A rendered item in the timeline: either a checkpoint card or an auto-save gap. */
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

/**
 * Walk prev pointers from a tip hash and build timeline items.
 * Uses `prev` (chronological predecessor) instead of `parent` (which skips
 * intermediates for consolidation snapshots).
 *
 * Returns newest-first: checkpoint cards with auto-save counts between them.
 */
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
      // Flush any accumulated syncs before this checkpoint.
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

  // Trailing syncs after the last checkpoint (oldest syncs at the bottom).
  if (syncCount > 0 && items.length > 0) {
    items.push({ type: 'autosaves', count: syncCount });
  }

  return items;
}

/**
 * Find fork points: hashes in the active branch's ancestor chain that are
 * also pointed to by other branches (i.e. they diverged from this point).
 */
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
        className="w-full flex items-center justify-between gap-2 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white hover:border-gray-600 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <GitBranch size={14} className="text-gray-400 flex-shrink-0" />
          <span className="truncate">{active?.display_name}</span>
          {active?.is_current && (
            <span className="px-1.5 py-0.5 bg-green-900/50 text-green-400 text-[10px] rounded flex-shrink-0">
              current
            </span>
          )}
        </div>
        <CaretDown
          size={12}
          className={`text-gray-500 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-10 overflow-hidden">
          {branches.map((branch) => (
            <button
              key={branch.name}
              onClick={() => {
                onSelect(branch.name);
                setOpen(false);
              }}
              className={`w-full flex items-center justify-between gap-2 px-3 py-2 text-sm transition-colors ${
                branch.name === activeBranch
                  ? 'bg-blue-600/20 text-white'
                  : 'text-gray-300 hover:bg-gray-750'
              }`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <GitBranch size={14} className="text-gray-500 flex-shrink-0" />
                <span className="truncate">{branch.display_name}</span>
                {branch.is_current && (
                  <span className="px-1.5 py-0.5 bg-green-900/50 text-green-400 text-[10px] rounded flex-shrink-0">
                    current
                  </span>
                )}
              </div>
              <span className="text-xs text-gray-500 flex-shrink-0">
                {branch.checkpoint_count} saves
              </span>
            </button>
          ))}

          {/* Create branch */}
          <div className="border-t border-gray-700">
            {showCreate ? (
              <div className="p-2 flex flex-col gap-1.5">
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Branch name"
                  className="w-full px-2 py-1.5 bg-gray-900 border border-gray-600 rounded text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
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
                    className="flex-1 px-2 py-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white rounded text-xs font-medium transition-colors"
                  >
                    {creating ? 'Creating...' : 'Create'}
                  </button>
                  <button
                    onClick={() => {
                      setShowCreate(false);
                      setNewName('');
                    }}
                    className="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setShowCreate(true)}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-gray-400 hover:text-white hover:bg-gray-750 transition-colors"
              >
                <GitBranch size={12} />
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
      <div className="absolute left-[9px] top-1/2 w-4 h-px bg-purple-500/50" />
      <div className="absolute left-[25px] top-1/2 -translate-y-1/2">
        <GitFork size={10} className="text-purple-400" />
      </div>
      <div className="ml-4 bg-purple-500/10 border border-purple-500/20 rounded-lg px-3 py-2">
        {branches.map((branch) => (
          <button
            key={branch.name}
            onClick={() => onSwitchBranch(branch.name)}
            className="w-full flex items-center justify-between gap-2 text-xs group"
          >
            <div className="flex items-center gap-1.5 min-w-0">
              <GitBranch size={12} className="text-purple-400 flex-shrink-0" />
              <span className="text-purple-300 truncate">{branch.display_name}</span>
            </div>
            <span className="text-purple-400/60 group-hover:text-purple-300 flex-shrink-0 transition-colors">
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
        <CloudArrowUp size={10} className="text-gray-600" />
        <span className="text-[10px] text-gray-600">
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
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-5 max-w-sm mx-4 shadow-2xl">
        <h3 className="text-white font-medium mb-2">
          Restore to &ldquo;{snapshot.label || 'Checkpoint'}&rdquo;?
        </h3>
        <p className="text-gray-400 text-sm mb-4">
          {isOnCurrentBranch
            ? 'Your current work will be saved as a separate branch so you can return to it later.'
            : 'This will switch your project to this saved state.'}
        </p>
        {isOnCurrentBranch && (
          <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 mb-4">
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <GitBranch size={12} className="text-blue-400" />
              <span>Current state will be preserved as a branch</span>
            </div>
          </div>
        )}
        <div className="flex gap-2">
          <button
            onClick={onCancel}
            className="flex-1 px-3 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg text-sm transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
          >
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

  // Volume health
  const [volumeStatus, setVolumeStatus] = useState<VolumeStatus | null>(null);
  const [isRecovering, setIsRecovering] = useState(false);

  // ------------------------------------------------------------------
  // Data loading
  // ------------------------------------------------------------------

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

  // ------------------------------------------------------------------
  // Derived data
  // ------------------------------------------------------------------

  // ALL snapshots in the map (sync + checkpoint) for traversal.
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

  // Build timeline items: checkpoints as cards, sync counts between them.
  const timelineItems = useMemo(() => {
    if (!activeBranchObj) return [];
    return buildTimelineItems(activeBranchObj.hash, snapMap, graph?.head ?? '');
  }, [activeBranchObj, snapMap, graph]);

  // Build ancestor chain of the active branch for fork detection.
  // Walks ALL snapshots (sync + checkpoint) via prev pointers.
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

  // ------------------------------------------------------------------
  // Handlers
  // ------------------------------------------------------------------

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

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  const isHealthy = volumeStatus?.status === 'healthy';
  const isDegraded = volumeStatus && !isHealthy;
  const totalCheckpoints = graph?.branches.reduce((sum, b) => sum + b.checkpoint_count, 0) ?? 0;
  const checkpointItems = timelineItems.filter((i) => i.type === 'checkpoint');

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Spinner className="w-8 h-8 text-gray-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-gray-900">
      {/* Volume Health Section */}
      <div className="px-4 py-3 border-b border-gray-800">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <HardDrive className="w-4 h-4 text-gray-400" />
            <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">
              Storage
            </span>
          </div>
          <button
            onClick={checkVolumeHealth}
            className="p-1 rounded hover:bg-gray-800 transition-colors"
            title="Refresh status"
          >
            <ArrowsClockwise size={12} className="text-gray-500" />
          </button>
        </div>

        <div className="flex items-center gap-2">
          {isHealthy ? (
            <CheckCircle size={16} className="text-green-500" weight="fill" />
          ) : isDegraded ? (
            <Warning size={16} className="text-red-500" weight="fill" />
          ) : (
            <Spinner size={16} className="text-gray-500 animate-spin" />
          )}
          <span
            className={`text-sm ${isHealthy ? 'text-green-400' : isDegraded ? 'text-red-400' : 'text-gray-400'}`}
          >
            {isHealthy
              ? 'Connected'
              : isDegraded
                ? 'Unavailable — storage needs recovery'
                : 'Checking...'}
          </span>
        </div>

        {isDegraded && volumeStatus.recoverable && (
          <div className="mt-2 flex gap-2">
            <button
              onClick={handleRecover}
              disabled={isRecovering}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 bg-amber-600/20 border border-amber-600/30 text-amber-400 rounded-lg text-xs font-medium hover:bg-amber-600/30 transition-colors disabled:opacity-50"
            >
              <FirstAid size={14} />
              {isRecovering ? 'Recovering...' : 'Recover to Latest'}
            </button>
          </div>
        )}
      </div>

      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-5 h-5 text-gray-400" />
            <h3 className="font-medium text-white">Timeline</h3>
          </div>
          <span className="text-xs text-gray-500">{totalCheckpoints} saved</span>
        </div>
      </div>

      {/* Branch Selector */}
      {graph && (
        <div className="px-4 py-3 border-b border-gray-800">
          <BranchSelector
            branches={graph.branches}
            activeBranch={activeBranch}
            onSelect={setActiveBranch}
            onCreate={handleCreateBranch}
          />
        </div>
      )}

      {/* Create Checkpoint */}
      <div className="px-4 py-3 border-b border-gray-800">
        {showLabelInput ? (
          <div className="flex flex-col gap-2">
            <input
              type="text"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="Checkpoint label (optional)"
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
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
                className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors"
              >
                {isCreating ? (
                  <Spinner className="w-4 h-4 animate-spin" />
                ) : (
                  <Camera className="w-4 h-4" />
                )}
                Save
              </button>
              <button
                onClick={() => {
                  setShowLabelInput(false);
                  setNewLabel('');
                }}
                className="px-3 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg text-sm transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setShowLabelInput(true)}
            disabled={!isHealthy}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-750 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors border border-gray-700"
          >
            <FloppyDisk className="w-4 h-4" />
            Create Checkpoint
          </button>
        )}
        {!isHealthy && (
          <p className="mt-2 text-xs text-gray-500 text-center">
            Storage must be available to save checkpoints
          </p>
        )}
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {checkpointItems.length === 0 ? (
          <div className="text-center py-8">
            <Clock className="w-12 h-12 text-gray-700 mx-auto mb-3" />
            <p className="text-gray-500 text-sm">No checkpoints yet</p>
            <p className="text-gray-600 text-xs mt-1">Save your project state to restore later</p>
          </div>
        ) : (
          <div className="relative">
            <div className="absolute left-3 top-3 bottom-3 w-px bg-gray-700" />

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
                        className={`absolute left-1.5 top-3 w-3 h-3 rounded-full ring-4 ring-gray-900 ${
                          isHead ? 'bg-green-500' : 'bg-blue-500'
                        }`}
                      />

                      <div className="bg-gray-800 rounded-lg p-3 border border-gray-700 hover:border-gray-600 transition-colors">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <CheckCircle
                                className="text-green-500 flex-shrink-0"
                                weight="fill"
                                size={14}
                              />
                              <span className="font-medium text-white text-sm truncate">
                                {snapshot.label || 'Checkpoint'}
                              </span>
                              {isHead && (
                                <span className="px-1.5 py-0.5 bg-green-900/50 text-green-400 text-xs rounded flex-shrink-0">
                                  Current
                                </span>
                              )}
                              {isFirst && !isHead && (
                                <span className="px-1.5 py-0.5 bg-blue-900/50 text-blue-400 text-xs rounded flex-shrink-0">
                                  Latest
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-3 text-xs text-gray-500">
                              <span>{formatDate(snapshot.ts)}</span>
                            </div>
                          </div>

                          {!isHead && (
                            <button
                              onClick={() => setRestoreTarget(snapshot)}
                              title="Restore to this checkpoint"
                              className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors"
                            >
                              <ArrowCounterClockwise className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Fork indicator after this node */}
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

      {/* Footer spacer */}
      <div className="h-2" />

      {/* Restore confirmation dialog */}
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
