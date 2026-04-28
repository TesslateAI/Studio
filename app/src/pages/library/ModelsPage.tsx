import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { LockKeyhole, Plus, Rocket, Search, Server, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import {
  CustomProviderCard,
  CustomProviderModal,
  type CustomProvider,
} from '../../components/settings/CustomProviderComponents';
import { ProviderTile, type ProviderTileStatus } from '../../components/models/ProviderTile';
import { ProviderSetupDrawer } from '../../components/models/ProviderSetupDrawer';
import { ActiveModelRow } from '../../components/models/ActiveModelRow';
import { resolveProviderMeta } from '../../components/models/providers';
import { staggerContainer, staggerItem } from '../../components/cards';
import { marketplaceApi, secretsApi } from '../../lib/api';

// ─── Types ──────────────────────────────────────────────────────────

export interface ModelInfo {
  id: string;
  name: string;
  source: 'system' | 'provider' | 'custom';
  provider: string;
  provider_name?: string;
  pricing: { input: number; output: number } | null;
  available: boolean;
  health?: string | null;
  custom_id?: string;
  disabled?: boolean;
}

export interface ApiKey {
  id: string;
  provider: string;
  auth_type: string;
  key_name: string | null;
  key_preview: string;
  base_url: string | null;
  created_at: string;
  last_used_at: string | null;
}

export interface Provider {
  id: string;
  name: string;
  description: string;
  auth_type: string;
  website: string;
  requires_key: boolean;
  base_url?: string;
  api_type?: string;
}

interface TileEntry {
  provider: Provider;
  /** Only set when this tile represents a user-created custom provider. */
  customProvider?: CustomProvider;
}

interface ModelsPageProps {
  models: ModelInfo[];
  apiKeys: ApiKey[];
  providers: Provider[];
  customProviders: CustomProvider[];
  byokEnabled: boolean | null;
  onToggleModel: (modelId: string, currentlyDisabled: boolean) => void;
  /** Reload api keys + providers list. */
  onReload: () => void;
  /** Reload custom provider list. */
  onReloadProviders: () => void;
  /** Reload models list. */
  onReloadModels: () => void;
}

// ─── Synthetic Tesslate provider ──────────────────────────────────────
//
// The Tesslate (system) tile isn't returned by /api/secrets/providers
// because it doesn't accept a key — we synthesize one so it gets the
// same tile treatment as built-ins.

const TESSLATE_PROVIDER: Provider = {
  id: 'internal',
  name: 'Tesslate',
  description:
    'Frontier and open-source models metered against your subscription credits. No setup required.',
  auth_type: 'none',
  website: 'https://tesslate.com',
  requires_key: false,
};

// ─── Main ModelsPage ────────────────────────────────────────────────

export default function ModelsPage({
  models,
  apiKeys,
  providers,
  customProviders,
  byokEnabled,
  onToggleModel,
  onReload,
  onReloadProviders,
  onReloadModels,
}: ModelsPageProps) {
  const navigate = useNavigate();
  const [activeProviderKey, setActiveProviderKey] = useState<string | null>(null);
  const [showProviderModal, setShowProviderModal] = useState(false);
  const [editingProvider, setEditingProvider] = useState<CustomProvider | null>(null);
  const [search, setSearch] = useState('');
  const [filterProvider, setFilterProvider] = useState<string | null>(null);

  // Build the tile-grid entries: Tesslate first, then built-ins, then custom providers.
  const tileEntries = useMemo<TileEntry[]>(() => {
    const builtIn: TileEntry[] = [TESSLATE_PROVIDER, ...providers].map((p) => ({ provider: p }));
    const custom: TileEntry[] = customProviders.map((cp) => ({
      provider: {
        id: cp.slug,
        name: cp.name,
        description: `Custom ${cp.api_type || 'OpenAI-compatible'} endpoint at ${cp.base_url}`,
        auth_type: 'api_key',
        website: '',
        requires_key: true,
        base_url: cp.base_url,
        api_type: cp.api_type,
      },
      customProvider: cp,
    }));
    return [...builtIn, ...custom];
  }, [providers, customProviders]);

  // Group models by provider for fast lookups.
  const modelsByProvider = useMemo(() => {
    const map: Record<string, ModelInfo[]> = {};
    for (const m of models) {
      const key = m.source === 'system' ? 'internal' : m.provider;
      if (!map[key]) map[key] = [];
      map[key].push(m);
    }
    return map;
  }, [models]);

  const enabledModels = useMemo(() => models.filter((m) => !m.disabled), [models]);

  const activeModels = useMemo(() => {
    let list = enabledModels;
    if (filterProvider) {
      list = list.filter((m) =>
        m.source === 'system' ? filterProvider === 'internal' : m.provider === filterProvider
      );
    }
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (m) => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)
      );
    }
    return list;
  }, [enabledModels, filterProvider, search]);

  // Provider chip filter shows only providers that actually have enabled models.
  const filterChips = useMemo(() => {
    const seen = new Set<string>();
    const chips: { key: string; name: string; count: number }[] = [];
    for (const m of enabledModels) {
      const key = m.source === 'system' ? 'internal' : m.provider;
      if (seen.has(key)) {
        const existing = chips.find((c) => c.key === key);
        if (existing) existing.count += 1;
      } else {
        seen.add(key);
        const meta = resolveProviderMeta(key, m.provider_name);
        chips.push({ key, name: meta.name, count: 1 });
      }
    }
    return chips;
  }, [enabledModels]);

  const computeTileStatus = (
    hasKey: boolean,
    requiresKey: boolean
  ): ProviderTileStatus => {
    if (!requiresKey) return 'builtin';
    if (hasKey) return 'connected';
    if (byokEnabled === false) return 'locked';
    return 'available';
  };

  const computeCheapest = (
    list: ModelInfo[]
  ): { input: number; output: number } | null => {
    let cheapest: { input: number; output: number } | null = null;
    for (const m of list) {
      if (!m.pricing) continue;
      const total = m.pricing.input + m.pricing.output;
      if (
        !cheapest ||
        total < cheapest.input + cheapest.output
      ) {
        cheapest = m.pricing;
      }
    }
    return cheapest;
  };

  const handleTileClick = (entry: TileEntry) => {
    const requiresKey = entry.provider.requires_key;
    if (byokEnabled === false && requiresKey) {
      navigate('/settings/billing');
      return;
    }
    setActiveProviderKey(entry.provider.id);
  };

  const handleDeleteCustomProvider = async (providerId: string) => {
    try {
      await secretsApi.deleteCustomProvider(providerId);
      toast.success('Endpoint removed');
      onReloadProviders();
    } catch {
      toast.error('Failed to remove endpoint');
    }
  };

  const handleDeleteCustomModel = async (customId: string) => {
    try {
      await marketplaceApi.deleteCustomModel(customId);
      toast.success('Model removed');
      onReloadModels();
    } catch {
      toast.error('Failed to remove model');
    }
  };

  const handleProviderChanged = () => {
    onReload();
    onReloadModels();
    onReloadProviders();
  };

  if (byokEnabled === null) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <LoadingSpinner message="Loading models…" size={60} />
      </div>
    );
  }

  const activeEntry = activeProviderKey
    ? tileEntries.find((e) => e.provider.id === activeProviderKey)
    : null;
  const activeMeta = activeEntry
    ? resolveProviderMeta(activeEntry.provider.id, activeEntry.provider.name)
    : null;
  const activeKey = activeEntry
    ? apiKeys.find((k) => k.provider === activeEntry.provider.id)
    : undefined;
  const activeProviderModels = activeEntry
    ? modelsByProvider[activeEntry.provider.id] || []
    : [];

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-8">
        {/* Header */}
        <header className="mb-6">
          <h1 className="text-lg font-semibold text-[var(--text)]">Models</h1>
          <p className="mt-1 max-w-2xl text-[12.5px] leading-relaxed text-[var(--text-muted)]">
            Choose which models power your agents. Bring your own provider keys for direct access,
            or run with the bundled Tesslate models metered against your subscription credits.
          </p>
        </header>

        {/* BYOK upsell banner */}
        {byokEnabled === false && (
          <div className="mb-6 flex items-center gap-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
            <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-amber-500/10">
              <LockKeyhole size={16} className="text-amber-500" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-[var(--text)]">
                Bring your own keys is on paid plans
              </div>
              <p className="text-[11.5px] text-[var(--text-muted)]">
                Use the bundled Tesslate models below. Upgrade to connect OpenAI, Anthropic, and
                custom endpoints with your own keys.
              </p>
            </div>
            <button
              onClick={() => navigate('/settings/billing')}
              className="btn btn-filled btn-sm flex-shrink-0"
            >
              <Rocket size={12} />
              Upgrade
            </button>
          </div>
        )}

        {/* Provider tile grid */}
        <motion.div
          className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
        >
          {tileEntries.map((entry) => {
            const meta = resolveProviderMeta(entry.provider.id, entry.provider.name);
            const list = modelsByProvider[entry.provider.id] || [];
            const hasKey = apiKeys.some((k) => k.provider === entry.provider.id);
            const status = computeTileStatus(hasKey, entry.provider.requires_key);
            return (
              <motion.div key={entry.provider.id} variants={staggerItem}>
                <ProviderTile
                  meta={meta}
                  tagline={entry.provider.description}
                  status={status}
                  modelCount={list.length}
                  sampleModels={list.slice(0, 3)}
                  cheapestPrice={computeCheapest(list)}
                  onClick={() => handleTileClick(entry)}
                />
              </motion.div>
            );
          })}
        </motion.div>

        {/* Active models section */}
        <section className="mt-8">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              Active models
              <span className="ml-2 normal-case tracking-normal text-[var(--text-subtle)]">
                {activeModels.length} of {enabledModels.length}
              </span>
            </h2>
            <div className="flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface)] px-2.5 h-[29px]">
              <Search size={12} className="text-[var(--text-subtle)]" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search active models"
                className="w-32 border-none bg-transparent text-[11.5px] text-[var(--text)] placeholder:text-[var(--text-subtle)] outline-none sm:w-48"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch('')}
                  className="text-[var(--text-subtle)] hover:text-[var(--text)]"
                  aria-label="Clear search"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          </div>

          {filterChips.length > 1 && (
            <div className="mb-3 flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => setFilterProvider(null)}
                className={`btn btn-sm ${filterProvider === null ? 'btn-tab-active' : 'btn-tab'}`}
              >
                All <span className="ml-1 opacity-50">{enabledModels.length}</span>
              </button>
              {filterChips.map((chip) => (
                <button
                  key={chip.key}
                  type="button"
                  onClick={() =>
                    setFilterProvider(filterProvider === chip.key ? null : chip.key)
                  }
                  className={`btn btn-sm ${filterProvider === chip.key ? 'btn-tab-active' : 'btn-tab'}`}
                >
                  {chip.name} <span className="ml-1 opacity-50">{chip.count}</span>
                </button>
              ))}
            </div>
          )}

          {enabledModels.length === 0 ? (
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-4 py-12 text-center">
              <p className="text-[12.5px] text-[var(--text-muted)]">No models enabled yet.</p>
              <p className="mt-1 text-[11px] text-[var(--text-subtle)]">
                Connect a provider above to start enabling models.
              </p>
            </div>
          ) : activeModels.length === 0 ? (
            <p className="py-8 text-center text-[12px] text-[var(--text-muted)]">
              {search ? `No models match "${search}".` : 'No models in this filter.'}
            </p>
          ) : (
            <div className="overflow-hidden rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)]">
              <ul className="divide-y divide-[var(--border)]">
                {activeModels.map((m) => {
                  const providerKey = m.source === 'system' ? 'internal' : m.provider;
                  const meta = resolveProviderMeta(providerKey, m.provider_name);
                  return (
                    <ActiveModelRow
                      key={m.id}
                      model={m}
                      providerMeta={meta}
                      onToggle={onToggleModel}
                      onDelete={m.custom_id ? handleDeleteCustomModel : undefined}
                    />
                  );
                })}
              </ul>
            </div>
          )}
        </section>

        {/* Custom endpoints section */}
        {byokEnabled !== false && (
          <section className="mt-8">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  Custom endpoints
                </h2>
                <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">
                  Connect Ollama, vLLM, or any OpenAI-compatible service running on your own infra.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setEditingProvider(null);
                  setShowProviderModal(true);
                }}
                className="btn btn-sm flex-shrink-0"
              >
                <Plus size={12} />
                Add endpoint
              </button>
            </div>

            {customProviders.length === 0 ? (
              <div className="rounded-[var(--radius)] border border-dashed border-[var(--border)] bg-[var(--surface)] px-4 py-8 text-center">
                <Server size={20} className="mx-auto mb-2 text-[var(--text-subtle)]" />
                <p className="text-[12px] text-[var(--text-muted)]">No custom endpoints yet.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {customProviders.map((cp) => (
                  <CustomProviderCard
                    key={cp.id}
                    provider={cp}
                    onEdit={() => {
                      setEditingProvider(cp);
                      setShowProviderModal(true);
                    }}
                    onDelete={handleDeleteCustomProvider}
                  />
                ))}
              </div>
            )}
          </section>
        )}
      </div>

      {/* Drawer */}
      {activeEntry && activeMeta && (
        <ProviderSetupDrawer
          open
          meta={activeMeta}
          providerId={activeEntry.provider.id}
          requiresKey={activeEntry.provider.requires_key}
          existingKey={activeKey}
          providerModels={activeProviderModels}
          onClose={() => setActiveProviderKey(null)}
          onToggleModel={onToggleModel}
          onChanged={handleProviderChanged}
        />
      )}

      {/* Custom provider modal (create/edit) */}
      {showProviderModal && (
        <CustomProviderModal
          existing={editingProvider}
          onClose={() => {
            setShowProviderModal(false);
            setEditingProvider(null);
          }}
          onSuccess={() => {
            setShowProviderModal(false);
            setEditingProvider(null);
            onReloadProviders();
            onReloadModels();
          }}
        />
      )}
    </div>
  );
}
