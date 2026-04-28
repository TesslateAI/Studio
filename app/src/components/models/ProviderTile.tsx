import { ArrowRight, CheckCircle2 } from 'lucide-react';
import type { ProviderMeta } from './providers';
import type { ModelInfo } from '../../pages/library/ModelsPage';

export type ProviderTileStatus = 'connected' | 'available' | 'builtin' | 'locked';

interface ProviderTileProps {
  meta: ProviderMeta;
  /** Public-facing description from the provider registry — appears as the tile tagline. */
  tagline: string;
  status: ProviderTileStatus;
  modelCount: number;
  /** Two or three model names to show in the preview slab. */
  sampleModels: ModelInfo[];
  /** Cheapest pricing across this provider's models, in USD per 1M tokens. */
  cheapestPrice: { input: number; output: number } | null;
  onClick: () => void;
}

function formatCreditsPerMillion(usdPer1M: number): string {
  const credits = usdPer1M * 100;
  if (credits === 0) return '0';
  if (Number.isInteger(credits)) return credits.toLocaleString();
  return credits.toFixed(1);
}

function shortName(model: ModelInfo): string {
  if (model.name.includes('/')) {
    const last = model.name.split('/').pop();
    return last || model.name;
  }
  return model.name;
}

export function ProviderTile({
  meta,
  tagline,
  status,
  modelCount,
  sampleModels,
  cheapestPrice,
  onClick,
}: ProviderTileProps) {
  const ctaLabel =
    status === 'connected' || status === 'builtin' ? 'Manage' : status === 'locked' ? 'Upgrade' : 'Connect';

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${ctaLabel} ${meta.name}`}
      className="group relative flex h-full w-full flex-col overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] text-left motion-safe:transition-colors hover:border-[var(--border-hover)] hover:bg-[var(--surface-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)]"
    >
      {/* Header — brand chip + name + status */}
      <div className="flex items-center gap-2.5 px-4 pt-4 pb-3">
        <div
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md"
          style={{ backgroundColor: `${meta.brandColor}1a` }}
          aria-hidden="true"
        >
          <span
            className="block h-5 w-5"
            style={{
              backgroundColor: meta.brandColor,
              maskImage: `url("${meta.iconUrl}")`,
              WebkitMaskImage: `url("${meta.iconUrl}")`,
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
          <span className="truncate text-sm font-semibold text-[var(--text)]">{meta.name}</span>
          <StatusPill status={status} />
        </div>
      </div>

      {/* Tagline */}
      <p className="px-4 pb-3 text-[11.5px] leading-snug text-[var(--text-muted)] line-clamp-2">
        {tagline}
      </p>

      {/* Preview slab — show, don't tell */}
      <div className="mx-3 mb-3 flex-1">
        <div className="flex h-full flex-col gap-1.5 rounded-md bg-[var(--bg)] p-2.5 ring-1 ring-[var(--border)]">
          {sampleModels.length === 0 ? (
            <div className="flex flex-1 items-center justify-center py-2">
              <span className="text-[10.5px] text-[var(--text-subtle)]">
                No models yet
              </span>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-1">
                {sampleModels.slice(0, 3).map((m) => (
                  <span
                    key={m.id}
                    className="truncate rounded bg-[var(--surface)] px-1.5 py-px font-mono text-[10px] text-[var(--text-muted)] ring-1 ring-[var(--border)]"
                  >
                    {shortName(m)}
                  </span>
                ))}
                {modelCount > 3 && (
                  <span className="rounded px-1.5 py-px text-[10px] text-[var(--text-subtle)]">
                    +{modelCount - 3}
                  </span>
                )}
              </div>
              {cheapestPrice && (cheapestPrice.input > 0 || cheapestPrice.output > 0) ? (
                <div className="mt-auto flex items-baseline justify-between text-[10.5px] font-mono">
                  <span className="text-[var(--text-muted)]">
                    from {formatCreditsPerMillion(cheapestPrice.input)}/
                    {formatCreditsPerMillion(cheapestPrice.output)}
                  </span>
                  <span className="text-[var(--text-subtle)]">per 1M</span>
                </div>
              ) : (
                <div className="mt-auto text-[10.5px] font-mono text-[var(--text-subtle)]">
                  Free with subscription
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Footer CTA */}
      <div className="flex items-center justify-between border-t border-[var(--border)] px-4 py-2.5">
        <span className="text-[11px] text-[var(--text-muted)]">
          {modelCount === 0 ? 'No models' : `${modelCount} model${modelCount === 1 ? '' : 's'}`}
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

function StatusPill({ status }: { status: ProviderTileStatus }) {
  if (status === 'connected') {
    return (
      <span className="flex items-center gap-1 text-[11px] font-medium text-emerald-500">
        <CheckCircle2 size={11} className="flex-shrink-0" />
        Connected
      </span>
    );
  }
  if (status === 'builtin') {
    return (
      <span className="flex items-center gap-1 text-[11px] font-medium text-[var(--text-muted)]">
        <span
          className="h-1.5 w-1.5 rounded-full bg-[var(--primary)]"
          aria-hidden="true"
        />
        Built-in
      </span>
    );
  }
  if (status === 'locked') {
    return (
      <span className="flex items-center gap-1 text-[11px] font-medium text-amber-500">
        <span
          className="h-1.5 w-1.5 rounded-full bg-amber-500"
          aria-hidden="true"
        />
        Built-in only
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-[11px] text-[var(--text-muted)]">
      <span className="h-1.5 w-1.5 rounded-full bg-[var(--text-subtle)]" aria-hidden="true" />
      Add key to use
    </span>
  );
}
