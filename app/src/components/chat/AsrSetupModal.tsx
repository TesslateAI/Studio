import { createPortal } from 'react-dom';
import { Microphone, X } from '@phosphor-icons/react';
import type { AsrProgress } from '../../hooks/useAsr';
import type { AsrModelEntry } from '../../lib/asr-prefs';

interface AsrSetupModalProps {
  isOpen: boolean;
  model: AsrModelEntry;
  progress: AsrProgress | null;
  isLoading: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}

export function AsrSetupModal({
  isOpen,
  model,
  progress,
  isLoading,
  error,
  onConfirm,
  onClose,
}: AsrSetupModalProps) {
  if (!isOpen) return null;

  const handleClose = () => {
    if (!isLoading) onClose();
  };

  const percent = progress?.percent ?? 0;
  const progressLabel = progress?.status === 'done'
    ? 'Initializing model…'
    : progress?.file
      ? `Downloading ${progress.file}`
      : 'Preparing…';

  return createPortal(
    <div
      className="fixed inset-0 z-[300] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      onClick={handleClose}
    >
      <div
        className="w-full max-w-md bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start gap-3 px-5 pt-5 pb-4">
          <div className="w-8 h-8 flex-shrink-0 rounded-[var(--radius-medium)] bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center">
            <Microphone size={16} className="text-[var(--text-muted)]" weight="bold" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-semibold text-[var(--text)]">Enable voice input</div>
            <div className="mt-1 text-[11px] text-[var(--text-muted)] leading-relaxed space-y-1.5">
              <p>
                We'll download <span className="text-[var(--text)]">{model.label}</span> (~
                {model.sizeMb} MB) on first use. After that, transcription runs entirely on your
                device.
              </p>
              <p>
                <span className="text-[var(--text)]">Your voice never leaves your computer.</span>{' '}
                Only the resulting text is sent to the agent — the same as if you had typed it.
              </p>
            </div>
          </div>
          {!isLoading && (
            <button
              type="button"
              onClick={handleClose}
              className="btn btn-icon btn-sm flex-shrink-0"
              title="Cancel"
            >
              <X size={14} weight="bold" />
            </button>
          )}
        </div>

        {/* Progress / error region */}
        {isLoading && (
          <div className="px-5 pb-4 space-y-1.5">
            <div className="h-1 rounded-full bg-[var(--surface)] overflow-hidden">
              <div
                className="h-full bg-[var(--primary)] transition-all"
                style={{ width: `${percent}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] text-[var(--text-subtle)]">
              <span className="truncate">{progressLabel}</span>
              <span className="tabular-nums">{percent}%</span>
            </div>
          </div>
        )}

        {error && !isLoading && (
          <div className="mx-5 mb-4 px-3 py-2 rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--surface)] text-[11px] text-[var(--status-error)]">
            {error}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2 px-5 pb-5">
          <button
            type="button"
            onClick={handleClose}
            disabled={isLoading}
            className="btn btn-sm flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isLoading}
            className="btn btn-filled btn-sm flex-1 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? 'Loading…' : 'Download & enable'}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
