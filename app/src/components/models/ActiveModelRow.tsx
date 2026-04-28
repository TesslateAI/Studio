import { Trash2 } from 'lucide-react';
import { ToggleLeft, ToggleRight } from '@phosphor-icons/react';
import type { ProviderMeta } from './providers';
import type { ModelInfo } from '../../pages/library/ModelsPage';

interface ActiveModelRowProps {
  model: ModelInfo;
  providerMeta: ProviderMeta;
  onToggle: (id: string, isCurrentlyDisabled: boolean) => void;
  /** Provided only for custom models so the row can render a delete affordance. */
  onDelete?: (customId: string) => void;
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

export function ActiveModelRow({
  model,
  providerMeta,
  onToggle,
  onDelete,
}: ActiveModelRowProps) {
  const isDisabled = !!model.disabled;
  const showPrice = model.pricing && (model.pricing.input > 0 || model.pricing.output > 0);

  return (
    <li
      className={`group flex items-center gap-3 px-4 py-3 hover:bg-[var(--surface-hover)] ${
        isDisabled ? 'opacity-60' : ''
      }`}
    >
      {/* Brand chip */}
      <div
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md"
        style={{ backgroundColor: `${providerMeta.brandColor}1a` }}
        aria-hidden="true"
      >
        <span
          className="block h-4 w-4"
          style={{
            backgroundColor: providerMeta.brandColor,
            maskImage: `url("${providerMeta.iconUrl}")`,
            WebkitMaskImage: `url("${providerMeta.iconUrl}")`,
            maskRepeat: 'no-repeat',
            WebkitMaskRepeat: 'no-repeat',
            maskSize: 'contain',
            WebkitMaskSize: 'contain',
            maskPosition: 'center',
            WebkitMaskPosition: 'center',
          }}
        />
      </div>

      {/* Name + provider */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-[var(--text)]">{shortName(model)}</span>
          {model.health === 'unhealthy' && (
            <span className="rounded bg-red-500/10 px-1.5 py-px text-[9px] font-medium uppercase tracking-wide text-red-500">
              Down
            </span>
          )}
          {model.source === 'custom' && (
            <span className="rounded bg-[var(--surface)] px-1.5 py-px text-[9px] font-medium uppercase tracking-wide text-[var(--text-subtle)] ring-1 ring-[var(--border)]">
              Custom
            </span>
          )}
        </div>
        <p className="truncate text-[11px] text-[var(--text-muted)]">{providerMeta.name}</p>
      </div>

      {/* Pricing */}
      <div className="hidden flex-shrink-0 text-right sm:block">
        {showPrice ? (
          <div className="font-mono text-[10.5px] text-[var(--text-subtle)]">
            <span className="text-[var(--text-muted)]">
              {formatCreditsPerMillion(model.pricing!.input)}/
              {formatCreditsPerMillion(model.pricing!.output)}
            </span>
            <span className="ml-1">/1M</span>
          </div>
        ) : (
          <div className="text-[10.5px] text-[var(--text-subtle)]">—</div>
        )}
      </div>

      {/* Actions */}
      <div className="flex flex-shrink-0 items-center gap-1">
        {model.custom_id && onDelete && (
          <button
            type="button"
            onClick={() => onDelete(model.custom_id!)}
            className="rounded p-1.5 text-[var(--text-muted)] opacity-0 transition-opacity hover:bg-red-500/10 hover:text-red-500 group-hover:opacity-100 focus:opacity-100"
            aria-label={`Remove ${shortName(model)}`}
            title="Remove"
          >
            <Trash2 size={14} />
          </button>
        )}
        <button
          type="button"
          onClick={() => onToggle(model.id, isDisabled)}
          className="text-[var(--text-muted)] hover:text-[var(--text)]"
          aria-label={isDisabled ? `Enable ${shortName(model)}` : `Disable ${shortName(model)}`}
          title={isDisabled ? 'Enable' : 'Disable'}
        >
          {isDisabled ? (
            <ToggleLeft size={20} />
          ) : (
            <ToggleRight size={20} className="text-[var(--primary)]" />
          )}
        </button>
      </div>
    </li>
  );
}
