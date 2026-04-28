import { CheckCircle, MapPin, ArrowSquareOut } from '@phosphor-icons/react';
import { DEPLOYMENT_PROVIDERS } from '../../lib/deployment-providers';
import { COMING_SOON_PROVIDERS } from '../../lib/utils';

export interface ProviderQuickGridProps {
  connectedProviders: Set<string>;
  onGraphProviders: Set<string>;
  onChipClick: (provider: string) => void;
}

export function ProviderQuickGrid({
  connectedProviders,
  onGraphProviders,
  onChipClick,
}: ProviderQuickGridProps) {
  const entries = Object.entries(DEPLOYMENT_PROVIDERS);
  // Sort: connected first, then on-graph, then alphabetical by display name.
  const sorted = [...entries].sort(([aKey, aCfg], [bKey, bCfg]) => {
    const aConnected = connectedProviders.has(aKey) ? 0 : 1;
    const bConnected = connectedProviders.has(bKey) ? 0 : 1;
    if (aConnected !== bConnected) return aConnected - bConnected;
    const aOnGraph = onGraphProviders.has(aKey) ? 0 : 1;
    const bOnGraph = onGraphProviders.has(bKey) ? 0 : 1;
    if (aOnGraph !== bOnGraph) return aOnGraph - bOnGraph;
    return aCfg.displayName.localeCompare(bCfg.displayName);
  });

  return (
    <div className="grid grid-cols-2 gap-2">
      {sorted.map(([key, cfg]) => {
        const connected = connectedProviders.has(key);
        const onGraph = onGraphProviders.has(key);
        const isComingSoon = COMING_SOON_PROVIDERS.includes(key.toLowerCase());

        return (
          <button
            key={key}
            type="button"
            onClick={() => {
              if (isComingSoon) return;
              onChipClick(key);
            }}
            disabled={isComingSoon}
            className={`group relative flex items-center gap-2.5 rounded-[var(--radius-medium)] border px-2.5 py-2 text-left transition-colors ${
              isComingSoon
                ? 'border-[var(--border)] bg-[var(--surface)] opacity-50 cursor-not-allowed'
                : connected
                  ? 'border-[var(--border-hover)] bg-[var(--surface-hover)] hover:border-[var(--primary)]'
                  : 'border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-hover)] hover:bg-[var(--surface-hover)]'
            }`}
            title={
              isComingSoon
                ? `${cfg.displayName} — coming soon`
                : connected
                  ? `Deploy to ${cfg.displayName}`
                  : `Connect ${cfg.displayName}`
            }
          >
            <span
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-small)] text-sm font-bold ${cfg.textColor}`}
              style={{ backgroundColor: cfg.color }}
              aria-hidden="true"
            >
              {cfg.icon}
            </span>
            <span className="flex-1 min-w-0">
              <span className="block text-[11px] font-semibold text-[var(--text)] truncate">
                {cfg.displayName}
              </span>
              <span className="flex items-center gap-1 text-[9.5px] text-[var(--text-subtle)]">
                {connected ? (
                  <>
                    <CheckCircle
                      size={10}
                      weight="fill"
                      className="text-[var(--status-success)]"
                    />
                    <span>Connected</span>
                  </>
                ) : isComingSoon ? (
                  <span>Coming soon</span>
                ) : (
                  <>
                    <ArrowSquareOut size={10} weight="bold" />
                    <span>Connect</span>
                  </>
                )}
                {onGraph && (
                  <>
                    <span className="text-[var(--border)]">·</span>
                    <MapPin size={10} weight="fill" className="text-[var(--primary)]" />
                    <span className="text-[var(--primary)]">On graph</span>
                  </>
                )}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
