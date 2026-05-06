import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Stop, X } from '@phosphor-icons/react';

interface RecordingPanelProps {
  isOpen: boolean;
  isFinalizing: boolean;
  partialTranscript: string;
  level: number;
  elapsedMs: number;
  device: 'webgpu' | 'wasm' | null;
  onStop: () => void;
  onCancel: () => void;
}

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

const BAR_COUNT = 56;

export function RecordingPanel({
  isOpen,
  isFinalizing,
  partialTranscript,
  level,
  elapsedMs,
  device,
  onStop,
  onCancel,
}: RecordingPanelProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const barsRef = useRef<number[]>(Array.from({ length: BAR_COUNT }, () => 0));
  const rafRef = useRef<number | null>(null);
  const levelRef = useRef(level);
  const finalizingRef = useRef(isFinalizing);

  useEffect(() => {
    levelRef.current = level;
  }, [level]);
  useEffect(() => {
    finalizingRef.current = isFinalizing;
  }, [isFinalizing]);

  useEffect(() => {
    if (!isOpen) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let running = true;
    const draw = () => {
      if (!running) return;
      const dpr = window.devicePixelRatio || 1;
      const cssWidth = canvas.clientWidth;
      const cssHeight = canvas.clientHeight;
      if (canvas.width !== cssWidth * dpr) canvas.width = cssWidth * dpr;
      if (canvas.height !== cssHeight * dpr) canvas.height = cssHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssWidth, cssHeight);

      const bars = barsRef.current;
      const incoming = finalizingRef.current ? 0 : Math.min(1, levelRef.current * 4);
      bars.shift();
      bars.push(incoming);

      const gap = 2;
      const barWidth = Math.max(1, (cssWidth - gap * (bars.length - 1)) / bars.length);
      const midY = cssHeight / 2;
      const fillStyle = finalizingRef.current
        ? getCssVar('--text-subtle')
        : getCssVar('--text');

      ctx.fillStyle = fillStyle;
      for (let i = 0; i < bars.length; i++) {
        const v = bars[i];
        const h = Math.max(2, v * cssHeight * 0.85);
        const x = i * (barWidth + gap);
        const y = midY - h / 2;
        ctx.fillRect(x, y, barWidth, h);
      }

      rafRef.current = requestAnimationFrame(draw);
    };
    rafRef.current = requestAnimationFrame(draw);
    return () => {
      running = false;
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return createPortal(
    <div className="fixed inset-x-0 bottom-28 z-[200] flex justify-center px-4 pointer-events-none">
      <div className="pointer-events-auto w-full max-w-xl bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--border)]">
          <span
            className={`w-2 h-2 rounded-full ${
              isFinalizing
                ? 'bg-[var(--text-subtle)]'
                : 'bg-[var(--status-error)] animate-pulse'
            }`}
          />
          <span className="text-[11px] font-medium text-[var(--text)]">
            {isFinalizing ? 'Finalizing' : 'Listening'}
          </span>
          <span className="text-[10px] text-[var(--text-subtle)] tabular-nums">
            {formatElapsed(elapsedMs)}
          </span>
          <span className="flex-1" />
          {device && (
            <span className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)] font-mono">
              {device}
            </span>
          )}
          <button
            type="button"
            onClick={onCancel}
            className="btn btn-icon btn-sm"
            title="Cancel"
          >
            <X size={12} weight="bold" />
          </button>
        </div>

        {/* Body */}
        <div className="px-4 py-3 space-y-3">
          <canvas ref={canvasRef} className="w-full h-10" />

          <div className="min-h-[2.25rem] text-xs text-[var(--text)] leading-relaxed break-words">
            {partialTranscript || (
              <span className="text-[var(--text-subtle)] italic">
                {isFinalizing ? 'Cleaning up transcript…' : 'Start speaking…'}
              </span>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 pt-1">
            <span className="text-[10px] text-[var(--text-subtle)]">
              Audio stays on your device. Only the resulting text is sent.
            </span>
            <button
              type="button"
              onClick={onStop}
              disabled={isFinalizing}
              className="btn btn-filled btn-sm disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              <Stop weight="fill" size={12} />
              {isFinalizing ? 'Finalizing…' : 'Stop'}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

function getCssVar(name: string): string {
  if (typeof document === 'undefined') return '#ffffff';
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || '#ffffff';
}
