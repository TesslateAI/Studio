import { useState, useEffect, useCallback } from 'react';
import { ArrowsClockwise, FirstAid, Warning, CheckCircle, X } from '@phosphor-icons/react';
import { volumeApi, type VolumeStatus, type VolumeRecoverResponse } from '../lib/api';
import toast from 'react-hot-toast';

interface VolumeHealthBannerProps {
  projectSlug: string;
  /** Poll interval in ms. 0 = poll once on mount. */
  pollInterval?: number;
  /** Called after successful recovery so parent can refresh file tree etc. */
  onRecovered?: (result: VolumeRecoverResponse) => void;
}

type BannerState = 'hidden' | 'healthy' | 'degraded' | 'recovering';

export function VolumeHealthBanner({
  projectSlug,
  pollInterval = 0,
  onRecovered,
}: VolumeHealthBannerProps) {
  const [status, setStatus] = useState<VolumeStatus | null>(null);
  const [bannerState, setBannerState] = useState<BannerState>('hidden');
  const [recovering, setRecovering] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const checkHealth = useCallback(async () => {
    try {
      const s = await volumeApi.status(projectSlug);
      setStatus(s);
      if (s.status === 'healthy') {
        setBannerState('healthy');
      } else {
        setBannerState('degraded');
        setDismissed(false); // Re-show on new degradation
      }
    } catch {
      // API itself failed — Hub might be down
      setStatus({ status: 'unavailable', message: 'Cannot reach volume service' });
      setBannerState('degraded');
      setDismissed(false);
    }
  }, [projectSlug]);

  // Poll on mount + interval
  useEffect(() => {
    checkHealth();
    if (pollInterval > 0) {
      const id = setInterval(checkHealth, pollInterval);
      return () => clearInterval(id);
    }
  }, [checkHealth, pollInterval]);

  const handleRecover = useCallback(
    async (hash?: string) => {
      setRecovering(true);
      setBannerState('recovering');
      try {
        const result = await volumeApi.recover(projectSlug, hash || undefined);
        toast.success(`Volume recovered to node ${result.node}`);
        setRecovering(false);
        setBannerState('healthy');
        setStatus({ status: 'healthy', node: result.node });
        onRecovered?.(result);
      } catch (err) {
        toast.error(`Recovery failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
        setRecovering(false);
        setBannerState('degraded');
      }
    },
    [projectSlug, onRecovered]
  );

  // Don't render if healthy or dismissed
  if (bannerState === 'hidden' || (bannerState === 'healthy' && !recovering)) return null;
  if (dismissed && bannerState !== 'recovering') return null;

  const statusColor =
    bannerState === 'recovering' ? 'blue' : bannerState === 'degraded' ? 'red' : 'green';

  const statusMessage =
    status?.status === 'restoring'
      ? 'Volume is restoring from backup...'
      : status?.status === 'unreachable'
        ? 'Volume node is temporarily unreachable'
        : status?.status === 'unavailable'
          ? 'Volume storage is unavailable'
          : bannerState === 'recovering'
            ? 'Recovering volume...'
            : `Volume healthy on ${status?.node || 'unknown'}`;

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 animate-in fade-in slide-in-from-top-2 duration-300">
      <div
        className={`flex items-center gap-3 rounded-xl px-5 py-3 backdrop-blur-sm shadow-lg border ${
          statusColor === 'red'
            ? 'bg-red-500/10 border-red-500/30'
            : statusColor === 'blue'
              ? 'bg-blue-500/10 border-blue-500/30'
              : 'bg-green-500/10 border-green-500/30'
        }`}
      >
        {/* Status icon */}
        {bannerState === 'recovering' ? (
          <ArrowsClockwise size={20} weight="bold" className="text-blue-400 animate-spin" />
        ) : bannerState === 'degraded' ? (
          <Warning size={20} weight="bold" className="text-red-400" />
        ) : (
          <CheckCircle size={20} weight="bold" className="text-green-400" />
        )}

        {/* Message */}
        <span
          className={`text-sm font-medium ${
            statusColor === 'red'
              ? 'text-red-300'
              : statusColor === 'blue'
                ? 'text-blue-300'
                : 'text-green-300'
          }`}
        >
          {statusMessage}
        </span>

        {/* Actions for degraded state */}
        {bannerState === 'degraded' && status?.recoverable && (
          <div className="flex items-center gap-2 ml-2">
            <button
              onClick={() => handleRecover()}
              disabled={recovering}
              className="px-3 py-1 rounded-lg text-xs font-semibold bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 transition-colors disabled:opacity-50 flex items-center gap-1"
            >
              <FirstAid size={14} />
              Recover to Latest
            </button>

            {/* Restore to specific snapshot available via Timeline panel */}
          </div>
        )}

        {/* Refresh button */}
        {bannerState !== 'recovering' && (
          <button
            onClick={checkHealth}
            className="ml-1 p-1 rounded hover:bg-white/10 transition-colors"
            title="Refresh volume status"
          >
            <ArrowsClockwise size={14} className="text-white/50" />
          </button>
        )}

        {/* Dismiss */}
        {bannerState === 'degraded' && (
          <button
            onClick={() => setDismissed(true)}
            className="p-1 rounded hover:bg-white/10 transition-colors"
          >
            <X size={14} className="text-white/40" />
          </button>
        )}
      </div>

      {/* No technical details shown to user */}
    </div>
  );
}
