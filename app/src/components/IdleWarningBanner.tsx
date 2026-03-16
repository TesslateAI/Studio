import React, { useCallback } from 'react';
import { Clock, X } from '@phosphor-icons/react';

interface IdleWarningBannerProps {
  minutesLeft: number;
  projectSlug: string;
  onDismiss: () => void;
}

/**
 * Dismissible banner shown when the backend sends an `idle_warning` event.
 * "Keep Active" resets the idle timer via POST /api/projects/{slug}/activity.
 * "Dismiss" also fires the same request (any interaction counts).
 */
const IdleWarningBanner: React.FC<IdleWarningBannerProps> = ({
  minutesLeft,
  projectSlug,
  onDismiss,
}) => {
  const keepActive = useCallback(async () => {
    try {
      await fetch(`/api/projects/${projectSlug}/activity`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${localStorage.getItem('token')}`,
        },
        credentials: 'include',
      });
    } catch {
      // Best-effort — the middleware will also reset on any subsequent request
    }
    onDismiss();
  }, [projectSlug, onDismiss]);

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 animate-in fade-in slide-in-from-top-2 duration-300">
      <div className="flex items-center gap-3 rounded-xl px-5 py-3 bg-yellow-500/10 border border-yellow-500/30 backdrop-blur-sm shadow-lg">
        <Clock size={20} weight="bold" className="text-yellow-400 flex-shrink-0" />

        <span className="text-sm text-yellow-300 font-medium">
          Environment will stop in {minutesLeft} min due to inactivity
        </span>

        <button
          onClick={keepActive}
          className="ml-2 px-3 py-1 rounded-lg text-xs font-semibold bg-yellow-500/20 text-yellow-300 hover:bg-yellow-500/30 transition-colors"
        >
          Keep Active
        </button>

        <button
          onClick={keepActive}
          className="p-1 rounded-lg text-yellow-400/60 hover:text-yellow-300 hover:bg-yellow-500/10 transition-colors"
          aria-label="Dismiss"
        >
          <X size={16} weight="bold" />
        </button>
      </div>
    </div>
  );
};

export default IdleWarningBanner;
