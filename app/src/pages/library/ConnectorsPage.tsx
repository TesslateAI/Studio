import { useState, useEffect, useRef } from 'react';
import {
  Plugs,
  Key,
  TestTube,
  Trash,
  Check,
  SignOut,
  Plus,
  Wrench,
  Database,
  ChatCircleDots,
  Storefront,
  MagnifyingGlass,
  X,
  CaretDown,
  SortAscending,
  SortDescending,
  Gear,
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { marketplaceApi } from '../../lib/api';
import toast from 'react-hot-toast';
import { runOAuthPopup } from '../../components/connectors/ConnectorOAuthPopup';
import {
  ConnectorPermissionsDrawer,
  type ConnectorTool,
} from '../../components/connectors/ConnectorPermissionsDrawer';
import { motion } from 'framer-motion';
import { staggerContainer, staggerItem } from '../../components/cards';
import type { LibraryAgent } from './types';

// ─── Types ──────────────────────────────────────────────────────────
export interface InstalledMcpServer {
  id: string;
  server_name: string | null;
  server_slug: string | null;
  is_active: boolean;
  marketplace_agent_id: string | null;
  enabled_capabilities: string[] | null;
  env_vars: string[] | null;
  created_at: string;
  updated_at: string | null;
  // Issue #307 — scoping + OAuth metadata emitted by McpConfigResponse.
  scope_level?: string | null;
  project_id?: string | null;
  is_oauth?: boolean;
  // True when the connector actually has working credentials. Distinct
  // from is_active — a row can be enabled but not yet connected.
  is_connected?: boolean;
  // True when tool discovery last failed with a 401/OAuth error — the
  // connector was previously authorized but tokens went stale. UI renders a
  // red dot + "Reconnect" CTA when this flag is set.
  needs_reauth?: boolean;
  last_auth_error?: string | null;
  disabled_tools?: string[] | null;
  // Agent ids this connector is currently assigned to. Pre-filled by the
  // list endpoint so the "Add to Agent" button can render its count
  // immediately after a refresh, without waiting for the dropdown to open.
  assigned_agent_ids?: string[];
  // Provider branding (provider favicon / avatar) so the card shows the
  // real logo instead of a generic plug.
  icon?: string | null;
  icon_url?: string | null;
}

interface ConnectorsPageProps {
  servers: InstalledMcpServer[];
  agents: LibraryAgent[];
  loading: boolean;
  onReload: () => void;
  onBrowse: () => void;
}

// ─── Sort / Filter types ────────────────────────────────────────────
type SortField = 'name' | 'status' | 'date';
type SortDir = 'asc' | 'desc';
type FilterStatus = 'all' | 'active' | 'inactive';
type ViewMode = 'cards' | 'list';

const sortLabels: Record<SortField, string> = {
  name: 'Name',
  status: 'Status',
  date: 'Date added',
};

// ─── Discovery result type ──────────────────────────────────────────
interface DiscoveryResult {
  tools?: { name: string; description: string }[];
  resources?: { uri: string; name: string; description?: string }[];
  prompts?: { name: string; description: string }[];
}

// ─── Main ConnectorsPage component (renamed from McpServersPage, #307) ─
export default function ConnectorsPage({
  servers,
  agents,
  loading,
  onReload,
  onBrowse,
}: ConnectorsPageProps) {
  // Local state
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [viewMode, _setViewMode] = useState<ViewMode>('cards');
  const [showSortMenu, setShowSortMenu] = useState(false);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const sortMenuRef = useRef<HTMLDivElement>(null);

  // Focus search input when opened
  useEffect(() => {
    if (showSearch) searchInputRef.current?.focus();
  }, [showSearch]);

  // Close sort menu on outside click
  useEffect(() => {
    if (!showSortMenu) return;
    const handler = (e: MouseEvent) => {
      if (sortMenuRef.current && !sortMenuRef.current.contains(e.target as Node)) {
        setShowSortMenu(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showSortMenu]);

  // ─── Counts ─────────────────────────────────────────────────────
  // "Active" means the connector is enabled AND has working credentials
  // (OAuth tokens for OAuth servers, encrypted env vars for static ones).
  // OAuth installs that haven't completed authorize live under "Inactive".
  const isUsable = (s: InstalledMcpServer) => s.is_active && s.is_connected !== false;
  const activeCount = servers.filter(isUsable).length;
  const inactiveCount = servers.filter((s) => !isUsable(s)).length;

  // ─── Filtering & sorting ─────────────────────────────────────────
  const filtered = servers
    .filter((s) => {
      if (filterStatus === 'active' && !isUsable(s)) return false;
      if (filterStatus === 'inactive' && isUsable(s)) return false;
      return true;
    })
    .filter((s) => {
      if (!searchQuery) return true;
      const q = searchQuery.toLowerCase();
      return (
        (s.server_name || '').toLowerCase().includes(q) ||
        (s.server_slug || '').toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      let cmp = 0;
      if (sortField === 'name') cmp = (a.server_name || '').localeCompare(b.server_name || '');
      else if (sortField === 'status') cmp = Number(b.is_active) - Number(a.is_active);
      else if (sortField === 'date') cmp = (a.created_at || '').localeCompare(b.created_at || '');
      return sortDir === 'desc' ? -cmp : cmp;
    });

  // ─── Loading state ───────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  // ─── Render ──────────────────────────────────────────────────────
  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      {/* Toolbar */}
      <div
        className="h-10 flex items-center justify-between flex-shrink-0"
        style={{ paddingLeft: '7px', paddingRight: '10px' }}
      >
        {/* Left: Filter tabs */}
        <div
          className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-none"
          style={{
            maskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)',
            WebkitMaskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)',
          }}
        >
          <button
            onClick={() => setFilterStatus('all')}
            className={`btn ${filterStatus === 'all' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}
          >
            All servers <span className="text-[10px] opacity-50 ml-0.5">{servers.length}</span>
          </button>
          <button
            onClick={() => setFilterStatus('active')}
            className={`btn ${filterStatus === 'active' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}
          >
            Active <span className="text-[10px] opacity-50 ml-0.5">{activeCount}</span>
          </button>
          <button
            onClick={() => setFilterStatus('inactive')}
            className={`btn ${filterStatus === 'inactive' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}
          >
            Inactive <span className="text-[10px] opacity-50 ml-0.5">{inactiveCount}</span>
          </button>
        </div>

        {/* Right: Search, Sort, Display, Divider, Browse */}
        <div className="flex items-center gap-[2px]">
          {/* Search toggle */}
          {showSearch ? (
            <div className="flex items-center gap-1.5 bg-[var(--surface)] border border-[var(--border)] rounded-full px-2.5 h-[29px]">
              <MagnifyingGlass size={16} className="text-[var(--text-subtle)]" />
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') {
                    setSearchQuery('');
                    setShowSearch(false);
                  }
                }}
                placeholder="Search..."
                className="bg-transparent border-none outline-none text-xs w-24 sm:w-32 text-[var(--text)]"
              />
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  setShowSearch(false);
                }}
              >
                <X size={12} className="text-[var(--text-subtle)]" />
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowSearch(true)}
              className={`btn btn-icon ${searchQuery ? 'btn-active' : ''}`}
            >
              <MagnifyingGlass size={16} />
            </button>
          )}

          {/* Sort */}
          <div ref={sortMenuRef} className="relative">
            <button
              onClick={() => setShowSortMenu((v) => !v)}
              className={`btn ${sortField !== 'name' || sortDir !== 'asc' ? 'btn-active' : ''}`}
              style={{ gap: '4px' }}
            >
              {sortDir === 'desc' ? <SortDescending size={16} /> : <SortAscending size={16} />}
              <span className="hidden sm:inline text-xs">{sortLabels[sortField]}</span>
              <CaretDown size={12} className="opacity-50" />
            </button>
            {showSortMenu && (
              <div
                className="absolute right-0 top-full mt-1 z-50 min-w-[180px] py-1 rounded-[var(--radius-medium)] border bg-[var(--surface)]"
                style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}
              >
                <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                  Sort by
                </div>
                {(['name', 'status', 'date'] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => {
                      setSortField(f);
                      setShowSortMenu(false);
                    }}
                    className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${sortField === f ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}
                  >
                    {f === 'name' ? 'Name' : f === 'status' ? 'Status' : 'Date added'}
                  </button>
                ))}
                <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />
                <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                  Direction
                </div>
                <button
                  onClick={() => {
                    setSortDir('asc');
                    setShowSortMenu(false);
                  }}
                  className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${sortDir === 'asc' ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}
                >
                  Ascending
                </button>
                <button
                  onClick={() => {
                    setSortDir('desc');
                    setShowSortMenu(false);
                  }}
                  className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${sortDir === 'desc' ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}
                >
                  Descending
                </button>
              </div>
            )}
          </div>

          {/* Display toggle — hidden until list view has actions (M8, #347) */}

          <div className="w-px h-[22px] bg-[var(--border)] mx-0.5" />

          {/* Browse marketplace */}
          <button onClick={onBrowse} className="btn">
            <Storefront size={16} />
            <span className="hidden sm:inline">Browse</span>
          </button>
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-hidden flex relative">
        <div className="flex-1 overflow-auto min-w-0">
          <div className="p-4 md:p-5">
            {servers.length === 0 ? (
              /* Empty state — no servers at all */
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="w-12 h-12 bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] flex items-center justify-center mb-4">
                  <Plugs size={20} className="text-[var(--text-subtle)]" />
                </div>
                <h3 className="text-xs font-semibold text-[var(--text)] mb-2">No connectors yet</h3>
                <p className="text-[11px] text-[var(--text-muted)] max-w-sm mb-6">
                  Connectors give your agents access to external tools, APIs, and data sources
                  (Linear, GitHub, Notion, and more). Browse the marketplace to install one.
                </p>
                <button onClick={onBrowse} className="btn btn-filled">
                  <Plus size={16} />
                  Browse Connectors Marketplace
                </button>
              </div>
            ) : filtered.length === 0 ? (
              /* No results for current filter/search */
              <div className="text-center py-16">
                <MagnifyingGlass size={48} className="mx-auto mb-4 text-[var(--text-subtle)]" />
                <p className="text-[var(--text-muted)] mb-2">No servers match your filters</p>
                <button
                  onClick={() => {
                    setFilterStatus('all');
                    setSearchQuery('');
                  }}
                  className="text-xs text-[var(--primary)] hover:underline"
                >
                  Clear filters
                </button>
              </div>
            ) : viewMode === 'cards' ? (
              <motion.div
                variants={staggerContainer}
                initial="initial"
                animate="animate"
                className="grid gap-5"
                style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}
              >
                {filtered.map((server) => (
                  <McpServerCard
                    key={server.id}
                    server={server}
                    agents={agents}
                    onReload={onReload}
                  />
                ))}
              </motion.div>
            ) : (
              <div className="space-y-1">
                {filtered.map((server) => (
                  <McpServerListRow key={server.id} server={server} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── McpServerListRow (list view) ───────────────────────────────────
function McpServerListRow({ server }: { server: InstalledMcpServer }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-lg transition-colors hover:bg-[var(--surface-hover)] border border-transparent">
      {/* Icon */}
      <div className="w-7 h-7 rounded-lg bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center shrink-0 text-[var(--primary)]">
        <Plugs size={14} weight="duotone" />
      </div>
      {/* Name + slug */}
      <div className="flex-1 min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-[var(--text)] truncate">
            {server.server_name || server.server_slug || 'Connector'}
          </span>
          <span
            className={`w-1.5 h-1.5 rounded-full shrink-0 ${
              server.needs_reauth
                ? 'bg-[var(--status-error)]'
                : server.is_active
                  ? 'bg-[var(--status-success)]'
                  : 'bg-[var(--text-subtle)]'
            }`}
            title={
              server.needs_reauth ? 'Reconnect required' : server.is_active ? 'Active' : 'Inactive'
            }
          />
        </span>
        <span className="text-[11px] text-[var(--text-subtle)] block truncate font-mono">
          {server.server_slug}
        </span>
      </div>
      {/* Status label */}
      <span className="text-[10px] text-[var(--text-muted)] hidden sm:block">
        {server.is_active ? 'Active' : 'Inactive'}
      </span>
      {/* Settings icon placeholder */}
      <div className="shrink-0 p-1 rounded-md">
        <Gear size={14} className="text-[var(--text-subtle)]" />
      </div>
    </div>
  );
}

// ─── McpServerCard (card view) ──────────────────────────────────────
function McpServerCard({
  server,
  agents,
  onReload,
}: {
  server: InstalledMcpServer;
  agents: LibraryAgent[];
  onReload: () => void;
}) {
  const [showDropdown, setShowDropdown] = useState(false);
  const [, setAssigning] = useState(false);
  const [showCredentials, setShowCredentials] = useState(false);
  const [showDetails] = useState(false);
  const [credentialValues, setCredentialValues] = useState<Record<string, string>>({});
  const [savingCredentials, setSavingCredentials] = useState(false);
  const [discoveryResult] = useState<DiscoveryResult | null>(null);
  const [discovering] = useState(false);
  const [testingId, setTestingId] = useState(false);
  const [uninstalling, setUninstalling] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [permsOpen, setPermsOpen] = useState(false);
  const [permsTools, setPermsTools] = useState<ConnectorTool[]>([]);
  // Multi-agent assignment state. Pre-loaded once on dropdown open so the
  // user sees checkmarks against agents the connector already serves and
  // can toggle multiple in a single open without the menu closing on each
  // click. agentBusyId tracks the row currently being toggled to disable
  // it during the network round-trip.
  // Seed assignedAgentIds from the install row so the count survives
  // refresh; lazy-load on dropdown open is a fallback if the field is
  // absent (older clients / cached responses).
  const [assignedAgentIds, setAssignedAgentIds] = useState<Set<string>>(
    () => new Set(server.assigned_agent_ids ?? [])
  );
  const [assignmentsLoaded, setAssignmentsLoaded] = useState(
    () => server.assigned_agent_ids !== undefined
  );
  const [agentBusyId, setAgentBusyId] = useState<string | null>(null);

  // Re-sync if the parent reloads with a fresh assigned_agent_ids value.
  useEffect(() => {
    if (server.assigned_agent_ids !== undefined) {
      setAssignedAgentIds(new Set(server.assigned_agent_ids));
      setAssignmentsLoaded(true);
    }
  }, [server.assigned_agent_ids]);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const handleReconnect = async () => {
    setReconnecting(true);
    try {
      const { authorize_url, flow_id } = await marketplaceApi.reconnectMcp(server.id);
      const result = await runOAuthPopup(authorize_url, flow_id, marketplaceApi.getMcpOAuthStatus);
      if (result.status === 'success') {
        toast.success(`Reconnected ${server.server_name || 'connector'}`);
        onReload();
      } else {
        toast.error(result.message || 'Reconnection failed');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string };
      toast.error(err.response?.data?.detail || err.message || 'Failed to reconnect');
    } finally {
      setReconnecting(false);
    }
  };

  const [disconnecting, setDisconnecting] = useState(false);
  const handleDisconnect = async () => {
    const label = server.server_name || server.server_slug || 'connector';
    if (
      !window.confirm(
        `Disconnect ${label}? Your stored credentials will be removed, but the connector stays installed and its agent assignments are preserved. Click Connect later to re-authorize.`
      )
    )
      return;
    setDisconnecting(true);
    try {
      await marketplaceApi.disconnectMcp(server.id);
      toast.success(`Disconnected ${label}`);
      onReload();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to disconnect');
    } finally {
      setDisconnecting(false);
    }
  };

  const handleOpenPerms = async () => {
    // No tokens yet → tool list can't be discovered. Tell the user clearly
    // instead of opening an empty drawer or hitting a 409 from the backend.
    if (server.is_oauth && !server.is_connected) {
      toast.error('Connector not authorized. Connect it before managing permissions.');
      return;
    }
    try {
      const discovery = (await marketplaceApi.discoverMcpServer(server.id)) as DiscoveryResult;
      const slug = server.server_slug || server.server_name || 'connector';
      const tools: ConnectorTool[] = (discovery?.tools || []).map((t) => ({
        name: t.name,
        description: t.description,
        prefixedName: `mcp__${slug}__${t.name}`,
      }));
      setPermsTools(tools);
      setPermsOpen(true);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to discover tools');
    }
  };

  // Close dropdown on outside click
  useEffect(() => {
    if (!showDropdown) return;
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showDropdown]);

  // Lazy-load the assigned-agents set the first time the dropdown opens —
  // avoids paying for the round-trip on every Library render.
  const ensureAssignmentsLoaded = async () => {
    if (assignmentsLoaded) return;
    try {
      const ids = await marketplaceApi.getConnectorAgents(server.id);
      setAssignedAgentIds(new Set(ids));
    } catch {
      // Non-fatal — dropdown still works, just without ✓ marks.
    } finally {
      setAssignmentsLoaded(true);
    }
  };

  const toggleAgentAssignment = async (agentId: string, agentName: string) => {
    const isAssigned = assignedAgentIds.has(agentId);
    setAgentBusyId(agentId);
    setAssigning(true);
    try {
      if (isAssigned) {
        await marketplaceApi.unassignMcpFromAgent(server.id, agentId);
        setAssignedAgentIds((prev) => {
          const next = new Set(prev);
          next.delete(agentId);
          return next;
        });
        toast.success(`${server.server_name || server.server_slug} removed from ${agentName}`);
      } else {
        await marketplaceApi.assignMcpToAgent(server.id, agentId);
        setAssignedAgentIds((prev) => new Set(prev).add(agentId));
        toast.success(`${server.server_name || server.server_slug} added to ${agentName}`);
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to update assignment');
    } finally {
      setAgentBusyId(null);
      setAssigning(false);
    }
  };

  const handleSaveCredentials = async () => {
    setSavingCredentials(true);
    try {
      await marketplaceApi.updateMcpServer(server.id, { credentials: credentialValues });
      toast.success('Credentials saved');
      setShowCredentials(false);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to save credentials');
    } finally {
      setSavingCredentials(false);
    }
  };

  const handleTestConnection = async () => {
    setTestingId(true);
    try {
      const result = await marketplaceApi.testMcpServer(server.id);
      if (result.success) {
        toast.success('Connection successful');
      } else {
        toast.error(result.error || 'Connection failed');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Connection test failed');
    } finally {
      setTestingId(false);
    }
  };

  const handleUninstall = async () => {
    setUninstalling(true);
    try {
      await marketplaceApi.uninstallMcpServer(server.id);
      toast.success('Connector removed');
      onReload();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to remove connector');
    } finally {
      setUninstalling(false);
    }
  };

  const enabledAgents = agents.filter((a) => a.is_enabled !== false);
  const hasEnvVars = server.env_vars && server.env_vars.length > 0;

  return (
    <motion.div
      variants={staggerItem}
      initial="initial"
      animate="animate"
      role="article"
      aria-label={`${server.server_name || server.server_slug || 'Connector'} connector`}
      className={`
        group relative flex flex-col
        bg-[var(--surface-hover)] rounded-[var(--radius)] border
        transition-all duration-200
        hover:-translate-y-0.5
        border-[var(--border)] hover:border-[var(--border-hover)]
        ${!server.is_active ? 'opacity-45' : ''}
      `}
    >
      <div className="p-4 flex flex-col h-full">
        {/* Top row: provider icon + name + status dot + Permissions Gear */}
        <div className="flex items-center gap-3 mb-3">
          {server.icon_url ? (
            <img
              src={server.icon_url}
              alt=""
              className="w-8 h-8 rounded-[var(--radius-medium)] object-cover border border-[var(--border)] shrink-0 bg-[var(--surface)]"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = 'none';
              }}
            />
          ) : (
            <div className="w-8 h-8 rounded-[var(--radius-medium)] bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center shrink-0">
              <Plugs size={16} weight="duotone" className="text-[var(--text-muted)]" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <span className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-[var(--text)] truncate">
                {server.server_name || server.server_slug || 'Connector'}
              </span>
              {/* Status dot: red = authorized-but-tokens-stale (needs_reauth),
                  green = actively connected, grey = never connected / no creds.
                  Red wins over green because a broken token is worse than
                  not-yet-connected from the user's POV. */}
              <span
                className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                  server.needs_reauth
                    ? 'bg-[var(--status-error)]'
                    : server.is_connected
                      ? 'bg-[var(--status-success)]'
                      : 'bg-[var(--text-subtle)]'
                }`}
                title={
                  server.needs_reauth
                    ? `Reconnect required${server.last_auth_error ? `: ${server.last_auth_error}` : ''}`
                    : server.is_connected
                      ? 'Connected'
                      : 'Not connected'
                }
              />
            </span>
            <span className="text-[11px] text-[var(--text-subtle)] block truncate">
              {server.server_slug}
            </span>
          </div>
          {/* Tool permissions gear — only relevant once the connector is
              actually authorized (otherwise discovery returns a 409 and the
              drawer would open empty). */}
          {server.is_connected && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleOpenPerms();
              }}
              className="shrink-0 p-1 rounded-[var(--radius-small)] hover:bg-[var(--surface)] transition-colors"
              aria-label="Tool permissions"
              title="Tool permissions"
            >
              <Gear
                size={14}
                className="text-[var(--text-subtle)] group-hover:text-[var(--text-muted)] transition-colors"
              />
            </button>
          )}
        </div>

        {/* Description / capability summary */}
        <p className="text-[11px] leading-relaxed text-[var(--text-muted)] line-clamp-2 mb-3 min-h-[28px]">
          {server.is_oauth
            ? server.is_connected
              ? 'OAuth connector — your account is linked.'
              : 'OAuth connector — finish connecting to start using its tools.'
            : 'Connector exposes tools, resources, and prompts to your agents.'}
        </p>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Metadata row — monochrome, quiet */}
        <div className="flex items-center gap-2 text-[10px] text-[var(--text-subtle)]">
          <span>{server.is_oauth ? 'OAuth' : 'Static'}</span>
          {server.scope_level && (
            <>
              <span className="opacity-30">·</span>
              <span>{server.scope_level === 'project' ? 'Project' : 'Account'}</span>
            </>
          )}
          {(server.disabled_tools?.length ?? 0) > 0 && (
            <>
              <span className="opacity-30">·</span>
              <span>{server.disabled_tools!.length} hidden</span>
            </>
          )}
        </div>

        {/* Inline expansion panels render INSIDE the padded wrapper so they
            stay visually contained within the card frame. They use
            --surface to recede against the --surface-hover card. */}

        {/* Credentials panel (static-auth connectors only) */}
        {showCredentials && hasEnvVars && (
          <div className="mt-3 p-3 bg-[var(--surface)] rounded-[var(--radius-small)] border border-[var(--border)]">
            <p className="text-[11px] text-[var(--text-muted)] mb-2 font-medium">
              Server Credentials
            </p>
            {server.env_vars!.map((key) => (
              <div key={key} className="mb-2">
                <label className="text-[10px] text-[var(--text-subtle)] font-mono">{key}</label>
                <input
                  type="password"
                  placeholder={`Enter ${key}`}
                  value={credentialValues[key] || ''}
                  onChange={(e) =>
                    setCredentialValues((prev) => ({ ...prev, [key]: e.target.value }))
                  }
                  className="w-full mt-0.5 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--border-hover)]"
                />
              </div>
            ))}
            <button
              onClick={handleSaveCredentials}
              disabled={savingCredentials}
              className="btn btn-filled btn-sm w-full"
            >
              {savingCredentials ? 'Saving...' : 'Save Credentials'}
            </button>
          </div>
        )}

        {/* Add to Agent — only visible when the connector is enabled AND
            authorized. Hiding it for unconnected connectors prevents users
            from attaching a connector that has no working credentials, which
            would silently fail at agent runtime. */}
        {server.is_active && server.is_connected && (
          <div ref={dropdownRef} className="relative mt-3">
            <button
              onClick={() => {
                const next = !showDropdown;
                setShowDropdown(next);
                if (next) ensureAssignmentsLoaded();
              }}
              className="btn btn-sm w-full"
            >
              <Plugs size={12} />
              {assignedAgentIds.size === 0
                ? 'Add to Agent'
                : assignedAgentIds.size === 1
                  ? 'Assigned to 1 agent'
                  : `Assigned to ${assignedAgentIds.size} agents`}
            </button>
            {showDropdown && (
              <div className="absolute left-0 right-0 top-full mt-1 z-30 bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-1.5 shadow-lg max-h-56 overflow-y-auto">
                <div className="px-2 pt-1 pb-1.5 text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                  Agents
                </div>
                {enabledAgents.length === 0 ? (
                  <p className="px-2 py-3 text-[11px] text-[var(--text-muted)] text-center">
                    No active agents. Enable an agent first.
                  </p>
                ) : (
                  enabledAgents.map((agent) => {
                    const isAssigned = assignedAgentIds.has(agent.id);
                    const isBusy = agentBusyId === agent.id;
                    return (
                      <button
                        key={agent.id}
                        onClick={() => toggleAgentAssignment(agent.id, agent.name)}
                        disabled={isBusy}
                        className={`w-full text-left px-2 py-1.5 rounded-[var(--radius-small)] text-xs transition-colors flex items-center gap-2 ${
                          isAssigned
                            ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                            : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                        } ${isBusy ? 'opacity-50' : ''}`}
                      >
                        {agent.avatar_url ? (
                          <img
                            src={agent.avatar_url}
                            alt=""
                            className="w-5 h-5 rounded-[var(--radius-small)] object-cover border border-[var(--border)] shrink-0"
                          />
                        ) : (
                          <div className="w-5 h-5 rounded-[var(--radius-small)] bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center shrink-0">
                            <img src="/favicon.svg" alt="" className="w-3 h-3" />
                          </div>
                        )}
                        <span className="truncate font-medium flex-1">{agent.name}</span>
                        {isAssigned && (
                          <Check
                            size={12}
                            weight="bold"
                            className="text-[var(--status-success)] shrink-0"
                          />
                        )}
                      </button>
                    );
                  })
                )}
              </div>
            )}
          </div>
        )}

        {/* Actions row */}
        <div
          className="flex items-center gap-1 mt-3 pt-3 border-t border-[var(--border)]"
          onClick={(e) => e.stopPropagation()}
        >
          {server.is_oauth ? (
            <>
              <button
                onClick={handleReconnect}
                disabled={reconnecting || disconnecting}
                className="btn btn-sm"
              >
                <Plugs size={12} />
                {reconnecting
                  ? server.is_connected
                    ? 'Reconnecting…'
                    : 'Connecting…'
                  : server.is_connected
                    ? 'Reconnect'
                    : 'Connect'}
              </button>
              {server.is_connected && (
                <button
                  onClick={handleDisconnect}
                  disabled={disconnecting || reconnecting}
                  className="btn btn-sm"
                  title="Sign out of this connector (keeps it installed)"
                >
                  <SignOut size={12} />
                  {disconnecting ? 'Disconnecting…' : 'Disconnect'}
                </button>
              )}
            </>
          ) : hasEnvVars ? (
            <button onClick={() => setShowCredentials(!showCredentials)} className="btn btn-sm">
              <Key size={12} />
              Credentials
            </button>
          ) : (
            <button
              onClick={() => handleTestConnection()}
              disabled={testingId}
              className="btn btn-sm"
            >
              <TestTube size={12} />
              {testingId ? 'Testing…' : 'Test'}
            </button>
          )}
          <div className="flex-1" />
          <button
            onClick={handleUninstall}
            disabled={uninstalling}
            className="btn btn-icon btn-sm btn-danger"
            aria-label="Uninstall connector"
            title="Uninstall"
          >
            <Trash size={12} />
          </button>
        </div>
      </div>

      {/* Render unconditionally so AnimatePresence can run the exit animation
          when permsOpen flips back to false. */}
      <ConnectorPermissionsDrawer
        open={permsOpen}
        onClose={() => setPermsOpen(false)}
        configId={server.id}
        serverName={server.server_name || server.server_slug || 'Connector'}
        tools={permsTools}
        initiallyDisabled={server.disabled_tools || []}
        onSaved={() => onReload()}
      />

      {/* Details / Discovery (legacy disclosure — only renders if the old
          Details button is reintroduced; kept for compat). */}
      {showDetails && (
        <div className="mx-4 mb-4 p-3 bg-[var(--surface)] rounded-[var(--radius-small)] border border-[var(--border)]">
          {discovering ? (
            <div className="flex items-center justify-center py-4">
              <LoadingSpinner />
            </div>
          ) : discoveryResult ? (
            <div className="space-y-2">
              {discoveryResult.tools && discoveryResult.tools.length > 0 && (
                <div>
                  <p className="text-[11px] font-medium text-[var(--text-muted)] mb-1">
                    Tools ({discoveryResult.tools.length})
                  </p>
                  {discoveryResult.tools.map((t) => (
                    <div key={t.name} className="flex items-start gap-1.5 py-1">
                      <Wrench size={11} className="text-[var(--text-subtle)] mt-0.5 shrink-0" />
                      <div>
                        <p className="text-[11px] font-medium text-[var(--text)] font-mono">
                          {t.name}
                        </p>
                        {t.description && (
                          <p className="text-[10px] text-[var(--text-muted)]">{t.description}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {discoveryResult.resources && discoveryResult.resources.length > 0 && (
                <div>
                  <p className="text-[11px] font-medium text-[var(--text-muted)] mb-1">
                    Resources ({discoveryResult.resources.length})
                  </p>
                  {discoveryResult.resources.map((r) => (
                    <div key={r.uri} className="flex items-start gap-1.5 py-1">
                      <Database size={11} className="text-[var(--text-subtle)] mt-0.5 shrink-0" />
                      <div>
                        <p className="text-[11px] font-medium text-[var(--text)] font-mono">
                          {r.name}
                        </p>
                        <p className="text-[10px] text-[var(--text-subtle)] font-mono">{r.uri}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {discoveryResult.prompts && discoveryResult.prompts.length > 0 && (
                <div>
                  <p className="text-[11px] font-medium text-[var(--text-muted)] mb-1">
                    Prompts ({discoveryResult.prompts.length})
                  </p>
                  {discoveryResult.prompts.map((p) => (
                    <div key={p.name} className="flex items-start gap-1.5 py-1">
                      <ChatCircleDots
                        size={11}
                        className="text-[var(--text-subtle)] mt-0.5 shrink-0"
                      />
                      <div>
                        <p className="text-[11px] font-medium text-[var(--text)]">{p.name}</p>
                        {p.description && (
                          <p className="text-[10px] text-[var(--text-muted)]">{p.description}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {(!discoveryResult.tools || discoveryResult.tools.length === 0) &&
                (!discoveryResult.resources || discoveryResult.resources.length === 0) &&
                (!discoveryResult.prompts || discoveryResult.prompts.length === 0) && (
                  <p className="text-[11px] text-[var(--text-muted)] text-center py-2">
                    No capabilities discovered
                  </p>
                )}
            </div>
          ) : null}
        </div>
      )}
    </motion.div>
  );
}
