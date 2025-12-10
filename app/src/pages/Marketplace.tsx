import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  MagnifyingGlass,
  FunnelSimple,
  Check,
  ShoppingCart,
  Lightning,
  Sparkle,
  Package,
  X,
  GitFork,
  LockSimpleOpen,
  ChartLine,
  Cpu,
  Wrench,
  Plug,
  File,
  FileText,
  FilePlus,
  Terminal,
  Globe,
  ListChecks,
  Pencil,
  Folder,
  Storefront,
  Books,
  Sun,
  Moon,
  Gear,
  SignOut
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { MobileMenu } from '../components/ui';
import { marketplaceApi } from '../lib/api';
import toast from 'react-hot-toast';
import { useTheme } from '../theme/ThemeContext';

interface MarketplaceItem {
  id: string;
  name: string;
  slug: string;
  description: string;
  long_description?: string;
  category: string;
  item_type: 'agent' | 'base' | 'tool' | 'integration';
  mode?: string;
  agent_type?: string;
  model?: string;
  source_type: 'open' | 'closed';
  is_forkable: boolean;
  is_active: boolean;
  icon: string;
  avatar_url?: string | null;
  pricing_type: string;
  price: number;
  downloads: number;
  rating: number;
  reviews_count: number;
  usage_count: number;
  features: string[];
  tags: string[];
  tools?: string[] | null;
  is_featured: boolean;
  is_purchased: boolean;
  creator_type?: 'official' | 'community';
  creator_name?: string;
}

export default function Marketplace() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [items, setItems] = useState<MarketplaceItem[]>([]);
  const [filteredItems, setFilteredItems] = useState<MarketplaceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedItemType, setSelectedItemType] = useState<'agent' | 'base' | 'tool' | 'integration'>('agent');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showItemDetail, setShowItemDetail] = useState<MarketplaceItem | null>(null);

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  // Sidebar items for mobile menu
  const mobileMenuItems = {
    left: [
      {
        icon: <Folder className="w-5 h-5" weight="fill" />,
        title: 'Projects',
        onClick: () => navigate('/dashboard')
      },
      {
        icon: <Storefront className="w-5 h-5" weight="fill" />,
        title: 'Marketplace',
        onClick: () => {},
        active: true
      },
      {
        icon: <Books className="w-5 h-5" weight="fill" />,
        title: 'Library',
        onClick: () => navigate('/library')
      },
      {
        icon: <Package className="w-5 h-5" weight="fill" />,
        title: 'Components',
        onClick: () => toast('Components library coming soon!')
      }
    ],
    right: [
      {
        icon: theme === 'dark' ? <Sun className="w-5 h-5" weight="fill" /> : <Moon className="w-5 h-5" weight="fill" />,
        title: theme === 'dark' ? 'Light Mode' : 'Dark Mode',
        onClick: toggleTheme
      },
      {
        icon: <Gear className="w-5 h-5" weight="fill" />,
        title: 'Settings',
        onClick: () => navigate('/settings')
      },
      {
        icon: <SignOut className="w-5 h-5" weight="fill" />,
        title: 'Logout',
        onClick: logout
      }
    ]
  };

  const categories = [
    { id: 'all', name: 'All Agents' },
    { id: 'builder', name: 'Builder' },
    { id: 'frontend', name: 'Frontend' },
    { id: 'fullstack', name: 'Full Stack' },
    { id: 'data', name: 'Data & AI' }
  ];

  useEffect(() => {
    loadMarketplaceItems();
  }, []);

  useEffect(() => {
    filterItems();
  }, [items, selectedItemType, selectedCategory, searchQuery]);

  const loadMarketplaceItems = async () => {
    try {
      const [agentsData, basesData] = await Promise.all([
        marketplaceApi.getAllAgents(),
        marketplaceApi.getAllBases()
      ]);

      const agents = (agentsData.agents || []).map((agent: any) => ({
        ...agent,
        item_type: 'agent'
      }));

      const bases = (basesData.bases || []).map((base: any) => ({
        ...base,
        item_type: 'base'
      }));

      setItems([...agents, ...bases]);
    } catch (error) {
      console.error('Failed to load marketplace:', error);
      toast.error('Failed to load marketplace');
    } finally {
      setLoading(false);
    }
  };

  const filterItems = () => {
    let filtered = [...items];

    // Filter by item type
    filtered = filtered.filter(item => item.item_type === selectedItemType);

    if (selectedCategory !== 'all') {
      filtered = filtered.filter(item => item.category === selectedCategory);
    }

    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(item =>
        item.name.toLowerCase().includes(query) ||
        item.description.toLowerCase().includes(query) ||
        item.tags.some(tag => tag.toLowerCase().includes(query))
      );
    }

    setFilteredItems(filtered);
  };

  const handlePurchase = async (item: MarketplaceItem) => {
    if (item.is_purchased) {
      toast.success(`${item.name} already in your library`);
      return;
    }

    if (!item.is_active) {
      toast('Coming soon!', { icon: 'ℹ️' });
      return;
    }

    try {
      // Call the correct endpoint based on item type
      const data = item.item_type === 'base'
        ? await marketplaceApi.purchaseBase(item.id)
        : await marketplaceApi.purchaseAgent(item.id);

      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        toast.success(`${item.name} added to your library!`);
        setItems(prev => prev.map(i =>
          i.id === item.id ? { ...i, is_purchased: true } : i
        ));
      }
    } catch (error) {
      console.error('Failed to purchase:', error);
      toast.error('Failed to add to library');
    }
  };

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading marketplace..." size={80} />
      </div>
    );
  }

  return (
    <>
      {/* Mobile Menu */}
      <MobileMenu leftItems={mobileMenuItems.left} rightItems={mobileMenuItems.right} />
        {/* Top Bar with Search and Filters */}
        <div className="bg-[var(--surface)] border-b border-white/10">
          <div className="h-12 flex items-center px-4 md:px-6 justify-between border-b border-white/10">
            <h1 className="font-heading text-sm font-semibold text-[var(--text)]">Marketplace</h1>

            {/* Mobile hamburger menu */}
            <button
              onClick={() => window.dispatchEvent(new Event('toggleMobileMenu'))}
              className="md:hidden p-2 hover:bg-white/10 active:bg-white/20 rounded-lg transition-colors"
            >
              <svg className="w-6 h-6 text-[var(--text)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          </div>

          {/* Search Bar */}
          <div className="p-4 md:px-6">
            <div className="relative max-w-2xl">
              <MagnifyingGlass className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text)]/40" size={20} />
              <input
                type="text"
                placeholder="Search marketplace..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className={`w-full pl-12 pr-4 py-2.5 border rounded-lg text-sm text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] ${
                  theme === 'light' ? 'bg-black/5 border-black/20' : 'bg-white/5 border-white/10'
                }`}
              />
            </div>
          </div>

          {/* Item Type Tabs */}
          <div className="px-4 md:px-6 pb-3">
            <div className="flex items-center gap-2 overflow-x-auto">
              <button
                onClick={() => { setSelectedItemType('agent'); setSelectedCategory('all'); }}
                className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                  selectedItemType === 'agent'
                    ? 'bg-[var(--primary)] text-white'
                    : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
                }`}
              >
                <Cpu size={16} weight={selectedItemType === 'agent' ? 'fill' : 'regular'} />
                Agents
              </button>
              <button
                onClick={() => { setSelectedItemType('base'); setSelectedCategory('all'); }}
                className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                  selectedItemType === 'base'
                    ? 'bg-[var(--primary)] text-white'
                    : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
                }`}
              >
                <Package size={16} weight={selectedItemType === 'base' ? 'fill' : 'regular'} />
                Bases
              </button>
              <button
                onClick={() => { setSelectedItemType('tool'); setSelectedCategory('all'); }}
                className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                  selectedItemType === 'tool'
                    ? 'bg-[var(--primary)] text-white'
                    : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
                }`}
              >
                <Wrench size={16} weight={selectedItemType === 'tool' ? 'fill' : 'regular'} />
                Tools
              </button>
              <button
                onClick={() => { setSelectedItemType('integration'); setSelectedCategory('all'); }}
                className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                  selectedItemType === 'integration'
                    ? 'bg-[var(--primary)] text-white'
                    : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
                }`}
              >
                <Plug size={16} weight={selectedItemType === 'integration' ? 'fill' : 'regular'} />
                Integrations
              </button>
            </div>

            {/* Filter Pills - Only show for agents */}
            {selectedItemType === 'agent' && (
              <div className="mt-3 flex items-center gap-2 overflow-x-auto">
                {categories.map(category => (
                  <button
                    key={category.id}
                    onClick={() => setSelectedCategory(category.id)}
                    className={`px-3 py-1 rounded-full text-xs font-medium transition-all whitespace-nowrap ${
                      selectedCategory === category.id
                        ? 'bg-[var(--primary)] text-white'
                        : theme === 'light'
                          ? 'bg-black/10 text-black/70 hover:bg-black/20'
                          : 'bg-white/10 text-white/70 hover:bg-white/20'
                    }`}
                  >
                    {category.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-auto bg-[var(--bg)]">
          <div className="p-4 md:p-6">

      {/* Featured Section */}
      {filteredItems.filter(item => item.is_featured).length > 0 && (
        <div className="mb-12">
          <div className="flex items-center justify-between mb-6">
            <h3 className="font-heading text-2xl font-bold text-[var(--text)]">
              Featured {selectedItemType === 'agent' ? 'Agents' : selectedItemType === 'base' ? 'Bases' : selectedItemType === 'tool' ? 'Tools' : 'Integrations'}
            </h3>
            <button className="text-sm text-[var(--text)]/60 hover:text-[var(--text)] font-medium flex items-center gap-1">
              View all <span>→</span>
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6 gap-4">
            {filteredItems.filter(item => item.is_featured).slice(0, 6).map(item => (
              <ItemCard
                key={item.id}
                item={item}
                onClick={() => setShowItemDetail(item)}
                onPurchase={() => handlePurchase(item)}
                theme={theme}
              />
            ))}
          </div>
        </div>
      )}

      {/* Open Source Section */}
      {filteredItems.filter(item => item.source_type === 'open').length > 0 && (
        <div className="mb-12">
          <div className="flex items-center justify-between mb-6">
            <h3 className="font-heading text-2xl font-bold text-[var(--text)]">
              Open Source {selectedItemType === 'agent' ? 'Agents' : selectedItemType === 'base' ? 'Bases' : selectedItemType === 'tool' ? 'Tools' : 'Integrations'}
            </h3>
            <button className="text-sm text-[var(--text)]/60 hover:text-[var(--text)] font-medium flex items-center gap-1">
              View all <span>→</span>
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6 gap-4">
            {filteredItems.filter(item => item.source_type === 'open' && !item.is_featured).slice(0, 6).map(item => (
              <ItemCard
                key={item.id}
                item={item}
                onClick={() => setShowItemDetail(item)}
                onPurchase={() => handlePurchase(item)}
                theme={theme}
              />
            ))}
          </div>
        </div>
      )}

      {filteredItems.length === 0 && (
        <div className="text-center py-16">
          <Package size={48} className="mx-auto mb-4 text-[var(--text)]/20" />
          <p className="text-[var(--text)]/60">No agents found matching your criteria</p>
        </div>
      )}

          </div>
        </div>

      {/* Detail Modal */}
      {showItemDetail && (
        <ItemDetailModal
          item={showItemDetail}
          onClose={() => setShowItemDetail(null)}
          onPurchase={() => {
            handlePurchase(showItemDetail);
            setShowItemDetail(null);
          }}
          theme={theme}
        />
      )}

    </>
  );
}

// All available tools in the system
const ALL_TOOLS = [
  'read_file',
  'write_file',
  'patch_file',
  'multi_edit',
  'bash_exec',
  'shell_open',
  'shell_exec',
  'shell_close',
  'get_project_info',
  'todo_read',
  'todo_write',
  'web_fetch'
];

// Tool icon mapping
const toolIcons: Record<string, { icon: React.ReactNode; label: string }> = {
  read_file: { icon: <File size={14} weight="fill" />, label: 'Read' },
  write_file: { icon: <FilePlus size={14} weight="fill" />, label: 'Write' },
  patch_file: { icon: <Pencil size={14} weight="fill" />, label: 'Patch' },
  multi_edit: { icon: <FileText size={14} weight="fill" />, label: 'Multi-Edit' },
  bash_exec: { icon: <Terminal size={14} weight="fill" />, label: 'Bash' },
  shell_open: { icon: <Terminal size={14} weight="fill" />, label: 'Shell Open' },
  shell_exec: { icon: <Terminal size={14} weight="fill" />, label: 'Shell' },
  shell_close: { icon: <Terminal size={14} weight="fill" />, label: 'Shell Close' },
  get_project_info: { icon: <Package size={14} weight="fill" />, label: 'Project Info' },
  todo_read: { icon: <ListChecks size={14} weight="fill" />, label: 'Todo Read' },
  todo_write: { icon: <ListChecks size={14} weight="fill" />, label: 'Todo Write' },
  web_fetch: { icon: <Globe size={14} weight="fill" />, label: 'Web Fetch' },
};

// Item Card
function ItemCard({ item, onClick, onPurchase, theme }: {
  item: MarketplaceItem;
  onClick: () => void;
  onPurchase: () => void;
  theme: string;
}) {
  return (
    <div
      onClick={onClick}
      className={`relative group rounded-2xl border transition-all cursor-pointer ${
        item.is_active
          ? theme === 'light'
            ? 'bg-white border-black/10 hover:border-[var(--primary)] hover:shadow-xl'
            : 'bg-white/[0.02] border-white/10 hover:border-[var(--primary)] hover:shadow-xl'
          : 'opacity-60 border-white/5'
      }`}
    >
      {/* Badge */}
      <div className="absolute top-3 right-3 z-10">
        {item.source_type === 'open' ? (
          <span className="px-2.5 py-1 bg-green-500/20 text-green-400 text-xs rounded-md font-medium backdrop-blur">
            Open Source
          </span>
        ) : (
          <span className="px-2.5 py-1 bg-purple-500/20 text-purple-400 text-xs rounded-md font-medium backdrop-blur">
            Closed Source
          </span>
        )}
      </div>

      {/* Image - Full Bleed */}
      <div className="w-full h-28 bg-gradient-to-br from-orange-500/20 to-purple-500/20 rounded-t-2xl flex items-center justify-center p-6">
        {item.avatar_url ? (
          <img src={item.avatar_url} alt={item.name} className="w-full h-full object-cover rounded-lg" />
        ) : (
          <img src="/favicon.svg" alt="Tesslate" className="w-full h-full" />
        )}
      </div>

      {/* Content */}
      <div className="p-3">
        {/* Name */}
        <h3 className="font-heading font-bold text-[var(--text)] mb-1 text-sm group-hover:text-[var(--primary)] transition-colors">
          {item.name}
        </h3>

        {/* Description */}
        <p className={`text-xs mb-2 line-clamp-2 min-h-[32px] ${theme === 'light' ? 'text-black/70' : 'text-white/70'}`}>
          {item.description}
        </p>

        {/* Usage Count */}
        <div className={`flex items-center gap-1.5 mb-2 text-xs ${theme === 'light' ? 'text-black/60' : 'text-white/60'}`}>
          <Lightning size={12} weight="fill" className="text-orange-400" />
          <span className="font-medium">{item.usage_count || 0} uses</span>
        </div>

        {/* Tags */}
        <div className="flex flex-wrap gap-1 mb-2">
          {item.tags?.slice(0, 2).map((tag, idx) => (
            <span
              key={idx}
              className={`px-1.5 py-0.5 rounded text-[10px] ${theme === 'light' ? 'bg-black/10 text-black/60' : 'bg-white/10 text-white/60'}`}
            >
              {tag}
            </span>
          ))}
        </div>

        {/* Actions */}
        <div className={`flex items-center justify-between pt-2 border-t ${theme === 'light' ? 'border-black/10' : 'border-white/10'}`}>
          <div className="text-xs font-semibold text-[var(--text)]">
            {item.pricing_type === 'free' ? 'Free' : `$${item.price}/mo`}
          </div>
          {item.is_purchased ? (
            <button
              disabled
              onClick={(e) => e.stopPropagation()}
              className="px-2 py-1 bg-green-500/20 text-green-400 rounded text-[10px] flex items-center gap-1 font-medium"
            >
              <Check size={12} weight="bold" />
              Installed
            </button>
          ) : (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onPurchase();
              }}
              disabled={!item.is_active}
              className={`px-2.5 py-1 rounded text-[10px] font-semibold transition-all ${
                item.is_active
                  ? 'bg-[var(--primary)] hover:bg-orange-600 text-white shadow-lg hover:shadow-xl'
                  : theme === 'light' ? 'bg-black/5 text-black/40' : 'bg-white/5 text-white/40'
              }`}
            >
              {item.is_active ? 'Install' : 'Soon'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// Detail Modal
function ItemDetailModal({ item, onClose, onPurchase, theme }: {
  item: MarketplaceItem;
  onClose: () => void;
  onPurchase: () => void;
  theme: string;
}) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" onClick={onClose}>
      <div className={`rounded-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden shadow-2xl border ${theme === 'light' ? 'bg-white border-black/10' : 'bg-[var(--surface)] border-white/10'}`} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="bg-gradient-to-r from-orange-500/20 to-purple-500/20 p-8 border-b border-white/10">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4">
              <div className="w-16 h-16 flex items-center justify-center">
                {item.avatar_url ? (
                  <img src={item.avatar_url} alt={item.name} className="w-full h-full object-cover rounded-lg" />
                ) : (
                  <img src="/favicon.svg" alt="Tesslate" className="w-full h-full" />
                )}
              </div>
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <h2 className="font-heading text-3xl font-bold text-[var(--text)]">{item.name}</h2>
                  {item.source_type === 'open' && (
                    <span className="flex items-center gap-1.5 px-3 py-1 bg-green-500/20 text-green-400 text-sm rounded-lg font-medium">
                      <LockSimpleOpen size={14} />
                      Open Source
                    </span>
                  )}
                </div>
                <p className={`mb-3 ${theme === 'light' ? 'text-black/80' : 'text-white/80'}`}>{item.description}</p>
                <div className={`flex items-center gap-4 text-sm flex-wrap ${theme === 'light' ? 'text-black/60' : 'text-white/60'}`}>
                  <span className="flex items-center gap-1.5">
                    <Lightning size={14} weight="fill" className="text-orange-400" />
                    <span className="font-medium">{item.usage_count || 0} uses</span>
                  </span>
                </div>
              </div>
            </div>
            <button
              onClick={onClose}
              className={`p-2 rounded-lg transition-colors ${theme === 'light' ? 'hover:bg-black/5 text-black/60' : 'hover:bg-white/10 text-white/60'}`}
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="p-8 overflow-y-auto max-h-[60vh]">
          {item.long_description && (
            <div className="mb-8">
              <h3 className="font-heading font-semibold text-[var(--text)] mb-3 text-xl">About this Agent</h3>
              <p className={theme === 'light' ? 'text-black/80' : 'text-white/80'}>{item.long_description}</p>
            </div>
          )}

          {item.features && item.features.length > 0 && (
            <div className="mb-8">
              <h3 className="font-heading font-semibold text-[var(--text)] mb-4 text-xl">Features</h3>
              <div className="grid grid-cols-2 gap-3">
                {item.features.map((feature, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <Check size={16} className="text-green-500" weight="bold" />
                    <span className={`text-sm ${theme === 'light' ? 'text-black/80' : 'text-white/80'}`}>{feature}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tools Section - Only for agents */}
          {item.item_type === 'agent' && (
            <div className="mb-8">
              <h3 className="font-heading font-semibold text-[var(--text)] mb-4 text-xl">Available Tools</h3>
              <div className="flex flex-wrap gap-2">
                {(item.tools && item.tools.length > 0 ? item.tools : ALL_TOOLS).map((toolName, idx) => {
                  const tool = toolIcons[toolName];
                  if (!tool) return null;
                  return (
                    <div
                      key={idx}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${
                        theme === 'light'
                          ? 'bg-orange-50 border border-orange-200 text-orange-700'
                          : 'bg-orange-500/10 border border-orange-500/20 text-orange-400'
                      }`}
                    >
                      {tool.icon}
                      <span>{tool.label}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className={`p-8 border-t flex items-center justify-between ${theme === 'light' ? 'border-black/10' : 'border-white/10'}`}>
          <div>
            <div className={`text-sm mb-1 ${theme === 'light' ? 'text-black/60' : 'text-white/60'}`}>
              {item.pricing_type === 'free' ? 'Free Agent' : 'Subscription'}
            </div>
            {item.pricing_type !== 'free' && (
              <div className="font-heading text-2xl font-bold text-[var(--text)]">
                ${item.price}<span className="text-sm font-normal text-[var(--text)]/60">/month</span>
              </div>
            )}
          </div>
          {item.is_purchased ? (
            <button
              disabled
              className="px-8 py-3 bg-green-500/20 text-green-400 rounded-xl font-semibold flex items-center gap-2"
            >
              <Check size={20} weight="bold" />
              Already in Library
            </button>
          ) : (
            <button
              onClick={onPurchase}
              disabled={!item.is_active}
              className={`px-8 py-3 rounded-xl font-semibold transition-all flex items-center gap-2 ${
                item.is_active
                  ? 'bg-[var(--primary)] hover:bg-orange-600 text-white shadow-lg hover:shadow-xl'
                  : theme === 'light' ? 'bg-black/5 text-black/40' : 'bg-white/5 text-white/40'
              }`}
            >
              <ShoppingCart size={20} />
              {item.is_active
                ? (item.pricing_type === 'free' ? 'Add to Library' : `Subscribe for $${item.price}/mo`)
                : 'Coming Soon'
              }
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
