import { useState, useEffect } from 'react';
import {
  Clock,
  FloppyDisk,
  ArrowCounterClockwise,
  CheckCircle,
  Warning,
  Spinner,
  Camera
} from '@phosphor-icons/react';
import { snapshotsApi, type Snapshot, type SnapshotListResponse } from '../../lib/api';
import toast from 'react-hot-toast';

interface TimelinePanelProps {
  projectId: string;
  projectStatus: string;  // 'active', 'hibernated', 'stopped', etc.
}

export function TimelinePanel({ projectId, projectStatus }: TimelinePanelProps) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [maxSnapshots, setMaxSnapshots] = useState(5);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [showLabelInput, setShowLabelInput] = useState(false);
  const [newLabel, setNewLabel] = useState('');

  useEffect(() => {
    loadSnapshots();
  }, [projectId]);

  // Poll for pending snapshots to update their status
  useEffect(() => {
    const hasPending = snapshots.some(s => s.status === 'pending');
    if (!hasPending) return;

    const pollInterval = setInterval(() => {
      loadSnapshots();
    }, 3000); // Poll every 3 seconds

    return () => clearInterval(pollInterval);
  }, [snapshots]);

  const loadSnapshots = async () => {
    try {
      const response: SnapshotListResponse = await snapshotsApi.list(projectId);
      setSnapshots(response.snapshots);
      setMaxSnapshots(response.max_snapshots);
    } catch (error) {
      console.error('Failed to load snapshots:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateSnapshot = async () => {
    if (projectStatus !== 'active') {
      toast.error('Project must be running to create a snapshot');
      return;
    }

    setIsCreating(true);

    try {
      const snapshot = await snapshotsApi.create(projectId, newLabel || undefined);
      // Snapshot is created but still 'pending' - polling will update status
      toast.success(`Snapshot "${snapshot.label}" started - saving in background`);
      setNewLabel('');
      setShowLabelInput(false);
      await loadSnapshots();
    } catch (error: unknown) {
      const errorMsg = error instanceof Error ? error.message : 'Failed to create snapshot';
      toast.error(errorMsg);
    } finally {
      setIsCreating(false);
    }
  };

  const handleRestore = async (snapshot: Snapshot) => {
    if (projectStatus === 'active') {
      toast.error('Stop the project first before restoring from a snapshot');
      return;
    }

    const loadingToast = toast.loading('Setting restore point...');

    try {
      const response = await snapshotsApi.restore(projectId, snapshot.id);
      toast.success(response.message, { id: loadingToast });
    } catch (error: unknown) {
      const errorMsg = error instanceof Error ? error.message : 'Failed to set restore point';
      toast.error(errorMsg, { id: loadingToast });
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
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
      minute: '2-digit'
    });
  };

  const formatSize = (bytes: number | null) => {
    if (!bytes) return '';
    const mb = bytes / (1024 * 1024);
    if (mb < 1024) return `${mb.toFixed(1)} MB`;
    return `${(mb / 1024).toFixed(1)} GB`;
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'ready':
        return <CheckCircle className="text-green-500" weight="fill" />;
      case 'pending':
        return <Spinner className="text-blue-500 animate-spin" />;
      case 'error':
        return <Warning className="text-red-500" weight="fill" />;
      default:
        return null;
    }
  };

  const getTypeColor = (type: string) => {
    return type === 'manual' ? 'bg-purple-500' : 'bg-blue-500';
  };

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Spinner className="w-8 h-8 text-gray-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-gray-900">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-5 h-5 text-gray-400" />
            <h3 className="font-medium text-white">Project Timeline</h3>
          </div>
          <span className="text-xs text-gray-500">
            {snapshots.length}/{maxSnapshots} snapshots
          </span>
        </div>
      </div>

      {/* Create Snapshot Button */}
      <div className="px-4 py-3 border-b border-gray-800">
        {showLabelInput ? (
          <div className="flex flex-col gap-2">
            <input
              type="text"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="Snapshot label (optional)"
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
                disabled={isCreating || projectStatus !== 'active'}
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
            disabled={projectStatus !== 'active'}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-750 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors border border-gray-700"
          >
            <FloppyDisk className="w-4 h-4" />
            Save Current State
          </button>
        )}
        {projectStatus !== 'active' && (
          <p className="mt-2 text-xs text-gray-500 text-center">
            Start the project to create snapshots
          </p>
        )}
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {snapshots.length === 0 ? (
          <div className="text-center py-8">
            <Clock className="w-12 h-12 text-gray-700 mx-auto mb-3" />
            <p className="text-gray-500 text-sm">No snapshots yet</p>
            <p className="text-gray-600 text-xs mt-1">
              Snapshots are created automatically when the project hibernates
            </p>
          </div>
        ) : (
          <div className="relative">
            {/* Timeline line */}
            <div className="absolute left-3 top-3 bottom-3 w-px bg-gray-700" />

            {/* Timeline entries */}
            <div className="space-y-4">
              {snapshots.map((snapshot, index) => (
                <div key={snapshot.id} className="relative pl-8">
                  {/* Timeline dot */}
                  <div className={`absolute left-1.5 top-2 w-3 h-3 rounded-full ${getTypeColor(snapshot.snapshot_type)} ring-4 ring-gray-900`} />

                  {/* Entry card */}
                  <div className="bg-gray-800 rounded-lg p-3 border border-gray-700 hover:border-gray-600 transition-colors">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          {getStatusIcon(snapshot.status)}
                          <span className="font-medium text-white text-sm truncate">
                            {snapshot.label || 'Auto-save'}
                          </span>
                          {index === 0 && snapshot.status === 'ready' && (
                            <span className="px-1.5 py-0.5 bg-green-900/50 text-green-400 text-xs rounded">
                              Latest
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-3 text-xs text-gray-500">
                          <span>{formatDate(snapshot.created_at)}</span>
                          {snapshot.volume_size_bytes && (
                            <span>{formatSize(snapshot.volume_size_bytes)}</span>
                          )}
                          <span className={`capitalize ${snapshot.snapshot_type === 'manual' ? 'text-purple-400' : 'text-blue-400'}`}>
                            {snapshot.snapshot_type}
                          </span>
                        </div>
                      </div>

                      {/* Restore button */}
                      {snapshot.status === 'ready' && (
                        <button
                          onClick={() => handleRestore(snapshot)}
                          disabled={projectStatus === 'active'}
                          title={projectStatus === 'active' ? 'Stop the project first' : 'Restore to this point'}
                          className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
                        >
                          <ArrowCounterClockwise className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Info footer */}
      <div className="px-4 py-2 border-t border-gray-800 bg-gray-900/50">
        <p className="text-xs text-gray-600 text-center">
          Snapshots include all files (including node_modules)
        </p>
      </div>
    </div>
  );
}
