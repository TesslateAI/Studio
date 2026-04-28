import { ArrowsClockwise, Warning } from '@phosphor-icons/react';
import { PulsingGridSpinner } from '../PulsingGridSpinner';
import type { IframeHealthPhase } from '../../hooks/useIframeHealth';

export interface AppPreviewOverlayProps {
  phase: Exclude<IframeHealthPhase, 'healthy'>;
  appName?: string;
  statusCode?: number | null;
  error?: string | null;
  onRetry?: () => void;
}

/**
 * Overlay rendered while the apps preview iframe is not yet ready.
 * Mirrors the builder-mode `ContainerLoadingOverlay` UX (spinner +
 * friendly message during install; distinct error card for non-startup
 * failures) without dragging in the project-specific recovery flows.
 */
export function AppPreviewOverlay({
  phase,
  appName,
  statusCode,
  error,
  onRetry,
}: AppPreviewOverlayProps) {
  if (phase === 'error') {
    return (
      <div
        className="w-full h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6"
        data-testid="app-preview-error"
      >
        <div className="flex flex-col items-center gap-4 max-w-md text-center">
          <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center">
            <Warning size={32} className="text-red-500" weight="fill" />
          </div>
          <h3 className="text-lg font-semibold text-[var(--text)]">
            {appName ? `${appName} couldn't be reached` : 'App unavailable'}
          </h3>
          <p className="text-[var(--text)]/60 text-sm">
            {error ?? 'The app responded with an unexpected error.'}
            {statusCode ? ` (HTTP ${statusCode})` : ''}
          </p>
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
      </div>
    );
  }

  // installing | checking | idle — all render the same friendly waiting UI.
  // Idle effectively means "not enabled yet" but is harmless to render.
  return (
    <div
      className="w-full h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6"
      data-testid="app-preview-installing"
    >
      <div className="flex flex-col items-center gap-6 w-full max-w-md">
        <PulsingGridSpinner size={72} />
        <div className="text-center">
          <h3 className="text-lg font-medium text-[var(--text)] mb-1">
            {appName ? `Starting ${appName}…` : 'Starting app…'}
          </h3>
          <p className="text-sm text-[var(--text)]/50">
            Installing dependencies and waking the runtime.
          </p>
        </div>
        <p className="text-xs text-[var(--text)]/30 text-center">
          First-time installs can take a moment. This will refresh automatically when ready.
        </p>
      </div>
    </div>
  );
}

export default AppPreviewOverlay;
