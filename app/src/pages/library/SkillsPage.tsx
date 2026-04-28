import { useState, useEffect, useRef } from 'react';
import {
  Plus,
  Storefront,
  MagnifyingGlass,
  X,
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
  Rocket,
  Plugs,
  GithubLogo,
  ArrowSquareOut,
  LockSimpleOpen,
  LockKey,
  CaretDown,
  SortAscending,
  SortDescending,
  Tag,
  Star,
  DownloadSimple,
  Info,
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { marketplaceApi } from '../../lib/api';
import toast from 'react-hot-toast';
import { motion } from 'framer-motion';
import { Badge, staggerContainer, staggerItem } from '../../components/cards';
import type { LibraryAgent } from './types';

// ─── LibrarySkill interface ─────────────────────────────────────────
export interface LibrarySkill {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: string;
  icon: string;
  pricing_type: string;
  price: number;
  downloads: number;
  rating: number;
  tags: string[];
  is_purchased: boolean;
  source_type?: string;
  git_repo_url?: string;
  features?: string[];
}

// Extended detail from API
interface SkillDetail extends LibrarySkill {
  long_description?: string;
  creator_type?: string;
  creator_name?: string;
  creator_username?: string;
  creator_avatar_url?: string;
  usage_count?: number;
  reviews_count?: number;
  is_featured?: boolean;
  is_forkable?: boolean;
}

// ─── Category icon mapping ──────────────────────────────────────────
const SKILL_CATEGORY_ICONS: Record<string, React.ReactNode> = {
  frontend: <Code size={16} weight="duotone" />,
  design: <PaintBucket size={16} weight="duotone" />,
  backend: <Broadcast size={16} weight="duotone" />,
  testing: <TestTube size={16} weight="duotone" />,
  database: <Database size={16} weight="duotone" />,
  security: <Shield size={16} weight="duotone" />,
  media: <FilmStrip size={16} weight="duotone" />,
  'code-quality': <Sparkle size={16} weight="duotone" />,
  deployment: <Rocket size={16} weight="duotone" />,
  devops: <Stack size={16} weight="duotone" />,
};

function getSkillCategoryIcon(category: string, size = 16): React.ReactNode {
  const icons: Record<string, React.ReactNode> = {
    frontend: <Code size={size} weight="duotone" />,
    design: <PaintBucket size={size} weight="duotone" />,
    backend: <Broadcast size={size} weight="duotone" />,
    testing: <TestTube size={size} weight="duotone" />,
    database: <Database size={size} weight="duotone" />,
    security: <Shield size={size} weight="duotone" />,
    media: <FilmStrip size={size} weight="duotone" />,
    'code-quality': <Sparkle size={size} weight="duotone" />,
    deployment: <Rocket size={size} weight="duotone" />,
    devops: <Stack size={size} weight="duotone" />,
  };
  return icons[category] || <Lightning size={size} weight="duotone" />;
}

// Keep the static map for SkillCard/SkillListRow that don't need custom size
void SKILL_CATEGORY_ICONS;

// ─── Sort config ────────────────────────────────────────────────────
type SortField = 'name' | 'category' | 'downloads';
type SortDir = 'asc' | 'desc';
type FilterTab = 'all' | 'open' | 'free';
type ViewMode = 'cards' | 'list';

const sortLabels: Record<SortField, string> = {
  name: 'Name',
  category: 'Category',
  downloads: 'Downloads',
};

// ─── Main SkillsPage component ─────────────────────────────────────
export default function SkillsPage({
  skills,
  agents,
  loading,
  onBrowse,
}: {
  skills: LibrarySkill[];
  agents: LibraryAgent[];
  loading: boolean;
  onBrowse: () => void;
}) {
  const [filterTab, setFilterTab] = useState<FilterTab>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [viewMode, setViewMode] = useState<ViewMode>('cards');
  const [showSortMenu, setShowSortMenu] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState<LibrarySkill | null>(null);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const sortMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (showSearch) searchInputRef.current?.focus();
  }, [showSearch]);

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
  const filtered = skills
    .filter((s) => {
      if (filterTab === 'open' && s.source_type !== 'open') return false;
      if (filterTab === 'free' && s.pricing_type !== 'free') return false;
      return true;
    })
    .filter((s) => {
      if (!searchQuery) return true;
      const q = searchQuery.toLowerCase();
      return (
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.category.toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      let cmp = 0;
      if (sortField === 'name') cmp = a.name.localeCompare(b.name);
      else if (sortField === 'category') cmp = a.category.localeCompare(b.category);
      else if (sortField === 'downloads') cmp = (a.downloads || 0) - (b.downloads || 0);
      return sortDir === 'desc' ? -cmp : cmp;
    });

  const openSourceCount = skills.filter((s) => s.source_type === 'open').length;
  const freeCount = skills.filter((s) => s.pricing_type === 'free').length;

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      {/* Toolbar */}
      <div className="h-10 flex items-center justify-between flex-shrink-0" style={{ paddingLeft: '7px', paddingRight: '10px' }}>
        <div className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-none" style={{ maskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)', WebkitMaskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)' }}>
          <button onClick={() => setFilterTab('all')} className={`btn ${filterTab === 'all' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}>
            All skills <span className="text-[10px] opacity-50 ml-0.5">{skills.length}</span>
          </button>
          <button onClick={() => setFilterTab('open')} className={`btn ${filterTab === 'open' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}>
            Open Source <span className="text-[10px] opacity-50 ml-0.5">{openSourceCount}</span>
          </button>
          <button onClick={() => setFilterTab('free')} className={`btn ${filterTab === 'free' ? 'btn-tab-active' : 'btn-tab'} shrink-0`}>
            Free <span className="text-[10px] opacity-50 ml-0.5">{freeCount}</span>
          </button>
        </div>

        <div className="flex items-center gap-[2px]">
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

          <div ref={sortMenuRef} className="relative">
            <button onClick={() => setShowSortMenu((v) => !v)} className={`btn ${sortField !== 'name' || sortDir !== 'asc' ? 'btn-active' : ''}`} style={{ gap: '4px' }}>
              {sortDir === 'desc' ? <SortDescending size={16} /> : <SortAscending size={16} />}
              <span className="hidden sm:inline text-xs">{sortLabels[sortField]}</span>
              <CaretDown size={12} className="opacity-50" />
            </button>
            {showSortMenu && (
              <div className="absolute right-0 top-full mt-1 z-50 min-w-[180px] py-1 rounded-[var(--radius-medium)] border bg-[var(--surface)]" style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}>
                <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">Sort by</div>
                {(['name', 'category', 'downloads'] as const).map((f) => (
                  <button key={f} onClick={() => { setSortField(f); setShowSortMenu(false); }} className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${sortField === f ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}>
                    {sortLabels[f]}
                  </button>
                ))}
                <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />
                <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">Direction</div>
                <button onClick={() => { setSortDir('asc'); setShowSortMenu(false); }} className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${sortDir === 'asc' ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}>Ascending</button>
                <button onClick={() => { setSortDir('desc'); setShowSortMenu(false); }} className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 ${sortDir === 'desc' ? 'text-[var(--text)] bg-[var(--surface-hover)]' : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)]'}`}>Descending</button>
              </div>
            )}
          </div>

          <button onClick={() => setViewMode((v) => v === 'cards' ? 'list' : 'cards')} className={`btn btn-icon ${viewMode === 'list' ? 'btn-active' : ''}`}>
            {viewMode === 'cards' ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
            )}
          </button>

          <div className="w-px h-[22px] bg-[var(--border)] mx-0.5" />

          <button onClick={onBrowse} className="btn">
            <Storefront size={16} />
            <span className="hidden sm:inline">Browse</span>
          </button>
        </div>
      </div>

      {/* Content area + Detail panel */}
      <div className="flex-1 overflow-hidden flex relative">
        <div className="flex-1 overflow-auto min-w-0">
          <div className="p-4 md:p-5">
            {skills.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="w-12 h-12 bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] flex items-center justify-center mb-4">
                  <Lightning size={24} className="text-[var(--text-subtle)]" />
                </div>
                <h3 className="text-xs font-semibold text-[var(--text)] mb-2">No skills yet</h3>
                <p className="text-[11px] text-[var(--text-muted)] max-w-sm mb-6">
                  Skills teach your agents specialized patterns and best practices.
                  Browse the marketplace to find skills for frontend, backend, DevOps, and more.
                </p>
                <button onClick={onBrowse} className="btn btn-filled flex items-center gap-2">
                  <Plus size={16} />
                  Browse Skills Marketplace
                </button>
              </div>
            ) : filtered.length === 0 ? (
              <div className="text-center py-16">
                <MagnifyingGlass size={48} className="mx-auto mb-4 text-[var(--text-subtle)]" />
                <p className="text-[var(--text-muted)] mb-2">No skills match your filters</p>
                <button
                  onClick={() => { setFilterTab('all'); setSearchQuery(''); }}
                  className="text-xs text-[var(--primary)] hover:underline"
                >
                  Clear filters
                </button>
              </div>
            ) : viewMode === 'cards' ? (
              <motion.div variants={staggerContainer} initial="initial" animate="animate" className="grid gap-5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
                {filtered.map((skill) => (
                  <SkillCard
                    key={skill.id}
                    skill={skill}
                    agents={agents}
                    isSelected={selectedSkill?.id === skill.id}
                    onSelect={() => setSelectedSkill(selectedSkill?.id === skill.id ? null : skill)}
                  />
                ))}
              </motion.div>
            ) : (
              <div className="space-y-1">
                {filtered.map((skill) => (
                  <SkillListRow
                    key={skill.id}
                    skill={skill}
                    agents={agents}
                    isSelected={selectedSkill?.id === skill.id}
                    onSelect={() => setSelectedSkill(selectedSkill?.id === skill.id ? null : skill)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Detail panel */}
        {selectedSkill && (
          <div
            className="w-full sm:w-[360px] lg:w-[440px] xl:w-[480px] max-sm:absolute max-sm:inset-0 max-sm:z-30 max-sm:bg-[var(--bg)] flex-shrink-0 overflow-y-auto animate-slide-in-right max-sm:!pl-[var(--app-margin)]"
            style={{ padding: 'var(--app-margin)', paddingLeft: 0 }}
          >
            <SkillDetailPanel
              skill={selectedSkill}
              agents={agents}
              onClose={() => setSelectedSkill(null)}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ─── SkillDetailPanel (sidebar) ─────────────────────────────────────
function SkillDetailPanel({
  skill,
  agents,
  onClose,
}: {
  skill: LibrarySkill;
  agents: LibraryAgent[];
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);
  const [descriptionExpanded, setDescriptionExpanded] = useState(true);
  const [featuresExpanded, setFeaturesExpanded] = useState(true);
  const [tagsExpanded, setTagsExpanded] = useState(false);
  const [agentsExpanded, setAgentsExpanded] = useState(true);
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const [installing, setInstalling] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Fetch full skill details
  useEffect(() => {
    setDetailLoading(true);
    marketplaceApi
      .getSkillDetails(skill.slug)
      .then((data) => setDetail(data as SkillDetail))
      .catch(() => {
        // Fall back to basic skill data
        setDetail(skill as SkillDetail);
      })
      .finally(() => setDetailLoading(false));
  }, [skill.slug]);

  // Close dropdown on outside click
  useEffect(() => {
    if (!showAgentDropdown) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowAgentDropdown(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showAgentDropdown]);

  const handleInstall = async (agentId: string, agentName: string) => {
    setInstalling(true);
    try {
      await marketplaceApi.installSkillOnAgent(skill.id, agentId);
      toast.success(`${skill.name} added to ${agentName}`);
      setShowAgentDropdown(false);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to install skill');
    } finally {
      setInstalling(false);
    }
  };

  const enabledAgents = agents.filter((a) => a.is_enabled !== false);
  const d = detail || skill;
  const card = 'bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden';

  const SectionHeader = ({ label, count, expanded, onToggle }: { label: string; count?: number; expanded: boolean; onToggle: () => void }) => (
    <button
      type="button"
      onClick={onToggle}
      className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-[var(--surface-hover)] transition-colors group"
    >
      <span className="text-[11px] font-medium text-[var(--text-muted)] group-hover:text-[var(--text)]">{label}</span>
      {count != null && count > 0 && (
        <span className="text-[10px] text-[var(--text-subtle)]">{count}</span>
      )}
      <span className={`transition-transform duration-200 text-[var(--text-subtle)] ${expanded ? 'rotate-0' : '-rotate-90'}`}>
        <CaretDown size={10} />
      </span>
    </button>
  );

  return (
    <div className="flex flex-col gap-2">
      {/* Identity card */}
      <div className={card}>
        <div className="flex items-center justify-between h-10 px-4 border-b border-[var(--border)]">
          <span className="text-xs font-semibold text-[var(--text)] truncate">{d.name}</span>
          <button type="button" onClick={onClose} className="btn btn-icon btn-sm">
            <X size={14} />
          </button>
        </div>
        <div className="flex items-start gap-3 p-4">
          <div className="w-10 h-10 rounded-[var(--radius-medium)] bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center shrink-0 text-[var(--primary)]">
            {getSkillCategoryIcon(d.category, 20)}
          </div>
          <div className="flex-1 min-w-0 pt-0.5">
            <h3 className="text-sm font-semibold text-[var(--text)] truncate">{d.name}</h3>
            <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{d.description}</p>
            <div className="flex flex-wrap items-center gap-1.5 mt-2">
              <Badge intent="muted">{d.category}</Badge>
              {d.source_type === 'open' ? (
                <Badge intent="success" icon={<LockSimpleOpen size={11} />}>Open</Badge>
              ) : (
                <Badge intent="accent" icon={<LockKey size={11} />}>Closed</Badge>
              )}
              {d.pricing_type === 'free' && <Badge intent="success">Free</Badge>}
            </div>
          </div>
        </div>
        {/* Stats row */}
        <div className="flex items-center gap-4 px-4 pb-3">
          {d.downloads > 0 && (
            <span className="flex items-center gap-1 text-[10px] text-[var(--text-subtle)]">
              <DownloadSimple size={12} /> {d.downloads.toLocaleString()}
            </span>
          )}
          {d.rating > 0 && (
            <span className="flex items-center gap-1 text-[10px] text-[var(--text-subtle)]">
              <Star size={12} weight="fill" className="text-yellow-500" /> {d.rating.toFixed(1)}
            </span>
          )}
          {(detail as SkillDetail)?.creator_name && (
            <span className="flex items-center gap-1 text-[10px] text-[var(--text-subtle)]">
              by {(detail as SkillDetail).creator_name}
            </span>
          )}
        </div>
        {/* GitHub link */}
        {d.git_repo_url && (
          <div className="px-4 pb-3">
            <a
              href={d.git_repo_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-[11px] text-[var(--text-subtle)] hover:text-[var(--text-muted)] transition-colors"
            >
              <GithubLogo size={14} weight="fill" />
              <span className="truncate">{d.git_repo_url.replace('https://github.com/', '')}</span>
              <ArrowSquareOut size={10} className="shrink-0" />
            </a>
          </div>
        )}
      </div>

      {/* Description card */}
      {((detail as SkillDetail)?.long_description || d.description) && (
        <div className={card}>
          <SectionHeader label="About" expanded={descriptionExpanded} onToggle={() => setDescriptionExpanded(!descriptionExpanded)} />
          {descriptionExpanded && (
            <div className="px-4 pb-4">
              {detailLoading ? (
                <div className="flex items-center justify-center py-4">
                  <LoadingSpinner />
                </div>
              ) : (
                <p className="text-xs leading-relaxed text-[var(--text-muted)] whitespace-pre-wrap">
                  {(detail as SkillDetail)?.long_description || d.description}
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Features card */}
      {d.features && d.features.length > 0 && (
        <div className={card}>
          <SectionHeader label="Features" count={d.features.length} expanded={featuresExpanded} onToggle={() => setFeaturesExpanded(!featuresExpanded)} />
          {featuresExpanded && (
            <div className="px-4 pb-4 space-y-1.5">
              {d.features.map((feature, i) => (
                <div key={i} className="flex items-start gap-2">
                  <Info size={12} className="text-[var(--primary)] shrink-0 mt-0.5" />
                  <span className="text-xs text-[var(--text-muted)]">{feature}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tags card */}
      {d.tags && d.tags.length > 0 && (
        <div className={card}>
          <SectionHeader label="Tags" count={d.tags.length} expanded={tagsExpanded} onToggle={() => setTagsExpanded(!tagsExpanded)} />
          {tagsExpanded && (
            <div className="px-4 pb-4 flex flex-wrap gap-1.5">
              {d.tags.map((tag, i) => (
                <span key={i} className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium text-[var(--text-muted)] bg-[var(--bg)] border border-[var(--border)] rounded-full">
                  <Tag size={10} />
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Add to Agent card */}
      <div className={card}>
        <SectionHeader label="Agents" count={enabledAgents.length} expanded={agentsExpanded} onToggle={() => setAgentsExpanded(!agentsExpanded)} />
        {agentsExpanded && (
          <div className="px-4 pb-4">
            <div ref={dropdownRef} className="relative">
              <button
                onClick={() => setShowAgentDropdown(!showAgentDropdown)}
                disabled={installing}
                className="btn w-full flex items-center justify-center gap-1.5 disabled:opacity-50"
              >
                {installing ? (
                  <LoadingSpinner />
                ) : (
                  <>
                    <Plugs size={14} />
                    Add to Agent
                  </>
                )}
              </button>
              {showAgentDropdown && (
                <div
                  className="absolute left-0 right-0 bottom-full mb-1 bg-[var(--surface)] border rounded-[var(--radius-medium)] z-20 py-1 max-h-52 overflow-y-auto"
                  style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}
                >
                  {enabledAgents.length === 0 ? (
                    <p className="px-3 py-3 text-xs text-[var(--text-muted)] text-center">
                      No active agents. Enable an agent first.
                    </p>
                  ) : (
                    enabledAgents.map((agent) => (
                      <button
                        key={agent.id}
                        onClick={() => handleInstall(agent.id, agent.name)}
                        className="w-full text-left px-3 py-1.5 text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors flex items-center gap-2"
                      >
                        {agent.avatar_url ? (
                          <img src={agent.avatar_url} alt="" className="w-6 h-6 rounded-lg object-cover border border-[var(--border)]" />
                        ) : (
                          <div className="w-6 h-6 rounded-lg bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center">
                            <img src="/favicon.svg" alt="" className="w-4 h-4" />
                          </div>
                        )}
                        <span className="truncate font-medium">{agent.name}</span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── SkillListRow (list view) ───────────────────────────────────────
function SkillListRow({
  skill,
  agents,
  isSelected,
  onSelect,
}: {
  skill: LibrarySkill;
  agents: LibraryAgent[];
  isSelected: boolean;
  onSelect: () => void;
}) {
  const [showDropdown, setShowDropdown] = useState(false);
  const [installing, setInstalling] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

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

  const handleInstall = async (agentId: string, agentName: string) => {
    setInstalling(true);
    try {
      await marketplaceApi.installSkillOnAgent(skill.id, agentId);
      toast.success(`${skill.name} added to ${agentName}`);
      setShowDropdown(false);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to install skill');
    } finally {
      setInstalling(false);
    }
  };

  const enabledAgents = agents.filter((a) => a.is_enabled !== false);

  return (
    <div
      onClick={onSelect}
      className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors cursor-pointer ${
        isSelected
          ? 'bg-[var(--surface-hover)] border border-[var(--border-hover)]'
          : 'hover:bg-[var(--surface-hover)] border border-transparent'
      }`}
    >
      <div className="w-7 h-7 rounded-lg bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center shrink-0 text-[var(--primary)]">
        {getSkillCategoryIcon(skill.category)}
      </div>
      <div className="flex-1 min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-[var(--text)] truncate">{skill.name}</span>
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${skill.is_purchased ? 'bg-[var(--status-success)]' : 'bg-[var(--text-subtle)]'}`} />
        </span>
        <span className="text-[11px] text-[var(--text-subtle)] block truncate">{skill.description}</span>
      </div>
      <span className="text-[10px] text-[var(--text-muted)] hidden sm:block truncate max-w-[100px] capitalize">
        {skill.category}
      </span>
      <div className="hidden md:flex items-center gap-1">
        {skill.source_type === 'open' ? (
          <Badge intent="success" icon={<LockSimpleOpen size={11} />}>Open</Badge>
        ) : (
          <Badge intent="accent" icon={<LockKey size={11} />}>Closed</Badge>
        )}
        {skill.pricing_type === 'free' && (
          <Badge intent="success">Free</Badge>
        )}
      </div>
      <div ref={dropdownRef} className="relative shrink-0" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => setShowDropdown(!showDropdown)}
          disabled={installing}
          className="shrink-0 p-1 rounded-md hover:bg-[var(--surface)] transition-colors"
        >
          {installing ? (
            <LoadingSpinner />
          ) : (
            <Plugs size={14} className="text-[var(--text-subtle)]" />
          )}
        </button>
        {showDropdown && (
          <div
            className="absolute right-0 bottom-full mb-1 bg-[var(--surface)] border rounded-[var(--radius-medium)] z-20 py-1 max-h-52 overflow-y-auto min-w-[200px]"
            style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}
          >
            <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">Add to agent</div>
            {enabledAgents.length === 0 ? (
              <p className="px-3 py-3 text-xs text-[var(--text-muted)] text-center">
                No active agents. Enable an agent first.
              </p>
            ) : (
              enabledAgents.map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => handleInstall(agent.id, agent.name)}
                  className="w-full text-left px-3 py-1.5 text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors flex items-center gap-2"
                >
                  {agent.avatar_url ? (
                    <img src={agent.avatar_url} alt="" className="w-6 h-6 rounded-lg object-cover border border-[var(--border)]" />
                  ) : (
                    <div className="w-6 h-6 rounded-lg bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center">
                      <img src="/favicon.svg" alt="" className="w-4 h-4" />
                    </div>
                  )}
                  <span className="truncate font-medium">{agent.name}</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── SkillCard (card view) ──────────────────────────────────────────
function SkillCard({
  skill,
  agents,
  isSelected,
  onSelect,
}: {
  skill: LibrarySkill;
  agents: LibraryAgent[];
  isSelected: boolean;
  onSelect: () => void;
}) {
  const [showDropdown, setShowDropdown] = useState(false);
  const [installing, setInstalling] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

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

  const handleInstall = async (agentId: string, agentName: string) => {
    setInstalling(true);
    try {
      await marketplaceApi.installSkillOnAgent(skill.id, agentId);
      toast.success(`${skill.name} added to ${agentName}`);
      setShowDropdown(false);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to install skill');
    } finally {
      setInstalling(false);
    }
  };

  const enabledAgents = agents.filter((a) => a.is_enabled !== false);

  return (
    <motion.div
      variants={staggerItem}
      role="article"
      aria-label={`${skill.name} skill`}
      onClick={onSelect}
      className={`group relative flex flex-col h-full p-4 bg-[var(--surface)] rounded-[var(--radius)] border border-[var(--border)] transition-all duration-200 hover:-translate-y-1 hover:bg-[var(--card-hover)] cursor-pointer ${
        isSelected ? 'border-[var(--primary)] ring-1 ring-[var(--primary)]/20' : ''
      }`}
    >
      <div className="flex items-center gap-3 mb-3">
        <div className="w-8 h-8 rounded-lg bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center shrink-0 text-[var(--primary)]">
          {getSkillCategoryIcon(skill.category)}
        </div>
        <div className="min-w-0">
          <h4 className="text-xs font-semibold text-[var(--text)] truncate">{skill.name}</h4>
          <span className="text-[11px] text-[var(--text-subtle)] capitalize">{skill.category}</span>
        </div>
      </div>

      <p className="text-[11px] leading-relaxed text-[var(--text-muted)] line-clamp-2 mb-3 min-h-[28px]">
        {skill.description}
      </p>

      <div className="flex flex-wrap items-center gap-1.5 mb-3">
        {skill.source_type === 'open' ? (
          <Badge intent="success" icon={<LockSimpleOpen size={11} />}>Open</Badge>
        ) : (
          <Badge intent="accent" icon={<LockKey size={11} />}>Closed</Badge>
        )}
        {skill.pricing_type === 'free' && (
          <Badge intent="success">Free</Badge>
        )}
        {skill.features && skill.features.length > 0 && (
          <>
            {skill.features.slice(0, 2).map((feature, i) => (
              <Badge key={i} intent="muted">{feature}</Badge>
            ))}
            {skill.features.length > 2 && (
              <span className="px-1.5 py-0.5 text-[var(--text-subtle)] text-[10px] font-medium">
                +{skill.features.length - 2}
              </span>
            )}
          </>
        )}
      </div>

      {skill.git_repo_url && (
        <a
          href={skill.git_repo_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-[10px] text-[var(--text-subtle)] hover:text-[var(--text-muted)] transition-colors mb-2"
          onClick={(e) => e.stopPropagation()}
        >
          <GithubLogo size={13} weight="fill" />
          <span className="truncate">{skill.git_repo_url.replace('https://github.com/', '')}</span>
          <ArrowSquareOut size={10} className="shrink-0" />
        </a>
      )}

      <div className="flex-1" />

      <div ref={dropdownRef} className="relative mt-1" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => setShowDropdown(!showDropdown)}
          disabled={installing}
          className="btn w-full flex items-center justify-center gap-1.5 disabled:opacity-50"
        >
          {installing ? (
            <LoadingSpinner />
          ) : (
            <>
              <Plugs size={14} />
              Add to Agent
            </>
          )}
        </button>
        {showDropdown && (
          <div
            className="absolute left-0 right-0 bottom-full mb-1 bg-[var(--surface)] border rounded-[var(--radius-medium)] z-20 py-1 max-h-52 overflow-y-auto"
            style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}
          >
            {enabledAgents.length === 0 ? (
              <p className="px-3 py-3 text-xs text-[var(--text-muted)] text-center">
                No active agents. Enable an agent first.
              </p>
            ) : (
              enabledAgents.map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => handleInstall(agent.id, agent.name)}
                  className="w-full text-left px-3 py-1.5 text-xs text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] transition-colors flex items-center gap-2"
                >
                  {agent.avatar_url ? (
                    <img src={agent.avatar_url} alt="" className="w-6 h-6 rounded-lg object-cover border border-[var(--border)]" />
                  ) : (
                    <div className="w-6 h-6 rounded-lg bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center">
                      <img src="/favicon.svg" alt="" className="w-4 h-4" />
                    </div>
                  )}
                  <span className="truncate font-medium">{agent.name}</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}
