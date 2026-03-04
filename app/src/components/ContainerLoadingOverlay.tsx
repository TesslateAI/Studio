import { useEffect, useRef } from 'react';
import { PulsingGridSpinner } from './PulsingGridSpinner';
import { ArrowsClockwise, Warning, ChatCircleDots } from '@phosphor-icons/react';

interface ContainerLoadingOverlayProps {
  phase: string;
  progress: number;
  message: string;
  logs: string[];
  error?: string;
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
  onRetry,
  onAskAgent,
  containerPort = 3000,
}: ContainerLoadingOverlayProps) {
  const logsContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll logs to bottom when new logs arrive
  useEffect(() => {
    if (logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [logs]);

  // Health check timeout — container is alive but dev server isn't responding
  const isHealthCheckTimeout = error?.startsWith('HEALTH_CHECK_TIMEOUT:');

  if (error && isHealthCheckTimeout) {
    const displayError = error.replace('HEALTH_CHECK_TIMEOUT:', '');
    return (
      <div className="w-full h-full flex flex-col items-center justify-center bg-[#0a0a0a] p-6">
        <div className="flex flex-col items-center gap-4 max-w-md text-center">
          <div className="w-16 h-16 rounded-full bg-[var(--primary)]/20 flex items-center justify-center">
            <ChatCircleDots size={32} className="text-[var(--primary)]" weight="fill" />
          </div>
          <h3 className="text-lg font-semibold text-white">Container needs setup</h3>
          <p className="text-white/60 text-sm">
            {displayError}. Use the agent to get the dev server running.
          </p>

          {onAskAgent && (
            <button
              onClick={() =>
                onAskAgent(
                  `Use the running tmux process to get this up and running. The port for the preview url is ${containerPort}.`
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
              className="flex items-center gap-2 px-4 py-2 text-white/60 hover:text-white transition-colors text-sm"
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
  if (error) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center bg-[#0a0a0a] p-6">
        <div className="flex flex-col items-center gap-4 max-w-md text-center">
          <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center">
            <Warning size={32} className="text-red-500" weight="fill" />
          </div>
          <h3 className="text-lg font-semibold text-white">Container Failed to Start</h3>
          <p className="text-white/60 text-sm">{error}</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] text-white rounded-lg hover:bg-[var(--primary)]/80 transition-colors"
            >
              <ArrowsClockwise size={18} />
              Retry
            </button>
          )}

          {/* Show logs on error for debugging */}
          {logs.length > 0 && (
            <div className="w-full mt-4">
              <p className="text-xs text-white/40 mb-2 text-left">Logs:</p>
              <div className="bg-[#111] rounded-lg border border-white/10 p-3 max-h-32 overflow-y-auto">
                <pre className="text-xs font-mono text-white/60 whitespace-pre-wrap">
                  {logs.slice(-10).join('\n')}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full flex flex-col items-center justify-center bg-[#0a0a0a] p-6">
      <div className="flex flex-col items-center gap-6 w-full max-w-lg">
        {/* Spinner */}
        <PulsingGridSpinner size={80} />

        {/* Phase message */}
        <div className="text-center">
          <h3 className="text-lg font-medium text-white mb-1">{message}</h3>
          <p className="text-sm text-white/50 capitalize">{phase.replace(/_/g, ' ')}</p>
        </div>

        {/* Progress bar */}
        <div className="w-full">
          <div className="flex justify-between text-xs text-white/50 mb-2">
            <span>Progress</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full h-2 bg-white/10 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-[var(--primary)] to-orange-400 rounded-full transition-all duration-300 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Terminal-style log output */}
        <div className="w-full">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-white/40 font-mono">Startup logs</span>
          </div>
          <div
            ref={logsContainerRef}
            className="bg-[#111] rounded-lg border border-white/10 p-4 h-48 overflow-y-auto font-mono text-xs"
          >
            {logs.length === 0 ? (
              <div className="text-white/30 animate-pulse">Waiting for logs...</div>
            ) : (
              logs.map((log, index) => (
                <div
                  key={index}
                  className={`mb-1 ${
                    log.toLowerCase().includes('error')
                      ? 'text-red-400'
                      : log.toLowerCase().includes('warn')
                      ? 'text-yellow-400'
                      : log.toLowerCase().includes('success') || log.toLowerCase().includes('ready')
                      ? 'text-green-400'
                      : 'text-white/70'
                  }`}
                >
                  <span className="text-white/30 mr-2">{`>`}</span>
                  {log}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Helpful tip */}
        <p className="text-xs text-white/30 text-center">
          This may take a moment for first-time setup. We're installing dependencies and starting your dev server.
        </p>
      </div>
    </div>
  );
}
