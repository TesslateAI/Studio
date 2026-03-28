import { Terminal, Monitor } from '@phosphor-icons/react';
import { StartupLogViewer } from './StartupLogViewer';
import type { ComputeTier } from '../types/project';

export interface NoComputePlaceholderProps {
  onStart?: () => void;
  variant: 'terminal' | 'preview';
  computeTier?: ComputeTier;
  isStarting?: boolean;
  startupProgress?: number;
  startupMessage?: string;
  startupLogs?: string[];
  startupError?: string;
  onRetry?: () => void;
  onAskAgent?: (msg: string) => void;
  containerPort?: number;
}

export function NoComputePlaceholder({
  onStart,
  variant,
  computeTier,
  isStarting,
  startupProgress,
  startupMessage,
  startupLogs,
  startupError,
  onRetry,
  onAskAgent,
  containerPort = 3000,
}: NoComputePlaceholderProps) {
  const accessLabel = variant === 'terminal' ? 'terminal access' : 'live preview';

  // Starting state — show progress + logs
  if (isStarting) {
    // Error during startup
    if (startupError) {
      const isHealthCheck = startupError.startsWith('HEALTH_CHECK_TIMEOUT:');
      const displayError = isHealthCheck
        ? startupError.replace('HEALTH_CHECK_TIMEOUT:', '')
        : startupError;
      return (
        <div className="h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6">
          <div className="flex flex-col items-center gap-4 max-w-lg text-center">
            <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center">
              <Terminal size={32} className="text-red-400" />
            </div>
            <h3 className="text-lg font-semibold text-[var(--text)]">
              {isHealthCheck ? 'Container needs setup' : 'Failed to Start'}
            </h3>
            <p className="text-[var(--text)]/60 text-sm">{displayError}</p>

            <div className="flex items-center gap-3">
              {onAskAgent && isHealthCheck && (
                <button
                  onClick={() =>
                    onAskAgent(
                      `The dev server failed to start. Check its output and restart it on port ${containerPort}.`
                    )
                  }
                  className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] text-white rounded-lg hover:bg-[var(--primary)]/80 transition-colors text-sm font-medium"
                >
                  Ask Agent
                </button>
              )}
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="flex items-center gap-2 px-4 py-2 text-[var(--text)]/60 hover:text-[var(--text)] transition-colors text-sm"
                >
                  Retry
                </button>
              )}
            </div>

            {startupLogs && startupLogs.length > 0 && (
              <StartupLogViewer logs={startupLogs.slice(-10)} maxHeight="h-32" />
            )}
          </div>
        </div>
      );
    }

    return (
      <div className="h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6">
        <div className="flex flex-col items-center gap-3 max-w-lg text-center">
          <div className="w-12 h-12 rounded-full bg-[var(--primary)]/10 flex items-center justify-center animate-pulse">
            <Terminal size={24} className="text-[var(--primary)]" />
          </div>
          <p className="text-sm font-medium text-[var(--text)]">Starting compute environment...</p>
          {startupProgress !== undefined && (
            <div className="w-48 h-1.5 bg-[var(--text)]/10 rounded-full overflow-hidden">
              <div
                className="h-full bg-[var(--primary)] rounded-full transition-all"
                style={{ width: `${startupProgress}%` }}
              />
            </div>
          )}
          {startupMessage && <p className="text-xs text-[var(--text)]/50">{startupMessage}</p>}

          {startupLogs && startupLogs.length > 0 && (
            <StartupLogViewer logs={startupLogs} maxHeight="h-36" className="mt-2" />
          )}
        </div>
      </div>
    );
  }

  // Determine icon, title, description, and button label based on state
  let icon = <Monitor size={32} className="text-emerald-400" />;
  let iconBg = 'bg-emerald-500/10';
  let title = 'Files available';
  let description = `Start the environment for ${accessLabel}.`;
  let buttonLabel = 'Start Environment';

  if (computeTier === 'ephemeral') {
    icon = <Terminal size={32} className="text-[var(--primary)]" />;
    iconBg = 'bg-[var(--primary)]/10';
    title = 'Agent commands running';
    description = `Start full environment for ${accessLabel}.`;
    buttonLabel = 'Start Environment';
  }

  return (
    <div className="h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6">
      <div className="flex flex-col items-center gap-4 max-w-md text-center">
        <div className={`w-16 h-16 rounded-full ${iconBg} flex items-center justify-center`}>
          {icon}
        </div>
        <h3 className="text-lg font-semibold text-[var(--text)]">{title}</h3>
        <p className="text-[var(--text)]/60 text-sm">{description}</p>
        {onStart && buttonLabel && (
          <button
            onClick={onStart}
            className="px-5 py-2.5 bg-[var(--primary)] text-white rounded-lg hover:opacity-80 transition font-medium"
          >
            {buttonLabel}
          </button>
        )}
      </div>
    </div>
  );
}
