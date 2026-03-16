import { useEffect, useRef } from 'react';

interface StartupLogViewerProps {
  logs: string[];
  maxHeight?: string;
  className?: string;
}

export function StartupLogViewer({ logs, maxHeight = 'h-48', className = '' }: StartupLogViewerProps) {
  const logsContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className={`w-full ${className}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs text-[var(--text)]/40 font-mono">Startup logs</span>
      </div>
      <div
        ref={logsContainerRef}
        className={`bg-[var(--surface)] rounded-lg border border-[var(--border)] p-4 ${maxHeight} overflow-y-auto font-mono text-xs`}
      >
        {logs.length === 0 ? (
          <div className="text-[var(--text)]/30 animate-pulse">Waiting for logs...</div>
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
                  : 'text-[var(--text)]/70'
              }`}
            >
              <span className="text-[var(--text)]/30 mr-2">{`>`}</span>
              {log}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
