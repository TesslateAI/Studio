import { useState } from 'react';
import { ArrowsClockwise, Warning, ChatCircleDots, FirstAid } from '@phosphor-icons/react';
import { PulsingGridSpinner } from './PulsingGridSpinner';
import { StartupLogViewer } from './StartupLogViewer';
import { volumeApi } from '../lib/api';

interface ContainerLoadingOverlayProps {
  phase: string;
  progress: number;
  message: string;
  logs: string[];
  error?: string;
  projectSlug?: string;
  onRetry?: () => void;
  onAskAgent?: (message: string) => void;
  containerPort?: number;
}

export function ContainerLoadingOverlay({
  phase,
  progress,
  message,
  logs,
  error,
  projectSlug,
  onRetry,
  onAskAgent,
  containerPort = 3000,
}: ContainerLoadingOverlayProps) {
  // Volume recovery state — must be before any early returns (React hooks rules)
  const [recovering, setRecovering] = useState(false);
  const [recoverResult, setRecoverResult] = useState<string | null>(null);

  // Health check timeout — container is alive but dev server isn't responding
  const isHealthCheckTimeout = error?.startsWith('HEALTH_CHECK_TIMEOUT:');

  if (error && isHealthCheckTimeout) {
    const displayError = error.replace('HEALTH_CHECK_TIMEOUT:', '');
    return (
      <div className="w-full h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6">
        <div className="flex flex-col items-center gap-4 max-w-md text-center">
          <div className="w-16 h-16 rounded-full bg-[var(--primary)]/20 flex items-center justify-center">
            <ChatCircleDots size={32} className="text-[var(--primary)]" weight="fill" />
          </div>
          <h3 className="text-lg font-semibold text-[var(--text)]">Container needs setup</h3>
          <p className="text-[var(--text)]/60 text-sm">
            {displayError}. Use the agent to get the dev server running.
          </p>

          {onAskAgent && (
            <button
              onClick={() =>
                onAskAgent(
                  `The dev server failed to start. Check its output and restart it on port ${containerPort}.`
                )
              }
              className="flex items-center gap-2 px-5 py-2.5 bg-[var(--primary)] text-white rounded-lg hover:bg-[var(--primary)]/80 transition-colors font-medium"
            >
              <ChatCircleDots size={18} />
              Ask Agent to start it
            </button>
          )}

          {onRetry && (
            <button
              onClick={onRetry}
              className="flex items-center gap-2 px-4 py-2 text-[var(--text)]/60 hover:text-[var(--text)] transition-colors text-sm"
            >
              <ArrowsClockwise size={16} />
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  // Actual task failure error state
  const isVolumeError =
    error &&
    (error.toLowerCase().includes('storage') ||
      error.toLowerCase().includes('volume') ||
      error.toLowerCase().includes('unavailable') ||
      error.toLowerCase().includes('unreachable'));

  const handleRecover = async () => {
    if (!projectSlug) return;
    setRecovering(true);
    setRecoverResult(null);
    try {
      const result = await volumeApi.recover(projectSlug);
      setRecoverResult(`Recovered to node ${result.node}. Retrying start...`);
      // Auto-retry after successful recovery
      setTimeout(() => {
        onRetry?.();
        setRecovering(false);
        setRecoverResult(null);
      }, 1500);
    } catch (err) {
      setRecoverResult(`Recovery failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
      setRecovering(false);
    }
  };

  if (error) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6">
        <div className="flex flex-col items-center gap-4 max-w-md text-center">
          <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center">
            <Warning size={32} className="text-red-500" weight="fill" />
          </div>
          <h3 className="text-lg font-semibold text-[var(--text)]">Container Failed to Start</h3>
          <p className="text-[var(--text)]/60 text-sm">{error}</p>

          {recoverResult && <p className="text-[var(--text)]/70 text-sm">{recoverResult}</p>}

          <div className="flex items-center gap-3">
            {isVolumeError && projectSlug && (
              <button
                onClick={handleRecover}
                disabled={recovering}
                className="flex items-center gap-2 px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-500 transition-colors disabled:opacity-50"
              >
                <FirstAid size={18} />
                {recovering ? 'Recovering...' : 'Recover Storage'}
              </button>
            )}
            {onRetry && (
              <button
                onClick={onRetry}
                className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] text-white rounded-lg hover:bg-[var(--primary)]/80 transition-colors"
              >
                <ArrowsClockwise size={18} />
                Retry
              </button>
            )}
          </div>

          {/* Show logs on error for debugging */}
          {logs.length > 0 && (
            <StartupLogViewer logs={logs.slice(-10)} maxHeight="h-32" className="mt-4" />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6">
      <div className="flex flex-col items-center gap-6 w-full max-w-lg">
        {/* Spinner */}
        <PulsingGridSpinner size={80} />

        {/* Phase message */}
        <div className="text-center">
          <h3 className="text-lg font-medium text-[var(--text)] mb-1">{message}</h3>
          <p className="text-sm text-[var(--text)]/50 capitalize">{phase.replace(/_/g, ' ')}</p>
        </div>

        {/* Progress bar */}
        <div className="w-full">
          <div className="flex justify-between text-xs text-[var(--text)]/50 mb-2">
            <span>Progress</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full h-2 bg-[var(--text)]/10 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-[var(--primary)] to-orange-400 rounded-full transition-all duration-300 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Terminal-style log output */}
        <StartupLogViewer logs={logs} />

        {/* Helpful tip */}
        <p className="text-xs text-[var(--text)]/30 text-center">
          This may take a moment for first-time setup. We're installing dependencies and starting
          your dev server.
        </p>
      </div>
    </div>
  );
}
