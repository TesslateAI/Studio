import { forwardRef, useCallback, useState } from 'react';
import {
  ArrowsClockwise,
  CaretLeft,
  CaretRight,
  DeviceMobile,
  LockSimple,
  Monitor,
  X,
} from '@phosphor-icons/react';
import {
  PreviewPortPicker,
  type PreviewableContainer,
} from '../PreviewPortPicker';

export interface PreviewPaneProps {
  devServerUrl: string | null;
  devServerUrlWithAuth: string | null;
  currentPreviewUrl: string;
  previewableContainers: PreviewableContainer[];
  selectedPreviewContainerId: string | null | undefined;
  onPreviewContainerSwitch: (target: PreviewableContainer) => void;
  onRefresh: () => void;
  onNavigateBack: () => void;
  onNavigateForward: () => void;
  onClose?: () => void;
  onPointerEnter?: () => void;
  onPointerLeave?: () => void;
  placeholder?: React.ReactNode;
  overlay?: React.ReactNode;
  showClose?: boolean;
}

export const PreviewPane = forwardRef<HTMLIFrameElement, PreviewPaneProps>(
  function PreviewPane(
    {
      devServerUrl,
      devServerUrlWithAuth,
      currentPreviewUrl,
      previewableContainers,
      selectedPreviewContainerId,
      onPreviewContainerSwitch,
      onRefresh,
      onNavigateBack,
      onNavigateForward,
      onClose,
      onPointerEnter,
      onPointerLeave,
      placeholder,
      overlay,
      showClose = true,
    },
    iframeRef
  ) {
    const [viewportMode, setViewportMode] = useState<'desktop' | 'mobile'>('desktop');

    const handleViewportToggle = useCallback(() => {
      setViewportMode((m) => (m === 'desktop' ? 'mobile' : 'desktop'));
    }, []);

    // Early placeholder: no compute / no dev server
    if (!devServerUrl && placeholder) {
      return <div className="w-full h-full">{placeholder}</div>;
    }

    if (overlay) {
      return <div className="w-full h-full">{overlay}</div>;
    }

    if (!devServerUrl) {
      return (
        <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)] text-xs">
          Loading preview…
        </div>
      );
    }

    return (
      <div className="w-full h-full flex flex-col overflow-hidden bg-[var(--bg)]">
        {/* Browser chrome */}
        <div className="h-10 bg-[var(--surface)] border-b border-[var(--border)] px-2 flex items-center gap-1.5 flex-shrink-0">
          <div className="flex items-center gap-0.5">
            <button
              onClick={onNavigateBack}
              className="btn btn-icon btn-sm"
              title="Go back"
              aria-label="Go back"
            >
              <CaretLeft size={14} weight="bold" />
            </button>
            <button
              onClick={onNavigateForward}
              className="btn btn-icon btn-sm"
              title="Go forward"
              aria-label="Go forward"
            >
              <CaretRight size={14} weight="bold" />
            </button>
          </div>

          <div className="hidden md:flex flex-1 items-center gap-1.5 h-7 bg-[var(--bg)] border border-[var(--border)] rounded-full px-3 min-w-0">
            <LockSimple
              size={11}
              weight="bold"
              className="text-[var(--text-subtle)] flex-shrink-0"
            />
            <span className="text-[11px] text-[var(--text-muted)] font-mono truncate">
              {currentPreviewUrl || devServerUrl}
            </span>
          </div>

          <div className="flex items-center gap-0.5 ml-auto">
            <PreviewPortPicker
              containers={previewableContainers}
              selectedContainerId={selectedPreviewContainerId ?? null}
              onSelect={onPreviewContainerSwitch}
            />
            <button
              onClick={onRefresh}
              className="btn btn-icon btn-sm"
              title="Refresh"
              aria-label="Refresh"
            >
              <ArrowsClockwise size={14} />
            </button>
            <button
              onClick={handleViewportToggle}
              className={`btn btn-icon btn-sm ${viewportMode === 'mobile' ? 'btn-active text-[var(--primary)]' : ''}`}
              title={
                viewportMode === 'desktop'
                  ? 'Switch to mobile view'
                  : 'Switch to desktop view'
              }
              aria-label="Toggle viewport"
            >
              {viewportMode === 'desktop' ? (
                <DeviceMobile size={14} />
              ) : (
                <Monitor size={14} />
              )}
            </button>
            {showClose && onClose && (
              <button
                onClick={onClose}
                className="btn btn-icon btn-sm"
                title="Close preview"
                aria-label="Close preview"
              >
                <X size={14} weight="bold" />
              </button>
            )}
          </div>
        </div>

        {/* Iframe viewport */}
        <div
          className={`flex-1 relative overflow-auto ${
            viewportMode === 'mobile'
              ? 'bg-[var(--bg)] flex items-center justify-center'
              : 'bg-white'
          }`}
          onMouseEnter={onPointerEnter}
          onMouseLeave={onPointerLeave}
        >
          <div
            className={
              viewportMode === 'mobile'
                ? 'w-[375px] h-[667px] border border-[var(--border)] rounded-[var(--radius)] overflow-hidden flex-shrink-0 bg-white'
                : 'w-full h-full'
            }
          >
            <iframe
              ref={iframeRef}
              id="preview-iframe"
              src={devServerUrlWithAuth || devServerUrl}
              className="w-full h-full"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
              title="Project preview"
            />
          </div>
        </div>
      </div>
    );
  }
);

export default PreviewPane;
