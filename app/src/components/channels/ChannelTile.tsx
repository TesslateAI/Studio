import { ArrowRight, CheckCircle2, AlertCircle } from 'lucide-react';
import type { ChannelPlatform } from './platforms';
import type { ChannelConfig } from '../../lib/api';

interface ChannelTileProps {
  platform: ChannelPlatform;
  /** All connected channels for this platform (>=0). Empty = "Not connected". */
  connections: ChannelConfig[];
  onClick: () => void;
}

export function ChannelTile({ platform, connections, onClick }: ChannelTileProps) {
  const Preview = platform.preview;
  const activeCount = connections.filter((c) => c.is_active).length;
  const hasInactive = connections.some((c) => !c.is_active);

  let statusLabel: string;
  let statusTone: 'idle' | 'connected' | 'warning';
  if (activeCount > 0) {
    statusLabel = activeCount === 1 ? 'Connected' : `${activeCount} connected`;
    statusTone = 'connected';
  } else if (hasInactive) {
    statusLabel = 'Inactive';
    statusTone = 'warning';
  } else {
    statusLabel = 'Not connected';
    statusTone = 'idle';
  }

  const ctaLabel = activeCount > 0 ? 'Manage' : 'Connect';

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${ctaLabel} ${platform.name}`}
      className="group relative flex h-full w-full flex-col overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] text-left motion-safe:transition-colors hover:border-[var(--border-hover)] hover:bg-[var(--surface-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)]"
    >
      {/* Header — brand color accent + name + status */}
      <div className="flex items-center gap-2.5 px-4 pt-4 pb-3">
        <div
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md"
          style={{ backgroundColor: `${platform.brandColor}1a` }}
          aria-hidden="true"
        >
          <span
            className="block h-5 w-5"
            style={{
              backgroundColor: platform.brandColor,
              maskImage: `url("${platform.iconUrl}")`,
              WebkitMaskImage: `url("${platform.iconUrl}")`,
              maskRepeat: 'no-repeat',
              WebkitMaskRepeat: 'no-repeat',
              maskSize: 'contain',
              WebkitMaskSize: 'contain',
              maskPosition: 'center',
              WebkitMaskPosition: 'center',
            }}
          />
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm font-semibold text-[var(--text)]">{platform.name}</span>
          <StatusPill tone={statusTone} label={statusLabel} />
        </div>
      </div>

      {/* Tagline */}
      <p className="px-4 pb-3 text-[11.5px] leading-snug text-[var(--text-muted)]">
        {platform.tagline}
      </p>

      {/* Preview slab — show, don't tell */}
      <div className="mx-3 mb-3 flex-1">
        <div className="rounded-md bg-[var(--bg)] p-2 ring-1 ring-[var(--border)]">
          <Preview />
        </div>
      </div>

      {/* Footer CTA */}
      <div className="flex items-center justify-between border-t border-[var(--border)] px-4 py-2.5">
        <span className="text-[11px] text-[var(--text-muted)]">
          {platform.credentials.length === 0
            ? 'No credentials needed'
            : `${platform.credentials.length} field${platform.credentials.length === 1 ? '' : 's'}`}
        </span>
        <span className="flex items-center gap-1 text-[12px] font-semibold text-[var(--text)]">
          {ctaLabel}
          <ArrowRight
            size={14}
            className="motion-safe:transition-transform group-hover:translate-x-0.5"
          />
        </span>
      </div>
    </button>
  );
}

function StatusPill({ tone, label }: { tone: 'idle' | 'connected' | 'warning'; label: string }) {
  if (tone === 'connected') {
    return (
      <span className="flex items-center gap-1 text-[11px] font-medium text-emerald-500">
        <CheckCircle2 size={11} className="flex-shrink-0" />
        {label}
      </span>
    );
  }
  if (tone === 'warning') {
    return (
      <span className="flex items-center gap-1 text-[11px] font-medium text-amber-500">
        <AlertCircle size={11} className="flex-shrink-0" />
        {label}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[11px] text-[var(--text-muted)]">
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--text-subtle)]" aria-hidden="true" />
      {label}
    </span>
  );
}
