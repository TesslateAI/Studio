import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Package,
  Pencil,
  Power,
  Rocket,
  Plus,
  Trash,
  File,
  FileText,
  FilePlus,
  Terminal,
  Globe,
  ListChecks,
  Wrench,
  Storefront,
  CaretDown,
  CaretRight,
  Robot,
  ToggleLeft,
  ToggleRight,
  X,
  MagnifyingGlass,
  Lightning,
  Code,
  PaintBucket,
  Broadcast,
  TestTube,
  Database,
  Shield,
  FilmStrip,
  Sparkle,
  Stack,
  Article,
  Gear,
  SortAscending,
  SortDescending,
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { ModelSelector } from '../../components/chat/ModelSelector';
import {
  MarkerEditor,
  MarkerPalette,
  type MarkerEditorHandle,
} from '../../components/ui';
import { ConfirmDialog } from '../../components/modals';
import { ToolManagement } from '../../components/ToolManagement';
import { ImageUpload } from '../../components/ImageUpload';
import { marketplaceApi } from '../../lib/api';
import toast from 'react-hot-toast';
import { motion } from 'framer-motion';
import { StatusDot, staggerContainer, staggerItem } from '../../components/cards';
import type { LibraryAgent, SubagentItem } from './types';
import { FEATURE_FLAGS } from './types';

// Re-export types for convenience
export type { LibraryAgent } from './types';

// Tool icon mapping helper
const getToolIcon = (toolName: string): { icon: React.ReactNode; label: string } | null => {
  const toolIcons: Record<string, { icon: React.ReactNode; label: string }> = {
    read_file: { icon: <File size={12} weight="fill" />, label: 'Read' },
    write_file: { icon: <FilePlus size={12} weight="fill" />, label: 'Write' },
    patch_file: { icon: <Pencil size={12} weight="fill" />, label: 'Patch' },
    multi_edit: { icon: <FileText size={12} weight="fill" />, label: 'Multi-Edit' },
    bash_exec: { icon: <Terminal size={12} weight="fill" />, label: 'Bash' },
    shell_open: { icon: <Terminal size={12} weight="fill" />, label: 'Shell Open' },
    shell_exec: { icon: <Terminal size={12} weight="fill" />, label: 'Shell' },
    shell_close: { icon: <Terminal size={12} weight="fill" />, label: 'Shell Close' },
    get_project_info: { icon: <Package size={12} weight="fill" />, label: 'Project Info' },
    todo_read: { icon: <ListChecks size={12} weight="fill" />, label: 'Todo Read' },
    todo_write: { icon: <ListChecks size={12} weight="fill" />, label: 'Todo Write' },
    save_plan: { icon: <ListChecks size={12} weight="fill" />, label: 'Save Plan' },
    update_plan: { icon: <ListChecks size={12} weight="fill" />, label: 'Update Plan' },
    apply_patch: { icon: <FileText size={12} weight="fill" />, label: 'Apply Patch' },
    web_fetch: { icon: <Globe size={12} weight="fill" />, label: 'Web Fetch' },
  };
  return toolIcons[toolName] || null;
};

// Category-to-icon mapping for skills
const SKILL_CATEGORY_ICONS: Record<string, React.ReactNode> = {
  frontend: <Code size={20} weight="duotone" />,
  design: <PaintBucket size={20} weight="duotone" />,
  backend: <Broadcast size={20} weight="duotone" />,
  testing: <TestTube size={20} weight="duotone" />,
  database: <Database size={20} weight="duotone" />,
  security: <Shield size={20} weight="duotone" />,
  media: <FilmStrip size={20} weight="duotone" />,
  'code-quality': <Sparkle size={20} weight="duotone" />,
  deployment: <Rocket size={20} weight="duotone" />,
  devops: <Stack size={20} weight="duotone" />,
};

function getSkillCategoryIcon(category: string): React.ReactNode {
  return SKILL_CATEGORY_ICONS[category] || <Lightning size={20} weight="duotone" />;
}

// Sort options
type SortField = 'name' | 'updated' | 'usage';
type SortDir = 'asc' | 'desc';
type FilterStatus = 'all' | 'active' | 'custom';
type ViewMode = 'cards' | 'list';

const sortLabels: Record<SortField, string> = {
  name: 'Name',
  updated: 'Updated',
  usage: 'Usage',
};

function makeNewAgent(): LibraryAgent {
  return {
    id: '',
    name: '',
    slug: '',
    description: '',
    category: 'general',
    mode: 'agent',
    agent_type: 'IterativeAgent',
    model: '',
    source_type: 'open',
    is_forkable: false,
    icon: '',
    avatar_url: null,
    pricing_type: 'free',
    features: [],
    tools: [],
    tool_configs: {},
    purchase_date: new Date().toISOString(),
    purchase_type: 'free',
    expires_at: null,
    is_custom: true,
    parent_agent_id: null,
    system_prompt: '',
    is_enabled: true,
    is_published: false,
    usage_count: 0,
  };
}

// ─── Main AgentsPage component ──────────────────────────────────────
export default function AgentsPage({
  agents,
  loading,
  onReload,
  onToggleEnable,
  onTogglePublish,
}: {
  agents: LibraryAgent[];
  loading: boolean;
  onReload: () => void;
  onToggleEnable: (agent: LibraryAgent) => void;
  onTogglePublish: (agent: LibraryAgent) => void;
}) {
  const navigate = useNavigate();

  // Local state
  const [editingAgent, setEditingAgent] = useState<LibraryAgent | null>(null);
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [viewMode, setViewMode] = useState<ViewMode>('cards');
  const [showSortMenu, setShowSortMenu] = useState(false);

  // Delete/remove dialog
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [agentToDelete, setAgentToDelete] = useState<LibraryAgent | null>(null);
  const [deleteAction, setDeleteAction] = useState<'remove' | 'delete'>('remove');

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

  // ─── Filtering & sorting ─────────────────────────────────────────
  const filtered = agents
    .filter((a) => {
      if (filterStatus === 'active' && !a.is_enabled) return false;
      if (filterStatus === 'custom' && !a.is_custom) return false;
      return true;
    })
    .filter((a) => {
      if (!searchQuery) return true;
      const q = searchQuery.toLowerCase();
      return (
        a.name.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q) ||
        a.category.toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      let cmp = 0;
      if (sortField === 'name') cmp = a.name.localeCompare(b.name);
      else if (sortField === 'updated') cmp = (a.purchase_date || '').localeCompare(b.purchase_date || '');
      else if (sortField === 'usage') cmp = (a.usage_count || 0) - (b.usage_count || 0);
      return sortDir === 'desc' ? -cmp : cmp;
    });

  // ─── Handlers ────────────────────────────────────────────────────
  const handleCreateAgent = () => setEditingAgent(makeNewAgent());

  const handleRemove = (agent: LibraryAgent) => {
    setAgentToDelete(agent);
    setDeleteAction('remove');
    setShowDeleteDialog(true);
  };

  const handleDelete = (agent: LibraryAgent) => {
    setAgentToDelete(agent);
    setDeleteAction('delete');
    setShowDeleteDialog(true);
  };

  const confirmRemoveAgent = async () => {
    if (!agentToDelete) return;
    setShowDeleteDialog(false);
    const isDelete = deleteAction === 'delete';
    const actionToast = toast.loading(
      isDelete ? `Deleting ${agentToDelete.name}...` : `Removing ${agentToDelete.name}...`
    );
    try {
      if (isDelete) {
        await marketplaceApi.deleteCustomAgent(agentToDelete.id);
        toast.success(`${agentToDelete.name} deleted permanently`, { id: actionToast });
      } else {
        await marketplaceApi.removeFromLibrary(agentToDelete.id);
        toast.success(`${agentToDelete.name} removed from library`, { id: actionToast });
      }
      onReload();
    } catch (error: unknown) {
      console.error(`${isDelete ? 'Delete' : 'Remove'} failed:`, error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(
        err.response?.data?.detail || `Failed to ${isDelete ? 'delete' : 'remove'} agent`,
        { id: actionToast }
      );
    } finally {
      setAgentToDelete(null);
    }
  };

  const handleSaveAgent = async (updatedData: {
    name?: string;
    description?: string;
    system_prompt?: string;
    model?: string;
    tools?: string[];
    tool_configs?: Record<string, { description?: string; examples?: string[]; system_prompt?: string }>;
    avatar_url?: string | null;
    config?: Record<string, unknown>;
  }) => {
    if (!editingAgent) return;
    try {
      let response;
      if (!editingAgent.id || editingAgent.id === '') {
        // Creating a new agent
        const createData = {
          name: updatedData.name || '',
          description: updatedData.description || '',
          system_prompt: updatedData.system_prompt || '',
          mode: 'agent',
          agent_type: 'IterativeAgent',
          model: updatedData.model || '',
        };
        response = await marketplaceApi.createCustomAgent(createData);

        // Update with additional fields (tools, tool_configs, avatar_url, config)
        const agentId = response.agent_id || response.id;
        if (
          agentId &&
          (updatedData.tools ||
            updatedData.tool_configs ||
            updatedData.avatar_url ||
            updatedData.config)
        ) {
          await marketplaceApi.updateAgent(agentId, {
            tools: updatedData.tools,
            tool_configs: updatedData.tool_configs,
            avatar_url: updatedData.avatar_url,
            config: updatedData.config,
          });
        }

        toast.success('Agent created successfully!');
      } else {
        // Updating existing agent
        response = await marketplaceApi.updateAgent(editingAgent.id, updatedData);
        if (response.forked) {
          toast.success('Created a custom fork with your changes!');
        } else {
          toast.success('Agent updated successfully');
        }
      }
      setEditingAgent(null);
      onReload();
    } catch (error: unknown) {
      console.error('Save failed:', error);
      const err = error as {
        response?: { data?: { detail?: string | Array<{ msg: string }> } };
      };
      const detail = err.response?.data?.detail;
      const message =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((d) => d.msg).join(', ')
            : 'Failed to save agent';
      toast.error(message);
    }
  };

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
      <div className="h-10 flex items-center justify-between flex-shrink-0" style={{ paddingLeft: '7px', paddingRight: '10px' }}>
        {/* Left: Filter tabs */}
        <div className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-none" style={{ maskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)', WebkitMaskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)' }}>
          <button onClick={() => setFilterStatus('all')} className={`btn ${filterStatus === 'all' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}>
            All agents <span className="text-[10px] opacity-50 ml-0.5">{agents.length}</span>
          </button>
          <button onClick={() => setFilterStatus('active')} className={`btn ${filterStatus === 'active' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}>
            Active <span className="text-[10px] opacity-50 ml-0.5">{agents.filter((a) => a.is_enabled).length}</span>
          </button>
          <button onClick={() => setFilterStatus('custom')} className={`btn ${filterStatus === 'custom' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}>
            Custom <span className="text-[10px] opacity-50 ml-0.5">{agents.filter((a) => a.is_custom).length}</span>
          </button>
        </div>

        {/* Right: Search, Sort, Display, Divider, Browse, Create */}
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
              <button type="button" onClick={() => { setSearchQuery(''); setShowSearch(false); }}>
                <X size={12} className="text-[var(--text-subtle)]" />
              </button>
            </div>
          ) : (
            <button onClick={() => setShowSearch(true)} className={`btn btn-icon ${searchQuery ? 'btn-active' : ''}`}>
              <MagnifyingGlass size={16} />
            </button>
          )}

          {/* Sort */}
          <div ref={sortMenuRef} className="relative">
            <button onClick={() => setShowSortMenu((v) => !v)} className={`btn ${sortField !== 'name' || sortDir !== 'asc' ? 'btn-active' : ''}`} style={{ gap: '4px' }}>
              {sortDir === 'desc' ? <SortDescending size={16} /> : <SortAscending size={16} />}
              <span className="hidden sm:inline text-xs">{sortLabels[sortField]}</span>
              <CaretDown size={12} className="opacity-50" />
            </button>
            {showSortMenu && (
              <div className="absolute right-0 top-full mt-1 z-50 min-w-[180px] py-1 rounded-[var(--radius-medium)] border bg-[var(--surface)]" style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}>
                <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">Sort by</div>
                {(['name', 'updated', 'usage'] as const).map((f) => (
                  <button key={f} onClick={() => { setSortField(f); setShowSortMenu(false); }} className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${sortField === f ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}>
                    {f === 'name' ? 'Name' : f === 'updated' ? 'Last updated' : 'Usage'}
                  </button>
                ))}
                <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />
                <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">Direction</div>
                <button onClick={() => { setSortDir('asc'); setShowSortMenu(false); }} className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${sortDir === 'asc' ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}>Ascending</button>
                <button onClick={() => { setSortDir('desc'); setShowSortMenu(false); }} className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${sortDir === 'desc' ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}>Descending</button>
              </div>
            )}
          </div>

          {/* Display toggle */}
          <button onClick={() => setViewMode((v) => v === 'cards' ? 'list' : 'cards')} className={`btn btn-icon ${viewMode === 'list' ? 'btn-active' : ''}`}>
            {viewMode === 'cards' ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
            )}
          </button>

          <div className="w-px h-[22px] bg-[var(--border)] mx-0.5" />

          {/* Browse marketplace */}
          <button onClick={() => navigate('/marketplace/browse/agent')} className="btn">
            <Storefront size={16} />
            <span className="hidden sm:inline">Browse</span>
          </button>

          {/* Create agent */}
          <button onClick={handleCreateAgent} className="btn btn-filled">
            <Plus size={16} weight="bold" />
            <span className="hidden sm:inline">Create</span>
          </button>
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-hidden flex relative">
        {/* Agent grid / list */}
        <div className="flex-1 overflow-auto min-w-0">
          <div className="p-4 md:p-5">
            {agents.length === 0 ? (
              /* Empty state — no agents at all */
              <div className="text-center py-16">
                <Package size={48} className="mx-auto mb-4 text-[var(--text-subtle)]" />
                <p className="text-[var(--text-muted)] mb-4">Your library is empty</p>
                <button
                  onClick={() => navigate('/marketplace')}
                  className="px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white transition-colors"
                >
                  Browse Marketplace
                </button>
              </div>
            ) : filtered.length === 0 ? (
              /* No results for current filter/search */
              <div className="text-center py-16">
                <MagnifyingGlass size={48} className="mx-auto mb-4 text-[var(--text-subtle)]" />
                <p className="text-[var(--text-muted)] mb-2">No agents match your filters</p>
                <button
                  onClick={() => { setFilterStatus('all'); setSearchQuery(''); }}
                  className="text-xs text-[var(--primary)] hover:underline"
                >
                  Clear filters
                </button>
              </div>
            ) : viewMode === 'cards' ? (
              <motion.div variants={staggerContainer} initial="initial" animate="animate" className="grid gap-5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
                {filtered.map((agent) => (
                  <AgentCard
                    key={agent.id || `agent-${agent.name}-${agent.slug}`}
                    agent={agent}
                    isSelected={editingAgent?.id === agent.id}
                    onToggleEnable={() => onToggleEnable(agent)}
                    onEdit={() => setEditingAgent(agent)}
                    onTogglePublish={() => onTogglePublish(agent)}
                    onRemove={() => handleRemove(agent)}
                    onDelete={() => handleDelete(agent)}
                  />
                ))}
              </motion.div>
            ) : (
              <div className="space-y-1">
                {filtered.map((agent) => (
                  <AgentListRow
                    key={agent.id || `row-${agent.name}-${agent.slug}`}
                    agent={agent}
                    isSelected={editingAgent?.id === agent.id}
                    onEdit={() => setEditingAgent(agent)}
                    onToggleEnable={() => onToggleEnable(agent)}
                    onTogglePublish={() => onTogglePublish(agent)}
                    onRemove={() => handleRemove(agent)}
                    onDelete={() => handleDelete(agent)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Detail panel */}
        {editingAgent && (
          <div
            className="w-full sm:w-[360px] lg:w-[440px] xl:w-[480px] max-sm:absolute max-sm:inset-0 max-sm:z-30 max-sm:bg-[var(--bg)] flex-shrink-0 overflow-y-auto animate-slide-in-right max-sm:!pl-[var(--app-margin)]"
            style={{ padding: 'var(--app-margin)', paddingLeft: 0 }}
          >
            <EditAgentModal
              agent={editingAgent}
              onClose={() => setEditingAgent(null)}
              onSave={handleSaveAgent}
            />
          </div>
        )}
      </div>

      {/* Delete/Remove Confirmation Dialog */}
      <ConfirmDialog
        isOpen={showDeleteDialog}
        onClose={() => {
          setShowDeleteDialog(false);
          setAgentToDelete(null);
        }}
        onConfirm={confirmRemoveAgent}
        title={deleteAction === 'delete' ? 'Delete Agent' : 'Remove Agent'}
        message={
          deleteAction === 'delete'
            ? `Permanently delete "${agentToDelete?.name}"? This will remove the agent entirely and cannot be undone.`
            : `Remove "${agentToDelete?.name}" from your library? You can re-install it from the Marketplace at any time.`
        }
        confirmText={deleteAction === 'delete' ? 'Delete Permanently' : 'Remove'}
        cancelText="Cancel"
        variant="danger"
      />
    </div>
  );
}

// ─── AgentListRow (list view) ───────────────────────────────────────
function AgentListRow({
  agent,
  isSelected,
  onEdit,
  onToggleEnable,
  onTogglePublish: _onTogglePublish,
  onRemove: _onRemove,
  onDelete: _onDelete,
}: {
  agent: LibraryAgent;
  isSelected?: boolean;
  onEdit: () => void;
  onToggleEnable: () => void;
  onTogglePublish: () => void;
  onRemove: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onEdit}
      className={`flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
        isSelected
          ? 'bg-[var(--surface-hover)] border border-[var(--primary)]/30'
          : 'hover:bg-[var(--surface-hover)] border border-transparent'
      } ${!agent.is_enabled ? 'opacity-50' : ''}`}
    >
      {/* Avatar */}
      {agent.avatar_url ? (
        <img src={agent.avatar_url} alt="" className="w-7 h-7 rounded-lg object-cover border border-[var(--border)]" />
      ) : (
        <div className="w-7 h-7 rounded-lg bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center">
          <img src="/favicon.svg" alt="" className="w-4 h-4" />
        </div>
      )}
      {/* Name + dot + description */}
      <div className="flex-1 min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-[var(--text)] truncate">{agent.name}</span>
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${agent.is_enabled ? 'bg-[var(--status-success)]' : 'bg-[var(--text-subtle)]'}`} />
        </span>
        <span className="text-[11px] text-[var(--text-subtle)] block truncate">{agent.description}</span>
      </div>
      {/* Model */}
      <span className="text-[10px] text-[var(--text-muted)] hidden sm:block truncate max-w-[100px]">
        {agent.selected_model || agent.model}
      </span>
      {/* Settings */}
      <button onClick={(e) => { e.stopPropagation(); onEdit(); }} className="shrink-0 p-1 rounded-md hover:bg-[var(--surface)] transition-colors">
        <Gear size={14} className="text-[var(--text-subtle)]" />
      </button>
    </div>
  );
}

// ─── AgentCard (card view) ──────────────────────────────────────────
function AgentCard({
  agent,
  isSelected,
  onToggleEnable,
  onEdit,
  onTogglePublish,
  onRemove,
  onDelete,
}: {
  agent: LibraryAgent;
  isSelected?: boolean;
  onToggleEnable: () => void;
  onEdit: () => void;
  onTogglePublish: () => void;
  onRemove: () => void;
  onDelete: () => void;
}) {
  const modelName = agent.selected_model || agent.model;
  const toolCount = agent.tools?.length || 0;

  return (
    <motion.div
      variants={staggerItem}
      initial="initial"
      animate="animate"
      onClick={onEdit}
      className={`
        group relative flex flex-col cursor-pointer
        bg-[var(--surface-hover)] rounded-[var(--radius)] border
        transition-all duration-200
        hover:-translate-y-0.5
        ${isSelected
          ? 'border-[var(--primary)] ring-1 ring-[var(--primary)]/20'
          : 'border-[var(--border)] hover:border-[var(--border-hover)]'
        }
        ${!agent.is_enabled ? 'opacity-45' : ''}
      `}
    >
      <div className="p-4 flex flex-col h-full">
        {/* Top row: avatar + name + enable dot */}
        <div className="flex items-center gap-3 mb-3">
          {agent.avatar_url ? (
            <img src={agent.avatar_url} alt="" className="w-8 h-8 rounded-lg object-cover border border-[var(--border)] shrink-0" />
          ) : (
            <div className="w-8 h-8 rounded-lg bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center shrink-0">
              <img src="/favicon.svg" alt="" className="w-5 h-5" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <span className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-[var(--text)] truncate">{agent.name}</span>
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${agent.is_enabled ? 'bg-[var(--status-success)]' : 'bg-[var(--text-subtle)]'}`} />
            </span>
            <span className="text-[11px] text-[var(--text-subtle)] block truncate">
              {agent.creator_username ? `@${agent.creator_username}` : agent.category}
            </span>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); onEdit(); }}
            className="shrink-0 p-1 rounded-md hover:bg-[var(--surface)] transition-colors"
            aria-label="Agent settings"
          >
            <Gear size={14} className="text-[var(--text-subtle)] group-hover:text-[var(--text-muted)] transition-colors" />
          </button>
        </div>

        {/* Description */}
        <p className="text-[11px] leading-relaxed text-[var(--text-muted)] line-clamp-2 mb-3 min-h-[28px]">
          {agent.description || 'No description'}
        </p>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Metadata row — monochrome, quiet */}
        <div className="flex items-center gap-2 text-[10px] text-[var(--text-subtle)]">
          {modelName && (
            <span className="truncate max-w-[100px]">{modelName.split('/').pop()}</span>
          )}
          {modelName && toolCount > 0 && <span className="opacity-30">·</span>}
          {toolCount > 0 && <span>{toolCount} tool{toolCount !== 1 ? 's' : ''}</span>}
          {(modelName || toolCount > 0) && <span className="opacity-30">·</span>}
          <span>{agent.source_type === 'open' ? 'Open' : 'Closed'}</span>
          {agent.is_custom && (
            <>
              <span className="opacity-30">·</span>
              <span>Custom</span>
            </>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 mt-3 pt-3 border-t border-[var(--border)]" onClick={(e) => e.stopPropagation()}>
          <button onClick={onToggleEnable} className="btn btn-sm">
            <Power size={12} />
            {agent.is_enabled ? 'Disable' : 'Enable'}
          </button>
          <div className="flex-1" />
          <button
            onClick={agent.is_custom && !agent.is_published ? onDelete : onRemove}
            className="btn btn-icon btn-sm btn-danger"
          >
            <Trash size={12} />
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// ─── EditAgentModal (detail panel) ──────────────────────────────────
function EditAgentModal({
  agent,
  onClose,
  onSave,
}: {
  agent: LibraryAgent;
  onClose: () => void;
  onSave: (data: {
    name?: string;
    description?: string;
    system_prompt?: string;
    model?: string;
    tools?: string[];
    tool_configs?: Record<
      string,
      { description?: string; examples?: string[]; system_prompt?: string }
    >;
    avatar_url?: string | null;
    config?: Record<string, unknown>;
  }) => void;
}) {
  const [name, setName] = useState(agent.name);
  const [description, setDescription] = useState(agent.description);
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt || '');
  const currentModel = agent.selected_model || agent.model;
  const [model, setModel] = useState(currentModel);
  const [originalPrompt] = useState(agent.system_prompt || '');
  const [tools, setTools] = useState<string[]>(agent.tools || []);
  const [toolConfigs, setToolConfigs] = useState<
    Record<string, { description?: string; examples?: string[]; system_prompt?: string }>
  >(agent.tool_configs || {});
  const [avatarUrl, setAvatarUrl] = useState<string | null>(agent.avatar_url || null);
  const editorRef = useRef<MarkerEditorHandle>(null);

  // Feature flags state — default all enabled
  const defaultFeatures: Record<string, boolean> = {};
  FEATURE_FLAGS.forEach((f) => {
    defaultFeatures[f.key] = true;
  });
  const [features, setFeatures] = useState<Record<string, boolean>>({
    ...defaultFeatures,
    ...(agent.config?.features || {}),
  });

  // Subagents state
  const [subagents, setSubagents] = useState<SubagentItem[]>([]);
  const [subagentsExpanded, setSubagentsExpanded] = useState(false);
  const [subagentsLoading, setSubagentsLoading] = useState(false);
  const [editingSubagent, setEditingSubagent] = useState<string | null>(null);
  const [editingSubagentPrompt, setEditingSubagentPrompt] = useState('');
  const [showAddSubagent, setShowAddSubagent] = useState(false);
  const [newSubagent, setNewSubagent] = useState({
    name: '',
    description: '',
    system_prompt: '',
  });

  // Collapsible section state
  const [propertiesExpanded, setPropertiesExpanded] = useState(true);
  const [toolsExpanded, setToolsExpanded] = useState(true);
  const [promptExpanded, setPromptExpanded] = useState(false);

  // Skills state
  const [agentSkills, setAgentSkills] = useState<{ id: string; name: string; description: string; slug: string }[]>([]);
  const [skillsExpanded, setSkillsExpanded] = useState(false);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [showSkillSearch, setShowSkillSearch] = useState(false);
  const [skillSearchQuery, setSkillSearchQuery] = useState('');
  const [skillSearchResults, setSkillSearchResults] = useState<{ id: string; name: string; description: string; slug: string; category: string }[]>([]);
  const [skillSearchLoading, setSkillSearchLoading] = useState(false);

  // Load subagents when section is expanded
  useEffect(() => {
    if (subagentsExpanded && agent.id && subagents.length === 0) {
      setSubagentsLoading(true);
      marketplaceApi
        .getSubagents(agent.id)
        .then((data) => {
          setSubagents(data.subagents || []);
        })
        .catch((err) => {
          console.error('Failed to load subagents:', err);
        })
        .finally(() => setSubagentsLoading(false));
    }
  }, [subagentsExpanded, agent.id, subagents.length]);

  // Load skills when section is expanded
  useEffect(() => {
    if (skillsExpanded && agent.id && agentSkills.length === 0) {
      setSkillsLoading(true);
      marketplaceApi
        .getAgentSkills(agent.id)
        .then((data) => {
          setAgentSkills((data.skills || []).map((s: { id: string; name: string; description: string; slug: string }) => ({
            id: s.id,
            name: s.name,
            description: s.description,
            slug: s.slug,
          })));
        })
        .catch((err) => {
          console.error('Failed to load agent skills:', err);
        })
        .finally(() => setSkillsLoading(false));
    }
  }, [skillsExpanded, agent.id, agentSkills.length]);

  const toggleFeature = (key: string) => {
    setFeatures((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleReset = () => {
    setSystemPrompt(originalPrompt);
    toast.success('Reset to original system prompt');
  };

  const insertMarker = (marker: string) => {
    editorRef.current?.insertMarker(marker);
  };

  const handleSaveSubagentPrompt = async (subagentId: string) => {
    try {
      await marketplaceApi.updateSubagent(agent.id, subagentId, {
        system_prompt: editingSubagentPrompt,
      });
      setSubagents((prev) =>
        prev.map((s) => (s.id === subagentId ? { ...s, system_prompt: editingSubagentPrompt } : s))
      );
      setEditingSubagent(null);
      toast.success('Subagent prompt updated');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to update subagent');
    }
  };

  const handleAddSubagent = async () => {
    if (!newSubagent.name.trim() || !newSubagent.system_prompt.trim()) {
      toast.error('Name and system prompt are required');
      return;
    }
    try {
      const created = await marketplaceApi.createSubagent(agent.id, {
        name: newSubagent.name,
        description: newSubagent.description,
        system_prompt: newSubagent.system_prompt,
      });
      setSubagents((prev) => [...prev, created]);
      setShowAddSubagent(false);
      setNewSubagent({ name: '', description: '', system_prompt: '' });
      toast.success('Subagent created');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to create subagent');
    }
  };

  const handleDeleteSubagent = async (subagentId: string) => {
    try {
      await marketplaceApi.deleteSubagent(agent.id, subagentId);
      setSubagents((prev) => prev.filter((s) => s.id !== subagentId));
      toast.success('Subagent removed');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to delete subagent');
    }
  };

  const handleSearchSkills = async (query: string) => {
    setSkillSearchQuery(query);
    if (!query.trim()) {
      setSkillSearchResults([]);
      return;
    }
    setSkillSearchLoading(true);
    try {
      const data = await marketplaceApi.getAllSkills({ search: query, limit: 5 });
      const installed = new Set(agentSkills.map((s) => s.id));
      setSkillSearchResults(
        (data.skills || [])
          .filter((s: { id: string }) => !installed.has(s.id))
          .map((s: { id: string; name: string; description: string; slug: string; category: string }) => ({
            id: s.id,
            name: s.name,
            description: s.description,
            slug: s.slug,
            category: s.category,
          }))
      );
    } catch {
      setSkillSearchResults([]);
    } finally {
      setSkillSearchLoading(false);
    }
  };

  const handleInstallSkill = async (skillId: string) => {
    try {
      await marketplaceApi.installSkillOnAgent(skillId, agent.id);
      const skill = skillSearchResults.find((s) => s.id === skillId);
      if (skill) {
        setAgentSkills((prev) => [...prev, { id: skill.id, name: skill.name, description: skill.description, slug: skill.slug }]);
        setSkillSearchResults((prev) => prev.filter((s) => s.id !== skillId));
      }
      toast.success('Skill installed');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to install skill');
    }
  };

  const handleUninstallSkill = async (skillId: string) => {
    try {
      await marketplaceApi.uninstallSkillFromAgent(skillId, agent.id);
      setAgentSkills((prev) => prev.filter((s) => s.id !== skillId));
      toast.success('Skill removed');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to remove skill');
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      name,
      description,
      system_prompt: systemPrompt,
      model,
      tools,
      tool_configs: toolConfigs,
      avatar_url: avatarUrl,
      config: { features },
    });
  };

  // Card wrapper for each section
  const card = 'bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden';

  // Collapsible section header inside a card
  const SectionHeader = ({ label, count, expanded, onToggle, trailing }: { label: string; icon?: React.ReactNode; count?: number; expanded: boolean; onToggle: () => void; trailing?: React.ReactNode }) => (
    <div className="flex items-center">
      <button
        type="button"
        onClick={onToggle}
        className="flex-1 flex items-center gap-2 px-4 py-2.5 hover:bg-[var(--surface-hover)] transition-colors group"
      >
        <span className="text-[11px] font-medium text-[var(--text-muted)] group-hover:text-[var(--text)]">{label}</span>
        {count != null && count > 0 && (
          <span className="text-[10px] text-[var(--text-subtle)]">{count}</span>
        )}
        <span className={`transition-transform duration-200 text-[var(--text-subtle)] ${expanded ? 'rotate-0' : '-rotate-90'}`}>
          <CaretDown size={10} />
        </span>
      </button>
      {trailing && <div className="pr-3 flex-shrink-0">{trailing}</div>}
    </div>
  );

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">

      {/* Identity card — save + close + avatar + name */}
      <div className={card}>
        <div className="flex items-center justify-between h-10 px-4 border-b border-[var(--border)]">
          <span className="text-xs font-semibold text-[var(--text)] truncate">{name || 'New Agent'}</span>
          <div className="flex items-center gap-1.5">
            <button type="button" onClick={() => handleSubmit({ preventDefault: () => {} } as React.FormEvent)} className="btn btn-sm btn-filled">Save</button>
            <button type="button" onClick={onClose} className="btn btn-icon btn-sm"><X size={14} /></button>
          </div>
        </div>
        <div className="flex items-start gap-3 p-4">
          <ImageUpload value={avatarUrl} onChange={setAvatarUrl} maxSizeKB={200} />
          <div className="flex-1 min-w-0 pt-0.5">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full text-sm font-semibold bg-transparent text-[var(--text)] outline-none placeholder:text-[var(--text-subtle)]"
              placeholder="Agent name"
              required
            />
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full text-xs bg-transparent text-[var(--text-muted)] outline-none placeholder:text-[var(--text-subtle)] mt-0.5"
              placeholder="Add a description..."
            />
          </div>
        </div>
      </div>

      {/* Properties card */}
      <div className={card}>
        <SectionHeader label="Properties" icon={<Gear size={13} />} expanded={propertiesExpanded} onToggle={() => setPropertiesExpanded(!propertiesExpanded)} />
        {propertiesExpanded && (
          <div className="px-4 pb-4 space-y-3">
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-[var(--text-subtle)] w-14 flex-shrink-0">Model</span>
              <div className="flex-1">
                <ModelSelector
                  currentAgent={{ id: agent.id, name: agent.name, icon: agent.icon || '', model: agent.model, selectedModel: model, sourceType: agent.source_type, isCustom: agent.is_custom }}
                  onModelChange={setModel}
                  dropUp={false}
                />
              </div>
            </div>
            {agent.agent_type === 'TesslateAgent' && FEATURE_FLAGS.map((flag) => (
              <div key={flag.key} className="flex items-center gap-3">
                <span className="text-[11px] text-[var(--text-subtle)] w-14 flex-shrink-0">{flag.label}</span>
                <button type="button" onClick={() => toggleFeature(flag.key)} className="flex items-center">
                  {features[flag.key] ? (
                    <ToggleRight size={20} weight="fill" className="text-[var(--primary)]" />
                  ) : (
                    <ToggleLeft size={20} className="text-[var(--text-subtle)]" />
                  )}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Tools card */}
      <div className={card}>
        <SectionHeader label="Tools" icon={<Wrench size={13} />} count={tools.length} expanded={toolsExpanded} onToggle={() => setToolsExpanded(!toolsExpanded)} />
        {toolsExpanded && (
          <div className="px-4 pb-4">
            <ToolManagement
              selectedTools={tools}
              toolConfigs={toolConfigs}
              onToolsChange={(newTools, newConfigs) => { setTools(newTools); setToolConfigs(newConfigs); }}
              defaultCollapsed
            />
          </div>
        )}
      </div>

          {/* Subagents card */}
          {agent.agent_type === 'TesslateAgent' && (
            <div className={card}>
              <SectionHeader label="Subagents" icon={<Robot size={13} />} count={subagents.length} expanded={subagentsExpanded} onToggle={() => setSubagentsExpanded(!subagentsExpanded)} />
              {subagentsExpanded && (
                <div className="px-4 pb-4 space-y-2">
                  {subagentsLoading ? (
                    <div className="flex justify-center py-4"><LoadingSpinner /></div>
                  ) : (
                    <>
                      {subagents.map((sub) => (
                        <div key={sub.id} className="p-2.5 rounded-lg bg-[var(--surface-hover)] border border-[var(--border)]">
                          {editingSubagent === sub.id ? (
                            <div className="space-y-2">
                              <span className="text-xs font-medium text-[var(--text)]">{sub.name}</span>
                              <textarea
                                value={editingSubagentPrompt}
                                onChange={(e) => setEditingSubagentPrompt(e.target.value)}
                                className="w-full px-2.5 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-md text-[var(--text)] text-xs font-mono focus:outline-none focus:border-[var(--primary)] resize-y"
                                rows={6}
                              />
                              <div className="flex gap-1.5 justify-end">
                                <button type="button" onClick={() => setEditingSubagent(null)} className="btn btn-sm">Cancel</button>
                                <button type="button" onClick={() => handleSaveSubagentPrompt(sub.id)} className="btn btn-sm btn-filled">Save</button>
                              </div>
                            </div>
                          ) : (
                            <div className="flex items-center justify-between gap-2">
                              <div className="min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <span className="text-xs font-medium text-[var(--text)]">{sub.name}</span>
                                  {sub.is_builtin && <span className="text-[9px] px-1 py-px rounded bg-[var(--border)] text-[var(--text-subtle)]">built-in</span>}
                                </div>
                                <p className="text-[11px] text-[var(--text-subtle)] truncate">{sub.description}</p>
                              </div>
                              <div className="flex items-center gap-1 flex-shrink-0">
                                <button type="button" onClick={() => { setEditingSubagent(sub.id); setEditingSubagentPrompt(sub.system_prompt || ''); }} className="btn btn-sm">Edit</button>
                                {!sub.is_builtin && (
                                  <button type="button" onClick={() => handleDeleteSubagent(sub.id)} className="btn btn-icon btn-sm btn-danger"><Trash size={12} /></button>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                      {showAddSubagent ? (
                        <div className="p-2.5 rounded-lg bg-[var(--surface-hover)] border border-[var(--primary)]/30 space-y-2">
                          <input type="text" value={newSubagent.name} onChange={(e) => setNewSubagent((p) => ({ ...p, name: e.target.value }))} placeholder="Name" className="w-full px-2.5 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-md text-xs text-[var(--text)] focus:outline-none focus:border-[var(--primary)]" />
                          <input type="text" value={newSubagent.description} onChange={(e) => setNewSubagent((p) => ({ ...p, description: e.target.value }))} placeholder="Description" className="w-full px-2.5 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-md text-xs text-[var(--text)] focus:outline-none focus:border-[var(--primary)]" />
                          <textarea value={newSubagent.system_prompt} onChange={(e) => setNewSubagent((p) => ({ ...p, system_prompt: e.target.value }))} placeholder="System prompt..." className="w-full px-2.5 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-md text-xs font-mono text-[var(--text)] focus:outline-none focus:border-[var(--primary)] resize-y" rows={4} />
                          <div className="flex gap-1.5 justify-end">
                            <button type="button" onClick={() => { setShowAddSubagent(false); setNewSubagent({ name: '', description: '', system_prompt: '' }); }} className="btn btn-sm">Cancel</button>
                            <button type="button" onClick={handleAddSubagent} className="btn btn-sm btn-filled">Create</button>
                          </div>
                        </div>
                      ) : (
                        <button type="button" onClick={() => setShowAddSubagent(true)} className="btn btn-sm w-full"><Plus size={12} /> Add Subagent</button>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Skills card */}
          <div className={card}>
            <SectionHeader
              label="Skills"
              icon={<Lightning size={13} />}
              count={agentSkills.length}
              expanded={skillsExpanded}
              onToggle={() => setSkillsExpanded(!skillsExpanded)}
              trailing={
                <button type="button" onClick={() => { setSkillsExpanded(true); setShowSkillSearch(true); }} className="btn btn-icon btn-sm"><Plus size={12} /></button>
              }
            />
            {skillsExpanded && (
              <div className="px-4 pb-4 space-y-2">
                {skillsLoading ? (
                  <div className="flex justify-center py-4"><LoadingSpinner /></div>
                ) : (
                  <>
                    {agentSkills.map((skill) => (
                      <div key={skill.id} className="flex items-center justify-between p-2.5 rounded-lg bg-[var(--surface-hover)] border border-[var(--border)]">
                        <div className="min-w-0">
                          <span className="text-xs font-medium text-[var(--text)]">{skill.name}</span>
                          <p className="text-[11px] text-[var(--text-subtle)] truncate">{skill.description}</p>
                        </div>
                        <button type="button" onClick={() => handleUninstallSkill(skill.id)} className="btn btn-icon btn-sm btn-danger flex-shrink-0 ml-2"><Trash size={12} /></button>
                      </div>
                    ))}
                    {showSkillSearch ? (
                      <div className="space-y-2">
                        <input
                          type="text"
                          value={skillSearchQuery}
                          onChange={(e) => handleSearchSkills(e.target.value)}
                          placeholder="Search skills..."
                          className="w-full px-2.5 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-md text-xs text-[var(--text)] focus:outline-none focus:border-[var(--primary)]"
                          autoFocus
                        />
                        {skillSearchLoading && <div className="flex justify-center py-2"><LoadingSpinner /></div>}
                        {skillSearchResults.map((skill) => (
                          <div key={skill.id} className="flex items-center justify-between p-2 rounded-lg bg-[var(--surface-hover)]">
                            <div className="flex items-center gap-2 min-w-0">
                              <div className="w-6 h-6 rounded-md bg-[var(--primary)]/10 flex items-center justify-center shrink-0 text-[var(--primary)]">{getSkillCategoryIcon(skill.category)}</div>
                              <div className="min-w-0">
                                <span className="text-xs font-medium text-[var(--text)]">{skill.name}</span>
                                <p className="text-[11px] text-[var(--text-subtle)] truncate">{skill.description}</p>
                              </div>
                            </div>
                            <button type="button" onClick={() => handleInstallSkill(skill.id)} className="btn btn-sm btn-filled flex-shrink-0 ml-2">Install</button>
                          </div>
                        ))}
                        {skillSearchQuery && !skillSearchLoading && skillSearchResults.length === 0 && (
                          <p className="text-[11px] text-[var(--text-subtle)] text-center py-2">No skills found</p>
                        )}
                        <button type="button" onClick={() => { setShowSkillSearch(false); setSkillSearchQuery(''); setSkillSearchResults([]); }} className="btn btn-sm w-full">Close Search</button>
                      </div>
                    ) : null}
                  </>
                )}
              </div>
            )}
          </div>

          {/* System Prompt card */}
          <div className={card}>
            <SectionHeader
              label="System Prompt"
              icon={<Article size={13} />}
              expanded={promptExpanded}
              onToggle={() => setPromptExpanded(!promptExpanded)}
            />
            {promptExpanded && (
              <div className="px-4 pb-4 space-y-2">
                <MarkerEditor
                  ref={editorRef}
                  value={systemPrompt}
                  onChange={setSystemPrompt}
                  placeholder="Enter agent instructions..."
                  rows={10}
                />
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[var(--text-subtle)]">{systemPrompt.length.toLocaleString()} chars</span>
                  {systemPrompt !== originalPrompt && (
                    <button type="button" onClick={handleReset} className="btn btn-sm">Reset</button>
                  )}
                </div>
                <MarkerPalette onInsertMarker={insertMarker} />
              </div>
            )}
          </div>

    </form>
  );
}
