/**
 * Persistent Config tab — one card per service / internal container.
 *
 * Reads the architecture graph autonomously via `GET /api/projects/{id}/config`
 * and refreshes on graph events (`architecture-node-added`, `node-config-resumed`,
 * `node-config-cancelled`, `secret-rotated`, `containers-restarting`,
 * `user-input-required`). The agent never opens or scrolls this tab — it just
 * reflects whatever the graph says.
 *
 * Cards are sorted: external services first (Stripe, Supabase, REST APIs),
 * then internal containers, alphabetical within each group.
 */

import { useCallback, useEffect, useState } from 'react';
import { ArrowsClockwise, SlidersHorizontal } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import { nodeConfigApi } from '../../lib/api';
import type { ProjectConfigService } from '../../types/nodeConfig';
import { nodeConfigEvents } from '../../utils/nodeConfigEvents';
import { ConfigCard } from './ConfigCard';

export interface ConfigPanelProps {
  projectId: string;
}

export function ConfigPanel({ projectId }: ConfigPanelProps) {
  const [services, setServices] = useState<ProjectConfigService[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    if (!projectId) return;
    try {
      const data = await nodeConfigApi.getProjectConfig(projectId);
      setServices(data.services);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load config';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setIsLoading(true);
    void refetch();
  }, [refetch]);

  // Refresh on graph-level events.
  useEffect(() => {
    const unsubs: Array<() => void> = [];
    unsubs.push(nodeConfigEvents.on('architecture-node-added', () => void refetch()));
    unsubs.push(nodeConfigEvents.on('node-config-resumed', () => void refetch()));
    unsubs.push(nodeConfigEvents.on('node-config-cancelled', () => void refetch()));
    unsubs.push(nodeConfigEvents.on('secret-rotated', () => void refetch()));
    unsubs.push(nodeConfigEvents.on('user-input-required', () => void refetch()));
    unsubs.push(
      nodeConfigEvents.on('containers-restarting', (payload) => {
        const names = payload.container_names.join(', ') || 'containers';
        toast(`Restarting ${names}…`, { icon: '🔄' });
        void refetch();
      })
    );
    return () => {
      for (const unsub of unsubs) unsub();
    };
  }, [refetch]);

  return (
    <div className="w-full h-full flex flex-col overflow-hidden bg-[var(--bg)]">
      {/* Header */}
      <div className="flex items-center justify-between h-10 px-4 border-b border-[var(--border)] bg-[var(--surface)] flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <SlidersHorizontal size={13} weight="bold" className="text-[var(--text-muted)] flex-shrink-0" />
          <h2 className="text-[12px] font-medium text-[var(--text)] truncate">Config</h2>
          <span className="text-[10px] text-[var(--text-muted)]">
            {services.length} {services.length === 1 ? 'service' : 'services'}
          </span>
        </div>
        <button
          type="button"
          onClick={() => void refetch()}
          className="btn"
          aria-label="Refresh"
          title="Refresh"
        >
          <ArrowsClockwise size={12} weight="bold" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {isLoading && services.length === 0 && (
          <div className="text-[11px] text-[var(--text-muted)]">Loading config…</div>
        )}

        {error && (
          <div className="text-[11px] text-red-400 px-3 py-2 bg-red-500/10 border border-red-500/30 rounded-[var(--radius-small)]">
            {error}
          </div>
        )}

        {!isLoading && !error && services.length === 0 && (
          <div className="text-[11px] text-[var(--text-muted)] px-3 py-6 text-center bg-[var(--surface)] border border-dashed border-[var(--border)] rounded-[var(--radius)]">
            No services configured yet. Ask the agent to add one
            (e.g. "add Stripe") or drop a card here from the Architecture tab.
          </div>
        )}

        {services.map((service) => (
          <ConfigCard
            key={service.container_id}
            projectId={projectId}
            service={service}
            onSaved={() => void refetch()}
          />
        ))}
      </div>
    </div>
  );
}
