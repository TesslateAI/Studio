import { useCallback, useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import {
  Plug,
  Plus,
  ArrowsClockwise,
  LinkBreak,
  Sliders,
  CheckCircle,
  Circle,
} from '@phosphor-icons/react';
import { marketplaceApi } from '../../lib/api';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { runOAuthPopup } from '../../components/connectors/ConnectorOAuthPopup';
import { AddCustomConnectorModal } from '../../components/connectors/AddCustomConnectorModal';
import {
  ConnectorPermissionsDrawer,
  type ConnectorTool,
} from '../../components/connectors/ConnectorPermissionsDrawer';

interface CatalogEntry {
  id: string;
  slug: string;
  name: string;
  description: string;
  icon?: string | null;
  icon_url?: string | null;
  category?: string | null;
  config: Record<string, any>;
}

interface InstalledConfig {
  id: string;
  marketplace_agent_id?: string | null;
  server_name?: string | null;
  server_slug?: string | null;
  enabled_capabilities?: string[];
  is_active: boolean;
  disabled_tools?: string[] | null;
  scope_level?: string;
}

interface DiscoveredTool {
  name: string;
  description?: string;
}

export function ConnectorsPage() {
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [installed, setInstalled] = useState<InstalledConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null); // catalog slug OR installed id
  const [connecting, setConnecting] = useState<string | null>(null);
  const [addCustomOpen, setAddCustomOpen] = useState(false);

  // Per-tool permissions drawer state
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTools, setDrawerTools] = useState<ConnectorTool[]>([]);
  const [drawerConfigId, setDrawerConfigId] = useState<string | null>(null);
  const [drawerDisabled, setDrawerDisabled] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cat, inst] = await Promise.all([
        marketplaceApi.getMcpCatalog(),
        marketplaceApi.getInstalledMcpServers(),
      ]);
      setCatalog(cat);
      setInstalled(inst);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to load connectors');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const installedBySlug = useMemo(() => {
    const m = new Map<string, InstalledConfig>();
    for (const c of installed) if (c.server_slug) m.set(c.server_slug, c);
    return m;
  }, [installed]);

  const connect = async (entry: CatalogEntry) => {
    if (connecting) return;
    const method = (entry.config?.registration_method as 'dcr' | 'platform_app' | 'byo') || 'dcr';
    setConnecting(entry.slug);
    try {
      const { authorize_url, flow_id } = await marketplaceApi.startMcpOAuth({
        marketplace_agent_slug: entry.slug,
        registration_method: method,
        scope_level: 'user',
      });
      const result = await runOAuthPopup(
        authorize_url,
        flow_id,
        marketplaceApi.getMcpOAuthStatus,
      );
      if (result.status === 'success') {
        toast.success(`Connected ${entry.name}`);
        await load();
      } else {
        toast.error(result.message || 'Connection failed');
      }
    } catch (err: any) {
      toast.error(err?.message || 'Failed to start OAuth flow');
    } finally {
      setConnecting(null);
    }
  };

  const reconnect = async (configId: string, label: string) => {
    try {
      const { authorize_url, flow_id } = await marketplaceApi.reconnectMcp(configId);
      const result = await runOAuthPopup(
        authorize_url,
        flow_id,
        marketplaceApi.getMcpOAuthStatus,
      );
      if (result.status === 'success') {
        toast.success(`Reconnected ${label}`);
        await load();
      } else {
        toast.error(result.message || 'Reconnection failed');
      }
    } catch (err: any) {
      toast.error(err?.message || 'Failed to reconnect');
    }
  };

  const disconnect = async (configId: string, label: string) => {
    if (!window.confirm(`Disconnect ${label}? Agents will lose access to its tools.`)) return;
    try {
      await marketplaceApi.uninstallMcpServer(configId);
      toast.success(`Disconnected ${label}`);
      await load();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to disconnect');
    }
  };

  const openPermissions = async (config: InstalledConfig, label: string) => {
    try {
      const discovery = await marketplaceApi.discoverMcpServer(config.id);
      const slug = config.server_slug || label.toLowerCase().replace(/\s+/g, '-');
      const tools: ConnectorTool[] = (discovery?.tools || []).map((t: DiscoveredTool) => ({
        name: t.name,
        description: t.description,
        prefixedName: `mcp__${slug}__${t.name}`,
      }));
      setDrawerTools(tools);
      setDrawerConfigId(config.id);
      setDrawerDisabled(config.disabled_tools || []);
      setDrawerOpen(true);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to discover tools');
    }
  };

  const selectedEntry = useMemo(() => {
    if (!selected) return null;
    const cat = catalog.find((c) => c.slug === selected);
    if (cat) return { type: 'catalog' as const, entry: cat };
    const ins = installed.find((c) => c.id === selected);
    if (ins) return { type: 'installed' as const, entry: ins };
    return null;
  }, [selected, catalog, installed]);

  if (loading) {
    return (
      <div className="p-8 flex justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="flex h-full">
      {/* Left: catalog + installed list */}
      <section
        className="w-96 border-r overflow-y-auto flex-shrink-0"
        style={{ borderColor: 'var(--border)' }}
      >
        <div
          className="flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--border)' }}
        >
          <div>
            <h1 className="text-base font-semibold text-[var(--text)]">Connectors</h1>
            <p className="text-xs text-[var(--text-muted)]">
              Give your agents access to external tools.
            </p>
          </div>
          <button
            onClick={() => setAddCustomOpen(true)}
            className="btn btn-primary text-xs px-2 py-1 rounded flex items-center gap-1"
          >
            <Plus size={12} />
            Custom
          </button>
        </div>

        {/* Connected group */}
        {installed.length > 0 && (
          <div className="px-4 py-3">
            <div className="text-xs font-semibold text-[var(--text-muted)] uppercase mb-2">
              Connected
            </div>
            <ul className="space-y-1">
              {installed.map((c) => {
                const label = c.server_name || c.server_slug || 'Custom connector';
                return (
                  <li key={c.id}>
                    <button
                      onClick={() => setSelected(c.id)}
                      className={`w-full text-left px-2 py-2 rounded flex items-center gap-2 transition ${
                        selected === c.id
                          ? 'bg-[var(--hover-bg)]'
                          : 'hover:bg-[var(--hover-bg)]'
                      }`}
                    >
                      <CheckCircle size={16} weight="fill" color="var(--color-success, #22c55e)" />
                      <span className="text-sm text-[var(--text)] truncate flex-1">{label}</span>
                      {c.scope_level && c.scope_level !== 'user' && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--hover-bg)] text-[var(--text-muted)]">
                          {c.scope_level}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {/* Not connected group */}
        <div className="px-4 py-3">
          <div className="text-xs font-semibold text-[var(--text-muted)] uppercase mb-2">
            Available
          </div>
          <ul className="space-y-1">
            {catalog
              .filter((entry) => !installedBySlug.has(entry.slug))
              .map((entry) => (
                <li key={entry.slug}>
                  <button
                    onClick={() => setSelected(entry.slug)}
                    className={`w-full text-left px-2 py-2 rounded flex items-center gap-2 transition ${
                      selected === entry.slug
                        ? 'bg-[var(--hover-bg)]'
                        : 'hover:bg-[var(--hover-bg)]'
                    }`}
                  >
                    <Circle size={16} color="var(--text-muted)" />
                    {entry.icon_url ? (
                      <img
                        src={entry.icon_url}
                        alt=""
                        className="w-4 h-4 rounded-sm object-contain"
                      />
                    ) : null}
                    <span className="text-sm text-[var(--text)] truncate flex-1">
                      {entry.name}
                    </span>
                  </button>
                </li>
              ))}
          </ul>
          {catalog.length === 0 && (
            <p className="text-xs text-[var(--text-muted)] italic">
              No connectors available in the catalog yet.
            </p>
          )}
        </div>
      </section>

      {/* Right: detail panel */}
      <section className="flex-1 overflow-y-auto">
        {!selectedEntry ? (
          <div className="h-full flex flex-col items-center justify-center text-[var(--text-muted)] gap-2">
            <Plug size={40} weight="thin" />
            <p className="text-sm">Select a connector to configure it.</p>
          </div>
        ) : selectedEntry.type === 'catalog' ? (
          <CatalogDetail
            entry={selectedEntry.entry}
            onConnect={() => connect(selectedEntry.entry)}
            connecting={connecting === selectedEntry.entry.slug}
            installed={installedBySlug.get(selectedEntry.entry.slug) || null}
          />
        ) : (
          <InstalledDetail
            config={selectedEntry.entry}
            catalogEntry={
              catalog.find((c) => c.slug === selectedEntry.entry.server_slug) || null
            }
            onReconnect={(label) => reconnect(selectedEntry.entry.id, label)}
            onDisconnect={(label) => disconnect(selectedEntry.entry.id, label)}
            onOpenPermissions={(label) => openPermissions(selectedEntry.entry, label)}
          />
        )}
      </section>

      <AddCustomConnectorModal
        open={addCustomOpen}
        onClose={() => setAddCustomOpen(false)}
        onSuccess={load}
        scopeLevel="user"
      />

      {drawerConfigId && (
        <ConnectorPermissionsDrawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          configId={drawerConfigId}
          serverName={
            installed.find((c) => c.id === drawerConfigId)?.server_name || 'Connector'
          }
          tools={drawerTools}
          initiallyDisabled={drawerDisabled}
          onSaved={(disabled) => {
            setInstalled((prev) =>
              prev.map((c) =>
                c.id === drawerConfigId ? { ...c, disabled_tools: disabled } : c,
              ),
            );
          }}
        />
      )}
    </div>
  );
}

function CatalogDetail({
  entry,
  onConnect,
  connecting,
  installed,
}: {
  entry: CatalogEntry;
  onConnect: () => void;
  connecting: boolean;
  installed: InstalledConfig | null;
}) {
  return (
    <div className="p-6 max-w-2xl">
      <div className="flex items-start gap-3 mb-4">
        {entry.icon_url ? (
          <img src={entry.icon_url} alt="" className="w-10 h-10 rounded object-contain" />
        ) : (
          <div className="w-10 h-10 rounded bg-[var(--hover-bg)] flex items-center justify-center">
            <Plug size={20} />
          </div>
        )}
        <div>
          <h2 className="text-lg font-semibold text-[var(--text)]">{entry.name}</h2>
          <p className="text-sm text-[var(--text-muted)]">{entry.description}</p>
        </div>
      </div>

      <div className="mb-4 text-xs text-[var(--text-muted)] space-y-1">
        {entry.config?.url && (
          <div>
            <span className="font-semibold">Server</span> — {String(entry.config.url)}
          </div>
        )}
        {entry.config?.registration_method && (
          <div>
            <span className="font-semibold">Auth</span> — OAuth 2.1 (
            {String(entry.config.registration_method)})
          </div>
        )}
      </div>

      {installed ? (
        <p className="text-sm text-[var(--text-muted)]">
          Already connected. Select it on the left to manage.
        </p>
      ) : (
        <button
          onClick={onConnect}
          disabled={connecting}
          className="btn btn-primary text-sm px-3 py-1.5 rounded flex items-center gap-1 disabled:opacity-50"
        >
          <Plug size={14} />
          {connecting ? 'Connecting…' : 'Connect'}
        </button>
      )}
    </div>
  );
}

function InstalledDetail({
  config,
  catalogEntry,
  onReconnect,
  onDisconnect,
  onOpenPermissions,
}: {
  config: InstalledConfig;
  catalogEntry: CatalogEntry | null;
  onReconnect: (label: string) => void;
  onDisconnect: (label: string) => void;
  onOpenPermissions: (label: string) => void;
}) {
  const label = config.server_name || catalogEntry?.name || 'Custom connector';
  return (
    <div className="p-6 max-w-2xl">
      <div className="flex items-start gap-3 mb-4">
        {catalogEntry?.icon_url ? (
          <img src={catalogEntry.icon_url} alt="" className="w-10 h-10 rounded object-contain" />
        ) : (
          <div className="w-10 h-10 rounded bg-[var(--hover-bg)] flex items-center justify-center">
            <Plug size={20} />
          </div>
        )}
        <div>
          <h2 className="text-lg font-semibold text-[var(--text)]">{label}</h2>
          <p className="text-sm text-[var(--text-muted)]">
            {catalogEntry?.description ||
              'Custom MCP connector. Agents can use its tools, resources, and prompts.'}
          </p>
        </div>
      </div>

      <div className="mb-6 text-xs text-[var(--text-muted)]">
        Scope: {config.scope_level || 'user'}
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => onOpenPermissions(label)}
          className="text-sm px-3 py-1.5 rounded border flex items-center gap-1"
          style={{ borderColor: 'var(--border)' }}
        >
          <Sliders size={14} />
          Tool permissions
        </button>
        <button
          onClick={() => onReconnect(label)}
          className="text-sm px-3 py-1.5 rounded border flex items-center gap-1"
          style={{ borderColor: 'var(--border)' }}
        >
          <ArrowsClockwise size={14} />
          Reconnect
        </button>
        <button
          onClick={() => onDisconnect(label)}
          className="text-sm px-3 py-1.5 rounded border flex items-center gap-1 text-[var(--color-danger,#ef4444)]"
          style={{ borderColor: 'var(--border)' }}
        >
          <LinkBreak size={14} />
          Disconnect
        </button>
      </div>
    </div>
  );
}

export default ConnectorsPage;
